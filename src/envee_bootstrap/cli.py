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
from . import agent_tools, preferences, recipes
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
    original_stage = runner.STAGE_CALLBACK
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
            runner.STAGE_CALLBACK = lambda name: status.update(f"{action.capitalize()} · {name}")
            try:
                with redirect_stdout(stream):
                    yield
            except BaseException:
                stream.flush()
                console.print(f"\n{action.capitalize()} stopped. Details: {path}", style="yellow", markup=False)
                tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
                console.print("\n".join(tail), markup=False)
                raise
            finally:
                runner.run, runner.OUTPUT_STREAM = original_run, original_output
                runner.STAGE_CALLBACK = original_stage
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
            *[("recipe:" + name, "Saved setup · " + name) for name in recipes.names()],
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


@click.group(invoke_without_command=True)
@click.version_option(__version__)
@click.pass_context
def main(ctx):
    """ENVEE — your development environment, ready."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        root = runner.discover(Path.cwd())
        if root:
            manifest = runner.load(root)
            console.print(Panel(f"{manifest['name']}\n{PRESETS[manifest['preset']]}\n"
                                f"Runs: {manifest['environment']}", title="ENVEE"), markup=False)
            show_previous_setup(root)
            action = choose("What next?", [("dev", "Start development"), ("check", "Check project"),
                            ("doctor", "Diagnose prerequisites"), ("setup", "Retry setup"),
                            ("exit", "Exit")])
            if action == "doctor":
                ctx.invoke(doctor, directory=root)
            elif action != "exit":
                existing_project(root, action, False, False)
        elif not any(Path.cwd().iterdir()):
            ctx.invoke(init)
        elif choose("This folder contains files. Create a project in a new child folder?",
                    [("create", "Create in a new folder"), ("exit", "Exit")]) == "create":
            child = click.prompt("New folder name")
            destination = Path(child)
            if destination.is_absolute() or len(destination.parts) != 1 or child in {".", ".."}:
                raise ValueError("Choose a single child folder name.")
            ctx.invoke(init, directory=Path.cwd() / child)
    except click.exceptions.Exit:
        raise
    except (RuntimeError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("presets")
def list_presets():
    """List the bundled project starters."""
    for key, label in PRESETS.items():
        console.print(f"{key:20} {label}", markup=False)


@main.command("init")
@click.argument("directory", type=click.Path(path_type=Path), default=".")
@click.option("--name", help="Project name: lowercase words separated by hyphens.")
@click.option("--preset", type=click.Choice(list(PRESETS)))
@click.option("--recipe", "recipe_reference", help="Use a personal recipe name or local JSON file.")
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
    codegraph, ponytail, database, install, yes, dry_run, recipe_reference
):
    """Turn an empty DIRECTORY into a ready-to-code project."""
    target = directory.absolute()
    if target.is_symlink():
        raise click.ClickException("Use a real directory, not a symbolic link.")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise click.ClickException("The destination must be empty. Envee will not overwrite existing files.")
    interactive = not yes
    console.print(Panel("[bold cyan]ENVEE[/bold cyan]\nGet ready to build.", border_style="cyan"))
    advanced = bool(advanced)
    default_name = re.sub(r"[^a-z0-9]+", "-", target.name.lower()).strip("-")
    if name is None:
        try:
            Options(name=default_name, preset="python").validate()
            name = default_name
        except ValueError:
            name = click.prompt("Project name", default="my-project") if interactive else "my-project"
    recipe_values = {}
    selected_recipe = None
    try:
        if recipe_reference:
            selected_recipe = recipes.load(recipe_reference)
        if preset is None and selected_recipe is None:
            preset = wizard_preset() if interactive else "python"
            if preset.startswith("recipe:"):
                selected_recipe = recipes.load(preset.removeprefix("recipe:"))
                preset = None
        if selected_recipe:
            recipe_values = selected_recipe["options"].copy()
        preset = preset or recipe_values.get("preset", "python")
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--recipe") from exc
    environment = environment or recipe_values.get("environment", "local")
    database = database or recipe_values.get("database", "none")
    try:
        saved = preferences.load()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    choices = {
        "git": (git, True, "Initialise Git?"),
        "lint": (lint, True, "Add a formatter and linter?"),
        "tests": (tests, True, "Add tests?"),
        "ci": (ci, False, "Add GitHub Actions?"),
        "editor": (editor, True, "Add VS Code configuration?"),
        "env": (env, True, "Add environment-file examples?"),
        "codegraph": (codegraph, saved.get("codegraph", False), "Add CodeGraph?"),
        "ponytail": (ponytail, saved.get("ponytail", False), "Add Ponytail?"),
    }
    values = {key: recipe_values.get(key, default) if value is None else value
              for key, (value, default, _) in choices.items()}
    remembered = dict(saved)
    if interactive:
        for key in ("codegraph", "ponytail"):
            if key not in saved:
                explain_ai(key)
                explicit = choices[key][0]
                if explicit is None and not advanced:
                    values[key] = click.confirm(choices[key][2], default=False)
                remembered[key] = values[key]

    def customise():
        nonlocal environment, database, name
        name = click.prompt("Project name", default=name)
        environment = choose("Where should it run?", [
            ("local", "Local — tools on this computer"), ("docker", "Docker — containers"),
            ("devcontainer", "Dev Container — VS Code")],
            default=["local", "docker", "devcontainer"].index(environment) + 1)
        for key, (_, _, question) in choices.items():
            values[key] = click.confirm(question, default=values[key])
        if preset.removeprefix("fullstack-") in {"flask", "fastapi"}:
            database = "sqlite" if click.confirm("Add a local SQLite database?",
                                                default=database == "sqlite") else "none"
    if interactive and advanced:
        customise()
        for key in ("codegraph", "ponytail"):
            if key not in saved:
                remembered[key] = values[key]
    options = Options(name=name, preset=preset, environment=environment, database=database, **values)
    try:
        options.validate()
        files = render(options)
        manifest = json.loads(files["envee.json"])
        while True:
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
            if options.has_python:
                table.add_row("Python locks", f"uv {runner.UV_VERSION} · temporary resolver download during setup")
            console.print(Panel(table, title="Your project", border_style="cyan"))
            if dry_run or not interactive:
                break
            action = choose("Ready to create?", [("create", "Create"), ("customise", "Customise"),
                                                ("cancel", "Cancel")])
            if action == "cancel":
                console.print("Cancelled. No files created.")
                return
            if action == "create":
                break
            customise()
            options = Options(name=name, preset=preset, environment=environment, database=database, **values)
            options.validate()
            files = render(options)
            manifest = json.loads(files["envee.json"])
        if dry_run:
            for path in sorted(files):
                console.print(f"  {path}", markup=False)
            console.print("Preview only. No files created.")
            return
        if install:
            try:
                runner.preflight(manifest, environment == "local")
            except RuntimeError as exc:
                if not (interactive and environment == "local" and
                        not runner.prerequisite_problems(manifest, False)):
                    raise
                console.print(str(exc), style="yellow", markup=False)
                console.print("Docker is available for this new project.", style="cyan")
                if not click.confirm("Use Docker for this new project?", default=False):
                    raise
                environment = "docker"
                options = Options(name=name, preset=preset, environment=environment, database=database, **values)
                files = render(options)
                manifest = json.loads(files["envee.json"])
                runner.preflight(manifest, False)
        if options.git:
            runner.executable("git")
        write_files(target, files)
        if interactive and remembered != saved:
            preferences.save(remembered)
        console.print("✓ Project files created", style="green")
        if options.git:
            runner.run(["git", "init", "--initial-branch=main"], target)
        warnings = []
        if install:
            with progress(target, "setup"):
                tracker = runner.setup(target, manifest, environment == "local")
                warnings = setup_optional(target, manifest, tracker)
            report_ready(target, warnings)
        else:
            console.print(
                "\n✓ Project created. Dependencies and startup have not been verified.", style="yellow"
            )
        console.print(f"\nOpen: {target}", markup=False)
        console.print(f"First: cd {shlex.quote(str(target))}", markup=False)
        if not install:
            console.print("Next: envee setup .")
        elif environment == "devcontainer":
            console.print("Next: open in VS Code → Dev Containers: Reopen in Container")
        else:
            console.print("Start: envee dev")
        if install and interactive and recipes.choices(options) != recipe_values:
            if click.confirm("Save this setup for next time?", default=False):
                while True:
                    recipe_name = click.prompt("Recipe name", default=preset)
                    try:
                        path = recipes.save(recipe_name, recipes.choices(options))
                        console.print(f"Recipe saved: {path}", markup=False)
                        break
                    except ValueError as exc:
                        console.print(str(exc), markup=False, style="yellow")
                        if not click.confirm("Choose another recipe name?", default=True):
                            break
                    except OSError as exc:
                        warning = (f"Recipe was not saved: {exc}. Retry with envee recipe save NAME "
                                   + shlex.quote(str(target)))
                        warnings.append(warning)
                        report_ready(target, [warning])
                        break
        if install and interactive and click.confirm("Start now?", default=False):
            existing_project(target, "dev", False, False)
        if warnings:
            raise click.exceptions.Exit(3)
    except click.exceptions.Exit:
        raise
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
    try:
        root = runner.discover(directory)
        if root is None:
            raise RuntimeError("No Envee project found. Use envee init in an empty folder.")
        manifest = runner.load(root)
        use_local = (
            local
            or manifest["environment"] == "local"
            or (manifest["environment"] == "devcontainer" and Path("/.dockerenv").exists())
        )
        if action == "dev":
            try:
                runner.dev(root, manifest, use_local)
            except KeyboardInterrupt:
                console.print("\nStopped.")
            return
        warnings = []
        if manifest["schema"] == 2 and action in {"setup", "lock"} and any(
            c["kind"] in runner.PYTHON_KINDS and (action == "lock" or
            not (root / c["path"] / "requirements.lock").exists()) for c in manifest["components"]
        ):
            console.print(f"Python locking downloads uv {runner.UV_VERSION} into a temporary tool environment. "
                          "Python runtimes are not downloaded.", markup=False)
        with progress(root, action):
            if action == "setup":
                tracker = runner.setup(root, manifest, use_local, skip_runtime)
                warnings = setup_optional(root, manifest, tracker)
            elif action == "lock":
                runner.preflight(manifest, use_local, skip_runtime=True)
                runner.lock(root, manifest, use_local)
            else:
                runner.check(root, manifest, use_local, skip_runtime)
        if action == "setup":
            report_ready(root, warnings, verified=not skip_runtime)
            if warnings:
                raise click.exceptions.Exit(3)
    except click.exceptions.Exit:
        raise
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        raise click.ClickException(str(exc) + f"\nRetry: envee {action} {shlex.quote(str(directory))}") from exc


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
@click.argument("directory", type=click.Path(path_type=Path), default=".")
@click.option("--local", is_flag=True)
def dev(directory, local):
    """Start development, report readiness and stop cleanly with Ctrl+C."""
    existing_project(directory, "dev", local, False)


@main.command()
@click.argument("directory", type=click.Path(path_type=Path), default=".")
@click.option("--preset", type=click.Choice(list(PRESETS)), default=None)
@click.option("--environment", type=click.Choice(["local", "docker", "devcontainer"]), default=None)
def doctor(directory, preset, environment):
    """Diagnose prerequisites without installing or creating files."""
    try:
        root = runner.discover(directory)
        manifest = runner.load(root) if root else json.loads(render(Options(
            name="doctor", preset=preset or "python", environment=environment or "local"))["envee.json"])
        if preset is not None:
            manifest = json.loads(render(Options(name="doctor", preset=preset,
                                  environment=environment or manifest["environment"]))["envee.json"])
        if environment is not None:
            manifest["environment"] = environment
        use_local = manifest["environment"] == "local" or (
            manifest["environment"] == "devcontainer" and Path("/.dockerenv").exists())
        problems = runner.prerequisite_problems(manifest, use_local)
        if root:
            show_previous_setup(root)
            problems += runner.locking_problems(root, manifest)
        if problems:
            raise RuntimeError("Prerequisite problems:\n- " + "\n- ".join(problems) +
                               "\nAfter fixing these, retry: envee doctor " + shlex.quote(str(root or directory)))
        console.print(f"✓ Prerequisites available for {manifest['preset']} / {manifest['environment']}",
                      style="green")
        if root:
            console.print(f"Next: envee setup {shlex.quote(str(root))}", markup=False)
    except click.exceptions.Exit:
        raise
    except (RuntimeError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


def show_previous_setup(root):
    lines = runner.previous_setup(root)
    if lines:
        console.print("Previous setup:", style="yellow")
        for line in lines:
            console.print("  " + line, markup=False)
        console.print(f"Retry: envee setup {shlex.quote(str(root))}", markup=False)


def setup_optional(root, manifest, tracker):
    if not (manifest.get("codegraph") or manifest.get("ponytail")) or not tracker:
        return agent_tools.setup(root, manifest) or []
    with tracker.stage("Optional AI tools"):
        warnings = agent_tools.setup(root, manifest) or []
    if warnings:
        tracker.state["stages"][-1]["status"] = "warning"
        tracker.write()
    return warnings


@main.command()
@click.argument("directory", type=click.Path(path_type=Path), default=".")
@click.option("--local", is_flag=True)
@click.option("--check", "check_only", is_flag=True, help="Validate locks without writing or downloading.")
def lock(directory, local, check_only):
    """Refresh project dependency locks after editing dependency declarations."""
    if not check_only:
        existing_project(directory, "lock", local, False)
        return
    try:
        root = runner.discover(directory)
        if root is None:
            raise ValueError("No Envee project found.")
        manifest = runner.load(root)
        if manifest["schema"] != 2:
            raise ValueError("Locking requires a new Envee 0.4 project; this project's setup is unchanged.")
        problems = runner.locking_problems(root, manifest)
        if problems:
            raise ValueError("\n".join(problems))
        console.print("✓ Dependency locks are current", style="green")
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.group()
def recipe():
    """Save and share reusable setup choices."""


@recipe.command("list")
def recipe_list():
    """List personal recipes."""
    names = recipes.names()
    for name in names:
        console.print(name, markup=False)
    if not names:
        console.print("No saved recipes yet. Use envee recipe save NAME inside a project.")


@recipe.command("show")
@click.argument("reference")
def recipe_show(reference):
    """Show a personal recipe or local recipe file."""
    try:
        console.print(json.dumps(recipes.load(reference), indent=2), markup=False)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


@recipe.command("save")
@click.argument("name")
@click.argument("directory", type=click.Path(path_type=Path), default=".")
@click.option("--output", type=click.Path(path_type=Path), help="Write a shareable file instead of a personal recipe.")
@click.option("--force", is_flag=True, help="Replace an existing recipe explicitly.")
def recipe_save(name, directory, output, force):
    """Save supported choices from an Envee or legacy Forge project."""
    try:
        root = runner.discover(directory)
        if root is None:
            raise ValueError("No Envee project found.")
        manifest = runner.load(root)
        defaults = Options(name="recipe", preset="python")
        values = {key: manifest.get(key, getattr(defaults, key)) for key in recipes.KEYS}
        path = recipes.save(name, values, output, force)
        console.print(f"Recipe saved: {path}", markup=False)
    except (ValueError, RuntimeError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc


@recipe.command("remove")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Remove without prompting.")
def recipe_remove(name, yes):
    """Remove a personal recipe; project files are untouched."""
    try:
        path = recipes.personal(name)
        if not path.is_file():
            raise ValueError(f"No personal recipe named {name}.")
        if yes or click.confirm(f"Remove personal recipe {name}?", default=False):
            path.unlink()
            console.print(f"Removed recipe: {name}", markup=False)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc


def explain_ai(key):
    if key == "codegraph":
        console.print("CodeGraph creates a local code index for coding assistants. Setup may download "
                      "CodeGraph with its own runtime; it creates .codegraph/ and local Codex MCP settings.",
                      markup=False)
    else:
        console.print("Ponytail adds bundled coding guidelines that favour small, complete solutions "
                      "in .agents/skills/ponytail/ and AGENTS.md. Plugin hooks are separate.", markup=False)
    console.print("Envee adds local AI files to the project and global Git-ignore rules during setup.",
                  markup=False)


def report_ready(root, warnings, verified=True):
    if verified:
        console.print("Application ready—with warnings" if warnings else "✓ YOUR ENVIRONMENT IS READY",
                      style="yellow" if warnings else "bold green")
    else:
        console.print("Dependencies checked; application startup has not been verified.", style="yellow")
    for warning in warnings:
        console.print(f"Warning: {warning}", markup=False, style="yellow")
    if warnings:
        console.print(f"Retry: envee setup {shlex.quote(str(root))}", markup=False)


@main.command()
@click.option("--codegraph/--no-codegraph", default=None)
@click.option("--ponytail/--no-ponytail", default=None)
def config(codegraph, ponytail):
    """Edit remembered optional AI preferences for future projects."""
    try:
        values = preferences.load()
        interactive = codegraph is None and ponytail is None
        for key, explicit in [("codegraph", codegraph), ("ponytail", ponytail)]:
            if explicit is not None:
                values[key] = explicit
            elif interactive:
                explain_ai(key)
                values[key] = click.confirm(f"Enable {key.title()} for future projects?",
                                            default=values.get(key, False))
        preferences.save(values)
        console.print(f"Preferences saved: {preferences.path()}", markup=False)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc


if __name__ == "__main__":
    main()
