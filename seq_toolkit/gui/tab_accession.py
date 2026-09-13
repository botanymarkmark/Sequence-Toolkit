"""④ 按登录号下载：粘贴、读文件、或从已有序列文件里自动提取登录号。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..ncbi import (
    DownloadOptions,
    NcbiClient,
    collect_accessions_from_files,
    parse_accession_text,
)
from .tab_merge import NAMING_LABELS, _label_to_key
from .widgets import FilePicker, ProgressPanel, format_download_summary, grid_row

TITLE = "按登录号下载"


def build(parent: ttk.Frame, app) -> ttk.Frame:
    # 本函数里所有 Tk 变量都显式写 master=parent：不传 master 时 Variable 会挂到
    # tkinter 的 _default_root 上，进程里有第二个 Tk 根窗口时控件与变量就落在不同的
    # Tcl 解释器里，勾选框点了、get() 却仍读到旧值。

    source = ttk.LabelFrame(parent, text="登录号（每行一个，或用空格/逗号/分号分隔）")
    source.pack(fill="both", expand=True, padx=8, pady=(8, 4))
    text = tk.Text(source, height=9, wrap="none")
    text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
    scroll = ttk.Scrollbar(source, orient="vertical", command=text.yview)
    scroll.pack(side="left", fill="y", pady=6)
    text.configure(yscrollcommand=scroll.set)

    side = ttk.Frame(source)
    side.pack(side="left", fill="y", padx=6, pady=6)

    def replace_text(content: str) -> None:
        text.delete("1.0", "end")
        text.insert("1.0", content)

    def load_from_file() -> None:
        chosen = filedialog.askopenfilename(
            title="选择包含登录号的文本文件",
            filetypes=[("文本文件", "*.txt"), ("全部文件", "*.*")])
        if not chosen:
            return
        # utf-8-sig：Windows 记事本另存的文本带 BOM，用普通 utf-8 读会让首个登录号
        # 前面多出 "\ufeff" 而被当成另一个号发出去（必然下不到）。
        with open(chosen, "rt", encoding="utf-8-sig", errors="replace") as handle:
            content = handle.read()
        replace_text(content)
        app.log.info(f"从 {chosen} 读入 {len(parse_accession_text(content))} 个登录号")

    def extract_from_sequences() -> None:
        chosen = filedialog.askopenfilenames(title="选择已有的 FASTA / GenBank 文件")
        if not chosen:
            return
        # 后缀名取「设置」页里的配置：用户自定义的后缀同样要能被认出来。
        # 必须把 app.log 传进去：本回调在主线程直调、外层没有 try，坏文件（截断的 .gz 等）
        # 若既不记日志又逃逸出异常，界面会零反应——没有日志、没有对话框。
        found = collect_accessions_from_files(
            [str(path) for path in chosen],
            fasta_suffixes=app.settings.fasta_suffixes,
            genbank_suffixes=app.settings.genbank_suffixes,
            log=app.log,
        )
        replace_text("\n".join(found))
        app.log.info(f"从文件提取到 {len(found)} 个登录号")

    def clear_text() -> None:
        replace_text("")

    ttk.Button(side, text="从文本文件导入…", command=load_from_file).pack(fill="x", pady=2)
    ttk.Button(side, text="从序列文件提取…", command=extract_from_sequences).pack(fill="x", pady=2)
    ttk.Button(side, text="清空", command=clear_text).pack(fill="x", pady=2)

    download_box = ttk.LabelFrame(parent, text="下载选项")
    download_box.pack(fill="x", padx=8, pady=4)

    want_fasta = tk.BooleanVar(master=parent, value=True)
    want_genbank = tk.BooleanVar(master=parent, value=True)
    per_sequence = tk.BooleanVar(master=parent, value=True)
    merged = tk.BooleanVar(master=parent, value=True)
    row = ttk.Frame(download_box)
    grid_row(download_box, 0, "产物", row)
    ttk.Checkbutton(row, text="FASTA", variable=want_fasta).pack(side="left")
    ttk.Checkbutton(row, text="GenBank",
                    variable=want_genbank).pack(side="left", padx=(10, 0))
    ttk.Checkbutton(row, text="每序列单文件",
                    variable=per_sequence).pack(side="left", padx=(10, 0))
    ttk.Checkbutton(row, text="同时合并为大文件",
                    variable=merged).pack(side="left", padx=(10, 0))

    naming = tk.StringVar(master=parent, value=NAMING_LABELS["accession"])
    combo = ttk.Combobox(download_box, textvariable=naming, state="readonly",
                         values=list(NAMING_LABELS.values()))
    grid_row(download_box, 1, "命名规则", combo)

    out_dir = FilePicker(download_box, mode="directory", title="下载输出文件夹")
    out_dir.set_path(app.settings.output_dir)
    grid_row(download_box, 2, "输出文件夹", out_dir)

    action = ttk.Frame(parent)
    action.pack(fill="x", padx=8, pady=(4, 8))
    progress = ProgressPanel(action)
    progress.pack(side="left", fill="x", expand=True)
    start_button = ttk.Button(action, text="开始下载")

    def on_progress(done: int, total: int, text_message: str) -> None:
        # 只由主线程的 App._drain 调用（后台线程一律经 ctx.progress 投队列）。
        if done == 0:
            progress.start(total)
        progress.update(done, total, text_message)

    def on_done(report) -> None:
        summary = format_download_summary(report, per_sequence.get())
        progress.finish(summary)
        app.log.info(f"下载完成：{summary}")
        for path in (report.merged_fasta, report.merged_genbank):
            if path:
                app.log.info(f"合并产物：{path}")
        messagebox.showinfo(
            "下载完成",
            f"{summary}。\n输出目录：{report.out_dir}")
        if report.failures:
            # 失败清单才是排查现场：顺手把「设置」页切到前台，方便核对邮箱/代理。
            app.open_tab(4)

    def start() -> None:
        accessions = parse_accession_text(text.get("1.0", "end"))
        if not accessions:
            app.log.warn("请先填写或导入登录号")
            return
        target_dir = out_dir.path()
        if not target_dir:
            app.log.warn("请指定下载输出文件夹")
            return
        if not app.settings.email:
            app.log.warn("请先在「设置」中填写 NCBI 邮箱（NCBI 的合规要求）")
            app.open_tab(4)
            return

        # 控件取值全部在主线程一次取完：job 跑在后台线程里，读 Tk 变量同样是跨线程
        # 访问 Tcl。下面这几个是**字符串快照**（不是控件），job 内不再触碰任何控件。
        options = DownloadOptions(
            out_dir=target_dir,
            want_fasta=want_fasta.get(),
            want_genbank=want_genbank.get(),
            per_sequence_files=per_sequence.get(),
            merged_files=merged.get(),
            naming_mode=_label_to_key(NAMING_LABELS, naming.get()),
            force_redownload=app.settings.force_redownload,
            wrap=app.settings.wrap,
        )
        settings_email = app.settings.email
        settings_api_key = app.settings.api_key
        settings_proxy = app.settings.proxy

        def job(ctx):
            client = NcbiClient(email=settings_email, api_key=settings_api_key,
                                proxy=settings_proxy, log=app.log,
                                cancel=ctx.cancel_event)
            return client.download(accessions, options, progress=ctx.progress)

        app.run_job(job, on_done=on_done,
                    on_error=lambda e: (progress.reset(),
                                        app.log.error(f"下载失败: {e}")),
                    progress_handler=on_progress)

    start_button.configure(command=start)
    start_button.pack(side="right")
    # 按钮的禁用与恢复统一交给 App：标签页自己 app.after(...) 恢复会让任务仍在
    # 运行时按钮就变可点。
    app.register_busy_widget(start_button)
    return parent
