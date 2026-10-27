"""Scoped CLI logging without changing third-party/root logger settings."""
from contextlib import contextmanager
import logging

LOGGER_NAMES = ('scraper', 'scraper_common', 'interfaces', 'ner')


class SecretFormatter(logging.Formatter):
    def __init__(self, secrets):
        super().__init__('%(asctime)s %(levelname)s %(name)s: %(message)s', datefmt='%H:%M:%S')
        self.secrets = sorted({value for value in secrets if value}, key=len, reverse=True)

    def format(self, record):
        text = super().format(record)
        for secret in self.secrets:
            text = text.replace(secret, '[скрыто]')
        return text


@contextmanager
def cli_logging(debug: bool, *, secrets=()):
    handler = logging.StreamHandler()
    handler.setFormatter(SecretFormatter(secrets))
    previous = []
    for name in LOGGER_NAMES:
        logger = logging.getLogger(name)
        previous.append((logger, logger.handlers[:], logger.level, logger.propagate))
        logger.handlers = [handler]
        logger.setLevel(logging.DEBUG if debug else logging.WARNING)
        logger.propagate = False
    try:
        yield
    finally:
        for logger, handlers, level, propagate in previous:
            logger.handlers = handlers
            logger.setLevel(level)
            logger.propagate = propagate
        handler.close()
