"""Install one committed universal lock unchanged on every CI operating system."""

from pathlib import Path
import re
import subprocess
import tempfile

from envee_bootstrap import project_runner as runner
from envee_bootstrap.cli import write_files
from envee_bootstrap.model import Options
from envee_bootstrap.templates import render


def main():
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/python-lock/requirements.lock"
    original = fixture.read_bytes()
    original_text = fixture.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="envee-portable-lock-") as temporary:
        root = Path(temporary) / "project"
        write_files(root, render(Options(name="portable-lock", preset="flask", git=False,
                                        lint=False, tests=False)))
        (root / "requirements.lock").write_bytes(original)
        manifest = runner.load(root)
        def unexpected_resolution(*args):
            raise AssertionError("Setup attempted to resolve an existing shared lock")
        original_resolver = runner.python_lock
        runner.python_lock = unexpected_resolution
        runner.setup(root, manifest, True)
        assert (root / "requirements.lock").read_bytes() == original
        corrupt = root / "corrupt.lock"
        corrupt.write_text(re.sub(r"sha256:[a-f0-9]{64}", "sha256:" + "0" * 64,
                                  original_text), encoding="utf-8", newline="\n")
        result = subprocess.run([runner.python(root), "-m", "pip", "install", "--ignore-installed",
                                 "--no-cache-dir", "--require-hashes", "-r", str(corrupt)],
                                cwd=root, text=True, capture_output=True, timeout=180)
        assert result.returncode != 0 and "do not match the hashes" in (result.stdout + result.stderr).lower(), (
            result.stdout + result.stderr)
        assert (root / "requirements.lock").read_bytes() == original
        runner.python_lock = original_resolver
        runner.python_lock(root)
        before = re.findall(r"^[a-z][^\n]*==[^\n]*", original_text, re.MULTILINE)
        after = re.findall(r"^[a-z][^\n]*==[^\n]*", (root / "requirements.lock").read_text(), re.MULTILINE)
        assert before == after, "Refresh upgraded compatible pins"
        assert not runner.locking_problems(root, manifest)
    print("Shared universal lock installed unchanged; incorrect hashes were rejected.")


if __name__ == "__main__":
    main()
