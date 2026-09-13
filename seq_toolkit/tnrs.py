"""TNRS（Taxonomic Name Resolution Service）客户端与解析。纯逻辑，不 import tkinter。

契约全部来自 2026-09-12 的实测（探针 p2_tnrs.py，结论见规格 §7.1）：
``POST https://tnrsapi.xyz/tnrs_api.php``，体为
``{"opts": {...}, "data": [[整数ID, 学名], ...]}``；``data`` 恰好两列；
单请求上限 5001 行，超出返回 ``HTTP 413``；响应是 JSON 数组，每元素 46 个字段；
未匹配的标记是字面量 ``"[No match found]"``，且得分是**空字符串**而非 0。
"""

from __future__ import annotations

import csv
import http.client as http_client
import json
import os
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from .model import SeqToolkitError
from .pipeline import OperationCancelled

TNRS_URL = "https://tnrsapi.xyz/tnrs_api.php"

# 实测：发送 5100 行时返回 HTTP 413 "exceeds 5001 row limit"，故取 5000 保守值。
BATCH_LIMIT = 5000

DEFAULT_SOURCES = "wcvp,wfo"
DEFAULT_CLASS = "wfo"
MODE_RESOLVE = "resolve"          # 本工具只做"清洗"，不做 parse（见规格 D-3）
MATCHES_BEST = "best"
MATCHES_ALL = "all"

NO_MATCH = "[No match found]"


def dedupe_names(raw_lines: Iterable[str]) -> list[str]:
    """按输入顺序去重：忽略空行与首尾空白，比较时忽略大小写。

    保留**首次出现时的原始拼写**——学名的大小写有分类学含义（属名首字母大写），
    不能拿规范化后的形式去请求。
    """
    seen: set[str] = set()
    names: list[str] = []
    for raw in raw_lines:
        name = (raw or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def build_batches(names: Sequence[str], limit: int = BATCH_LIMIT) -> list[list[str]]:
    """按上限切批（每请求 ≤ limit 行）。空输入返回空列表。"""
    if limit <= 0:
        raise ValueError("批大小必须为正整数")
    return [list(names[start:start + limit])
            for start in range(0, len(names), limit)]


def build_payload(names: Sequence[str], sources: str = DEFAULT_SOURCES,
                  klass: str = DEFAULT_CLASS, matches: str = MATCHES_BEST,
                  start_id: int = 1) -> dict:
    """构造请求体。``data`` 两列：第一列整数 ID，第二列学名原文。"""
    return {
        "opts": {"sources": sources, "class": klass,
                 "mode": MODE_RESOLVE, "matches": matches},
        "data": [[start_id + offset, name] for offset, name in enumerate(names)],
    }


STATUS_MATCHED = "已匹配"
STATUS_PARTIAL = "部分匹配"
STATUS_UNMATCHED = "未匹配"


def parse_score(text) -> float | None:
    """把得分文本转成 float。

    实测：未匹配时 ``Overall_score`` 是**空字符串**（不是 0、不是 null），
    因此不能写 ``float(text or 0)``——那会把"没匹配上"误记成"得分 0"。
    """
    if text is None:
        return None
    stripped = str(text).strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


@dataclass(frozen=True)
class TnrsRow:
    """TNRS 返回的一行结果（只保留本工具用到的字段）。"""

    row_id: str
    submitted: str
    name_matched: str
    score: float | None
    accepted_name: str
    accepted_rank: str
    accepted_author: str
    family_matched: str
    source: str
    warnings: str
    unmatched_terms: str
    candidate_index: int = 1

    @property
    def status(self) -> str:
        """三态判定。

        **判据必须是字面量比较**：未匹配时 ``Name_matched`` 是 ``"[No match found]"``
        而不是空串或 null，靠 falsy 判断会把未匹配错认成已匹配。

        **得分未知判为"部分匹配"**：TNRS 对匹配成功的行会给可解析的分数，
        "有名字但没有分数"属异常形状。把它当满分匹配，这类行会静默进入结果表与统计
        （"绝不静默"约束瞄准的正是这种无声误报）；判成部分匹配则会出现在计数里、
        被人工复核。代价是极少数异常行要多看一眼，方向明显更安全。
        """
        if not self.name_matched or self.name_matched == NO_MATCH:
            return STATUS_UNMATCHED
        if self.score is None or self.score < 1.0:
            return STATUS_PARTIAL
        return STATUS_MATCHED

    @property
    def key(self) -> str:
        """表格行键：ID + 候选序号。

        ``matches=all`` 时一个名称会有多行，只用 ID 作键会让
        ``CheckboxTable.set_rows()`` 的按 key 去重**静默丢掉后续候选**。
        """
        return f"{self.row_id}|{self.candidate_index}"


def _text(row: dict, key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value).strip()


def parse_response(text: str) -> list[TnrsRow]:
    """解析 TNRS 响应。

    非 JSON、或顶层不是数组 ⇒ 抛 ``ValueError``（调用方据此记 ERROR 并打印响应片段）。
    数组里非对象的元素直接跳过：服务端偶尔会插入说明字符串，不该让整批解析失败。
    """
    import json

    try:
        payload = json.loads(text)
    except (ValueError, TypeError) as error:
        raise ValueError(f"TNRS 响应不是合法 JSON: {error}") from error
    if not isinstance(payload, list):
        raise ValueError("TNRS 响应不是数组（期望 JSON 数组，每元素一个对象）")

    rows: list[TnrsRow] = []
    candidates: dict[str, int] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        row_id = _text(item, "ID")
        candidates[row_id] = candidates.get(row_id, 0) + 1
        rows.append(TnrsRow(
            row_id=row_id,
            submitted=_text(item, "Name_submitted"),
            name_matched=_text(item, "Name_matched"),
            score=parse_score(item.get("Overall_score")),
            accepted_name=_text(item, "Accepted_name"),
            accepted_rank=_text(item, "Accepted_name_rank"),
            accepted_author=_text(item, "Accepted_name_author"),
            family_matched=_text(item, "Family_matched"),
            source=_text(item, "Source"),
            warnings=_text(item, "WarningsEng") or _text(item, "Warnings"),
            unmatched_terms=_text(item, "Unmatched_terms"),
            candidate_index=candidates[row_id],
        ))
    return rows


def summarize_status(rows: Iterable[TnrsRow]) -> dict[str, int]:
    """按三态计数，供界面顶部的统计行使用。"""
    counts = {STATUS_MATCHED: 0, STATUS_PARTIAL: 0, STATUS_UNMATCHED: 0}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts


class TnrsError(SeqToolkitError):
    """TNRS 请求失败（网络不可达、响应异常等）。"""


def http_post(payload: dict, proxy: str = "", timeout: int = 120) -> str:
    """真实 HTTP 请求。单元测试一律用替身，不进这里。"""
    handlers = []
    if proxy:
        handlers.append(ProxyHandler({"http": proxy, "https": proxy}))
    opener = build_opener(*handlers).open
    request = Request(TNRS_URL, data=json.dumps(payload).encode("utf-8"),
                      method="POST",
                      headers={"Content-Type": "application/json",
                               "Accept": "application/json",
                               "charset": "UTF-8"})
    try:
        with opener(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        body = ""
        try:
            body = error.read().decode("utf-8", errors="replace")[:200]
        except Exception:  # noqa: BLE001 读错误体失败不影响报错
            pass
        raise TnrsError(f"TNRS 返回 {error.code}: {error.reason} {body}".strip()) from error
    except URLError as error:
        raise TnrsError(f"无法连接 TNRS: {error.reason}") from error
    except (OSError, http_client.HTTPException) as error:
        # 读阶段（response.read()）的超时与断连抛的是**裸 OSError**（TimeoutError、
        # ConnectionResetError），urlopen 只在建连/取响应头阶段才把它包成 URLError。
        # 不收进来，异常会穿过 clean_names 的 except 列表让整批清洗崩掉——
        # 与「单批失败不得中断整批」直接冲突。
        # 分支顺序不可调换：HTTPError ⊂ URLError ⊂ OSError，提前会改掉既有报错文案。
        raise TnrsError(f"读取 TNRS 响应失败: {error}") from error


@dataclass
class TnrsReport:
    """一次清洗的完整结果。

    ``failures`` 记的是**批次**（第几批、错误原因）：单批失败不影响其余批次，
    但必须显式归因，否则用户看到的行数会少于输入名称数而无从解释。

    ``mismatched_batches`` 记的是"提交了几个名称、只回来几行"的批次：
    服务端丢行、或响应里混进非对象元素被 :func:`parse_response` 跳过，都会让结果
    静默少几行；只有拿请求端与返回端对账，这类缺口才会暴露在界面与日志里。
    """

    names: list[str]
    rows: list[TnrsRow]
    batches: int
    failures: list[tuple[int, str]] = field(default_factory=list)
    # 提交名称数与该批返回行数不一致的批次：(批次号从 1 起, 提交名称数, 返回行数)。
    # 服务端正常情况下对 best 模式是"一个名称一行"，数量对不上就意味着有行没回来
    # （被跳过的非对象元素、服务端丢行等），必须显式报出而不是静默少几行。
    mismatched_batches: list[tuple[int, int, int]] = field(default_factory=list)

    @property
    def unmatched_names(self) -> list[str]:
        return [row.submitted for row in self.rows if row.status == STATUS_UNMATCHED]


def clean_names(post: Callable[[dict], str], names: Sequence[str],
                sources: str = DEFAULT_SOURCES, klass: str = DEFAULT_CLASS,
                matches: str = MATCHES_BEST,
                on_progress: Callable[[int, int, str], None] | None = None,
                cancel: threading.Event | None = None) -> TnrsReport:
    """分批清洗。``post(payload) -> str`` 由调用方提供（真实实现是 http_post）。

    单批失败只记入 ``failures`` 并继续：一批网络抖动不该让其余名称一条都拿不到。
    """
    batches = build_batches(names)
    total = len(batches)
    rows: list[TnrsRow] = []
    failures: list[tuple[int, str]] = []
    mismatched_batches: list[tuple[int, int, int]] = []
    next_id = 1
    for index, batch in enumerate(batches, start=1):
        if cancel is not None and cancel.is_set():
            raise OperationCancelled("操作已取消")
        if on_progress is not None:
            on_progress(index - 1, total, f"清洗第 {index}/{total} 批")
        payload = build_payload(batch, sources=sources, klass=klass,
                                matches=matches, start_id=next_id)
        before = len(rows)
        try:
            rows.extend(parse_response(post(payload)))
        except OperationCancelled:
            raise
        # OSError 也在捕获列表里：注入的 post 若把读阶段的裸 OSError（TimeoutError 等）
        # 泄漏出来，没有它整批清洗会崩掉——「单批失败不得中断整批」是硬约束。
        # 真实的 http_post 已把这类错误包成 TnrsError，这里是第二层防御。
        except (SeqToolkitError, ValueError, OSError) as error:
            failures.append((index, str(error)))
        else:
            returned = len(rows) - before
            if returned != len(batch):
                mismatched_batches.append((index, len(batch), returned))
        next_id += len(batch)
    if on_progress is not None:
        on_progress(total, total, "清洗完成")
    return TnrsReport(names=list(names), rows=rows, batches=total,
                      failures=failures, mismatched_batches=mismatched_batches)


CSV_HEADERS = ("原始名称", "清洗后名称", "匹配状态", "备注")


def rows_to_csv(rows: Iterable[TnrsRow]) -> list[tuple[str, str, str, str]]:
    """导出用的四列（用户指定）。备注列合并英文警告与未匹配残留词。"""
    out: list[tuple[str, str, str, str]] = []
    for row in rows:
        notes = [part for part in (row.warnings, row.unmatched_terms) if part]
        out.append((row.submitted, row.accepted_name or row.name_matched,
                    row.status, "；".join(notes)))
    return out


def write_csv(path, rows: Iterable[TnrsRow]) -> None:
    """写出 CSV。``utf-8-sig`` 与既有异常清单导出一致（Excel 双击不乱码）。"""
    with open(str(path), "wt", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADERS)
        for record in rows_to_csv(rows):
            writer.writerow(record)


def build_rename_map(rows: Iterable[TnrsRow]) -> dict[str, str]:
    """构造「原始名 → 接受名」映射。

    只收**匹配成功**的行；同一原始名有多个候选（``matches=all``）时取第一条，
    其余候选的接受名不同则记入返回值之外由调用方报告（见 ``apply_names_to_files``）。
    未匹配（``[No match found]``）的名称绝不参与替换。
    """
    mapping: dict[str, str] = {}
    for row in rows:
        if row.status == STATUS_UNMATCHED:
            continue
        accepted = row.accepted_name or row.name_matched
        if not accepted:
            continue
        mapping.setdefault(row.submitted, accepted)
    return mapping


def conflicting_names(rows: Iterable[TnrsRow]) -> dict[str, list[str]]:
    """同一原始名给出多个**不同**接受名的名称（``matches=all`` 下会发生）。

    返回 ``{原始名: [候选接受名, ...]}``（去重、保持顺序）。界面据此提示用户改用
    ``best`` 模式重跑，绝不静默挑一条了事。
    """
    seen: dict[str, list[str]] = {}
    for row in rows:
        if row.status == STATUS_UNMATCHED:
            continue
        accepted = row.accepted_name or row.name_matched
        if not accepted:
            continue
        bucket = seen.setdefault(row.submitted, [])
        if accepted not in bucket:
            bucket.append(accepted)
    return {name: values for name, values in seen.items() if len(values) > 1}


def rewrite_text(text: str, mapping: dict[str, str], *,
                 genbank: bool) -> tuple[str, int]:
    """在文本层面替换物种名，返回 ``(新文本, 替换处数)``。

    - FASTA：只动以 ``>`` 开头的 header 行，序列行一个字节都不碰
    - GenBank：只动 ``DEFINITION`` / ``SOURCE`` / ``ORGANISM`` 行与 ``/organism=``
      限定符行；``ORIGIN`` 段与其余字段逐字节保真（与 genbank_io 的保真文化一致）

    匹配是**字面子串替换**（``old in line`` / ``line.replace``），并按映射的字典顺序
    逐条应用，因此：键若写成属级或前缀名（如 ``"Salsola"``），会改出
    ``Salsola australis pellucida`` 这种不存在的学名；若某个接受名恰好等于另一条的
    原始名，后一条会在已改写的文本上再改一遍。调用方应使用**完整学名**做键。
    """
    in_origin = False
    count = 0
    out_lines: list[str] = []
    for line in text.split("\n"):
        if genbank:
            if line.startswith("ORIGIN"):
                in_origin = True
                out_lines.append(line)
                continue
            if not in_origin:
                editable = (line.startswith(("DEFINITION", "SOURCE"))
                            or line.lstrip().startswith("ORGANISM")
                            or "/organism=" in line)
                if editable:
                    for old, new in mapping.items():
                        if old and old in line:
                            count += line.count(old)
                            line = line.replace(old, new)
            out_lines.append(line)
            continue
        if line.startswith(">"):
            for old, new in mapping.items():
                if old and old in line:
                    count += line.count(old)
                    line = line.replace(old, new)
        out_lines.append(line)
    return "\n".join(out_lines), count


@dataclass(frozen=True)
class RenameOutcome:
    """一个文件回写的结果。``missing`` 是在该文件里一个都没找到的名称。"""

    source: str
    target: str
    replacements: int
    missing: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


def apply_names_to_file(path: str, mapping: dict[str, str], out_dir: str,
                        log=None) -> RenameOutcome:
    """把一个序列文件的物种名替换成接受名，**另存为 ``<主干>_cleaned<后缀>``**。

    绝不就地覆盖：名称回写是破坏性操作，必须可回退（规格 D-6）。
    输出名与磁盘上已有文件撞车时让位 ``_1`` 并 WARN。
    """
    from .format_detect import detect_format
    from .pipeline import resolve_output_path
    from .textio import has_decoding_damage

    source = str(path)
    if source.lower().endswith(".gz"):
        # 压缩输入必须显式拒绝。以文本模式 errors="replace" 读 .gz 不会抛异常，
        # 只会把二进制解成替换字符，于是"一个名称都没找到"→ 写出一个内容损坏、
        # replacements=0 的 _cleaned.gz，而用户以为处理成功了——静默损坏数据。
        raise TnrsError(f"压缩文件暂不支持回写，请先解压后再试: {source}")
    detected = detect_format(source)
    if detected not in ("fasta", "genbank"):
        raise TnrsError(f"无法识别格式，跳过: {source}")
    with open(source, "rb") as handle:
        raw = handle.read()
    try:
        # 用 strict 解码而不是 errors="replace"：替换模式不抛异常，只会把非 UTF-8
        # 字节（中文 Windows 上常见的 GBK）静默解成 U+FFFD 再写进 _cleaned 文件——
        # 用户以为处理成功，拿到的却是内容损坏的产物。宁可明确报错让他先转码。
        # 用 bytes.decode 而不是 open(newline=...)：既保留 \r\n 原样，又能拿到
        # UnicodeDecodeError 而不是被替换模式吞掉。
        # 边界（不宣称彻底解决）：少数 GBK 字节对恰好也是合法 UTF-8 时会被解成乱码
        # 且不抛异常——这是编码探测的固有限制，strict 解码挡不住这一小类。
        original = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise TnrsError(
            f"文件不是 UTF-8 编码，回写会写出内容损坏的文件，请先转码为 UTF-8: "
            f"{source}（{error}）") from error
    if has_decoding_damage(original):
        raise TnrsError(
            f"文件里已有替换字符 U+FFFD（可能此前被别的工具损坏过），"
            f"请先修复后再试: {source}")

    rewritten, count = rewrite_text(original, mapping, genbank=(detected == "genbank"))
    found = {name for name in mapping if name and name in original}
    missing = tuple(name for name in mapping if name not in found)

    base_name = os.path.basename(source)
    stem, extension = os.path.splitext(base_name)
    if base_name.lower().endswith(".gz"):
        stem, extension = os.path.splitext(stem)[0], ".gz"
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, f"{stem}_cleaned{extension}")
    final = resolve_output_path(target)
    if final != target and log is not None:
        log.warn(f"目标文件已存在，实际写入: {final}")

    with open(final, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write(rewritten)
    return RenameOutcome(source=source, target=final, replacements=count,
                         missing=missing)
