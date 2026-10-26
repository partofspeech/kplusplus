"""Regression tests on recorded decision text; no browser or account needed."""
import csv
import json
from pathlib import Path
from unittest.mock import MagicMock
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from scraper.consultantplus import ConsultantPlusScraper
from scraper.consultantplus.config import ConsultantPlusSettings
from scraper.consultantplus.http_text import verified_http_text
from scraper.consultantplus.text import clean_decision_text
from scraper_common.config import Config, SourceConfig

FIXTURES = Path(__file__).parent / 'fixtures' / 'consultantplus'


def recorded_config(output_dir, metadata):
    # Replay begins with a saved application page. No username/password needed.
    options = ConsultantPlusSettings(login='', password='')
    return Config(query=metadata['law'], directory=output_dir, headless=True,
                  slow_mo_ms=0, timeout_ms=5000, source_options=options,
                  source='consultantplus', source_name='Консультант+', transport='browser',
                  sources=(SourceConfig('consultantplus', 'Консультант+', options),),
                  source_names={'consultantplus': 'Консультант+'})


@pytest.fixture
def recorded():
    metadata = json.loads((FIXTURES / 'metadata.json').read_text(encoding='utf-8'))
    return metadata, (FIXTURES / 'decision_raw.txt').read_text(encoding='utf-8'), (FIXTURES / 'decision_expected.txt').read_text(encoding='utf-8')


def test_recorded_decision_cleanup_keeps_full_text(recorded):
    _, raw, expected = recorded
    actual = clean_decision_text(raw)
    assert ' '.join(actual.split()) == ' '.join(expected.split())
    assert 'Краткий пересказ' not in actual
    assert 'Документ: 1/19' not in actual
    assert 'В.Д.ЗОРЬКИН' in actual


def test_recorded_export_reference_docx_csv_and_resume(tmp_path, recorded):
    metadata, raw, expected = recorded
    page = MagicMock()
    page.frames = []
    page.url = metadata['source_url']
    page.title.return_value = metadata['title']
    body = page.locator.return_value
    body.inner_text.return_value = raw

    def open_reference():
        body.inner_text.return_value = (FIXTURES / 'reference.txt').read_text(encoding='utf-8')

    body.first.click.side_effect = open_reference
    context = MagicMock()
    context.new_page.return_value = page
    scraper = ConsultantPlusScraper(context, recorded_config(tmp_path, metadata))
    assert scraper.export_related([metadata['source_url']], tmp_path) == (1, 0)
    with (tmp_path / 'судакты.csv').open(encoding='utf-8-sig', newline='') as stream:
        row = next(csv.DictReader(stream))
    assert row['Название документа'] == metadata['title']
    assert row['Примечание'] == metadata['note']
    assert row['Источник парсинга'] == 'Консультант+'
    assert ' '.join(row['Текст решения'].split()) == ' '.join(expected.split())
    with ZipFile(next((tmp_path / 'consultantplus').glob('*.docx'))) as archive:
        document = ET.fromstring(archive.read('word/document.xml'))
    assert ' '.join(' '.join(document.itertext()).split()) == ' '.join(expected.split())
    assert scraper.export_related([metadata['source_url'] + '&rnd=new-session'], tmp_path) == (0, 1)
    assert context.new_page.call_count == 1
    context.request.get.assert_not_called()


def test_http_checks_recorded_document_body(recorded):
    metadata, raw, _ = recorded
    context = MagicMock()
    response = context.request.get.return_value
    response.status = 200
    response.headers = {'content-type': 'text/html; charset=utf-8'}
    response.body.return_value = (FIXTURES / 'document_inner.html').read_bytes()
    text = verified_http_text(context, 'https://demo.consultant.ru/document_inner.htm',
                              metadata['source_url'], raw, timeout_ms=5000)
    assert text is not None
    assert ' '.join(text.split()) == ' '.join(raw.split())
