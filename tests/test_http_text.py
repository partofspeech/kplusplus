from unittest.mock import Mock

import pytest

from scraper.consultantplus.http_text import decode_document, verified_http_text

URL = 'https://demo.consultant.ru/document_inner.htm'
PAGE = 'https://demo.consultant.ru/cgi/online.cgi?req=doc&base=LAW&n=123'
TEXT = 'РЕШЕНИЕ\nГражданин Ёлкин — статья № 113-ФЗ.'


def response(body, content_type='text/html; charset=utf-8', status=200):
    result = Mock(status=status, headers={'content-type': content_type})
    result.body.return_value = body
    return result


def test_http_uses_authenticated_context_and_validates_full_text():
    reply = response(('<html><head><title>Не текст решения</title></head><body>'
                      '<p>РЕШЕНИЕ</p><script>ignore()</script>'
                      '<p>Гражданин Ёлкин — статья № 113-ФЗ.</p></body></html>').encode())
    context = Mock()
    context.request.get.return_value = reply
    actual = verified_http_text(context, URL, PAGE, TEXT, timeout_ms=45000)
    assert ' '.join(actual.split()) == ' '.join(TEXT.split())
    context.request.get.assert_called_once_with(URL, timeout=15000, max_redirects=0)
    reply.dispose.assert_called_once()


@pytest.mark.parametrize('body,content_type,status', [
    (b'<p>partial</p>', 'text/html', 200),
    (b'<form>Login required</form>', 'text/html', 200),
    (b'', 'text/html', 302),
    (b'', 'text/html', 403),
    (b'opaque binary', 'application/octet-stream', 200),
])
def test_bad_http_responses_fall_back_to_browser(body, content_type, status):
    context = Mock()
    reply = response(body, content_type, status)
    context.request.get.return_value = reply
    assert verified_http_text(context, URL, PAGE, TEXT, timeout_ms=45000) is None
    reply.dispose.assert_called_once()


def test_request_failure_falls_back_to_browser():
    context = Mock()
    context.request.get.side_effect = RuntimeError('timeout')
    assert verified_http_text(context, URL, PAGE, TEXT, timeout_ms=1000) is None


def test_http_comparison_ignores_only_removed_service_lines():
    context = Mock()
    context.request.get.return_value = response(
        ('Краткий пересказ\nДокумент: 1/19\n' + TEXT).encode(), 'text/plain; charset=utf-8',
    )
    assert verified_http_text(context, URL, PAGE, TEXT, timeout_ms=1000) is not None


def test_http_difference_diagnostic_does_not_log_document_text(caplog):
    context = Mock()
    context.request.get.return_value = response('Другая версия решения'.encode(), 'text/plain; charset=utf-8')
    with caplog.at_level('DEBUG', logger='scraper.consultantplus.http_text'):
        assert verified_http_text(context, URL, PAGE, TEXT, timeout_ms=1000) is None
    assert 'первое различие: 0' in caplog.text
    assert 'Другая версия решения' not in caplog.text
    assert 'Ёлкин' not in caplog.text


def test_never_fetches_cross_origin_or_unobserved_scheme():
    context = Mock()
    for url in ['https://external.test/text', 'file:///private/file', 'about:blank']:
        assert verified_http_text(context, url, PAGE, TEXT, timeout_ms=1000) is None
    context.request.get.assert_not_called()


@pytest.mark.parametrize('charset', ['utf-8', 'windows-1251'])
def test_decodes_cyrillic_in_http_response(charset):
    assert decode_document(TEXT.encode(charset), f'text/plain; charset={charset}') == TEXT
    html = f'<meta charset="{charset}"><p>{TEXT}</p>'
    assert decode_document(html.encode(charset), 'text/html') == html


def test_export_retains_browser_text_if_http_is_partial(tmp_path, monkeypatch):
    import csv
    from dataclasses import replace
    from unittest.mock import MagicMock
    from scraper.consultantplus import ConsultantPlusScraper
    from scraper_common.config import config_from_mapping
    cfg = config_from_mapping({'consultant': {'login': 'user', 'password': 'secret'}}, use_environment=False)
    page = MagicMock()
    page.frames = []
    page.url = PAGE
    page.locator.return_value.inner_text.return_value = TEXT
    page.title.return_value = 'Решение'
    context = Mock()
    context.new_page.return_value = page
    context.request.get.return_value = response(b'<html>incomplete</html>')
    exporter = ConsultantPlusScraper(context, replace(cfg, transport='hybrid'))
    exporter.session.captcha_present = Mock(return_value=False)
    exporter._reference_fields = Mock(return_value={})
    assert exporter.export_related([PAGE], tmp_path) == (1, 0)
    assert (exporter.http_texts, exporter.browser_texts) == (0, 1)
    with (tmp_path / 'судакты.csv').open(encoding='utf-8-sig', newline='') as stream:
        assert next(csv.DictReader(stream))['Текст решения'] == TEXT
