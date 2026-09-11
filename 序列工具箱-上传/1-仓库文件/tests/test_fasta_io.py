import gzip

import pytest

from seq_toolkit.fasta_io import FastaParseError, read_fasta


def _write(tmp_path, name, text, encoding="utf-8"):
    target = tmp_path / name
    target.write_text(text, encoding=encoding)
    return str(target)


def test_read_single_record(tmp_path):
    path = _write(tmp_path, "a.fa", ">ON929859.1 Salsola pellucida chloroplast, complete genome\nACGTACGT\n")
    records = list(read_fasta(path))
    assert len(records) == 1
    record = records[0]
    assert record.accession == "ON929859.1"
    assert record.accession_base == "ON929859"
    assert record.version == 1
    assert record.species == "Salsola_pellucida"
    assert record.species_raw == "Salsola pellucida"
    assert record.seq == "ACGTACGT"
    assert record.source_format == "fasta"
    assert record.origin_line == 1
    assert record.warnings == ()


def test_read_multiline_sequence_is_concatenated(tmp_path):
    path = _write(tmp_path, "multi.fa", ">ON1.1 Salsola pellucida\nACGT\nACGT\nAC\n")
    record = list(read_fasta(path))[0]
    assert record.seq == "ACGTACGTAC"


def test_read_multiple_records_tracks_line_numbers(tmp_path):
    path = _write(tmp_path, "two.fa",
                  ">ON1.1 Salsola pellucida\nACGT\n>MF2.1 Kochia scoparia\nTTTT\n")
    records = list(read_fasta(path))
    assert [r.accession for r in records] == ["ON1.1", "MF2.1"]
    assert records[0].origin_line == 1
    assert records[1].origin_line == 3


def test_read_lowercase_sequence_is_uppercased(tmp_path):
    path = _write(tmp_path, "lower.fa", ">ON1.1 Salsola pellucida\nacgt\n")
    assert list(read_fasta(path))[0].seq == "ACGT"


def test_read_handles_crlf(tmp_path):
    target = tmp_path / "crlf.fa"
    target.write_bytes(b">ON1.1 Salsola pellucida\r\nACGT\r\n")
    assert list(read_fasta(str(target)))[0].seq == "ACGT"


def test_read_handles_bare_cr_line_endings(tmp_path):
    target = tmp_path / "cr.fa"
    target.write_bytes(b">ON1.1 Salsola pellucida\rACGT\r>MF2.1 Kochia scoparia\rTTTT\r")
    records = list(read_fasta(str(target)))
    assert [r.accession for r in records] == ["ON1.1", "MF2.1"]
    assert records[0].seq == "ACGT"


def test_read_handles_bom(tmp_path):
    target = tmp_path / "bom.fa"
    target.write_bytes(b"\xef\xbb\xbf>ON1.1 Salsola pellucida\nACGT\n")
    assert list(read_fasta(str(target)))[0].accession == "ON1.1"


def test_read_transparently_handles_gzip(tmp_path):
    target = tmp_path / "gz.fa.gz"
    with gzip.open(str(target), "wt", encoding="utf-8") as handle:
        handle.write(">ON1.1 Salsola pellucida\nACGT\n")
    assert list(read_fasta(str(target)))[0].seq == "ACGT"


def test_read_flags_ill_formed_accession(tmp_path):
    path = _write(tmp_path, "weird.fa", ">scaffold_12.3 Salsola pellucida\nACGT\n")
    record = list(read_fasta(path))[0]
    assert record.accession == "SCAFFOLD_12.3"
    assert any("可疑" in w for w in record.warnings)


def test_read_flags_unparsable_species(tmp_path):
    path = _write(tmp_path, "nospecies.fa", ">ON1.1 chloroplast, complete genome\nACGT\n")
    record = list(read_fasta(path))[0]
    assert record.species == ""
    assert any("物种名" in w for w in record.warnings)


def test_read_flags_non_iupac_characters(tmp_path):
    path = _write(tmp_path, "bad.fa", ">ON1.1 Salsola pellucida\nACGT*NN\n")
    record = list(read_fasta(path))[0]
    assert record.seq == "ACGT*NN"
    assert any("IUPAC" in w for w in record.warnings)


def test_read_raises_on_empty_file(tmp_path):
    path = _write(tmp_path, "empty.fa", "")
    with pytest.raises(FastaParseError):
        list(read_fasta(path))


def test_read_raises_when_no_header_present(tmp_path):
    path = _write(tmp_path, "nohdr.fa", "ACGTACGT\n")
    with pytest.raises(FastaParseError):
        list(read_fasta(path))


def test_read_works_with_chinese_path(tmp_path):
    folder = tmp_path / "中文目录"
    folder.mkdir()
    target = folder / "样本.fa"
    target.write_text(">ON1.1 Salsola pellucida\nACGT\n", encoding="utf-8")
    assert list(read_fasta(str(target)))[0].species == "Salsola_pellucida"


from seq_toolkit.naming import build_name_map
from seq_toolkit.fasta_io import write_fasta


def test_write_fasta_without_name_map_uses_accession(tmp_path):
    source = _write(tmp_path, "in.fa", ">ON1.1 Salsola pellucida\nACGT\n")
    records = list(read_fasta(source))
    out = tmp_path / "out.fa"
    write_fasta(records, str(out))
    assert out.read_text(encoding="utf-8") == ">ON1.1\nACGT\n"


def test_write_fasta_applies_name_map(tmp_path):
    source = _write(tmp_path, "in.fa", ">ON1.1 Salsola pellucida\nACGT\n")
    records = list(read_fasta(source))
    mapping = build_name_map(records, "accession_species")
    out = tmp_path / "out.fa"
    write_fasta(records, str(out), mapping)
    assert out.read_text(encoding="utf-8") == ">ON1.1_Salsola_pellucida\nACGT\n"


def test_write_fasta_wraps_when_requested(tmp_path):
    source = _write(tmp_path, "in.fa", ">ON1.1 Salsola pellucida\nACGTACGT\n")
    records = list(read_fasta(source))
    out = tmp_path / "out.fa"
    write_fasta(records, str(out), wrap=3)
    assert out.read_text(encoding="utf-8") == ">ON1.1\nACG\nTAC\nGT\n"


def test_write_then_read_round_trip_preserves_sequence(tmp_path):
    source = _write(tmp_path, "in.fa", ">ON1.1 Salsola pellucida\nACGTACGTAC\n")
    records = list(read_fasta(source))
    out = tmp_path / "out.fa"
    write_fasta(records, str(out), build_name_map(records, "species"))
    back = list(read_fasta(str(out)))
    assert back[0].seq == "ACGTACGTAC"
    # species 模式只把物种名写进 header（"Salsola_pellucida"），原登录号按设计不保留；
    # 读回时该名字成为新的登录号 token，并经 parse_accession 统一转大写。
    assert back[0].accession == "SALSOLA_PELLUCIDA"


def test_write_fasta_uses_lf_line_endings(tmp_path):
    source = _write(tmp_path, "in.fa", ">ON1.1 Salsola pellucida\nACGT\n")
    out = tmp_path / "out.fa"
    write_fasta(list(read_fasta(source)), str(out))
    assert b"\r\n" not in out.read_bytes()


def test_read_flags_non_utf8_encoding(tmp_path):
    # 以 GBK 写入中文描述，读入时这些字节无法按 UTF-8 解码
    target = tmp_path / "gbk.fa"
    target.write_bytes(">ON1.1 Salsola pellucida 中国叶绿体\nACGT\n".encode("gbk"))
    record = list(read_fasta(str(target)))[0]
    assert any("UTF-8" in w for w in record.warnings)


def test_utf8_file_has_no_encoding_warning(tmp_path):
    path = _write(tmp_path, "ok.fa", ">ON1.1 Salsola pellucida chloroplast\nACGT\n")
    assert not any("UTF-8" in w for w in list(read_fasta(path))[0].warnings)
