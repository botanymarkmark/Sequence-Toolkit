"""V.PhyloMaker2 调用与 Newick 处理。纯逻辑，不 import tkinter。

所有事实来自 2026-09-12 的实测（探针 p2_phylo.R / p3_family.R / p3_auto.R）：
包内置三套系统树（TPL 74,529 / LCVP 73,420 / WP 72,570 种）；
``Rscript`` 下数据集是 lazy-load，**必须显式 data() 载入**，否则抛
``object 'GBOTB.extended.TPL' not found``；``tips.info.<系统>$species`` 用**下划线**
形式（按空格查会全部落空），属级回退可补齐 family；``phylo.maker`` 对无法绑定的物种
只打印一行 Note 然后静默丢弃。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .model import SeqToolkitError
from .pipeline import OperationCancelled, resolve_output_path

MISSING_PREFIX = "SEQTOOLKIT_MISSING\t"
TIPS_PREFIX = "SEQTOOLKIT_TIPS\t"
ERROR_PREFIX = "SEQTOOLKIT_ERROR: "
DEFAULT_TIMEOUT = 600
# 让 Rscript 带着自己的进程组启动，取消时好整棵树一起杀（见 _kill_process_tree）。
# POSIX 上没有这个常量，getattr 降级为 0——**不能**在非 Windows 上传非 0，Popen 会
# 直接抛 ValueError("creationflags is only supported on Windows platforms")。
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
# taskkill 与回收子进程的超时。都不能无限等：取消/超时路径本来就要求"尽快回到界面"。
KILL_TIMEOUT = 15.0


class PhyloError(SeqToolkitError):
    """系统树生成失败（R 缺失、脚本报错、超时等）。"""


@dataclass(frozen=True)
class PhyloSystem:
    """一套命名系统（实测的三个，包里没有 APG III/APG IV）。"""

    key: str
    label: str
    species_count: int


SYSTEMS = (
    PhyloSystem("TPL", "The Plant List", 74529),
    PhyloSystem("LCVP", "Leipzig Catalogue of Vascular Plants", 73420),
    PhyloSystem("WP", "World Plants", 72570),
)
SYSTEM_KEYS = tuple(system.key for system in SYSTEMS)

SCENARIOS = ("S1", "S2", "S3")   # S1 绑定到属节点 / S2 科内随机 / S3 属内随机
DEFAULT_SCENARIO = "S3"

_VERSION = re.compile(r"R-(\d+)\.(\d+)\.(\d+)")


def locate_rscript(configured: str = "",
                   which: Callable[[str], str | None] | None = None,
                   program_files: str | None = None,
                   local_app_data: str | None = None) -> str | None:
    """按「设置项 → PATH → 常见安装目录」顺序找 Rscript，找不到返回 None。

    安装目录里可能有多个版本，取版本号最大者：用户升级 R 之后旧版本仍在磁盘上，
    随机挑一个会让"上次能跑、这次报错"变得无法解释。
    """
    configured = (configured or "").strip()
    if configured and os.path.isfile(configured):
        return configured

    finder = which if which is not None else shutil.which
    found = finder("Rscript")
    if found:
        return found

    roots = []
    program_files = program_files if program_files is not None else \
        os.environ.get("ProgramFiles", r"C:\Program Files")
    local_app_data = local_app_data if local_app_data is not None else \
        os.environ.get("LOCALAPPDATA", "")
    if program_files:
        roots.append(os.path.join(program_files, "R"))
    if local_app_data:
        roots.append(os.path.join(local_app_data, "Programs", "R"))

    candidates: list[tuple[tuple[int, int, int], str]] = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            executable = os.path.join(root, name, "bin", "Rscript.exe")
            if not os.path.isfile(executable):
                continue
            match = _VERSION.search(name)
            version = tuple(int(part) for part in match.groups()) if match else (0, 0, 0)
            candidates.append((version, executable))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _r_string(text: str) -> str:
    """把字符串渲染成 R 字面量（转义反斜杠与双引号）。"""
    escaped = str(text).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_script(species: Sequence[str], system: str, scenario: str,
                  out_path: str) -> str:
    """渲染 R 脚本。**模板的每一处都是实测跑通后固化下来的**，改动前先读模块 docstring。"""
    if system not in SYSTEM_KEYS:
        raise ValueError(f"未知命名系统: {system}")
    if scenario not in SCENARIOS:
        raise ValueError(f"未知场景: {scenario}")

    names = ", ".join(_r_string(name) for name in species)
    # R 不认 Windows 的反斜杠路径（会被当转义序列），统一转正斜杠
    out = str(out_path).replace("\\", "/")

    return f'''suppressMessages(library(V.PhyloMaker2))

SYSTEM <- {_r_string(system)}
SCENARIO <- {_r_string(scenario)}
OUT <- {_r_string(out)}
species <- c({names})

# 数据集在 Rscript 下是 lazy-load：不显式 data() 载入会抛 object not found
data(list = paste0("tips.info.", SYSTEM), package = "V.PhyloMaker2")
tips <- get(paste0("tips.info.", SYSTEM))

genus_of <- function(x) sub(" .*$", "", trimws(x))
norm <- function(x) gsub(" ", "_", trimws(x))

# family 自动补齐：先按物种（下划线形式）查，再按属回退；都没有则 NA。
# tips$species 用的是下划线形式（如 Stylotrichium_rotundifolium），
# 直接拿带空格的学名去匹配会**全部落空**。
family_of <- function(sp) {{
  hit <- tips$family[tips$species == norm(sp)]
  hit <- hit[!is.na(hit)]
  if (length(hit) > 0) return(hit[1])
  hit <- tips$family[tips$genus == genus_of(sp)]
  hit <- hit[!is.na(hit)]
  if (length(hit) > 0) return(hit[1])
  NA_character_
}}

sp.list <- data.frame(
  species = species,
  genus = vapply(species, genus_of, character(1)),
  family = vapply(species, family_of, character(1)),
  stringsAsFactors = FALSE
)

data(list = paste0("GBOTB.extended.", SYSTEM), package = "V.PhyloMaker2")
data(list = paste0("nodes.info.1.", SYSTEM), package = "V.PhyloMaker2")
tree <- get(paste0("GBOTB.extended.", SYSTEM))
nodes <- get(paste0("nodes.info.1.", SYSTEM))

result <- tryCatch(
  V.PhyloMaker2::phylo.maker(sp.list = sp.list, scenarios = SCENARIO,
                             tree = tree, nodes = nodes),
  error = function(e) {{
    cat(sprintf("{ERROR_PREFIX}%s\\n", conditionMessage(e)))
    quit(status = 1)
  }}
)

target <- result[[paste0("scenario.", sub("^S", "", SCENARIO))]]
ape::write.tree(target, file = OUT)

labels <- ape::read.tree(OUT)$tip.label
cat(sprintf("{TIPS_PREFIX}%d\\n", length(labels)))
for (missing_name in setdiff(norm(species), labels)) {{
  cat(sprintf("{MISSING_PREFIX}%s\\n", missing_name))
}}
'''


_QUOTED = re.compile(r'"([^"]*)"')
_ARRAY_LINE = re.compile(r"^\[\d+\]\s")


def parse_missing(stdout: str) -> list[str]:
    """未入树物种清单。**两条来源，以脚本汇总行为准**：

    1. 我们自己的脚本打印的 ``SEQTOOLKIT_MISSING`` 行——它由脚本读回 treefile 的
       叶标签与输入求差算出，可信度最高
    2. 兜底：解析 ``phylo.maker`` 自己打印的 ``Note: N taxa fail to be binded to the
       tree,`` 及其后的物种名行。这段文本是给人看的，格式可能随包版本变化，
       因此只在前者缺失时使用
    """
    lines = stdout.splitlines()
    direct = [line[len(MISSING_PREFIX):].strip()
              for line in lines if line.startswith(MISSING_PREFIX)]
    if direct:
        return [name for name in direct if name]

    found: list[str] = []
    collecting = False
    for line in lines:
        stripped = line.strip()
        if "fail to be binded to the tree" in stripped:
            collecting = True
            for name in _QUOTED.findall(stripped):
                if "fail to be binded" not in name:
                    found.append(name)
            continue
        if collecting:
            if not _ARRAY_LINE.match(stripped):
                break
            found.extend(_QUOTED.findall(stripped))
    return found


def parse_tip_count(stdout: str) -> int | None:
    """脚本汇总行里的入树叶节点数；没有则返回 None。"""
    for line in stdout.splitlines():
        if line.startswith(TIPS_PREFIX):
            try:
                return int(line[len(TIPS_PREFIX):].strip())
            except ValueError:
                return None
    return None


def parse_error(stdout: str, stderr: str, returncode: int | None = None) -> str:
    """从输出里提取最有用的错误文本：优先脚本标记，其次 stderr 尾部。

    **绝不返回空串**：实测 R 被外部结束（任务管理器结束进程、内存不足被杀）时退出码非零
    而两条管道都没有任何输出，旧实现返回 ``''``，界面上的提示就只剩「生成失败: 」
    ——等于什么都没说。
    """
    for line in (stdout or "").splitlines():
        if line.startswith(ERROR_PREFIX):
            return line[len(ERROR_PREFIX):].strip()
    tail = "\n".join((stderr or "").splitlines()[-30:]).strip()
    message = tail or (stdout or "").strip()[-2000:]
    if message:
        return message
    if returncode is None:
        return "R 已结束但没有任何输出"
    return f"R 以退出码 {returncode} 结束且没有任何输出（进程可能被外部结束）"


@dataclass
class TreeNode:
    """Newick 节点。叶节点 ``children`` 为空。"""

    label: str = ""
    length: float | None = None
    children: list["TreeNode"] = field(default_factory=list)


def parse_newick(text: str) -> TreeNode:
    """极简 Newick 解析：分支长度、内部节点标签、单引号标签（``''`` 转义）。

    只服务界面预览，不做树比较等高级功能；畸形输入抛 ``ValueError``。
    """
    source = (text or "").strip()
    if not source:
        raise ValueError("Newick 内容为空")
    pos = 0
    size = len(source)

    def skip_ws() -> None:
        nonlocal pos
        while pos < size and source[pos].isspace():
            pos += 1

    def read_label() -> str:
        nonlocal pos
        skip_ws()
        if pos < size and source[pos] == "'":
            pos += 1
            buffer: list[str] = []
            while pos < size:
                if source[pos] == "'":
                    if pos + 1 < size and source[pos + 1] == "'":
                        buffer.append("'")
                        pos += 2
                        continue
                    pos += 1
                    break
                buffer.append(source[pos])
                pos += 1
            return "".join(buffer)
        start = pos
        while pos < size and source[pos] not in "(),:;":
            pos += 1
        return source[start:pos].strip()

    def read_length() -> float | None:
        nonlocal pos
        skip_ws()
        if pos < size and source[pos] == ":":
            pos += 1
            start = pos
            while pos < size and source[pos] not in "(),;":
                pos += 1
            try:
                return float(source[start:pos])
            except ValueError:
                return None
        return None

    def parse_node() -> TreeNode:
        nonlocal pos
        skip_ws()
        node = TreeNode()
        if pos < size and source[pos] == "(":
            pos += 1
            while True:
                child = parse_node()
                if not child.children and not child.label:
                    # "(A,,B)" 这类空元素必须报错：放过它会渲染出一个空标签的叶节点
                    raise ValueError("Newick 里有空元素")
                node.children.append(child)
                skip_ws()
                if pos < size and source[pos] == ",":
                    pos += 1
                    continue
                break
            if pos >= size or source[pos] != ")":
                # 少了右括号通常意味着文件被截断（进程被杀、磁盘写满）
                raise ValueError("Newick 括号不匹配（文件可能被截断）")
            pos += 1
            node.label = read_label()
            node.length = read_length()
        else:
            node.label = read_label()
            node.length = read_length()
        return node

    root = parse_node()
    skip_ws()
    if pos < size and source[pos] == ";":
        pos += 1
    skip_ws()
    if pos < size:
        raise ValueError(f"Newick 尾部有多余内容: {source[pos:pos + 20]!r}")
    if not root.label and not root.children:
        raise ValueError("Newick 解析结果为空")
    return root


@dataclass(frozen=True)
class LayoutNode:
    """绝对坐标的布局节点（cladogram：x 只取决于深度）。"""

    x: float
    y: float
    label: str
    children: tuple["LayoutNode", ...] = ()


def layout_cladogram(root: TreeNode, *, leaf_gap: float = 18.0,
                     level_gap: float = 180.0) -> LayoutNode:
    """把树排成拓扑布局：叶节点按中序均匀铺开，内部节点取子节点 y 的中点。"""
    counter = [0]

    def walk(node: TreeNode, depth: int) -> LayoutNode:
        if not node.children:
            y = counter[0] * leaf_gap
            counter[0] += 1
            return LayoutNode(depth * level_gap, y, node.label, ())
        kids = tuple(walk(child, depth + 1) for child in node.children)
        ys = [kid.y for kid in kids]
        return LayoutNode(depth * level_gap, (min(ys) + max(ys)) / 2.0,
                          node.label, kids)

    return walk(root, 0)


def count_nodes(node: LayoutNode | TreeNode) -> tuple[int, int]:
    """返回 ``(总节点数, 叶节点数)``，用于给 Canvas 预估尺寸。"""
    total = 1
    leaves = 0 if node.children else 1
    for child in node.children:
        child_total, child_leaves = count_nodes(child)
        total += child_total
        leaves += child_leaves
    return total, leaves


INSTALL_HINT = (
    "功能 7 需要本机安装 R 与 V.PhyloMaker2 包（均为可选外部依赖，不随本程序打包）：\n"
    "1) 安装 R：https://cran.r-project.org/bin/windows/base/（默认安装即可，无需管理员权限）\n"
    "2) 安装 R 包：打开 R，依次执行\n"
    '     install.packages("remotes")\n'
    '     remotes::install_github("jinyizju/V.PhyloMaker2")\n'
    "3) 回到本程序，在「设置」页填写 Rscript.exe 的完整路径，或点「检测」自动查找。"
)


@dataclass
class PhyloRun:
    """一次 R 调用的结果。"""

    returncode: int
    stdout: str
    stderr: str
    tree_path: str
    missing: list[str] = field(default_factory=list)
    tip_count: int | None = None
    # 临时 .R 脚本没能删掉时的**残留路径**（空串表示删干净了）。取消/超时路径上没有
    # 本对象可返回，那条路径靠 run_phylo 的 ``warn`` 回调报出去。
    leaked_script: str = ""


def _spawn(argv: Sequence[str], popen: Callable | None = None):
    """启动 Rscript。**模块级接缝**：测试替换 ``popen`` 或改写 ``argv`` 即可离线断言
    启动/取消行为，不必在本机装 R。
    """
    factory = popen if popen is not None else subprocess.Popen
    flags = CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return factory(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                   encoding="utf-8", errors="replace", creationflags=flags)


def _kill_process_tree(process, *, runner: Callable | None = None) -> str | None:
    """终止**整棵** R 进程树并回收主进程；无法确认时返回一段可读说明，正常返回 None。

    Windows 上 ``Rscript.exe`` 只是个启动器：实测一次 ``Popen([Rscript, slow.R])`` 会同时
    看到**三个** Rscript.exe（初测记的是两个，复审用 ``tasklist`` 复核为三个），被
    ``Popen`` 拿到的那个只是外壳，真正的 R 是它的子进程。
    只 ``process.kill()`` 外壳的话，孤儿 R 会把 ``Sys.sleep`` 睡完、把 treefile 写进磁盘
    （实测：报「操作已取消」之后 8 秒树文件照样落盘，且没有任何提示），还会一直占着临时
    ``.R``，使 ``os.unlink`` 抛 ``[WinError 32]``——每次取消都在 ``%TEMP%`` 里多一个脚本。

    Windows 走 ``taskkill /F /T /PID``（``/T`` 才是"杀整棵树"）；taskkill 不存在/失败时
    退回 ``process.kill()``。非 Windows 平台直接走退回路径，保持可移植。
    """
    note = None
    killed_tree = False
    if os.name == "nt":
        pid = getattr(process, "pid", None)
        if pid:
            kill = runner if runner is not None else subprocess.run
            try:
                result = kill(["taskkill", "/F", "/T", "/PID", str(pid)],
                              capture_output=True, timeout=KILL_TIMEOUT)
                killed_tree = getattr(result, "returncode", 1) == 0
                if not killed_tree:
                    note = f"taskkill 未能结束进程树（pid {pid}）"
            except Exception as error:  # noqa: BLE001 taskkill 缺失/超时都不能让取消路径炸掉
                note = f"taskkill 调用失败（{error}）"
    if not killed_tree:
        try:
            process.kill()
        except OSError as error:
            note = f"{note}；结束进程也失败（{error}）" if note else f"结束进程失败（{error}）"
    try:
        process.wait(timeout=KILL_TIMEOUT)
    except Exception as error:  # noqa: BLE001 收尾失败不该覆盖正在抛出的取消/超时
        extra = f"R 进程在 {KILL_TIMEOUT:.0f} 秒内没有退出（{error}）"
        note = f"{note}；{extra}" if note else extra
    return note


def _remove_script(path: str) -> str | None:
    """删掉临时 ``.R``：成功返回 None，失败返回失败原因。**绝不静默吞掉**。"""
    try:
        os.unlink(path)
    except OSError as error:
        return str(error)
    return None


def run_phylo(rscript: str, species: Sequence[str], system: str, scenario: str,
              tree_path: str, *, popen: Callable | None = None,
              timeout: float = DEFAULT_TIMEOUT, cancel=None,
              poll_interval: float = 0.2,
              progress: Callable[[str], None] | None = None,
              warn: Callable[[str], None] | None = None) -> PhyloRun:
    """渲染脚本 → 调 Rscript → 解析输出。

    用 ``Popen`` + 轮询而不是 ``subprocess.run``：后者无法在运行中响应取消与超时，
    而实测一次建树要 16 秒以上、大列表会显著更久，用户必须能中途放弃。

    ``tree_path`` 已存在时让位 ``_1``、``_2``…（:func:`pipeline.resolve_output_path`），
    **绝不覆盖**：``ape::write.tree`` 是原地覆盖，而界面上的默认输出名恰好就是上一轮的
    文件名，不设防就会把用户上一次的树无声抹掉（B8 用真实 R 复现过）。**渲染进 R 脚本的
    路径、磁盘上的落点、以及 :attr:`PhyloRun.tree_path` 三者都是让位后的路径**——三者
    必须一致，否则调用方会拿着一个不存在的路径去找树。

    ``warn`` 是可选的"要告诉用户但不算失败"的通道（GUI 传 ``ctx.warn``）：临时脚本删不掉、
    进程树没能确认杀干净这类事都走它。取消/超时路径上没有 :class:`PhyloRun` 可返回，
    只有这个回调能把消息带到界面上。
    """
    tree_path = resolve_output_path(tree_path)
    script_text = render_script(species, system, scenario, tree_path)
    handle = tempfile.NamedTemporaryFile("wt", suffix=".R", delete=False,
                                         encoding="utf-8", newline="\n")
    script_path = handle.name
    leaked: list[str] = []

    def _report(message: str) -> None:
        if warn is not None:
            warn(message)

    try:
        handle.write(script_text)
        handle.close()
        if progress is not None:
            progress(f"正在调用 R（{len(species)} 个物种）")
        try:
            process = _spawn([rscript, script_path], popen)
        except OSError as error:
            # R 在「检测通过」与「实际运行」之间被卸载/改名：裸 OSError 不该冒到界面层
            raise PhyloError(f"无法启动 Rscript（{rscript}）：{error}") from error
        started = time.monotonic()
        # 必须**并发**排空管道：R 在写完树文件之后才逐条 cat 未入树物种，Windows 匿名
        # 管道缓冲只有几 KB，几十条就能写满。写满后 R 阻塞在 cat、poll() 永远返回 None，
        # 轮询循环会一路走到超时分支，把一个**已经成功**的进程杀掉并报假超时
        # ——而 treefile 其实早已写好。用守护线程持续读，管道就不会成为背压。
        collected: dict[str, str] = {}

        def _drain() -> None:
            try:
                out, err = process.communicate()
            except Exception as error:  # noqa: BLE001 读失败不该覆盖已经拿到的退出信息
                # 异常文本**并进 stderr**而不是丢掉：两条管道都空时，这句话就是界面上
                # 唯一能说明"到底为什么没有任何输出"的证据。
                out, err = "", f"（读取 R 输出失败：{error!r}）"
            collected["stdout"] = out or ""
            collected["stderr"] = err or ""

        reader = threading.Thread(target=_drain, daemon=True)
        reader.start()
        try:
            while process.poll() is None:
                if cancel is not None and cancel.is_set():
                    _report_if_any(_kill_process_tree(process), _report)
                    raise OperationCancelled("操作已取消")
                if time.monotonic() - started > timeout:
                    _report_if_any(_kill_process_tree(process), _report)
                    raise PhyloError(f"R 执行超时（已超过 {timeout:.0f} 秒），已终止")
                time.sleep(poll_interval)
        finally:
            reader.join(timeout=5.0)
        stdout = collected.get("stdout", "")
        stderr = collected.get("stderr", "")
    finally:
        reason = _remove_script(script_path)
        if reason is not None:
            # 残留必须说出来：用户与日志都要知道 %TEMP% 里多了什么（实测取消时孤儿 R
            # 占着脚本 ⇒ WinError 32，旧实现 except OSError: pass 把它全吞了）
            leaked.append(script_path)
            _report(f"临时 R 脚本未能删除，残留在临时目录：{script_path}（{reason}）")

    returncode = getattr(process, "returncode", None)
    if returncode not in (0, None):
        raise PhyloError(parse_error(stdout or "", stderr or "", returncode))
    if not os.path.exists(tree_path):
        raise PhyloError(f"R 已结束但没有产出树文件: {tree_path}")
    return PhyloRun(returncode=int(returncode or 0), stdout=stdout or "",
                    stderr=stderr or "", tree_path=tree_path,
                    missing=parse_missing(stdout or ""),
                    tip_count=parse_tip_count(stdout or ""),
                    leaked_script=leaked[0] if leaked else "")


def _report_if_any(note: str | None, report: Callable[[str], None]) -> None:
    """把 :func:`_kill_process_tree` 的"没能确认杀干净"说明转给 warn 回调。"""
    if note:
        report(f"{note}；残留的 R 子进程可能仍在运行并把树文件写到磁盘")


@dataclass(frozen=True)
class REnvironment:
    """R 环境检测结果。``message`` 直接展示给用户。"""

    rscript: str | None
    version: str
    has_package: bool
    message: str


def detect_environment(rscript_path: str = "", *, runner: Callable | None = None,
                       which: Callable | None = None, program_files: str | None = None,
                       local_app_data: str | None = None) -> REnvironment:
    """检测 Rscript 与 V.PhyloMaker2 是否可用，并给出人话结论。

    检测命令只做两件事：打印 R 版本、打印包是否已装——不去加载巨型系统树，
    否则每次点「检测」都要等十几秒。
    """
    import subprocess

    rscript = locate_rscript(rscript_path, which=which, program_files=program_files,
                             local_app_data=local_app_data)
    if not rscript:
        return REnvironment(None, "", False,
                            "未找到 Rscript。\n" + INSTALL_HINT)

    call = runner if runner is not None else subprocess.run
    probe = ('cat(paste(R.version$major, R.version$minor, sep="."), "\\n"); '
             'cat(requireNamespace("V.PhyloMaker2", quietly=TRUE), "\\n")')
    try:
        result = call([rscript, "-e", probe], capture_output=True, text=True,
                      encoding="utf-8", errors="replace", timeout=120)
        lines = [line.strip() for line in (result.stdout or "").splitlines()
                 if line.strip()]
    except Exception as error:  # noqa: BLE001 检测失败不能把界面搞崩
        return REnvironment(rscript, "", False,
                            f"Rscript 已找到但无法执行：{error}\n{INSTALL_HINT}")

    if getattr(result, "returncode", 0) not in (0, None):
        # 非零退出时不能报成「缺少 V.PhyloMaker2 包」：那会把诊断指向错误方向
        first = next((line.strip() for line in (result.stderr or "").splitlines()
                      if line.strip()), "")
        return REnvironment(
            rscript, "", False,
            f"Rscript 执行失败（退出码 {result.returncode}）：{first}\n" + INSTALL_HINT)

    version = lines[0] if lines else ""
    has_package = len(lines) > 1 and lines[1].upper().startswith("TRUE")
    if has_package:
        message = f"R {version} 与 V.PhyloMaker2 就绪（{rscript}）"
    else:
        message = (f"已找到 R {version}（{rscript}），但缺少 V.PhyloMaker2 包。\n"
                   + INSTALL_HINT)
    return REnvironment(rscript, version, has_package, message)
