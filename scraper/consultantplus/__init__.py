"""Источник КонсультантПлюс: настройки, авторизация и сбор документов."""
from .config import parse_settings, form_options
from .scraper import ConsultantPlusScraper

Scraper = ConsultantPlusScraper
from .identity import document_key, normalize_legacy_row
