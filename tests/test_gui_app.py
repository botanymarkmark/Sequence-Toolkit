import gc
import time

import pytest

tk = pytest.importorskip("tkinter")

from seq_toolkit.applog import RunLog  # noqa: E402
from seq_toolkit.settings import Settings  # noqa: E402


@pytest.fixture(scope="session")
def app():
    """整个测试会话共用一个 App 根窗口。

    本机实测：同一进程内只要不是"第一次" Tk()，就会以约 20%~30% 的概率瞬时
    读不到 Tcl 的 tk.tcl/ttk.tcl（表现为随机的 TclError），所以本模块只建一次
    根窗口（与 tests/test_gui_widgets.py 的既有做法一致），并带几次短重试。
    用 session 作用域而不是 module 作用域，是为了让根窗口活到会话结束，避免
    "本模块销毁根窗口之后、test_gui_widgets 再新建根窗口"这种销毁—新建交替。
    用例之间的状态由下面的 _isolated 复位。
    """
    from seq_toolkit.gui.app import App
    gc.collect()
    instance = None
    last_error = None
    for _ in range(3):
        try:
            instance = App(Settings(), start_polling=False)
            break
        except tk.TclError as error:  # 无头环境或 Tcl 瞬时读不到 tk.tcl
            last_error = error
            time.sleep(0.2)
    if instance is None:  # pragma: no cover - 无图形环境时跳过
        pytest.skip(f"当前环境没有可用的显示，跳过 GUI 测试：{last_error}")
    yield instance
    instance.destroy()
    gc.collect()


@pytest.fixture(autouse=True)
def _isolated(app):
    """让每个用例从干净状态开始，并保证没有后台任务跨用例残留。

    这里必须走 App._clear_log()：它同时清空日志文本控件与增量游标。
    只清 RunLog 再 refresh_log_view() 会留下上一次渲染的旧行，而
    test_refresh_log_view_is_incremental 断言的是全文计数（"[WARN]" 里也含
    字母 A），旧行会让计数失真。
    """
    app._clear_log()
    app.set_status("就绪")
    yield
    app.worker.cancel()
    deadline = time.monotonic() + 2.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)


def test_app_has_log_and_worker(app):
    assert isinstance(app.log, RunLog)
    assert app.worker.is_running() is False


def test_run_job_returns_false_when_busy(app):
    app.worker.start(lambda ctx: time.sleep(0.3))
    assert app.run_job(lambda ctx: None) is False
    app.worker.cancel()
    time.sleep(0.35)


def _wait_for_idle(app, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()          # 正常由 _poll 调用；本模块 start_polling=False


def _cancellable_job(context):
    """一直等到被取消的后台任务：用来走 App 的 OperationCancelled 分支。"""
    from seq_toolkit.pipeline import OperationCancelled

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if context.cancel_event.is_set():
            raise OperationCancelled("操作已取消")
        time.sleep(0.01)
    return None


def test_run_job_calls_on_cancel_and_not_on_error(app):
    """M2：取消是**成功之外的第三种结局**，以前它不走任何回调。

    于是标签页里"复位进度条"的代码只挂在 on_error 上就永远不会执行——建树被取消后，
    进度标签一直停在「正在生成（大列表可能需要数分钟）」，用户以为任务还在跑。
    """
    seen = []
    assert app.run_job(_cancellable_job,
                       on_error=lambda error: seen.append(("error", error)),
                       on_cancel=lambda: seen.append(("cancel", None))) is True
    app.cancel_job()
    _wait_for_idle(app)

    assert [kind for kind, _ in seen] == ["cancel"], "取消只应走 on_cancel，不能走 on_error"
    assert "已取消" in app.status_label.cget("text")
    assert any(entry.level == "WARN" and "操作已取消" in entry.message
               for entry in app.log.entries)


def test_cancelled_job_without_on_cancel_still_works(app):
    """不传 ``on_cancel`` 的既有调用方行为完全不变（可选参数，默认 None）。"""
    assert app.run_job(_cancellable_job) is True
    app.cancel_job()
    _wait_for_idle(app)
    assert "已取消" in app.status_label.cget("text")
    # 取消后按钮与忙碌状态照旧恢复（_finish 不被新参数影响）
    assert str(app.cancel_button.cget("state")) == "disabled"



def test_cancel_then_success_does_not_leave_the_status_stuck(app):
    """Minor：取消信号发出去了、任务却照常跑完时，状态栏不能永久停在「正在取消…」。

    ``_finish()`` 原先只认字面「正在处理…」，于是"点了取消 → 任务没理会取消信号 →
    正常结束"这条路径（例如「检测 R 环境」走不可中断的 ``subprocess.run``）会把
    「正在取消…」永远留在状态栏上：任务早已结束、按钮也恢复了 ``normal``，界面却在骗人。
    """
    def _ignores_cancel(context):
        time.sleep(0.4)          # 压根不看 cancel_event：模拟不可中断的调用
        return "done"

    assert app.run_job(_ignores_cancel) is True     # 故意不传 on_cancel
    app.cancel_job()
    assert "正在取消" in app.status_label.cget("text"), "前提：取消请求已发出"

    _wait_for_idle(app)
    assert app.status_label.cget("text") == "就绪", \
        f"状态栏卡在「{app.status_label.cget('text')}」"


def test_log_view_reflects_run_log_entries(app):
    app.log.info("第一条")
    app.log.warn("第二条")
    app.refresh_log_view()
    content = app.log_text.get("1.0", "end")
    assert "第一条" in content and "WARN" in content


def test_refresh_log_view_is_incremental(app):
    app.log.info("A")
    app.refresh_log_view()
    app.log.info("B")
    app.refresh_log_view()
    content = app.log_text.get("1.0", "end")
    assert content.count("A") == 1
    assert content.count("B") == 1


def test_exception_view_lists_rows(app):
    app.log.add_exception("a.fa", 3, ">ON1.1", "物种名缺失", "ON1.1")
    app.refresh_exception_view()
    children = app.exception_table.get_children()
    assert len(children) == 1
    assert "a.fa" in app.exception_table.item(children[0], "values")


def test_set_status_updates_label(app):
    app.set_status("正在下载")
    assert "正在下载" in app.status_label.cget("text")


def test_tabs_are_registered(app):
    titles = [app.notebook.tab(tab, "text") for tab in app.notebook.tabs()]
    # 用"前五页精确 + 其余允许追加"的写法，而不是断言整个列表相等：
    # 本程序会持续追加新面板（后续周期还要加「进化树生成」），精确列表每加一页就变红，
    # 而每次"改期望值凑绿"都可能把真正的顺序回归一并掩盖掉。
    # 前五页的顺序必须钉死：tab_search 里硬编码了 open_tab(4) 指向「设置」。
    assert titles[:5] == ["合并 / 转换", "重命名 / 拆分", "检索与批量下载",
                          "按登录号下载", "设置"]
    assert "物种名清洗" in titles[5:]


def test_msg_failed_without_error_handler_is_non_modal(app, monkeypatch):
    """失败路径无 on_error 时只能走非模态处理。

    模态对话框会阻塞主循环，T21–T25 的标签页测试一旦跑到失败路径就会挂死；
    这里把 messagebox.showerror 换成"调用即失败"的探针，确保不会尝试弹框。
    """
    import tkinter.messagebox as messagebox_module

    def _modal_should_not_be_used(*args, **kwargs):  # pragma: no cover - 触发即失败
        raise AssertionError("任务失败时不应弹出模态对话框")

    monkeypatch.setattr(messagebox_module, "showerror", _modal_should_not_be_used,
                        raising=False)

    def _fail(context):
        raise RuntimeError("连接超时")

    assert app.run_job(_fail) is True  # 故意不传 on_error
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()  # 正常由 _poll 调用；本模块 start_polling=False

    assert "任务失败" in app.status_label.cget("text")
    assert "连接超时" in app.status_label.cget("text")
    assert any(entry.level == "ERROR" and "连接超时" in entry.message
               for entry in app.log.entries)
    assert "连接超时" in app.log_text.get("1.0", "end")


def test_log_view_recovers_after_direct_log_clear(app):
    """标签页直接调用公开 API app.log.clear() 后，新日志不得静默丢失。"""
    app.log.info("清空前的日志")
    app.refresh_log_view()
    assert "清空前的日志" in app.log_text.get("1.0", "end")

    app.log.clear()  # 绕过 App，模拟标签页直接清 RunLog
    app.log.info("清空后的第一条")
    app.refresh_log_view()
    content = app.log_text.get("1.0", "end")
    assert "清空后的第一条" in content
    assert "清空前的日志" not in content

    app.log.info("清空后的第二条")
    app.refresh_log_view()
    assert "清空后的第二条" in app.log_text.get("1.0", "end")


def test_clear_log_public_api_resets_view_and_cursor(app):
    """App.clear_log() 是标签页应使用的公开入口：同时复位文本与增量游标。"""
    app.log.info("旧日志")
    app.refresh_log_view()
    app.clear_log()
    assert app.log.entries == ()
    assert app.log_text.get("1.0", "end").strip() == ""

    app.log.info("新日志")
    app.refresh_log_view()
    content = app.log_text.get("1.0", "end")
    assert "新日志" in content and "旧日志" not in content
