"""Collect files or folders into RenameItem rows."""

from __future__ import annotations

from pathlib import Path

from .engine import RenameItem, fill_times, natural_sort_key


def _make_item(path: Path, is_dir: bool) -> RenameItem:
    path = path.resolve()
    return RenameItem(
        directory=str(path.parent),
        name=path.name,
        is_dir=is_dir,
    )


def add_paths(paths: list[str | Path], folders: bool = False) -> list[RenameItem]:
    items: list[RenameItem] = []
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            continue
        if folders:
            if p.is_dir():
                items.append(_make_item(p, True))
        elif p.is_file():
            items.append(_make_item(p, False))
    fill_times(items)
    return items


def add_directory_files(directory: str | Path, recursive: bool = False) -> list[RenameItem]:
    root = Path(directory)
    if not root.is_dir():
        return []
    iterator = root.rglob("*") if recursive else root.iterdir()
    items: list[RenameItem] = []
    paths = [p for p in iterator if p.is_file()]
    paths.sort(key=lambda p: (natural_sort_key(p.name), str(p.parent).casefold()))
    for p in paths:
        items.append(_make_item(p, False))
    fill_times(items)
    return items


def merge_unique(existing: list[RenameItem], incoming: list[RenameItem]) -> list[RenameItem]:
    seen = {(it.directory.lower(), it.name.lower(), it.is_dir) for it in existing}
    out = list(existing)
    for it in incoming:
        key = (it.directory.lower(), it.name.lower(), it.is_dir)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
