import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from interfaces.web.app import Jobs, open_folder, validate_input
from scraper_common.config import config_from_mapping


def config(tmp_path):
    return config_from_mapping({'consultant': {'login': 'user', 'password': 'secret'},
                                'export': {'directory': str(tmp_path / 'out')}}, use_environment=False)


@pytest.mark.parametrize('data', [dict(login='', password='a', law='b'),
                                   dict(login='a', password='', law='b'),
                                   dict(login='a', password='b', law=''),
                                   dict(login='a', password='b', law='c', debug='false')])
def test_reject_invalid_input(data):
    with pytest.raises(ValueError):
        validate_input(data)


def test_form_credentials_override_environment(monkeypatch):
    monkeypatch.setenv('CONSULTANT_PASSWORD', 'wrong-account')
    cfg = config_from_mapping({'consultant': {'login': 'client', 'password': '${literal}'}},
                              use_environment=False)
    assert cfg.source_options.password == '${literal}'
    assert cfg.source_options.login == 'client'


@pytest.mark.parametrize('debug', [False, True])
def test_job_passes_headless_and_credentials_over_stdin(tmp_path, monkeypatch, debug):
    process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(), poll=lambda: None)
    popen = Mock(return_value=process)
    monkeypatch.setattr('interfaces.web.app.subprocess.Popen', popen)
    monkeypatch.setattr('interfaces.web.app.threading.Thread', Mock())
    jobs = Jobs(tmp_path)
    jobs.start({'login': 'client', 'password': 'sensitive', 'law': 'N-113-ФЗ', 'debug': debug})
    payload = json.loads(process.stdin.getvalue())
    assert payload['config']['export']['headless'] is (not debug)
    assert popen.call_args.args[0][1:3] == ['-X', 'utf8']
    assert payload['config']['export']['directory'] == str(tmp_path / 'output')
    assert payload['config']['export']['overwrite'] is False
    assert payload['config']['sources']['consultantplus']['password'] == 'sensitive'
    assert payload['config']['search']['query'] == 'N-113-ФЗ'
    assert 'sensitive' not in repr(popen.call_args)
    assert 'sensitive' not in json.dumps(jobs.snapshot())
    assert not list(tmp_path.rglob('*'))  # no configuration containing credentials on disk
    with pytest.raises(ValueError, match='уже работает'):
        jobs.start({'login': 'client', 'password': 'sensitive', 'law': 'law'})
    jobs.stop()
    assert process.stdin.getvalue().endswith('stop\n')
    assert jobs.snapshot()['running']  # logout completes before the UI unlocks


@pytest.mark.parametrize('platform,command', [('win32', None), ('darwin', 'open'), ('linux', 'xdg-open')])
def test_native_folder_opener(tmp_path, monkeypatch, platform, command):
    monkeypatch.setattr('interfaces.web.app.sys.platform', platform)
    windows_open = Mock()
    popen = Mock()
    monkeypatch.setattr('interfaces.web.app.os.startfile', windows_open, raising=False)
    monkeypatch.setattr('interfaces.web.app.subprocess.Popen', popen)
    folder = tmp_path / 'Документы с пробелами'
    open_folder(folder)
    if command:
        popen.assert_called_once_with([command, str(folder)])
    else:
        windows_open.assert_called_once_with(str(folder))
    assert folder.is_dir()


def make_handler(tmp_path, path, *, token='token', origin=None, body=b'{}'):
    from interfaces.web.app import Handler
    handler = object.__new__(Handler)
    handler.server = SimpleNamespace(server_port=8765, token='token', jobs=Jobs(tmp_path))
    handler.path = path
    handler.headers = {'Host': '127.0.0.1:8765', 'X-App-Token': token,
                       'Content-Length': str(len(body))}
    if origin:
        handler.headers['Origin'] = origin
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    return handler


def test_http_rejects_foreign_origin_and_missing_token(tmp_path):
    for kwargs in ({'token': ''}, {'origin': 'https://other.example'}):
        handler = make_handler(tmp_path, '/api/start', **kwargs)
        handler.do_POST()
        handler.send_response.assert_called_once_with(403)
        assert not handler.server.jobs.snapshot()['running']


def test_http_serves_assets_and_bootstraps_token(tmp_path):
    for path in ('/', '/app.js', '/style.css'):
        handler = make_handler(tmp_path, path)
        handler.do_GET()
        handler.send_response.assert_called_once_with(200)
        assert handler.wfile.getvalue()
        assert b'__APP_TOKEN__' not in handler.wfile.getvalue()


def test_http_rejects_invalid_form_before_starting_worker(tmp_path):
    handler = make_handler(tmp_path, '/api/start', body=b'{"login":"client"}')
    handler.do_POST()
    handler.send_response.assert_called_once_with(400)
    assert not handler.server.jobs.snapshot()['running']


def test_http_folder_uses_server_directory_not_untrusted_input(tmp_path, monkeypatch):
    opener = Mock()
    monkeypatch.setattr('interfaces.web.app.open_folder', opener)
    handler = make_handler(tmp_path, '/api/open-folder', body=b'{"directory":"/arbitrary"}')
    handler.do_POST()
    opener.assert_called_once_with(tmp_path / 'output')


def test_stop_does_not_prevent_logout_confirmation(tmp_path):
    from scraper.consultantplus import ConsultantPlusScraper
    exporter = ConsultantPlusScraper(Mock(), config(tmp_path), cancelled=lambda: True)
    with pytest.raises(InterruptedError):
        exporter._status('export')
    exporter._status('logged-out')


def test_selected_folder_is_used_for_next_export(tmp_path, monkeypatch):
    destination = tmp_path / 'Мои документы'
    monkeypatch.setattr('interfaces.web.app.choose_folder', lambda: destination)
    jobs = Jobs(tmp_path)
    jobs.select_folder()
    assert jobs.snapshot()['save_directory'] == str(destination)
    process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(), poll=lambda: None)
    monkeypatch.setattr('interfaces.web.app.subprocess.Popen', Mock(return_value=process))
    monkeypatch.setattr('interfaces.web.app.threading.Thread', Mock())
    jobs.start({'login': 'client', 'password': 'secret', 'law': 'N-113-ФЗ'})
    payload = json.loads(process.stdin.getvalue())
    from pathlib import Path
    assert Path(payload['config']['export']['directory']) == destination
    with pytest.raises(ValueError):
        jobs.select_folder()


def test_cancel_folder_dialog_keeps_previous_selection(tmp_path, monkeypatch):
    jobs = Jobs(tmp_path)
    before = jobs.snapshot()
    monkeypatch.setattr('interfaces.web.app.choose_folder', lambda: None)
    jobs.select_folder()
    assert jobs.snapshot() == before


@pytest.mark.parametrize('platform', ['darwin', 'win32', 'linux'])
def test_native_folder_selection(tmp_path, monkeypatch, platform):
    from interfaces.web.app import choose_folder
    destination = tmp_path / 'Папка с пробелами'
    monkeypatch.setattr('interfaces.web.app.sys.platform', platform)
    call = Mock(return_value=SimpleNamespace(returncode=0, stdout=str(destination) + '\n'))
    monkeypatch.setattr('interfaces.web.app.subprocess.run', call)
    assert choose_folder() == destination
    command = call.call_args.args[0]
    assert command[0] == 'osascript' if platform == 'darwin' else command[-1] == 'interfaces.web.folder_picker'


def test_docx_preserves_decision_text_before_reference_panel(tmp_path, monkeypatch):
    import csv
    from unittest.mock import MagicMock
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    from scraper.consultantplus import ConsultantPlusScraper

    document = MagicMock()
    document.frames = []
    document.title.return_value = 'Заголовок вкладки'
    content = 'Текст судебного решения: гражданин Ёлкин — статья 3.'
    document.locator.return_value.inner_text.return_value = content
    context = Mock()
    context.new_page.return_value = document
    exporter = ConsultantPlusScraper(context, config(tmp_path))
    exporter.session.captcha_present = Mock(return_value=False)

    def reference(_page):
        document.locator.return_value.inner_text.return_value = 'Текст справки вместо решения'
        return {'Название документа (К+)': 'Название из К+', 'Примечание к документу': 'Примечание К+'}

    exporter._reference_fields = reference
    assert exporter.export_related(['https://example.test/decision'], tmp_path) == (1, 0)
    docx = next((tmp_path / 'consultantplus').glob('*.docx'))
    with ZipFile(docx) as archive:
        document_xml = ET.fromstring(archive.read('word/document.xml'))
        assert ''.join(document_xml.itertext()) == content
    assert not list(tmp_path.glob('*.rtf'))
    with (tmp_path / 'судакты.csv').open(encoding='utf-8-sig', newline='') as table:
        reader = csv.DictReader(table)
        assert reader.fieldnames == ['Связанный акт', 'Источник', 'Дата сохранения', 'Название документа', 'Текст решения', 'Примечание', 'Источник парсинга']
        row = next(reader)
        assert row['Название документа'] == 'Название из К+'
        assert row['Текст решения'] == content
        assert row['Примечание'] == 'Примечание К+'


def test_form_accepts_multiple_sources_and_ner_stub():
    values = validate_input({'sources': ['consultantplus', 'sudact'], 'login': 'test', 'password': 'secret',
                             'law': '113-ФЗ', 'ner': {'enabled': True, 'method': 'openai', 'fields': ['court']}})
    assert values['sources'] == ['consultantplus', 'sudact']
    assert values['ner']['enabled'] is True
    assert values['ner']['fields'] == ['court']
    assert values['transport'] == 'browser'


def test_open_source_form_does_not_require_credentials():
    values = validate_input({'sources': ['sudact'], 'law': '113-ФЗ'})
    assert values['all_source_options'] == {'sudact': {}}


def test_api_options_never_exposes_credentials(tmp_path):
    handler = make_handler(tmp_path, '/api/options')
    handler.do_GET()
    response = json.loads(handler.wfile.getvalue())
    assert [source['id'] for source in response['sources']] == ['consultantplus', 'sudact']
    assert response['ner']['available'] is False
    assert 'password' not in response
    assert 'api_key' not in response


def test_documents_tab_reads_real_csv_columns_only(tmp_path):
    import csv
    output = tmp_path / 'output'
    output.mkdir()
    with (output / 'судакты.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['Название документа', 'Источник', 'Источник парсинга', 'Текст решения'])
        writer.writeheader()
        writer.writerow({'Название документа': 'Определение', 'Источник': 'https://example.test/doc',
                         'Источник парсинга': 'Тестовый источник', 'Текст решения': 'Большой полный текст'})
    handler = make_handler(tmp_path, '/api/documents')
    handler.do_GET()
    assert json.loads(handler.wfile.getvalue()) == {'documents': [
        {'title': 'Определение', 'url': 'https://example.test/doc', 'source': 'Тестовый источник'}]}


def test_worker_events_update_real_progress_and_session_history(tmp_path):
    events = [
        {'type': 'status', 'phase': 'starting', 'source': 'one'},
        {'type': 'log', 'level': 'DEBUG', 'message': 'Найдено актов: 3', 'event': 'documents_found', 'count': 3, 'source': 'one'},
        {'type': 'status', 'phase': 'saved:1', 'source': 'one'},
        {'type': 'status', 'phase': 'skipped:1', 'source': 'one'},
        {'type': 'log', 'level': 'WARNING', 'message': 'Таймаут', 'event': 'document_error', 'source': 'one'},
        {'type': 'result', 'saved': 1, 'skipped': 1, 'logout_confirmed': True},
    ]
    process = Mock()
    process.stdout = io.StringIO(''.join(json.dumps(event) + '\n' for event in events))
    process.stdin = io.StringIO()
    jobs = Jobs(tmp_path)
    jobs.state.update(running=True, run_id=1)
    jobs._read(process)
    state = jobs.snapshot()
    assert state['found'] == 3
    assert state['saved'] == 1
    assert state['skipped'] == 1
    assert state['failed'] == 1
    assert len(state['logs']) == 2
    assert not state['running']
    assert jobs.history[0]['phase'] == 'done'


def test_form_passes_ner_settings_to_worker_without_exposing_api_key(tmp_path, monkeypatch):
    process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(), poll=lambda: None)
    monkeypatch.setattr('interfaces.web.app.subprocess.Popen', Mock(return_value=process))
    monkeypatch.setattr('interfaces.web.app.threading.Thread', Mock())
    jobs = Jobs(tmp_path)
    jobs.start({'sources': ['sudact'], 'law': '113-ФЗ',
                'ner': {'enabled': True, 'method': 'openai', 'fields': ['court'], 'openai_api_key': 'private-ner-key'}})
    payload = json.loads(process.stdin.getvalue())
    assert payload['config']['scraper']['sources'] == ['sudact']
    assert payload['config']['ner']['method'] == 'openai'
    assert payload['config']['ner']['fields'] == ['court']
    assert jobs.snapshot()['ner_enabled']
    assert 'private-ner-key' not in json.dumps(jobs.snapshot())
    assert any('заглушка' in text for text in jobs.snapshot()['warnings'])
