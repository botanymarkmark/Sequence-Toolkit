"""运行日志与异常清单收集。线程安全：后台工作线程写、主线程读。"""

from __future__ import annotations

import csv
import threading
from dataclasses import dataclass

INFO = "INFO"
WARN = "WARN"
ERROR = "ERROR"

EXCEPTION_HEADERS = ("文件", "行号", "原始 header", "判定原因", "最终采用的名称")


@dataclass(frozen=True)
class LogEntry:
    level: str
    message: str


@dataclass(frozen=True)
class ExceptionEntry:
    path: str
    line: int
    header: str
    reason: str
    final_name: str = ""


class RunLog:
    """收集一次运行的日志与异常清单。所有变更加锁，读取返回快照元组。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[LogEntry] = []
        self._exceptions: list[ExceptionEntry] = []

    def _add(self, level: str, message: str) -> None:
        with self._lock:
            self._entries.append(LogEntry(level, message))

    def info(self, message: str) -> None:
        self._add(INFO, message)

    def warn(self, message: str) -> None:
        self._add(WARN, message)

    def error(self, message: str) -> None:
        self._add(ERROR, message)

    def add_exception(self, path: str, line: int, header: str, reason: str,
                      final_name: str = "") -> None:
        with self._lock:
            self._exceptions.append(ExceptionEntry(path, line, header, reason, final_name))

    @property
    def entries(self) -> tuple[LogEntry, ...]:
        with self._lock:
            return tuple(self._entries)

    @property
    def exceptions(self) -> tuple[ExceptionEntry, ...]:
        with self._lock:
            return tuple(self._exceptions)

    def exception_count(self) -> int:
        with self._lock:
            return len(self._exceptions)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._exceptions.clear()

    def export_text(self) -> str:
        return "\n".join(f"[{entry.level}] {entry.message}" for entry in self.entries)

    def export_log(self, out_path: str) -> None:
        with open(str(out_path), "wt", encoding="utf-8", newline="\n") as handle:
            handle.write(self.export_text())
            handle.write("\n")

    def export_exceptions_csv(self, out_path: str) -> None:
        with open(str(out_path), "wt", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(EXCEPTION_HEADERS)
            for entry in self.exceptions:
                writer.writerow([entry.path, entry.line, entry.header,
                                 entry.reason, entry.final_name])
