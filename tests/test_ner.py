from unittest.mock import Mock

import pytest

from ner import NerConfig, extract, parse_config
from scraper_common.config import config_from_mapping
from scraper.runner import run_export


def test_ner_is_disabled_by_default():
    assert parse_config({}) == NerConfig()


@pytest.mark.parametrize('data', [
    {'enabled': 'yes'}, {'method': 'unknown'}, {'fields': ['not-a-field']},
    {'fields': 'court'}, {'openai_api_key': 123}, None,
])
def test_rejects_invalid_ner_options(data):
    with pytest.raises(ValueError):
        parse_config(data)


def test_ner_settings_and_secret_are_loaded_from_config(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'private-test-api-key')
    config = config_from_mapping({'scraper': {'source': 'sudact'}, 'ner': {
        'enabled': True, 'method': 'openai', 'fields': ['court', 'region', 'court'],
        'openai_api_key': '${OPENAI_API_KEY}',
    }})
    assert config.ner.enabled
    assert config.ner.fields == ('court', 'region')
    assert config.ner.api_key == 'private-test-api-key'
    assert config.ner.api_key in config.secrets
    assert config.ner.api_key not in repr(config)
    assert config.ner.api_key not in repr(config.ner)


def test_extraction_is_an_explicit_stub():
    with pytest.raises(NotImplementedError, match='пока не реализовано'):
        extract('Текст решения', NerConfig(enabled=True))


def test_ner_stub_does_not_block_download_runner(tmp_path, monkeypatch, caplog):
    config = config_from_mapping({'scraper': {'source': 'sudact'}, 'ner': {'enabled': True}})
    launch = Mock()
    monkeypatch.setattr('scraper.runner.sync_playwright', launch)
    assert run_export(config, tmp_path / 'runtime')['skipped_sources'] == ['sudact']
    assert 'без дополнительных полей' in caplog.text
    launch.assert_not_called()
