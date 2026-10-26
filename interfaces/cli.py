from __future__ import annotations

import argparse
import logging
import signal
from dataclasses import replace
from pathlib import Path

from scraper_common.config import load_config
from scraper.runner import run_export
from scraper_common.logging_setup import cli_logging

logger = logging.getLogger(__name__)


def resolve_output_directory(config_path: Path, directory: Path) -> Path:
    """Resolve relative output paths against the config's directory on this OS."""
    directory = directory.expanduser()
    if not directory.is_absolute():
        directory = config_path.expanduser().resolve().parent / directory
    return directory.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description='Выгружает судебные акты из выбранного источника.')
    parser.add_argument('--config', default='config.toml', type=Path)
    parser.add_argument('--debug', action='store_true', help='Показать окно Chromium и подробные логи в терминале. По умолчанию отладка выключена.')
    parser.add_argument('--http', action=argparse.BooleanOptionalAction, default=True,
                        help='Включить пробный HTTP-режим (по умолчанию включён); --no-http отключает его.')
    args = parser.parse_args()

    def stop_gracefully(_signal_number, _frame):
        raise InterruptedError('Выгрузка остановлена.')

    signal.signal(signal.SIGTERM, stop_gracefully)
    signal.signal(signal.SIGINT, stop_gracefully)
    config_path = args.config.expanduser().resolve()
    config = load_config(config_path)
    output = resolve_output_directory(config_path, config.directory)
    config = replace(config, directory=output, headless=not args.debug,
                     transport='hybrid' if args.http else 'browser')
    with cli_logging(args.debug, secrets=config.secrets):
        logger.debug('Конфиг: %s; папка: %s; HTTP: %s; headless: %s; перезапись: %s',
                     config_path, output, args.http, config.headless, config.overwrite)
        try:
            result = run_export(config, config_path.parent / '.playwright')
        except InterruptedError:
            raise SystemExit('Выгрузка остановлена.') from None
        except Exception as error:
            if args.debug:
                logger.exception('Выгрузка завершилась с ошибкой')
                raise SystemExit(1) from None
            message = str(error)
            for secret in sorted(config.secrets, key=len, reverse=True):
                if secret:
                    message = message.replace(secret, '[скрыто]')
            raise SystemExit(message) from None
    print(f"Готово: сохранено {result['saved']}, пропущено {result['skipped']}. Каталог: {output}")


if __name__ == '__main__':
    main()
