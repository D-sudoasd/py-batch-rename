"""Drive the shipped settings panel: ext replace must be selectable and wired."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from py_batch_rename.engine import ExtMode, InsertKind, Method
from py_batch_rename.gui import METHOD_LABELS, STYLE, MainWindow, smoke


def _app():
    from PySide6.QtWidgets import QApplication
    import sys

    return QApplication.instance() or QApplication(sys.argv)


def test_ext_replace_is_selectable_and_not_set_only():
    _app()
    win = MainWindow()
    panel = win.settings_panel
    values = []
    for i in range(panel.ext_mode.count()):
        data = panel.ext_mode.itemData(i)
        values.append(data if isinstance(data, ExtMode) else ExtMode(data))
    assert ExtMode.SET in values
    assert ExtMode.REPLACE in values
    panel.ext_mode.setCurrentIndex(values.index(ExtMode.REPLACE))
    panel.ext_find.setText("jpg")
    panel.ext_replace.setText("jpeg")
    settings = panel.settings()
    assert settings.ext_mode is ExtMode.REPLACE
    assert settings.ext_find == "jpg"
    assert settings.ext_replace == "jpeg"
    win.close()


def test_all_eight_methods_exist_on_the_window():
    _app()
    win = MainWindow()
    labels = [win.settings_panel.method.itemText(i) for i in range(win.settings_panel.method.count())]
    assert len(labels) == 8
    assert [m for m, _ in METHOD_LABELS] == [
        win.settings_panel.method.itemData(i)
        if isinstance(win.settings_panel.method.itemData(i), Method)
        else Method(win.settings_panel.method.itemData(i))
        for i in range(win.settings_panel.method.count())
    ]
    win.close()


def test_insert_numbering_enablement():
    _app()
    win = MainWindow()
    panel = win.settings_panel
    panel.method.setCurrentIndex([m.value for m, _ in METHOD_LABELS].index("insert"))
    panel.insert_kind.button(0).setChecked(True)
    panel._sync_stack()
    assert panel.settings().insert_kind is InsertKind.TEXT
    assert not panel.start.isEnabled()
    panel.insert_kind.button(1).setChecked(True)
    panel._sync_stack()
    assert panel.settings().insert_kind is InsertKind.NUMBER
    assert panel.start.isEnabled()
    win.close()


def test_folder_mode_hides_extension_controls():
    _app()
    win = MainWindow()
    win.show()
    assert win.settings_panel.ext_box.isEnabled()
    win.settings_panel.set_folder_mode(True)
    assert not win.settings_panel.ext_box.isEnabled()
    win.settings_panel.set_folder_mode(False)
    assert win.settings_panel.ext_box.isEnabled()
    win.close()


def test_criterion1_tooltips_are_chinese_explanations():
    _app()
    win = MainWindow()
    targets = win.tip_targets()
    assert len(targets) >= 15
    for widget, label in targets:
        tip = (widget.toolTip() or "").strip()
        assert tip, f"empty tooltip for {label}"
        assert tip != label, f"tooltip repeats label {label}"
        assert any("\u4e00" <= ch <= "\u9fff" for ch in tip), f"tooltip not Chinese: {tip}"
    win.close()


def test_stylesheet_has_hover_focus_and_primary():
    assert "QPushButton:hover" in STYLE
    assert "QPushButton:focus" in STYLE
    assert "QPushButton#primary" in STYLE
    assert "QLineEdit:hover" in STYLE
    assert "QLineEdit:focus" in STYLE
    assert "#header" in STYLE
    assert "#toolbar" in STYLE
    assert "#settingsFrame" in STYLE


def test_table_tooltip_includes_path_and_status():
    _app()
    win = MainWindow()
    from py_batch_rename.collect import add_paths
    from pathlib import Path
    import tempfile

    td = Path(tempfile.mkdtemp())
    sample = td / "hello.jpg"
    sample.write_text("x", encoding="utf-8")
    win._append(add_paths([sample]))
    tip = win.model.index(0, 0).data(Qt.ToolTipRole)
    assert "当前位置" in tip
    assert "新文件名" in tip
    assert "状态" in tip
    assert "hello.jpg" in tip
    win.close()


def test_smoke_entry_returns_zero():
    assert smoke() == 0
