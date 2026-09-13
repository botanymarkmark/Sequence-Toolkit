import csv
import threading

from seq_toolkit.applog import RunLog


def test_records_entries_in_order():
    log = RunLog()
    log.info("a")
    log.warn("b")
    log.error("c")
    assert [(e.level, e.message) for e in log.entries] == [
        ("INFO", "a"), ("WARN", "b"), ("ERROR", "c")]


def test_add_exception_and_count():
    log = RunLog()
    log.add_exception("a.fa", 3, ">ON1.1 chloroplast", "物种名缺失", "ON1.1")
    assert log.exception_count() == 1
    entry = log.exceptions[0]
    assert (entry.path, entry.line, entry.final_name) == ("a.fa", 3, "ON1.1")


def test_clear_resets_both_collections():
    log = RunLog()
    log.info("x")
    log.add_exception("a", 1, "h", "r")
    log.clear()
    assert log.entries == () and log.exceptions == ()


def test_export_text_contains_levels_and_messages():
    log = RunLog()
    log.warn("小心")
    text = log.export_text()
    assert "WARN" in text and "小心" in text


def test_export_log_writes_utf8_file(tmp_path):
    log = RunLog()
    log.info("中文日志")
    target = tmp_path / "run.log"
    log.export_log(str(target))
    assert "中文日志" in target.read_text(encoding="utf-8")


def test_export_exceptions_csv_round_trips_chinese(tmp_path):
    log = RunLog()
    log.add_exception("样本.fa", 7, ">ON1.1 未知", "无法提取物种名", "sequence_1")
    target = tmp_path / "exceptions.csv"
    log.export_exceptions_csv(str(target))
    with open(str(target), "r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][0] == "文件"
    assert rows[1][0] == "样本.fa"
    assert rows[1][3] == "无法提取物种名"


def test_export_exceptions_csv_with_no_rows_still_writes_header(tmp_path):
    log = RunLog()
    target = tmp_path / "empty.csv"
    log.export_exceptions_csv(str(target))
    text = target.read_text(encoding="utf-8-sig")
    assert text.strip().startswith("文件")


def test_run_log_is_thread_safe_under_concurrent_writes():
    log = RunLog()

    def worker(tag):
        for index in range(200):
            log.info(f"{tag}-{index}")

    threads = [threading.Thread(target=worker, args=(tag,)) for tag in "abcd"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(log.entries) == 800
