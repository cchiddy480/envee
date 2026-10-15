# Envee 0.2.0 validation

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
