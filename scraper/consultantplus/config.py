"""Настройки и совместимость старых конфигов КонсультантПлюс."""
from dataclasses import dataclass, field
import os
import re


@dataclass(frozen=True)
class ConsultantPlusSettings:
    login: str = field(repr=False)
    password: str = field(repr=False)
    court_scope: str = 'available'
    all_courts_open_selector: str = ''
    all_courts_option_selector: str = ''
    search_input_selector: str = '.x-page-components-search-panel__filter'
    search_submit_selector: str = '.x-page-components-search-panel__button'
    manual_intervention_timeout_ms: int = 300000

    @property
    def secrets(self) -> tuple[str, ...]:
        return self.login, self.password


def parse_settings(raw: dict, *, use_environment: bool = True) -> ConsultantPlusSettings:
    # Legacy sections stay supported without leaking their structure into core.
    options = {**raw.get('consultant', {}), **raw.get('search', {})}
    options['manual_intervention_timeout_seconds'] = raw.get('export', {}).get('manual_intervention_timeout_seconds', 300)
    options.update(raw.get('sources', {}).get('consultantplus', {}))
    login, password = str(options.get('login', '')), str(options.get('password', ''))
    if use_environment:
        def expand(value):
            return re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}', lambda match: os.environ.get(match.group(1), ''), value)
        login = os.environ.get('CONSULTANT_LOGIN', expand(login))
        password = os.environ.get('CONSULTANT_PASSWORD', expand(password))
    if not login or not password:
        raise ValueError('Укажите реквизиты в [sources.consultantplus] или CONSULTANT_LOGIN и CONSULTANT_PASSWORD.')
    scope = str(options.get('court_scope', 'available'))
    if scope not in {'available', 'all'}:
        raise ValueError('court_scope должен быть available или all.')
    return ConsultantPlusSettings(
        login=login, password=password, court_scope=scope,
        all_courts_open_selector=str(options.get('all_courts_open_selector', '')),
        all_courts_option_selector=str(options.get('all_courts_option_selector', '')),
        search_input_selector=str(options.get('search_input_selector', '.x-page-components-search-panel__filter')),
        search_submit_selector=str(options.get('search_submit_selector', '.x-page-components-search-panel__button')),
        manual_intervention_timeout_ms=int(options['manual_intervention_timeout_seconds']) * 1000,
    )


def form_options(data: dict) -> dict:
    options = {}
    for key, label in [('login', 'Логин'), ('password', 'Пароль')]:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError(f'Заполните поле «{label}» (до 2000 символов).')
        options[key] = value if key == 'password' else value.strip()
    return options
