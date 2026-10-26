"""Авторизация, проверки сессии и выход из КонсультантПлюс."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from scraper_common.config import Config

logger = logging.getLogger(__name__)

LOGIN_URL = "https://login.consultant.ru/"
APP_HOME_URL = "https://demo.consultant.ru/cgi/online.cgi?req=home"
_CAPTCHA_WORDS = ("captcha", "капч", "подтвердите, что вы не робот")


class AccessRequired(RuntimeError):
    """The account, CAPTCHA, or page layout requires a human action."""


def first_visible(page: Page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector)
        try:
            if locator.count() and locator.first.is_visible():
                return locator.first
        except PlaywrightTimeoutError:
            continue
    return None


class ConsultantPlusSession:
    def __init__(self, context: BrowserContext, config: Config, status_path: Path | None = None,
                 cancelled: Callable[[], bool] | None = None) -> None:
        self.context = context
        self.config = config
        self.settings = config.source_options
        self.status_path = status_path
        self.cancelled = cancelled or (lambda: False)

    def _check_cancelled(self) -> None:
        if self.cancelled():
            raise InterruptedError("Выгрузка остановлена пользователем.")

    def _status(self, phase: str) -> None:
        if phase != "logged-out":
            self._check_cancelled()
        logger.debug('Этап: %s', phase, extra={'phase': phase})
        if self.status_path:
            self.status_path.write_text(phase + "\n", encoding="utf-8")

    def captcha_present(self, page: Page) -> bool:
        text = page.locator("body").inner_text(timeout=5_000).lower()
        return any(word in text for word in _CAPTCHA_WORDS)

    def _wait_for_manual_action(self, page: Page, message: str, complete) -> bool:
        """Wait for a person to finish a visible CAPTCHA/OTP/licence step."""
        if self.config.headless:
            return False
        print(message + " Продолжу автоматически после завершения.", flush=True)
        deadline = time.monotonic() + self.settings.manual_intervention_timeout_ms / 1000
        while time.monotonic() < deadline:
            self._check_cancelled()
            if complete():
                return True
            page.wait_for_timeout(1_000)
        return False

    def login(self) -> Page:
        self._status("login")
        page = self.context.pages[0] if self.context.pages else self.context.new_page()
        # Reuse an authenticated session directly. Opening the login endpoint
        # on every run can cause ConsultantPlus to register a needless second
        # device/session before the actual search begins.
        has_session = any(cookie["domain"].endswith("consultant.ru") for cookie in self.context.cookies())
        page.goto(APP_HOME_URL if has_session else LOGIN_URL, wait_until="domcontentloaded")
        app_search = page.locator(".x-page-components-search-panel__filter").first
        # If the server reports a session left by an interrupted run, use the
        # product's own button to release it before attempting another login.
        if "Учетная запись занята" in page.locator("body").inner_text(timeout=5_000):
            release = first_visible(page, ["text=Выйти из системы", "button:has-text('Выйти из системы')"])
            if not release:
                raise AccessRequired("Учётная запись занята другой сессией; нажмите «Выйти из системы» вручную.")
            release.click()
            try:
                page.wait_for_timeout(1_000)
                page.wait_for_load_state("domcontentloaded", timeout=self.config.timeout_ms)
            except PlaywrightTimeoutError:
                pass
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
        try:
            app_search.wait_for(state="visible", timeout=2_000)
            self._status("home")
            return page
        except PlaywrightTimeoutError:
            pass
        # A saved session is redirected to the main system.  Never fall back
        # to a generic text input here: on that page it is the document search
        # bar, not a login control.
        if "login.consultant.ru" not in page.url:
            self._status("home")
            return page
        if self.captcha_present(page):
            raise AccessRequired("На странице входа показана CAPTCHA. Пройдите её вручную и повторите запуск.")
        login = first_visible(page, ["#loginform-login", "input#login", "input[name='login']", "input[autocomplete='username']"])
        password = first_visible(page, ["#loginform-password", "input#password", "input[name='password']", "input[autocomplete='current-password']"])
        if not login or not password:
            # ConsultantPlus can keep the authenticated application under the
            # login host. Its visible profile control distinguishes it from the
            # actual sign-in form.
            raise AccessRequired("Не найдены поля входа. Укажите селекторы или проверьте страницу входа.")
        if login.is_editable():
            login.fill(self.settings.login)
        elif login.input_value() != self.settings.login:
            raise AccessRequired("Поле логина защищено от редактирования и содержит другую учётную запись.")
        password.fill(self.settings.password)
        submit = first_visible(page, ["#buttonLogin", "button[type='submit']", "input[type='submit']"])
        if not submit:
            raise AccessRequired("Не найдена кнопка «Войти».")
        if not submit.is_enabled():
            if not self._wait_for_manual_action(
                page, "Подтвердите условия лицензии или иной обязательный пункт в окне браузера.", submit.is_enabled
            ):
                raise AccessRequired("Кнопка входа неактивна: подтвердите условия лицензии в видимом браузере.")
            if not submit.is_enabled():
                raise AccessRequired("Кнопка входа по-прежнему неактивна.")
        submit.click()
        try:
            page.wait_for_timeout(1_500)
            page.wait_for_load_state("domcontentloaded", timeout=self.config.timeout_ms)
        except PlaywrightTimeoutError:
            pass
        # The application may keep the login host in the URL after a
        # successful login. The visible search field is the authoritative
        # signal that the authenticated home page is ready.
        try:
            app_search.wait_for(state="visible", timeout=self.config.timeout_ms)
            self._status("home")
            return page
        except PlaywrightTimeoutError:
            pass
        if self.captcha_present(page) or "login.consultant.ru" in page.url:
            if not self._wait_for_manual_action(
                page,
                "Завершите CAPTCHA, одноразовый код или иной шаг входа в окне браузера.",
                lambda: "login.consultant.ru" not in page.url and not self.captcha_present(page),
            ):
                raise AccessRequired("Вход требует CAPTCHA или дополнительного подтверждения в видимом браузере.")
        if "login.consultant.ru" in page.url:
            raise AccessRequired("Вход не завершён. Проверьте реквизиты, срок доступа и возможный одноразовый код.")
        self._status("home")
        return page

    def logout(self, page: Page) -> bool:
        """Request server logout through the UI and confirm the login form."""
        selectors = [
            "button:has-text('Выйти из системы')",
            "[data-title='Выход из системы во всех вкладках']",
            "text=Выйти", "text=Выход",
        ]
        logout = first_visible(page, selectors)
        if not logout:
            profile = first_visible(page, [
                ".x-page-home-header-profile__button",
                ".x-page-components-main-toolbar-top-button",
            ])
            if not profile:
                return False
            profile.click()
            logout = first_visible(page, selectors)
        if not logout:
            return False
        logout.click()
        page.locator("#loginform-password, input[name='password'], input[autocomplete='current-password']").first.wait_for(
            state="visible", timeout=self.config.timeout_ms
        )
        self._status("logged-out")
        return True

    def logout_all(self) -> bool:
        """Завершить сессию через одну из открытых вкладок, в том числе после ошибки."""
        logger.debug('Выполняется выход из К+', extra={'phase': 'logging-out'})
        for page in reversed(self.context.pages):
            if page.is_closed():
                continue
            try:
                if self.logout(page):
                    return True
            except Exception:
                logger.debug('Не удалось выйти через вкладку К+', exc_info=True)
        logger.warning('Выход из КонсультантПлюс не подтверждён.', extra={'phase': 'logout-unconfirmed'})
        return False
