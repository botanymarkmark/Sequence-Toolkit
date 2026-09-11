"""NCBI E-utilities 客户端：限速、重试、代理、分批。"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import zlib
from dataclasses import dataclass, field
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from .applog import RunLog
from .fasta_io import read_fasta, write_fasta
from .format_detect import detect_format, list_input_files
from .genbank_io import read_genbank, write_genbank
from .model import SequenceRecord, SeqToolkitError, parse_accession
from .naming import NAMING_MODES, build_name_map, sanitize_accession
from .pipeline import OperationCancelled, resolve_output_path

NCBI_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL_NAME = "seq_toolkit"

RATE_WITHOUT_KEY = 3.0
RATE_WITH_KEY = 10.0

MAX_SUMMARY_BATCH = 500
MAX_FETCH_BATCH = 200

# 合并产物的固定文件名（下载目录下与逐序列文件并存）
MERGED_FASTA_NAME = "all_sequences.fasta"
MERGED_GENBANK_NAME = "all_sequences.gb"

# 逐序列产物的后缀。**输出侧统一用 .fasta**：旧行为写 .fa，用户拿到手的下载产物后缀
# 是 .fa，与合并产物 all_sequences.fasta 不一致。这里定义常量而不是把字面量散落在
# 各处，避免"改了写出路径、漏了预跳过判据"这种半改。
# 注意这只约束**写出**：读取侧仍由 format_detect.DEFAULT_FASTA_SUFFIXES 说了算，
# 它继续接受 .fa/.fna/... —— 用户手上的老文件就是这些后缀，不能只认一种。
FASTA_FILE_SUFFIX = ".fasta"
GENBANK_FILE_SUFFIX = ".gb"

# NCBI 对无效号、撤稿号会直接略过该 id 且不报错：差额必须显式归因，否则静默丢数据
MISSING_RECORD_REASON = "NCBI 未返回该登录号的记录"


class NcbiError(SeqToolkitError):
    """NCBI 请求失败（网络不可达、被限流、响应异常等）。"""


COMPLETE_GENOME_PATTERNS = (
    "complete genome",
    "complete chloroplast genome",
    "complete plastid genome",
    "complete mitochondrial genome",
    "complete plastome",
    "complete mitochondrial dna",
)

KNOWN_SCOPES = ("species", "genus")


def matches_complete_genome(definition: str) -> bool:
    """本地判定"是否完整基因组"。NCBI 服务端没有可信字段，只能按定义行匹配。"""
    lowered = (definition or "").lower()
    return any(pattern in lowered for pattern in COMPLETE_GENOME_PATTERNS)


_ACCESSION_SPLITTER = re.compile(r"[\s,;]+")


def parse_accession_text(text: str) -> list[str]:
    """把粘贴的文本切成登录号列表：转大写、去重、保持出现顺序。

    按空白 / 逗号 / 分号一起切分，而不是逐行切分：从网页或表格里复制出来的登录号常常
    混用这几种分隔符。去重后再交给下载流程，避免同一个登录号被请求两次（NCBI 会返回
    两条记录，白白多下一遍）。
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for chunk in _ACCESSION_SPLITTER.split(text or ""):
        token = chunk.strip().upper()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def collect_accessions_from_files(paths, recursive: bool = True,
                                  fasta_suffixes=None,
                                  genbank_suffixes=None,
                                  log: RunLog | None = None) -> list[str]:
    """从已有的 FASTA / GenBank 文件中提取登录号，去重并保持顺序。

    ``fasta_suffixes`` / ``genbank_suffixes`` 缺省用 :mod:`format_detect` 的默认后缀表；
    传 ``None`` 以外的值时按它展开文件夹（「设置」页里自定义的后缀名据此生效，否则
    用户加的后缀会被静默忽略）。

    单个文件读不动（截断的 gzip、损坏的 GenBank）只记一条 WARN 并跳过该文件，不中断
    整次提取：用户选了一堆文件时，一个坏文件不该让其余登录号一个都拿不到。

    异常捕获集必须与 :func:`pipeline.run_merge` 保持一致，写成
    ``(OSError, EOFError, zlib.error)``：截断的 .gz 抛的是 ``EOFError``、deflate 数据体
    损坏抛的是 ``zlib.error``，两者都**不是** ``OSError`` 的子类。本函数的 GUI 调用点
    （``tab_accession``）直接从 Tk 回调里调用它、外层没有 try，只捕 SeqToolkitError 时
    这类异常会一路逃到 Tk 主循环——界面零反应：没有日志、没有对话框，按钮像没电一样。
    """
    keyword = {}
    if fasta_suffixes is not None:
        keyword["fasta_suffixes"] = fasta_suffixes
    if genbank_suffixes is not None:
        keyword["genbank_suffixes"] = genbank_suffixes

    seen: set[str] = set()
    ordered: list[str] = []
    for path in list_input_files(paths, recursive=recursive, **keyword):
        detected = detect_format(path)
        try:
            if detected == "genbank":
                records = read_genbank(path)
            elif detected == "fasta":
                records = read_fasta(path)
            else:
                continue
            for record in records:
                if record.accession and record.accession not in seen:
                    seen.add(record.accession)
                    ordered.append(record.accession)
        except SeqToolkitError as error:
            # 解析层判定（损坏的 GenBank/FASTA 等）：跳过该文件，其余照常提取。
            if log is not None:
                log.warn(f"跳过无法提取登录号的文件: {path}: {error}")
            continue
        except (OSError, EOFError, zlib.error) as error:
            # 必须连 EOFError 与 zlib.error 一起捕获：损坏或截断的 .gz 抛出的正是这两类，
            # 而它们都不是 OSError 的子类。漏掉任一，一个坏文件就会中断整次提取。
            if log is not None:
                log.warn(f"跳过无法读取的文件: {path}: {error}")
            continue
    return ordered


def build_query(term: str, scope: str = "species", min_length: int | None = None,
                max_length: int | None = None, refseq_only: bool = False) -> str:
    """构造 nuccore 检索式。物种名加引号精确匹配，属名不加引号以覆盖属下所有种。"""
    cleaned = (term or "").strip()
    if not cleaned:
        raise ValueError("检索词不能为空")
    if scope not in KNOWN_SCOPES:
        raise ValueError(f"未知检索范围: {scope}")

    clause = f'"{cleaned}"[Organism]' if scope == "species" else f"{cleaned}[Organism]"
    parts = [clause]
    if min_length is not None or max_length is not None:
        low = 0 if min_length is None else int(min_length)
        high = 1_000_000_000 if max_length is None else int(max_length)
        parts.append(f"{low}:{high}[SLEN]")
    if refseq_only:
        parts.append("srcdb_refseq[prop]")
    return " AND ".join(parts)


@dataclass
class SearchResult:
    query: str
    total: int
    ids: list[str]
    webenv: str = ""
    query_key: str = ""


@dataclass
class SeqSummary:
    accession: str
    length: int
    organism: str
    definition: str
    date: str = ""
    source_db: str = ""


@dataclass
class DownloadOptions:
    """一次批量下载的全部选项。

    ``naming_mode`` 用 :data:`seq_toolkit.naming.NAMING_MODES` 的取值；
    ``wrap`` 只影响 FASTA（0 表示整条序列写一行）。
    """

    out_dir: str
    want_fasta: bool = True
    want_genbank: bool = True
    per_sequence_files: bool = True
    merged_files: bool = True
    naming_mode: str = "accession"
    force_redownload: bool = False
    wrap: int = 0


@dataclass
class DownloadReport:
    """一次批量下载的结果。

    **计数单位是登录号（请求的那一个），不是响应里的记录条数**，四者恒满足
    ``succeeded + skipped + failed == total``：

    - ``succeeded``：下载并写出的登录号数。口径随配置变化——``per_sequence_files``
      为真时它数的是"真正落盘的序列"；为假（不写单序列文件）时它数的是"本次收下
      的登录号"，这些序列只出现在合并产物里（若 ``merged_files`` 也为假则什么都不
      落盘，因此那种组合在校验阶段就被拒绝）。
    - ``skipped``：因产物已存在而跳过的登录号数（含下载前按登录号预判跳过、
      以及拿到记录后才发现文件已存在两种）。
    - ``failed``：``failures`` 的条数，即下载或写出失败的登录号数，含三类——
      逐条重试后仍失败、**NCBI 未返回该登录号的记录**（无效号 / 撤稿号会被直接略过，
      若不计入这里差额就被静默吞掉）、写出产物时报错（磁盘满、文件名被占用）。
    """

    total: int
    succeeded: int
    skipped: int
    failed: int
    out_dir: str
    failures: list[tuple[str, str]] = field(default_factory=list)
    merged_fasta: str = ""
    merged_genbank: str = ""


def _accession_key(accession: str) -> str:
    """宽松匹配键：登录号基号（去版本号）大写。

    NCBI 允许按 GI、旧号或别的版本形式请求，返回的 ``accession`` 可能与请求形式
    不同（常常只差版本号）。严格逐字比较会把好记录误判成"未返回"，把好数据记成
    失败；因此对账一律走这个键。
    """
    return parse_accession(accession).base.upper()


def _exists_nonempty(path: str) -> bool:
    """判断文件存在且非空。

    空文件往往是上次中断留下的残迹（已创建但没写进任何内容），把它当作"已下载"
    会让用户永远拿不到这条序列，因此判据是"存在**且**非空"。
    """
    return os.path.exists(path) and os.path.getsize(path) > 0


class RateLimiter:
    """令牌桶限速：保证相邻两次请求至少间隔 1/rate 秒。"""

    def __init__(self, rate_per_second: float,
                 clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self._interval = 1.0 / float(rate_per_second)
        self._clock = clock
        self._sleep = sleeper
        self._last: float | None = None
        self._lock = threading.Lock()

    @property
    def interval(self) -> float:
        """相邻两次请求的最小间隔（秒），即 1/rate。"""
        return self._interval

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last is not None:
                wait = self._interval - (now - self._last)
                if wait > 0:
                    self._sleep(wait)
                    now = self._clock()
            self._last = now


class NcbiClient:
    """封装 E-utilities 调用。opener / sleeper / clock 均可注入，便于离线测试。

    时间只有一个来源：注入的 ``clock``。限速器（:class:`RateLimiter`）与重试退避
    （:meth:`_wait`）共用它，因此"退避已经消耗掉的时间"天然计入限速额度，
    无需第二套计时。
    """

    def __init__(self, email: str, api_key: str | None = None,
                 proxy: str | None = None, tool: str = TOOL_NAME,
                 log: RunLog | None = None, cancel: threading.Event | None = None,
                 opener: Callable | None = None,
                 sleeper: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.email = email or ""
        self.api_key = api_key or ""
        self.proxy = proxy or ""
        self.tool = tool
        self.log = log
        self.cancel = cancel
        self._sleep = sleeper
        self._clock_source = clock
        self._clock_credit = 0.0
        self.rate_limit = RATE_WITH_KEY if self.api_key else RATE_WITHOUT_KEY
        self.limiter = RateLimiter(self.rate_limit, clock=self._clock, sleeper=sleeper)
        self._opener = opener if opener is not None else self._build_opener()

    def _clock(self) -> float:
        """限速器唯一的时间源：注入时钟 + 注入 sleeper 已消耗而时钟未记录的部分。

        若 sleeper 自己就推进同一个 ``clock``（测试中的配套假时钟：sleeper 推进时钟、
        时钟返回假时间），下面的差值为 0，补偿自动失效，同一段时间不会被算两遍。
        只有"sleeper 不推进时钟"的注入方式（如仅记录的 ``delays.append``）才会被补偿。
        """
        return self._clock_source() + self._clock_credit

    def _wait(self, seconds: float) -> None:
        """退避等待：统一走注入的 sleeper，并把这段时间记到限速器的时间源上。

        硬约束：不论时钟是否被注入，相邻两次真实请求的间隔都不得小于 ``1/rate``。
        因此等待量至少取 ``1/rate``——退避值当前是 1/2/4/5/7 秒（都 ≥ 1/rate），但将来
        若引入亚秒退避（例如 3 次/秒下的 0.2 秒），直接等 0.2 秒就会让真实间隔小于
        1/rate，硬约束被无声破坏。这里取 max 夹紧，把该前提变成代码里的守卫。
        """
        waited = max(float(seconds), self.limiter.interval)
        before = self._clock()
        self._sleep(waited)
        after = self._clock()
        self._clock_credit += waited - (after - before)

    def _build_opener(self) -> Callable:
        handlers = []
        if self.proxy:
            handlers.append(ProxyHandler({"http": self.proxy, "https": self.proxy}))
        director = build_opener(*handlers)
        return director.open

    def _check_cancelled(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise OperationCancelled("操作已取消")

    def _request(self, endpoint: str, params: dict, method: str = "GET",
                 retries: int = 3) -> str:
        url = f"{NCBI_BASE_URL}/{endpoint}"
        payload = dict(params)
        payload.setdefault("tool", self.tool)
        if self.email:
            payload.setdefault("email", self.email)
        if self.api_key:
            payload.setdefault("api_key", self.api_key)

        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            self._check_cancelled()
            self.limiter.acquire()
            try:
                if method == "POST":
                    request = Request(url, data=urlencode(payload).encode("utf-8"),
                                      method="POST")
                else:
                    request = Request(f"{url}?{urlencode(payload)}")
                with self._opener(request) as response:
                    return response.read().decode("utf-8", errors="replace")
            except HTTPError as error:
                last_error = error
                if error.code == 429:
                    header = error.headers.get("Retry-After") if error.headers else None
                    delay = float(header) if header and str(header).isdecimal() else 5.0
                    if self.log is not None:
                        self.log.warn(f"NCBI 限流（429），等待 {delay:.0f} 秒后重试")
                elif 500 <= error.code < 600:
                    delay = float(2 ** (attempt - 1))
                else:
                    # 4xx（除 429）是客户端错误，重试没有意义
                    raise NcbiError(f"NCBI 返回 {error.code}: {error.reason}") from error
            except URLError as error:
                last_error = error
                delay = float(2 ** (attempt - 1))

            # 最后一次尝试失败后不再等待，直接抛错
            if attempt < retries:
                self._wait(delay)

        raise NcbiError(f"请求失败（已重试 {retries} 次）: {last_error}")

    def search(self, term: str, scope: str = "species", retmax: int = 500,
               min_length: int | None = None, max_length: int | None = None,
               refseq_only: bool = False) -> SearchResult:
        """检索 nuccore，返回命中总数与首批 id（附历史记录供分页取全量）。

        ``build_query`` 在发请求之前调用，所以非法检索式抛出的 ``ValueError`` 不会被
        ``_request`` 的重试逻辑吞掉（它只捕获 HTTPError / URLError）。
        """
        query = build_query(term, scope, min_length, max_length, refseq_only)
        text = self._request("esearch.fcgi", {
            "db": "nuccore", "term": query, "retmode": "json",
            "usehistory": "y", "retmax": str(retmax),
        })
        try:
            payload = json.loads(text)
            result = payload["esearchresult"]
        except (ValueError, KeyError, TypeError) as error:
            raise NcbiError(f"esearch 响应无法解析: {error}") from error
        if not isinstance(result, dict):
            raise NcbiError("esearch 响应无法解析: esearchresult 不是对象")
        return SearchResult(
            query=query,
            total=int(result.get("count", 0) or 0),
            ids=list(result.get("idlist", []) or []),
            webenv=result.get("webenv", "") or "",
            query_key=str(result.get("querykey", "") or ""),
        )

    def summarize(self, accessions: list[str]) -> list[SeqSummary]:
        """批量取元数据，每批至多 :data:`MAX_SUMMARY_BATCH` 个 id，批间检查取消。"""
        summaries: list[SeqSummary] = []
        for start in range(0, len(accessions), MAX_SUMMARY_BATCH):
            self._check_cancelled()
            batch = accessions[start:start + MAX_SUMMARY_BATCH]
            text = self._request("esummary.fcgi", {
                "db": "nuccore", "retmode": "json", "id": ",".join(batch),
            })
            summaries.extend(self._parse_summaries(text))
        return summaries

    @staticmethod
    def _parse_summaries(text: str) -> list[SeqSummary]:
        """解析 esummary 响应。缺失 / 非 dict / slen 非法只跳过该条，不拖垮整批。"""
        try:
            payload = json.loads(text)
            result = payload["result"]
        except (ValueError, KeyError, TypeError) as error:
            raise NcbiError(f"esummary 响应无法解析: {error}") from error
        if not isinstance(result, dict):
            raise NcbiError("esummary 响应无法解析: result 不是对象")
        uids = result.get("uids", []) or []
        summaries: list[SeqSummary] = []
        for uid in uids:
            doc = result.get(uid)
            if not isinstance(doc, dict):
                continue
            try:
                length = int(doc.get("slen") or 0)
            except (TypeError, ValueError):
                length = 0
            summaries.append(SeqSummary(
                accession=doc.get("accessionversion") or doc.get("caption") or "",
                length=length,
                organism=doc.get("organism") or "",
                definition=doc.get("title") or "",
                date=doc.get("createdate") or "",
                source_db=doc.get("sourcedb") or "",
            ))
        return summaries

    def search_summaries(self, term: str, scope: str = "species",
                         retmax: int = 500, min_length: int | None = None,
                         max_length: int | None = None, refseq_only: bool = False,
                         complete_genome_only: bool = False,
                         refseq_only_local: bool = False,
                         ) -> tuple[SearchResult, list[SeqSummary]]:
        """检索 + 取元数据 + 本地筛选（长度、完整基因组、RefSeq）。

        ``refseq_only`` 进检索式（服务端条件）；``refseq_only_local`` 按
        ``source_db == "RefSeq"`` 在本地再筛一遍，两者互不替代。
        """
        result = self.search(term, scope, retmax, min_length, max_length, refseq_only)
        if not result.ids:
            return result, []
        summaries = self.summarize(result.ids)
        if min_length is not None:
            summaries = [s for s in summaries if s.length >= min_length]
        if max_length is not None:
            summaries = [s for s in summaries if s.length <= max_length]
        if complete_genome_only:
            summaries = [s for s in summaries if matches_complete_genome(s.definition)]
        if refseq_only_local:
            summaries = [s for s in summaries if s.source_db == "RefSeq"]
        return result, summaries

    # ------------------------------------------------------------------
    # Task 17：序列获取（efetch）与批量下载编排
    # ------------------------------------------------------------------

    def _batch(self, accessions: list[str]) -> list[list[str]]:
        """按 :data:`MAX_FETCH_BATCH` 切批：efetch 一次最多取 200 条。"""
        return [list(accessions[start:start + MAX_FETCH_BATCH])
                for start in range(0, len(accessions), MAX_FETCH_BATCH)]

    @staticmethod
    def _write_temp(text: str, suffix: str) -> str:
        """把网络文本落盘，供既有解析器按路径读取。调用方负责删除。

        后缀名不能以 .gz 结尾：``textio.open_text`` 见到 .gz 会走 gzip 解压分支，
        把纯文本当压缩流读会直接报错。

        写入本身也可能失败（磁盘满、编码错），此时必须在这里清掉半截临时文件——
        调用方的 ``finally`` 只在 ``_write_temp`` 正常返回后才有路径可删。
        """
        handle = tempfile.NamedTemporaryFile(
            "wt", suffix=suffix, delete=False, encoding="utf-8", newline="\n")
        try:
            try:
                handle.write(text)
            finally:
                handle.close()
        except BaseException:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise
        return handle.name

    @staticmethod
    def _write_atomic(target: str, write: Callable[[str], None]) -> None:
        """原子写出：先写同目录的 ``target + ".part"``，成功后再 ``os.replace``。

        直接写目标文件时，磁盘满 / 文件名被占用会留下**半截文件**，而跳过判据只是
        "存在且非空"，下次运行会把它当成完整产物静默跳过——比白费一次下载更糟。
        临时文件与目标同目录，且用 ``os.replace`` 覆盖，因此文件要么完整存在、
        要么根本不存在，跳过判据才真正可靠。
        """
        part = f"{target}.part"
        try:
            write(part)
            os.replace(part, target)
        finally:
            try:
                os.unlink(part)
            except OSError:
                pass

    @staticmethod
    def _parse_fetched(text: str, fmt: str) -> list[SequenceRecord]:
        """解析 efetch 响应。

        必须复用现成解析器（经临时文件）：手写解析会丢掉 FEATURES 段，
        而 ``raw_block`` 逐字节保真是本项目导出 GenBank 的硬要求。
        """
        temp_path = NcbiClient._write_temp(
            text, GENBANK_FILE_SUFFIX if fmt == "genbank" else FASTA_FILE_SUFFIX)
        try:
            if fmt == "genbank":
                return list(read_genbank(temp_path))
            return list(read_fasta(temp_path))
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    def fetch_genbank(self, accessions: list[str]) -> str:
        """取 GenBank 文本（``gbwithparts``），每批一次 POST，批间检查取消。"""
        chunks = []
        for batch in self._batch(accessions):
            self._check_cancelled()
            chunks.append(self._request("efetch.fcgi", {
                "db": "nuccore", "id": ",".join(batch),
                "rettype": "gbwithparts", "retmode": "text",
            }, method="POST"))
        return "".join(chunks)

    def fetch_fasta(self, accessions: list[str]) -> str:
        """取 FASTA 文本，每批一次 POST，批间检查取消。"""
        chunks = []
        for batch in self._batch(accessions):
            self._check_cancelled()
            chunks.append(self._request("efetch.fcgi", {
                "db": "nuccore", "id": ",".join(batch),
                "rettype": "fasta", "retmode": "text",
            }, method="POST"))
        return "".join(chunks)

    def _fetch_records(self, accessions: list[str],
                       options: DownloadOptions) -> list[SequenceRecord]:
        """取回并解析一批记录。

        **只取一次网络数据**：`want_genbank` 为真时只请求 ``gbwithparts``，GenBank 与
        FASTA 两种产物都由同一条记录派生（内容必然一致，网络流量减半）；只有
        "只要 FASTA"时才请求 ``rettype=fasta``。
        """
        if options.want_genbank:
            records = self._parse_fetched(self.fetch_genbank(accessions), "genbank")
        else:
            records = self._parse_fetched(self.fetch_fasta(accessions), "fasta")
        if not records:
            # 空响应或整批都解析不出记录：当成这一批失败，由调用方降级为逐条重试，
            # 否则整批会"零信号"消失（既不计成功也不计入失败清单）。
            raise NcbiError("efetch 未返回任何可用记录")
        return records

    @staticmethod
    def _match_batch(batch: list[str], records: list[SequenceRecord]
                     ) -> tuple[list[SequenceRecord], list[str]]:
        """把一批响应记录与请求的登录号对账，返回 (收下的记录, NCBI 未返回的登录号)。

        宽松匹配：按 :func:`_accession_key` 比较（忽略版本号、忽略大小写）。

        响应里多出来的记录（分段记录的各部件等）照常收下，绝不静默丢弃；请求了却没
        返回记录的登录号交由调用方计入 ``failures``——NCBI 对无效号、撤稿号直接略过，
        不显式归因的话它既不算成功也不算失败，差额被静默吞掉。
        """
        wanted: dict[str, int] = {}
        for accession in batch:
            key = _accession_key(accession)
            wanted[key] = wanted.get(key, 0) + 1

        matched_records: list[SequenceRecord] = []
        for record in records:
            key = _accession_key(record.accession_base or record.accession)
            if key and wanted.get(key, 0) > 0:
                wanted[key] -= 1
            matched_records.append(record)

        # 记录循环之后 wanted 里的余量就是"请求了却没拿到记录"的登录号个数
        missing: list[str] = []
        for accession in batch:
            key = _accession_key(accession)
            if wanted.get(key, 0) > 0:
                wanted[key] -= 1
                missing.append(accession)
        return matched_records, missing

    def _retry_individually(self, batch: list[str], options: DownloadOptions,
                            failures: list[tuple[str, str]]) -> list[SequenceRecord]:
        """批量失败后逐条重试：只有该条自身也失败才计入 failures。

        一个坏登录号不能让同批其余 199 条一起丢失。取消不是数据错误，必须原样抛出。
        """
        log = self.log
        recovered: list[SequenceRecord] = []
        for accession in batch:
            self._check_cancelled()
            try:
                recovered.extend(self._fetch_records([accession], options))
            except OperationCancelled:
                raise
            except SeqToolkitError as error:
                failures.append((accession, str(error)))
                if log is not None:
                    log.error(f"下载失败: {accession}: {error}")
        return recovered

    def _pending_accessions(self, accessions: list[str],
                            options: DownloadOptions) -> tuple[list[str], int]:
        """返回 (需要下载的登录号, 预先跳过数)。

        只有"命名模式为登录号 + 逐序列单文件"时文件名在下载前就能算出来，可据此提前
        跳过以省网络；其它命名模式的文件名依赖记录内容，必须拿到记录后再判断。
        """
        log = self.log
        predictable = (options.naming_mode == "accession"
                       and options.per_sequence_files
                       and not options.force_redownload)
        if not predictable:
            return list(accessions), 0

        pending: list[str] = []
        skipped = 0
        for accession in accessions:
            stem = sanitize_accession(accession)
            targets = self._per_sequence_targets(options.out_dir, stem, options)
            if all(_exists_nonempty(target) for target in targets):
                skipped += 1
                if log is not None:
                    log.info(f"已存在，跳过下载: {accession}")
                continue
            pending.append(accession)
        return pending, skipped

    @staticmethod
    def _per_sequence_targets(out_dir: str, name: str,
                              options: DownloadOptions) -> list[str]:
        """单条序列会写出的文件路径（按需勾选的格式决定）。"""
        targets = []
        if options.want_genbank:
            targets.append(os.path.join(out_dir, f"{name}{GENBANK_FILE_SUFFIX}"))
        if options.want_fasta:
            targets.append(os.path.join(out_dir, f"{name}{FASTA_FILE_SUFFIX}"))
        return targets

    def _write_per_sequence(self, records: list[SequenceRecord],
                            name_map: dict[SequenceRecord, str],
                            options: DownloadOptions,
                            failures: list[tuple[str, str]]) -> tuple[int, int]:
        """逐条写单序列文件，返回 (因已存在而跳过的名字数, 写出失败的名字数)。

        绝不静默覆盖。单条写出失败（磁盘满、文件名被占用……）只记入 ``failures``
        并继续写其余记录：此时整批**已经下载完了**，中断等于让用户既拿不到其余序列、
        也拿不到合并产物与汇总报告，违反"单条失败不得中断整批"的全局约束。

        每次写出都走 :meth:`_write_atomic`，失败不留半截文件——否则下次运行会把
        半截文件当成完整产物静默跳过。计数按名字去重（同一名字只结算一次）。
        """
        log = self.log
        skipped: set[str] = set()
        failed: set[str] = set()
        for record in records:
            name = name_map.get(record) or sanitize_accession(record.accession)
            if name in failed:
                continue
            targets = self._per_sequence_targets(options.out_dir, name, options)
            if not options.force_redownload and all(
                    _exists_nonempty(target) for target in targets):
                skipped.add(name)
                if log is not None:
                    log.info(f"文件已存在，跳过写入: {name}")
                continue
            # 显式传入 {record: name}，保证文件名与文件内序列名逐字一致：
            # 否则两者各自兜底（登录号 / sequence_N），会算出不同的名字。
            gb_path = os.path.join(options.out_dir, f"{name}{GENBANK_FILE_SUFFIX}")
            fa_path = os.path.join(options.out_dir, f"{name}{FASTA_FILE_SUFFIX}")
            try:
                if options.want_genbank:
                    NcbiClient._write_atomic(
                        gb_path, lambda path, rec=record, nm=name:
                        write_genbank([rec], path, {rec: nm}))
                if options.want_fasta:
                    NcbiClient._write_atomic(
                        fa_path, lambda path, rec=record, nm=name:
                        write_fasta([rec], path, {rec: nm}, wrap=options.wrap))
            except (OSError, SeqToolkitError) as error:
                failed.add(name)
                failures.append((name, str(error)))
                if log is not None:
                    log.error(f"写出失败: {name}: {error}")
        return len(skipped - failed), len(failed)

    def _write_merged(self, records: list[SequenceRecord],
                      name_map: dict[SequenceRecord, str],
                      options: DownloadOptions) -> tuple[str, str]:
        """写合并产物，返回 (fasta 路径, genbank 路径)。

        合并文件绝不覆盖：已存在时用 :func:`resolve_output_path` 递增追加并记 WARN。
        WARN 里带上本次合并的条数：合并产物**只含本次下载的记录**，预跳过 / 写出跳过
        的序列都不在里面；不写清楚，用户重跑时会把 all_sequences_1.fasta 当全集。
        """
        log = self.log
        merged_fasta = ""
        merged_genbank = ""
        if not options.merged_files or not records:
            return merged_fasta, merged_genbank

        if options.want_fasta:
            target = resolve_output_path(
                os.path.join(options.out_dir, MERGED_FASTA_NAME))
            if os.path.basename(target) != MERGED_FASTA_NAME and log is not None:
                log.warn(f"{MERGED_FASTA_NAME} 已存在，改写入 {target}"
                         f"（本次合并仅含本次下载的 {len(records)} 条记录，"
                         f"不含跳过或此前已存在的序列）")
            NcbiClient._write_atomic(
                target, lambda path: write_fasta(records, path, name_map,
                                                 wrap=options.wrap))
            merged_fasta = target

        if options.want_genbank:
            target = resolve_output_path(
                os.path.join(options.out_dir, MERGED_GENBANK_NAME))
            if os.path.basename(target) != MERGED_GENBANK_NAME and log is not None:
                log.warn(f"{MERGED_GENBANK_NAME} 已存在，改写入 {target}"
                         f"（本次合并仅含本次下载的 {len(records)} 条记录，"
                         f"不含跳过或此前已存在的序列）")
            NcbiClient._write_atomic(
                target, lambda path: write_genbank(records, path, name_map))
            merged_genbank = target

        return merged_fasta, merged_genbank

    def download(self, accessions: list[str], options: DownloadOptions,
                 progress: Callable[[int, int, str], None] | None = None
                 ) -> DownloadReport:
        """批量下载并落盘：逐序列单文件 + 合并文件，绝不静默覆盖。

        计数口径见 :class:`DownloadReport`（单位为登录号）；一次批次只发一次 efetch
        请求。
        """
        # 校验必须在建目录、发请求之前：
        # 两个格式都不选会"下载成功却什么都不写"；两个输出目标都不选同样是
        # "全部下载完却一个文件都不落盘"，而报告仍会显示"成功 N 条"；
        # 非法命名模式则要等全部记录下载完才由 build_name_map 抛 ValueError。
        if not options.want_fasta and not options.want_genbank:
            raise SeqToolkitError("至少要选择一种输出格式（FASTA 或 GenBank）")
        if not options.per_sequence_files and not options.merged_files:
            raise SeqToolkitError(
                "未选择任何输出目标：请至少勾选「每序列单文件」或「同时合并为大文件」")
        if options.naming_mode not in NAMING_MODES:
            raise SeqToolkitError(f"未知命名模式: {options.naming_mode}")

        log = self.log
        os.makedirs(options.out_dir, exist_ok=True)
        total = len(accessions)
        failures: list[tuple[str, str]] = []
        collected: list[SequenceRecord] = []

        pending, skipped = self._pending_accessions(accessions, options)
        matched = 0
        done = skipped
        for batch in self._batch(pending):
            self._check_cancelled()
            try:
                batch_records = self._fetch_records(batch, options)
            except OperationCancelled:
                raise
            except SeqToolkitError as error:
                if log is not None:
                    log.warn(f"批量下载失败，改为逐条重试: {error}")
                before = len(failures)
                batch_records = self._retry_individually(batch, options, failures)
                matched += len(batch) - (len(failures) - before)
            else:
                batch_records, missing = self._match_batch(batch, batch_records)
                matched += len(batch) - len(missing)
                for accession in missing:
                    # 显式归因：NCBI 略过的登录号既不算成功也不算失败的话，
                    # 用户看到的"成功 + 跳过 + 失败"就凑不齐总数，差额被静默吞掉。
                    failures.append((accession, MISSING_RECORD_REASON))
                    if log is not None:
                        log.warn(f"{MISSING_RECORD_REASON}: {accession}")
            collected.extend(batch_records)
            done += len(batch)
            if progress is not None:
                progress(done, total, f"已下载 {len(collected)} 条")

        # 命名表必须在收集完**所有**记录之后统一建一次：同物种的流水号是全局的，
        # 每批各建一次会让不同批次的同物种记录各自从 _1 开始，产出重名。
        # 另外必须在任何写入之前建表：SequenceRecord 是 frozen dataclass，其
        # __eq__/__hash__ 覆盖全部 14 个字段，with_warning()/replace() 之后的对象
        # 不再等于这里的键，name_map.get(record) 会静默失配并回退到登录号。
        name_map = build_name_map(collected, options.naming_mode)

        skipped_names = 0
        failed_names = 0
        if options.per_sequence_files:
            skipped_names, failed_names = self._write_per_sequence(
                collected, name_map, options, failures)

        merged_fasta, merged_genbank = self._write_merged(collected, name_map, options)

        # 以登录号为单位结算：每个登录号最终恰好落在 成功 / 跳过 / 失败 之一，
        # 因此 succeeded + skipped + failed == total 恒成立。
        succeeded = matched - skipped_names - failed_names
        skipped += skipped_names
        if log is not None:
            log.info(f"下载完成：成功 {succeeded} 条，跳过 {skipped} 条，"
                     f"失败 {len(failures)} 条（计数单位为登录号）")

        return DownloadReport(
            total=total,
            succeeded=succeeded,
            skipped=skipped,
            failed=len(failures),
            out_dir=options.out_dir,
            failures=failures,
            merged_fasta=merged_fasta,
            merged_genbank=merged_genbank,
        )
