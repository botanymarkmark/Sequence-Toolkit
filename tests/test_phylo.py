"""phylo 纯逻辑的单元测试。不发网络请求、不启动 R。"""

import os
import subprocess
import sys
import threading
import time

import pytest

from seq_toolkit.phylo import (
    DEFAULT_SCENARIO,
    ERROR_PREFIX,
    MISSING_PREFIX,
    SCENARIOS,
    SYSTEM_KEYS,
    SYSTEMS,
    TIPS_PREFIX,
    PhyloError,
    count_nodes,
    detect_environment,
    layout_cladogram,
    locate_rscript,
    parse_error,
    parse_missing,
    parse_newick,
    parse_tip_count,
    render_script,
    run_phylo,
)


def test_systems_match_the_measured_package_data():
    assert SYSTEM_KEYS == ("TPL", "LCVP", "WP")
    counts = {system.key: system.species_count for system in SYSTEMS}
    assert counts == {"TPL": 74529, "LCVP": 73420, "WP": 72570}
    assert SCENARIOS == ("S1", "S2", "S3")
    assert DEFAULT_SCENARIO == "S3"


def test_locate_rscript_prefers_the_configured_path(tmp_path):
    fake = tmp_path / "Rscript.exe"
    fake.write_text("", encoding="utf-8")
    assert locate_rscript(str(fake)) == str(fake)


def test_locate_rscript_falls_back_to_path(tmp_path):
    fake = tmp_path / "Rscript.exe"
    fake.write_text("", encoding="utf-8")
    assert locate_rscript("", which=lambda name: str(fake) if name == "Rscript" else None) \
        == str(fake)


def test_locate_rscript_scans_install_dirs_and_picks_newest(tmp_path):
    # 真实布局是 <ProgramFiles>\R\R-4.6.1\bin\Rscript.exe：program_files 下面还有一层 R
    # （本机 %LOCALAPPDATA%\Programs\R\R-4.6.1 同构）。少了这一层，用例其实一个目录都扫不到。
    root = tmp_path / "R"
    for version in ("R-4.5.0", "R-4.6.1", "R-3.6.3"):
        target = root / version / "bin"
        target.mkdir(parents=True)
        (target / "Rscript.exe").write_text("", encoding="utf-8")
    found = locate_rscript("", which=lambda _name: None, program_files=str(tmp_path),
                           local_app_data="")
    assert found is not None
    # 光断言 "R-4.6.1" in found 抓不到回归：真实机器上 %LOCALAPPDATA%\Programs\R 可能
    # 恰好也装着同名版本，那样"根本没扫传入目录"也会碰巧通过。先钉住结果确实来自 tmp。
    assert str(tmp_path) in found
    assert "R-4.6.1" in found


def test_locate_rscript_returns_none_when_nothing_found(tmp_path):
    assert locate_rscript("", which=lambda _name: None,
                          program_files=str(tmp_path), local_app_data="") is None


def test_render_script_contains_every_verified_ingredient():
    script = render_script(["Salsola pellucida", "Pinus thunbergii"], "TPL", "S3",
                           r"C:\out\phylogeny_tree.treefile")
    assert "library(V.PhyloMaker2)" in script
    # 三处 data() 显式载入：Rscript 下数据集是 lazy-load，缺了会 object not found
    assert 'data(list = paste0("tips.info.", SYSTEM)' in script
    assert 'data(list = paste0("GBOTB.extended.", SYSTEM)' in script
    assert 'data(list = paste0("nodes.info.1.", SYSTEM)' in script
    assert '"TPL"' in script and '"S3"' in script
    assert '"Salsola pellucida"' in script and '"Pinus thunbergii"' in script
    # 输 Windows 路径必须转成正斜杠，否则 R 里会被当转义序列
    assert "C:/out/phylogeny_tree.treefile" in script
    assert "\\" not in script.split("OUT <- ")[1].split("\n")[0]
    # 自动补齐 family：下划线归一 + 物种级 → 属级回退
    assert 'gsub(" ", "_"' in script
    assert "tips$genus == genus_of(sp)" in script
    # 未入树清单的机器可读汇总行
    assert MISSING_PREFIX.strip() in script


def test_render_script_escapes_quotes_in_species_names():
    script = render_script(['Genus "weird" species'], "WP", "S1", "/tmp/x.treefile")
    assert '\\"weird\\"' in script


def test_render_script_rejects_unknown_system_and_scenario():
    with pytest.raises(ValueError):
        render_script(["A b"], "APG-IV", "S3", "/tmp/x")
    with pytest.raises(ValueError):
        render_script(["A b"], "TPL", "S9", "/tmp/x")


R_STDOUT_SAMPLE = (
    '[1] "Note: 1 taxa fail to be binded to the tree,"\n'
    '[1] "Xyzzy_foobar"\n')


def test_parse_missing_prefers_the_script_summary():
    stdout = (f'{MISSING_PREFIX}A_b\n{MISSING_PREFIX}C_d\n'
              f'{R_STDOUT_SAMPLE}')
    assert parse_missing(stdout) == ["A_b", "C_d"]


def test_parse_missing_falls_back_to_the_note_line():
    """脚本汇总行缺失时（例如 R 版本差异导致中途出错）解析 R 的提示文本。"""
    assert parse_missing(R_STDOUT_SAMPLE) == ["Xyzzy_foobar"]


def test_parse_missing_returns_empty_when_nothing_missing():
    assert parse_missing('[1] "Note: 0 taxa fail to be binded to the tree,"\n') == []
    assert parse_missing("") == []


def test_parse_tip_count_and_error():
    assert parse_tip_count(f"{TIPS_PREFIX}6\n") == 6
    assert parse_tip_count("no marker here") is None
    assert parse_error("", f"{ERROR_PREFIX}boom\n").endswith("boom")
    assert parse_error("some stdout tail", "") == "some stdout tail"


def test_parse_error_never_returns_an_empty_string():
    """I3：R 被外部结束 ⇒ 非零退出、两条管道都空；空消息会让界面只剩「生成失败: 」。"""
    message = parse_error("", "", returncode=1)
    assert message.strip()
    assert "退出码 1" in message
    # 空白（而不是空串）同样要兜底，否则界面显示的是几个空格
    assert parse_error("   \n", "\n", returncode=137).strip()
    assert "137" in parse_error("   \n", "\n", returncode=137)
    # 没有退出码可用时也要给出可读文本
    assert parse_error("", "").strip()


def test_parse_newick_handles_lengths_internal_labels_and_quotes():
    text = "((A:1.5,'B quoted':2.0)Inner:0.5,C:3.0)Root;"
    root = parse_newick(text)
    assert root.label == "Root"
    assert len(root.children) == 2
    inner = root.children[0]
    assert inner.label == "Inner" and inner.length == 0.5
    assert inner.children[0].label == "A" and inner.children[0].length == 1.5
    assert inner.children[1].label == "B quoted"


def test_parse_newick_accepts_single_leaf_and_empty_raises():
    assert parse_newick("OnlyOne;").label == "OnlyOne"
    with pytest.raises(ValueError):
        parse_newick("   ")


def test_parse_newick_rejects_truncated_and_trailing_garbage():
    """畸形输入必须报错。

    调用方（GUI 预览）会照 docstring 写 try/except ValueError；若这里宽容，
    被中断或手工截断的 treefile 会被渲染成一棵看似合理的树——正是「绝不静默」禁止的。
    """
    with pytest.raises(ValueError):
        parse_newick("(A,B")          # 括号不匹配
    with pytest.raises(ValueError):
        parse_newick("(A,B);;;")      # 尾部垃圾
    with pytest.raises(ValueError):
        parse_newick("(A,,B);")       # 空元素


def test_layout_puts_leaves_in_order_and_internal_nodes_centered():
    root = parse_newick("((A,B),C);")
    laid = layout_cladogram(root, leaf_gap=10.0, level_gap=100.0)
    leaves = [node for node in _walk(laid) if not node.children]
    assert [node.label for node in leaves] == ["A", "B", "C"]
    assert [node.y for node in leaves] == [0.0, 10.0, 20.0]
    assert laid.x == 0.0 and laid.children[0].x == 100.0
    # 内部节点 y 取子节点的中点：内节点 (A,B) 是 (0+10)/2=5，根是 (5+20)/2=12.5
    assert laid.children[0].y == 5.0
    assert laid.y == 12.5


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def test_count_nodes_returns_total_and_leaves():
    root = parse_newick("((A,B),C);")
    total, leaves = count_nodes(root)
    assert leaves == 3 and total == 5


class FakeProcess:
    """假子进程：poll() 前若干次返回 None（模拟运行中），之后返回退出码。

    **必须暴露 ``returncode`` 属性**：``run_phylo`` 读的是 ``process.returncode``，
    只提供 ``poll()`` 会让"非零退出"这条分支测不到（假对象上取到 None 被当成成功）。
    """

    def __init__(self, stdout="", stderr="", returncode=0, polls_before_exit=0):
        self._stdout = stdout
        self._stderr = stderr
        self._polls = polls_before_exit
        self.returncode = returncode
        self.killed = False

    def poll(self):
        if self._polls > 0:
            self._polls -= 1
            return None
        return self.returncode

    def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        """``run_phylo`` 在取消/超时路径上杀完进程会 ``wait(timeout=...)`` 回收它。"""
        return self.returncode


def _fake_popen(process, on_spawn=None):
    """假 Popen 工厂。``on_spawn(args)`` 可选，用来模拟"R 启动后写出树文件"的副作用。

    树文件必须由假 R **在启动之后**写出，而不是测试预置：``run_phylo`` 现在的契约是
    "目标已存在就让位 ``_1``"（见 ``test_run_phylo_makes_way_for_an_existing_tree_file``），
    预置目标文件会让它改写到 ``_1``，于是"返回的路径就是传进去的路径"这类断言不再成立。
    """
    calls = {}

    def factory(args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        if on_spawn is not None:
            on_spawn(args)
        return process

    return factory, calls


class BackpressureProcess:
    """假子进程：模拟**真实管道背压**——只有 ``communicate()`` 被调用后 ``poll()`` 才返回退出码。

    真实 R 在写完 treefile 之后才逐条 ``cat`` 未入树物种，而 Windows 匿名管道缓冲只有几 KB：
    写满后 R 阻塞在 ``cat`` 上、``poll()`` 永远返回 ``None``。若 ``run_phylo`` 只在轮询
    **结束之后**才读管道，就会把一个**已经成功**的进程当超时杀掉（treefile 其实早已写好）。
    这条替身把这个死锁搬进单测：真管道写不满，但"不排空就永远退不出"的语义可以精确复现。
    """

    def __init__(self, stdout="", stderr="", returncode=0):
        self._stdout = stdout
        self._stderr = stderr
        self._exit_code = returncode
        self.returncode = None
        self.killed = False
        self.waited = False

    def poll(self):
        return self.returncode

    def communicate(self):
        self.returncode = self._exit_code
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waited = True
        return self.returncode


def test_run_phylo_returns_tree_and_missing(tmp_path):
    tree = tmp_path / "phylogeny_tree.treefile"
    stdout = f"{TIPS_PREFIX}2\n{MISSING_PREFIX}Xyzzy_foobar\n"
    # 树文件由假 R 在启动后写出（真实 R 就是 ape::write.tree 落盘），**不预置**：
    # 预置会被 run_phylo 当成"目标已存在"而让位到 _1，tree_path 断言就不再指向 tree。
    factory, calls = _fake_popen(
        FakeProcess(stdout=stdout),
        on_spawn=lambda _args: tree.write_text("(A,B);", encoding="utf-8"))
    run = run_phylo("Rscript.exe", ["A b", "B c", "Xyzzy foobar"], "TPL", "S3",
                    str(tree), popen=factory)
    assert run.returncode == 0
    assert run.missing == ["Xyzzy_foobar"]
    assert run.tip_count == 2
    assert run.tree_path == str(tree)
    # 脚本写到临时目录，且命令行是 [rscript, script]
    assert calls["args"][0] == "Rscript.exe"
    assert calls["args"][1].endswith(".R")


def test_run_phylo_raises_on_nonzero_exit(tmp_path):
    tree = tmp_path / "t.treefile"
    factory, _ = _fake_popen(FakeProcess(stdout=f"{ERROR_PREFIX}boom\n",
                                         stderr="traceback", returncode=1))
    with pytest.raises(PhyloError) as info:
        run_phylo("Rscript.exe", ["A b"], "TPL", "S3", str(tree), popen=factory)
    assert "boom" in str(info.value)


def test_run_phylo_reports_the_exit_code_when_r_prints_nothing(tmp_path):
    """I3：R 被外部结束 ⇒ 非零退出、两条管道都空，异常消息必须可读且含退出码。

    旧实现 ``parse_error("", "")`` 返回空串，界面上只剩「生成失败: 」——评审在真实 R 上
    复现过（外部结束 R 进程）。「绝不静默失败」不允许这种空提示。
    """
    factory, _ = _fake_popen(FakeProcess(stdout="", stderr="", returncode=1))
    with pytest.raises(PhyloError) as info:
        run_phylo("Rscript.exe", ["A b"], "TPL", "S3",
                  str(tmp_path / "t.treefile"), popen=factory)
    message = str(info.value)
    assert message.strip(), "错误消息不能是空串"
    assert "退出码 1" in message


class BrokenDrainProcess(FakeProcess):
    """``communicate()`` 直接抛异常：模拟管道读取失败（句柄失效等）。"""

    def communicate(self):
        raise OSError("模拟读取 R 输出失败")


def test_run_phylo_keeps_the_reason_when_draining_the_pipe_fails(tmp_path):
    """I3：排空管道失败时，异常文本要并进 stderr，不能静默丢成空串。"""
    factory, _ = _fake_popen(BrokenDrainProcess(returncode=1))
    with pytest.raises(PhyloError) as info:
        run_phylo("Rscript.exe", ["A b"], "TPL", "S3",
                  str(tmp_path / "t.treefile"), popen=factory)
    assert "模拟读取 R 输出失败" in str(info.value)


def test_run_phylo_times_out_and_kills(tmp_path):
    process = FakeProcess(polls_before_exit=10_000)
    factory, _ = _fake_popen(process)
    with pytest.raises(PhyloError) as info:
        run_phylo("Rscript.exe", ["A b"], "TPL", "S3", str(tmp_path / "t.treefile"),
                  popen=factory, timeout=0.0)
    assert "超时" in str(info.value)
    assert process.killed is True


def test_run_phylo_honours_cancel(tmp_path):
    import threading

    from seq_toolkit.pipeline import OperationCancelled
    process = FakeProcess(polls_before_exit=10_000)
    factory, _ = _fake_popen(process)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(OperationCancelled):
        run_phylo("Rscript.exe", ["A b"], "TPL", "S3", str(tmp_path / "t.treefile"),
                  popen=factory, cancel=cancel)
    assert process.killed is True


def test_run_phylo_drains_the_pipe_so_a_chatty_r_cannot_fake_a_timeout(tmp_path):
    """回归 1：轮询期间必须**并发**排空管道，否则未入树物种一多就报假超时。

    替身只有在 ``communicate()`` 被调用后才会"退出"，正是真实管道写满时的语义。
    只排空一次的旧实现会在这里一路走到超时分支，把成功的进程杀掉。
    """
    tree = tmp_path / "phylogeny_tree.treefile"
    payload = "x" * 200_000
    process = BackpressureProcess(stdout=f"{TIPS_PREFIX}2\n{payload}\n")
    # 同样由假 R 写出树文件而不是预置（预置会触发让位 _1）。
    factory, _ = _fake_popen(
        process, on_spawn=lambda _args: tree.write_text("(A,B);", encoding="utf-8"))
    run = run_phylo("Rscript.exe", ["A b", "B c"], "TPL", "S3", str(tree),
                    popen=factory, timeout=2.0, poll_interval=0.01)
    assert run.returncode == 0
    # 200 KB 一个字节都不能丢，且退出码仍取自 poll()
    assert payload in run.stdout and len(run.stdout) > 200_000
    assert run.tip_count == 2
    assert process.killed is False


def test_run_phylo_reports_the_exit_code_of_a_draining_process(tmp_path):
    """排空线程不能让退出码判定失效：R 非零退出时仍要以 R 的错误文本报错，而不是"超时"。"""
    payload = "y" * 200_000
    process = BackpressureProcess(stdout=f"{ERROR_PREFIX}boom\n{payload}\n",
                                  stderr="traceback", returncode=1)
    factory, _ = _fake_popen(process)
    with pytest.raises(PhyloError) as info:
        run_phylo("Rscript.exe", ["A b"], "TPL", "S3", str(tmp_path / "t.treefile"),
                  popen=factory, timeout=2.0, poll_interval=0.01)
    assert "boom" in str(info.value)
    assert "超时" not in str(info.value)


def test_run_phylo_reports_a_failed_spawn_as_a_phylo_error(tmp_path):
    """R 在「检测通过」与「实际运行」之间被卸载/改名时，裸 OSError 不该冒到界面层。"""
    def factory(args, **kwargs):
        raise FileNotFoundError(2, "系统找不到指定的文件。", args[0])

    with pytest.raises(PhyloError) as info:
        run_phylo("Rscript.exe", ["A b"], "TPL", "S3", str(tmp_path / "t.treefile"),
                  popen=factory)
    assert "无法启动" in str(info.value)
    assert "Rscript.exe" in str(info.value)


class _KillTreeProbe:
    """带 ``pid`` 的假子进程，用来观察杀树路径（真进程由 ``runner`` 记录）。"""

    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid
        self.killed = False
        self.waited = None

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None):
        self.waited = timeout
        return 0


@pytest.mark.skipif(os.name != "nt", reason="taskkill 是 Windows 专有降级路径")
def test_kill_process_tree_calls_taskkill_with_the_tree_flag():
    """I2：Windows 上必须 ``taskkill /F /T /PID``（``/T`` 才是杀整棵树的关键）。

    只杀 ``Popen`` 拿到的那个 ``Rscript.exe`` 是不够的：实测一次启动有**两个**
    Rscript.exe，真正的 R 是启动器的子进程，孤儿会把树跑完并把 treefile 落盘。
    """
    from seq_toolkit import phylo as phylo_module

    process = _KillTreeProbe(pid=4321)
    calls = []

    class Result:
        returncode = 0

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return Result()

    note = phylo_module._kill_process_tree(process, runner=runner)
    assert note is None                     # taskkill 成功，无需告警
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[0] == "taskkill"
    assert "/T" in argv and "/F" in argv
    assert "4321" in argv
    assert kwargs.get("capture_output") is True
    assert kwargs.get("timeout")
    assert process.killed is False          # taskkill 成功就不必再 kill 一遍
    assert process.waited is not None       # 杀完必须回收主进程


@pytest.mark.skipif(os.name != "nt", reason="taskkill 是 Windows 专有降级路径")
def test_kill_process_tree_falls_back_when_taskkill_is_unavailable():
    """taskkill 不存在/失败时退回 ``process.kill()``，并且**要把这件事说出来**。"""
    from seq_toolkit import phylo as phylo_module

    process = _KillTreeProbe()

    def runner(argv, **kwargs):
        raise FileNotFoundError(2, "系统找不到指定的文件。", "taskkill")

    note = phylo_module._kill_process_tree(process, runner=runner)
    assert process.killed is True
    assert note and "taskkill" in note


@pytest.mark.skipif(os.name != "nt", reason="杀进程树是 Windows 路径，非 Windows 按设计降级")
def test_run_phylo_cancel_kills_the_whole_process_tree(tmp_path, monkeypatch):
    """I2：取消必须杀掉**整棵进程树**，只杀启动器会留下孤儿继续跑。

    用真实子进程复现（**不用 R**）：假 ``Rscript`` 自己再拉起一个「孙子」进程，孙子每
    0.1 秒往心跳文件追加一个字节。取消后心跳必须停——旧实现只 ``Popen.kill()`` 直接子
    进程，孙子活得好好的、心跳照写；在真实 R 上这就是"已报操作已取消"之后 8 秒
    treefile 照样落盘（评审实测），而且孤儿占着临时 ``.R`` 不放。
    """
    from seq_toolkit import phylo as phylo_module
    from seq_toolkit.pipeline import OperationCancelled

    heartbeat = tmp_path / "heartbeat.txt"
    grandchild = tmp_path / "grandchild.py"
    grandchild.write_text(
        "import pathlib, sys, time\n"
        "beat = pathlib.Path(sys.argv[1])\n"
        "while True:\n"
        "    with beat.open('a', encoding='utf-8') as handle:\n"
        "        handle.write('x')\n"
        "    time.sleep(0.1)\n",
        encoding="utf-8", newline="\n")
    launcher = tmp_path / "fake_rscript.py"
    launcher.write_text(
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n"
        "pathlib.Path(sys.argv[3]).write_text(str(child.pid), encoding='utf-8')\n"
        "time.sleep(120)\n",
        encoding="utf-8", newline="\n")

    real_popen = subprocess.Popen
    spawned = []
    child_pid_file = tmp_path / "grandchild.pid"

    def factory(args, **kwargs):
        # argv[0] 是"解释器"、argv[1] 是 .R 脚本：这里只把程序换成 python + 替身启动器，
        # 管道、creationflags、杀树、回收全部走真实路径。
        assert args[1].endswith(".R")
        process = real_popen([sys.executable, str(launcher), str(grandchild),
                              str(heartbeat), str(child_pid_file)], **kwargs)
        spawned.append(process)
        return process

    killed = []
    real_kill = phylo_module._kill_process_tree

    def spy(process, **kwargs):
        killed.append(getattr(process, "pid", None))
        return real_kill(process, **kwargs)

    monkeypatch.setattr(phylo_module, "_kill_process_tree", spy)

    cancel = threading.Event()

    def _cancel_once_the_grandchild_is_running() -> None:
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            if heartbeat.exists() and heartbeat.stat().st_size > 0:
                break
            time.sleep(0.05)
        cancel.set()

    def _sweep() -> None:
        """兜底清理：修复若被回退，孤儿会活下来，不能留给后面的用例。

        直接对记录下来的两个 pid 各发一次 ``taskkill /F /T``（启动器与孙子各记一份）：
        孙子是启动器的子进程，启动器先死时按 pid 就够不到它了——那正是这个缺陷本身。
        """
        pids = [process.pid for process in spawned]
        if child_pid_file.exists():
            text = child_pid_file.read_text(encoding="utf-8").strip()
            if text.isdigit():
                pids.append(int(text))
        for pid in pids:                           # pragma: no cover - 仅失败路径需要
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True)

    trigger = threading.Thread(target=_cancel_once_the_grandchild_is_running, daemon=True)
    trigger.start()
    try:
        with pytest.raises(OperationCancelled):
            run_phylo("Rscript.exe", ["A b"], "TPL", "S3",
                      str(tmp_path / "t.treefile"), popen=factory, cancel=cancel,
                      poll_interval=0.05)
        trigger.join(timeout=25.0)

        # **先观测、后清理**：断言必须全部落在 _sweep() 之前。反过来的话（旧版把断言
        # 写在 try/finally 之后），扫尾会先把孤儿杀掉，心跳自然不再涨——于是"没杀树"
        # 这条缺陷也能测成绿的，用例名不副实。
        assert killed == [spawned[0].pid], "取消时必须走杀进程树的接缝"
        assert heartbeat.stat().st_size > 0, "前提没满足：孙子进程还没开始写心跳"
        before = heartbeat.stat().st_size
        time.sleep(0.8)
        after = heartbeat.stat().st_size
        assert after == before, \
            f"取消后孙子进程仍在写心跳（{before} → {after} 字节）：进程树没被杀干净"
    finally:
        # 兜底清理只负责收尾，不参与判定：断言在 try 内先跑完，失败时也照常清理。
        _sweep()


def test_run_phylo_reports_a_temp_script_that_could_not_be_removed(tmp_path, monkeypatch):
    """I2：临时 ``.R`` 删不掉必须**可见**（旧实现 ``except OSError: pass`` 全吞）。

    Windows 上孤儿 R 占着脚本不放，``os.unlink`` 会抛 ``[WinError 32] 另一个程序正在
    使用此文件``：每次取消都在 ``%TEMP%`` 里多一个 ``.R`` 而用户与日志都不知道。
    ``warn`` 回调覆盖包括取消/超时在内的**所有**路径（取消路径上没有 PhyloRun 可返回），
    ``PhyloRun.leaked_script`` 则给不带回调的调用方留一个可查的落点。
    """
    from seq_toolkit import phylo as phylo_module

    tree = tmp_path / "t.treefile"
    factory, _ = _fake_popen(
        FakeProcess(stdout=f"{TIPS_PREFIX}2\n"),
        on_spawn=lambda _args: tree.write_text("(A,B);", encoding="utf-8"))
    notes = []
    real_unlink = os.unlink

    def _busy(path, *args, **kwargs):
        raise OSError(32, "另一个程序正在使用此文件，进程无法访问。", path)

    with monkeypatch.context() as patch:
        patch.setattr(phylo_module.os, "unlink", _busy)
        run = run_phylo("Rscript.exe", ["A b"], "TPL", "S3", str(tree),
                        popen=factory, warn=notes.append)

    assert notes and "临时 R 脚本" in notes[0]
    assert run.leaked_script.endswith(".R")
    assert run.leaked_script in notes[0]
    real_unlink(run.leaked_script)      # 收尾：别把这条用例自己造的泄漏留在 %TEMP%


def test_run_phylo_makes_way_for_an_existing_tree_file(tmp_path):
    """目标已存在时让位 ``_1``，**绝不覆盖**。

    ``ape::write.tree`` 是原地覆盖：用户把输出指到上一次的 ``phylogeny_tree.treefile``
    上（界面默认值就是这个路径），旧结果会被无声抹掉。B8 用真实 R 复现过
    ``sentinel_survived=False``。这里钉住三件事：返回的路径是让位后的 ``_1``、
    旧文件一字未变、渲染进 R 脚本的也是让位后的路径。
    """
    tree = tmp_path / "tree.treefile"
    sentinel = "SENTINEL-上一轮的树，绝不能被覆盖"
    tree.write_text(sentinel, encoding="utf-8")
    rendered = []
    # 让位后的落点由**假 R 在启动时写出**（真实 R 就是 ape::write.tree 落盘），而不是
    # 测试预置：resolve_output_path 只返回**磁盘上不存在**的路径，预置 tree_1.treefile
    # 会让它一路跳到 tree_2.treefile，反而断言不到"让位到 _1"。
    resolved = tmp_path / "tree_1.treefile"

    def _on_spawn(args):
        with open(args[1], "rt", encoding="utf-8") as handle:
            rendered.append(handle.read())
        resolved.write_text("(A,B);", encoding="utf-8")

    factory, _ = _fake_popen(FakeProcess(stdout=f"{TIPS_PREFIX}2\n"),
                             on_spawn=_on_spawn)
    run = run_phylo("Rscript.exe", ["A b"], "TPL", "S3", str(tree), popen=factory)
    assert run.tree_path.endswith("tree_1.treefile")
    assert tree.read_text(encoding="utf-8") == sentinel
    # 渲染进 R 脚本的也必须是让位后的路径（R 不认反斜杠，脚本里统一是正斜杠）
    assert run.tree_path.replace("\\", "/") in rendered[0]


def test_detect_environment_reports_missing_r(tmp_path):
    env = detect_environment("", which=lambda _name: None,
                             program_files=str(tmp_path), local_app_data="")
    assert env.rscript is None
    assert env.has_package is False
    assert "R" in env.message


def test_detect_environment_reports_missing_package(tmp_path):
    rscript = tmp_path / "Rscript.exe"
    rscript.write_text("", encoding="utf-8")

    def runner(args, **kwargs):
        class Result:
            returncode = 0
            stdout = "4.6.1\nFALSE\n"
            stderr = ""
        return Result()

    env = detect_environment(str(rscript), runner=runner)
    assert env.rscript == str(rscript)
    assert env.version == "4.6.1"
    assert env.has_package is False
    assert "install_github" in env.message


def test_detect_environment_reports_ready(tmp_path):
    rscript = tmp_path / "Rscript.exe"
    rscript.write_text("", encoding="utf-8")

    def runner(args, **kwargs):
        class Result:
            returncode = 0
            stdout = "4.6.1\nTRUE\n"
            stderr = ""
        return Result()

    env = detect_environment(str(rscript), runner=runner)
    assert env.has_package is True
    assert "就绪" in env.message


def test_detect_environment_reports_a_failing_rscript(tmp_path):
    """R 非零退出时不能报成「缺少 V.PhyloMaker2 包」——那会把诊断指向错误方向。"""
    rscript = tmp_path / "Rscript.exe"
    rscript.write_text("", encoding="utf-8")

    def runner(args, **kwargs):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "Fatal error: cannot open file\nmore detail here\n"
        return Result()

    env = detect_environment(str(rscript), runner=runner)
    assert env.has_package is False
    assert "退出码 1" in env.message
    assert "Fatal error: cannot open file" in env.message
    assert "缺少 V.PhyloMaker2" not in env.message
