"""Заглушка открытого источника sudact.ru без авторизации."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SudactSettings:
    secrets: tuple[str, ...] = ()


def parse_settings(raw: dict, *, use_environment: bool = True) -> SudactSettings:
    return SudactSettings()


def form_options(data: dict) -> dict:
    return {}


class SudactScraper:
    supported = False
    source_name = 'Судакт.ру'


Scraper = SudactScraper

requires_credentials = False

ui_icon = 'scales'
ui_description = 'Открытые акты'
