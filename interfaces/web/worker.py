"""One browser job, with credentials received only over stdin."""
from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path

from scraper_common.config import config_from_mapping
from scraper.runner import run_export
from scraper_common.logging_setup import LOGGER_NAMES, SecretFormatter


def main():
    payload = json.loads(sys.stdin.readline())
    secrets = ()
    stopped = threading.Event()

    def watch_stop():
        for line in sys.stdin:
            if line.strip() == 'stop':
                stopped.set()
                return
        stopped.set()

    def emit(kind, **fields):
        print(json.dumps({'type': kind, **fields}, ensure_ascii=False), flush=True)

    class StatusHandler(logging.Handler):
        def emit(self, record):
            phase = getattr(record, 'phase', None)
            if phase:
                emit('status', phase=phase, source=getattr(record, 'source', None))
            if record.levelno < logging.INFO and payload['config'].get('export', {}).get('headless', True):
                return
            emit('log', message=self.format(record), level=record.levelname,
                 event=getattr(record, 'event', None), count=getattr(record, 'count', None),
                 document=getattr(record, 'document', None), source=getattr(record, 'source', None))

    # UI-specific adaptation stays here; the scraper uses ordinary logging.
    handler = StatusHandler()
    for name in LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
    threading.Thread(target=watch_stop, daemon=True).start()
    try:
        config = config_from_mapping(payload['config'], use_environment=False)
        secrets = config.secrets
        handler.setFormatter(SecretFormatter(secrets))
        result = run_export(config, Path(payload['runtime_dir']), cancelled=stopped.is_set)
        emit('result', **result)
    except Exception as error:
        message = str(error)
        for secret in sorted(secrets, key=len, reverse=True):
            if secret:
                message = message.replace(secret, '[скрыто]')
        emit('error', message=message[:1500], cancelled=isinstance(error, InterruptedError))


if __name__ == '__main__':
    main()
