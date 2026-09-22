"""Session context + coreference tests (V2 §16/§17)."""
import time

from agent.session import SessionContext


def test_set_get_roundtrip():
    s = SessionContext()
    s.set("current_app", "VS Code")
    assert s.get("current_app") == "VS Code"


def test_ttl_expiry():
    s = SessionContext(ttl_seconds=0.01)
    s.set("current_app", "Notepad")
    time.sleep(0.03)
    assert s.get("current_app") is None
    assert s.snapshot() == {}


def test_per_entry_ttl_override():
    s = SessionContext(ttl_seconds=0.01)
    s.set("sticky", "value", ttl=60)
    time.sleep(0.03)
    assert s.get("sticky") == "value"


def test_pronoun_coreference():
    s = SessionContext()
    s.set("selected_contact", "Rahul")
    s.set("selected_artifact", "/downloads/photo.jpg")
    resolved = s.resolve_coreference("Download it to Desktop")
    assert resolved.get("it") == "/downloads/photo.jpg"
    resolved = s.resolve_coreference("What did he send?")
    assert resolved.get("he") == "Rahul"


def test_apply_coreference_rewrites_text():
    s = SessionContext()
    s.set("selected_artifact", "report.pdf")
    out = s.apply_coreference("Move it to Documents")
    assert "report.pdf" in out and " it " not in out.lower()


def test_artifact_stack():
    s = SessionContext()
    s.add_artifact("photo", "img1.png")
    s.add_artifact("file", "doc.pdf")
    assert s.get("selected_artifact") == "doc.pdf"
    resolved = s.resolve_coreference("open it")
    assert resolved["it"] == "doc.pdf"


def test_no_coreference_without_context():
    s = SessionContext()
    assert s.resolve_coreference("Download it to Desktop") == {}
    assert s.apply_coreference("Download it") == "Download it"


def test_describe_shape():
    s = SessionContext()
    s.set("current_app", "Chrome")
    d = s.describe()
    assert d["count"] == 1 and "current_app" in d["entries"]
