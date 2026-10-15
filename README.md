# Envee

**Empty folder → one command → a few choices → a verified development environment.**

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

Envee is the new name for Forge. Install the renamed package using the command above;
once `envee --version` works, the old `forge-bootstrap` package can be uninstalled.
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

The wizard starts with two setup routes:

- **Default:** choose your project and environment. Git, formatting/linting, tests,
  VS Code settings, environment examples, CodeGraph and Ponytail are included.
  CI and databases are off.
- **Advanced:** make the same project choices, then select each development tool
  and optionally SQLite for Python APIs.

Skip the route menu with `envee init ./my-project --default` or
`envee init ./my-project --advanced`. Explicit flags override either route's defaults;
`--yes` remains fully noninteractive.

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

Use `--no-codegraph` or `--no-ponytail` to opt out. Advanced setup asks about both.
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
```

Every wizard choice has a matching flag. `--yes` fills unanswered choices with defaults:
minimal Python, local, Git/lint/tests/editor/environment examples on, CI/database off.
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
piped. Default setup has three stages: project, environment and summary. Advanced setup
adds a tool-selection stage.
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
