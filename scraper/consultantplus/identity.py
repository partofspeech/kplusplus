"""Устойчивый идентификатор документа К+ без параметров сессии."""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def document_key(url: str) -> str:
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query))
    if params.get('base') and params.get('n'):
        return f"{params['base'].upper()}:{params['n']}"
    transient = {'rnd', 'cacheid', 'mode', 'BASENODE'}
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if k not in transient))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ''))



def normalize_legacy_row(row: dict) -> dict:
    """Привести старую таблицу К+ к общему формату, сохранив её поля."""
    from scraper_common.storage import FIELDS
    data = {name: row.get(name, '') for name in FIELDS}
    data['Название документа'] = row.get('Название документа (К+)') or data['Название документа']
    data['Примечание'] = row.get('Примечание к документу') or data['Примечание']
    return data
