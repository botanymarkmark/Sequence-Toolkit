import sys

import seq_toolkit


def test_package_importable():
    assert seq_toolkit.__version__ == "0.1.0"


def test_python_version_is_supported():
    assert sys.version_info >= (3, 11), "需要 Python 3.11 及以上"


def test_main_module_exposes_entrypoint():
    import importlib

    module = importlib.import_module("main")
    assert callable(module.main)
    assert callable(module.install_crash_handler)


def test_crash_log_path_is_under_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import main

    path = main.crash_log_path()
    assert path.replace("\\", "/").endswith("seq_toolkit/crash.log")
