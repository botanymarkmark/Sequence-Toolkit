"""编排层：把"读 → 去重 → 命名 → 写"串成完整流程。"""

from __future__ import annotations

import os
import threading
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .applog import ExceptionEntry, RunLog
from .fasta_io import FastaParseError, read_fasta, write_fasta
from .format_detect import (
    DEFAULT_FASTA_SUFFIXES,
    DEFAULT_GENBANK_SUFFIXES,
    detect_format,
    format_from_suffix,
    list_input_files,
)
from .genbank_io import (
    LOCUS_NAME_WIDTH,
    GenBankParseError,
    read_genbank,
    write_genbank,
)
from .model import SequenceRecord, SeqToolkitError
from .naming import NAMING_MODES, build_name_map, render_name

# 这些 warning 表示"已自动处理完毕"，只进日志，不进需要人工复核的异常清单
BENIGN_WARNING_PREFIXES = ("已剥离伪装前缀",)

# 后缀名常量只在 format_detect 中定义一份，这里从那里导入，避免两处定义漂移


class OperationCancelled(SeqToolkitError):
    """用户请求取消。"""


def _is_benign_warning(message: str) -> bool:
    return message.startswith(BENIGN_WARNING_PREFIXES)


def _raise_if_cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise OperationCancelled("操作已取消")


def resolve_output_path(path: str) -> str:
    """返回一个当前不存在的输出路径：已存在时递增追加 _1、_2 …"""
    candidate = Path(path)
    if not candidate.exists():
        return str(candidate)
    for index in range(1, 1000):
        alternative = candidate.with_name(f"{candidate.stem}_{index}{candidate.suffix}")
        if not alternative.exists():
            return str(alternative)
    raise SeqToolkitError(f"无法为目标文件找到可用名称: {path}")


@dataclass
class ProcessPlan:
    inputs: list[str]
    output_path: str
    output_format: str = "fasta"
    input_format: str = "auto"
    naming_mode: str = "keep"
    dedup: str = "accession"
    recursive: bool = True
    wrap: int = 0
    fasta_suffixes: tuple[str, ...] = DEFAULT_FASTA_SUFFIXES
    genbank_suffixes: tuple[str, ...] = DEFAULT_GENBANK_SUFFIXES
    log: RunLog | None = None
    progress: Callable[[int, int, str], None] | None = None
    cancel: threading.Event | None = None

    def __post_init__(self) -> None:
        """在构造时就校验枚举字段。

        否则：output_format 传错值不会报错，而是静默按 FASTA 写出（用户要 GenBank
        却拿到 FASTA 且日志里一个字都没有）；naming_mode 传错值要等整批文件读完才由
        build_name_map 抛 ValueError，而 ValueError 不在调用方的 SeqToolkitError
        捕获集内（GUI 层会崩）。本项目招牌规则是「永不静默」，因此必须在此把关。

        只做校验、不触碰其它字段：GUI 标签页在构造**之后**才赋
        `plan.cancel = ctx.cancel_event`，该用法不受影响。
        """
        if self.output_format not in ("fasta", "genbank"):
            raise SeqToolkitError(f"未知输出格式: {self.output_format}")
        if self.input_format not in ("auto", "fasta", "genbank"):
            raise SeqToolkitError(f"未知输入格式: {self.input_format}")
        if self.naming_mode not in NAMING_MODES:
            raise SeqToolkitError(f"未知命名模式: {self.naming_mode}")
        if self.dedup not in ("accession", "none"):
            raise SeqToolkitError(f"未知去重方式: {self.dedup}")


@dataclass
class ProcessResult:
    records_in: int
    records_out: int
    duplicates_removed: int
    skipped_files: list[str]
    output_path: str
    exceptions: list[ExceptionEntry] = field(default_factory=list)


def _log_genbank_write_notes(log: RunLog, records: Sequence[SequenceRecord],
                             name_map: Mapping[SequenceRecord, str]) -> None:
    """写出 GenBank 前交代两处数据保真细节，避免用户事后才发现。

    format_genbank_record 的签名里没有 log，因此这两条告知由调用方（本模块）负责。
    """
    synthesised = sum(1 for record in records if not record.raw_block)
    if synthesised:
        log.warn(
            f"{synthesised} 条记录来源为 FASTA，没有可保留的原始注释，"
            f"将合成最小合法 GenBank 记录（仅含 source feature，不含其它 feature 注释）"
        )
    for record in records:
        if not record.raw_block:
            continue
        name = name_map.get(record, "")
        if len(name) > LOCUS_NAME_WIDTH:
            log.warn(
                f"{record.accession}: 新名称 {name} 超过 {LOCUS_NAME_WIDTH} 字符，"
                f"LOCUS 保留原名不改（不截断、不破坏列对齐），该记录请以 ACCESSION 为准"
            )


def run_merge(plan: ProcessPlan) -> ProcessResult:
    """合并 / 转换主流程。绝不静默覆盖输出文件，绝不因单条记录失败而中断整批。"""
    log = plan.log if plan.log is not None else RunLog()

    files = list_input_files(
        plan.inputs,
        recursive=plan.recursive,
        fasta_suffixes=plan.fasta_suffixes,
        genbank_suffixes=plan.genbank_suffixes,
    )
    if not files:
        raise SeqToolkitError("没有找到可处理的输入文件")

    records: list[SequenceRecord] = []
    pending_warnings: list[tuple[SequenceRecord, str]] = []
    skipped_files: list[str] = []
    seen_accessions: dict[str, str] = {}
    duplicates = 0
    total = len(files)

    def _on_skip(skip_path: str, line: int, reason: str) -> None:
        log.add_exception(skip_path, line, "", reason, "")
        log.warn(f"{skip_path}:{line} {reason}")

    for index, path in enumerate(files, start=1):
        _raise_if_cancelled(plan.cancel)
        if plan.progress is not None:
            plan.progress(index - 1, total, f"读取 {os.path.basename(path)}")

        detected = detect_format(path, plan.input_format)
        if detected not in ("fasta", "genbank"):
            log.warn(f"跳过无法识别格式的文件: {path}")
            skipped_files.append(path)
            continue

        guessed = format_from_suffix(path)
        if plan.input_format == "auto" and guessed and guessed != detected:
            log.warn(f"后缀名与内容不符，按内容判定为 {detected}: {path}")

        try:
            if detected == "genbank":
                producer = read_genbank(path, on_skip=_on_skip)
            else:
                producer = read_fasta(path)
            for record in producer:
                _raise_if_cancelled(plan.cancel)

                if record.warnings:
                    for warning in record.warnings:
                        log.warn(f"{record.origin_path}:{record.origin_line} {warning}")

                if plan.dedup == "accession":
                    key = record.accession.upper()
                    if key in seen_accessions:
                        duplicates += 1
                        log.info(
                            f"去重：{record.accession} 已出现在 {seen_accessions[key]}，"
                            f"跳过 {path}"
                        )
                        continue
                    seen_accessions[key] = path

                # 待复核项必须在去重判断**之后**登记：被去重丢弃的记录并没有写出，
                # 出现在人工复核清单里会误导用户去核对一个不存在的产物。
                if record.warnings:
                    hard = [w for w in record.warnings if not _is_benign_warning(w)]
                    if hard:
                        pending_warnings.append((record, "; ".join(hard)))
                records.append(record)
        except (FastaParseError, GenBankParseError) as error:
            log.error(f"解析失败: {path}: {error}")
            skipped_files.append(path)
            continue
        except (OSError, EOFError, zlib.error) as error:
            # 必须连 EOFError 与 zlib.error 一起捕获：损坏或截断的 .gz 在**解析阶段**
            # 抛出的正是这两类，而它们都不是 OSError 的子类。漏掉任一，一个坏文件
            # 就会中断整批处理，而不是被记入异常清单后继续。
            log.error(f"无法读取文件: {path}: {error}")
            skipped_files.append(path)
            continue

    _raise_if_cancelled(plan.cancel)
    if not records:
        raise SeqToolkitError("没有任何记录可写出")

    # 必须在任何记录加工之前建表：SequenceRecord 是 frozen dataclass，其 __eq__/__hash__
    # 覆盖全部 14 个字段，因此 with_warning()/replace() 之后的对象不再等于这里的键，
    # name_map.get(record) 会静默失配并回退到登录号，用户选的命名模式被无声忽略。
    name_map = build_name_map(records, plan.naming_mode)

    # 复核清单的「最终采用的名称」必须与实际写入的名字一致。keep 模式下
    # build_name_map 按设计返回 {}，若只写 name_map.get(record, "") 会得到空串，
    # 而 write_fasta / write_genbank 都会 `or record.accession` 回退到登录号——
    # 于是默认配置下这一列全是空白（Task 13/23 的报表与 GUI 会直接显示空列）。
    for record, reason in pending_warnings:
        log.add_exception(record.origin_path, record.origin_line,
                          record.definition or record.species_raw or record.accession,
                          reason, name_map.get(record) or record.accession)
    for record in records:
        if not record.species:
            log.add_exception(record.origin_path, record.origin_line,
                              record.definition or record.accession,
                              "物种名缺失，名称回退为登录号",
                              name_map.get(record) or record.accession)

    target = resolve_output_path(plan.output_path)
    if target != plan.output_path:
        log.warn(f"目标文件已存在，实际写入: {target}")

    if plan.progress is not None:
        plan.progress(total, total, "写出结果")

    if plan.output_format == "genbank":
        _log_genbank_write_notes(log, records, name_map)
        write_genbank(records, target, name_map)
    else:
        write_fasta(records, target, name_map, wrap=plan.wrap)

    log.info(f"完成：读入 {len(records) + duplicates} 条，写出 {len(records)} 条，"
             f"去重 {duplicates} 条，跳过文件 {len(skipped_files)} 个")

    return ProcessResult(
        records_in=len(records) + duplicates,
        records_out=len(records),
        duplicates_removed=duplicates,
        skipped_files=skipped_files,
        output_path=target,
        exceptions=list(log.exceptions),
    )


# ---------------------------------------------------------------------------
# Task 13：按序列拆分与磁盘批量重命名
# ---------------------------------------------------------------------------

_FASTA_OUT_SUFFIX = ".fasta"
_GENBANK_OUT_SUFFIX = ".gb"
_OUTPUT_FORMATS = ("fasta", "genbank")
_INPUT_FORMAT_HINTS = ("auto", "fasta", "genbank")


@dataclass
class RenamePlan:
    """磁盘重命名的结果。

    字段语义（调用方按此理解，不要自行推断）：

    - ``pairs``：进入重命名流程的文件，每项为 ``(原路径, 实际新路径)``。
      ``dry_run=False`` 时只收**改名成功**的文件；``dry_run=True`` 时收全部候选
      （预览不改盘，也就没有成功/失败之分）。
    - ``renamed``：真正在磁盘上改了名的文件数；``dry_run=True`` 时恒为 0
      （想预告「将改名几个」请用 ``len(pairs)``）。
    - ``conflicts``：**因目标文件名已被占用而被迫改用带序号名称**（``_1``、``_2``…）
      的文件，每项为 ``(原路径, 实际新路径)``。

    关于 ``conflicts`` 需要特别说明的三点，避免调用方误用：

    1. 它不是「被让位的文件」。被让位的是**已占用该名字的那个文件**，本实现不记录它；
       ``conflicts`` 记的是**被迫改名到带序号名字的那个文件自己**。
    2. 它**不保证是 ``pairs`` 的子集**。``dry_run=False`` 时若 ``rename()`` 中途失败，
       该文件只记 ERROR 日志并跳过，**不进 ``pairs``**；但如果它同时是个冲突文件，
       它的条目已经在 ``conflicts`` 里了。因此 ``conflicts ⊆ pairs`` 不成立，
       调用方**不要**用 ``len(pairs) - len(conflicts)`` 之类的算术。
    3. 「重命名中途失败」的文件只出现在**两处**，没有第三处记录：``conflicts``
       （若它恰好是个冲突文件）与日志的 ERROR 行。它**绝不**出现在 ``pairs`` 里。
    """

    pairs: list[tuple[str, str]]
    renamed: int
    conflicts: list[tuple[str, str]]


# 比较「磁盘上已有的产物」与「本次渲染结果」时用的临时文件：必须与目标同目录
# （同一卷，且比较的就是最终会落盘的那份字节），后缀刻意不在任何输入后缀集里
# （.tmp 既不是 FASTA 也不是 GenBank），万一进程被杀也留不下会被回读的伪装输入。
_STAGING_SUFFIX = ".tmp"

_COMPARE_CHUNK = 1 << 16


def _staging_path(target: str) -> str:
    """返回与 target 同目录的临时路径。带 pid，避免两次运行互相踩对方的临时文件。"""
    directory, filename = os.path.split(target)
    return os.path.join(directory, f".{filename}.{os.getpid()}{_STAGING_SUFFIX}")


def _remove_quietly(path: str, log: RunLog, what: str = "写了一半的文件") -> None:
    """清理临时/半截文件。清理失败只记 WARN，绝不抛——否则会中断整批。"""
    try:
        os.remove(path)
    except OSError:
        log.warn(f"未能清理{what}，请手动删除: {path}")


def _same_bytes(left: str, right: str) -> bool:
    """逐字节比较两个文件是否完全相同。

    读不动（例如目标路径其实是个目录、或没有读权限）时返回 False ⇒ 退回让位分支。
    宁可多写一个 ``_1``，也不能把"读不出来"当成"内容相同"而跳过该记录。
    """
    try:
        with open(left, "rb") as first, open(right, "rb") as second:
            while True:
                chunk = first.read(_COMPARE_CHUNK)
                if chunk != second.read(_COMPARE_CHUNK):
                    return False
                if not chunk:
                    return True
    except OSError:
        return False


def _write_one_record(record: SequenceRecord, name: str, path: str,
                      output_format: str, wrap: int) -> None:
    """把单条记录渲染到 path。

    显式传入 {record: name}，保证「文件名」与「文件内序列名」逐字一致；否则登录号
    为空时两边各自兜底，会算出不同的 sequence_N。
    """
    if output_format == "genbank":
        write_genbank([record], path, {record: name})
    else:
        write_fasta([record], path, {record: name}, wrap=wrap)


def split_records(records: list[SequenceRecord], out_dir: str,
                  naming_mode: str = "accession_species",
                  output_format: str = "fasta", wrap: int = 0,
                  log: RunLog | None = None) -> ProcessResult:
    """把每条序列写成独立文件，文件名为最终序列名。绝不覆盖内容不同的已存在文件。

    输入批次内按登录号去重（与 ``run_merge`` 同一口径：完整登录号、不分大小写），
    只保留首次出现者。没有登录号的记录互不判重——它们没有任何共同的登录号，
    「都没有登录号」并不意味着是同一条序列。

    「本批内重名」与「磁盘上已存在」是两件语义完全不同的事，处理方式也不同：

    - 本批内已经有记录写出了同名文件 ⇒ 判重，记 WARN 并**跳过**该记录，
      绝不追加 ``_1``。否则同一条序列会被写成 ``X.fasta`` 与 ``X_1.fasta`` 两个文件，
      用户看到的是"一条序列变成了两条"。
    - 目标是磁盘上先前就存在的文件 ⇒ 按内容分两种：**逐字节相同**时跳过
      （记 INFO、不加后缀、不覆盖），**内容不同**时让位，走 ``resolve_output_path``
      追加 ``_1`` 并 WARN。「绝不静默覆盖」这条语义不变。

    为什么要按内容细分「磁盘上已存在」：拆分输出目录落在输入文件夹内时（GUI 允许，
    并会告警），第二次运行的目标名全都已存在，无条件让位会把每个产物都复制成一个
    内容完全相同的 ``_1`` 孪生文件——正是用户报告的"同一条序列变成了两个文件"。
    同名且同字节 ⇒ 跳过不丢任何信息，所以这是安全的。

    ``ProcessResult.records_out`` 计的是「本批记录在 ``out_dir`` 里拥有的产物数」：
    因内容相同而跳过的记录**计入**（它的产物就在目标名上且内容正确），因本批内重名
    被跳过的记录**不计入**（它没有任何产物）。
    """
    log = log if log is not None else RunLog()

    # 枚举校验必须在建目录之前：output_format 传错值若被静默当成 FASTA，用户要
    # GenBank 却拿到 FASTA，且日志里一个字都没有（与 ProcessPlan.__post_init__ 同约定）。
    if output_format not in _OUTPUT_FORMATS:
        raise SeqToolkitError(f"未知输出格式: {output_format}")
    if naming_mode not in NAMING_MODES:
        raise SeqToolkitError(f"未知命名模式: {naming_mode}")

    os.makedirs(out_dir, exist_ok=True)

    # 去重必须在 build_name_map **之前**：build_name_map 按「各模式渲染出的基名是否会
    # 撞车」分配流水号，若含重复的批次先建表，去掉重复后名字里会留下空洞。
    records_in = len(records)
    unique_records: list[SequenceRecord] = []
    seen_accessions: dict[str, str] = {}
    duplicates = 0
    for record in records:
        # 空登录号不参与判重：两条都没有登录号的记录并不因此是同一条序列，
        # 合并它们等于凭空丢掉一条序列。
        key = record.accession.upper() if record.accession else ""
        if not key:
            unique_records.append(record)
            continue
        if key in seen_accessions:
            duplicates += 1
            log.info(f"去重：{record.accession} 已出现在 {seen_accessions[key]}，"
                     f"跳过 {record.origin_path}")
            continue
        seen_accessions[key] = record.origin_path
        unique_records.append(record)
    records = unique_records

    # 下面写出的就是这里建表的**同一批对象**：SequenceRecord 是 frozen dataclass，
    # 其 __eq__/__hash__ 覆盖全部 14 个字段，任何 with_warning()/replace() 之后的对象
    # 都不再等于这里的键，name_map.get(record) 会静默失配并回退到登录号。
    name_map = build_name_map(records, naming_mode)
    suffix = _GENBANK_OUT_SUFFIX if output_format == "genbank" else _FASTA_OUT_SUFFIX
    written = 0
    identical = 0
    # 本次运行已经占用的文件名（既记"渲染出的目标名"，也记"实际落盘名"：
    # 后者是让位到 _1 之后的名字，下一条记录若正好想要它，同样属于本批内重名）。
    written_names: set[str] = set()

    for record in records:
        name = name_map.get(record) or record.accession or f"sequence_{written + 1}"
        filename = f"{name}{suffix}"
        if filename in written_names:
            # 本批内重名 ⇒ 判重，跳过。绝不走 resolve_output_path：那个分支的语义是
            # 「磁盘上有上一次运行的产物，该让位」，用在这里会把一条**另一条**序列
            # 装扮成"新增的一条"，用户最终看到同一条序列被写成两个文件。
            log.warn(f"目标文件名 {filename} 与本次运行已写出的文件重名，跳过该记录"
                     f"（{record.origin_path}:{record.origin_line}），不再另写一份")
            log.add_exception(
                record.origin_path, record.origin_line,
                record.definition or record.species_raw or record.accession,
                f"目标文件名 {filename} 与本次运行已写出的文件重名，未写出", name)
            continue

        target = os.path.join(out_dir, filename)
        if os.path.exists(target):
            # 目标名已被占用：只有"内容也相同"才跳过，否则必须让位。判断内容靠的是
            # 「把这一条渲染出来」再逐字节比较——渲染是确定性的（UTF-8 + LF），
            # 同样的输入必然产生同样的字节，不需要另写一套"内容指纹"逻辑。
            staging = _staging_path(target)
            try:
                _write_one_record(record, name, staging, output_format, wrap)
            except OSError as error:
                # 与直接写目标时同一处理：单条失败不中断整批，半截文件必须清掉。
                log.error(f"写出失败，已跳过该记录: {staging}: {error}")
                _remove_quietly(staging, log, "临时文件")
                continue
            same = _same_bytes(staging, target)
            _remove_quietly(staging, log, "临时文件")
            if same:
                # 同名且同字节 ⇒ 跳过不加 _1：加了就会多出一个内容完全相同的孪生文件，
                # 用户看到"同一条序列变成了两条"。跳过不丢任何信息，所以是安全的。
                # 但必须留下说明：否则用户只知道"这次没写出文件"，不知为何。
                log.info(f"目标文件 {target} 已存在且内容相同，已跳过"
                         f"（不另写 _1、不覆盖）")
                identical += 1
                # 该记录的产物就在目标名上且内容正确，因此计入写出数：GUI 摘要里的
                # 「拆分出 N 个文件」必须与 out_dir 里属于这批记录的产物数一致。
                written += 1
                written_names.add(filename)
                continue
            # 内容不同 ⇒ 绝不静默覆盖：让位到 _1。让位结果不可能撞上本次运行刚写出的
            # 文件——那类文件必然已在磁盘上，而 resolve_output_path 只返回磁盘上不存在的
            # 名字；本批内重名（含渲染名与实际落盘名）在进入本分支之前就已由上面的
            # written_names 检查拦下。
            target = resolve_output_path(target)
            log.warn(f"目标文件已存在且内容不同，实际写入: {target}")
        try:
            _write_one_record(record, name, target, output_format, wrap)
        except OSError as error:
            # 单条记录失败不得中断整批；半截文件必须清掉，否则它会留在磁盘上被
            # 下游当成完整序列，而 records_out 里根本没有它。
            log.error(f"写出失败，已跳过该记录: {target}: {error}")
            _remove_quietly(target, log)
            continue
        written += 1
        written_names.add(filename)
        written_names.add(os.path.basename(target))

    summary = (f"拆分完成：读入 {records_in} 条，写出 {written} 个文件到 {out_dir}，"
               f"去重 {duplicates} 条")
    if identical:
        # 报数含因内容相同而跳过的记录，必须点明，否则"写出 3 个"会让人以为磁盘上
        # 多出了 3 个新文件。
        summary += f"，其中 {identical} 个已存在且内容相同、未重写"
    log.info(summary)
    return ProcessResult(
        records_in=records_in,
        records_out=written,
        duplicates_removed=duplicates,
        skipped_files=[],
        output_path=out_dir,
        exceptions=list(log.exceptions),
    )


def _preserved_suffix(name: str) -> str:
    """保留原文件名的后缀链。.gz 是外层压缩后缀，必须连同它前面的 .fa/.gbk 一起保留。

    直接用 Path.stem 会漏掉内层后缀：Path("乱名.fa.gz").stem == "乱名.fa"，算出的
    后缀只剩 ".gz"，重命名会得到 "ON1.1_Salsola_pellucida.gz"——解压工具与按后缀
    分流的代码都会认不出这是 FASTA。
    """
    inner = name[:-3] if name.lower().endswith(".gz") else name
    suffix = Path(inner).suffix
    if inner != name:
        suffix += name[-3:]
    return suffix


def rename_disk_files(paths: list[str], naming_mode: str = "accession_species",
                      recursive: bool = True, dry_run: bool = True,
                      input_format: str = "auto",
                      log: RunLog | None = None) -> RenamePlan:
    """按文件内容重命名磁盘文件本身。dry_run=True 时只返回对照表，不动磁盘。

    多记录文件以第一条记录决定新文件名，并记 INFO。目标同名时追加 _1、_2，
    **被迫改用带序号名字的那个文件**记入 ``RenamePlan.conflicts``（不是「被让位的
    文件」，也不保证是 ``pairs`` 的子集——重命名中途失败的文件只进 conflicts 与日志，
    不进 pairs；详见 ``RenamePlan`` 的 docstring）。

    参数校验（naming_mode / input_format 枚举）在任何短路之前执行，非法值一律抛
    ``SeqToolkitError``，即使是 naming_mode="keep" 这条不读文件的分支也不例外。
    """
    log = log if log is not None else RunLog()

    # 校验必须先于 keep 短路：短路在 input_format 校验之前会让
    # rename_disk_files(paths, naming_mode="keep", input_format="bogus") 静默放行，
    # 与该函数自身的校验契约（以及与 ProcessPlan.__post_init__ 的同一约定）相悖。
    if naming_mode not in NAMING_MODES:
        raise SeqToolkitError(f"未知命名模式: {naming_mode}")
    if input_format not in _INPUT_FORMAT_HINTS:
        raise SeqToolkitError(f"未知输入格式: {input_format}")

    if naming_mode == "keep":
        # "不改名" 的字面语义就是不改动文件名。若照常渲染，render_name(..., "keep")
        # 会返回登录号，导致所有文件被改名成登录号——与用户所选模式相反。
        log.info("命名规则为「不改名」，磁盘文件保持原名")
        return RenamePlan(pairs=[], renamed=0, conflicts=[])

    files = list_input_files(paths, recursive=recursive)
    pairs: list[tuple[str, str]] = []
    conflicts: list[tuple[str, str]] = []
    renamed = 0
    planned: set[str] = set()

    for path in files:
        detected = detect_format(path, input_format)
        if detected not in ("fasta", "genbank"):
            log.warn(f"跳过无法识别格式的文件: {path}")
            continue
        iterator = None
        try:
            producer = (read_genbank(path) if detected == "genbank"
                        else read_fasta(path))
            iterator = iter(producer)
            first = next(iterator)
            has_more = next(iterator, None) is not None
        except (FastaParseError, GenBankParseError) as error:
            log.error(f"无法解析，跳过重命名: {path}: {error}")
            continue
        except StopIteration:
            log.error(f"文件中没有可解析的记录，跳过重命名: {path}")
            continue
        except (OSError, EOFError, zlib.error) as error:
            # 截断或损坏的 .gz 抛的正是后两类，二者都不是 OSError 子类：
            # 漏捕获任一个，一个坏文件就会中断整批重命名。
            log.error(f"无法读取文件，跳过重命名: {path}: {error}")
            continue
        finally:
            # 必须在 rename 之前关闭生成器以释放文件句柄。多记录文件只取第一条记录
            # 就停手（has_more 判定），此时生成器停在半途、底层句柄仍被占用，
            # Windows 上紧随其后的 Path.rename 会抛 WinError 32（另一个程序正在
            # 使用此文件），该文件被静默跳过——用户看到「预览说会改名、执行却没改」。
            # 单记录文件因为第二次 next() 已耗尽生成器、句柄自动关闭，掩盖了这个问题。
            # close() 会触发生成器内部的 with 块退出，从而真正关闭文件。
            close = getattr(iterator, "close", None)
            if close is not None:
                try:
                    close()
                except (OSError, FastaParseError, GenBankParseError):
                    # 关闭阶段的失败不影响「已读到的第一条记录」这一结论，
                    # 不能让它中断整批重命名。
                    pass

        if has_more:
            log.info(f"{os.path.basename(path)} 含多条记录，"
                     f"按第一条记录 {first.accession} 决定新文件名")

        name = render_name(first, naming_mode) or first.accession
        original = Path(path)
        suffix = _preserved_suffix(original.name)

        candidate = original.with_name(f"{name}{suffix}")
        counter = 0
        while candidate.exists() and str(candidate) != str(original):
            counter += 1
            candidate = original.with_name(f"{name}_{counter}{suffix}")
        while str(candidate) in planned:
            counter += 1
            candidate = original.with_name(f"{name}_{counter}{suffix}")
        if counter:
            log.warn(f"目标名已被占用，{original.name} 将改名为 {candidate.name}")
            # 记的是**被迫让位到带序号名字的那个文件自己**（original → candidate），
            # 不是占用名字的那个文件。名字取 conflicts 而非 skipped，因为它描述的
            # 是「命名冲突」这一事实，而不是「该文件被跳过了」——下面的 rename 失败
            # 分支才是真正的跳过，且那条路径不会把条目补进 pairs。
            conflicts.append((str(original), str(candidate)))

        if not dry_run and str(candidate) != str(original):
            try:
                original.rename(candidate)
            except OSError as error:
                # 中途失败：只记 ERROR 并跳过，**不**补进 pairs。若该文件同时是冲突
                # 文件，它的条目此刻已经留在 conflicts 里——这正是 conflicts 不保证
                # 是 pairs 子集的原因（见 RenamePlan docstring 第 2 点）。
                log.error(f"重命名失败，已跳过该文件: {original}: {error}")
                continue
            renamed += 1

        pairs.append((str(original), str(candidate)))
        planned.add(str(candidate))

    mode_text = "预览" if dry_run else "执行"
    log.info(f"文件重命名{mode_text}完成：{len(pairs)} 个文件，实际改名 {renamed} 个")
    return RenamePlan(pairs=pairs, renamed=renamed, conflicts=conflicts)


# ---------------------------------------------------------------------------
# 用户使用后新增：每个输入文件各输出一个文件（convert_each_file）
#
# 用户原话：「在转换这个部分，genbank 文件转 fasta 文件的时候，无论如何输出的只有
# 一个合并的 fasta 文件，请你增加批量将 genbank 文件分别转化为 fasta 文件的功能」。
# 用两个问题确认过：输出文件名沿用原文件主干只换后缀；文件内序列名套用「命名规则」。
# ---------------------------------------------------------------------------


@dataclass
class ConvertPlan:
    """按输入文件逐个转换的计划：一个输入文件 → 一个输出文件。

    ``out_dir`` 是**输出目录**而不是某一个输出文件。这里刻意不复用
    ``ProcessPlan.output_path``：那个字段名会让人以为行为仍是"写出一个文件"，
    而本模式产出的是一批文件（数量由输入文件数决定）。
    """

    inputs: list[str]
    out_dir: str
    output_format: str = "fasta"
    input_format: str = "auto"
    naming_mode: str = "keep"
    dedup: str = "none"
    recursive: bool = True
    wrap: int = 0
    fasta_suffixes: tuple[str, ...] = DEFAULT_FASTA_SUFFIXES
    genbank_suffixes: tuple[str, ...] = DEFAULT_GENBANK_SUFFIXES
    log: RunLog | None = None
    progress: Callable[[int, int, str], None] | None = None
    cancel: threading.Event | None = None

    def __post_init__(self) -> None:
        """在构造时就校验枚举字段（与 ProcessPlan.__post_init__ 同一约定）。

        非法值必须在构造期抛 SeqToolkitError：output_format 传错值否则会静默按 FASTA
        写出（用户要 GenBank 却拿到 FASTA，且日志里一个字都没有）；naming_mode 传错值
        要等读到文件才由 build_name_map 抛 ValueError，而 ValueError 不在调用方的
        SeqToolkitError 捕获集内（GUI 层会崩）。本项目招牌规则是「永不静默」，必须在此把关。

        只做校验、不触碰其它字段：GUI 标签页在构造**之后**才赋 cancel。
        """
        if self.output_format not in _OUTPUT_FORMATS:
            raise SeqToolkitError(f"未知输出格式: {self.output_format}")
        if self.input_format not in _INPUT_FORMAT_HINTS:
            raise SeqToolkitError(f"未知输入格式: {self.input_format}")
        if self.naming_mode not in NAMING_MODES:
            raise SeqToolkitError(f"未知命名模式: {self.naming_mode}")
        if self.dedup not in ("accession", "none"):
            raise SeqToolkitError(f"未知去重方式: {self.dedup}")


def _input_stem(path: str, fasta_suffixes: Sequence[str],
                genbank_suffixes: Sequence[str]) -> str:
    """原文件名去掉「格式后缀（含可选的 .gz）」后的主干：样本.gbk.gz → 样本。

    绝不能用裸 ``Path.stem``：Path("样本.gbk.gz").stem == "样本.gbk"，输出会变成
    「样本.gbk.fasta」——按后缀分流的工具与用户都会把它认成别的格式。

    后缀表以调用方传入的为准（「设置」页允许用户自定义），表里没有的后缀
    （例如显式给出的 .custom，格式靠内容识别）退回"去掉一层扩展名"——.gz 已在
    上一步剥离，因此这个回退不会重演 Path.stem 的双后缀问题。
    """
    name = os.path.basename(str(path))
    inner = name[:-3] if name.lower().endswith(".gz") else name
    lowered = inner.lower()
    known = sorted({str(suffix).lower() for suffix in tuple(fasta_suffixes)
                    + tuple(genbank_suffixes) if suffix}, key=len, reverse=True)
    for suffix in known:
        if lowered.endswith(suffix) and len(inner) > len(suffix):
            return inner[:len(inner) - len(suffix)]
    stem, _extension = os.path.splitext(inner)
    return stem or inner


def _write_many_records(records: Sequence[SequenceRecord],
                        name_map: Mapping[SequenceRecord, str], path: str,
                        output_format: str, wrap: int) -> None:
    """把一批记录整份渲染到 path（``_write_one_record`` 的多记录版本）。"""
    if output_format == "genbank":
        write_genbank(records, path, name_map)
    else:
        write_fasta(records, path, name_map, wrap=wrap)


def convert_each_file(plan: ConvertPlan) -> ProcessResult:
    """每个输入文件各自转换成一个输出文件，输出到 ``plan.out_dir``。

    与同模块另两个入口的区别：``run_merge`` 把所有输入合并成一个文件，
    ``split_records`` 把每条**记录**拆成一个文件；本函数是"一个输入文件 = 一个输出
    文件"，多记录文件仍是一个输出文件（内含全部记录）。

    几条不变量：

    - 每个文件**独立**处理：单独读取、单独建名字表、单独写盘。命名流水号与重名保护
      的作用域因此只在单个文件内——两个文件里各有一条同物种序列，互不影响。
    - 输出文件名 = 原文件主干 + 目标格式后缀（见 ``_input_stem``）。
    - 某文件 0 条可用记录（例如只有 CONTIG 记录）⇒ WARN 并跳过，**不产出空文件**。
    - 单个文件读取/写出失败只记 ERROR 并跳过，绝不中断整批。
    - 绝不静默覆盖：目标同名且逐字节相同 ⇒ 跳过（不加 ``_1``），内容不同 ⇒ 让位
      ``_1`` 并 WARN。目标名被一个**同名目录**占着时同样让位（不删、不改动该目录，
      也不拿它去比"内容是否相同"）。与 ``split_records`` 同一语义。
    """
    log = plan.log if plan.log is not None else RunLog()

    files = list_input_files(
        plan.inputs,
        recursive=plan.recursive,
        fasta_suffixes=plan.fasta_suffixes,
        genbank_suffixes=plan.genbank_suffixes,
    )
    if not files:
        raise SeqToolkitError("没有找到可处理的输入文件")

    os.makedirs(plan.out_dir, exist_ok=True)
    suffix = (_GENBANK_OUT_SUFFIX if plan.output_format == "genbank"
              else _FASTA_OUT_SUFFIX)
    total = len(files)
    records_in = 0
    written = 0
    duplicates = 0
    identical = 0
    skipped_files: list[str] = []

    for index, path in enumerate(files, start=1):
        _raise_if_cancelled(plan.cancel)
        if plan.progress is not None:
            plan.progress(index - 1, total, f"转换 {os.path.basename(path)}")

        detected = detect_format(path, plan.input_format)
        if detected not in ("fasta", "genbank"):
            log.warn(f"跳过无法识别格式的文件: {path}")
            skipped_files.append(path)
            continue

        guessed = format_from_suffix(path)
        if plan.input_format == "auto" and guessed and guessed != detected:
            log.warn(f"后缀名与内容不符，按内容判定为 {detected}: {path}")

        def _on_skip(skip_path: str, line: int, reason: str) -> None:
            log.add_exception(skip_path, line, "", reason, "")
            log.warn(f"{skip_path}:{line} {reason}")

        try:
            producer = (read_genbank(path, on_skip=_on_skip) if detected == "genbank"
                        else read_fasta(path))
            parsed: list[SequenceRecord] = []
            for record in producer:
                _raise_if_cancelled(plan.cancel)
                if record.warnings:
                    for warning in record.warnings:
                        log.warn(f"{record.origin_path}:{record.origin_line} {warning}")
                parsed.append(record)
        except (FastaParseError, GenBankParseError) as error:
            log.error(f"解析失败: {path}: {error}")
            skipped_files.append(path)
            continue
        except (OSError, EOFError, zlib.error) as error:
            # 与 run_merge 同一理由：损坏/截断的 .gz 抛的是 EOFError 或 zlib.error，
            # 二者都不是 OSError 子类，漏捕获任一个就会让一个坏文件中断整批转换。
            log.error(f"无法读取文件: {path}: {error}")
            skipped_files.append(path)
            continue

        records_in += len(parsed)

        # 去重的作用域是**本文件**：登录号相同的序列出现在不同文件里各写一份
        # （它们属于不同的样本文件），同一条序列在同一文件内出现两次才判重。
        file_duplicates = 0
        if plan.dedup == "accession":
            unique: list[SequenceRecord] = []
            seen: dict[str, str] = {}
            for record in parsed:
                # 空登录号不参与判重：两条都没有登录号的记录并不因此是同一条序列，
                # 合并它们等于凭空丢掉一条序列（与 split_records 同一口径）。
                key = record.accession.upper() if record.accession else ""
                if not key:
                    unique.append(record)
                    continue
                if key in seen:
                    file_duplicates += 1
                    log.info(f"去重（本文件内）：{record.accession} 已出现在 "
                             f"{seen[key]}，跳过该记录")
                    continue
                seen[key] = f"{path}:{record.origin_line}"
                unique.append(record)
        else:
            unique = parsed
        duplicates += file_duplicates

        if not unique:
            log.warn(f"{path}: 没有可用记录（例如全部为 CONTIG 记录），跳过该文件")
            skipped_files.append(path)
            continue

        # 必须在任何记录加工之前建表（理由同 run_merge）：SequenceRecord 是 frozen
        # dataclass，with_warning()/replace() 之后的对象不再等于这里的键，
        # name_map.get(record) 会静默失配并回退到登录号。
        name_map = build_name_map(unique, plan.naming_mode)

        # 复核清单只收真正会写出的记录：被去重丢弃的记录没有产物，
        # 列进清单会误导用户去核对一个不存在的文件。
        for record in unique:
            if not record.species:
                log.add_exception(record.origin_path, record.origin_line,
                                  record.definition or record.accession,
                                  "物种名缺失，名称回退为登录号",
                                  name_map.get(record) or record.accession)

        stem = _input_stem(path, plan.fasta_suffixes, plan.genbank_suffixes)
        target = os.path.join(plan.out_dir, f"{stem}{suffix}")
        if os.path.exists(target):
            if os.path.isdir(target):
                # 目标名被一个**同名目录**占着（用户机器上恰好有个同名文件夹是常事）。
                # 目录里可能有用户自己的东西 ⇒ 既不删也不覆盖，走同一套「让位」策略。
                # 这里**显式**判一次目录，而不是指望 _same_bytes 去打不开的目录：后者
                # 只是碰巧因为内部吞掉 OSError 才返回 False，一旦它将来把捕获范围收窄
                # （例如只捕 FileNotFoundError），IsADirectoryError 就会从比较那行冒泡
                # 出去，整批当场中断——而"单文件失败不中断整批"是本功能的承诺，不能让
                # 它挂在另一个函数的异常口径上。另外让位前也不该说"内容不同"：目录没有
                # 内容可比，那句话是不实的，所以要单独给一句说明。
                target = resolve_output_path(target)
                log.warn(f"目标名被目录占用，未改动该目录，实际写入: {target}")
            else:
                # 目标名已被文件占用：只有"内容也相同"才跳过，否则必须让位。判断内容
                # 靠的是「把这一份渲染出来」再逐字节比较——渲染是确定性的（UTF-8+LF）。
                staging = _staging_path(target)
                try:
                    _write_many_records(unique, name_map, staging,
                                        plan.output_format, plan.wrap)
                except OSError as error:
                    log.error(f"写出失败，已跳过该文件: {staging}: {error}")
                    _remove_quietly(staging, log, "临时文件")
                    skipped_files.append(path)
                    continue
                same = _same_bytes(staging, target)
                _remove_quietly(staging, log, "临时文件")
                if same:
                    # 同名且同字节 ⇒ 跳过不加 _1：加了就会多出一个内容完全相同的孪生
                    # 文件，用户看到"同一个样本变成了两份"。跳过不丢任何信息，必须留
                    # INFO 说明，否则用户只看到"这次没写出文件"而不知为何。
                    log.info(f"目标文件 {target} 已存在且内容相同，"
                             f"已跳过（不另写 _1、不覆盖）")
                    identical += 1
                    # 该文件的内容就在目标名上且正确，因此计入写出数：GUI 摘要里的
                    # 「转换了 N 个文件」必须与 out_dir 里属于这批输入的产物数一致。
                    written += 1
                    continue
                target = resolve_output_path(target)
                log.warn(f"目标文件已存在且内容不同，实际写入: {target}")

        if plan.output_format == "genbank":
            _log_genbank_write_notes(log, unique, name_map)
        try:
            _write_many_records(unique, name_map, target, plan.output_format, plan.wrap)
        except OSError as error:
            # 单个文件失败不得中断整批；半截文件必须清掉，否则它会留在磁盘上被下游
            # 当成完整序列，而 records_out 里根本没有它。
            log.error(f"写出失败，已跳过该文件: {target}: {error}")
            _remove_quietly(target, log)
            skipped_files.append(path)
            continue
        written += 1

    _raise_if_cancelled(plan.cancel)
    if plan.progress is not None:
        plan.progress(total, total, "转换完成")

    summary = (f"批量转换完成：读入 {records_in} 条，写出 {written} 个文件到 "
               f"{plan.out_dir}，去重 {duplicates} 条（按文件内去重），"
               f"跳过文件 {len(skipped_files)} 个")
    if identical:
        # 报数含因内容相同而跳过的文件，必须点明，否则"写出 3 个"会让人以为磁盘上
        # 多出了 3 个新文件。
        summary += f"，其中 {identical} 个已存在且内容相同、未重写"
    log.info(summary)

    return ProcessResult(
        records_in=records_in,
        # records_out 数的是**写出的文件数**（本模式的产物单位是文件，不是序列条数）。
        records_out=written,
        duplicates_removed=duplicates,
        skipped_files=skipped_files,
        # 批量模式没有"那一个输出文件"：填输出目录本身。
        output_path=plan.out_dir,
        exceptions=list(log.exceptions),
    )
