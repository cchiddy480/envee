# Envee

**Get a project ready, start it reliably, and return to it effortlessly.**

Envee creates new projects with the languages and conventions already used in `dev-env`.
It never imports application code, credentials or licensed assets from that workspace.

## Install

On macOS with Homebrew:

```sh
brew install cchiddy480/envee/envee
envee init ./my-project
```

Homebrew installs Python and Envee's dependencies in an isolated environment. You can
run `envee` from any folder without activating a virtual environment. The package and command are both named `envee`.
Homebrew may ask you to trust this formula from the personal tap.

Update with `brew update && brew upgrade envee`. Uninstall with
`brew uninstall envee`; your generated projects remain in place.
Node 22, Docker and Azure Functions Core Tools are separate prerequisites for presets
that need them; `envee doctor --preset web` checks before you create a web project.

For release maintenance, see [HOMEBREW.md](HOMEBREW.md).

### Upgrading from Forge

Envee is the new name for Forge. If you installed Forge through the previous Homebrew
tap, migrate first so Homebrew does not report a conflict between the two tap names:

```sh
brew uninstall cchiddy480/forge/forge-bootstrap
brew untap cchiddy480/forge
brew install cchiddy480/envee/envee
```

Uninstalling the old CLI leaves your generated projects in place.
Existing projects work with `envee setup PATH` and `envee check PATH`: Envee reads
their original `forge.json` without regenerating application files. Their existing
`.forge/` logs remain in place. New projects use `envee.json` and `.envee/`.

### Install from source

For the one-command flow, run `bash /path/to/envee/envee` from an empty directory.
The launcher creates its own isolated environment on first use and opens the wizard.
On Windows, use `/path/to/envee/envee.ps1` in PowerShell.


Needs Python 3.12 or newer. From this directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
```

Then use `.venv/bin/envee`, or activate the environment to use `envee` directly:

```sh
source .venv/bin/activate
mkdir my-project
cd my-project
envee init
```

Windows: use `py -3.12 -m venv .venv`, `.venv\Scripts\python -m pip install .`
and `.venv\Scripts\Activate.ps1`. Generated projects use `python scripts/project.py` on Windows.
The Windows helper is a preview; this release was validated on macOS and Linux containers.

## Launch choices

Type `envee` anywhere. Empty folders open project creation. Inside an Envee or legacy
Forge project, a short menu shows its name, stack and execution mode with Start,
Check, Diagnose and Retry setup actions. Other folders offer creation in a child folder.
Discovery works from subdirectories and stops at a Git repository boundary.

`envee init [directory]` goes straight to project choices, infers a valid project name
from the destination, then shows **Create / Customise / Cancel**. Local execution is
the default. Git, formatting, tests, editor settings and environment examples are on;
CI and databases are off. Customise or `--advanced` exposes execution mode, tools and
SQLite for Python APIs, preserving your earlier answers. `--default` remains supported.
Explicit flags override saved preferences. `--yes` is completely noninteractive.
After verified interactive creation, Envee offers **Start now**.

### Agent tools

CodeGraph indexes the project on the host and creates project-local Codex MCP settings.
Codex loads these settings when you trust and open the project. Other agents can use
CodeGraph's own installer separately.
Envee reuses an installed `codegraph`; otherwise it downloads the official standalone
1.4.1 bundle for your platform and verifies its pinned SHA-256 before using it. That
bundle includes its own Node runtime and is cached under `~/.cache/envee/codegraph/`.
Your application and Docker images do not gain a CodeGraph dependency. CodeGraph's
own telemetry settings apply; see its [telemetry documentation](https://github.com/colbymchenry/codegraph/blob/main/TELEMETRY.md).

Ponytail's MIT-licensed core skill (5.2.0) is included under `.agents/skills/ponytail/`,
with local `AGENTS.md` instructions. Its plugin lifecycle hooks and additional slash
commands are separate; an existing Ponytail plugin remains available.

Both AI tools start unselected. First interactive creation explains each tool and
asks once, then remembers the choices for future projects. `envee config` revisits
them; `envee config --codegraph --no-ponytail` also works without prompts.
Preferences live in `$XDG_CONFIG_HOME/envee/config.json` (default
`~/.config/envee/config.json`), or `%APPDATA%/envee/config.json` on Windows.
`--codegraph`, `--no-codegraph`, `--ponytail` and `--no-ponytail` override them for one
project. Advanced changes are per-project; existing manifests retain their tools.
Noninteractive creation without preferences leaves both off. Help, doctor, previews
and noninteractive setup never save preferences. Cancelled creation saves nothing.
Installation adds local tool files to the existing global Git ignore file, respecting
`core.excludesfile` and existing rules. Generated projects also ignore them directly,
so agent instructions, skills, MCP settings and graph databases stay out of commits.
`--no-install` and `--dry-run` do not download tools or edit global Git settings.
`envee setup` retries indexing without replacing your application code or local skill.
The generated `scripts/project.py` manages application dependencies; host-side agent
setup uses `envee setup`.

| Project | Presets |
| --- | --- |
| Web application | Vue 3, Quasar, Vite, Pinia, Vue Router, TypeScript |
| API/backend | Python Flask; Python FastAPI; TypeScript Azure Functions v4 |
| Full-stack application | Vue/Quasar plus any of the three backends, with `/api` proxy |
| CLI tool | Python, Click and Rich; installed command matching your project name |
| Minimal project | Python or TypeScript |

Choose local, Docker or VS Code Dev Container. Git, lint/format, tests, VS Code settings,
environment examples and GitHub Actions are selectable. SQLite is available for Python backends.
No framework, machine-wide runtime or cloud resources are installed automatically.

## Repeatable commands

```sh
envee presets
envee doctor --preset fullstack-flask
envee init ./my-app --name my-app --preset fullstack-flask --yes --ci --database sqlite
envee init ./preview --preset web --yes --dry-run
envee init ./source-only --preset cli --yes --no-install
envee setup ./my-app
envee check ./my-app
envee doctor ./my-app
envee dev ./my-app
envee config
```

Every wizard choice has a matching flag. `--yes` fills unanswered choices with defaults:
minimal Python, local, Git/lint/tests/editor/environment examples on, CI/database off.
AI extras use saved preferences, or remain off without them.
`--dry-run` writes nothing. `--no-install` creates source only and never claims it is verified.
The target must be empty, including hidden files; there is intentionally no overwrite flag.

## What “ready” means

Envee checks prerequisites before creating files, installs dependencies, builds the project,
runs selected lint and tests, then starts the generated app and verifies its HTTP endpoints.
Full-stack checks include the frontend-to-backend proxy. CLI/minimal projects are executed.
Startup smoke checks stop their processes afterwards. Occupied ports cause a clear failure.

Python uses per-component `.venv` environments and pip. Node projects use the Node 22.x line
(22.13+) and npm. The first install creates `package-lock.json`; subsequent installs use `npm ci`.
If another Node version is active, Envee selects an installed Node 22 from nvm for its own
processes. It does not change your shell or download a runtime silently.
Docker mode resolves lockfiles inside Node containers, builds images, runs checks inside them,
and verifies live startup. Dev Container mode also supplies an image with Python and Node;
VS Code performs setup inside that container when you open it.

`envee dev` runs local or Docker development in the foreground, reports verified service
URLs and cleans up managed processes on Ctrl+C or failure. CLI/minimal projects run
once. Dev Containers keep the VS Code reopening workflow with direct host guidance.
`envee doctor` reports prerequisite problems together, with remedies; it never installs
runtimes or changes an existing project's execution mode.

If application verification passes but an optional AI tool fails, Envee reports
**Application ready—with warnings**, names the failure and gives an `envee setup` retry.
Exit codes: **0** success, **1** required failure, **2** usage error, **3** optional-tool
failure after application checks. Skipped startup is always labelled unverified.

If setup fails, source remains in place. Fix the reported prerequisite or download issue,
then run `envee setup PATH`. Each generated project includes a standalone standard-library
runner, so teammates do not need Envee installed to set up, check or run it:

```sh
python3 scripts/project.py setup
python3 scripts/project.py check
python3 scripts/project.py dev
```

CI uses `--local --skip-runtime` and explicitly reports that live startup was skipped.
For local development, API ports are 8000 (Python) or 7071 (Azure), and frontend is 5173.
Docker binds exposed ports to localhost. Docker images need rebuilding after source changes;
local development supports the frontend's normal hot reload.

## Settings and boundaries

Environment examples contain no secrets. `.env` is not automatically loaded: export values in
your shell or use your chosen environment loader. Azure HTTP starters create credential-free
`local.settings.json`; storage triggers need separate storage configuration. No Azure login,
Auth0, Crowdin, private registry, deployment, certificate or licence setup runs implicitly.

Presets contain development starters, not production deployment designs. C++, Java, PHP,
Flutter and arbitrary package-manager selection are outside this release.

## Development and testing

The wizard uses arrow keys and Enter in a terminal, with numbered choices when input is
piped. The recommended flow asks for a project type and necessary backend or language,
then shows a review screen. Customisation keeps the previous answers.
During setup, a spinner shows the current task; full installation output is saved to
`.envee/setup.log`. Failures show the last diagnostic lines and a retry command.
`envee check` saves its output to `.envee/check.log`. Completion tells you which folder
to enter and how to start your project.

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/python -m ruff check src tests scripts
.venv/bin/python scripts/smoke.py
.venv/bin/python scripts/acceptance.py --containers
```

Run the local and Docker smoke matrices sequentially; they use the same development ports.
The smoke matrix installs every preset into fresh temporary directories, performs real builds,
lint, tests and live startup, and checks setup retries. It requires internet access and the
listed runtimes. Container validation is separately selectable with `--docker`.

See `VALIDATION.md` for the actual verification performed on this release.
