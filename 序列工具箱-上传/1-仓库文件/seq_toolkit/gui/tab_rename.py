"""② 重命名 / 拆分：改 `>` 行序列名、按序列名拆成单文件、重命名磁盘文件。"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..fasta_io import read_fasta
from ..format_detect import detect_format, list_input_files
from ..genbank_io import read_genbank
from ..pipeline import ProcessPlan, rename_disk_files, run_merge, split_records
from .tab_merge import NAMING_LABELS, _label_to_key
from .widgets import FilePicker, ProgressPanel, grid_row

TITLE = "重命名 / 拆分"

PREVIEW_LIMIT = 50


def _is_within(path: str, folder: str) -> bool:
    """path 是否位于 folder 之内（folder 自身也算）。"""
    if not path or not folder:
        return False
    try:
        return os.path.commonpath([os.path.abspath(path),
                                   os.path.abspath(folder)]) == os.path.abspath(folder)
    except ValueError:
        # Windows 下不同盘符会让 commonpath 抛 ValueError：二者不可能互相包含。
        return False


def _output_dir_overlaps_inputs(split_dir: str, inputs) -> bool:
    """拆分输出目录与任一输入路径是否互相包含（任一方向）。"""
    return any(_is_within(split_dir, item) or _is_within(item, split_dir)
               for item in inputs)


def _canonical(path: str) -> str:
    """用于比较的路径：绝对化并统一大小写（Windows 下路径比较不分大小写）。"""
    return os.path.normcase(os.path.abspath(path))


def build(parent: ttk.Frame, app) -> ttk.Frame:
    inputs: list[str] = []
    # 本函数里所有 Tk 变量都显式写 master=parent：不传 master 时 Variable 会挂到
    # tkinter 的 _default_root（进程里第一个根窗口）上。若本进程还存在别的 Tk 根窗口，
    # 控件与本变量就落在两个不同的 Tcl 解释器里——勾选框点一下，控件自己的变量变成
    # "1"，而这里 get() 出来仍是旧值，界面显示与程序读到的状态静默不一致。

    source_box = ttk.LabelFrame(parent, text="源文件与文件夹")
    source_box.pack(fill="both", expand=False, padx=8, pady=(8, 4))
    listing = tk.Listbox(source_box, height=6, selectmode="extended")
    listing.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
    scroll = ttk.Scrollbar(source_box, orient="vertical", command=listing.yview)
    scroll.pack(side="left", fill="y", pady=6)
    listing.configure(yscrollcommand=scroll.set)

    side = ttk.Frame(source_box)
    side.pack(side="left", fill="y", padx=6, pady=6)
    recursive = tk.BooleanVar(master=parent, value=True)

    def refresh_listing() -> None:
        listing.delete(0, "end")
        for path in inputs:
            listing.insert("end", path)

    def add_files() -> None:
        chosen = filedialog.askopenfilenames(title="选择序列文件")
        if chosen:
            inputs.extend(str(p) for p in chosen)
            refresh_listing()

    def add_folder() -> None:
        chosen = filedialog.askdirectory(title="选择文件夹")
        if chosen:
            inputs.append(chosen)
            refresh_listing()

    def clear_all() -> None:
        inputs.clear()
        refresh_listing()

    ttk.Button(side, text="添加文件…", command=add_files).pack(fill="x", pady=2)
    ttk.Button(side, text="添加文件夹…", command=add_folder).pack(fill="x", pady=2)
    ttk.Button(side, text="清空", command=clear_all).pack(fill="x", pady=2)
    ttk.Checkbutton(side, text="含子文件夹", variable=recursive).pack(fill="x", pady=(6, 2))

    options = ttk.LabelFrame(parent, text="操作（可任意组合）")
    options.pack(fill="x", padx=8, pady=4)

    naming = tk.StringVar(master=parent, value=NAMING_LABELS["accession_species"])
    combo = ttk.Combobox(options, textvariable=naming, state="readonly",
                         values=list(NAMING_LABELS.values()))
    grid_row(options, 0, "命名规则", combo)

    rewrite_headers = tk.BooleanVar(master=parent, value=True)
    split_files = tk.BooleanVar(master=parent, value=False)
    rename_disk = tk.BooleanVar(master=parent, value=False)
    row = ttk.Frame(options)
    grid_row(options, 1, "操作", row)
    ttk.Checkbutton(row, text="改写 > 行序列名", variable=rewrite_headers).pack(side="left")
    ttk.Checkbutton(row, text="按序列名拆分为单文件",
                    variable=split_files).pack(side="left", padx=(10, 0))
    ttk.Checkbutton(row, text="重命名已有磁盘文件",
                    variable=rename_disk).pack(side="left", padx=(10, 0))

    rewritten_picker = FilePicker(options, mode="save", title="改写后的输出文件",
                                  filetypes=[("序列文件", "*.fasta *.fa *.gb *.gbk")])
    grid_row(options, 2, "输出文件", rewritten_picker)

    split_dir_picker = FilePicker(options, mode="directory", title="拆分输出文件夹")
    grid_row(options, 3, "拆分输出目录", split_dir_picker)

    output_format = tk.StringVar(master=parent, value="fasta")
    row = ttk.Frame(options)
    grid_row(options, 4, "输出格式", row)
    ttk.Radiobutton(row, text="FASTA", value="fasta",
                    variable=output_format).pack(side="left")
    ttk.Radiobutton(row, text="GenBank", value="genbank",
                    variable=output_format).pack(side="left", padx=(10, 0))

    action = ttk.Frame(parent)
    action.pack(fill="x", padx=8, pady=(4, 8))
    progress = ProgressPanel(action)
    progress.pack(side="left", fill="x", expand=True)
    preview_button = ttk.Button(action, text="预览改名对照表")
    start_button = ttk.Button(action, text="开始处理")

    def on_progress(done: int, total: int, text: str) -> None:
        # 只由主线程的 App._drain 调用；后台任务统一经 ctx.progress 投递消息。
        if done == 0:
            progress.start(total)
        progress.update(done, total, text)

    def run_preview() -> None:
        if not inputs:
            app.log.warn("请先添加源文件或文件夹")
            return

        # 控件取值在主线程取完：job 跑在后台线程，读 Tk 变量同样不安全。
        mode = _label_to_key(NAMING_LABELS, naming.get())
        recursive_flag = recursive.get()

        def show_preview(plan) -> None:
            if not plan.pairs:
                messagebox.showinfo("预览", "没有可改名的文件。")
                return
            lines = [f"{old}\n  → {new}" for old, new in plan.pairs[:PREVIEW_LIMIT]]
            if len(plan.pairs) > PREVIEW_LIMIT:
                lines.append(f"…… 其余 {len(plan.pairs) - PREVIEW_LIMIT} 个文件省略")
            if plan.conflicts:
                # conflicts 记的是"被迫改用带序号名称的文件自己"，且不保证是 pairs
                # 的子集，所以只报个数，不做 len(pairs) - len(conflicts) 之类的算术。
                lines.append(f"其中 {len(plan.conflicts)} 个文件的目标名已被占用，"
                             f"将改用带序号名称（见预览中的 _1、_2）")
            messagebox.showinfo("改名预览（尚未执行）", "\n\n".join(lines))

        def on_preview_error(error: BaseException) -> None:
            app.log.error(f"预览失败: {error}")

        def job(ctx):
            # 预览要读每个文件的头部，文件多时同样会阻塞界面，因此也走后台线程。
            return rename_disk_files(
                list(inputs),
                naming_mode=mode,
                recursive=recursive_flag,
                dry_run=True,
                log=app.log,
            )

        app.run_job(job, on_done=show_preview, on_error=on_preview_error)

    def on_done(summary: str) -> None:
        progress.finish("完成")
        app.log.info(summary)
        app.set_status(summary)

    def on_error(error: BaseException) -> None:
        progress.reset()
        app.log.error(f"处理失败: {error}")

    def start() -> None:
        if not inputs:
            app.log.warn("请先添加源文件或文件夹")
            return
        mode = _label_to_key(NAMING_LABELS, naming.get())
        want_rewrite = rewrite_headers.get()
        want_split = split_files.get()
        want_disk = rename_disk.get()
        target = rewritten_picker.path()
        split_dir = split_dir_picker.path()
        # 同上：全部控件取值在主线程完成，job 内只使用这些快照。
        recursive_flag = recursive.get()
        fmt = output_format.get()
        suffix_hint = (app.settings.fasta_suffixes, app.settings.genbank_suffixes)
        wrap_hint = app.settings.wrap

        if want_rewrite and not target:
            app.log.warn("勾选「改写 > 行序列名」时必须指定输出文件")
            return
        if want_split and not split_dir:
            app.log.warn("勾选「按序列名拆分为单文件」时必须指定拆分输出目录")
            return

        def job(ctx):
            parts: list[str] = []
            # 本作业本次真正写出的产物路径。后续的拆分步骤必须把它们排除在输入之外，
            # 否则就是自己读自己的产出（改写产物的 header 是渲染后的名称，回读后登录号
            # 与源文件已经不同，按登录号去重救不了它）。
            products: set[str] = set()
            if want_rewrite:
                ctx.progress(0, 2, "改写序列名")
                result = run_merge(ProcessPlan(
                    inputs=list(inputs), output_path=target,
                    output_format=fmt, input_format="auto",
                    naming_mode=mode, dedup="accession",
                    recursive=recursive_flag, log=app.log,
                    progress=None, cancel=ctx.cancel_event,
                    # 与同页的拆分路径、以及 T21 一样，必须显式传这两项：
                    # 不传就一直用 ProcessPlan 的默认后缀表，「设置」页里自定义的后缀名
                    # 在这一页被静默忽略（list_input_files 认不出 .myfa 之类的文件，
                    # 表现是"文件明明在那儿却被当成未知格式跳过"，日志里一个字都没有）。
                    fasta_suffixes=suffix_hint[0],
                    genbank_suffixes=suffix_hint[1],
                    # wrap 同理：FASTA 每行长度也是「设置」页里的用户配置。
                    wrap=wrap_hint,
                ))
                # 记实际落点而非请求的目标名：目标已存在时 run_merge 会写到 _1。
                products.add(_canonical(result.output_path))
                parts.append(f"改写 {result.records_out} 条 → {result.output_path}")

            if want_disk:
                ctx.progress(1, 2, "重命名磁盘文件")
                plan = rename_disk_files(list(inputs), naming_mode=mode,
                                         recursive=recursive_flag, dry_run=False,
                                         log=app.log)
                parts.append(f"磁盘改名 {plan.renamed} 个文件")

            if want_split:
                ctx.progress(1, 2, "拆分序列")
                if _output_dir_overlaps_inputs(split_dir, inputs):
                    # 这是"越跑越多"的直接原因：上一次拆出来的产物就躺在输入文件夹里，
                    # 下一次运行会被一并当成新的输入再拆一遍。必须明确告知，否则用户
                    # 只会看到产物莫名其妙地翻倍。
                    app.log.warn(f"拆分输出目录在输入目录内，重复运行会把上一次的产物"
                                 f"当作输入：{split_dir}")
                files = [
                    path for path in list_input_files(
                        list(inputs), recursive=recursive_flag,
                        fasta_suffixes=suffix_hint[0],
                        genbank_suffixes=suffix_hint[1])
                    # 精确排除本次的输出：拆分输出目录内的文件（含上一次留下的产物），
                    # 以及本作业刚写出的改写产物。否则就是自己读自己产出的文件——
                    # 同一条序列会被拆成两个文件，重复运行还会越跑越多。
                    if not _is_within(path, split_dir)
                    and _canonical(path) not in products
                ]
                records = []
                for path in files:
                    file_format = detect_format(path)
                    if file_format == "genbank":
                        records.extend(read_genbank(path))
                    elif file_format == "fasta":
                        records.extend(read_fasta(path))
                result = split_records(records, split_dir, naming_mode=mode,
                                       output_format=fmt, log=app.log)
                # 报的是实际写出的文件数：records 里可能含被去重的重复记录，
                # 用 len(records) 会报出一个磁盘上并不存在的文件数。
                text = f"拆分出 {result.records_out} 个文件 → {split_dir}"
                if result.duplicates_removed:
                    text += f"（去重 {result.duplicates_removed} 条）"
                parts.append(text)

            return "；".join(parts) if parts else "未选择任何操作"

        app.run_job(job, on_done=on_done, on_error=on_error,
                    progress_handler=on_progress)

    preview_button.configure(command=run_preview)
    preview_button.pack(side="right", padx=(0, 6))
    start_button.configure(command=start)
    start_button.pack(side="right")
    # 禁用与恢复统一交给 App；预览同样会占用后台任务，所以它一并注册。
    app.register_busy_widget(preview_button)
    app.register_busy_widget(start_button)
    return parent
