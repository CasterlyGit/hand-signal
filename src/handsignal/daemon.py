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


# What each gesture *would* do — shown in the HUD so the user knows the wiring.
GESTURE_ACTION_HINT = {
    "tick":        "Enter   (approve / continue)",
    "cross":       "Esc     (cancel / dismiss)",
    "thumbs_up":   "Enter   (yes / looks good)",
    "thumbs_down": "n       (no / reject)",
    "open_palm":   "Ctrl+C  (interrupt / stop)",
    "fist":        "Esc     (cancel)",
}

GESTURE_EMOJI = {
    "tick":        "v",
    "cross":       "x",
    "thumbs_up":   "^",
    "thumbs_down": "_",
    "open_palm":   "5",
    "fist":        "o",
}


def run_daemon(cfg: Config, preview: bool = False) -> None:
    """Block forever. Reads frames, classifies, fires debounced events.
    If preview=True, also opens an OpenCV window showing the live feed,
    detected landmarks, and the current candidate gesture.
    """
    import cv2  # imported here so `handsignal --help` works without opencv
    import mediapipe as mp
    import numpy as np

    console = Console()
    dispatcher = EventDispatcher(cfg.output, console=console)

    mp_hands = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils
    mp_styles = mp.solutions.drawing_styles
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
    history: deque = deque(maxlen=history_len)
    last_fire_ts: float = 0.0
    cooldown_s = cfg.detection.cooldown_ms / 1000.0

    # Event log for the HUD (newest first, max 10 entries).
    event_log: deque = deque(maxlen=10)
    session_start = time.time()
    fire_count = {g: 0 for g in GESTURE_ACTION_HINT}

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
            fired = None
            if stable is not None and (now - last_fire_ts) >= cooldown_s:
                dispatcher.fire(stable)
                last_fire_ts = now
                fired = stable
                fire_count[stable] = fire_count.get(stable, 0) + 1
                event_log.appendleft((now, stable))
                history.clear()

            if preview:
                # Draw landmarks on the camera frame
                if result.multi_hand_landmarks:
                    for hand_lms in result.multi_hand_landmarks:
                        mp_drawing.draw_landmarks(
                            frame, hand_lms, mp_hands.HAND_CONNECTIONS,
                            mp_styles.get_default_hand_landmarks_style(),
                            mp_styles.get_default_hand_connections_style(),
                        )
                composite = _render_hud(
                    frame=frame,
                    candidate=label,
                    stable=stable,
                    fired=fired,
                    event_log=event_log,
                    fire_count=fire_count,
                    session_start=session_start,
                    keystrokes_on=cfg.output.keystrokes_enabled,
                )
                cv2.imshow("hand-signal", composite)
                cv2.setWindowProperty("hand-signal", cv2.WND_PROP_TOPMOST, 1)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        console.print("\n[dim]bye[/dim]")
    finally:
        cap.release()
        hands.close()
        dispatcher.close()
        if preview:
            try:
                import cv2 as _cv2
                _cv2.destroyAllWindows()
            except Exception:
                pass


def _render_hud(
    *,
    frame,
    candidate: Optional[str],
    stable: Optional[str],
    fired: Optional[str],
    event_log,
    fire_count: dict,
    session_start: float,
    keystrokes_on: bool,
):
    """Compose: [ camera frame | side panel ] into one wide image."""
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    panel_w = 460
    panel = np.zeros((h, panel_w, 3), dtype=np.uint8)
    # Subtle border
    panel[:] = (24, 24, 28)

    def text(img, s, xy, scale=0.55, color=(220, 220, 220), thickness=1):
        cv2.putText(img, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)

    # Header
    cv2.rectangle(panel, (0, 0), (panel_w, 36), (60, 60, 70), -1)
    text(panel, "hand-signal  ·  press q to quit", (12, 24), scale=0.55, color=(255, 255, 255))

    # Current state
    y = 64
    text(panel, "NOW SEEING", (12, y), scale=0.42, color=(140, 140, 150))
    y += 22
    cand_str = candidate if candidate else "(no gesture)"
    cand_color = (255, 230, 120) if candidate else (110, 110, 120)
    text(panel, cand_str, (12, y), scale=0.85, color=cand_color, thickness=2)

    y += 30
    text(panel, "HOLDING", (12, y), scale=0.42, color=(140, 140, 150))
    y += 22
    stable_str = stable if stable else "(not held long enough)"
    stable_color = (120, 255, 160) if stable else (110, 110, 120)
    text(panel, stable_str, (12, y), scale=0.85, color=stable_color, thickness=2)

    # Last fired — big banner
    y += 36
    if fired:
        cv2.rectangle(panel, (8, y - 4), (panel_w - 8, y + 36), (40, 100, 40), -1)
        text(panel, f"FIRED: {fired.upper()}", (16, y + 24), scale=0.75, color=(255, 255, 255), thickness=2)
    y += 50

    # Action map — what each gesture does
    text(panel, "ACTIONS (config: keystrokes " + ("ON" if keystrokes_on else "OFF") + ")",
         (12, y), scale=0.42, color=(140, 140, 150))
    y += 20
    for g, hint in GESTURE_ACTION_HINT.items():
        sym = GESTURE_EMOJI.get(g, "·")
        line = f"  [{sym}]  {g:<12}  ->  {hint}"
        active = (g == stable) or (g == fired)
        color = (255, 230, 120) if active else (180, 180, 190)
        text(panel, line, (12, y), scale=0.45, color=color)
        y += 20

    # Recent events
    y += 12
    text(panel, "RECENT EVENTS", (12, y), scale=0.42, color=(140, 140, 150))
    y += 20
    if not event_log:
        text(panel, "  (none yet — try a peace sign ✌)", (12, y), scale=0.45, color=(120, 120, 130))
        y += 18
    else:
        now = time.time()
        for ts, g in list(event_log)[:6]:
            age = now - ts
            age_str = f"{age:>4.1f}s ago" if age < 60 else f"{int(age // 60)}m ago"
            text(panel, f"  {age_str}   {g}", (12, y), scale=0.5, color=(220, 220, 230))
            y += 20

    # Footer — session stats
    panel_h = panel.shape[0]
    elapsed = time.time() - session_start
    total = sum(fire_count.values())
    cv2.rectangle(panel, (0, panel_h - 30), (panel_w, panel_h), (40, 40, 50), -1)
    text(panel, f"session: {int(elapsed)}s   ·   fired: {total}",
         (12, panel_h - 10), scale=0.45, color=(180, 180, 200))

    # Compose side-by-side
    composite = np.hstack([frame, panel])
    return composite


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
