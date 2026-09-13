import threading
from pathlib import Path

import pytest

from seq_toolkit.applog import RunLog
from seq_toolkit.fasta_io import read_fasta
from seq_toolkit.model import SeqToolkitError
from seq_toolkit.pipeline import (
    ConvertPlan,
    OperationCancelled,
    ProcessPlan,
    RenamePlan,
    convert_each_file,
    rename_disk_files,
    resolve_output_path,
    run_merge,
    split_records,
)

FASTA_A = ">ON1.1 Salsola pellucida chloroplast, complete genome\nACGTACGT\n"
FASTA_B = ">MF2.1 Kochia scoparia chloroplast, complete genome\nTTTTGGGG\n"
GENBANK_C = (
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


def _write(tmp_path, name, text):
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return str(target)


def _plan(tmp_path, inputs, **overrides):
    options = dict(
        inputs=inputs,
        output_path=str(tmp_path / "out.fasta"),
        output_format="fasta",
        input_format="auto",
        naming_mode="keep",
        dedup="accession",
        recursive=True,
        wrap=0,
        log=RunLog(),
    )
    options.update(overrides)
    return ProcessPlan(**options)


def test_resolve_output_path_returns_input_when_free(tmp_path):
    target = tmp_path / "x.fasta"
    assert resolve_output_path(str(target)) == str(target)


def test_resolve_output_path_appends_index_when_taken(tmp_path):
    target = tmp_path / "x.fasta"
    target.write_text("taken", encoding="utf-8")
    resolved = resolve_output_path(str(target))
    assert Path(resolved).name == "x_1.fasta"


def test_resolve_output_path_keeps_incrementing(tmp_path):
    (tmp_path / "x.fasta").write_text("a", encoding="utf-8")
    (tmp_path / "x_1.fasta").write_text("b", encoding="utf-8")
    assert Path(resolve_output_path(str(tmp_path / "x.fasta"))).name == "x_2.fasta"


def test_merge_two_fasta_files(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    b = _write(tmp_path, "b.fasta", FASTA_B)
    result = run_merge(_plan(tmp_path, [a, b]))
    assert result.records_out == 2
    text = Path(result.output_path).read_text(encoding="utf-8")
    assert ">ON1.1" in text and ">MF2.1" in text


def test_merge_mixed_formats_into_fasta(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    c = _write(tmp_path, "c.gbk", GENBANK_C)
    plan = _plan(tmp_path, [a, c], dedup="none")
    result = run_merge(plan)
    assert result.records_out == 2


def test_deduplicate_by_accession(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    b = _write(tmp_path, "copy.fa", FASTA_A)
    result = run_merge(_plan(tmp_path, [a, b]))
    assert result.records_out == 1
    assert result.duplicates_removed == 1


def test_deduplication_keeps_distinct_versions(tmp_path):
    a = _write(tmp_path, "a.fa", ">ON1.1 Salsola pellucida\nACGT\n")
    b = _write(tmp_path, "b.fa", ">ON1.2 Salsola pellucida\nACGT\n")
    result = run_merge(_plan(tmp_path, [a, b]))
    assert result.records_out == 2
    assert result.duplicates_removed == 0


def test_dedup_none_keeps_duplicates(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    b = _write(tmp_path, "copy.fa", FASTA_A)
    result = run_merge(_plan(tmp_path, [a, b], dedup="none"))
    assert result.records_out == 2


def test_naming_mode_applied_to_output(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    result = run_merge(_plan(tmp_path, [a], naming_mode="accession_species"))
    assert Path(result.output_path).read_text(encoding="utf-8").startswith(
        ">ON1.1_Salsola_pellucida\n")


def test_unknown_format_file_is_skipped_and_logged(tmp_path):
    junk = _write(tmp_path, "junk.txt", "hello\n")
    a = _write(tmp_path, "a.fa", FASTA_A)
    log = RunLog()
    result = run_merge(_plan(tmp_path, [junk, a], log=log))
    assert result.records_out == 1
    assert junk in result.skipped_files
    assert any("无法识别" in e.message for e in log.entries)


def test_misleading_suffix_is_resolved_by_content(tmp_path):
    lying = _write(tmp_path, "lying.fa", GENBANK_C)
    log = RunLog()
    result = run_merge(_plan(tmp_path, [lying], log=log))
    assert result.records_out == 1
    assert any("后缀名与内容不符" in e.message for e in log.entries)


def test_existing_output_is_not_overwritten(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    target = tmp_path / "out.fasta"
    target.write_text("原有内容", encoding="utf-8")
    log = RunLog()
    result = run_merge(_plan(tmp_path, [a], log=log))
    assert target.read_text(encoding="utf-8") == "原有内容"
    assert Path(result.output_path).name == "out_1.fasta"
    assert any("已存在" in e.message for e in log.entries)


def test_cancellation_raises_operation_cancelled(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(OperationCancelled):
        run_merge(_plan(tmp_path, [a], cancel=cancel))


def test_empty_input_raises(tmp_path):
    with pytest.raises(SeqToolkitError):
        run_merge(_plan(tmp_path, []))


def test_progress_callback_is_invoked(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    seen: list[tuple[int, int, str]] = []
    run_merge(_plan(tmp_path, [a], progress=lambda d, t, m: seen.append((d, t, m))))
    assert seen and seen[-1][0] == seen[-1][1] == 1


def test_record_without_species_lands_in_exception_list_with_final_name(tmp_path):
    a = _write(tmp_path, "a.fa", ">ON1.1 chloroplast, complete genome\nACGT\n")
    log = RunLog()
    run_merge(_plan(tmp_path, [a], naming_mode="species", log=log))
    assert log.exception_count() >= 1
    entry = [e for e in log.exceptions if "物种名" in e.reason][0]
    assert entry.final_name == "ON1.1"


def test_benign_prefix_stripping_is_logged_as_info_not_exception(tmp_path):
    # 注意：简报此处原用 ">ON1.1"，但 "ON1.1" 不是合法 INSDC 登录号
    # （model._ACCESSION_RE 要求字母后至少 5 位数字），会额外产生一条
    # "accession 格式可疑" 警告——那是需要人工复核的，本就该留在异常清单里，
    # 与本测试要断言的「伪装前缀属于良性警告」无关。改用合法登录号以隔离被测行为。
    a = _write(tmp_path, "a.fa",
               ">ON929859.1 UNVERIFIED: Salsola pellucida chloroplast, complete genome\nACGT\n")
    log = RunLog()
    run_merge(_plan(tmp_path, [a], log=log))
    assert log.exception_count() == 0
    assert any("伪装前缀" in e.message for e in log.entries)


def test_suspicious_accession_stays_in_exception_list(tmp_path):
    """上一条测试改用合法登录号的原因，在此逐字钉住简报原始 fixture 的真实行为。"""
    a = _write(tmp_path, "a.fa",
               ">ON1.1 UNVERIFIED: Salsola pellucida chloroplast, complete genome\nACGT\n")
    log = RunLog()
    run_merge(_plan(tmp_path, [a], log=log))
    assert any("伪装前缀" in e.message for e in log.entries)
    assert [e for e in log.exceptions if "格式可疑" in e.reason]


def test_genbank_input_to_genbank_output_preserves_features(tmp_path):
    c = _write(tmp_path, "c.gbk", GENBANK_C)
    result = run_merge(_plan(tmp_path, [c], output_format="genbank"))
    text = Path(result.output_path).read_text(encoding="utf-8")
    assert '/gene="matK"' in text
    assert "FEATURES" in text


def test_fasta_input_to_genbank_output_is_synthesised_and_re_readable(tmp_path):
    from seq_toolkit.genbank_io import read_genbank
    a = _write(tmp_path, "a.fa", FASTA_A)
    result = run_merge(_plan(tmp_path, [a], output_format="genbank"))
    records = list(read_genbank(result.output_path))
    assert len(records) == 1
    assert records[0].seq == "ACGTACGT"
    assert records[0].species == "Salsola_pellucida"


# ---------------------------------------------------------------------------
# 以下为本任务在简报 19 个测试之外补充的回归测试：简报的测试集只覆盖了
# write_genbank 的「raw_block 保真」（上一个测试）与「合成记录」（上上个测试），
# 未覆盖「改名只动 LOCUS 名称列」以及截断 .gz 不得中断整批（关键约束 A）这两条
# 明确要求的行为。缺了它们，这两条约束一旦回归将没有任何测试会失败。
# ---------------------------------------------------------------------------


def test_genbank_rename_replaces_only_locus_name_columns(tmp_path):
    from seq_toolkit.genbank_io import format_genbank_record, read_genbank

    c = _write(tmp_path, "c.gbk", GENBANK_C)
    record = list(read_genbank(c))[0]
    text = format_genbank_record(record, "Shortname")

    lines = text.split("\n")
    original = GENBANK_C.split("\n")
    locus = lines[0]
    assert locus.startswith("LOCUS       ")
    assert locus[12:28] == "Shortname".ljust(16)
    assert locus[28:] == original[0][28:]
    # 除 LOCUS 行的名称列外，其余每一列逐字节不变
    assert lines[1:] == original[1:]
    # ACCESSION / VERSION 是序列的事实标识，改名不得篡改
    assert "ACCESSION   ON1\n" in text
    assert "VERSION     ON1.1\n" in text
    assert '/gene="matK"' in text


def test_genbank_overlong_name_keeps_original_locus(tmp_path):
    from seq_toolkit.genbank_io import format_genbank_record, read_genbank

    c = _write(tmp_path, "c.gbk", GENBANK_C)
    record = list(read_genbank(c))[0]
    long_name = "ON1.1_Salsola_pellucida"
    assert len(long_name) > 16
    # 超长名不截断写入，而是保持原 LOCUS 名（既不破坏列对齐，也不被下游工具截断）
    assert format_genbank_record(record, long_name) == record.raw_block


def test_truncated_gz_file_is_skipped_and_batch_continues(tmp_path):
    import gzip

    a = _write(tmp_path, "a.fa", FASTA_A)
    broken = tmp_path / "broken.fa.gz"
    raw = gzip.compress(FASTA_B.encode("utf-8"))
    broken.write_bytes(raw[:len(raw) // 2])
    log = RunLog()
    # 截断的 .gz 在解析阶段抛的是 EOFError 或 zlib.error，二者都不是 OSError 子类；
    # 漏捕获任一，这个坏文件就会中断整批处理而不是被跳过。
    result = run_merge(_plan(tmp_path, [str(broken), a], log=log))
    assert result.records_out == 1
    assert str(broken) in result.skipped_files


def test_fasta_to_genbank_logs_synthesised_record_notice(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    log = RunLog()
    run_merge(_plan(tmp_path, [a], output_format="genbank", log=log))
    assert any("合成" in e.message and "feature" in e.message for e in log.entries)


def test_genbank_to_genbank_logs_when_name_exceeds_locus_width(tmp_path):
    c = _write(tmp_path, "c.gbk", GENBANK_C)
    log = RunLog()
    # ON1.1_Salsola_pellucida 共 23 字符 > LOCUS 名称列宽 16，LOCUS 名保持不变，
    # 必须留下 ACCESSION 与新名称的对应关系，否则用户改名被无声丢弃。
    run_merge(_plan(tmp_path, [c], output_format="genbank",
                    naming_mode="accession_species", log=log))
    assert any("超过 16 字符" in e.message and "ON1.1" in e.message for e in log.entries)
    assert not any("合成" in e.message for e in log.entries)


# ---------------------------------------------------------------------------
# 修复轮次补充的回归测试（评审发现，控制器裁决必须修复）：
#   1. 默认命名模式（keep）下复核清单的「最终采用的名称」列恒为空白
#   2. output_format 等枚举字段完全不校验，会静默写出错误格式
#   3. 被去重丢弃的记录出现在人工复核清单里
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header,expected_name",
    [
        # 物种名提取失败 → 走「物种名缺失，名称回退为登录号」这条 add_exception
        ("ON929859.1 chloroplast, complete genome", "ON929859.1"),
        # 硬警告（登录号可疑）→ 走 pending_warnings 这条 add_exception
        ("ON1.1 UNVERIFIED: Salsola pellucida chloroplast, complete genome", "ON1.1"),
    ],
)
def test_default_plan_review_list_final_name_is_accession_not_blank(
        tmp_path, header, expected_name):
    """默认计划（naming_mode="keep"）下「最终采用的名称」不得为空白。

    keep 是 ProcessPlan 的默认值，而 build_name_map 在 keep 下按设计返回 {}，
    于是 name_map.get(record, "") 得到空串；但真正写出的名字是登录号
    （write_fasta / write_genbank 都有 `or record.accession` 回退）。复核清单必须与
    写入侧一致，否则默认配置下这一列全是空白——而它是本任务交付给用户的核心产物，
    Task 13/23 的报表与 GUI 会直接显示空列。
    """
    a = _write(tmp_path, "a.fa", f">{header}\nACGT\n")
    log = RunLog()
    # 刻意不传任何可选参数：要测的就是「用户直接使用默认计划」这条路径
    plan = ProcessPlan(inputs=[a], output_path=str(tmp_path / "out.fasta"), log=log)
    assert plan.naming_mode == "keep"
    result = run_merge(plan)

    assert log.exception_count() >= 1
    assert all(entry.final_name for entry in log.exceptions), log.exceptions
    for entry in log.exceptions:
        assert entry.final_name == expected_name
    # 与写入侧对齐：输出 header 用的正是同一个名称
    assert Path(result.output_path).read_text(encoding="utf-8") == f">{expected_name}\nACGT\n"


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("output_format", "gb"),
        ("input_format", "genbank2"),
        ("naming_mode", "species_v2"),
        ("dedup", "all"),
    ],
)
def test_invalid_plan_enum_is_rejected_at_construction(tmp_path, field, bad_value):
    """枚举字段必须在构造 ProcessPlan 时就抛 SeqToolkitError。

    否则：output_format 传错值（如 "gb"）不报错，而是静默按 FASTA 写出——用户要
    GenBank 却拿到 FASTA 且日志里一个字都没有；naming_mode 传错值则要等整批文件读完
    才由 build_name_map 抛 ValueError，而 ValueError 不在调用方的 SeqToolkitError
    捕获集内（GUI 层会崩）。本项目招牌规则是「永不静默」，因此必须在构造时把关。
    """
    with pytest.raises(SeqToolkitError) as info:
        _plan(tmp_path, ["a.fa"], **{field: bad_value})
    assert not isinstance(info.value, ValueError)
    assert bad_value in str(info.value)


@pytest.mark.parametrize(
    "field,good_value",
    [
        ("output_format", "fasta"),
        ("output_format", "genbank"),
        ("input_format", "auto"),
        ("input_format", "fasta"),
        ("input_format", "genbank"),
        ("naming_mode", "keep"),
        ("naming_mode", "accession"),
        ("naming_mode", "species"),
        ("naming_mode", "accession_species"),
        ("dedup", "accession"),
        ("dedup", "none"),
    ],
)
def test_legal_plan_enum_values_are_accepted(tmp_path, field, good_value):
    """校验不得误伤任何一个合法取值。"""
    _plan(tmp_path, ["a.fa"], **{field: good_value})


def test_post_construction_attribute_assignment_still_works(tmp_path):
    """GUI 标签页在构造**之后**才赋 plan.cancel = ctx.cancel_event；新增的
    __post_init__ 只做校验，不得妨碍该用法。"""
    plan = _plan(tmp_path, ["a.fa"])
    event = threading.Event()
    plan.cancel = event
    assert plan.cancel is event


def test_deduplicated_record_is_absent_from_manual_review_list(tmp_path):
    """被去重丢弃的记录并没有写出，不得出现在人工复核清单里。

    否则用户会在清单里看到一条并不存在的产物，去核对一个永远不会生成的文件。
    """
    duplicate = ">ON1.1 UNVERIFIED: Salsola pellucida chloroplast, complete genome\nACGT\n"
    a = _write(tmp_path, "a.fa", duplicate)
    b = _write(tmp_path, "copy.fa", duplicate)
    log = RunLog()
    result = run_merge(_plan(tmp_path, [a, b], log=log))

    assert result.records_out == 1
    assert result.duplicates_removed == 1
    # 清单行数与保留下来的记录数一致
    assert len(log.exceptions) == 1
    entry = log.exceptions[0]
    assert Path(entry.path).name == "a.fa"
    assert not any(Path(e.path).name == "copy.fa" for e in log.exceptions)
    # 保留下来的那条记录，其「最终采用的名称」仍必须是非空的登录号
    assert entry.final_name == "ON1.1"


# ---------------------------------------------------------------------------
# Task 13：按序列拆分（split_records）
# ---------------------------------------------------------------------------


def test_split_records_writes_one_file_per_record(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A + FASTA_B)
    records = list(read_fasta(a))
    out_dir = tmp_path / "split"
    result = split_records(records, str(out_dir))
    assert result.records_out == 2
    assert sorted(p.name for p in out_dir.iterdir()) == [
        "MF2.1_Kochia_scoparia.fasta", "ON1.1_Salsola_pellucida.fasta"]
    # 文件名与文件内序列名必须一致（否则下游按文件名索引会与内容对不上）。
    # 只断言文件名的话，write_fasta 漏传 name_map 时序列名会静默回退成登录号，
    # 测试仍然全绿——这一条就是那道防线。
    assert (out_dir / "ON1.1_Salsola_pellucida.fasta").read_text(
        encoding="utf-8").startswith(">ON1.1_Salsola_pellucida\n")
    assert (out_dir / "MF2.1_Kochia_scoparia.fasta").read_text(
        encoding="utf-8").startswith(">MF2.1_Kochia_scoparia\n")


def test_split_records_avoids_overwriting(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    records = list(read_fasta(a))
    out_dir = tmp_path / "split"
    out_dir.mkdir()
    (out_dir / "ON1.1_Salsola_pellucida.fasta").write_text("原有", encoding="utf-8")
    split_records(records, str(out_dir))
    assert (out_dir / "ON1.1_Salsola_pellucida.fasta").read_text(
        encoding="utf-8") == "原有"
    assert (out_dir / "ON1.1_Salsola_pellucida_1.fasta").exists()
    # 让位到 _1 的那个文件同样要做到「文件内序列名 == 文件名去扩展名」
    assert (out_dir / "ON1.1_Salsola_pellucida_1.fasta").read_text(
        encoding="utf-8").startswith(">ON1.1_Salsola_pellucida\n")


def test_rename_disk_files_dry_run_does_not_touch_disk(tmp_path):
    a = _write(tmp_path, "messy_name.fa", FASTA_A)
    plan = rename_disk_files([a], dry_run=True)
    assert isinstance(plan, RenamePlan)
    assert Path(a).exists()
    assert Path(plan.pairs[0][1]).name == "ON1.1_Salsola_pellucida.fa"


def test_rename_disk_files_actually_renames(tmp_path):
    a = _write(tmp_path, "messy_name.fa", FASTA_A)
    plan = rename_disk_files([a], dry_run=False)
    assert not Path(a).exists()
    assert Path(plan.pairs[0][1]).exists()
    assert plan.renamed == 1


def test_rename_disk_files_avoids_collision(tmp_path):
    a = _write(tmp_path, "messy_a.fa", FASTA_A)
    b = _write(tmp_path, "messy_b.fa", FASTA_A)
    plan = rename_disk_files([a, b], dry_run=False)
    targets = sorted(Path(new).name for _old, new in plan.pairs)
    assert targets == ["ON1.1_Salsola_pellucida.fa", "ON1.1_Salsola_pellucida_1.fa"]
    assert len(plan.conflicts) == 1


def test_rename_disk_files_keeps_gz_suffix(tmp_path):
    import gzip
    target = tmp_path / "messy.fa.gz"
    with gzip.open(str(target), "wt", encoding="utf-8") as handle:
        handle.write(FASTA_A)
    plan = rename_disk_files([str(target)], dry_run=True, input_format="fasta")
    assert Path(plan.pairs[0][1]).name == "ON1.1_Salsola_pellucida.fa.gz"


# ---------------------------------------------------------------------------
# Task 13 补充回归测试（控制器裁决的额外要求 + 自检项）
# ---------------------------------------------------------------------------


def test_rename_disk_files_keep_mode_leaves_every_file_untouched(tmp_path):
    """naming_mode="keep" 的语义就是「不改动文件名」，必须原样返回空对照表。

    若照常渲染，render_name(record, "keep") 返回的是登录号，用户在 GUI 里选
    「不改名（保留原始序列名）」+ 勾选「重命名已有磁盘文件」时，所有文件都会被
    改名成登录号——与所选模式恰好相反。
    """
    a = _write(tmp_path, "乱名.fa", FASTA_A)
    before = _snapshot(tmp_path)
    log = RunLog()
    plan = rename_disk_files([a], naming_mode="keep", dry_run=False, log=log)

    assert plan.pairs == []
    assert plan.renamed == 0
    assert plan.conflicts == []
    # 原文件仍在原位，且整个目录逐字节未变（既没有改名，也没有新文件产生）
    assert _snapshot(tmp_path) == before
    assert any("不改名" in entry.message for entry in log.entries)


def _snapshot(root: Path) -> dict[str, bytes]:
    """递归快照目录下所有文件的内容，用于逐字节比对磁盘状态。"""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def test_rename_disk_files_dry_run_leaves_disk_byte_identical(tmp_path):
    """dry_run=True 时磁盘必须逐字节未变——只断言「文件还在」不够。

    预览若顺手改了名，用户点「预览」就会毁掉原始文件名，而且没有任何征兆。
    """
    root = tmp_path / "data"
    _write(root, "乱名一.fa", FASTA_A)
    _write(root, "乱名二.gbk", GENBANK_C)
    _write(root, "sub/乱名三.fasta", FASTA_B)
    _write(root, "notes.txt", "无关文件\n")

    before = _snapshot(root)
    plan = rename_disk_files([str(root)], dry_run=True)

    assert _snapshot(root) == before
    assert len(plan.pairs) == 3, plan.pairs
    assert plan.renamed == 0


def test_rename_disk_files_uses_first_record_of_multi_record_file(tmp_path):
    """多记录文件以第一条记录决定新文件名，并记 INFO 说明这一取舍。"""
    a = _write(tmp_path, "乱名.fa", FASTA_A + FASTA_B)
    log = RunLog()
    plan = rename_disk_files([a], dry_run=True, log=log)

    assert Path(plan.pairs[0][1]).name == "ON1.1_Salsola_pellucida.fa"
    assert any(entry.level == "INFO" and "多" in entry.message
               and "ON1.1" in entry.message for entry in log.entries)


def test_rename_disk_files_renames_multi_record_file_for_real(tmp_path):
    """回归（Task 28 验收项 13 发现）：多记录文件在 dry_run=False 时也必须真的改名。

    旧实现用 next(iterator) 只取第一条记录就停手，多记录文件的生成器停在半途、
    底层文件句柄一直没关；Windows 上紧接着的 Path.rename 会抛 WinError 32
    （另一个程序正在使用此文件），该文件被静默跳过——日志里只有一行 ERROR，
    用户看到的是「预览说会改名、执行后名字却没变」。单记录文件因为第二次
    next() 已把生成器耗尽、句柄自动关闭，所以掩盖了这个缺陷。
    """
    second = GENBANK_C.replace("ON1.1", "ON9.1").replace("ON1\n", "ON9\n")
    a = _write(tmp_path, "乱名.gb", GENBANK_C + second)
    log = RunLog()
    plan = rename_disk_files([a], dry_run=False, log=log)

    assert plan.renamed == 1, [entry.message for entry in log.entries]
    assert not Path(a).exists()
    assert Path(plan.pairs[0][1]).name == "ON1.1_Salsola_pellucida.gb"


def test_rename_disk_files_skips_broken_file_and_continues(tmp_path):
    """单条记录失败不得中断整批：坏文件记 ERROR 跳过，好文件照常改名。"""
    broken = _write(tmp_path, "broken.fa", "这不是 FASTA\n")
    good = _write(tmp_path, "乱名.fa", FASTA_A)
    log = RunLog()
    plan = rename_disk_files([broken, good], dry_run=False, log=log)

    assert Path(broken).exists()
    assert [Path(new).name for _old, new in plan.pairs] == ["ON1.1_Salsola_pellucida.fa"]
    assert plan.renamed == 1
    assert any(entry.level == "ERROR" for entry in log.entries)


def test_rename_disk_files_skips_truncated_gz_and_continues(tmp_path):
    """截断的 .gz 抛的是 EOFError / zlib.error，二者都不是 OSError 子类。"""
    import gzip
    good = _write(tmp_path, "乱名.fa", FASTA_A)
    broken = tmp_path / "broken.fa.gz"
    raw = gzip.compress(FASTA_B.encode("utf-8"))
    broken.write_bytes(raw[:len(raw) // 2])

    log = RunLog()
    plan = rename_disk_files([str(broken), good], dry_run=False, log=log)

    assert broken.exists()
    assert plan.renamed == 1
    assert any(entry.level == "ERROR" for entry in log.entries)


def test_rename_disk_files_keeps_double_suffix_for_genbank_gz(tmp_path):
    """双后缀必须整段保留：乱名.gbk.gz → ON1.1_Salsola_pellucida.gbk.gz。"""
    import gzip
    target = tmp_path / "乱名.gbk.gz"
    with gzip.open(str(target), "wt", encoding="utf-8") as handle:
        handle.write(GENBANK_C)
    plan = rename_disk_files([str(target)], dry_run=True)
    assert Path(plan.pairs[0][1]).name == "ON1.1_Salsola_pellucida.gbk.gz"


def test_rename_disk_files_does_not_rename_file_already_correctly_named(tmp_path):
    """名字已经正确的文件不得产生对照表条目，更不能改名。"""
    a = _write(tmp_path, "ON1.1_Salsola_pellucida.fa", FASTA_A)
    log = RunLog()
    plan = rename_disk_files([a], dry_run=False, log=log)
    assert Path(a).exists()
    assert plan.renamed == 0
    assert [Path(new).name for _old, new in plan.pairs] == ["ON1.1_Salsola_pellucida.fa"]


def test_split_records_writes_genbank_and_is_re_readable(tmp_path):
    from seq_toolkit.genbank_io import read_genbank
    c = _write(tmp_path, "c.gbk", GENBANK_C)
    records = list(read_genbank(c))
    out_dir = tmp_path / "split"
    result = split_records(records, str(out_dir), output_format="genbank",
                           naming_mode="accession")
    assert result.records_out == 1
    written = out_dir / "ON1.1.gb"
    assert written.exists()
    assert '/gene="matK"' in written.read_text(encoding="utf-8")
    assert list(read_genbank(str(written)))[0].seq == "ACGTACGT"
    # GenBank 侧的同一不变式：LOCUS 行的名称列（第 13-28 列）必须等于文件名的
    # 主干。只断言文件名不够——write_genbank 漏传 name_map 时 LOCUS 会保持原名，
    # 下游按文件名索引就会与文件内声明的名称对不上。
    locus = written.read_text(encoding="utf-8").splitlines()[0]
    assert locus[12:28].strip() == written.stem


def test_split_records_genbank_locus_matches_filename(tmp_path):
    """最终名称与 LOCUS 原名不同的记录，写出的 LOCUS 名称列必须跟着变。

    上面的用例里渲染出的名称恰好就是 LOCUS 原名 "ON1.1"，而
    format_genbank_record 在 name == record.accession 时会原样返回 raw_block，
    漏传 name_map 也看不出来。这里刻意让 LOCUS 原名（STALE_LOCUS）与渲染出的
    名称（物种名 Salsola）不同，真正钉住 GenBank 侧「文件内名称 == 文件名」。
    """
    from seq_toolkit.genbank_io import read_genbank
    stale = GENBANK_C.replace("LOCUS       ON1.1 ", "LOCUS       STALE_LOCUS ")
    stale = stale.replace("  ORGANISM  Salsola pellucida\n", "  ORGANISM  Salsola\n")
    c = _write(tmp_path, "c.gbk", stale)
    records = list(read_genbank(c))
    out_dir = tmp_path / "split"
    split_records(records, str(out_dir), output_format="genbank",
                  naming_mode="species")

    written = out_dir / "Salsola.gb"
    assert written.exists()
    text = written.read_text(encoding="utf-8")
    assert text.splitlines()[0][12:28].strip() == written.stem == "Salsola"
    assert "STALE_LOCUS" not in text


def test_split_records_unnamed_records_keep_filename_and_inner_name_in_sync(tmp_path):
    """登录号与物种名都拿不到时，文件名与文件内序列名仍必须逐字一致。

    这里正是漏传 name_map 会暴露的退化情形：文件名用 build_name_map 在全批范围内
    算出的 sequence_3，而 write_fasta 每次只拿到 [record]，它自己的 index 从 1 重数，
    会写出 >sequence_1——文件名说 3、文件里说 1。
    """
    a = _write(tmp_path, "a.fa", FASTA_A + FASTA_B + ">\nAAAA\n")
    records = list(read_fasta(a))
    out_dir = tmp_path / "split"
    split_records(records, str(out_dir))

    written = out_dir / "sequence_3.fasta"
    assert written.exists()
    assert written.read_text(encoding="utf-8").startswith(">sequence_3\n")


def test_split_records_keep_mode_uses_accession_as_filename(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    records = list(read_fasta(a))
    out_dir = tmp_path / "split"
    split_records(records, str(out_dir), naming_mode="keep")
    assert [p.name for p in out_dir.iterdir()] == ["ON1.1.fasta"]
    # keep 模式下文件内序列名同样必须与文件名一致
    assert (out_dir / "ON1.1.fasta").read_text(
        encoding="utf-8").startswith(">ON1.1\n")


@pytest.mark.parametrize("bad_format", ["gb", "GENBANK", ""])
def test_split_records_rejects_unknown_output_format(tmp_path, bad_format):
    """未知输出格式必须报错，而不是静默按 FASTA 写出。

    与 ProcessPlan.__post_init__ 同一约定：用户要 GenBank 却拿到 FASTA，
    且日志里一个字都没有，属于本项目招牌规则「永不静默」明令禁止的情形。
    """
    a = _write(tmp_path, "a.fa", FASTA_A)
    records = list(read_fasta(a))
    with pytest.raises(SeqToolkitError):
        split_records(records, str(tmp_path / "split"), output_format=bad_format)
    assert not (tmp_path / "split").exists()


def test_rename_disk_files_rejects_unknown_naming_mode(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    with pytest.raises(SeqToolkitError):
        rename_disk_files([a], naming_mode="species_v2", dry_run=False)
    assert Path(a).exists()


def test_split_records_continues_after_single_record_write_failure(tmp_path,
                                                                   monkeypatch):
    """单条记录写出失败不得中断整批，且写了一半的文件必须清掉。

    半截文件若留在磁盘上，既不在 records_out 计数内，又会被下游当成一条完整序列读走。
    """
    from seq_toolkit import pipeline as pipeline_module

    a = _write(tmp_path, "a.fa", FASTA_A + FASTA_B)
    records = list(read_fasta(a))
    real_write_fasta = pipeline_module.write_fasta
    attempts: list[str] = []

    def flaky_write_fasta(recs, path, name_map=None, wrap=0):
        attempts.append(path)
        if len(attempts) == 1:
            # 模拟磁盘写满：先落下一段半截内容，再抛错
            Path(path).write_text(">ON1.1_Salsola_pellucida\nACGT", encoding="utf-8")
            raise OSError("模拟磁盘写入失败")
        return real_write_fasta(recs, path, name_map, wrap=wrap)

    monkeypatch.setattr(pipeline_module, "write_fasta", flaky_write_fasta)
    out_dir = tmp_path / "split"
    log = RunLog()
    result = split_records(records, str(out_dir), log=log)

    assert result.records_out == 1
    assert [p.name for p in out_dir.iterdir()] == ["MF2.1_Kochia_scoparia.fasta"]
    assert any(entry.level == "ERROR" for entry in log.entries)


# ---------------------------------------------------------------------------
# Task 13 修复轮：RenamePlan.conflicts 的语义与 keep 分支的参数校验
# ---------------------------------------------------------------------------


def test_rename_disk_files_conflicts_are_files_forced_to_a_numbered_name(tmp_path):
    """conflicts 记的是「被迫让位到 _1 的那个文件自己」，不是占用名字的文件。

    两种解释（记改名方 / 记被让位方）都能通过旧测试的 len(...) == 1，因此这里把
    语义钉到具体条目与具体内容上：只有「改名方」这一种解释能同时满足
    (原路径 == b)、(新路径以 _1 结尾)、(该路径下的内容确实是 b 的内容)。
    """
    a = _write(tmp_path, "messy_a.fa", FASTA_A)
    b = _write(tmp_path, "messy_b.fa",
               ">ON1.1 Salsola pellucida chloroplast, complete genome\nAAAACCCC\n")
    plan = rename_disk_files([a, b], dry_run=False)

    assert plan.conflicts == [
        (b, str(tmp_path / "ON1.1_Salsola_pellucida_1.fa"))]
    old, new = plan.conflicts[0]
    assert Path(new).name.endswith("_1.fa")
    # 实际新路径必须真的是「被迫让位」那个文件的落点：内容随 b 走，不随 a 走
    assert Path(new).read_text(encoding="utf-8").endswith("AAAACCCC\n")
    # 该条目同时也在 pairs 里（这一次没有中途失败），且与 pairs 指向同一落点
    assert (old, new) in plan.pairs


def test_rename_disk_files_conflicts_empty_when_no_collision(tmp_path):
    """普通改名不进 conflicts——它记的是命名冲突，不是「处理过的文件」。"""
    a = _write(tmp_path, "乱名.fa", FASTA_A)
    plan = rename_disk_files([a], dry_run=False)

    assert len(plan.pairs) == 1
    assert plan.conflicts == []


def test_rename_disk_files_midway_failure_is_in_conflicts_but_not_pairs(
        tmp_path, monkeypatch):
    """重命名中途失败的文件只出现在 conflicts 与日志，绝不出现在 pairs。

    本实现口径（写死在 RenamePlan docstring 里）：失败文件记 ERROR 日志并跳过、
    不进 pairs；若它同时是个冲突文件，条目已经在 conflicts 里了。因此
    「conflicts ⊆ pairs」**不成立**——调用方不得用 len(pairs) - len(conflicts) 做算术。
    """
    # 已占用目标名的文件（不在输入列表里，只是占位）
    _write(tmp_path, "ON1.1_Salsola_pellucida.fa", FASTA_B)
    messy = _write(tmp_path, "乱名.fa", FASTA_A)

    def failing_rename(self, target):
        raise OSError("模拟重命名失败")

    monkeypatch.setattr(Path, "rename", failing_rename)
    log = RunLog()
    plan = rename_disk_files([messy], dry_run=False, log=log)

    conflict = (messy, str(tmp_path / "ON1.1_Salsola_pellucida_1.fa"))
    assert plan.conflicts == [conflict]
    assert plan.pairs == []
    assert plan.renamed == 0
    # 显式排除那个「看起来成立其实不成立」的关系
    assert not set(plan.conflicts) <= set(plan.pairs)
    # 文件原封不动，且失败只记在日志里
    assert Path(messy).read_text(encoding="utf-8") == FASTA_A
    assert any(entry.level == "ERROR" and "重命名失败" in entry.message
               for entry in log.entries)


def test_rename_disk_files_keep_mode_still_validates_input_format(tmp_path):
    """keep 短路不得跳过参数校验。

    短路原先在 input_format 校验之前，非法枚举会被静默接受，与该函数自身的校验
    契约（以及与 ProcessPlan.__post_init__ 的同一约定）相悖。
    """
    a = _write(tmp_path, "a.fa", FASTA_A)
    with pytest.raises(SeqToolkitError):
        rename_disk_files([a], naming_mode="keep", input_format="bogus")
    assert Path(a).exists()


def test_rename_disk_files_keep_mode_still_returns_empty_plan(tmp_path):
    """校验前置不能改变 keep 的正常行为。"""
    a = _write(tmp_path, "乱名.fa", FASTA_A)
    plan = rename_disk_files([a], naming_mode="keep", dry_run=False,
                             input_format="fasta")
    assert plan.pairs == []
    assert plan.conflicts == []
    assert plan.renamed == 0
    assert Path(a).exists()


# ---------------------------------------------------------------------------
# 修复轮：拆分去重（同一批里的同一条序列不得被写成两个文件）
# ---------------------------------------------------------------------------

# 与 FASTA_A 同登录号、不同序列：用来证明"保留首次出现者"
FASTA_A_REPEAT = (">ON1.1 Salsola pellucida chloroplast, complete genome\n"
                  "TTTTGGGG\n")


def test_split_records_deduplicates_the_same_accession_within_one_batch(tmp_path):
    """同一批里出现两条同登录号记录时只写 1 个文件，并交代丢弃的那一条。

    GUI 允许把同一个文件添加两次，也允许改写产物落在输入文件夹内——两种操作都会让
    同一批 records 里出现两条同登录号记录。旧实现完全没有去重，只能靠"目标文件已存在
    就加 _1"收场，于是同一条序列被写成 ON1.1_Salsola_pellucida.fasta 与
    ON1.1_Salsola_pellucida_1.fasta 两个文件，用户看到"一条序列变成了两条"。
    """
    a = _write(tmp_path, "a.fa", FASTA_A)
    b = _write(tmp_path, "b.fa", FASTA_A_REPEAT)
    out_dir = tmp_path / "split"
    log = RunLog()

    result = split_records(list(read_fasta(a)) + list(read_fasta(b)), str(out_dir),
                           log=log)

    # 文件名里也不得出现流水号空洞：去重必须在 build_name_map 之前完成，
    # 否则这两条同登录号同物种的记录会被算成"同物种 2 条"而拿到 _1/_2。
    assert sorted(p.name for p in out_dir.iterdir()) == [
        "ON1.1_Salsola_pellucida.fasta"]
    assert result.records_in == 2
    assert result.records_out == 1
    assert result.duplicates_removed == 1
    # 保留首次出现者：留下的是 a 的序列
    assert (out_dir / "ON1.1_Salsola_pellucida.fasta").read_text(
        encoding="utf-8").endswith("ACGTACGT\n")
    # 「永不静默」：两个来源文件路径都要写进日志，用户才知道丢掉的是哪一份
    infos = [entry.message for entry in log.entries if entry.level == "INFO"]
    assert any("ON1.1" in message and a in message and b in message
               for message in infos)


def test_split_records_serials_two_records_rendering_the_same_target_name(tmp_path):
    """本批内渲染出同一基名的两条记录：新判据给它们发流水号，两条都写出、都不丢。

    **这个用例的期望值因用户使用后提出的调整而改变，改前请读完这段历史。**

    旧断言是「只写 ON1.1.fasta 一个文件，第二条记录收 WARN + 进异常清单」。它建立在旧的
    流水号判据上：旧判据按**物种**计数，而 ON/1.1（Kochia scoparia）与 ON1.1
    （Salsola pellucida）物种不同 ⇒ 不发号 ⇒ 两条记录渲染出同一个 ON1.1.fasta，只能靠
    split_records 的"本批内重名就跳过该条"防线收场——代价是丢掉一条序列。

    新判据是"渲染出的基名是否会撞车"。这里基名确实撞了（``sanitize_accession("ON/1.1")``
    == ``"ON1.1"``），于是两条分别拿到 ``ON1.1_1`` / ``ON1.1_2``，目标文件名不再重复，
    两条记录都能落盘，比"少写一条、只留在异常清单里"更符合「永不静默丢数据」。

    split_records 里那道"本批内重名"防线**仍然保留**（keep 模式与 name_map 未命中时的
    兜底路径依旧可能撞名），只是在本场景下不再触发。
    """
    a = _write(tmp_path, "a.fa", FASTA_A)
    b = _write(tmp_path, "b.fa",
               ">ON/1.1 Kochia scoparia chloroplast, complete genome\n"
               "TTTTGGGG\n")
    out_dir = tmp_path / "split"
    log = RunLog()

    result = split_records(list(read_fasta(a)) + list(read_fasta(b)), str(out_dir),
                           naming_mode="accession", log=log)

    assert sorted(p.name for p in out_dir.iterdir()) == ["ON1.1_1.fasta",
                                                         "ON1.1_2.fasta"]
    assert result.records_out == 2
    # 两条记录各自完整落盘，没有互相覆盖、也没有谁被静默丢掉
    bodies = sorted(path.read_text(encoding="utf-8").split("\n", 1)[1].strip()
                    for path in out_dir.iterdir())
    assert bodies == ["ACGTACGT", "TTTTGGGG"]
    assert len(log.exceptions) == 0
    assert not any(entry.level == "WARN" and "重名" in entry.message
                   for entry in log.entries)


def test_split_records_still_avoids_overwriting_a_file_left_on_disk(tmp_path):
    """磁盘上先前就存在的同名文件仍然让位到 _1 并告警：绝不覆盖，这条不能回归。

    这与"本批内重名"是两件不同的事：那个文件是磁盘上上一次运行的产物，该让位；
    本批内第二条记录想要同一个名字，才该判重。
    """
    a = _write(tmp_path, "a.fa", FASTA_A)
    out_dir = tmp_path / "split"
    out_dir.mkdir()
    (out_dir / "ON1.1_Salsola_pellucida.fasta").write_text("上一次的产物",
                                                           encoding="utf-8")
    log = RunLog()

    result = split_records(list(read_fasta(a)), str(out_dir), log=log)

    assert (out_dir / "ON1.1_Salsola_pellucida.fasta").read_text(
        encoding="utf-8") == "上一次的产物"
    assert (out_dir / "ON1.1_Salsola_pellucida_1.fasta").exists()
    assert result.records_out == 1
    assert result.duplicates_removed == 0
    assert any(entry.level == "WARN" and "目标文件已存在" in entry.message
               for entry in log.entries)


def test_split_records_keeps_every_record_that_has_no_accession(tmp_path):
    """没有登录号的记录不得被当成"重复"合并：它们之间没有任何共同的登录号。"""
    a = _write(tmp_path, "a.fa", ">\nAAAA\n>\nCCCC\n")
    out_dir = tmp_path / "split"

    result = split_records(list(read_fasta(a)), str(out_dir))

    assert sorted(p.name for p in out_dir.iterdir()) == [
        "sequence_1.fasta", "sequence_2.fasta"]
    assert result.records_out == 2
    assert result.duplicates_removed == 0


# ---------------------------------------------------------------------------
# Task 13 修复轮 2：目标已存在且内容相同时跳过，不再让位加 _1
# ---------------------------------------------------------------------------


def test_split_records_skips_a_target_that_already_holds_identical_bytes(tmp_path):
    """同一批记录连拆两次到同一目录：第二次不得产生内容完全相同的 _1 孪生文件。

    这正是用户报告的原始现象（场景 B：拆分输出目录在输入文件夹内，再跑一次）：
    第二次运行时目标名在磁盘上已存在，旧实现无条件让位到 ON1.1_Salsola_pellucida_1.fasta，
    于是用户看到 ON1.1_Salsola_pellucida.fasta 与 ..._1.fasta **内容完全相同**——
    "同一条序列还是变成了两个文件"。

    同名且逐字节相同 ⇒ 跳过不丢任何信息，因此不加后缀；但必须记 INFO 说明跳过原因，
    且**不得**出现那条"目标文件已存在 ⇒ 让位"的 WARN（那是内容不同时的语义）。
    """
    a = _write(tmp_path, "a.fa", FASTA_A)
    out_dir = tmp_path / "split"
    first_log = RunLog()

    first = split_records(list(read_fasta(a)), str(out_dir), log=first_log)
    assert first.records_out == 1
    product = out_dir / "ON1.1_Salsola_pellucida.fasta"
    written_bytes = product.read_bytes()

    second_log = RunLog()
    second = split_records(list(read_fasta(a)), str(out_dir), log=second_log)

    assert sorted(p.name for p in out_dir.iterdir()) == [
        "ON1.1_Salsola_pellucida.fasta"], "第二次运行多写了文件"
    assert product.read_bytes() == written_bytes, "已存在的产物被改写了"
    # 该记录的产物就在目标名上且内容正确，报数时按"已有产物"计入：GUI 摘要里
    # 「拆分出 N 个文件」必须与 out_dir 里属于这批记录的产物数一致，不能报 0。
    assert second.records_out == 1
    assert second.duplicates_removed == 0
    infos = [entry.message for entry in second_log.entries if entry.level == "INFO"]
    assert any("内容相同" in message for message in infos), \
        "跳过必须留下说明，否则就是静默地少写了一个文件"
    assert not any(entry.level == "WARN" and "目标文件已存在" in entry.message
                   for entry in second_log.entries), \
        "内容相同不该走「让位加 _1」那条分支"
    assert not second_log.exceptions, "内容相同是预期结果，不该进人工复核清单"


def test_split_records_yields_to_a_numbered_name_when_the_existing_target_differs(
        tmp_path):
    """同名但内容不同的产物仍然让位到 _1 并告警：绝不静默覆盖，这条不能回归。

    与上一条用例只差"磁盘上那个文件的字节"：内容相同 ⇒ 跳过；内容不同 ⇒ 让位。
    这条是那道分界线的守护测试，也是"输出永不静默覆盖"的底线。
    """
    a = _write(tmp_path, "a.fa", FASTA_A)
    out_dir = tmp_path / "split"
    out_dir.mkdir()
    product = out_dir / "ON1.1_Salsola_pellucida.fasta"
    previous = ">ON1.1 Salsola pellucida 上一次的产物\nTTTTTTTT\n"
    product.write_text(previous, encoding="utf-8")
    log = RunLog()

    result = split_records(list(read_fasta(a)), str(out_dir), log=log)

    assert product.read_text(encoding="utf-8") == previous, "磁盘上的旧产物被覆盖了"
    assert sorted(p.name for p in out_dir.iterdir()) == [
        "ON1.1_Salsola_pellucida.fasta", "ON1.1_Salsola_pellucida_1.fasta"]
    assert result.records_out == 1
    assert any(entry.level == "WARN" and "目标文件已存在" in entry.message
               for entry in log.entries)


# ---------------------------------------------------------------------------
# 用户使用后新增：每个输入文件各输出一个文件（convert_each_file）
#
# 用户原话：「genbank 文件转 fasta 文件的时候，无论如何输出的只有一个合并的 fasta
# 文件，请增加批量将 genbank 文件分别转化为 fasta 文件的功能」。
# 与之配套的两项确认：输出文件名沿用原文件主干只换后缀；文件内序列名套用「命名规则」。
# ---------------------------------------------------------------------------

# 登录号必须是合法的 INSDC 形式（ON929859），否则 model 会额外产生一条
# "accession 格式可疑" 的硬警告，把用例的意图搅浑。
GENBANK_LEGAL_A = (
    "LOCUS       ON929859.1              8 bp    DNA     linear   PLN 01-JAN-2020\n"
    "DEFINITION  Salsola pellucida chloroplast, complete genome.\n"
    "ACCESSION   ON929859\n"
    "VERSION     ON929859.1\n"
    "  ORGANISM  Salsola pellucida\n"
    "            Eukaryota; Amaranthaceae; Salsola.\n"
    "ORIGIN\n"
    "        1 acgtacgt\n"
    "//\n"
)
GENBANK_LEGAL_B = (
    "LOCUS       MF230595.1              8 bp    DNA     linear   PLN 01-JAN-2020\n"
    "DEFINITION  Kochia scoparia chloroplast, complete genome.\n"
    "ACCESSION   MF230595\n"
    "VERSION     MF230595.1\n"
    "  ORGANISM  Kochia scoparia\n"
    "            Eukaryota; Amaranthaceae; Kochia.\n"
    "ORIGIN\n"
    "        1 ttttgggg\n"
    "//\n"
)
# 与 A 同物种、不同登录号：用来验证「流水号的作用域只在单个文件内」——
# 两个文件各放一条，谁都不该给对方发号。
GENBANK_LEGAL_A2 = (
    "LOCUS       ON929860.1              8 bp    DNA     linear   PLN 01-JAN-2020\n"
    "DEFINITION  Salsola pellucida isolate 2 chloroplast, complete genome.\n"
    "ACCESSION   ON929860\n"
    "VERSION     ON929860.1\n"
    "  ORGANISM  Salsola pellucida\n"
    "            Eukaryota; Amaranthaceae; Salsola.\n"
    "ORIGIN\n"
    "        1 ggggtttt\n"
    "//\n"
)
# 只有 CONTIG 的记录（未组装）：read_genbank 经 on_skip 上报后跳过，产出 0 条序列。
GENBANK_CONTIG_ONLY = (
    "LOCUS       ON929859.1             500 bp    DNA     linear   PLN 01-JAN-2020\n"
    "DEFINITION  Salsola pellucida chloroplast, complete genome.\n"
    "ACCESSION   ON929859\n"
    "VERSION     ON929859.1\n"
    "  ORGANISM  Salsola pellucida\n"
    "CONTIG      join(AAAA01000001.1:1..500)\n"
    "//\n"
)


def _convert_plan(tmp_path, inputs, out_dir=None, **overrides):
    options = dict(
        inputs=inputs,
        # 刻意用 out_dir 而不是 output_path：批量模式下产物是一批文件，
        # 沿用「单个输出文件」的字段名会让调用方误以为还是一次写一个文件。
        out_dir=str(out_dir if out_dir is not None else tmp_path / "输出目录"),
        output_format="fasta",
        input_format="auto",
        naming_mode="keep",
        dedup="none",
        recursive=True,
        wrap=0,
        log=RunLog(),
    )
    options.update(overrides)
    return ConvertPlan(**options)


def test_convert_each_file_writes_one_output_per_input_file(tmp_path):
    """2 个 GenBank 文件 ⇒ 输出目录里恰好 2 个 .fasta，文件名是各自原文件的主干。

    其中一个是 .gb.gz 双后缀：主干必须去掉「格式后缀 + .gz」两层，
    绝不能用裸 Path.stem（那会得到「样本.gbk.fasta」）。中文目录与中文文件名同批验证。
    """
    import gzip

    plain = _write(tmp_path, "甲.gbk", GENBANK_LEGAL_A)
    packed = tmp_path / "样本.gbk.gz"
    with gzip.open(str(packed), "wt", encoding="utf-8") as handle:
        handle.write(GENBANK_LEGAL_B)

    out_dir = tmp_path / "中文 输出目录"
    result = convert_each_file(_convert_plan(tmp_path, [plain, str(packed)],
                                             out_dir=out_dir))

    assert sorted(p.name for p in out_dir.iterdir()) == ["样本.fasta", "甲.fasta"]
    assert ">ON929859.1" in (out_dir / "甲.fasta").read_text(encoding="utf-8")
    assert ">MF230595.1" in (out_dir / "样本.fasta").read_text(encoding="utf-8")
    assert result.records_out == 2          # records_out 数的是写出的文件数
    assert result.records_in == 2
    assert result.skipped_files == []
    # 批量模式没有"那一个输出文件"：output_path 填的是输出目录本身。
    assert result.output_path == str(out_dir)


def test_convert_each_file_keeps_one_files_records_together(tmp_path):
    """多记录文件只产出 1 个输出文件，内含全部记录（不是按记录拆）。"""
    both = _write(tmp_path, "双记录.gbk", GENBANK_LEGAL_A + GENBANK_LEGAL_B)
    out_dir = tmp_path / "out"
    result = convert_each_file(_convert_plan(tmp_path, [both], out_dir=out_dir))

    assert result.records_out == 1
    assert result.records_in == 2
    assert sorted(p.name for p in out_dir.iterdir()) == ["双记录.fasta"]
    text = (out_dir / "双记录.fasta").read_text(encoding="utf-8")
    assert ">ON929859.1" in text and ">MF230595.1" in text


def test_convert_each_file_applies_naming_mode_to_each_file(tmp_path):
    """文件内序列名套用本页「命名规则」：accession_species ⇒ >登录号_物种名。"""
    a = _write(tmp_path, "样本甲.gbk", GENBANK_LEGAL_A)
    out_dir = tmp_path / "out"
    convert_each_file(_convert_plan(tmp_path, [a], out_dir=out_dir,
                                    naming_mode="accession_species"))

    assert (out_dir / "样本甲.fasta").read_text(encoding="utf-8").startswith(
        ">ON929859.1_Salsola_pellucida\n")


def test_convert_each_file_dedups_inside_a_single_file_only(tmp_path):
    """去重的作用域是单个文件：同一登录号在两个文件里各写一份，互不牵连。"""
    twice = _write(tmp_path, "重复.gbk", GENBANK_LEGAL_A + GENBANK_LEGAL_A)
    other = _write(tmp_path, "另一份.gbk", GENBANK_LEGAL_A)
    out_dir = tmp_path / "out"
    log = RunLog()
    result = convert_each_file(_convert_plan(tmp_path, [twice, other],
                                             out_dir=out_dir, dedup="accession",
                                             log=log))

    assert result.duplicates_removed == 1        # 只有同一个文件内的那条被去掉
    assert result.records_out == 2
    assert sorted(p.name for p in out_dir.iterdir()) == ["另一份.fasta", "重复.fasta"]
    assert (out_dir / "重复.fasta").read_text(encoding="utf-8").count(">") == 1
    assert (out_dir / "另一份.fasta").read_text(encoding="utf-8").count(">") == 1
    assert any("本文件内" in entry.message for entry in log.entries), \
        "按文件转换时的去重作用域必须写在日志里，否则用户以为整批一起去重了"


def test_convert_each_file_skips_file_without_usable_records(tmp_path):
    """只有 CONTIG 记录的文件：不产出空文件，记 WARN，计入 skipped_files。"""
    contig = _write(tmp_path, "未组装.gbk", GENBANK_CONTIG_ONLY)
    good = _write(tmp_path, "好的.gbk", GENBANK_LEGAL_A)
    out_dir = tmp_path / "out"
    log = RunLog()
    result = convert_each_file(_convert_plan(tmp_path, [contig, good],
                                             out_dir=out_dir, log=log))

    assert sorted(p.name for p in out_dir.iterdir()) == ["好的.fasta"]
    assert contig in result.skipped_files
    assert any(entry.level == "WARN" and "没有可用记录" in entry.message
               for entry in log.entries)
    assert not (out_dir / "未组装.fasta").exists(), "跳过的文件不得留下空产物"


def test_convert_each_file_skips_unknown_format_and_continues(tmp_path):
    junk = _write(tmp_path, "说明.txt", "hello\n")
    good = _write(tmp_path, "好的.gbk", GENBANK_LEGAL_A)
    out_dir = tmp_path / "out"
    log = RunLog()
    result = convert_each_file(_convert_plan(tmp_path, [junk, good],
                                             out_dir=out_dir, log=log))

    assert junk in result.skipped_files
    assert sorted(p.name for p in out_dir.iterdir()) == ["好的.fasta"]
    assert any("无法识别" in entry.message for entry in log.entries)


def test_convert_each_file_continues_after_a_single_file_failure(tmp_path):
    """单个文件读不动（截断的 .gz 抛 EOFError/zlib.error，都不是 OSError 子类）不得中断整批。"""
    import gzip

    broken = tmp_path / "坏的.gbk.gz"
    raw = gzip.compress(GENBANK_LEGAL_B.encode("utf-8"))
    broken.write_bytes(raw[:len(raw) // 2])
    good = _write(tmp_path, "好的.gbk", GENBANK_LEGAL_A)
    out_dir = tmp_path / "out"
    log = RunLog()
    result = convert_each_file(_convert_plan(tmp_path, [str(broken), good],
                                             out_dir=out_dir, log=log))

    assert sorted(p.name for p in out_dir.iterdir()) == ["好的.fasta"]
    assert str(broken) in result.skipped_files
    assert any(entry.level == "ERROR" for entry in log.entries)


def test_convert_each_file_skips_identical_target_and_yields_to_different_one(tmp_path):
    """绝不静默覆盖：目标同名且同字节 ⇒ 跳过不加 _1；内容不同 ⇒ 让位 _1。

    第一次运行 → 第二次运行（同名同内容，不得多出 _1 孪生文件）→ 篡改磁盘上那份内容
    后再运行（必须让位到 _1，旧产物一个字节都不许动）。这是"绝不覆盖"的回归保护。
    """
    source = _write(tmp_path, "样本.gbk", GENBANK_LEGAL_A)
    out_dir = tmp_path / "out"

    first = convert_each_file(_convert_plan(tmp_path, [source], out_dir=out_dir))
    assert first.records_out == 1
    product = out_dir / "样本.fasta"
    written = product.read_bytes()

    second_log = RunLog()
    second = convert_each_file(_convert_plan(tmp_path, [source], out_dir=out_dir,
                                             log=second_log))
    assert sorted(p.name for p in out_dir.iterdir()) == ["样本.fasta"], \
        "同名同内容时多写了一个 _1 孪生文件"
    assert product.read_bytes() == written
    assert second.records_out == 1              # 产物就在目标名上且内容正确
    assert any("内容相同" in entry.message for entry in second_log.entries)
    assert not any(entry.level == "WARN" and "目标文件已存在" in entry.message
                   for entry in second_log.entries)

    product.write_text(">ON929859.1 上一次的手工产物\nTTTTTTTT\n", encoding="utf-8")
    previous = product.read_text(encoding="utf-8")
    third_log = RunLog()
    third = convert_each_file(_convert_plan(tmp_path, [source], out_dir=out_dir,
                                            log=third_log))

    assert product.read_text(encoding="utf-8") == previous, "磁盘上的旧产物被覆盖了"
    assert sorted(p.name for p in out_dir.iterdir()) == ["样本.fasta", "样本_1.fasta"]
    assert third.records_out == 1
    assert any(entry.level == "WARN" and "目标文件已存在" in entry.message
               for entry in third_log.entries)


def test_convert_each_file_derives_stem_from_explicit_file_with_unknown_suffix(tmp_path):
    """显式给出的文件后缀不在后缀表内（按内容识别）：主干仍要只去掉一层扩展名。"""
    source = _write(tmp_path, "样本数据.custom", GENBANK_LEGAL_A)
    out_dir = tmp_path / "out"
    convert_each_file(_convert_plan(tmp_path, [source], out_dir=out_dir))

    assert sorted(p.name for p in out_dir.iterdir()) == ["样本数据.fasta"]


def test_convert_each_file_reports_missing_species_in_review_list(tmp_path):
    """文件内写不出名字的序列同样要进人工复核清单，且「最终采用的名称」非空。"""
    source = _write(tmp_path, "无物种.fa", ">ON929859.1 chloroplast, complete genome\nACGT\n")
    log = RunLog()
    convert_each_file(_convert_plan(tmp_path, [source], out_dir=tmp_path / "out",
                                    naming_mode="species", log=log))

    assert log.exception_count() >= 1
    entry = [e for e in log.exceptions if "物种名" in e.reason][0]
    assert entry.final_name == "ON929859.1"


def test_convert_each_file_serials_two_records_of_one_species_inside_a_file(tmp_path):
    """核心新语义之一：流水号在**单个文件内**发号。

    同一文件里 2 条同物种记录 + species 模式 ⇒ 两个基名完全相同 ⇒ 必须有流水号，
    且是 1、2（不是 0、1，也不是只发一条）。
    """
    both = _write(tmp_path, "同物种两条.gbk", GENBANK_LEGAL_A + GENBANK_LEGAL_A2)
    out_dir = tmp_path / "out"
    convert_each_file(_convert_plan(tmp_path, [both], out_dir=out_dir,
                                    naming_mode="species"))

    text = (out_dir / "同物种两条.fasta").read_text(encoding="utf-8")
    assert [line for line in text.splitlines() if line.startswith(">")] == [
        ">Salsola_pellucida_1", ">Salsola_pellucida_2"]


def test_convert_each_file_serials_do_not_leak_across_files(tmp_path):
    """核心新语义之二：流水号的作用域**不跨文件**。

    两个文件各含 1 条同物种记录 ⇒ 两个产物里的序列名各自都是不带后缀的
    ``Salsola_pellucida``。本用例是「把 build_name_map 挪到循环外、对整批记录建
    一次表」这种退化的唯一探针：一旦挪出去，第二个文件会拿到 ``_2``，这里立刻失败。
    """
    first = _write(tmp_path, "甲.gbk", GENBANK_LEGAL_A)
    second = _write(tmp_path, "乙.gbk", GENBANK_LEGAL_A2)
    out_dir = tmp_path / "out"
    convert_each_file(_convert_plan(tmp_path, [first, second], out_dir=out_dir,
                                    naming_mode="species"))

    assert [line for line in (out_dir / "甲.fasta").read_text(encoding="utf-8").splitlines()
            if line.startswith(">")] == [">Salsola_pellucida"]
    assert [line for line in (out_dir / "乙.fasta").read_text(encoding="utf-8").splitlines()
            if line.startswith(">")] == [">Salsola_pellucida"], \
        "编号跨文件泄漏了：build_name_map 的作用域必须限单个输入文件"


def test_convert_each_file_target_name_occupied_by_a_directory(tmp_path):
    """目标名被**同名目录**占用：不中断整批，其余文件照常转换，本文件让位到 _1。

    目录里可能躺着用户自己的东西，所以既不删也不覆盖，走与「同名文件但内容不同」
    相同的让位策略；日志必须点明是「目录占用」，不能沿用「内容不同」——目录没有
    内容可比，那句话是假的。
    """
    source = _write(tmp_path, "样本.gbk", GENBANK_LEGAL_A)
    good = _write(tmp_path, "好的.gbk", GENBANK_LEGAL_B)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    occupied = out_dir / "样本.fasta"
    occupied.mkdir()
    inside = occupied / "用户自己的文件.txt"
    inside.write_text("别动我", encoding="utf-8")

    log = RunLog()
    result = convert_each_file(_convert_plan(tmp_path, [source, good],
                                             out_dir=out_dir, log=log))

    # 整批没被中断：两个输入文件都产出了（目录占名的那个让位到 _1）
    assert result.records_out == 2
    assert source not in result.skipped_files
    assert sorted(p.name for p in out_dir.iterdir()) == [
        "好的.fasta", "样本.fasta", "样本_1.fasta"]
    assert occupied.is_dir(), "同名目录被删/被换成了文件"
    assert inside.read_text(encoding="utf-8") == "别动我", "目录里的文件被动了"
    assert any(entry.level == "WARN" and "目录" in entry.message
               for entry in log.entries)
    assert not any("内容不同" in entry.message for entry in log.entries), \
        "目标是个目录，根本没有内容可比，不能沿用「内容不同」这句不实的话"


def test_convert_each_file_empty_input_raises(tmp_path):
    with pytest.raises(SeqToolkitError):
        convert_each_file(_convert_plan(tmp_path, []))


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("output_format", "gb"),
        ("input_format", "genbank2"),
        ("naming_mode", "species_v2"),
        ("dedup", "all"),
    ],
)
def test_invalid_convert_plan_enum_is_rejected_at_construction(tmp_path, field,
                                                               bad_value):
    """与 ProcessPlan.__post_init__ 同一约定：构造期校验，抛 SeqToolkitError。

    ValueError 不在 GUI 的捕获集内，会让界面直接崩，所以必须是本项目自己的异常类型。
    """
    with pytest.raises(SeqToolkitError) as info:
        _convert_plan(tmp_path, ["a.gbk"], **{field: bad_value})
    assert not isinstance(info.value, ValueError)
    assert bad_value in str(info.value)


@pytest.mark.parametrize(
    "field,good_value",
    [
        ("output_format", "fasta"),
        ("output_format", "genbank"),
        ("input_format", "auto"),
        ("naming_mode", "accession_species"),
        ("dedup", "accession"),
    ],
)
def test_legal_convert_plan_enum_values_are_accepted(tmp_path, field, good_value):
    _convert_plan(tmp_path, ["a.gbk"], **{field: good_value})


def test_convert_each_file_progress_is_reported_by_file_count(tmp_path):
    a = _write(tmp_path, "甲.gbk", GENBANK_LEGAL_A)
    b = _write(tmp_path, "乙.gbk", GENBANK_LEGAL_B)
    seen: list[tuple[int, int, str]] = []
    convert_each_file(_convert_plan(tmp_path, [a, b], out_dir=tmp_path / "out",
                                    progress=lambda d, t, m: seen.append((d, t, m))))

    assert seen
    assert seen[-1][0] == seen[-1][1] == 2
    assert all(total == 2 for _done, total, _text in seen)


def test_convert_each_file_honours_cancellation(tmp_path):
    a = _write(tmp_path, "甲.gbk", GENBANK_LEGAL_A)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(OperationCancelled):
        convert_each_file(_convert_plan(tmp_path, [a], out_dir=tmp_path / "out",
                                        cancel=cancel))
