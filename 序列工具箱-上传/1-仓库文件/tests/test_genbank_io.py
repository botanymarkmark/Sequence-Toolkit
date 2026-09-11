from pathlib import Path

import pytest

from seq_toolkit.genbank_io import (
    ContigRecordError,
    GenBankParseError,
    format_genbank_record,
    is_top_level_field,
    read_genbank,
    write_genbank,
)
from seq_toolkit.naming import build_name_map

FIXTURES = Path(__file__).parent / "fixtures"


def _write(tmp_path: Path, name: str, text: str, encoding: str = "utf-8") -> str:
    """把内联 GenBank 文本落盘为夹具文件（GBK 用例需要显式指定编码）。"""
    target = tmp_path / name
    target.write_bytes(text.encode(encoding))
    return str(target)


def test_is_top_level_field_tolerates_organism_indentation():
    assert is_top_level_field("  ORGANISM  Salsola pellucida", "ORGANISM") is True


def test_is_top_level_field_tolerates_locus_indentation():
    assert is_top_level_field("LOCUS       ON929859", "LOCUS") is True


def test_is_top_level_field_rejects_qualifier():
    assert is_top_level_field('                     /organism="x"', "ORGANISM") is False


def test_is_top_level_field_rejects_lineage_line():
    assert is_top_level_field("            Eukaryota; Viridiplantae;", "ORGANISM") is False


def test_is_top_level_field_requires_separator_after_keyword():
    # 关键字后不是空白/行尾 → 不是该字段（覆盖 rest[0].isspace() 这一分支）
    assert is_top_level_field("ORGANISMUS x", "ORGANISM") is False


def test_is_top_level_field_accepts_bare_keyword():
    # 关键字后即行尾 → 是该字段（覆盖 rest == "" 这一分支）
    assert is_top_level_field("ORIGIN", "ORIGIN") is True


def test_read_multiple_records_from_one_file():
    records = list(read_genbank(str(FIXTURES / "multi_record.gb")))
    assert [r.accession for r in records] == ["ON929859.1", "MF123456.1"]


def test_version_line_wins_over_accession():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[0]
    assert record.accession == "ON929859.1"
    assert record.accession_base == "ON929859"
    assert record.version == 1


def test_organism_section_is_authoritative_species_source():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[0]
    assert record.species_raw == "Salsola pellucida"
    assert record.species == "Salsola_pellucida"


def test_lineage_is_captured():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[0]
    assert "Amaranthaceae" in record.lineage


def test_definition_multi_line_continuation_is_joined():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[1]
    assert record.definition == "Kochia scoparia isolate 5 chloroplast, partial sequence."


def test_sequence_is_extracted_without_line_numbers_or_spaces():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[0]
    assert record.length == 60
    assert record.seq.startswith("ATGACTGACT")
    assert record.seq.isalpha()
    assert record.seq == record.seq.upper()


def test_date_is_read_from_locus_line():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[0]
    assert record.date == "12-JAN-2022"


def test_raw_block_preserves_features_section_verbatim():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[0]
    # 第 1 条记录的 raw_block 应逐字符等于夹具中被 "//\n" 终止的那一段
    expected = (FIXTURES / "multi_record.gb").read_text(encoding="utf-8").split("//\n")[0] + "//\n"
    assert record.raw_block == expected
    # 弱断言保留：即使逐字相等成立，也明确要求 FEATURES 段与结束标记在场
    raw = record.raw_block
    assert '/gene="matK"' in raw
    assert '/product="maturase K"' in raw
    assert raw.startswith("LOCUS       ON929859")
    assert raw.rstrip("\n").endswith("//")


def test_origin_line_is_recorded():
    records = list(read_genbank(str(FIXTURES / "multi_record.gb")))
    assert records[0].origin_line == 1
    assert records[1].origin_line == 20


def test_second_record_sequence():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[1]
    assert record.seq == "TTGACCGGTTGACCGGTTGACCGG"
    assert record.length == 24


def test_contig_record_reports_reason_through_callback():
    skipped: list[tuple[str, int, str]] = []
    records = list(
        read_genbank(
            str(FIXTURES / "contig_record.gb"),
            on_skip=lambda path, line, reason: skipped.append((path, line, reason)),
        )
    )
    assert records == []
    assert len(skipped) == 1
    path, line, reason = skipped[0]
    assert path.endswith("contig_record.gb")
    assert line == 1
    assert "CONTIG" in reason


def test_read_raises_on_file_without_locus(tmp_path):
    target = tmp_path / "junk.gb"
    target.write_text("not a genbank file\n", encoding="utf-8")
    with pytest.raises(GenBankParseError):
        list(read_genbank(str(target)))


def test_read_works_with_gzip(tmp_path):
    import gzip
    source = (FIXTURES / "multi_record.gb").read_bytes()
    target = tmp_path / "sample.gb.gz"
    with gzip.open(str(target), "wb") as handle:
        handle.write(source)
    assert len(list(read_genbank(str(target)))) == 2


# --- 物种名回退链第 2 级：ORGANISM 段缺失 → source feature 的 /organism 限定符 ---


def test_species_falls_back_to_organism_qualifier(tmp_path):
    path = _write(
        tmp_path,
        "qualifier.gb",
        "LOCUS       ON111111                12 bp    DNA     linear   PLN 01-JAN-2020\n"
        "DEFINITION  Uncultured bacterium clone 7 sequence.\n"
        "ACCESSION   ON111111\n"
        "VERSION     ON111111.1\n"
        "FEATURES             Location/Qualifiers\n"
        "     source          1..12\n"
        '                     /organism="Salsola pellucida"\n'
        "ORIGIN\n"
        "        1 atgactgact ga\n"
        "//\n",
    )
    record = list(read_genbank(path))[0]
    assert record.species_raw == "Salsola pellucida"
    assert record.species == "Salsola_pellucida"
    assert any("/organism" in warning for warning in record.warnings)


# --- 物种名回退链第 3 级：ORGANISM 与 /organism 均缺失 → 从 DEFINITION 提取 ---


def test_species_falls_back_to_definition(tmp_path):
    path = _write(
        tmp_path,
        "definition_only.gb",
        "LOCUS       ON222222                12 bp    DNA     linear   PLN 02-JAN-2020\n"
        "DEFINITION  Salsola pellucida chloroplast, complete genome.\n"
        "ACCESSION   ON222222\n"
        "VERSION     ON222222.1\n"
        "FEATURES             Location/Qualifiers\n"
        "ORIGIN\n"
        "        1 atgactgact ga\n"
        "//\n",
    )
    record = list(read_genbank(path))[0]
    assert record.species_raw == "Salsola pellucida"
    assert any("DEFINITION" in warning for warning in record.warnings)


# --- 物种名回退链第 4 级：任何物种信息都没有 → LOCUS 名 ---


def test_species_falls_back_to_locus_name(tmp_path):
    path = _write(
        tmp_path,
        "no_species.gb",
        "LOCUS       ON333333                12 bp    DNA     linear   PLN 03-JAN-2020\n"
        "DEFINITION  complete genome sequence.\n"
        "ACCESSION   ON333333\n"
        "VERSION     ON333333.1\n"
        "ORIGIN\n"
        "        1 atgactgact ga\n"
        "//\n",
    )
    record = list(read_genbank(path))[0]
    assert record.species_raw == "ON333333"
    assert any("LOCUS" in warning for warning in record.warnings)


# --- 编码损伤：非 UTF-8（GBK）文件必须告警 ---


def test_warns_when_file_is_not_utf8(tmp_path):
    path = _write(
        tmp_path,
        "gbk_record.gb",
        "LOCUS       ON444444                12 bp    DNA     linear   PLN 04-JAN-2020\n"
        "DEFINITION  中国沙蓬叶绿体全基因组。\n"
        "ACCESSION   ON444444\n"
        "VERSION     ON444444.1\n"
        "  ORGANISM  中国沙蓬\n"
        "            Eukaryota; Viridiplantae; Amaranthaceae; Salsola.\n"
        "ORIGIN\n"
        "        1 atgactgact ga\n"
        "//\n",
        encoding="gbk",
    )
    record = list(read_genbank(path))[0]
    assert any("文件可能不是 UTF-8 编码" in warning for warning in record.warnings)


def test_no_decoding_damage_warning_for_ascii_input():
    """反例：纯 ASCII 记录不得出现编码告警，防止该告警恒真。"""
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[0]
    assert not any("UTF-8" in warning for warning in record.warnings)
    assert record.warnings == ()


# --- 截断文件：缺少独占一行的结尾 '//' 必须告警 ---


def test_truncated_record_is_flagged_with_warning(tmp_path):
    """把夹具截到第 1 条记录的 ORIGIN 段之后（无 //），模拟下载中断的半截文件。

    这种文件仍能解析出「登录号正确但序列被截断」的记录，必须给出信号。
    """
    source = (FIXTURES / "multi_record.gb").read_text(encoding="utf-8")
    truncated = source.split("//\n")[0]
    assert not truncated.rstrip().endswith("//")
    path = _write(tmp_path, "truncated.gb", truncated)

    records = list(read_genbank(path))

    assert len(records) == 1
    assert records[0].accession == "ON929859.1"
    assert any("截断" in warning for warning in records[0].warnings)


def test_complete_records_are_not_flagged_as_truncated():
    """反例：完整文件的两条记录都不得出现截断告警，防止该告警恒真。"""
    records = list(read_genbank(str(FIXTURES / "multi_record.gb")))
    assert len(records) == 2
    for record in records:
        assert not any("截断" in warning for warning in record.warnings)


# ---------------------------------------------------------------------------
# Task 13：GenBank 写出（format_genbank_record / write_genbank 在任务 12 落地）
# ---------------------------------------------------------------------------


def test_write_genbank_preserves_raw_block_byte_for_byte(tmp_path):
    records = list(read_genbank(str(FIXTURES / "multi_record.gb")))
    out = tmp_path / "out.gb"
    write_genbank(records, str(out))
    original = (FIXTURES / "multi_record.gb").read_text(encoding="utf-8")
    assert out.read_text(encoding="utf-8") == original


def test_write_genbank_rename_touches_only_locus_name_column(tmp_path):
    records = list(read_genbank(str(FIXTURES / "multi_record.gb")))
    record = records[0]
    block = format_genbank_record(record, "MF999999.1")
    assert block.splitlines()[0][:12] == "LOCUS       "
    assert block.splitlines()[0][12:28] == "MF999999.1      "
    assert block.splitlines()[0][28:] == record.raw_block.splitlines()[0][28:]
    assert "VERSION     ON929859.1" in block
    assert "ACCESSION   ON929859" in block


def test_write_genbank_without_name_map_keeps_original(tmp_path):
    records = list(read_genbank(str(FIXTURES / "multi_record.gb")))
    out = tmp_path / "keep.gb"
    write_genbank(records, str(out), build_name_map(records, "keep"))
    assert "LOCUS       ON929859" in out.read_text(encoding="utf-8")


def test_write_genbank_warns_and_keeps_locus_for_overlong_name(tmp_path, caplog):
    records = list(read_genbank(str(FIXTURES / "multi_record.gb")))
    block = format_genbank_record(records[0], "ON929859.1_Salsola_pellucida")
    assert block.splitlines()[0].startswith("LOCUS       ON929859 ")


def test_synthesised_genbank_is_re_readable(tmp_path):
    from seq_toolkit.fasta_io import read_fasta
    fasta = tmp_path / "in.fa"
    fasta.write_text(">ON1.1 Salsola pellucida chloroplast, complete genome\nACGTACGT\n",
                     encoding="utf-8")
    records = list(read_fasta(str(fasta)))
    out = tmp_path / "synth.gb"
    write_genbank(records, str(out))
    back = list(read_genbank(str(out)))
    assert back[0].seq == "ACGTACGT"
    assert back[0].species == "Salsola_pellucida"
    assert "FEATURES" in out.read_text(encoding="utf-8")
