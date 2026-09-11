"""后台工作线程与队列消息泵。

Tkinter 控件只能在主线程更新，因此后台线程只往 queue 投消息，
主线程用 App.after(100, ...) 周期消费。
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable

from ..pipeline import OperationCancelled

MSG_PROGRESS = "progress"
MSG_LOG = "log"
MSG_DONE = "done"
MSG_FAILED = "failed"

LEVEL_INFO = "INFO"
LEVEL_WARN = "WARN"
LEVEL_ERROR = "ERROR"


@dataclass(frozen=True)
class WorkerMessage:
    kind: str
    payload: object = None


class JobContext:
    """交给后台任务使用的上下文。任务只能通过它与界面通信。"""

    def __init__(self, out_queue: "queue.Queue[WorkerMessage]",
                 cancel_event: threading.Event) -> None:
        self._queue = out_queue
        self._cancel = cancel_event

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel

    def progress(self, done: int, total: int, message: str = "") -> None:
        self._queue.put(WorkerMessage(MSG_PROGRESS, (done, total, message)))

    def info(self, message: str) -> None:
        self._queue.put(WorkerMessage(MSG_LOG, (LEVEL_INFO, message)))

    def warn(self, message: str) -> None:
        self._queue.put(WorkerMessage(MSG_LOG, (LEVEL_WARN, message)))

    def error(self, message: str) -> None:
        self._queue.put(WorkerMessage(MSG_LOG, (LEVEL_ERROR, message)))

    def raise_if_cancelled(self) -> None:
        if self._cancel.is_set():
            raise OperationCancelled("操作已取消")


class BackgroundWorker:
    """单任务后台执行器。同一时刻只允许一个任务。"""

    def __init__(self) -> None:
        self.queue: "queue.Queue[WorkerMessage]" = queue.Queue()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, target: Callable[[JobContext], object]) -> None:
        if self.is_running():
            raise RuntimeError("已有任务在运行")
        self._cancel.clear()
        context = JobContext(self.queue, self._cancel)

        def _run() -> None:
            try:
                result = target(context)
            except BaseException as error:  # noqa: BLE001 必须捕获后送回主线程
                self.queue.put(WorkerMessage(MSG_FAILED, error))
            else:
                self.queue.put(WorkerMessage(MSG_DONE, result))

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def drain(self) -> list[WorkerMessage]:
        messages: list[WorkerMessage] = []
        while True:
            try:
                messages.append(self.queue.get_nowait())
            except queue.Empty:
                return messages
