"""⑦ 进化树生成：调用本机 R + V.PhyloMaker2，按物种学名生成 Newick 树。

R 是可选外部依赖，不随 exe 打包；缺失时给出可复制的安装指引。
所有耗时动作（检测 R、调 Rscript）都在后台线程执行。
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import phylo
from ..phylo import DEFAULT_SCENARIO, SYSTEMS
from .tree_canvas import TreeCanvas
from .widgets import FilePicker, ProgressPanel, grid_row

TITLE = "进化树生成"
SYSTEM_LABELS = {system.key: f"{system.key} — {system.label}"
                                  f"（{system.species_count:,} 种）"
                 for system in SYSTEMS}
SCENARIO_LABELS = {
    "S1": "S1 — 只绑定到属节点",
    "S2": "S2 — 科内按随机分辨率绑定",
    "S3": "S3 — 属内按随机分辨率绑定（默认）",
}


def missing_notice(missing: list[str], tip_count: int | None,
                   submitted: int) -> str:
    """未入树提示。数字对不上时必须给出解释，不能让用户拿到少了物种的树还不知情。"""
    if not missing:
        return ""
    head = (f"输入 {submitted} 个物种，入树 {tip_count if tip_count is not None else '?'} 个；"
            f"以下 {len(missing)} 个未能绑定到系统树（拼写错误或该名录未收录）：")
    names = "、".join(missing[:8]) + ("…" if len(missing) > 8 else "")
    return head + names


# 模块级工厂：测试会替换它们以注入替身（绝不真的启动 R）
def _detect_environment(rscript_path: str):
    return phylo.detect_environment(rscript_path)


def _run_phylo(*args, **kwargs):
    return phylo.run_phylo(*args, **kwargs)


def build(parent: ttk.Frame, app) -> ttk.Frame:
    # 所有 Tk 变量显式传 master=parent。

    # 底部按钮条必须**最先** pack 并用 side="bottom"：Tk 的 packer 按 pack 调用的先后
    # 分配空间，先调用的先拿到自己请求的高度，排在后面的只能分剩下的。本页请求高度
    # 680 px，窗口缩到最小（940x660 ⇒ 页面 620 px）时，最后 pack 的这条会被挤成 1 px
    # ——实测「生成进化树」「检测 R 环境」「从序列文件导入物种名」三个按钮同时消失
    # （mapped=0 / w=1 / h=1）。先占住底部之后，被压缩的变成可伸缩的物种列表与树预览。
    # 控件的创建仍留在下文原地，父容器先建好即可。
    action = ttk.Frame(parent)
    action.pack(side="bottom", fill="x", padx=8, pady=(4, 8))

    source_box = ttk.LabelFrame(parent, text="物种列表（一行一个学名，只需学名）")
    source_box.pack(fill="both", expand=False, padx=8, pady=(8, 4))
    species_text = tk.Text(source_box, height=7, wrap="none")
    species_text.pack(fill="both", expand=True, padx=6, pady=6)

    options = ttk.LabelFrame(parent, text="生成参数")
    options.pack(fill="x", padx=8, pady=4)
    system = tk.StringVar(master=parent, value=SYSTEM_LABELS[app.settings.phylo_system]
                          if app.settings.phylo_system in SYSTEM_LABELS
                          else SYSTEM_LABELS["TPL"])
    scenario = tk.StringVar(master=parent,
                            value=SCENARIO_LABELS.get(app.settings.phylo_scenario,
                                                      SCENARIO_LABELS[DEFAULT_SCENARIO]))
    grid_row(options, 0, "命名系统",
             ttk.Combobox(options, textvariable=system, state="readonly",
                          values=list(SYSTEM_LABELS.values())))
    grid_row(options, 1, "绑定场景",
             ttk.Combobox(options, textvariable=scenario, state="readonly",
                          values=list(SCENARIO_LABELS.values())))
    default_tree = os.path.join(app.settings.output_dir or os.getcwd(),
                                "phylogeny_tree.treefile")
    out_path = FilePicker(options, mode="save", title="保存进化树",
                          filetypes=[("Treefile", "*.treefile"), ("所有文件", "*.*")])
    out_path.set_path(default_tree)
    grid_row(options, 2, "输出文件", out_path)
    env_label = ttk.Label(options, text="尚未检测 R 环境", anchor="w",
                          justify="left", wraplength=900, foreground="#606060")
    grid_row(options, 3, "R 环境", env_label)

    notice = ttk.Label(parent, text="", anchor="w", justify="left",
                       foreground="#a05000", wraplength=1000)
    notice.pack(fill="x", padx=12)

    preview_box = ttk.LabelFrame(parent, text="树形预览（拓扑）")
    preview_box.pack(fill="both", expand=True, padx=8, pady=4)
    preview = TreeCanvas(preview_box)
    preview.pack(fill="both", expand=True, padx=6, pady=6)

    # action 已在 build 开头创建并占好了底部位置（理由见那里的注释）。
    progress = ProgressPanel(action)
    progress.pack(side="left", fill="x", expand=True)
    detect_button = ttk.Button(action, text="检测 R 环境")
    generate_button = ttk.Button(action, text="生成进化树")
    import_button = ttk.Button(action, text="从序列文件导入物种名")

    def import_species() -> None:
        from .tab_tnrs import import_species_from_files
        chosen = filedialog.askopenfilenames(parent=parent, title="从序列文件导入物种名")
        if not chosen:
            return
        # log=app.log 不能省：坏文件/提不出物种名的记录要被记成 WARN，
        # 否则用户看到"导入 0 个"却完全不知道是哪几个文件出的问题。
        found = import_species_from_files(list(chosen), app.settings, log=app.log)
        if not found:
            app.log.warn("没有从所选文件中提取到物种名")
            return
        species_text.insert("end", "\n".join(found) + "\n")
        app.log.info(f"已从文件导入 {len(found)} 个物种名")

    def on_progress(done: int, total: int, text: str) -> None:
        if done == 0:
            progress.start(total)
        progress.update(done, total, text)

    def do_detect() -> None:
        def job(ctx):
            env = _detect_environment(app.settings.rscript_path)
            # 检测本身是不可中断的 subprocess.run（timeout=120）：取消信号只能在它返回
            # 之后被看到。不在这里看一眼的话，on_cancel 永远不会触发——那就成了一个
            # 挂上去也永远不会执行的回调，用户点了取消照样会看到结果。
            ctx.raise_if_cancelled()
            return env

        def done(env) -> None:
            env_label.configure(text=env.message,
                                foreground="#606060" if env.has_package else "#a05000")
            (app.log.info if env.has_package else app.log.warn)(env.message)

        def on_cancel() -> None:
            # 取消走 App 的 OperationCancelled 分支，**不会**调 on_error：不在这里交代，
            # 环境标签会一直停在上一轮的结论上，用户不知道刚才那一下到底生效没有。
            env_label.configure(text="尚未检测 R 环境", foreground="#606060")
            app.log.warn("R 环境检测已取消（该步骤无法中断，检测进程可能仍在后台跑完）")

        app.run_job(job, on_done=done,
                    on_error=lambda error: app.log.error(f"检测失败: {error}"),
                    on_cancel=on_cancel)

    def on_generate_done(run) -> None:
        progress.finish(f"已写出 {os.path.basename(run.tree_path)}")
        requested = requested_path[0]
        # run_phylo 绝不覆盖已有文件（见 phylo.run_phylo 的 docstring）：目标被让位到 _1 时
        # 必须说清"实际写到哪儿了"，否则用户会去输出框里那个（并没有被更新的）旧文件里
        # 找新树。比较前先规范化：用户手打的 C:/x/t.treefile 与 Path 出来的
        # C:\x\t.treefile 是同一个文件，直接比字符串会报出一条假的"已存在"。
        if requested and (os.path.normcase(os.path.abspath(requested))
                          != os.path.normcase(os.path.abspath(run.tree_path))):
            app.log.warn(f"目标文件已存在，实际写入: {run.tree_path}")
        text = missing_notice(run.missing, run.tip_count, submitted_count[0])
        notice.configure(text=text)
        if text:
            app.log.warn(text)
        if run.missing:
            # 标签里的名单截断到 8 个（否则撑坏布局），但**完整清单必须进日志**：
            # 第 9 个起若哪儿都看不到，用户就无从知道到底少了哪些物种。
            app.log.warn(f"未绑定到系统树的物种共 {len(run.missing)} 个："
                         f"{'、'.join(run.missing)}")
        app.log.info(f"进化树已生成：{run.tree_path}（叶节点 "
                     f"{run.tip_count if run.tip_count is not None else '?'} 个）")
        app.set_status(f"进化树已生成：{os.path.basename(run.tree_path)}")
        try:
            with open(run.tree_path, "rt", encoding="utf-8") as handle:
                preview.set_tree(phylo.parse_newick(handle.read()))
        except (OSError, ValueError, RecursionError) as error:
            # RecursionError 必须在这里被接住：parse_newick 是递归下降的，超深 Newick
            # （评审实测毛毛虫树 n=900，阈值随当前栈深浮动）会撞上 Python 递归上限。它不在
            # (OSError, ValueError) 里，漏出去就从 after 回调冒到 Tk，使下面的
            # 「生成完成」弹窗**再也不出现**——用户既看不到树，也不知道为什么没有树。
            if isinstance(error, RecursionError):
                app.log.error("树太深/文件异常，无法预览（分支嵌套层数超出递归上限）；"
                              f"树文件本身已正常写出：{run.tree_path}")
            else:
                app.log.error(f"树文件读取失败，无法预览: {error}")
        messagebox.showinfo("生成完成", f"输出：{run.tree_path}")

    submitted_count = [0]
    # 主线程快照：用户请求的输出路径。完成回调里要拿它与 run.tree_path 比对，
    # 判断是否发生了让位（绝不能去读输出框的当前值——任务跑完前用户可能已经改过它）。
    requested_path = [""]

    def do_generate() -> None:
        raw = species_text.get("1.0", "end").splitlines()
        seen: set[str] = set()
        names: list[str] = []
        for line in raw:
            name = line.strip()
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                names.append(name)
        if not names:
            app.log.warn("请输入至少一个物种名")
            return
        target = out_path.path()
        if not target:
            app.log.warn("请指定输出文件")
            return
        system_key = next(key for key, label in SYSTEM_LABELS.items()
                          if label == system.get())
        scenario_key = next(key for key, label in SCENARIO_LABELS.items()
                            if label == scenario.get())
        rscript = app.settings.rscript_path
        submitted_count[0] = len(names)
        requested_path[0] = target

        def job(ctx):
            env = _detect_environment(rscript)
            if not env.rscript or not env.has_package:
                raise phylo.PhyloError(env.message)
            ctx.progress(0, 1, "正在生成（大列表可能需要数分钟）")
            # warn=ctx.warn 不能省：临时 .R 删不掉、进程树没能确认杀干净这类事在
            # **取消路径**上也要有人知道（那条路径没有 PhyloRun 可以返回给界面）。
            run = _run_phylo(env.rscript, names, system_key, scenario_key,
                             target, cancel=ctx.cancel_event,
                             warn=ctx.warn,
                             progress=lambda text: ctx.info(text))
            ctx.progress(1, 1, "完成")
            return run

        def on_cancel() -> None:
            # 取消走的是 App 的 OperationCancelled 分支，**不会**调 on_error：
            # 不在这里复位，进度标签就会永远停在「正在生成（大列表可能需要数分钟）」。
            progress.reset()
            app.log.warn("进化树生成已取消")

        app.run_job(job, on_done=on_generate_done,
                    on_error=lambda error: (progress.reset(),
                                            app.log.error(f"生成失败: {error}")),
                    on_cancel=on_cancel,
                    progress_handler=on_progress)

    detect_button.configure(command=do_detect)
    generate_button.configure(command=do_generate)
    import_button.configure(command=import_species)
    generate_button.pack(side="right")
    detect_button.pack(side="right", padx=4)
    import_button.pack(side="right", padx=4)
    app.register_busy_widget(generate_button)
    app.register_busy_widget(detect_button)
    app.register_busy_widget(import_button)
    return parent
