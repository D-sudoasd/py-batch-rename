"""Apply and undo rename operations with Windows-safe two-phase moves."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from .engine import Method, RenameItem, RenameSettings, Status, STATUS_LABEL
from .timeset import set_file_times


def _same_path(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except OSError:
        return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _exists_other(dest: Path, src: Path) -> bool:
    if not dest.exists():
        return False
    return not _same_path(dest, src)


def apply_items(items: list[RenameItem], settings: RenameSettings) -> list[RenameItem]:
    if settings.method is Method.TIME_ATTR:
        return _apply_times(items, settings)
    return _apply_renames(items)


def _apply_times(items: list[RenameItem], settings: RenameSettings) -> list[RenameItem]:
    if settings.created is None and settings.modified is None:
        for item in items:
            item.status = Status.FAILED
            item.message = "请选择需要更改的时间"
        return items
    for item in items:
        src = item.src_path
        if not src.exists():
            item.status = Status.MISSING
            item.message = STATUS_LABEL[Status.MISSING]
            continue
        created = settings.created or item.created
        modified = settings.modified or item.modified
        try:
            set_file_times(src, created=created, modified=modified, accessed=modified)
            item.status = Status.SUCCESS
            item.message = STATUS_LABEL[Status.SUCCESS]
            if created:
                item.created = created
            if modified:
                item.modified = modified
        except OSError as exc:
            item.status = Status.FAILED
            item.message = str(exc)
    return items


def _apply_renames(items: list[RenameItem]) -> list[RenameItem]:
    planned: list[tuple[RenameItem, Path, Path]] = []
    dest_used: dict[str, int] = {}

    for item in items:
        src = item.src_path
        dest = item.dest_path
        if item.status in {Status.FAILED, Status.DUPLICATE}:
            continue
        if item.new_name == item.name:
            item.status = Status.SKIPPED
            item.message = STATUS_LABEL[Status.SKIPPED]
            continue
        if not src.exists():
            item.status = Status.MISSING
            item.message = STATUS_LABEL[Status.MISSING]
            continue
        key = os.path.normcase(str(dest))
        dest_used[key] = dest_used.get(key, 0) + 1
        planned.append((item, src, dest))

    batch_src = {os.path.normcase(str(src)) for _, src, _ in planned}
    collisions = {k for k, n in dest_used.items() if n > 1}

    # First pass: files whose destination is still occupied by another source
    # in this batch get a temporary name.
    temps: list[tuple[RenameItem, Path, Path]] = []
    finals: list[tuple[RenameItem, Path, Path]] = []
    for item, src, dest in planned:
        dest_key = os.path.normcase(str(dest))
        if dest_key in collisions:
            item.status = Status.EXISTS
            item.message = STATUS_LABEL[Status.EXISTS]
            continue
        needs_temp = False
        if _exists_other(dest, src):
            if os.path.normcase(str(dest)) in batch_src:
                needs_temp = True
            else:
                item.status = Status.EXISTS
                item.message = STATUS_LABEL[Status.EXISTS]
                continue
        elif os.name == "nt" and os.path.normcase(item.name) == os.path.normcase(item.new_name):
            needs_temp = True
        if needs_temp:
            temps.append((item, src, dest))
        else:
            finals.append((item, src, dest))

    parked: list[tuple[RenameItem, Path, Path, Path]] = []
    for item, src, dest in temps:
        tmp = src.with_name(f".__rename_{uuid.uuid4().hex[:8]}__{src.name}")
        try:
            src.rename(tmp)
            parked.append((item, src, dest, tmp))
        except OSError as exc:
            item.status = Status.FAILED
            item.message = str(exc)

    for item, src, dest in finals:
        try:
            src.rename(dest)
            item.name = item.new_name
            item.status = Status.SUCCESS
            item.message = STATUS_LABEL[Status.SUCCESS]
        except OSError as exc:
            item.status = Status.FAILED
            item.message = str(exc)

    for item, src, dest, tmp in parked:
        try:
            tmp.rename(dest)
            item.name = item.new_name
            item.status = Status.SUCCESS
            item.message = STATUS_LABEL[Status.SUCCESS]
        except OSError as exc:
            try:
                tmp.rename(src)
            except OSError:
                pass
            item.status = Status.FAILED
            item.message = str(exc)

    return items


def undo_items(snapshot: list[tuple[str, str, str, bool]]) -> list[str]:
    """snapshot: list of (directory, current_name, original_name, is_dir)."""
    errors: list[str] = []
    for directory, current, original, _is_dir in snapshot:
        src = Path(directory) / current
        dest = Path(directory) / original
        if current == original:
            continue
        if not src.exists():
            errors.append(f"找不到 {src}")
            continue
        if dest.exists() and os.path.normcase(str(src)) != os.path.normcase(str(dest)):
            errors.append(f"目标已存在 {dest}")
            continue
        try:
            if os.name == "nt" and os.path.normcase(current) == os.path.normcase(original):
                tmp = src.with_name(f".__undo_{uuid.uuid4().hex[:8]}__{src.name}")
                src.rename(tmp)
                tmp.rename(dest)
            else:
                src.rename(dest)
        except OSError as exc:
            errors.append(f"{src} -> {dest}: {exc}")
    return errors
