from dataclasses import dataclass, field
import os
import re

FIELD_LABELS = {
    'court': 'Судебная инстанция', 'hearing_date': 'Дата заседания',
    'defendant': 'Ответчик', 'plaintiff': 'Истец', 'decision': 'Решение', 'region': 'Регион',
}


@dataclass(frozen=True)
class NerConfig:
    enabled: bool = False
    method: str = 'simple'
    fields: tuple[str, ...] = ('court', 'hearing_date', 'defendant', 'plaintiff', 'decision')
    api_key: str = field(default='', repr=False)


def parse_config(raw: dict, *, use_environment: bool = True) -> NerConfig:
    if not isinstance(raw, dict):
        raise ValueError('ner должен быть набором настроек.')
    enabled = raw.get('enabled', False)
    method = raw.get('method', 'simple')
    fields = raw.get('fields', list(NerConfig().fields))
    if not isinstance(enabled, bool):
        raise ValueError('ner.enabled должен быть true или false.')
    if method not in ('simple', 'openai'):
        raise ValueError('ner.method должен быть simple или openai.')
    if not isinstance(fields, list) or not all(isinstance(name, str) and name in FIELD_LABELS for name in fields):
        raise ValueError('ner.fields содержит неизвестные поля.')
    api_key = raw.get('openai_api_key', '')
    if not isinstance(api_key, str):
        raise ValueError('ner.openai_api_key должен быть строкой.')
    if use_environment:
        api_key = re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}', lambda m: os.environ.get(m.group(1), ''), api_key)
    return NerConfig(enabled=enabled, method=method, fields=tuple(dict.fromkeys(fields)), api_key=api_key)
