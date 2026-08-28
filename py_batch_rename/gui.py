"""PySide6 desktop UI for the Python batch rename tool."""

from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .apply import apply_items, undo_items
from .collect import add_directory_files, add_paths, merge_unique
from .engine import (
    STATUS_LABEL,
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
    preview_items,
    sort_items_naturally,
)
from .excel import load_name_column

METHOD_LABELS = [
    (Method.CUSTOM, "自定义（名称+编号）"),
    (Method.REPLACE, "替换"),
    (Method.INSERT, "插入"),
    (Method.DELETE, "删除"),
    (Method.TIME_ATTR, "时间属性"),
    (Method.IMPORT, "导入表格"),
    (Method.QUICK_DELETE, "一键删除"),
    (Method.TIME_NAME, "时间命名"),
]

CASE_LABELS = [
    (CaseMode.KEEP, "不变"),
    (CaseMode.UPPER, "全部大写"),
    (CaseMode.LOWER, "全部小写"),
    (CaseMode.FIRST_UPPER, "首字母大写"),
    (CaseMode.FIRST_LOWER, "首字母小写"),
]

TIME_STYLES = [
    "yyyy-mm-dd hh-mm-ss",
    "yyyy-mm-dd-hh-mm-ss",
    "yyyymmddhhmmss",
    "yyyy年mm月dd日hh时mm分ss秒",
]

# Hover copy lives next to construction. Tests read widget.toolTip() on the live window.
TOOLTIPS = {
    "add_files": "打开系统文件框，一次加入多个要改名的文件；也可直接拖到表格。",
    "add_dir": "选择一个文件夹，把它里面的文件（不含该文件夹自己）加入列表。勾选「包含子目录」会连同下级目录一起收。",
    "add_folders": "选择要改名的文件夹本身（改的是目录名，不是里面的文件）。",
    "clear_list": "清空当前列表和上次撤回快照，不会改磁盘上的文件。",
    "remove": "从列表里拿掉选中行，不改磁盘。也可按 Delete 键。",
    "natsort": "按自然数排序，让 2 排在 10 前面。自定义编号按排序后的顺序重新预览。",
    "start": "按当前预览把名字或时间写到磁盘。批次内目标重名时会先拦住。",
    "undo": "把上一次成功的重命名改回原来的名字。改时间属性不能撤回。",
    "mode_files": "处理普通文件。可添加文件、添加目录中的文件，并改拓展名。",
    "mode_folders": "处理文件夹名称。拓展名相关选项会隐藏。",
    "method": "选择命名规则。改完后表格「新文件名」列会马上刷新预览。",
    "start_number": "第一项的编号。例如起始 1、位数 3 时第一项是 001。",
    "increment": "每一项编号比前一项增加多少。设成 0 时全部用同一个编号（容易重名）。",
    "width": "编号至少几位，不足的左边补 0。数字更长时不会截断。",
    "ext_mode": "改拓展名：整段换成新拓展名，或只替换拓展名里的一段文字。导入表格和改时间属性时不用。",
    "recursive": "添加目录时是否连同子文件夹里的文件一起加入。",
}


def apply_tip(widget, key: str) -> None:
    text = TOOLTIPS[key]
    widget.setToolTip(text)
    if hasattr(widget, "setStatusTip"):
        widget.setStatusTip(text)

STATUS_COLOR = {
    Status.PENDING: QColor("#666666"),
    Status.SUCCESS: QColor("#1a9f5a"),
    Status.FAILED: QColor("#d23c3c"),
    Status.MISSING: QColor("#b36b00"),
    Status.EXISTS: QColor("#c27800"),
    Status.SKIPPED: QColor("#888888"),
    Status.DUPLICATE: QColor("#c27800"),
}


class ItemTableModel(QAbstractTableModel):
    HEADERS = ["原文件名", "新文件名", "位置", "状态"]

    def __init__(self) -> None:
        super().__init__()
        self.items: list[RenameItem] = []

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 4

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        item = self.items[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return item.name if item.status is not Status.SUCCESS else item.new_name
            if col == 1:
                return item.new_name
            if col == 2:
                return item.directory
            if col == 3:
                return item.message or STATUS_LABEL.get(item.status, "")
        if role == Qt.ForegroundRole and col == 3:
            return STATUS_COLOR.get(item.status)
        if role == Qt.ToolTipRole:
            status = item.message or STATUS_LABEL.get(item.status, "")
            return (
                f"当前位置：{item.src_path}\n"
                f"新文件名：{item.new_name or item.name}\n"
                f"状态：{status}"
            )
        return None

    def set_items(self, items: list[RenameItem]) -> None:
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def refresh(self) -> None:
        if self.items:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.items) - 1, 3))


class DropTable(QTableView):
    def __init__(self, on_drop, on_delete=None) -> None:
        super().__init__()
        self._on_drop = on_drop
        self._on_delete = on_delete
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if paths:
            self._on_drop(paths)
            event.acceptProposedAction()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self._on_delete:
            self._on_delete()
            return
        super().keyPressEvent(event)


def _combo(pairs: list[tuple], current=None) -> QComboBox:
    box = QComboBox()
    for value, label in pairs:
        box.addItem(label, value)
        if current is not None and value == current:
            box.setCurrentIndex(box.count() - 1)
    return box


class SettingsPanel(QWidget):
    def __init__(self, on_change) -> None:
        super().__init__()
        self._on_change = on_change
        self._building = True

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)

        title = QLabel("命名规则")
        title.setObjectName("panelTitle")
        root.addWidget(title)

        form = QFormLayout()
        self.method = _combo(METHOD_LABELS, Method.CUSTOM)
        self.method.setObjectName("nameMethod")
        apply_tip(self.method, "method")
        self.method.currentIndexChanged.connect(self._changed)
        form.addRow("命名方式", self.method)
        root.addLayout(form)

        self.stack = QStackedWidget()
        self.pages = {}
        self._build_pages()
        root.addWidget(self.stack)

        extra = QFormLayout()
        self.case = _combo(CASE_LABELS, CaseMode.KEEP)
        self.case.currentIndexChanged.connect(self._changed)
        extra.addRow("大小写", self.case)

        num = QHBoxLayout()
        self.start = QSpinBox()
        self.start.setRange(0, 999999)
        self.start.setValue(1)
        apply_tip(self.start, "start_number")
        self.increment = QSpinBox()
        self.increment.setRange(-999999, 999999)
        self.increment.setValue(1)
        apply_tip(self.increment, "increment")
        self.width = QSpinBox()
        self.width.setRange(1, 12)
        self.width.setValue(3)
        apply_tip(self.width, "width")
        for w in (self.start, self.increment, self.width):
            w.valueChanged.connect(self._changed)
        num.addWidget(QLabel("起始"))
        num.addWidget(self.start)
        num.addWidget(QLabel("增量"))
        num.addWidget(self.increment)
        num.addWidget(QLabel("位数"))
        num.addWidget(self.width)
        extra.addRow("编号", num)
        self.num_row_widgets = [self.start, self.increment, self.width]
        root.addLayout(extra)

        self.ext_box = QWidget()
        ext_form = QFormLayout(self.ext_box)
        ext_form.setContentsMargins(0, 0, 0, 0)
        self.ext_mode = _combo(
            [(ExtMode.SET, "设置为新拓展名"), (ExtMode.REPLACE, "替换拓展名中的文字")],
            ExtMode.SET,
        )
        self.ext_mode.setObjectName("extMode")
        apply_tip(self.ext_mode, "ext_mode")
        self.ext_mode.currentIndexChanged.connect(self._changed)
        ext_form.addRow("拓展名变更", self.ext_mode)
        self.new_ext = QLineEdit()
        self.new_ext.setPlaceholderText("留空则保持原拓展名，不要带点")
        self.new_ext.setObjectName("newExt")
        self.new_ext.textChanged.connect(self._changed)
        ext_form.addRow("新拓展名", self.new_ext)
        self.ext_find = QLineEdit()
        self.ext_find.setObjectName("extFind")
        self.ext_replace = QLineEdit()
        self.ext_replace.setObjectName("extReplace")
        self.ext_find.textChanged.connect(self._changed)
        self.ext_replace.textChanged.connect(self._changed)
        ext_form.addRow("拓展名查找", self.ext_find)
        ext_form.addRow("拓展名替换为", self.ext_replace)
        self.ext_case = _combo(CASE_LABELS, CaseMode.KEEP)
        self.ext_case.setObjectName("extCase")
        self.ext_case.currentIndexChanged.connect(self._changed)
        ext_form.addRow("拓展名大小写", self.ext_case)
        root.addWidget(self.ext_box)
        self.folder_mode = False

        reset = QPushButton("重置规则")
        reset.clicked.connect(self.reset)
        root.addWidget(reset)
        root.addStretch(1)
        self._building = False
        self._sync_stack()

    def _page(self, name: str, widget: QWidget) -> None:
        self.pages[name] = widget
        self.stack.addWidget(widget)

    def _build_pages(self) -> None:
        custom = QWidget()
        f = QFormLayout(custom)
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("新文件名，可留空只保留编号")
        self.new_name.textChanged.connect(self._changed)
        f.addRow("新文件名", self.new_name)
        self._page("custom", custom)

        replace = QWidget()
        f = QFormLayout(replace)
        self.find = QLineEdit()
        self.replace = QLineEdit()
        self.find.textChanged.connect(self._changed)
        self.replace.textChanged.connect(self._changed)
        f.addRow("查找", self.find)
        f.addRow("替换为", self.replace)
        self._page("replace", replace)

        insert = QWidget()
        f = QFormLayout(insert)
        self.insert_kind = QButtonGroup(insert)
        kind_row = QHBoxLayout()
        r1 = QRadioButton("自定义内容")
        r2 = QRadioButton("编号")
        r1.setChecked(True)
        self.insert_kind.addButton(r1, 0)
        self.insert_kind.addButton(r2, 1)
        kind_row.addWidget(r1)
        kind_row.addWidget(r2)
        kind_wrap = QWidget()
        kind_wrap.setLayout(kind_row)
        self.insert_kind.idToggled.connect(self._changed)
        self.insert_text = QLineEdit()
        self.insert_text.textChanged.connect(self._changed)
        self.insert_where = _combo(
            [
                (InsertWhere.HEAD, "文件名头"),
                (InsertWhere.TAIL, "文件名尾"),
                (InsertWhere.INDEX, "指定位置"),
            ],
            InsertWhere.HEAD,
        )
        self.insert_where.currentIndexChanged.connect(self._changed)
        self.insert_index = QSpinBox()
        self.insert_index.setRange(1, 999)
        self.insert_index.setValue(1)
        self.insert_index.valueChanged.connect(self._changed)
        f.addRow("插入类型", kind_wrap)
        f.addRow("插入内容", self.insert_text)
        f.addRow("插入位置", self.insert_where)
        f.addRow("位置序号", self.insert_index)
        self._page("insert", insert)

        delete = QWidget()
        f = QFormLayout(delete)
        self.delete_kind = QButtonGroup(delete)
        drow = QHBoxLayout()
        d1 = QRadioButton("删除指定内容")
        d2 = QRadioButton("按位置删除")
        d1.setChecked(True)
        self.delete_kind.addButton(d1, 0)
        self.delete_kind.addButton(d2, 1)
        dwrap = QWidget()
        drow.addWidget(d1)
        drow.addWidget(d2)
        dwrap.setLayout(drow)
        self.delete_kind.idToggled.connect(self._changed)
        self.delete_text = QLineEdit()
        self.delete_text.textChanged.connect(self._changed)
        self.delete_start = QSpinBox()
        self.delete_start.setRange(1, 999)
        self.delete_length = QSpinBox()
        self.delete_length.setRange(1, 999)
        self.delete_start.valueChanged.connect(self._changed)
        self.delete_length.valueChanged.connect(self._changed)
        f.addRow("删除类型", dwrap)
        f.addRow("删除内容", self.delete_text)
        f.addRow("开始位置", self.delete_start)
        f.addRow("长度", self.delete_length)
        self._page("delete", delete)

        time_attr = QWidget()
        f = QFormLayout(time_attr)
        self.use_created = QCheckBox("修改创建时间")
        self.use_modified = QCheckBox("修改修改时间")
        self.created = QDateTimeEdit(datetime.now())
        self.modified = QDateTimeEdit(datetime.now())
        self.created.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.modified.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.created.setCalendarPopup(True)
        self.modified.setCalendarPopup(True)
        for w in (self.use_created, self.use_modified):
            w.toggled.connect(self._changed)
        self.created.dateTimeChanged.connect(self._changed)
        self.modified.dateTimeChanged.connect(self._changed)
        f.addRow(self.use_created, self.created)
        f.addRow(self.use_modified, self.modified)
        hint = QLabel("不勾选的一侧会保持原时间。Windows 可改创建时间。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        f.addRow(hint)
        self._page("time_attr", time_attr)

        imported = QWidget()
        f = QFormLayout(imported)
        row = QHBoxLayout()
        self.excel_path = QLineEdit()
        self.excel_path.setReadOnly(True)
        self.excel_path.setPlaceholderText("导入第一列作为新文件名")
        btn = QPushButton("选择表格")
        btn.clicked.connect(self._pick_excel)
        row.addWidget(self.excel_path)
        row.addWidget(btn)
        wrap = QWidget()
        wrap.setLayout(row)
        f.addRow("Excel / CSV", wrap)
        hint = QLabel("第一张表第一列，按列表顺序对应。文件会自动补上原拓展名。")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        f.addRow(hint)
        self._page("import", imported)
        self.imported_names: list[str] = []

        quick = QWidget()
        f = QFormLayout(quick)
        self.quick = _combo(
            [
                (QuickDelete.BRACKETS, "文件名中的括号 ()（）"),
                (QuickDelete.SPACES, "文件名中的空格"),
                (QuickDelete.LETTERS, "文件名中的字母"),
                (QuickDelete.DIGITS, "文件名中的数字"),
                (QuickDelete.QUOTES, "文件名中的引号"),
            ],
            QuickDelete.BRACKETS,
        )
        self.quick.currentIndexChanged.connect(self._changed)
        f.addRow("删除对象", self.quick)
        self._page("quick_delete", quick)

        time_name = QWidget()
        f = QFormLayout(time_name)
        self.time_source = _combo(
            [(TimeSource.CREATED, "创建时间"), (TimeSource.MODIFIED, "修改时间")],
            TimeSource.CREATED,
        )
        self.time_style = QComboBox()
        self.time_style.addItems(TIME_STYLES)
        self.time_source.currentIndexChanged.connect(self._changed)
        self.time_style.currentIndexChanged.connect(self._changed)
        f.addRow("时间来源", self.time_source)
        f.addRow("时间样式", self.time_style)
        self._page("time_name", time_name)

    def _pick_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入文件名", "", "表格 (*.xlsx *.xlsm *.csv *.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            names = load_name_column(path)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        self.imported_names = names
        self.excel_path.setText(path)
        self._changed()

    def reset(self) -> None:
        self._building = True
        self.method.setCurrentIndex(0)
        self.new_name.clear()
        self.find.clear()
        self.replace.clear()
        self.insert_text.clear()
        self.insert_kind.button(0).setChecked(True)
        self.insert_where.setCurrentIndex(0)
        self.insert_index.setValue(1)
        self.delete_kind.button(0).setChecked(True)
        self.delete_text.clear()
        self.delete_start.setValue(1)
        self.delete_length.setValue(1)
        self.use_created.setChecked(False)
        self.use_modified.setChecked(False)
        self.excel_path.clear()
        self.imported_names = []
        self.quick.setCurrentIndex(0)
        self.time_source.setCurrentIndex(0)
        self.time_style.setCurrentIndex(0)
        self.case.setCurrentIndex(0)
        self.start.setValue(1)
        self.increment.setValue(1)
        self.width.setValue(3)
        self.ext_mode.setCurrentIndex(0)
        self.new_ext.clear()
        self.ext_find.clear()
        self.ext_replace.clear()
        self.ext_case.setCurrentIndex(0)
        self._building = False
        self._changed()

    def _current_enum(self, box: QComboBox, enum_cls):
        data = box.currentData()
        if isinstance(data, enum_cls):
            return data
        return enum_cls(data)

    def set_folder_mode(self, folders: bool) -> None:
        self.folder_mode = folders
        self._sync_stack()
        self._on_change()

    def _sync_stack(self) -> None:
        method = self._current_enum(self.method, Method)
        keys = [m.value for m, _ in METHOD_LABELS]
        self.stack.setCurrentIndex(keys.index(method.value))
        insert_number = method is Method.INSERT and self.insert_kind.checkedId() == 1
        numbering = method is Method.CUSTOM or insert_number
        for w in self.num_row_widgets:
            w.setEnabled(numbering)
        self.insert_text.setEnabled(method is Method.INSERT and not insert_number)
        self.insert_index.setEnabled(
            method is Method.INSERT and self._current_enum(self.insert_where, InsertWhere) is InsertWhere.INDEX
        )
        del_range = self.delete_kind.checkedId() == 1
        self.delete_text.setEnabled(method is Method.DELETE and not del_range)
        self.delete_start.setEnabled(method is Method.DELETE and del_range)
        self.delete_length.setEnabled(method is Method.DELETE and del_range)
        ext_ok = (not self.folder_mode) and method not in {Method.TIME_ATTR, Method.IMPORT}
        self.ext_box.setVisible(ext_ok)
        self.ext_box.setEnabled(ext_ok)
        ext_replace = self._current_enum(self.ext_mode, ExtMode) is ExtMode.REPLACE
        self.new_ext.setEnabled(ext_ok and not ext_replace)
        self.ext_find.setEnabled(ext_ok and ext_replace)
        self.ext_replace.setEnabled(ext_ok and ext_replace)
        self.ext_case.setEnabled(ext_ok)
        self.case.setEnabled(method not in {Method.IMPORT, Method.TIME_ATTR})

    def _changed(self, *_args) -> None:
        if self._building:
            return
        self._sync_stack()
        self._on_change()

    def settings(self) -> RenameSettings:
        method = self._current_enum(self.method, Method)
        created = self.created.dateTime().toPython() if self.use_created.isChecked() else None
        modified = self.modified.dateTime().toPython() if self.use_modified.isChecked() else None
        if hasattr(created, "replace") and getattr(created, "tzinfo", None):
            created = created.replace(tzinfo=None)
        if hasattr(modified, "replace") and getattr(modified, "tzinfo", None):
            modified = modified.replace(tzinfo=None)
        return RenameSettings(
            method=method,
            new_name=self.new_name.text(),
            find=self.find.text(),
            replace=self.replace.text(),
            insert_kind=InsertKind.NUMBER if self.insert_kind.checkedId() == 1 else InsertKind.TEXT,
            insert_text=self.insert_text.text(),
            insert_where=self._current_enum(self.insert_where, InsertWhere),
            insert_index=self.insert_index.value(),
            delete_kind=DeleteKind.RANGE if self.delete_kind.checkedId() == 1 else DeleteKind.TEXT,
            delete_text=self.delete_text.text(),
            delete_start=self.delete_start.value(),
            delete_length=self.delete_length.value(),
            quick_delete=self._current_enum(self.quick, QuickDelete),
            case=self._current_enum(self.case, CaseMode),
            start_number=self.start.value(),
            increment=self.increment.value(),
            width=self.width.value(),
            ext_mode=self._current_enum(self.ext_mode, ExtMode),
            new_ext=self.new_ext.text(),
            ext_find=self.ext_find.text(),
            ext_replace=self.ext_replace.text(),
            ext_case=self._current_enum(self.ext_case, CaseMode),
            time_source=self._current_enum(self.time_source, TimeSource),
            time_style=self.time_style.currentText(),
            created=created,
            modified=modified,
            imported_names=list(self.imported_names),
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("文件批量重命名")
        self.resize(1100, 720)
        self.setAcceptDrops(True)
        self.folder_mode = False
        self.undo_snapshot: list[tuple[str, str, str, bool]] = []
        self.model = ItemTableModel()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_toolbar())

        split = QSplitter()
        self.table = DropTable(self._drop_paths, on_delete=self.remove_selected)
        self.table.setModel(self.model)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 320)
        split.addWidget(self.table)
        self.settings_panel = SettingsPanel(self.refresh_preview)
        settings_frame = QFrame()
        settings_frame.setObjectName("settingsFrame")
        sf = QVBoxLayout(settings_frame)
        sf.setContentsMargins(0, 0, 0, 0)
        sf.addWidget(self.settings_panel)
        split.addWidget(settings_frame)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, 1)

        self.status = self.statusBar()
        self.status.setSizeGripEnabled(False)
        self._set_status("拖入文件，或点上方按钮添加。规则变更会即时预览。把鼠标放到按钮上可看说明。")

    def tip_targets(self) -> list[tuple]:
        """Widgets that must carry Chinese hover help (criterion 1)."""
        return [
            (self.btn_add_files, self.btn_add_files.text()),
            (self.btn_add_dir, self.btn_add_dir.text()),
            (self.btn_add_folders, self.btn_add_folders.text()),
            (self.btn_clear, self.btn_clear.text()),
            (self.btn_remove, self.btn_remove.text()),
            (self.btn_natsort, self.btn_natsort.text()),
            (self.btn_start, self.btn_start.text()),
            (self.btn_undo, self.btn_undo.text()),
            (self.btn_files, self.btn_files.text()),
            (self.btn_folders, self.btn_folders.text()),
            (self.settings_panel.method, "命名方式"),
            (self.settings_panel.start, "起始"),
            (self.settings_panel.increment, "增量"),
            (self.settings_panel.width, "位数"),
            (self.settings_panel.ext_mode, "拓展名变更"),
        ]

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("header")
        row = QHBoxLayout(bar)
        title = QLabel("文件批量重命名")
        title.setObjectName("appTitle")
        sub = QLabel("纯 Python 替代 · 无数量限制 · 无会员")
        sub.setObjectName("appSub")
        col = QVBoxLayout()
        col.addWidget(title)
        col.addWidget(sub)
        row.addLayout(col)
        row.addStretch(1)
        self.btn_files = QPushButton("文件")
        self.btn_folders = QPushButton("文件夹")
        self.btn_files.setCheckable(True)
        self.btn_folders.setCheckable(True)
        self.btn_files.setChecked(True)
        apply_tip(self.btn_files, "mode_files")
        apply_tip(self.btn_folders, "mode_folders")
        self.btn_files.clicked.connect(lambda: self._set_mode(False))
        self.btn_folders.clicked.connect(lambda: self._set_mode(True))
        row.addWidget(self.btn_files)
        row.addWidget(self.btn_folders)
        return bar

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("toolbar")
        row = QHBoxLayout(bar)
        self.btn_add_files = self._tool("添加文件", self.add_files, "add_files")
        self.btn_add_dir = self._tool("添加目录中的文件", self.add_dir_files, "add_dir")
        self.btn_add_folders = self._tool("添加文件夹", self.add_folders, "add_folders")
        self.btn_clear = self._tool("清除列表", self.clear_list, "clear_list")
        self.btn_remove = self._tool("移除选中", self.remove_selected, "remove")
        self.btn_natsort = self._tool("自然排序", self.natural_sort, "natsort")
        self.chk_recursive = QCheckBox("包含子目录")
        apply_tip(self.chk_recursive, "recursive")
        self.btn_start = QPushButton("开始重命名")
        self.btn_start.setObjectName("primary")
        apply_tip(self.btn_start, "start")
        self.btn_start.clicked.connect(self.start_rename)
        self.btn_undo = QPushButton("命名撤回")
        apply_tip(self.btn_undo, "undo")
        self.btn_undo.clicked.connect(self.undo_rename)
        self.btn_undo.setEnabled(False)
        row.addWidget(self.btn_add_files)
        row.addWidget(self.btn_add_dir)
        row.addWidget(self.btn_add_folders)
        row.addWidget(self.chk_recursive)
        row.addWidget(self.btn_remove)
        row.addWidget(self.btn_natsort)
        row.addWidget(self.btn_clear)
        row.addStretch(1)
        row.addWidget(self.btn_undo)
        row.addWidget(self.btn_start)
        self.btn_add_folders.setVisible(False)
        return bar

    def _tool(self, text: str, slot, tip_key: str | None = None) -> QPushButton:
        btn = QPushButton(text)
        btn.clicked.connect(slot)
        if tip_key:
            apply_tip(btn, tip_key)
        return btn

    def _set_mode(self, folders: bool) -> None:
        self.folder_mode = folders
        self.btn_files.setChecked(not folders)
        self.btn_folders.setChecked(folders)
        self.btn_add_files.setVisible(not folders)
        self.btn_add_dir.setVisible(not folders)
        self.btn_add_folders.setVisible(folders)
        self.chk_recursive.setVisible(not folders)
        self.settings_panel.set_folder_mode(folders)
        self.clear_list()

    def _set_status(self, text: str) -> None:
        n = len(self.model.items)
        kind = "文件夹" if self.folder_mode else "文件"
        self.status.showMessage(f"{kind} {n} 个    {text}")

    def _append(self, incoming: list[RenameItem]) -> None:
        items = merge_unique(self.model.items, incoming)
        self.model.set_items(items)
        self.refresh_preview()

    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "添加文件")
        if paths:
            self._append(add_paths(paths, folders=False))

    def add_dir_files(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "添加目录中的文件")
        if path:
            self._append(add_directory_files(path, recursive=self.chk_recursive.isChecked()))

    def add_folders(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "添加文件夹")
        if path:
            self._append(add_paths([path], folders=True))

    def _drop_paths(self, paths: list[str]) -> None:
        files: list[str] = []
        dirs: list[str] = []
        for p in paths:
            path = Path(p)
            if path.is_dir():
                dirs.append(p)
            elif path.is_file():
                files.append(p)
        if self.folder_mode:
            self._append(add_paths(dirs, folders=True))
        else:
            incoming = add_paths(files, folders=False)
            for d in dirs:
                incoming = merge_unique(
                    incoming, add_directory_files(d, recursive=self.chk_recursive.isChecked())
                )
            self._append(incoming)

    def clear_list(self) -> None:
        self.model.set_items([])
        self.undo_snapshot = []
        self.btn_undo.setEnabled(False)
        self._set_status("列表已清空")

    def remove_selected(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if not rows:
            return
        keep = [it for i, it in enumerate(self.model.items) if i not in set(rows)]
        self.model.set_items(keep)
        self.refresh_preview()
        self._set_status(f"已移除 {len(rows)} 项")

    def natural_sort(self) -> None:
        items = sort_items_naturally(list(self.model.items))
        self.model.set_items(items)
        self.refresh_preview()
        self._set_status("已按自然数顺序排列")

    def refresh_preview(self) -> None:
        settings = self.settings_panel.settings()
        preview_items(self.model.items, settings)
        self.model.refresh()
        self._set_status("预览已更新")

    def start_rename(self) -> None:
        items = self.model.items
        if not items:
            QMessageBox.information(self, "提示", "请先添加文件或文件夹")
            return
        settings = self.settings_panel.settings()
        preview_items(items, settings)
        if settings.method is Method.TIME_ATTR and settings.created is None and settings.modified is None:
            QMessageBox.warning(self, "提示", "请选择需要更改的时间")
            return
        if settings.method is Method.IMPORT and not settings.imported_names:
            QMessageBox.warning(self, "提示", "请先导入表格")
            return
        if any(it.status is Status.DUPLICATE for it in items):
            QMessageBox.warning(self, "提示", "批次内有重复的新文件名，请先调整规则、列表顺序或移除冲突项")
            return
        changing = [it for it in items if it.new_name != it.name or settings.method is Method.TIME_ATTR]
        if not changing:
            QMessageBox.information(self, "提示", "没有需要修改的项目")
            return
        reply = QMessageBox.question(
            self,
            "确认",
            f"即将处理 {len(changing)} 个项目，是否继续？",
        )
        if reply != QMessageBox.Yes:
            return
        self.undo_snapshot = [
            (it.directory, it.new_name, it.name, it.is_dir)
            for it in items
            if it.new_name != it.name
        ]
        try:
            apply_items(items, settings)
        except Exception as exc:
            QMessageBox.critical(self, "执行失败", f"{exc}\n\n{traceback.format_exc()}")
            return
        self.model.refresh()
        ok = sum(1 for it in items if it.status is Status.SUCCESS)
        fail = sum(1 for it in items if it.status in {Status.FAILED, Status.EXISTS, Status.MISSING})
        self.btn_undo.setEnabled(bool(self.undo_snapshot) and settings.method is not Method.TIME_ATTR)
        QMessageBox.information(self, "完成", f"成功 {ok} 个，未成功 {fail} 个")
        self._set_status(f"完成：成功 {ok}，未成功 {fail}")

    def undo_rename(self) -> None:
        if not self.undo_snapshot:
            return
        if QMessageBox.question(self, "确认", "确认执行撤回操作吗？") != QMessageBox.Yes:
            return
        errors = undo_items(self.undo_snapshot)
        restored: list[RenameItem] = []
        for directory, _current, original, is_dir in self.undo_snapshot:
            restored.append(RenameItem(directory, original, is_dir=is_dir))
        from .engine import fill_times

        fill_times(restored)
        self.model.set_items(restored)
        self.refresh_preview()
        self.undo_snapshot = []
        self.btn_undo.setEnabled(False)
        if errors:
            QMessageBox.warning(self, "部分撤回失败", "\n".join(errors[:20]))
        else:
            QMessageBox.information(self, "提示", "撤回成功")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if paths:
            self._drop_paths(paths)


STYLE = """
QMainWindow { background: #e6edf4; font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; }
QWidget { font-family: "Microsoft YaHei UI", "Segoe UI"; }
#header { background: #14324f; padding: 14px 18px; }
#appTitle { color: #ffffff; font-size: 20px; font-weight: 700; }
#appSub { color: #b9cbe0; font-size: 12px; }
#toolbar { background: #f8fafc; padding: 10px 14px; border-bottom: 1px solid #cfd9e4; }
#settingsFrame { background: #f3f6fa; border-left: 1px solid #cfd9e4; }
#panelTitle { font-size: 15px; font-weight: 700; color: #14324f; padding: 2px 0 8px 0; }
#hint { color: #6b7785; font-size: 12px; }
QToolTip { background: #1b2e44; color: #f4f7fb; border: 0; padding: 6px 8px; font-size: 12px; }
QPushButton { background: #eef3f8; border: 1px solid #c5d2e0; padding: 6px 12px; border-radius: 5px; color: #1d2b3a; }
QPushButton:hover { background: #d7e4f0; border-color: #7fa0bd; }
QPushButton:focus { border: 1px solid #2f6ea5; }
QPushButton:checked { background: #14324f; color: white; border-color: #14324f; }
QPushButton#primary { background: #c62828; color: white; border: 1px solid #a31d1d; padding: 9px 22px; font-weight: 700; font-size: 14px; }
QPushButton#primary:hover { background: #a61f1f; border-color: #8a1818; }
QPushButton#primary:focus { border: 2px solid #6d1212; }
QPushButton:disabled { color: #8a96a3; background: #eef1f4; border-color: #dde3ea; }
QTableView { background: #ffffff; gridline-color: #e6edf3; border: none; selection-background-color: #d4e6f5; selection-color: #14324f; alternate-background-color: #f7fafc; }
QTableView::item:hover { background: #eef5fb; }
QHeaderView::section { background: #edf2f7; padding: 8px; border: none; border-bottom: 1px solid #cfd9e4; font-weight: 600; color: #3a4a5b; }
QLineEdit, QComboBox, QSpinBox, QDateTimeEdit { padding: 5px 8px; background: #ffffff; border: 1px solid #c5d2e0; border-radius: 4px; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDateTimeEdit:hover { border-color: #7fa0bd; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateTimeEdit:focus { border: 1px solid #2f6ea5; background: #ffffff; }
QSplitter::handle { background: #cfd9e4; width: 1px; }
QStatusBar { background: #dce5ee; color: #3a4a5b; padding: 4px 12px; }
QStatusBar::item { border: none; }
"""


def run() -> None:
    import sys

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    font = QFont("Microsoft YaHei UI", 10)
    app.setFont(font)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


def smoke() -> int:
    """Headless construct + preview check used by `python run.py --smoke`."""
    import os
    import sys
    import tempfile
    from pathlib import Path

    from .collect import add_paths
    from .engine import preview_name

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    td = Path(tempfile.mkdtemp(prefix="pyrename-smoke-"))
    sample = td / "hello.jpg"
    sample.write_text("x", encoding="utf-8")
    win._append(add_paths([sample]))
    panel = win.settings_panel
    panel.new_name.setText("pic")
    panel.start.setValue(1)
    panel.increment.setValue(1)
    panel.width.setValue(3)
    win.refresh_preview()
    table_new = win.model.index(0, 1).data()
    settings = panel.settings()
    expected = preview_name(win.model.items[0], 0, settings)
    methods = []
    for i in range(panel.method.count()):
        panel.method.setCurrentIndex(i)
        methods.append(panel.settings().method.value)
    ext_labels = [panel.ext_mode.itemText(i) for i in range(panel.ext_mode.count())]
    ext_values = []
    for i in range(panel.ext_mode.count()):
        data = panel.ext_mode.itemData(i)
        ext_values.append(data.value if hasattr(data, "value") else str(data))
    panel.ext_mode.setCurrentIndex(1)
    panel.ext_find.setText("pg")
    panel.ext_replace.setText("peg")
    wired = panel.settings()
    ext_ok = wired.ext_mode is ExtMode.REPLACE and wired.ext_find == "pg" and wired.ext_replace == "peg"
    print("preview_table", table_new)
    print("preview_engine", expected)
    print("methods", methods)
    print("ext_mode_labels", ext_labels)
    print("ext_mode_values", ext_values)
    print("ext_replace_wired", ext_ok, wired.ext_mode)
    print("ext_mode_objectName", panel.ext_mode.objectName())
    tip_pairs = win.tip_targets()
    tips_ok = True
    missing = []
    for widget, label in tip_pairs:
        tip = (widget.toolTip() or "").strip()
        if not tip or tip == label or not any("\u4e00" <= ch <= "\u9fff" for ch in tip):
            tips_ok = False
            missing.append(label)
    print("tooltips_attached", len(tip_pairs), "missing", missing)
    print("tooltip_sample", win.btn_start.toolTip())
    fail = False
    if not tips_ok:
        print("FAIL tooltips missing", missing)
        fail = True
    if table_new != expected or table_new != "pic001.jpg":
        print("FAIL preview mismatch")
        fail = True
    if methods != [m.value for m, _ in METHOD_LABELS]:
        print("FAIL method cycle", methods)
        fail = True
    if "replace" not in ext_values or not any("替换" in lab for lab in ext_labels):
        print("FAIL ext replace not selectable")
        fail = True
    if not ext_ok:
        print("FAIL ext replace not wired into settings")
        fail = True
    if fail:
        win.close()
        return 1
    print("SMOKE_OK")
    win.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = list(sys.argv if argv is None else argv)
    if "--smoke" in argv:
        return smoke()
    run()
    return 0
