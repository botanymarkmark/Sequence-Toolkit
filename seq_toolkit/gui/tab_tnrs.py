"""⑧ 物种名清洗：调用 TNRS 批量清洗学名，导出 CSV，可选回写序列文件。

所有网络动作都在后台线程执行（App.run_job + JobContext）；job 内不触碰任何 Tk 控件。
"""

from __future__ import annotations

# os / messagebox / FilePicker 由「应用到序列文件 / 打开输出文件夹」流程使用：改写输出
# 目录选择器（FilePicker）、完成提示框（messagebox）、os.startfile 打开产物。
# **不是**可以顺手清理的死导入——删掉会让后续任务多出一处与计划文本的无谓冲突。
# （ProgressPanel 由本页的进度条用上。）
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import tnrs
from ..tnrs import TnrsRow, summarize_status
from .widgets import CheckboxTable, FilePicker, ProgressPanel, grid_row

TITLE = "物种名清洗"
# 首列是序号（1 基、按结果顺序）：它同时是表格的行键。CheckboxTable 用首元素作 iid
# 并按 key 去重，序号天然唯一 ⇒ matches=all 时同一名称的多条候选一行都不会被丢掉。
RESULT_COLUMNS = ("index", "submitted", "accepted", "status", "score", "source", "warnings")
RESULT_HEADINGS = ("#", "原始名称", "接受名", "匹配状态", "得分", "来源数据库", "警告")
RESULT_WIDTHS = (45, 240, 240, 90, 70, 110, 260)
MATCHES_LABELS = {tnrs.MATCHES_BEST: "只取最佳匹配 (best)",
                  tnrs.MATCHES_ALL: "返回全部候选 (all)"}
SOURCES_LABELS = {"wcvp,wfo": "WCVP + WFO（推荐）", "wfo": "仅 WFO", "wcvp": "仅 WCVP"}


def _make_poster(app):
    """返回 ``post(payload) -> str``。测试会替换本函数以注入替身，绝不联网。"""
    def post(payload: dict) -> str:
        return tnrs.http_post(payload, proxy=app.settings.proxy)
    return post


def row_values(row: TnrsRow, index: int) -> tuple:
    """结果表一行的显示值。``index`` 是 1 基序号，同时充当表格行键。

    「警告」列合并 ``warnings`` 与 ``unmatched_terms``，与 ``tnrs.rows_to_csv`` 的
    备注列口径一致——只取前者会让"同时有英文告警与残留词"的行在表格里丢掉残留词，
    而导出的 CSV 里有，用户按表格复核时对不上。
    """
    score = "—" if row.score is None else f"{row.score:.2f}"
    notes = "；".join(part for part in (row.warnings, row.unmatched_terms) if part)
    return (str(index), row.submitted, row.accepted_name or "", row.status, score,
            row.source, notes)


def status_summary_text(rows: list[TnrsRow]) -> str:
    """顶部统计：名称数 → 结果行数，以及三态计数。``matches=all`` 时两者不等。"""
    counts = summarize_status(rows)
    names = len({row.row_id for row in rows})
    return (f"{names} 个名称 → {len(rows)} 行结果"
            f"（已匹配 {counts[tnrs.STATUS_MATCHED]}、"
            f"部分匹配 {counts[tnrs.STATUS_PARTIAL]}、"
            f"未匹配 {counts[tnrs.STATUS_UNMATCHED]}）")


def import_species_from_files(paths, settings, log=None) -> list[str]:
    """从 FASTA / GenBank 文件提取物种名（去重、保持顺序）。

    用 ``record.species_raw`` 而**不是** ``record.species``：后者是**下划线形态**
    （``Salsola_pellucida``，给文件名用的），拿它去 TNRS 查询匹配不上。

    ``log`` 非空时，读不动或格式不识别的文件逐个记 WARN——单个坏文件不该中断导入，
    但也**不该被静默丢掉**（与 ``ncbi.collect_accessions_from_files(..., log=None)``
    的既有约定一致）。**粒度同样是文件级**：单个文件里提不出物种名的记录按文件聚合记
    一条 WARN，绝不逐条刷屏，也绝不无声丢弃。
    """
    from ..fasta_io import read_fasta
    from ..format_detect import detect_format, list_input_files
    from ..genbank_io import read_genbank
    from ..naming import extract_species_from_header

    found: list[str] = []
    for path in list_input_files(list(paths), recursive=True,
                                 fasta_suffixes=settings.fasta_suffixes,
                                 genbank_suffixes=settings.genbank_suffixes):
        detected = detect_format(path)
        if detected not in ("fasta", "genbank"):
            if log is not None:
                log.warn(f"跳过无法识别格式的文件: {path}")
            continue
        try:
            producer = (read_genbank(path) if detected == "genbank"
                        else read_fasta(path))
            skipped = 0
            for record in producer:
                name = (record.species_raw or "").strip()
                if not name:
                    name, _warnings = extract_species_from_header(record.definition)
                if not name:
                    # 记录级静默同样是「绝不静默」禁止的：header 不规范的记录（例如
                    # ">12345 ..." 这种以数字开头的）拿不到物种名，若一声不响地跳过，
                    # 用户看到的"已导入 N 个"与实际文件内容对不上却无从解释。
                    # 按文件聚合记一条，而不是逐条刷屏。
                    skipped += 1
                    continue
                if name not in found:
                    found.append(name)
            if skipped and log is not None:
                log.warn(f"{path}: {skipped} 条记录未能提取物种名，已跳过")
        except Exception as error:  # noqa: BLE001 单个坏文件不中断导入
            if log is not None:
                log.warn(f"跳过无法读取的文件: {path}: {error}")
            continue
    return found


def build(parent: ttk.Frame, app) -> ttk.Frame:
    # 所有 Tk 变量显式传 master=parent（见 tab_search.py 的同一约定）。

    # 底部固定行（选择条 / 按钮条 / 提示 / 汇总）必须**最先** pack，并且用
    # side="bottom"：Tk 的 packer 按 pack 调用的先后分配空间，先调用的先拿到自己请求的
    # 高度，排在后面的只能分剩下的。本页内容请求高度是 797 px，而笔记本页在默认窗口
    # （1120x780）里只有 740 px，于是按「从上到下」的顺序 pack 时，最后这三行会被挤成
    # 1 px——实测四个按钮 mapped=0 / w=1 / h=1，用户在界面上**根本看不到「开始清洗」**。
    # 先从下往上占位之后，被压缩的变成可伸缩的输入框与结果表（两者自带滚动条），
    # 按钮条则任何窗口高度下都在。控件的创建仍留在下文原地，父容器先建好即可。
    selection_bar = ttk.Frame(parent)
    selection_bar.pack(side="bottom", fill="x", padx=8)
    action = ttk.Frame(parent)
    action.pack(side="bottom", fill="x", padx=8, pady=(4, 4))
    notes = ttk.Label(parent, text="", anchor="w", justify="left",
                      foreground="#a05000", wraplength=1000)
    notes.pack(side="bottom", fill="x", padx=12)
    summary = ttk.Label(parent, text="尚未清洗", anchor="w")
    summary.pack(side="bottom", fill="x", padx=12)

    source_box = ttk.LabelFrame(parent, text="物种名列表")
    source_box.pack(fill="both", expand=True, padx=8, pady=(8, 4))
    # 这一行是用户对"数据会离开本机"的唯一提示：本页把名称发给**线上**服务，光看
    # 「清洗」二字不足以让人知道要联网、也没法预判名称的写法要求（属名 + 种加词）。
    ttk.Label(source_box,
              text="每行一个学名（如 Salsola pellucida）；这些名称会提交给 TNRS "
                   "（Taxonomic Name Resolution Service）在线服务解析，需要联网。",
              anchor="w", justify="left",
              foreground="#606060").pack(fill="x", padx=6, pady=(6, 0))
    species_text = tk.Text(source_box, height=8, wrap="none")
    species_text.pack(fill="both", expand=True, padx=6, pady=(2, 2))

    # 导入按钮归本任务：它调用的 import_species_from_files 就是本模块的函数。
    # 其余按钮（开始清洗 / 导出 / 应用）由 A7、A8 加入。
    import_row = ttk.Frame(source_box)
    import_row.pack(fill="x", padx=6, pady=(0, 6))
    import_button = ttk.Button(import_row, text="从序列文件导入物种名")

    def do_import() -> None:
        chosen = filedialog.askopenfilenames(parent=parent, title="从序列文件导入物种名")
        if not chosen:
            return
        found = import_species_from_files(list(chosen), app.settings, log=app.log)
        if not found:
            app.log.warn("没有从所选文件中提取到物种名")
            return
        species_text.insert("end", "\n".join(found) + "\n")
        app.log.info(f"已从文件导入 {len(found)} 个物种名")

    import_button.configure(command=do_import)
    import_button.pack(side="left")

    options = ttk.LabelFrame(parent, text="清洗参数")
    options.pack(fill="x", padx=8, pady=4)
    # 下拉框的取值是**中文标签**，而设置里存的是协议键（"wcvp,wfo" / "best"）。
    # 直接把键塞进 StringVar，Combobox 会显示 "wcvp,wfo" 这种原始键，而且 do_clean
    # 里的反查（按标签找键）会 StopIteration 当场崩掉——因此这里必须把键翻成标签，
    # 并对设置里存了非法值的陈旧配置回退到默认项。
    sources = tk.StringVar(master=parent,
                           value=SOURCES_LABELS.get(app.settings.tnrs_sources,
                                                    SOURCES_LABELS["wcvp,wfo"]))
    matches = tk.StringVar(master=parent,
                           value=MATCHES_LABELS.get(app.settings.tnrs_matches,
                                                    MATCHES_LABELS[tnrs.MATCHES_BEST]))
    # 这两个变量必须活到界面销毁：tkinter 的 Variable 被回收时会 __del__ 掉它对应的
    # Tcl 变量，而控件只记住变量**名**。本任务里还没有任何回调闭包捕获它们（do_import
    # 用不到下拉框），不显式留引用的话 build 一返回就按引用计数被回收，两个下拉框建好
    # 就是**空白**的，A7 按标签反查键时还会在空串上 StopIteration 崩掉。挂在标签页容器
    # 上即可——控件的 Python 对象由父控件的 children 表持有，容器与界面同生命周期。
    parent.tnrs_vars = (sources, matches)
    grid_row(options, 0, "名录来源",
             ttk.Combobox(options, textvariable=sources, state="readonly",
                          values=list(SOURCES_LABELS.values())))
    grid_row(options, 1, "匹配模式",
             ttk.Combobox(options, textvariable=matches, state="readonly",
                          values=list(MATCHES_LABELS.values())))
    ttk.Label(options, text="每批最多 5000 个名称（实测服务端硬上限），超出会自动分批",
              foreground="#606060").grid(row=2, column=1, sticky="w", padx=(0, 8))
    # 改写输出目录用**常驻**的 FilePicker，而不是在 do_apply 里临时弹目录框：用户要
    # 反复改写多批文件时，每次重选目录是纯摩擦。do_apply 与 do_open_dir 共用这一个控件。
    out_dir_picker = FilePicker(options, mode="directory", title="改写输出文件夹")
    out_dir_picker.set_path(app.settings.output_dir)
    grid_row(options, 3, "改写输出文件夹", out_dir_picker)

    result_box = ttk.LabelFrame(parent, text="清洗结果")
    result_box.pack(fill="both", expand=True, padx=8, pady=4)
    table = CheckboxTable(result_box, RESULT_COLUMNS, RESULT_HEADINGS, RESULT_WIDTHS)
    table.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
    scroll = ttk.Scrollbar(result_box, orient="vertical", command=table.yview)
    scroll.pack(side="left", fill="y", pady=6)
    table.configure(yscrollcommand=scroll.set)

    # 下面这些控件的父容器（action / selection_bar / notes / summary）已在 build 开头
    # 创建并占好了底部位置，理由见那里的注释：底部固定行必须先 pack 才不会被挤没。
    progress = ProgressPanel(action)
    progress.pack(side="left", fill="x", expand=True)
    clean_button = ttk.Button(action, text="开始清洗")
    export_button = ttk.Button(action, text="导出 CSV")
    apply_button = ttk.Button(action, text="应用到序列文件")
    open_button = ttk.Button(action, text="打开输出文件夹")

    counter = ttk.Label(selection_bar, text="已选 0 / 0 行")

    def update_counter() -> None:
        counter.configure(text=f"已选 {table.selection.count()} / "
                               f"{table.selection.total()} 行")

    table.bind_selection_change(update_counter)

    rows_holder: dict[str, list[TnrsRow]] = {"rows": []}

    def on_progress(done: int, total: int, text: str) -> None:
        # clean_names 在**空输入**时也会发一次 on_progress(0, 0, ...)：total 是 0，
        # 自己算 done / total 会当场 ZeroDivisionError。按 total 起条即可——
        # ProgressPanel.start 内部已有 max(total, 1) 兜底。
        if done == 0:
            progress.start(total)
        progress.update(done, total, text)

    def on_clean_done(report) -> None:
        rows_holder["rows"] = list(report.rows)
        table.set_rows([row_values(row, index)
                        for index, row in enumerate(report.rows, start=1)])
        update_counter()
        summary.configure(text=status_summary_text(list(report.rows)))
        progress.finish(f"完成 {report.batches} 批")
        notices: list[str] = []
        unmatched = report.unmatched_names
        if unmatched:
            head = "、".join(unmatched[:5]) + ("…" if len(unmatched) > 5 else "")
            notices.append(f"未匹配 {len(unmatched)} 个名称：{head}")
            app.log.warn(notices[-1])
        for index, reason in report.failures:
            notices.append(f"第 {index} 批失败：{reason}")
            app.log.error(notices[-1])
        # 批次对账的**另一半**：单批失败进 failures，而"提交 N 个名称、只回来 M 行"
        # （服务端丢行，或响应里混进非对象元素被 parse_response 跳过）不进 failures。
        # 只报 failures 的话，这类缺口表现为"结果比输入少几行"而界面上找不到任何
        # 解释——「绝不静默」在界面层被打折。两级（批次号 + 两个计数）都要露出来。
        for index, submitted, returned in report.mismatched_batches:
            notices.append(f"第 {index} 批提交 {submitted} 个名称、只返回 {returned} 行")
            app.log.warn(notices[-1])
        # 冲突取自 conflicting_names(report.rows)，**不是** RenameOutcome.conflicts：
        # 后者的 conflicts 在 A4 恒为空，用它这条提示永远也不会出现。
        conflicts = tnrs.conflicting_names(report.rows)
        if conflicts:
            detail = "；".join(f"{name} → {'/'.join(values)}"
                              for name, values in list(conflicts.items())[:3])
            notices.append(f"{len(conflicts)} 个名称有多个不同候选（回写时取第一条）：{detail}")
            app.log.warn(notices[-1])
        notes.configure(text="　".join(notices))
        app.log.info(f"清洗完成：{status_summary_text(list(report.rows))}")
        app.set_status(f"清洗完成：{len(report.rows)} 行")

    def do_clean() -> None:
        raw = species_text.get("1.0", "end").splitlines()
        names = tnrs.dedupe_names(raw)
        if not names:
            app.log.warn("请输入至少一个物种名")
            return
        # 控件取值在主线程一次取完；job 内零控件调用。
        chosen_sources = next(key for key, label in SOURCES_LABELS.items()
                              if label == sources.get())
        chosen_matches = next(key for key, label in MATCHES_LABELS.items()
                              if label == matches.get())

        def job(ctx):
            poster = _make_poster(app)
            return tnrs.clean_names(poster, names, sources=chosen_sources,
                                    matches=chosen_matches,
                                    on_progress=ctx.progress,
                                    cancel=ctx.cancel_event)

        app.run_job(job, on_done=on_clean_done,
                    on_error=lambda error: (progress.reset(),
                                            app.log.error(f"清洗失败: {error}")),
                    progress_handler=on_progress)

    def do_export() -> None:
        rows = rows_holder["rows"]
        if not rows:
            app.log.warn("还没有清洗结果可导出")
            return
        chosen = table.selection.checked_keys()
        # 说明留到**写成功之后**再记：用户在另存框点取消、或磁盘满导致写出失败时，
        # 先记"已导出"就是让日志说谎（tab_search 的导出亦为此把 notice 推迟到写出之后）。
        note = ""
        if chosen:
            # 勾选键就是序号（1 基），据此从结果里取回对应的 TnrsRow。判定用 isdecimal()
            # 而不是 isdigit()：后者对 "²" 这类上标数字返回 True，int() 却会抛 ValueError。
            indexes = sorted(int(key) for key in chosen if str(key).isdecimal())
            selected = [rows[index - 1] for index in indexes
                        if 1 <= index <= len(rows)]
        else:
            selected = list(rows)
            note = f"未勾选任何行，已导出表格显示的全部 {len(selected)} 行"
        target = filedialog.asksaveasfilename(
            parent=parent, title="导出清洗结果", defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")])
        if not target:
            # 取消另存对话框：不写文件、也不记"已导出"
            return
        try:
            tnrs.write_csv(target, selected)
        except OSError as error:
            app.log.error(f"导出失败: {error}")
            return
        if note:
            app.log.info(note)
        app.log.info(f"已导出 {len(selected)} 行到 {target}")

    def do_apply() -> None:
        rows = rows_holder["rows"]
        if not rows:
            app.log.warn("还没有清洗结果可应用")
            return
        chosen = table.selection.checked_keys()
        if chosen:
            indexes = sorted(int(key) for key in chosen if str(key).isdecimal())
            selected = [rows[index - 1] for index in indexes
                        if 1 <= index <= len(rows)]
        else:
            selected = list(rows)
        # 「部分匹配」的行**也会**被改名（取它的接受名）：规格 FR-1.6 只排除「未匹配」。
        # 用户不知道这件事，就会对"某个名字为什么被改成了不完全等于它的接受名"
        # 莫名其妙。这不是可选项，是回写前的必要交代。
        partial = sum(1 for row in selected if row.status == tnrs.STATUS_PARTIAL)
        if partial:
            app.log.warn(f"{partial} 行是部分匹配，其接受名将一并写入（规格只排除未匹配）")
        mapping = tnrs.build_rename_map(selected)
        if not mapping:
            app.log.warn("勾选的行里没有可用的接受名（可能全是未匹配）")
            return
        paths = filedialog.askopenfilenames(
            parent=parent, title="选择要改写的 FASTA / GenBank 文件")
        if not paths:
            return
        # 控件取值在主线程一次取完；job 内零控件调用。**不能**在 job 里读
        # `out_dir_picker.path()`：那是在后台线程里读 Tk 变量，App 不在 mainloop 时
        # _tkinter 直接抛 RuntimeError("main thread is not in main loop")，整个 job
        # 当场失败——「点了按钮什么都没写出来」且日志里只有一行毫不相干的报错。
        # 下面是**字符串快照**（不是控件）；on_apply_done 也用它，保证弹窗报出的目录
        # 就是文件真正写入的目录（运行中改写选择器不会让提示与实际产物对不上）。
        out_dir = out_dir_picker.path()
        if not out_dir:
            # 与 tab_search / tab_accession 的既有口径一致：默认设置里 output_dir 就是
            # 空串，不拦的话每个文件都在 os.makedirs("") 处失败，逐个记 ERROR 之后
            # 弹窗还会说"已处理 0 个文件、替换 0 处"——把一次全批失败报成了成功。
            app.log.warn("请先指定改写输出文件夹")
            return
        # 文件 IO 是耗时操作（大文件可能很慢），同样走后台线程。
        def job(ctx):
            outcomes = []
            for path in paths:
                ctx.raise_if_cancelled()
                try:
                    outcomes.append(tnrs.apply_names_to_file(
                        path, mapping, out_dir, log=app.log))
                # 这里必须是 Exception 而不是只捕 SeqToolkitError：
                # apply_names_to_file 的 IO 失败（FileNotFoundError、
                # NotADirectoryError 等）抛的是**裸 OSError**，它不是 SeqToolkitError
                # 的子类，只捕后者会让单个文件失败中断整批。log 必须显式传：
                # 不传的话"目标文件已存在时让位 _1 并记 WARN"会静默失效（默认 None）。
                except Exception as error:  # noqa: BLE001 单文件失败不中断整批
                    app.log.error(f"改写失败，已跳过: {path}: {error}")
            return outcomes

        def on_apply_done(outcomes) -> None:
            total = sum(outcome.replacements for outcome in outcomes)
            missing = sorted({name for outcome in outcomes for name in outcome.missing})
            app.log.info(f"已改写 {len(outcomes)} 个文件，共替换 {total} 处，"
                         f"输出到 {out_dir}")
            if missing:
                app.log.warn(f"以下 {len(missing)} 个名称在文件里未找到："
                             f"{'、'.join(missing[:5])}")
            messagebox.showinfo("改写完成",
                                f"已处理 {len(outcomes)} 个文件，替换 {total} 处。\n"
                                f"输出：{out_dir}")

        app.run_job(job, on_done=on_apply_done,
                    on_error=lambda error: app.log.error(f"改写失败: {error}"))

    def do_open_dir() -> None:
        target = out_dir_picker.path()
        if not target:
            app.log.warn("请先指定输出文件夹")
            return
        try:
            os.startfile(target)  # noqa: S606 Windows 专用
        except OSError as error:
            app.log.error(f"无法打开文件夹: {error}")

    clean_button.configure(command=do_clean)
    export_button.configure(command=do_export)
    apply_button.configure(command=do_apply)
    open_button.configure(command=do_open_dir)
    clean_button.pack(side="right")
    export_button.pack(side="right", padx=4)
    apply_button.pack(side="right", padx=4)
    open_button.pack(side="right", padx=4)
    ttk.Button(selection_bar, text="全选",
               command=lambda: (table.selection.check_all(),
                                table.refresh_checks())).pack(side="left")
    ttk.Button(selection_bar, text="反选",
               command=lambda: (table.selection.invert(),
                                table.refresh_checks())).pack(side="left", padx=4)
    counter.pack(side="left", padx=12)
    app.register_busy_widget(clean_button)
    app.register_busy_widget(export_button)
    app.register_busy_widget(apply_button)

    return parent
