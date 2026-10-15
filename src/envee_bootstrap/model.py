"""The supported choices and validation boundary."""

from dataclasses import dataclass
import re

PRESETS = {
    "web": "Web application · Vue / Quasar / Vite",
    "flask": "API / backend · Python / Flask",
    "fastapi": "API / backend · Python / FastAPI",
    "azure": "API / backend · TypeScript / Azure Functions",
    "fullstack-flask": "Full stack · Vue + Flask",
    "fullstack-fastapi": "Full stack · Vue + FastAPI",
    "fullstack-azure": "Full stack · Vue + Azure Functions",
    "cli": "CLI tool · Python / Click / Rich",
    "python": "Minimal · Python",
    "typescript": "Minimal · TypeScript",
}


@dataclass(frozen=True)
class Options:
    name: str
    preset: str
    environment: str = "local"
    git: bool = True
    lint: bool = True
    tests: bool = True
    ci: bool = False
    editor: bool = True
    env: bool = True
    codegraph: bool = True
    ponytail: bool = True
    database: str = "none"

    def validate(self):
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", self.name) or len(self.name) > 64:
            raise ValueError(
                "Use a name of 1–64 lowercase letters, numbers and single hyphens, starting with a letter."
            )
        if self.name in {"con", "prn", "aux", "nul"} or re.fullmatch(r"(?:com|lpt)[1-9]", self.name):
            raise ValueError("This project name is reserved on Windows.")
        if self.preset not in PRESETS:
            raise ValueError("Unknown preset.")
        if self.environment not in {"local", "docker", "devcontainer"}:
            raise ValueError("Unknown environment.")
        if self.database not in {"none", "sqlite"}:
            raise ValueError("Unknown database.")
        if self.database == "sqlite" and self.backend not in {"flask", "fastapi"}:
            raise ValueError("SQLite is supported for Flask and FastAPI backends.")

    @property
    def backend(self):
        return self.preset.removeprefix("fullstack-")

    @property
    def fullstack(self):
        return self.preset.startswith("fullstack-")

    @property
    def has_web(self):
        return self.preset == "web" or self.fullstack

    @property
    def has_python(self):
        return self.backend in {"flask", "fastapi", "cli", "python"}

    @property
    def has_node(self):
        return self.has_web or self.backend in {"azure", "typescript"}
