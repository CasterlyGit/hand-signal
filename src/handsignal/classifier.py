"""Gesture classifier — pure functions on 21-landmark MediaPipe Hands output.

Landmark indices (MediaPipe Hands):
    0  wrist
    1-4   thumb (cmc, mcp, ip, tip)
    5-8   index (mcp, pip, dip, tip)
    9-12  middle
    13-16 ring
    17-20 pinky

We deliberately keep this dependency-light: callers pass `np.ndarray` of shape
(21, 3) or (21, 2). No MediaPipe imports here so tests can run on CI without a
camera.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np


GestureLabel = str  # one of DEFAULT_GESTURES in config


# Landmark indices
WRIST = 0
THUMB_TIP, THUMB_IP, THUMB_MCP = 4, 3, 2
INDEX_TIP, INDEX_PIP, INDEX_MCP = 8, 6, 5
MIDDLE_TIP, MIDDLE_PIP, MIDDLE_MCP = 12, 10, 9
RING_TIP, RING_PIP, RING_MCP = 16, 14, 13
PINKY_TIP, PINKY_PIP, PINKY_MCP = 20, 18, 17

FINGER_TIPS = (INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)
FINGER_PIPS = (INDEX_PIP, MIDDLE_PIP, RING_PIP, PINKY_PIP)
FINGER_MCPS = (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)


@dataclass
class FingerState:
    """Per-finger extension state. True = extended (straight)."""
    index: bool
    middle: bool
    ring: bool
    pinky: bool
    thumb_up: bool      # thumb pointing roughly upward (image y decreasing)
    thumb_down: bool    # thumb pointing roughly downward
    thumb_extended: bool  # thumb is straight (not curled into palm)

    def count_extended_fingers(self) -> int:
        """Count extended non-thumb fingers."""
        return sum((self.index, self.middle, self.ring, self.pinky))


def _finger_extended(lm: np.ndarray, tip: int, pip: int, mcp: int) -> bool:
    """A finger is extended when its tip is farther from the wrist than its pip,
    and the pip is farther from the wrist than its mcp.
    Uses 2D image distance — robust enough for the classes we care about."""
    wrist = lm[WRIST, :2]
    d_tip = np.linalg.norm(lm[tip, :2] - wrist)
    d_pip = np.linalg.norm(lm[pip, :2] - wrist)
    d_mcp = np.linalg.norm(lm[mcp, :2] - wrist)
    return d_tip > d_pip > d_mcp


def _thumb_state(lm: np.ndarray) -> tuple[bool, bool, bool]:
    """Return (thumb_up, thumb_down, extended). Image y increases downward."""
    tip = lm[THUMB_TIP, :2]
    ip = lm[THUMB_IP, :2]
    mcp = lm[THUMB_MCP, :2]
    wrist = lm[WRIST, :2]
    # Extended: tip farther from wrist than ip
    extended = np.linalg.norm(tip - wrist) > np.linalg.norm(ip - wrist) + 0.005
    dy = tip[1] - mcp[1]
    # Pointing up: tip well above mcp. Down: well below.
    span = abs(np.linalg.norm(tip - wrist))
    threshold = max(0.04, 0.25 * span)
    return (dy < -threshold and extended,
            dy > threshold and extended,
            extended)


def finger_state(landmarks: np.ndarray) -> FingerState:
    """Convert raw landmarks → FingerState."""
    lm = np.asarray(landmarks, dtype=float)
    if lm.shape[0] < 21:
        raise ValueError(f"expected 21 landmarks, got {lm.shape}")
    idx = _finger_extended(lm, INDEX_TIP, INDEX_PIP, INDEX_MCP)
    mid = _finger_extended(lm, MIDDLE_TIP, MIDDLE_PIP, MIDDLE_MCP)
    rng = _finger_extended(lm, RING_TIP, RING_PIP, RING_MCP)
    pnk = _finger_extended(lm, PINKY_TIP, PINKY_PIP, PINKY_MCP)
    tu, td, te = _thumb_state(lm)
    return FingerState(idx, mid, rng, pnk, tu, td, te)


def classify(landmarks: np.ndarray) -> Optional[GestureLabel]:
    """Return one of:
        - "thumbs_up"
        - "thumbs_down"
        - "open_palm"        — all 5 fingers extended
        - "fist"             — no fingers extended (or only thumb curled)
        - "tick"             — index + middle extended (peace / v / check)
        - "cross"            — index + pinky extended, middle + ring curled (rock)
        - None               — unknown / unstable
    Single-frame classifier. Stability is enforced by the daemon's hold timer.
    """
    s = finger_state(landmarks)
    n = s.count_extended_fingers()

    # Thumbs up / down: thumb pointing, all other fingers curled
    if n == 0:
        if s.thumb_up:
            return "thumbs_up"
        if s.thumb_down:
            return "thumbs_down"
        # Pure fist: thumb tucked too
        return "fist"

    if n == 4 and s.thumb_extended:
        return "open_palm"

    # Tick / peace: index + middle only
    if s.index and s.middle and not s.ring and not s.pinky:
        return "tick"

    # Cross / rock: index + pinky only
    if s.index and not s.middle and not s.ring and s.pinky:
        return "cross"

    return None


def classify_sequence(history: Sequence[Optional[GestureLabel]], min_agree: int) -> Optional[GestureLabel]:
    """Return a label only if the last `min_agree` frames all agree (non-None).
    Used by the daemon to enforce the hold-time requirement."""
    if len(history) < min_agree:
        return None
    tail = history[-min_agree:]
    first = tail[0]
    if first is None:
        return None
    if all(h == first for h in tail):
        return first
    return None
