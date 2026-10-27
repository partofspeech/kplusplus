"""Single-run lock with recovery after an exited process, on macOS, Linux and Windows."""
from __future__ import annotations

import os
from pathlib import Path


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return True  # An invalid lock must not target a process group.
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            # ERROR_INVALID_PARAMETER means this PID does not exist.
            # Access denied is not proof that a process has exited.
            return ctypes.get_last_error() != 87
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
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
