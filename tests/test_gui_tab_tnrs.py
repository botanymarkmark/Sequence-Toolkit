"""「物种名清洗」标签页的 GUI 与纯格式化助手测试。"""

import gc
import time

import pytest

pytest.importorskip("tkinter")

from tkinter import ttk  # noqa: E402

from seq_toolkit.settings import Settings  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from seq_toolkit.gui.app import App
    gc.collect()
    instance = None
    last_error = None
    for _ in range(3):
        try:
            instance = App(Settings(), start_polling=False)
            break
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
    if instance is None:  # pragma: no cover
        pytest.skip(f"无可用显示: {last_error}")
    yield instance
    instance.destroy()
    gc.collect()


@pytest.fixture(autouse=True)
def _forget_destroyed_busy_widgets(app):
    """每例前后把已销毁的控件从共享 App 的忙碌登记表里摘掉。

    A7 起 ``build()`` 会把「开始清洗 / 导出 CSV / 应用到序列文件」登记进
    ``app._busy_widgets``（A6 时本页还没有任何登记）；而本模块的 App 是**模块级共享**
    的，多个用例各自建 frame、又在结尾 destroy 它。已销毁的控件留在登记表里之后，任何
    一次 ``run_job`` 逐个 ``configure(state="disabled")`` 都会抛 TclError——异常被 Tk
    回调吞掉（只在 stderr 打一行 traceback），现象是"点了按钮任务没起、表格空着"，
    排查时毫无线索。这里保证登记表里始终只有活着的控件。
    """

    def prune() -> None:
        app._busy_widgets[:] = [widget for widget in app._busy_widgets
                                if widget.winfo_exists()]

    prune()
    yield
    prune()
    # 还要在主线程上主动回收一次。用例结尾 destroy 掉 frame 之后，页里的
    # tk.StringVar 就成了垃圾，而 tkinter.Variable.__del__ 是要调 Tcl 的。这堆垃圾若一直
    # 留到**后台任务线程**分配对象时才触发 GC，__del__ 就会在工作线程里跑，当场和工作
    # 线程自己的 Tcl 调用撞上。实测（faulthandler 抓的栈）：工作线程卡在
    # `pipeline.resolve_output_path` → `Path.exists` → `pathlib._parse_path` 里触发的
    # `tkinter.Variable.__del__`，主线程此刻也在 GC，两边互相等，`_wait_for_job` 的 5s
    # 上限被打满；现象是"apply 明明点了却没写文件、日志一条都没有"。
    # 在这里回收，垃圾在主线程、Tcl 空闲时就清干净了，工作线程的 GC 自然无事可做。
    gc.collect()


def _descendants(widget) -> list:
    found = []
    for child in widget.winfo_children():
        found.append(child)
        found.extend(_descendants(child))
    return found


def _button(parent, text):
    return next(w for w in _descendants(parent)
                if isinstance(w, ttk.Button) and w.cget("text") == text)


def _wait_for_job(app) -> None:
    """等后台任务跑完并抽干消息队列（本模块每个 GUI 用例的既有写法，抽成助手）。"""
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()


def _page_after_clean(app, names_text, result_rows):
    """建页 → 注入离线替身 → 清洗 → 返回 ``(frame, table)``。

    ``_make_poster`` 用裸赋值替换（与本文件既有两条 GUI 用例同一做法）；替身只在
    ``do_clean`` 真正发请求时被读，所以调用方随后仍可放心 patch 别的东西。
    """
    import tkinter as tk
    import seq_toolkit.gui.tab_tnrs as tab_tnrs
    from seq_toolkit.gui.widgets import CheckboxTable
    from tests.fakes_tnrs import FakePoster, rows_json

    frame = ttk.Frame(app)
    tab_tnrs.build(frame, app)
    tab_tnrs._make_poster = lambda _app: FakePoster([rows_json(result_rows)])
    text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
    text.insert("1.0", names_text)
    _button(frame, "开始清洗").invoke()
    _wait_for_job(app)
    return frame, next(w for w in _descendants(frame)
                       if isinstance(w, CheckboxTable))


def _out_dir_picker(frame):
    from seq_toolkit.gui.widgets import FilePicker
    return next(w for w in _descendants(frame) if isinstance(w, FilePicker))


def test_row_values_has_one_cell_per_heading():
    from seq_toolkit.gui.tab_tnrs import RESULT_HEADINGS, row_values
    from tests.fakes_tnrs import make_row, rows_json
    from seq_toolkit.tnrs import parse_response
    row = parse_response(rows_json([make_row()]))[0]
    values = row_values(row, 1)
    assert len(values) == len(RESULT_HEADINGS)
    assert values[0] == "1"                  # 序号列，也是表格行键
    assert values[1] == "Acer rubrum"
    assert values[2] == "Acer rubrum"
    assert values[3] == "已匹配"
    assert values[4] == "1.00"


def test_status_summary_text_counts_three_states():
    from seq_toolkit.gui.tab_tnrs import status_summary_text
    from tests.fakes_tnrs import make_row, rows_json
    from seq_toolkit.tnrs import parse_response
    rows = parse_response(rows_json([
        make_row(row_id=1), make_row(row_id=2, score="0.5"),
        make_row(row_id=3, matched="[No match found]", score="")]))
    text = status_summary_text(rows)
    assert "3 个名称" in text and "3 行" in text
    assert "已匹配 1" in text and "部分匹配 1" in text and "未匹配 1" in text


def test_tab_builds_with_expected_controls(app):
    """骨架控件存在性：输入区、导入按钮、参数下拉、结果表。

    按钮是**包含式**断言：A7 起「开始清洗 / 导出 CSV / 应用到序列文件 / 打开输出文件夹
    / 全选 / 反选」加入，A8 还会再动这一排。原先的精确相等（``buttons == [...]``）会在
    每次新增按钮时变红，而"把期望列表改成新的精确列表"凑绿恰好会掩盖真正的回归（按钮
    被删掉、文案被改坏）。这里只钉"这些按钮必须存在、且各恰好一个"。
    """
    import tkinter as tk
    from seq_toolkit.gui.tab_tnrs import build
    from seq_toolkit.gui.widgets import CheckboxTable

    frame = ttk.Frame(app)
    build(frame, app)

    assert len([w for w in _descendants(frame) if isinstance(w, CheckboxTable)]) == 1
    assert len([w for w in _descendants(frame) if isinstance(w, tk.Text)]) == 1
    combos = [w for w in _descendants(frame) if isinstance(w, ttk.Combobox)]
    assert len(combos) == 2                       # 名录来源 + 匹配模式
    buttons = [w.cget("text") for w in _descendants(frame) if isinstance(w, ttk.Button)]
    for expected in ("从序列文件导入物种名", "开始清洗", "导出 CSV", "应用到序列文件",
                     "打开输出文件夹", "全选", "反选"):
        assert buttons.count(expected) == 1, f"按钮「{expected}」应恰好一个：{buttons}"
    labels = [w.cget("text") for w in _descendants(frame) if isinstance(w, ttk.Label)]
    assert any("TNRS" in text for text in labels)
    frame.destroy()


def test_import_species_from_files_reads_fasta(tmp_path):
    from seq_toolkit.gui.tab_tnrs import import_species_from_files
    path = tmp_path / "s.fasta"
    path.write_text(">ON1.1 Salsola pellucida voucher X\nATGC\n"
                    ">ON2.1 Salsola tragus\nTTTT\n", encoding="utf-8")
    names = import_species_from_files([str(path)], Settings())
    assert names == ["Salsola pellucida", "Salsola tragus"]


def test_combo_boxes_keep_their_initial_values(app):
    """下拉框初值必须是中文标签，且不能被 GC 掉变空白。

    两个 StringVar 若只作 build() 的局部变量、又没有任何闭包捕获它们，引用计数归零
    后 Variable.__del__ 会 unset 掉 Tcl 变量，下拉框变成空白（实测 get() == ''）。
    这条用例钉住 parent.tnrs_vars 那个承重引用。
    """
    from seq_toolkit.gui.tab_tnrs import build
    frame = ttk.Frame(app)
    build(frame, app)
    combos = [w for w in _descendants(frame) if isinstance(w, ttk.Combobox)]
    assert len(combos) == 2
    values = [w.get() for w in combos]
    assert all(values), f"下拉框初值不能为空：{values}"
    assert "WCVP" in values[0]
    assert "best" in values[1]
    frame.destroy()


def test_import_species_warns_about_unreadable_files(tmp_path):
    """单个坏文件不中断导入，但必须记 WARN——「绝不静默」。"""

    class FakeLog:
        def __init__(self):
            self.messages = []

        def warn(self, message):
            self.messages.append(message)

    from seq_toolkit.gui.tab_tnrs import import_species_from_files
    good = tmp_path / "good.fasta"
    good.write_text(">ON1.1 Salsola pellucida\nATGC\n", encoding="utf-8")
    bad = tmp_path / "bad.custom"
    bad.write_bytes(b"\x00\x01 not a sequence file \x00")

    log = FakeLog()
    names = import_species_from_files([str(good), str(bad)], Settings(), log=log)
    assert names == ["Salsola pellucida"]
    assert len(log.messages) == 1
    assert "bad.custom" in log.messages[0]


def test_import_species_warns_about_records_without_species(tmp_path):
    """记录级静默也是静默：提不出物种名的记录必须计入 WARN。"""

    class FakeLog:
        def __init__(self):
            self.messages = []

        def warn(self, message):
            self.messages.append(message)

    from seq_toolkit.gui.tab_tnrs import import_species_from_files
    mixed = tmp_path / "mixed.fasta"
    # 第二条的 header 只剩登录号与凭证词（实测 species_raw == ''）：提不出物种名，
    # 必须计入 WARN。注意 **不能** 写成 ">12345 no species"——read_fasta 会把首个词
    # 当登录号剥掉，剩下的 "no species" 会被 naming 扫成物种名 "no_species"，
    # 反而走不到这个分支（实测见报告）。
    mixed.write_text(">ON1.1 Salsola pellucida\nATGC\n>12345 voucher X\nTTTT\n",
                     encoding="utf-8")

    log = FakeLog()
    names = import_species_from_files([str(mixed)], Settings(), log=log)
    assert names == ["Salsola pellucida"]
    assert any("1 条记录未能提取物种名" in message for message in log.messages)


def test_row_values_merges_warnings_and_unmatched_terms():
    """「警告」列与 CSV 的备注列口径一致：英文告警与残留词都要带上。"""
    from seq_toolkit.gui.tab_tnrs import RESULT_HEADINGS, row_values
    from tests.fakes_tnrs import make_row, rows_json
    from seq_toolkit.tnrs import parse_response
    row = parse_response(rows_json([
        make_row(matched="[No match found]", score="",
                 warnings="名字被更正", unmatched="voucher X")]))[0]
    values = row_values(row, 1)
    assert len(values) == len(RESULT_HEADINGS)
    assert "名字被更正" in values[6]
    assert "voucher X" in values[6]


def test_clean_populates_table_and_summary(app):
    import tkinter as tk
    import seq_toolkit.gui.tab_tnrs as tab_tnrs
    from tests.fakes_tnrs import FakePoster, make_row, rows_json

    frame = ttk.Frame(app)
    tab_tnrs.build(frame, app)
    poster = FakePoster([rows_json([
        make_row(row_id=1, submitted="Acer rubrum"),
        make_row(row_id=2, submitted="Xyzzy foobar", matched="[No match found]",
                 score="")])])
    tab_tnrs._make_poster = lambda _app: poster

    text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
    text.insert("1.0", "Acer rubrum\nXyzzy foobar\n")
    _button(frame, "开始清洗").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    from seq_toolkit.gui.widgets import CheckboxTable
    table = next(w for w in _descendants(frame) if isinstance(w, CheckboxTable))
    assert len(table.get_children()) == 2          # 未匹配的名称也在表里
    labels = [w.cget("text") for w in _descendants(frame) if isinstance(w, ttk.Label)]
    assert any("2 个名称" in text for text in labels)
    # 未匹配必须被显式提示
    assert any("未匹配" in entry.message for entry in app.log.entries)
    frame.destroy()


def test_mismatched_batches_are_surfaced_in_notes_and_log(app):
    """服务端少回行时必须同时出现在界面与日志里。

    这是控制器接线要求的硬项：`clean_names` 的 `mismatched_batches` 只给批次号与计数、
    不点名，如果界面不呈现，"被服务端丢了行"这件事不出现在任何界面元素里——
    「绝不静默」在界面层被打折。计划文本原先漏了这段循环，已被控制器同步补上。
    """
    import tkinter as tk
    import seq_toolkit.gui.tab_tnrs as tab_tnrs
    from tests.fakes_tnrs import FakePoster, make_row, rows_json

    frame = ttk.Frame(app)
    tab_tnrs.build(frame, app)
    # 提交 2 个名称、只回 1 行 ⇒ clean_names 记一条 mismatched_batches
    poster = FakePoster([rows_json([make_row(row_id=1, submitted="Acer rubrum")])])
    tab_tnrs._make_poster = lambda _app: poster

    text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
    text.insert("1.0", "Acer rubrum\nSolanum bipatens\n")
    _button(frame, "开始清洗").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    labels = [w.cget("text") for w in _descendants(frame) if isinstance(w, ttk.Label)]
    assert any("只返回" in text for text in labels), labels
    assert any("只返回" in entry.message for entry in app.log.entries)
    frame.destroy()


def test_export_csv_writes_utf8_sig_file(app, tmp_path, monkeypatch):
    import tkinter as tk
    import seq_toolkit.gui.tab_tnrs as tab_tnrs
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    from tkinter import filedialog

    frame = ttk.Frame(app)
    tab_tnrs.build(frame, app)
    poster = FakePoster([rows_json([make_row(row_id=1)])])
    tab_tnrs._make_poster = lambda _app: poster

    text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
    text.insert("1.0", "Acer rubrum\n")
    _button(frame, "开始清洗").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    target = tmp_path / "cleaned.csv"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kwargs: str(target))
    _button(frame, "导出 CSV").invoke()
    assert target.exists()
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "原始名称" in target.read_text(encoding="utf-8-sig")
    frame.destroy()


def test_apply_writes_cleaned_copy(app, tmp_path, monkeypatch):
    import tkinter as tk
    import seq_toolkit.gui.tab_tnrs as tab_tnrs
    from tkinter import filedialog
    from tests.fakes_tnrs import FakePoster, make_row, rows_json

    source = tmp_path / "样本.fasta"
    original_text = ">ON1.1 Adenostoma fasciculatum\nATGC\n"
    source.write_text(original_text, encoding="utf-8")
    out_dir = tmp_path / "out"

    frame = ttk.Frame(app)
    tab_tnrs.build(frame, app)
    poster = FakePoster([rows_json([
        make_row(row_id=1, submitted="Adenostoma fasciculatum",
                 accepted="Adenostoma fasciculatum")])])
    tab_tnrs._make_poster = lambda _app: poster
    # 完成提示是模态对话框：测试里必须换成空实现，否则用例会一直等它被点掉
    monkeypatch.setattr(tab_tnrs.messagebox, "showinfo", lambda *a, **k: None)

    text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
    text.insert("1.0", "Adenostoma fasciculatum\n")
    _button(frame, "开始清洗").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    from seq_toolkit.gui.widgets import FilePicker
    picker = next(w for w in _descendants(frame) if isinstance(w, FilePicker))
    picker.set_path(str(out_dir))
    monkeypatch.setattr(filedialog, "askopenfilenames",
                        lambda **kwargs: (str(source),))
    _button(frame, "应用到序列文件").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    written = out_dir / "样本_cleaned.fasta"
    assert written.exists()
    # 原文件必须原封不动（绝不就地覆盖）
    assert source.read_text(encoding="utf-8") == original_text
    frame.destroy()


def test_apply_refuses_empty_output_dir(app, tmp_path, monkeypatch):
    """输出目录为空时必须前置拦截，不能把全批失败报成成功。

    默认设置里 ``output_dir`` 就是空串、用户又没点过「浏览…」时，若不拦截，每个文件
    都会在 ``os.makedirs("")`` 处抛 FileNotFoundError，逐个被文件级 ``except`` 记 ERROR，
    ``outcomes`` 空着进 ``on_apply_done`` —— 弹窗会宣称「改写完成 / 已处理 0 个文件」，
    即「一次全批失败被报成了成功」。这里同时钉住「任务根本没起」与「弹窗一次都没出现」。
    """
    import seq_toolkit.gui.tab_tnrs as tab_tnrs
    from tkinter import filedialog
    from tests.fakes_tnrs import make_row

    shown: list = []
    monkeypatch.setattr(tab_tnrs.messagebox, "showinfo",
                        lambda *a, **k: shown.append(a))
    source = tmp_path / "样本.fasta"
    source.write_text(">ON1.1 Acer rubrum\nATGC\n", encoding="utf-8")

    frame, table = _page_after_clean(
        app, "Acer rubrum\n",
        [make_row(row_id=1, submitted="Acer rubrum")])
    table.selection.check("1")                 # 覆盖 do_apply 的勾选分支
    _out_dir_picker(frame).set_path("")        # 用户没点「浏览…」⇒ 空目录
    monkeypatch.setattr(filedialog, "askopenfilenames",
                        lambda **kwargs: (str(source),))
    _button(frame, "应用到序列文件").invoke()
    _wait_for_job(app)

    messages = [entry.message for entry in app.log.entries]
    assert any("请先指定改写输出文件夹" in text for text in messages), messages
    # 拦截必须发生在动手之前：一条"改写失败"都不该有
    assert not any("改写失败" in text for text in messages), messages
    assert shown == [], f"没有发生任何改写，弹窗不该出现：{shown}"
    frame.destroy()


def test_apply_lets_existing_target_yield_and_warns(app, tmp_path, monkeypatch):
    """目标已存在时让位 _1 并记 WARN——不传 ``log=app.log`` 的话这条 WARN 会静默失效。

    ``apply_names_to_file`` 的 ``log`` 默认为 ``None``：调用方少传一个 kwarg，全局约束
    「绝不静默覆盖」就无声失效而其余测试全绿。这条用例是那个 kwarg 唯一的回归网。
    """
    import seq_toolkit.gui.tab_tnrs as tab_tnrs
    from tkinter import filedialog
    from tests.fakes_tnrs import make_row

    monkeypatch.setattr(tab_tnrs.messagebox, "showinfo", lambda *a, **k: None)
    source = tmp_path / "样本.fasta"
    source.write_text(">ON1.1 Acer rubrum\nATGC\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    placeholder = out_dir / "样本_cleaned.fasta"
    placeholder.write_text(">占位\nAAAA\n", encoding="utf-8")

    frame, table = _page_after_clean(
        app, "Acer rubrum\n",
        [make_row(row_id=1, submitted="Acer rubrum")])
    table.selection.check("1")
    _out_dir_picker(frame).set_path(str(out_dir))
    monkeypatch.setattr(filedialog, "askopenfilenames",
                        lambda **kwargs: (str(source),))
    _button(frame, "应用到序列文件").invoke()
    _wait_for_job(app)

    written = out_dir / "样本_cleaned_1.fasta"
    assert written.exists(), sorted(path.name for path in out_dir.iterdir())
    assert "Acer rubrum" in written.read_text(encoding="utf-8")
    # 让位而不是覆盖：撞名的那份一个字节都不能动
    assert placeholder.read_text(encoding="utf-8") == ">占位\nAAAA\n"
    assert any("目标文件已存在，实际写入" in entry.message
               for entry in app.log.entries), [e.message for e in app.log.entries]
    frame.destroy()


def test_apply_warns_about_partial_matches(app, tmp_path, monkeypatch):
    """部分匹配的行也会被改名，必须先提示。

    规格 FR-1.6 只排除「未匹配」，因此 ``部分匹配`` 的行会照常取接受名回写。用户不知道
    这件事就会对"某个名字为什么被改成了不完全等于它的接受名"莫名其妙。
    """
    import seq_toolkit.gui.tab_tnrs as tab_tnrs
    from tkinter import filedialog
    from tests.fakes_tnrs import make_row

    monkeypatch.setattr(tab_tnrs.messagebox, "showinfo", lambda *a, **k: None)
    source = tmp_path / "样本.fasta"
    source.write_text(">ON1.1 Xyzzy foobar\nATGC\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    frame, table = _page_after_clean(app, "Acer rubrum\nXyzzy foobar\n", [
        make_row(row_id=1, submitted="Acer rubrum"),
        make_row(row_id=2, submitted="Xyzzy foobar", matched="Xyzzy foobar",
                 accepted="Xyzzy bar", score="0.5")])
    table.selection.check("1")
    table.selection.check("2")                 # 部分匹配的那行也在勾选集里
    _out_dir_picker(frame).set_path(str(out_dir))
    monkeypatch.setattr(filedialog, "askopenfilenames",
                        lambda **kwargs: (str(source),))
    _button(frame, "应用到序列文件").invoke()
    _wait_for_job(app)

    messages = [entry.message for entry in app.log.entries]
    assert any("1 行是部分匹配" in text and "规格只排除未匹配" in text
               for text in messages), messages
    # 提示说的就是实际会发生的事：它的接受名真的被写进去了
    assert "Xyzzy bar" in (out_dir / "样本_cleaned.fasta").read_text(encoding="utf-8")
    frame.destroy()


def test_apply_isolates_a_failing_file(app, tmp_path, monkeypatch):
    """单个文件失败不得中断整批：坏文件记 ERROR，好文件照常写出。

    坏文件走的是**裸 OSError**（后缀是 .fasta ⇒ ``sniff_format`` 吞掉读取失败、
    ``detect_format`` 按后缀判成 fasta，随后 ``open()`` 抛 FileNotFoundError），
    它不是 ``SeqToolkitError`` 的子类——文件级 ``except`` 若只捕后者，这里会让整批中断。
    """
    import seq_toolkit.gui.tab_tnrs as tab_tnrs
    from seq_toolkit.applog import ERROR
    from tkinter import filedialog
    from tests.fakes_tnrs import make_row

    monkeypatch.setattr(tab_tnrs.messagebox, "showinfo", lambda *a, **k: None)
    good = tmp_path / "good.fasta"
    good.write_text(">ON1.1 Acer rubrum\nATGC\n", encoding="utf-8")
    missing = tmp_path / "gone.fasta"          # 不存在的路径，但后缀会让它被判成 fasta
    out_dir = tmp_path / "out"

    frame, table = _page_after_clean(
        app, "Acer rubrum\n",
        [make_row(row_id=1, submitted="Acer rubrum")])
    table.selection.check("1")
    _out_dir_picker(frame).set_path(str(out_dir))
    monkeypatch.setattr(filedialog, "askopenfilenames",
                        lambda **kwargs: (str(missing), str(good)))
    _button(frame, "应用到序列文件").invoke()
    _wait_for_job(app)

    errors = [entry.message for entry in app.log.entries if entry.level == ERROR]
    assert any("改写失败，已跳过" in text and "gone.fasta" in text
               for text in errors), errors
    # 第一个文件失败之后，第二个文件照旧写出 ⇒ 整批没有被中断
    written = out_dir / "good_cleaned.fasta"
    assert written.exists(), sorted(path.name for path in out_dir.iterdir())
    assert "Acer rubrum" in written.read_text(encoding="utf-8")
    frame.destroy()


def test_export_csv_logs_only_after_a_successful_write(app, tmp_path, monkeypatch):
    """取消另存框不得留下"已导出"的假记录；勾选分支只导出勾选行。

    tab_search.rows_to_export 把说明推迟到写出之后，就是为了这条；顺序颠倒会让日志
    在用户取消后仍然宣称"已导出 N 行"，事后无法从日志判断到底导没导。

    **取消这一步必须跑在「未勾选」状态下**：那句会撒谎的说明（"未勾选任何行，已导出
    表格显示的全部 N 行"）只在未勾选分支里产生；勾选状态下新旧两种顺序都一个字节都不
    记，在那里断言"没有已导出"是空转、钉不住顺序。（实测：把说明挪回另存框之前，勾选
    状态下取消该用例仍全绿。）
    """
    import csv
    import seq_toolkit.gui.tab_tnrs as tab_tnrs
    from tkinter import filedialog
    from tests.fakes_tnrs import make_row

    frame, table = _page_after_clean(app, "Acer rubrum\nSolanum bipatens\n", [
        make_row(row_id=1, submitted="Acer rubrum"),
        make_row(row_id=2, submitted="Solanum bipatens")])

    # 1) 未勾选 + 取消另存框：不写文件、也**不许**留下任何"已导出"的假记录
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kwargs: "")
    app._clear_log()
    _button(frame, "导出 CSV").invoke()
    assert not [entry.message for entry in app.log.entries
                if "已导出" in entry.message], [e.message for e in app.log.entries]

    # 2) 勾选第 1 行 → 写成功：只导出勾选的那一行，且不再出现"未勾选任何行"的说明
    table.selection.check("1")
    target = tmp_path / "out.csv"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kwargs: str(target))
    app._clear_log()
    _button(frame, "导出 CSV").invoke()

    assert target.exists()
    with open(target, newline="", encoding="utf-8-sig") as handle:
        data = list(csv.reader(handle))
    assert len(data) == 2, data                    # 表头 + 唯一一条数据行
    assert data[0][0] == "原始名称"
    assert data[1][0] == "Acer rubrum"             # 勾选的就是它
    assert "Solanum bipatens" not in target.read_text(encoding="utf-8-sig")
    messages = [entry.message for entry in app.log.entries]
    # 勾选分支与未勾选分支的分界：这里**不能**有"未勾选"说明
    assert not any("未勾选任何行" in text for text in messages), messages
    assert any("已导出 1 行到" in text for text in messages), messages
    frame.destroy()


def test_tab_is_registered_and_settings_index_unchanged(app):
    titles = [app.notebook.tab(index, "text")
              for index in range(len(app.notebook.tabs()))]
    assert "物种名清洗" in titles
    # 新页排在「设置」之后（而不是断言它是最后一页：后续任务还会追加页面）
    assert titles.index("物种名清洗") > titles.index("设置")
    assert app.notebook.tab(4, "text") == "设置"   # tab_search 里硬编码的 open_tab(4)
