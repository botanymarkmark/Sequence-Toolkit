"""① 合并 / 转换：把"合并 FASTA""合并 GenBank""GenBank 转 FASTA"做成一件事。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk

from ..pipeline import ConvertPlan, ProcessPlan, convert_each_file, run_merge
from .widgets import FilePicker, ProgressPanel, grid_row

TITLE = "合并 / 转换"
FORMAT_LABELS = {"auto": "自动识别", "fasta": "强制 FASTA", "genbank": "强制 GenBank"}
NAMING_LABELS = {
    "keep": "不改名（保留原始序列名）",
    "accession": "登录号",
    "species": "物种名",
    "accession_species": "登录号_物种名",
}
DEDUP_LABELS = {"accession": "按登录号去重", "none": "不去重"}
OUTPUT_LABELS = {"fasta": "FASTA", "genbank": "GenBank"}
# 用户使用后新增的输出方式：默认仍是「合并为单个文件」（原有行为），
# 新增「每个输入文件各输出一个文件」——GenBank 批量转 FASTA 时需要一批文件而不是
# 一个合并的大文件。
OUTPUT_MODE_LABELS = {
    "merge": "合并为单个文件",
    "per_file": "每个输入文件各输出一个文件",
}


def _label_to_key(labels: dict, text: str) -> str:
    for key, value in labels.items():
        if value == text:
            return key
    raise KeyError(text)


def build(parent: ttk.Frame, app) -> ttk.Frame:
    inputs: list[str] = []
    # 本函数里所有 Tk 变量都显式写 master=parent：不传 master 时 Variable 会挂到
    # tkinter 的 _default_root（进程里第一个根窗口）上。若本进程还存在别的 Tk 根窗口，
    # 控件与本变量就落在两个不同的 Tcl 解释器里——勾选框点一下，控件自己的变量变成
    # "1"，而这里 get() 出来仍是旧值，界面显示与程序读到的状态静默不一致。

    # ---------- 输入 ----------
    input_box = ttk.LabelFrame(parent, text="输入文件与文件夹")
    input_box.pack(fill="both", expand=False, padx=8, pady=(8, 4))

    listing = tk.Listbox(input_box, height=6, selectmode="extended")
    listing.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
    scroll = ttk.Scrollbar(input_box, orient="vertical", command=listing.yview)
    scroll.pack(side="left", fill="y", pady=6)
    listing.configure(yscrollcommand=scroll.set)

    side = ttk.Frame(input_box)
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

    def remove_selected() -> None:
        for index in sorted(listing.curselection(), reverse=True):
            del inputs[index]
        refresh_listing()

    def clear_all() -> None:
        inputs.clear()
        refresh_listing()

    ttk.Button(side, text="添加文件…", command=add_files).pack(fill="x", pady=2)
    ttk.Button(side, text="添加文件夹…", command=add_folder).pack(fill="x", pady=2)
    ttk.Button(side, text="移除选中", command=remove_selected).pack(fill="x", pady=2)
    ttk.Button(side, text="清空", command=clear_all).pack(fill="x", pady=2)
    ttk.Checkbutton(side, text="含子文件夹", variable=recursive).pack(fill="x", pady=(6, 2))

    # ---------- 选项 ----------
    options = ttk.LabelFrame(parent, text="处理选项")
    options.pack(fill="x", padx=8, pady=4)

    input_format = tk.StringVar(master=parent, value=FORMAT_LABELS["auto"])
    row = ttk.Frame(options)
    grid_row(options, 0, "输入类型", row)
    for key, text in FORMAT_LABELS.items():
        ttk.Radiobutton(row, text=text, value=text,
                        variable=input_format).pack(side="left", padx=(0, 10))

    output_format = tk.StringVar(master=parent, value=OUTPUT_LABELS["fasta"])
    row = ttk.Frame(options)
    grid_row(options, 1, "输出格式", row)
    for key, text in OUTPUT_LABELS.items():
        ttk.Radiobutton(row, text=text, value=text,
                        variable=output_format).pack(side="left", padx=(0, 10))

    output_mode = tk.StringVar(master=parent, value=OUTPUT_MODE_LABELS["merge"])
    output_mode_row = ttk.Frame(options)
    output_mode_buttons = []
    grid_row(options, 2, "输出方式", output_mode_row)

    def _current_mode() -> str:
        return _label_to_key(OUTPUT_MODE_LABELS, output_mode.get())

    def _on_output_mode_change() -> None:
        """输出方式单选变化时，把输出选择器切换成对应的类型。

        目录模式必须让「浏览…」真的弹目录对话框：只改标签文字而留一个"另存为"
        对话框，用户选不到目录，只能手打路径。
        """
        if _current_mode() == "per_file":
            output_label.configure(text="输出目录")
            output_picker.set_mode("directory", title="输出目录")
        else:
            output_label.configure(text="输出文件")
            output_picker.set_mode("save", title="选择输出文件")

    for key, text in OUTPUT_MODE_LABELS.items():
        button = ttk.Radiobutton(output_mode_row, text=text, value=text,
                                 variable=output_mode, command=_on_output_mode_change)
        button.pack(side="left", padx=(0, 10))
        output_mode_buttons.append(button)

    naming = tk.StringVar(master=parent, value=NAMING_LABELS["keep"])
    combo = ttk.Combobox(options, textvariable=naming, state="readonly",
                         values=list(NAMING_LABELS.values()))
    grid_row(options, 3, "命名规则", combo)

    dedup = tk.StringVar(master=parent, value=DEDUP_LABELS["accession"])
    combo = ttk.Combobox(options, textvariable=dedup, state="readonly",
                         values=list(DEDUP_LABELS.values()))
    grid_row(options, 4, "重复序列", combo)

    output_picker = FilePicker(options, mode="save", title="选择输出文件",
                               filetypes=[("序列文件", "*.fasta *.fa *.gb *.gbk"),
                                          ("全部文件", "*.*")])
    output_label = grid_row(options, 5, "输出文件", output_picker)

    wrap = tk.IntVar(master=parent, value=app.settings.wrap)
    row = ttk.Frame(options)
    grid_row(options, 6, "FASTA 换行", row)
    ttk.Radiobutton(row, text="不换行", value=0, variable=wrap).pack(side="left")
    for width in (60, 70, 80):
        ttk.Radiobutton(row, text=str(width), value=width,
                        variable=wrap).pack(side="left", padx=(8, 0))

    # ---------- 执行 ----------
    action = ttk.Frame(parent)
    action.pack(fill="x", padx=8, pady=(4, 8))
    progress = ProgressPanel(action)
    progress.pack(side="left", fill="x", expand=True)
    start_button = ttk.Button(action, text="开始处理")

    def on_progress(done: int, total: int, text: str) -> None:
        # 本函数只由主线程的 App._drain 调用：后台线程一律经 ctx.progress 投递消息，
        # 因此这里碰控件是安全的（进度条只能由主线程更新）。
        if done == 0:
            progress.start(total)
        progress.update(done, total, text)

    def on_done(result) -> None:
        progress.finish(f"完成：写出 {result.records_out} 条")
        app.log.info(f"输出文件：{result.output_path}")
        app.set_status(f"完成，输出 {result.output_path}")

    def on_error(error: BaseException) -> None:
        progress.reset()
        app.log.error(f"处理失败: {error}")

    def start() -> None:
        if not inputs:
            app.log.warn("请先添加输入文件或文件夹")
            return
        per_file = _current_mode() == "per_file"
        target = output_picker.path()
        if not target:
            # 两种输出方式的校验口径不同：批量模式的产物是一批文件，
            # 要的是目录；合并模式要的是那一个输出文件。
            app.log.warn("请先指定输出目录" if per_file else "请先指定输出文件")
            return

        # 所有控件取值都在主线程一次取完：job 跑在后台线程里，读 Tk 变量同样是
        # 跨线程访问 Tcl。取值快照传进去，job 内不再触碰任何控件。
        common = dict(
            inputs=list(inputs),
            output_format=_label_to_key(OUTPUT_LABELS, output_format.get()),
            input_format=_label_to_key(FORMAT_LABELS, input_format.get()),
            naming_mode=_label_to_key(NAMING_LABELS, naming.get()),
            dedup=_label_to_key(DEDUP_LABELS, dedup.get()),
            recursive=recursive.get(),
            wrap=wrap.get(),
            # 必须来自 app.settings：否则「设置」页里自定义的后缀名不会生效。
            fasta_suffixes=app.settings.fasta_suffixes,
            genbank_suffixes=app.settings.genbank_suffixes,
        )

        def done(result) -> None:
            if per_file:
                # 批量模式的产物单位是文件：摘要必须按"转换了几个文件"来报，
                # 否则用户会拿合并模式的条数去核对磁盘上的文件个数。
                progress.finish(f"完成：转换 {result.records_out} 个文件")
                app.log.info(f"输出目录：{result.output_path}")
                app.set_status(f"完成，转换 {result.records_out} 个文件 → "
                               f"{result.output_path}")
            else:
                on_done(result)

        def job(ctx):
            # 进度只能经 ctx.progress 上报（它投队列，由主线程更新进度条）：
            # 直接把 on_progress 交给流水线会让它在后台线程里写控件。
            if per_file:
                plan = ConvertPlan(out_dir=target, log=app.log, progress=ctx.progress,
                                   cancel=ctx.cancel_event, **common)
                ctx.progress(0, max(len(inputs), 1), "开始转换")
                return convert_each_file(plan)
            plan = ProcessPlan(output_path=target, log=app.log, progress=ctx.progress,
                               cancel=ctx.cancel_event, **common)
            ctx.progress(0, max(len(inputs), 1), "开始读取")
            return run_merge(plan)

        app.run_job(job, on_done=done, on_error=on_error,
                    progress_handler=on_progress)

    start_button.configure(command=start)
    start_button.pack(side="right")
    # 按钮的禁用与恢复统一交给 App：标签页自己 app.after(200, ...) 恢复会让任务
    # 仍在运行时按钮就变可点。输出方式两个单选一并注册，避免任务运行中还能切换
    # 输出方式，让界面显示与实际生效的模式不一致。
    app.register_busy_widget(start_button)
    for button in output_mode_buttons:
        app.register_busy_widget(button)
    return parent
