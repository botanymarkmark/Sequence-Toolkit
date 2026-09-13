"""③ 检索与批量下载：按物种名/属名检索 nuccore，勾选后批量下载。"""

from __future__ import annotations

import csv
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Iterable

from ..ncbi import (
    DownloadOptions,
    NcbiClient,
    SearchResult,
    SeqSummary,
)
from .tab_merge import NAMING_LABELS, _label_to_key
from .widgets import (
    CheckboxTable,
    FilePicker,
    ProgressPanel,
    format_download_summary,
    grid_row,
)

TITLE = "检索与批量下载"
RESULT_HEADINGS = ("Accession", "长度", "物种名", "定义行", "发布日期", "来源")
MAX_DISPLAY_ROWS = 5000
SCOPE_LABELS = {"species": "物种名", "genus": "属名"}

# 批量导出登录号：两个按钮的文字与后缀集中在这里，测试据常量定位按钮。
EXPORT_TXT_LABEL = "导出登录号 .txt…"
EXPORT_CSV_LABEL = "导出登录号 .csv…"

# 本次检索向 NCBI 索取的 id 上限。显式传进 search_summaries 而不是靠它的缺省值：
# 截断提示里的数字必须与实际请求的参数同源，否则改了缺省值提示就在撒谎。
SEARCH_RETMAX = 500


def truncation_notice(result: SearchResult, summaries: list[SeqSummary]) -> str:
    """命中数超过本次真正取回的条数时给出可操作的中文提示；未截断时返回空串。

    ``search_summaries`` 只为 esearch 返回的前 ``retmax``（这里固定传
    :data:`SEARCH_RETMAX`，默认 500）个 id 取元数据，因此按属名检索命中上千条时，
    本地筛选（长度区间、「只要完整基因组」）只发生在那前 500 条里。
    这时"筛后剩几条"是**静默截断**的结果，不是全部命中——必须显式说清楚，并给出缩小
    范围的具体办法，否则用户会以为筛后结果就是全部而漏掉数据。

    判据用 ``len(result.ids)`` 而不是 ``len(summaries)``：后者在"本地筛选恰好过滤掉
    若干条"时也会变小，但那是筛选本身的效果、不是截断，据此报警会误导用户。
    """
    fetched = len(result.ids)
    if result.total <= fetched:
        return ""
    kept = len(summaries)
    # 只在"确实取满了请求上限"时才提 retmax：否则 fetched 比上限小，说明本次请求
    # 本来就只拿到这么多个 id，提"最多 500 条"反而会把用户引到错误的猜测上。
    ceiling = (f"（单次检索最多取回 {SEARCH_RETMAX} 条 id）"
               if fetched >= SEARCH_RETMAX else "")
    return (f"检索命中 {result.total} 条，但只取回了前 {fetched} 条{ceiling}的元数据："
            f"本地筛选只在这 {fetched} 条里进行，筛后剩下的 {kept} 条来自被截断的首批，"
            f"不是全部命中。请用「序列长度」区间或「只要完整基因组」缩小检索范围，"
            f"把命中数降到 {fetched} 条以内再检索，或改用更精确的检索词。")


def rows_to_export(displayed: list[tuple],
                   checked: list[str]) -> tuple[list[tuple], str]:
    """决定导出哪些行：勾选了就只导出勾选的，否则导出表格显示的全部。

    返回 ``(行列表, 需要写进日志的说明)``。说明为空串表示"导出的正是用户勾选的那些"；
    非空时**必须**写进日志——否则用户看到 5000 行的导出文件，会以为导的是自己勾的那几条。

    以表格的显示顺序（而不是勾选顺序）输出：勾选顺序由点击先后决定，用户对照表格核对
    导出结果时会以为串行了。行键是首列（登录号），勾选集合也以它为键。
    """
    if checked:
        wanted = set(checked)
        return [row for row in displayed if str(row[0]) in wanted], ""
    return list(displayed), f"未勾选任何行，已导出表格显示的全部 {len(displayed)} 条"


def write_accessions_txt(out_path: str, rows: Iterable[tuple]) -> None:
    """一行一个登录号；utf-8（无 BOM）+ ``newline="\\n"``，与项目其余文本输出一致。"""
    with open(str(out_path), "wt", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(f"{row[0]}\n")


def write_accessions_csv(out_path: str, rows: Iterable[tuple]) -> None:
    """带表头导出，列与结果表格逐列对应。

    ``utf-8-sig`` 与 :meth:`RunLog.export_exceptions_csv` 同一先例：Excel 双击打开时
    靠 BOM 判定编码，否则中文物种名会变成乱码。
    """
    with open(str(out_path), "wt", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(RESULT_HEADINGS)
        for row in rows:
            writer.writerow([str(value) for value in row])


def _make_client(app, cancel_event) -> NcbiClient:
    return NcbiClient(
        email=app.settings.email,
        api_key=app.settings.api_key,
        proxy=app.settings.proxy,
        log=app.log,
        cancel=cancel_event,
    )


def build(parent: ttk.Frame, app) -> ttk.Frame:
    # 本函数里所有 Tk 变量都显式写 master=parent：不传 master 时 Variable 会挂到
    # tkinter 的 _default_root（进程里第一个根窗口）上，控件与变量就落在两个不同的
    # Tcl 解释器里——输入框里看得见"检索词已填"，而 get() 出来的仍是空串。

    criteria = ttk.LabelFrame(parent, text="检索条件")
    criteria.pack(fill="x", padx=8, pady=(8, 4))

    term = tk.StringVar(master=parent)
    entry = ttk.Entry(criteria, textvariable=term)
    grid_row(criteria, 0, "检索词", entry)

    scope = tk.StringVar(master=parent, value=SCOPE_LABELS["species"])
    row = ttk.Frame(criteria)
    grid_row(criteria, 1, "检索范围", row)
    for key, text in SCOPE_LABELS.items():
        ttk.Radiobutton(row, text=text, value=text,
                        variable=scope).pack(side="left", padx=(0, 12))

    minimum = tk.StringVar(master=parent, value="100000")
    maximum = tk.StringVar(master=parent, value="200000")
    row = ttk.Frame(criteria)
    grid_row(criteria, 2, "序列长度 (bp)", row)
    ttk.Label(row, text="下限").pack(side="left")
    ttk.Entry(row, textvariable=minimum, width=12).pack(side="left", padx=4)
    ttk.Label(row, text="上限").pack(side="left")
    ttk.Entry(row, textvariable=maximum, width=12).pack(side="left", padx=4)

    complete_only = tk.BooleanVar(master=parent, value=True)
    refseq_only = tk.BooleanVar(master=parent, value=False)
    row = ttk.Frame(criteria)
    grid_row(criteria, 3, "筛选", row)
    ttk.Checkbutton(row, text="只要完整基因组",
                    variable=complete_only).pack(side="left")
    ttk.Checkbutton(row, text="只要 RefSeq",
                    variable=refseq_only).pack(side="left", padx=(12, 0))

    search_button = ttk.Button(criteria, text="检索")
    grid_row(criteria, 4, "", search_button)

    results_box = ttk.LabelFrame(parent, text="检索结果")
    results_box.pack(fill="both", expand=True, padx=8, pady=4)
    table = CheckboxTable(results_box, ("accession", "length", "organism",
                                        "definition", "date", "source"),
                          RESULT_HEADINGS, (130, 90, 190, 420, 100, 90))
    table.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
    scroll = ttk.Scrollbar(results_box, orient="vertical", command=table.yview)
    scroll.pack(side="left", fill="y", pady=6)
    table.configure(yscrollcommand=scroll.set)

    selection_bar = ttk.Frame(parent)
    selection_bar.pack(fill="x", padx=8)
    counter = ttk.Label(selection_bar, text="已选 0 / 0 条")

    def update_counter() -> None:
        counter.configure(text=f"已选 {table.selection.count()} / "
                               f"{table.selection.total()} 条")

    table.bind_selection_change(update_counter)
    ttk.Button(selection_bar, text="全选",
               command=lambda: (table.selection.check_all(),
                                table.refresh_checks())).pack(side="left")
    ttk.Button(selection_bar, text="反选",
               command=lambda: (table.selection.invert(),
                                table.refresh_checks())).pack(side="left", padx=4)
    ttk.Button(selection_bar, text="清空勾选",
               command=lambda: (table.selection.uncheck_all(),
                                table.refresh_checks())).pack(side="left")
    counter.pack(side="left", padx=12)

    def do_export(extension: str, write) -> None:
        """把登录号导出到用户选定的文件。

        同步执行：行数上限就是表格显示上限（``MAX_DISPLAY_ROWS`` = 5000），是毫秒级
        操作，与 app.py 的「导出日志 / 导出异常清单」同一做法，不必走 run_job。
        """
        displayed = table.displayed_rows()
        if not displayed:
            app.log.warn("检索结果为空，没有可导出的登录号")
            return
        target = filedialog.asksaveasfilename(
            parent=parent,
            title="导出登录号",
            defaultextension=extension,
            filetypes=[(f"{extension.lstrip('.').upper()} 文件", f"*{extension}")],
        )
        if not target:
            return                       # 取消另存对话框：不写文件、也不记"已导出"
        rows, notice = rows_to_export(displayed, table.selection.checked_keys())
        try:
            write(target, rows)
        except OSError as error:
            # 磁盘满 / 路径被占：记 ERROR 即可，绝不让异常穿过 Tk 回调
            app.log.error(f"导出登录号失败: {error}")
            return
        if notice:
            app.log.info(notice)
        app.log.info(f"已导出 {len(rows)} 条登录号: {target}")

    export_txt = ttk.Button(selection_bar, text=EXPORT_TXT_LABEL,
                            command=lambda: do_export(".txt", write_accessions_txt))
    export_csv = ttk.Button(selection_bar, text=EXPORT_CSV_LABEL,
                            command=lambda: do_export(".csv", write_accessions_csv))
    export_txt.pack(side="right")
    export_csv.pack(side="right", padx=(0, 4))

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
    download_button = ttk.Button(action, text="下载勾选的序列")

    def on_progress(done: int, total: int, text: str) -> None:
        # 只由主线程的 App._drain 调用（后台线程一律经 ctx.progress 投队列），
        # 因此这里碰控件是安全的。
        if done == 0:
            progress.start(total)
        progress.update(done, total, text)

    def on_search_done(payload) -> None:
        result, summaries = payload
        # 表格行以 accession 作为唯一 iid，若出现重复 accession 会导致 TclError，
        # 因此展示前先按 accession 去重并保持原有顺序（CheckboxTable 内另有一道防线，
        # 那道防线会静默丢行，这里必须自己算并告警，用户才知道结果被动过）。
        seen: set[str] = set()
        unique: list[SeqSummary] = []
        for summary in summaries:
            if summary.accession and summary.accession not in seen:
                seen.add(summary.accession)
                unique.append(summary)
        dropped = len(summaries) - len(unique)
        if dropped:
            app.log.warn(f"检索结果里有 {dropped} 条重复登录号，已按 accession 去重后显示")
        fetched = len(result.ids)
        shown = unique[:MAX_DISPLAY_ROWS]
        table.set_rows([
            (s.accession, f"{s.length:,}", s.organism, s.definition,
             s.date, s.source_db) for s in shown
        ])
        update_counter()
        progress.finish(f"命中 {result.total} 条，取回 {fetched} 条，筛后 {len(unique)} 条")
        # 命中数超过本次取回元数据的条数 ⇒ NCBI 侧截断，本地筛选只覆盖了首批。
        notice = truncation_notice(result, unique)
        if notice:
            app.log.warn(notice)
        elif len(unique) > MAX_DISPLAY_ROWS:
            app.log.warn(f"结果过多，界面只显示前 {MAX_DISPLAY_ROWS} 条；"
                         f"请用长度区间或「只要完整基因组」缩小范围")
        app.log.info(f"检索完成：命中 {result.total} 条，取回元数据 {fetched} 条，"
                     f"本地筛选后 {len(unique)} 条，已显示 {len(shown)} 条")
        app.set_status(f"检索完成：命中 {result.total} 条，取回 {fetched} 条，"
                       f"筛选后 {len(unique)} 条")

    def do_search() -> None:
        text = term.get().strip()
        if not text:
            app.log.warn("请输入检索词")
            return
        if not app.settings.email:
            app.log.warn("请先在「设置」中填写 NCBI 邮箱（NCBI 的合规要求）")
            app.open_tab(4)
            return
        try:
            min_length = int(minimum.get()) if minimum.get().strip() else None
            max_length = int(maximum.get()) if maximum.get().strip() else None
        except ValueError:
            app.log.warn("长度区间必须是整数")
            return

        # 所有控件取值都在主线程取完快照：job 跑在后台线程里，读 Tk 变量同样是
        # 跨线程访问 Tcl。job 内不再触碰任何控件。
        scope_key = _label_to_key(SCOPE_LABELS, scope.get())
        complete_genome_only = complete_only.get()
        refseq_only_local = refseq_only.get()

        def job(ctx):
            client = _make_client(app, ctx.cancel_event)
            ctx.progress(0, 1, "正在检索")
            return client.search_summaries(
                text,
                scope=scope_key,
                retmax=SEARCH_RETMAX,
                min_length=min_length,
                max_length=max_length,
                complete_genome_only=complete_genome_only,
                refseq_only_local=refseq_only_local,
            )

        app.run_job(job, on_done=on_search_done,
                    on_error=lambda e: (progress.reset(),
                                        app.log.error(f"检索失败: {e}")))

    def on_download_done(report) -> None:
        summary = format_download_summary(report, per_sequence.get())
        progress.finish(summary)
        app.log.info(f"下载完成：{summary}")
        for path in (report.merged_fasta, report.merged_genbank):
            if path:
                app.log.info(f"合并产物：{path}")
        messagebox.showinfo(
            "下载完成",
            f"{summary}。\n输出目录：{report.out_dir}")

    def do_download() -> None:
        chosen = table.selection.checked_keys()
        if not chosen:
            app.log.warn("请先在结果表格中勾选要下载的序列")
            return
        target_dir = out_dir.path()
        if not target_dir:
            app.log.warn("请指定下载输出文件夹")
            return
        # 控件取值同样在主线程一次取完，job 内零控件调用。
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

        def job(ctx):
            client = _make_client(app, ctx.cancel_event)
            return client.download(chosen, options, progress=ctx.progress)

        app.run_job(job, on_done=on_download_done,
                    on_error=lambda e: (progress.reset(),
                                        app.log.error(f"下载失败: {e}")),
                    progress_handler=on_progress)

    search_button.configure(command=do_search)
    download_button.configure(command=do_download)
    download_button.pack(side="right")
    # 按钮的禁用与恢复统一交给 App：标签页自己 app.after(...) 恢复会让任务仍在
    # 运行时按钮就变可点。
    app.register_busy_widget(search_button)
    app.register_busy_widget(download_button)
    app.register_busy_widget(export_txt)
    app.register_busy_widget(export_csv)
    return parent
