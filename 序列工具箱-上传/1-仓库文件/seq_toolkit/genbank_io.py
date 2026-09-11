"""GenBank 读取：多记录文件、字段回退链、CONTIG 记录识别、原始块保真。"""

from __future__ import annotations

import datetime
import re
from typing import Callable, Iterable, Iterator, Mapping

from .model import SequenceRecord, SeqToolkitError, parse_accession
from .naming import extract_species_from_header, sanitize_species
from .textio import has_decoding_damage, open_text

_LOCUS_DATE = re.compile(r"\b\d{1,2}-[A-Z]{3}-\d{4}\b")
_ORGANISM_QUALIFIER = re.compile(r'/organism="([^"]+)"')
_ORIGIN_DIGITS = re.compile(r"[\s0-9]")

# LOCUS 行的名称列：第 13-28 列（0-based 切片 [12:28]），宽度固定 16 字符
LOCUS_NAME_START = 12
LOCUS_NAME_END = 28
LOCUS_NAME_WIDTH = LOCUS_NAME_END - LOCUS_NAME_START  # 16


class GenBankParseError(SeqToolkitError):
    """GenBank 记录无法解析。"""


class ContigRecordError(GenBankParseError):
    """记录只有 CONTIG（未组装），没有 ORIGIN 段，无法产出序列。"""

    def __init__(self, line: int, reason: str) -> None:
        super().__init__(reason)
        self.line = line


def is_top_level_field(line: str, keyword: str) -> bool:
    """判断某行是否为指定字段行。

    容忍前导缩进（ORGANISM / SOURCE 缩进 2 空格），并要求关键字之后是空白或行尾，
    因此 '/organism="x"' 与谱系行都不会被误判。
    """
    stripped = line.lstrip()
    if not stripped.startswith(keyword):
        return False
    rest = stripped[len(keyword):]
    return rest == "" or rest[0].isspace()


def _iter_blocks(path: str) -> Iterator[tuple[int, list[str]]]:
    """按 '//' 切分记录块，并跳过块之间的空行（保证 raw_block 从 LOCUS 开始）。"""
    block: list[str] = []
    start = 0
    with open_text(path) as handle:
        for lineno, raw in enumerate(handle, start=1):
            line = raw.rstrip("\n")
            if not block:
                if not line.strip():
                    continue
                start = lineno
            block.append(line)
            if line.strip() == "//":
                yield start, block
                block = []
    if any(line.startswith("LOCUS") for line in block):
        yield start, block


def _collect_field(lines: list[str], index: int, keyword: str) -> str:
    """收集一个可跨行的字段值（续行为缩进行，遇到顶格字段停止）。"""
    first = lines[index].strip()[len(keyword):].strip()
    parts = [first] if first else []
    cursor = index + 1
    while cursor < len(lines):
        current = lines[cursor]
        if not current.strip():
            break
        if not current[:1].isspace():
            break
        parts.append(current.strip())
        cursor += 1
    return " ".join(parts)


def _parse_block(path: str, start_line: int, lines: list[str]) -> SequenceRecord:
    warnings: list[str] = []

    if not any(line.startswith("LOCUS") for line in lines):
        raise GenBankParseError("记录缺少 LOCUS 行")

    locus_name = ""
    date = ""
    for line in lines:
        if line.startswith("LOCUS"):
            tokens = line.split()
            if len(tokens) > 1:
                locus_name = tokens[1]
            match = _LOCUS_DATE.search(line)
            if match:
                date = match.group(0)
            break

    accession_raw = ""
    for line in lines:
        if line.startswith("VERSION"):
            tokens = line.split()
            if len(tokens) > 1:
                accession_raw = tokens[1]
            break
    if not accession_raw:
        for line in lines:
            if line.startswith("ACCESSION"):
                tokens = line.split()
                if len(tokens) > 1:
                    accession_raw = tokens[1]
                break
        if accession_raw:
            warnings.append("缺少 VERSION 行，已回退使用 ACCESSION")
    accession = parse_accession(accession_raw or locus_name)
    if not accession.well_formed:
        warnings.append(f"accession 格式可疑: {accession_raw or locus_name!r}")

    definition = ""
    for index, line in enumerate(lines):
        if line.startswith("DEFINITION"):
            definition = _collect_field(lines, index, "DEFINITION")
            break

    species_raw = ""
    lineage = ""
    for index, line in enumerate(lines):
        if is_top_level_field(line, "ORGANISM"):
            species_raw = line.strip()[len("ORGANISM"):].strip()
            lineage_parts: list[str] = []
            cursor = index + 1
            while cursor < len(lines):
                current = lines[cursor]
                if not current.strip() or not current[:1].isspace():
                    break
                lineage_parts.append(current.strip())
                cursor += 1
            lineage = " ".join(lineage_parts)
            break

    if not species_raw:
        match = _ORGANISM_QUALIFIER.search("\n".join(lines))
        if match:
            species_raw = match.group(1).strip()
            warnings.append("ORGANISM 段缺失，已回退使用 source feature 的 /organism 限定符")

    if not species_raw:
        extracted, extract_warnings = extract_species_from_header(definition)
        if extracted:
            species_raw = extracted
            warnings.extend(extract_warnings)
            warnings.append("ORGANISM 与 /organism 均缺失，已从 DEFINITION 提取物种名")

    if not species_raw:
        species_raw = locus_name
        if locus_name:
            warnings.append("无物种信息，已回退为 LOCUS 名")

    species = sanitize_species(species_raw)
    if not species:
        warnings.append("无法从 GenBank 记录取得物种名，该记录将不改名")

    origin_index = next(
        (i for i, line in enumerate(lines) if line.startswith("ORIGIN")), -1
    )
    if origin_index < 0:
        if any(line.startswith("CONTIG") for line in lines):
            raise ContigRecordError(start_line, "序列未组装（CONTIG 记录），无 ORIGIN 段")
        raise GenBankParseError("记录缺少 ORIGIN 段")

    sequence_parts: list[str] = []
    for line in lines[origin_index + 1:]:
        if line.strip() == "//":
            break
        sequence_parts.append(_ORIGIN_DIGITS.sub("", line))
    sequence = "".join(sequence_parts).upper()
    if not sequence:
        raise GenBankParseError("ORIGIN 段为空")

    raw_block = "".join(line + "\n" for line in lines)

    if has_decoding_damage("\n".join(lines)):
        warnings.append(
            "文件可能不是 UTF-8 编码（出现替换字符 U+FFFD），请转码为 UTF-8 后重试"
        )

    # 截断检测：GenBank 记录必须以独占一行的 '//' 结束。缺了它说明文件被截断
    # （下载中断、磁盘写满等），此时仍能解析出「登录号正确但序列被截断」的记录——
    # 零信号地污染下游数据集，比直接报错危险得多。
    non_empty = [line for line in lines if line.strip()]
    if not non_empty or non_empty[-1].strip() != "//":
        warnings.append("文件可能被截断（记录未以 // 结束），序列可能不完整")

    return SequenceRecord(
        accession=accession.accession or locus_name,
        accession_base=accession.base or locus_name,
        version=accession.version,
        species=species,
        species_raw=species_raw,
        lineage=lineage,
        definition=definition,
        seq=sequence,
        source_format="genbank",
        origin_path=str(path),
        origin_line=start_line,
        date=date,
        raw_block=raw_block,
        warnings=tuple(warnings),
    )


def read_genbank(
    path: str,
    on_skip: Callable[[str, int, str], None] | None = None,
) -> Iterator[SequenceRecord]:
    """逐条产出 GenBank 记录。

    无法产出序列的记录（CONTIG 型）通过 on_skip(path, line, reason) 上报后跳过，
    绝不静默丢弃；整块解析失败同样上报后继续处理后续记录。
    整个文件都没有 LOCUS 行时抛 GenBankParseError，由调用方按"格式不符"处理。
    """
    saw_locus = False
    for start_line, lines in _iter_blocks(path):
        if not any(line.startswith("LOCUS") for line in lines):
            if on_skip is not None:
                on_skip(str(path), start_line, "记录缺少 LOCUS 行")
            continue
        saw_locus = True
        try:
            yield _parse_block(path, start_line, lines)
        except ContigRecordError as error:
            if on_skip is not None:
                on_skip(str(path), error.line, str(error))
            continue
        except GenBankParseError as error:
            if on_skip is not None:
                on_skip(str(path), start_line, str(error))
            continue

    if not saw_locus:
        raise GenBankParseError(f"{path}: 未找到任何 GenBank 记录（缺少 LOCUS 行）")


def _replace_locus_name(raw_block: str, name: str) -> tuple[str, bool]:
    """把 LOCUS 行第 13-28 列替换为新名称。返回 (新文本, 是否成功替换)。"""
    if len(name) > LOCUS_NAME_WIDTH:
        return raw_block, False
    lines = raw_block.split("\n")
    for index, line in enumerate(lines):
        if line.startswith("LOCUS"):
            padded = name.ljust(LOCUS_NAME_WIDTH)
            lines[index] = line[:LOCUS_NAME_START] + padded + line[LOCUS_NAME_END:]
            return "\n".join(lines), True
    return raw_block, False


def _synthesise_genbank(record: SequenceRecord, name: str) -> str:
    """把 FASTA 来源的记录合成为最小合法 GenBank 记录。"""
    today = datetime.date.today().strftime("%d-%b-%Y").upper()
    locus_name = (name or record.accession or "sequence")[:LOCUS_NAME_WIDTH]
    sequence = record.seq
    lines = [
        f"LOCUS       {locus_name:<16}{len(sequence):>12} bp    DNA     linear   UNK {today}",
        f"DEFINITION  {record.definition or record.accession}.",
        f"ACCESSION   {record.accession_base or record.accession}",
        f"VERSION     {record.accession}",
        "KEYWORDS    .",
        f"SOURCE      {record.species_raw or record.accession}",
    ]
    if record.species_raw:
        lines.append(f"  ORGANISM  {record.species_raw}")
    lines.append("FEATURES             Location/Qualifiers")
    lines.append(f"     source          1..{len(sequence)}")
    if record.species_raw:
        lines.append(f'                     /organism="{record.species_raw}"')
        lines.append('                     /mol_type="genomic DNA"')
    lines.append("ORIGIN")
    for start in range(0, len(sequence), 60):
        chunk = sequence[start:start + 60]
        groups = " ".join(chunk[i:i + 10] for i in range(0, len(chunk), 10))
        lines.append(f"{start + 1:>9} {groups}")
    lines.append("//")
    return "\n".join(lines) + "\n"


def format_genbank_record(record: SequenceRecord, name: str) -> str:
    """产出一条 GenBank 文本。有原始块时逐字节保真，仅替换 LOCUS 名称列。

    ACCESSION 与 VERSION 始终保留原值：它们是序列的事实标识，随文件名一起改写
    会造成数据失真（下游按登录号回溯原始记录时会失配）。
    """
    if record.raw_block:
        if not name or name == record.accession:
            return record.raw_block
        replaced, _ok = _replace_locus_name(record.raw_block, name)
        return replaced
    return _synthesise_genbank(record, name)


def write_genbank(records: Iterable[SequenceRecord], out_path: str,
                  name_map: Mapping[SequenceRecord, str] | None = None) -> None:
    """把记录写成 GenBank。name_map 为 None 时使用登录号作为名称。

    输出固定使用 UTF-8 与 LF 换行，保证跨平台一致。
    """
    mapping = name_map or {}
    with open(str(out_path), "wt", encoding="utf-8", newline="\n") as handle:
        for index, record in enumerate(records, start=1):
            name = mapping.get(record) or record.accession or f"sequence_{index}"
            handle.write(format_genbank_record(record, name))
