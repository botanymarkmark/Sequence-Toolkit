"""统一数据模型：跨模块传递序列记录的唯一契约。"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import NamedTuple

# 覆盖 ON929859.1 这类常规形式，以及 NC_027224.1 / NZ_CM000001.1 这类 RefSeq 形式
_ACCESSION_RE = re.compile(
    r"^(?:[A-Z]{1,4}[0-9]{5,8}|[A-Z]{2}_[0-9]{6,9})(?:\.[0-9]+)?$"
)


class SeqToolkitError(Exception):
    """本工具所有自定义异常的基类。"""


class AccessionParts(NamedTuple):
    accession: str
    base: str
    version: int | None
    well_formed: bool


def parse_accession(raw: str) -> AccessionParts:
    """把任意来历的登录号拆成 (完整登录号, 基号, 版本号, 是否通过格式校验)。

    统一转大写。即使格式不合规，也尽力拆出版本号，并通过 well_formed 标记异常，
    由调用方决定是记警告还是回退。
    """
    upper = (raw or "").strip().upper()
    if _ACCESSION_RE.match(upper):
        base, _, tail = upper.partition(".")
        version = int(tail) if tail else None
        return AccessionParts(upper, base, version, True)

    base = upper
    version = None
    if "." in upper:
        head, _, tail = upper.rpartition(".")
        if tail.isdecimal():
            base, version = head, int(tail)
    accession = f"{base}.{version}" if version is not None else base
    return AccessionParts(accession, base, version, False)


@dataclass(frozen=True)
class SequenceRecord:
    """一条序列及其元数据。不可变，可哈希（因此可直接用作字典键）。"""

    accession: str
    accession_base: str
    version: int | None
    species: str
    species_raw: str
    lineage: str
    definition: str
    seq: str
    source_format: str
    origin_path: str
    origin_line: int
    date: str = ""
    raw_block: str = ""
    warnings: tuple[str, ...] = ()

    def with_warning(self, *messages: str) -> "SequenceRecord":
        return replace(self, warnings=self.warnings + tuple(messages))

    @property
    def length(self) -> int:
        return len(self.seq)
