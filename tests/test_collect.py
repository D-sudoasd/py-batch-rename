from pathlib import Path

from py_batch_rename.collect import add_directory_files


def test_add_directory_files_uses_natural_order(tmp_path: Path):
    (tmp_path / "file10.txt").write_text("10", encoding="utf-8")
    (tmp_path / "file2.txt").write_text("2", encoding="utf-8")
    (tmp_path / "file1.txt").write_text("1", encoding="utf-8")
    items = add_directory_files(tmp_path)
    assert [it.name for it in items] == ["file1.txt", "file2.txt", "file10.txt"]
