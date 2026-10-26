"""Общие настройки запуска; настройки источника разбирает сам источник."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scraper import DEFAULT_SOURCE, get_source


@dataclass(frozen=True)
class SourceConfig:
    key: str
    name: str
    options: Any = field(repr=False)


@dataclass(frozen=True)
class Config:
    query: str
    directory: Path
    headless: bool
    slow_mo_ms: int
    timeout_ms: int
    source_options: Any = field(repr=False)
    secrets: tuple[str, ...] = field(default=(), repr=False)
    transport: str = 'browser'
    overwrite: bool = False
    source: str = DEFAULT_SOURCE
    source_name: str = ""
    sources: tuple[SourceConfig, ...] = ()
    source_names: dict[str, str] = field(default_factory=dict)


def load_config(path: Path) -> Config:
    return config_from_mapping(tomllib.loads(path.read_text(encoding='utf-8')))


def config_from_mapping(raw: dict, *, use_environment: bool = True) -> Config:
    scraper = raw.get('scraper', {})
    source_keys = scraper.get('sources', [scraper.get('source', DEFAULT_SOURCE)])
    if not isinstance(source_keys, list) or not source_keys or not all(isinstance(key, str) and key.strip() for key in source_keys):
        raise ValueError('scraper.sources должен быть непустым списком источников.')
    selections = []
    secrets = []
    for key in dict.fromkeys(source_keys):
        source = get_source(key)
        options = source.parse_settings(raw, use_environment=use_environment)
        name = raw.get('sources', {}).get(key, {}).get('name', source.Scraper.source_name)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f'sources.{key}.name должен содержать название источника.')
        selections.append(SourceConfig(key, name.strip(), options))
        secrets.extend(options.secrets)
    if len({item.name for item in selections}) != len(selections):
        raise ValueError('Названия источников должны отличаться.')
    first = selections[0]
    source_names = {item.key: item.name for item in selections}
    for key, settings in raw.get('sources', {}).items():
        name = settings.get('name', get_source(key).Scraper.source_name)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f'sources.{key}.name должен содержать название источника.')
        source_names.setdefault(key, name.strip())
    if len(set(source_names.values())) != len(source_names):
        raise ValueError('Названия источников должны отличаться.')
    search, export = raw.get('search', {}), raw.get('export', {})
    transport = str(export.get('transport', 'browser'))
    if transport not in {'browser', 'hybrid'}:
        raise ValueError('export.transport должен быть browser или hybrid.')
    if not isinstance(export.get('overwrite', False), bool):
        raise ValueError('export.overwrite должен быть true или false.')
    return Config(
        source=first.key, source_name=first.name, source_options=first.options,
        sources=tuple(selections), source_names=source_names, secrets=tuple(secrets),
        query=str(search.get('query', '')), directory=Path(str(export.get('directory', 'output'))),
        headless=bool(export.get('headless', False)), slow_mo_ms=int(export.get('slow_mo_ms', 100)),
        timeout_ms=int(export.get('timeout_seconds', 45)) * 1000,
        transport=transport, overwrite=export.get('overwrite', False),
    )
