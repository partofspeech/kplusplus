from pathlib import Path

import pytest

from scraper_common.config import load_config


def test_load_config_expands_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONSULTANT_LOGIN", "login")
    monkeypatch.setenv("CONSULTANT_PASSWORD", "secret")
    config_file = tmp_path / "config.toml"
    config_file.write_text("[consultant]\nlogin='${CONSULTANT_LOGIN}'\npassword='${CONSULTANT_PASSWORD}'\n", encoding="utf-8")
    config = load_config(config_file)
    assert (config.source_options.login, config.source_options.password, config.source_options.court_scope) == ("login", "secret", "available")


def test_rejects_unknown_scope(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("[consultant]\nlogin='a'\npassword='b'\n[search]\ncourt_scope='everything'", encoding="utf-8")
    with pytest.raises(ValueError, match="court_scope"):
        load_config(config_file)
