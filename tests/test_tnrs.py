"""TNRS 纯逻辑的单元测试。全程离线，不发真实请求。"""

import pytest

import seq_toolkit.tnrs as tnrs

from seq_toolkit.tnrs import (
    BATCH_LIMIT,
    CSV_HEADERS,
    DEFAULT_CLASS,
    DEFAULT_SOURCES,
    MATCHES_BEST,
    MODE_RESOLVE,
    STATUS_MATCHED,
    STATUS_PARTIAL,
    STATUS_UNMATCHED,
    TNRS_URL,
    TnrsError,
    apply_names_to_file,
    build_batches,
    build_payload,
    build_rename_map,
    clean_names,
    conflicting_names,
    dedupe_names,
    parse_response,
    parse_score,
    rewrite_text,
    rows_to_csv,
    summarize_status,
    write_csv,
)


def test_contract_constants_match_the_measured_service():
    assert TNRS_URL == "https://tnrsapi.xyz/tnrs_api.php"
    assert BATCH_LIMIT == 5000          # 实测 5100 被 HTTP 413 拒绝（上限 5001）
    assert DEFAULT_SOURCES == "wcvp,wfo"
    assert DEFAULT_CLASS == "wfo"
    assert MODE_RESOLVE == "resolve"
    assert MATCHES_BEST == "best"


def test_payload_shape_is_two_columns_with_integer_ids():
    payload = build_payload(["Acer rubrum", "Salsola pellucida"])
    assert set(payload) == {"opts", "data"}
    assert payload["opts"] == {"sources": DEFAULT_SOURCES, "class": DEFAULT_CLASS,
                               "mode": MODE_RESOLVE, "matches": MATCHES_BEST}
    assert payload["data"] == [[1, "Acer rubrum"], [2, "Salsola pellucida"]]


def test_payload_ids_continue_across_batches():
    payload = build_payload(["A", "B"], start_id=5001)
    assert payload["data"] == [[5001, "A"], [5002, "B"]]


def test_build_batches_splits_at_the_limit():
    names = [f"Genus{i} species{i}" for i in range(12000)]
    batches = build_batches(names)
    assert [len(batch) for batch in batches] == [5000, 5000, 2000]


def test_build_batches_handles_boundaries():
    assert build_batches([]) == []
    assert len(build_batches(["x"])) == 1
    assert [len(b) for b in build_batches(["x"] * 5000)] == [5000]
    assert [len(b) for b in build_batches(["x"] * 5001)] == [5000, 1]


def test_dedupe_names_trims_blanks_and_ignores_case():
    assert dedupe_names([" Acer rubrum ", "", "  ", "acer rubrum",
                         "Salsola pellucida"]) == ["Acer rubrum", "Salsola pellucida"]


# ---------- 响应解析与三态判定（实测：空串得分 / [No match found] / matches=all 多行） ----------


def test_parse_score_handles_empty_string_and_junk():
    # 实测：未匹配时 Overall_score 是**空字符串**，不是 0 也不是 null
    assert parse_score("") is None
    assert parse_score("   ") is None
    assert parse_score(None) is None
    assert parse_score("abc") is None
    assert parse_score("1") == 1.0
    assert parse_score("0.85") == 0.85


def test_parse_response_reads_the_fields_we_use():
    from tests.fakes_tnrs import make_row, rows_json
    text = rows_json([make_row(row_id=1, submitted="Acer rubrum",
                               matched="Acer rubrum", score="1",
                               accepted="Acer rubrum", family="Sapindaceae",
                               source="wcvp")])
    rows = parse_response(text)
    assert len(rows) == 1
    row = rows[0]
    assert (row.row_id, row.submitted, row.name_matched) == ("1", "Acer rubrum", "Acer rubrum")
    assert row.score == 1.0
    assert row.accepted_name == "Acer rubrum"
    assert row.family_matched == "Sapindaceae"
    assert row.source == "wcvp"
    assert row.status == STATUS_MATCHED


def test_unmatched_is_the_literal_marker_not_falsy():
    from tests.fakes_tnrs import make_row, rows_json
    text = rows_json([make_row(matched="[No match found]", score="",
                               accepted="", unmatched="Xyzzy foobar")])
    row = parse_response(text)[0]
    assert row.status == STATUS_UNMATCHED
    assert row.score is None
    assert row.unmatched_terms == "Xyzzy foobar"


def test_partial_match_status():
    from tests.fakes_tnrs import make_row, rows_json
    text = rows_json([make_row(matched="Solanum bipatens", score="0.85",
                               accepted="Solanum cordifolium")])
    row = parse_response(text)[0]
    assert row.status == STATUS_PARTIAL
    assert row.accepted_name == "Solanum cordifolium"


def test_matched_name_with_unparsable_score_is_partial():
    """得分未知 ≠ 满分匹配。

    判成"已匹配"会让这类异常行静默混进结果表与统计；判成"部分匹配"则它会出现在
    计数里、被人工复核。这条规则必须被测试钉死，不能停留在分支顺序的副作用里。
    """
    from tests.fakes_tnrs import make_row, rows_json
    text = rows_json([make_row(matched="Acer rubrum", score="")])
    row = parse_response(text)[0]
    assert row.score is None
    assert row.status == STATUS_PARTIAL


def test_matches_all_numbers_candidates_per_id():
    from tests.fakes_tnrs import make_row, rows_json
    text = rows_json([
        make_row(row_id=1, submitted="Salsola pellucida", accepted="Salsola pellucida"),
        make_row(row_id=1, submitted="Salsola pellucida", accepted="Salsola paulsenii"),
        make_row(row_id=2, submitted="Acer rubrum", accepted="Acer rubrum"),
    ])
    rows = parse_response(text)
    assert [row.candidate_index for row in rows] == [1, 2, 1]
    # 行键必须能区分同一 ID 的多条候选，否则表格会静默丢行
    assert rows[0].key != rows[1].key


def test_summarize_status_counts_three_states():
    from tests.fakes_tnrs import make_row, rows_json
    text = rows_json([make_row(row_id=1), make_row(row_id=2, score="0.5"),
                      make_row(row_id=3, matched="[No match found]", score="")])
    counts = summarize_status(parse_response(text))
    assert counts[STATUS_MATCHED] == 1
    assert counts[STATUS_PARTIAL] == 1
    assert counts[STATUS_UNMATCHED] == 1


def test_parse_response_tolerates_missing_fields_and_skips_non_objects():
    import json
    text = json.dumps([{"ID": "1"}, "字符串不是对象", 42])
    rows = parse_response(text)
    assert len(rows) == 1
    assert rows[0].row_id == "1"
    assert rows[0].status == STATUS_UNMATCHED      # 没有 Name_matched 即未匹配


def test_parse_response_rejects_non_json_and_non_array():
    with pytest.raises(ValueError):
        parse_response("<html>502 Bad Gateway</html>")
    with pytest.raises(ValueError):
        parse_response('{"error": "boom"}')


# ---------- 清洗编排与 CSV 导出（单批失败不中断其余批次，行数对不上必须显式记账） ----------


def test_clean_names_sends_one_request_per_batch_and_keeps_ids():
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    poster = FakePoster([rows_json([make_row(row_id=1)]),
                         rows_json([make_row(row_id=5001)])])
    names = [f"Genus{i} species{i}" for i in range(5001)]
    report = clean_names(poster, names)
    assert report.batches == 2
    assert [len(p["data"]) for p in poster.payloads] == [5000, 1]
    assert poster.payloads[1]["data"][0][0] == 5001        # 第二批 ID 接着数
    assert [row.row_id for row in report.rows] == ["1", "5001"]


def test_clean_names_isolates_a_failed_batch():
    from seq_toolkit.ncbi import NcbiError
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    poster = FakePoster([NcbiError("模拟网络失败"),
                         rows_json([make_row(row_id=5001)])])
    names = [f"Genus{i} species{i}" for i in range(5001)]
    report = clean_names(poster, names)
    assert report.batches == 2
    assert len(report.failures) == 1
    assert report.failures[0][0] == 1                      # 第 1 批（从 1 开始编号）
    assert [row.row_id for row in report.rows] == ["5001"]  # 第 2 批照常返回


def test_clean_names_records_row_count_mismatch():
    """服务端少回行时必须显式记账，绝不静默少几行。"""
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    poster = FakePoster([rows_json([make_row(row_id=1)])])
    report = clean_names(poster, ["Acer rubrum", "Solanum bipatens"])
    assert report.mismatched_batches == [(1, 2, 1)]
    assert report.failures == []


def test_clean_names_reports_unmatched_names():
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    poster = FakePoster([rows_json([
        make_row(row_id=1, submitted="Acer rubrum"),
        make_row(row_id=2, submitted="Xyzzy foobar", matched="[No match found]", score="")])])
    report = clean_names(poster, ["Acer rubrum", "Xyzzy foobar"])
    assert report.unmatched_names == ["Xyzzy foobar"]


def test_clean_names_calls_progress_per_batch():
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    poster = FakePoster([rows_json([make_row()])])
    seen: list[tuple[int, int]] = []
    clean_names(poster, ["Acer rubrum"],
                on_progress=lambda done, total, text: seen.append((done, total)))
    assert seen == [(0, 1), (1, 1)]


def test_csv_rows_and_headers_match_the_spec():
    from tests.fakes_tnrs import make_row, rows_json
    rows = parse_response(rows_json([make_row(warnings="名字被更正")]))
    assert CSV_HEADERS == ("原始名称", "清洗后名称", "匹配状态", "备注")
    csv_rows = rows_to_csv(rows)
    assert csv_rows[0][:3] == ("Acer rubrum", "Acer rubrum", STATUS_MATCHED)
    assert "名字被更正" in csv_rows[0][3]


def test_write_csv_uses_utf8_sig(tmp_path):
    from tests.fakes_tnrs import make_row, rows_json
    rows = parse_response(rows_json([make_row()]))
    target = tmp_path / "out.csv"
    write_csv(target, rows)
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")                 # Excel 双击不乱码
    assert "原始名称" in raw.decode("utf-8-sig")


# ---------- 单批失败不得击穿整批（读阶段网络错误）+ 记账与三态口径的回归钉 ----------


def test_clean_names_survives_a_leaked_oserror_from_post():
    """注入的 post 泄出裸 OSError 时，只能失败该批，不能崩掉整批。

    真实路径上 http_post 会把读阶段超时包成 TnrsError，但 clean_names 是公开函数、
    post 由调用方注入，必须自己兜住——否则一次网络抖动会让前面所有批次的结果一起丢失。
    """
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    poster = FakePoster([TimeoutError("timed out"),
                         rows_json([make_row(row_id=5001)])])
    names = [f"Genus{i} species{i}" for i in range(5001)]
    report = clean_names(poster, names)
    assert len(report.failures) == 1
    assert report.failures[0][0] == 1
    assert [row.row_id for row in report.rows] == ["5001"]


def test_failed_batch_is_not_double_counted_as_a_row_mismatch():
    """失败批次只进 failures，不得同时进 mismatched_batches。

    两处都记会让用户以为出了两个问题；这条靠 try/except/else 的结构保证，
    必须有测试钉住，否则有人把记账挪进 finally 时无人发现。
    """
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    poster = FakePoster([ValueError("模拟响应异常"),
                         rows_json([make_row(row_id=5001)])])
    names = [f"Genus{i} species{i}" for i in range(5001)]
    report = clean_names(poster, names)
    assert len(report.failures) == 1
    assert report.mismatched_batches == []


def test_unmatched_names_excludes_partial_matches():
    """「有真名但得分缺失」是部分匹配，绝不能算成未匹配。

    A2 的语义修订把这类行从"已匹配"改成"部分匹配"；若 unmatched_names 用
    `not row.accepted_name` 之类的朴素写法，这类行会重新变成静默误报。
    """
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    poster = FakePoster([rows_json([
        make_row(row_id=1, submitted="Acer rubrum", matched="Acer rubrum", score="")])])
    report = clean_names(poster, ["Acer rubrum"])
    assert report.unmatched_names == []
    assert summarize_status(report.rows)[STATUS_PARTIAL] == 1


# ---------- http_post 读阶段异常包装（替身 opener，不联网、不开端口） ----------


class _FakeResponse:
    """只用于 http_post 的读阶段异常测试：read() 直接抛出预置异常。"""

    def __init__(self, error):
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        raise self._error


def _patch_opener(monkeypatch, response):
    """把 tnrs 的 build_opener 换成替身，使其返回的 opener 直接给出预置响应。"""

    class _Opener:
        def open(self, request, timeout=None):
            return response

    monkeypatch.setattr(tnrs, "build_opener", lambda *args, **kwargs: _Opener())


def test_http_post_wraps_read_stage_timeout(monkeypatch):
    """读阶段超时抛的是裸 OSError，必须被包成 TnrsError。

    urlopen 只在建连/取响应头阶段把 OSError 包成 URLError；response.read() 中途超时
    抛的是 TimeoutError（OSError 子类）。不包住，异常会穿过 clean_names 的捕获列表，
    让整批清洗崩掉——「单批失败不得中断整批」是硬约束。
    """
    _patch_opener(monkeypatch, _FakeResponse(TimeoutError("timed out")))
    with pytest.raises(tnrs.TnrsError) as info:
        tnrs.http_post({"opts": {}, "data": []})
    assert "读取" in str(info.value)


def test_http_post_wraps_incomplete_read(monkeypatch):
    """IncompleteRead 是 HTTPException 而不是 OSError，靠第二支兜住。"""
    import http.client

    _patch_opener(monkeypatch, _FakeResponse(http.client.IncompleteRead(b"partial")))
    with pytest.raises(tnrs.TnrsError):
        tnrs.http_post({"opts": {}, "data": []})


# ---------- 名称回写序列文件（另存 _cleaned，绝不就地覆盖） ----------


FASTA_SAMPLE = (
    ">ON929859.1 Salsola pellucida voucher X matK gene, partial cds\n"
    "ATGCATGCATGC\n"
    ">ON929860.1 Salsola tragus isolate Y\n"
    "TTTTGGGGCCCC\n")

GENBANK_SAMPLE = (
    "LOCUS       ON929859                 12 bp    DNA     linear   PLN 01-JAN-2024\n"
    "DEFINITION  Salsola pellucida matK gene, partial cds.\n"
    "ACCESSION   ON929859\n"
    "VERSION     ON929859.1\n"
    "SOURCE      Salsola pellucida\n"
    "  ORGANISM  Salsola pellucida\n"
    "FEATURES             Location/Qualifiers\n"
    "     source          1..12\n"
    '                     /organism="Salsola pellucida"\n'
    "ORIGIN\n"
    "        1 atgcatgcat gc\n"
    "//\n")


def test_build_rename_map_skips_unmatched_and_keeps_first_candidate():
    from tests.fakes_tnrs import make_row, rows_json
    rows = parse_response(rows_json([
        make_row(row_id=1, submitted="Salsola pellucida", accepted="Salsola pellucida"),
        make_row(row_id=1, submitted="Salsola pellucida", accepted="Salsola paulsenii"),
        make_row(row_id=2, submitted="Xyzzy foobar", matched="[No match found]",
                 score="", accepted=""),
    ]))
    assert build_rename_map(rows) == {"Salsola pellucida": "Salsola pellucida"}


def test_rewrite_text_replaces_only_header_lines_in_fasta():
    mapping = {"Salsola pellucida": "Salsola pellucida subsp. pellucida"}
    text, count = rewrite_text(FASTA_SAMPLE, mapping, genbank=False)
    assert count == 1
    assert ">ON929859.1 Salsola pellucida subsp. pellucida voucher X" in text
    assert ">ON929860.1 Salsola tragus" in text          # 未命中不动
    assert text.count("ATGCATGCATGC") == 1               # 序列行字节不变


def test_rewrite_text_touches_organism_source_and_qualifier_in_genbank():
    mapping = {"Salsola pellucida": "Salsola australis"}
    text, count = rewrite_text(GENBANK_SAMPLE, mapping, genbank=True)
    assert count == 4                                     # DEFINITION/SOURCE/ORGANISM//organism
    assert "DEFINITION  Salsola australis matK gene" in text
    assert "SOURCE      Salsola australis\n" in text
    assert "  ORGANISM  Salsola australis\n" in text
    assert '/organism="Salsola australis"' in text
    assert "LOCUS       ON929859" in text                 # 其余行字节不变
    assert "        1 atgcatgcat gc" in text


def test_rewrite_text_does_not_touch_sequence_lines_in_genbank():
    # ORIGIN 段里的碱基行绝不能被替换（哪怕短名恰好出现在碱基里）
    text, count = rewrite_text(GENBANK_SAMPLE, {"atgc": "XXXX"}, genbank=True)
    assert count == 0
    assert "atgcatgcat gc" in text


def test_apply_names_to_file_writes_cleaned_copy(tmp_path):
    source = tmp_path / "样本.fasta"
    source.write_text(FASTA_SAMPLE, encoding="utf-8", newline="\n")
    out_dir = tmp_path / "out"
    outcome = apply_names_to_file(str(source),
                                  {"Salsola pellucida": "Salsola australis"},
                                  str(out_dir))
    assert outcome.target.endswith("样本_cleaned.fasta")
    assert outcome.replacements == 1
    written = (out_dir / "样本_cleaned.fasta").read_text(encoding="utf-8")
    assert "Salsola australis voucher X" in written
    # 原文件必须原封不动
    assert source.read_text(encoding="utf-8") == FASTA_SAMPLE


def test_apply_names_to_file_reports_names_not_found(tmp_path):
    source = tmp_path / "样本.fasta"
    source.write_text(FASTA_SAMPLE, encoding="utf-8", newline="\n")
    outcome = apply_names_to_file(str(source),
                                  {"种不存在 Xyzzy": "Something else"},
                                  str(tmp_path / "out"))
    assert outcome.replacements == 0
    assert outcome.missing == ("种不存在 Xyzzy",)


def test_apply_names_to_file_lets_existing_target_yield(tmp_path):
    source = tmp_path / "样本.fasta"
    source.write_text(FASTA_SAMPLE, encoding="utf-8", newline="\n")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "样本_cleaned.fasta").write_text("已存在的内容", encoding="utf-8")
    outcome = apply_names_to_file(str(source), {"Salsola pellucida": "A"}, str(out_dir))
    assert outcome.target.endswith("样本_cleaned_1.fasta")


def test_apply_names_to_file_refuses_gzip_input(tmp_path):
    """压缩输入必须显式报错，绝不静默写出损坏的 _cleaned.gz。"""
    import gzip

    source = tmp_path / "样本.fasta.gz"
    with gzip.open(source, "wt", encoding="utf-8") as handle:
        handle.write(">ON1.1 Salsola pellucida\nATGC\n")

    out_dir = tmp_path / "out"
    with pytest.raises(TnrsError) as info:
        apply_names_to_file(str(source),
                            {"Salsola pellucida": "Salsola australis"}, str(out_dir))
    assert "解压" in str(info.value)
    # 不产出任何文件
    assert not out_dir.exists() or not list(out_dir.iterdir())


def test_apply_names_to_file_refuses_non_utf8_input(tmp_path):
    """非 UTF-8 输入必须显式拒绝，绝不静默写出含 U+FFFD 的损坏文件。"""
    source = tmp_path / "样本.fasta"
    source.write_bytes(">ON1.1 Salsola pellucida 中文注释\nATGC\n".encode("gbk"))
    out_dir = tmp_path / "out"
    with pytest.raises(TnrsError) as info:
        apply_names_to_file(str(source), {"Salsola pellucida": "Salsola australis"},
                            str(out_dir))
    assert "UTF-8" in str(info.value)
    assert not out_dir.exists() or not list(out_dir.iterdir())


def test_apply_names_to_file_refuses_replacement_characters(tmp_path):
    """文件里已含 U+FFFD 时也要拒绝：不能把别处造成的损坏继续往下传。"""
    source = tmp_path / "样本.fasta"
    source.write_text(">ON1.1 Salsola pellucida \ufffd\ufffd\nATGC\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    with pytest.raises(TnrsError) as info:
        apply_names_to_file(str(source), {"Salsola pellucida": "Salsola australis"},
                            str(out_dir))
    assert "替换字符" in str(info.value)


def test_fasta_sequence_lines_are_never_touched():
    """序列行一个字节都不能动。

    旧用例的映射键是学名，**不可能**出现在碱基行里，所以那条断言是空真断言：
    把 `>` 判定挪出循环它照样全绿。这里用确实会出现在序列里的键去打。
    """
    text, count = rewrite_text(FASTA_SAMPLE, {"ATGC": "XXXX"}, genbank=False)
    assert count == 0
    assert text == FASTA_SAMPLE


def test_conflicting_names_dedupes_and_keeps_order():
    """同一原始名给出多个不同接受名时：去重、保持首次出现顺序。"""
    from tests.fakes_tnrs import make_row, rows_json
    rows = parse_response(rows_json([
        make_row(row_id=1, submitted="Salsola pellucida", accepted="Salsola pellucida"),
        make_row(row_id=1, submitted="Salsola pellucida", accepted="Salsola paulsenii"),
        make_row(row_id=1, submitted="Salsola pellucida", accepted="Salsola pellucida"),
    ]))
    assert conflicting_names(rows) == {
        "Salsola pellucida": ["Salsola pellucida", "Salsola paulsenii"]}
