"""Classifier tests — synthetic 21-landmark hand poses, no camera required."""

from __future__ import annotations

import numpy as np
import pytest

from handsignal.classifier import (
    classify,
    classify_sequence,
    finger_state,
)


def _hand(curls: dict[str, bool], thumb: str = "neutral") -> np.ndarray:
    """Build a 21-landmark hand. Each finger is either 'extended' (curls[f]=False)
    or 'curled' (curls[f]=True). Thumb is 'up' | 'down' | 'neutral' | 'tucked'.
    The wrist is at (0.5, 0.9). Extended fingers reach upward; curled fingers
    stop near the palm.
    """
    pts = np.zeros((21, 3), dtype=float)
    wrist = np.array([0.5, 0.9])
    pts[0, :2] = wrist

    # Lay out the four non-thumb fingers along x. mcp / pip / tip y-positions
    # are arranged so that extended fingers have tip_y < pip_y < mcp_y < wrist_y
    # (image y grows downward → smaller y = higher in frame).
    finger_x = {"index": 0.42, "middle": 0.48, "ring": 0.54, "pinky": 0.60}
    finger_indices = {
        "index":  (5, 6, 7, 8),
        "middle": (9, 10, 11, 12),
        "ring":   (13, 14, 15, 16),
        "pinky":  (17, 18, 19, 20),
    }
    for name, (mcp, pip, dip, tip) in finger_indices.items():
        x = finger_x[name]
        pts[mcp, :2] = (x, 0.80)
        if curls.get(name, False):
            # Curled finger: knuckle bumps up, then folds back toward the palm so
            # the tip ends up *closer* to the wrist than the pip.
            pts[pip, :2] = (x, 0.74)        # knuckle bump (peak)
            pts[dip, :2] = (x - 0.005, 0.78)
            pts[tip, :2] = (x - 0.01, 0.81)  # tip back near the palm
        else:
            # Extended: each joint farther from wrist than the previous
            pts[pip, :2] = (x, 0.68)
            pts[dip, :2] = (x, 0.58)
            pts[tip, :2] = (x, 0.48)

    # Thumb (landmarks 1-4)
    # mcp at (0.40, 0.82); orientation depends on `thumb`.
    pts[1, :2] = (0.42, 0.85)
    pts[2, :2] = (0.40, 0.82)  # thumb_mcp
    if thumb == "up":
        pts[3, :2] = (0.36, 0.70)
        pts[4, :2] = (0.32, 0.55)
    elif thumb == "down":
        pts[3, :2] = (0.36, 0.95)
        pts[4, :2] = (0.32, 1.05)
    elif thumb == "tucked":
        # Curled into palm: tip very close to mcp
        pts[3, :2] = (0.42, 0.83)
        pts[4, :2] = (0.44, 0.84)
    else:  # neutral, extended to the side
        pts[3, :2] = (0.32, 0.78)
        pts[4, :2] = (0.24, 0.74)
    return pts


def test_finger_state_open_palm():
    h = _hand({"index": False, "middle": False, "ring": False, "pinky": False}, thumb="neutral")
    s = finger_state(h)
    assert s.index and s.middle and s.ring and s.pinky
    assert s.thumb_extended


def test_classify_open_palm():
    h = _hand({"index": False, "middle": False, "ring": False, "pinky": False}, thumb="neutral")
    assert classify(h) == "open_palm"


def test_classify_fist():
    h = _hand({"index": True, "middle": True, "ring": True, "pinky": True}, thumb="tucked")
    assert classify(h) == "fist"


def test_classify_thumbs_up():
    h = _hand({"index": True, "middle": True, "ring": True, "pinky": True}, thumb="up")
    assert classify(h) == "thumbs_up"


def test_classify_thumbs_down():
    h = _hand({"index": True, "middle": True, "ring": True, "pinky": True}, thumb="down")
    assert classify(h) == "thumbs_down"


def test_classify_tick_peace():
    h = _hand({"index": False, "middle": False, "ring": True, "pinky": True}, thumb="tucked")
    assert classify(h) == "tick"


def test_classify_cross_rock():
    h = _hand({"index": False, "middle": True, "ring": True, "pinky": False}, thumb="tucked")
    assert classify(h) == "cross"


def test_classify_unknown_returns_none():
    # Three fingers extended — index + middle + ring — not one of our 6.
    h = _hand({"index": False, "middle": False, "ring": False, "pinky": True}, thumb="tucked")
    assert classify(h) is None


def test_classify_sequence_stable():
    hist = ["tick", "tick", "tick", "tick"]
    assert classify_sequence(hist, 4) == "tick"


def test_classify_sequence_unstable_returns_none():
    hist = ["tick", "tick", "cross", "tick"]
    assert classify_sequence(hist, 4) is None


def test_classify_sequence_too_short():
    assert classify_sequence(["tick"], 4) is None


def test_classify_sequence_none_in_tail():
    assert classify_sequence(["tick", "tick", None, "tick"], 4) is None


def test_classify_rejects_short_input():
    with pytest.raises(ValueError):
        finger_state(np.zeros((10, 3)))
