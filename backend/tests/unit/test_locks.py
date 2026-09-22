"""Resource lock tests (V2 §30)."""
from core.locks import ResourceLocks


def test_path_lock_exclusive_between_tasks():
    locks = ResourceLocks()
    ok, owner = locks.acquire_path("/tmp/x.txt", "task-a")
    assert ok and owner == ""
    ok, owner = locks.acquire_path("/tmp/x.txt", "task-b")
    assert not ok and owner == "task-a"


def test_same_task_reentrant():
    locks = ResourceLocks()
    assert locks.acquire_path("/tmp/y.txt", "task-a")[0]
    assert locks.acquire_path("/tmp/y.txt", "task-a")[0]


def test_release_allows_next_task():
    locks = ResourceLocks()
    locks.acquire_path("/tmp/z.txt", "task-a")
    locks.release_path("/tmp/z.txt", "task-a")
    ok, _ = locks.acquire_path("/tmp/z.txt", "task-b")
    assert ok


def test_release_wrong_owner_noop():
    locks = ResourceLocks()
    locks.acquire_path("/tmp/w.txt", "task-a")
    locks.release_path("/tmp/w.txt", "task-b")
    ok, owner = locks.acquire_path("/tmp/w.txt", "task-b")
    assert not ok and owner == "task-a"


def test_release_task_clears_all_its_locks():
    locks = ResourceLocks()
    locks.acquire_path("/tmp/1.txt", "task-a")
    locks.acquire_path("/tmp/2.txt", "task-a")
    locks.release_task("task-a")
    assert locks.acquire_path("/tmp/1.txt", "task-b")[0]
    assert locks.acquire_path("/tmp/2.txt", "task-b")[0]


def test_input_and_screen_locks_exist():
    import asyncio
    locks = ResourceLocks()
    assert isinstance(locks.input_lock(), asyncio.Lock)
    assert locks.input_lock() is locks.input_lock()  # stable instance
    assert locks.screen_lock() is not locks.input_lock()


def test_path_normalisation():
    locks = ResourceLocks()
    locks.acquire_path("./sub/../file.txt", "task-a")
    ok, owner = locks.acquire_path("file.txt", "task-b")
    assert not ok and owner == "task-a"
