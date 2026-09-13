import json

from seq_toolkit.settings import Settings, load_settings, save_settings, settings_path


def test_defaults_are_used_when_file_missing(tmp_path):
    settings = load_settings(str(tmp_path / "absent.json"))
    assert settings.email == ""
    assert settings.wrap == 0
    assert ".fa" in settings.fasta_suffixes


def test_round_trip(tmp_path):
    target = str(tmp_path / "s.json")
    original = Settings(email="me@example.org", api_key="KEY", proxy="http://127.0.0.1:7890",
                        output_dir="D:/out", wrap=70, force_redownload=True)
    save_settings(original, target)
    loaded = load_settings(target)
    assert loaded == original


def test_corrupt_json_falls_back_to_defaults(tmp_path):
    target = tmp_path / "broken.json"
    target.write_text("{not json at all", encoding="utf-8")
    assert load_settings(str(target)).email == ""


def test_unknown_keys_are_ignored(tmp_path):
    target = tmp_path / "extra.json"
    target.write_text(json.dumps({"email": "a@b.c", "legacy_field": 1}), encoding="utf-8")
    assert load_settings(str(target)).email == "a@b.c"


def test_wrong_type_falls_back_to_default_for_that_field(tmp_path):
    target = tmp_path / "bad.json"
    target.write_text(json.dumps({"wrap": "eighty", "email": "a@b.c"}), encoding="utf-8")
    settings = load_settings(str(target))
    assert settings.wrap == 0
    assert settings.email == "a@b.c"


def test_save_creates_parent_directory(tmp_path):
    target = str(tmp_path / "nested" / "deep" / "s.json")
    save_settings(Settings(email="x@y.z"), target)
    assert load_settings(target).email == "x@y.z"


def test_settings_path_points_into_appdata(monkeypatch):
    monkeypatch.setenv("APPDATA", "C:/Users/tester/AppData/Roaming")
    path = settings_path()
    assert path.replace("\\", "/").endswith("seq_toolkit/settings.json")


def test_saved_json_is_utf8_and_readable(tmp_path):
    target = tmp_path / "cn.json"
    save_settings(Settings(output_dir="D:/中文目录"), str(target))
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["output_dir"] == "D:/中文目录"


def test_round_trip_preserves_every_field_including_suffix_tuples(tmp_path):
    """守住 info.type 陷阱：字段若静默回退默认值，此断言必失败。"""
    target = str(tmp_path / "all.json")
    original = Settings(
        email="me@example.org",
        api_key="KEY",
        proxy="http://127.0.0.1:7890",
        output_dir="D:/中文目录",
        wrap=70,
        force_redownload=True,
        fasta_suffixes=(".fa", ".fas"),
        genbank_suffixes=(".gb", ".gbk"),
    )
    save_settings(original, target)
    loaded = load_settings(target)
    assert loaded.fasta_suffixes == (".fa", ".fas")
    assert loaded.genbank_suffixes == (".gb", ".gbk")
    assert loaded == original


def test_deeply_nested_json_does_not_escape_recursion_error(tmp_path):
    """畸形配置（深度极大的嵌套数组）会抛 RecursionError，而它不是 ValueError/OSError 的子类。

    本函数对外的契约是"任何配置问题都不得抛异常"，否则调用方（GUI 启动、下载流程）
    会直接崩掉，而不是退回默认配置。用字符串拼接构造，避免测试自身爆栈。
    """
    target = tmp_path / "deep.json"
    depth = 50000
    target.write_text("[" * depth + "]" * depth, encoding="utf-8")
    settings = load_settings(str(target))  # 不得抛异常
    assert settings == Settings()


def test_bom_prefixed_config_is_read_not_discarded(tmp_path):
    """带 BOM 的 UTF-8 配置（Windows 记事本存盘默认）必须被正确读出，而不是整份回默认。

    这条测试同时守住"读入用 utf-8-sig"：若改回 encoding="utf-8"，
    json.load 会抛 JSONDecodeError，8 个字段全部静默回默认值，此断言必失败。
    """
    target = tmp_path / "bom.json"
    payload = {
        "email": "bom@example.org",
        "wrap": 60,
        "force_redownload": True,
        "fasta_suffixes": [".fas"],
    }
    target.write_bytes(b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8"))
    settings = load_settings(str(target))
    assert settings.email == "bom@example.org"
    assert settings.wrap == 60
    assert settings.force_redownload is True
    assert settings.fasta_suffixes == (".fas",)
    assert settings != Settings()


def test_schema_covers_every_settings_field():
    """守住 _SCHEMA 与 dataclass 字段名的"第二份真相"：漏更新会让该字段静默回默认且无测试发现。"""
    from dataclasses import fields

    from seq_toolkit.settings import _SCHEMA

    assert set(_SCHEMA) == {f.name for f in fields(Settings)}


def test_new_fields_round_trip(tmp_path):
    from seq_toolkit.settings import Settings, load_settings, save_settings
    target = tmp_path / "settings.json"
    original = Settings(rscript_path=r"C:\R\R-4.6.1\bin\Rscript.exe",
                        phylo_system="LCVP", phylo_scenario="S2",
                        tnrs_sources="wfo", tnrs_matches="all")
    save_settings(original, str(target))
    loaded = load_settings(str(target))
    assert loaded.rscript_path == original.rscript_path
    assert loaded.phylo_system == "LCVP"
    assert loaded.phylo_scenario == "S2"
    assert loaded.tnrs_sources == "wfo"
    assert loaded.tnrs_matches == "all"


def test_new_fields_default_when_absent(tmp_path):
    import json

    from seq_toolkit.settings import load_settings
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"email": "a@b.c"}), encoding="utf-8")
    loaded = load_settings(str(target))
    assert loaded.phylo_system == "TPL"
    assert loaded.phylo_scenario == "S3"
    assert loaded.tnrs_sources == "wcvp,wfo"
    assert loaded.tnrs_matches == "best"
    assert loaded.rscript_path == ""


def test_new_fields_reject_wrong_types(tmp_path):
    """类型不符时必须回退默认值。

    注意：本用例**不能**发现「漏登记 _SCHEMA」——那种情况下该键根本不出现在
    values 里，Settings 会取 dataclass 默认值，结果同样是默认值、断言照样通过。
    漏登记的守门由 test_new_fields_round_trip 承担（它的 5 个输入全取非默认值）。
    """
    import json

    from seq_toolkit.settings import load_settings
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"phylo_system": 123, "tnrs_matches": ["best"]}),
                      encoding="utf-8")
    loaded = load_settings(str(target))
    assert loaded.phylo_system == "TPL"
    assert loaded.tnrs_matches == "best"
