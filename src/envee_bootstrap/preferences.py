"""Remember optional AI choices without changing project manifests."""

import json
import os
from pathlib import Path
import tempfile


def path():
    base = os.environ.get("APPDATA") if os.name == "nt" else os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "envee/config.json"


def load():
    target = path()
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or any(
            key not in {"codegraph", "ponytail"} or type(value) is not bool
            for key, value in data.items()
        ):
            raise ValueError("expected CodeGraph and Ponytail boolean preferences")
        return data
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid preferences in {target}: {exc}") from exc


def save(values):
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(values, stream, indent=2)
            stream.write("\n")
        temporary.replace(target)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
