from datetime import datetime
from pathlib import Path

from py_batch_rename.engine import (
    CaseMode,
    DeleteKind,
    ExtMode,
    InsertKind,
    InsertWhere,
    Method,
    QuickDelete,
    RenameItem,
    RenameSettings,
    Status,
    TimeSource,
    format_file_time,
    preview_items,
    preview_name,
    serial_at,
    sort_items_naturally,
    split_filename,
)
from py_batch_rename.excel import load_name_column


def item(name: str, is_dir: bool = False, **kwargs) -> RenameItem:
    return RenameItem(directory="C:\\tmp", name=name, is_dir=is_dir, **kwargs)


def test_split_filename():
    assert split_filename("a.txt", False) == ("a", "txt")
    assert split_filename("noext", False) == ("noext", "")
    assert split_filename(".gitignore", False) == (".gitignore", "")
    assert split_filename("a.b.c", False) == ("a.b", "c")
    assert split_filename("folder.v2", True) == ("folder.v2", "")


def test_serial_padding():
    assert serial_at(0, 1, 1, 3) == "001"
    assert serial_at(2, 0, 1, 1) == "2"
    assert serial_at(0, 1000, 1, 3) == "1000"


def test_custom_with_prefix():
    s = RenameSettings(method=Method.CUSTOM, new_name="照片", start_number=1, increment=1, width=3)
    assert preview_name(item("a.jpg"), 0, s) == "照片001.jpg"
    assert preview_name(item("b.jpg"), 1, s) == "照片002.jpg"


def test_custom_number_only():
    s = RenameSettings(method=Method.CUSTOM, start_number=1, width=3)
    assert preview_name(item("x.png"), 0, s) == "001.png"


def test_replace_and_case():
    s = RenameSettings(method=Method.REPLACE, find="草稿", replace="终稿", case=CaseMode.LOWER)
    assert preview_name(item("草稿A.TXT"), 0, s) == "终稿a.TXT"


def test_replace_escapes_dot():
    s = RenameSettings(method=Method.REPLACE, find="a.b", replace="x")
    assert preview_name(item("a.b-aXb.txt"), 0, s) == "x-aXb.txt"


def test_insert_head_tail_index():
    head = RenameSettings(method=Method.INSERT, insert_text="pre_", insert_where=InsertWhere.HEAD)
    tail = RenameSettings(method=Method.INSERT, insert_text="_end", insert_where=InsertWhere.TAIL)
    idx = RenameSettings(
        method=Method.INSERT, insert_text="X", insert_where=InsertWhere.INDEX, insert_index=2
    )
    assert preview_name(item("abc.txt"), 0, head) == "pre_abc.txt"
    assert preview_name(item("abc.txt"), 0, tail) == "abc_end.txt"
    assert preview_name(item("abc.txt"), 0, idx) == "aXbc.txt"


def test_insert_number():
    s = RenameSettings(
        method=Method.INSERT,
        insert_kind=InsertKind.NUMBER,
        insert_where=InsertWhere.HEAD,
        start_number=1,
        width=2,
    )
    assert preview_name(item("a.txt"), 0, s) == "01a.txt"
    assert preview_name(item("b.txt"), 1, s) == "02b.txt"


def test_delete_text_and_range():
    text = RenameSettings(method=Method.DELETE, delete_text="副本")
    rng = RenameSettings(
        method=Method.DELETE, delete_kind=DeleteKind.RANGE, delete_start=1, delete_length=2
    )
    assert preview_name(item("文件副本.txt"), 0, text) == "文件.txt"
    assert preview_name(item("abcdef.txt"), 0, rng) == "cdef.txt"
    overlapping = RenameSettings(
        method=Method.DELETE, delete_kind=DeleteKind.RANGE, delete_start=5, delete_length=3
    )
    assert preview_name(item("abcXabc.txt"), 0, overlapping) == "abcX.txt"


def test_quick_delete():
    br = RenameSettings(method=Method.QUICK_DELETE, quick_delete=QuickDelete.BRACKETS)
    sp = RenameSettings(method=Method.QUICK_DELETE, quick_delete=QuickDelete.SPACES)
    let = RenameSettings(method=Method.QUICK_DELETE, quick_delete=QuickDelete.LETTERS)
    num = RenameSettings(method=Method.QUICK_DELETE, quick_delete=QuickDelete.DIGITS)
    qt = RenameSettings(method=Method.QUICK_DELETE, quick_delete=QuickDelete.QUOTES)
    assert preview_name(item("a(1)（二）.txt"), 0, br) == "a1二.txt"
    assert preview_name(item("a b  c.txt"), 0, sp) == "abc.txt"
    assert preview_name(item("图ABC12.txt"), 0, let) == "图12.txt"
    assert preview_name(item("图ABC12.txt"), 0, num) == "图ABC.txt"
    assert preview_name(item("“引号”.txt"), 0, qt) == "引号.txt"
    assert preview_name(item('"photo".txt'), 0, qt) == "photo.txt"


def test_import_appends_original_suffix():
    s = RenameSettings(method=Method.IMPORT, imported_names=["合同A", "合同B"])
    assert preview_name(item("1.docx"), 0, s) == "合同A.docx"
    assert preview_name(item("2.docx"), 1, s) == "合同B.docx"
    folder = RenameSettings(method=Method.IMPORT, imported_names=["新文件夹"])
    assert preview_name(item("old", is_dir=True), 0, folder) == "新文件夹"


def test_time_name_styles():
    dt = datetime(2024, 1, 2, 3, 4, 5)
    it = item("a.txt", created=dt, modified=dt)
    s = RenameSettings(method=Method.TIME_NAME, time_source=TimeSource.CREATED, time_style="yyyy-mm-dd hh-mm-ss")
    assert preview_name(it, 0, s) == "2024-01-02 03-04-05.txt"
    s.time_style = "yyyy年mm月dd日hh时mm分ss秒"
    assert preview_name(it, 0, s) == "2024年01月02日03时04分05秒.txt"
    s.time_style = "yyyymmddhhmmss"
    assert preview_name(it, 0, s) == "20240102030405.txt"


def test_format_file_time_for_setfiletime():
    dt = datetime(2024, 1, 2, 3, 4, 5)
    assert format_file_time(dt) == "2024-01-02-03-04-05"


def test_extension_set_and_replace():
    set_ext = RenameSettings(method=Method.REPLACE, new_ext="png", ext_mode=ExtMode.SET)
    assert preview_name(item("a.JPG"), 0, set_ext) == "a.png"
    repl = RenameSettings(
        method=Method.REPLACE, ext_mode=ExtMode.REPLACE, ext_find="pg", ext_replace="peg"
    )
    assert preview_name(item("a.jpg"), 0, repl) == "a.jpeg"


def test_preview_items_flags_illegal_names():
    s = RenameSettings(method=Method.CUSTOM, new_name="a:b", start_number=1, width=1)
    rows = preview_items([item("x.txt")], s)
    assert rows[0].status.value == "failed"


def test_folder_custom():
    s = RenameSettings(method=Method.CUSTOM, new_name="dir", start_number=1, width=2)
    assert preview_name(item("old", is_dir=True), 0, s) == "dir01"


def test_all_methods_on_files_and_folders():
    dt = datetime(2024, 1, 2, 3, 4, 5)
    file_item = item("草稿(A) 1.txt", created=dt, modified=dt)
    folder_item = item("草稿(A) 1", is_dir=True, created=dt, modified=dt)
    cases = [
        RenameSettings(method=Method.CUSTOM, new_name="名", start_number=1, width=2),
        RenameSettings(method=Method.REPLACE, find="草稿", replace="终稿"),
        RenameSettings(method=Method.INSERT, insert_text="X", insert_where=InsertWhere.HEAD),
        RenameSettings(method=Method.INSERT, insert_kind=InsertKind.NUMBER, insert_where=InsertWhere.TAIL, start_number=7, width=2),
        RenameSettings(method=Method.DELETE, delete_text="草稿"),
        RenameSettings(method=Method.DELETE, delete_kind=DeleteKind.RANGE, delete_start=1, delete_length=2),
        RenameSettings(method=Method.TIME_ATTR, case=CaseMode.UPPER, new_ext="png"),
        RenameSettings(method=Method.IMPORT, imported_names=["导入名"], case=CaseMode.UPPER),
        RenameSettings(method=Method.QUICK_DELETE, quick_delete=QuickDelete.BRACKETS),
        RenameSettings(method=Method.TIME_NAME, time_style="yyyy-mm-dd-hh-mm-ss"),
    ]
    for settings in cases:
        file_name = preview_name(file_item, 0, settings)
        folder_name = preview_name(folder_item, 0, settings)
        assert file_name, settings.method
        assert folder_name, settings.method
        if settings.method is Method.TIME_ATTR:
            assert file_name == file_item.name
            assert folder_name == folder_item.name
        if settings.method is Method.IMPORT:
            assert file_name == "导入名.txt"
            assert folder_name == "导入名"


def test_case_modes_except_import_and_time_attr():
    src = item("abC.txt")
    for mode, want in [
        (CaseMode.KEEP, "abC.txt"),
        (CaseMode.UPPER, "ABC.txt"),
        (CaseMode.LOWER, "abc.txt"),
        (CaseMode.FIRST_UPPER, "AbC.txt"),
        (CaseMode.FIRST_LOWER, "abC.txt"),
    ]:
        s = RenameSettings(method=Method.REPLACE, case=mode)
        assert preview_name(src, 0, s) == want
    locked = item("abC.txt")
    assert preview_name(locked, 0, RenameSettings(method=Method.TIME_ATTR, case=CaseMode.UPPER)) == "abC.txt"
    imported = RenameSettings(method=Method.IMPORT, imported_names=["xy"], case=CaseMode.UPPER)
    assert preview_name(item("abC.txt"), 0, imported) == "xy.txt"


def test_ext_set_replace_and_case():
    src = item("photo.JPG")
    set_ext = RenameSettings(method=Method.REPLACE, ext_mode=ExtMode.SET, new_ext="png", ext_case=CaseMode.LOWER)
    assert preview_name(src, 0, set_ext) == "photo.png"
    repl = RenameSettings(
        method=Method.REPLACE,
        ext_mode=ExtMode.REPLACE,
        ext_find="JP",
        ext_replace="jpe",
        ext_case=CaseMode.LOWER,
    )
    assert preview_name(src, 0, repl) == "photo.jpeg"
    skip = RenameSettings(method=Method.IMPORT, imported_names=["a"], new_ext="png", ext_case=CaseMode.LOWER)
    assert preview_name(src, 0, skip) == "a.JPG"
    time_skip = RenameSettings(method=Method.TIME_ATTR, new_ext="png")
    assert preview_name(src, 0, time_skip) == "photo.JPG"


def test_time_name_all_four_styles():
    dt = datetime(2024, 1, 2, 3, 4, 5)
    it = item("a.txt", created=dt, modified=datetime(2020, 6, 7, 8, 9, 10))
    styles = {
        "yyyy-mm-dd hh-mm-ss": "2024-01-02 03-04-05.txt",
        "yyyy-mm-dd-hh-mm-ss": "2024-01-02-03-04-05.txt",
        "yyyymmddhhmmss": "20240102030405.txt",
        "yyyy年mm月dd日hh时mm分ss秒": "2024年01月02日03时04分05秒.txt",
    }
    for style, want in styles.items():
        s = RenameSettings(method=Method.TIME_NAME, time_source=TimeSource.CREATED, time_style=style)
        assert preview_name(it, 0, s) == want
    modified = RenameSettings(
        method=Method.TIME_NAME, time_source=TimeSource.MODIFIED, time_style="yyyymmddhhmmss"
    )
    assert preview_name(it, 0, modified) == "20200607080910.txt"
    folder = item("old", is_dir=True, created=dt)
    s = RenameSettings(method=Method.TIME_NAME, time_style="yyyy-mm-dd hh-mm-ss")
    assert preview_name(folder, 0, s) == "2024-01-02 03-04-05"


def test_duplicate_destinations_flagged_in_preview():
    rows = [
        item("a.txt"),
        item("b.txt"),
    ]
    settings = RenameSettings(method=Method.CUSTOM, new_name="x", start_number=1, increment=0, width=1)
    preview_items(rows, settings)
    assert rows[0].new_name == rows[1].new_name == "x1.txt"
    assert rows[0].status is Status.DUPLICATE
    assert rows[1].status is Status.DUPLICATE
    assert "重名" in rows[0].message


def test_natural_sort_puts_2_before_10():
    rows = [item("file10.txt"), item("file2.txt"), item("file1.txt")]
    sort_items_naturally(rows)
    assert [it.name for it in rows] == ["file1.txt", "file2.txt", "file10.txt"]
    settings = RenameSettings(method=Method.CUSTOM, new_name="p", start_number=1, width=1)
    preview_items(rows, settings)
    assert [it.new_name for it in rows] == ["p1.txt", "p2.txt", "p3.txt"]


def test_excel_and_csv_first_column_keeps_suffix(tmp_path: Path):
    from openpyxl import Workbook

    xlsx = tmp_path / "names.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["合同A"])
    ws.append(["合同B"])
    wb.save(xlsx)
    names = load_name_column(xlsx)
    settings = RenameSettings(method=Method.IMPORT, imported_names=names)
    assert preview_name(item("1.docx"), 0, settings) == "合同A.docx"
    assert preview_name(item("2.docx"), 1, settings) == "合同B.docx"

    csv_path = tmp_path / "names.csv"
    csv_path.write_text("相册一\n相册二\n", encoding="utf-8")
    csv_names = load_name_column(csv_path)
    csv_settings = RenameSettings(method=Method.IMPORT, imported_names=csv_names)
    assert preview_name(item("a.png"), 0, csv_settings) == "相册一.png"
    assert preview_name(item("old", is_dir=True), 1, csv_settings) == "相册二"
