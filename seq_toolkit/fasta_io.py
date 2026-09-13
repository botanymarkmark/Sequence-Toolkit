"""FASTA 读取：支持多行序列、CRLF、BOM、.gz，以及多种后缀名。"""

from __future__ import annotations

import re
from typing import Iterable, Iterator, Mapping

from .model import SequenceRecord, SeqToolkitError, parse_accession
from .naming import extract_species_from_header, sanitize_species
from .textio import has_decoding_damage, open_text

IUPAC_CHARS = frozenset("ACGTURYSWKMBDHVN")
_WHITESPACE = re.compile(r"\s+")


class FastaParseError(SeqToolkitError):
    """FASTA 文件无法解析（空文件、缺少记录头等）。"""


def _build_record(path: str, header: str, chunks: list[str],
                  start_line: int) -> SequenceRecord:
    warnings: list[str] = []
    body = header.strip()
    parts = body.split(None, 1)
    token = parts[0] if parts else ""
    remainder = parts[1] if len(parts) > 1 else ""

    accession = parse_accession(token)
    if not accession.well_formed:
        warnings.append(f"accession 格式可疑: {token!r}")

    species_raw, species_warnings = extract_species_from_header(remainder)
    warnings.extend(species_warnings)
    species = sanitize_species(species_raw)
    if not species:
        warnings.append("无法从 header 提取物种名，该记录将不改名")

    sequence = _WHITESPACE.sub("", "".join(chunks)).upper()
    unexpected = sorted(set(sequence) - IUPAC_CHARS)
    if unexpected:
        warnings.append("序列含非 IUPAC 字符: " + "".join(unexpected))

    # 编码损伤必须单独告警：否则 GBK 等非 UTF-8 输入会被报成"序列含非 IUPAC 字符"
    # （用户会去查序列而不是查编码），若乱码只落在定义行尾部则完全无声。
    if has_decoding_damage(header) or has_decoding_damage(sequence):
        warnings.append(
            "文件可能不是 UTF-8 编码（出现替换字符 U+FFFD），请转码为 UTF-8 后重试"
        )

    return SequenceRecord(
        accession=accession.accession or token,
        accession_base=accession.base or token,
        version=accession.version,
        species=species,
        species_raw=species_raw,
        lineage="",
        definition=remainder,
        seq=sequence,
        source_format="fasta",
        origin_path=str(path),
        origin_line=start_line,
        date="",
        raw_block="",
        warnings=tuple(warnings),
    )


def read_fasta(path: str) -> Iterator[SequenceRecord]:
    """逐条产出 FASTA 记录。文件中不含任何 '>' 行时抛 FastaParseError。"""
    header: str | None = None
    chunks: list[str] = []
    start_line = 0
    produced = 0

    with open_text(path) as handle:
        for lineno, raw in enumerate(handle, start=1):
            line = raw.rstrip("\n")
            if line.startswith(">"):
                if header is not None:
                    yield _build_record(path, header, chunks, start_line)
                    produced += 1
                header = line[1:]
                chunks = []
                start_line = lineno
            elif header is not None:
                chunks.append(line)

    if header is not None:
        yield _build_record(path, header, chunks, start_line)
        produced += 1

    if produced == 0:
        raise FastaParseError(f"{path}: 未找到任何 FASTA 记录（缺少 '>' 记录头）")


def write_fasta(records: Iterable[SequenceRecord], out_path: str,
                name_map: Mapping[SequenceRecord, str] | None = None,
                wrap: int = 0) -> None:
    """把记录写成 FASTA。name_map 为 None 时使用登录号作为序列名。

    wrap=0 表示整条序列写在一行；wrap=N 表示每行 N 个碱基。
    输出固定使用 UTF-8 与 LF 换行，保证跨平台一致。
    """
    mapping = name_map or {}
    with open(str(out_path), "wt", encoding="utf-8", newline="\n") as handle:
        for index, record in enumerate(records, start=1):
            name = mapping.get(record) or record.accession or f"sequence_{index}"
            handle.write(f">{name}\n")
            sequence = record.seq
            if wrap and wrap > 0:
                for start in range(0, len(sequence), wrap):
                    handle.write(sequence[start:start + wrap] + "\n")
            else:
                handle.write(sequence + "\n")
