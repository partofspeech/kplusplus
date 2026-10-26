"""Chromium replays local fixtures: no credentials and no website connection."""
import csv
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import sync_playwright

from scraper.consultantplus import ConsultantPlusScraper
from scraper.consultantplus.config import ConsultantPlusSettings
from scraper_common.config import Config, SourceConfig

pytestmark = pytest.mark.skipif(os.environ.get('SCRAPER_OFFLINE_BROWSER_TESTS') != '1',
                                reason='Set SCRAPER_OFFLINE_BROWSER_TESTS=1 to run Chromium fixture replay')
FIXTURES = Path(__file__).parents[1] / 'fixtures' / 'consultantplus'


def test_search_reference_export_logout_and_resume_from_local_pages(tmp_path):
    metadata = json.loads((FIXTURES / 'metadata.json').read_text(encoding='utf-8'))
    expected = (FIXTURES / 'decision_expected.txt').read_text(encoding='utf-8')
    options = ConsultantPlusSettings(login='', password='')
    cfg = Config(query=metadata['law'], directory=tmp_path / 'output', headless=True,
                 slow_mo_ms=0, timeout_ms=5000, source_options=options,
                 source='consultantplus', source_name='Консультант+', transport='browser',
                 sources=(SourceConfig('consultantplus', 'Консультант+', options),),
                 source_names={'consultantplus': 'Консультант+'})
    unexpected_requests = []
    replayed = []
    decision_id = parse_qs(urlsplit(metadata['source_url']).query)['n'][0]

    def replay(route):
        url = urlsplit(route.request.url)
        params = parse_qs(url.query)
        if url.hostname == 'login.consultant.ru' and url.path == '/':
            name = 'search.html'
        elif url.hostname == 'demo.consultant.ru' and url.path == '/document_inner.htm':
            name = 'document_inner.html'
        elif url.hostname == 'demo.consultant.ru' and url.path == '/cgi/online.cgi' and params.get('req') == ['doc']:
            if params.get('base') == ['LAW'] and params.get('n') == ['541153']:
                name = 'law.html'
            elif params.get('n') == [decision_id]:
                name = 'document.html'
            else:
                unexpected_requests.append(route.request.url)
                route.abort()
                return
        elif url.path == '/favicon.ico':
            route.fulfill(status=204, body='')
            return
        else:
            unexpected_requests.append(route.request.url)
            route.abort()
            return
        replayed.append(name)
        route.fulfill(status=200, content_type='text/html; charset=utf-8',
                      body=(FIXTURES / name).read_bytes())

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            # Offline mode is additional protection; all allowed URLs are fulfilled locally.
            context = browser.new_context(offline=True, service_workers='block')
            context.set_default_timeout(cfg.timeout_ms)
            context.route('**/*', replay)
            scraper = ConsultantPlusScraper(context, cfg)
            first = scraper.run(cfg.directory)
            assert first['saved'] == 1
            assert first['logout_confirmed'] is True
            assert {'search.html', 'law.html', 'document.html', 'document_inner.html'} <= set(replayed)
            with (cfg.directory / 'судакты.csv').open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            assert len(rows) == 1  # repeated URL with another session parameter is not duplicated
            assert rows[0]['Название документа'] == metadata['title']
            assert rows[0]['Примечание'] == metadata['note']
            assert ' '.join(rows[0]['Текст решения'].split()) == ' '.join(expected.split())
            assert rows[0]['Источник парсинга'] == 'Консультант+'
            assert len(list((cfg.directory / 'consultantplus').glob('*.docx'))) == 1
            documents_before = replayed.count('document.html')
            second = ConsultantPlusScraper(context, cfg).run(cfg.directory)
            assert second['saved'] == 0
            assert second['skipped'] == 1
            assert second['logout_confirmed'] is True
            assert replayed.count('document.html') == documents_before
            assert unexpected_requests == []
        finally:
            browser.close()
