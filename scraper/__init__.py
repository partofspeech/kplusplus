"""Единственное место регистрации источников."""
from importlib import import_module

SOURCE_MODULES = {
    'consultantplus': '.consultantplus',
    'sudact': '.sudact',
}
DEFAULT_SOURCE = 'consultantplus'


def get_source(name: str | None = None):
    name = name or DEFAULT_SOURCE
    if not isinstance(name, str) or name not in SOURCE_MODULES:
        raise ValueError(f'Неизвестный scraper.source: {name}')
    return import_module(SOURCE_MODULES[name], package=__name__)


def get_scraper_class(source: str):
    return get_source(source).Scraper
