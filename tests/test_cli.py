from pathlib import Path
from unittest.mock import Mock

import pytest

from interfaces import cli
from scraper_common.config import config_from_mapping


def test_output_path_is_relative_to_config_not_current_directory(tmp_path, monkeypatch):
    config_path = tmp_path / 'Настройки с пробелами' / 'config.toml'
    monkeypatch.chdir(tmp_path)
    assert cli.resolve_output_directory(config_path, Path('../Документы')) == tmp_path / 'Документы'
    assert not (tmp_path / 'Документы').exists()


def test_absolute_output_path_is_preserved(tmp_path):
    target = tmp_path / 'Документы с пробелами'
    assert cli.resolve_output_directory(tmp_path / 'settings' / 'config.toml', target) == target


def test_output_path_expands_home_directory(tmp_path):
    assert cli.resolve_output_directory(tmp_path / 'config.toml', Path('~/kplusplus-output')) == Path.home() / 'kplusplus-output'


@pytest.mark.parametrize('flags,headless,transport', [
    ([], True, 'hybrid'),
    (['--debug'], False, 'hybrid'),
    (['--no-http'], True, 'browser'),
    (['--debug', '--no-http'], False, 'browser'),
    (['--http'], True, 'hybrid'),
])
def test_cli_modes_override_config_and_output_comes_from_config(tmp_path, monkeypatch, flags, headless, transport):
    config_path = tmp_path / 'settings' / 'config.toml'
    cfg = config_from_mapping({'consultant': {'login': 'test', 'password': 'test'},
                               'export': {'directory': 'results', 'headless': False, 'transport': 'browser'}},
                              use_environment=False)
    load = Mock(return_value=cfg)
    run = Mock(return_value={'saved': 0, 'skipped': 0})
    monkeypatch.setattr(cli, 'load_config', load)
    monkeypatch.setattr(cli, 'run_export', run)
    monkeypatch.setattr(cli.signal, 'signal', Mock())
    monkeypatch.setattr('sys.argv', ['parser', '--config', str(config_path), *flags])
    cli.main()
    load.assert_called_once_with(config_path)
    passed = run.call_args.args[0]
    assert passed.headless is headless
    assert passed.transport == transport
    assert passed.directory == config_path.parent / 'results'
    assert run.call_args.args[1] == config_path.parent / '.playwright'


@pytest.mark.parametrize('flag', ['--output', '--fresh-session'])
def test_removed_options_are_rejected(monkeypatch, flag):
    monkeypatch.setattr('sys.argv', ['parser', flag])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
