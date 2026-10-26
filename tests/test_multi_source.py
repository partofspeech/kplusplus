import csv
from unittest.mock import Mock

from scraper_common.config import config_from_mapping
from scraper_common.documents import write_docx
from scraper.runner import run_export
from scraper import get_source
from scraper_common.storage import ExportStore, FIELDS, document_key


def config(tmp_path, names=('Консультант+', 'Судакт.ру')):
    return config_from_mapping({
        'scraper': {'sources': ['consultantplus', 'sudact']},
        'sources': {'consultantplus': {'name': names[0], 'login': 'test', 'password': 'secret'},
                    'sudact': {'name': names[1]}},
        'search': {'query': '113-ФЗ'},
        'export': {'directory': str(tmp_path / 'output')},
    }, use_environment=False)


def test_implemented_source_runs_and_stub_does_not_interrupt_cycle(tmp_path, monkeypatch, caplog):
    cfg = config(tmp_path)
    run_source = Mock(return_value={'saved': 3, 'skipped': 2, 'logout_confirmed': True})
    monkeypatch.setattr('scraper.runner.run_source', run_source)
    result = run_export(cfg, tmp_path / 'runtime')
    assert result['saved'] == 3
    assert result['skipped_sources'] == ['sudact']
    assert run_source.call_count == 1
    selected_config = run_source.call_args.args[0]
    assert selected_config.source == 'consultantplus'
    assert selected_config.source_name == 'Консультант+'
    assert 'Судакт.ру' in caplog.text


def test_two_sources_share_csv_and_resume_in_separate_directories(tmp_path, monkeypatch):
    cfg = config(tmp_path, names=('Мой Консультант', 'Мой Судакт'))
    monkeypatch.setattr('scraper.runner.get_scraper_class', lambda source: Mock(supported=True))
    calls = []

    def run_source(selected, runtime_dir, scraper_class, cancelled):
        calls.append(selected.source)
        module = get_source(selected.source)
        identity = getattr(module, 'document_key', document_key)
        store = ExportStore(selected.directory, source_id=selected.source, source_name=selected.source_name,
                            source_names=selected.source_names, document_key=identity,
                            normalize_row=getattr(module, 'normalize_legacy_row', None))
        url = 'https://example.test/doc?base=TEST&n=123'
        key = identity(url)
        try:
            previous = store.row(selected.query, key)
            if previous is not None and store.file(key, url, previous):
                return {'saved': 0, 'skipped': 1}
            write_docx(store.documents_dir / 'Решение.docx', 'Текст из ' + selected.source_name)
            store.record(key, 'Решение.docx', {
                'Связанный акт': selected.query, 'Источник': url, 'Дата сохранения': '26.10.2026',
                'Название документа': 'Решение', 'Текст решения': 'Текст из ' + selected.source_name,
                'Примечание': '',
            })
            return {'saved': 1, 'skipped': 0}
        finally:
            store.close()

    monkeypatch.setattr('scraper.runner.run_source', run_source)
    result = run_export(cfg, tmp_path / 'runtime')
    assert result['saved'] == 2
    assert calls == ['consultantplus', 'sudact']
    assert (cfg.directory / 'consultantplus' / 'Решение.docx').is_file()
    assert (cfg.directory / 'sudact' / 'Решение.docx').is_file()
    with (cfg.directory / 'судакты.csv').open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == FIELDS
        rows = list(reader)
    assert [row['Источник парсинга'] for row in rows] == ['Мой Консультант', 'Мой Судакт']
    result = run_export(cfg, tmp_path / 'runtime')
    assert result['saved'] == 0
    assert result['skipped'] == 2
    with (cfg.directory / 'судакты.csv').open(encoding='utf-8-sig', newline='') as stream:
        assert len(list(csv.DictReader(stream))) == 2


def test_legacy_flat_export_is_moved_and_not_downloaded_again(tmp_path):
    import hashlib
    from scraper.consultantplus.identity import document_key as consultant_key
    url = 'https://demo.consultant.ru/cgi/online.cgi?req=doc&base=ARB&n=123'
    filename = 'Старый документ--' + hashlib.sha256(url.encode()).hexdigest()[:12] + '.docx'
    write_docx(tmp_path / filename, 'Старый текст')
    old_fields = [field for field in FIELDS if field != 'Источник парсинга']
    old_row = dict(zip(old_fields, ['113-ФЗ', url, '26.10.2026', 'Старый документ', 'Старый текст', '']))
    with (tmp_path / 'судакты.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=old_fields)
        writer.writeheader()
        writer.writerow(old_row)
    store = ExportStore(tmp_path, source_id='consultantplus', source_name='Консультант+',
                        document_key=consultant_key)
    try:
        key = consultant_key(url)
        imported = store.row('113-ФЗ', key)
        assert imported['Источник парсинга'] == 'Консультант+'
        assert store.file(key, url, imported) == tmp_path / 'consultantplus' / filename
        assert not (tmp_path / filename).exists()
    finally:
        store.close()


def test_source_names_are_read_from_configuration(tmp_path):
    cfg = config(tmp_path, names=('Подпись А', 'Подпись Б'))
    assert [(item.key, item.name) for item in cfg.sources] == [
        ('consultantplus', 'Подпись А'), ('sudact', 'Подпись Б'),
    ]


def test_legacy_sqlite_progress_and_csv_are_migrated_together(tmp_path):
    import json
    import sqlite3
    from scraper.consultantplus.identity import document_key as consultant_key
    url = 'https://demo.consultant.ru/cgi/online.cgi?req=doc&base=ARB&n=123'
    key = consultant_key(url)
    filename = 'Старый документ.docx'
    write_docx(tmp_path / filename, 'Текст')
    old_fields = FIELDS[:-1]
    old_row = dict(zip(old_fields, ['113-ФЗ', url, '26.10.2026', 'Документ', 'Текст', '']))
    with (tmp_path / 'судакты.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=old_fields)
        writer.writeheader()
        writer.writerow(old_row)
    db = sqlite3.connect(tmp_path / '.kplusplus.sqlite3')
    db.executescript('''
        CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT NOT NULL);
        CREATE TABLE records (law TEXT, document TEXT, data TEXT, PRIMARY KEY (law, document));
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO metadata VALUES ('imported', '1');
        INSERT INTO metadata VALUES ('csv_dirty', '0');
    ''')
    db.execute('INSERT INTO documents VALUES (?, ?)', (key, filename))
    db.execute('INSERT INTO records VALUES (?, ?, ?)', ('113-фз', key, json.dumps(old_row)))
    db.commit()
    db.close()
    store = ExportStore(tmp_path, source_id='consultantplus', source_name='Консультант+', document_key=consultant_key)
    try:
        imported = store.row('113-ФЗ', key)
        assert imported['Текст решения'] == 'Текст'
        assert store.file(key, url, imported) == tmp_path / 'consultantplus' / filename
        assert store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0] == 1
    finally:
        store.close()
