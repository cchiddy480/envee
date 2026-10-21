"""Standalone generated-project runner. Uses only the Python standard library."""

import argparse
from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import tempfile
import tomllib
from urllib.request import urlopen

PYTHON_KINDS = {"python", "cli", "flask", "fastapi"}
NODE_KINDS = {"typescript", "azure", "web"}
OUTPUT_STREAM = None
STAGE_CALLBACK = None
UV_VERSION = "0.13.4"


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
        or type(manifest.get("schema")) is not int
        or manifest.get("schema") not in {1, 2}
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


def prerequisite_problems(manifest, local, skip_runtime=False):
    """Collect independent failures so one doctor visit gives the whole picture."""
    problems = []
    def attempt(check):
        try:
            check()
        except (RuntimeError, OSError, ValueError) as exc:
            problems.append(str(exc))
    if sys.version_info < (3, 12):
        problems.append("Python 3.12 or newer is required. Install Python, then retry envee setup.")
    if manifest.get("git") and not shutil.which("git"):
        problems.append("Git is missing. Install Git, then retry envee setup.")
    if not local:
        if shutil.which("docker"):
            attempt(lambda: capture([executable("docker"), "info", "--format", "{{.ServerVersion}}"]))
            attempt(lambda: capture([executable("docker"), "compose", "version"]))
            if problems:
                problems.append("Start Docker and ensure Docker Compose is available, then retry envee doctor.")
        else:
            problems.append("Docker is missing. Install and start Docker, then retry envee doctor.")
        return problems
    kinds = {c["kind"] for c in manifest["components"]}
    if kinds & NODE_KINDS:
        attempt(select_node)
        if not shutil.which("npm"):
            problems.append("npm is missing. Install Node 22 with npm, then retry envee setup.")
    if "azure" in kinds and not skip_runtime:
        def azure():
            version = capture([executable("func"), "--version"])
            if not version.startswith("4."):
                raise RuntimeError("Azure Functions Core Tools v4 is required.")
        attempt(azure)
        if any("func" in problem.lower() for problem in problems):
            problems.append("Install Azure Functions Core Tools v4, then retry envee doctor.")
    return problems


def preflight(manifest, local, skip_runtime=False):
    problems = prerequisite_problems(manifest, local, skip_runtime)
    if problems:
        raise RuntimeError("Prerequisite problems:\n- " + "\n- ".join(problems))


def discover(directory):
    """Find the nearest manifest, without crossing a Git checkout boundary."""
    root = directory.resolve()
    if not root.is_dir():
        raise RuntimeError(f"Directory does not exist: {root}")
    for candidate in (root, *root.parents):
        if any((candidate / name).exists() for name in ("envee.json", "forge.json")):
            load(candidate)
            return candidate
        if (candidate / ".git").exists():
            break
    return None


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


def atomic_write(path, content, mode=None):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        if mode is not None:
            temporary.chmod(mode)
        elif path.exists():
            shutil.copymode(path, temporary)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class SetupProgress:
    """Advisory progress; never used to skip installation or verification."""
    def __init__(self, root, stages):
        self.path = log_directory(root) / "setup-state.json"
        self.path.parent.mkdir(exist_ok=True)
        self.state = {"schema": 1, "log": "setup.log" if (self.path.parent / "setup.log").exists() else None,
                      "stages": [{"name": name, "status": "pending"} for name in stages]}

    @contextmanager
    def stage(self, name):
        item = next((item for item in self.state["stages"] if item["name"] == name), None)
        if item is None:
            item = {"name": name, "status": "pending"}
            self.state["stages"].append(item)
        item["status"] = "running"
        self.write()
        print(f"Setup · {name}", flush=True)
        if STAGE_CALLBACK:
            STAGE_CALLBACK(name)
        try:
            yield
        except BaseException as exc:
            item["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            self.write()
            raise
        else:
            item["status"] = "completed"
            self.write()

    def write(self):
        atomic_write(self.path, json.dumps(self.state, indent=2) + "\n", mode=0o644)


def previous_setup(root):
    path = log_directory(root) / "setup-state.json"
    if not path.exists():
        return []
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        stages = state["stages"]
        if state["schema"] != 1 or not isinstance(stages, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("name"), str) or
            item.get("status") not in {"pending", "running", "completed", "failed", "interrupted", "warning"}
            for item in stages
        ):
            raise ValueError("Invalid progress")
        if all(item["status"] == "completed" for item in stages):
            return []
        return [f"{item['status'].capitalize()}: {item['name']}" for item in stages]
    except (OSError, ValueError, KeyError, TypeError):
        return ["Previous setup progress is unreadable; it is safe to retry setup."]


def dependency_fingerprint(cwd):
    data = tomllib.loads((cwd / "pyproject.toml").read_text(encoding="utf-8")).get("project")
    if not isinstance(data, dict):
        raise ValueError("pyproject.toml requires a [project] table.")
    values = {key: data.get(key) for key in ("requires-python", "dependencies", "optional-dependencies")}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def locking_problems(root, manifest, allow_missing=False):
    if manifest["schema"] == 1:
        return []
    problems = []
    for component in manifest["components"]:
        cwd = root / component["path"]
        try:
            if component["kind"] in PYTHON_KINDS:
                path = cwd / "requirements.lock"
                if not path.exists():
                    if not allow_missing:
                        problems.append(f"Missing Python lock in {component['path']}. Run envee setup.")
                elif not path.read_text(encoding="utf-8").startswith(
                    "# envee-input-sha256: " + dependency_fingerprint(cwd) + "\n"
                ):
                    problems.append(f"Python dependencies changed in {component['path']}. Run envee lock.")
            else:
                path = cwd / "package-lock.json"
                if not path.exists():
                    if not allow_missing:
                        problems.append(f"Missing npm lock in {component['path']}. Run envee setup.")
                else:
                    package = json.loads((cwd / "package.json").read_text(encoding="utf-8"))
                    lock_data = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(package, dict) or not isinstance(lock_data, dict) or not isinstance(
                        lock_data.get("packages"), dict
                    ):
                        raise ValueError("Invalid npm dependency or lock metadata; refresh with envee lock.")
                    locked = lock_data["packages"].get("")
                    if not isinstance(locked, dict) or any(package.get(key, {}) != locked.get(key, {})
                                             for key in ("dependencies", "devDependencies", "optionalDependencies")):
                        problems.append(f"Node dependencies changed in {component['path']}. Run envee lock.")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            problems.append(f"Cannot validate dependency files in {component['path']}: {exc}")
    return problems


def python_lock(cwd):
    """Resolve with a disposable tool environment; the application still uses pip."""
    path = cwd / "requirements.lock"
    fingerprint = dependency_fingerprint(cwd)
    print(f"Preparing uv {UV_VERSION} in a temporary tool environment (no Python downloads).", flush=True)
    with tempfile.TemporaryDirectory(prefix="envee-lock-") as temporary:
        tool = Path(temporary)
        run([sys.executable, "-m", "venv", str(tool / ".venv")], cwd)
        py = python(tool)
        run([py, "-m", "pip", "install", "--only-binary=:all:", f"uv=={UV_VERSION}"], cwd)
        output = tool / "requirements.txt"
        if path.exists():
            output.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        run([py, "-m", "uv", "pip", "compile", "pyproject.toml", "--extra", "dev",
             "--universal", "--python-version", "3.12", "--generate-hashes", "--no-header",
             "--no-annotate", "--no-config", "--no-python-downloads", "--output-file", str(output)], cwd)
        if dependency_fingerprint(cwd) != fingerprint:
            raise RuntimeError("Dependencies changed while locking. Retry envee lock.")
        content = ("# envee-input-sha256: " + fingerprint + "\n"
                   f"# Generated with uv {UV_VERSION}; refresh with envee lock.\n" +
                   output.read_text(encoding="utf-8"))
        atomic_write(path, content, mode=0o644)


def node_lock(cwd, local):
    package_before = (cwd / "package.json").read_bytes()
    with tempfile.TemporaryDirectory(prefix="envee-npm-lock-") as temporary:
        stage = Path(temporary)
        for name in ("package.json", "package-lock.json", ".npmrc"):
            if (cwd / name).exists():
                shutil.copy2(cwd / name, stage / name)
        args = ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-fund", "--no-audit"]
        if local:
            args[0] = executable("npm")
        else:
            args = ["docker", "run", "--rm", "--user",
                    f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "0:0",
                    "--env", "HOME=/tmp", "--mount", f"type=bind,source={stage},target=/workspace",
                    "--workdir", "/workspace", "node:22-bookworm-slim", *args]
        run(args, stage)
        content = (stage / "package-lock.json").read_text(encoding="utf-8")
        json.loads(content)
        if (cwd / "package.json").read_bytes() != package_before:
            raise RuntimeError("Dependencies changed while locking. Retry envee lock.")
        atomic_write(cwd / "package-lock.json", content, mode=0o644)


def lock(root, manifest, local, refresh=True):
    if manifest["schema"] != 2:
        raise RuntimeError("Locking is available for new Envee 0.4 projects; this project's setup is unchanged.")
    if not refresh:
        problems = locking_problems(root, manifest, allow_missing=True)
        if problems:
            raise RuntimeError("\n".join(problems))
    for component in manifest["components"]:
        cwd = root / component["path"]
        if component["kind"] in PYTHON_KINDS:
            if refresh or not (cwd / "requirements.lock").exists():
                if local:
                    python_lock(cwd)
                else:
                    code = ("import runpy,sys; from pathlib import Path; "
                            "r=runpy.run_path('scripts/project.py'); "
                            "r['python_lock'](Path('/workspace')/sys.argv[1])")
                    run(["docker", "run", "--rm", "--user",
                         f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "0:0",
                         "--env", "HOME=/tmp", "--mount", f"type=bind,source={root},target=/workspace",
                         "--workdir", "/workspace", "python:3.12-slim-bookworm", "python", "-c", code,
                         component["path"]], root)
        elif refresh or not (cwd / "package-lock.json").exists():
            node_lock(cwd, local)


def setup(root, manifest, local, skip_runtime=False):
    """Install and verify; progress is advisory and application files stay intact."""
    container = not local and manifest["environment"] == "devcontainer"
    stages = ["Prerequisites"]
    if container:
        stages += ["Dev Container setup and verification"]
    else:
        if manifest["schema"] == 2:
            stages += ["Dependency locks"]
        stages += ([f"Install {c['kind']} ({c['path']})" for c in manifest["components"]]
                   if local else ["Build application images"])
        stages += ["Selected checks"] + ([] if skip_runtime else ["Startup verification"])
    progress = SetupProgress(root, stages)
    with progress.stage("Prerequisites"):
        preflight(manifest, local, skip_runtime)
    if container:
        with progress.stage("Dev Container setup and verification"):
            devcontainer(root, manifest, "setup", skip_runtime, build=True)
        return progress
    if manifest["schema"] == 2:
        with progress.stage("Dependency locks"):
            lock(root, manifest, local, refresh=False)
    if not local:
        with progress.stage("Build application images"):
            if manifest["schema"] == 1:
                docker_locks(root, manifest)
            run(["docker", "compose", "build"], root, timeout=1800)
    else:
        for c in manifest["components"]:
            cwd = root / c["path"]
            with progress.stage(f"Install {c['kind']} ({c['path']})"):
                if c["kind"] in PYTHON_KINDS:
                    if not (cwd / ".venv").exists():
                        run([sys.executable, "-m", "venv", ".venv"], cwd)
                    py = python(cwd)
                    args = [py, "-m", "pip", "install"]
                    run([*args, *(["--require-hashes"] if manifest["schema"] == 2 else []),
                         "-r", "requirements.txt"], cwd)
                    run([*args, *(["--no-deps"] if manifest["schema"] == 2 else []), "-e", "."], cwd)
                else:
                    command = "ci" if (cwd / "package-lock.json").exists() else "install"
                    run([executable("npm"), command, "--no-fund", "--no-audit"], cwd)
                settings(cwd, c["kind"])
    check(root, manifest, local, skip_runtime, progress)
    return progress


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


def check(root, manifest, local, skip_runtime=False, progress=None):
    """Run builds, selected tools and a live startup smoke check."""
    if not local and manifest["environment"] == "devcontainer":
        preflight(manifest, local, skip_runtime)
        devcontainer(root, manifest, "check", skip_runtime)
        return
    with progress.stage("Selected checks") if progress else nullcontext():
        preflight(manifest, local, skip_runtime)
        problems = locking_problems(root, manifest)
        if problems:
            raise RuntimeError("\n".join(problems))
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
        with progress.stage("Startup verification") if progress else nullcontext():
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


def available_ports(urls):
    """Reject occupied ports before a different service can pass readiness."""
    import socket

    for url, _ in urls:
        port = int(url.split(":")[2].split("/")[0])
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(
                    f"Port {port} is in use. Stop the other service, then retry."
                ) from exc


def dev(root, manifest, local):
    """Run in the foreground and own every process until shutdown."""
    if manifest["environment"] == "devcontainer" and not local:
        print("Open this project in VS Code → Dev Containers: Reopen in Container.\n"
              "Inside the container, run: python3 scripts/project.py dev --local", flush=True)
        return
    preflight(manifest, local)
    problems = locking_problems(root, manifest)
    if problems:
        raise RuntimeError("\n".join(problems))
    urls = endpoints(manifest)
    if not urls:
        if local:
            for c in manifest["components"]:
                cwd = root / c["path"]
                if c["kind"] == "typescript":
                    run([executable("npm"), "run", "build"], cwd)
                run(dev_command(cwd, c["kind"]), cwd)
        else:
            try:
                for c in manifest["components"]:
                    run(["docker", "compose", "run", "--rm", "--build", service_name(manifest, c)], root)
            finally:
                run(["docker", "compose", "down", "--remove-orphans"], root, timeout=90)
        return
    available_ports(urls)
    processes = []
    try:
        if local:
            processes = start(root, manifest)
        else:
            processes = [subprocess.Popen([executable("docker"), "compose", "up", "--build", "--abort-on-container-exit"],
                         cwd=root, start_new_session=os.name != "nt")]
        probe(urls, processes)
        for url, _ in urls:
            print(f"Ready: {url}", flush=True)
        print("Press Ctrl+C to stop.", flush=True)
        while True:
            if any(p.poll() is not None for p in processes):
                raise RuntimeError("A development server exited. Check its output, then retry envee dev.")
            time.sleep(0.2)
    finally:
        stop(processes)
        if not local:
            run(["docker", "compose", "down"], root, timeout=90)


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
    available_ports(urls)
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
    parser.add_argument("action", choices=["setup", "check", "dev", "lock"])
    parser.add_argument("--check", action="store_true", help="Validate locks without changes.")
    parser.add_argument("--local", action="store_true", help="Use local tools instead of Docker.")
    parser.add_argument("--skip-runtime", action="store_true", help="Skip live startup (useful in CI).")
    args = parser.parse_args()
    if args.check and args.action != "lock":
        parser.error("--check is only valid with the lock action")
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
        elif args.action == "lock":
            if args.check:
                if manifest["schema"] != 2:
                    raise RuntimeError("Locking requires a new Envee 0.4 project.")
                problems = locking_problems(root, manifest)
                if problems:
                    raise RuntimeError("\n".join(problems))
                print("Dependency locks are current.")
            else:
                preflight(manifest, local, skip_runtime=True)
                lock(root, manifest, local)
        else:
            dev(root, manifest, local)
    except KeyboardInterrupt:
        print("\nStopped.")
    except (RuntimeError, OSError, KeyError, ValueError) as exc:
        print(
            f"\n{args.action.capitalize()} failed: {exc}\nRetry python3 scripts/project.py {args.action}.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
