"""Loopback-only browser UI. No credentials are written to disk."""
from __future__ import annotations

import argparse
import csv
import hmac
import json
import os
import secrets
import subprocess
import sys
import threading
from datetime import datetime, timezone
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scraper import DEFAULT_SOURCE, SOURCE_MODULES, get_source
from ner import FIELD_LABELS, parse_config as parse_ner_config

ASSETS = Path(__file__).with_name('static')


def validate_input(data: dict) -> dict:
    source_keys = data.get('sources', [data.get('source', DEFAULT_SOURCE)])
    if not isinstance(source_keys, list) or not source_keys or not all(isinstance(key, str) for key in source_keys):
        raise ValueError('Выберите хотя бы один источник.')
    source_keys = list(dict.fromkeys(source_keys))
    all_options = {key: get_source(key).form_options(data) for key in source_keys}
    values = {'sources': source_keys, 'source': source_keys[0],
              'all_source_options': all_options, 'source_options': all_options[source_keys[0]]}
    law = data.get('law')
    if not isinstance(law, str) or not law.strip() or len(law) > 2000:
        raise ValueError('Заполните поле «Федеральный закон» (до 2000 символов).')
    values['law'] = law.strip()
    for flag in ('debug', 'overwrite'):
        if not isinstance(data.get(flag, False), bool):
            raise ValueError(f'Некорректное значение {flag}.')
        values[flag] = data.get(flag, False)
    values['transport'] = data.get('transport', 'browser')
    if values['transport'] not in ('browser', 'hybrid'):
        raise ValueError('Некорректный режим получения документов.')
    ner = parse_ner_config(data.get('ner', {}), use_environment=False)
    values['ner'] = {'enabled': ner.enabled, 'method': ner.method,
                     'fields': list(ner.fields), 'openai_api_key': ner.api_key}
    return values


def open_folder(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'win32':
        os.startfile(str(path))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path)])


def choose_folder() -> Path | None:
    if sys.platform == 'darwin':
        script = ('try\nreturn POSIX path of (choose folder with prompt '
                  '"Выберите папку для сохранения документов")\n'
                  'on error number -128\nreturn ""\nend try')
        command = ['osascript', '-e', script]
    else:
        # A separate process gives Tk its own main thread on Windows/Linux.
        command = [sys.executable, '-X', 'utf8', '-m', 'interfaces.web.folder_picker']
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise ValueError('Не удалось открыть окно выбора папки. Проверьте доступность системного интерфейса.')
    selected = result.stdout.strip()
    return Path(selected).resolve() if selected else None


class Jobs:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.lock = threading.RLock()
        self.process = None
        self.output_root = self.root / 'output'
        self.run_number = 0
        self.history = []
        self.source_counts = {}
        self.found_counts = {}
        self.state = self.new_state()

    def new_state(self):
        return {'running': False, 'phase': 'idle', 'saved': 0, 'skipped': 0, 'failed': 0,
                'found': None, 'error': '', 'logout': None, 'directory': str(self.output_root),
                'save_directory': str(self.output_root), 'http_texts': 0, 'browser_texts': 0,
                'run_id': self.run_number, 'started_at': None, 'finished_at': None,
                'sources': [], 'logs': [], 'warnings': [], 'ner_enabled': False}

    def snapshot(self):
        with self.lock:
            return {**self.state, 'logs': list(self.state['logs']), 'warnings': list(self.state['warnings'])}

    def select_folder(self):
        with self.lock:
            if self.state['running']:
                raise ValueError('Дождитесь завершения выгрузки перед сменой папки.')
        selected = choose_folder()
        if selected is not None:
            with self.lock:
                if self.state['running']:
                    raise ValueError('Парсер уже запущен. Выберите папку после завершения выгрузки.')
                self.output_root = selected
                self.state['save_directory'] = str(selected)
                if self.state['phase'] == 'idle':
                    self.state['directory'] = str(selected)

    def start(self, data):
        values = validate_input(data)
        with self.lock:
            if self.state['running']:
                raise ValueError('Парсер уже работает.')
            output = self.output_root
            config = {
                'scraper': {'sources': values['sources']},
                'sources': {key: {'name': get_source(key).Scraper.source_name, **options}
                            for key, options in values['all_source_options'].items()},
                'ner': values['ner'],
                'search': {'query': values['law']},
                'export': {'directory': str(output), 'transport': values['transport'], 'headless': not values['debug'],
                           'slow_mo_ms': 100 if values['debug'] else 0, 'overwrite': values['overwrite']},
            }
            process = subprocess.Popen(
                [sys.executable, '-X', 'utf8', '-u', '-m', 'interfaces.web.worker'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', cwd=str(self.root),
            )
            self.process = process
            self.run_number += 1
            self.source_counts = {}
            self.found_counts = {}
            self.state = self.new_state()
            self.state.update(running=True, phase='starting',
                              started_at=datetime.now(timezone.utc).isoformat(),
                              sources=[get_source(key).Scraper.source_name for key in values['sources']],
                              ner_enabled=values['ner']['enabled'])
            for key in values['sources']:
                if not get_source(key).Scraper.supported:
                    self.state['warnings'].append(f'{get_source(key).Scraper.source_name}: источник пока не реализован и будет пропущен.')
            if values['ner']['enabled']:
                self.state['warnings'].append('Извлечение данных — заглушка. Документы будут сохранены без дополнительных полей.')
            try:
                process.stdin.write(json.dumps({'config': config, 'runtime_dir': str(self.root / '.playwright')}) + '\n')
                process.stdin.flush()
            except (OSError, BrokenPipeError):
                self.state.update(running=False, phase='failed', failed=1,
                                  finished_at=datetime.now(timezone.utc).isoformat(),
                                  error='Не удалось запустить процесс парсера.')
                process.stdin.close()
                process.wait()
                raise ValueError(self.state['error']) from None
            threading.Thread(target=self._read, args=(process,), daemon=True).start()

    def _read(self, process):
        for line in process.stdout:
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                continue  # Never expose raw worker output (which could contain credentials).
            with self.lock:
                if event.get('type') == 'status':
                    phase = event['phase']
                    self.state['phase'] = phase
                    if phase.startswith(('saved:', 'skipped:')):
                        key, count = phase.split(':')
                        source = event.get('source') or 'current'
                        self.source_counts.setdefault(source, {})[key] = int(count)
                        self.state[key] = sum(counts.get(key, 0) for counts in self.source_counts.values())
                    if phase in ('logged-out', 'logout-unconfirmed'):
                        self.state['logout'] = phase == 'logged-out'
                elif event.get('type') == 'log':
                    item = {'time': datetime.now().strftime('%H:%M:%S'),
                            'level': event.get('level', 'INFO'), 'message': event.get('message', '')}
                    self.state['logs'].append(item)
                    del self.state['logs'][:-500]
                    if event.get('event') == 'documents_found':
                        self.found_counts[event.get('source') or 'current'] = event['count']
                        self.state['found'] = sum(self.found_counts.values())
                    if event.get('event') == 'document_error':
                        self.state['failed'] += 1
                elif event.get('type') == 'result':
                    self.state.update(saved=event['saved'], skipped=event['skipped'],
                                      logout=event['logout_confirmed'], phase='done',
                                      http_texts=event.get('http_texts', 0), browser_texts=event.get('browser_texts', 0))
                elif event.get('type') == 'error':
                    if not event.get('cancelled'):
                        self.state['failed'] += 1
                    self.state.update(error=event['message'], phase='stopped' if event.get('cancelled') else 'failed')
        process.wait()
        with self.lock:
            if self.state['phase'] not in ('done', 'stopped', 'failed'):
                self.state.update(phase='failed', failed=self.state['failed'] + 1,
                                  error='Процесс неожиданно завершился. Выход из системы не подтверждён.')
            self.state['running'] = False
            self.state['finished_at'] = datetime.now(timezone.utc).isoformat()
            self.history.append({key: self.state[key] for key in ('run_id', 'started_at', 'finished_at', 'phase', 'saved', 'skipped', 'failed', 'sources')})
            self.history = self.history[-50:]
            process.stdin.close()
            process.stdout.close()

    def stop(self):
        with self.lock:
            if self.state['running'] and self.process.poll() is None:
                try:
                    self.process.stdin.write('stop\n')
                    self.process.stdin.flush()
                    self.state['phase'] = 'stopping'
                except (OSError, BrokenPipeError):
                    pass


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, root: Path):
        self.token = secrets.token_urlsafe(32)
        self.jobs = Jobs(root)
        super().__init__(('127.0.0.1', port), Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, status, body, content_type='application/json; charset=utf-8'):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def trusted(self):
        expected = f'127.0.0.1:{self.server.server_port}'
        return (self.headers.get('Host') == expected
                and self.headers.get('Origin', f'http://{expected}') == f'http://{expected}')

    def authorized(self):
        return self.trusted() and hmac.compare_digest(self.headers.get('X-App-Token', ''), self.server.token)

    def do_GET(self):
        if not self.trusted():
            return self.respond(403, {'error': 'Доступ запрещён.'})
        if self.path == '/api/documents':
            if not self.authorized():
                return self.respond(403, {'error': 'Доступ запрещён.'})
            table = Path(self.server.jobs.snapshot()['directory']) / 'судакты.csv'
            documents = []
            try:
                if table.exists():
                    csv.field_size_limit(2**31 - 1)
                    with table.open(encoding='utf-8-sig', newline='') as stream:
                        for index, row in enumerate(csv.DictReader(stream)):
                            if index >= 200:
                                break
                            if row.get('Название документа') and row.get('Источник'):
                                documents.append({'title': row['Название документа'], 'url': row['Источник'],
                                                  'source': row.get('Источник парсинга', '')})
            except (OSError, csv.Error):
                return self.respond(409, {'error': 'Таблица сейчас обновляется. Повторите открытие вкладки.'})
            return self.respond(200, {'documents': documents})
        if self.path in ('/api/options', '/api/runs'):
            if not self.authorized():
                return self.respond(403, {'error': 'Доступ запрещён.'})
            if self.path == '/api/runs':
                with self.server.jobs.lock:
                    return self.respond(200, {'runs': list(self.server.jobs.history)})
            return self.respond(200, {
                'sources': [{'id': key, 'name': get_source(key).Scraper.source_name,
                             'supported': get_source(key).Scraper.supported,
                             'requires_credentials': getattr(get_source(key), 'requires_credentials', False),
                             'mark': getattr(get_source(key), 'ui_mark', ''),
                             'icon': getattr(get_source(key), 'ui_icon', 'file'),
                             'description': getattr(get_source(key), 'ui_description', '')}
                            for key in SOURCE_MODULES],
                'default_source': DEFAULT_SOURCE,
                'ner': {'available': False, 'fields': FIELD_LABELS},
            })
        if self.path == '/api/status':
            if not self.authorized():
                return self.respond(403, {'error': 'Доступ запрещён.'})
            return self.respond(200, self.server.jobs.snapshot())
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if self.path not in assets:
            return self.respond(404, {'error': 'Не найдено.'})
        name, content_type = assets[self.path]
        body = (ASSETS / name).read_bytes()
        if name == 'index.html':
            body = body.replace(b'__APP_TOKEN__', self.server.token.encode())
        self.respond(200, body, content_type)

    def do_POST(self):
        if not self.authorized():
            return self.respond(403, {'error': 'Доступ запрещён.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 16000:
                return self.respond(413, {'error': 'Слишком большой запрос.'})
            data = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(data, dict):
                raise ValueError('Некорректный запрос.')
            if self.path == '/api/start':
                self.server.jobs.start(data)
            elif self.path == '/api/stop':
                self.server.jobs.stop()
            elif self.path == '/api/choose-folder':
                self.server.jobs.select_folder()
            elif self.path == '/api/open-folder':
                open_folder(Path(self.server.jobs.snapshot()['directory']))
            else:
                return self.respond(404, {'error': 'Не найдено.'})
            self.respond(200, self.server.jobs.snapshot())
        except (ValueError, OSError) as error:
            self.respond(400, {'error': str(error)})


def main():
    parser = argparse.ArgumentParser(description='Локальное приложение Kplusplus')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--data-dir', type=Path, default=Path.cwd())
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    server = AppServer(args.port, args.data_dir)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Kplusplus: {url}\nДля закрытия приложения нажмите Ctrl+C.', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print('Завершаю парсер и выполняю выход из системы…', flush=True)
    finally:
        server.jobs.stop()
        process = server.jobs.process
        if process and process.poll() is None:
            # Cooperative stop preserves server logout on Windows as well.
            process.wait()
        server.server_close()


if __name__ == '__main__':
    main()
