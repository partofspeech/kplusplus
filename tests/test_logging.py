import logging

import pytest

from scraper_common.logging_setup import cli_logging


def test_debug_messages_are_hidden_without_debug_flag(capsys):
    with cli_logging(False):
        logging.getLogger('scraper.consultantplus').debug('Обработка документа')
    assert capsys.readouterr().err == ''


@pytest.mark.parametrize('namespace', ['scraper.consultantplus', 'scraper_common.storage', 'interfaces.cli'])
def test_debug_logs_include_time_level_and_module(capsys, namespace):
    with cli_logging(True):
        logging.getLogger(namespace).debug('Сохранён документ: %s', 'ARB:123')
    text = capsys.readouterr().err
    assert f'DEBUG {namespace}: Сохранён документ: ARB:123' in text
    assert text[:8].count(':') == 2


def test_credentials_are_redacted_in_messages_and_tracebacks(capsys):
    login, password = 'private-login', 'private-password'
    logger = logging.getLogger('scraper.consultantplus')
    with cli_logging(True, secrets=(login, password)):
        logger.debug('Ошибка входа %s %s', login, password)
        try:
            raise RuntimeError(f'Не удалось войти: {login} / {password}')
        except RuntimeError:
            logger.exception('Ошибка')
    text = capsys.readouterr().err
    assert login not in text
    assert password not in text
    assert 'Traceback' in text
    assert '[скрыто]' in text


def test_logging_configuration_is_restored_after_run():
    logger = logging.getLogger('scraper')
    previous = logger.handlers[:], logger.level, logger.propagate
    with cli_logging(True):
        assert logger.level == logging.DEBUG
        assert not logger.propagate
    assert (logger.handlers, logger.level, logger.propagate) == previous
