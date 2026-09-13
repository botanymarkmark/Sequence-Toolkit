"""「进化树生成」标签页与树形预览控件的测试。"""

import contextlib
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

    与 ``tests/test_gui_tab_tnrs.py`` 的同名夹具同一理由：本模块的 App 是**模块级共享**
    的，而 B5 起 ``build()`` 会把「从序列文件导入物种名 / 检测 R 环境 / 生成进化树」
    登记进 ``app._busy_widgets``，每个用例又各自建 frame、结尾 destroy 它。已销毁的控件
    留在登记表里之后，任何一次 ``run_job`` 逐个 ``configure(state="disabled")`` 都会抛
    TclError——异常被 Tk 回调吞掉（只在 stderr 打一行 traceback），现象是"点了生成按钮
    任务没起、预览画布空着"，排查时毫无线索。这里保证登记表里始终只有活着的控件。
    """

    def prune() -> None:
        app._busy_widgets[:] = [widget for widget in app._busy_widgets
                                if widget.winfo_exists()]

    prune()
    yield
    prune()
    # 还要在主线程上主动回收一次：用例结尾 destroy 掉 frame 之后，页里的 tk.StringVar
    # 就成了垃圾，而 tkinter.Variable.__del__ 是要调 Tcl 的。这堆垃圾若一直留到后台任务
    # 线程分配对象时才触发 GC，__del__ 就会在工作线程里跑，与工作线程自己的 Tcl 调用
    # 撞上（A7/A8 实测：两边互相等，任务静默卡死）。
    gc.collect()


def _descendants(widget) -> list:
    found = []
    for child in widget.winfo_children():
        found.append(child)
        found.extend(_descendants(child))
    return found


@contextlib.contextmanager
def _tree_canvas_window(app, geometry: str = "900x600"):
    """在**真实 Tk 窗口**里装一个 TreeCanvas，返回 ``(window, canvas)``。

    必须另开 Toplevel 而不是往共享 App 上挂控件：App 的主 Notebook 带了
    ``expand=True``，把整个窗口高度吃光，之后 pack 进去的控件高度为 0、不被映射，
    ``winfo_width()`` 就永远是 1——连"可见尺寸"这条被测路径都走不到。
    """
    import tkinter as tk
    from seq_toolkit.gui.tree_canvas import TreeCanvas

    window = tk.Toplevel(app)
    window.geometry(geometry)
    canvas = TreeCanvas(window)
    canvas.pack(fill="both", expand=True)
    app.update()
    try:
        yield window, canvas
    finally:
        window.destroy()
        app.update()


def _star_tree(leaves: int) -> str:
    """``leaves`` 个叶节点的星形树（Newick 文本）。"""
    return f"({','.join(f'L{i}' for i in range(leaves))});"


def _caterpillar_tree(leaves: int) -> str:
    """``leaves`` 个叶节点的毛毛虫树：每层只分出一片叶子，嵌套深度 = 叶数。"""
    text = "L0"
    for index in range(1, leaves):
        text = f"({text},L{index})"
    return text + ";"


def test_tree_canvas_draws_nodes_and_fits(app):
    from seq_toolkit.gui.tree_canvas import TreeCanvas
    from seq_toolkit.phylo import parse_newick
    canvas = TreeCanvas(app)
    canvas.pack()
    canvas.set_tree(parse_newick("((A:1,B:2)Inner:0.5,C:3)Root;"))
    assert canvas.item_count() > 0
    canvas.fit()
    canvas.zoom(1.5)
    canvas.zoom(0.5)
    canvas.set_tree(None)
    assert canvas.item_count() == 0
    canvas.destroy()


def test_tree_canvas_culls_off_screen_nodes(app):
    """大树的绘制量必须随视口收敛，不能为每个节点都建 item。

    计数方式是自证的：先缩到 0.05 倍让整棵树都进视口，数出"不裁剪时会建多少 item"，
    再回到 1:1 只让竖着的前十几个叶节点进视口，两次数值必须差一个数量级。
    只断言 ``full > 0 and fitted > 0``（旧版）把裁剪整段删掉照样绿。
    """
    from seq_toolkit.gui.tree_canvas import TreeCanvas
    from seq_toolkit.phylo import parse_newick

    with _tree_canvas_window(app, "320x240") as (_window, canvas):
        assert isinstance(canvas, TreeCanvas)
        canvas.set_tree(parse_newick(_star_tree(200)))
        # 缩到 0.05 倍：200 个叶节点全在视口内（标签因缩放过小不画，只剩 400 条折线）
        canvas._scale = 0.05
        canvas._offset = [20.0, 20.0]
        canvas._draw()
        everything = canvas.item_count()
        assert everything >= 380, f"整棵树应全部入画，实得 {everything}"

        # 回到 1:1 并把画布拉到左上角：只有前十几个叶节点落在 320x240 里
        canvas._scale = 1.0
        canvas._offset = [20.0, 20.0]
        canvas._draw()
        visible = canvas.item_count()
        assert visible < everything / 4, \
            f"裁剪没生效：视口内 {visible} 项 vs 全树 {everything} 项"

        # 平移到树底，另外十几个叶节点进视口：两次加起来仍远小于全树
        canvas._offset = [20.0, -3500.0]
        canvas._draw()
        bottom = canvas.item_count()
        assert bottom < everything / 4, \
            f"裁剪没生效：视口内 {bottom} 项 vs 全树 {everything} 项"
        assert visible + bottom < everything, "两段视口之和不可能超过整棵树"


def _hidden_page_canvas(app, tree: str, *, leaf_gap: float):
    """在一个**未被选中**的 Notebook 页里建 TreeCanvas 并 ``set_tree``，返回现场。

    返回 ``(window, notebook, hidden_page, canvas)``；调用方负责 ``window.destroy()``。
    另开 Toplevel 是必须的：往共享 App 上挂控件会被它的主 Notebook（``expand=True``）
    挤成 0 高度、连"可见尺寸"这条路径都走不到。
    """
    import tkinter as tk
    from seq_toolkit.gui.tree_canvas import TreeCanvas
    from seq_toolkit.phylo import parse_newick

    window = tk.Toplevel(app)
    window.geometry("900x600")
    notebook = ttk.Notebook(window)
    notebook.pack(fill="both", expand=True)
    shown = ttk.Frame(notebook)
    hidden = ttk.Frame(notebook)
    notebook.add(shown, text="可见页")
    notebook.add(hidden, text="隐藏页")
    notebook.select(shown)
    app.update()
    canvas = TreeCanvas(hidden, leaf_gap=leaf_gap)
    canvas.pack(fill="both", expand=True)
    canvas.set_tree(parse_newick(tree))
    return window, notebook, hidden, canvas


def test_tree_canvas_refits_when_a_hidden_page_becomes_visible(app):
    """I1：树是在**隐藏页**里 set_tree 的（建树要十几秒到数分钟，用户早切走了）。

    Tk 对未映射的控件返回 ``winfo_width() == 1``（**不是 0**），旧代码的 ``or 400``
    因此拿不到兜底，整棵树被压到极小；切回该页后 ``<Configure>`` 只重画不重算，
    scale 停留在那个小值上，必须手点「适应窗口」才恢复——用户看到的就是"点了生成、
    回来一看什么都没有"。

    **判据必须能区分「补算 / 不补算」**：40 叶树在 400x300 兜底下 scale 就有 0.39，
    早就过了 ``MIN_LABEL_SCALE``，把补算整段删掉也照样绿。这里用 200 叶（复审探针
    同款）：兜底尺寸下 scale=0.0771、树高约 276px（占视口 51%）；补算后 scale=0.1400、
    树高 505px（占 93%），三条判据都能把两种状态分开。
    """
    from seq_toolkit.gui.tree_canvas import (FALLBACK_HEIGHT, FALLBACK_WIDTH,
                                             MIN_LABEL_SCALE)

    window, notebook, page, canvas = _hidden_page_canvas(app, _star_tree(200),
                                                         leaf_gap=18.0)
    try:
        # 前提：隐藏页里的画布确实没有布局尺寸（Tk 给的是 1，不是 0）
        assert canvas.canvas.winfo_width() <= 1
        assert canvas._viewport() == (FALLBACK_WIDTH, FALLBACK_HEIGHT), \
            "未布局时必须按文档里的兜底视口算"
        assert canvas._fitted_with_fallback is True, "这次 fit() 确实是按兜底尺寸算的"
        hidden_scale = canvas._scale
        # 兜底生效 ⇒ 不是被 0.02 下限截断出来的值；200 叶下它天然低于标签阈值
        assert 0.05 < hidden_scale < MIN_LABEL_SCALE, \
            f"兜底尺寸下的 scale 应在 0.077 上下，实得 {hidden_scale}"

        notebook.select(page)
        app.update()
        width = canvas.canvas.winfo_width()
        height = canvas.canvas.winfo_height()
        assert width > 100 and height > 100, "切回该页后画布应当拿到真实尺寸"

        # 只重画不重算的话，下面三条全部不成立——先报用户看得见的现象（树太小），
        # 再报内部状态，失败信息才对得上"切回来什么都没有"这个症状。
        assert canvas._scale > 0.1, f"切回该页后 scale 仍是 {canvas._scale}"
        assert canvas._scale > hidden_scale * 1.5, \
            f"补算后 scale 应明显变大：{hidden_scale} → {canvas._scale}"
        drawn = canvas.canvas.bbox("all")
        assert drawn is not None and canvas.item_count() > 0
        assert (drawn[3] - drawn[1]) >= height * 0.75, \
            f"树高只占视口的 {(drawn[3] - drawn[1]) / height:.0%}（视口高 {height}）"
        assert canvas._fitted_with_fallback is False, "拿到真实尺寸后必须重算一次"
    finally:
        window.destroy()
        app.update()

    # 同规模但把叶间距压小：这样"补算"才会把 scale 抬过 MIN_LABEL_SCALE，叶标签也真的
    # 画出来（默认间距下 200 叶的 fit 受高度限制、scale 只有 0.14，天然够不到阈值，
    # 用不了这条判据——所以两种间距各测一遍，而不是拿 40 叶凑数）。
    window, notebook, page, canvas = _hidden_page_canvas(app, _star_tree(200),
                                                         leaf_gap=5.0)
    try:
        assert canvas._scale < MIN_LABEL_SCALE, "前提：兜底尺寸下还没到画标签的阈值"
        assert canvas.item_count() <= 400, "低于阈值时不该画叶标签（只剩折线）"
        notebook.select(page)
        app.update()
        assert canvas._scale > MIN_LABEL_SCALE, \
            f"补算后 scale 应高于 MIN_LABEL_SCALE，实得 {canvas._scale}"
        assert canvas.item_count() > 400, "过了阈值就该把叶标签画出来"
    finally:
        window.destroy()
        app.update()


def test_missing_notice_reports_counts_and_names():
    from seq_toolkit.gui.tab_phylo import missing_notice
    text = missing_notice(["Xyzzy_foobar"], 6, 7)
    assert "输入 7 个物种" in text and "入树 6 个" in text
    assert "Xyzzy_foobar" in text
    assert missing_notice([], 6, 6) == ""


def test_tab_builds_with_expected_controls(app):
    from seq_toolkit.gui.tab_phylo import build
    frame = ttk.Frame(app)
    build(frame, app)
    buttons = [w.cget("text") for w in _descendants(frame) if isinstance(w, ttk.Button)]
    for expected in ("从序列文件导入物种名", "生成进化树", "检测 R 环境"):
        assert expected in buttons, f"缺少按钮：{expected}"
    combos = [w for w in _descendants(frame) if isinstance(w, ttk.Combobox)]
    assert len(combos) >= 2                       # 系统 + 场景
    frame.destroy()


def test_generate_runs_in_background_and_reports_missing(app, tmp_path, monkeypatch):
    import tkinter as tk
    import seq_toolkit.gui.tab_phylo as tab_phylo
    from seq_toolkit.phylo import REnvironment

    frame = ttk.Frame(app)
    tab_phylo.build(frame, app)
    tree_file = tmp_path / "phylogeny_tree.treefile"
    tree_file.write_text("((A:1,B:2):0.5,C:3);", encoding="utf-8")

    tab_phylo._detect_environment = lambda *_a, **_k: REnvironment(
        "Rscript.exe", "4.6.1", True, "就绪")
    tab_phylo._run_phylo = lambda *args, **kwargs: type("R", (), {
        "returncode": 0, "stdout": "", "stderr": "", "tree_path": str(tree_file),
        "missing": ["Xyzzy_foobar"], "tip_count": 2})()
    # 完成提示是模态对话框：测试里必须换成空实现，否则用例会挂住
    monkeypatch.setattr(tab_phylo.messagebox, "showinfo", lambda *a, **k: None)

    picker_text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
    picker_text.insert("1.0", "A b\nB c\nXyzzy foobar\n")
    from seq_toolkit.gui.widgets import FilePicker
    picker = next(w for w in _descendants(frame)
                  if isinstance(w, FilePicker))
    picker.set_path(str(tree_file))

    next(w for w in _descendants(frame)
         if isinstance(w, ttk.Button)
         and w.cget("text") == "生成进化树").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    from seq_toolkit.gui.tree_canvas import TreeCanvas
    canvas = next(w for w in _descendants(frame) if isinstance(w, TreeCanvas))
    assert canvas.item_count() > 0
    assert any("Xyzzy_foobar" in entry.message for entry in app.log.entries)
    frame.destroy()


def test_generate_resets_the_progress_panel_when_cancelled(app, tmp_path, monkeypatch):
    """M2：取消后进度必须复位，不能停在「正在生成（大列表可能需要数分钟）」。

    取消既不是成功也不是失败：``OperationCancelled`` 不走 ``on_error``，所以"复位进度条"
    只挂在 ``on_error`` 上的话永远轮不到执行，用户会以为任务还在跑。
    """
    import tkinter as tk
    import seq_toolkit.gui.tab_phylo as tab_phylo
    from seq_toolkit.gui.widgets import FilePicker, ProgressPanel
    from seq_toolkit.phylo import REnvironment
    from seq_toolkit.pipeline import OperationCancelled

    frame = ttk.Frame(app)
    tab_phylo.build(frame, app)
    monkeypatch.setattr(tab_phylo, "_detect_environment",
                        lambda *_a, **_k: REnvironment("Rscript.exe", "4.6.1", True, "就绪"))

    def _blocking_run(*_args, **_kwargs):
        cancel = _kwargs.get("cancel")
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                raise OperationCancelled("操作已取消")
            time.sleep(0.01)
        return None

    monkeypatch.setattr(tab_phylo, "_run_phylo", _blocking_run)
    monkeypatch.setattr(tab_phylo.messagebox, "showinfo", lambda *a, **k: None)

    def _pump_until_idle() -> None:
        deadline = time.monotonic() + 5.0
        while app.worker.is_running() and time.monotonic() < deadline:
            app._drain()          # start_polling=False：消息泵要手动转
            time.sleep(0.01)
        app._drain()

    try:
        next(w for w in _descendants(frame)
             if isinstance(w, tk.Text)).insert("1.0", "A b\n")
        next(w for w in _descendants(frame)
             if isinstance(w, FilePicker)).set_path(str(tmp_path / "phylogeny_tree.treefile"))
        generate = next(w for w in _descendants(frame)
                        if isinstance(w, ttk.Button)
                        and w.cget("text") == "生成进化树")
        generate.invoke()

        progress = next(w for w in _descendants(frame) if isinstance(w, ProgressPanel))
        label = next(w for w in progress.winfo_children() if isinstance(w, ttk.Label))
        deadline = time.monotonic() + 5.0
        while "正在生成" not in label.cget("text") and time.monotonic() < deadline:
            app._drain()
            time.sleep(0.01)
        assert "正在生成" in label.cget("text"), "前提没满足：任务还没进入生成阶段"

        app.cancel_job()
        _pump_until_idle()
        assert label.cget("text") == "就绪", f"取消后进度标签停在「{label.cget('text')}」"
        # 按钮的禁用/恢复由 App 统一处理（register_busy_widget → _finish），
        # 取消路径不额外开小灶，但必须真的恢复可用，否则用户要重开程序
        assert str(generate.cget("state")) == "normal", "取消后「生成进化树」必须恢复可用"
    finally:
        # 断言失败时也别把一条还在跑的任务留给下一条用例（消息泵会串味）
        app.worker.cancel()
        _pump_until_idle()
        frame.destroy()


def test_detect_cancel_is_reported_on_the_detect_panel(app, monkeypatch):
    """Minor：检测面板的取消也要有人交代（状态栏 + 日志 + 环境标签）。

    检测走不可中断的 ``subprocess.run``，``on_cancel`` 只可能在它返回之后触发；因此
    ``do_detect`` 的 job 必须在返回前看一眼取消标记，否则这个回调永远不会执行。
    """
    import seq_toolkit.gui.tab_phylo as tab_phylo
    from seq_toolkit.phylo import REnvironment

    frame = ttk.Frame(app)
    tab_phylo.build(frame, app)

    def _slow_detect(*_args, **_kwargs):
        time.sleep(0.5)                 # 不看取消标记：模拟不可中断的外部命令
        return REnvironment("Rscript.exe", "4.6.1", True, "R 4.6.1 与 V.PhyloMaker2 就绪")

    monkeypatch.setattr(tab_phylo, "_detect_environment", _slow_detect)
    app.clear_log()

    def _pump_until_idle() -> None:
        deadline = time.monotonic() + 5.0
        while app.worker.is_running() and time.monotonic() < deadline:
            app._drain()
            time.sleep(0.01)
        app._drain()

    try:
        next(w for w in _descendants(frame) if isinstance(w, ttk.Button)
             and w.cget("text") == "检测 R 环境").invoke()
        app.cancel_job()
        assert "正在取消" in app.status_label.cget("text"), "前提：取消请求已发出"
        _pump_until_idle()

        assert any(entry.level == "WARN" and "检测已取消" in entry.message
                   for entry in app.log.entries), \
            [entry.message for entry in app.log.entries]
        assert app.status_label.cget("text") == "已取消"
        labels = [w for w in _descendants(frame) if isinstance(w, ttk.Label)]
        assert any(w.cget("text") == "尚未检测 R 环境" for w in labels), \
            "取消后环境标签不能停在上一轮的结论上"
    finally:
        app.worker.cancel()
        _pump_until_idle()
        frame.destroy()


def test_deep_tree_preview_failure_keeps_the_completion_notice(app, tmp_path, monkeypatch):
    """M3：超深 Newick 触发 RecursionError 时，必须给中文可读提示**且**完成弹窗照常出现。

    递归下降的 ``parse_newick`` 在毛毛虫树上会撞上 Python 递归上限（评审实测 n=900；
    阈值随当前栈深浮动，这里取 3000 保证稳定复现）。``RecursionError`` 不在
    ``(OSError, ValueError)`` 里，漏出去就从 ``after`` 回调冒到 Tk，于是「生成完成」弹窗
    再也不出现——用户既看不到树，也不知道为什么没有树。
    """
    import tkinter as tk
    import seq_toolkit.gui.tab_phylo as tab_phylo
    from seq_toolkit.gui.tree_canvas import TreeCanvas
    from seq_toolkit.gui.widgets import FilePicker
    from seq_toolkit.phylo import PhyloRun, REnvironment

    deep = tmp_path / "deep.treefile"
    deep.write_text(_caterpillar_tree(3000), encoding="utf-8", newline="\n")
    # 前提：这棵树确实深到会 RecursionError，否则本用例什么都没测到
    with pytest.raises(RecursionError):
        tab_phylo.phylo.parse_newick(deep.read_text(encoding="utf-8"))

    notices = []
    frame = ttk.Frame(app)
    tab_phylo.build(frame, app)
    monkeypatch.setattr(tab_phylo, "_detect_environment",
                        lambda *_a, **_k: REnvironment("Rscript.exe", "4.6.1", True, "就绪"))
    monkeypatch.setattr(tab_phylo, "_run_phylo",
                        lambda *_a, **_k: PhyloRun(returncode=0, stdout="", stderr="",
                                                  tree_path=str(deep), missing=[],
                                                  tip_count=3000))
    monkeypatch.setattr(tab_phylo.messagebox, "showinfo",
                        lambda *args, **kwargs: notices.append(args))
    app.clear_log()
    try:
        next(w for w in _descendants(frame)
             if isinstance(w, tk.Text)).insert("1.0", "A b\n")
        next(w for w in _descendants(frame)
             if isinstance(w, FilePicker)).set_path(str(deep))
        next(w for w in _descendants(frame)
             if isinstance(w, ttk.Button)
             and w.cget("text") == "生成进化树").invoke()
        deadline = time.monotonic() + 5.0
        while app.worker.is_running() and time.monotonic() < deadline:
            time.sleep(0.01)
        app._drain()          # 修复前这里会把 RecursionError 抛出来
        assert notices, "完成弹窗必须照常出现（否则用户不知道任务已经结束）"
        # 提示里必须带"树其实写成功了、写到哪儿"：只说"无法预览"，用户会以为整件事白跑了
        errors = [entry.message for entry in app.log.entries if entry.level == "ERROR"]
        assert any("无法预览" in message and "已正常写出" in message
                   and str(deep) in message for message in errors), errors
        canvas = next(w for w in _descendants(frame) if isinstance(w, TreeCanvas))
        assert canvas.item_count() == 0
    finally:
        app.worker.cancel()
        deadline = time.monotonic() + 5.0
        while app.worker.is_running() and time.monotonic() < deadline:
            time.sleep(0.01)
        app._drain()
        frame.destroy()


def test_tab_is_registered_at_the_end(app):
    titles = [app.notebook.tab(index, "text")
              for index in range(len(app.notebook.tabs()))]
    assert "进化树生成" in titles and "物种名清洗" in titles
    assert titles[-2:] == ["物种名清洗", "进化树生成"]
    assert app.notebook.tab(4, "text") == "设置"     # open_tab(4) 仍然正确


def _generate_with_stub_run(app, tmp_path, monkeypatch, run):
    """在新建的 phylo 面板上点一次「生成进化树」，由模块级工厂替身返回给定的 run。

    与 ``test_generate_runs_in_background_and_reports_missing`` 用同一个接缝，
    绝不真的启动 R；请求的输出路径固定为 ``tmp_path/phylogeny_tree.treefile``。
    """
    import tkinter as tk
    import seq_toolkit.gui.tab_phylo as tab_phylo
    from seq_toolkit.gui.widgets import FilePicker
    from seq_toolkit.phylo import REnvironment

    frame = ttk.Frame(app)
    tab_phylo.build(frame, app)
    tab_phylo._detect_environment = lambda *_a, **_k: REnvironment(
        "Rscript.exe", "4.6.1", True, "就绪")
    tab_phylo._run_phylo = lambda *args, **kwargs: run
    monkeypatch.setattr(tab_phylo.messagebox, "showinfo", lambda *a, **k: None)
    # 本模块共用一个 App，日志也是共用的：先清空，后续"日志里出现了/没出现某行"的断言
    # 才只反映本用例自己的行为（否则上一条用例留下的 WARN 会把断言带偏）。
    app.clear_log()

    requested = tmp_path / "phylogeny_tree.treefile"
    species_text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
    species_text.insert("1.0", "A b\nB c\nC d\n")
    next(w for w in _descendants(frame)
         if isinstance(w, FilePicker)).set_path(str(requested))
    next(w for w in _descendants(frame)
         if isinstance(w, ttk.Button)
         and w.cget("text") == "生成进化树").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()
    frame.destroy()
    return requested


def test_generate_warns_when_the_target_file_had_to_make_way(app, tmp_path, monkeypatch):
    """输出目标被让位到 ``_1`` 时必须在日志里说清"实际写到哪儿了"。

    ``run_phylo`` 现在绝不覆盖已有文件（见 ``tests/test_phylo.py`` 的让位用例），
    但界面上的输出框仍显示用户填的路径；不记这条 WARN，用户会去旧文件里找新树。
    """
    from seq_toolkit.phylo import PhyloRun

    _generate_with_stub_run(
        app, tmp_path, monkeypatch,
        PhyloRun(returncode=0, stdout="", stderr="",
                 tree_path=str(tmp_path / "phylogeny_tree_1.treefile"),
                 missing=[], tip_count=2))
    messages = [entry.message for entry in app.log.entries]
    assert any("目标文件已存在，实际写入" in message
               and "phylogeny_tree_1.treefile" in message for message in messages)


def test_generate_logs_the_full_missing_list(app, tmp_path, monkeypatch):
    """界面标签只显示前 8 个未入树物种（避免撑爆布局），日志必须给完整清单。

    第 9 个起若哪儿都看不到，用户就无从知道到底少了哪些物种——「绝不静默」不允许。
    """
    from seq_toolkit.phylo import PhyloRun

    names = [f"Xyzzy_genus{i:02d}" for i in range(1, 13)]
    tree_file = tmp_path / "phylogeny_tree.treefile"
    tree_file.write_text("((A:1,B:2):0.5,C:3);", encoding="utf-8")
    _generate_with_stub_run(
        app, tmp_path, monkeypatch,
        PhyloRun(returncode=0, stdout="", stderr="", tree_path=str(tree_file),
                 missing=list(names), tip_count=1))
    logged = " ".join(entry.message for entry in app.log.entries)
    for name in names:
        assert name in logged, f"日志里缺少未入树物种：{name}"
    # 请求路径与实际路径相同，就不该冒出"目标文件已存在"的假警报
    assert not any("目标文件已存在" in entry.message for entry in app.log.entries)
