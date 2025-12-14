"""Optional splash screen for setup runs."""

from __future__ import annotations

import os
import shutil
import sys
import time
from typing import Iterable


SKULL_FRAMES = [
    r"""
                .-=========-.
              .' =-  ___  -= '.
             /  .-"`   `"-._  \
            /  /  .--.--.  \  \
           |  |  /  _  _ \  |  |
           |  | |  (o)(o) | |  |
           |  | |   ___   | |  |
           |  | |  (___)  | |  |
           |  |  \  V /  /  |  |
           |  |   '---'     |  |
           |  |  ._____..   |  |
           |  |  \_____/    |  |
           |  |   /   \     |  |
            \  \  `-.-'   /  /
             '. '-.___.-' .'
               '-._____.-'
""",
    r"""
                .-=========-.
              .' =-  ___  -= '.
             /  .-"`   `"-._  \
            /  /  .--.--.  \  \
           |  |  /  ^  ^ \  |  |
           |  | |  (x)(x) | |  |
           |  | |   ___   | |  |
           |  | |  (___)  | |  |
           |  |  \  V /  /  |  |
           |  |   '---'     |  |
           |  |  ._____..   |  |
           |  |  \_____/    |  |
           |  |   /   \     |  |
            \  \  `-.-'   /  /
             '. '-.___.-' .'
               '-._____.-'
""",
]

SMALL_FRAMES = [
    r"""
    .------.
   /  .--.  \
  |  (o  o)  |
  |   ____   |
  |  (____)  |
  |   \  /   |
  |    \/    |
   \  .--.  /
    '------'
""",
    r"""
    .------.
   /  .--.  \
  |  (x  x)  |
  |   ____   |
  |  (____)  |
  |  /\  /\  |
  |  \/  \/  |
   \  haha  /
    '------'
""",
]

TAGLINE = "UE Dev Configurator - definitely not a virus."


def maybe_show_splash(options) -> None:
    """Render the splash screen if the session allows it."""
    try:
        if not getattr(options, "show_splash", False):
            return
        if os.environ.get("UECFG_NO_SPLASH") == "1":
            return
        if not sys.stdin.isatty():
            return
        _play_animation()
    except Exception:
        # Splash is strictly cosmetic; ignore any failure.
        return


def _play_animation(duration: float = 4.0, frame_delay: float = 0.4) -> None:
    width = shutil.get_terminal_size(fallback=(80, 24)).columns
    frames = SKULL_FRAMES if width >= 60 else SMALL_FRAMES
    start = time.time()
    index = 0
    while time.time() - start < duration:
        _clear_screen()
        _render_frame(frames[index % len(frames)], width)
        _render_tagline(width, laugh=index)
        time.sleep(frame_delay)
        index += 1
    _clear_screen()


def _render_frame(frame: str, width: int) -> None:
    for line in _normalize_lines(frame):
        print(line.center(width))


def _render_tagline(width: int, laugh: int = 0) -> None:
    laugh_cycle = ["BWA", "HA", "HA"]
    ticker = " ".join(laugh_cycle[: (laugh % len(laugh_cycle)) + 1])
    print()
    print(TAGLINE.center(width))
    print(f"[{ticker}]".center(width))


def _normalize_lines(block: str) -> Iterable[str]:
    return [line.rstrip("\n") for line in block.strip("\n").splitlines()]


def _clear_screen() -> None:
    if os.name == "nt":
        os.system("cls")  # nosec - cosmetic terminal clear
    else:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
