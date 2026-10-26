import os

import pytest

from scraper_common.process_lock import acquire_lock, process_alive


def test_current_process_is_alive():
    assert process_alive(os.getpid())


def test_recovers_lock_after_exited_process(tmp_path, monkeypatch):
    path = tmp_path / 'active.lock'
    path.write_text('12345')
    monkeypatch.setattr('scraper_common.process_lock.process_alive', lambda _pid: False)
    fd = acquire_lock(path)
    try:
        assert int(path.read_text()) == os.getpid()
    finally:
        os.close(fd)
        path.unlink()


def test_retains_lock_of_live_process(tmp_path):
    path = tmp_path / 'active.lock'
    path.write_text(str(os.getpid()))
    with pytest.raises(RuntimeError, match='уже работает'):
        acquire_lock(path)
    assert path.read_text() == str(os.getpid())
