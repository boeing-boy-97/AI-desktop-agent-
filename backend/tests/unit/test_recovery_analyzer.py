"""Recovery classification + error analyzer tests (V2 §12/§23)."""
from agent.error_analyzer import analyze, to_report
from agent.recovery import classify_failure


def test_classify_app_not_found():
    f = classify_failure("computer.launch_app", "Application 'foo' was not found")
    assert f.kind == "app_not_found"
    assert f.retryable
    assert "catalog" in f.strategy


def test_classify_path_missing():
    f = classify_failure("filesystem.move", "Source not found: /x/y")
    assert f.kind == "path_missing"


def test_classify_permission_denied_not_retried():
    f = classify_failure("shell.run", "Access is denied")
    assert f.kind == "permission_denied"
    assert f.retryable is False


def test_classify_network():
    f = classify_failure("downloads.download_url", "connection timed out")
    assert f.kind == "network"


def test_classify_build_error():
    f = classify_failure("shell.run", "npm ERR! Cannot find module 'react'")
    assert f.kind == "build_error"


def test_classify_exit_code():
    f = classify_failure("shell.run", "failed", {"returncode": 2})
    assert f.kind == "exit_code"
    assert f.evidence["returncode"] == "2"


def test_classify_unknown_fallback():
    f = classify_failure("x.y", "")
    assert f.kind == "unknown"


def test_analyze_typescript_error():
    errs = analyze("module.ts(12,5): error TS2304: Cannot find name 'foo'")
    assert errs and errs[0].kind == "compiler"
    assert errs[0].file == "module.ts" and errs[0].line == 12
    assert errs[0].code == "TS2304"
    assert errs[0].confidence > 0.8


def test_analyze_python_traceback():
    errs = analyze('  File "app.py", line 42\nValueError: bad')
    assert any(e.kind == "runtime" and e.file == "app.py" and e.line == 42
               for e in errs)


def test_analyze_npm_error_and_fix_suggestion():
    errs = analyze("npm ERR! Cannot find module 'lodash'")
    assert errs and errs[0].kind == "package_manager"
    assert "install" in errs[0].proposed_fix.lower()


def test_analyze_missing_module_suggests_install():
    errs = analyze("src/a.js:3: Cannot find module 'express'")
    assert errs and "install" in errs[0].proposed_fix.lower()


def test_analyze_empty_output():
    assert analyze("") == []


def test_to_report_shape():
    rep = to_report("a.py:1:2: error: nope")
    assert rep["error_count"] == 1
    assert rep["primary"]["file"] == "a.py"


def test_analyze_bounded():
    out = "\n".join(f"f{i}.py({i},1): error E{i}: x" for i in range(50))
    assert len(analyze(out, max_errors=5)) == 5
