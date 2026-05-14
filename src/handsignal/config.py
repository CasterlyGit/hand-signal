"""Config loader: ~/.config/hand-signal/config.toml."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]


CONFIG_PATH = Path(
    os.environ.get("HANDSIGNAL_CONFIG", "~/.config/hand-signal/config.toml")
).expanduser()


# Gesture vocabulary — v0.1 uses 6 universal signals.
DEFAULT_GESTURES = ("tick", "cross", "thumbs_up", "thumbs_down", "open_palm", "fist")


@dataclass
class CameraConfig:
    index: int = 0          # /dev/video<index>
    width: int = 640
    height: int = 480
    fps: int = 30


@dataclass
class DetectionConfig:
    hold_ms: int = 400              # gesture must be stable this long to fire
    cooldown_ms: int = 1000         # min gap between fires (any gesture)
    min_confidence: float = 0.7     # MediaPipe detection confidence
    min_tracking: float = 0.5       # MediaPipe tracking confidence
    mirror: bool = True             # flip the frame horizontally (selfie view)


@dataclass
class OutputConfig:
    print_events: bool = True
    keystrokes_enabled: bool = False
    websocket_enabled: bool = False
    websocket_port: int = 8765
    # Per-gesture keystroke. Values are pynput-friendly:
    #   "enter", "esc", "tab", "space", "y", "n", or a chord like "cmd+v".
    keymap: Dict[str, str] = field(default_factory=lambda: {
        "tick":         "enter",
        "cross":        "esc",
        "thumbs_up":    "enter",
        "thumbs_down":  "n",
        "open_palm":    "ctrl+c",
        "fist":         "esc",
    })


@dataclass
class HotkeyConfig:
    # Optional: hold-to-arm. When set, the daemon only classifies while this key is held.
    # Empty string = always-on. Same naming as laptop-dictation (pynput key names).
    arm_key: str = ""


@dataclass
class Config:
    camera: CameraConfig = field(default_factory=CameraConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)


DEFAULT_TOML = """\
# hand-signal config — edit to taste
[camera]
index = 0
width = 640
height = 480
fps = 30

[detection]
hold_ms = 400              # gesture must be stable this long to fire
cooldown_ms = 1000         # min gap between any two fires
min_confidence = 0.7
min_tracking = 0.5
mirror = true              # selfie view

[output]
print_events = true
keystrokes_enabled = false # set true to actually inject keys (requires Accessibility on macOS)
websocket_enabled = false  # set true to broadcast events on ws://localhost:<port>
websocket_port = 8765

[output.keymap]
tick         = "enter"
cross        = "esc"
thumbs_up    = "enter"
thumbs_down  = "n"
open_palm    = "ctrl+c"
fist         = "esc"

[hotkey]
# Hold-to-arm key. Leave empty for always-on. Try "alt_r" or "cmd_r" to mirror laptop-dictation.
arm_key = ""
"""


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return _from_dict(raw)


def _from_dict(raw: Dict[str, Any]) -> Config:
    cfg = Config()
    if "camera" in raw:
        cfg.camera = CameraConfig(**{k: v for k, v in raw["camera"].items() if k in CameraConfig.__dataclass_fields__})
    if "detection" in raw:
        cfg.detection = DetectionConfig(**{k: v for k, v in raw["detection"].items() if k in DetectionConfig.__dataclass_fields__})
    if "output" in raw:
        out_raw = dict(raw["output"])
        keymap = out_raw.pop("keymap", None)
        cfg.output = OutputConfig(**{k: v for k, v in out_raw.items() if k in OutputConfig.__dataclass_fields__})
        if isinstance(keymap, dict):
            cfg.output.keymap = {**cfg.output.keymap, **{str(k): str(v) for k, v in keymap.items()}}
    if "hotkey" in raw:
        cfg.hotkey = HotkeyConfig(**{k: v for k, v in raw["hotkey"].items() if k in HotkeyConfig.__dataclass_fields__})
    return cfg


def write_default_config(path: Path = CONFIG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_TOML, encoding="utf-8")
    return path
