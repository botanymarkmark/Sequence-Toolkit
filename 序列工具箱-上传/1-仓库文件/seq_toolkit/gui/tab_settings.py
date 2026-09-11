"""⑤ 设置：NCBI 凭据、代理、默认输出目录、后缀名与换行策略。"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, ttk

from ..settings import Settings
from .widgets import grid_row

TITLE = "设置"
_SEPARATOR = re.compile(r"[\s,;]+")


def split_suffixes(text: str) -> tuple[str, ...]:
    """把用户输入的后缀串切成元组，缺前导点自动补上。

    补点不是美化：后缀名要拿去和文件名结尾逐字比较，用户写成 "fa fna" 时若不补点，
    ``list_input_files`` 一个文件都匹配不到，界面上的表现是"加了后缀却什么都没识别到"。
    """
    parts = [chunk.strip() for chunk in _SEPARATOR.split(text or "") if chunk.strip()]
    return tuple(chunk if chunk.startswith(".") else f".{chunk}" for chunk in parts)


def join_suffixes(suffixes) -> str:
    return ", ".join(suffixes)


def build(parent: ttk.Frame, app) -> ttk.Frame:
    # 本函数里所有 Tk 变量都显式写 master=parent：不传 master 时 Variable 会挂到
    # tkinter 的 _default_root（进程里第一个根窗口）上。进程里存在第二个根窗口时控件
    # 与变量就落在两个不同的 Tcl 解释器里——输入框里看得见新填的邮箱，而 get() 出来
    # 仍是旧值，点保存等于把旧配置又存了一遍，用户会觉得"设置根本存不上"。
    settings: Settings = app.settings

    box = ttk.LabelFrame(parent, text="NCBI 访问设置")
    box.pack(fill="x", padx=8, pady=(8, 4))

    ttk.Label(box, text="NCBI 邮箱（必填）").grid(
        row=0, column=0, sticky="w", padx=(8, 6), pady=3)
    email = tk.StringVar(master=parent, value=settings.email)
    ttk.Entry(box, textvariable=email).grid(
        row=0, column=1, sticky="ew", padx=(0, 8), pady=3)
    ttk.Label(box, text="NCBI 要求所有 E-utilities 请求附带联系邮箱，否则可能被限流。",
              foreground="#666666").grid(row=1, column=1, sticky="w", padx=(0, 8))

    ttk.Label(box, text="NCBI API key（选填）").grid(
        row=2, column=0, sticky="w", padx=(8, 6), pady=3)
    api_key = tk.StringVar(master=parent, value=settings.api_key)
    ttk.Entry(box, textvariable=api_key).grid(
        row=2, column=1, sticky="ew", padx=(0, 8), pady=3)
    ttk.Label(box, text="填写后请求速率由 3 次/秒提升到 10 次/秒。",
              foreground="#666666").grid(row=3, column=1, sticky="w", padx=(0, 8))

    ttk.Label(box, text="代理服务器（选填）").grid(
        row=4, column=0, sticky="w", padx=(8, 6), pady=3)
    proxy = tk.StringVar(master=parent, value=settings.proxy)
    ttk.Entry(box, textvariable=proxy).grid(
        row=4, column=1, sticky="ew", padx=(0, 8), pady=3)
    ttk.Label(box, text="例如 http://127.0.0.1:7890。国内直连 NCBI 常常超时，填了更稳。",
              foreground="#666666").grid(row=5, column=1, sticky="w", padx=(0, 8))
    box.columnconfigure(1, weight=1)

    file_box = ttk.LabelFrame(parent, text="文件处理偏好")
    file_box.pack(fill="x", padx=8, pady=4)

    out_dir = tk.StringVar(master=parent, value=settings.output_dir)
    grid_row(file_box, 0, "默认输出目录",
             ttk.Entry(file_box, textvariable=out_dir))

    fasta_suffixes = tk.StringVar(master=parent,
                                 value=join_suffixes(settings.fasta_suffixes))
    grid_row(file_box, 1, "FASTA 后缀名",
             ttk.Entry(file_box, textvariable=fasta_suffixes))

    genbank_suffixes = tk.StringVar(master=parent,
                                   value=join_suffixes(settings.genbank_suffixes))
    grid_row(file_box, 2, "GenBank 后缀名",
             ttk.Entry(file_box, textvariable=genbank_suffixes))

    wrap = tk.IntVar(master=parent, value=settings.wrap)
    row = ttk.Frame(file_box)
    grid_row(file_box, 3, "FASTA 每行长度", row)
    ttk.Radiobutton(row, text="不换行", value=0, variable=wrap).pack(side="left")
    for width in (60, 70, 80):
        ttk.Radiobutton(row, text=str(width), value=width,
                        variable=wrap).pack(side="left", padx=(8, 0))

    force = tk.BooleanVar(master=parent, value=settings.force_redownload)
    grid_row(file_box, 4, "重复下载",
             ttk.Checkbutton(file_box, text="强制重新下载（默认跳过已存在的文件）",
                             variable=force))

    action = ttk.Frame(parent)
    action.pack(fill="x", padx=8, pady=(8, 8))
    save_button = ttk.Button(action, text="保存设置")

    def apply_values() -> None:
        app.settings.email = email.get().strip()
        app.settings.api_key = api_key.get().strip()
        app.settings.proxy = proxy.get().strip()
        app.settings.output_dir = out_dir.get().strip()
        app.settings.fasta_suffixes = split_suffixes(fasta_suffixes.get())
        app.settings.genbank_suffixes = split_suffixes(genbank_suffixes.get())
        app.settings.wrap = wrap.get()
        app.settings.force_redownload = force.get()

    def save() -> None:
        apply_values()
        if not app.settings.email:
            messagebox.showwarning("提示", "NCBI 邮箱为必填项，缺失会导致下载功能被限流。")
        # 邮箱缺失也要落盘：其余设置（代理、后缀名）是用户刚改的，直接丢弃更糟。
        app.save_settings()
        messagebox.showinfo("已保存", "设置已保存。")

    save_button.configure(command=save)
    save_button.pack(side="right")
    # 保存本身是同步操作，但设置是全局的：注册成 busy 控件后，下载/合并任务运行期间
    # 保存按钮会被 App 一并禁用，避免任务跑到一半配置被换掉。
    app.register_busy_widget(save_button)
    return parent
