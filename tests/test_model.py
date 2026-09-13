import dataclasses

import pytest

from seq_toolkit.model import (
    AccessionParts,
    SequenceRecord,
    SeqToolkitError,
    parse_accession,
)


def _rec(accession="ON929859.1", species="Salsola_pellucida", seq="ACGT", **overrides):
    parts = parse_accession(accession)
    data = dict(
        accession=parts.accession,
        accession_base=parts.base,
        version=parts.version,
        species=species,
        species_raw=species.replace("_", " "),
        lineage="",
        definition="",
        seq=seq,
        source_format="fasta",
        origin_path="memory.fa",
        origin_line=1,
    )
    data.update(overrides)
    return SequenceRecord(**data)


def test_parse_accession_simple_form_is_uppercased():
    parts = parse_accession("on929859.1")
    assert parts.accession == "ON929859.1"
    assert parts.base == "ON929859"
    assert parts.version == 1
    assert parts.well_formed is True


def test_parse_accession_refseq_underscore_form():
    parts = parse_accession("NC_027224.1")
    assert parts.base == "NC_027224"
    assert parts.version == 1
    assert parts.well_formed is True


def test_parse_accession_without_version():
    parts = parse_accession("ON929859")
    assert parts.accession == "ON929859"
    assert parts.version is None
    assert parts.well_formed is True


def test_parse_accession_multi_digit_version():
    parts = parse_accession("ON929859.12")
    assert parts.base == "ON929859"
    assert parts.version == 12
    assert parts.well_formed is True


def test_parse_accession_ill_formed_still_splits_version():
    parts = parse_accession("scaffold_12.3")
    assert parts.base == "SCAFFOLD_12"
    assert parts.version == 3
    assert parts.accession == "SCAFFOLD_12.3"
    assert parts.well_formed is False


def test_parse_accession_handles_empty_string():
    parts = parse_accession("")
    assert parts.accession == ""
    assert parts.base == ""
    assert parts.version is None
    assert parts.well_formed is False


def test_record_is_hashable_and_immutable():
    record = _rec()
    assert hash(record) == hash(_rec())  # 等价记录哈希一致，而非仅仅「hash() 返回 int」
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.accession = "OTHER.1"


def test_with_warning_returns_new_record():
    record = _rec()
    updated = record.with_warning("a", "b")
    assert record.warnings == ()
    assert updated.warnings == ("a", "b")


def test_length_property():
    assert _rec(seq="ACGTACGT").length == 8


# ---------------------------------------------------------------------------
# 契约锁定：14 个字段的名称与顺序是后续 26 个任务的唯一依赖面。
# 顺序错位会破坏位置参数构造；默认值被改动会让下游解析器静默填错数据。
# ---------------------------------------------------------------------------

_EXPECTED_FIELD_ORDER = (
    "accession",
    "accession_base",
    "version",
    "species",
    "species_raw",
    "lineage",
    "definition",
    "seq",
    "source_format",
    "origin_path",
    "origin_line",
    "date",
    "raw_block",
    "warnings",
)


def test_sequence_record_field_names_and_order():
    assert tuple(f.name for f in dataclasses.fields(SequenceRecord)) == _EXPECTED_FIELD_ORDER


def test_sequence_record_positional_construction_follows_field_order():
    record = SequenceRecord(
        "ON929859.1",
        "ON929859",
        1,
        "Salsola_pellucida",
        "Salsola pellucida",
        "",
        "",
        "ACGT",
        "fasta",
        "memory.fa",
        1,
    )
    assert record.accession == "ON929859.1"
    assert record.accession_base == "ON929859"
    assert record.version == 1
    assert record.species == "Salsola_pellucida"
    assert record.species_raw == "Salsola pellucida"
    assert record.lineage == ""
    assert record.definition == ""
    assert record.seq == "ACGT"
    assert record.source_format == "fasta"
    assert record.origin_path == "memory.fa"
    assert record.origin_line == 1
    assert record.date == ""
    assert record.raw_block == ""
    assert record.warnings == ()


def test_sequence_record_only_three_fields_have_defaults():
    fields = dataclasses.fields(SequenceRecord)
    defaults = {
        f.name: f.default for f in fields if f.default is not dataclasses.MISSING
    }
    assert defaults == {"date": "", "raw_block": "", "warnings": ()}
    assert all(f.default_factory is dataclasses.MISSING for f in fields)


def test_accession_parts_field_order():
    assert AccessionParts._fields == ("accession", "base", "version", "well_formed")


def test_seq_toolkit_error_is_custom_exception_base():
    assert issubclass(SeqToolkitError, Exception)
    assert SeqToolkitError.__bases__ == (Exception,)

    class _ProbeError(SeqToolkitError):
        pass

    with pytest.raises(SeqToolkitError):
        raise _ProbeError("probe")


def test_record_can_be_used_as_dict_key():
    record = _rec()
    lookup = {record: "payload"}
    assert lookup[record] == "payload"
    assert lookup[_rec()] == "payload"  # 等价记录命中同一键


def test_parse_accession_superscript_digit_does_not_raise():
    """回归：`str.isdigit()` 对 No 类字符返回 True，但 `int()` 无法解析它们。"""
    parts = parse_accession("contig.\u00b2")
    assert parts.well_formed is False
    assert parts.version is None
    assert parts.accession == "CONTIG.\u00b2"


@pytest.mark.parametrize(
    "raw",
    [
        "contig.\u00b2",
        "contig.\u2460",
        "ON929859.\u00b2.3",
        "contig.",
        ".",
        "...",
        "\u767b\u5f55\u53f7.1",
    ],
)
def test_parse_accession_is_total_for_arbitrary_strings(raw):
    """契约：对任意字符串都只返回 AccessionParts，绝不抛异常。"""
    parts = parse_accession(raw)
    assert isinstance(parts, AccessionParts)
    assert parts.well_formed is False


def test_parse_accession_still_splits_non_ascii_decimal_digits():
    """`isdecimal()` 仍接受全角数字（`int()` 可用），仅排除 No 类字符。"""
    parts = parse_accession("contig.\uff11\uff12")
    assert parts.base == "CONTIG"
    assert parts.version == 12
    assert parts.well_formed is False
