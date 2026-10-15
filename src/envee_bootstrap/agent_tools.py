"""Host-side agent tools, separate from application and container dependencies."""

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from urllib.request import urlopen
import zipfile

from . import project_runner as runner

CODEGRAPH_VERSION = "1.4.1"
CODEGRAPH_SHA256 = {
    "darwin-arm64": "4a679ae5a5cb9fff900dd59bb786da6a581b7f68f4cf713bdedd137e347d34dc",
    "darwin-x64": "436f96943cfd926ea6d0a8454f18833d21254d5fd9b3d224317b1426132def95",
    "linux-arm64": "0d62c5eb2722f8d19d20f7a1bd974445e18d5294cb59be116a0c3d55ce87591f",
    "linux-x64": "fb585ff5018d6faaa46d282b61f4f689bc7967ed8a1b467a5c556dd7ced9b542",
    "win32-arm64": "1adaf3ec30143996fc1a240f4399b4cd82eb494b29240b103444b1f78f4c7b95",
    "win32-x64": "559cb1010b7899b5137f0801d35698f722a33370e907a84968852d3d68f6458d",
}
IGNORE_PATTERNS = (".codegraph/", ".ponytail/", "AGENTS.md", ".agents/skills/ponytail/", ".codex/config.toml")


def global_ignore():
    """Append missing rules to Git's existing global excludes file."""
    configured = ""
    git = shutil.which("git")
    if git:
        result = subprocess.run(
            [git, "config", "--global", "--path", "--get", "core.excludesfile"],
            text=True, capture_output=True, timeout=30,
        )
        if result.returncode not in {0, 1}:
            raise RuntimeError("Could not read Git's global ignore configuration: " + result.stderr.strip())
        configured = result.stdout.strip()
    path = (Path(configured).expanduser() if configured else
            Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "git/ignore")
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [rule for rule in IGNORE_PATTERNS if rule not in existing.splitlines()]
    if missing:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            if existing and not existing.endswith("\n"):
                stream.write("\n")
            stream.write("\n# Envee: local CodeGraph and Ponytail files\n" + "\n".join(missing) + "\n")
    return path


def unpack(archive, destination, target):
    """Extract a verified bundle without permitting paths outside its directory."""
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as package:
            for item in package.infolist():
                if not (destination / item.filename).resolve().is_relative_to(destination.resolve()):
                    raise RuntimeError("CodeGraph archive contains an unsafe path.")
            package.extractall(destination)
    else:
        try:
            with tarfile.open(archive) as package:
                package.extractall(destination, filter="data")
        except tarfile.TarError as exc:
            raise RuntimeError("CodeGraph archive could not be safely extracted.") from exc
    bundle = destination / f"codegraph-{target}"
    node = bundle / ("node.exe" if target.startswith("win32") else "node")
    if not node.is_file() or not (bundle / "lib/dist/bin/codegraph.js").is_file():
        raise RuntimeError("CodeGraph archive is missing its executable.")
    return bundle


def codegraph_command():
    installed = shutil.which("codegraph")
    if installed:
        return [installed]
    system = {"Darwin": "darwin", "Linux": "linux", "Windows": "win32"}.get(platform.system())
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(
        platform.machine().lower()
    )
    target = f"{system}-{arch}"
    if target not in CODEGRAPH_SHA256:
        raise RuntimeError("CodeGraph is unavailable on this platform. Retry with --no-codegraph.")
    cache = Path.home() / ".cache/envee/codegraph" / CODEGRAPH_VERSION / target
    node = cache / ("node.exe" if system == "win32" else "node")
    entry = cache / "lib/dist/bin/codegraph.js"
    if not node.is_file() or not entry.is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="download-", dir=cache.parent) as temporary:
            directory = Path(temporary)
            extension = "zip" if system == "win32" else "tar.gz"
            archive = directory / f"codegraph.{extension}"
            url = ("https://github.com/colbymchenry/codegraph/releases/download/"
                   f"v{CODEGRAPH_VERSION}/codegraph-{target}.{extension}")
            print(f"Downloading CodeGraph {CODEGRAPH_VERSION} ({target})", flush=True)
            digest = hashlib.sha256()
            with urlopen(url, timeout=60) as response, archive.open("wb") as stream:
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    stream.write(chunk)
            if digest.hexdigest() != CODEGRAPH_SHA256[target]:
                raise RuntimeError("CodeGraph download checksum did not match; nothing was installed.")
            bundle = unpack(archive, directory / "unpacked", target)
            if cache.exists():
                raise RuntimeError("An incomplete CodeGraph cache exists. Remove it and retry: " + str(cache))
            bundle.rename(cache)
    return [str(node), "--liftoff-only", str(entry)]


def setup(root, manifest):
    """Index on the host and install project-scoped MCP configuration once."""
    if not (manifest.get("codegraph", False) or manifest.get("ponytail", False)):
        return
    path = global_ignore()
    print(f"Global ignore rules ready: {path}", flush=True)
    if manifest.get("codegraph", False):
        command = codegraph_command()
        runner.run([*command, "--version"], root)
        action = "sync" if (root / ".codegraph").exists() else "init"
        runner.run([*command, action, str(root)], root)
        configure_codex(root, command)


def configure_codex(root, command):
    """Add one project MCP server without overwriting existing agent settings."""
    path = root / ".codex/config.toml"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if "codegraph" in tomllib.loads(existing).get("mcp_servers", {}):
        print("Existing project CodeGraph MCP settings preserved.", flush=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n[mcp_servers.codegraph]\n")
        stream.write("command = " + json.dumps(command[0]) + "\n")
        stream.write("args = " + json.dumps([*command[1:], "serve", "--mcp"]) + "\n")
    print("CodeGraph MCP configured locally; Codex loads it when this project is trusted.", flush=True)
