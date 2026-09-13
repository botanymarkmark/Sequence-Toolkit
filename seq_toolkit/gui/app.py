"""主窗口：标签页容器、日志面板、状态栏、后台任务消息泵。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ..applog import RunLog
from ..pipeline import OperationCancelled
from ..settings import Settings, save_settings
from . import (tab_accession, tab_merge, tab_phylo, tab_rename, tab_search,
               tab_settings, tab_tnrs)
from .worker import (
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARN,
    MSG_DONE,
    MSG_FAILED,
    MSG_LOG,
    MSG_PROGRESS,
    BackgroundWorker,
)
from .widgets import SortableTable

POLL_INTERVAL_MS = 100

TAB_SPECS = (
    ("合并 / 转换", tab_merge),
    ("重命名 / 拆分", tab_rename),
    ("检索与批量下载", tab_search),
    ("按登录号下载", tab_accession),
    ("设置", tab_settings),
    # 新面板一律追加在末尾而不是插在「设置」之前：tab_search 里硬编码了
    # open_tab(4) 用于跳转到「设置」，插队会让那个索引指向错误的标签。
    ("物种名清洗", tab_tnrs),
    ("进化树生成", tab_phylo),
)


class App(tk.Tk):
    def __init__(self, settings: Settings, start_polling: bool = True) -> None:
        super().__init__()
        self.title("序列工具箱 — FASTA / GenBank 合并、转换、命名与 NCBI 下载")
        self.geometry("1120x780")
        self.minsize(940, 660)

        self.settings = settings
        self.log = RunLog()
        self.worker = BackgroundWorker()

        self._progress_handler: Callable[[int, int, str], None] | None = None
        self._on_done: Callable[[object], None] | None = None
        self._on_error: Callable[[BaseException], None] | None = None
        self._on_cancel: Callable[[], None] | None = None
        self._log_cursor = 0
        self._log_last_entry = None
        self._busy_widgets: list = []
        self._log_levels = {LEVEL_INFO: self.log.info,
                            LEVEL_WARN: self.log.warn,
                            LEVEL_ERROR: self.log.error}

        self._build_tabs()
        self._build_log_panel()
        self._build_status_bar()

        if start_polling:
            self.after(POLL_INTERVAL_MS, self._poll)

    # ---------- 构建界面 ----------

    def _build_tabs(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        for title, module in TAB_SPECS:
            frame = ttk.Frame(self.notebook)
            self.notebook.add(frame, text=title)
            module.build(frame, self)

    def _build_log_panel(self) -> None:
        panel = ttk.LabelFrame(self, text="日志")
        panel.pack(fill="both", expand=False, padx=8, pady=4)

        inner = ttk.Notebook(panel)
        inner.pack(fill="both", expand=True, padx=4, pady=4)

        log_frame = ttk.Frame(inner)
        inner.add(log_frame, text="运行日志")
        self.log_text = tk.Text(log_frame, height=9, wrap="none")
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical",
                                  command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set, state="disabled")

        exception_frame = ttk.Frame(inner)
        inner.add(exception_frame, text="异常清单")
        columns = ("path", "line", "header", "reason", "final_name")
        headings = ("文件", "行号", "原始 header", "判定原因", "最终采用的名称")
        self.exception_table = SortableTable(exception_frame, columns, headings,
                                             (240, 60, 300, 260, 180))
        self.exception_table.pack(side="left", fill="both", expand=True)
        exception_scroll = ttk.Scrollbar(exception_frame, orient="vertical",
                                         command=self.exception_table.yview)
        exception_scroll.pack(side="right", fill="y")
        self.exception_table.configure(yscrollcommand=exception_scroll.set)

        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(buttons, text="导出日志", command=self._export_log).pack(side="left")
        ttk.Button(buttons, text="导出异常清单 CSV",
                   command=self._export_exceptions).pack(side="left", padx=4)
        ttk.Button(buttons, text="清空日志", command=self._clear_log).pack(side="left")

    def _build_status_bar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        self.status_label = ttk.Label(bar, text="就绪", anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(bar, text="取消", state="disabled",
                                        command=self.cancel_job)
        self.cancel_button.pack(side="right")

    # ---------- 任务调度 ----------

    def run_job(self, target, on_done=None, on_error=None,
                progress_handler=None, on_cancel=None) -> bool:
        """启动后台任务。四个回调都是可选的，不传时行为与以前完全一致。

        ``on_cancel`` 是**取消**这一种结局的专用回调（默认 None）：取消既不是成功也不是
        失败，``OperationCancelled`` 不会走 ``on_error``。标签页里"复位进度条/恢复按钮文字"
        这类收尾只挂在 on_error 上就会漏掉取消路径——建树被取消后进度标签永远停在
        「正在生成（大列表可能需要数分钟）」。按钮的禁用/恢复由 App 统一处理
        （``register_busy_widget``），标签页在 ``on_cancel`` 里只需复位自己的进度显示。
        """
        if self.worker.is_running():
            # 用非模态提示而不是 messagebox：模态对话框会阻塞主循环，
            # 也让自动化测试无法继续执行。
            self.log.warn("已有任务正在运行，请先等待完成或点击取消。")
            self.set_status("已有任务正在运行")
            return False
        self._progress_handler = progress_handler
        self._on_done = on_done
        self._on_error = on_error
        self._on_cancel = on_cancel
        self.cancel_button.configure(state="normal")
        for widget in self._busy_widgets:
            widget.configure(state="disabled")
        self.set_status("正在处理…")
        self.worker.start(target)
        return True

    def register_busy_widget(self, widget) -> None:
        """注册"任务运行期间应被禁用"的控件。由标签页在构建时调用。

        这样按钮的禁用/恢复统一由 App 在任务真正结束时处理，标签页无需自己
        猜测何时恢复——避免出现"任务还在跑但按钮已可点"的时序漏洞。
        """
        self._busy_widgets.append(widget)

    def cancel_job(self) -> None:
        if self.worker.is_running():
            self.worker.cancel()
            self.set_status("正在取消…")

    def _poll(self) -> None:
        try:
            self._drain()
        finally:
            self.after(POLL_INTERVAL_MS, self._poll)

    def _drain(self) -> None:
        for message in self.worker.drain():
            if message.kind == MSG_PROGRESS:
                done, total, text = message.payload
                if self._progress_handler is not None:
                    self._progress_handler(done, total, text)
                self.set_status(text or f"{done} / {total}")
            elif message.kind == MSG_LOG:
                level, text = message.payload
                self._log_levels.get(level, self.log.info)(text)
                self.refresh_log_view()
            elif message.kind == MSG_DONE:
                self._finish()
                handler = self._on_done
                self._on_done = None
                if handler is not None:
                    handler(message.payload)
            elif message.kind == MSG_FAILED:
                self._finish()
                handler = self._on_error
                self._on_error = None
                error = message.payload
                if isinstance(error, OperationCancelled):
                    self.log.warn("操作已取消")
                    self.set_status("已取消")
                    cancel_handler = self._on_cancel
                    self._on_cancel = None
                    if cancel_handler is not None:
                        cancel_handler()
                elif handler is not None:
                    handler(error)
                else:
                    self.log.error(f"任务失败: {error}")
                    self.set_status(f"任务失败：{error}")
            self.refresh_log_view()
            self.refresh_exception_view()

    def _finish(self) -> None:
        self.cancel_button.configure(state="disabled")
        for widget in self._busy_widgets:
            widget.configure(state="normal")
        self._progress_handler = None
        # 「进行中」有两种写法，都要能收尾：用户点过取消、但任务没理会取消信号而是正常
        # 跑完（例如「检测 R 环境」走的是不可中断的 subprocess.run）时，状态栏原先会永远
        # 停在「正在取消…」——任务早已结束、按钮也恢复了，界面却在骗人。真正被取消的那条
        # 路径由 _drain 显式写成「已取消」，不受这里影响。
        if self.status_label.cget("text") in ("正在处理…", "正在取消…"):
            self.set_status("就绪")

    # ---------- 视图刷新 ----------

    def set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def refresh_log_view(self) -> None:
        entries = self.log.entries
        if (self._log_cursor > len(entries)
                or (self._log_cursor
                    and entries[self._log_cursor - 1] is not self._log_last_entry)):
            # 重同步（修复 2 采 (a) 方案：以"已渲染的最后一条条目"的身份做快照比较）。
            # 只用条数做游标时，只要有人绕过 App 直接调用 RunLog 的公开方法
            # log.clear()（标签页作者很自然会这么做），游标就会大于实际条目数：
            # 切片为空，而落在"清空"与"本次刷新"之间的新条目被永久丢弃，界面看起来
            # 像"程序没反应"。身份比较让这种外部清空自动被识别，此时整屏重画一次，
            # 宁可多画一次也不静默丢日志。选 (a) 而不是只提供 app.clear_log()：
            # (a) 对任何调用路径都成立，不依赖标签页作者记得换 API。
            self._reset_log_text()
            self._log_cursor = 0
            self._log_last_entry = None
        pending = entries[self._log_cursor:]
        if not pending:
            return
        self.log_text.configure(state="normal")
        for entry in pending:
            self.log_text.insert("end", f"[{entry.level}] {entry.message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self._log_cursor = len(entries)
        self._log_last_entry = entries[-1]

    def _reset_log_text(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def refresh_exception_view(self) -> None:
        self.exception_table.set_rows([
            (entry.path, entry.line, entry.header, entry.reason, entry.final_name)
            for entry in self.log.exceptions
        ])

    def _clear_log(self) -> None:
        self.log.clear()
        self._log_cursor = 0
        self._log_last_entry = None
        self._reset_log_text()
        self.refresh_exception_view()

    def clear_log(self) -> None:
        """清空日志面板与异常清单。**标签页请调用 app.clear_log()**。

        不要直接调用 app.log.clear()：它只清 RunLog，不会清空日志文本控件、也不会
        复位增量游标，界面会留下与日志内容不一致的旧行。即便标签页确实走了
        app.log.clear()，refresh_log_view() 也会自动重同步（见其注释），不会静默
        丢日志——两条路径都安全，但公开入口是更清晰的那个。
        """
        self._clear_log()

    def _export_log(self) -> None:
        from tkinter import filedialog
        target = filedialog.asksaveasfilename(defaultextension=".log",
                                              filetypes=[("日志文件", "*.log")])
        if target:
            self.log.export_log(target)
            self.log.info(f"日志已导出到 {target}")

    def _export_exceptions(self) -> None:
        from tkinter import filedialog
        target = filedialog.asksaveasfilename(defaultextension=".csv",
                                              filetypes=[("CSV 文件", "*.csv")])
        if target:
            self.log.export_exceptions_csv(target)
            self.log.info(f"异常清单已导出到 {target}")

    def open_tab(self, index: int) -> None:
        self.notebook.select(index)

    def save_settings(self) -> None:
        path = save_settings(self.settings)
        self.log.info(f"设置已保存到 {path}")
