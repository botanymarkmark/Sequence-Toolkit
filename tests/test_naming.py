from seq_toolkit.model import SequenceRecord, parse_accession
from seq_toolkit.naming import sanitize_accession, sanitize_species


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


# ---------- sanitize_accession ----------

def test_sanitize_accession_keeps_version_dot():
    assert sanitize_accession("ON929859.1") == "ON929859.1"


def test_sanitize_accession_removes_spaces_and_illegal_chars():
    assert sanitize_accession(" ON929859.1 | x ") == "ON929859.1x"


def test_sanitize_accession_keeps_refseq_underscore():
    assert sanitize_accession("NZ_CM000001.1") == "NZ_CM000001.1"


# ---------- sanitize_species ----------

def test_sanitize_species_replaces_spaces_with_underscores():
    assert sanitize_species("Salsola pellucida") == "Salsola_pellucida"


def test_sanitize_species_drops_period():
    assert sanitize_species("Salsola sp. A-2019") == "Salsola_sp_A-2019"


def test_sanitize_species_translates_hybrid_sign():
    assert sanitize_species("Salsola × tragus") == "Salsola_x_tragus"


def test_sanitize_species_handles_fullwidth_space():
    assert sanitize_species("Salsola\u3000pellucida") == "Salsola_pellucida"


def test_sanitize_species_drops_path_separators_and_punctuation():
    assert sanitize_species("a/b\\c:d;(e)") == "abcde"


def test_sanitize_species_collapses_repeated_underscores():
    assert sanitize_species("Salsola   pellucida") == "Salsola_pellucida"


def test_sanitize_species_returns_empty_when_nothing_left():
    assert sanitize_species("   ...   ") == ""


def test_sanitize_species_is_idempotent():
    once = sanitize_species("Salsola sp. A-2019")
    assert sanitize_species(once) == once


# ---------- 核心设计点：句点在两处方向相反 ----------

def test_period_is_kept_in_accession_but_dropped_in_species():
    """若把两个函数合并、或让 sanitize_accession 也删句点，
    登录号会被破坏成 ON9298591，下游全部按登录号的逻辑随之失效。"""
    record = _rec(accession="ON929859.1", species="Salsola sp. A-2019")
    assert sanitize_accession(record.accession) == "ON929859.1"
    assert sanitize_species(record.species_raw) == "Salsola_sp_A-2019"


# ---------- extract_species_from_header ----------

from seq_toolkit.naming import extract_species_from_header


def test_extract_species_plain_binomial():
    species, warnings = extract_species_from_header(
        "Salsola pellucida chloroplast, complete genome"
    )
    assert species == "Salsola pellucida"
    assert warnings == ()


def test_extract_species_strips_unverified_prefix():
    species, warnings = extract_species_from_header(
        "UNVERIFIED: Salsola pellucida chloroplast, complete genome"
    )
    assert species == "Salsola pellucida"
    assert any("UNVERIFIED" in w.upper() for w in warnings)


def test_extract_species_absorbs_sp_marker_and_strain_code():
    species, _ = extract_species_from_header(
        "Salsola sp. A-2019 voucher Smith 123 chloroplast"
    )
    assert species == "Salsola sp. A-2019"


def test_extract_species_absorbs_cf_marker():
    species, _ = extract_species_from_header(
        "Salsola cf. pellucida isolate 5 chloroplast"
    )
    assert species == "Salsola cf. pellucida"


def test_extract_species_absorbs_hybrid_sign():
    species, _ = extract_species_from_header(
        "Salsola × tragus chloroplast, complete genome"
    )
    assert species == "Salsola × tragus"


def test_extract_species_stops_at_isolate_keyword():
    species, _ = extract_species_from_header(
        "Salsola pellucida isolate 5 chloroplast, partial sequence"
    )
    assert species == "Salsola pellucida"


def test_extract_species_accepts_genus_only():
    species, _ = extract_species_from_header("Salsola")
    assert species == "Salsola"


def test_extract_species_fails_when_header_has_no_latin_name():
    species, warnings = extract_species_from_header("chloroplast, complete genome")
    assert species == ""
    assert warnings == ("无法从 header 提取物种名",)


def test_extract_species_supports_all_lowercase_header():
    species, _ = extract_species_from_header("salsola pellucida chloroplast")
    assert species == "salsola pellucida"


def test_extract_species_absorbs_var_marker():
    species, _ = extract_species_from_header(
        "Salsola pellucida var. tragus isolate 1 chloroplast"
    )
    assert species == "Salsola pellucida var. tragus"


def test_extract_species_never_exceeds_four_tokens():
    species, _ = extract_species_from_header(
        "Alpha Beta Gamma Delta Epsilon Zeta chloroplast"
    )
    assert species == "Alpha Beta Gamma Delta"


def test_extract_species_ignores_cultivar_name():
    species, _ = extract_species_from_header("Salsola cv. Xyz chloroplast")
    assert species == "Salsola"


# ---------- 修复轮次：MAX_SPECIES_TOKENS 硬上限在标记词分支失效 ----------

def test_extract_species_var_marker_branch_respects_token_cap():
    """标记词分支在同一次迭代内追加标记词 + follower 两个词；
    若 follower 的追加不重复检查上限，4 词上限会被突破到 5 词。"""
    species, _ = extract_species_from_header(
        "Alpha Beta Gamma var. tragus chloroplast"
    )
    assert species == "Alpha Beta Gamma var."
    assert len(species.split(" ")) == 4


def test_extract_species_hybrid_marker_branch_respects_token_cap():
    species, _ = extract_species_from_header(
        "Alpha Beta Gamma × tragus chloroplast"
    )
    assert species == "Alpha Beta Gamma ×"
    assert len(species.split(" ")) == 4


def test_extract_species_glued_hybrid_marker_respects_token_cap():
    species, _ = extract_species_from_header(
        "Alpha Beta Gamma ×tragus chloroplast"
    )
    assert species == "Alpha Beta Gamma ×"
    assert len(species.split(" ")) == 4


# ---------- 修复轮次：粘连的杂交符号不再静默只取到属名 ----------

def test_extract_species_absorbs_glued_hybrid_sign():
    species, warnings = extract_species_from_header(
        "Salsola ×tragus chloroplast"
    )
    assert species == "Salsola × tragus"
    assert warnings == ()


def test_extract_species_absorbs_fully_glued_hybrid_sign():
    species, warnings = extract_species_from_header(
        "Salsola×tragus chloroplast"
    )
    assert species == "Salsola × tragus"
    assert warnings == ()


def test_extract_species_glued_hybrid_matches_canonical_form():
    """粘连写法与规范写法必须归一到同一个下游序列名。"""
    glued, _ = extract_species_from_header("Salsola×tragus chloroplast")
    canonical, _ = extract_species_from_header("Salsola × tragus chloroplast")
    assert glued == canonical
    assert sanitize_species(glued) == "Salsola_x_tragus"


# ---------- 命名模式渲染与流水号分配 ----------

import pytest

from seq_toolkit.naming import NAMING_MODES, build_name_map, render_name, species_key


def test_naming_modes_are_exactly_the_four_supported():
    assert NAMING_MODES == ("keep", "accession", "species", "accession_species")


def test_render_accession_mode():
    assert render_name(_rec(), "accession") == "ON929859.1"


def test_render_species_mode():
    assert render_name(_rec(), "species") == "Salsola_pellucida"


def test_render_accession_species_mode():
    assert render_name(_rec(), "accession_species") == "ON929859.1_Salsola_pellucida"


def test_render_with_serial_appends_suffix():
    assert render_name(_rec(), "accession_species", 2) == (
        "ON929859.1_Salsola_pellucida_2"
    )


def test_render_without_serial_has_no_suffix():
    assert render_name(_rec(), "species", None) == "Salsola_pellucida"


def test_render_rejects_unknown_mode():
    with pytest.raises(ValueError):
        render_name(_rec(), "bogus")


def test_render_falls_back_to_accession_when_species_missing():
    assert render_name(_rec(species=""), "species") == "ON929859.1"


def test_render_falls_back_to_species_when_accession_missing():
    assert render_name(_rec(accession="", species="Salsola_pellucida"),
                       "accession") == "Salsola_pellucida"


def test_species_key_uses_sanitized_species():
    assert species_key(_rec(species="Salsola pellucida")) == "Salsola_pellucida"


def test_species_key_falls_back_to_accession_base():
    assert species_key(_rec(accession="ON929859.1", species="")) == "ON929859"


def test_build_name_map_keep_mode_returns_empty_mapping():
    assert build_name_map([_rec()], "keep") == {}


def test_build_name_map_unique_species_has_no_serial():
    records = [_rec(accession="ON1.1", species="Salsola_pellucida"),
               _rec(accession="MF1.1", species="Kochia_scoparia")]
    mapping = build_name_map(records, "accession_species")
    assert mapping[records[0]] == "ON1.1_Salsola_pellucida"
    assert mapping[records[1]] == "MF1.1_Kochia_scoparia"


def test_build_name_map_duplicate_species_gets_no_serials_when_names_differ():
    """同物种多条（不同登录号）在 accession_species 模式下**不再**发流水号。

    这是用户使用后提出的行为调整：流水号的唯一目的是防止最终文件名撞车，判据因此是
    "渲染出的基名是否会重复"，而不是"物种是否重复"。``accession_species`` 模式渲染出的
    基名以登录号开头，登录号天然唯一 ⇒ 基名不可能撞车 ⇒ 加 `_1`/`_2` 纯属多余。
    用户实际下载到的 `MZ230595.1_Salsola_heptapotamica_3` 正是旧判据的产物
    （同一物种有 3 条不同登录号的序列，第 3 条被发了 `_3`）。

    旧期望是 `ON1.1_Salsola_pellucida_1` / `ON2.1_Salsola_pellucida_2`，已按新语义更新。
    """
    records = [_rec(accession="ON1.1", species="Salsola_pellucida"),
               _rec(accession="MF1.1", species="Kochia_scoparia"),
               _rec(accession="ON2.1", species="Salsola_pellucida")]
    mapping = build_name_map(records, "accession_species")
    assert mapping[records[0]] == "ON1.1_Salsola_pellucida"
    assert mapping[records[1]] == "MF1.1_Kochia_scoparia"
    assert mapping[records[2]] == "ON2.1_Salsola_pellucida"


def test_build_name_map_accession_mode_gets_no_serials_for_duplicate_species():
    """``accession`` 模式同理：登录号已保证唯一，同物种多条也不该发号。"""
    records = [_rec(accession="ON1.1", species="Salsola_pellucida"),
               _rec(accession="ON2.1", species="Salsola_pellucida")]
    mapping = build_name_map(records, "accession")
    assert mapping[records[0]] == "ON1.1"
    assert mapping[records[1]] == "ON2.1"


def test_build_name_map_species_mode_protects_against_duplicate_names():
    """``species`` 模式必须继续发号：基名里没有登录号，不加 `_1`/`_2` 就真的会重名。"""
    records = [_rec(accession="ON1.1", species="Salsola_pellucida"),
               _rec(accession="ON2.1", species="Salsola_pellucida")]
    mapping = build_name_map(records, "species")
    assert mapping[records[0]] == "Salsola_pellucida_1"
    assert mapping[records[1]] == "Salsola_pellucida_2"


def test_build_name_map_serials_duplicate_accession_in_accession_species_mode():
    """新判据仍要兜得住真正的撞车：同一登录号出现两次时基名完全相同，必须发号。

    去重默认开启时不会发生，只有关掉去重（或两条记录来自不同文件且登录号相同）才会。
    """
    records = [_rec(accession="ON1.1", species="Salsola_pellucida", origin_line=1),
               _rec(accession="ON1.1", species="Salsola_pellucida", origin_line=2)]
    mapping = build_name_map(records, "accession_species")
    assert mapping[records[0]] == "ON1.1_Salsola_pellucida_1"
    assert mapping[records[1]] == "ON1.1_Salsola_pellucida_2"


def test_build_name_map_serials_duplicate_accession_in_accession_mode():
    """``accession`` 模式下同一登录号出现两次同样是基名撞车，照样发号。"""
    records = [_rec(accession="ON1.1", species="", origin_line=1),
               _rec(accession="ON1.1", species="", origin_line=2)]
    mapping = build_name_map(records, "accession")
    assert mapping[records[0]] == "ON1.1_1"
    assert mapping[records[1]] == "ON1.1_2"


def test_build_name_map_is_deterministic():
    records = [_rec(accession="ON1.1", species="Salsola_pellucida"),
               _rec(accession="ON2.1", species="Salsola_pellucida")]
    assert build_name_map(records, "species") == build_name_map(records, "species")


# ---------- 修复轮次：空名兜底与空批次模式校验 ----------


def test_render_name_with_serial_is_empty_when_base_name_is_empty():
    """基名为空时不得追加流水号：否则 "_1" 去下划线后成 "1"，是会被当成有效名的真值。"""
    blank = _rec(accession="", species="")
    assert render_name(blank, "accession", 1) == ""
    assert render_name(blank, "species", 1) == ""
    assert render_name(blank, "accession_species", 1) == ""


def test_render_name_without_serial_is_empty_when_base_name_is_empty():
    blank = _rec(accession="", species="")
    assert render_name(blank, "accession_species", None) == ""


def test_build_name_map_blank_records_fall_back_to_sequence_index():
    """两条 accession 与 species 均为空的记录（如文件里出现两行裸 ">"）→ sequence_N。"""
    first = _rec(accession="", species="", seq="ACGT", origin_line=7)
    second = _rec(accession="", species="", seq="TTTT", origin_line=9)
    mapping = build_name_map([first, second], "species")
    assert mapping[first] == "sequence_1"
    assert mapping[second] == "sequence_2"


def test_build_name_map_blank_records_never_get_bare_numeric_names():
    first = _rec(accession="", species="", seq="ACGT", origin_line=7)
    second = _rec(accession="", species="", seq="TTTT", origin_line=9)
    mapping = build_name_map([first, second], "species")
    assert sorted(mapping.values()) == ["sequence_1", "sequence_2"]
    for name in mapping.values():
        assert not name.isdigit()


def test_build_name_map_rejects_unknown_mode_on_empty_batch():
    """空批次也必须校验 mode：不能把非法模式静默当成 keep 而返回 {}。"""
    with pytest.raises(ValueError):
        build_name_map([], "bogus")


def test_build_name_map_keep_mode_on_empty_batch_still_returns_empty():
    assert build_name_map([], "keep") == {}
