"""Set Windows file created / modified / accessed timestamps."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def _to_filetime(dt: datetime) -> int:
    """Windows FILETIME: 100-ns intervals since 1601-01-01 UTC.

    Naive datetime is treated as local time, matching the original helper.
    """
    return int((dt.timestamp() + 11644473600) * 10_000_000)


def set_file_times(
    path: str | Path,
    created: datetime | None = None,
    modified: datetime | None = None,
    accessed: datetime | None = None,
) -> None:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    if os.name != "nt":
        atime = (accessed or modified or datetime.fromtimestamp(path.stat().st_atime)).timestamp()
        mtime = (modified or datetime.fromtimestamp(path.stat().st_mtime)).timestamp()
        os.utime(path, (atime, mtime))
        return

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    def pack(dt: datetime | None) -> ctypes.POINTER(FILETIME) | None:
        if dt is None:
            return None
        value = _to_filetime(dt)
        ft = FILETIME(value & 0xFFFFFFFF, value >> 32)
        return ctypes.pointer(ft)

    GENERIC_WRITE = 0x40000000
    FILE_WRITE_ATTRIBUTES = 0x100
    FILE_SHARE_READ = 0x1
    FILE_SHARE_WRITE = 0x2
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    handle = kernel32.CreateFileW(
        str(path),
        FILE_WRITE_ATTRIBUTES | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    INVALID = ctypes.c_void_p(-1).value
    if handle == INVALID or handle == 0xFFFFFFFF:
        raise OSError(ctypes.get_last_error(), f"CreateFileW failed for {path}")
    try:
        ok = kernel32.SetFileTime(handle, pack(created), pack(accessed or modified), pack(modified))
        if not ok:
            raise OSError(ctypes.get_last_error(), f"SetFileTime failed for {path}")
    finally:
        kernel32.CloseHandle(handle)
