from unittest.mock import Mock

import pytest

from scraper_common.config import config_from_mapping
from scraper.consultantplus import ConsultantPlusScraper
from scraper.consultantplus.session import ConsultantPlusSession


def config():
    return config_from_mapping({'consultant': {'login': 'test', 'password': 'secret'}}, use_environment=False)


@pytest.mark.parametrize('error', [RuntimeError('Ошибка входа'), InterruptedError('Остановка')])
def test_consultantplus_logs_out_even_when_login_or_collection_fails(tmp_path, error):
    scraper = ConsultantPlusScraper(Mock(), config())
    scraper.collect_urls = Mock(side_effect=error)
    scraper.session = Mock()
    with pytest.raises(type(error)):
        scraper.run(tmp_path)
    scraper.session.logout_all.assert_called_once_with()


def test_consultantplus_logs_out_after_export_failure(tmp_path):
    scraper = ConsultantPlusScraper(Mock(), config())
    scraper.collect_urls = Mock(return_value=['https://example.test/doc'])
    scraper.export_related = Mock(side_effect=OSError('disk full'))
    scraper.session = Mock()
    with pytest.raises(OSError, match='disk full'):
        scraper.run(tmp_path)
    scraper.session.logout_all.assert_called_once_with()


def test_session_tries_other_tabs_after_failed_logout():
    first, last, closed = Mock(), Mock(), Mock()
    first.is_closed.return_value = last.is_closed.return_value = False
    closed.is_closed.return_value = True
    session = ConsultantPlusSession(Mock(pages=[first, last, closed]), config(), cancelled=lambda: True)
    session.logout = Mock(side_effect=[RuntimeError('tab unavailable'), True])
    assert session.logout_all() is True
    assert [call.args[0] for call in session.logout.call_args_list] == [last, first]


def test_session_reports_unconfirmed_logout(caplog):
    page = Mock()
    page.is_closed.return_value = False
    session = ConsultantPlusSession(Mock(pages=[page]), config())
    session.logout = Mock(return_value=False)
    assert session.logout_all() is False
    assert 'Выход из КонсультантПлюс не подтверждён' in caplog.text


@pytest.mark.parametrize('confirmed', [True, False])
def test_logout_checks_login_endpoint_after_home_redirect(monkeypatch, confirmed):
    from playwright.sync_api import TimeoutError
    from scraper.consultantplus.session import LOGIN_URL

    page, button = Mock(), Mock()
    monkeypatch.setattr('scraper.consultantplus.session.first_visible', lambda *args: button)
    password = page.locator.return_value.first
    password.wait_for.side_effect = [TimeoutError('home page'), None if confirmed else TimeoutError('still logged in')]
    session = ConsultantPlusSession(Mock(), config())
    session._status = Mock()

    assert session.logout(page) is confirmed
    button.click.assert_called_once()
    page.goto.assert_called_once_with(LOGIN_URL, wait_until='domcontentloaded', timeout=session.config.timeout_ms)
    if confirmed:
        session._status.assert_called_once_with('logged-out')
    else:
        session._status.assert_not_called()
