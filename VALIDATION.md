# Envee 0.4.0 validation

Verified on 21 October 2026.

- 173 contracts pass on macOS, Linux and Windows with Python 3.12 and 3.14, including strict recipe validation and precedence, sharing,
  optional-action failures, lock preservation, malformed dependency files, stale inputs,
  interrupted setup records and existing daily-development behavior.
- All ten local starters pass real installation, selected checks, startup verification
  and repeated setup on macOS Apple Silicon and hosted Linux with the new lock policy.
- Real Docker Flask and full-stack FastAPI projects pass installation, builds, selected
  checks and live readiness, including the frontend-to-backend proxy. A generated
  Dev Container passes actual Python setup and startup inside its image.
- Fresh launcher and wheel installation pass, including the interactive wizard,
  shared recipe files, source-only creation and packaged Ponytail assets.
- Fresh teammate setup preserves the original Python lock without invoking the resolver,
  and preserves source and local settings. A corrupted lock fails pip hash verification.
- A real 0.3-generated project retains schema 1, its original files and dependency workflow;
  the Forge manifest path and original standalone runner also work without migration.

Release-specific evidence: [validation/envee-0.4.0.json](validation/envee-0.4.0.json).
The [hosted contract and shared-lock checks](https://github.com/cchiddy480/envee/actions/runs/39587687258)
pass across the six OS/Python combinations, including real installation, incorrect-hash rejection
and explicit lock refresh retaining compatible pins. The [Linux ten-starter matrix](https://github.com/cchiddy480/envee/actions/runs/39587001828)
also passes.

Homebrew source installation, formula style and formula tests pass on Apple Silicon.
A real terminal session using Homebrew Python verifies application creation, the recipe-save
prompt and arrow-key selection of the saved setup; previewing that recipe creates no project.

Full interactive Windows sessions and Linux Homebrew installation are not manually covered.
Dependency locks do not freeze OS packages, image digests or the full build toolchain.

## Previous release: Envee 0.3.0

Verified on 16 October 2026.

- 140 contract tests pass on macOS, Linux and Windows with Python 3.12 and 3.14, covering context-aware launch, Git-boundary discovery,
  invalid manifests, remembered AI preferences, per-project overrides, previews, safe retries,
  aggregate diagnostics, optional-tool warning exits and foreground lifecycle handling.
- All ten local starters pass fresh installation, builds, selected checks, real startup
  verification and repeated setup on macOS Apple Silicon and hosted Linux.
- Real local and Docker Flask development report health URLs only after readiness,
  stop on Ctrl+C, release their ports and leave no managed Docker services running.
- Dev Container host commands give the VS Code reopening workflow. Container setup
  and checks run in a real generated image.
- Fresh source launcher and wheel installs pass. Fresh teammate setup from a subdirectory
  preserves application files and local settings. Docker and Dev Container CLI creation
  and checks pass. Packaged Ponytail assets are present when selected.
- The real terminal review menu supports arrow keys, Create / Customise / Cancel,
  and cancellation without creating a project.

Homebrew source installation from the public release URL, formula style and formula tests
pass on Apple Silicon. A [hosted fresh tap installation](https://github.com/cchiddy480/homebrew-envee/actions/runs/38879232337)
also passes.
The globally installed 0.3 CLI creates a verified application using Homebrew Python,
and runs daily commands from subdirectories without saving automation preferences.

Release evidence is in [validation/envee-0.3.0.json](validation/envee-0.3.0.json).
The [release CI run](https://github.com/cchiddy480/envee/actions/runs/38878801094) passed
contracts on macOS, Linux and Windows with Python 3.12 and 3.14, plus all ten local
starters on Linux.

Full runtime management, additional stacks and arbitrary-repository adoption remain
outside this release. Full interactive Windows sessions and Linux Homebrew installation
are not covered by the macOS acceptance run.

## Previous release: Envee 0.2.0

Verified on 15 October 2026.

- 112 passing contract tests, including the new name, new manifest, old Forge manifest
  compatibility, both setup tracks, agent-tool safety and generated-file exclusions.
- All ten presets passed fresh local installation, build, selected lint/tests, live
  startup and a repeated setup under the Envee name on macOS Apple Silicon.
- Fresh source launcher installation, the real advanced wizard, safe retries, Git
  exclusions and installation of the renamed wheel all passed.
- The renamed wheel contains the `envee` entry point, renamed modules and Ponytail assets.
- CodeGraph download verification and project MCP handshake passed during development.

Release-specific evidence is in [validation/envee-0.2.0.json](validation/envee-0.2.0.json).
Docker/Dev Container matrices and browser checks below are historical baseline evidence;
they were not repeated for this rename. Windows remains subject to hosted CI verification.

## Historical baseline: Forge 0.1.0

The following records describe the original Forge release verified on 14 October 2026.
They are retained as baseline evidence, rather than presented as reruns of Envee 0.2.0.

Verified on 14 October 2026. Detailed results are in [validation/results.json](validation/results.json).

## Verified release scope

Homebrew packaging passed an actual source install on Apple Silicon, `brew test`,
the globally installed `forge --version` and `forge doctor`, and fresh Python project
installation and live verification using Homebrew's Python 3.14.8 runtime.
The formula contains checksummed resources and generates shell completions.
Linux Homebrew installation remains unverified.

Ten presets: web, Flask, FastAPI, Azure Functions, each of the three full-stack
combinations, Python CLI, minimal Python and minimal TypeScript.

All ten passed real installation and startup checks in each environment:

| Environment | Verification |
| --- | --- |
| Local | Fresh dependency installation, build/compile, selected lint and tests, live startup, repeat setup |
| Docker | Lockfile resolution in Node containers, image builds, checks inside containers, live HTTP checks, repeat setup |
| Dev Container | Actual generated image build and post-create setup inside Linux, selected checks and live startup |

API checks request `/api/health`. Full-stack checks additionally request that endpoint
through the frontend proxy. CLI/minimal starters execute successfully; Python CLI
checks also exercise the installed console command.

## Safety and user flow

83 passing contract tests cover all template/environment combinations, generated syntax,
optional tooling, name validation, empty-directory enforcement, hidden-file protection,
symlink/path escapes, malformed manifests, failed-install recovery, credential-free settings
preservation, occupied ports, process cleanup, timeout handling and selection of an already installed Node 22 runtime.

The guided CLI update additionally passed real terminal arrow-key selection, cancellation,
a fresh Python project installation and live check, quiet command logging and failure-log
recovery. The ten-preset container matrices above predate this presentation update;
the subprocess logging change has been regression-tested, but those full matrices were not rerun.

Fresh-install acceptance checks passed for:

- Installing the launcher into its own isolated environment on first use.
- Running the real interactive wizard and creating a verified CLI project.
- Initialising Git on `main` and excluding virtual environments and local settings.
- Retrying setup without changing application source.
- Running the generated installed CLI command with arguments.
- Creating a verified web project while Node 26 is the shell default, using the installed
  Node 22 privately and leaving the parent shell unchanged.
- Installing the packaged Forge wheel into a clean environment and generating projects.
- Actual `forge init` and `forge check` commands in Docker and Dev Container modes.

## Browser and dependency checks

The generated full-stack screen passed browser checks at 320, 768, 1024 and 1440 pixels,
in both light and dark themes: no horizontal overflow, visible keyboard focus and a
44-pixel button target. Default, loading, connected, error and retry states were exercised.
Button contrast measured 4.60:1. No browser exceptions were observed.

The representative full-stack starter reported zero npm audit findings. A scoped
`js-yaml` override removes the old parser dependency tree in Jest's NYC configuration
loader; parsing an actual YAML configuration was checked for compatibility.
This is a dated dependency check, not a security guarantee.

## Practical limits

- Verified on macOS Apple Silicon and Linux ARM64 containers, using Python 3.12/3.14
  and Node 22. Windows helpers and a cross-platform CI workflow are provided; Windows
  and the hosted GitHub workflow have not been executed in this session.
- Docker images are development environments and need rebuilding after source changes.
  The web starter uses Quasar's Vite plugin for browser applications, rather than its
  mobile/SSR tooling.
- Setup time depends on network and caches. Local matrix timings include installation,
  verification and a second setup; cold Docker image downloads take longer.
- Azure HTTP starters run without cloud credentials. Storage triggers, authentication,
  private registries, certificates and production deployment require project-specific setup.
- `dev-env` was used as a read-only reference and was not modified.

## Repeat the checks

Run the three full matrices sequentially because their live checks use the same ports:

```sh
python scripts/smoke.py
python scripts/smoke.py --docker
python scripts/smoke.py --devcontainer
python scripts/smoke.py --minimal-options
python scripts/acceptance.py --containers
```

The smoke runner accepts `--node-bin /path/to/node22/bin` if another Node version is
the shell default. Each matrix uses fresh temporary projects; source and application
servers are cleaned up afterwards. Docker build caches remain available for later use.
