"""Webcam daemon: capture → MediaPipe Hands → classify → debounce → dispatch.

Designed to be CPU-friendly on a 2020-era laptop: 30fps capture, no GPU needed.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Optional

from rich.console import Console

from .classifier import classify, classify_sequence
from .config import Config
from .output import EventDispatcher


def run_daemon(cfg: Config) -> None:
    """Block forever. Reads frames, classifies, fires debounced events."""
    import cv2  # imported here so `handsignal --help` works without opencv
    import mediapipe as mp
    import numpy as np

    console = Console()
    dispatcher = EventDispatcher(cfg.output, console=console)

    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(
        max_num_hands=1,
        model_complexity=0,
        min_detection_confidence=cfg.detection.min_confidence,
        min_tracking_confidence=cfg.detection.min_tracking,
    )

    cap = cv2.VideoCapture(cfg.camera.index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.camera.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.camera.height)
    cap.set(cv2.CAP_PROP_FPS, cfg.camera.fps)

    if not cap.isOpened():
        console.print(f"[red]could not open camera index {cfg.camera.index}[/red]")
        return

    # Debounce state.
    fps_est = max(15, cfg.camera.fps)
    history_len = max(3, int(fps_est * cfg.detection.hold_ms / 1000))
    history: deque[Optional[str]] = deque(maxlen=history_len)
    last_fire_ts: float = 0.0
    cooldown_s = cfg.detection.cooldown_ms / 1000.0

    arm_key = cfg.hotkey.arm_key.strip()
    armed = {"value": arm_key == ""}  # always-on if no arm_key
    if arm_key:
        _start_arm_listener(arm_key, armed, console)

    console.print(
        f"[bold]hand-signal[/bold] watching camera {cfg.camera.index}. "
        f"hold any of: tick / cross / thumbs_up / thumbs_down / open_palm / fist "
        f"for {cfg.detection.hold_ms}ms. ctrl-c to quit."
    )
    if arm_key:
        console.print(f"[dim]hold-to-arm: {arm_key}[/dim]")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            if cfg.detection.mirror:
                frame = cv2.flip(frame, 1)
            if not armed["value"]:
                history.clear()
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = hands.process(rgb)
            label: Optional[str] = None
            if result.multi_hand_landmarks:
                lm = result.multi_hand_landmarks[0]
                pts = np.array([[p.x, p.y, p.z] for p in lm.landmark], dtype=float)
                label = classify(pts)
            history.append(label)

            stable = classify_sequence(history, history_len)
            now = time.time()
            if stable is not None and (now - last_fire_ts) >= cooldown_s:
                dispatcher.fire(stable)
                last_fire_ts = now
                history.clear()
    except KeyboardInterrupt:
        console.print("\n[dim]bye[/dim]")
    finally:
        cap.release()
        hands.close()
        dispatcher.close()


def _start_arm_listener(arm_key: str, armed: dict, console: Console) -> None:
    """Spin a pynput listener that flips `armed['value']` while the key is held."""
    try:
        from pynput.keyboard import Key, Listener
    except ImportError:
        console.print("[yellow]pynput missing — arm_key disabled[/yellow]")
        return

    name = arm_key.strip().lower()
    target = getattr(Key, name, None) if hasattr(Key, name) else (name if len(name) == 1 else None)
    if target is None:
        console.print(f"[yellow]unknown arm_key {arm_key!r} — running always-on[/yellow]")
        armed["value"] = True
        return

    def on_press(k):
        if k == target:
            armed["value"] = True

    def on_release(k):
        if k == target:
            armed["value"] = False

    Listener(on_press=on_press, on_release=on_release, daemon=True).start()
