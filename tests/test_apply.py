import os
from datetime import datetime
from pathlib import Path

from py_batch_rename.apply import apply_items, undo_items
from py_batch_rename.engine import (
    Method,
    RenameItem,
    RenameSettings,
    Status,
    fill_times,
    preview_items,
)
from py_batch_rename.timeset import set_file_times


def _write(path: Path, text: str = "x") -> None:
    path.write_text(text, encoding="utf-8")


def test_apply_and_undo(tmp_path: Path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    _write(a, "A")
    _write(b, "B")
    items = [
        RenameItem(str(tmp_path), "a.txt"),
        RenameItem(str(tmp_path), "b.txt"),
    ]
    settings = RenameSettings(method=Method.CUSTOM, new_name="f", start_number=1, width=1)
    preview_items(items, settings)
    apply_items(items, settings)
    assert (tmp_path / "f1.txt").read_text(encoding="utf-8") == "A"
    assert (tmp_path / "f2.txt").read_text(encoding="utf-8") == "B"
    snapshot = [(str(tmp_path), it.name, orig, False) for it, orig in zip(items, ["a.txt", "b.txt"])]
    # items.name already updated to new names
    errs = undo_items(snapshot)
    assert not errs
    assert a.exists() and b.exists()


def test_conflict_existing_file(tmp_path: Path):
    _write(tmp_path / "a.txt")
    _write(tmp_path / "keep.txt")
    items = [RenameItem(str(tmp_path), "a.txt", new_name="keep.txt")]
    apply_items(items, RenameSettings(method=Method.REPLACE))
    assert items[0].status is Status.EXISTS
    assert (tmp_path / "a.txt").exists()


def test_case_only_rename(tmp_path: Path):
    _write(tmp_path / "abc.txt", "ok")
    items = [RenameItem(str(tmp_path), "abc.txt", new_name="ABC.txt")]
    apply_items(items, RenameSettings())
    names = os.listdir(tmp_path)
    assert "ABC.txt" in names
    assert items[0].status is Status.SUCCESS
    assert (tmp_path / "ABC.txt").read_text(encoding="utf-8") == "ok"


def test_missing_source_reported(tmp_path: Path):
    items = [RenameItem(str(tmp_path), "gone.txt", new_name="next.txt")]
    apply_items(items, RenameSettings(method=Method.CUSTOM))
    assert items[0].status is Status.MISSING


def test_duplicate_preview_is_not_applied(tmp_path: Path):
    _write(tmp_path / "a.txt", "A")
    _write(tmp_path / "b.txt", "B")
    items = [
        RenameItem(str(tmp_path), "a.txt"),
        RenameItem(str(tmp_path), "b.txt"),
    ]
    settings = RenameSettings(method=Method.CUSTOM, new_name="same", start_number=1, increment=0, width=1)
    preview_items(items, settings)
    assert all(it.status is Status.DUPLICATE for it in items)
    apply_items(items, settings)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "A"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "B"
    assert not (tmp_path / "same1.txt").exists()


def test_chain_rename_vacates_before_claiming_dest(tmp_path: Path):
    _write(tmp_path / "1.txt", "one")
    _write(tmp_path / "2.txt", "two")
    items = [
        RenameItem(str(tmp_path), "1.txt"),
        RenameItem(str(tmp_path), "2.txt"),
    ]
    settings = RenameSettings(method=Method.CUSTOM, start_number=2, increment=1, width=1)
    preview_items(items, settings)
    assert [it.new_name for it in items] == ["2.txt", "3.txt"]
    apply_items(items, settings)
    assert all(it.status is Status.SUCCESS for it in items)
    assert (tmp_path / "2.txt").read_text(encoding="utf-8") == "one"
    assert (tmp_path / "3.txt").read_text(encoding="utf-8") == "two"
    assert not (tmp_path / "1.txt").exists()


def test_time_attr_sets_mtime_and_birthtime(tmp_path: Path):
    path = tmp_path / "timed.txt"
    _write(path, "t")
    items = [RenameItem(str(tmp_path), "timed.txt")]
    fill_times(items)
    target = datetime(2021, 2, 3, 4, 5, 6)
    settings = RenameSettings(method=Method.TIME_ATTR, created=target, modified=target)
    apply_items(items, settings)
    assert items[0].status is Status.SUCCESS
    st = path.stat()
    assert abs(st.st_mtime - target.timestamp()) < 2
    birth = getattr(st, "st_birthtime", None)
    if birth:
        assert abs(birth - target.timestamp()) < 2
    else:
        set_file_times(path, created=target, modified=target)
        st2 = path.stat()
        assert abs(st2.st_mtime - target.timestamp()) < 2
