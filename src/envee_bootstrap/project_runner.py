"""Standalone generated-project runner. Uses only the Python standard library."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from urllib.request import urlopen

PYTHON_KINDS = {"python", "cli", "flask", "fastapi"}
NODE_KINDS = {"typescript", "azure", "web"}
OUTPUT_STREAM = None


def run(args, cwd, timeout=900):
    """Execute an argument list, never a shell string."""
    print("  " + " ".join(map(str, args)), flush=True)
    try:
        process = subprocess.Popen(
            list(map(str, args)), cwd=cwd, start_new_session=os.name != "nt",
            stdout=OUTPUT_STREAM, stderr=subprocess.STDOUT if OUTPUT_STREAM else None,
        )
        try:
            code = process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            stop([process])
            raise
        if code:
            raise subprocess.CalledProcessError(code, args)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required command not found: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Command failed with exit code {exc.returncode}: {' '.join(map(str, args))}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out after {timeout}s: {args[0]}") from exc


def capture(args, cwd=None):
    """Read bounded prerequisite output."""
    try:
        return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT, timeout=30).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Cannot run {' '.join(args)}. Install it and check permissions.") from exc


def executable(name):
    """Resolve platform-specific executable names."""
    found = shutil.which(name + ".cmd") if os.name == "nt" and name in {"npm", "func"} else shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} is missing from PATH. Install it, then retry setup.")
    return found


def log_directory(root):
    """Keep existing Forge projects' logs covered by their original ignore rules."""
    legacy = (root / "forge.json").exists() and not (root / "envee.json").exists()
    return root / (".forge" if legacy else ".envee")


def load(root):
    """Validate the saved manifest before using its paths."""
    try:
        path = root / "envee.json"
        if not path.exists():
            path = root / "forge.json"
        manifest = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError("Not an Envee project: envee.json (or legacy forge.json) is missing or invalid.") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != 1
        or not isinstance(manifest.get("components"), list)
    ):
        raise RuntimeError("Unsupported Envee manifest schema.")
    if not manifest["components"]:
        raise RuntimeError("A project must have at least one component.")
    for c in manifest["components"]:
        if not isinstance(c, dict) or c.get("kind") not in PYTHON_KINDS | NODE_KINDS:
            raise RuntimeError("Invalid component kind.")
        if not isinstance(c.get("path"), str) or c["path"] not in {".", "backend", "frontend"}:
            raise RuntimeError("Invalid component path.")
        if not (root / c["path"]).resolve().is_relative_to(root.resolve()):
            raise RuntimeError("Component path escapes this project.")
    if (
        not isinstance(manifest.get("name"), str)
        or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", manifest["name"])
        or len(manifest["name"]) > 64
        or manifest.get("environment") not in {"local", "docker", "devcontainer"}
        or manifest.get("database") not in {"none", "sqlite"}
        or manifest.get("preset")
        not in PYTHON_KINDS | NODE_KINDS | {"fullstack-flask", "fullstack-fastapi", "fullstack-azure"}
        or any(type(manifest.get(key)) is not bool for key in ["lint", "tests"])
        or any(type(manifest.get(key, False)) is not bool for key in ["codegraph", "ponytail"])
    ):
        raise RuntimeError("Invalid project settings in envee.json.")
    return manifest


def preflight(manifest, local, skip_runtime=False):
    """Check everything needed before downloading dependencies."""
    if sys.version_info < (3, 12):
        raise RuntimeError("Python 3.12 or newer is required.")
    if not local:
        docker = executable("docker")
        capture([docker, "info", "--format", "{{.ServerVersion}}"])
        capture([docker, "compose", "version"])
        return
    kinds = {c["kind"] for c in manifest["components"]}
    if kinds & NODE_KINDS:
        select_node()
        executable("npm")
    if "azure" in kinds and not skip_runtime:
        version = capture([executable("func"), "--version"])
        if not version.startswith("4."):
            raise RuntimeError("Azure Functions Core Tools v4 is required.")


def select_node():
    """Use an already installed nvm runtime without changing the user's shell."""

    def supported(node):
        version = capture([str(node), "--version"]).lstrip("v").split(".")
        return len(version) >= 2 and version[0] == "22" and int(version[1]) >= 13

    current = shutil.which("node")
    if current and supported(current):
        return
    nvm = Path(os.environ.get("NVM_DIR", str(Path.home() / ".nvm"))) / "versions/node"
    candidates = []
    for node in nvm.glob("v22.*/bin/node"):
        match = re.fullmatch(r"v22\.(\d+)\.(\d+)", node.parent.parent.name)
        if match and os.access(node, os.X_OK):
            candidates.append((tuple(map(int, match.groups())), node))
    for _, node in sorted(candidates, reverse=True):
        if supported(node):
            os.environ["PATH"] = str(node.parent) + os.pathsep + os.environ.get("PATH", "")
            print("Using your installed Node 22 runtime for this project.", flush=True)
            return
    raise RuntimeError("Node 22.13+ (22.x) is required. Install it with nvm install 22, or choose Docker.")


def python(cwd):
    """Use the project interpreter rather than global site packages."""
    path = cwd / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not path.is_file():
        raise RuntimeError(f"Missing virtual environment in {cwd}. Run setup first.")
    return str(path)


def check_commands(manifest, kind, py):
    """One source of truth for local and container validation."""
    if kind in PYTHON_KINDS:
        commands = [[py, "-m", "compileall", "-q", "app"]]
        if manifest["lint"]:
            commands.extend([[py, "-m", "pylint", "app"], [py, "-m", "black", "--check", "app"]])
        if manifest["tests"]:
            commands.append([py, "-m", "pytest", "-q"])
        if manifest["database"] == "sqlite" and kind in {"flask", "fastapi"}:
            commands.append([py, "-c", "from app.database import check_database; assert check_database()"])
        return commands
    commands = [["npm", "run", "build"]]
    if manifest["lint"]:
        commands.append(["npm", "run", "lint"])
    if manifest["tests"]:
        commands.append(["npm", "test"])
    return commands


def setup(root, manifest, local, skip_runtime=False):
    """Install and verify; preserve existing sources and settings."""
    preflight(manifest, local, skip_runtime)
    if not local and manifest["environment"] == "devcontainer":
        devcontainer(root, manifest, "setup", skip_runtime, build=True)
        return
    if not local:
        docker_locks(root, manifest)
        run(["docker", "compose", "build"], root, timeout=1800)
    else:
        for c in manifest["components"]:
            cwd = root / c["path"]
            print(f"Installing {c['kind']} ({c['path']})", flush=True)
            if c["kind"] in PYTHON_KINDS:
                if not (cwd / ".venv").exists():
                    run([sys.executable, "-m", "venv", ".venv"], cwd)
                py = python(cwd)
                run([py, "-m", "pip", "install", "-r", "requirements.txt"], cwd)
                run([py, "-m", "pip", "install", "-e", "."], cwd)
            else:
                command = "ci" if (cwd / "package-lock.json").exists() else "install"
                run([executable("npm"), command, "--no-fund", "--no-audit"], cwd)
            settings(cwd, c["kind"])
    check(root, manifest, local, skip_runtime)


def settings(cwd, kind):
    """Create credential-free local settings once, with exclusive creation."""
    if kind == "azure":
        target = cwd / "local.settings.json"
        if not target.exists():
            with target.open("x") as stream:
                stream.write((cwd / "local.settings.example.json").read_text())


def docker_locks(root, manifest):
    """Resolve npm lockfiles using the selected container runtime."""
    for c in manifest["components"]:
        if c["kind"] not in NODE_KINDS:
            continue
        cwd = root / c["path"]
        if not (cwd / "package-lock.json").exists():
            run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--user",
                    f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "0:0",
                    "--env",
                    "HOME=/tmp",
                    "--mount",
                    f"type=bind,source={cwd},target=/workspace",
                    "--workdir",
                    "/workspace",
                    "node:22-bookworm-slim",
                    "npm",
                    "install",
                    "--package-lock-only",
                    "--no-fund",
                    "--no-audit",
                ],
                root,
            )


def service_name(manifest, c):
    """Match generated Compose service names."""
    if c["kind"] == "web" and manifest["preset"].startswith("fullstack-"):
        return "frontend"
    return "backend" if manifest["preset"].startswith("fullstack-") else "app"


def check(root, manifest, local, skip_runtime=False):
    """Run builds, selected tools and a live startup smoke check."""
    preflight(manifest, local, skip_runtime)
    if not local and manifest["environment"] == "devcontainer":
        devcontainer(root, manifest, "check", skip_runtime)
        return
    for c in manifest["components"]:
        cwd = root / c["path"]
        py = python(cwd) if local and c["kind"] in PYTHON_KINDS else "python"
        for args in check_commands(manifest, c["kind"], py):
            if local:
                if args[0] == "npm":
                    args[0] = executable("npm")
                run(args, cwd)
            else:
                run(
                    [
                        "docker",
                        "compose",
                        "run",
                        "--rm",
                        "--no-deps",
                        "--entrypoint",
                        args[0],
                        service_name(manifest, c),
                        *args[1:],
                    ],
                    root,
                )
    if not skip_runtime:
        smoke(root, manifest, local)
    print("Project checks passed" + (" (live startup skipped)" if skip_runtime else ""), flush=True)


def dev_command(cwd, kind):
    """Start without a shell or reload grandchildren."""
    if kind in PYTHON_KINDS:
        py = python(cwd)
        if kind == "flask":
            return [
                py,
                "-m",
                "flask",
                "--app",
                "app.main:create_app",
                "run",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ]
        if kind == "fastapi":
            return [py, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
        return [py, "-m", "app.main"]
    if kind == "azure":
        return [executable("func"), "start", "--port", "7071"]
    if kind == "web":
        return [executable("npm"), "run", "dev"]
    return [executable("node"), "dist/index.js"]


def start(root, manifest, quiet=False):
    """Start all components; clean up partial startup failures."""
    processes = []
    try:
        for c in manifest["components"]:
            cwd = root / c["path"]
            if c["kind"] in {"azure", "typescript"}:
                run([executable("npm"), "run", "build"], cwd)
            settings(cwd, c["kind"])
            output = None
            if quiet:
                logs = log_directory(root)
                logs.mkdir(exist_ok=True)
                output = (logs / f"{c['kind']}-startup.log").open("w")
            try:
                process = subprocess.Popen(
                    dev_command(cwd, c["kind"]),
                    cwd=cwd,
                    stdout=output,
                    stderr=subprocess.STDOUT if quiet else None,
                    start_new_session=os.name != "nt",
                )
            finally:
                if output:
                    output.close()
            processes.append(process)
    except BaseException:
        stop(processes)
        raise
    return processes


def stop(processes):
    """Stop each process tree, including npm's child server."""
    for process in processes:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False
                )
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait(timeout=5)


def endpoints(manifest):
    """Verify the API directly and through the full-stack proxy."""
    kinds = {c["kind"] for c in manifest["components"]}
    urls = []
    if kinds & {"flask", "fastapi", "azure"}:
        urls.append(("http://127.0.0.1:" + ("7071" if "azure" in kinds else "8000") + "/api/health", True))
    if "web" in kinds:
        urls.append(("http://127.0.0.1:5173/", False))
        if manifest["preset"].startswith("fullstack-"):
            urls.append(("http://127.0.0.1:5173/api/health", True))
    return urls


def probe(urls, processes=(), timeout=90):
    """Wait for real HTTP responses instead of assuming spawn means ready."""
    deadline = time.monotonic() + timeout
    pending = list(urls)
    while pending and time.monotonic() < deadline:
        if any(p.poll() is not None for p in processes):
            raise RuntimeError("A development server exited during startup. See the project's startup logs in .envee/ (legacy .forge/).")
        for url, is_json in pending[:]:
            try:
                with urlopen(url, timeout=2) as response:
                    body = response.read()
                    if is_json and json.loads(body).get("status") != "ok":
                        continue
                    if not is_json and b'<div id="app"' not in body:
                        continue
                pending.remove((url, is_json))
            except (OSError, ValueError):
                pass
        if pending:
            time.sleep(0.3)
    if pending:
        raise RuntimeError("Startup did not become ready: " + ", ".join(url for url, _ in pending))


def smoke(root, manifest, local):
    """Check startup while leaving no servers running."""
    urls = endpoints(manifest)
    if not urls:
        for c in manifest["components"]:
            cwd = root / c["path"]
            if local:
                run(dev_command(cwd, c["kind"]), cwd, timeout=30)
                if c["kind"] == "cli":
                    command = (
                        cwd
                        / ".venv"
                        / ("Scripts" if os.name == "nt" else "bin")
                        / (manifest["name"] + (".exe" if os.name == "nt" else ""))
                    )
                    run([str(command), "--name", "Envee"], cwd, timeout=30)
            else:
                run(["docker", "compose", "run", "--rm", service_name(manifest, c)], root, timeout=30)
                if c["kind"] == "cli":
                    run(
                        [
                            "docker",
                            "compose",
                            "run",
                            "--rm",
                            "--entrypoint",
                            manifest["name"],
                            service_name(manifest, c),
                            "--name",
                            "Envee",
                        ],
                        root,
                        timeout=30,
                    )
        return
    # Fail before starting if the port is occupied; never mistake another service for this project.
    import socket

    for url, _ in urls:
        port = int(url.split(":")[2].split("/")[0])
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(
                    f"Port {port} is in use. Stop the other service, then retry check."
                ) from exc
    if local:
        processes = start(root, manifest, quiet=True)
        try:
            probe(urls, processes)
        finally:
            stop(processes)
    else:
        try:
            run(["docker", "compose", "up", "-d", "--wait", "--wait-timeout", "90"], root)
            probe(urls, timeout=120)
        except (RuntimeError, OSError):
            logs = capture(["docker", "compose", "logs", "--no-color"], root)
            log_directory(root).mkdir(exist_ok=True)
            (log_directory(root) / "compose-startup.log").write_text(logs)
            print(logs[-8000:], flush=True)
            raise
        finally:
            run(["docker", "compose", "down"], root)
    print("Live startup and HTTP checks passed", flush=True)


def devcontainer(root, manifest, action, skip_runtime, build=False):
    """Validate the actual VS Code image and setup command in a clean container."""
    image = "envee-devcontainer:" + manifest["name"]
    if build:
        run(["docker", "build", "-t", image, str(root / ".devcontainer")], root, timeout=1800)
    args = [
        "docker",
        "run",
        "--rm",
        "--init",
        "--mount",
        f"type=bind,source={root},target=/workspace",
        "--workdir",
        "/workspace",
        image,
        "python3",
        "scripts/project.py",
        action,
        "--local",
    ]
    if skip_runtime:
        args.append("--skip-runtime")
    run(args, root, timeout=1800)


def main():
    parser = argparse.ArgumentParser(description="Install, check or run this Envee project.")
    parser.add_argument("action", choices=["setup", "check", "dev"])
    parser.add_argument("--local", action="store_true", help="Use local tools instead of Docker.")
    parser.add_argument("--skip-runtime", action="store_true", help="Skip live startup (useful in CI).")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        manifest = load(root)
        local = (
            args.local
            or manifest["environment"] == "local"
            or (manifest["environment"] == "devcontainer" and Path("/.dockerenv").exists())
        )
        if args.action == "setup":
            setup(root, manifest, local, args.skip_runtime)
        elif args.action == "check":
            check(root, manifest, local, args.skip_runtime)
        elif not local:
            run(["docker", "compose", "up", "--build"], root, timeout=86400)
        else:
            preflight(manifest, True)
            processes = start(root, manifest)
            try:
                while True:
                    exited = [p for p in processes if p.poll() is not None]
                    if exited:
                        if any(p.returncode for p in exited):
                            raise RuntimeError("A development process failed. See its output above.")
                        break
                    time.sleep(0.2)
            finally:
                stop(processes)
    except KeyboardInterrupt:
        print("\nStopped.")
    except (RuntimeError, OSError, KeyError, ValueError) as exc:
        print(
            f"\nSetup failed: {exc}\nFix the issue and rerun python3 scripts/project.py setup.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
