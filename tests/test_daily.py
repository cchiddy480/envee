"""Daily CLI contracts: preferences, discovery, recovery and owned processes."""

import os
import re
import socket
import subprocess
import sys
from types import SimpleNamespace

from click.testing import CliRunner
import pytest

from envee_bootstrap import agent_tools, preferences, project_runner as runner
from envee_bootstrap.cli import main, write_files
from envee_bootstrap.model import Options
from envee_bootstrap.templates import render


def project(path, **options):
    write_files(path, render(Options(name="example", preset="python", git=False, **options)))
    manifest = runner.load(path)
    for component in manifest["components"]:
        if component["kind"] in runner.PYTHON_KINDS:
            cwd = path / component["path"]
            (cwd / "requirements.lock").write_text("# envee-input-sha256: " + runner.dependency_fingerprint(cwd) + "\n")
    return manifest


def test_discovery_legacy_invalid_and_git_boundaries(tmp_path):
    project(tmp_path / "outer")
    root = tmp_path / "outer"
    child = root / "nested/deep"
    child.mkdir(parents=True)
    assert runner.discover(child) == root.resolve()
    (root / "envee.json").rename(root / "forge.json")
    assert runner.discover(child) == root.resolve()
    (child.parent / ".git").write_text("gitdir: elsewhere")
    assert runner.discover(child) is None
    (child / "envee.json").write_text("broken")
    with pytest.raises(RuntimeError, match="invalid"):
        runner.discover(child)


def test_home_empty_and_unrelated_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, [], input="5\n1\nn\nn\n3\n")
    assert result.exit_code == 0, result.output
    assert "What are we building?" in result.output
    assert not (tmp_path / "envee.json").exists()
    (tmp_path / "existing.txt").write_text("preserve")
    result = CliRunner().invoke(main, [], input="1\nchild\n5\n1\nn\nn\n3\n")
    assert result.exit_code == 0, result.output
    assert re.search(r"Project\s+child", result.output)
    assert (tmp_path / "existing.txt").read_text() == "preserve"
    assert not (tmp_path / "child").exists()


@pytest.mark.parametrize("action", ["dev", "check", "setup"])
def test_daily_commands_from_subdirectories(tmp_path, monkeypatch, action):
    project(tmp_path / "project")
    child = tmp_path / "project/app"
    calls = []
    monkeypatch.setattr(runner, action, lambda root, *args: calls.append(root))
    monkeypatch.setattr(agent_tools, "setup", lambda *args: [])
    result = CliRunner().invoke(main, [action, str(child)])
    assert result.exit_code == 0, result.output
    assert calls == [(tmp_path / "project").resolve()]


def test_home_shows_saved_project_and_calls_action(tmp_path, monkeypatch):
    project(tmp_path / "project", environment="docker")
    monkeypatch.chdir(tmp_path / "project/app")
    calls = []
    monkeypatch.setattr(runner, "dev", lambda *args: calls.append(args))
    result = CliRunner().invoke(main, [], input="1\n")
    assert result.exit_code == 0, result.output
    assert "example" in result.output and "docker" in result.output
    assert calls[0][2] is False


def test_first_use_saved_preferences_and_override(tmp_path):
    first = tmp_path / "first"
    result = CliRunner().invoke(main, ["init", str(first), "--preset", "python", "--no-git", "--no-install"],
                                input="y\nn\n1\n")
    assert result.exit_code == 0, result.output
    assert "local code index" in result.output and "bundled coding guidelines" in result.output
    assert preferences.load() == {"codegraph": True, "ponytail": False}
    second = tmp_path / "second"
    result = CliRunner().invoke(main, ["init", str(second), "--yes", "--no-install", "--no-git",
                                      "--no-codegraph", "--ponytail"])
    assert result.exit_code == 0, result.output
    manifest = runner.load(second)
    assert manifest["ponytail"] and not manifest["codegraph"]
    assert preferences.load() == {"codegraph": True, "ponytail": False}
    result = CliRunner().invoke(main, ["init", str(tmp_path / "third"), "--preset", "python",
                                      "--no-install", "--no-git"], input="3\n")
    assert result.exit_code == 0, result.output
    assert "Add CodeGraph?" not in result.output


@pytest.mark.parametrize("args", [["--help"], ["doctor"], ["init", "preview", "--yes", "--dry-run"],
                                  ["init", "source", "--yes", "--no-install", "--no-git"]])
def test_no_preference_side_effects(tmp_path, monkeypatch, args):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agent_tools, "codegraph_command", lambda: pytest.fail("download"))
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    assert not preferences.path().exists()
    if "source" in args:
        assert not runner.load(tmp_path / "source")["codegraph"]
        assert not runner.load(tmp_path / "source")["ponytail"]


def test_interactive_preview_and_cancel_do_not_save(tmp_path):
    for suffix, args, answers in [("preview", ["--dry-run"], "y\ny\n"),
                                   ("cancel", [], "y\ny\n3\n")]:
        target = tmp_path / suffix
        result = CliRunner().invoke(main, ["init", str(target), "--preset", "python", *args], input=answers)
        assert result.exit_code == 0, result.output
        assert not target.exists() and not preferences.path().exists()


def test_customisation_preserves_answers(tmp_path):
    preferences.save({"codegraph": False, "ponytail": False})
    result = CliRunner().invoke(main, ["init", str(tmp_path / "chosen"), "--preset", "fastapi",
                                      "--no-install", "--no-git", "--ci", "--database", "sqlite"],
                                input="2\n\n\n\n\n\n\n\n\n\n\n\n1\n")
    assert result.exit_code == 0, result.output
    manifest = runner.load(tmp_path / "chosen")
    assert manifest["name"] == "chosen" and manifest["preset"] == "fastapi"
    assert manifest["ci"] and not manifest["git"] and manifest["database"] == "sqlite"


def test_config_flags_preserve_other_choices_and_validate(tmp_path):
    result = CliRunner().invoke(main, ["config", "--codegraph", "--no-ponytail"])
    assert result.exit_code == 0, result.output
    result = CliRunner().invoke(main, ["config", "--no-codegraph"])
    assert result.exit_code == 0, result.output
    assert preferences.load() == {"codegraph": False, "ponytail": False}
    preferences.path().write_text('{"codegraph": "false"}')
    with pytest.raises(ValueError, match="Invalid preferences"):
        preferences.load()


def test_doctor_collects_all_runtime_problems(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.shutil, "which", lambda _: None)
    monkeypatch.setattr(runner, "select_node", lambda: (_ for _ in ()).throw(RuntimeError("Node 22 missing")))
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["doctor", "--preset", "fullstack-azure"])
    assert result.exit_code == 1
    assert all(word in result.output for word in ["Node 22", "npm", "func", "Core Tools", "retry"])
    assert not preferences.path().exists()


@pytest.mark.parametrize("required_failure,expected", [(False, 3), (True, 1)])
def test_optional_failure_has_distinct_status(tmp_path, monkeypatch, required_failure, expected):
    monkeypatch.setattr(runner, "preflight", lambda *a: None)
    def setup(*args):
        if required_failure:
            raise RuntimeError("application failed")
    monkeypatch.setattr(runner, "setup", setup)
    monkeypatch.setattr(agent_tools, "setup", lambda *a: ["CodeGraph: download failed"])
    result = CliRunner().invoke(main, ["init", str(tmp_path / "project"), "--yes", "--no-git", "--codegraph"])
    assert result.exit_code == expected, result.output
    if required_failure:
        assert "ready" not in result.output.lower().split("project files created")[-1]
    else:
        assert "Application ready—with warnings" in result.output
        assert "CodeGraph" in result.output and "envee setup" in result.output


def test_optional_tools_fail_independently(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_tools, "global_ignore", lambda: (_ for _ in ()).throw(OSError("denied")))
    monkeypatch.setattr(agent_tools, "codegraph_command", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    warnings = agent_tools.setup(tmp_path, {"codegraph": True, "ponytail": True})
    assert len(warnings) == 2
    assert "Ponytail" in warnings[0] and "offline" in warnings[1]


def test_dev_occupied_port_does_not_spawn(tmp_path, monkeypatch):
    manifest = project(tmp_path / "project")
    monkeypatch.setattr(runner, "preflight", lambda *a: None)
    monkeypatch.setattr(runner, "start", lambda *a: pytest.fail("spawn"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        monkeypatch.setattr(runner, "endpoints", lambda _: [(f"http://127.0.0.1:{sock.getsockname()[1]}/", False)])
        with pytest.raises(RuntimeError, match="in use"):
            runner.dev(tmp_path / "project", manifest, True)


@pytest.mark.parametrize("interrupt", [False, True])
def test_dev_stops_process_after_readiness_or_interruption(tmp_path, monkeypatch, capsys, interrupt):
    manifest = project(tmp_path / "project")
    processes = []
    monkeypatch.setattr(runner, "preflight", lambda *a: None)
    monkeypatch.setattr(runner, "available_ports", lambda *a: None)
    monkeypatch.setattr(runner, "endpoints", lambda _: [("http://127.0.0.1:8000/api/health", True)])
    def start(*args):
        processes.append(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                         start_new_session=os.name != "nt"))
        return processes
    monkeypatch.setattr(runner, "start", start)
    monkeypatch.setattr(runner, "probe", lambda *a: None)
    original_sleep = runner.time.sleep
    interrupted = False
    def sleep(_):
        nonlocal interrupted
        if interrupt and not interrupted:
            interrupted = True
            raise KeyboardInterrupt
        if interrupt:
            original_sleep(0.01)
        else:
            processes[0].terminate()
            processes[0].wait(timeout=10)
    monkeypatch.setattr(runner, "time", SimpleNamespace(sleep=sleep, monotonic=runner.time.monotonic))
    with pytest.raises(KeyboardInterrupt if interrupt else RuntimeError):
        runner.dev(tmp_path / "project", manifest, True)
    assert processes[0].poll() is not None
    assert "Ready: http://127.0.0.1:8000/api/health" in capsys.readouterr().out


def test_devcontainer_host_guidance_without_start(tmp_path, monkeypatch, capsys):
    manifest = project(tmp_path / "project", environment="devcontainer")
    monkeypatch.setattr(runner, "preflight", lambda *a: pytest.fail("host execution"))
    runner.dev(tmp_path / "project", manifest, False)
    assert "Reopen in Container" in capsys.readouterr().out


def test_dev_one_shot_runs_once(tmp_path, monkeypatch):
    manifest = project(tmp_path / "project")
    monkeypatch.setattr(runner, "preflight", lambda *a: None)
    monkeypatch.setattr(runner, "dev_command", lambda *a: [sys.executable, "-c", "print('once')"])
    runner.dev(tmp_path / "project", manifest, True)


def test_real_http_readiness_and_shutdown(tmp_path, monkeypatch, capsys):
    manifest = project(tmp_path / "project")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}/api/health"
    script = f'''from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{{"status":"ok"}}')
HTTPServer(("127.0.0.1", {port}), Handler).serve_forever()
'''
    monkeypatch.setattr(runner, "preflight", lambda *a: None)
    monkeypatch.setattr(runner, "endpoints", lambda _: [(url, True)])
    monkeypatch.setattr(runner, "dev_command", lambda *a: [sys.executable, "-c", script])
    original_start, original_sleep = runner.start, runner.time.sleep
    processes = []
    def start(*args):
        processes.extend(original_start(*args))
        return processes
    monkeypatch.setattr(runner, "start", start)
    def sleep(seconds):
        if seconds == 0.2:
            raise KeyboardInterrupt
        original_sleep(seconds)
    monkeypatch.setattr(runner, "time", SimpleNamespace(sleep=sleep, monotonic=runner.time.monotonic))
    with pytest.raises(KeyboardInterrupt):
        runner.dev(tmp_path / "project", manifest, True)
    assert f"Ready: {url}" in capsys.readouterr().out
    assert all(p.poll() is not None for p in processes)


def test_setup_without_preferences_does_not_create_them(tmp_path, monkeypatch):
    project(tmp_path / "project", codegraph=True, ponytail=True)
    monkeypatch.setattr(runner, "setup", lambda *a: None)
    monkeypatch.setattr(agent_tools, "setup", lambda *a: [])
    result = CliRunner().invoke(main, ["setup", str(tmp_path / "project")])
    assert result.exit_code == 0, result.output
    assert not preferences.path().exists()
    manifest = runner.load(tmp_path / "project")
    assert manifest["codegraph"] and manifest["ponytail"]


def test_advanced_first_use_asks_each_ai_choice_once(tmp_path):
    result = CliRunner().invoke(main, ["init", str(tmp_path / "advanced"), "--preset", "python",
                                      "--advanced", "--no-install", "--no-git"],
                                input="\n" * 8 + "y\nn\n1\n")
    assert result.exit_code == 0, result.output
    assert result.output.count("Add CodeGraph?") == 1
    assert result.output.count("Add Ponytail?") == 1
    assert preferences.load() == {"codegraph": True, "ponytail": False}


def test_setup_warning_exit_and_unverified_label(tmp_path, monkeypatch):
    project(tmp_path / "project", codegraph=True)
    monkeypatch.setattr(runner, "setup", lambda *a: None)
    monkeypatch.setattr(agent_tools, "setup", lambda *a: ["CodeGraph: offline"])
    for flags, label in [([], "Application ready—with warnings"),
                         (["--skip-runtime"], "startup has not been verified")]:
        result = CliRunner().invoke(main, ["setup", str(tmp_path / "project"), *flags])
        assert result.exit_code == 3, result.output
        assert label in result.output
        if flags:
            assert "Application ready" not in result.output


def test_creation_can_offer_docker_without_writing_early(tmp_path, monkeypatch):
    calls = []
    def preflight(manifest, local):
        assert not (tmp_path / "project").exists()
        if local:
            raise RuntimeError("Node 22 missing")
    monkeypatch.setattr(runner, "preflight", preflight)
    monkeypatch.setattr(runner, "prerequisite_problems", lambda *a: [])
    monkeypatch.setattr(runner, "setup", lambda root, manifest, local: calls.append(local))
    monkeypatch.setattr(agent_tools, "setup", lambda *a: [])
    preferences.save({"codegraph": False, "ponytail": False})
    result = CliRunner().invoke(main, ["init", str(tmp_path / "project"), "--preset", "web", "--no-git"],
                                input="1\ny\nn\nn\n")
    assert result.exit_code == 0, result.output
    assert calls == [False]
    assert runner.load(tmp_path / "project")["environment"] == "docker"
    assert "Node 22 missing" in result.output
