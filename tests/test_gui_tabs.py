"""T21 合并/转换 与 T22 重命名/拆分 标签页的测试。

单根窗口：本模块共用一个 App（与 tests/test_gui_widgets.py、tests/test_gui_app.py
的既有做法一致）。同一进程里只要已经存在别的 Tk 根窗口，新建根窗口就会以约
20%~30% 的概率瞬时读不到 Tcl 的 tk.tcl/ttk.tcl，因此这里用模块级单根 + 短重试；
每个用例只建一次窗口，避免"每个用例 Tk()/destroy()"造成的随机跳过。
"""

import gc
import io
import json
import time
import tkinter as tk
from urllib.parse import urlparse

import pytest

pytest.importorskip("tkinter")

from tkinter import ttk  # noqa: E402

from seq_toolkit.gui.widgets import CheckboxTable, FilePicker  # noqa: E402
from seq_toolkit.ncbi import NcbiClient  # noqa: E402
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
        except Exception as exc:  # 无头环境或 Tcl 瞬时读不到 tk.tcl
            last_error = exc
            time.sleep(0.2)
    if instance is None:  # pragma: no cover - 无图形环境时跳过
        pytest.skip(f"无可用显示: {last_error}")
    yield instance
    instance.destroy()
    gc.collect()


@pytest.fixture(autouse=True)
def _isolated(app):
    """每个用例从干净状态开始，且不让后台任务跨用例残留。"""
    app._clear_log()
    app.set_status("就绪")
    yield
    app.worker.cancel()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()


# ---------- 控件查找助手（标签页不对外暴露控件，测试按类型/文字在子树里定位） ----------

def _descendants(widget) -> list:
    found = []
    for child in widget.winfo_children():
        found.append(child)
        found.extend(_descendants(child))
    return found


def _button(parent, text: str):
    for widget in _descendants(parent):
        if isinstance(widget, ttk.Button) and widget.cget("text") == text:
            return widget
    raise AssertionError(f"未找到按钮：{text}")


def _checkbutton(parent, text: str):
    for widget in _descendants(parent):
        if isinstance(widget, ttk.Checkbutton) and widget.cget("text") == text:
            return widget
    raise AssertionError(f"未找到勾选框：{text}")


def _pickers(parent) -> list:
    return [widget for widget in _descendants(parent)
            if isinstance(widget, FilePicker)]


def _wait_for_job(app, timeout: float = 15.0) -> None:
    """本模块的 App 未启动 after 轮询，因此手动等待并抽干消息队列。"""
    deadline = time.monotonic() + timeout
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not app.worker.is_running(), "后台任务超时未结束"
    app._drain()


def _new_tab_frame(app):
    """新建一个空的标签页容器，避免与 App 启动时已建的同名标签页互相干扰。"""
    frame = ttk.Frame(app.notebook)
    app.notebook.add(frame, text="测试用")
    return frame


# ---------- 新面板的底部按钮条必须真的可见 ----------
#
# 用户报告「物种名清洗功能没有开始按钮」。根因不是忘了建按钮（按钮建了也 pack 了），
# 而是 pack 的分配顺序：Tk 的 packer 按 pack 调用的先后分配空间，先调用的先拿到自己
# 请求的高度，排在后面的只能分剩下的。清洗页请求高度 797 px，而默认窗口（1120x780）
# 里笔记本页只有 740 px，于是最后 pack 的按钮条被挤成 1 px——实测四个按钮
# mapped=0 / w=1 / h=1，界面上完全看不到「开始清洗」。本会话此前从未有人眼看过窗口，
# 而其余用例一律用 invoke()，控件不可见也照样通过，所以这套断言是唯一能拦住它的。
# 修法是让底部固定行最先 pack(side="bottom")：被压缩的变成可伸缩的输入框与结果表。

def _tab_index(app, title: str) -> int:
    for index in range(app.notebook.index("end")):
        if app.notebook.tab(index, "text") == title:
            return index
    raise AssertionError(f"未找到标签页：{title}")


def _assert_buttons_are_visible(app, title: str, names: tuple) -> None:
    app.notebook.select(_tab_index(app, title))
    app.update()
    page = app.nametowidget(app.notebook.select())
    if page.winfo_height() < 600:  # pragma: no cover - 小屏/无窗口管理器的兜底
        pytest.skip(f"窗口被系统限制得太小（页面仅 {page.winfo_height()} px）")
    for name in names:
        button = _button(page, name)
        assert button.winfo_ismapped(), f"「{name}」按钮没有显示出来"
        assert button.winfo_height() >= 20, (
            f"「{name}」被挤成 {button.winfo_height()} px 高，用户看不见它")


def test_cleaning_tab_shows_all_of_its_buttons(app):
    """默认窗口尺寸下，清洗页的四个按钮都必须在可视区内。"""
    app.geometry("1120x780")
    app.update()
    _assert_buttons_are_visible(app, "物种名清洗",
                                ("开始清洗", "导出 CSV",
                                 "应用到序列文件", "打开输出文件夹"))


def test_both_new_tabs_keep_their_buttons_at_the_minimum_window_size(app):
    """窗口缩到 App.minsize()（940x660）时按钮条也不得被挤掉。

    清洗页在最小尺寸下曾整条消失；建树页请求高度 680 px > 620 px，同理会一起丢掉
    「生成进化树」「检测 R 环境」「从序列文件导入物种名」。
    """
    app.geometry("940x660")
    app.update()
    try:
        _assert_buttons_are_visible(app, "物种名清洗",
                                    ("开始清洗", "导出 CSV",
                                     "应用到序列文件", "打开输出文件夹"))
        _assert_buttons_are_visible(app, "进化树生成",
                                    ("生成进化树", "检测 R 环境",
                                     "从序列文件导入物种名"))
    finally:                       # 本模块共用一个 App，尺寸必须还原给后续用例
        app.geometry("1120x780")
        app.update()


# ---------- T21：合并 / 转换 ----------

def test_merge_tab_exposes_expected_labels():
    from seq_toolkit.gui import tab_merge
    assert tab_merge.TITLE == "合并 / 转换"
    assert tab_merge.FORMAT_LABELS["auto"] == "自动识别"
    assert set(tab_merge.NAMING_LABELS) == {
        "keep", "accession", "species", "accession_species"}
    assert set(tab_merge.DEDUP_LABELS) == {"accession", "none"}


def test_merge_tab_builds_without_error(app):
    from seq_toolkit.gui import tab_merge
    frame = tab_merge.build(app.notebook.winfo_children()[0], app)
    assert frame is not None


def test_label_to_key_is_reusable_for_other_tabs():
    from seq_toolkit.gui import tab_merge
    for key, text in tab_merge.NAMING_LABELS.items():
        assert tab_merge._label_to_key(tab_merge.NAMING_LABELS, text) == key
    with pytest.raises(KeyError):
        tab_merge._label_to_key(tab_merge.NAMING_LABELS, "不存在的标签")


def test_merge_tab_registers_start_button_as_busy_widget(app):
    """按钮禁用/恢复必须交给 App，标签页不得自行 app.after 恢复。"""
    from seq_toolkit.gui import tab_merge

    before = list(app._busy_widgets)
    frame = _new_tab_frame(app)
    tab_merge.build(frame, app)
    added = [widget for widget in app._busy_widgets if widget not in before]
    assert added, "标签页没有注册任何 busy 控件"
    assert any(isinstance(widget, ttk.Button) and widget.cget("text") == "开始处理"
               for widget in added)


def test_merge_tab_runs_job_end_to_end(app, monkeypatch, tmp_path):
    """真实跑一次合并：验证设置页的后缀名生效、按钮在任务期间保持禁用。"""
    from seq_toolkit.gui import tab_merge

    work = tmp_path / "中文 目录"
    work.mkdir()
    source = work / "样本数据.custom"
    source.write_text(">ON1.1 Salsola pellucida chloroplast, complete genome\n"
                      "ACGTACGTACGT\n", encoding="utf-8")
    target = tmp_path / "合并 输出.fa"

    # 默认后缀表里没有 .custom：只有把 app.settings 的后缀名传进 ProcessPlan，
    # 「设置」页里自定义的后缀名才会被 list_input_files 认出来。
    monkeypatch.setattr(app.settings, "fasta_suffixes", (".custom",))
    monkeypatch.setattr(app.settings, "genbank_suffixes", ())

    frame = _new_tab_frame(app)
    tab_merge.build(frame, app)
    monkeypatch.setattr(tab_merge.filedialog, "askdirectory",
                        lambda **kwargs: str(work))
    _button(frame, "添加文件夹…").invoke()
    _pickers(frame)[0].set_path(str(target))

    start = _button(frame, "开始处理")
    start.invoke()
    # run_job 必须已经禁用按钮；若标签页自己 app.after(200, ...) 提前恢复，
    # 这两行断言在文件多、任务长时会失败。
    assert str(start["state"]) == "disabled"
    _wait_for_job(app)
    assert str(start["state"]) == "normal"

    assert target.exists()
    assert "ON1.1" in target.read_text(encoding="utf-8")
    assert "完成，输出" in app.status_label.cget("text")


# ---------- T22：重命名 / 拆分 ----------

def test_rename_tab_builds_without_error(app):
    from seq_toolkit.gui import tab_rename
    assert tab_rename.TITLE == "重命名 / 拆分"
    frame = tab_rename.build(app.notebook.winfo_children()[1], app)
    assert frame is not None


def test_rename_tab_reuses_naming_labels_from_merge_tab():
    """命名规则只有一份定义：T22 必须复用 T21 的标签表与转换函数。"""
    from seq_toolkit.gui import tab_merge, tab_rename
    assert tab_rename.NAMING_LABELS is tab_merge.NAMING_LABELS
    assert tab_rename._label_to_key is tab_merge._label_to_key


def _prepare_rename_source(tmp_path):
    work = tmp_path / "中文目录"
    work.mkdir()
    source = work / "乱名.fa"
    source.write_text(">ON929859.1 Salsola pellucida chloroplast, complete genome\n"
                      "ACGTACGT\n", encoding="utf-8")
    return work, source


def test_rename_preview_runs_in_background_and_is_dry_run(app, monkeypatch, tmp_path):
    from seq_toolkit.gui import tab_rename

    work, source = _prepare_rename_source(tmp_path)
    frame = _new_tab_frame(app)
    tab_rename.build(frame, app)
    monkeypatch.setattr(tab_rename.filedialog, "askdirectory",
                        lambda **kwargs: str(work))
    _button(frame, "添加文件夹…").invoke()

    seen = {}
    monkeypatch.setattr(tab_rename.messagebox, "showinfo",
                        lambda title, message, **kwargs: seen.update(
                            title=title, message=message))

    preview = _button(frame, "预览改名对照表")
    preview.invoke()
    # 预览要读每个文件的头部，同样必须走后台线程，因此按钮此刻应处于禁用态。
    assert str(preview["state"]) == "disabled"
    _wait_for_job(app)
    assert str(preview["state"]) == "normal"

    assert "ON929859.1_Salsola_pellucida.fa" in seen.get("message", "")
    assert source.exists(), "预览不得改动磁盘文件"
    assert not (work / "ON929859.1_Salsola_pellucida.fa").exists()


def test_rename_tab_renames_disk_file_on_start(app, monkeypatch, tmp_path):
    from seq_toolkit.gui import tab_rename

    work, source = _prepare_rename_source(tmp_path)
    target = tmp_path / "改写 输出.fa"
    frame = _new_tab_frame(app)
    tab_rename.build(frame, app)
    monkeypatch.setattr(tab_rename.filedialog, "askdirectory",
                        lambda **kwargs: str(work))
    _button(frame, "添加文件夹…").invoke()

    pickers = _pickers(frame)
    pickers[0].set_path(str(target))          # 改写后的输出文件
    _checkbutton(frame, "重命名已有磁盘文件").invoke()

    start = _button(frame, "开始处理")
    start.invoke()
    assert str(start["state"]) == "disabled"
    _wait_for_job(app)
    assert str(start["state"]) == "normal"

    assert (work / "ON929859.1_Salsola_pellucida.fa").exists()
    assert not source.exists()
    assert target.exists()


def test_rename_rewrite_path_honours_settings_suffixes_and_wrap(app, monkeypatch, tmp_path):
    """改写路径必须把 app.settings 的后缀名与 wrap 传进 ProcessPlan。

    不传就一直用 ProcessPlan 的默认后缀表：「设置」里自定义的 .myfa 文件在这一页被
    list_input_files 认不出来，于是被当成未知格式静默跳过（用户看到"文件明明在那儿却
    什么也没发生"）；wrap 不传则「FASTA 每行长度」在这一页静默失效。同页的拆分路径
    一直是对的，所以这条只覆盖改写路径。
    """
    from seq_toolkit.gui import tab_rename

    work = tmp_path / "自定义后缀 目录"
    work.mkdir()
    source = work / "样本.myfa"
    source.write_text(">ON929859.1 Salsola pellucida chloroplast, complete genome\n"
                      "ACGTACGTACGTACGTACGTACGT\n", encoding="utf-8")
    target = tmp_path / "改写 输出.fa"

    # 只留自定义后缀：默认表里没有 .myfa，认不认全看有没有把 settings 传下去。
    monkeypatch.setattr(app.settings, "fasta_suffixes", (".myfa",))
    monkeypatch.setattr(app.settings, "genbank_suffixes", ())
    monkeypatch.setattr(app.settings, "wrap", 6)

    frame = _new_tab_frame(app)
    tab_rename.build(frame, app)
    monkeypatch.setattr(tab_rename.filedialog, "askdirectory",
                        lambda **kwargs: str(work))
    _button(frame, "添加文件夹…").invoke()
    _pickers(frame)[0].set_path(str(target))   # 改写后的输出文件（「改写」默认已勾选）

    start = _button(frame, "开始处理")
    start.invoke()
    _wait_for_job(app)

    assert target.exists(), "自定义后缀的输入文件被整批跳过了：settings 没有传进 ProcessPlan"
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ">ON929859.1_Salsola_pellucida"
    # wrap=6 生效：24 个碱基被切成每行 6 个（4 行），而不是整条写在一行。
    assert lines[1:] == ["ACGTAC", "GTACGT", "ACGTAC", "GTACGT"]


def test_rename_split_step_does_not_feed_on_its_own_previous_output(app, monkeypatch,
                                                                    tmp_path):
    """拆分输出目录落在输入文件夹内时，第二次运行既不得自喂、也不得写出 _1 孪生文件。

    这是用户"越跑越多"的直接原因：拆分步骤在改写之后才枚举输入，既不排除本作业刚写出的
    文件、也不排除落在输入目录内的拆分输出目录，于是自己读自己产出的文件。第二次运行
    因此读到 2 条记录，产出从 1 个涨到 3 个。

    自喂被修掉之后还剩最后一个：第二次运行的目标名在磁盘上已存在，按"绝不静默覆盖"让位到
    _1，而那个 _1 与产物**内容完全相同**——用户报告的原始现象仍在。同名且同字节时跳过，
    目录里始终只有那一个文件。
    """
    from seq_toolkit.gui import tab_rename

    work = tmp_path / "样本目录"
    work.mkdir()
    source = work / "样本.fa"
    source.write_text(">ON929859.1 Salsola pellucida chloroplast, complete genome\n"
                      "ACGTACGT\n", encoding="utf-8")
    split_dir = work / "拆分结果"          # 在输入文件夹内部

    frame = _new_tab_frame(app)
    tab_rename.build(frame, app)
    monkeypatch.setattr(tab_rename.filedialog, "askdirectory",
                        lambda **kwargs: str(work))
    _button(frame, "添加文件夹…").invoke()
    _checkbutton(frame, "改写 > 行序列名").invoke()      # 关掉改写，只做拆分
    _checkbutton(frame, "按序列名拆分为单文件").invoke()
    _pickers(frame)[1].set_path(str(split_dir))         # 拆分输出目录

    start = _button(frame, "开始处理")
    start.invoke()
    _wait_for_job(app)
    first_run = sorted(p.name for p in split_dir.iterdir())
    assert first_run == ["ON929859.1_Salsola_pellucida.fasta"]

    app._clear_log()
    start.invoke()
    _wait_for_job(app)

    second_run = sorted(p.name for p in split_dir.iterdir())
    # 1 → 1：第二次运行的产物与磁盘上的那份逐字节相同，跳过即可，不再让位到 _1。
    assert second_run == ["ON929859.1_Salsola_pellucida.fasta"]
    messages = [entry.message for entry in app.log.entries]
    assert not any(message.startswith("去重：") for message in messages), \
        "第二次运行把上一次的拆分产物当成了输入（日志里出现了去重记录）"
    assert any("内容相同" in message for message in messages), \
        "跳过必须留下说明，否则用户只看到「拆分出 0 个文件」而不知为何"
    assert any("拆分输出目录在输入目录内" in message for message in messages), \
        "输出目录落在输入目录内时必须明确告警"
    # 摘要报的是本批记录在 out_dir 里的产物数，不能因为"这次没重写"就报 0 个。
    assert any(message.startswith("拆分出 1 个文件") for message in messages)


def test_rename_split_step_excludes_the_rewrite_product_of_the_same_job(
        app, monkeypatch, tmp_path):
    """改写输出落在输入文件夹内时，拆分不得把本作业刚写出的改写产物当成输入。

    改写产物的 header 是渲染后的名称（>ON929859.1_Salsola_pellucida），回读时登录号
    成了 ON929859.1_SALSOLA_PELLUCIDA，与源文件的 ON929859.1 已不是同一个登录号——
    按登录号去重救不了它，同一条序列仍会被拆成两个文件。
    """
    from seq_toolkit.gui import tab_rename

    work = tmp_path / "样本目录"
    work.mkdir()
    source = work / "样本.fa"
    source.write_text(">ON929859.1 Salsola pellucida chloroplast, complete genome\n"
                      "ACGTACGT\n", encoding="utf-8")
    target = work / "改成规范名.fasta"      # 改写输出落在输入文件夹内
    split_dir = tmp_path / "拆分结果"       # 拆分输出落在输入文件夹外

    frame = _new_tab_frame(app)
    tab_rename.build(frame, app)
    monkeypatch.setattr(tab_rename.filedialog, "askdirectory",
                        lambda **kwargs: str(work))
    _button(frame, "添加文件夹…").invoke()
    _checkbutton(frame, "按序列名拆分为单文件").invoke()   # 改写默认已勾选
    pickers = _pickers(frame)
    pickers[0].set_path(str(target))
    pickers[1].set_path(str(split_dir))

    _button(frame, "开始处理").invoke()
    _wait_for_job(app)

    assert target.exists()
    # 只有源文件参与拆分：本作业刚写出的改写产物不是输入。
    assert sorted(p.name for p in split_dir.iterdir()) == [
        "ON929859.1_Salsola_pellucida.fasta"]


# ---------- 离线 NCBI 假件：T23/T24 的测试一律不得发起真实网络请求 ----------

class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


class _RecordingOpener:
    """与 tests/test_ncbi.py 的 RecordingOpener 同构：按调用顺序返回预设响应。

    把它注入 NcbiClient 之后，标签页里发生的所有"网络请求"都只打到这个假件上，
    测试因此完全离线、且不必等真实限速（sleeper 也被换成空操作）。
    """

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome.encode("utf-8"))

    def endpoints(self) -> list:
        return [urlparse(request.full_url).path.rsplit("/", 1)[-1]
                for request in self.requests]


def _offline_client(opener):
    """把标签页模块里的 NcbiClient 换成注入了假 opener 的实例工厂。

    保留真实 ``_make_client`` 代码路径（照样构造 NcbiClient、传 log/cancel），
    只把 opener 与 sleeper 换成假的。
    """
    def factory(**kwargs):
        return NcbiClient(opener=opener, sleeper=lambda seconds: None, **kwargs)
    return factory


def _esearch_payload(count: int, ids: list) -> str:
    return json.dumps({"esearchresult": {"count": str(count), "idlist": ids,
                                         "webenv": "WE", "querykey": "1"}})


def _esummary_payload(mapping: dict) -> str:
    return json.dumps({"result": mapping})


def _doc(accession: str, length: int = 150000, organism: str = "Salsola pellucida",
         title: str = "Salsola pellucida chloroplast, complete genome",
         date: str = "2022/01/12", sourcedb: str = "GenBank") -> dict:
    return {"accessionversion": accession, "slen": str(length), "organism": organism,
            "title": title, "createdate": date, "sourcedb": sourcedb}


# 一个批次只发一次 efetch，响应里含该批全部序列，故两条记录写在同一个响应里。
GENBANK_ON1_MF2 = (
    "LOCUS       ON1.1                   8 bp    DNA     linear   PLN 01-JAN-2020\n"
    "DEFINITION  Salsola pellucida chloroplast, complete genome.\n"
    "ACCESSION   ON1\n"
    "VERSION     ON1.1\n"
    "  ORGANISM  Salsola pellucida\n"
    "            Eukaryota; Amaranthaceae; Salsola.\n"
    "FEATURES             Location/Qualifiers\n"
    "     CDS             1..8\n"
    '                     /gene="matK"\n'
    "ORIGIN\n"
    "        1 acgtacgt\n"
    "//\n"
    "LOCUS       MF2.1                   8 bp    DNA     linear   PLN 01-JAN-2020\n"
    "DEFINITION  Kochia scoparia chloroplast, complete genome.\n"
    "ACCESSION   MF2\n"
    "VERSION     MF2.1\n"
    "  ORGANISM  Kochia scoparia\n"
    "            Eukaryota; Amaranthaceae; Kochia.\n"
    "ORIGIN\n"
    "        1 ttttgggg\n"
    "//\n"
)


def _labelframe(parent, text: str):
    for widget in _descendants(parent):
        if isinstance(widget, ttk.LabelFrame) and widget.cget("text") == text:
            return widget
    raise AssertionError(f"未找到分组框：{text}")


def _entries(parent) -> list:
    return [widget for widget in _descendants(parent) if isinstance(widget, ttk.Entry)]


def _table(parent):
    for widget in _descendants(parent):
        if isinstance(widget, CheckboxTable):
            return widget
    raise AssertionError("未找到结果表格")


def _warnings(app) -> list:
    return [entry.message for entry in app.log.entries if entry.level == "WARN"]


# ---------- T23：检索与批量下载 ----------

def test_search_tab_builds_without_error(app):
    from seq_toolkit.gui import tab_search
    assert tab_search.TITLE == "检索与批量下载"
    assert tab_search.MAX_DISPLAY_ROWS == 5000
    assert tab_search.RESULT_HEADINGS == ("Accession", "长度", "物种名",
                                          "定义行", "发布日期", "来源")
    frame = tab_search.build(app.notebook.winfo_children()[2], app)
    assert frame is not None


def test_search_tab_registers_all_four_buttons_as_busy_widgets(app):
    from seq_toolkit.gui import tab_search

    before = list(app._busy_widgets)
    frame = _new_tab_frame(app)
    tab_search.build(frame, app)
    added = [widget for widget in app._busy_widgets if widget not in before]
    texts = {widget.cget("text") for widget in added
             if isinstance(widget, ttk.Button)}
    assert {"检索", "下载勾选的序列",
            tab_search.EXPORT_TXT_LABEL, tab_search.EXPORT_CSV_LABEL} <= texts


def _run_search(app, monkeypatch, tmp_path, opener, term="Salsola pellucida"):
    """建一个检索页、填检索词、点检索，等后台任务结束。返回 (frame, opener)。"""
    from seq_toolkit.gui import tab_search

    monkeypatch.setattr(tab_search, "NcbiClient", _offline_client(opener))
    monkeypatch.setattr(app.settings, "email", "tester@example.org")
    frame = _new_tab_frame(app)
    tab_search.build(frame, app)
    _entries(_labelframe(frame, "检索条件"))[0].insert(0, term)
    _button(frame, "检索").invoke()
    _wait_for_job(app)
    return frame, opener


def test_search_tab_searches_and_downloads_offline(app, monkeypatch, tmp_path):
    """检索 + 勾选 + 下载全流程，只打假 opener：验证表格、勾选与落盘产物。"""
    from seq_toolkit.gui import tab_search

    opener = _RecordingOpener([
        _esearch_payload(2, ["1", "2"]),
        _esummary_payload({"uids": ["1", "2"],
                           "1": _doc("ON1.1"),
                           "2": _doc("MF2.1", organism="Kochia scoparia")}),
        GENBANK_ON1_MF2,
    ])
    seen = {}

    frame = _new_tab_frame(app)
    monkeypatch.setattr(tab_search, "NcbiClient", _offline_client(opener))
    monkeypatch.setattr(app.settings, "email", "tester@example.org")
    monkeypatch.setattr(tab_search.messagebox, "showinfo",
                        lambda title, message, **kwargs: seen.update(
                            title=title, message=message))
    tab_search.build(frame, app)
    _entries(_labelframe(frame, "检索条件"))[0].insert(0, "Salsola pellucida")
    _pickers(frame)[0].set_path(str(tmp_path))

    search = _button(frame, "检索")
    search.invoke()
    assert str(search["state"]) == "disabled"
    _wait_for_job(app)
    assert str(search["state"]) == "normal"

    table = _table(frame)
    assert table.selection.total() == 2
    assert table.selection.count() == 0

    _button(frame, "全选").invoke()
    assert table.selection.count() == 2

    download = _button(frame, "下载勾选的序列")
    download.invoke()
    assert str(download["state"]) == "disabled"
    _wait_for_job(app)
    assert str(download["state"]) == "normal"

    assert opener.endpoints() == ["esearch.fcgi", "esummary.fcgi", "efetch.fcgi"]
    assert (tmp_path / "ON1.1.gb").exists()
    assert (tmp_path / "MF2.1.fasta").exists()
    assert (tmp_path / "all_sequences.fasta").exists()
    assert seen["title"] == "下载完成"
    assert "输出目录" in seen["message"]


def test_search_tab_deduplicates_accessions_before_set_rows(app, monkeypatch, tmp_path):
    """重复登录号必须先去掉：表格以 accession 作行 iid，重复会让 Tcl 建表失败。"""
    opener = _RecordingOpener([
        _esearch_payload(2, ["1", "2"]),
        _esummary_payload({"uids": ["1", "2"],
                           "1": _doc("ON1.1"),
                           "2": _doc("ON1.1")}),
    ])
    frame, _opener = _run_search(app, monkeypatch, tmp_path, opener)
    assert _table(frame).selection.total() == 1
    assert any("重复" in message for message in _warnings(app))


# ---------- 用户使用后提出的改进 3：批量导出登录号（.txt / .csv） ----------
#
# 一律 monkeypatch filedialog.asksaveasfilename 指到 tmp_path：绝不弹真实对话框。
# 用 monkeypatch.setattr(tab_search.filedialog, ...) 是因为 tab_search 内是
# `from tkinter import filedialog`，改到模块属性上的补丁会被 pytest 自动还原。


def _three_doc_opener():
    """3 条命中。长度都落在检索条件默认区间 100000–200000 内，否则会被本地筛掉。"""
    return _RecordingOpener([
        _esearch_payload(3, ["1", "2", "3"]),
        _esummary_payload({
            "uids": ["1", "2", "3"],
            "1": _doc("ON1.1"),
            "2": _doc("MF2.1", length=120000, organism="Kochia scoparia",
                      title="Kochia scoparia chloroplast, complete genome"),
            "3": _doc("ON3.1", length=160000, organism="Salsola heptapotamica",
                      title="Salsola heptapotamica chloroplast, complete genome"),
        }),
    ])


def _search_only(app, monkeypatch, opener):
    """检索一次并返回 frame（不下载）。"""
    from seq_toolkit.gui import tab_search

    monkeypatch.setattr(tab_search, "NcbiClient", _offline_client(opener))
    monkeypatch.setattr(app.settings, "email", "tester@example.org")
    frame = _new_tab_frame(app)
    tab_search.build(frame, app)
    _entries(_labelframe(frame, "检索条件"))[0].insert(0, "Salsola")
    _button(frame, "检索").invoke()
    _wait_for_job(app)
    return frame


def _patch_save_dialog(monkeypatch, target: str):
    """把另存为对话框指到 target；返回记录调用次数的列表。"""
    from seq_toolkit.gui import tab_search

    calls: list = []
    monkeypatch.setattr(tab_search.filedialog, "asksaveasfilename",
                        lambda **kwargs: (calls.append(kwargs), target)[1])
    return calls


def _log_messages(app) -> list:
    return [entry.message for entry in app.log.entries]


def test_search_tab_exports_checked_accessions_as_txt(app, monkeypatch, tmp_path):
    """勾选 2 条 → .txt 内容恰为那 2 个登录号，一行一个、顺序与表格一致。"""
    from seq_toolkit.gui import tab_search

    assert tab_search.EXPORT_TXT_LABEL == "导出登录号 .txt…"
    assert tab_search.EXPORT_CSV_LABEL == "导出登录号 .csv…"

    frame = _search_only(app, monkeypatch, _three_doc_opener())
    table = _table(frame)
    assert table.selection.total() == 3

    target = tmp_path / "登录号.txt"
    _patch_save_dialog(monkeypatch, str(target))
    table.selection.check("ON1.1")
    table.selection.check("ON3.1")          # 故意跳过中间那条，验证顺序按其出现位置
    table.refresh_checks()

    _button(frame, tab_search.EXPORT_TXT_LABEL).invoke()

    assert target.read_text(encoding="utf-8") == "ON1.1\nON3.1\n"
    # .txt 不带 BOM，且换行是 \n（项目约定的输出编码）
    assert not target.read_bytes().startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in target.read_bytes()
    assert any(str(target) in message and "2" in message
               for message in _log_messages(app))


def test_search_tab_export_without_selection_exports_all_rows_and_says_so(
        app, monkeypatch, tmp_path):
    """未勾选 → 导出表格显示的全部 N 条，并在日志里写明"未勾选"，不让用户误会。"""
    from seq_toolkit.gui import tab_search

    frame = _search_only(app, monkeypatch, _three_doc_opener())
    target = tmp_path / "全部.txt"
    _patch_save_dialog(monkeypatch, str(target))

    _button(frame, tab_search.EXPORT_TXT_LABEL).invoke()

    assert target.read_text(encoding="utf-8") == "ON1.1\nMF2.1\nON3.1\n"
    assert any("未勾选" in message and "3" in message
               for message in _log_messages(app))


def test_search_tab_export_csv_has_header_and_columns_aligned(app, monkeypatch,
                                                              tmp_path):
    """CSV 首行表头、次行起列与内容对应：这个页面刚修过一次列错位，必须钉死。"""
    import csv

    from seq_toolkit.gui import tab_search

    frame = _search_only(app, monkeypatch, _three_doc_opener())
    target = tmp_path / "登录号.csv"
    _patch_save_dialog(monkeypatch, str(target))

    _button(frame, tab_search.EXPORT_CSV_LABEL).invoke()

    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")          # utf-8-sig：Excel 打开中文不乱码
    with target.open("rt", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == list(tab_search.RESULT_HEADINGS)
    assert rows[0] == ["Accession", "长度", "物种名", "定义行", "发布日期", "来源"]
    assert rows[1] == ["ON1.1", "150,000", "Salsola pellucida",
                       "Salsola pellucida chloroplast, complete genome",
                       "2022/01/12", "GenBank"]
    assert rows[2][0] == "MF2.1" and rows[2][2] == "Kochia scoparia"
    assert rows[2][1] == "120,000"                 # 长度列也是表格里那一版（带千分位）
    assert rows[3] == ["ON3.1", "160,000", "Salsola heptapotamica",
                       "Salsola heptapotamica chloroplast, complete genome",
                       "2022/01/12", "GenBank"]
    assert len(rows) == 4                          # 表头 + 3 条


def test_search_tab_export_warns_and_writes_nothing_when_table_is_empty(
        app, monkeypatch, tmp_path):
    """表格为空 → WARN 提示，连另存对话框都不弹、不写文件。"""
    from seq_toolkit.gui import tab_search

    frame = _new_tab_frame(app)
    tab_search.build(frame, app)
    target = tmp_path / "不该出现.txt"
    calls = _patch_save_dialog(monkeypatch, str(target))

    for label in (tab_search.EXPORT_TXT_LABEL, tab_search.EXPORT_CSV_LABEL):
        _button(frame, label).invoke()

    assert calls == []                             # 没内容就不该弹对话框
    assert list(tmp_path.iterdir()) == []
    assert any("空" in message for message in _warnings(app))


def test_search_tab_export_does_nothing_when_dialog_is_cancelled(app, monkeypatch,
                                                                tmp_path):
    """取消另存对话框 → 什么都不做：不写文件、不记"已导出"。"""
    from seq_toolkit.gui import tab_search

    frame = _search_only(app, monkeypatch, _three_doc_opener())
    target = tmp_path / "取消.txt"
    _patch_save_dialog(monkeypatch, "")            # 用户点了取消

    _button(frame, tab_search.EXPORT_TXT_LABEL).invoke()

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []
    assert not any("已导出" in message for message in _log_messages(app))


def test_search_tab_export_reports_oserror_without_crashing(app, monkeypatch,
                                                            tmp_path):
    """写出失败（磁盘满、路径被占用）只能记 ERROR，不得让异常穿过 Tk 回调。"""
    from seq_toolkit.gui import tab_search

    frame = _search_only(app, monkeypatch, _three_doc_opener())
    locked = tmp_path / "被占用的文件.txt"
    locked.write_text("占位", encoding="utf-8")
    _patch_save_dialog(monkeypatch, str(locked / "子路径.txt"))   # 父路径是文件 ⇒ 必然失败

    _button(frame, tab_search.EXPORT_TXT_LABEL).invoke()

    assert locked.is_file()
    assert any(entry.level == "ERROR" and "导出" in entry.message
               for entry in app.log.entries)


def test_write_accessions_txt_uses_utf8_and_lf(tmp_path):
    """模块级写出函数：utf-8（无 BOM）+ newline="\\n"，与项目输出约定一致。"""
    from seq_toolkit.gui.tab_search import write_accessions_txt

    target = tmp_path / "中文名.txt"
    write_accessions_txt(str(target), [("ON1.1",), ("样本甲",)])

    assert target.read_bytes() == "ON1.1\n样本甲\n".encode("utf-8")


def test_write_accessions_csv_keeps_column_order(tmp_path):
    """模块级写出函数：列顺序严格等于 RESULT_HEADINGS 的顺序，不做任何重排。"""
    import csv

    from seq_toolkit.gui.tab_search import RESULT_HEADINGS, write_accessions_csv

    target = tmp_path / "表.csv"
    write_accessions_csv(str(target), [("ON1.1", "8", "Salsola pellucida",
                                        "定义", "2022/01/12", "GenBank")])

    with target.open("rt", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows == [list(RESULT_HEADINGS),
                    ["ON1.1", "8", "Salsola pellucida", "定义",
                     "2022/01/12", "GenBank"]]


def test_search_truncation_notice_is_actionable():
    """命中数超过本次取回元数据的条数时必须显式提示，并给出可操作的建议。"""
    from seq_toolkit.gui import tab_search

    result = tab_search.SearchResult(query="Salsola[Organism]", total=1200,
                                     ids=[str(index) for index in range(500)])
    notice = tab_search.truncation_notice(result, [object()] * 500)
    assert "1200" in notice and "500" in notice
    assert "不是全部" in notice                 # 明确说明这不是全部命中
    assert "序列长度" in notice and "只要完整基因组" in notice   # 可操作的缩小范围手段


def test_search_truncation_notice_is_empty_when_nothing_was_dropped():
    """本地筛选只是过滤掉若干条时不算截断，不得弹出误导性的"结果被截断"。"""
    from seq_toolkit.gui import tab_search

    result = tab_search.SearchResult(query="q", total=3, ids=["1", "2", "3"])
    assert tab_search.truncation_notice(result, [object()]) == ""


def test_search_tab_warns_when_ncbi_truncated_the_result(app, monkeypatch, tmp_path):
    """按属名检索命中 1200 条、只取回前 500 条元数据时，界面必须提示被截断。"""
    opener = _RecordingOpener([
        _esearch_payload(1200, [str(index) for index in range(500)]),
        _esummary_payload({"uids": ["0"], "0": _doc("ON1.1")}),
    ])
    _run_search(app, monkeypatch, tmp_path, opener, term="Salsola")

    truncated = [message for message in _warnings(app) if "1200" in message]
    assert truncated, f"没有给出截断提示，实际告警：{_warnings(app)}"
    assert any("500" in message for message in truncated)
    assert any("截断" in message for message in truncated)
    assert any("序列长度" in message for message in truncated)


# ---------- T24：按登录号下载 ----------

def _text_widget(parent):
    for widget in _descendants(parent):
        if isinstance(widget, tk.Text):
            return widget
    raise AssertionError("未找到文本输入框")


def test_accession_tab_builds_without_error(app):
    from seq_toolkit.gui import tab_accession
    assert tab_accession.TITLE == "按登录号下载"
    frame = tab_accession.build(app.notebook.winfo_children()[3], app)
    assert frame is not None


def test_accession_tab_registers_start_button_as_busy_widget(app):
    from seq_toolkit.gui import tab_accession

    before = list(app._busy_widgets)
    frame = _new_tab_frame(app)
    tab_accession.build(frame, app)
    added = [widget for widget in app._busy_widgets if widget not in before]
    assert any(isinstance(widget, ttk.Button) and widget.cget("text") == "开始下载"
               for widget in added)


def test_accession_tab_reuses_naming_labels_from_merge_tab():
    from seq_toolkit.gui import tab_accession, tab_merge
    assert tab_accession.NAMING_LABELS is tab_merge.NAMING_LABELS
    assert tab_accession._label_to_key is tab_merge._label_to_key


def test_accession_tab_downloads_pasted_accessions_offline(app, monkeypatch, tmp_path):
    from seq_toolkit.gui import tab_accession

    opener = _RecordingOpener([GENBANK_ON1_MF2])
    seen = {}
    monkeypatch.setattr(tab_accession, "NcbiClient", _offline_client(opener))
    monkeypatch.setattr(app.settings, "email", "tester@example.org")
    monkeypatch.setattr(tab_accession.messagebox, "showinfo",
                        lambda title, message, **kwargs: seen.update(
                            title=title, message=message))

    frame = _new_tab_frame(app)
    tab_accession.build(frame, app)
    _text_widget(frame).insert("1.0", "on1.1\nMF2.1, on1.1")   # 含重复与大小写混杂
    _pickers(frame)[0].set_path(str(tmp_path))

    start = _button(frame, "开始下载")
    start.invoke()
    assert str(start["state"]) == "disabled"
    _wait_for_job(app)
    assert str(start["state"]) == "normal"

    assert opener.endpoints() == ["efetch.fcgi"]
    # efetch 的 id 参数必须已去重（on1.1 只请求一次），否则会白下载一遍
    assert opener.requests[0].data.decode("utf-8").count("ON1.1") == 1
    assert (tmp_path / "ON1.1.gb").exists()
    assert (tmp_path / "MF2.1.fasta").exists()
    assert seen["title"] == "下载完成"
    assert "计数单位为登录号" in seen["message"]
    assert "输出目录" in seen["message"]


def test_accession_tab_extracts_accessions_from_sequence_files(app, monkeypatch, tmp_path):
    """「从序列文件提取…」必须把文件里的登录号填进文本框（去重、大写）。"""
    from seq_toolkit.gui import tab_accession

    fasta = tmp_path / "样本.fa"
    fasta.write_text(">on1.1 Salsola pellucida\nACGT\n", encoding="utf-8")
    genbank = tmp_path / "样本.gb"
    genbank.write_text(GENBANK_ON1_MF2, encoding="utf-8")

    frame = _new_tab_frame(app)
    tab_accession.build(frame, app)
    monkeypatch.setattr(tab_accession.filedialog, "askopenfilenames",
                        lambda **kwargs: (str(fasta), str(genbank)))
    _button(frame, "从序列文件提取…").invoke()

    assert _text_widget(frame).get("1.0", "end").split() == ["ON1.1", "MF2.1"]
    assert any("2 个登录号" in entry.message for entry in app.log.entries)


def test_accession_tab_warns_when_nothing_to_download(app, monkeypatch, tmp_path):
    from seq_toolkit.gui import tab_accession

    frame = _new_tab_frame(app)
    tab_accession.build(frame, app)
    _text_widget(frame).insert("1.0", "  ,, \n")
    _pickers(frame)[0].set_path(str(tmp_path))
    _button(frame, "开始下载").invoke()

    assert not app.worker.is_running(), "空输入不得启动后台任务"
    assert any("登录号" in message for message in _warnings(app))


# ---------- T25：设置 ----------

def _radiobutton(parent, text: str):
    for widget in _descendants(parent):
        if isinstance(widget, ttk.Radiobutton) and widget.cget("text") == text:
            return widget
    raise AssertionError(f"未找到单选框：{text}")


def _temporary_settings_path(monkeypatch, tmp_path):
    """把配置路径改到临时目录——绝不能读写用户真实的 %APPDATA%/seq_toolkit。"""
    import seq_toolkit.settings as settings_module
    monkeypatch.setattr(settings_module, "settings_path",
                        lambda: str(tmp_path / "settings.json"))
    return tmp_path / "settings.json"


_SNAPSHOT_FIELDS = ("email", "api_key", "proxy", "output_dir", "wrap",
                    "force_redownload", "fasta_suffixes", "genbank_suffixes")


def _snapshot_settings(monkeypatch, app):
    """把 app.settings 的字段纳入 monkeypatch 的还原范围。

    「保存设置」会整体覆写这些字段，而本模块的 App 是模块级共享的：不还原就会把
    邮箱、后缀名等泄漏给后续用例（它们看起来"莫名其妙地失败"）。
    """
    for name in _SNAPSHOT_FIELDS:
        monkeypatch.setattr(app.settings, name, getattr(app.settings, name))


def test_split_and_join_suffixes_round_trip():
    from seq_toolkit.gui.tab_settings import join_suffixes, split_suffixes
    assert split_suffixes(".fa, .fasta .fna") == (".fa", ".fasta", ".fna")
    assert split_suffixes("") == ()
    assert join_suffixes((".fa", ".fna")) == ".fa, .fna"


def test_split_suffixes_adds_missing_leading_dot():
    """用户写成 "fa fna"（漏点）时必须自动补上，否则文件永远匹配不上。"""
    from seq_toolkit.gui.tab_settings import split_suffixes
    assert split_suffixes("fa;fna") == (".fa", ".fna")


def test_settings_tab_builds_and_saves(app, tmp_path, monkeypatch):
    from seq_toolkit.gui import tab_settings
    target = _temporary_settings_path(monkeypatch, tmp_path)
    _snapshot_settings(monkeypatch, app)
    assert tab_settings.TITLE == "设置"
    frame = tab_settings.build(app.notebook.winfo_children()[4], app)
    assert frame is not None
    app.settings.email = "tester@example.org"
    app.save_settings()
    assert app.log.entries[-1].message.startswith("设置已保存")
    assert target.exists()


def test_settings_tab_registers_save_button_as_busy_widget(app):
    from seq_toolkit.gui import tab_settings

    before = list(app._busy_widgets)
    frame = _new_tab_frame(app)
    tab_settings.build(frame, app)
    added = [widget for widget in app._busy_widgets if widget not in before]
    assert any(isinstance(widget, ttk.Button) and widget.cget("text") == "保存设置"
               for widget in added)


def test_settings_tab_save_writes_widget_values_into_settings(app, monkeypatch, tmp_path):
    """点「保存设置」必须把界面上看到的值真正写进 app.settings 并落盘。

    这条同时钉住"Tk 变量必须带 master"：变量若挂到别的 Tcl 解释器上，输入框里文字
    看得见、get() 却是旧值，保存下来的仍是旧配置。
    """
    from seq_toolkit.gui import tab_settings

    target = _temporary_settings_path(monkeypatch, tmp_path)
    _snapshot_settings(monkeypatch, app)
    monkeypatch.setattr(tab_settings.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(tab_settings.messagebox, "showwarning", lambda *a, **k: None)

    frame = _new_tab_frame(app)
    tab_settings.build(frame, app)

    email, api_key, proxy = _entries(_labelframe(frame, "NCBI 访问设置"))
    for widget, value in ((email, " lab@example.org "),
                          (api_key, "KEY123"),
                          (proxy, "http://127.0.0.1:7890")):
        widget.delete(0, "end")
        widget.insert(0, value)

    files_box = _labelframe(frame, "文件处理偏好")
    out_dir, fasta_suffixes, genbank_suffixes = _entries(files_box)
    out_dir.delete(0, "end"); out_dir.insert(0, str(tmp_path / "输出 目录"))
    fasta_suffixes.delete(0, "end"); fasta_suffixes.insert(0, "fa fna")
    genbank_suffixes.delete(0, "end"); genbank_suffixes.insert(0, ".gb, .gbk")
    _radiobutton(files_box, "70").invoke()
    _checkbutton(frame, "强制重新下载（默认跳过已存在的文件）").invoke()

    _button(frame, "保存设置").invoke()

    assert app.settings.email == "lab@example.org"
    assert app.settings.api_key == "KEY123"
    assert app.settings.proxy == "http://127.0.0.1:7890"
    assert app.settings.output_dir == str(tmp_path / "输出 目录")
    assert app.settings.fasta_suffixes == (".fa", ".fna")
    assert app.settings.genbank_suffixes == (".gb", ".gbk")
    assert app.settings.wrap == 70
    assert app.settings.force_redownload is True
    assert target.exists()
    assert app.log.entries[-1].message.startswith("设置已保存")


def test_settings_tab_warns_when_email_is_missing(app, monkeypatch, tmp_path):
    """邮箱是 NCBI 的硬性合规要求：空着保存必须弹警告，但仍要落盘其余设置。"""
    from seq_toolkit.gui import tab_settings

    target = _temporary_settings_path(monkeypatch, tmp_path)
    _snapshot_settings(monkeypatch, app)
    warned = []
    monkeypatch.setattr(tab_settings.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(tab_settings.messagebox, "showwarning",
                        lambda title, message, **kwargs: warned.append(message))

    frame = _new_tab_frame(app)
    tab_settings.build(frame, app)
    email = _entries(_labelframe(frame, "NCBI 访问设置"))[0]
    email.delete(0, "end")
    _button(frame, "保存设置").invoke()

    assert warned and "邮箱" in warned[0]
    assert app.settings.email == ""
    assert target.exists()


# ---------- T21 用户使用后新增：每个输入文件各输出一个文件 ----------
#
# 用户的抱怨是「无论如何输出的只有一个合并的 fasta 文件」。这里钉住输出方式单选：
# 切到「每个输入文件各输出一个文件」后选择器必须变成**目录**选择（含「浏览…」真的
# 打开目录对话框），校验与产物都随之变化；切回去则一切恢复原样。

def _output_mode_radio(frame, mode: str):
    from seq_toolkit.gui import tab_merge
    return _radiobutton(frame, tab_merge.OUTPUT_MODE_LABELS[mode])


def _patch_inputs_dialog(monkeypatch, paths):
    """把「添加文件…」的对话框指到给定文件；绝不弹真实对话框。"""
    from seq_toolkit.gui import tab_merge

    monkeypatch.setattr(tab_merge.filedialog, "askopenfilenames",
                        lambda **kwargs: tuple(str(path) for path in paths))


def _patch_browse(monkeypatch, kind: str, answer: str):
    """把 FilePicker 的某类对话框换成记录调用参数的假件。返回调用记录列表。"""
    from seq_toolkit.gui import widgets

    calls: list = []
    monkeypatch.setattr(widgets.filedialog, kind,
                        lambda **kwargs: (calls.append(kwargs), answer)[1])
    return calls


_GUI_GENBANK_A = (
    "LOCUS       ON929859.1              8 bp    DNA     linear   PLN 01-JAN-2020\n"
    "DEFINITION  Salsola pellucida chloroplast, complete genome.\n"
    "ACCESSION   ON929859\n"
    "VERSION     ON929859.1\n"
    "  ORGANISM  Salsola pellucida\n"
    "ORIGIN\n"
    "        1 acgtacgt\n"
    "//\n"
)
_GUI_GENBANK_B = (
    "LOCUS       MF230595.1              8 bp    DNA     linear   PLN 01-JAN-2020\n"
    "DEFINITION  Kochia scoparia chloroplast, complete genome.\n"
    "ACCESSION   MF230595\n"
    "VERSION     MF230595.1\n"
    "  ORGANISM  Kochia scoparia\n"
    "ORIGIN\n"
    "        1 ttttgggg\n"
    "//\n"
)


def test_merge_tab_output_mode_radio_switches_picker_to_directory(app, monkeypatch,
                                                                  tmp_path):
    """切到批量模式：选择器进入目录模式，「浏览…」真的打开目录对话框。"""
    from seq_toolkit.gui import tab_merge

    frame = _new_tab_frame(app)
    tab_merge.build(frame, app)
    picker = _pickers(frame)[0]
    assert picker.mode == "save"

    _output_mode_radio(frame, "per_file").invoke()
    assert picker.mode == "directory"
    assert picker.title == "输出目录"

    chosen = tmp_path / "输出 目录"
    chosen.mkdir()
    save_calls = _patch_browse(monkeypatch, "asksaveasfilename", str(tmp_path / "不该出现"))
    dir_calls = _patch_browse(monkeypatch, "askdirectory", str(chosen))
    _button(picker, "浏览…").invoke()

    assert dir_calls and dir_calls[0]["title"] == "输出目录"
    assert save_calls == [], "目录模式下点「浏览…」不得打开另存为对话框"
    assert picker.path() == str(chosen)


def test_merge_tab_per_file_mode_requires_an_output_directory(app, monkeypatch, tmp_path):
    """批量模式下校验要求目录非空：空着点开始必须只记 WARN、不起后台任务。"""
    from seq_toolkit.gui import tab_merge

    source = tmp_path / "样本.gbk"
    source.write_text(_GUI_GENBANK_A, encoding="utf-8")

    frame = _new_tab_frame(app)
    tab_merge.build(frame, app)
    _patch_inputs_dialog(monkeypatch, [source])
    _button(frame, "添加文件…").invoke()
    _output_mode_radio(frame, "per_file").invoke()

    _button(frame, "开始处理").invoke()

    assert not app.worker.is_running(), "没指定输出目录就启动了后台任务"
    assert any("输出目录" in message for message in _warnings(app))


def test_merge_tab_converts_each_input_file_into_the_output_directory(app, monkeypatch,
                                                                     tmp_path):
    """端到端：2 个 GenBank 输入 → 目录里 2 个 .fasta，文件名沿用各自主干。"""
    from seq_toolkit.gui import tab_merge

    first = tmp_path / "样本甲.gbk"
    second = tmp_path / "样本乙.gb.gz"
    first.write_text(_GUI_GENBANK_A, encoding="utf-8")
    import gzip
    with gzip.open(str(second), "wt", encoding="utf-8") as handle:
        handle.write(_GUI_GENBANK_B)
    out_dir = tmp_path / "批量 输出"

    frame = _new_tab_frame(app)
    tab_merge.build(frame, app)
    _patch_inputs_dialog(monkeypatch, [first, second])
    _button(frame, "添加文件…").invoke()
    _output_mode_radio(frame, "per_file").invoke()
    _pickers(frame)[0].set_path(str(out_dir))

    start = _button(frame, "开始处理")
    start.invoke()
    assert str(start["state"]) == "disabled"
    _wait_for_job(app)
    assert str(start["state"]) == "normal"

    assert sorted(p.name for p in out_dir.iterdir()) == ["样本乙.fasta", "样本甲.fasta"]
    assert ">ON929859.1" in (out_dir / "样本甲.fasta").read_text(encoding="utf-8")
    assert ">MF230595.1" in (out_dir / "样本乙.fasta").read_text(encoding="utf-8")
    status = app.status_label.cget("text")
    assert "2 个文件" in status and str(out_dir) in status


def test_merge_tab_restores_single_file_mode_when_switched_back(app, monkeypatch,
                                                                tmp_path):
    """切回「合并为单个文件」：选择器与产物都恢复原来的单文件行为。"""
    from seq_toolkit.gui import tab_merge

    work = tmp_path / "输入目录"
    work.mkdir()
    (work / "样本甲.gbk").write_text(_GUI_GENBANK_A, encoding="utf-8")
    (work / "样本乙.gbk").write_text(_GUI_GENBANK_B, encoding="utf-8")
    target = tmp_path / "合并输出.fasta"

    frame = _new_tab_frame(app)
    tab_merge.build(frame, app)
    monkeypatch.setattr(tab_merge.filedialog, "askdirectory",
                        lambda **kwargs: str(work))
    _button(frame, "添加文件夹…").invoke()

    _output_mode_radio(frame, "per_file").invoke()
    _output_mode_radio(frame, "merge").invoke()
    picker = _pickers(frame)[0]
    assert picker.mode == "save"
    assert picker.title == "选择输出文件"

    # 恢复成单文件模式后空着输出文件同样要被拦下（校验也回到原来的口径）
    _button(frame, "开始处理").invoke()
    assert not app.worker.is_running()
    assert any("输出文件" in message for message in _warnings(app))

    picker.set_path(str(target))
    _button(frame, "开始处理").invoke()
    _wait_for_job(app)

    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["合并输出.fasta"]
    text = target.read_text(encoding="utf-8")
    assert ">ON929859.1" in text and ">MF230595.1" in text


def test_merge_tab_registers_output_mode_radios_as_busy_widgets(app):
    """两个输出方式单选也要随任务禁用/恢复（与同页其他控件一致）。"""
    from seq_toolkit.gui import tab_merge

    before = list(app._busy_widgets)
    frame = _new_tab_frame(app)
    tab_merge.build(frame, app)
    added = [widget for widget in app._busy_widgets if widget not in before]
    texts = {widget.cget("text") for widget in added
             if isinstance(widget, ttk.Radiobutton)}
    assert set(tab_merge.OUTPUT_MODE_LABELS.values()) <= texts


def test_settings_has_external_dependency_section(app, monkeypatch):
    """设置页必须能配置 Rscript 路径，并提供检测与可复制的安装指引。

    **不要用 ``cget("textvariable")`` 去找输入框**：它返回的是 Tcl 变量名
    （如 ``PY_VAR3``），不是 Python 里的标识符，按名字匹配永远找不到。
    这里改为验证区块存在 + 检测按钮真的会跑检测流程（用替身注入结果）。
    """
    import seq_toolkit.gui.tab_settings as tab_settings
    from seq_toolkit.phylo import REnvironment

    tab = app.nametowidget(app.notebook.tabs()[4])
    buttons = [w.cget("text") for w in _descendants(tab) if isinstance(w, ttk.Button)]
    assert "检测 R 环境" in buttons
    assert "复制安装指引" in buttons

    labels = [w.cget("text") for w in _descendants(tab) if isinstance(w, ttk.Label)]
    assert any("Rscript 路径" in text for text in labels)

    monkeypatch.setattr(tab_settings, "_detect_environment",
                        lambda path: REnvironment("Rscript.exe", "4.6.1", True, "就绪"))
    _button(tab, "检测 R 环境").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()
    assert any("就绪" in entry.message for entry in app.log.entries)
