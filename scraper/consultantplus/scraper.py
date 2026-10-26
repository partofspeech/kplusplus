from __future__ import annotations

import hashlib
import logging
import re
from typing import Callable
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from scraper_common.config import Config
from scraper_common.documents import write_docx
from .http_text import verified_http_text
from .text import clean_decision_text
from scraper_common.storage import ExportStore
from .identity import document_key, normalize_legacy_row
from .session import ConsultantPlusSession, AccessRequired, first_visible as _first_visible

logger = logging.getLogger(__name__)

def _safe_name(title: str, url: str, suffix: str) -> str:
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    title = re.sub(r"[^0-9A-Za-zА-Яа-яЁё._ -]+", "_", title).strip(" ._")
    return f"{title[:110] or 'court_decision'}--{digest}{suffix}"


def _canonical(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))



class ConsultantPlusScraper:
    supported = True
    source_name = "Консультант+"

    def __init__(self, context: BrowserContext, config: Config, status_path: Path | None = None,
                 cancelled: Callable[[], bool] | None = None) -> None:
        self.context, self.config, self.status_path = context, config, status_path
        self.settings = config.source_options
        self.http_texts = 0
        self.browser_texts = 0
        self.cancelled = cancelled or (lambda: False)
        self.session = ConsultantPlusSession(context, config, status_path, cancelled)

    def run(self, output_dir: Path) -> dict:
        """Выгрузить документы К+ и завершить авторизованную сессию."""
        try:
            urls = self.collect_urls()
            logger.debug('Найдено ссылок на акты: %d', len(urls))
            saved, skipped = self.export_related(urls, output_dir)
        finally:
            logout_confirmed = self.session.logout_all()
        return {
            'saved': saved,
            'skipped': skipped,
            'logout_confirmed': logout_confirmed,
            'http_texts': self.http_texts,
            'browser_texts': self.browser_texts,
        }

    def collect_urls(self) -> list[str]:
        """Найти закон и получить ссылки из связанной практики высших судов."""
        page = self.session.login()
        page = self.search(page)
        self.open_related_high_courts(page)
        urls = list(self.related_urls(page))
        if not urls:
            raise RuntimeError("В разделе судебной практики не найдены ссылки на акты.")
        return urls

    def _check_cancelled(self) -> None:
        if self.cancelled():
            raise InterruptedError("Выгрузка остановлена пользователем.")

    def _status(self, phase: str) -> None:
        if phase != "logged-out":
            self._check_cancelled()
        logger.debug('Этап: %s', phase, extra={'phase': phase})
        if self.status_path:
            self.status_path.write_text(phase + "\n", encoding="utf-8")

    def _apply_all_courts(self, page: Page) -> None:
        if self.settings.court_scope != "all":
            return
        if not self.settings.all_courts_open_selector or not self.settings.all_courts_option_selector:
            raise AccessRequired(
                "Для court_scope = all укажите селекторы all_courts_open_selector и "
                "all_courts_option_selector из обычного интерфейса КонсультантПлюс."
            )
        opener = page.locator(self.settings.all_courts_open_selector).first
        if not opener.is_visible():
            raise AccessRequired("Фильтр «Все суды» не найден или не доступен для этой учётной записи.")
        opener.click()
        option = page.locator(self.settings.all_courts_option_selector).first
        if not option.is_visible():
            raise AccessRequired("Пункт «Все суды» не найден или не доступен для этой учётной записи.")
        option.click()

    def search(self, page: Page) -> Page:
        self._status("search-start")
        field = page.locator(self.settings.search_input_selector).first if self.settings.search_input_selector else _first_visible(page, [
            "input[placeholder*='Поиск']", "input[aria-label*='Поиск']", "input[type='search']",
        ])
        if not field or not field.is_visible():
            raise AccessRequired("Не найдено поле поиска. Задайте search.search_input_selector в config.toml.")
        field.click()
        field.fill(self.config.query)
        if field.input_value() != self.config.query:
            raise AccessRequired("Запрос не удалось записать в поле поиска; выгрузка не начата.")
        self._status("query-filled")
        self._apply_all_courts(page)
        submit = page.locator(self.settings.search_submit_selector).first if self.settings.search_submit_selector else None
        if not submit or not submit.is_visible() or not submit.is_enabled():
            raise AccessRequired("Кнопка «Найти» не видна или неактивна; запрос не отправлен.")
        submit.click()
        self._status("find-clicked")
        try:
            # Quick-search results are rendered in place; the URL can remain
            # unchanged. Wait for the actual result row first.
            page.locator(".x-page-components-search-result-item").first.wait_for(
                state="visible", timeout=self.config.timeout_ms
            )
        except PlaywrightTimeoutError:
            raise AccessRequired("Поиск не показал строку результатов; выгрузка не начата.")
        if self.session.captcha_present(page):
            raise AccessRequired("CAPTCHA появилась при поиске. Пройдите её вручную и повторите запуск.")
        self._status("results")
        first_document = page.locator("a.x-page-components-search-result-item__extra-title").first
        if not first_document.is_visible():
            first_document = page.locator("a[href*='online.cgi'][href*='req=doc']").first
        if not first_document.is_visible():
            first_document = page.get_by_text(self.config.query, exact=False).first
        if first_document.is_visible():
            href = first_document.get_attribute("href")
            if not href:
                raise AccessRequired("У первой карточки отсутствует адрес документа; выгрузка не начата.")
            # The result anchor uses target="_blank". Follow the same popup
            # that a human click creates, then continue in that document tab.
            try:
                with self.context.expect_page(timeout=5_000) as popup_info:
                    first_document.click()
                document_page = popup_info.value
                document_page.wait_for_load_state("domcontentloaded", timeout=self.config.timeout_ms)
                page = document_page
            except PlaywrightTimeoutError:
                page.goto(urljoin(page.url, href), wait_until="domcontentloaded")
            self._status("first-card-opened")
            try:
                if "req=doc" not in page.url:
                    page.wait_for_url(re.compile(r".*online\.cgi\?.*req=doc.*"), timeout=self.config.timeout_ms)
            except PlaywrightTimeoutError:
                raise AccessRequired("Первая карточка не открылась; выгрузка не начата.")
        else:
            raise AccessRequired("Не найдена карточка закона по введённому запросу.")
        # Court filters normally live on the result page. Applying them after
        # the first search also avoids depending on a particular start page.
        self._apply_all_courts(page)
        return page

    def open_related_high_courts(self, page: Page) -> None:
        """Navigate the visible document UI to related higher-court practice."""
        # The document shell is returned before its inner frame and context
        # toolbar finish loading.  Give the site time to populate those
        # controls; otherwise a valid document is mistaken for a missing menu.
        try:
            page.locator("#waitOverlay").wait_for(state="hidden", timeout=self.config.timeout_ms)
        except PlaywrightTimeoutError:
            # Some editions keep the overlay node in the DOM while switching
            # its display style asynchronously.  A bounded grace period is
            # safer than aborting immediately.
            page.wait_for_timeout(3_000)
        page.wait_for_timeout(2_000)

        # The overflow menu contains the actual related-documents command.
        # Use its visible Russian label instead of clicking another toolbar
        # item by position.
        more = _first_visible(page, [
            "[test='context-panel-dots-button']",
            "button[title='Еще']",
            "button[title='Ещё']",
        ])
        related_clicked = False
        if more:
            more.click()
            page.wait_for_timeout(1_500)
            related = _first_visible(page, [
                "text=Связи документа",
                "a:has-text('Связи документа')",
                "[data-title*='Связи документа']",
            ])
            if related:
                related.click()
                related_clicked = True
                page.wait_for_timeout(3_000)

        # Some product builds expose the same command as a purple info icon.
        # Fall back to it only when the overflow menu did not contain the
        # labelled command.
        if not related_clicked:
            for frame in [frame for frame in page.frames if "document_inner" in frame.url]:
                info = _first_visible(frame, [
                    ".icon.info", ".icon[class*='info']", "[title*='информац']",
                ])
                if info:
                    info.click()
                    page.wait_for_timeout(3_000)
                    break
        practice = _first_visible(page, [
            "text=Судебная практика",
            "a:has-text('Судебная практика')",
            "[data-title='Судебная практика']",
        ])
        if not practice:
            raise AccessRequired("В связанных документах не найден раздел «Судебная практика».")
        practice.click()
        page.wait_for_timeout(500)
        higher = _first_visible(page, [
            "text=Высшие суды",
            "a:has-text('Высшие суды')",
            "[data-title='Высшие суды']",
            "text=Решения высших судов",
            "a:has-text('Решения высших судов')",
            "[data-title='Решения высших судов']",
        ])
        if not higher:
            raise AccessRequired("Подраздел «Высшие суды» недоступен для этой учётной записи.")
        higher.click()
        self._status("court-practice-high-courts")
        page.wait_for_timeout(1_000)

    def related_urls(self, page: Page):
        seen: set[str] = set()
        links = page.locator("a[href*='online.cgi'][href*='req=doc']")
        for index in range(links.count()):
            href = links.nth(index).get_attribute("href")
            if not href:
                continue
            url = _canonical(urljoin(page.url, href))
            if url not in seen:
                seen.add(url)
                yield url

    def _reference_fields(self, page: Page) -> dict[str, str]:
        """Read the visible structured fields from the K+ «Справка» panel."""
        button = _first_visible(page, ["[test='context-panel-esse-button']", "button:has-text('Справка')"])
        if button:
            button.click()
            page.wait_for_timeout(800)
        body = page.locator("body").inner_text(timeout=8_000)
        start = body.rfind("Справка к документу")
        section = body[start:] if start >= 0 else body
        def between(left: str, right: str) -> str:
            if left not in section:
                return ""
            value = section.split(left, 1)[1]
            if right in value:
                value = value.split(right, 1)[0]
            return " ".join(value.split()).strip()
        title_section = section.split("Название документа", 1)[1] if "Название документа" in section else ""
        title_lines = [line.strip() for line in title_section.split("Выйти", 1)[0].splitlines() if line.strip()]
        return {
            "Примечание к документу": between("Примечание к документу", "Название документа"),
            "Название документа (К+)": title_lines[0] if title_lines else "",
        }

    def export_related(self, urls, output: Path) -> tuple[int, int]:
        self._status("export")
        output.mkdir(parents=True, exist_ok=True)
        saved = skipped = 0
        store = ExportStore(output, document_key=document_key, normalize_row=normalize_legacy_row,
                            source_id=self.config.source, source_name=self.config.source_name,
                            source_names=self.config.source_names)
        seen = set()
        try:
            for url in urls:
                self._check_cancelled()
                key = document_key(url)
                if key in seen:
                    logger.debug('Повтор ссылки на документ, пропуск: %s', key)
                    continue
                seen.add(key)
                previous = store.row(self.config.query, key)
                existing_file = store.file(key, url, previous)
                if previous is not None and existing_file is not None and not self.config.overwrite:
                    skipped += 1
                    logger.debug("Документ уже сохранён, пропуск: %s", key)
                    self._status(f"skipped:{skipped}")
                    continue
                logger.debug("Обработка документа: %s", key)
                document = self.context.new_page()
                try:
                    document.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
                    if self.session.captcha_present(document):
                        raise AccessRequired("CAPTCHA появилась при открытии судебного акта.")
                    # ConsultantPlus returns the document shell first and
                    # fills document_inner.htm asynchronously.  Do not print
                    # or render the PDF while the shell still says
                    # «Идёт загрузка…».
                    try:
                        document.locator("#waitOverlay").wait_for(
                            state="hidden", timeout=self.config.timeout_ms
                        )
                    except PlaywrightTimeoutError:
                        pass
                    inner = next(
                        (frame for frame in document.frames if "document_inner" in frame.url),
                        None,
                    )
                    if inner:
                        inner.locator("body").wait_for(
                            state="visible", timeout=self.config.timeout_ms
                        )
                    document.wait_for_timeout(2_000)
                    text = (
                        inner.locator("body").inner_text(timeout=8_000)
                        if inner
                        else document.locator("body").inner_text(timeout=8_000)
                    )
                    if self.config.transport == "hybrid":
                        http_text = verified_http_text(
                            self.context, inner.url if inner else document.url,
                            document.url, text, timeout_ms=self.config.timeout_ms,
                        )
                        if http_text is not None:
                            text = http_text
                            self.http_texts += 1
                        else:
                            self.browser_texts += 1
                    else:
                        self.browser_texts += 1
                    title = document.title()
                    # Capture the decision before switching to «Справка».
                    # DOCX stores Unicode text and avoids RTF reader differences.
                    text = clean_decision_text(text)
                    reference = self._reference_fields(document)
                    filename = existing_file.name if existing_file else _safe_name(reference.get("Название документа (К+)") or title, key, ".docx")
                    if existing_file is None or self.config.overwrite:
                        write_docx(store.documents_dir / filename, text)
                    store.record(key, filename, {
                        "Связанный акт": self.config.query,
                        "Источник": url,
                        "Дата сохранения": date.today().strftime("%d.%m.%Y"),
                        "Название документа": reference.get("Название документа (К+)", ""),
                        "Текст решения": text,
                        "Примечание": reference.get("Примечание к документу", ""),
                    })
                    saved += 1
                    logger.debug("Сохранён документ: %s; файл: %s", key, filename)
                    self._status(f"saved:{saved}")
                except PlaywrightTimeoutError:
                    logger.debug("Таймаут документа, пропуск: %s", key, exc_info=True)
                    skipped += 1
                    self._status(f"skipped:{skipped}")
                finally:
                    document.close()
        finally:
            store.close()
        return saved, skipped
