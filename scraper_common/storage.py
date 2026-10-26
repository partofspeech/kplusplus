"""Общий прогресс и CSV; документы каждого источника лежат в своей папке."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zipfile import BadZipFile, ZipFile

from scraper import get_source

FIELDS = ['Связанный акт', 'Источник', 'Дата сохранения', 'Название документа', 'Текст решения', 'Примечание', 'Источник парсинга']


def document_key(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ''))


def law_key(law: str) -> str:
    return ' '.join(law.split()).casefold()


def valid_docx(path: Path) -> bool:
    try:
        with ZipFile(path) as archive:
            return 'word/document.xml' in archive.namelist() and archive.testzip() is None
    except (OSError, BadZipFile):
        return False


class ExportStore:
    def __init__(self, directory: Path, *, document_key=document_key, normalize_row=None,
                 source_id: str = '', source_name: str = '', source_names: dict | None = None):
        self.document_key = document_key
        self.normalize_row = normalize_row or (lambda row: {name: row.get(name, '') for name in FIELDS})
        self.source_id = source_id
        self.source_name = source_name
        self.directory = directory
        self.documents_dir = directory / source_id if source_id else directory
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.csv_path = directory / 'судакты.csv'
        self.db = sqlite3.connect(directory / '.kplusplus.sqlite3')
        self.dirty = True
        self.pending_updates = 0
        try:
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, filename TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS records (
                    law TEXT NOT NULL, document TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY (law, document));
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
            ''')
            aliases = self.db.execute("SELECT value FROM metadata WHERE key='source_labels'").fetchone()
            self.source_labels = json.loads(aliases[0]) if aliases else {}
            self.source_labels.update({name: key for key, name in (source_names or {}).items()})
            if source_name:
                self.source_labels[source_name] = source_id
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('source_labels', ?)", (json.dumps(self.source_labels, ensure_ascii=False),))
            migrated = self._upgrade_legacy_records()
            imported = self.db.execute("SELECT 1 FROM metadata WHERE key='imported'").fetchone()
            pending = self.db.execute("SELECT value FROM metadata WHERE key='csv_dirty'").fetchone()
            if not imported:
                self._import_csv()
            elif pending == ('0',) and self.csv_path.exists():
                with self.csv_path.open(encoding='utf-8-sig', newline='') as stream:
                    current_columns = next(csv.reader(stream), [])
                self._import_csv()
                self.dirty = migrated or current_columns != FIELDS
            self.files = {}
            for folder in {directory, self.documents_dir}:
                for path in folder.glob('*--*.docx'):
                    self.files.setdefault(path.stem.rsplit('--', 1)[-1], []).append(path)
            self.flush()
        except BaseException:
            self.db.close()
            raise

    def _key(self, key: str, source_id: str | None = None) -> str:
        source_id = self.source_id if source_id is None else source_id
        return f'{source_id}|{key}' if source_id else key

    def _prepare_row(self, row: dict) -> tuple[str, dict]:
        label = row.get('Источник парсинга') or self.source_name
        if label and label not in self.source_labels:
            if not self.source_id:  # Standalone generic storage can preserve arbitrary labels.
                source_id = ''
            else:
                raise ValueError(f'Название источника «{label}» не найдено в настройках.')
        else:
            source_id = self.source_labels.get(label, self.source_id)
        if source_id == self.source_id:
            normalize, identity = self.normalize_row, self.document_key
        else:
            source = get_source(source_id)
            normalize = getattr(source, 'normalize_legacy_row', lambda row: {name: row.get(name, '') for name in FIELDS})
            identity = getattr(source, 'document_key', document_key)
        data = normalize(row)
        data['Источник парсинга'] = label
        return self._key(identity(data['Источник']), source_id), data

    def _upgrade_legacy_records(self) -> bool:
        changed = False
        with self.db:
            for law, key, raw in list(self.db.execute("SELECT law, document, data FROM records WHERE instr(document, '|')=0")):
                if '|' in key:
                    continue
                row = json.loads(raw)
                new_key, data = self._prepare_row(row)
                if new_key == key and data == row:
                    continue
                self.db.execute('DELETE FROM records WHERE law=? AND document=?', (law, key))
                self.db.execute('INSERT OR IGNORE INTO records VALUES (?, ?, ?)', (law, new_key, json.dumps(data, ensure_ascii=False)))
                self.db.execute('UPDATE OR IGNORE documents SET id=? WHERE id=?', (new_key, key))
                changed = True
        return changed

    def _import_csv(self):
        csv.field_size_limit(2**31 - 1)
        with self.db:
            if self.csv_path.exists() and self.csv_path.stat().st_size:
                with self.csv_path.open(encoding='utf-8-sig', newline='') as stream:
                    reader = csv.DictReader(stream, strict=True)
                    if not reader.fieldnames or not {'Связанный акт', 'Источник', 'Текст решения'} <= set(reader.fieldnames):
                        raise ValueError('Существующая таблица имеет неизвестный формат; выберите другую папку.')
                    for row in reader:
                        if not row.get('Источник') or None in row or any(value is None for value in row.values()):
                            raise ValueError('Существующая CSV повреждена; исходный файл сохранён без изменений.')
                        key, data = self._prepare_row(row)
                        self.db.execute('INSERT INTO records VALUES (?, ?, ?) ON CONFLICT(law, document) DO UPDATE SET data=excluded.data',
                                        (law_key(data['Связанный акт']), key, json.dumps(data, ensure_ascii=False)))
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('imported', '1')")

    def row(self, law: str, key: str) -> dict | None:
        record = self.db.execute('SELECT data FROM records WHERE law=? AND document=?', (law_key(law), self._key(key))).fetchone()
        return json.loads(record[0]) if record else None

    def file(self, key: str, url: str, row: dict | None) -> Path | None:
        stored = self.db.execute('SELECT filename FROM documents WHERE id=?', (self._key(key),)).fetchone()
        candidates = [self.directory / stored[0]] if stored else []
        for value in (key, url, row['Источник'] if row else ''):
            candidates.extend(self.files.get(hashlib.sha256(value.encode()).hexdigest()[:12], []))
        path = next((candidate for candidate in candidates if valid_docx(candidate)), None)
        if path is not None and path.parent != self.documents_dir:
            destination = self.documents_dir / path.name
            if destination.exists() and not valid_docx(destination):
                raise ValueError(f'Нельзя перенести документ: файл {destination.name} уже существует и повреждён.')
            if not destination.exists():
                path.replace(destination)
            path = destination
        if path is not None:
            with self.db:
                self.db.execute('INSERT INTO documents VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET filename=excluded.filename',
                                (self._key(key), str(path.relative_to(self.directory))))
        return path

    def record(self, key: str, filename: str, row: dict):
        row = {**row, 'Источник парсинга': self.source_name or row.get('Источник парсинга', '')}
        is_new = self.row(row['Связанный акт'], key) is None
        relative_file = str((self.documents_dir / filename).relative_to(self.directory))
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('csv_dirty', '1')")
            self.db.execute('INSERT INTO documents VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET filename=excluded.filename', (self._key(key), relative_file))
            self.db.execute('INSERT INTO records VALUES (?, ?, ?) ON CONFLICT(law, document) DO UPDATE SET data=excluded.data',
                            (law_key(row['Связанный акт']), self._key(key), json.dumps(row, ensure_ascii=False)))
        if is_new and not self.dirty:
            self.dirty = True
            with self.csv_path.open('a', encoding='utf-8', newline='') as stream:
                csv.DictWriter(stream, fieldnames=FIELDS).writerow(row)
                stream.flush()
                os.fsync(stream.fileno())
            self.dirty = False
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('csv_dirty', '0')")
        else:
            self.dirty = True
            self.pending_updates += 1
            if self.pending_updates >= 25:
                self.flush()

    def flush(self):
        if not self.dirty:
            return
        temporary = self.csv_path.with_suffix('.csv.tmp')
        try:
            with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                for data, in self.db.execute('SELECT data FROM records ORDER BY rowid'):
                    row = json.loads(data)
                    writer.writerow({name: row.get(name, '') for name in FIELDS})
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.csv_path)
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('csv_dirty', '0')")
            self.dirty = False
            self.pending_updates = 0
        finally:
            temporary.unlink(missing_ok=True)

    def close(self):
        try:
            self.flush()
        finally:
            self.db.close()
