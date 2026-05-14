"""`handsignal ask` — pop up a focused gesture prompt and return the user's choice.

Designed to be called from a wrapper, shell hook, or Claude Code PreToolUse hook.
Exit codes:
    0  approve   (thumbs_up)
    1  deny      (thumbs_down)
    2  manual    (fist — user wants to handle this themselves)
    3  timeout
    4  quit / esc
"""

from __future__ import annotations

import sys
import time
from collections import deque
from typing import Optional

from .classifier import classify, classify_sequence
from .config import Config


EXIT_APPROVE = 0
EXIT_DENY = 1
EXIT_MANUAL = 2
EXIT_TIMEOUT = 3
EXIT_QUIT = 4

# v1 vocabulary for ask mode — only 3 gestures matter.
ALLOWED_GESTURES = ("thumbs_up", "thumbs_down", "fist")
GESTURE_TO_EXIT = {
    "thumbs_up": EXIT_APPROVE,
    "thumbs_down": EXIT_DENY,
    "fist": EXIT_MANUAL,
}


def run_ask(cfg: Config, prompt: str, timeout_s: float = 15.0) -> int:
    import cv2
    import mediapipe as mp
    import numpy as np

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
        print(f"handsignal ask: camera {cfg.camera.index} unavailable", file=sys.stderr)
        return EXIT_QUIT

    fps_est = max(15, cfg.camera.fps)
    history_len = max(3, int(fps_est * cfg.detection.hold_ms / 1000))
    history: deque = deque(maxlen=history_len)

    started = time.time()
    last_label: Optional[str] = None
    last_stable: Optional[str] = None
    decision: Optional[int] = None

    window = "hand-signal — confirm"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    try:
        while True:
            elapsed = time.time() - started
            if elapsed >= timeout_s:
                return EXIT_TIMEOUT

            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            if cfg.detection.mirror:
                frame = cv2.flip(frame, 1)

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = hands.process(rgb)

            label: Optional[str] = None
            if result.multi_hand_landmarks:
                lm = result.multi_hand_landmarks[0]
                pts = np.array([[p.x, p.y, p.z] for p in lm.landmark], dtype=float)
                raw = classify(pts)
                # Restrict to ask-mode vocabulary.
                if raw in ALLOWED_GESTURES:
                    label = raw

            history.append(label)
            stable = classify_sequence(history, history_len)
            last_label = label
            last_stable = stable

            if stable in GESTURE_TO_EXIT:
                decision = GESTURE_TO_EXIT[stable]

            # Draw landmarks on the camera frame
            if result.multi_hand_landmarks:
                for hand_lms in result.multi_hand_landmarks:
                    mp_drawing.draw_landmarks(
                        frame, hand_lms, mp_hands.HAND_CONNECTIONS,
                        mp_styles.get_default_hand_landmarks_style(),
                        mp_styles.get_default_hand_connections_style(),
                    )

            composite = _render_ask_hud(
                frame=frame,
                prompt=prompt,
                candidate=last_label,
                stable=last_stable,
                time_left=max(0.0, timeout_s - elapsed),
            )
            cv2.imshow(window, composite)
            try:
                cv2.setWindowProperty(window, cv2.WND_PROP_TOPMOST, 1)
            except Exception:
                pass

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):  # q or esc
                return EXIT_QUIT

            if decision is not None:
                # Hold the result on screen briefly so the user sees what fired.
                _flash_result(window, composite, decision)
                return decision
    finally:
        cap.release()
        hands.close()
        cv2.destroyAllWindows()


def _render_ask_hud(*, frame, prompt: str, candidate, stable, time_left: float):
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    panel_w = 520
    panel = np.zeros((h, panel_w, 3), dtype=np.uint8)
    panel[:] = (22, 22, 28)

    def text(s, xy, scale=0.6, color=(220, 220, 220), thick=1):
        cv2.putText(panel, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)

    # Header
    cv2.rectangle(panel, (0, 0), (panel_w, 50), (50, 50, 65), -1)
    text("Claude needs your decision", (16, 28), scale=0.6, color=(255, 255, 255), thick=2)
    text("(advisory — you still click)", (16, 46), scale=0.4, color=(180, 180, 200))

    # Prompt — wrap to 2 lines if long
    y = 80
    cv2.rectangle(panel, (12, y - 22), (panel_w - 12, y + 56), (35, 35, 45), -1)
    wrapped = _wrap(prompt, 44)
    for line in wrapped[:3]:
        text(line, (22, y), scale=0.55, color=(230, 230, 240))
        y += 24

    # Choices — each row is a big readable target
    y = 200
    choices = [
        ("thumbs_up",   "Thumbs up",    "APPROVE",         (90, 200, 110)),
        ("thumbs_down", "Thumbs down",  "DENY",            (220, 120, 110)),
        ("fist",        "Fist",         "I'LL DO IT",      (180, 180, 220)),
    ]
    for gesture, gname, action, base in choices:
        active = (stable == gesture) or (candidate == gesture)
        bg = base if active else (45, 45, 55)
        fg = (20, 20, 25) if active else (220, 220, 230)
        cv2.rectangle(panel, (12, y), (panel_w - 12, y + 70), bg, -1)
        text(gname, (24, y + 28), scale=0.7, color=fg, thick=2)
        text(f"-> {action}", (24, y + 55), scale=0.6, color=fg)
        y += 84

    # Footer — timer + current detection
    cur = candidate if candidate else "(no hand)"
    sta = stable if stable else "-"
    text(f"seeing: {cur}    holding: {sta}", (16, panel.shape[0] - 38), scale=0.5, color=(150, 150, 170))
    text(f"timeout in {time_left:.1f}s     q to cancel", (16, panel.shape[0] - 14), scale=0.5, color=(150, 150, 170))

    return np.hstack([frame, panel])


def _flash_result(window: str, composite, decision: int) -> None:
    """Show what the user gestured — but make it explicit that the human
    still has the final say. Safe-mode v1: advisory only."""
    import cv2
    import numpy as np
    label = {EXIT_APPROVE: "YOU SIGNALED: APPROVE",
             EXIT_DENY:    "YOU SIGNALED: DENY",
             EXIT_MANUAL:  "YOU SIGNALED: I'LL DO IT"}.get(decision, "")
    sub = "Now confirm by clicking in Claude Code yourself."
    color = {EXIT_APPROVE: (60, 200, 90),
             EXIT_DENY:    (200, 80, 90),
             EXIT_MANUAL:  (180, 180, 220)}.get(decision, (200, 200, 200))
    overlay = composite.copy()
    h, w = overlay.shape[:2]
    cv2.rectangle(overlay, (0, h // 2 - 90), (w, h // 2 + 90), color, -1)
    cv2.putText(overlay, label, (40, h // 2 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(overlay, sub, (40, h // 2 + 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imshow(window, overlay)
    cv2.waitKey(1500)


def _wrap(text: str, width: int) -> list:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + 1 + len(w) <= width:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]
