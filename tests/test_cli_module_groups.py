"""CLI integration tests for module groups (install / update / uninstall)."""

import shutil
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from lola.cli.install import install_cmd, uninstall_cmd, update_cmd
from lola.models import Installation, InstallationRegistry


def _module_with_groups(root: Path) -> None:
    """Baseline + groups/frontend (skill) + groups/api (command)."""
    content = root / "module"
    content.mkdir(parents=True)
    skill = content / "skills" / "base-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: base-skill\ndescription: base\n---\n# base\n"
    )
    frontend = root / "groups" / "frontend"
    frontend.mkdir(parents=True)
    fe_skill = frontend / "skills" / "fe-skill"
    fe_skill.mkdir(parents=True)
    (fe_skill / "SKILL.md").write_text(
        "---\nname: fe-skill\ndescription: fe\n---\n# fe\n"
    )
    api = root / "groups" / "api"
    api.mkdir(parents=True)
    (api / "commands").mkdir()
    (api / "commands" / "api-cmd.md").write_text(
        "---\ndescription: api\n---\nDo api.\n"
    )


def _setup_grouped(tmp_path: Path, name: str = "grouped") -> tuple[Path, Path, Path]:
    """Register a grouped module; return (modules_dir, installed_file, module_path)."""
    modules_dir = tmp_path / ".lola" / "modules"
    mod = modules_dir / name
    mod.mkdir(parents=True)
    _module_with_groups(mod)
    installed_file = tmp_path / ".lola" / "installed.yml"
    return modules_dir, installed_file, mod


@contextmanager
def _install_env(modules_dir: Path, installed_file: Path, *, interactive: bool = False):
    """Patch install CLI paths; yield a shared InstallationRegistry."""
    registry = InstallationRegistry(installed_file)
    with (
        patch("lola.cli.install.MODULES_DIR", modules_dir),
        patch("lola.cli.install.ensure_lola_dirs"),
        patch("lola.cli.install.get_registry", return_value=registry),
        patch("lola.cli.install.get_local_modules_path", return_value=modules_dir),
        patch("lola.cli.install.is_interactive", return_value=interactive),
    ):
        yield registry


class TestGroupFlagErrors:
    def test_group_and_all_groups_conflict(self, cli_runner, tmp_path):
        modules_dir, installed_file, _ = _setup_grouped(tmp_path)
        with _install_env(modules_dir, installed_file):
            result = cli_runner.invoke(
                install_cmd,
                ["grouped", "-a", "claude-code", "-g", "frontend", "--all-groups"],
            )
        assert result.exit_code != 0
        out = result.output.lower()
        assert "all-groups" in out or "group" in out

    def test_group_flags_on_module_without_groups(
        self, cli_runner, sample_module, tmp_path
    ):
        modules_dir = tmp_path / ".lola" / "modules"
        modules_dir.mkdir(parents=True)
        shutil.copytree(sample_module, modules_dir / "sample-module")
        installed_file = tmp_path / ".lola" / "installed.yml"
        with _install_env(modules_dir, installed_file):
            result = cli_runner.invoke(
                install_cmd,
                ["sample-module", "-a", "claude-code", "--all-groups"],
            )
        assert result.exit_code != 0
        assert "no groups" in result.output.lower()

    def test_unknown_group_lists_known(self, cli_runner, tmp_path):
        modules_dir, installed_file, _ = _setup_grouped(tmp_path)
        with _install_env(modules_dir, installed_file):
            result = cli_runner.invoke(
                install_cmd,
                ["grouped", "-a", "claude-code", "-g", "nope"],
            )
        assert result.exit_code == 1
        assert "Unknown group" in result.output
        assert "frontend" in result.output
        assert "api" in result.output


class TestGroupInstallFilesystem:
    def test_selected_groups_in_registry_and_assistant_dirs(self, cli_runner, tmp_path):
        modules_dir, installed_file, _ = _setup_grouped(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        with _install_env(modules_dir, installed_file) as registry:
            result = cli_runner.invoke(
                install_cmd,
                ["grouped", "-a", "claude-code", "-g", "frontend", str(project)],
            )
        assert result.exit_code == 0, result.output

        insts = registry.find("grouped")
        assert len(insts) == 1
        assert insts[0].groups == ["frontend"]

        skills = project / ".claude" / "skills"
        commands = project / ".claude" / "commands"
        assert (skills / "base-skill" / "SKILL.md").exists()
        assert (skills / "fe-skill" / "SKILL.md").exists()
        assert not (commands / "api-cmd.md").exists()

    def test_all_groups_installs_every_artifact(self, cli_runner, tmp_path):
        modules_dir, installed_file, _ = _setup_grouped(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        with _install_env(modules_dir, installed_file) as registry:
            result = cli_runner.invoke(
                install_cmd,
                ["grouped", "-a", "claude-code", "--all-groups", str(project)],
            )
        assert result.exit_code == 0, result.output

        insts = registry.find("grouped")
        assert len(insts) == 1
        assert insts[0].groups == ["api", "frontend"]

        skills = project / ".claude" / "skills"
        commands = project / ".claude" / "commands"
        assert (skills / "base-skill" / "SKILL.md").exists()
        assert (skills / "fe-skill" / "SKILL.md").exists()
        assert (commands / "api-cmd.md").exists()


class TestGroupUpdateUninstall:
    def test_update_refreshes_recorded_groups(self, cli_runner, tmp_path):
        modules_dir, installed_file, mod = _setup_grouped(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        with _install_env(modules_dir, installed_file) as registry:
            result = cli_runner.invoke(
                install_cmd,
                ["grouped", "-a", "claude-code", "-g", "frontend", str(project)],
            )
            assert result.exit_code == 0, result.output

            fe_skill = mod / "groups" / "frontend" / "skills" / "fe-skill" / "SKILL.md"
            fe_skill.write_text(
                "---\nname: fe-skill\ndescription: fe\n---\n# refreshed\n"
            )

            result = cli_runner.invoke(update_cmd, ["grouped"])
            assert result.exit_code == 0, result.output
            content = (
                project / ".claude" / "skills" / "fe-skill" / "SKILL.md"
            ).read_text()
            assert "refreshed" in content
            assert registry.find("grouped")[0].groups == ["frontend"]

    def test_update_missing_recorded_group_errors(self, cli_runner, tmp_path):
        modules_dir, installed_file, mod = _setup_grouped(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        registry = InstallationRegistry(installed_file)
        registry.add(
            Installation(
                module_name="grouped",
                assistant="claude-code",
                scope="project",
                project_path=str(project),
                skills=["base-skill", "fe-skill"],
                groups=["frontend"],
            )
        )
        shutil.rmtree(mod / "groups" / "frontend")

        with (
            patch("lola.cli.install.MODULES_DIR", modules_dir),
            patch("lola.cli.install.ensure_lola_dirs"),
            patch("lola.cli.install.get_registry", return_value=registry),
            patch("lola.cli.install.get_local_modules_path", return_value=modules_dir),
        ):
            result = cli_runner.invoke(update_cmd, ["grouped"])

        assert "Unknown group" in result.output
        assert "frontend" in result.output

    def test_uninstall_grouped_install(self, cli_runner, tmp_path):
        modules_dir, installed_file, _ = _setup_grouped(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        with _install_env(modules_dir, installed_file) as registry:
            result = cli_runner.invoke(
                install_cmd,
                ["grouped", "-a", "claude-code", "-g", "frontend", str(project)],
            )
            assert result.exit_code == 0, result.output
            assert (project / ".claude" / "skills" / "fe-skill" / "SKILL.md").exists()

            result = cli_runner.invoke(uninstall_cmd, ["grouped", "-f"])
            assert result.exit_code == 0, result.output
            assert "Uninstalled" in result.output
            assert registry.find("grouped") == []
            assert not (project / ".claude" / "skills" / "fe-skill").exists()
            assert not (project / ".claude" / "skills" / "base-skill").exists()


class TestGroupDefaultBaseline:
    def test_no_flags_installs_baseline_and_hints_groups(self, cli_runner, tmp_path):
        modules_dir, installed_file, _ = _setup_grouped(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        with _install_env(modules_dir, installed_file) as registry:
            result = cli_runner.invoke(
                install_cmd,
                ["grouped", "-a", "claude-code", str(project)],
            )
        assert result.exit_code == 0, result.output
        assert "baseline only" in result.output.lower()
        assert "Optional groups:" in result.output
        assert "frontend" in result.output
        assert "api" in result.output
        assert "--all-groups" in result.output

        insts = registry.find("grouped")
        assert len(insts) == 1
        assert insts[0].groups == []

        skills = project / ".claude" / "skills"
        assert (skills / "base-skill" / "SKILL.md").exists()
        assert not (skills / "fe-skill").exists()
        assert not (project / ".claude" / "commands" / "api-cmd.md").exists()

    def test_interactive_also_defaults_to_baseline(self, cli_runner, tmp_path):
        modules_dir, installed_file, _ = _setup_grouped(tmp_path)
        project = tmp_path / "proj"
        project.mkdir()
        with _install_env(modules_dir, installed_file, interactive=True) as registry:
            result = cli_runner.invoke(
                install_cmd,
                ["grouped", "-a", "claude-code", str(project)],
            )
        assert result.exit_code == 0, result.output
        assert registry.find("grouped")[0].groups == []
        assert (project / ".claude" / "skills" / "base-skill" / "SKILL.md").exists()
        assert not (project / ".claude" / "skills" / "fe-skill").exists()


class TestModGroupsCommand:
    def test_lists_groups_with_counts(self, cli_runner, tmp_path):
        from lola.cli.mod import mod

        modules_dir, _, _ = _setup_grouped(tmp_path)
        with (
            patch("lola.cli.mod.MODULES_DIR", modules_dir),
            patch("lola.cli.mod.ensure_lola_dirs"),
        ):
            result = cli_runner.invoke(mod, ["groups", "grouped"])
        assert result.exit_code == 0, result.output
        assert "Groups in grouped" in result.output
        assert "frontend" in result.output
        assert "api" in result.output
        assert "1 skill" in result.output
        assert "1 command" in result.output

    def test_no_groups_message(self, cli_runner, sample_module, tmp_path):
        from lola.cli.mod import mod

        modules_dir = tmp_path / ".lola" / "modules"
        modules_dir.mkdir(parents=True)
        shutil.copytree(sample_module, modules_dir / "sample-module")
        with (
            patch("lola.cli.mod.MODULES_DIR", modules_dir),
            patch("lola.cli.mod.ensure_lola_dirs"),
        ):
            result = cli_runner.invoke(mod, ["groups", "sample-module"])
        assert result.exit_code == 0
        assert "no groups" in result.output.lower()
