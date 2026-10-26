import csv
from unittest.mock import MagicMock, Mock

import pytest

from scraper.consultantplus.scraper import ConsultantPlusScraper, _safe_name
from scraper_common.config import config_from_mapping
from scraper_common.documents import write_docx
from scraper_common.storage import ExportStore, FIELDS
from scraper.consultantplus.identity import document_key

URL = 'https://demo.consultant.ru/cgi/online.cgi?req=doc&base=ARB&n=123&cacheid=old&rnd=old'
NEW_URL = 'https://full.consultant.ru/cgi/online.cgi?rnd=new&req=doc&base=ARB&n=123&mode=backrefs'
LAW = 'Федеральный закон N 113-ФЗ'


def row(url=URL, text='Текст решения', law=LAW):
    return dict(zip(FIELDS, [law, url, '26.10.2026', 'Название из К+', text, 'Примечание', 'Консультант+']))


def rows(directory):
    with (directory / 'судакты.csv').open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def exporter(tmp_path, *, overwrite=False, fail_on=None):
    cfg = config_from_mapping({'consultant': {'login': 'user', 'password': 'secret'},
                               'search': {'query': LAW}, 'export': {'overwrite': overwrite}}, use_environment=False)
    document = MagicMock()
    document.frames = []
    document.title.return_value = 'Название вкладки'
    document.locator.return_value.inner_text.return_value = 'Обновлённый текст решения'
    context = Mock()
    context.new_page.return_value = document
    if fail_on:
        document.goto.side_effect = fail_on
    instance = ConsultantPlusScraper(context, cfg)
    instance.session.captcha_present = Mock(return_value=False)
    instance._reference_fields = Mock(return_value={'Название документа (К+)': 'Новое название из К+'})
    return instance, context


def test_document_identity_ignores_transient_parameters_and_subscription_host():
    assert document_key(URL) == document_key(NEW_URL) == 'ARB:123'
    assert document_key(URL.replace('n=123', 'n=124')) != document_key(URL)


def test_resume_skips_document_without_opening_browser_and_preserves_row(tmp_path):
    instance, context = exporter(tmp_path)
    assert instance.export_related([URL], tmp_path) == (1, 0)
    before_rows = rows(tmp_path)
    before_files = {p.name: p.read_bytes() for p in (tmp_path / 'consultantplus').glob('*.docx')}
    assert instance.export_related([NEW_URL], tmp_path) == (0, 1)
    assert context.new_page.call_count == 1
    assert rows(tmp_path) == before_rows
    assert {p.name: p.read_bytes() for p in (tmp_path / 'consultantplus').glob('*.docx')} == before_files


def test_overwrite_updates_existing_file_and_row_without_duplicates(tmp_path):
    instance, _ = exporter(tmp_path)
    instance.export_related([URL], tmp_path)
    original_name = next((tmp_path / 'consultantplus').glob('*.docx')).name
    other = row(URL.replace('n=123', 'n=999'), 'Чужая строка')
    store = ExportStore(tmp_path, document_key=document_key)
    store.record(document_key(other['Источник']), 'unrelated.docx', other)
    store.close()
    instance, context = exporter(tmp_path, overwrite=True)
    context.new_page.return_value.locator.return_value.inner_text.return_value = 'Новый текст'
    assert instance.export_related([NEW_URL, URL], tmp_path) == (1, 0)
    result = rows(tmp_path)
    assert len(result) == 2
    assert result[0]['Текст решения'] == 'Новый текст'
    assert result[1] == other
    assert [p.name for p in (tmp_path / 'consultantplus').glob('*.docx')] == [original_name]


def test_exception_preserves_successful_documents_and_allows_resume(tmp_path):
    instance, context = exporter(tmp_path, fail_on=[None, RuntimeError('connection lost')])
    second = URL.replace('n=123', 'n=456')
    with pytest.raises(RuntimeError, match='connection lost'):
        instance.export_related([URL, second], tmp_path)
    assert len(rows(tmp_path)) == 1
    instance, context = exporter(tmp_path)
    assert instance.export_related([NEW_URL, second], tmp_path) == (1, 1)
    assert context.new_page.call_count == 1
    assert len(rows(tmp_path)) == 2


def test_missing_or_corrupt_docx_is_recreated_without_duplicate_row(tmp_path):
    instance, context = exporter(tmp_path)
    instance.export_related([URL], tmp_path)
    next((tmp_path / 'consultantplus').glob('*.docx')).write_bytes(b'interrupted file')
    assert instance.export_related([NEW_URL], tmp_path) == (1, 0)
    assert len(rows(tmp_path)) == 1
    assert len(list((tmp_path / 'consultantplus').glob('*.docx'))) == 1


def test_imports_legacy_csv_and_legacy_url_based_filename(tmp_path):
    existing = row(text='Исходный текст')
    name = _safe_name('Старое название', URL, '.docx')
    write_docx(tmp_path / name, existing['Текст решения'])
    with (tmp_path / 'судакты.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(existing)
    instance, context = exporter(tmp_path)
    assert instance.export_related([NEW_URL], tmp_path) == (0, 1)
    context.new_page.assert_not_called()
    assert rows(tmp_path) == [existing]
    assert len(list((tmp_path / 'consultantplus').glob('*.docx'))) == 1


def test_repairs_csv_after_commit_followed_by_interruption(tmp_path):
    store = ExportStore(tmp_path, document_key=document_key)
    original = row()
    name = _safe_name('Название', document_key(URL), '.docx')
    write_docx(tmp_path / name, original['Текст решения'])
    store.record(document_key(URL), name, original)
    updated = row(NEW_URL, 'Сохранённое обновление')
    store.record(document_key(URL), name, updated)
    # Simulate a hard interruption before the CSV projection was refreshed.
    store.db.close()
    (tmp_path / 'судакты.csv').write_text('partial CSV', encoding='utf-8')
    recovered = ExportStore(tmp_path, document_key=document_key)
    assert rows(tmp_path) == [updated]
    recovered.close()


def test_imports_large_decision_text(tmp_path):
    existing = row(text='Судебный акт. ' * 30000)
    with (tmp_path / 'судакты.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(existing)
    store = ExportStore(tmp_path, document_key=document_key)
    assert store.row(LAW, document_key(URL)) == existing
    store.close()


def test_corrupt_legacy_csv_is_not_truncated(tmp_path):
    path = tmp_path / 'судакты.csv'
    path.write_text('Название,Неизвестное поле\nА,Б\n', encoding='utf-8')
    original = path.read_bytes()
    with pytest.raises(ValueError):
        ExportStore(tmp_path, document_key=document_key)
    assert path.read_bytes() == original


def test_preserves_user_edits_to_existing_rows_on_normal_resume(tmp_path):
    instance, _ = exporter(tmp_path)
    instance.export_related([URL], tmp_path)
    existing = rows(tmp_path)
    existing[0]['Примечание'] = 'Моя заметка в таблице'
    with (tmp_path / 'судакты.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(existing)
    instance, _ = exporter(tmp_path)
    assert instance.export_related([NEW_URL, URL.replace('n=123', 'n=999')], tmp_path) == (1, 1)
    assert rows(tmp_path)[0]['Примечание'] == 'Моя заметка в таблице'


def test_generic_storage_does_not_apply_consultant_url_rules():
    from scraper_common.storage import document_key as generic_document_key
    first = 'https://first.test/decision?base=ABC&n=123&mode=first'
    second = 'https://second.test/decision?base=ABC&n=123&mode=second'
    assert generic_document_key(first) != generic_document_key(second)
    assert document_key(first) == document_key(second)


def test_consultant_adapter_imports_legacy_reference_columns(tmp_path):
    from scraper.consultantplus.identity import normalize_legacy_row
    existing = row()
    existing['Название документа (К+)'] = 'Заголовок К+ из старой таблицы'
    existing['Примечание к документу'] = 'Старое примечание К+'
    with (tmp_path / 'судакты.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(existing))
        writer.writeheader()
        writer.writerow(existing)
    store = ExportStore(tmp_path, document_key=document_key, normalize_row=normalize_legacy_row)
    try:
        imported = store.row(LAW, document_key(URL))
        assert imported['Название документа'] == existing['Название документа (К+)']
        assert imported['Примечание'] == existing['Примечание к документу']
    finally:
        store.close()
