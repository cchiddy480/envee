# Homebrew release maintenance

Source: https://github.com/cchiddy480/envee

Tap: https://github.com/cchiddy480/homebrew-envee

Users install with `brew install cchiddy480/envee/envee`, then run
`envee init ./my-project`. The formula installs Python 3.14 and pins Envee's five
Python dependencies by source URL and SHA-256. Bash, Zsh and Fish completions are generated
at install time. Bash completion needs Bash 4.4 or newer; macOS's bundled Bash 3.2
does not support Click completion. Project runtimes remain optional prerequisites.

## Publishing the next version

1. Update the version in `pyproject.toml` and `src/envee_bootstrap/__init__.py`.
2. Run the existing checks and build the release with `python -m build`.
3. Commit the source and tag the matching version, for example `v0.2.1`.
4. Create the GitHub release and upload the source archive and wheel from `dist/`.
5. Update the tap formula's release URL and SHA-256 to that exact archive.
6. Test with `brew reinstall cchiddy480/envee/envee --build-from-source`
   and `brew test cchiddy480/envee/envee`, then push the tap change.

Never replace an archive for an already published version. Dependency upgrades require
updating their resource URLs and checksums and testing a fresh Homebrew install.
If only the formula changes, add or increase the formula's `revision` so Homebrew sees an update.

The tap workflow checks installation and the formula test on macOS. Linux Homebrew
support is not yet verified. No prebuilt Homebrew bottles are published; the small Python
application is installed from source using Homebrew's virtual environment helper.
