import io
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

from seq_toolkit.applog import RunLog
from seq_toolkit.ncbi import NcbiClient, NcbiError, RateLimiter
from seq_toolkit.pipeline import OperationCancelled


class FakeClock:
    """假时钟 + 配套 sleeper：sleeper 推进时钟，时钟返回假时间（唯一时间源）。"""

    def __init__(self):
        self.now_value = 0.0
        self.slept = []

    def now(self):
        return self.now_value

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now_value += seconds


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


class RecordingOpener:
    """按调用顺序返回预设结果；记录每个 Request 的 URL/方法/参数。"""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome.encode("utf-8"))

    def params_of(self, index):
        request = self.requests[index]
        raw = request.data.decode("utf-8") if request.data else urlparse(request.full_url).query
        return {k: v[0] for k, v in parse_qs(raw).items()}


class TimelineOpener(RecordingOpener):
    """在"客户端已消耗的时间"轴上记录每次真实请求发生的时刻。

    - ``clock`` 与 sleeper 配套（sleeper 推进时钟）时传 ``sleeps=None``：等待已经
      体现在时钟读数里，不能再加一遍。
    - 用默认真实时钟 + 仅记录型 sleeper 时传 ``sleeps=<记录列表>``：把 sleeper 承诺的
      等待量加回时间轴，得到"sleeper 真的等了"时应有的时间。
    """

    def __init__(self, outcomes, clock=None, sleeps=None):
        super().__init__(outcomes)
        self._clock = time.monotonic if clock is None else clock
        self._sleeps = sleeps
        self.consumed = []

    def __call__(self, request):
        consumed = self._clock()
        if self._sleeps is not None:
            consumed += sum(self._sleeps)
        self.consumed.append(consumed)
        return super().__call__(request)


def _adjacent_gaps(opener):
    """相邻两次真实请求之间消耗掉的时间。"""
    return [later - earlier
            for earlier, later in zip(opener.consumed, opener.consumed[1:])]


def _client(opener, **kwargs):
    return NcbiClient(email="me@example.org", opener=opener, sleeper=lambda s: None, **kwargs)


def test_rate_limiter_spaces_calls_without_api_key():
    clock = FakeClock()
    limiter = RateLimiter(2.0, clock=clock.now, sleeper=clock.sleep)
    limiter.acquire()
    limiter.acquire()
    assert clock.slept == [0.5]


def test_rate_limiter_does_not_sleep_when_clock_advanced():
    clock = FakeClock()
    limiter = RateLimiter(10.0, clock=clock.now, sleeper=clock.sleep)
    limiter.acquire()
    clock.now_value += 1.0
    limiter.acquire()
    assert clock.slept == []


def test_rate_limiter_throttles_every_adjacent_request_without_key():
    """无 key（3 次/秒）时相邻请求必须真的等待约 1/3 秒，且一次都不放过。"""
    clock = FakeClock()
    limiter = RateLimiter(3.0, clock=clock.now, sleeper=clock.sleep)
    for _ in range(3):
        limiter.acquire()
    assert clock.slept == [pytest.approx(1 / 3)] * 2


def test_rate_limit_is_three_without_key_and_ten_with_key():
    assert _client(RecordingOpener([])).rate_limit == 3.0
    assert _client(RecordingOpener([]), api_key="K").rate_limit == 10.0


def test_client_throttles_requests_at_the_configured_rate():
    """客户端按 3 次/秒（无 key）与 10 次/秒（有 key）限速。

    用配套假时钟（sleeper 推进时钟、时钟返回假时间）断言，完全确定性：
    不读真实时钟、不真实睡眠、无容差。
    """
    for api_key, rate in ((None, 3.0), ("K", 10.0)):
        clock = FakeClock()
        opener = RecordingOpener(["{}", "{}"])
        client = NcbiClient(email="a@b.c", api_key=api_key, opener=opener,
                            sleeper=clock.sleep, clock=clock.now)
        assert client.rate_limit == rate
        client._request("esearch.fcgi", {})
        client._request("esearch.fcgi", {})
        # 相邻两次请求之间恰好发生一次限速等待，等待量精确等于 1/rate
        assert clock.slept == [1.0 / rate]
        assert clock.now_value == 1.0 / rate


def test_client_decides_throttling_from_the_injected_clock():
    """限速决策只用注入的时钟：它已前进超过 1/rate 时不得再等待（真实时钟不参与）。"""
    clock = FakeClock()
    opener = RecordingOpener(["{}", "{}"])
    client = NcbiClient(email="a@b.c", opener=opener,
                        sleeper=clock.sleep, clock=clock.now)
    clock.now_value = 10.0
    client._request("esearch.fcgi", {})
    clock.now_value += 10.0
    client._request("esearch.fcgi", {})
    assert clock.slept == []
    assert len(opener.requests) == 2


def test_adjacent_requests_hold_the_interval_with_an_injected_clock():
    """注入时钟下：相邻两次真实请求的间隔不得小于 1/rate（含重试退避全程）。"""
    for api_key, rate in ((None, 3.0), ("K", 10.0)):
        clock = FakeClock()
        opener = TimelineOpener(
            [URLError("offline"), URLError("offline"), "{}", "{}"], clock=clock.now)
        client = NcbiClient(email="a@b.c", api_key=api_key, opener=opener,
                            sleeper=clock.sleep, clock=clock.now)
        client._request("esearch.fcgi", {}, retries=3)  # 失败两次（退避 1s、2s）后成功
        client._request("esearch.fcgi", {})
        gaps = _adjacent_gaps(opener)
        assert len(gaps) == 3
        assert all(gap >= 1.0 / rate for gap in gaps)


def test_adjacent_requests_hold_the_interval_with_the_default_clock():
    """未注入时钟（默认真实单调时钟）时同样成立。

    此处 sleeper 是仅记录型（不推进真实时钟），于是把 sleeper 承诺的等待量加回时间轴，
    得到"sleeper 真的等了"时应有的消耗时间——该时间轴上间隔仍不得小于 1/rate。
    """
    sleeps = []
    opener = TimelineOpener([URLError("offline"), "{}", "{}"], sleeps=sleeps)
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=sleeps.append)
    client._request("esearch.fcgi", {}, retries=3)
    client._request("esearch.fcgi", {})
    assert len(opener.consumed) == 3
    gaps = _adjacent_gaps(opener)
    assert all(gap >= 1 / 3 for gap in gaps)


def test_backoff_is_not_double_counted_when_the_sleeper_advances_the_clock():
    """限速器与退避共用注入的同一个 clock：配套假时钟下补偿必须失效。

    sleeper 已经推进了时钟，所以"退避消耗的时间"天然计入限速额度，不能再加一遍
    （否则限速器的时间就是假的）。此断言同时钉住"注入的 clock 真的被使用"。
    """
    clock = FakeClock()
    client = NcbiClient(email="a@b.c", opener=RecordingOpener([]),
                        sleeper=clock.sleep, clock=clock.now)
    client._wait(1.0)
    assert clock.slept == [1.0]
    assert clock.now_value == 1.0
    assert client._clock() == clock.now_value  # 单一时钟：补偿为 0，不是 2.0


def test_sub_second_backoff_is_clamped_to_the_rate_interval():
    """亚秒退避必须被夹紧到 1/rate。

    补偿逻辑的正确性隐含"退避值 ≥ 1/rate"这一前提：3 次/秒下退避 0.2 秒时，若真的只等
    0.2 秒，相邻请求间隔就会小于 1/rate，硬约束被无声破坏。（当前退避值都是 1 秒以上，
    但 T16/T17 会继续改这个文件，故用守卫钉住前提。）
    """
    clock = FakeClock()
    client = NcbiClient(email="a@b.c", opener=RecordingOpener([]),
                        sleeper=clock.sleep, clock=clock.now)
    assert client.rate_limit == 3.0
    client._wait(0.2)
    assert clock.slept == [1 / 3]
    assert clock.now_value == 1 / 3


def test_adjacent_requests_stay_apart_after_a_sub_second_backoff():
    """走真实 429 路径的亚秒退避（Retry-After: 0）之后，相邻请求间隔仍 ≥ 1/rate。"""
    for api_key, rate in ((None, 3.0), ("K", 10.0)):
        clock = FakeClock()
        opener = TimelineOpener(
            [HTTPError("u", 429, "slow down", {"Retry-After": "0"}, None), "{}"],
            clock=clock.now)
        client = NcbiClient(email="a@b.c", api_key=api_key, opener=opener,
                            sleeper=clock.sleep, clock=clock.now)
        assert client._request("esearch.fcgi", {}) == "{}"
        assert clock.slept == [1.0 / rate]  # 0 秒退避被夹紧到 1/rate
        gaps = _adjacent_gaps(opener)
        assert len(gaps) == 1
        assert gaps[0] >= 1.0 / rate


def test_request_sends_tool_email_and_api_key():
    opener = RecordingOpener(["{}"])
    client = _client(opener, api_key="SECRET")
    client._request("esearch.fcgi", {"db": "nuccore"})
    params = opener.params_of(0)
    assert params["tool"] == "seq_toolkit"
    assert params["email"] == "me@example.org"
    assert params["api_key"] == "SECRET"
    assert params["db"] == "nuccore"


def test_request_omits_optional_params_when_empty():
    opener = RecordingOpener(["{}"])
    client = NcbiClient(email="", opener=opener, sleeper=lambda s: None)
    client._request("esearch.fcgi", {})
    params = opener.params_of(0)
    assert params["tool"] == "seq_toolkit"
    assert "email" not in params
    assert "api_key" not in params


def test_request_retries_on_server_error_then_succeeds():
    delays = []
    opener = RecordingOpener([
        HTTPError("u", 500, "boom", {}, None),
        HTTPError("u", 500, "boom", {}, None),
        "OK",
    ])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=delays.append)
    assert client._request("esummary.fcgi", {}) == "OK"
    assert delays == [1, 2]


def test_request_retries_on_network_error():
    opener = RecordingOpener([URLError("offline"), "OK"])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=lambda s: None)
    assert client._request("efetch.fcgi", {}) == "OK"


def test_request_honours_retry_after_on_429():
    delays = []
    error = HTTPError("u", 429, "slow down", {"Retry-After": "7"}, None)
    opener = RecordingOpener([error, "OK"])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=delays.append)
    assert client._request("esearch.fcgi", {}) == "OK"
    assert delays == [7.0]


def test_request_falls_back_to_five_seconds_without_retry_after():
    delays = []
    opener = RecordingOpener([HTTPError("u", 429, "slow", {}, None), "OK"])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=delays.append)
    assert client._request("esearch.fcgi", {}) == "OK"
    assert delays == [5.0]


def test_request_survives_non_decimal_retry_after():
    """Retry-After 可能是非十进制字符串（isdigit() 为真但 float() 会抛错）。"""
    delays = []
    opener = RecordingOpener([HTTPError("u", 429, "slow", {"Retry-After": "²"}, None), "OK"])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=delays.append)
    assert client._request("esearch.fcgi", {}) == "OK"
    assert delays == [5.0]


def test_request_gives_up_after_retries_and_raises_ncbi_error():
    opener = RecordingOpener([URLError("x"), URLError("x"), URLError("x")])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=lambda s: None)
    with pytest.raises(NcbiError):
        client._request("esearch.fcgi", {}, retries=3)


def test_request_raises_immediately_on_client_error():
    opener = RecordingOpener([HTTPError("u", 400, "bad request", {}, None)])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=lambda s: None)
    with pytest.raises(NcbiError):
        client._request("esearch.fcgi", {})
    assert len(opener.requests) == 1


def test_request_raises_immediately_on_404():
    opener = RecordingOpener([HTTPError("u", 404, "not found", {}, None)])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=lambda s: None)
    with pytest.raises(NcbiError):
        client._request("esearch.fcgi", {})
    assert len(opener.requests) == 1


def test_post_uses_request_body():
    opener = RecordingOpener(["{}"])
    client = _client(opener)
    client._request("efetch.fcgi", {"db": "nuccore", "id": "1,2,3"}, method="POST")
    request = opener.requests[0]
    assert request.get_method() == "POST"
    assert b"id=1%2C2%2C3" in request.data


def test_request_honours_cancel_before_first_attempt():
    opener = RecordingOpener(["OK"])
    cancel = threading.Event()
    cancel.set()
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=lambda s: None, cancel=cancel)
    with pytest.raises(OperationCancelled):
        client._request("esearch.fcgi", {})
    assert opener.requests == []


def test_request_honours_cancel_set_after_the_first_failed_attempt():
    """cancel 必须在**每次**尝试前检查，而不只是第一次尝试前。

    第一次请求失败后再置位 cancel（在退避的 sleeper 回调里 set）：第二次尝试不得发出，
    直接抛 OperationCancelled。把 _check_cancelled() 挪到循环外会被这条用例抓住。
    """
    cancel = threading.Event()
    opener = RecordingOpener([URLError("offline"), "OK"])

    def sleeper(seconds):
        cancel.set()

    client = NcbiClient(email="a@b.c", opener=opener, sleeper=sleeper, cancel=cancel)
    with pytest.raises(OperationCancelled):
        client._request("esearch.fcgi", {})
    assert len(opener.requests) == 1


def test_errors_are_logged_when_a_log_is_injected():
    log = RunLog()
    opener = RecordingOpener([HTTPError("u", 429, "slow", {"Retry-After": "1"}, None), "OK"])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=lambda s: None, log=log)
    assert client._request("esearch.fcgi", {}) == "OK"
    assert any("429" in entry.message for entry in log.entries)


import json

from seq_toolkit.ncbi import (
    COMPLETE_GENOME_PATTERNS,
    SeqSummary,
    SearchResult,
    build_query,
    matches_complete_genome,
)


def test_build_query_for_species_quotes_the_term():
    assert build_query("Salsola pellucida") == '"Salsola pellucida"[Organism]'


def test_build_query_for_genus_does_not_quote():
    assert build_query("Salsola", scope="genus") == "Salsola[Organism]"


def test_build_query_adds_length_filter():
    assert build_query("Salsola", scope="genus", min_length=100000,
                       max_length=200000) == "Salsola[Organism] AND 100000:200000[SLEN]"


def test_build_query_adds_refseq_filter():
    assert build_query("Salsola", scope="genus", refseq_only=True) == (
        "Salsola[Organism] AND srcdb_refseq[prop]")


def test_build_query_rejects_empty_term():
    with pytest.raises(ValueError):
        build_query("   ")


def test_build_query_rejects_unknown_scope():
    with pytest.raises(ValueError):
        build_query("Salsola", scope="kingdom")


def test_complete_genome_patterns_are_the_documented_six():
    assert COMPLETE_GENOME_PATTERNS == (
        "complete genome",
        "complete chloroplast genome",
        "complete plastid genome",
        "complete mitochondrial genome",
        "complete plastome",
        "complete mitochondrial dna",
    )


def test_matches_complete_genome_is_case_insensitive():
    assert matches_complete_genome("Salsola pellucida chloroplast, COMPLETE GENOME") is True
    assert matches_complete_genome("Salsola pellucida chloroplast, partial sequence") is False
    assert matches_complete_genome("Salsola pellucida complete chloroplast genome") is True


def _esearch_payload(count, ids, webenv="WE", query_key="1"):
    return json.dumps({"esearchresult": {"count": str(count), "idlist": ids,
                                         "webenv": webenv, "querykey": query_key}})


def test_search_parses_esearch_response():
    opener = RecordingOpener([_esearch_payload(2, ["111", "222"])])
    client = _client(opener)
    result = client.search("Salsola pellucida")
    assert isinstance(result, SearchResult)
    assert result.total == 2
    assert result.ids == ["111", "222"]
    assert result.webenv == "WE"
    assert result.query_key == "1"
    assert result.query == '"Salsola pellucida"[Organism]'


def test_search_uses_history_for_large_result_sets():
    opener = RecordingOpener([_esearch_payload(99999, ["1"])])
    _client(opener).search("Salsola", scope="genus")
    params = opener.params_of(0)
    assert params["usehistory"] == "y"
    assert params["db"] == "nuccore"
    assert params["retmode"] == "json"


def _esummary_payload(mapping):
    return json.dumps({"result": mapping})


def _doc(accession, length, organism, title, date="2022/01/12", srcdb="GenBank"):
    return {"accessionversion": accession, "slen": str(length), "organism": organism,
            "title": title, "createdate": date, "sourcedb": srcdb}


def test_summarize_parses_documents():
    payload = _esummary_payload({
        "uids": ["111"],
        "111": _doc("ON929859.1", 152398, "Salsola pellucida",
                    "Salsola pellucida chloroplast, complete genome"),
    })
    opener = RecordingOpener([payload])
    summaries = _client(opener).summarize(["111"])
    assert len(summaries) == 1
    summary = summaries[0]
    assert isinstance(summary, SeqSummary)
    assert summary.accession == "ON929859.1"
    assert summary.length == 152398
    assert summary.organism == "Salsola pellucida"
    assert summary.source_db == "GenBank"


def test_summarize_splits_into_batches_of_500():
    ids = [str(i) for i in range(1200)]
    payloads = [_esummary_payload({"uids": []}) for _ in range(3)]
    opener = RecordingOpener(payloads)
    _client(opener).summarize(ids)
    assert len(opener.requests) == 3
    assert len(opener.params_of(0)["id"].split(",")) == 500
    assert len(opener.params_of(2)["id"].split(",")) == 200


def test_search_summaries_applies_local_complete_genome_filter():
    search_payload = _esearch_payload(2, ["1", "2"])
    summary_payload = _esummary_payload({
        "uids": ["1", "2"],
        "1": _doc("A.1", 150000, "Salsola pellucida",
                  "Salsola pellucida chloroplast, complete genome"),
        "2": _doc("B.1", 800, "Salsola pellucida",
                  "Salsola pellucida matK gene, partial cds"),
    })
    opener = RecordingOpener([search_payload, summary_payload])
    result, summaries = _client(opener).search_summaries(
        "Salsola pellucida", complete_genome_only=True)
    assert result.total == 2
    assert [s.accession for s in summaries] == ["A.1"]


def test_search_summaries_applies_local_length_filter():
    search_payload = _esearch_payload(2, ["1", "2"])
    summary_payload = _esummary_payload({
        "uids": ["1", "2"],
        "1": _doc("A.1", 150000, "Salsola pellucida", "complete genome"),
        "2": _doc("B.1", 800, "Salsola pellucida", "complete genome"),
    })
    opener = RecordingOpener([search_payload, summary_payload])
    _result, summaries = _client(opener).search_summaries(
        "Salsola pellucida", min_length=100000)
    assert [s.accession for s in summaries] == ["A.1"]


def test_search_summaries_applies_local_refseq_filter():
    search_payload = _esearch_payload(2, ["1", "2"])
    summary_payload = _esummary_payload({
        "uids": ["1", "2"],
        "1": _doc("NC_1.1", 150000, "Salsola pellucida", "complete genome",
                  srcdb="RefSeq"),
        "2": _doc("MF1.1", 150000, "Salsola pellucida", "complete genome",
                  srcdb="GenBank"),
    })
    opener = RecordingOpener([search_payload, summary_payload])
    _result, summaries = _client(opener).search_summaries(
        "Salsola pellucida", refseq_only_local=True)
    assert [s.accession for s in summaries] == ["NC_1.1"]


# ---------------------------------------------------------------------------
# Task 17：序列获取（efetch）与批量下载编排
# ---------------------------------------------------------------------------

from seq_toolkit.ncbi import DownloadOptions, DownloadReport

GENBANK_TWO = (
    "LOCUS       ON1.1                   8 bp    DNA     linear   PLN 01-JAN-2020\n"
    "DEFINITION  Salsola pellucida chloroplast, complete genome.\n"
    "ACCESSION   ON1\n"
    "VERSION     ON1.1\n"
    "  ORGANISM  Salsola pellucida\n"
    "            Eukaryota; Amaranthaceae; Salsola.\n"
    "FEATURES             Location/Qualifiers\n"
    "     CDS             1..8\n"
    '                     /gene="matK"\n'
    "ORIGIN\n"
    "        1 acgtacgt\n"
    "//\n"
)

FASTA_TWO = ">MF2.1 Kochia scoparia chloroplast, complete genome\nTTTTGGGG\n"

GENBANK_MF2 = (
    "LOCUS       MF2.1                   8 bp    DNA     linear   PLN 01-JAN-2020\n"
    "DEFINITION  Kochia scoparia chloroplast, complete genome.\n"
    "ACCESSION   MF2\n"
    "VERSION     MF2.1\n"
    "  ORGANISM  Kochia scoparia\n"
    "            Eukaryota; Amaranthaceae; Kochia.\n"
    "ORIGIN\n"
    "        1 ttttgggg\n"
    "//\n"
)

# 一个批次只发一次 efetch 请求，响应里含该批全部序列。
# 因此模拟"多序列下载"必须让**一次响应包含多条记录**，
# 而不是给 fake opener 准备多条响应——那会与实际请求次数不符。
GENBANK_TWO_RECORDS = GENBANK_TWO + GENBANK_MF2


def test_fetch_genbank_batches_by_two_hundred():
    opener = RecordingOpener([GENBANK_TWO, GENBANK_TWO])
    client = _client(opener)
    client.fetch_genbank([str(i) for i in range(250)])
    assert len(opener.requests) == 2
    assert opener.params_of(0)["rettype"] == "gbwithparts"
    assert opener.requests[0].get_method() == "POST"


def test_fetch_fasta_uses_fasta_rettype():
    opener = RecordingOpener([FASTA_TWO])
    _client(opener).fetch_fasta(["MF2.1"])
    assert opener.params_of(0)["rettype"] == "fasta"


def test_download_writes_per_sequence_files_and_merged_files(tmp_path):
    # 2 个登录号落在同一个批次（每批上限 200），因此只发生 1 次请求
    opener = RecordingOpener([GENBANK_TWO_RECORDS])
    client = _client(opener)
    options = DownloadOptions(out_dir=str(tmp_path), naming_mode="accession")
    report = client.download(["ON1.1", "MF2.1"], options)
    assert isinstance(report, DownloadReport)
    assert len(opener.requests) == 1
    assert report.succeeded == 2
    assert (tmp_path / "ON1.1.gb").exists()
    assert (tmp_path / "ON1.1.fasta").exists()
    assert (tmp_path / "MF2.1.gb").exists()
    assert (tmp_path / "MF2.1.fasta").exists()
    assert (tmp_path / "all_sequences.fasta").exists()
    assert (tmp_path / "all_sequences.gb").exists()


def test_downloaded_genbank_keeps_features(tmp_path):
    opener = RecordingOpener([GENBANK_TWO])
    client = _client(opener)
    client.download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path)))
    assert '/gene="matK"' in (tmp_path / "ON1.1.gb").read_text(encoding="utf-8")


def test_download_applies_naming_mode(tmp_path):
    opener = RecordingOpener([GENBANK_TWO])
    client = _client(opener)
    client.download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path),
                                               naming_mode="accession_species"))
    assert (tmp_path / "ON1.1_Salsola_pellucida.gb").exists()
    merged = (tmp_path / "all_sequences.fasta").read_text(encoding="utf-8")
    assert merged.startswith(">ON1.1_Salsola_pellucida\n")


def test_download_skips_existing_files_without_force(tmp_path):
    (tmp_path / "ON1.1.gb").write_text("已存在", encoding="utf-8")
    (tmp_path / "ON1.1.fasta").write_text("已存在", encoding="utf-8")
    opener = RecordingOpener([])
    client = _client(opener)
    report = client.download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path)))
    assert report.skipped == 1
    assert opener.requests == []
    assert (tmp_path / "ON1.1.gb").read_text(encoding="utf-8") == "已存在"


def test_download_force_redownload_overwrites(tmp_path):
    (tmp_path / "ON1.1.gb").write_text("旧内容", encoding="utf-8")
    (tmp_path / "ON1.1.fasta").write_text("旧内容", encoding="utf-8")
    opener = RecordingOpener([GENBANK_TWO])
    client = _client(opener)
    report = client.download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path),
                                                        force_redownload=True))
    assert report.succeeded == 1
    assert '/gene="matK"' in (tmp_path / "ON1.1.gb").read_text(encoding="utf-8")


def test_download_falls_back_to_per_accession_when_batch_fails(tmp_path):
    opener = RecordingOpener([
        URLError("batch failed"),
        URLError("batch failed"),
        URLError("batch failed"),
        GENBANK_TWO,          # 单条重试成功
        URLError("bad accession"),
        URLError("bad accession"),
        URLError("bad accession"),
    ])
    client = _client(opener)
    report = client.download(["ON1.1", "BAD.9"], DownloadOptions(out_dir=str(tmp_path)))
    assert report.succeeded == 1
    assert report.failed == 1
    assert report.failures[0][0] == "BAD.9"


def test_download_reports_progress(tmp_path):
    opener = RecordingOpener([GENBANK_TWO, FASTA_TWO])
    client = _client(opener)
    seen = []
    client.download(["ON1.1", "MF2.1"], DownloadOptions(out_dir=str(tmp_path)),
                    progress=lambda done, total, message: seen.append((done, total)))
    assert seen[-1] == (2, 2)


def test_download_only_fasta_requests_fasta_endpoint(tmp_path):
    opener = RecordingOpener([FASTA_TWO])
    client = _client(opener)
    client.download(["MF2.1"], DownloadOptions(out_dir=str(tmp_path),
                                               want_genbank=False))
    assert opener.params_of(0)["rettype"] == "fasta"
    assert (tmp_path / "MF2.1.fasta").exists()
    assert not (tmp_path / "MF2.1.gb").exists()


# --- 补充用例：简报用例未覆盖的计数口径与"绝不静默覆盖" ---


def test_download_gets_genbank_once_and_both_formats_agree(tmp_path):
    """约束 A：两种格式都想要时只请求 gbwithparts 一次，.gb 与 .fasta 同源于一条记录。"""
    opener = RecordingOpener([GENBANK_TWO_RECORDS])
    client = _client(opener)
    report = client.download(["ON1.1", "MF2.1"], DownloadOptions(out_dir=str(tmp_path)))
    assert len(opener.requests) == 1
    assert opener.params_of(0)["rettype"] == "gbwithparts"
    # .fasta 的序列与 .gb 的 ORIGIN 段一致（同一记录派生，不是第二次请求）
    assert (tmp_path / "ON1.1.fasta").read_text(
        encoding="utf-8") == ">ON1.1\nACGTACGT\n"
    assert "acgtacgt" in (tmp_path / "ON1.1.gb").read_text(encoding="utf-8")


def test_download_counts_are_self_consistent(tmp_path):
    """succeeded + skipped + failed == total（混合：1 条预跳过 + 2 条下载）。"""
    (tmp_path / "MF2.1.gb").write_text("已存在", encoding="utf-8")
    (tmp_path / "MF2.1.fasta").write_text("已存在", encoding="utf-8")
    opener = RecordingOpener([GENBANK_TWO])
    client = _client(opener)
    report = client.download(["ON1.1", "MF2.1"], DownloadOptions(out_dir=str(tmp_path)))
    assert (report.total, report.succeeded, report.skipped, report.failed) == (2, 1, 1, 0)
    assert report.succeeded + report.skipped + report.failed == report.total

    # 上面这条只是"预跳过"这种恒成立的路径。真正会漏数的反例（响应少返回登录号）
    # 见 test_download_attributes_missing_accession_to_failures；
    # 这里再补一次"预跳过 + 响应里同样没有该登录号"的组合：被预跳过的登录号根本没进
    # 批次，不能因为响应里没有它就被误记成失败。
    second = tmp_path / "second"
    second.mkdir()
    (second / "MF2.1.gb").write_text("已存在", encoding="utf-8")
    (second / "MF2.1.fasta").write_text("已存在", encoding="utf-8")
    report2 = _client(RecordingOpener([GENBANK_TWO])).download(
        ["ON1.1", "MF2.1"], DownloadOptions(out_dir=str(second)))
    assert (report2.total, report2.succeeded,
            report2.skipped, report2.failed) == (2, 1, 1, 0)
    assert report2.succeeded + report2.skipped + report2.failed == report2.total
    assert report2.failures == []


def test_download_skips_existing_unpredictable_names_after_fetch(tmp_path):
    """命名模式非登录号时文件名下载前不可预知：仍要请求，但绝不覆盖已有产物。"""
    (tmp_path / "ON1.1_Salsola_pellucida.gb").write_text("已存在", encoding="utf-8")
    (tmp_path / "ON1.1_Salsola_pellucida.fasta").write_text("已存在", encoding="utf-8")
    log = RunLog()
    opener = RecordingOpener([GENBANK_TWO])
    client = _client(opener, log=log)
    report = client.download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path),
                                                        naming_mode="accession_species"))
    assert len(opener.requests) == 1          # 名字算不出来，只能先下载
    assert (report.succeeded, report.skipped, report.failed) == (0, 1, 0)
    assert report.succeeded + report.skipped + report.failed == report.total
    assert (tmp_path / "ON1.1_Salsola_pellucida.gb").read_text(
        encoding="utf-8") == "已存在"
    assert any(entry.level == "INFO" and "跳过" in entry.message
               for entry in log.entries)


def test_download_never_overwrites_existing_merged_files(tmp_path):
    """约束 C：合并文件已存在时递增追加（_1）并记 WARN，不改动原文件。"""
    (tmp_path / "all_sequences.fasta").write_text("旧内容", encoding="utf-8")
    (tmp_path / "all_sequences.gb").write_text("旧内容", encoding="utf-8")
    log = RunLog()
    opener = RecordingOpener([GENBANK_TWO])
    client = _client(opener, log=log)
    report = client.download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path)))
    assert (tmp_path / "all_sequences.fasta").read_text(encoding="utf-8") == "旧内容"
    assert (tmp_path / "all_sequences.gb").read_text(encoding="utf-8") == "旧内容"
    assert report.merged_fasta == str(tmp_path / "all_sequences_1.fasta")
    assert report.merged_genbank == str(tmp_path / "all_sequences_1.gb")
    assert (tmp_path / "all_sequences_1.fasta").read_text(
        encoding="utf-8").startswith(">ON1.1\n")
    warnings = [entry.message for entry in log.entries if entry.level == "WARN"]
    assert any("all_sequences.fasta" in message for message in warnings)
    assert any("all_sequences.gb" in message for message in warnings)
    # 合并产物只含本次下载的记录，WARN 必须把条数说清楚
    assert any("本次合并仅含本次下载的 1 条记录" in message for message in warnings)


# ---------------------------------------------------------------------------
# 修复轮补充：计数归因、单条写出失败不中断、原子写出、入口校验与取消传播
# ---------------------------------------------------------------------------

import glob
import os
import tempfile

from seq_toolkit.fasta_io import write_fasta as _real_write_fasta
from seq_toolkit.model import SeqToolkitError


def test_download_attributes_missing_accession_to_failures(tmp_path):
    """反例：请求 2 个登录号、响应只含 1 条记录 —— 差额必须记入 failed。

    NCBI 对无效号、撤稿号会直接略过该 id 且不报错。若只在成功时按记录条数累加，
    这个登录号既不算成功也不算失败，用户看到"成功 1 / 跳过 0 / 失败 0"却请求了 2 个，
    差额被静默吞掉。
    """
    log = RunLog()
    opener = RecordingOpener([GENBANK_TWO])          # 只返回 ON1，MF2 被 NCBI 略过
    client = _client(opener, log=log)
    report = client.download(["ON1.1", "MF2.1"], DownloadOptions(out_dir=str(tmp_path)))
    assert len(opener.requests) == 1
    assert report.failed == 1
    assert report.failures[0][0] == "MF2.1"          # 归因到缺失的那个登录号
    assert (report.total, report.succeeded, report.skipped, report.failed) == (2, 1, 0, 1)
    assert report.succeeded + report.skipped + report.failed == report.total
    assert (tmp_path / "ON1.1.gb").exists()
    assert not (tmp_path / "MF2.1.gb").exists()
    assert any(entry.level == "WARN" and "MF2.1" in entry.message
               for entry in log.entries)


def test_download_matches_accessions_ignoring_version_suffix(tmp_path):
    """宽松匹配：请求 ON1、响应 ON1.1 算命中，不能把好记录记成"未返回"。"""
    opener = RecordingOpener([GENBANK_TWO])
    report = _client(opener).download(["ON1"], DownloadOptions(out_dir=str(tmp_path)))
    assert (report.succeeded, report.failed) == (1, 0)
    assert report.failures == []


def test_download_continues_and_keeps_merged_output_when_one_write_fails(
        tmp_path, monkeypatch):
    """单条写出抛 OSError 不得中断整批：其余照写、该条进 failures、合并产物照生成。"""
    def flaky_write_fasta(records, out_path, name_map=None, wrap=0):
        records = list(records)
        if [record.accession for record in records] == ["ON1.1"]:
            # 先写半截内容再报错，模拟磁盘写满：原子写出必须把半截文件清掉
            with open(out_path, "wt", encoding="utf-8", newline="\n") as handle:
                handle.write(">ON1.1\nAC")
            raise OSError("磁盘已满")
        return _real_write_fasta(records, out_path, name_map, wrap=wrap)

    monkeypatch.setattr("seq_toolkit.ncbi.write_fasta", flaky_write_fasta)
    log = RunLog()
    opener = RecordingOpener([GENBANK_TWO_RECORDS])
    report = _client(opener, log=log).download(
        ["ON1.1", "MF2.1"], DownloadOptions(out_dir=str(tmp_path)))

    # 其余记录照常写出（.gb 在前、.fasta 失败，ON1.1 的 .gb 是完整产物）
    assert (tmp_path / "MF2.1.gb").exists()
    assert (tmp_path / "MF2.1.fasta").exists()
    assert '/gene="matK"' in (tmp_path / "ON1.1.gb").read_text(encoding="utf-8")
    # 该条进 failures，并记 ERROR
    assert report.failed == 1
    assert report.failures[0][0] == "ON1.1"
    assert any(entry.level == "ERROR" and "ON1.1" in entry.message
               for entry in log.entries)
    # 合并产物与汇总报告照常产出（不会因为单条失败而全部拿不到）
    assert report.merged_fasta == str(tmp_path / "all_sequences.fasta")
    assert report.merged_genbank == str(tmp_path / "all_sequences.gb")
    assert (tmp_path / "all_sequences.fasta").exists()
    assert (tmp_path / "all_sequences.gb").exists()
    # 计数等式仍成立
    assert (report.total, report.succeeded, report.skipped, report.failed) == (2, 1, 0, 1)
    assert report.succeeded + report.skipped + report.failed == report.total
    # 失败路径不留半截文件，也不留 .part 残迹
    assert not (tmp_path / "ON1.1.fasta").exists()
    assert list(tmp_path.glob("*.part")) == []


def test_download_requires_at_least_one_output_target(tmp_path):
    """两个输出目标都不选 = 全部下载完却什么都不写：必须在校验阶段拒绝，且不发请求。"""
    out_dir = tmp_path / "out"
    opener = RecordingOpener([])
    client = _client(opener)
    with pytest.raises(SeqToolkitError):
        client.download(["ON1.1"], DownloadOptions(
            out_dir=str(out_dir), per_sequence_files=False, merged_files=False))
    assert opener.requests == []
    assert not out_dir.exists()          # 连目录都不该建：失败发生在发请求之前


def test_download_requires_at_least_one_format(tmp_path):
    """两个格式都不选同样会"下载成功却什么都不写"：入口校验抛 SeqToolkitError。"""
    opener = RecordingOpener([])
    client = _client(opener)
    with pytest.raises(SeqToolkitError):
        client.download(["ON1.1"], DownloadOptions(
            out_dir=str(tmp_path), want_fasta=False, want_genbank=False))
    assert opener.requests == []


def test_download_rejects_unknown_naming_mode(tmp_path):
    """非法命名模式必须是 SeqToolkitError（ValueError 不在 GUI 的捕获集内）。"""
    opener = RecordingOpener([])
    client = _client(opener)
    with pytest.raises(SeqToolkitError):
        client.download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path),
                                                   naming_mode="no-such-mode"))
    assert opener.requests == []


def test_download_propagates_cancellation_instead_of_recording_failure(tmp_path):
    """取消必须原样抛出：不能被吞成"逐条重试"并混进 failures。"""
    cancel = threading.Event()
    calls = []

    def opener(request):
        calls.append(request)
        if len(calls) >= 3:          # 批量三次重试失败后、逐条重试开始前用户点了取消
            cancel.set()
        raise URLError("batch failed")

    log = RunLog()
    client = NcbiClient(email="me@example.org", opener=opener,
                        sleeper=lambda seconds: None, cancel=cancel, log=log)
    with pytest.raises(OperationCancelled):
        client.download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path)))
    assert len(calls) == 3                       # 取消后不再逐条重发
    assert not any(entry.level == "ERROR" for entry in log.entries)
    assert not any("ON1.1" in entry.message
                   for entry in log.entries if entry.level == "ERROR")
    assert not (tmp_path / "ON1.1.gb").exists()


def test_write_temp_removes_partial_file_when_write_fails():
    """临时文件写入失败（磁盘满、编码错）必须顺手清理，不留零字节残迹。"""
    pattern = os.path.join(tempfile.gettempdir(), "*.fa")
    before = set(glob.glob(pattern))
    with pytest.raises(TypeError):
        NcbiClient._write_temp(object(), ".fa")
    assert set(glob.glob(pattern)) - before == set()


# ---------------------------------------------------------------------------
# Task 24：登录号输入解析（按登录号下载标签页用）
# ---------------------------------------------------------------------------

from seq_toolkit.ncbi import collect_accessions_from_files, parse_accession_text


def test_parse_accession_text_splits_on_whitespace_and_punctuation():
    assert parse_accession_text("ON1.1, MF2.1\nKX3.1;AB4.1") == [
        "ON1.1", "MF2.1", "KX3.1", "AB4.1"]


def test_parse_accession_text_uppercases_and_deduplicates():
    assert parse_accession_text("on1.1 ON1.1  on1.1") == ["ON1.1"]


def test_parse_accession_text_ignores_blank_input():
    assert parse_accession_text("   \n  ,, ") == []


def test_collect_accessions_from_files_reads_fasta_and_genbank(tmp_path):
    fasta = tmp_path / "a.fa"
    fasta.write_text(">ON1.1 Salsola pellucida\nACGT\n>MF2.1 Kochia scoparia\nTTTT\n",
                     encoding="utf-8")
    genbank = tmp_path / "b.gb"
    genbank.write_text(GENBANK_TWO, encoding="utf-8")
    found = collect_accessions_from_files([str(fasta), str(genbank)])
    assert found == ["ON1.1", "MF2.1"]


def test_collect_accessions_from_files_deduplicates(tmp_path):
    fasta = tmp_path / "a.fa"
    fasta.write_text(">ON1.1 Salsola pellucida\nACGT\n", encoding="utf-8")
    twice = collect_accessions_from_files([str(fasta), str(fasta)])
    assert twice == ["ON1.1"]


def test_collect_accessions_from_files_walks_folders(tmp_path):
    """给文件夹时要展开（默认递归），且保持自然排序下的出现顺序。"""
    nested = tmp_path / "子目录"
    nested.mkdir()
    (tmp_path / "b.gb").write_text(GENBANK_MF2, encoding="utf-8")
    (nested / "a.fa").write_text(">ON1.1 Salsola pellucida\nACGT\n", encoding="utf-8")
    assert collect_accessions_from_files([str(tmp_path)]) == ["MF2.1", "ON1.1"]


def test_collect_accessions_from_files_skips_unreadable_files(tmp_path):
    """坏文件不得中断整次提取：能读到几条就返回几条。"""
    broken = tmp_path / "broken.gb"
    broken.write_bytes(b"\x00\x01\x02\x03")
    good = tmp_path / "good.fa"
    good.write_text(">ON1.1 Salsola pellucida\nACGT\n", encoding="utf-8")
    assert collect_accessions_from_files([str(broken), str(good)]) == ["ON1.1"]


def test_collect_accessions_from_files_honours_custom_suffixes(tmp_path):
    """后缀名要能自定义：否则用户在「设置」里加的 .custom 会被静默忽略。"""
    custom = tmp_path / "sample.custom"
    custom.write_text(">ON1.1 Salsola pellucida\nACGT\n", encoding="utf-8")
    assert collect_accessions_from_files([str(tmp_path)]) == []
    assert collect_accessions_from_files([str(tmp_path)],
                                         fasta_suffixes=(".custom",),
                                         genbank_suffixes=()) == ["ON1.1"]


def test_collect_accessions_from_files_survives_truncated_gzip(tmp_path):
    """截断的 .gz 必须只丢这一个文件，并留下一条 WARN。

    截断的 gzip 抛的是 ``EOFError``、deflate 数据体损坏抛的是 ``zlib.error``，两者都
    不是 ``OSError`` 的子类。捕获集只写 ``SeqToolkitError`` 时它们会一路逃出去：本函数的
    GUI 调用点（tab_accession 的「从序列文件提取…」）在主线程直调、外层没有 try，
    于是异常穿过 Tk 回调——界面零反应，没有日志、没有对话框、按钮像没电一样。
    捕获集必须与 pipeline.run_merge 的 (OSError, EOFError, zlib.error) 一致。
    """
    import gzip

    from seq_toolkit.applog import WARN

    log = RunLog()
    truncated = tmp_path / "trunc.fa.gz"
    with gzip.open(truncated, "wt", encoding="utf-8") as handle:
        handle.write(">ON1.1 Salsola pellucida\n" + "ACGT" * 500 + "\n")
    raw = truncated.read_bytes()
    # 砍掉后半段：gzip 尾部校验与 end-of-stream 标记都没了，读到末尾必抛 EOFError。
    truncated.write_bytes(raw[: len(raw) // 2])

    good = tmp_path / "good.fa"
    good.write_text(">MF2.1 Kochia scoparia\nACGT\n", encoding="utf-8")

    # 不得抛异常，且其余文件的登录号照样拿到（单条失败不中断整批）。
    found = collect_accessions_from_files([str(truncated), str(good)], log=log)
    assert found == ["MF2.1"]

    warnings = [entry.message for entry in log.entries if entry.level == WARN]
    assert warnings, "被跳过的坏文件必须留下日志，不能静默丢弃"
    assert any("trunc.fa.gz" in message for message in warnings)


# ---------------------------------------------------------------------------
# 用户使用后提出的改进 1：写出的 FASTA 产物统一用 .fasta 后缀
#
# 旧行为写出 `ON1.1.fa`，用户拿到手的下载产物后缀是 .fa。输出侧统一成 .fasta，
# **读取侧不动**：DEFAULT_FASTA_SUFFIXES 继续接受 .fa/.fna 等（用户手上的老文件
# 就是这些后缀），这是"输出统一"而不是"只认一种后缀"。
# ---------------------------------------------------------------------------


def test_download_writes_per_sequence_fasta_with_fasta_suffix(tmp_path):
    """下载产物必须在磁盘上是 ON1.1.fasta，而不是 ON1.1.fa。"""
    opener = RecordingOpener([GENBANK_TWO_RECORDS])
    report = _client(opener).download(["ON1.1", "MF2.1"],
                                      DownloadOptions(out_dir=str(tmp_path)))
    assert (tmp_path / "ON1.1.fasta").exists()
    assert (tmp_path / "MF2.1.fasta").exists()
    assert not (tmp_path / "ON1.1.fa").exists()
    assert not (tmp_path / "MF2.1.fa").exists()
    assert report.succeeded == 2


def test_download_fasta_only_uses_fasta_suffix(tmp_path):
    """只要 FASTA 的路径同样写 .fasta。"""
    opener = RecordingOpener([FASTA_TWO])
    _client(opener).download(["MF2.1"], DownloadOptions(out_dir=str(tmp_path),
                                                        want_genbank=False))
    assert (tmp_path / "MF2.1.fasta").exists()
    assert not (tmp_path / "MF2.1.fa").exists()


def test_download_single_fasta_file_can_be_read_back_with_default_suffixes(tmp_path):
    """写出的 .fasta 必须能被默认后缀集认成输入：否则用户拿它当输入会被静默跳过。"""
    from seq_toolkit.fasta_io import read_fasta

    opener = RecordingOpener([GENBANK_TWO])
    _client(opener).download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path)))
    records = list(read_fasta(str(tmp_path / "ON1.1.fasta")))
    assert [record.accession for record in records] == ["ON1.1"]


def test_download_pre_skip_judges_on_fasta_suffix(tmp_path):
    """预跳过的判据是本次会写出的那组路径：.gb + .fasta 都在才跳过、才不发请求。"""
    (tmp_path / "ON1.1.gb").write_text("已存在", encoding="utf-8")
    (tmp_path / "ON1.1.fasta").write_text("已存在", encoding="utf-8")
    opener = RecordingOpener([])          # 预跳过成立 ⇒ 一个请求都不该发
    report = _client(opener).download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path)))
    assert opener.requests == []
    assert report.skipped == 1
    assert (tmp_path / "ON1.1.fasta").read_text(encoding="utf-8") == "已存在"


def test_download_pre_skip_is_not_fooled_by_legacy_fa_file(tmp_path):
    """老后缀 .fa 不是本次产物：只有它存在时判据不成立，仍要下载（且绝不覆盖它）。"""
    (tmp_path / "ON1.1.gb").write_text("旧产物", encoding="utf-8")
    (tmp_path / "ON1.1.fa").write_text("旧产物", encoding="utf-8")
    opener = RecordingOpener([GENBANK_TWO])
    report = _client(opener).download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path)))
    assert len(opener.requests) == 1
    assert report.skipped == 0
    # 老文件原样保留，新产物是 .fasta，两者并存（绝不静默覆盖）
    assert (tmp_path / "ON1.1.fa").read_text(encoding="utf-8") == "旧产物"
    assert (tmp_path / "ON1.1.fasta").exists()


def test_collect_accessions_from_files_warns_for_corrupt_genbank(tmp_path):
    """解析层失败（SeqToolkitError）同样要记日志跳过，而不是无声无息。"""
    from seq_toolkit.applog import WARN

    log = RunLog()
    broken = tmp_path / "broken.gb"
    broken.write_bytes(b"\x00\x01\x02\x03")
    good = tmp_path / "good.fa"
    good.write_text(">ON1.1 Salsola pellucida\nACGT\n", encoding="utf-8")

    assert collect_accessions_from_files([str(broken), str(good)], log=log) == ["ON1.1"]
    warnings = [entry.message for entry in log.entries if entry.level == WARN]
    assert any("broken.gb" in message for message in warnings)
