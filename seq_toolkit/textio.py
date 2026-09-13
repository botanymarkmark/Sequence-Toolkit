"""统一的文本打开入口：显式 UTF-8、兼容 BOM、透明解压 .gz、统一换行。"""

from __future__ import annotations

import gzip
from typing import IO


def open_text(path: str) -> IO[str]:
    """按 UTF-8 打开文本文件，供 fasta_io 与 genbank_io 共用。

    - encoding="utf-8-sig"：自动吃掉 BOM，普通 UTF-8 文件不受影响
    - newline=None：把 CRLF / CR / LF 统一翻译为 "\\n"
    - .gz 后缀透明解压
    """
    if str(path).lower().endswith(".gz"):
        return gzip.open(str(path), "rt", encoding="utf-8-sig",
                         errors="replace", newline=None)
    return open(str(path), "rt", encoding="utf-8-sig",
                errors="replace", newline=None)


REPLACEMENT_CHAR = "\ufffd"


def has_decoding_damage(text: str) -> bool:
    """文本中是否出现 U+FFFD 替换字符。

    errors="replace" 让非 UTF-8 文件（例如中文 Windows 上常见的 GBK/cp936）被静默
    解码成一堆 U+FFFD。本函数让调用方能把"文件编码不对"与"序列里有脏字符"区分开，
    给出可操作的提示，而不是让用户去查序列。
    """
    return REPLACEMENT_CHAR in text
