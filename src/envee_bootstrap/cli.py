"""The interactive entry point and its equivalent automation flags."""

import json
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
import re
import shlex
import sys

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.text import Text

from . import __version__
from .model import Options, PRESETS
from . import project_runner as runner
from . import agent_tools
from .templates import render

console = Console(highlight=False)


def choose(question, choices, default=1):
    if console.is_terminal and not console.is_dumb_terminal and sys.stdin.isatty():
        index = default - 1
        def menu():
            lines = Text()
            lines.append(question + "\n\n", style="bold")
            for i, (_, label) in enumerate(choices):
                lines.append(f"  {'❯' if i == index else ' '} {label}\n", style="bold cyan" if i == index else "")
            lines.append("\n↑ / ↓ to move · Enter to select · Ctrl+C to cancel", style="dim")
            return lines
        with Live(menu(), console=console, auto_refresh=False) as live:
            while True:
                key = click.getchar()
                if key in {"\r", "\n"}:
                    break
                if key in {"\x1b[A", "\xe0H", "\x00H"}:
                    index = (index - 1) % len(choices)
                elif key in {"\x1b[B", "\xe0P", "\x00P"}:
                    index = (index + 1) % len(choices)
                elif key.isdigit() and 1 <= int(key) <= len(choices):
                    index = int(key) - 1
                live.update(menu(), refresh=True)
        console.print()
        return choices[index][0]
    console.print(question, style="bold", markup=False)
    for i, (_, label) in enumerate(choices, 1):
        console.print(f"  {i}. {label}", markup=False)
    index = click.prompt("Choose", default=default, type=click.IntRange(1, len(choices)))
    return choices[index - 1][0]


@contextmanager
def progress(root, action):
    """Keep terminal output readable while preserving full command diagnostics."""
    logs = runner.log_directory(root)
    logs.mkdir(exist_ok=True)
    path = logs / f"{action}.log"
    original_run, original_output = runner.run, runner.OUTPUT_STREAM
    terminal = Console(file=console.file, highlight=False)
    with path.open("w", encoding="utf-8") as stream:
        with terminal.status(f"{action.capitalize()} · preparing your environment", spinner="dots") as status:
            def run(args, cwd, timeout=900):
                command = " ".join(map(str, args))
                label = (
                    "Indexing project with CodeGraph" if "codegraph" in command and
                    any(action in args for action in ["init", "sync"]) else
                    "Creating Python environment" if "venv" in args else
                    "Installing dependencies" if "install" in args or "ci" in args else
                    "Building project" if "build" in args else
                    "Running tests" if "test" in args or "pytest" in args else
                    "Checking code" if "lint" in args or "pylint" in args or "black" in args else
                    "Verifying environment"
                )
                status.update(f"{label} · {Path(cwd).name}")
                stream.write(command + "\n")
                stream.flush()
                original_run(args, cwd, timeout)
                status.update("Verifying startup and finishing checks")
            runner.run, runner.OUTPUT_STREAM = run, stream
            try:
                with redirect_stdout(stream):
                    yield
            except BaseException:
                stream.flush()
                console.print(f"\nSetup stopped. Details: {path}", style="yellow", markup=False)
                tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
                console.print("\n".join(tail), markup=False)
                raise
            finally:
                runner.run, runner.OUTPUT_STREAM = original_run, original_output
    console.print(f"✓ {action.capitalize()} completed", style="green")
    console.print(f"Details saved to {path}", style="dim", markup=False)


def wizard_preset():
    kind = choose(
        "What are we building?",
        [
            ("web", "Web application"),
            ("api", "API / backend"),
            ("fullstack", "Full-stack application"),
            ("cli", "CLI tool"),
            ("minimal", "Minimal project"),
        ],
    )
    if kind in {"api", "fullstack"}:
        backend = choose(
            "Choose your backend",
            [
                ("flask", "Python · Flask"),
                ("fastapi", "Python · FastAPI"),
                ("azure", "TypeScript · Azure Functions"),
            ],
        )
        return "fullstack-" + backend if kind == "fullstack" else backend
    if kind == "minimal":
        return choose("Choose your language", [("python", "Python"), ("typescript", "TypeScript")])
    return kind


@click.group()
@click.version_option(__version__)
def main():
    """ENVEE — your development environment, ready."""


@main.command("presets")
def list_presets():
    """List the bundled project starters."""
    for key, label in PRESETS.items():
        console.print(f"{key:20} {label}", markup=False)


@main.command("init")
@click.argument("directory", type=click.Path(path_type=Path), default=".")
@click.option("--name", help="Project name: lowercase words separated by hyphens.")
@click.option("--preset", type=click.Choice(list(PRESETS)))
@click.option("--environment", type=click.Choice(["local", "docker", "devcontainer"]))
@click.option("--advanced/--default", "advanced", default=None,
              help="Choose individual tools, or use the recommended development tools.")
@click.option("--git/--no-git", default=None)
@click.option("--lint/--no-lint", default=None)
@click.option("--tests/--no-tests", default=None)
@click.option("--ci/--no-ci", default=None)
@click.option("--editor/--no-editor", default=None)
@click.option("--env/--no-env", default=None)
@click.option("--codegraph/--no-codegraph", default=None, help="Install and initialise CodeGraph on the host.")
@click.option("--ponytail/--no-ponytail", default=None, help="Include the Ponytail core coding skill.")
@click.option("--database", type=click.Choice(["none", "sqlite"]))
@click.option("--install/--no-install", default=True, help="Install and verify by default.")
@click.option("--yes", is_flag=True, help="Use defaults for any unanswered choices.")
@click.option("--dry-run", is_flag=True, help="Preview files and choices without writing or installing.")
def init(
    directory, name, preset, environment, advanced, git, lint, tests, ci, editor, env,
    codegraph, ponytail, database, install, yes, dry_run
):
    """Turn an empty DIRECTORY into a ready-to-code project."""
    target = directory.absolute()
    if target.is_symlink():
        raise click.ClickException("Use a real directory, not a symbolic link.")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise click.ClickException("The destination must be empty. Envee will not overwrite existing files.")
    interactive = not yes
    console.print(Panel("[bold cyan]ENVEE[/bold cyan]\nYour development environment, ready.", border_style="cyan"))
    if advanced is None:
        advanced = interactive and choose(
            "How would you like to set up?",
            [("default", "Default setup — recommended tools, fewer questions"),
             ("advanced", "Advanced setup — choose individual tools and database")],
        ) == "advanced"
    stages = 4 if advanced else 3
    if interactive:
        console.print(f"1 / {stages} · Choose your project", style="bold cyan")
    default_name = re.sub(r"[^a-z0-9]+", "-", target.name.lower()).strip("-")
    if not default_name or not default_name[0].isalpha():
        default_name = "my-project"
    if name is None:
        name = click.prompt("Project name", default=default_name) if interactive else default_name
    if preset is None:
        preset = wizard_preset() if interactive else "python"
    if environment is None:
        if interactive:
            console.print(f"\n2 / {stages} · Choose where it runs", style="bold cyan")
        environment = (
            choose(
                "Where should it run?",
                [("local", "Local — use tools on this computer"), ("docker", "Docker — run in containers"),
                 ("devcontainer", "Dev Container — develop inside VS Code")],
            )
            if interactive
            else "local"
        )
    choices = {
        "git": (git, True, "Initialise Git?"),
        "lint": (lint, True, "Add a formatter and linter?"),
        "tests": (tests, True, "Add tests?"),
        "ci": (ci, False, "Add GitHub Actions?"),
        "editor": (editor, True, "Add VS Code configuration?"),
        "env": (env, True, "Add environment-file examples?"),
        "codegraph": (codegraph, True, "Add CodeGraph indexing and Codex integration?"),
        "ponytail": (ponytail, True, "Add the Ponytail core coding skill?"),
    }
    values = {}
    if interactive and advanced:
        console.print("\n3 / 4 · Choose your tools", style="bold cyan")
        console.print("Press Enter to accept each recommended default. [Y/n] means yes; [y/N] means no.",
                      style="dim", markup=False)
    for key, (value, default, question) in choices.items():
        values[key] = (
            value
            if value is not None
            else click.confirm(question, default=default)
            if interactive and advanced
            else default
        )
    if database is None:
        database = (
            "sqlite"
            if interactive
            and advanced
            and preset.removeprefix("fullstack-") in {"flask", "fastapi"}
            and click.confirm("Add a local SQLite database?", default=False)
            else "none"
        )
    options = Options(name=name, preset=preset, environment=environment, database=database, **values)
    try:
        options.validate()
        files = render(options)
        manifest = json.loads(files["envee.json"])
        table = Table(show_header=False, box=None)
        for key, value in [
            ("Setup", "Advanced" if advanced else "Default"),
            ("Project", name),
            ("Preset", PRESETS[preset]),
            ("Environment", environment),
            ("Destination", str(target)),
            ("Files", str(len(files))),
        ]:
            table.add_row(key, value)
        labels = {"git": "Git", "lint": "Formatter / linter", "tests": "Tests",
                  "ci": "GitHub Actions", "editor": "VS Code", "env": "Environment examples",
                  "codegraph": "CodeGraph", "ponytail": "Ponytail"}
        enabled = [labels[key] for key, enabled in values.items() if enabled]
        table.add_row("Tools", ", ".join(enabled) or "None")
        table.add_row("Database", database)
        console.print(Panel(table, title=f"{stages} / {stages} · Your project", border_style="cyan"))
        if dry_run:
            for path in sorted(files):
                console.print(f"  {path}", markup=False)
            console.print("Preview only. No files created.")
            return
        if install:
            runner.preflight(manifest, environment == "local")
        if options.git:
            runner.executable("git")
        write_files(target, files)
        console.print("✓ Project files created", style="green")
        if options.git:
            runner.run(["git", "init", "--initial-branch=main"], target)
        if install:
            with progress(target, "setup"):
                runner.setup(target, manifest, environment == "local")
                agent_tools.setup(target, manifest)
            console.print("\n✓ YOUR ENVIRONMENT IS READY", style="bold green")
        else:
            console.print(
                "\n✓ Project created. Dependencies and startup have not been verified.", style="yellow"
            )
        console.print(f"\nOpen: {target}", markup=False)
        console.print(f"First: cd {shlex.quote(str(target))}", markup=False)
        if not install:
            console.print("Next: envee setup ." if options.codegraph or options.ponytail
                          else "Next: python3 scripts/project.py setup")
        elif environment == "devcontainer":
            console.print("Next: open in VS Code → Dev Containers: Reopen in Container")
        elif environment == "docker":
            console.print("Start: docker compose up")
        else:
            console.print("Start: python3 scripts/project.py dev")
    except (ValueError, RuntimeError, OSError) as exc:
        suffix = (
            f"\nYour files are preserved. Retry with: envee setup {shlex.quote(str(target))}"
            if (target / "envee.json").exists()
            else "\nNo setup was completed."
        )
        raise click.ClickException(str(exc) + suffix) from exc


def write_files(target, files):
    """Create files exclusively; recheck destination after the interactive prompts."""
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError("The destination changed while choosing options; it must still be empty.")
    target.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = target / name
        if not path.resolve().is_relative_to(target.resolve()):
            raise ValueError("Template path escapes the project directory.")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)


def existing_project(directory, action, local, skip_runtime):
    root = directory.resolve()
    try:
        manifest = runner.load(root)
        use_local = (
            local
            or manifest["environment"] == "local"
            or (manifest["environment"] == "devcontainer" and Path("/.dockerenv").exists())
        )
        with progress(root, action):
            if action == "setup":
                runner.setup(root, manifest, use_local, skip_runtime)
                agent_tools.setup(root, manifest)
            else:
                runner.check(root, manifest, use_local, skip_runtime)
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@click.argument("directory", type=click.Path(path_type=Path), default=".")
@click.option("--local", is_flag=True)
@click.option("--skip-runtime", is_flag=True, help="Skip live startup, for CI.")
def setup(directory, local, skip_runtime):
    """Retry installation and verification without regenerating source."""
    existing_project(directory, "setup", local, skip_runtime)


@main.command()
@click.argument("directory", type=click.Path(path_type=Path), default=".")
@click.option("--local", is_flag=True)
@click.option("--skip-runtime", is_flag=True, help="Skip live startup, for CI.")
def check(directory, local, skip_runtime):
    """Run builds, selected checks and live startup verification."""
    existing_project(directory, "check", local, skip_runtime)


@main.command()
@click.option("--preset", type=click.Choice(list(PRESETS)), default="python")
@click.option("--environment", type=click.Choice(["local", "docker", "devcontainer"]), default="local")
def doctor(preset, environment):
    """Check prerequisites without installing or creating files."""
    options = Options(name="doctor", preset=preset, environment=environment)
    try:
        manifest = json.loads(render(options)["envee.json"])
        runner.preflight(manifest, environment == "local")
        console.print(f"✓ Prerequisites available for {preset} / {environment}", style="green")
        console.print(f"Python {sys.version.split()[0]}")
    except (RuntimeError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


if __name__ == "__main__":
    main()
