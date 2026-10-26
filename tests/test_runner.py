from unittest.mock import Mock

import pytest

from scraper_common.config import config_from_mapping
from scraper.runner import run_export


@pytest.fixture
def setup_runner(tmp_path, monkeypatch):
    page = Mock()
    page.is_closed.return_value = False
    context = Mock(pages=[page])
    browser = Mock()
    browser.new_context.return_value = context
    playwright = Mock()
    playwright.chromium.launch.return_value = browser
    manager = Mock()
    manager.__enter__ = Mock(return_value=playwright)
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr('scraper.runner.sync_playwright', lambda: manager)
    scraper = Mock()
    scraper.run.return_value = {'saved': 1, 'skipped': 0, 'logout_confirmed': True, 'http_texts': 0, 'browser_texts': 1}
    scraper_class = Mock(return_value=scraper, supported=True)
    monkeypatch.setattr('scraper.runner.get_scraper_class', lambda source: scraper_class)
    config = config_from_mapping({'consultant': {'login': 'test', 'password': 'secret'}})
    return config, playwright, browser, context, scraper


@pytest.mark.parametrize('error', [RuntimeError('Ошибка входа'), InterruptedError('Остановка')])
def test_runner_closes_resources_after_source_failure(tmp_path, setup_runner, error):
    config, _, browser, context, scraper = setup_runner
    scraper.run.side_effect = error
    with pytest.raises(type(error)):
        run_export(config, tmp_path / 'runtime')
    context.close.assert_called_once()
    browser.close.assert_called_once()
    assert not (tmp_path / 'runtime' / 'active.lock').exists()


def test_failed_browser_launch_releases_lock(tmp_path, setup_runner):
    config, playwright, _, _, _ = setup_runner
    playwright.chromium.launch.side_effect = RuntimeError('browser unavailable')
    with pytest.raises(RuntimeError, match='browser unavailable'):
        run_export(config, tmp_path / 'runtime')
    assert not (tmp_path / 'runtime' / 'active.lock').exists()


def test_success_returns_statistics(tmp_path, setup_runner):
    config, _, browser, context, _ = setup_runner
    assert run_export(config, tmp_path / 'runtime') == {
        'saved': 1, 'skipped': 0, 'logout_confirmed': True, 'http_texts': 0, 'browser_texts': 1, 'skipped_sources': [],
    }
    context.close.assert_called_once()
    browser.close.assert_called_once()


def test_open_source_needs_no_login_or_logout_methods(tmp_path, setup_runner, monkeypatch):
    _, _, browser, context, _ = setup_runner
    config = config_from_mapping({'scraper': {'source': 'sudact'}})
    scraper = Mock(spec=['run'])
    scraper.run.return_value = {'saved': 2, 'skipped': 0, 'logout_confirmed': None}
    scraper_class = Mock(return_value=scraper, supported=True)
    monkeypatch.setattr('scraper.runner.get_scraper_class', lambda source: scraper_class)
    assert run_export(config, tmp_path / 'runtime')['saved'] == 2
    scraper.run.assert_called_once_with(config.directory)
    context.close.assert_called_once()
    browser.close.assert_called_once()
