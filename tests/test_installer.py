import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import install as installer


@pytest.mark.parametrize('system', ['Darwin', 'Linux'])
def test_install_plans_dependencies_for_each_os_and_preserves_config(tmp_path, monkeypatch, system):
    config = tmp_path / 'config.toml'
    config.write_text('личные настройки', encoding='utf-8')
    execute = Mock()
    monkeypatch.setattr(installer, 'run_step', execute)
    monkeypatch.setattr(installer, 'environment_is_usable', lambda *args: False)
    installer.install(tmp_path, system=system, dev=True)
    commands = [call.args[1] for call in execute.call_args_list]
    expected_python = tmp_path / '.venv' / 'bin/python'
    assert commands[0][1:3] == ['-m', 'venv']
    assert commands[1] == [str(expected_python), '-m', 'pip', 'install', '-e', str(tmp_path) + '[test]']
    assert ('--with-deps' in commands[2]) is (system == 'Linux')
    assert commands[2][-1] == 'chromium'
    compile(commands[3][-1], '<browser-check>', 'exec')
    assert config.read_text(encoding='utf-8') == 'личные настройки'


def test_healthy_environment_is_reused_and_missing_config_is_created(tmp_path, monkeypatch):
    (tmp_path / 'config.example.toml').write_text('example')
    monkeypatch.setattr(installer, 'environment_is_usable', lambda *args: True)
    execute = Mock()
    monkeypatch.setattr(installer, 'run_step', execute)
    installer.install(tmp_path, system='Darwin')
    assert execute.call_count == 3
    assert (tmp_path / 'config.toml').read_text() == 'example'


def test_incompatible_environment_is_backed_up_instead_of_deleted(tmp_path, monkeypatch):
    environment = tmp_path / '.venv'
    environment.mkdir()
    (environment / 'preserve-me').write_text('old environment')
    (tmp_path / 'config.toml').write_text('config')
    monkeypatch.setattr(installer, 'environment_is_usable', lambda *args: False)
    monkeypatch.setattr(installer, 'run_step', Mock())
    installer.install(tmp_path, system='Darwin')
    backups = list(tmp_path.glob('.venv.backup-*'))
    assert len(backups) == 1
    assert (backups[0] / 'preserve-me').read_text() == 'old environment'


def test_dry_run_changes_nothing_and_runs_no_installation(tmp_path, monkeypatch):
    environment = tmp_path / '.venv'
    environment.mkdir()
    (environment / 'preserve-me').write_text('old environment')
    monkeypatch.setattr(installer, 'environment_is_usable', lambda *args: False)
    subprocess = Mock()
    monkeypatch.setattr(installer.subprocess, 'run', subprocess)
    installer.install(tmp_path, system='Linux', dry_run=True)
    subprocess.assert_not_called()
    assert environment.exists()
    assert not list(tmp_path.glob('.venv.backup-*'))
    assert not (tmp_path / 'config.toml').exists()


def test_linux_system_dependencies_can_be_skipped(tmp_path, monkeypatch):
    (tmp_path / 'config.toml').write_text('config')
    monkeypatch.setattr(installer, 'environment_is_usable', lambda *args: True)
    execute = Mock()
    monkeypatch.setattr(installer, 'run_step', execute)
    installer.install(tmp_path, system='Linux', skip_system_deps=True)
    assert '--with-deps' not in execute.call_args_list[1].args[1]


@pytest.mark.parametrize('version,system,expected', [([3, 12], 'Darwin', True), ([3, 10], 'Darwin', False), ([3, 12], 'Linux', False)])
def test_existing_environment_version_and_os_are_checked(tmp_path, monkeypatch, version, system, expected):
    environment = tmp_path / '.venv'
    python = environment / 'bin' / 'python'
    python.parent.mkdir(parents=True)
    python.touch()
    probe = SimpleNamespace(returncode=0, stdout=json.dumps([version, str(environment), system]))
    monkeypatch.setattr(installer.subprocess, 'run', Mock(return_value=probe))
    assert installer.environment_is_usable(python, environment, 'Darwin') is expected
