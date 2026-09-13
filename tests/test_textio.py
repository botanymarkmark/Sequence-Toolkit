import gzip

from seq_toolkit.textio import has_decoding_damage, open_text


def test_open_text_reads_utf8(tmp_path):
    target = tmp_path / "a.fa"
    target.write_text(">ON1.1 Salsola\nACGT\n", encoding="utf-8")
    with open_text(str(target)) as handle:
        assert handle.read() == ">ON1.1 Salsola\nACGT\n"


def test_open_text_strips_utf8_bom(tmp_path):
    target = tmp_path / "bom.fa"
    target.write_bytes(b"\xef\xbb\xbf>ON1.1 Salsola\nACGT\n")
    with open_text(str(target)) as handle:
        assert handle.read().startswith(">ON1.1")


def test_open_text_translates_crlf(tmp_path):
    target = tmp_path / "crlf.fa"
    target.write_bytes(b">ON1.1 Salsola\r\nACGT\r\n")
    with open_text(str(target)) as handle:
        lines = handle.read().splitlines()
    assert lines == [">ON1.1 Salsola", "ACGT"]


def test_open_text_transparently_decompresses_gzip(tmp_path):
    target = tmp_path / "gz.fa.gz"
    with gzip.open(str(target), "wt", encoding="utf-8") as handle:
        handle.write(">ON1.1 Salsola\nACGT\n")
    with open_text(str(target)) as handle:
        assert handle.read() == ">ON1.1 Salsola\nACGT\n"


def test_open_text_handles_chinese_path(tmp_path):
    folder = tmp_path / "中文目录"
    folder.mkdir()
    target = folder / "样本.fa"
    target.write_text(">ON1.1 Salsola\nACGT\n", encoding="utf-8")
    with open_text(str(target)) as handle:
        assert "Salsola" in handle.read()


def test_has_decoding_damage_detects_replacement_char():
    assert has_decoding_damage(">ON1.1 Salsola pellucida \ufffd\ufffd\ufffd") is True


def test_has_decoding_damage_is_false_for_clean_text():
    assert has_decoding_damage(">ON1.1 Salsola pellucida 中国叶绿体\nACGT\n") is False
