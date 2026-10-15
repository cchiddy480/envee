"""Contract tests for generation, safety and the interactive flow."""

import ast
from contextlib import nullcontext
from dataclasses import replace
import itertools
import json
import socket
import subprocess
import tomllib
import sys

from click.testing import CliRunner
import pytest

from envee_bootstrap.cli import main, write_files
from envee_bootstrap import cli
from envee_bootstrap.model import Options, PRESETS
from envee_bootstrap import project_runner as runner
from envee_bootstrap.templates import render


def test_rename_preserves_existing_projects(tmp_path, monkeypatch):
    files = render(Options(name="legacy", preset="python", codegraph=False, ponytail=False))
    files["forge.json"] = files.pop("envee.json")
    write_files(tmp_path, files)
    original = (tmp_path / "app/main.py").read_bytes()
    monkeypatch.setattr(runner, "check", lambda *args: None)
    result = CliRunner().invoke(main, ["check", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".forge/check.log").exists()
    assert not (tmp_path / "envee.json").exists()
    assert (tmp_path / "app/main.py").read_bytes() == original


def test_new_manifest_takes_precedence(tmp_path):
    files = render(Options(name="new-project", preset="python"))
    (tmp_path / "envee.json").write_text(files["envee.json"])
    (tmp_path / "forge.json").write_text("invalid legacy file")
    assert runner.load(tmp_path)["name"] == "new-project"
    assert runner.log_directory(tmp_path) == tmp_path / ".envee"


def test_new_brand_and_version(tmp_path):
    result = CliRunner().invoke(main, ["init", str(tmp_path / "brand"), "--yes", "--no-git", "--no-install"])
    assert result.exit_code == 0, result.output
    assert "ENVEE" in result.output and "FORGE" not in result.output
    manifest = json.loads((tmp_path / "brand/envee.json").read_text())
    assert manifest["envee_version"] == "0.2.0"


@pytest.mark.parametrize("keys,expected", [(["\x1b[B", "\r"], "b"), (["\x1b[A", "\r"], "c"), (["2", "\r"], "b")])
def test_keyboard_menu(monkeypatch, keys, expected):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(cli.console, "_force_terminal", True)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    presses = iter(keys)
    monkeypatch.setattr(cli.click, "getchar", lambda: next(presses))
    assert cli.choose("Choose a starter", [("a", "First"), ("b", "Second"), ("c", "Third")]) == expected


@pytest.mark.parametrize("fails", [False, True])
def test_progress_logs_and_restores_runner(tmp_path, capsys, fails):
    original = runner.run
    with pytest.raises(RuntimeError) if fails else nullcontext():
        with cli.progress(tmp_path, "setup"):
            runner.run([sys.executable, "-c", "print('installer details')"], tmp_path)
            if fails:
                raise RuntimeError("failed")
    output = capsys.readouterr().out
    assert "installer details" in (tmp_path / ".envee/setup.log").read_text()
    assert ("installer details" in output) is fails
    assert runner.run is original
    assert runner.OUTPUT_STREAM is None


@pytest.mark.parametrize(
    "preset,environment", list(itertools.product(PRESETS, ["local", "docker", "devcontainer"]))
)
def test_all_templates_parse(preset, environment):
    files = render(Options(name="test-app", preset=preset, environment=environment, ci=True))
    for name, content in files.items():
        if name.endswith(".json") or name == "compose.yaml":
            json.loads(content)
        elif name.endswith(".toml"):
            tomllib.loads(content)
        elif name.endswith(".py"):
            ast.parse(content, filename=name)
    manifest = json.loads(files["envee.json"])
    assert all("\\" not in name for name in files)
    assert len(manifest["components"]) == (2 if preset.startswith("fullstack-") else 1)
    assert "scripts/project.py" in files
    assert ("compose.yaml" in files) == (environment != "local")
    assert files["README.md"].startswith("# test-app\n")
    if environment != "local":
        services = json.loads(files["compose.yaml"])["services"]
        for component in manifest["components"]:
            assert runner.service_name(manifest, component) in services


@pytest.mark.parametrize(
    "name", ["../escape", "A Project", "-bad", "a--b", "null\x00", "a" * 65, "con", "lpt1"]
)
def test_bad_names_rejected(name):
    with pytest.raises(ValueError):
        Options(name=name, preset="python").validate()


@pytest.mark.parametrize("preset", PRESETS)
def test_optional_tools_removed(preset):
    files = render(
        Options(name="plain", preset=preset, lint=False, tests=False, editor=False, env=False, git=False)
    )
    assert not any(
        name.startswith(".vscode") or "/tests/" in name or name.startswith("tests/") for name in files
    )
    assert not any(name.endswith(".env.example") or "eslint.config" in name for name in files)
    for name, content in files.items():
        if name.endswith("package.json"):
            package = json.loads(content)
            assert "test" not in package["scripts"] and "lint" not in package["scripts"]


def test_dry_run_has_no_side_effects(tmp_path):
    target = tmp_path / "preview"
    result = CliRunner().invoke(
        main, ["init", str(target), "--preset", "fullstack-fastapi", "--yes", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "Preview only" in result.output
    assert not target.exists()


def test_existing_files_preserved(tmp_path):
    original = tmp_path / "important.txt"
    original.write_text("keep this")
    result = CliRunner().invoke(main, ["init", str(tmp_path), "--yes", "--no-install"])
    assert result.exit_code != 0
    assert original.read_text() == "keep this"
    assert not (tmp_path / "envee.json").exists()


def test_hidden_files_also_protected(tmp_path):
    (tmp_path / ".env").write_text("secret")
    result = CliRunner().invoke(main, ["init", str(tmp_path), "--yes", "--no-install"])
    assert result.exit_code != 0
    assert "secret" not in result.output


def test_symlink_target_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(real, target_is_directory=True)
    result = CliRunner().invoke(main, ["init", str(link), "--yes", "--no-install"])
    assert result.exit_code != 0 and not list(real.iterdir())


def test_destination_rechecked(tmp_path):
    (tmp_path / "new-file").touch()
    with pytest.raises(ValueError, match="changed"):
        write_files(tmp_path, {"README.md": "hello"})


def test_path_traversal_rejected(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        write_files(tmp_path / "target", {"../../outside": "bad"})
    assert not (tmp_path / "outside").exists()


def test_wizard_fullstack(tmp_path):
    result = CliRunner().invoke(
        main,
        ["init", str(tmp_path / "wizard"), "--no-install", "--no-git"],
        input="2\nmy-project\n3\n2\n1\ny\ny\nn\ny\ny\ny\ny\ny\n",
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((tmp_path / "wizard/envee.json").read_text())
    assert manifest["preset"] == "fullstack-fastapi"
    assert manifest["database"] == "sqlite"
    assert "not been verified" in result.output


def test_default_wizard_skips_tool_questions(tmp_path):
    result = CliRunner().invoke(
        main, ["init", str(tmp_path / "default"), "--no-install", "--no-git"],
        input="\nmy-project\n3\n2\n1\n",
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((tmp_path / "default/envee.json").read_text())
    assert manifest["preset"] == "fullstack-fastapi"
    assert all(manifest[key] for key in ["lint", "tests", "editor", "env"])
    assert not manifest["git"] and not manifest["ci"]
    assert manifest["database"] == "none"
    assert "Add tests?" not in result.output
    assert "Add a local SQLite" not in result.output
    assert "3 / 3" in result.output


@pytest.mark.parametrize("preset", PRESETS)
def test_default_route_honours_flags(tmp_path, preset):
    result = CliRunner().invoke(
        main, ["init", str(tmp_path / preset), "--default", "--name", "test-app",
               "--preset", preset, "--environment", "local", "--ci", "--no-lint",
               "--no-git", "--no-install"],
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((tmp_path / preset / "envee.json").read_text())
    assert manifest["ci"] and manifest["tests"]
    assert not manifest["lint"] and not manifest["git"]
    assert "How would you like" not in result.output and "Add tests?" not in result.output


def test_advanced_flag_with_yes_is_noninteractive(tmp_path):
    result = CliRunner().invoke(
        main, ["init", str(tmp_path / "advanced"), "--advanced", "--yes", "--no-git", "--no-install"],
    )
    assert result.exit_code == 0, result.output
    assert "How would you like" not in result.output and "Add tests?" not in result.output
    assert "Advanced" in result.output


def test_invalid_database_no_writes(tmp_path):
    target = tmp_path / "bad"
    result = CliRunner().invoke(
        main, ["init", str(target), "--preset", "web", "--database", "sqlite", "--yes"]
    )
    assert result.exit_code != 0
    assert not target.exists()


def test_missing_prerequisite_no_writes(tmp_path, monkeypatch):
    target = tmp_path / "missing"
    monkeypatch.setattr(
        runner, "preflight", lambda *args: (_ for _ in ()).throw(RuntimeError("Node is missing"))
    )
    result = CliRunner().invoke(main, ["init", str(target), "--preset", "web", "--yes"])
    assert result.exit_code != 0
    assert "Node is missing" in result.output
    assert not target.exists()


def test_failed_install_retains_retryable_project(tmp_path, monkeypatch):
    target = tmp_path / "retry"
    monkeypatch.setattr(runner, "preflight", lambda *args: None)
    monkeypatch.setattr(runner, "setup", lambda *args: (_ for _ in ()).throw(RuntimeError("Download failed")))
    result = CliRunner().invoke(main, ["init", str(target), "--yes", "--no-git"])
    assert result.exit_code != 0
    assert (target / "envee.json").exists()
    assert "envee setup" in result.output
    assert "ENVIRONMENT IS READY" not in result.output


def test_settings_not_overwritten(tmp_path):
    (tmp_path / "local.settings.example.json").write_text('{"example":true}')
    runner.settings(tmp_path, "azure")
    (tmp_path / "local.settings.json").write_text('{"my-setting":true}')
    runner.settings(tmp_path, "azure")
    assert json.loads((tmp_path / "local.settings.json").read_text()) == {"my-setting": True}


@pytest.mark.parametrize("path", ["../outside", "/tmp", "backend/../../outside"])
def test_untrusted_manifest_paths_rejected(tmp_path, path):
    (tmp_path / "envee.json").write_text(
        json.dumps({"schema": 1, "components": [{"path": path, "kind": "python"}]})
    )
    with pytest.raises(RuntimeError, match="path"):
        runner.load(tmp_path)


def test_manifest_symlink_escape_rejected(tmp_path):
    (tmp_path / "backend").symlink_to(tmp_path.parent, target_is_directory=True)
    (tmp_path / "envee.json").write_text(
        json.dumps({"schema": 1, "components": [{"path": "backend", "kind": "python"}]})
    )
    with pytest.raises(RuntimeError, match="escapes"):
        runner.load(tmp_path)


@pytest.mark.parametrize(
    "manifest", [[], None, {"schema": 1, "components": [{"path": ".", "kind": "python"}]}]
)
def test_malformed_manifest_fails_clearly(tmp_path, manifest):
    (tmp_path / "envee.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="schema|settings"):
        runner.load(tmp_path)


def test_command_failure_reports_exit_code(tmp_path):
    import sys

    with pytest.raises(RuntimeError, match="exit code 7"):
        runner.run([sys.executable, "-c", "raise SystemExit(7)"], tmp_path)


def test_missing_command_reports_remediation(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        runner.run(["envee-nonexistent-command"], tmp_path)


def test_command_timeout_stops_process(tmp_path):
    import os
    import sys

    marker = tmp_path / "pid"
    with pytest.raises(RuntimeError, match="timed out"):
        runner.run(
            [
                sys.executable,
                "-c",
                "import os,time; from pathlib import Path; Path('pid').write_text(str(os.getpid())); time.sleep(60)",
            ],
            tmp_path,
            timeout=1,
        )
    assert marker.exists()
    if os.name != "nt":
        with pytest.raises(ProcessLookupError):
            os.kill(int(marker.read_text()), 0)


def test_occupied_port_fails_without_starting(tmp_path, monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        monkeypatch.setattr(runner, "endpoints", lambda m: [(f"http://127.0.0.1:{port}/", False)])
        with pytest.raises(RuntimeError, match="in use"):
            runner.smoke(tmp_path, {}, True)


def test_process_group_cleaned_up(tmp_path):
    import os
    import sys

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=os.name != "nt"
    )
    runner.stop([process])
    assert process.poll() is not None


def test_options_are_immutable():
    base = Options(name="test", preset="flask")
    assert replace(base, database="sqlite").database == "sqlite"
    assert base.database == "none"


def test_selects_installed_nvm_runtime_without_download(tmp_path, monkeypatch):
    import os

    nvm = tmp_path / "nvm"
    node = nvm / "versions/node/v22.22.3/bin/node"
    node.parent.mkdir(parents=True)
    node.touch()
    monkeypatch.setenv("NVM_DIR", str(nvm))
    monkeypatch.setenv("PATH", "original-path")
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/current/node")
    monkeypatch.setattr(runner.os, "access", lambda *args: True)
    monkeypatch.setattr(runner, "capture", lambda args: "v22.22.3" if args[0] == str(node) else "v26.5.0")
    runner.select_node()
    assert os.environ["PATH"] == str(node.parent) + os.pathsep + "original-path"


def test_missing_node_runtime_has_clear_next_step(tmp_path, monkeypatch):
    monkeypatch.setenv("NVM_DIR", str(tmp_path))
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="nvm install 22"):
        runner.select_node()


def test_matching_node_runtime_keeps_path(monkeypatch):
    import os

    monkeypatch.setenv("PATH", "original-path")
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/current/node")
    monkeypatch.setattr(runner, "capture", lambda args: "v22.22.3")
    runner.select_node()
    assert os.environ["PATH"] == "original-path"


def test_init_in_empty_existing_directory(tmp_path):
    result = CliRunner().invoke(
        main, ["init", str(tmp_path), "--name", "empty", "--yes", "--no-install", "--no-git"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "app/main.py").is_file()
    assert not (tmp_path / ".git").exists()


def test_compose_proxy_and_volume():
    files = render(Options(name="test", preset="fullstack-fastapi", environment="docker", database="sqlite"))
    compose = json.loads(files["compose.yaml"])
    assert compose["services"]["frontend"]["environment"]["API_PROXY_TARGET"] == "http://backend:8000"
    assert compose["services"]["backend"]["volumes"] == ["database:/workspace/data"]
    assert "database" in compose["volumes"]


def test_manifest_and_readme_port_agree():
    files = render(Options(name="test", preset="fullstack-azure"))
    assert "7071" in files["frontend/vite.config.ts"]
    assert "7071" in files["README.md"]
    assert ("http://127.0.0.1:5173/api/health", True) in runner.endpoints(json.loads(files["envee.json"]))
