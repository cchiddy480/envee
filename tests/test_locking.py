"""Locks constrain setup; progress records never authorize skipped verification."""

import json
from pathlib import Path
import sys
import tomllib

from click.testing import CliRunner
import pytest

from envee_bootstrap import project_runner as runner
from envee_bootstrap.cli import main, write_files
from envee_bootstrap.model import Options
from envee_bootstrap.templates import render


def project(path, preset="python"):
    files = render(Options(name="locked", preset=preset, git=False))
    write_files(path, files)
    return runner.load(path)


def python_lock(path):
    (path / "requirements.lock").write_text(
        "# envee-input-sha256: " + runner.dependency_fingerprint(path) + "\n# fixture lock\n")


def test_python_declarations_have_one_source_and_required_hashes(tmp_path):
    manifest = project(tmp_path, "flask")
    assert manifest["schema"] == 2
    data = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    assert data["project"]["dependencies"] == ["Flask==3.1.3"]
    assert "pytest==9.1.1" in data["project"]["optional-dependencies"]["dev"]
    assert (tmp_path / "requirements.txt").read_text() == "--require-hashes\n-r requirements.lock\n"


def test_python_lock_staleness_and_cosmetic_changes(tmp_path):
    manifest = project(tmp_path)
    assert "Missing" in runner.locking_problems(tmp_path, manifest)[0]
    python_lock(tmp_path)
    assert not runner.locking_problems(tmp_path, manifest)
    path = tmp_path / "pyproject.toml"
    path.write_text(path.read_text() + "\n# user formatting\n")
    assert not runner.locking_problems(tmp_path, manifest)
    path.write_text(path.read_text().replace('dependencies = []', 'dependencies = ["click==8.4.2"]'))
    assert "Run envee lock" in runner.locking_problems(tmp_path, manifest)[0]


def test_setup_reuses_locks_but_repeats_checks(tmp_path, monkeypatch):
    manifest = project(tmp_path)
    python_lock(tmp_path)
    original = (tmp_path / "requirements.lock").read_bytes()
    monkeypatch.setattr(runner, "preflight", lambda *a: None)
    monkeypatch.setattr(runner, "python_lock", lambda *a: pytest.fail("unexpected resolution"))
    calls = []
    monkeypatch.setattr(runner, "run", lambda args, *a, **kw: calls.append(args))
    monkeypatch.setattr(runner, "python", lambda *a: sys.executable)
    monkeypatch.setattr(runner, "smoke", lambda *a: calls.append(["live startup"]))
    for _ in range(2):
        runner.setup(tmp_path, manifest, True)
    assert (tmp_path / "requirements.lock").read_bytes() == original
    assert sum("live startup" in args for args in calls) == 2
    assert sum("--require-hashes" in args for args in calls) == 2
    assert sum("--no-deps" in args for args in calls) == 2
    assert not runner.previous_setup(tmp_path)


def test_lock_failure_preserves_old_lock_and_cleans_tool_environment(tmp_path, monkeypatch):
    project(tmp_path)
    python_lock(tmp_path)
    original = (tmp_path / "requirements.lock").read_bytes()
    tools = []
    monkeypatch.setattr(runner, "python", lambda *a: sys.executable)
    def run(args, *unused, **kwargs):
        if "venv" in args:
            tools.append(Path(args[-1]).parent)
        if "compile" in args:
            assert "--universal" in args and "--generate-hashes" in args
            assert "--no-python-downloads" in args
            output = Path(args[args.index("--output-file") + 1])
            assert output.read_bytes() == original
            output.write_text("partial invalid output")
            raise RuntimeError("resolver failed")
    monkeypatch.setattr(runner, "run", run)
    with pytest.raises(RuntimeError, match="resolver failed"):
        runner.python_lock(tmp_path)
    assert (tmp_path / "requirements.lock").read_bytes() == original
    assert tools and not tools[0].exists()


def test_missing_and_changed_node_locks(tmp_path):
    manifest = project(tmp_path, "typescript")
    assert runner.locking_problems(tmp_path, manifest)
    data = json.loads((tmp_path / "package.json").read_text())
    lock = {"lockfileVersion": 3, "packages": {"": {key: data[key] for key in
            ("dependencies", "devDependencies")}}}
    (tmp_path / "package-lock.json").write_text(json.dumps(lock))
    assert not runner.locking_problems(tmp_path, manifest)
    data["devDependencies"]["another-package"] = "1.0.0"
    (tmp_path / "package.json").write_text(json.dumps(data))
    assert "envee lock" in runner.locking_problems(tmp_path, manifest)[0]


def test_node_refresh_is_staged_and_never_runs_scripts(tmp_path, monkeypatch):
    project(tmp_path, "typescript")
    lock = tmp_path / "package-lock.json"
    lock.write_text('{"before":true}')
    original = lock.read_bytes()
    monkeypatch.setattr(runner, "executable", lambda x: x)
    def run(args, cwd, **kw):
        assert "--ignore-scripts" in args and "--package-lock-only" in args
        assert cwd != tmp_path
        (cwd / "package-lock.json").write_text('{"partial":true}')
        raise RuntimeError("offline")
    monkeypatch.setattr(runner, "run", run)
    with pytest.raises(RuntimeError, match="offline"):
        runner.node_lock(tmp_path, True)
    assert lock.read_bytes() == original


def test_old_manifest_uses_existing_pip_workflow(tmp_path, monkeypatch):
    manifest = project(tmp_path)
    manifest["schema"] = 1
    monkeypatch.setattr(runner, "preflight", lambda *a: None)
    monkeypatch.setattr(runner, "lock", lambda *a, **kw: pytest.fail("old project migrated"))
    monkeypatch.setattr(runner, "python", lambda *a: sys.executable)
    monkeypatch.setattr(runner, "smoke", lambda *a: None)
    calls = []
    monkeypatch.setattr(runner, "run", lambda args, *a, **kw: calls.append(args))
    runner.setup(tmp_path, manifest, True)
    assert any("requirements.txt" in args for args in calls)
    assert not any("--require-hashes" in args or "--no-deps" in args for args in calls)
    assert not runner.locking_problems(tmp_path, manifest)
    assert not (tmp_path / "requirements.lock").exists()


def test_check_only_and_doctor_are_read_only(tmp_path, monkeypatch):
    manifest = project(tmp_path)
    monkeypatch.setattr(runner, "prerequisite_problems", lambda *a: [])
    monkeypatch.setattr(runner, "python_lock", lambda *a: pytest.fail("download"))
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    result = CliRunner().invoke(main, ["lock", str(tmp_path), "--check"])
    assert result.exit_code == 1 and "Missing" in result.output
    result = CliRunner().invoke(main, ["doctor", str(tmp_path)])
    assert result.exit_code == 1 and "Missing" in result.output
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before
    python_lock(tmp_path)
    result = CliRunner().invoke(main, ["lock", str(tmp_path), "--check"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".envee").exists()
    assert not runner.locking_problems(tmp_path, manifest)


@pytest.mark.parametrize("error", [RuntimeError("SECRET credential"), KeyboardInterrupt()])
def test_progress_failure_has_remaining_steps_without_error_payload(tmp_path, monkeypatch, error):
    manifest = project(tmp_path)
    monkeypatch.setattr(runner, "preflight", lambda *a: (_ for _ in ()).throw(error))
    with pytest.raises(type(error)):
        runner.setup(tmp_path, manifest, True)
    path = tmp_path / ".envee/setup-state.json"
    assert "SECRET" not in path.read_text()
    record = json.loads(path.read_text())
    assert record["stages"][0]["status"] in {"failed", "interrupted"}
    assert record["stages"][-1]["status"] == "pending"
    assert runner.previous_setup(tmp_path)


def test_unreadable_progress_is_advisory_and_doctor_does_not_rewrite(tmp_path, monkeypatch):
    project(tmp_path)
    python_lock(tmp_path)
    (tmp_path / ".envee").mkdir()
    path = tmp_path / ".envee/setup-state.json"
    path.write_text("broken")
    monkeypatch.setattr(runner, "prerequisite_problems", lambda *a: [])
    result = CliRunner().invoke(main, ["doctor", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "unreadable" in result.output and path.read_text() == "broken"


def test_docker_consumes_same_locks_and_ci_checks_before_install():
    files = render(Options(name="locked", preset="flask", environment="docker", ci=True))
    assert "COPY requirements.txt requirements.lock" in files["Dockerfile"]
    assert "--require-hashes" in files["Dockerfile"] and "--no-deps -e" in files["Dockerfile"]
    ci = files[".github/workflows/check.yml"]
    assert ci.index("lock --check") < ci.index("setup --local")


@pytest.mark.parametrize("value", [[], {"packages": []}, {"packages": {"": []}}])
def test_malformed_node_lock_has_a_diagnostic(tmp_path, value):
    manifest = project(tmp_path, "typescript")
    (tmp_path / "package-lock.json").write_text(json.dumps(value))
    assert runner.locking_problems(tmp_path, manifest)
    result = CliRunner().invoke(main, ["lock", str(tmp_path), "--check"])
    assert result.exit_code == 1 and "Traceback" not in result.output


def test_python_edit_during_resolution_preserves_old_lock(tmp_path, monkeypatch):
    project(tmp_path)
    python_lock(tmp_path)
    before = (tmp_path / "requirements.lock").read_bytes()
    monkeypatch.setattr(runner, "python", lambda *a: sys.executable)
    def run(args, *unused, **kw):
        if "compile" in args:
            path = tmp_path / "pyproject.toml"
            path.write_text(path.read_text().replace('dependencies = []', 'dependencies = ["click"]'))
    monkeypatch.setattr(runner, "run", run)
    with pytest.raises(RuntimeError, match="changed while"):
        runner.python_lock(tmp_path)
    assert (tmp_path / "requirements.lock").read_bytes() == before


def test_read_only_flag_cannot_accidentally_run_setup(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["project.py", "setup", "--check"])
    monkeypatch.setattr(runner, "setup", lambda *a: pytest.fail("installation"))
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2
