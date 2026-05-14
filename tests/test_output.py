"""Output backend tests — fakes pynput + websockets so nothing physical happens."""

from __future__ import annotations

import sys
import types

import pytest


def _install_fake_pynput(monkeypatch):
    events: list = []

    class FakeKey:
        cmd = "CMD"; ctrl = "CTRL"; alt = "ALT"; shift = "SHIFT"
        enter = "ENTER"; escape = "ESCAPE"; tab = "TAB"; space = "SPACE"
        backspace = "BACKSPACE"
        left = "LEFT"; right = "RIGHT"; up = "UP"; down = "DOWN"
        home = "HOME"; end = "END"; page_up = "PGUP"; page_down = "PGDN"
        delete = "DEL"

    class FakeController:
        def press(self, k): events.append(("press", k))
        def release(self, k): events.append(("release", k))

    fake_mod = types.ModuleType("pynput.keyboard")
    fake_mod.Controller = FakeController
    fake_mod.Key = FakeKey
    monkeypatch.setitem(sys.modules, "pynput", types.ModuleType("pynput"))
    monkeypatch.setitem(sys.modules, "pynput.keyboard", fake_mod)
    return events


def test_send_keystroke_simple_key(monkeypatch):
    events = _install_fake_pynput(monkeypatch)
    from handsignal.output import send_keystroke
    send_keystroke("enter")
    assert events == [("press", "ENTER"), ("release", "ENTER")]


def test_send_keystroke_chord(monkeypatch):
    events = _install_fake_pynput(monkeypatch)
    from handsignal.output import send_keystroke
    send_keystroke("cmd+v")
    assert events == [
        ("press", "CMD"),
        ("press", "v"),
        ("release", "v"),
        ("release", "CMD"),
    ]


def test_send_keystroke_esc_alias(monkeypatch):
    events = _install_fake_pynput(monkeypatch)
    from handsignal.output import send_keystroke
    send_keystroke("esc")
    assert events == [("press", "ESCAPE"), ("release", "ESCAPE")]


def test_send_keystroke_unknown_modifier(monkeypatch):
    _install_fake_pynput(monkeypatch)
    from handsignal.output import send_keystroke
    with pytest.raises(ValueError):
        send_keystroke("meta+a")


def test_event_dispatcher_print_only(monkeypatch):
    """With keystrokes + websocket disabled, fire() only prints."""
    _install_fake_pynput(monkeypatch)
    from handsignal.config import OutputConfig
    from handsignal.output import EventDispatcher

    printed: list = []

    class FakeConsole:
        def print(self, msg): printed.append(msg)

    cfg = OutputConfig(print_events=True, keystrokes_enabled=False, websocket_enabled=False)
    d = EventDispatcher(cfg, console=FakeConsole())
    d.fire("tick")
    d.close()
    assert any("tick" in str(m) for m in printed)


def test_event_dispatcher_fires_keystroke(monkeypatch):
    events = _install_fake_pynput(monkeypatch)
    from handsignal.config import OutputConfig
    from handsignal.output import EventDispatcher

    cfg = OutputConfig(print_events=False, keystrokes_enabled=True, websocket_enabled=False)
    d = EventDispatcher(cfg, console=None)
    d.fire("tick")  # default keymap: tick → enter
    d.close()
    assert ("press", "ENTER") in events
