"""Config loader tests."""

from __future__ import annotations

from pathlib import Path

from handsignal.config import (
    Config,
    DEFAULT_TOML,
    load_config,
    write_default_config,
)


def test_default_config_values():
    cfg = Config()
    assert cfg.camera.index == 0
    assert cfg.detection.hold_ms == 400
    assert cfg.detection.cooldown_ms == 1000
    assert cfg.output.keystrokes_enabled is False
    assert cfg.output.websocket_enabled is False
    assert cfg.output.keymap["tick"] == "enter"
    assert cfg.hotkey.arm_key == ""


def test_load_missing_returns_defaults(tmp_path: Path):
    cfg = load_config(tmp_path / "absent.toml")
    assert cfg.detection.hold_ms == 400


def test_load_overrides(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[detection]\nhold_ms = 250\n\n'
        '[output]\nkeystrokes_enabled = true\n\n'
        '[output.keymap]\ntick = "cmd+v"\n'
    )
    cfg = load_config(p)
    assert cfg.detection.hold_ms == 250
    assert cfg.output.keystrokes_enabled is True
    assert cfg.output.keymap["tick"] == "cmd+v"
    # Untouched keymap entries keep defaults
    assert cfg.output.keymap["cross"] == "esc"


def test_default_toml_parses(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text(DEFAULT_TOML)
    cfg = load_config(p)
    assert cfg.detection.hold_ms == 400


def test_write_default_idempotent(tmp_path: Path):
    p = tmp_path / "c.toml"
    write_default_config(p)
    assert p.exists()
    p.write_text("# custom\n[detection]\nhold_ms = 99\n")
    write_default_config(p)
    assert "custom" in p.read_text()
