import time

import pytest

from seq_toolkit.gui.worker import (
    MSG_DONE,
    MSG_FAILED,
    MSG_LOG,
    MSG_PROGRESS,
    BackgroundWorker,
)
from seq_toolkit.pipeline import OperationCancelled


def _wait(worker, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        messages = worker.drain()
        if any(m.kind in (MSG_DONE, MSG_FAILED) for m in messages):
            return messages
        time.sleep(0.01)
    raise AssertionError("worker 未在超时前结束")


def test_worker_reports_done_with_result():
    worker = BackgroundWorker()
    worker.start(lambda ctx: 42)
    messages = _wait(worker)
    assert messages[-1].kind == MSG_DONE
    assert messages[-1].payload == 42


def test_worker_reports_failure_with_exception():
    def boom(ctx):
        raise ValueError("炸了")

    worker = BackgroundWorker()
    worker.start(boom)
    messages = _wait(worker)
    assert messages[-1].kind == MSG_FAILED
    assert isinstance(messages[-1].payload, ValueError)


class _CustomBaseError(BaseException):
    """自定义 BaseException 子类；except Exception 抓不到它。"""


@pytest.mark.parametrize(
    "error",
    [KeyboardInterrupt("用户中断"), _CustomBaseError("自定义中断")],
    ids=["KeyboardInterrupt", "BaseException 子类"],
)
def test_worker_reports_base_exception_as_failure(error):
    """只捕获 Exception 会漏掉 KeyboardInterrupt/SystemExit，必须捕获 BaseException。"""

    def boom(ctx):
        raise error

    worker = BackgroundWorker()
    worker.start(boom)
    messages = _wait(worker)
    assert messages[-1].kind == MSG_FAILED
    assert messages[-1].payload is error


def test_worker_delivers_progress_and_log_in_order():
    def job(ctx):
        ctx.info("开始")
        ctx.progress(1, 3, "第一")
        ctx.progress(2, 3, "第二")
        ctx.warn("注意")
        return "ok"

    worker = BackgroundWorker()
    worker.start(job)
    payloads = [(m.kind, m.payload) for m in _wait(worker)]
    assert payloads == [
        (MSG_LOG, ("INFO", "开始")),
        (MSG_PROGRESS, (1, 3, "第一")),
        (MSG_PROGRESS, (2, 3, "第二")),
        (MSG_LOG, ("WARN", "注意")),
        (MSG_DONE, "ok"),
    ]


def test_cancel_sets_event_and_job_can_abort():
    worker = BackgroundWorker()

    def job(ctx):
        ctx.cancel_event.set()
        ctx.raise_if_cancelled()
        return "never"

    worker.start(job)
    messages = _wait(worker)
    assert messages[-1].kind == MSG_FAILED
    assert isinstance(messages[-1].payload, OperationCancelled)


def test_cancel_method_sets_event():
    worker = BackgroundWorker()
    worker.cancel()
    assert worker.cancel_event.is_set()


def test_is_running_is_false_before_start_and_after_finish():
    worker = BackgroundWorker()
    assert worker.is_running() is False
    worker.start(lambda ctx: None)
    _wait(worker)
    time.sleep(0.05)
    assert worker.is_running() is False


def test_start_refuses_while_running():
    worker = BackgroundWorker()
    worker.start(lambda ctx: time.sleep(0.3))
    with pytest.raises(RuntimeError):
        worker.start(lambda ctx: None)
    _wait(worker)
