"""Loopback-only browser UI. No credentials are written to disk."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scraper import DEFAULT_SOURCE, get_source

ASSETS = Path(__file__).with_name('static')


def validate_input(data: dict) -> dict:
    source_name = data.get('source', DEFAULT_SOURCE)
    source = get_source(source_name)
    values = {'source': source_name, 'source_options': source.form_options(data)}
    for key, label in [('law', 'Федеральный закон')]:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError(f'Заполните поле «{label}» (до 2000 символов).')
        values[key] = value if key == 'password' else value.strip()
    if not isinstance(data.get('debug', False), bool):
        raise ValueError('Некорректное значение режима отладки.')
    values['debug'] = data.get('debug', False)
    values['overwrite'] = data.get('overwrite', False)
    if not isinstance(values['overwrite'], bool):
        raise ValueError('Некорректное значение перезаписи файлов.')
    values['transport'] = data.get('transport', 'browser')
    if values['transport'] not in ('browser', 'hybrid'):
        raise ValueError('Некорректный режим получения документов.')
    return values


def open_folder(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'darwin':
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
        # A separate process gives Tk its own main thread on Linux.
        command = [sys.executable, '-m', 'interfaces.web.folder_picker']
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
        self.state = {'running': False, 'phase': 'idle', 'saved': 0, 'skipped': 0,
                      'error': '', 'logout': None, 'directory': str(self.output_root),
                      'save_directory': str(self.output_root), 'http_texts': 0, 'browser_texts': 0}

    def snapshot(self):
        with self.lock:
            return dict(self.state)

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
                'scraper': {'source': values['source']},
                'sources': {values['source']: values['source_options']},
                'search': {'query': values['law']},
                'export': {'directory': str(output), 'transport': values['transport'], 'headless': not values['debug'],
                           'slow_mo_ms': 100 if values['debug'] else 0, 'overwrite': values['overwrite']},
            }
            process = subprocess.Popen(
                [sys.executable, '-u', '-m', 'interfaces.web.worker'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', cwd=str(self.root),
            )
            self.process = process
            self.state = {'running': True, 'phase': 'starting', 'saved': 0, 'skipped': 0,
                          'error': '', 'logout': None, 'directory': str(output),
                          'save_directory': str(self.output_root), 'http_texts': 0, 'browser_texts': 0}
            try:
                process.stdin.write(json.dumps({'config': config, 'runtime_dir': str(self.root / '.playwright')}) + '\n')
                process.stdin.flush()
            except (OSError, BrokenPipeError):
                self.state.update(running=False, phase='failed', error='Не удалось запустить процесс парсера.')
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
                        self.state[key] = int(count)
                    if phase in ('logged-out', 'logout-unconfirmed'):
                        self.state['logout'] = phase == 'logged-out'
                elif event.get('type') == 'result':
                    self.state.update(saved=event['saved'], skipped=event['skipped'],
                                      logout=event['logout_confirmed'], phase='done',
                                      http_texts=event.get('http_texts', 0), browser_texts=event.get('browser_texts', 0))
                elif event.get('type') == 'error':
                    self.state.update(error=event['message'], phase='stopped' if event.get('cancelled') else 'failed')
        process.wait()
        with self.lock:
            if self.state['phase'] not in ('done', 'stopped', 'failed'):
                self.state.update(phase='failed', error='Процесс неожиданно завершился. Выход из системы не подтверждён.')
            self.state['running'] = False
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
            # Cooperative stop preserves server logout.
            process.wait()
        server.server_close()


if __name__ == '__main__':
    main()
