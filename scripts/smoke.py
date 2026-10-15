"""Real installs, builds and startup. Run deliberately; needs network/runtimes."""

import argparse
from dataclasses import replace
import json
import os
import secrets
import hashlib
from pathlib import Path
import tempfile
import time

from envee_bootstrap.cli import write_files
from envee_bootstrap.model import Options, PRESETS
from envee_bootstrap import project_runner as runner
from envee_bootstrap.templates import render


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", choices=list(PRESETS))
    parser.add_argument("--docker", action="store_true")
    parser.add_argument("--devcontainer", action="store_true")
    parser.add_argument("--minimal-options", action="store_true")
    parser.add_argument("--node-bin", type=Path, help="Directory containing the Node 22 runtime to test.")
    parser.add_argument("--output", type=Path, default=Path(".envee/smoke-results.json"))
    args = parser.parse_args()
    if args.node_bin:
        os.environ["PATH"] = str(args.node_bin) + os.pathsep + os.environ["PATH"]
    results = []
    presets = [args.preset] if args.preset else list(PRESETS)
    environment = "devcontainer" if args.devcontainer else "docker" if args.docker else "local"
    for preset in presets:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="envee-smoke-") as temporary:
            root = Path(temporary) / "project"
            options = Options(
                name="smoke-" + secrets.token_hex(4),
                preset=preset,
                environment=environment,
                ci=True,
                database="sqlite" if preset.removeprefix("fullstack-") in {"flask", "fastapi"} else "none",
            )
            if args.minimal_options:
                options = replace(options, lint=False, tests=False, editor=False, env=False, ci=False)
            files = render(options)
            digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
            write_files(root, files)
            manifest = json.loads(files["envee.json"])
            print(f"\n=== {preset} / {environment} ===", flush=True)
            error = None
            try:
                if args.devcontainer:
                    image = "envee-devcontainer-test:" + ("azure" if options.backend == "azure" else "base")
                    runner.run(
                        ["docker", "build", "-t", image, str(root / ".devcontainer")], root, timeout=1800
                    )
                    runner.run(
                        [
                            "docker",
                            "run",
                            "--rm",
                            "--mount",
                            f"type=bind,source={root},target=/workspace",
                            "--workdir",
                            "/workspace",
                            image,
                            "python3",
                            "scripts/project.py",
                            "setup",
                            "--local",
                        ],
                        root,
                        timeout=1800,
                    )
                else:
                    runner.setup(root, manifest, not args.docker)
                    # Prove that retry preserves a user's source and settings.
                    source = (
                        root
                        / manifest["components"][0]["path"]
                        / (
                            "app/main.py"
                            if options.has_python
                            else "src/main.ts"
                            if preset == "web"
                            else "src/health.ts"
                            if options.backend == "azure"
                            else "src/index.ts"
                        )
                    )
                    before = source.read_bytes()
                    runner.setup(root, manifest, not args.docker)
                    assert source.read_bytes() == before, "Setup changed source on retry"
                results.append(
                    {
                        "preset": preset,
                        "environment": environment,
                        "minimal_options": args.minimal_options,
                        "passed": True,
                        "files_sha256": digest,
                        "seconds": round(time.monotonic() - started, 2),
                    }
                )
            except Exception as exc:
                error = str(exc)
                results.append(
                    {
                        "preset": preset,
                        "environment": environment,
                        "minimal_options": args.minimal_options,
                        "passed": False,
                        "error": error,
                    }
                )
                for log in (root / ".envee").glob("*-startup.log"):
                    print(log.name, log.read_text()[-8000:])
            finally:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(results, indent=2) + "\n")
            if error:
                raise RuntimeError(f"{preset} failed: {error}")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
