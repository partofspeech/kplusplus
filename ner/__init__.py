"""Настройки будущего извлечения структурированных данных из судебных актов."""
from .config import NerConfig, FIELD_LABELS, parse_config


def extract(text: str, config: NerConfig) -> dict:
    """Заглушка: ни локальное извлечение, ни внешние API пока не вызываются."""
    raise NotImplementedError('Извлечение структурированных данных пока не реализовано.')
