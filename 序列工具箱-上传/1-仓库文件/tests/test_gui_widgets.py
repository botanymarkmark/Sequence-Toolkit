import time

import pytest

from seq_toolkit.gui.widgets import (
    CHECKED,
    UNCHECKED,
    CheckboxTable,
    RowSelection,
    SortableTable,
)


@pytest.fixture(scope="module")
def tk_root():
    """创建隐藏的 Tk 根窗口；无 tkinter 或无显示环境时跳过这些用例。

    根窗口整个模块只创建一次：同一进程内反复 Tk()/destroy() 会让 Tcl 偶发
    找不到 tk.tcl（表现为随机的 TclError），那会让 Tk 覆盖时有时无。

    即便如此，本进程里只要还另有 Tk 根窗口（例如 test_gui_app.py 的 App），
    本模块这次创建仍会以约 20%~30% 的概率瞬时读不到 ttk.tcl。这是环境瞬时
    故障而非无显示环境，所以先做几次短重试再判定为无显示（重试前全量套件
    10 次里有 2~3 次随机跳过本模块用例，重试后 12/12 干净）。
    """
    tk = pytest.importorskip("tkinter")
    root = None
    last_error = None
    for _ in range(3):
        try:
            root = tk.Tk()
            break
        except tk.TclError as error:  # 无头环境或瞬时失败
            last_error = error
            time.sleep(0.2)
    if root is None:
        pytest.skip(f"无可用显示环境：{last_error}")
    root.withdraw()
    yield root
    root.destroy()


def _column_values(table, position=0):
    """按当前渲染顺序返回某一列的值。"""
    return [table.item(iid, "values")[position] for iid in table.get_children()]


def test_checked_keys_follow_insertion_order():
    selection = RowSelection()
    selection.set_keys(["c", "a", "b"])
    selection.check("b")
    selection.check("a")
    assert selection.checked_keys() == ["a", "b"]


def test_toggle_switches_state():
    selection = RowSelection()
    selection.set_keys(["a"])
    assert selection.is_checked("a") is False
    selection.toggle("a")
    assert selection.is_checked("a") is True
    selection.toggle("a")
    assert selection.is_checked("a") is False


def test_check_all_and_uncheck_all():
    selection = RowSelection()
    selection.set_keys(["a", "b", "c"])
    selection.check_all()
    assert selection.count() == 3
    selection.uncheck_all()
    assert selection.count() == 0


def test_invert():
    selection = RowSelection()
    selection.set_keys(["a", "b", "c"])
    selection.check("b")
    selection.invert()
    assert selection.checked_keys() == ["a", "c"]


def test_set_keys_drops_stale_checked_entries():
    selection = RowSelection()
    selection.set_keys(["a", "b"])
    selection.check_all()
    selection.set_keys(["b", "c"])
    # checked_keys() 按 _order 过滤，单看它会掩盖"勾选集合未清理"的退化，
    # 因此显式断言底层集合本身：失效的 "a" 必须被真正丢弃。
    assert selection.checked_keys() == ["b"]
    assert selection.count() == 1
    assert selection.is_checked("a") is False
    assert selection.is_checked("b") is True
    assert selection.total() == 2


def test_set_keys_preserves_still_valid_checks():
    selection = RowSelection()
    selection.set_keys(["a", "b"])
    selection.check("a")
    selection.set_keys(["a", "b", "c"])
    assert selection.checked_keys() == ["a"]


def test_toggle_unknown_key_is_ignored():
    selection = RowSelection()
    selection.set_keys(["a"])
    selection.toggle("zzz")
    assert selection.count() == 0


# --- 以下用例需要可用的 Tk 显示环境，无头环境自动跳过 ---


def test_checkbox_table_deduplicates_repeated_row_keys(tk_root):
    """重复首元素不能让表格半空，也不能抛 Tcl 的 "Item k already exists"。"""
    table = CheckboxTable(tk_root, ["name"], ["名称"])
    try:
        table.set_rows([("k1", "甲"), ("k2", "乙"), ("k1", "甲副本")])
        assert list(table.get_children()) == ["k1", "k2"]
        assert table.selection.total() == 2
        assert _column_values(table) == [UNCHECKED, UNCHECKED]
        # 首元素既是行键、也是第 1 列（"名称"）要显示的值，故第 2 列才是这段数据列。
        assert _column_values(table, 2) == ["甲", "乙"]  # 保留首次出现
    finally:
        table.destroy()


def test_checkbox_table_shows_the_row_key_as_the_first_data_column(tk_root):
    """表头与值必须逐列对应：首元素既当行 iid，也必须出现在它自己那一列里。

    调用方（tab_search.py）按 SortableTable 的约定传入**全部**要显示的字段，
    首元素是登录号而不是"只用来当键"。若实现把它从 values 里丢掉，整行会左移一位：
    accession 列下显示长度、长度列显示物种名，最后一列永远空白。
    """
    table = CheckboxTable(tk_root, ["accession", "length", "organism"],
                          ["Accession", "长度", "物种名"])
    try:
        table.set_rows([("ON929854.1", "152,398", "Salsola pellucida")])
        assert list(table.item("ON929854.1", "values")) == [
            UNCHECKED, "ON929854.1", "152,398", "Salsola pellucida"]
    finally:
        table.destroy()


def test_checkbox_table_keeps_the_row_key_as_the_selection_key(tk_root):
    """显示全部值之后，勾选键仍必须是登录号（下载按登录号取勾选），不是行序号。"""
    table = CheckboxTable(tk_root, ["accession", "length", "organism"],
                          ["Accession", "长度", "物种名"])
    try:
        table.set_rows([("ON929854.1", "152,398", "Salsola pellucida")])
        table.selection.check("ON929854.1")
        table.refresh_checks()
        assert table.selection.checked_keys() == ["ON929854.1"]
        # 勾选标记占的是独立的"选"列，不得覆盖登录号单元格。
        assert list(table.item("ON929854.1", "values")) == [
            CHECKED, "ON929854.1", "152,398", "Salsola pellucida"]
    finally:
        table.destroy()


def test_checkbox_table_dedup_keeps_table_usable(tk_root):
    """去重后表格仍可正常工作：勾选、刷新、换批数据都不受影响。"""
    table = CheckboxTable(tk_root, ["name"], ["名称"])
    try:
        table.set_rows([("k1", "甲"), ("k1", "重复"), ("k2", "乙")])
        table.selection.check("k2")
        table.refresh_checks()
        assert _column_values(table) == [UNCHECKED, CHECKED]
        table.set_rows([("k3", "丙"), ("k3", "重复")])
        assert _column_values(table) == [UNCHECKED]
        assert table.selection.checked_keys() == []
    finally:
        table.destroy()


def test_sortable_table_sorts_mixed_number_and_text_without_type_error(tk_root):
    """(0, float) 优先于 (1, str)：混合类型不比较不同类型，故不抛 TypeError。"""
    table = SortableTable(tk_root, ["value"], ["数值"])
    try:
        table.set_rows([("10",), ("9",), ("a",)])
        table.sort_by("value")
        assert _column_values(table) == ["9", "10", "a"]
        table.sort_by("value")
        assert _column_values(table) == ["a", "10", "9"]
    finally:
        table.destroy()


def test_sortable_table_handles_thousands_separator_before_text(tk_root):
    table = SortableTable(tk_root, ["value"], ["数值"])
    try:
        table.set_rows([("1,200",), ("x",), ("900",)])
        table.sort_by("value")
        assert _column_values(table) == ["900", "1,200", "x"]
    finally:
        table.destroy()


def test_sortable_table_first_click_sorts_ascending(tk_root):
    table = SortableTable(tk_root, ["value"], ["值"])
    try:
        table.set_rows([("b",), ("a",), ("c",)])
        table.sort_by("value")
        assert _column_values(table) == ["a", "b", "c"]
        table.sort_by("value")
        assert _column_values(table) == ["c", "b", "a"]
    finally:
        table.destroy()


def test_sortable_table_set_rows_resets_sort_direction(tk_root):
    table = SortableTable(tk_root, ["value"], ["值"])
    try:
        table.set_rows([("b",), ("a",)])
        # 只排一次：该列方向状态记录为"上次升序"，因此换数据后若不清状态，
        # 下次点击会取降序（与"新数据首次点击升序"的预期错位）。
        table.sort_by("value")
        assert _column_values(table) == ["a", "b"]
        table.set_rows([("d",), ("c",)])
        assert _column_values(table) == ["d", "c"]  # 新数据按原始顺序渲染
        table.sort_by("value")
        assert _column_values(table) == ["c", "d"]  # 方向已重置 ⇒ 又是升序
        table.sort_by("value")
        assert _column_values(table) == ["d", "c"]  # 同一批数据内继续交替
    finally:
        table.destroy()


# ---------- FilePicker：运行中切换选择类型（输出文件 ⇄ 输出目录） ----------

def _browse_button(picker):
    from tkinter import ttk
    for child in picker.winfo_children():
        if isinstance(child, ttk.Button):
            return child
    raise AssertionError("FilePicker 里没有「浏览…」按钮")


def test_file_picker_set_mode_switches_the_dialog_type(tk_root, monkeypatch):
    """set_mode 之后「浏览…」必须打开对应类型的对话框，标题也一并换掉。

    不能用"另存为"对话框去选目录：用户在那里选不到目录，只能手打路径。
    """
    from seq_toolkit.gui import widgets

    picker = widgets.FilePicker(tk_root, mode="save", title="选择输出文件")
    try:
        assert picker.mode == "save"
        assert picker.title == "选择输出文件"

        picker.set_mode("directory", title="输出目录")
        assert picker.mode == "directory"
        assert picker.title == "输出目录"

        asked = []
        monkeypatch.setattr(widgets.filedialog, "askdirectory",
                            lambda **kwargs: (asked.append(kwargs), "D:/输出")[1])
        monkeypatch.setattr(widgets.filedialog, "asksaveasfilename",
                            lambda **kwargs: pytest.fail("目录模式下不得打开另存为对话框"))
        _browse_button(picker).invoke()

        assert asked and asked[0]["title"] == "输出目录"
        assert picker.path() == "D:/输出"
    finally:
        picker.destroy()


def test_file_picker_rejects_an_unknown_mode(tk_root):
    """模式拼错必须立刻报错：否则会被当成"选文件"，用户要选目录却弹出文件对话框。"""
    from seq_toolkit.gui import widgets

    with pytest.raises(ValueError):
        widgets.FilePicker(tk_root, mode="dir")

    picker = widgets.FilePicker(tk_root, mode="directory")
    try:
        with pytest.raises(ValueError):
            picker.set_mode("folder")
        assert picker.mode == "directory", "校验失败时不得改动当前模式"
    finally:
        picker.destroy()
