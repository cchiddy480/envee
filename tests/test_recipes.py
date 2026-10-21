"""Recipe files are portable choices; their contents never become executable hooks."""

import json

from click.testing import CliRunner
import pytest

from envee_bootstrap import agent_tools, preferences, project_runner as runner, recipes
from envee_bootstrap.cli import main, write_files
from envee_bootstrap.model import Options
from envee_bootstrap.templates import render


def project(path, **kwargs):
    options = Options(name="private-project", preset="fastapi", git=False, **kwargs)
    write_files(path, render(options))
    (path / ".env").write_text("SECRET=not-a-recipe\n")
    return options


def test_save_shared_and_personal_then_remove(tmp_path):
    root = tmp_path / "project"
    options = project(root, database="sqlite", ci=True, codegraph=True, ponytail=True)
    result = CliRunner().invoke(main, ["recipe", "save", "team-api", str(root / "app")])
    assert result.exit_code == 0, result.output
    data = recipes.load("team-api")
    assert data["options"] == recipes.choices(options)
    assert set(data["options"]) == set(recipes.KEYS)
    assert all(value not in recipes.personal("team-api").read_text() for value in
               ["SECRET", "not-a-recipe", "private-project", "codegraph", "ponytail", str(root)])
    shared = tmp_path / "team.json"
    result = CliRunner().invoke(main, ["recipe", "save", "team-api", str(root), "--output", str(shared)])
    assert result.exit_code == 0, result.output
    assert recipes.load(shared) == data
    assert "team-api" in CliRunner().invoke(main, ["recipe", "list"]).output
    assert '"sqlite"' in CliRunner().invoke(main, ["recipe", "show", str(shared)]).output
    result = CliRunner().invoke(main, ["recipe", "remove", "team-api", "--yes"])
    assert result.exit_code == 0 and not recipes.personal("team-api").exists()
    assert shared.exists() and (root / "app/main.py").exists()


def test_recipe_flags_override_choices_and_ai_stays_personal(tmp_path):
    options = Options(name="recipe", preset="fastapi", database="sqlite", git=False, ci=True)
    shared = recipes.save("team", recipes.choices(options), output=tmp_path / "shared.json")
    preferences.save({"codegraph": False, "ponytail": True})
    target = tmp_path / "new-project"
    result = CliRunner().invoke(main, ["init", str(target), "--recipe", str(shared), "--yes",
                                      "--no-install", "--no-ci", "--environment", "docker",
                                      "--codegraph", "--no-ponytail"])
    assert result.exit_code == 0, result.output
    manifest = runner.load(target)
    assert manifest["name"] == "new-project" and manifest["preset"] == "fastapi"
    assert manifest["database"] == "sqlite" and manifest["environment"] == "docker"
    assert manifest["codegraph"] and not manifest["ponytail"] and not manifest["ci"]
    assert preferences.load() == {"codegraph": False, "ponytail": True}
    assert recipes.load(shared)["options"]["ci"]


@pytest.mark.parametrize("change", [
    lambda d: d.update(schema=99), lambda d: d.update(schema=True),
    lambda d: d.update(name="../escape"), lambda d: d["options"].update(ponytail=True),
    lambda d: d["options"].update(post_create="run command"),
    lambda d: d["options"].update(tests="false"), lambda d: d["options"].update(preset=[]),
    lambda d: d["options"].update(database="sqlite", preset="web"),
])
def test_invalid_recipe_fails_before_writes(tmp_path, change, monkeypatch):
    data = {"schema": 1, "name": "team", "envee_version": "0.4.0",
            "options": recipes.choices(Options(name="team", preset="python"))}
    change(data)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(runner, "preflight", lambda *a: pytest.fail("installation"))
    target = tmp_path / "new"
    result = CliRunner().invoke(main, ["init", str(target), "--recipe", str(path), "--yes"])
    assert result.exit_code == 2, result.output
    assert not target.exists() and not preferences.path().exists()


def test_overwrite_explicit_and_remote_names_rejected(tmp_path):
    values = recipes.choices(Options(name="team", preset="python"))
    path = recipes.save("team", values)
    original = path.read_bytes()
    values["tests"] = False
    with pytest.raises(ValueError, match="already exists"):
        recipes.save("team", values)
    assert path.read_bytes() == original
    recipes.save("team", values, force=True)
    assert not recipes.load("team")["options"]["tests"]
    with pytest.raises(ValueError, match="remote"):
        recipes.load("https://example.test/recipe.json")
    with pytest.raises(ValueError):
        recipes.personal("../team")


def test_menu_uses_recipe_without_extra_route_question(tmp_path):
    recipes.save("team-api", recipes.choices(Options(name="team", preset="fastapi", git=False)))
    preferences.save({"codegraph": False, "ponytail": False})
    result = CliRunner().invoke(main, ["init", str(tmp_path / "new"), "--no-install"], input="6\n1\n")
    assert result.exit_code == 0, result.output
    assert runner.load(tmp_path / "new")["preset"] == "fastapi"
    assert "Choose your backend" not in result.output and "Save this setup" not in result.output


def test_post_create_offer_and_unchanged_recipe_skip(tmp_path, monkeypatch):
    preferences.save({"codegraph": False, "ponytail": False})
    monkeypatch.setattr(runner, "setup", lambda *a: None)
    monkeypatch.setattr(runner, "preflight", lambda *a: None)
    monkeypatch.setattr(agent_tools, "setup", lambda *a: [])
    result = CliRunner().invoke(main, ["init", str(tmp_path / "first"), "--preset", "python", "--no-git"],
                                input="1\ny\nmy-setup\nn\n")
    assert result.exit_code == 0, result.output
    assert recipes.load("my-setup")["options"]["preset"] == "python"
    assert result.output.index("Save this setup") < result.output.index("Start now?")
    result = CliRunner().invoke(main, ["init", str(tmp_path / "second"), "--recipe", "my-setup"], input="1\nn\n")
    assert result.exit_code == 0, result.output
    assert "Save this setup" not in result.output


def test_preview_and_source_only_never_save_recipe(tmp_path):
    for flag in ("--dry-run", "--no-install"):
        result = CliRunner().invoke(main, ["init", str(tmp_path / flag[2:]), "--preset", "python",
                                          "--no-git", flag], input="n\nn\n1\n")
        assert result.exit_code == 0, result.output
        assert "Save this setup" not in result.output
        assert not recipes.names()


def test_failed_optional_recipe_save_keeps_application_ready(tmp_path, monkeypatch):
    preferences.save({"codegraph": False, "ponytail": False})
    monkeypatch.setattr(runner, "setup", lambda *a: None)
    monkeypatch.setattr(runner, "preflight", lambda *a: None)
    monkeypatch.setattr(agent_tools, "setup", lambda *a: [])
    monkeypatch.setattr(recipes, "save", lambda *a: (_ for _ in ()).throw(OSError("permission denied")))
    result = CliRunner().invoke(main, ["init", str(tmp_path / "new"), "--preset", "python", "--no-git"],
                                input="1\ny\nteam\nn\n")
    assert result.exit_code == 3, result.output
    assert "Application ready—with warnings" in result.output and "envee recipe save" in result.output
    assert (tmp_path / "new/app/main.py").exists()


def test_recipe_can_be_saved_from_legacy_manifest(tmp_path):
    root = tmp_path / "legacy"
    project(root)
    manifest = runner.load(root)
    manifest["schema"] = 1
    (root / "envee.json").unlink()
    (root / "forge.json").write_text(json.dumps(manifest))
    result = CliRunner().invoke(main, ["recipe", "save", "legacy", str(root)])
    assert result.exit_code == 0, result.output
    assert recipes.load("legacy")["options"]["preset"] == "fastapi"
