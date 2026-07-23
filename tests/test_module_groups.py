"""Unit tests for module groups discovery and select_groups effective-set."""

from pathlib import Path

import pytest

from lola.exceptions import ValidationError
from lola.models import GROUPS_DIRNAME, Installation, Module

VALID_SKILL = """---
name: {name}
description: Test skill {name}
---
# {name}
"""

VALID_CMD = """---
description: Test command
---
Do the thing.
"""

VALID_AGENT = """---
description: Test agent
---
Be helpful.
"""


def _write_skill(root: Path, name: str) -> None:
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(VALID_SKILL.format(name=name))


def _write_command(root: Path, name: str) -> None:
    commands = root / "commands"
    commands.mkdir(parents=True, exist_ok=True)
    (commands / f"{name}.md").write_text(VALID_CMD)


def _write_agent(root: Path, name: str) -> None:
    agents = root / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / f"{name}.md").write_text(VALID_AGENT)


def _module_with_subdir(tmp_path: Path) -> tuple[Path, Path]:
    """module/ baseline + groups/ sibling under module root."""
    module_root = tmp_path / "mymod"
    content = module_root / "module"
    content.mkdir(parents=True)
    _write_skill(content, "base-skill")
    _write_command(content, "base-cmd")
    groups = module_root / GROUPS_DIRNAME
    frontend = groups / "frontend"
    frontend.mkdir(parents=True)
    _write_skill(frontend, "fe-skill")
    _write_command(frontend, "fe-cmd")
    api = groups / "api"
    api.mkdir(parents=True)
    _write_agent(api, "api-agent")
    return module_root, content


def _flat_module(tmp_path: Path) -> Path:
    """Flat content at root; groups/ still sibling under module root."""
    module_root = tmp_path / "flatmod"
    module_root.mkdir()
    _write_skill(module_root, "base-skill")
    groups = module_root / GROUPS_DIRNAME / "extra"
    groups.mkdir(parents=True)
    _write_skill(groups, "extra-skill")
    return module_root


class TestGroupDiscovery:
    def test_groups_only_module_loads(self, tmp_path):
        """Empty baseline is OK when groups/ has installable content."""
        root = tmp_path / "groups-only"
        (root / "module").mkdir(parents=True)
        g = root / GROUPS_DIRNAME / "pack"
        g.mkdir(parents=True)
        _write_skill(g, "only-skill")
        module = Module.from_path(root)
        assert module is not None
        assert module.skills == []
        assert module.list_groups() == ["pack"]
        selected = module.select_groups(["pack"])
        assert selected.skills == ["only-skill"]

    def test_list_groups_module_subdir(self, tmp_path):
        root, _ = _module_with_subdir(tmp_path)
        module = Module.from_path(root)
        assert module is not None
        assert module.has_groups()
        assert module.list_groups() == ["api", "frontend"]

    def test_list_groups_flat(self, tmp_path):
        root = _flat_module(tmp_path)
        module = Module.from_path(root)
        assert module is not None
        assert module.list_groups() == ["extra"]

    def test_skips_dot_dirs(self, tmp_path):
        root, _ = _module_with_subdir(tmp_path)
        (root / GROUPS_DIRNAME / ".hidden").mkdir()
        module = Module.from_path(root)
        assert module is not None
        assert ".hidden" not in module.list_groups()

    def test_no_groups(self, tmp_path):
        module_root = tmp_path / "plain"
        content = module_root / "module"
        content.mkdir(parents=True)
        _write_skill(content, "only")
        module = Module.from_path(module_root)
        assert module is not None
        assert not module.has_groups()
        assert module.list_groups() == []


class TestSelectGroups:
    def test_baseline_only_empty_selection(self, tmp_path):
        root, _ = _module_with_subdir(tmp_path)
        module = Module.from_path(root)
        assert module is not None
        filtered = module.select_groups([])
        assert filtered.skills == ["base-skill"]
        assert filtered.commands == ["base-cmd"]
        assert filtered.agents == []
        assert filtered.skill_relpaths is None

    def test_union_paths(self, tmp_path):
        root, _ = _module_with_subdir(tmp_path)
        module = Module.from_path(root)
        assert module is not None
        filtered = module.select_groups(["frontend", "api"])
        assert filtered.skills == ["base-skill", "fe-skill"]
        assert filtered.commands == ["base-cmd", "fe-cmd"]
        assert filtered.agents == ["api-agent"]
        assert filtered.mcps == []  # groups never contribute mcps

        skill_paths = {p.name: p for p in filtered.get_skill_paths()}
        assert skill_paths["base-skill"] == root / "module" / "skills" / "base-skill"
        assert (
            skill_paths["fe-skill"]
            == root / GROUPS_DIRNAME / "frontend" / "skills" / "fe-skill"
        )
        assert filtered.get_command_paths() == [
            root / "module" / "commands" / "base-cmd.md",
            root / GROUPS_DIRNAME / "frontend" / "commands" / "fe-cmd.md",
        ]
        assert filtered.get_agent_paths() == [
            root / GROUPS_DIRNAME / "api" / "agents" / "api-agent.md",
        ]

    def test_flat_union(self, tmp_path):
        root = _flat_module(tmp_path)
        module = Module.from_path(root)
        assert module is not None
        filtered = module.select_groups(["extra"])
        assert filtered.skills == ["base-skill", "extra-skill"]
        paths = filtered.get_skill_paths()
        assert paths[0] == root / "skills" / "base-skill"
        assert paths[1] == root / GROUPS_DIRNAME / "extra" / "skills" / "extra-skill"

    def test_unknown_group(self, tmp_path):
        root, _ = _module_with_subdir(tmp_path)
        module = Module.from_path(root)
        assert module is not None
        with pytest.raises(ValidationError) as exc:
            module.select_groups(["nope"])
        assert "Unknown group 'nope'" in str(exc.value)
        assert "frontend" in str(exc.value)

    def test_empty_group(self, tmp_path):
        root, _ = _module_with_subdir(tmp_path)
        (root / GROUPS_DIRNAME / "empty").mkdir()
        module = Module.from_path(root)
        assert module is not None
        with pytest.raises(ValidationError) as exc:
            module.select_groups(["empty"])
        assert "no installable artifacts" in str(exc.value)

    def test_forbidden_agents_md(self, tmp_path):
        root, _ = _module_with_subdir(tmp_path)
        bad = root / GROUPS_DIRNAME / "frontend"
        (bad / "AGENTS.md").write_text("# no")
        module = Module.from_path(root)
        assert module is not None
        with pytest.raises(ValidationError) as exc:
            module.select_groups(["frontend"])
        assert "Forbidden file" in str(exc.value)
        assert "AGENTS.md" in str(exc.value)

    def test_forbidden_mcps_json(self, tmp_path):
        root, _ = _module_with_subdir(tmp_path)
        bad = root / GROUPS_DIRNAME / "frontend"
        (bad / "mcps.json").write_text("{}")
        module = Module.from_path(root)
        assert module is not None
        with pytest.raises(ValidationError) as exc:
            module.select_groups(["frontend"])
        assert "mcps.json" in str(exc.value)

    def test_duplicate_skill_name(self, tmp_path):
        root, content = _module_with_subdir(tmp_path)
        # Same skill name in baseline and group
        _write_skill(root / GROUPS_DIRNAME / "frontend", "base-skill")
        module = Module.from_path(root)
        assert module is not None
        with pytest.raises(ValidationError) as exc:
            module.select_groups(["frontend"])
        msg = str(exc.value)
        assert "Duplicate skill 'base-skill'" in msg
        assert "baseline" in msg
        assert "group:frontend" in msg

    def test_path_escape_rejected(self, tmp_path):
        root, _ = _module_with_subdir(tmp_path)
        module = Module.from_path(root)
        assert module is not None
        with pytest.raises(ValidationError) as exc:
            module.select_groups(["../outside"])
        assert "Invalid group name" in str(exc.value)


class TestInstallationGroups:
    def test_to_dict_omits_none(self):
        inst = Installation("m", "cursor", "user", skills=["s"])
        assert "groups" not in inst.to_dict()

    def test_roundtrip(self):
        inst = Installation(
            "m", "cursor", "user", skills=["s"], groups=["frontend", "api"]
        )
        d = inst.to_dict()
        assert d["groups"] == ["frontend", "api"]
        loaded = Installation.from_dict(d)
        assert loaded.groups == ["frontend", "api"]

    def test_from_dict_missing(self):
        inst = Installation.from_dict(
            {"module": "m", "assistant": "cursor", "scope": "user"}
        )
        assert inst.groups is None
