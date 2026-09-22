"""Undo journal / rollback tests (V2 §13/§21)."""
from pathlib import Path

import pytest

from agent.undo import UndoJournal, snapshot_backup


@pytest.fixture()
def journal(tmp_path):
    return UndoJournal(tmp_path / "journal.json")


def test_create_rollback_moves_to_trash(journal, tmp_path):
    target = tmp_path / "made-by-nova.txt"
    target.write_text("hi")
    journal.record("task-1", "create", target)
    out = journal.undo_last("task-1")
    assert len(out.undone) == 1
    assert not target.exists()  # gone from its original location


def test_modify_rollback_restores_content(journal, tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("original")
    backup = snapshot_backup(str(f))
    f.write_text("overwritten")
    journal.record("task-2", "modify", f, backup=backup)
    out = journal.undo_last("task-2")
    assert len(out.undone) == 1
    assert f.read_text() == "original"
    assert not Path(backup).exists()  # backup cleaned up after restore


def test_move_rollback_returns_item(journal, tmp_path):
    src = tmp_path / "a.txt"
    dst = tmp_path / "sub" / "b.txt"
    src.write_text("payload")
    dst.parent.mkdir()
    src.rename(dst)
    journal.record("task-3", "move", dst, **{"from": str(src)})
    out = journal.undo_last("task-3")
    assert len(out.undone) == 1
    assert src.exists() and not dst.exists()


def test_delete_rollback_is_honest(journal, tmp_path):
    journal.record("task-4", "delete", "/tmp/already-gone.txt")
    out = journal.undo_last("task-4")
    assert out.undone == []
    assert len(out.skipped) == 1
    assert "trash" in out.skipped[0]["note"]  # actionable, not fake success


def test_undo_last_targets_most_recent_task(journal, tmp_path):
    f1 = tmp_path / "one.txt"
    f2 = tmp_path / "two.txt"
    f1.write_text("1")
    f2.write_text("2")
    journal.record("task-a", "create", f1)
    journal.record("task-b", "create", f2)
    out = journal.undo_last()  # no task id -> newest task wins
    assert len(out.undone) == 1
    assert not f2.exists() and f1.exists()


def test_undo_nothing(journal):
    out = journal.undo_last()
    assert out.undone == [] and out.skipped == []
    assert "Nothing to undo" in out.summary


def test_entries_for_task_and_persistence(tmp_path):
    p = tmp_path / "j.json"
    j1 = UndoJournal(p)
    j1.record("t9", "create", "/tmp/x")
    j2 = UndoJournal(p)  # reload from disk
    assert [e["task_id"] for e in j2.entries_for("t9")] == ["t9"]


def test_journal_bounded(tmp_path):
    j = UndoJournal(tmp_path / "big.json")
    for i in range(600):
        j.record("t", "create", f"/tmp/f{i}")
    assert len(j.describe_recent(limit=1000)) <= 500
