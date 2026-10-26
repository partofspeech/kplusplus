from unittest.mock import Mock

import pytest

from scraper_common.config import config_from_mapping
from scraper.runner import run_export
from scraper import get_scraper_class
from scraper.consultantplus import ConsultantPlusScraper


def test_existing_configs_default_to_consultantplus():
    config = config_from_mapping({'consultant': {'login': 'test', 'password': 'secret'}})
    assert config.source == 'consultantplus'
    assert get_scraper_class(config.source) is ConsultantPlusScraper


def test_sudact_stub_is_skipped_without_browser_or_runtime(tmp_path, monkeypatch):
    config = config_from_mapping({'scraper': {'source': 'sudact'}})
    playwright = Mock()
    monkeypatch.setattr('scraper.runner.sync_playwright', playwright)
    runtime_dir = tmp_path / 'runtime'
    result = run_export(config, runtime_dir)
    assert result['saved'] == 0
    assert result['skipped_sources'] == ['sudact']
    playwright.assert_not_called()
    assert not runtime_dir.exists()


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError, match='scraper.source'):
        config_from_mapping({'scraper': {'source': 'unknown'}})


def test_sudact_cli_reports_skipped_source_without_credentials(tmp_path, monkeypatch, capsys):
    from interfaces.cli import main
    config_path = tmp_path / 'sudact.toml'
    config_path.write_text('[scraper]\nsource="sudact"\n')
    monkeypatch.delenv('CONSULTANT_LOGIN', raising=False)
    monkeypatch.delenv('CONSULTANT_PASSWORD', raising=False)
    monkeypatch.setattr('interfaces.cli.signal.signal', Mock())
    monkeypatch.setattr('sys.argv', ['scraper', '--config', str(config_path)])
    main()
    output = capsys.readouterr()
    assert 'реализация пока отсутствует' in output.err
    assert 'сохранено 0' in output.out


def test_open_source_ignores_consultant_credentials_and_settings(monkeypatch):
    monkeypatch.setenv('CONSULTANT_LOGIN', 'private-account')
    monkeypatch.setenv('CONSULTANT_PASSWORD', 'private-password')
    config = config_from_mapping({
        'scraper': {'source': 'sudact'},
        'consultant': {'login': 'unused', 'password': 'unused'},
        'search': {'query': '113-ФЗ', 'court_scope': 'not-relevant-to-open-source'},
    })
    assert config.secrets == ()
    assert config.query == '113-ФЗ'
    assert not hasattr(config.source_options, 'login')
    assert not hasattr(config, 'court_scope')


def test_new_consultant_settings_are_local_to_source():
    config = config_from_mapping({
        'scraper': {'source': 'consultantplus'},
        'sources': {'consultantplus': {'login': 'client', 'password': 'secret', 'court_scope': 'available'}},
        'search': {'query': '113-ФЗ'},
    }, use_environment=False)
    assert config.source_options.login == 'client'
    assert config.secrets == ('client', 'secret')
    assert 'secret' not in repr(config)
    assert 'secret' not in repr(config.source_options)
