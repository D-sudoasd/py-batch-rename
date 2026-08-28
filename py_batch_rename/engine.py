"""Rename preview engine.

Independent reimplementation of common batch-rename rules:
custom+serial, find/replace, insert, delete, Excel import,
one-click strip, and time-based names.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence


class Method(str, Enum):
    CUSTOM = "custom"
    REPLACE = "replace"
    INSERT = "insert"
    DELETE = "delete"
    TIME_ATTR = "time_attr"
    IMPORT = "import"
    QUICK_DELETE = "quick_delete"
    TIME_NAME = "time_name"


class CaseMode(str, Enum):
    KEEP = "keep"
    UPPER = "upper"
    LOWER = "lower"
    FIRST_UPPER = "first_upper"
    FIRST_LOWER = "first_lower"


class InsertKind(str, Enum):
    TEXT = "text"
    NUMBER = "number"


class InsertWhere(str, Enum):
    INDEX = "index"
    HEAD = "head"
    TAIL = "tail"


class DeleteKind(str, Enum):
    TEXT = "text"
    RANGE = "range"


class QuickDelete(str, Enum):
    BRACKETS = "brackets"
    SPACES = "spaces"
    LETTERS = "letters"
    DIGITS = "digits"
    QUOTES = "quotes"


class ExtMode(str, Enum):
    SET = "set"
    REPLACE = "replace"


class TimeSource(str, Enum):
    CREATED = "created"
    MODIFIED = "modified"


WIN_INVALID = re.compile(r'[<>:"/\\|?*]')

# Characters that the original Electron tool escaped in find/replace.
_FIND_ESCAPE = frozenset("$()+.[^{|")


class Status(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    MISSING = "missing"
    EXISTS = "exists"
    SKIPPED = "skipped"
    DUPLICATE = "duplicate"


STATUS_LABEL = {
    Status.PENDING: "待操作",
    Status.SUCCESS: "修改成功",
    Status.FAILED: "修改失败",
    Status.MISSING: "原文件不存在",
    Status.EXISTS: "目标已存在",
    Status.SKIPPED: "无需改名",
    Status.DUPLICATE: "批次内目标重名",
}

_NAT_PARTS = re.compile(r"(\d+)")


@dataclass
class RenameSettings:
    method: Method = Method.CUSTOM
    new_name: str = ""
    find: str = ""
    replace: str = ""
    insert_kind: InsertKind = InsertKind.TEXT
    insert_text: str = ""
    insert_where: InsertWhere = InsertWhere.INDEX
    insert_index: int = 1
    delete_kind: DeleteKind = DeleteKind.TEXT
    delete_text: str = ""
    delete_start: int = 1
    delete_length: int = 1
    quick_delete: QuickDelete = QuickDelete.BRACKETS
    case: CaseMode = CaseMode.KEEP
    start_number: int = 0
    increment: int = 1
    width: int = 1
    ext_mode: ExtMode = ExtMode.SET
    new_ext: str = ""
    ext_find: str = ""
    ext_replace: str = ""
    ext_case: CaseMode = CaseMode.KEEP
    time_source: TimeSource = TimeSource.CREATED
    time_style: str = "yyyy-mm-dd hh-mm-ss"
    created: datetime | None = None
    modified: datetime | None = None
    imported_names: list[str] = field(default_factory=list)


@dataclass
class RenameItem:
    directory: str
    name: str
    is_dir: bool = False
    created: datetime | None = None
    modified: datetime | None = None
    new_name: str = ""
    status: Status = Status.PENDING
    message: str = ""

    @property
    def src_path(self) -> Path:
        return Path(self.directory) / self.name

    @property
    def dest_path(self) -> Path:
        return Path(self.directory) / (self.new_name or self.name)


def pad_number(value: int, width: int) -> str:
    text = str(int(value))
    if width > len(text):
        return text.zfill(width)
    return text


def serial_at(index: int, start: int, increment: int, width: int) -> str:
    return pad_number(increment * index + start, width)


def apply_case(text: str, mode: CaseMode) -> str:
    if not text:
        return text
    if mode is CaseMode.UPPER:
        return text.upper()
    if mode is CaseMode.LOWER:
        return text.lower()
    if mode is CaseMode.FIRST_UPPER:
        return text[0].upper() + text[1:]
    if mode is CaseMode.FIRST_LOWER:
        return text[0].lower() + text[1:]
    return text


def escape_find(text: str) -> str:
    return "".join("\\" + ch if ch in _FIND_ESCAPE else ch for ch in text)


def split_filename(name: str, is_dir: bool) -> tuple[str, str]:
    """Return (stem, extension_without_dot). Directories keep the full name."""
    if is_dir:
        return name, ""
    dot = name.rfind(".")
    if dot <= 0:
        return name, ""
    return name[:dot], name[dot + 1 :]


def format_file_time(dt: datetime, style: str | None = None) -> str:
    """Format like the original: first `mm` is month, second `mm` is minute."""
    year = f"{dt.year:04d}"
    month = f"{dt.month:02d}"
    day = f"{dt.day:02d}"
    hour = f"{dt.hour:02d}"
    minute = f"{dt.minute:02d}"
    second = f"{dt.second:02d}"
    if not style:
        return "-".join((year, month, day, hour, minute, second))
    out = style
    out = out.replace("yyyy", year, 1)
    out = out.replace("mm", month, 1)
    out = out.replace("dd", day, 1)
    out = out.replace("hh", hour, 1)
    out = out.replace("mm", minute, 1)
    out = out.replace("ss", second, 1)
    return out


def _time_of(item: RenameItem, source: TimeSource) -> datetime | None:
    if source is TimeSource.CREATED:
        return item.created
    return item.modified


def _quick_delete(stem: str, kind: QuickDelete) -> str:
    if kind is QuickDelete.BRACKETS:
        return re.sub(r"[()（）]", "", stem)
    if kind is QuickDelete.SPACES:
        return re.sub(r"\s+", "", stem)
    if kind is QuickDelete.LETTERS:
        return re.sub(r"[a-zA-Z]+", "", stem)
    if kind is QuickDelete.DIGITS:
        return re.sub(r"[0-9]+", "", stem)
    if kind is QuickDelete.QUOTES:
        return re.sub(r"['\"‘’“”]", "", stem)
    return stem


def preview_name(item: RenameItem, index: int, settings: RenameSettings) -> str:
    stem, ext = split_filename(item.name, item.is_dir)
    method = settings.method
    new_stem = stem

    if method is Method.CUSTOM:
        serial = serial_at(index, settings.start_number, settings.increment, settings.width)
        new_stem = f"{settings.new_name}{serial}" if settings.new_name else serial
    elif method is Method.REPLACE:
        if settings.find:
            new_stem = re.sub(escape_find(settings.find), settings.replace, stem)
    elif method is Method.INSERT:
        if settings.insert_kind is InsertKind.NUMBER:
            inserted = serial_at(index, settings.start_number, settings.increment, settings.width)
        else:
            inserted = settings.insert_text
        if settings.insert_where is InsertWhere.HEAD:
            new_stem = inserted + stem
        elif settings.insert_where is InsertWhere.TAIL:
            new_stem = stem + inserted
        else:
            pos = max(settings.insert_index, 1) - 1
            new_stem = stem[:pos] + inserted + stem[pos:]
    elif method is Method.DELETE:
        if settings.delete_kind is DeleteKind.TEXT:
            if settings.delete_text:
                new_stem = re.sub(escape_find(settings.delete_text), "", stem)
        else:
            start = max(settings.delete_start, 1) - 1
            length = max(settings.delete_length, 0)
            new_stem = stem[:start] + stem[start + length :]
    elif method is Method.TIME_ATTR:
        return item.name
    elif method is Method.IMPORT:
        if index < len(settings.imported_names):
            imported = str(settings.imported_names[index] or "").replace("\f", "")
            imported = re.sub(r"[\n\r\t\v]+", "", imported)
            if item.is_dir:
                return imported or item.name
            if imported:
                return imported + (f".{ext}" if ext else "")
        if item.is_dir:
            return item.name
        return item.name
    elif method is Method.QUICK_DELETE:
        new_stem = _quick_delete(stem, settings.quick_delete)
    elif method is Method.TIME_NAME:
        dt = _time_of(item, settings.time_source)
        if dt is None:
            new_stem = stem
        else:
            new_stem = format_file_time(dt, settings.time_style)

    new_stem = str(new_stem)
    if item.is_dir:
        return apply_case(new_stem, settings.case)

    new_stem = apply_case(new_stem, settings.case)
    if settings.ext_mode is ExtMode.SET:
        new_ext = settings.new_ext.strip().lstrip(".") if settings.new_ext else ext
    else:
        new_ext = re.sub(escape_find(settings.ext_find), settings.ext_replace, ext) if settings.ext_find else ext
    new_ext = apply_case(str(new_ext), settings.ext_case)
    if new_ext:
        return f"{new_stem}.{new_ext}"
    return new_stem


def dest_key(item: RenameItem) -> str:
    dest = str(Path(item.directory) / (item.new_name or item.name))
    return os.path.normcase(os.path.normpath(dest))


def natural_sort_key(text: str) -> tuple:
    parts: list[tuple[int, int | str]] = []
    for part in _NAT_PARTS.split(text):
        if not part:
            continue
        if part.isdigit():
            parts.append((1, int(part)))
        else:
            parts.append((0, part.casefold()))
    return tuple(parts)


def sort_items_naturally(items: list[RenameItem]) -> list[RenameItem]:
    items.sort(key=lambda it: (natural_sort_key(it.name), it.directory.casefold(), it.is_dir))
    return items


def preview_items(items: Sequence[RenameItem], settings: RenameSettings) -> list[RenameItem]:
    for i, item in enumerate(items):
        try:
            item.new_name = preview_name(item, i, settings)
            if item.new_name == item.name and settings.method is not Method.TIME_ATTR:
                item.status = Status.SKIPPED
                item.message = STATUS_LABEL[Status.SKIPPED]
            else:
                item.status = Status.PENDING
                item.message = STATUS_LABEL[Status.PENDING]
            if WIN_INVALID.search(item.new_name) or item.new_name in {".", ".."} or not item.new_name.strip():
                item.status = Status.FAILED
                item.message = "新文件名含非法字符"
        except re.error as exc:
            item.new_name = item.name
            item.status = Status.FAILED
            item.message = f"规则错误: {exc}"
    counts = Counter(
        dest_key(item) for item in items if item.status is not Status.FAILED
    )
    for item in items:
        if item.status is Status.FAILED:
            continue
        if counts[dest_key(item)] > 1:
            item.status = Status.DUPLICATE
            item.message = STATUS_LABEL[Status.DUPLICATE]
    return list(items)


def fill_times(items: Iterable[RenameItem]) -> None:
    for item in items:
        src = item.src_path
        if not src.exists():
            continue
        try:
            stat = src.stat()
        except OSError:
            continue
        item.modified = datetime.fromtimestamp(stat.st_mtime)
        birth = getattr(stat, "st_birthtime", None)
        if birth:
            item.created = datetime.fromtimestamp(birth)
        else:
            item.created = datetime.fromtimestamp(stat.st_ctime)
