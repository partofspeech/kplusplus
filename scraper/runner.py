"""Полный жизненный цикл скрепинга/парсинга выбранного источника."""
from __future__ import annotations

import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Callable

from playwright.sync_api import sync_playwright

from scraper_common.config import Config
from scraper_common.process_lock import acquire_lock
from . import get_scraper_class

logger = logging.getLogger(__name__)


def run_export(config: Config, runtime_dir: Path, *,
               cancelled: Callable[[], bool] | None = None) -> dict:
    """Запустить выбранный источник с новой сессией браузера."""
    selected = []
    skipped_sources = []
    for selection in config.sources:
        scraper_class = get_scraper_class(selection.key)
        if not scraper_class.supported:
            logger.warning('Источник %s пропущен: реализация пока отсутствует.', selection.name)
            skipped_sources.append(selection.key)
            continue
        selected.append((selection, scraper_class))
    total = {'saved': 0, 'skipped': 0, 'logout_confirmed': None,
             'http_texts': 0, 'browser_texts': 0, 'skipped_sources': skipped_sources}
    if not selected:
        return total

    runtime_dir.mkdir(parents=True, exist_ok=True)
    lock_path = runtime_dir / 'active.lock'
    lock_fd = acquire_lock(lock_path)
    try:
        for selection, scraper_class in selected:
            if cancelled and cancelled():
                raise InterruptedError('Выгрузка остановлена.')
            source_config = replace(config, source=selection.key, source_name=selection.name,
                                    source_options=selection.options)
            result = run_source(source_config, runtime_dir, scraper_class, cancelled)
            for counter in ('saved', 'skipped', 'http_texts', 'browser_texts'):
                total[counter] += result.get(counter, 0)
            confirmed = result.get('logout_confirmed')
            if confirmed is not None:
                total['logout_confirmed'] = confirmed if total['logout_confirmed'] is None else total['logout_confirmed'] and confirmed
        return total
    finally:
        # Release the lock even when writing the final status fails.
        try:
            (runtime_dir / 'run-status.txt').write_text('closed\n', encoding='utf-8')
        finally:
            try:
                os.close(lock_fd)
            finally:
                lock_path.unlink(missing_ok=True)


def run_source(config: Config, runtime_dir: Path, scraper_class,
               cancelled: Callable[[], bool] | None) -> dict:
    """Каждый источник получает отдельную свежую сессию браузера."""
    logger.debug('Запуск источника: %s', config.source_name, extra={'phase': 'starting'})
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=config.headless, slow_mo=config.slow_mo_ms)
        try:
            context = browser.new_context()
            try:
                context.set_default_timeout(config.timeout_ms)
                scraper = scraper_class(context, config, runtime_dir / 'run-status.txt', cancelled=cancelled)
                return scraper.run(config.directory)
            finally:
                context.close()
        finally:
            browser.close()
