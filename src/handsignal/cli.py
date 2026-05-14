"""CLI: handsignal init / listen / doctor / once."""

from __future__ import annotations

import shutil
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import CONFIG_PATH, load_config, write_default_config

console = Console()


@click.group()
@click.version_option(__version__)
def cli() -> None:
    """hand-signal — webcam gesture daemon for hands-free Claude Code confirmations."""


@cli.command()
def init() -> None:
    """Write a default config to ~/.config/hand-signal/config.toml."""
    path = write_default_config()
    console.print(f"[green]✔[/green] config at [cyan]{path}[/cyan]")
    console.print("Edit it to enable keystrokes / websocket or pick a hold-to-arm key.")


@cli.command()
def config() -> None:
    """Show resolved config."""
    cfg = load_config()
    t = Table(title=f"config — {CONFIG_PATH}")
    t.add_column("section"); t.add_column("key"); t.add_column("value")
    for section_name in ("camera", "detection", "output", "hotkey"):
        section = getattr(cfg, section_name)
        for k, v in section.__dict__.items():
            t.add_row(section_name, k, str(v))
    console.print(t)


@cli.command()
@click.option("--keystrokes", is_flag=True, help="Override config: enable keystroke injection.")
@click.option("--websocket", is_flag=True, help="Override config: enable websocket broadcast.")
@click.option("--preview", is_flag=True, help="Open a window showing the webcam + landmarks + current gesture.")
def listen(keystrokes: bool, websocket: bool, preview: bool) -> None:
    """Run the gesture daemon. Hold a recognized gesture in front of the webcam to fire."""
    cfg = load_config()
    if keystrokes:
        cfg.output.keystrokes_enabled = True
    if websocket:
        cfg.output.websocket_enabled = True
    from .daemon import run_daemon
    run_daemon(cfg, preview=preview)


@cli.command()
@click.argument("prompt", required=False, default="Approve this action?")
@click.option("--timeout", default=15.0, show_default=True, help="Seconds before auto-timeout.")
def ask(prompt: str, timeout: float) -> None:
    """Pop up a gesture confirmation window. Exit codes: 0=approve, 1=deny, 2=manual, 3=timeout, 4=quit."""
    cfg = load_config()
    from .ask import run_ask
    code = run_ask(cfg, prompt=prompt, timeout_s=timeout)
    raise SystemExit(code)


@cli.command()
def doctor() -> None:
    """Diagnose setup: opencv, mediapipe, pynput, camera, model."""
    t = Table(title="hand-signal doctor")
    t.add_column("check"); t.add_column("status"); t.add_column("note")

    def row(label, ok, note=""):
        t.add_row(label, "[green]ok[/green]" if ok else "[red]missing[/red]", note)

    # Python packages
    for pkg in ("cv2", "mediapipe", "numpy", "pynput", "websockets"):
        try:
            __import__(pkg)
            row(pkg, True)
        except ImportError as e:
            row(pkg, False, str(e))

    # Camera probe
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        ok = cap.isOpened()
        cap.release()
        row("camera index 0", ok, "couldn't open — check Privacy & Security → Camera" if not ok else "")
    except Exception as e:
        row("camera index 0", False, str(e))

    # Accessibility — best-effort note
    if shutil.which("tccutil"):
        row("Accessibility (macOS)", True, "grant your terminal app under System Settings → Privacy & Security → Accessibility if keystrokes fail")

    console.print(t)


if __name__ == "__main__":
    cli()
