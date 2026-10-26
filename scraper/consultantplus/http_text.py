"""Conservative HTTP text retrieval inside the browser's authenticated session."""
from __future__ import annotations

import codecs
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit


logger = logging.getLogger(__name__)


class DocumentHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in {'head', 'script', 'style', 'noscript', 'template'}:
            self.hidden.append(tag)
        if not self.hidden and tag in {'p', 'div', 'br', 'tr', 'li', 'h1', 'h2', 'h3'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag in {'p', 'div', 'tr', 'li', 'h1', 'h2', 'h3'}:
            self.parts.append('\n')
        elif tag == 'td':
            self.parts.append('\t')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def decode_document(body: bytes, content_type: str) -> str:
    if body.startswith(codecs.BOM_UTF8):
        return body.decode('utf-8-sig')
    if body.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return body.decode('utf-16')
    header = re.search(r'charset\s*=\s*["\']?([\w-]+)', content_type, re.I)
    meta = re.search(br'<meta\b[^>]*charset\s*=\s*["\']?([\w-]+)', body[:8192], re.I)
    encoding = header.group(1) if header else meta.group(1).decode('ascii') if meta else None
    if encoding:
        return body.decode(encoding)
    try:
        return body.decode('utf-8')
    except UnicodeDecodeError:
        return body.decode('cp1251')


def verified_http_text(context, url: str, browser_url: str, rendered_text: str, *, timeout_ms: int) -> str | None:
    """Only use an observed URL and text matching the rendered document in full.

    The first hybrid version intentionally keeps the DOM text as a reference.
    Dynamic shells, login pages, redirects and truncated replies fall back to
    that text rather than producing incomplete documents.
    """
    target, origin = urlsplit(url), urlsplit(browser_url)
    if target.scheme not in {'http', 'https'} or (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
        return None
    if not rendered_text.strip():
        return None
    response = None
    try:
        response = context.request.get(url, timeout=min(timeout_ms, 15000), max_redirects=0)
        if response.status != 200:
            logger.debug('HTTP-ответ %s; используем браузерный текст', response.status)
            return None
        content_type = response.headers.get('content-type', '').lower()
        if not any(kind in content_type for kind in ('text/html', 'application/xhtml+xml', 'text/plain')):
            logger.debug('HTTP вернул нетекстовый ответ; используем браузерный текст')
            return None
        body = response.body()
        if len(body) > 20 * 1024 * 1024:
            logger.debug('HTTP-ответ превышает лимит размера; используем браузерный текст')
            return None
        text = decode_document(body, content_type)
        if 'text/plain' not in content_type:
            parser = DocumentHTML()
            parser.feed(text)
            text = ''.join(parser.parts).strip()
        # Exact content comparison tolerates paragraph/space representation only.
        if ' '.join(text.split()) != ' '.join(rendered_text.split()):
            logger.debug('HTTP-текст не совпадает с браузерным; используем браузерный текст')
            return None
        logger.debug('Полный текст подтверждён через HTTP')
        return text
    except Exception:
        logger.debug('Ошибка HTTP-получения; используем браузерный текст', exc_info=True)
        return None
    finally:
        if response is not None:
            response.dispose()
