"""Agent-tool packaging, safe downloads and Git exclusion behavior."""

from io import BytesIO
import json
from pathlib import Path
import subprocess
import tarfile
import tomllib
import zipfile

from click.testing import CliRunner
import pytest

from envee_bootstrap import agent_tools, project_runner
from envee_bootstrap.cli import main, write_files
from envee_bootstrap.model import Options
from envee_bootstrap.templates import render


def isolate_git(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return tmp_path / ".config/git/ignore"


@pytest.mark.parametrize("custom", [False, True])
def test_global_ignore_preserves_rules_and_is_idempotent(tmp_path, monkeypatch, custom):
    path = isolate_git(tmp_path, monkeypatch)
    if custom:
        path = tmp_path / "custom-ignore"
        subprocess.run(["git", "config", "--global", "core.excludesfile", str(path)], check=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Existing user rules\nmy-local-file")
    assert agent_tools.global_ignore() == path
    first = path.read_bytes()
    agent_tools.global_ignore()
    assert path.read_bytes() == first
    assert first.startswith(b"# Existing user rules\nmy-local-file\n")
    assert all(rule in path.read_text() for rule in agent_tools.IGNORE_PATTERNS)


def test_agent_files_are_ignored_without_global_rules(tmp_path, monkeypatch):
    isolate_git(tmp_path, monkeypatch)
    project = tmp_path / "project"
    write_files(project, render(Options(name="test", preset="python")))
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True)
    paths = ["AGENTS.md", ".agents/skills/ponytail/SKILL.md", ".codegraph/codegraph.db", ".codex/config.toml"]
    for path in paths:
        result = subprocess.run(["git", "check-ignore", path], cwd=project, capture_output=True)
        assert result.returncode == 0, path
    assert (project / ".agents/skills/ponytail/LICENSE").read_text().startswith("MIT License")


def test_agent_tools_can_be_disabled():
    files = render(Options(name="test", preset="python", codegraph=False, ponytail=False))
    assert "AGENTS.md" not in files
    assert not any(path.startswith(".agents/") for path in files)


def test_cli_agent_optouts_are_respected(tmp_path):
    result = CliRunner().invoke(main, ["init", str(tmp_path / "plain"), "--yes", "--no-git",
                                      "--no-install", "--no-codegraph", "--no-ponytail"])
    assert result.exit_code == 0, result.output
    manifest = json.loads((tmp_path / "plain/envee.json").read_text())
    assert not manifest["codegraph"] and not manifest["ponytail"]
    assert not (tmp_path / "plain/AGENTS.md").exists()


def test_existing_codegraph_is_reused(monkeypatch):
    monkeypatch.setattr(agent_tools.shutil, "which", lambda name: "/installed/codegraph")
    assert agent_tools.codegraph_command() == ["/installed/codegraph"]


def test_download_checksum_failure_installs_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(agent_tools.shutil, "which", lambda name: None)
    monkeypatch.setattr(agent_tools.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(agent_tools.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(agent_tools, "urlopen", lambda *args, **kwargs: BytesIO(b"wrong archive"))
    with pytest.raises(RuntimeError, match="checksum"):
        agent_tools.codegraph_command()
    assert not (tmp_path / ".cache/envee/codegraph/1.4.1/darwin-arm64").exists()


@pytest.mark.parametrize("extension", ["zip", "tar.gz"])
def test_archive_escape_rejected(tmp_path, extension):
    archive = tmp_path / ("unsafe." + extension)
    if extension == "zip":
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("../escaped", "unsafe")
    else:
        with tarfile.open(archive, "w:gz") as package:
            entry = tarfile.TarInfo("../escaped")
            entry.size = 6
            package.addfile(entry, BytesIO(b"unsafe"))
    with pytest.raises(RuntimeError):
        agent_tools.unpack(archive, tmp_path / "unpack", "darwin-arm64")
    assert not (tmp_path / "escaped").exists()


def test_setup_retries_sync_existing_index(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_tools, "global_ignore", lambda: tmp_path / "ignore")
    monkeypatch.setattr(agent_tools, "codegraph_command", lambda: ["codegraph"])
    commands = []
    monkeypatch.setattr(project_runner, "run", lambda args, cwd: commands.append(args))
    agent_tools.setup(tmp_path, {"codegraph": True, "ponytail": True})
    assert any("init" in command for command in commands)
    (tmp_path / ".codegraph").mkdir()
    commands.clear()
    agent_tools.setup(tmp_path, {"codegraph": True})
    assert any("sync" in command for command in commands)
    assert not any("init" in command for command in commands)
    config = tomllib.loads((tmp_path / ".codex/config.toml").read_text())
    assert config["mcp_servers"]["codegraph"] == {"command": "codegraph", "args": ["serve", "--mcp"]}


def test_project_mcp_preserves_existing_settings(tmp_path):
    path = tmp_path / ".codex/config.toml"
    path.parent.mkdir()
    path.write_text('[mcp_servers.other]\ncommand = "other-server"\n')
    agent_tools.configure_codex(tmp_path, ["node", "C:\\my tools\\codegraph.js"])
    first = path.read_bytes()
    agent_tools.configure_codex(tmp_path, ["different-codegraph"])
    assert path.read_bytes() == first
    config = tomllib.loads(path.read_text())
    assert config["mcp_servers"]["other"]["command"] == "other-server"
    assert config["mcp_servers"]["codegraph"]["args"] == ["C:\\my tools\\codegraph.js", "serve", "--mcp"]


def test_agent_setup_failure_keeps_retryable_project(tmp_path, monkeypatch):
    monkeypatch.setattr(project_runner, "preflight", lambda *args: None)
    monkeypatch.setattr(project_runner, "setup", lambda *args: None)
    monkeypatch.setattr(agent_tools, "setup", lambda *args: (_ for _ in ()).throw(RuntimeError("Index failed")))
    target = tmp_path / "retry"
    result = CliRunner().invoke(main, ["init", str(target), "--yes", "--no-git"])
    assert result.exit_code != 0 and "envee setup" in result.output
    assert (target / "envee.json").exists() and "ENVIRONMENT IS READY" not in result.output


def test_old_manifests_skip_agent_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_tools, "global_ignore", lambda: pytest.fail("Unexpected global write"))
    agent_tools.setup(tmp_path, {"preset": "python"})


def test_agent_manifest_flag_types_validated(tmp_path):
    files = render(Options(name="test", preset="python"))
    manifest = json.loads(files["envee.json"])
    manifest["codegraph"] = "false"
    (tmp_path / "envee.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="settings"):
        project_runner.load(tmp_path)
