"""Single-run lock with recovery after an exited process, on macOS and Linux."""
from __future__ import annotations

import os
from pathlib import Path


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return True  # An invalid lock must not target a process group.
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def acquire_lock(path: Path) -> int:
    message = 'Другой экземпляр парсера уже работает. Дождитесь его завершения.'
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(path.read_text())
            except (OSError, ValueError):
                raise RuntimeError(message) from None
            if process_alive(pid):
                raise RuntimeError(message) from None
            path.unlink(missing_ok=True)
        else:
            os.write(fd, str(os.getpid()).encode())
            return fd
    raise RuntimeError(message)
