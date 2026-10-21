"""Portable setup choices, with no project files or executable hooks."""

from dataclasses import asdict
import json
from pathlib import Path

from . import __version__, preferences
from .model import Options

KEYS = ("preset", "environment", "git", "lint", "tests", "ci", "editor", "env", "database")


def directory():
    return preferences.path().parent / "recipes"


def validate(data):
    if not isinstance(data, dict) or set(data) != {"schema", "name", "envee_version", "options"}:
        raise ValueError("Invalid recipe: expected schema, name, envee_version and options.")
    if type(data["schema"]) is not int or data["schema"] != 1:
        raise ValueError("Unsupported recipe schema; update Envee or use a supported recipe.")
    if not isinstance(data["envee_version"], str) or not isinstance(data["options"], dict):
        raise ValueError("Invalid recipe metadata or options.")
    if set(data["options"]) != set(KEYS):
        raise ValueError("Invalid recipe options: only supported setup choices are allowed.")
    values = data["options"]
    if any(type(values[key]) is not bool for key in KEYS if key not in {"preset", "environment", "database"}):
        raise ValueError("Recipe tool choices must be true or false.")
    if any(not isinstance(values[key], str) for key in ("preset", "environment", "database")):
        raise ValueError("Recipe stack, environment and database must be strings.")
    if not isinstance(data["name"], str):
        raise ValueError("Recipe name must be a string.")
    Options(name=data["name"], **values).validate()
    return data


def personal(name):
    Options(name=name, preset="python").validate()
    return directory() / (name + ".json")


def load(reference):
    value = str(reference)
    if "://" in value:
        raise ValueError("Use a local recipe file; remote recipe fetching is not supported.")
    path = Path(value).expanduser() if any(c in value for c in "/\\") or value.endswith(".json") else personal(value)
    try:
        return validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read recipe {path}: {exc}") from exc


def names():
    return sorted(path.stem for path in directory().glob("*.json") if path.is_file())


def save(name, values, output=None, force=False):
    data = validate({"schema": 1, "name": name, "envee_version": __version__,
                     "options": {key: values[key] for key in KEYS}})
    target = Path(output).expanduser() if output is not None else personal(name)
    if target.is_symlink():
        raise ValueError("Use a real recipe file, not a symbolic link.")
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2) + "\n"
    if force:
        # Replacement is atomic so an interrupted save preserves the old recipe.
        from .project_runner import atomic_write
        atomic_write(target, content)
    else:
        try:
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        except FileExistsError as exc:
            raise ValueError(f"Recipe already exists: {target}. Choose another name or use --force.") from exc
    return target


def choices(options):
    return {key: value for key, value in asdict(options).items() if key in KEYS}
