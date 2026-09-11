"""可复用控件。勾选状态逻辑（RowSelection）与 Tk 控件分离，便于测试。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Iterable, Sequence

CHECKED = "\u2611"      # ☑
UNCHECKED = "\u2610"    # ☐
CHECK_COLUMN = "#1"

# FilePicker 支持的三种选择模式：显式列出来，拼错时立刻报错而不是静默降级成"选文件"
PICKER_MODES = ("file", "save", "directory")


class RowSelection:
    """表格勾选状态。纯逻辑，不依赖 Tk。"""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._checked: set[str] = set()

    def set_keys(self, keys: Iterable[str]) -> None:
        self._order = [str(key) for key in keys]
        valid = set(self._order)
        self._checked &= valid

    def toggle(self, key: str) -> None:
        key = str(key)
        if key not in self._order:
            return
        if key in self._checked:
            self._checked.discard(key)
        else:
            self._checked.add(key)

    def check(self, key: str) -> None:
        if str(key) in self._order:
            self._checked.add(str(key))

    def uncheck(self, key: str) -> None:
        self._checked.discard(str(key))

    def is_checked(self, key: str) -> bool:
        return str(key) in self._checked

    def checked_keys(self) -> list[str]:
        return [key for key in self._order if key in self._checked]

    def check_all(self) -> None:
        self._checked = set(self._order)

    def uncheck_all(self) -> None:
        self._checked.clear()

    def invert(self) -> None:
        self._checked = set(self._order) - self._checked

    def count(self) -> int:
        return len(self._checked)

    def total(self) -> int:
        return len(self._order)


class CheckboxTable(ttk.Treeview):
    """首列为勾选框的表格。行数据以元组给出，首元素既作行的唯一键、也作第 1 列的值。

    **整行都要显示**：调用方（tab_search.py 的检索结果表）传的是全部要显示的字段，
    与同文件的 SortableTable 同一约定。勾选标记占用的是额外的"选"列，不得以任何
    形式顶掉首元素，否则整行会左移一位——accession 列下显示长度、长度列显示物种名，
    最后一列永远是空的。
    """

    def __init__(self, parent, columns: Sequence[str], headings: Sequence[str],
                 widths: Sequence[int] | None = None) -> None:
        all_columns = ("check",) + tuple(columns)
        super().__init__(parent, columns=all_columns, show="headings", height=14)
        self.selection = RowSelection()
        self._rows: list[tuple] = []
        self._on_change: Callable[[], None] | None = None

        self.heading("check", text="选")
        self.column("check", width=40, anchor="center", stretch=False)
        for index, column in enumerate(columns):
            self.heading(column, text=headings[index])
            width = widths[index] if widths else 120
            self.column(column, width=width, anchor="w", stretch=True)

        self.bind("<Button-1>", self._on_click)

    def _on_click(self, event) -> None:
        if self.identify_region(event.x, event.y) != "cell":
            return
        if self.identify_column(event.x) != CHECK_COLUMN:
            return
        item = self.identify_row(event.y)
        if not item:
            return
        self.selection.toggle(item)
        self.refresh_checks()

    def set_rows(self, rows: list[tuple]) -> None:
        # 行 iid 由首元素决定，重复会让 Tcl 抛 "Item k already exists"，
        # 使表格停在中途（半空表）。这里按 key 去重（保留首次出现）作为防线，
        # 保证永远能建构成功；T23 侧另有去重，此处静默丢弃而不报错。
        self.delete(*self.get_children())
        unique_rows: list[tuple] = []
        seen: set[str] = set()
        for row in rows:
            key = str(row[0])
            if key in seen:
                continue
            seen.add(key)
            unique_rows.append(row)
        self._rows = unique_rows
        self.selection.set_keys([str(row[0]) for row in self._rows])
        for row in self._rows:
            key = str(row[0])
            # values 与 headings 逐列对应：首元素留在它自己的那一列，不再被 iid 吞掉。
            # checked_keys() 依旧按 iid（登录号）返回，下载取勾选不受影响。
            self.insert("", "end", iid=key,
                        values=(UNCHECKED,) + tuple(row))
        self.refresh_checks()

    def refresh_checks(self) -> None:
        for key in self.get_children():
            mark = CHECKED if self.selection.is_checked(key) else UNCHECKED
            values = list(self.item(key, "values"))
            values[0] = mark
            self.item(key, values=values)
        if self._on_change is not None:
            self._on_change()

    def displayed_rows(self) -> list[tuple]:
        """当前表格里显示的全部行，顺序与屏幕上从上到下一致（首元素即行键）。

        返回副本：调用方（检索页的导出）不得改动表格自身的行数据。行内容就是
        ``set_rows`` 收到的那一版（不含"选"列那个勾选标记），因此导出 CSV 时
        逐列与表头对应，不会左移一位。
        """
        return list(self._rows)

    def bind_selection_change(self, callback: Callable[[], None]) -> None:
        self._on_change = callback


class SortableTable(ttk.Treeview):
    """支持点击表头排序的只读表格。"""

    def __init__(self, parent, columns: Sequence[str], headings: Sequence[str],
                 widths: Sequence[int] | None = None) -> None:
        super().__init__(parent, columns=tuple(columns), show="headings", height=14)
        self._rows: list[tuple] = []
        # 记录该列上一次排序是否为降序；新列没有条目，故首次点击取升序。
        self._reverse: dict[str, bool] = {}
        for index, column in enumerate(columns):
            self.heading(column, text=headings[index],
                         command=lambda c=column: self.sort_by(c))
            width = widths[index] if widths else 120
            self.column(column, width=width, anchor="w", stretch=True)

    @staticmethod
    def _sort_value(value) -> tuple[int, object]:
        text = str(value)
        try:
            return (0, float(text.replace(",", "")))
        except ValueError:
            return (1, text.lower())

    def set_rows(self, rows: list[tuple]) -> None:
        self._rows = list(rows)
        # 换一批数据后方向状态失效：重置，使该列下次点击回到升序。
        self._reverse.clear()
        self._render(self._rows)

    def _render(self, rows: list[tuple]) -> None:
        self.delete(*self.get_children())
        for index, row in enumerate(rows):
            self.insert("", "end", iid=f"r{index}", values=tuple(row))

    def sort_by(self, column: str) -> None:
        columns = list(self["columns"])
        if column not in columns:
            return
        position = columns.index(column)
        # 缺省（尚未排过该列）取 True ⇒ reverse=False ⇒ 首次点击为升序。
        reverse = not self._reverse.get(column, True)
        self._reverse[column] = reverse
        self._render(sorted(self._rows,
                            key=lambda row: self._sort_value(row[position]),
                            reverse=reverse))


class ProgressPanel(ttk.Frame):
    """进度条 + 状态文字。"""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self._bar = ttk.Progressbar(self, mode="determinate", maximum=100)
        self._bar.pack(fill="x", side="left", expand=True)
        self._label = ttk.Label(self, text="就绪", width=24, anchor="w")
        self._label.pack(side="left", padx=(8, 0))

    def start(self, total: int) -> None:
        self._bar.configure(maximum=max(total, 1), value=0)
        self._label.configure(text=f"0 / {total}")

    def update(self, done: int, total: int, text: str = "") -> None:
        self._bar.configure(maximum=max(total, 1), value=done)
        self._label.configure(text=text or f"{done} / {total}")

    def finish(self, text: str = "完成") -> None:
        self._bar.configure(value=self._bar["maximum"])
        self._label.configure(text=text)

    def reset(self) -> None:
        self._bar.configure(value=0)
        self._label.configure(text="就绪")


class FilePicker(ttk.Frame):
    """一行输入框 + 浏览按钮。"""

    def __init__(self, parent, mode: str = "file", title: str = "选择",
                 filetypes=None) -> None:
        super().__init__(parent)
        self._check_mode(mode)
        self._mode = mode
        self._title = title
        self._filetypes = filetypes
        # master 必须显式传 self：不传时 Variable 会挂到 tkinter 的 _default_root
        # （进程里第一个根窗口）上。本控件若建在另一个 Tk 根窗口的子树里，控件与变量
        # 就落在两个不同的 Tcl 解释器里——用户点了「浏览…」并选中目录后，控件显示新
        # 路径，而 path() 读出来仍是空串，表现为"选了目录却提示未指定输出文件夹"。
        self._variable = tk.StringVar(master=self)
        entry = ttk.Entry(self, textvariable=self._variable)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(self, text="浏览…", command=self._browse).pack(side="left", padx=(4, 0))

    @staticmethod
    def _check_mode(mode: str) -> None:
        """模式拼错时必须立刻报错：否则会被 _browse 当成 "选文件"，
        用户要选目录却弹出文件对话框（本项目招牌规则是「永不静默」）。"""
        if mode not in PICKER_MODES:
            raise ValueError(f"未知的选择模式: {mode}")

    @property
    def mode(self) -> str:
        """当前选择模式：``file`` / ``save`` / ``directory``。"""
        return self._mode

    @property
    def title(self) -> str:
        """「浏览…」打开的对话框标题。"""
        return self._title

    def set_mode(self, mode: str, title: str | None = None) -> None:
        """运行中切换选择模式（可一并换掉对话框标题）。

        标签页需要在「选输出文件」与「选输出目录」之间切换时用它，而不是建两个
        选择器再互相藏起来：后者会留下两个各自持有路径的控件，界面显示与程序读到的
        状态迟早不一致。
        """
        self._check_mode(mode)
        self._mode = mode
        if title is not None:
            self._title = title

    def _browse(self) -> None:
        if self._mode == "directory":
            chosen = filedialog.askdirectory(title=self._title)
        else:
            chosen = filedialog.asksaveasfilename if self._mode == "save" else \
                filedialog.askopenfilename
            chosen = chosen(title=self._title, filetypes=self._filetypes or [])
        if chosen:
            self._variable.set(chosen)

    def set_path(self, path: str) -> None:
        self._variable.set(path)

    def path(self) -> str:
        return self._variable.get().strip()


def grid_row(parent, row: int, label: str, widget):
    """两列表单排版助手：左标签、右控件。返回左标签，便于调用方运行中改它的文字。"""
    text = ttk.Label(parent, text=label)
    text.grid(row=row, column=0, sticky="w", padx=(8, 6), pady=3)
    widget.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=3)
    parent.columnconfigure(1, weight=1)
    return text


def format_download_summary(report, per_sequence_files: bool = True) -> str:
    """一次批量下载结果的中文汇总。T23 / T24 共用，保证两处口径一致。

    **计数单位是登录号，不是写出的文件数**：``DownloadReport.succeeded`` 的含义随配置
    漂移——勾了「每序列单文件」时它数的是真正落盘的序列；没勾时它数的是"本次收下的
    登录号"（这些序列只出现在合并产物里）。因此这里的量词一律是"条"，绝不写成
    "成功写出 N 个文件"，否则用户会按文件数去核对磁盘而对不上。
    """
    text = (f"成功 {report.succeeded} 条，跳过 {report.skipped} 条，"
            f"失败 {report.failed} 条（计数单位为登录号）")
    if not per_sequence_files:
        text += "；未勾选「每序列单文件」，序列只写入合并产物"
    return text
