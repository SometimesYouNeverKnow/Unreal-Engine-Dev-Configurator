"""Optional splash screen for setup runs."""

from __future__ import annotations

import os
import sys
import time
from typing import Iterable
import shutil

TAGLINE = "UE Dev Configurator - definitely not a virus."


def get_laughing_skull_frames() -> list[str]:
    """Return the large-format laughing skull animation frames."""
    base_closed = r"""
                       .:=================:.
                     .'  .-"`````"-.  `.  '.
                    /  .'  .-. .-.  '.  \   \
                   /  /  .'  ) (  '.  \  \   \
                  |  |  /  /|_|_|`\  \  |  |  |
                  |  | |  ( o   o ) | |  |  | |
                  |  | |   \  _  /   | |  |  | |
                  |  | |    '._.'    | |  |  | |
                  |  |  \    ___    /  |  |  | |
                  |  |   '._/   \_.'   |  |  | |
                  |  |    .-------.    |  |  | |
                  |  |    |  / \  |    |  |  | |
                  |  |    | |___| |    |  |  | |
                  |  |    |_/___\_|    |  |  | |
                   \  \   / /   \ \   /  /  / /
                    '. '._| |   | |_.' .' .' /
                      '-.  \_|   |_/  .-' .-'
                         '._/#####\_.'
    """

    base_half = r"""
                       .:=================:.
                     .'  .-"`````"-.  `.  '.
                    /  .'  .-. .-.  '.  \   \
                   /  /  .'  ) (  '.  \  \   \
                  |  |  /  /|_|_|`\  \  |  |  |
                  |  | |  ( o   o ) | |  |  | |
                  |  | |   \  _  /   | |  |  | |
                  |  | |    '._.'    | |  |  | |
                  |  |  \    ___    /  |  |  | |
                  |  |   '._/   \_.'   |  |  | |
                  |  |    .-------.    |  |  | |
                  |  |    |  / \  |    |  |  | |
                  |  |    | |   | |    |  |  | |
                  |  |    | |   | |    |  |  | |
                   \  \   \ \___/ /   /  /  / /
                    '. '.  '.___.'  .' .' .' /
                      '-.   \___/   .-' .-'
                         '._/#####\_.'
    """

    base_open = r"""
                       .:=================:.
                     .'  .-"`````"-.  `.  '.
                    /  .'  .-. .-.  '.  \   \
                   /  /  .'  ) (  '.  \  \   \
                  |  |  /  /|_|_|`\  \  |  |  |
                  |  | |  ( o   o ) | |  |  | |
                  |  | |   \  _  /   | |  |  | |
                  |  | |    '._.'    | |  |  | |
                  |  |  \    ___    /  |  |  | |
                  |  |   '._/   \_.'   |  |  | |
                  |  |    .-------.    |  |  | |
                  |  |    |       |    |  |  | |
                  |  |    |       |    |  |  | |
                  |  |                 |  |  | |
                   \  \   | |===| |   /  /  / /
                    '. '. |_/###\_| .' .' .' /
                      '-.  \#####/  .-' .-'
                         '._/#####\_.'
    """

    # Tight 64x18 art; all frames same width/height.
    keyframes = [base_closed, base_half, base_open, base_half]

    # 10 fps for ~4 seconds => 40 frames; repeat keyframes evenly.
    loop: list[str] = []
    repeat_pattern = [6, 4, 8, 4]  # totals 22; we will extend to 40 by duplicating cycle.
    while len(loop) < 40:
        for frame, count in zip(keyframes, repeat_pattern):
            loop.extend([frame] * count)
            if len(loop) >= 40:
                break
    return loop[:40]


def get_compact_skull_frames() -> list[str]:
    """Return a compact animation for narrow terminals."""
    closed = r"""
        .------.
       /  .--.  \
      |  (o  o)  |
      |   ____   |
      |  (____)  |
      |   |  |   |
      |   |__|   |
       \  '--'  /
        '------'
    """
    half = r"""
        .------.
       /  .--.  \
      |  (o  o)  |
      |   ____   |
      |  (____)  |
      |   \  /   |
      |    \/    |
       \  '--'  /
        '------'
    """
    open_mouth = r"""
        .------.
       /  .--.  \
      |  (o  o)  |
      |   ____   |
      |  (____)  |
      |   /  \   |
      |  /_/\_\  |
       \  '--'  /
        '------'
    """
    keyframes = [closed, half, open_mouth, half]
    loop: list[str] = []
    repeat_pattern = [6, 4, 8, 4]
    while len(loop) < 40:
        for frame, count in zip(keyframes, repeat_pattern):
            loop.extend([frame] * count)
            if len(loop) >= 40:
                break
    return loop[:40]


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


def _play_animation(duration: float = 4.0, frame_delay: float = 0.1) -> None:
    width = shutil.get_terminal_size(fallback=(80, 24)).columns
    frames = get_laughing_skull_frames() if width >= 60 else get_compact_skull_frames()
    total_frames = min(int(duration / frame_delay), len(frames))
    for index in range(total_frames):
        _clear_screen()
        _render_frame(frames[index % len(frames)], width)
        _render_tagline(width, laugh=index)
        time.sleep(frame_delay)
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
