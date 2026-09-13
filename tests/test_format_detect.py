import os

from seq_toolkit.format_detect import (
    detect_format,
    format_from_suffix,
    list_input_files,
    natural_key,
    sniff_format,
)


def test_format_from_suffix_recognises_fasta_variants():
    for name in ("a.fa", "a.FASTA", "a.fna", "a.fas", "a.seq", "a.fa.gz"):
        assert format_from_suffix(name) == "fasta", name


def test_format_from_suffix_recognises_genbank_variants():
    for name in ("a.gb", "a.GBK", "a.genbank", "a.gbff", "a.gb.gz"):
        assert format_from_suffix(name) == "genbank", name


def test_format_from_suffix_returns_empty_for_unknown():
    assert format_from_suffix("a.txt") == ""


def test_sniff_detects_fasta(tmp_path):
    target = tmp_path / "x.dat"
    target.write_text(">ON1.1 Salsola\nACGT\n", encoding="utf-8")
    assert sniff_format(str(target)) == "fasta"


def test_sniff_detects_genbank(tmp_path):
    target = tmp_path / "x.dat"
    target.write_text("LOCUS       ON1.1\nORIGIN\n//\n", encoding="utf-8")
    assert sniff_format(str(target)) == "genbank"


def test_content_wins_over_misleading_suffix(tmp_path):
    target = tmp_path / "misleading.fa"
    target.write_text("LOCUS       ON1.1    4 bp    DNA     linear   PLN 01-JAN-2020\n"
                      "ORIGIN\n        1 acgt\n//\n", encoding="utf-8")
    assert detect_format(str(target)) == "genbank"


def test_hint_forces_format(tmp_path):
    target = tmp_path / "a.gbk"
    target.write_text(">ON1.1 Salsola\nACGT\n", encoding="utf-8")
    assert detect_format(str(target), "genbank") == "genbank"
    assert detect_format(str(target), "fasta") == "fasta"


def test_detect_returns_empty_for_junk(tmp_path):
    target = tmp_path / "junk.txt"
    target.write_text("hello world\n", encoding="utf-8")
    assert detect_format(str(target)) == ""


def test_detect_rejects_unknown_hint():
    import pytest
    with pytest.raises(ValueError):
        detect_format("whatever", "bogus")


def test_natural_key_sorts_numbers_numerically():
    names = ["chr10.fa", "chr2.fa", "chr1.fa"]
    assert sorted(names, key=natural_key) == ["chr1.fa", "chr2.fa", "chr10.fa"]


def test_list_input_files_keeps_explicit_files_regardless_of_suffix(tmp_path):
    odd = tmp_path / "weird.txt"
    odd.write_text(">ON1.1 Salsola\nACGT\n", encoding="utf-8")
    assert list_input_files([str(odd)]) == [str(odd)]


def test_list_input_files_filters_by_suffix_inside_directories(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "a.fa").write_text(">ON1.1 S\nACGT\n", encoding="utf-8")
    (folder / "b.gbk").write_text("LOCUS       X\nORIGIN\n//\n", encoding="utf-8")
    (folder / "note.md").write_text("ignore me\n", encoding="utf-8")
    found = list_input_files([str(folder)])
    assert [f.split("\\")[-1].split("/")[-1] for f in found] == ["a.fa", "b.gbk"]


def test_list_input_files_recursive_flag(tmp_path):
    folder = tmp_path / "in"
    sub = folder / "nested"
    sub.mkdir(parents=True)
    (folder / "a.fa").write_text(">ON1.1 S\nACGT\n", encoding="utf-8")
    (sub / "b.fa").write_text(">ON2.1 S\nACGT\n", encoding="utf-8")
    assert len(list_input_files([str(folder)], recursive=False)) == 1
    assert len(list_input_files([str(folder)], recursive=True)) == 2


def test_sniff_format_returns_empty_for_truncated_gzip(tmp_path):
    import gzip
    target = tmp_path / "broken.fa.gz"
    with gzip.open(str(target), "wb") as handle:
        handle.write(b">ON1.1 Salsola pellucida\nACGTACGTACGTACGT\n")
    raw = target.read_bytes()
    target.write_bytes(raw[: len(raw) // 2])   # 截断，去掉 end-of-stream 标记
    assert sniff_format(str(target)) == ""


def test_detect_format_falls_back_to_suffix_for_truncated_gzip(tmp_path):
    import gzip
    target = tmp_path / "broken.fa.gz"
    with gzip.open(str(target), "wb") as handle:
        handle.write(b">ON1.1 Salsola pellucida\nACGTACGTACGTACGT\n")
    raw = target.read_bytes()
    target.write_bytes(raw[: len(raw) // 2])   # 截断，去掉 end-of-stream 标记
    # 内容读不出来（嗅探容错返回空串），应回落到后缀而不是抛异常
    assert detect_format(str(target)) == "fasta"


def _gzip_bytes(payload: bytes) -> bytes:
    """构造带 10 字节干净头的合法 gzip 流。

    filename="" 让 gzip 不写 FNAME 字段，deflate 数据体因此恰好从偏移 10 开始
    （否则开头会多出「原文件名 + NUL」，固定下标就不再落在数据体上）。
    """
    import gzip
    import io
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="") as handle:
        handle.write(payload)
    return buffer.getvalue()


def _write_body_corrupted_gz(target, payload, offset: int) -> bytes:
    """把 deflate 数据体内指定偏移的一个字节翻转，写出损坏文件并返回损坏后的字节。"""
    raw = bytearray(_gzip_bytes(payload))
    raw[offset] ^= 0xFF
    target.write_bytes(bytes(raw))
    return bytes(raw)


def _raw_decompression_error(raw: bytes):
    """完整解压一份 gzip 字节，返回抛出的异常；正常解压返回 None。"""
    import gzip
    import io
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as handle:
            handle.read()
    except Exception as exc:  # noqa: BLE001 - 这里就是要看异常类型
        return exc
    return None


_FASTA_PAYLOAD = b">ON1.1 Salsola pellucida\n" + b"ACGT" * 400 + b"\n"


def test_sniff_format_tolerates_corrupted_deflate_body(tmp_path):
    """deflate 数据体损坏（非截断）抛 zlib.error，同样必须被 sniff_format 吞掉。"""
    import zlib
    target = tmp_path / "corrupt.fa.gz"
    raw = _write_body_corrupted_gz(target, _FASTA_PAYLOAD, offset=10)
    # 见证断言：这份构造确实让解压抛 zlib.error（而不是 BadGzipFile/EOFError）。
    # 少了它，测试可能在别的解释器上退化成「什么都没测到」还显示通过。
    assert isinstance(_raw_decompression_error(raw), zlib.error)
    assert sniff_format(str(target)) == ""


def test_detect_format_falls_back_to_suffix_for_corrupted_deflate_body(tmp_path):
    import zlib
    target = tmp_path / "corrupt.fa.gz"
    raw = _write_body_corrupted_gz(target, _FASTA_PAYLOAD, offset=10)
    assert isinstance(_raw_decompression_error(raw), zlib.error)
    # 内容读不出来（嗅探容错返回空串），应回落到后缀而不是抛异常
    assert detect_format(str(target)) == "fasta"


def test_sniff_format_survives_byte_flips_across_deflate_body(tmp_path):
    """穷举数据体内每一个单字节翻转：嗅探与判定都不得抛异常。

    首行取一条 20 kb 的长行（无换行），让「读首行」必须解码完整个 deflate 体，
    从而把数据体中段的损坏也真正走到，而不是读到第一个换行就提前收工。
    """
    import zlib
    payload = b">ON1.1 Salsola pellucida " + b"ACGT" * 5000
    base = _gzip_bytes(payload)
    body = range(10, len(base) - 8)   # 跳过 10 字节头与 8 字节尾部校验
    assert len(body) > 40

    target = tmp_path / "flip.fa.gz"
    zlib_hits = 0
    for offset in body:
        raw = _write_body_corrupted_gz(target, payload, offset=offset)
        if isinstance(_raw_decompression_error(raw), zlib.error):
            zlib_hits += 1
        # 关键点：这里不允许任何异常逃出
        assert sniff_format(str(target)) in ("", "fasta", "genbank"), offset
        assert detect_format(str(target)) in ("", "fasta", "genbank"), offset
    # 语料必须真的覆盖 zlib.error 分支，否则本测试无法回归这个缺陷
    assert zlib_hits > 0


def test_list_input_files_handles_chinese_paths(tmp_path):
    folder = tmp_path / "输入 数据"
    sub = folder / "子目录"
    sub.mkdir(parents=True)
    (folder / "chr10.fa").write_text(">ON10.1 S\nACGT\n", encoding="utf-8")
    (folder / "chr2.fa").write_text(">ON2.1 S\nACGT\n", encoding="utf-8")
    (folder / "样本甲.fa").write_text(">ON1.1 S\nACGT\n", encoding="utf-8")
    (folder / "样本乙.gbk").write_text("LOCUS       X\nORIGIN\n//\n", encoding="utf-8")
    (folder / "说明.md").write_text("ignore me\n", encoding="utf-8")
    (sub / "深层.fna").write_text(">ON3.1 S\nACGT\n", encoding="utf-8")

    flat = list_input_files([str(folder)], recursive=False)
    # 非 ASCII 目录 + 非 ASCII 文件名：仍按后缀过滤，且数字块按数值排
    assert [os.path.basename(f) for f in flat] == [
        "chr2.fa", "chr10.fa", "样本乙.gbk", "样本甲.fa",
    ]
    assert all(os.path.isfile(f) for f in flat)

    deep = list_input_files([str(folder)], recursive=True)
    assert len(deep) == 5
    # 中文子目录被正确拼进路径，且该路径真实存在（能再次 stat）
    assert os.path.join(str(sub), "深层.fna") in deep
    assert all(os.path.isfile(f) for f in deep)

    explicit = str(folder / "样本甲.fa")
    assert list_input_files([explicit]) == [explicit]


def test_detect_format_handles_chinese_paths(tmp_path):
    import gzip
    folder = tmp_path / "中文 目录"
    folder.mkdir()
    fasta = folder / "样本甲.fa"
    fasta.write_text(">ON1.1 Salsola pellucida\nACGTACGT\n", encoding="utf-8")
    mislabelled = folder / "伪装.fa"
    mislabelled.write_text(
        "LOCUS       ON1.1    8 bp    DNA     linear   PLN 01-JAN-2020\n"
        "ORIGIN\n        1 acgtacgt\n//\n", encoding="utf-8")
    compressed = folder / "压缩 样本.fa.gz"
    with gzip.open(str(compressed), "wb") as handle:
        handle.write(b">ON2.1 Salsola\nACGTACGT\n")

    assert format_from_suffix(str(fasta)) == "fasta"
    assert sniff_format(str(fasta)) == "fasta"
    assert detect_format(str(fasta)) == "fasta"
    # 中文文件名 + 起错后缀：内容优先依然成立
    assert detect_format(str(mislabelled)) == "genbank"
    # 中文名 + 空格 + .gz：透明解压后嗅探为 fasta
    assert detect_format(str(compressed)) == "fasta"
