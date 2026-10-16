"""Exercise first-use installation, the real wizard and a packaged wheel."""

import json
import os
import argparse
import secrets
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def command(args, cwd, env=None, input_text=None):
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=900,
    )
    if result.returncode:
        raise RuntimeError(result.stdout[-12000:])
    return result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--containers",
        action="store_true",
        help="Also exercise CLI init/check in Docker and Dev Container modes.",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if os.name == "nt":
        raise RuntimeError(
            "The shell-launcher acceptance test runs on macOS/Linux; use the CI contract suite on Windows."
        )
    with tempfile.TemporaryDirectory(prefix="envee-acceptance-") as temporary:
        temporary = Path(temporary)
        checkout = temporary / "envee"
        checkout.mkdir()
        for name in ["pyproject.toml", "README.md", "LICENSE", "envee", "envee.ps1", "MANIFEST.in", "HOMEBREW.md"]:
            shutil.copy2(root / name, checkout / name)
        shutil.copytree(
            root / "src/envee_bootstrap",
            checkout / "src/envee_bootstrap",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        os.environ["XDG_CONFIG_HOME"] = str(temporary / "config")
        environment = os.environ.copy()
        environment["ENVEE_PYTHON"] = sys.executable
        assert "0.3.0" in command(["bash", str(checkout / "envee"), "--version"], checkout, environment)
        project = temporary / "new-project"
        project.mkdir()
        output = command(
            ["bash", str(checkout / "envee")],
            project,
            environment,
            "4\nn\nn\n2\nacceptance-tool\n\n\n\n\ny\n\n\n\n\n1\nn\n",
        )
        assert "YOUR ENVIRONMENT IS READY" in output
        manifest = json.loads((project / "envee.json").read_text())
        assert manifest["preset"] == "cli" and manifest["ci"]
        assert command(["git", "symbolic-ref", "--short", "HEAD"], project).strip() == "main"
        (project / ".env").write_text("PLACEHOLDER=true\n")
        (project / "local.settings.json").write_text("{}\n")
        status = command(["git", "status", "--porcelain", "--untracked-files=all"], project)
        assert "local.settings.json" not in status and " .env\n" not in status and ".venv/" not in status
        source = (project / "app/main.py").read_bytes()
        command([str(checkout / ".venv/bin/envee"), "setup", str(project)], project)
        assert (project / "app/main.py").read_bytes() == source
        teammate = temporary / "teammate"
        shutil.copytree(project, teammate, ignore=shutil.ignore_patterns(".venv", ".git", ".envee", "__pycache__"))
        command([str(checkout / ".venv/bin/envee"), "setup"], teammate / "app")
        assert (teammate / "app/main.py").read_bytes() == source
        assert (teammate / ".env").read_text() == "PLACEHOLDER=true\n"
        assert (teammate / "local.settings.json").read_text() == "{}\n"
        assert "Hello, team!" in command(
            [str(project / ".venv/bin/acceptance-tool"), "--name", "team"], project
        )
        active_node = command(["node", "--version"], temporary).strip()
        web_project = temporary / "web-project"
        output = command([str(checkout / ".venv/bin/envee"), "init", str(web_project), "--name", "acceptance-web",
                          "--preset", "web", "--yes", "--no-git"], temporary)
        assert "YOUR ENVIRONMENT IS READY" in output
        assert command(["node", "--version"], temporary).strip() == active_node
        wheel = root / "dist/envee-0.3.0-py3-none-any.whl"
        wheel_env = temporary / "wheel-env"
        command([sys.executable, "-m", "venv", str(wheel_env)], temporary)
        command([str(wheel_env / "bin/python"), "-m", "pip", "install", str(wheel)], temporary)
        preview = temporary / "wheel-preview"
        command(
            [
                str(wheel_env / "bin/envee"),
                "init",
                str(preview),
                "--yes",
                "--preset",
                "fullstack-azure",
                "--dry-run",
            ],
            temporary,
        )
        assert not preview.exists()
        # Generation from the installed wheel proves packaged template resources are present.
        command(
            [
                str(wheel_env / "bin/envee"),
                "init",
                str(preview),
                "--yes",
                "--preset",
                "fullstack-fastapi",
                "--ponytail",
                "--no-install",
                "--no-git",
            ],
            temporary,
        )
        assert (preview / "scripts/project.py").is_file()
        assert (preview / ".agents/skills/ponytail/SKILL.md").is_file()
        result = {
            "passed": True,
            "fresh_launcher_install": True,
            "real_interactive_wizard": True,
            "verified_cli_project": True,
            "git_and_secret_exclusions": True,
            "retry_preserves_source": True,
            "fresh_teammate_setup_preserves_source_and_settings": True,
            "installed_project_command": True,
            "web_init_ready_with_existing_runtime": True,
            "original_node_version": active_node,
            "parent_shell_runtime_unchanged": True,
            "wheel_install_and_generation": True,
        }
        if args.containers:
            for mode in ["docker", "devcontainer"]:
                target = temporary / mode
                name = "acceptance-" + secrets.token_hex(4)
                output = command(
                    [
                        str(checkout / ".venv/bin/envee"),
                        "init",
                        str(target),
                        "--name",
                        name,
                        "--preset",
                        "python",
                        "--environment",
                        mode,
                        "--yes",
                        "--no-git",
                    ],
                    temporary,
                )
                assert "YOUR ENVIRONMENT IS READY" in output
                command([str(checkout / ".venv/bin/envee"), "check", str(target)], temporary)
                result[mode + "_cli_init_and_check"] = True
        (root / ".envee").mkdir(exist_ok=True)
        (root / ".envee/acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
