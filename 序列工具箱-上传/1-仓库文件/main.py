"""序列工具箱入口。

负责：加载设置、安装顶层异常处理、启动 Tk 主循环。
任何未捕获异常都会写入 %APPDATA%/seq_toolkit/crash.log，并弹出可复制的错误对话框，
而不是让窗口静默消失。
"""

from __future__ import annotations

import datetime
import os
import sys
import traceback

from seq_toolkit.settings import load_settings

_APP_DIR = "seq_toolkit"
_CRASH_FILE = "crash.log"


def crash_log_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, _APP_DIR, _CRASH_FILE)


def install_crash_handler() -> str:
    """安装全局异常钩子，返回崩溃日志路径。"""
    target = crash_log_path()

    def _handle(exc_type, exc_value, exc_tb) -> None:
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(target, "at", encoding="utf-8") as handle:
                handle.write(f"\n===== {stamp} =====\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=handle)
        except OSError:
            pass

        try:
            import tkinter.messagebox as messagebox

            messagebox.showerror(
                "程序出现未预期的错误",
                f"{exc_type.__name__}: {exc_value}\n\n"
                f"详细信息已写入：\n{target}",
            )
        except Exception:  # noqa: BLE001 图形环境不可用时退回控制台
            traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)

    sys.excepthook = _handle
    return target


def main() -> int:
    install_crash_handler()
    settings = load_settings()

    from seq_toolkit.gui.app import App

    app = App(settings)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
