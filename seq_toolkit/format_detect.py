"""输入格式识别与输入文件展开。内容嗅探优先于后缀名。"""

from __future__ import annotations

import os
import re
import zlib
from typing import Iterable, Sequence

from .textio import open_text

DEFAULT_FASTA_SUFFIXES = (".fasta", ".fa", ".fna", ".fas", ".ffn", ".frn", ".fsa", ".seq")
DEFAULT_GENBANK_SUFFIXES = (".gb", ".gbk", ".genbank", ".gbff", ".gp")

_NUMERIC_CHUNK = re.compile(r"(\d+)")
SNIFF_LINE_LIMIT = 50


def format_from_suffix(path: str) -> str:
    """按后缀名猜测格式；.gz 先剥离。无法判定返回空串。"""
    name = os.path.basename(str(path)).lower()
    if name.endswith(".gz"):
        name = name[:-3]
    if any(name.endswith(suffix) for suffix in DEFAULT_GENBANK_SUFFIXES):
        return "genbank"
    if any(name.endswith(suffix) for suffix in DEFAULT_FASTA_SUFFIXES):
        return "fasta"
    return ""


def sniff_format(path: str) -> str:
    """读取首个非空行判定格式：'LOCUS' 开头为 GenBank，'>' 开头为 FASTA。"""
    try:
        with open_text(path) as handle:
            for _ in range(SNIFF_LINE_LIMIT):
                line = handle.readline()
                if not line:
                    return ""
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("LOCUS"):
                    return "genbank"
                if stripped.startswith(">"):
                    return "fasta"
                return ""
    except (OSError, EOFError, zlib.error):
        # 三类异常都必须捕获，且都不是彼此的父类：
        #   BadGzipFile/OSError —— gzip 头损坏
        #   EOFError            —— 文件被截断（gzip 的 EOFError 不是 OSError 子类）
        #   zlib.error          —— deflate 数据体损坏（同样不是 OSError 子类）
        # 任其逃逸会一路穿过 detect_format（它在 run_merge 的 try 之外）中断整批合并。
        return ""
    return ""


def detect_format(path: str, hint: str = "auto") -> str:
    """判定文件格式。hint 为 'fasta'/'genbank' 时强制采用；'auto' 时内容优先于后缀。"""
    if hint in ("fasta", "genbank"):
        return hint
    if hint != "auto":
        raise ValueError(f"未知的输入格式提示: {hint}")
    by_suffix = format_from_suffix(path)
    by_content = sniff_format(path)
    if by_content and by_suffix and by_content != by_suffix:
        return by_content
    return by_content or by_suffix


def natural_key(text: str) -> list[tuple[int, object]]:
    """数字感知排序键：chr2 排在 chr10 之前。混合类型用元组包裹，避免比较时抛 TypeError。"""
    return [
        (0, int(chunk)) if chunk.isdecimal() else (1, chunk.lower())
        for chunk in _NUMERIC_CHUNK.split(str(text))
    ]


def _matches_suffix(name: str, suffixes: Sequence[str]) -> bool:
    lowered = name.lower()
    if lowered.endswith(".gz"):
        lowered = lowered[:-3]
    return any(lowered.endswith(suffix) for suffix in suffixes)


def list_input_files(
    paths: Iterable[str],
    recursive: bool = True,
    fasta_suffixes: Sequence[str] = DEFAULT_FASTA_SUFFIXES,
    genbank_suffixes: Sequence[str] = DEFAULT_GENBANK_SUFFIXES,
) -> list[str]:
    """展开输入：显式文件一律保留；文件夹里的文件按后缀过滤后自然排序。"""
    suffixes = tuple(fasta_suffixes) + tuple(genbank_suffixes)
    collected: list[str] = []
    for raw in paths:
        path = str(raw)
        if os.path.isdir(path):
            if recursive:
                for root, _dirs, files in os.walk(path):
                    for name in sorted(files, key=natural_key):
                        if _matches_suffix(name, suffixes):
                            collected.append(os.path.join(root, name))
            else:
                for name in sorted(os.listdir(path), key=natural_key):
                    full = os.path.join(path, name)
                    if os.path.isfile(full) and _matches_suffix(name, suffixes):
                        collected.append(full)
        elif os.path.isfile(path):
            collected.append(path)
    return collected
