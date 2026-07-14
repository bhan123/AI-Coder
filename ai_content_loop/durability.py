from __future__ import annotations

import os
from pathlib import Path


_IS_WINDOWS = os.name == "nt"


def fsync_directory(path: str | Path) -> None:
    """Best-effort directory durability on POSIX; intentionally no-op on Windows."""

    if _IS_WINDOWS:
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(Path(path), flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
