"""Real local HTTP server + Chromium, without a ConsultantPlus account."""
import os
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from interfaces.web.app import AppServer, Jobs, validate_input
from scraper_common.documents import write_docx
from scraper_common.storage import ExportStore, document_key
from scraper import get_source

pytestmark = pytest.mark.skipif(os.environ.get('SCRAPER_GUI_TESTS') != '1',
                                reason='Enable SCRAPER_GUI_TESTS=1 for browser integration tests')


class TestJobs(Jobs):
    __test__ = False

    def __init__(self, root):
        super().__init__(root)
        self.requests = []
        self.wait_for_stop = False

    def start(self, data):
        values = validate_input(data)
        self.requests.append(values)
        self.state.update(directory=str(self.output_root), running=self.wait_for_stop,
                          phase='export' if self.wait_for_stop else 'done')
        if self.wait_for_stop:
            return
        store = ExportStore(self.output_root, source_id=values['source'],
                            source_name=get_source(values['source']).Scraper.source_name)
        try:
            source = 'https://example.test/cgi/online.cgi?req=doc&base=TEST&n=1'
            key = document_key(source)
            record = store.row(values['law'], key)
            path = store.file(key, source, record)
            if record is not None and path is not None and not values['overwrite']:
                self.state.update(saved=0, skipped=1)
            else:
                path = path or store.documents_dir / 'Тестовый документ.docx'
                write_docx(path, 'Текст решения — русский язык, Ё, №.')
                store.record(key, path.name, {'Связанный акт': values['law'], 'Источник': source,
                                             'Дата сохранения': '26.10.2026', 'Название документа': 'Тестовый документ',
                                             'Текст решения': 'Текст решения — русский язык, Ё, №.', 'Примечание': ''})
                self.state.update(saved=1, skipped=0, logout=True)
        finally:
            store.close()

    def stop(self):
        self.state.update(running=False, phase='stopped', logout=True)


@pytest.fixture
def app(tmp_path, monkeypatch):
    selected = tmp_path / 'Папка с пробелами'
    monkeypatch.setattr('interfaces.web.app.choose_folder', lambda: selected)
    opened = []
    monkeypatch.setattr('interfaces.web.app.open_folder', opened.append)
    server = AppServer(0, tmp_path)
    server.jobs = TestJobs(tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}')
                yield page, server.jobs, opened
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def fill_form(page):
    page.get_by_label('Логин источника').fill('test-client')
    page.get_by_label('Пароль', exact=True).fill('not-a-real-password')
    page.get_by_label('Федеральный закон или запрос').fill('N-113-ФЗ')


def test_form_folder_resume_and_overwrite(app):
    from playwright.sync_api import expect
    page, jobs, opened = app
    page.get_by_role('button', name='Выбрать папку…').click()
    expect(page.locator('#save-directory')).to_have_value(str(jobs.root / 'Папка с пробелами'))
    fill_form(page)
    page.get_by_role('button', name='Запустить выгрузку').click()
    expect(page.locator('#phase')).to_have_text('Выгрузка завершена')
    assert jobs.requests[-1]['debug'] is False
    assert jobs.requests[-1]['overwrite'] is False
    expect(page.locator('#password')).to_have_value('')
    expect(page.locator('#saved')).to_have_text('1')
    with page.expect_response(lambda response: response.url.endswith('/api/open-folder')):
        page.get_by_role('button', name='Открыть папку').click()
    expect(page.locator('#error')).to_be_hidden()
    assert opened == [jobs.output_root]
    fill_form(page)
    page.get_by_role('button', name='Запустить выгрузку').click()
    expect(page.locator('#skipped')).to_have_text('1')
    fill_form(page)
    page.get_by_label('Перезаписывать существующие файлы').check()
    page.get_by_label('Режим отладки', exact=False).check()
    page.get_by_role('button', name='Запустить выгрузку').click()
    expect(page.locator('#saved')).to_have_text('1')
    assert jobs.requests[-1]['debug'] is True
    assert jobs.requests[-1]['overwrite'] is True
    assert len(list(jobs.output_root.rglob('*.docx'))) == 1
    Path('artifacts').mkdir(exist_ok=True)
    page.screenshot(path='artifacts/gui.png', full_page=True)


def test_stop_waits_for_logout(app):
    from playwright.sync_api import expect
    page, jobs, _ = app
    jobs.wait_for_stop = True
    fill_form(page)
    page.get_by_role('button', name='Запустить выгрузку').click()
    expect(page.locator('#start')).to_be_disabled()
    page.get_by_role('button', name='Остановить и выйти из системы').click()
    expect(page.locator('#phase')).to_have_text('Выгрузка остановлена')
    expect(page.locator('#logout')).to_have_text('Выход из источника подтверждён.')
    expect(page.locator('#start')).to_be_enabled()


def test_source_selection_and_ner_stub_settings_reach_backend(app):
    from playwright.sync_api import expect
    page, jobs, _ = app
    page.get_by_role('checkbox', name='Судакт.ру', exact=True).check()
    page.get_by_label('Извлекать структурированные данные').check()
    page.get_by_label('С использованием OpenAI').check()
    page.get_by_label('Регион', exact=True).check()
    expect(page.locator('#api-key')).to_be_disabled()
    expect(page.locator('#ner-note')).to_contain_text('пока не реализовано')
    fill_form(page)
    page.get_by_role('button', name='Запустить выгрузку').click()
    expect(page.locator('#saved')).to_have_text('1')
    assert jobs.requests[-1]['sources'] == ['consultantplus', 'sudact']
    assert jobs.requests[-1]['ner']['enabled'] is True
    assert jobs.requests[-1]['ner']['method'] == 'openai'
    assert 'region' in jobs.requests[-1]['ner']['fields']
    page.get_by_role('tab', name='Найденные акты').click()
    expect(page.locator('#journal-documents')).to_contain_text('Тестовый документ')
