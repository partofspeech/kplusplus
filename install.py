#!/usr/bin/env python3
"""Установка приложения на Windows, macOS и Linux. Нужен Python 3.11+."""
from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path
import shlex
import subprocess
import sys
from datetime import datetime

MIN_PYTHON = (3, 11)
SUPPORTED_SYSTEMS = {'Windows', 'Darwin', 'Linux'}


def environment_python(environment_dir: Path, system: str) -> Path:
    return environment_dir / ('Scripts/python.exe' if system == 'Windows' else 'bin/python')


def environment_is_usable(python: Path, environment_dir: Path, system: str) -> bool:
    if not python.is_file():
        return False
    probe = 'import pip,json,sys,platform; print(json.dumps([list(sys.version_info[:2]),sys.prefix,platform.system()]))'
    try:
        result = subprocess.run([str(python), '-c', probe], capture_output=True, text=True, timeout=15)
        version, prefix, installed_system = json.loads(result.stdout)
        return (result.returncode == 0 and tuple(version) >= MIN_PYTHON
                and Path(prefix).resolve() == environment_dir.resolve() and installed_system == system)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def command_text(command: list[str]) -> str:
    if platform.system() == 'Windows':
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def run_step(title: str, command: list[str], root: Path, *, dry_run: bool):
    print('\n' + title, flush=True)
    print('  ' + command_text(command), flush=True)
    if not dry_run:
        subprocess.run(command, cwd=root, check=True)


def install(root: Path, *, system: str | None = None, dev: bool = False,
            skip_system_deps: bool = False, dry_run: bool = False):
    system = system or platform.system()
    if system not in SUPPORTED_SYSTEMS:
        raise RuntimeError(f'ОС {system} не поддерживается установщиком.')
    root = root.resolve()
    environment_dir = root / '.venv'
    python = environment_python(environment_dir, system)
    print(f'ОС: {system}; архитектура: {platform.machine()}; Python: {platform.python_version()}', flush=True)
    print(f'Папка приложения: {root}', flush=True)
    if not environment_is_usable(python, environment_dir, system):
        if environment_dir.exists():
            backup = root / ('.venv.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            print(f'Старое окружение будет сохранено в {backup.name}', flush=True)
            if not dry_run:
                environment_dir.rename(backup)
        run_step('Создаём Python-окружение', [sys.executable, '-m', 'venv', str(environment_dir)], root, dry_run=dry_run)
    else:
        print('Используем существующее исправное .venv.', flush=True)

    target = str(root) + ('[test]' if dev else '')
    run_step('Устанавливаем приложение и зависимости',
             [str(python), '-m', 'pip', 'install', '-e', target], root, dry_run=dry_run)
    browser_command = [str(python), '-m', 'playwright', 'install']
    if system == 'Linux' and not skip_system_deps:
        print('Linux: системные зависимости Chromium могут потребовать sudo.', flush=True)
        browser_command.append('--with-deps')
    browser_command.append('chromium')
    run_step('Устанавливаем Chromium', browser_command, root, dry_run=dry_run)

    gui_check = 'import tkinter; ' if system == 'Windows' else ''
    run_step('Проверяем импорты и запуск Chromium без авторизации', [str(python), '-c',
             gui_check + 'import interfaces.cli, interfaces.web.app, scraper.runner; '
             'from playwright.sync_api import sync_playwright; '
             '\nwith sync_playwright() as p:\n    browser = p.chromium.launch(headless=True)\n    browser.close()'],
             root, dry_run=dry_run)
    config_path = root / 'config.toml'
    if config_path.exists():
        print('\nСуществующий config.toml сохранён без изменений.', flush=True)
    elif not dry_run:
        # Exclusive creation protects a config created concurrently by the user.
        try:
            with config_path.open('xb') as stream:
                stream.write((root / 'config.example.toml').read_bytes())
            print('\nСоздан config.toml из примера; заполните настройки перед запуском CLI.', flush=True)
        except FileExistsError:
            print('\nСуществующий config.toml сохранён без изменений.', flush=True)
    else:
        print('\nБудет создан config.toml из примера.', flush=True)
    if dry_run:
        print('\nПроверка плана завершена. Файлы не изменены, установка не выполнялась.', flush=True)
    else:
        print('\nУстановка завершена. Запуск веб-приложения:', flush=True)
        print('  ' + command_text([str(python), '-m', 'interfaces.web.app']), flush=True)
        print('CLI: ' + command_text([str(python), '-m', 'interfaces.cli', '--config', str(config_path)]), flush=True)


def main():
    if sys.version_info < MIN_PYTHON:
        print('Нужен Python 3.11 или новее. Установите его с https://www.python.org/downloads/', file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dev', action='store_true', help='Также установить зависимости тестов.')
    parser.add_argument('--skip-system-deps', action='store_true', help='Не устанавливать системные пакеты Linux.')
    parser.add_argument('--dry-run', action='store_true', help='Показать план без изменений и скачивания.')
    args = parser.parse_args()
    try:
        install(Path(__file__).resolve().parent, dev=args.dev,
                skip_system_deps=args.skip_system_deps, dry_run=args.dry_run)
    except KeyboardInterrupt:
        print('\nУстановка остановлена. Её можно запустить повторно.', file=sys.stderr)
        return 130
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'\nУстановка не завершена: {error}\nИсправьте причину и запустите установщик повторно.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
