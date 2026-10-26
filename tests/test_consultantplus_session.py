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
