"""Output backends: keystroke injection, websocket broadcast, stdout."""

from __future__ import annotations

import asyncio
import json
import platform
import threading
import time
from typing import Optional


# ----- keystrokes -----------------------------------------------------------

_PYNPUT_SPECIAL = {
    "enter", "esc", "escape", "tab", "space", "backspace",
    "left", "right", "up", "down", "home", "end", "page_up", "page_down",
    "delete", "shift", "ctrl", "alt", "cmd",
}


def _resolve_key(name: str):
    """Map a config string ('enter', 'a', 'cmd+v') to (modifiers, key) for pynput."""
    from pynput.keyboard import Key
    parts = [p.strip().lower() for p in name.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"empty keymap entry: {name!r}")
    *mods, last = parts
    mod_keys = []
    for m in mods:
        if m == "cmd":
            mod_keys.append(Key.cmd)
        elif m == "ctrl":
            mod_keys.append(Key.ctrl)
        elif m == "alt" or m == "option":
            mod_keys.append(Key.alt)
        elif m == "shift":
            mod_keys.append(Key.shift)
        else:
            raise ValueError(f"unknown modifier: {m!r}")
    target_name = "escape" if last == "esc" else last
    if target_name in _PYNPUT_SPECIAL and hasattr(Key, target_name):
        target = getattr(Key, target_name)
    elif len(last) == 1:
        target = last
    else:
        raise ValueError(f"unknown key: {last!r}")
    return mod_keys, target


def send_keystroke(combo: str) -> None:
    """Inject the keystroke. macOS requires Accessibility permission."""
    try:
        from pynput.keyboard import Controller
    except ImportError:
        return
    mods, key = _resolve_key(combo)
    kb = Controller()
    for m in mods:
        kb.press(m)
    try:
        kb.press(key)
        kb.release(key)
    finally:
        for m in reversed(mods):
            kb.release(m)


# ----- websocket broadcast --------------------------------------------------

class WebsocketBroadcaster:
    """Tiny pub-sub server. Background thread runs an asyncio loop.
    Each event is a JSON line: {"gesture": "tick", "ts": 1715693745.123}.
    """

    def __init__(self, port: int = 8765):
        self.port = port
        self._clients: set = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stopping = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(timeout=2.0)

    def _run(self, ready: threading.Event) -> None:
        import websockets  # imported here so unit tests can mock cleanly

        async def handler(ws):
            self._clients.add(ws)
            try:
                async for _ in ws:
                    pass  # we ignore incoming; this is broadcast-only
            finally:
                self._clients.discard(ws)

        async def main():
            async with websockets.serve(handler, "127.0.0.1", self.port):
                ready.set()
                while not self._stopping.is_set():
                    await asyncio.sleep(0.1)

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(main())
        finally:
            self._loop.close()

    def broadcast(self, payload: dict) -> None:
        if self._loop is None or not self._clients:
            return
        msg = json.dumps(payload)

        async def _send():
            dead = []
            for c in list(self._clients):
                try:
                    await c.send(msg)
                except Exception:
                    dead.append(c)
            for d in dead:
                self._clients.discard(d)

        asyncio.run_coroutine_threadsafe(_send(), self._loop)

    def stop(self) -> None:
        self._stopping.set()


# ----- combined dispatcher --------------------------------------------------

class EventDispatcher:
    """Combines print + keystrokes + websocket per config."""

    def __init__(self, output_cfg, console=None):
        self.cfg = output_cfg
        self.console = console
        self._ws: Optional[WebsocketBroadcaster] = None
        if output_cfg.websocket_enabled:
            self._ws = WebsocketBroadcaster(output_cfg.websocket_port)
            self._ws.start()

    def fire(self, gesture: str) -> None:
        ts = time.time()
        if self.cfg.print_events and self.console is not None:
            self.console.print(f"[bold green]✋ {gesture}[/bold green] [dim]@ {ts:.2f}[/dim]")
        if self.cfg.keystrokes_enabled:
            combo = self.cfg.keymap.get(gesture)
            if combo:
                try:
                    send_keystroke(combo)
                except Exception as e:
                    if self.console is not None:
                        self.console.print(f"[red]keystroke failed:[/red] {e}")
        if self._ws is not None:
            self._ws.broadcast({"gesture": gesture, "ts": ts})

    def close(self) -> None:
        if self._ws is not None:
            self._ws.stop()
