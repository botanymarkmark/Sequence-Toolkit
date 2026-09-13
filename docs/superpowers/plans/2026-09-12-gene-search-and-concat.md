# 周期 1 实施计划：按基因名检索下载、序列统计、序列拼接

> **面向 Agent 执行者：** 必需子技能：使用 superpower-subagent-driven-development（推荐）或 superpower-executing-plans 按任务逐项执行本计划。步骤使用复选框（`- [ ]`）语法进行跟踪。

**目标：** 在序列工具箱中新增「按基因名检索下载」（物种 × 基因组合检索、排除完整基因组、以 `物种_基因.fasta` 命名、下载后回填 GC）与「序列拼接」两个面板，并交付可复用的序列统计纯函数。

**架构：** 逻辑与界面严格分离：`stats.py` / `gene_query.py` / `concat.py` 三个纯函数模块承载全部可测逻辑（不 import tkinter），`gui/tab_gene.py` / `gui/tab_concat.py` 只做控件与线程编排。下载复用既有的 `NcbiClient.download()`（分批、逐条重试、缺失归因、原子写出、绝不覆盖），命名通过给 `DownloadOptions` 新增的 `name_resolver` 注入，**按基因分组**各调用一次，从而回避"登录号 → 基因"反查在双位点记录上的无解问题。

**技术栈：** Python 3.12 标准库（`tkinter`/`ttk`、`dataclasses`、`urllib`、`threading`、`re`、`csv`）；pytest；PyInstaller（仅打包验证，不新增依赖）。

**规格：** `docs/superpowers/specs/2026-09-12-gene-search-and-concat-design.md`（本计划实现的规格，执行者必须同时阅读）

## 全局约束

- 运行时零第三方依赖：周期 1 全部代码只用 Python 标准库（`tkinter`/`ttk` 属标准库）。
- 目标平台 Windows 10/11 x64；单文件 exe 体积不超 20 MB（周期 1 不引入新依赖，体积应保持不变）。
- 纯函数模块 `seq_toolkit/stats.py`、`seq_toolkit/gene_query.py`、`seq_toolkit/concat.py` **不得 import tkinter**。
- 所有耗时操作必须经 `App.run_job(target, ...)` 在后台线程执行；`target(ctx)` 内**不得触碰任何 Tk 控件或 Tk 变量**，控件取值必须在主线程取完快照后再定义 job。
- 绝不静默覆盖：目标文件已存在时让位 `_1`、`_2` 并记 WARN。
- 绝不静默：任何被跳过、被排除、未命中的数据都必须出现在日志或界面上。
- 单条/单组合失败不得中断整批。
- 文本输出统一 UTF-8（`newline="\n"`）；CSV 导出统一 `utf-8-sig`。
- 所有 Tk 变量必须显式传 `master=<父控件>`。
- UI 文案一律中文；提交信息用中文约定式提交（`feat:` / `fix:` / `test:` / `docs:` / `chore:`）。
- 每个任务结束时 `python -m pytest` 必须全绿；**不得**改动 `naming.py`、`model.py`、`pipeline.py`、`genbank_io.py`、`fasta_io.py`、`settings.py`、`applog.py`、`format_detect.py`、`textio.py`。

## 文件结构

**新建（源码）**

| 文件 | 职责 |
|---|---|
| `seq_toolkit/stats.py` | 序列统计：长度 / GC / AT / N 计数与占比。纯函数 |
| `seq_toolkit/gene_query.py` | 基因表与别名归一、检索式构造、完整基因组判据、组合展开、命名构造、检索与下载编排。纯逻辑（依赖注入 client） |
| `seq_toolkit/concat.py` | 拼接长度计算与记录合成。纯函数 |
| `seq_toolkit/gui/tab_gene.py` | 「按基因检索」子页（含 `build_subpanel`） |
| `seq_toolkit/gui/tab_concat.py` | 「序列拼接」标签页（含 `build`） |

**新建（测试）**

| 文件 | 职责 |
|---|---|
| `tests/test_stats.py` | stats 单元测试 |
| `tests/test_gene_query.py` | gene_query 单元测试 |
| `tests/test_concat.py` | concat 单元测试 |
| `tests/test_gui_tab_gene.py` | 基因检索子页 GUI 测试 |
| `tests/test_gui_tab_concat.py` | 拼接面板 GUI 测试 |
| `tests/fakes_ncbi.py` | 测试替身：`FakeGeneClient`、`make_record`、`make_summary`（被多个测试模块复用） |

**修改**

| 文件 | 位置 | 改动 |
|---|---|---|
| `tests/test_ncbi.py` | 第 170–183 行 | 时间轴断言加容差（任务 1） |
| `seq_toolkit/ncbi.py` | `DownloadOptions`、`DownloadReport`、`download()`、`_pending_accessions()` | `name_resolver`、`records`（任务 8） |
| `seq_toolkit/gui/widgets.py` | `CheckboxTable.__init__` / `set_rows` | 可选 `key_of`（任务 12） |
| `seq_toolkit/gui/app.py` | `TAB_SPECS` | 末尾追加「序列拼接」（任务 14） |
| `seq_toolkit/gui/tab_search.py` | `build()` 开头 | 包一层子 Notebook（任务 18） |
| `README.md`、`README.zh-CN.md`、`docs/acceptance.md` | — | 文档与验收记录（任务 19） |

---

### 任务 1：修复既有失败测试（计量容差）

**文件：**
- 修改：`tests/test_ncbi.py:170-183`
- 测试：`tests/test_ncbi.py::test_adjacent_requests_hold_the_interval_with_the_default_clock`

**接口：**
- 依赖输入：无
- 对外产出：无（只为后续任务的"全绿"提供可信基线）

- [ ] **步骤 1：复现失败并记录实测缺口**

运行：`python -m pytest tests/test_ncbi.py::test_adjacent_requests_hold_the_interval_with_the_default_clock`

预期：FAIL。失败信息里 `gaps` 形如 `['1.0', '0.3333333333139308']`，比 `1/3` 小约 `1.9e-11`。这不是限速缺陷（`test_adjacent_requests_hold_the_interval_with_an_injected_clock` 精确通过），而是该用例用「真实单调时钟 + 仅记录型 sleeper」重建时间轴时的浮点/计量残差，而断言是零容差。

- [ ] **步骤 2：给断言加容差**

把 `tests/test_ncbi.py` 中该用例的断言：

```python
    gaps = _adjacent_gaps(opener)
    assert all(gap >= 1 / 3 for gap in gaps)
```

改为：

```python
    gaps = _adjacent_gaps(opener)
    # 容差 1e-9 秒：本用例的时间轴是"真实单调时钟 + 仅记录型 sleeper 的承诺值"
    # 重建出来的，与限速器内部使用的 _clock_source() + _clock_credit 差在
    # 亚纳秒量级（实测缺口 1.94e-11 秒）。断言零容差会让这条用例稳定红。
    # 硬约束仍被钉住：注入假时钟的同场景用例是精确比较，无容差。
    assert all(gap >= 1 / 3 - 1e-9 for gap in gaps)
```

- [ ] **步骤 3：确认该用例通过**

运行：`python -m pytest tests/test_ncbi.py::test_adjacent_requests_hold_the_interval_with_the_default_clock`

预期：PASS。

- [ ] **步骤 4：确认整个测试套件全绿**

运行：`python -m pytest`

预期：全部 PASS，无 FAILED。

- [ ] **步骤 5：提交**

```bash
git add tests/test_ncbi.py
git commit -m "fix(test): 时间轴重建断言加 1e-9 容差，消除 1.94e-11 秒的浮点缺口"
```

---

### 任务 2：`stats.py` 核心统计（GC 分母不含 N）

**文件：**
- 新建：`seq_toolkit/stats.py`
- 测试：`tests/test_stats.py`

**接口：**
- 依赖输入：无
- 对外产出：`Stats` 与 `sequence_stats(seq: str) -> SeqStats`；`SeqStats` 字段 `length: int`、`gc: float | None`、`at: float | None`、`n_count: int`、`n_ratio: float | None`

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_stats.py`：

```python
"""序列统计的单元测试。纯函数，不需要 Tk 或网络。"""

import pytest

from seq_toolkit.stats import SeqStats, sequence_stats


def test_gc_denominator_excludes_n():
    # 4 个 ATGC + 6 个 N：GC = 2/4 = 50.00%，N 占比 = 6/10 = 60.00%
    stats = sequence_stats("ATGC" + "NNNNNN")
    assert stats.length == 10
    assert stats.gc == 50.0
    assert stats.at == 50.0
    assert stats.n_count == 6
    assert stats.n_ratio == 60.0


def test_iupac_codes_do_not_enter_the_gc_denominator():
    # R/Y/S/W 既不是 ATGC 也不是 N：不进 GC 分母，也不计入 n_count
    stats = sequence_stats("GGCCRYSW")
    assert stats.length == 8
    assert stats.gc == 100.0
    assert stats.at == 0.0
    assert stats.n_count == 0
    assert stats.n_ratio == 0.0


def test_gc_and_at_always_sum_to_hundred():
    stats = sequence_stats("AAAG")
    assert stats.gc + stats.at == 100.0


def test_percentages_round_to_two_decimals():
    assert sequence_stats("AAAG").gc == 25.0
    assert sequence_stats("AAG").gc == 33.33      # 1/3 → 33.333… 四舍五入
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_stats.py`

预期：FAIL，提示 `ModuleNotFoundError: No module named 'seq_toolkit.stats'`。

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/stats.py`：

```python
"""序列统计：长度、GC、AT、N 计数与占比。纯函数，不做任何 IO。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeqStats:
    """一条序列的统计结果。

    ``gc`` / ``at`` / ``n_ratio`` 为 ``None`` 表示**分母为 0**（空序列，或全是不确定
    碱基），界面显示 ``—``。它与 ``0.00`` 含义不同：后者是"算出来确实是 0"。
    """

    length: int
    gc: float | None
    at: float | None
    n_count: int
    n_ratio: float | None


def sequence_stats(seq: str) -> SeqStats:
    """统计一条序列。

    **GC/AT 的分母是 A+T+G+C，不含 N 与其它 IUPAC 模糊代码**：若分母含 N，
    一条 50% N 的序列 GC 会被腰斩，序列之间失去可比性。
    ``n_count`` 只数 ``N``；因此当序列含 R/Y/S/W/K/M/B/D/H/V 时，
    ``length > A+T+G+C+N`` 是刻意设计，不是漏算。
    """
    upper = (seq or "").upper()
    length = len(upper)
    if length == 0:
        return SeqStats(0, None, None, 0, None)

    at_count = upper.count("A") + upper.count("T")
    gc_count = upper.count("G") + upper.count("C")
    n_count = upper.count("N")
    denominator = at_count + gc_count
    if denominator == 0:
        gc = at = None
    else:
        gc = round(gc_count / denominator * 100, 2)
        at = round(at_count / denominator * 100, 2)
    return SeqStats(length, gc, at, n_count, round(n_count / length * 100, 2))
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_stats.py`

预期：4 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/stats.py tests/test_stats.py
git commit -m "feat(stats): 序列统计纯函数，GC 分母不含 N 与其它 IUPAC 代码"
```

---

### 任务 3：`stats.py` 边界情况与界面格式化

**文件：**
- 修改：`seq_toolkit/stats.py`
- 测试：`tests/test_stats.py`

**接口：**
- 依赖输入：`stats.SeqStats`、`stats.sequence_stats()`（任务 2）
- 对外产出：`format_stats(stats: SeqStats) -> tuple[str, str, str, str]`，返回 `(长度, GC%, AT%, N 计数与占比)`，未定义处为 `—`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_stats.py` 末尾追加：

```python
def test_empty_sequence_has_no_division_by_zero():
    stats = sequence_stats("")
    assert stats.length == 0
    assert stats.gc is None and stats.at is None and stats.n_ratio is None
    assert stats.n_count == 0


def test_all_n_sequence_has_undefined_gc():
    stats = sequence_stats("nnnn")
    assert stats.length == 4
    assert stats.gc is None and stats.at is None
    assert stats.n_count == 4
    assert stats.n_ratio == 100.0


def test_lowercase_and_uracil_are_handled():
    # A、T 计 2；G 计 1；U 既不是 ATGC 也不是 N，不进 GC 分母也不计入 n_count。
    # 因此分母是 3 而不是长度 4。用不对称的 66.67/33.33 而不是 50/50：
    # 对称的期望值会让"实现把 AT 与 GC 计数写反"这类缺陷溜过去。
    stats = sequence_stats("atgu")
    assert stats.length == 4
    assert stats.at == pytest.approx(66.67, abs=0.001)
    assert stats.gc == pytest.approx(33.33, abs=0.001)
    assert stats.n_count == 0


def test_format_stats_renders_dash_for_undefined_values():
    assert format_stats(sequence_stats("")) == ("0", "—", "—", "0")


def test_format_stats_renders_percentages_and_counts():
    assert format_stats(sequence_stats("ATGC" + "NN")) == (
        "6", "50.00", "50.00", "2（33.33%）")
```

并把该文件顶部的导入改为：

```python
from seq_toolkit.stats import SeqStats, format_stats, sequence_stats
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_stats.py`

预期：FAIL，提示 `ImportError: cannot import name 'format_stats'`。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/stats.py` 末尾追加：

```python
def _percent(value: float | None) -> str:
    """百分比文本；``None``（分母为 0）显示破折号而不是 0.00。"""
    return "—" if value is None else f"{value:.2f}"


def format_stats(stats: SeqStats) -> tuple[str, str, str, str]:
    """界面用的四个字符串：(长度, GC%, AT%, N 计数与占比)。

    空序列不给 N 加括号：``0（—%）`` 是无意义的写法。
    """
    if stats.n_ratio is None:
        n_text = f"{stats.n_count}"
    else:
        n_text = f"{stats.n_count}（{_percent(stats.n_ratio)}%）"
    return (f"{stats.length:,}", _percent(stats.gc), _percent(stats.at), n_text)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_stats.py`

预期：9 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/stats.py tests/test_stats.py
git commit -m "feat(stats): 空序列/全 N/含 U 的边界处理与界面格式化"
```

---

### 任务 4：`gene_query.py` 基因表与别名归一化

**文件：**
- 新建：`seq_toolkit/gene_query.py`
- 测试：`tests/test_gene_query.py`

**接口：**
- 依赖输入：无
- 对外产出：`GeneEntry`（frozen dataclass，字段 `name`、`aliases`、`clause`、`note`）、`GENES`、`normalize_gene_key(text) -> str`

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_gene_query.py`：

```python
"""基因表、检索式、完整基因组判据、命名与编排的单元测试。离线，无需 Tk。"""

from seq_toolkit.gene_query import (
    GENES,
    GeneEntry,
    normalize_gene_key,
)


def test_every_builtin_gene_is_reachable_by_its_own_name():
    for entry in GENES:
        assert normalize_gene_key(entry.name) != ""
        assert isinstance(entry, GeneEntry)


def test_normalization_ignores_case_space_dot_hyphen_slash():
    for text in ("ITS", "its", "I.T.S", "i t s"):
        assert normalize_gene_key(text) == "its"
    assert normalize_gene_key("trnL-F") == normalize_gene_key("trnL F") == "trnlf"
    assert normalize_gene_key("rbc-l") == "rbcl"


def test_its_clause_is_the_phrase_not_the_gene_field():
    """实测结论：ITS[Gene] 命中恒为 0，ITS 只能走 internal transcribed spacer 短语。"""
    entry = next(e for e in GENES if e.name == "ITS")
    assert entry.clause == '"internal transcribed spacer"[All Fields]'


def test_spacer_genes_have_no_clause():
    """实测：trnL-F / psbA-trnH / rpl32-trnL / trnL 在 GenBank 没有可用检索字段。"""
    for name in ("trnL", "trnL-F", "psbA-trnH", "rpl32-trnL"):
        entry = next(e for e in GENES if e.name == name)
        assert entry.clause == ""
        assert entry.note != ""
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gene_query.py`

预期：FAIL，提示 `ModuleNotFoundError: No module named 'seq_toolkit.gene_query'`。

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/gene_query.py`：

```python
"""基因名 → NCBI 检索式映射，以及检索/下载编排。纯逻辑，不 import tkinter。

**内置检索式全部经过实测标定**（2026-09-12，探针脚本 gene_query_probe.py）：
``ITS[Gene]`` 在三个代表物种上命中恒为 0，ITS 只能通过
``"internal transcribed spacer"`` 这个短语检索；trnL / trnL-F / psbA-trnH /
rpl32-trnL 在 GenBank 里没有可用检索字段，多种写法实测命中均为 0，
因此 ``clause`` 留空并在界面上直接给出说明，而不是发起一次必然为空的检索。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 归一化时删除的字符：空白、句点、连字符、下划线、斜杠
_NORMALIZE_DROP = re.compile(r"[\s.\-_/]+")


@dataclass(frozen=True)
class GeneEntry:
    """一个基因的检索定义。

    ``clause`` 为空串表示**当前没有可用检索字段**（实测命中恒为 0），
    此时界面必须直接给出 ``note`` 里的说明，绝不发起检索。
    """

    name: str
    aliases: tuple[str, ...]
    clause: str
    note: str = ""


GENES: tuple[GeneEntry, ...] = (
    GeneEntry("ITS",
              ("its", "internal transcribed spacer",
               "internaltranscribedspacer", "its1-5.8s-its2"),
              '"internal transcribed spacer"[All Fields]'),
    GeneEntry("ITS1", ("its1", "internal transcribed spacer 1"),
              '"internal transcribed spacer 1"[All Fields]'),
    GeneEntry("ITS2", ("its2", "internal transcribed spacer 2"),
              '"internal transcribed spacer 2"[All Fields]'),
    GeneEntry("matK", ("matk", "mat k"), "matK[Gene]"),
    GeneEntry("rbcL", ("rbcl", "rbc l"), "rbcL[Gene]"),
    GeneEntry("ndhF", ("ndhf", "ndh f"), "ndhF[Gene]"),
    GeneEntry("ycf1", ("ycf1", "ycf 1", "ycf-1"), "ycf1[Gene]"),
    GeneEntry("trnL", ("trnl", "trn l"), "",
              "GenBank 没有 trnL 的检索字段，实测命中为 0"),
    GeneEntry("trnL-F", ("trnlf", "trnl f", "trnl-trnf", "trnl/trnf"), "",
              "GenBank 没有 trnL-F 的检索字段，实测三种写法命中均为 0"),
    GeneEntry("psbA-trnH", ("psbath", "psba-trnh", "psba trnh"), "",
              "GenBank 没有 psbA-trnH 的检索字段，实测命中为 0 或个位数"),
    GeneEntry("rpl32-trnL", ("rpl32trnl", "rpl32 trnl", "rpl32-trnl uag"), "",
              "GenBank 没有 rpl32-trnL 的检索字段，实测命中为 0"),
)


def normalize_gene_key(text: str) -> str:
    """别名归一化键：转小写并删除空白、句点、连字符、下划线、斜杠。"""
    return _NORMALIZE_DROP.sub("", (text or "")).lower()


_BY_KEY: dict[str, GeneEntry] = {
    normalize_gene_key(alias): entry
    for entry in GENES
    for alias in (entry.name,) + entry.aliases
}
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gene_query.py`

预期：4 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gene_query.py tests/test_gene_query.py
git commit -m "feat(gene_query): 内置基因表与别名归一化（检索式均经实测标定）"
```

---

### 任务 5：`gene_query.py` 基因解析与检索式构造

**文件：**
- 修改：`seq_toolkit/gene_query.py`
- 测试：`tests/test_gene_query.py`

**接口：**
- 依赖输入：`GENES`、`normalize_gene_key()`（任务 4）
- 对外产出：`resolve_gene(text: str) -> GeneEntry`、`is_unsearchable(entry: GeneEntry) -> bool`、`build_query(species: str, entry: GeneEntry) -> str`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gene_query.py` 末尾追加，并把它顶部的导入改为：

```python
from seq_toolkit.gene_query import (
    GENES,
    GeneEntry,
    build_query,
    is_unsearchable,
    normalize_gene_key,
    resolve_gene,
)
```

```python
def test_alias_resolves_to_canonical_entry():
    assert resolve_gene("internal transcribed spacer").name == "ITS"
    assert resolve_gene("mat K").name == "matK"
    assert resolve_gene("rbcl").name == "rbcL"


def test_unknown_gene_becomes_free_text_entry():
    entry = resolve_gene("rpoC1")
    assert entry.name == "rpoC1"
    assert entry.clause == "rpoC1[All Fields]"
    assert entry.note != ""


def test_empty_gene_name_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        resolve_gene("   ")


def test_is_unsearchable_matches_missing_clause():
    assert is_unsearchable(resolve_gene("trnL-F")) is True
    assert is_unsearchable(resolve_gene("matK")) is False


def test_build_query_quotes_species_and_appends_clause():
    assert (build_query("Salsola pellucida", resolve_gene("matK"))
            == '"Salsola pellucida"[Organism] AND matK[Gene]')


def test_build_query_refuses_unsearchable_gene():
    import pytest
    with pytest.raises(ValueError):
        build_query("Salsola pellucida", resolve_gene("trnL-F"))


def test_build_query_rejects_empty_species():
    import pytest
    with pytest.raises(ValueError):
        build_query("  ", resolve_gene("matK"))
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gene_query.py`

预期：FAIL，提示 `ImportError: cannot import name 'build_query'`。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/gene_query.py` 的 `_BY_KEY` 定义之后追加：

```python
def resolve_gene(text: str) -> GeneEntry:
    """把用户输入解析成基因条目；未收录时构造自由文本条目。

    自由文本条目的检索子句是 ``<输入>[All Fields]``，并由界面显示出来，
    让用户自己判断这次检索靠不靠谱。
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("基因名不能为空")
    entry = _BY_KEY.get(normalize_gene_key(cleaned))
    if entry is not None:
        return entry
    return GeneEntry(cleaned, (), f"{cleaned}[All Fields]",
                     "无内置检索式，按自由文本检索")


def is_unsearchable(entry: GeneEntry) -> bool:
    """该基因当前是否有可用检索字段。"""
    return not entry.clause


def build_query(species: str, entry: GeneEntry) -> str:
    """构造 nuccore 检索式。

    物种名加引号精确匹配，与 :func:`seq_toolkit.ncbi.build_query` 的 species
    范围同一约定（不加引号的属名会连带命中同属其它种）。
    """
    name = (species or "").strip()
    if not name:
        raise ValueError("物种名不能为空")
    if not entry.clause:
        raise ValueError(f"{entry.name} 没有可用的检索字段，不应发起检索")
    return f'"{name}"[Organism] AND {entry.clause}'
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gene_query.py`

预期：11 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gene_query.py tests/test_gene_query.py
git commit -m "feat(gene_query): 基因解析、不可检索标记与检索式构造"
```

---

### 任务 6：`gene_query.py` 完整基因组判据与命中拆分

**文件：**
- 修改：`seq_toolkit/gene_query.py`
- 测试：`tests/test_gene_query.py`
- 新建：`tests/fakes_ncbi.py`

**接口：**
- 依赖输入：`ncbi.matches_complete_genome()`、`ncbi.SeqSummary`
- 对外产出：`COMPLETE_GENOME_MIN_LENGTH: int`、`is_complete_genome(definition: str, length: int) -> tuple[bool, str]`、`HitSplit`（frozen dataclass，字段 `kept: list`、`excluded: list[tuple[SeqSummary, str]]`，方法 `count_by(reason: str) -> int`）、`split_hits(summaries) -> HitSplit`

- [ ] **步骤 1：编写失败的测试**

新建 `tests/fakes_ncbi.py`（后续任务复用）：

```python
"""测试替身：让 gene_query 的编排逻辑完全离线可测。"""

from __future__ import annotations

from seq_toolkit.model import SequenceRecord
from seq_toolkit.ncbi import DownloadReport, SearchResult, SeqSummary


def make_summary(accession="ON929859.1", length=800,
                 definition="Salsola pellucida matK gene, partial cds",
                 organism="Salsola pellucida", source_db="GenBank",
                 date="01-JAN-2024") -> SeqSummary:
    return SeqSummary(accession=accession, length=length, organism=organism,
                      definition=definition, date=date, source_db=source_db)


def make_record(accession="ON929859.1", seq="ATGCATGC",
                species="Salsola pellucida") -> SequenceRecord:
    parts = accession.partition(".")
    return SequenceRecord(
        accession=accession, accession_base=parts[0],
        version=int(parts[2]) if parts[2] else None,
        species=species, species_raw=species, lineage="", definition="",
        seq=seq, source_format="fasta", origin_path="", origin_line=0)


class FakeGeneClient:
    """按**完整检索式**返回预设命中；记录收到的检索式与下载请求。

    真实客户端走 ``search_raw``（gene_query.build_query 负责拼出完整检索式），
    因此这里的键就是 '"物种"[Organism] AND <基因子句>' 这样的整串。
    """

    def __init__(self, hits=None, failing_terms=(), fail_download=False):
        self.hits: dict[str, list[SeqSummary]] = dict(hits or {})
        self.failing_terms = set(failing_terms)
        self.fail_download = fail_download
        self.queries: list[str] = []
        self.downloads: list[tuple[list[str], object]] = []

    def search_raw(self, query, retmax=500, **kwargs):
        from seq_toolkit.ncbi import NcbiError
        self.queries.append(query)
        if query in self.failing_terms:
            raise NcbiError("模拟检索失败")
        summaries = list(self.hits.get(query, []))
        return (SearchResult(query=query, total=len(summaries),
                             ids=[s.accession for s in summaries]), summaries)

    def download(self, accessions, options, progress=None):
        from seq_toolkit.ncbi import NcbiError
        self.downloads.append((list(accessions), options))
        if self.fail_download:
            raise NcbiError("模拟下载失败")
        records = [make_record(accession) for accession in accessions]
        return DownloadReport(total=len(accessions), succeeded=len(accessions),
                              skipped=0, failed=0, out_dir=options.out_dir,
                              records=records)
```

在 `tests/test_gene_query.py` 末尾追加：

```python
def test_definition_pattern_excludes_complete_genomes():
    from seq_toolkit.gene_query import is_complete_genome
    # 真实 definition 字符串
    drop, reason = is_complete_genome("Nicotiana tabacum plastid, complete genome.", 155943)
    assert drop is True and reason == "definition"


def test_plain_gene_definition_is_kept():
    from seq_toolkit.gene_query import is_complete_genome
    drop, reason = is_complete_genome("Salsola pellucida matK gene, partial cds", 800)
    assert drop is False and reason == ""


def test_length_criterion_catches_unusual_definitions():
    from seq_toolkit.gene_query import is_complete_genome
    drop, reason = is_complete_genome("Nicotiana tabacum chloroplast sequence", 155943)
    assert drop is True and reason == "length"


def test_split_hits_counts_each_criterion_separately():
    from tests.fakes_ncbi import make_summary
    from seq_toolkit.gene_query import split_hits
    kept = make_summary(accession="A1", length=800)
    by_definition = make_summary(accession="A2", length=155943,
                                 definition="Nicotiana tabacum plastid, complete genome.")
    by_length = make_summary(accession="A3", length=120000,
                             definition="Salsola pellucida chloroplast sequence")
    split = split_hits([kept, by_definition, by_length])
    assert [s.accession for s in split.kept] == ["A1"]
    assert split.count_by("definition") == 1
    assert split.count_by("length") == 1
    assert len(split.excluded) == 2
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gene_query.py`

预期：FAIL，提示 `ImportError: cannot import name 'is_complete_genome'`。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/gene_query.py` 顶部把导入改为：

```python
from dataclasses import dataclass
from typing import Iterable

from .model import SeqToolkitError
from .ncbi import SeqSummary, matches_complete_genome
```

并在文件末尾追加：

```python
# 完整基因组记录的长度判据：质体/线粒体完整基因组都在 100 kb 以上，
# 而基因序列（含 ITS）极少超过 10 kb。
COMPLETE_GENOME_MIN_LENGTH = 100_000


def is_complete_genome(definition: str, length: int) -> tuple[bool, str]:
    """是否为完整基因组记录，返回 ``(是否排除, 判据名)``。

    两条判据并联：definition 命中既有模式，或长度达到
    :data:`COMPLETE_GENOME_MIN_LENGTH`。**判据名必须回传**——界面要按判据分别
    计数（"其中 definition 命中 X 条、长度判据 Y 条"），只报一个总数的话，
    用户无法判断是哪条规则在起作用，也就无法发现误杀。
    """
    if matches_complete_genome(definition):
        return True, "definition"
    if int(length or 0) >= COMPLETE_GENOME_MIN_LENGTH:
        return True, "length"
    return False, ""


@dataclass(frozen=True)
class HitSplit:
    """一次检索命中的拆分结果。"""

    kept: list[SeqSummary]
    excluded: list[tuple[SeqSummary, str]]

    def count_by(self, reason: str) -> int:
        """按判据名计数被排除的记录数。"""
        return sum(1 for _summary, why in self.excluded if why == reason)


def split_hits(summaries: Iterable[SeqSummary]) -> HitSplit:
    """把命中拆成"可下载的基因序列"与"被排除的完整基因组记录"。"""
    kept: list[SeqSummary] = []
    excluded: list[tuple[SeqSummary, str]] = []
    for summary in summaries:
        drop, reason = is_complete_genome(summary.definition, summary.length)
        if drop:
            excluded.append((summary, reason))
        else:
            kept.append(summary)
    return HitSplit(kept=kept, excluded=excluded)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gene_query.py`

预期：15 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gene_query.py tests/fakes_ncbi.py tests/test_gene_query.py
git commit -m "feat(gene_query): 完整基因组双判据与命中拆分（按判据分别计数）"
```

---

### 任务 7：`gene_query.py` 组合展开与最优一条

**文件：**
- 修改：`seq_toolkit/gene_query.py`
- 测试：`tests/test_gene_query.py`

**接口：**
- 依赖输入：`resolve_gene()`（任务 5）
- 对外产出：`expand_combinations(species_list, gene_texts) -> list[tuple[str, GeneEntry]]`、`rank_key(summary) -> tuple`、`pick_best(summaries) -> SeqSummary | None`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gene_query.py` 末尾追加：

```python
def test_expand_combinations_dedupes_and_keeps_order():
    from seq_toolkit.gene_query import expand_combinations
    combos = expand_combinations(["Salsola pellucida", " ", "Salsola pellucida",
                                  "Pinus thunbergii"],
                                 ["ITS", "its", "matK"])
    assert [(s, e.name) for s, e in combos] == [
        ("Salsola pellucida", "ITS"),
        ("Salsola pellucida", "matK"),
        ("Pinus thunbergii", "ITS"),
        ("Pinus thunbergii", "matK"),
    ]


def test_rank_key_prefers_refseq_then_longer_then_newer():
    from tests.fakes_ncbi import make_summary
    from seq_toolkit.gene_query import pick_best
    refseq = make_summary(accession="R1", length=700, source_db="RefSeq")
    longer = make_summary(accession="G1", length=900, source_db="GenBank")
    assert pick_best([longer, refseq]).accession == "R1"

    short_new = make_summary(accession="G1", length=700, date="01-JAN-2024")
    long_old = make_summary(accession="G2", length=900, date="01-JAN-2001")
    assert pick_best([short_new, long_old]).accession == "G2"

    older = make_summary(accession="G3", length=800, date="01-JAN-2001")
    newer = make_summary(accession="G4", length=800, date="05-MAY-2020")
    assert pick_best([older, newer]).accession == "G4"


def test_rank_key_puts_unparsable_dates_last():
    from tests.fakes_ncbi import make_summary
    from seq_toolkit.gene_query import pick_best
    weird = make_summary(accession="W1", length=800, date="")
    dated = make_summary(accession="D1", length=800, date="01-JAN-2001")
    assert pick_best([weird, dated]).accession == "D1"


def test_pick_best_of_empty_is_none():
    from seq_toolkit.gene_query import pick_best
    assert pick_best([]) is None
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gene_query.py`

预期：FAIL，提示 `ImportError: cannot import name 'expand_combinations'`。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/gene_query.py` 末尾追加：

```python
def expand_combinations(species_list: Iterable[str],
                        gene_texts: Iterable[str]
                        ) -> list[tuple[str, GeneEntry]]:
    """展开 (物种, 基因) 组合：物种与基因各自去重，并保持输入顺序。"""
    species: list[str] = []
    seen_species: set[str] = set()
    for raw in species_list:
        name = (raw or "").strip()
        if name and name not in seen_species:
            seen_species.add(name)
            species.append(name)

    entries: list[GeneEntry] = []
    seen_genes: set[str] = set()
    for raw in gene_texts:
        if not (raw or "").strip():
            continue
        entry = resolve_gene(raw)
        if entry.name in seen_genes:
            continue
        seen_genes.add(entry.name)
        entries.append(entry)

    return [(name, entry) for name in species for entry in entries]


# esummary 的 createdate 形如 "12-SEP-2026"。**不能**用 strptime 的 %b 解析：
# 它依赖进程 locale，中文 Windows 上解析不了 "SEP"。
_MONTHS = {name: index for index, name in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1)}


def _date_key(text: str) -> tuple[int, int]:
    """日期比较键：``(是否解析失败, 可比较的数值)``，解析失败排最后。"""
    parts = (text or "").strip().upper().split("-")
    if (len(parts) == 3 and parts[0].isdigit()
            and parts[1] in _MONTHS and parts[2].isdigit()):
        return (0, int(parts[2]) * 10000 + _MONTHS[parts[1]] * 100 + int(parts[0]))
    return (1, 0)


def rank_key(summary: SeqSummary) -> tuple:
    """最优一条的排序键（``min`` 即最优）：RefSeq 优先 → 长度最长 → 日期最新。"""
    failed, value = _date_key(summary.date)
    return (0 if summary.source_db == "RefSeq" else 1,
            -int(summary.length or 0),
            failed,
            -value)


def pick_best(summaries: Iterable[SeqSummary]) -> SeqSummary | None:
    """同一组合的最优一条；空输入返回 ``None``。"""
    candidates = list(summaries)
    return min(candidates, key=rank_key) if candidates else None
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gene_query.py`

预期：19 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gene_query.py tests/test_gene_query.py
git commit -m "feat(gene_query): 组合展开与最优一条排序（RefSeq→长度→日期）"
```

---

### 任务 8：`ncbi.py` 增量改动 ① ②（`name_resolver` 与 `records`）

**文件：**
- 修改：`seq_toolkit/ncbi.py:188-203`（`DownloadOptions`）、`seq_toolkit/ncbi.py:205-230`（`DownloadReport`）、`seq_toolkit/ncbi.py:644-669`（`_pending_accessions`）、`seq_toolkit/ncbi.py:824-856`（`download` 内建名字表与返回值）
- 测试：`tests/test_ncbi.py`

**接口：**
- 依赖输入：既有 `NcbiClient.download()`、`NcbiClient.search()`、`NcbiClient.summarize()`
- 对外产出：`DownloadOptions.name_resolver: Callable[[SequenceRecord], str] | None`、`DownloadReport.records: list[SequenceRecord]`、`NcbiClient.search_raw(query: str, retmax: int = 500) -> tuple[SearchResult, list[SeqSummary]]`

**为什么必须新增 `search_raw`：** 既有的 `search()` / `search_summaries()` 只接受**检索词**并由 `ncbi.build_query()` 拼成 `"<词>"[Organism]`，基因子句没有位置可放。`gene_query` 必须能提交完整检索式（`"Salsola pellucida"[Organism] AND matK[Gene]`），否则"按基因检索"退化成"按物种检索"。做法是把 `search()` 里解析 esearch 响应的那段**抽成 `_parse_esearch()` 静态方法**，`search()` 与新增的 `search_raw()` 共用——绝不复制一份解析逻辑（两处实现迟早漂移，正是本仓库注释里反复警告的事）。

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_ncbi.py` 末尾追加（该文件顶部已有 `io` / `threading` / `time` 与 `urllib` 的导入，**需要补一行 `import json`**）：

```python
def test_name_resolver_overrides_the_naming_mode(tmp_path):
    """给了 resolver 就用它，不再走 build_name_map。"""
    opener = RecordingOpener(["", ""])
    client = _client(opener)
    gb_text = (
        "LOCUS       SCU49845     100 bp    DNA     linear   PLN 01-JAN-2024\n"
        "DEFINITION  Salsola pellucida matK gene, partial cds.\n"
        "ACCESSION   SCU49845\n"
        "VERSION     SCU49845.1\n"
        "FEATURES             Location/Qualifiers\n"
        "     source          1..100\n"
        "ORIGIN\n"
        "        1 atgcatgcat gcatgcatgc atgcatgcat gcatgcatgc atgcatgcat\n"
        "       61 gcatgcatgc atgcatgcat gcatgcatgc atgcatgcat\n"
        "//\n")
    opener.outcomes = [gb_text, gb_text]
    options = DownloadOptions(out_dir=str(tmp_path), want_genbank=True,
                              want_fasta=True, merged_files=False,
                              naming_mode="keep",
                              name_resolver=lambda record: "CUSTOM_NAME")
    client.download(["SCU49845.1"], options)
    assert (tmp_path / "CUSTOM_NAME.fasta").exists()
    assert (tmp_path / "CUSTOM_NAME.gb").exists()


def test_download_report_carries_the_records(tmp_path):
    """报告带回记录，供调用方算 GC / 送浏览器，不必重读磁盘。"""
    gb_text = (
        "LOCUS       SCU49845     100 bp    DNA     linear   PLN 01-JAN-2024\n"
        "DEFINITION  Salsola pellucida matK gene, partial cds.\n"
        "ACCESSION   SCU49845\n"
        "VERSION     SCU49845.1\n"
        "FEATURES             Location/Qualifiers\n"
        "     source          1..100\n"
        "ORIGIN\n"
        "        1 atgcatgcat gcatgcatgc atgcatgcat gcatgcatgc atgcatgcat\n"
        "       61 gcatgcatgc atgcatgcat gcatgcatgc atgcatgcat\n"
        "//\n")
    opener = RecordingOpener([gb_text, gb_text])
    client = _client(opener)
    options = DownloadOptions(out_dir=str(tmp_path), want_genbank=True,
                              want_fasta=True, merged_files=False)
    report = client.download(["SCU49845.1"], options)
    assert [record.accession for record in report.records] == ["SCU49845.1"]


def test_name_resolver_disables_predownload_skip(tmp_path):
    """有 resolver 时文件名依赖记录内容，不能按登录号预判跳过（否则会漏下载）。"""
    opener = RecordingOpener(["", "", "", ""])
    client = _client(opener)
    options = DownloadOptions(out_dir=str(tmp_path), naming_mode="accession",
                              name_resolver=lambda record: "WHATEVER")
    pending, skipped = client._pending_accessions(["ON929859.1"], options)
    assert pending == ["ON929859.1"]
    assert skipped == 0


def test_search_raw_sends_the_query_verbatim():
    """基因检索必须提交完整检索式：search() 会再包一层 "词"[Organism]，用不了。"""
    esearch = json.dumps({"esearchresult": {"count": "1", "idlist": ["1"],
                                            "webenv": "", "querykey": "1"}})
    esummary = json.dumps({"result": {"uids": ["1"], "1": {
        "accessionversion": "ON929859.1", "slen": "800",
        "organism": "Salsola pellucida",
        "title": "Salsola pellucida matK gene, partial cds",
        "createdate": "01-JAN-2024", "sourcedb": "GenBank"}}})
    opener = RecordingOpener([esearch, esummary])
    client = _client(opener)
    query = '"Salsola pellucida"[Organism] AND matK[Gene]'
    result, summaries = client.search_raw(query, retmax=20)
    assert opener.params_of(0)["term"] == query          # 逐字提交，没有再加引号
    assert result.total == 1
    assert [s.accession for s in summaries] == ["ON929859.1"]


def test_search_raw_with_no_hits_skips_esummary():
    opener = RecordingOpener([json.dumps(
        {"esearchresult": {"count": "0", "idlist": [], "webenv": "", "querykey": "1"}})])
    client = _client(opener)
    result, summaries = client.search_raw("nothing[All Fields]")
    assert result.total == 0 and summaries == []
    assert len(opener.requests) == 1                     # 没有发第二次请求
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_ncbi.py -k "name_resolver or carries_the_records or search_raw"`

预期：FAIL，提示 `TypeError: DownloadOptions.__init__() got an unexpected keyword argument 'name_resolver'`（修完这一条后会接着报 `AttributeError: 'NcbiClient' object has no attribute 'search_raw'`）。

- [ ] **步骤 3：编写最小实现**

在 `DownloadOptions` 末尾追加字段：

```python
    # 命名解析钩子：给出后**不再**调用 build_name_map，文件名完全由它决定。
    # 基因检索模式用它绑定"物种_基因"命名——那个基名由检索上下文（物种 × 基因）
    # 而非记录字段决定，现有 render_name 表达不了。
    name_resolver: Callable[[SequenceRecord], str] | None = None
```

在 `DownloadReport` 末尾追加字段：

```python
    # 本次真正收下的记录（顺序与下载顺序一致）。调用方据此算 GC、送序列浏览器，
    # 无需重读磁盘。默认空列表，既有调用方不受影响。
    records: list[SequenceRecord] = field(default_factory=list)
```

在 `_pending_accessions()` 里把可预判条件改为：

```python
        predictable = (options.naming_mode == "accession"
                       and options.per_sequence_files
                       and not options.force_redownload
                       and options.name_resolver is None)
```

在 `download()` 里把建表那一行改为：

```python
        if options.name_resolver is not None:
            # resolver 自己就是权威命名来源：它有全部记录上下文，
            # build_name_map 在此毫无意义（且 keep 模式下它按设计返回 {}）。
            name_map = {record: options.name_resolver(record) for record in collected}
        else:
            name_map = build_name_map(collected, options.naming_mode)
```

并在 `download()` 的 `return DownloadReport(...)` 中补上：

```python
            records=list(collected),
```

**再处理检索侧**：把 `NcbiClient.search()` 里解析响应的那段抽成静态方法，并新增 `search_raw()`。`search()` 的方法体改为：

```python
    def search(self, term: str, scope: str = "species", retmax: int = 500,
               min_length: int | None = None, max_length: int | None = None,
               refseq_only: bool = False) -> SearchResult:
        """检索 nuccore，返回命中总数与首批 id（附历史记录供分页取全量）。

        ``build_query`` 在发请求之前调用，所以非法检索式抛出的 ``ValueError`` 不会被
        ``_request`` 的重试逻辑吞掉（它只捕获 HTTPError / URLError）。
        """
        query = build_query(term, scope, min_length, max_length, refseq_only)
        return self._parse_esearch(query, self._request("esearch.fcgi", {
            "db": "nuccore", "term": query, "retmode": "json",
            "usehistory": "y", "retmax": str(retmax),
        }))
```

`_parse_esearch` 是**从原 `search()` 里原样搬出来的**那段解析逻辑（一行未改），声明为静态方法放在 `search()` 之后：

```python
    @staticmethod
    def _parse_esearch(query: str, text: str) -> SearchResult:
        """解析 esearch 响应。

        ``search()`` 与 ``search_raw()`` 共用这一份实现：复制两份解析逻辑迟早漂移，
        而"同一响应两种解析口径"是查不出来的静默缺陷。
        """
        try:
            payload = json.loads(text)
            result = payload["esearchresult"]
        except (ValueError, KeyError, TypeError) as error:
            raise NcbiError(f"esearch 响应无法解析: {error}") from error
        if not isinstance(result, dict):
            raise NcbiError("esearch 响应无法解析: esearchresult 不是对象")
        return SearchResult(
            query=query,
            total=int(result.get("count", 0) or 0),
            ids=list(result.get("idlist", []) or []),
            webenv=result.get("webenv", "") or "",
            query_key=str(result.get("querykey", "") or ""),
        )

    def search_raw(self, query: str, retmax: int = 500
                   ) -> tuple[SearchResult, list[SeqSummary]]:
        """按**完整检索式**检索并取回元数据。

        ``search()`` / ``search_summaries()`` 把检索词当物种名、再包一层
        ``"<词>"[Organism]``，基因检索的子句（``matK[Gene]``）没有位置可放，
        因此这里直接提交调用方拼好的整串检索式（见
        :func:`seq_toolkit.gene_query.build_query`）。
        """
        text = self._request("esearch.fcgi", {
            "db": "nuccore", "term": query, "retmode": "json",
            "usehistory": "y", "retmax": str(retmax),
        })
        result = self._parse_esearch(query, text)
        if not result.ids:
            return result, []
        return result, self.summarize(result.ids)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_ncbi.py`

预期：全部 PASS（含既有用例，尤其 `search()` 的既有用例必须仍然通过——抽 `_parse_esearch` 是行为保持的重构），新增 5 个用例通过。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/ncbi.py tests/test_ncbi.py
git commit -m "feat(ncbi): DownloadOptions.name_resolver 与 DownloadReport.records（纯增量）"
```

---

### 任务 9：`gene_query.py` 命名构造与流水号

**文件：**
- 修改：`seq_toolkit/gene_query.py`
- 测试：`tests/test_gene_query.py`

**接口：**
- 依赖输入：`naming.sanitize_species()`、`naming.sanitize_accession()`、`model.parse_accession()`、`ncbi.SeqSummary`
- 对外产出：`sanitize_gene(text) -> str`、`build_name(species, gene, serial=None) -> str`、`accession_key(accession) -> str`、`GeneRow`（frozen dataclass，字段 `species`、`gene`、`summary`，属性 `key`）、`build_gene_names(rows, gene) -> dict[str, str]`（键为 `accession_key()`）、`row_key(species, gene, accession) -> str`、`shared_accessions(rows) -> list[str]`、`SELECT_BEST`/`SELECT_ALL`、`default_checked_keys(rows, mode) -> list[str]`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gene_query.py` 末尾追加：

```python
def test_build_name_uses_underscores_and_keeps_gene_case():
    from seq_toolkit.gene_query import build_name
    assert build_name("Salsola pellucida", "ITS") == "Salsola_pellucida_ITS"
    assert build_name("Salsola pellucida", "matK", 2) == "Salsola_pellucida_matK_2"
    # 物种名里的标点与杂交符号复用 naming.sanitize_species 的既有规则
    assert build_name("Salsola × tragus", "rbcL") == "Salsola_x_tragus_rbcL"


def test_sanitize_gene_drops_filesystem_hostile_characters():
    from seq_toolkit.gene_query import sanitize_gene
    assert sanitize_gene("internal transcribed spacer") == "internal_transcribed_spacer"
    assert sanitize_gene("trnL-F") == "trnL-F"
    assert sanitize_gene("a/b:c*?") == "abc"


def test_accession_key_ignores_version_case():
    from seq_toolkit.gene_query import accession_key
    assert accession_key("on929859.1") == accession_key("ON929859.2") == "ON929859"


def test_build_gene_names_numbers_only_collisions():
    from tests.fakes_ncbi import make_summary
    from seq_toolkit.gene_query import GeneRow, build_gene_names
    rows = [GeneRow("Salsola pellucida", "ITS", make_summary(accession="A1")),
            GeneRow("Salsola pellucida", "ITS", make_summary(accession="A2")),
            GeneRow("Pinus thunbergii", "ITS", make_summary(accession="A3"))]
    names = build_gene_names(rows, "ITS")
    assert names == {"A1": "Salsola_pellucida_ITS",
                     "A2": "Salsola_pellucida_ITS_2",
                     "A3": "Pinus_thunbergii_ITS"}


def test_gene_row_key_is_unique_per_species_gene_accession():
    from tests.fakes_ncbi import make_summary
    from seq_toolkit.gene_query import GeneRow, row_key
    row = GeneRow("Salsola pellucida", "matK", make_summary(accession="A1"))
    assert row.key == "Salsola pellucida|matK|A1"
    assert row.key == row_key("Salsola pellucida", "matK", "A1")


def test_default_checked_keys_picks_best_per_combination():
    from tests.fakes_ncbi import make_summary
    from seq_toolkit.gene_query import (GeneRow, SELECT_ALL, SELECT_BEST,
                                        default_checked_keys)
    rows = [GeneRow("S", "ITS", make_summary(accession="A1", length=700)),
            GeneRow("S", "ITS", make_summary(accession="A2", length=900)),
            GeneRow("S", "matK", make_summary(accession="A3", length=800))]
    assert default_checked_keys(rows, SELECT_BEST) == ["S|ITS|A2", "S|matK|A3"]
    assert default_checked_keys(rows, SELECT_ALL) == ["S|ITS|A1", "S|ITS|A2", "S|matK|A3"]


def test_shared_accessions_finds_records_hitting_multiple_genes():
    """双位点记录（matK + rbcL 同一条）会被各写一份，必须能识别出来告知用户。"""
    from tests.fakes_ncbi import make_summary
    from seq_toolkit.gene_query import GeneRow, shared_accessions
    rows = [GeneRow("S", "matK", make_summary(accession="A1")),
            GeneRow("S", "rbcL", make_summary(accession="A1")),
            GeneRow("S", "ITS", make_summary(accession="A9"))]
    assert shared_accessions(rows) == ["A1"]
    # 版本号不同但基号相同 → 同一条记录
    versioned = [GeneRow("S", "matK", make_summary(accession="A1.1")),
                 GeneRow("S", "rbcL", make_summary(accession="A1.2"))]
    assert len(shared_accessions(versioned)) == 1
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gene_query.py`

预期：FAIL，提示 `ImportError: cannot import name 'build_name'`。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/gene_query.py` 顶部把导入改为：

```python
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from .model import SeqToolkitError, SequenceRecord, parse_accession
from .naming import sanitize_accession, sanitize_species
from .ncbi import SeqSummary, matches_complete_genome
```

在文件末尾追加：

```python
# 选择策略（界面开关的两个取值）
SELECT_BEST = "best"
SELECT_ALL = "all"

_SPACES = re.compile(r"\s+")
# 文件名里不允许出现的字符（Windows + 保守起见一并挡掉 Unix 侧的特殊字符）
_HOSTILE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_gene(text: str) -> str:
    """基因名进入文件名前的规范化：空白转下划线，删除非法字符。

    内置规范名（``matK``、``rbcL``）**保留原有大小写**——它们是约定俗成的写法，
    统一转小写会让下游按名字匹配的脚本失配。
    """
    cleaned = _SPACES.sub("_", (text or "").strip())
    cleaned = _HOSTILE.sub("", cleaned)
    return cleaned.strip("_.") or "gene"


def build_name(species: str, gene: str, serial: int | None = None) -> str:
    """构造 ``<物种名>_<基因名>``（可带流水号）。

    物种名复用 :func:`naming.sanitize_species`，与既有三种命名模式**同源**，
    不另写一套规范化（否则同一物种在两种模式下的文件名会不一致）。
    """
    base = f"{sanitize_species(species)}_{sanitize_gene(gene)}".strip("_")
    if not base:
        base = "sequence"
    return f"{base}_{serial}" if serial else base


def accession_key(accession: str) -> str:
    """宽松匹配键：登录号基号（去版本号）大写。

    与 ``ncbi._accession_key`` 同口径：esummary 与 efetch 返回的 accession
    可能只差版本号，严格逐字比较会让命名静默回退到登录号。
    """
    return parse_accession(accession or "").base.upper()


def row_key(species: str, gene: str, accession: str) -> str:
    """结果表格行的唯一键（``CheckboxTable(key_of=...)`` 用它）。

    必须是"物种 | 基因 | 登录号"三段：同一登录号可能同时命中两个基因
    （``matK gene, partial cds; rbcL gene, complete cds`` 形式的双位点记录），
    只用登录号会让第二行被表格静默丢掉。
    """
    return f"{species}|{gene}|{accession}"


@dataclass(frozen=True)
class GeneRow:
    """结果表里的一行：一个（物种, 基因）组合下的一条候选序列。"""

    species: str
    gene: str
    summary: SeqSummary

    @property
    def key(self) -> str:
        return row_key(self.species, self.gene, self.summary.accession)


def build_gene_names(rows: Sequence[GeneRow], gene: str) -> dict[str, str]:
    """按首次出现顺序给同一 (物种, 基因) 的多条候选分配流水号。

    返回 ``{accession_key: 名称}``。第一条不加号，第二条起 ``_2``、``_3``…，
    与 :func:`naming.build_name_map` 的既有约定一致（只在真会撞车时才发号）。
    """
    counts: dict[str, int] = {}
    for row in rows:
        base = build_name(row.species, gene)
        counts[base] = counts.get(base, 0) + 1

    seen: dict[str, int] = {}
    names: dict[str, str] = {}
    for row in rows:
        base = build_name(row.species, gene)
        serial = None
        if counts[base] > 1:
            seen[base] = seen.get(base, 0) + 1
            serial = seen[base]
        names[accession_key(row.summary.accession)] = build_name(row.species, gene, serial)
    return names


def default_checked_keys(rows: Sequence[GeneRow], mode: str) -> list[str]:
    """按选择策略算出默认勾选的行键（顺序与表格行序一致）。"""
    if mode == SELECT_ALL:
        return [row.key for row in rows]
    if mode != SELECT_BEST:
        raise ValueError(f"未知选择策略: {mode}")

    best: dict[tuple[str, str], SeqSummary] = {}
    for row in rows:
        group = (row.species, row.gene)
        current = best.get(group)
        if current is None or rank_key(row.summary) < rank_key(current):
            best[group] = row.summary
    return [row.key for row in rows if best[(row.species, row.gene)] is row.summary]


def shared_accessions(rows: Sequence[GeneRow]) -> list[str]:
    """同时出现在多个基因组合里的登录号（`matK` + `rbcL` 合写一条的"双位点"记录）。

    这类记录会按基因分组各下载一次、各写一份文件，而两份文件的内容都是**该记录的
    完整序列**（本工具不做基因区间提取）。这个后果必须由界面显式告知用户，
    不能让他以为 `X_matK.fasta` 里只有 matK。
    """
    genes: dict[str, set[str]] = {}
    display: dict[str, str] = {}
    for row in rows:
        key = accession_key(row.summary.accession)
        genes.setdefault(key, set()).add(row.gene)
        display.setdefault(key, row.summary.accession)
    return [display[key] for key, names in genes.items() if len(names) > 1]
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gene_query.py`

预期：27 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gene_query.py tests/test_gene_query.py
git commit -m "feat(gene_query): 物种_基因 命名构造、行键与默认勾选策略"
```

---

### 任务 10：`gene_query.py` 检索编排与报告合并

**文件：**
- 修改：`seq_toolkit/gene_query.py`
- 测试：`tests/test_gene_query.py`

**接口：**
- 依赖输入：`GeneRow`、`build_gene_names()`（任务 9）、`split_hits()`（任务 6）、`expand_combinations()`（任务 7）、`build_query()`（任务 5）、`DownloadOptions.name_resolver` 与 `NcbiClient.search_raw()`（任务 8）、`DownloadReport.records`（任务 8）、`pipeline.OperationCancelled`
- 对外产出：`GeneSearchOutcome`（dataclass，字段 `rows: list[GeneRow]`、`unmatched: list[tuple[str, str]]`、`failed: list[tuple[str, str, str]]`、`unsearchable: list[tuple[str, str]]`、`excluded: list[tuple[SeqSummary, str]]`、`total_hits: int`）、`search_genes(client, combinations, retmax=20, on_progress=None, cancel=None) -> GeneSearchOutcome`、`download_genes(client, rows, options, on_progress=None) -> DownloadReport`、`merge_reports(reports, out_dir) -> DownloadReport`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gene_query.py` 末尾追加：

```python
def _combos():
    from seq_toolkit.gene_query import expand_combinations
    return expand_combinations(["Salsola pellucida", "Pinus thunbergii"], ["ITS", "matK"])


def test_search_genes_collects_rows_and_splits_outcomes():
    from tests.fakes_ncbi import FakeGeneClient, make_summary
    from seq_toolkit.gene_query import search_genes
    client = FakeGeneClient(hits={
        '"Salsola pellucida"[Organism] AND "internal transcribed spacer"[All Fields]': [
            make_summary(accession="ITS1.1", length=700)],
        '"Salsola pellucida"[Organism] AND matK[Gene]': [
            make_summary(accession="MATK1.1", length=900,
                         definition="Nicotiana tabacum plastid, complete genome.")],
    })
    outcome = search_genes(client, _combos(), retmax=20)
    assert [row.summary.accession for row in outcome.rows] == ["ITS1.1"]
    assert outcome.unmatched == [("Salsola pellucida", "matK"),
                                ("Pinus thunbergii", "ITS"),
                                ("Pinus thunbergii", "matK")]
    assert len(outcome.excluded) == 1
    assert outcome.excluded[0][1] == "definition"
    assert outcome.failed == []


def test_search_genes_isolates_single_combination_failure():
    from tests.fakes_ncbi import FakeGeneClient, make_summary
    from seq_toolkit.gene_query import search_genes
    client = FakeGeneClient(
        hits={'"Salsola pellucida"[Organism] AND matK[Gene]': [
            make_summary(accession="MATK1.1")]},
        failing_terms={'"Salsola pellucida"[Organism] AND "internal transcribed spacer"[All Fields]'},
    )
    outcome = search_genes(client, _combos(), retmax=20)
    assert [row.summary.accession for row in outcome.rows] == ["MATK1.1"]
    assert outcome.failed == [("Salsola pellucida", "ITS", "模拟检索失败")]


def test_search_genes_skips_unsearchable_without_network():
    from tests.fakes_ncbi import FakeGeneClient, make_summary
    from seq_toolkit.gene_query import expand_combinations, search_genes
    client = FakeGeneClient(hits={})
    outcome = search_genes(client, expand_combinations(["Salsola pellucida"], ["trnL-F"]))
    assert outcome.unsearchable == [("Salsola pellucida", "trnL-F")]
    assert client.queries == []          # 一个请求都没发
    assert outcome.rows == []


def test_download_genes_binds_resolver_per_gene(tmp_path):
    from tests.fakes_ncbi import FakeGeneClient, make_record, make_summary
    from seq_toolkit.gene_query import GeneRow, download_genes
    from seq_toolkit.ncbi import DownloadOptions
    client = FakeGeneClient()
    rows = [GeneRow("Salsola pellucida", "ITS", make_summary(accession="A1")),
            GeneRow("Salsola pellucida", "ITS", make_summary(accession="A2")),
            GeneRow("Salsola pellucida", "matK", make_summary(accession="A3"))]
    options = DownloadOptions(out_dir=str(tmp_path), per_sequence_files=True,
                              merged_files=False, naming_mode="keep")
    report = download_genes(client, rows, options)
    # 每个基因一次 download 调用
    assert [len(accessions) for accessions, _opts in client.downloads] == [2, 1]
    names = [opts.name_resolver(make_record(accession))
             for accessions, opts in client.downloads
             for accession in accessions]
    assert names == ["Salsola_pellucida_ITS", "Salsola_pellucida_ITS_2",
                     "Salsola_pellucida_matK"]
    assert report.total == 3 and report.succeeded == 3


def test_merge_reports_sums_counts_and_concatenates(tmp_path):
    from tests.fakes_ncbi import make_record
    from seq_toolkit.gene_query import merge_reports
    from seq_toolkit.ncbi import DownloadReport
    first = DownloadReport(total=2, succeeded=1, skipped=1, failed=0,
                           out_dir=str(tmp_path), records=[make_record("A1")],
                           failures=[("A2", "已存在")])
    second = DownloadReport(total=1, succeeded=1, skipped=0, failed=0,
                            out_dir=str(tmp_path), records=[make_record("B1")])
    merged = merge_reports([first, second], str(tmp_path))
    assert (merged.total, merged.succeeded, merged.skipped, merged.failed) == (3, 2, 1, 0)
    assert [r.accession for r in merged.records] == ["A1", "B1"]
    assert merged.failures == [("A2", "已存在")]


def test_download_genes_writes_real_files_through_the_real_client(tmp_path):
    """集成（离线）：真实 NcbiClient + 假 opener，验证文件真的落盘、名字与 header 一致。"""
    import io

    from tests.fakes_ncbi import make_summary
    from seq_toolkit.gene_query import GeneRow, download_genes
    from seq_toolkit.ncbi import DownloadOptions, NcbiClient

    genbank_text = (
        "LOCUS       ON929859       12 bp    DNA     linear   PLN 01-JAN-2024\n"
        "DEFINITION  Salsola pellucida matK gene, partial cds.\n"
        "ACCESSION   ON929859\n"
        "VERSION     ON929859.1\n"
        "FEATURES             Location/Qualifiers\n"
        "     source          1..12\n"
        "ORIGIN\n"
        "        1 atgcatgcat gc\n"
        "//\n")

    class Opener:
        """efetch 的响应替身。_request 用 ``with ... as response`` 读它。"""

        def __init__(self, text):
            self.text = text
            self.requests = []

        def __call__(self, request):
            self.requests.append(request)
            return io.BytesIO(self.text.encode("utf-8"))

    opener = Opener(genbank_text)
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=lambda _s: None)
    rows = [GeneRow("Salsola pellucida", "matK",
                    make_summary(accession="ON929859.1"))]
    options = DownloadOptions(out_dir=str(tmp_path), want_fasta=True,
                              want_genbank=True, per_sequence_files=True,
                              merged_files=False, naming_mode="keep")
    report = download_genes(client, rows, options)

    fasta = tmp_path / "Salsola_pellucida_matK.fasta"
    assert fasta.exists()
    text = fasta.read_text(encoding="utf-8")
    assert text.startswith(">Salsola_pellucida_matK\n")     # header 与文件名逐字一致
    assert "ATGCATGCATGC" in text.upper()
    assert (tmp_path / "Salsola_pellucida_matK.gb").exists()
    assert [r.accession for r in report.records] == ["ON929859.1"]
    assert report.succeeded == 1
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gene_query.py`

预期：FAIL，提示 `ImportError: cannot import name 'search_genes'`。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/gene_query.py` 顶部把导入改为：

```python
import re
import threading
from dataclasses import dataclass, field, replace
from typing import Callable, Iterable, Sequence

from .model import SeqToolkitError, SequenceRecord, parse_accession
from .naming import sanitize_accession, sanitize_species
from .ncbi import DownloadOptions, DownloadReport, NcbiClient, SeqSummary, \
    matches_complete_genome
from .pipeline import OperationCancelled
```

在文件末尾追加：

```python
@dataclass
class GeneSearchOutcome:
    """一次「按基因检索」的完整结果。

    四类结果**分开记账**，因为它们对用户的含义完全不同：``rows`` 可下载、
    ``unmatched`` 是真没有、``unsearchable`` 是查不了、``failed`` 是网络出错。
    合并成一个"空结果"会让用户无法判断该去改检索词还是修网络。
    """

    rows: list[GeneRow] = field(default_factory=list)
    unmatched: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str, str]] = field(default_factory=list)
    unsearchable: list[tuple[str, str]] = field(default_factory=list)
    excluded: list[tuple[SeqSummary, str]] = field(default_factory=list)
    total_hits: int = 0


def search_genes(client, combinations: Sequence[tuple[str, GeneEntry]],
                 retmax: int = 20,
                 on_progress: Callable[[int, int, str], None] | None = None,
                 cancel: threading.Event | None = None) -> GeneSearchOutcome:
    """逐组合检索并汇总。

    单个组合失败只记入 ``failed`` 并继续下一个：一个拼错的物种名不该让其余
    组合一条都拿不到。不可检索的基因**不发请求**，直接记入 ``unsearchable``。
    """
    outcome = GeneSearchOutcome()
    total = len(combinations)
    for index, (species, entry) in enumerate(combinations, start=1):
        if cancel is not None and cancel.is_set():
            raise OperationCancelled("操作已取消")
        if on_progress is not None:
            on_progress(index - 1, total, f"检索 {species} × {entry.name}")
        if not entry.clause:
            outcome.unsearchable.append((species, entry.name))
            continue
        try:
            result, summaries = client.search_raw(
                build_query(species, entry), retmax=retmax)
        except OperationCancelled:
            raise
        except SeqToolkitError as error:
            outcome.failed.append((species, entry.name, str(error)))
            continue
        outcome.total_hits += int(getattr(result, "total", 0) or 0)
        split = split_hits(summaries)
        outcome.excluded.extend(split.excluded)
        if not split.kept:
            outcome.unmatched.append((species, entry.name))
            continue
        outcome.rows.extend(GeneRow(species, entry.name, summary)
                            for summary in split.kept)
    if on_progress is not None:
        on_progress(total, total, "检索完成")
    return outcome


def merge_reports(reports: Sequence[DownloadReport], out_dir: str) -> DownloadReport:
    """把各基因组的下载报告合并成一份。

    计数口径与 :class:`ncbi.DownloadReport` 完全一致（单位是登录号），
    因此界面可以直接把它交给 ``widgets.format_download_summary()``。
    """
    failures: list[tuple[str, str]] = []
    records: list[SequenceRecord] = []
    merged_fasta = merged_genbank = ""
    for report in reports:
        failures.extend(report.failures)
        records.extend(report.records)
        merged_fasta = report.merged_fasta or merged_fasta
        merged_genbank = report.merged_genbank or merged_genbank
    return DownloadReport(
        total=sum(report.total for report in reports),
        succeeded=sum(report.succeeded for report in reports),
        skipped=sum(report.skipped for report in reports),
        failed=sum(report.failed for report in reports),
        out_dir=out_dir,
        failures=failures,
        merged_fasta=merged_fasta,
        merged_genbank=merged_genbank,
        records=records,
    )


def download_genes(client, rows: Sequence[GeneRow], options: DownloadOptions,
                   on_progress: Callable[[int, int, str], None] | None = None
                   ) -> DownloadReport:
    """**按基因分组**下载，每组一次 ``client.download()``。

    每一组的 ``name_resolver`` 只绑定该组的基因，因此命名解析不需要
    "登录号 → 基因"的反查表——那条表在"同一登录号同时命中两个基因"
    （双位点记录）时无解，而按组下载时同一登录号在两组里各写一份，
    行为明确且可解释。
    """
    groups: dict[str, list[GeneRow]] = {}
    for row in rows:
        groups.setdefault(row.gene, []).append(row)

    total = len(rows)
    done = 0
    reports: list[DownloadReport] = []
    for gene, group in groups.items():
        names = build_gene_names(group, gene)

        def resolver(record: SequenceRecord, names=names) -> str:
            return (names.get(accession_key(record.accession))
                    or sanitize_accession(record.accession))

        def group_progress(_done: int, _total: int, text: str,
                           gene=gene, base=done) -> None:
            if on_progress is not None:
                on_progress(min(base + _done, total), total, text or f"下载 {gene}")

        group_options = replace(options, name_resolver=resolver)
        accessions = [row.summary.accession for row in group]
        reports.append(client.download(accessions, group_options,
                                       progress=group_progress))
        done += len(group)
    return merge_reports(reports, options.out_dir)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gene_query.py`

预期：32 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gene_query.py tests/test_gene_query.py
git commit -m "feat(gene_query): 组合检索编排与按基因分组的下载编排"
```

---

### 任务 11：`widgets.py` 增量改动 ⑤（`CheckboxTable.key_of`）

**文件：**
- 修改：`seq_toolkit/gui/widgets.py:67-146`（`CheckboxTable`）
- 测试：`tests/test_gui_widgets.py`

**接口：**
- 依赖输入：无
- 对外产出：`CheckboxTable(parent, columns, headings, widths=None, key_of=None)`；`key_of` 形如 `Callable[[tuple], str]`，提供后行 iid 与勾选键改用它，显示值不变

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gui_widgets.py` 末尾追加（该模块已有 `app` 夹具与本文件内的控件构建惯例，直接沿用）：

```python
def test_checkbox_table_key_of_separates_identity_from_display(app):
    """行键可由 key_of 单独指定：首列重复也不会被静默去重丢掉。"""
    from seq_toolkit.gui.widgets import CheckboxTable
    table = CheckboxTable(app, ("species", "gene", "accession"),
                          ("物种名", "基因", "Accession"),
                          key_of=lambda row: f"{row[0]}|{row[1]}|{row[2]}")
    table.set_rows([("Salsola pellucida", "matK", "A1"),
                    ("Salsola pellucida", "matK", "A2"),
                    ("Salsola pellucida", "rbcL", "A1")])
    assert len(table.get_children()) == 3
    assert table.selection.total() == 3
    assert table.selection.is_checked("Salsola pellucida|matK|A1")
    assert table.selection.is_checked("Salsola pellucida|matK|A2")
    assert table.selection.is_checked("Salsola pellucida|rbcL|A1")
    table.destroy()


def test_checkbox_table_without_key_of_keeps_legacy_behaviour(app):
    """不传 key_of 时行为与改动前一致：首元素既是键也是第一列的值。"""
    from seq_toolkit.gui.widgets import CheckboxTable
    table = CheckboxTable(app, ("accession", "length"), ("Accession", "长度"))
    table.set_rows([("A1", "100"), ("A2", "200")])
    assert table.selection.checked_keys() == []
    table.selection.check("A1")
    assert table.selection.checked_keys() == ["A1"]
    assert table.displayed_rows() == [("A1", "100"), ("A2", "200")]
    table.destroy()
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_widgets.py -k key_of`

预期：FAIL，提示 `TypeError: __init__() got an unexpected keyword argument 'key_of'`。

- [ ] **步骤 3：编写最小实现**

把 `CheckboxTable.__init__` 签名与 `set_rows` 改为：

```python
    def __init__(self, parent, columns: Sequence[str], headings: Sequence[str],
                 widths: Sequence[int] | None = None,
                 key_of: Callable[[tuple], str] | None = None) -> None:
        all_columns = ("check",) + tuple(columns)
        super().__init__(parent, columns=all_columns, show="headings", height=14)
        self.selection = RowSelection()
        # 行键的取法。缺省（None）沿用历史约定：首元素既是唯一键、也是第一列的值。
        # 提供 key_of 后，首列可以是会重复的展示字段（如物种名），行键另算——
        # 否则 set_rows 的按 key 去重会**静默丢掉重复行**，而"静默丢数据"正是
        # 本项目明令禁止的行为。
        self._key_of = key_of or (lambda row: str(row[0]))
        self._rows: list[tuple] = []
        self._on_change: Callable[[], None] | None = None
```

`set_rows` 里的两处键计算改用 `self._key_of`：

```python
    def set_rows(self, rows: list[tuple]) -> None:
        self.delete(*self.get_children())
        unique_rows: list[tuple] = []
        seen: set[str] = set()
        for row in rows:
            key = self._key_of(row)
            if key in seen:
                continue
            seen.add(key)
            unique_rows.append(row)
        self._rows = unique_rows
        self.selection.set_keys([self._key_of(row) for row in self._rows])
        for row in self._rows:
            self.insert("", "end", iid=self._key_of(row),
                        values=(UNCHECKED,) + tuple(row))
        self.refresh_checks()
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_widgets.py`

预期：全部 PASS（含既有用例），新增 2 个用例通过。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/widgets.py tests/test_gui_widgets.py
git commit -m "feat(widgets): CheckboxTable 支持独立行键 key_of，避免重复首列被静默去重"
```

---

### 任务 12：`concat.py` 拼接纯函数

**文件：**
- 新建：`seq_toolkit/concat.py`
- 测试：`tests/test_concat.py`

**接口：**
- 依赖输入：`model.SequenceRecord`
- 对外产出：`merged_length(lengths: Sequence[int], spacer: str) -> int`、`concatenate(records: Sequence[SequenceRecord], spacer: str, header: str) -> SequenceRecord`

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_concat.py`：

```python
"""序列拼接的单元测试。纯函数，不需要 Tk。"""

import pytest

from seq_toolkit.concat import concatenate, merged_length


def test_merged_length_adds_spacers_between_sequences_only():
    assert merged_length([10, 20, 30], "NNNNNN") == 60 + 12
    assert merged_length([10], "NNNNNN") == 10        # 单条不加间隔
    assert merged_length([], "NNNNNN") == 0
    assert merged_length([10, 20], "") == 30          # 无间隔


def test_concatenate_joins_in_given_order():
    from tests.fakes_ncbi import make_record
    records = [make_record("A1", seq="AAAA"), make_record("A2", seq="CCCC")]
    merged = concatenate(records, "NN", "merged_sequence")
    assert merged.seq == "AAAANNCCCC"
    assert merged.accession == "merged_sequence"
    assert len(merged.seq) == merged_length([4, 4], "NN")


def test_concatenate_without_spacer():
    from tests.fakes_ncbi import make_record
    merged = concatenate([make_record("A1", seq="AAAA"),
                          make_record("A2", seq="CCCC")], "", "h")
    assert merged.seq == "AAAACCCC"


def test_concatenate_empty_raises():
    with pytest.raises(ValueError):
        concatenate([], "NN", "h")
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_concat.py`

预期：FAIL，提示 `ModuleNotFoundError: No module named 'seq_toolkit.concat'`。

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/concat.py`：

```python
"""序列拼接：按给定顺序首尾相接，可选间隔序列。纯函数，不做 IO。"""

from __future__ import annotations

from typing import Sequence

from .model import SequenceRecord


def merged_length(lengths: Sequence[int], spacer: str) -> int:
    """合并后的长度 = Σ 各序列长度 + 间隔长度 × (条数 − 1)。

    单条序列**不加**间隔（否则会在末尾多出一段 N），空列表为 0。
    """
    count = len(lengths)
    if count == 0:
        return 0
    return sum(int(length) for length in lengths) + len(spacer) * (count - 1)


def concatenate(records: Sequence[SequenceRecord], spacer: str,
                header: str) -> SequenceRecord:
    """按给定顺序把多条记录拼成一条新记录。

    返回的新记录只保留序列与名称：拼接产物不再是任何一条原始记录，
    沿用原登录号/物种名会让下游误以为它就是那条序列。
    """
    if not records:
        raise ValueError("没有可拼接的序列")
    sequence = spacer.join(record.seq for record in records)
    return SequenceRecord(
        accession=header, accession_base=header, version=None,
        species="", species_raw="", lineage="", definition=header,
        seq=sequence, source_format="fasta", origin_path="", origin_line=0)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_concat.py`

预期：4 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/concat.py tests/test_concat.py
git commit -m "feat(concat): 序列拼接纯函数（顺序、间隔、长度、header）"
```

---

### 任务 13：`gui/tab_concat.py` 与 `app.py` 注册（增量改动 ④）

**文件：**
- 新建：`seq_toolkit/gui/tab_concat.py`
- 修改：`seq_toolkit/gui/app.py:27-33`（`TAB_SPECS`，**追加到末尾**）
- 测试：`tests/test_gui_tab_concat.py`

**接口：**
- 依赖输入：`concat.merged_length/concatenate`、`widgets.FilePicker/ProgressPanel/grid_row`、`format_detect.list_input_files`、`fasta_io.read_fasta/write_fasta`、`genbank_io.read_genbank`、`pipeline.resolve_output_path`、`app.log`、`app.set_status`
- 对外产出：`build(parent, app) -> ttk.Frame`

**关键约束：**「序列拼接」**必须追加在 `TAB_SPECS` 末尾**（即「设置」之后）。`tab_search.py` 里硬编码了 `app.open_tab(4)` 用于跳转到「设置」，把新页插在中间会让这个索引指向错误的页——用户点「请先在设置中填写邮箱」会跳到拼接页。

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_gui_tab_concat.py`（沿用 `tests/test_gui_tabs.py` 的单根窗口 + 短重试夹具）：

```python
"""「序列拼接」标签页的 GUI 测试。"""

import gc
import time

import pytest

pytest.importorskip("tkinter")

from tkinter import ttk  # noqa: E402

from seq_toolkit.settings import Settings  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from seq_toolkit.gui.app import App
    gc.collect()
    instance = None
    last_error = None
    for _ in range(3):
        try:
            instance = App(Settings(), start_polling=False)
            break
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
    if instance is None:  # pragma: no cover
        pytest.skip(f"无可用显示: {last_error}")
    yield instance
    instance.destroy()
    gc.collect()


def _descendants(widget) -> list:
    found = []
    for child in widget.winfo_children():
        found.append(child)
        found.extend(_descendants(child))
    return found


def _widgets(parent, cls):
    return [w for w in _descendants(parent) if isinstance(w, cls)]


def test_settings_tab_index_is_still_four(app):
    """回归：tab_search 里硬编码的 app.open_tab(4) 必须仍指向「设置」。"""
    assert app.notebook.tab(4, "text") == "设置"


def test_concat_tab_exists_and_has_controls(app):
    titles = [app.notebook.tab(index, "text")
              for index in range(len(app.notebook.tabs()))]
    assert "序列拼接" in titles
    assert titles[-1] == "序列拼接"
    frame = app.nametowidget(app.notebook.tabs()[titles.index("序列拼接")])
    labels = [w.cget("text") for w in _widgets(frame, ttk.Button)]
    for expected in ("添加文件", "添加文件夹", "上移", "下移", "开始拼接"):
        assert expected in labels, f"缺少按钮：{expected}"


def test_concat_preview_updates_with_spacer(app):
    from seq_toolkit.concat import merged_length
    assert merged_length([100, 200], "NNNNNN") == 300 + 6
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tab_concat.py`

预期：FAIL，`test_concat_tab_exists_and_has_controls` 断言 "序列拼接" 不在标题里。

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/gui/tab_concat.py`：

```python
"""⑥ 序列拼接：多条序列按指定顺序首尾相接，可选间隔序列。"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..concat import concatenate, merged_length
from ..fasta_io import read_fasta, write_fasta
from ..format_detect import detect_format, list_input_files
from ..genbank_io import read_genbank
from ..pipeline import resolve_output_path
from ..stats import format_stats, sequence_stats
from .widgets import FilePicker, grid_row

TITLE = "序列拼接"
DEFAULT_SPACER = "NNNNNN"
DEFAULT_HEADER = "merged_sequence"
LIST_COLUMNS = ("index", "name", "length", "gc", "source")
LIST_HEADINGS = ("序", "序列名", "长度", "GC%", "来源文件")
LIST_WIDTHS = (50, 260, 100, 90, 380)


def build(parent: ttk.Frame, app) -> ttk.Frame:
    # 所有 Tk 变量显式传 master=parent（见 tab_search.py 的同一约定）。
    inputs = ttk.LabelFrame(parent, text="输入序列")
    inputs.pack(fill="x", padx=8, pady=(8, 4))

    paths: list[str] = []          # 已读取的记录（每条一行，顺序即拼接顺序）
    records: list = []

    def refresh_list() -> None:
        # 手写 delete + insert 而不是调 SortableTable.set_rows：本表是只读 Treeview，
        # 没有 set_rows（上面解释了为什么不能用 SortableTable）。
        table.delete(*table.get_children())
        for index, record in enumerate(records, start=1):
            stats = sequence_stats(record.seq)
            length_text, gc_text, _at, _n = format_stats(stats)
            table.insert("", "end", iid=str(index),
                         values=(str(index), record.accession or f"sequence_{index}",
                                 length_text, gc_text,
                                 os.path.basename(record.origin_path)))
        preview.configure(text=preview_text())

    def preview_text() -> str:
        if not records:
            return "尚未添加序列"
        total = merged_length([len(r.seq) for r in records], spacer.get())
        return (f"共 {len(records)} 条，合并后长度 {total:,} bp"
                f"（间隔序列 {len(spacer.get())} bp × {len(records) - 1} 处）")

    def add_paths(chosen: list[str], recursive: bool) -> None:
        found = list_input_files(chosen, recursive=recursive,
                                 fasta_suffixes=app.settings.fasta_suffixes,
                                 genbank_suffixes=app.settings.genbank_suffixes)
        if not found:
            app.log.warn("没有找到可读取的 FASTA / GenBank 文件")
            return
        added = 0
        for path in found:
            # 用内容判定格式（仓库既有的 detect_format），不靠后缀猜：
            # 用户手上的老文件后缀五花八门，按后缀猜会把 FASTA 当 GenBank 读。
            detected = detect_format(path)
            if detected not in ("fasta", "genbank"):
                app.log.warn(f"跳过无法识别格式的文件: {path}")
                continue
            try:
                producer = (read_genbank(path) if detected == "genbank"
                            else read_fasta(path))
                for record in producer:
                    records.append(record)
                    added += 1
            except Exception as error:  # noqa: BLE001 单个坏文件不中断整批
                app.log.error(f"读取失败，已跳过: {path}: {error}")
        app.log.info(f"已添加 {added} 条序列（来自 {len(found)} 个文件）")
        refresh_list()

    row = ttk.Frame(inputs)
    grid_row(inputs, 0, "文件", row)

    def pick_files() -> None:
        chosen = filedialog.askopenfilenames(parent=parent, title="选择 FASTA / GenBank 文件")
        if chosen:
            add_paths(list(chosen), recursive=False)

    def pick_dir() -> None:
        chosen = filedialog.askdirectory(parent=parent, title="选择文件夹")
        if chosen:
            add_paths([chosen], recursive=True)

    ttk.Button(row, text="添加文件", command=pick_files).pack(side="left")
    ttk.Button(row, text="添加文件夹", command=pick_dir).pack(side="left", padx=4)

    list_box = ttk.LabelFrame(parent, text="序列顺序（自上而下即为拼接顺序）")
    list_box.pack(fill="both", expand=True, padx=8, pady=4)
    # 用只读的 Treeview，**不用** SortableTable：点表头排序只改显示顺序，
    # records 列表的顺序不变，用户会看到"已经排好序"却拼出另一个顺序。
    # 本表的显示顺序必须与拼接顺序严格一致。
    table = ttk.Treeview(list_box, columns=LIST_COLUMNS, show="headings", height=12)
    for column, heading, width in zip(LIST_COLUMNS, LIST_HEADINGS, LIST_WIDTHS):
        table.heading(column, text=heading)
        table.column(column, width=width, anchor="w", stretch=True)
    table.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
    scroll = ttk.Scrollbar(list_box, orient="vertical", command=table.yview)
    scroll.pack(side="left", fill="y", pady=6)
    table.configure(yscrollcommand=scroll.set)

    def selected_index() -> int | None:
        chosen = table.selection()
        if not chosen:
            app.log.warn("请先在列表中选择一行")
            return None
        return int(table.item(chosen[0], "values")[0]) - 1

    def move(offset: int) -> None:
        index = selected_index()
        if index is None:
            return
        target = index + offset
        if not 0 <= target < len(records):
            return
        records[index], records[target] = records[target], records[index]
        refresh_list()

    def remove() -> None:
        index = selected_index()
        if index is None:
            return
        del records[index]
        refresh_list()

    def clear() -> None:
        records.clear()
        refresh_list()

    order_bar = ttk.Frame(parent)
    order_bar.pack(fill="x", padx=8)
    for text, command in (("上移", lambda: move(-1)), ("下移", lambda: move(1)),
                          ("置顶", lambda: move(-len(records))),
                          ("置底", lambda: move(len(records))),
                          ("删除", remove), ("清空", clear)):
        ttk.Button(order_bar, text=text, command=command).pack(side="left", padx=2)

    options = ttk.LabelFrame(parent, text="合并选项")
    options.pack(fill="x", padx=8, pady=4)
    spacer = tk.StringVar(master=parent, value=DEFAULT_SPACER)
    grid_row(options, 0, "间隔序列", ttk.Entry(options, textvariable=spacer))
    header = tk.StringVar(master=parent, value=DEFAULT_HEADER)
    grid_row(options, 1, "序列名 (header)", ttk.Entry(options, textvariable=header))
    out_path = FilePicker(options, mode="save", title="保存合并结果",
                          filetypes=[("FASTA 文件", "*.fasta")])
    grid_row(options, 2, "输出文件", out_path)
    preview = ttk.Label(options, text="尚未添加序列", anchor="w")
    grid_row(options, 3, "预览", preview)
    ttk.Label(options, text="提示：间隔序列会被下游建树工具当作序列内容，请确认是否需要",
              foreground="#a05000").grid(row=4, column=1, sticky="w", padx=(0, 8))

    action = ttk.Frame(parent)
    action.pack(fill="x", padx=8, pady=(4, 8))
    run_button = ttk.Button(action, text="开始拼接")

    def do_merge() -> None:
        if not records:
            app.log.warn("请先添加序列")
            return
        target = out_path.path()
        if not target:
            app.log.warn("请指定输出文件")
            return
        # 控件取值在主线程一次取完，随后不动任何控件。
        name = header.get().strip() or DEFAULT_HEADER
        gap = spacer.get()
        try:
            merged = concatenate(list(records), gap, name)
        except ValueError as error:
            app.log.warn(str(error))
            return
        final = resolve_output_path(target)
        if final != target:
            app.log.warn(f"目标文件已存在，实际写入: {final}")
        try:
            write_fasta([merged], final, {merged: name}, wrap=app.settings.wrap)
        except OSError as error:
            app.log.error(f"写出失败: {error}")
            return
        app.log.info(f"拼接完成：{len(records)} 条 → {len(merged.seq):,} bp，已写入 {final}")
        app.set_status(f"拼接完成：{len(merged.seq):,} bp")
        messagebox.showinfo("拼接完成", f"共 {len(records)} 条序列，"
                                        f"合并后 {len(merged.seq):,} bp。\n输出：{final}")

    run_button.configure(command=do_merge)
    run_button.pack(side="right")
    spacer.trace_add("write", lambda *_a: preview.configure(text=preview_text()))
    refresh_list()
    return parent
```

把 `seq_toolkit/gui/app.py` 的 `TAB_SPECS` 改为（**追加在末尾**）：

```python
TAB_SPECS = (
    ("合并 / 转换", tab_merge),
    ("重命名 / 拆分", tab_rename),
    ("检索与批量下载", tab_search),
    ("按登录号下载", tab_accession),
    ("设置", tab_settings),
    # 追加在末尾而不是插在「设置」之前：tab_search 里硬编码了 open_tab(4)
    # 用于跳转到「设置」，插入新页会让那个索引指向错误的标签。
    ("序列拼接", tab_concat),
)
```

并把该文件的导入改为：

```python
from . import (tab_accession, tab_concat, tab_merge, tab_rename, tab_search,
               tab_settings)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tab_concat.py tests/test_gui_tabs.py tests/test_gui_app.py`

预期：全部 PASS。若 `test_gui_tabs.py` 出现「设置」页索引相关失败，检查 `TAB_SPECS` 是否真的把「序列拼接」放在末尾。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/tab_concat.py seq_toolkit/gui/app.py tests/test_gui_tab_concat.py
git commit -m "feat(concat): 序列拼接标签页（顺序调整、间隔序列、实时长度预览）"
```

---

### 任务 14：`gui/tab_gene.py` 输入区与纯格式化助手

**文件：**
- 新建：`seq_toolkit/gui/tab_gene.py`
- 测试：`tests/test_gui_tab_gene.py`

**接口：**
- 依赖输入：`gene_query.GENES/resolve_gene/is_unsearchable/expand_combinations`、`widgets.FilePicker/ProgressPanel/grid_row`
- 对外产出：`TITLE = "按基因检索"`、`build_subpanel(parent, app) -> ttk.Frame`、`row_values(row, gc_text="") -> tuple`、`combination_notice(count) -> str`、`exclusion_notice(excluded) -> str`、`outcome_notice(outcome) -> str`

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_gui_tab_gene.py`：

```python
"""「按基因检索」子页的 GUI 与格式化助手测试。"""

import gc
import time

import pytest

pytest.importorskip("tkinter")

from tkinter import ttk  # noqa: E402

from seq_toolkit.settings import Settings  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from seq_toolkit.gui.app import App
    gc.collect()
    instance = None
    last_error = None
    for _ in range(3):
        try:
            instance = App(Settings(), start_polling=False)
            break
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
    if instance is None:  # pragma: no cover
        pytest.skip(f"无可用显示: {last_error}")
    yield instance
    instance.destroy()
    gc.collect()


def _descendants(widget) -> list:
    found = []
    for child in widget.winfo_children():
        found.append(child)
        found.extend(_descendants(child))
    return found


def test_row_values_shape_matches_headings():
    from tests.fakes_ncbi import make_summary
    from seq_toolkit.gene_query import GeneRow
    from seq_toolkit.gui.tab_gene import RESULT_HEADINGS, row_values
    row = GeneRow("Salsola pellucida", "ITS",
                  make_summary(accession="A1", length=800, source_db="RefSeq"))
    values = row_values(row)
    assert len(values) == len(RESULT_HEADINGS)
    assert values[0] == "Salsola pellucida"
    assert values[2] == "A1"
    assert values[3] == "800"
    assert values[4] == ""                 # 检索阶段 GC 为空
    assert values[5] == "RefSeq"
    assert row_values(row, "44.44")[4] == "44.44"


def test_exclusion_notice_names_both_criteria_and_lists_accessions():
    from tests.fakes_ncbi import make_summary
    from seq_toolkit.gui.tab_gene import exclusion_notice
    excluded = [(make_summary(accession="G1"), "definition"),
                (make_summary(accession="G2"), "length"),
                (make_summary(accession="G3"), "length")]
    text = exclusion_notice(excluded)
    assert "已排除 3 条完整基因组记录" in text
    assert "definition 判据 1 条" in text
    assert "长度判据 2 条" in text
    assert "G1" in text


def test_exclusion_notice_is_empty_when_nothing_excluded():
    from seq_toolkit.gui.tab_gene import exclusion_notice
    assert exclusion_notice([]) == ""


def test_outcome_notice_lists_all_four_buckets():
    from seq_toolkit.gene_query import GeneSearchOutcome
    from seq_toolkit.gui.tab_gene import outcome_notice
    outcome = GeneSearchOutcome(
        unmatched=[("Salsola pellucida", "rpoC1")],
        unsearchable=[("Salsola pellucida", "trnL-F")],
        failed=[("Pinus thunbergii", "ITS", "网络不可达")])
    text = outcome_notice(outcome)
    assert "未检索到 1 个组合" in text
    assert "trnL-F" in text and "无可用检索字段" in text
    assert "检索失败 1 个组合" in text and "网络不可达" in text


def test_combination_notice_warns_above_threshold():
    from seq_toolkit.gui.tab_gene import combination_notice
    assert "50" in combination_notice(51)
    assert combination_notice(12) == ""


def test_subpanel_builds_inside_search_tab(app):
    from seq_toolkit.gui.tab_gene import TITLE, build_subpanel
    frame = ttk.Frame(app)
    build_subpanel(frame, app)
    labels = [w.cget("text") for w in _descendants(frame) if isinstance(w, ttk.Label)]
    assert any("组合" in text for text in labels)
    frame.destroy()


def test_free_text_gene_name_is_accepted_and_shows_its_clause(app):
    """手输基因名必须可用：输入框可编辑，未收录的名字走自由文本检索。"""
    import tkinter as tk
    from seq_toolkit.gui.tab_gene import build_subpanel
    frame = ttk.Frame(app)
    build_subpanel(frame, app)
    combo = next(w for w in _descendants(frame) if isinstance(w, ttk.Combobox))
    assert str(combo.cget("state")) == "normal"
    combo.set("rpoC1")
    next(w for w in _descendants(frame)
         if isinstance(w, ttk.Button) and w.cget("text") == "添加").invoke()
    listbox = next(w for w in _descendants(frame) if isinstance(w, tk.Listbox))
    assert listbox.size() == 1
    assert "rpoC1[All Fields]" in listbox.get(0)
    frame.destroy()
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tab_gene.py`

预期：FAIL，提示 `ModuleNotFoundError: No module named 'seq_toolkit.gui.tab_gene'`。

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/gui/tab_gene.py`：

```python
"""③-乙 按基因检索：物种 × 基因组合检索，下载并按 物种_基因 命名。

本页作为「检索与批量下载」标签页的第二个子选项卡挂载（见 tab_search.build）。
所有网络动作都在后台线程里执行，job 内不触碰任何 Tk 控件。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import gene_query, stats
from ..gene_query import (SELECT_ALL, SELECT_BEST, GeneRow, GeneSearchOutcome,
                          default_checked_keys, expand_combinations,
                          is_unsearchable, resolve_gene)
from ..ncbi import DownloadOptions, NcbiClient
from .widgets import (CheckboxTable, FilePicker, ProgressPanel,
                      format_download_summary, grid_row)

TITLE = "按基因检索"
RESULT_COLUMNS = ("species", "gene", "accession", "length", "gc", "source", "definition")
RESULT_HEADINGS = ("物种名", "基因", "Accession", "长度", "GC%", "来源", "定义行")
RESULT_WIDTHS = (190, 100, 130, 90, 80, 90, 380)
MODE_LABELS = {SELECT_BEST: "每个组合只取最优一条", SELECT_ALL: "取全部候选"}
COMBINATION_WARN_THRESHOLD = 50


def row_values(row: GeneRow, gc_text: str = "") -> tuple:
    """结果表一行的显示值。GC 检索阶段留空，下载完成后回填。"""
    return (row.species, row.gene, row.summary.accession,
            f"{row.summary.length:,}", gc_text, row.summary.source_db,
            row.summary.definition)


def combination_notice(count: int) -> str:
    """组合数超过阈值时的提醒（不阻止执行）。"""
    if count <= COMBINATION_WARN_THRESHOLD:
        return ""
    return (f"共 {count} 个组合，每个组合要发 2 次请求，预计耗时较长"
            f"（超过 {COMBINATION_WARN_THRESHOLD} 个组合）")


def exclusion_notice(excluded) -> str:
    """被排除的完整基因组记录汇总。两条判据分别报数，绝不合并成一个总数。"""
    if not excluded:
        return ""
    by_definition = sum(1 for _s, reason in excluded if reason == "definition")
    by_length = sum(1 for _s, reason in excluded if reason == "length")
    head = (f"已排除 {len(excluded)} 条完整基因组记录"
            f"（definition 判据 {by_definition} 条、长度判据 {by_length} 条）")
    accessions = [summary.accession for summary, _reason in excluded[:5]]
    tail = f"：{'、'.join(accessions)}" + ("…" if len(excluded) > 5 else "")
    return head + tail + "。需要完整基因组请改用「按物种 / 属名检索」子页。"


def outcome_notice(outcome: GeneSearchOutcome) -> str:
    """四类结果分别报告：未检索到 / 无可用检索字段 / 检索失败。"""
    parts = []
    if outcome.unmatched:
        names = "、".join(f"{s} × {g}" for s, g in outcome.unmatched[:5])
        more = "…" if len(outcome.unmatched) > 5 else ""
        parts.append(f"未检索到 {len(outcome.unmatched)} 个组合：{names}{more}")
    if outcome.unsearchable:
        names = "、".join(f"{s} × {g}" for s, g in outcome.unsearchable[:5])
        more = "…" if len(outcome.unsearchable) > 5 else ""
        parts.append(f"{len(outcome.unsearchable)} 个组合的基因在 GenBank "
                     f"无可用检索字段，未发起检索：{names}{more}")
    if outcome.failed:
        detail = "；".join(f"{s} × {g}（{why}）" for s, g, why in outcome.failed[:3])
        parts.append(f"检索失败 {len(outcome.failed)} 个组合：{detail}")
    return "　".join(parts)


def _make_client(app, cancel_event) -> NcbiClient:
    return NcbiClient(email=app.settings.email, api_key=app.settings.api_key,
                      proxy=app.settings.proxy, log=app.log, cancel=cancel_event)


def build_subpanel(parent: ttk.Frame, app) -> ttk.Frame:
    # 所有 Tk 变量显式传 master=parent：不传会挂到 _default_root 上。
    criteria = ttk.LabelFrame(parent, text="检索条件")
    criteria.pack(fill="x", padx=8, pady=(8, 4))

    species_text = tk.Text(criteria, height=4, wrap="none")
    grid_row(criteria, 0, "物种列表（一行一个）", species_text)

    chosen_genes: list[str] = []

    gene_var = tk.StringVar(master=parent, value=gene_query.GENES[0].name)
    # state="normal"（而不是 readonly）：需求明确要求"也允许手动输入"基因名，
    # 未收录的名字走 <输入>[All Fields] 自由检索，并在已选项里显示实际子句。
    gene_box = ttk.Combobox(criteria, textvariable=gene_var, state="normal",
                            values=[entry.name for entry in gene_query.GENES])
    gene_row = ttk.Frame(criteria)
    grid_row(criteria, 1, "基因", gene_row)
    gene_box.pack(side="left", fill="x", expand=True)
    gene_list = tk.Listbox(criteria, height=4)
    grid_row(criteria, 2, "已选基因", gene_list)
    ttk.Label(criteria, text="下拉选择内置基因，或直接输入基因名后点「添加」",
              foreground="#606060").grid(row=1, column=2, sticky="w", padx=(0, 8))

    def gene_label(name: str) -> str:
        entry = resolve_gene(name)
        if is_unsearchable(entry):
            return f"⚠ {entry.name}　{entry.note}"
        return f"{entry.name}　{entry.clause}"

    def refresh_genes() -> None:
        gene_list.delete(0, "end")
        for name in chosen_genes:
            gene_list.insert("end", gene_label(name))
        entries = [resolve_gene(name) for name in chosen_genes]
        count = len(_species_list()) * len(entries)
        preview.configure(text=f"{len(_species_list())} 物种 × {len(entries)} 基因 "
                               f"= {count} 个组合")
        notice = combination_notice(count)
        warn.configure(text=notice)

    def add_gene() -> None:
        name = gene_var.get().strip()
        if not name:
            return
        # 去重按**解析后的规范名**：手输 "its" 与下拉里的 "ITS" 是同一个基因，
        # 按原始字符串去重会让同一个基因在列表里出现两次、检索两次。
        canonical = resolve_gene(name).name
        if canonical in chosen_genes:
            return
        chosen_genes.append(canonical)
        refresh_genes()

    def remove_gene() -> None:
        selection = gene_list.curselection()
        if not selection:
            return
        del chosen_genes[selection[0]]
        refresh_genes()

    def _species_list() -> list[str]:
        raw = species_text.get("1.0", "end")
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def import_species() -> None:
        from ..fasta_io import read_fasta
        from ..format_detect import detect_format, list_input_files
        from ..genbank_io import read_genbank
        from ..naming import extract_species_from_header
        chosen = filedialog.askopenfilenames(parent=parent, title="从序列文件导入物种名")
        if not chosen:
            return
        found: list[str] = []
        for path in list_input_files(list(chosen), recursive=False,
                                     fasta_suffixes=app.settings.fasta_suffixes,
                                     genbank_suffixes=app.settings.genbank_suffixes):
            detected = detect_format(path)
            if detected not in ("fasta", "genbank"):
                app.log.warn(f"跳过无法识别格式的文件: {path}")
                continue
            try:
                producer = (read_genbank(path) if detected == "genbank"
                            else read_fasta(path))
                for record in producer:
                    name = (record.species or "").strip()
                    if not name:
                        name, _warnings = extract_species_from_header(record.definition)
                    if name and name not in found:
                        found.append(name)
            except Exception as error:  # noqa: BLE001 单个坏文件不中断导入
                app.log.error(f"读取失败，已跳过: {path}: {error}")
        if not found:
            app.log.warn("没有从所选文件中提取到物种名")
            return
        species_text.insert("end", "\n".join(found) + "\n")
        app.log.info(f"已从文件导入 {len(found)} 个物种名")
        refresh_genes()

    buttons = ttk.Frame(criteria)
    grid_row(criteria, 3, "", buttons)
    ttk.Button(buttons, text="添加", command=add_gene).pack(side="left")
    ttk.Button(buttons, text="删除", command=remove_gene).pack(side="left", padx=4)
    ttk.Button(buttons, text="从序列文件导入物种名",
               command=import_species).pack(side="left", padx=4)
    preview = ttk.Label(buttons, text="0 物种 × 0 基因 = 0 个组合", anchor="w")
    preview.pack(side="left", padx=12)
    warn = ttk.Label(criteria, text="", foreground="#a05000")
    grid_row(criteria, 4, "", warn)

    refresh_genes()
    return parent
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tab_gene.py`

预期：7 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/tab_gene.py tests/test_gui_tab_gene.py
git commit -m "feat(tab_gene): 按基因检索子页的输入区与结果格式化助手"
```

---

### 任务 15：`gui/tab_gene.py` 检索执行、结果表与默认勾选

**文件：**
- 修改：`seq_toolkit/gui/tab_gene.py`（在 `build_subpanel` 内追加）
- 测试：`tests/test_gui_tab_gene.py`

**接口：**
- 依赖输入：`gene_query.search_genes()`（任务 10）、`default_checked_keys()`（任务 9）、`CheckboxTable(key_of=...)`（任务 11）、`app.run_job()`
- 对外产出：`build_subpanel` 内的检索流程；结果表行键 = `GeneRow.key`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gui_tab_gene.py` 末尾追加：

```python
def _build_page(app):
    from seq_toolkit.gui.tab_gene import build_subpanel
    frame = ttk.Frame(app)
    build_subpanel(frame, app)
    return frame


def _button(parent, text):
    return next(w for w in _descendants(parent)
                if isinstance(w, ttk.Button) and w.cget("text") == text)


def _checkbox_tables(parent):
    from seq_toolkit.gui.widgets import CheckboxTable
    return [w for w in _descendants(parent) if isinstance(w, CheckboxTable)]


def test_search_populates_table_and_checks_best_per_combination(app):
    from tests.fakes_ncbi import FakeGeneClient, make_summary
    import seq_toolkit.gui.tab_gene as tab_gene
    frame = _build_page(app)
    client = FakeGeneClient(hits={
        '"Salsola pellucida"[Organism] AND "internal transcribed spacer"[All Fields]': [
            make_summary(accession="ITS_A", length=700),
            make_summary(accession="ITS_B", length=900)],
    })
    tab_gene._make_client = lambda _app, _cancel: client

    text = next(w for w in _descendants(frame) if isinstance(w, __import__("tkinter").Text))
    text.insert("1.0", "Salsola pellucida\n")
    gene_list = next(w for w in _descendants(frame)
                     if isinstance(w, __import__("tkinter").Listbox))
    _button(frame, "添加").invoke()          # 默认选中的第 1 个基因
    assert gene_list.size() == 1
    _button(frame, "检索").invoke()

    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()
    table = _checkbox_tables(frame)[0]
    assert len(table.get_children()) == 2
    # 默认只勾"最优一条"：ITS_B 更长
    assert table.selection.checked_keys() == ["Salsola pellucida|ITS|ITS_B"]
    frame.destroy()
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tab_gene.py -k search_populates`

预期：FAIL，提示找不到按钮 "检索"。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/gui/tab_gene.py` 的 `build_subpanel` 中、`refresh_genes()` 调用之前插入：

```python
    results_box = ttk.LabelFrame(parent, text="检索结果")
    results_box.pack(fill="both", expand=True, padx=8, pady=4)
    table = CheckboxTable(results_box, RESULT_COLUMNS, RESULT_HEADINGS,
                          RESULT_WIDTHS, key_of=lambda row: row_key(*row[:3]))
    table.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
    scroll = ttk.Scrollbar(results_box, orient="vertical", command=table.yview)
    scroll.pack(side="left", fill="y", pady=6)
    table.configure(yscrollcommand=scroll.set)

    selection_bar = ttk.Frame(parent)
    selection_bar.pack(fill="x", padx=8)
    counter = ttk.Label(selection_bar, text="已选 0 / 0 条")

    def update_counter() -> None:
        counter.configure(text=f"已选 {table.selection.count()} / "
                               f"{table.selection.total()} 条")

    table.bind_selection_change(update_counter)
    ttk.Button(selection_bar, text="全选",
               command=lambda: (table.selection.check_all(),
                                table.refresh_checks())).pack(side="left")
    ttk.Button(selection_bar, text="反选",
               command=lambda: (table.selection.invert(),
                                table.refresh_checks())).pack(side="left", padx=4)
    counter.pack(side="left", padx=12)

    notes = ttk.Label(parent, text="", anchor="w", justify="left",
                      foreground="#a05000", wraplength=1000)
    notes.pack(fill="x", padx=12)

    mode = tk.StringVar(master=parent, value=SELECT_BEST)
    mode_row = ttk.Frame(parent)
    mode_row.pack(fill="x", padx=8)
    ttk.Label(mode_row, text="选择策略").pack(side="left")
    for key, label in MODE_LABELS.items():
        ttk.Radiobutton(mode_row, text=label, value=key, variable=mode,
                        command=lambda: apply_mode(True)).pack(side="left", padx=6)

    action = ttk.Frame(parent)
    action.pack(fill="x", padx=8, pady=(4, 8))
    progress = ProgressPanel(action)
    progress.pack(side="left", fill="x", expand=True)
    search_button = ttk.Button(action, text="检索")
    download_button = ttk.Button(action, text="下载勾选的序列")
    open_button = ttk.Button(action, text="打开输出文件夹")

    rows_by_key: dict[str, GeneRow] = {}
    all_rows: list[GeneRow] = []
    gc_by_key: dict[str, str] = {}
    def apply_mode(log_change: bool) -> None:
        if log_change:
            app.log.info(f"选择策略已切换为「{MODE_LABELS[mode.get()]}」，"
                         f"默认勾选已按新模式重算（会覆盖此前的勾选）")
        table.selection.uncheck_all()
        for key in default_checked_keys(all_rows, mode.get()):
            table.selection.check(key)
        table.refresh_checks()
        update_counter()

    def on_progress(done: int, total: int, text: str) -> None:
        if done == 0:
            progress.start(total)
        progress.update(done, total, text)

    def on_search_done(outcome) -> None:
        nonlocal all_rows
        all_rows = list(outcome.rows)
        rows_by_key.clear()
        gc_by_key.clear()
        ordered = sorted(all_rows, key=lambda r: (r.species, r.gene,
                                                  -int(r.summary.length or 0)))
        table.set_rows([row_values(row) for row in ordered])
        for row in ordered:
            rows_by_key[row.key] = row
        apply_mode(False)
        progress.finish(f"可下载 {len(ordered)} 条")
        notices = [exclusion_notice(outcome.excluded), outcome_notice(outcome)]
        notes.configure(text="　".join(text for text in notices if text))
        for text in notices:
            if text:
                app.log.warn(text)
        app.log.info(f"检索完成：可下载 {len(ordered)} 条候选，"
                     f"命中总数 {outcome.total_hits} 条")
        app.set_status(f"检索完成：可下载 {len(ordered)} 条候选")

    def do_search() -> None:
        species = _species_list()
        if not species:
            app.log.warn("请输入至少一个物种名")
            return
        if not chosen_genes:
            app.log.warn("请至少添加一个基因")
            return
        if not app.settings.email:
            app.log.warn("请先在「设置」中填写 NCBI 邮箱（NCBI 的合规要求）")
            return
        combinations = expand_combinations(species, chosen_genes)
        strategy = mode.get()

        def job(ctx):
            client = _make_client(app, ctx.cancel_event)
            return gene_query.search_genes(client, combinations, retmax=20,
                                           on_progress=ctx.progress,
                                           cancel=ctx.cancel_event)

        app.run_job(job, on_done=on_search_done,
                    on_error=lambda error: (progress.reset(),
                                            app.log.error(f"检索失败: {error}")),
                    progress_handler=on_progress)

    search_button.configure(command=do_search)
    search_button.pack(side="right")
    app.register_busy_widget(search_button)
    app.register_busy_widget(download_button)
    app.register_busy_widget(open_button)
```

并把顶部的导入改为：

```python
from ..gene_query import (SELECT_ALL, SELECT_BEST, GeneRow, GeneSearchOutcome,
                          default_checked_keys, expand_combinations,
                          is_unsearchable, resolve_gene, row_key)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tab_gene.py`

预期：8 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/tab_gene.py tests/test_gui_tab_gene.py
git commit -m "feat(tab_gene): 组合检索执行、结果表与按策略默认勾选"
```

---

### 任务 16：`gui/tab_gene.py` 下载与 GC 回填

**文件：**
- 修改：`seq_toolkit/gui/tab_gene.py`（在 `build_subpanel` 内追加）
- 测试：`tests/test_gui_tab_gene.py`

**接口：**
- 依赖输入：`gene_query.download_genes()`、`stats.sequence_stats()`、`gene_query.accession_key()`、`DownloadOptions`、`widgets.format_download_summary()`
- 对外产出：`build_subpanel` 内的下载流程；`DownloadOptions(per_sequence_files=True, merged_files=False, naming_mode="keep", name_resolver=...)`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gui_tab_gene.py` 末尾追加：

```python
def test_download_writes_gene_named_files_and_backfills_gc(app, tmp_path):
    import seq_toolkit.gui.tab_gene as tab_gene
    from tests.fakes_ncbi import FakeGeneClient, make_summary
    from seq_toolkit.model import SequenceRecord
    from seq_toolkit.ncbi import DownloadReport

    frame = _build_page(app)
    summary = make_summary(accession="ITS_A", length=8, source_db="RefSeq")

    class DownloadingClient(FakeGeneClient):
        def download(self, accessions, options, progress=None):
            record = SequenceRecord(
                accession="ITS_A", accession_base="ITS_A", version=None,
                species="Salsola pellucida", species_raw="Salsola pellucida",
                lineage="", definition="ITS", seq="ATGCATGC",
                source_format="fasta", origin_path="", origin_line=0)
            return DownloadReport(total=1, succeeded=1, skipped=0, failed=0,
                                  out_dir=options.out_dir, records=[record])

    client = DownloadingClient(hits={
        '"Salsola pellucida"[Organism] AND "internal transcribed spacer"[All Fields]': [summary]})
    tab_gene._make_client = lambda _app, _cancel: client

    text = next(w for w in _descendants(frame) if isinstance(w, __import__("tkinter").Text))
    text.insert("1.0", "Salsola pellucida\n")
    _button(frame, "添加").invoke()
    _button(frame, "检索").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    picker = next(w for w in _descendants(frame)
                  if w.__class__.__name__ == "FilePicker")
    picker.set_path(str(tmp_path))
    _button(frame, "下载勾选的序列").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    table = _checkbox_tables(frame)[0]
    gc_cell = table.item(table.get_children()[0], "values")[5]
    assert gc_cell == "50.00"          # ATGCATGC → GC 50%
    assert client.downloads, "应发出一次下载请求"
    frame.destroy()


def test_download_warns_when_one_accession_hits_two_genes(app, tmp_path):
    """双位点记录：同一登录号命中两个基因时必须记 WARN（FR-1.8 的已知限制）。"""
    import tkinter as tk
    import seq_toolkit.gui.tab_gene as tab_gene
    from tests.fakes_ncbi import FakeGeneClient, make_summary

    frame = _build_page(app)
    same = make_summary(accession="BOTH1", length=8)
    client = FakeGeneClient(hits={
        '"Salsola pellucida"[Organism] AND "internal transcribed spacer"[All Fields]': [same],
        '"Salsola pellucida"[Organism] AND matK[Gene]': [same],
    })
    tab_gene._make_client = lambda _app, _cancel: client

    text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
    text.insert("1.0", "Salsola pellucida\n")
    combo = next(w for w in _descendants(frame) if isinstance(w, ttk.Combobox))
    add = _button(frame, "添加")
    add.invoke()                        # 下拉默认值 ITS
    combo.set("matK")
    add.invoke()
    _button(frame, "检索").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    picker = next(w for w in _descendants(frame)
                  if w.__class__.__name__ == "FilePicker")
    picker.set_path(str(tmp_path))
    app._clear_log()
    _button(frame, "下载勾选的序列").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    messages = [entry.message for entry in app.log.entries]
    assert any("同时命中多个基因" in message for message in messages), messages
    frame.destroy()
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tab_gene.py -k backfills_gc`

预期：FAIL，`gc_cell` 为空串（GC 未回填）。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/gui/tab_gene.py` 的 `do_search` 之后插入：

```python
    output = ttk.LabelFrame(parent, text="下载选项")
    output.pack(fill="x", padx=8, pady=4)
    want_fasta = tk.BooleanVar(master=parent, value=True)
    want_genbank = tk.BooleanVar(master=parent, value=False)
    format_row = ttk.Frame(output)
    grid_row(output, 0, "产物", format_row)
    ttk.Checkbutton(format_row, text="FASTA",
                    variable=want_fasta).pack(side="left")
    ttk.Checkbutton(format_row, text="GenBank",
                    variable=want_genbank).pack(side="left", padx=(10, 0))
    out_dir = FilePicker(output, mode="directory", title="下载输出文件夹")
    out_dir.set_path(app.settings.output_dir)
    grid_row(output, 1, "输出文件夹", out_dir)

    def do_download() -> None:
        chosen = table.selection.checked_keys()
        if not chosen:
            app.log.warn("请先在结果表格中勾选要下载的序列")
            return
        target_dir = out_dir.path()
        if not target_dir:
            app.log.warn("请指定下载输出文件夹")
            return
        rows = [rows_by_key[key] for key in chosen if key in rows_by_key]
        # FR-1.8 的已知限制：同一条记录同时命中多个基因（双位点记录）时，
        # 会按基因分组各写一份文件，两份内容都是该记录的完整序列。
        # 不说清楚，用户会以为 X_matK.fasta 里只有 matK。
        shared = gene_query.shared_accessions(rows)
        if shared:
            app.log.warn(
                f"以下 {len(shared)} 个登录号同时命中多个基因，将各写一份文件"
                f"（内容为该记录的完整序列，本工具不做基因区间提取）："
                f"{'、'.join(shared[:5])}"
                + ("…" if len(shared) > 5 else ""))
        # 下载选项与控件取值在主线程一次取完，job 内零控件调用。
        options = DownloadOptions(
            out_dir=target_dir,
            want_fasta=want_fasta.get(),
            want_genbank=want_genbank.get(),
            # 每序列单文件 + 不要合并产物：合并产物在按基因分组时会在每组里
            # 生成一个 all_sequences.fasta，第二组起被迫让位 _1，纯属噪音。
            per_sequence_files=True,
            merged_files=False,
            naming_mode="keep",
            force_redownload=app.settings.force_redownload,
            wrap=app.settings.wrap,
        )

        def job(ctx):
            client = _make_client(app, ctx.cancel_event)
            return gene_query.download_genes(client, rows, options,
                                             on_progress=ctx.progress)

        app.run_job(job, on_done=on_download_done,
                    on_error=lambda error: (progress.reset(),
                                            app.log.error(f"下载失败: {error}")),
                    progress_handler=on_progress)

    def on_download_done(report) -> None:
        nonlocal all_rows
        for record in report.records:
            gc_by_key[gene_query.accession_key(record.accession)] = \
                stats.format_stats(stats.sequence_stats(record.seq))[1]
        ordered = sorted(all_rows, key=lambda r: (r.species, r.gene,
                                                  -int(r.summary.length or 0)))
        table.set_rows([
            row_values(row, gc_by_key.get(
                gene_query.accession_key(row.summary.accession), ""))
            for row in ordered
        ])
        update_counter()
        summary = format_download_summary(report, per_sequence_files=True)
        progress.finish(summary)
        app.log.info(f"下载完成：{summary}")
        for accession, reason in report.failures:
            app.log.error(f"下载失败：{accession}（{reason}）")
        messagebox.showinfo("下载完成", f"{summary}。\n输出目录：{report.out_dir}")

    def open_output_dir() -> None:
        target = out_dir.path()
        if not target:
            app.log.warn("请先指定输出文件夹")
            return
        import os
        try:
            os.startfile(target)  # noqa: S606 Windows 专用
        except OSError as error:
            app.log.error(f"无法打开文件夹: {error}")

    download_button.configure(command=do_download)
    open_button.configure(command=open_output_dir)
    download_button.pack(side="right")
    open_button.pack(side="right", padx=4)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tab_gene.py`

预期：10 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/tab_gene.py tests/test_gui_tab_gene.py
git commit -m "feat(tab_gene): 按基因分组下载与 GC 回填"
```

---

### 任务 17：`gui/tab_search.py` 挂载子选项卡（增量改动 ③）

**文件：**
- 修改：`seq_toolkit/gui/tab_search.py:111-115`（`build()` 开头）
- 测试：`tests/test_gui_tabs.py`

**接口：**
- 依赖输入：`tab_gene.build_subpanel()`、`tab_gene.TITLE`
- 对外产出：`build()` 的返回类型与外部行为不变；新增一个内部子选项卡

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gui_tabs.py` 末尾追加：

```python
def test_search_tab_hosts_the_gene_subpage(app):
    """「检索与批量下载」页内嵌两个子选项卡；v0.1 的控件仍在第一个子页里。"""
    from seq_toolkit.gui.widgets import CheckboxTable
    tab = app.nametowidget(app.notebook.tabs()[2])
    inner = next(w for w in _descendants(tab) if isinstance(w, ttk.Notebook))
    titles = [inner.tab(i, "text") for i in range(len(inner.tabs()))]
    assert titles == ["按物种 / 属名检索", "按基因检索"]
    legacy = inner.nametowidget(inner.tabs()[0])
    assert _button(legacy, "检索") is not None
    assert _button(legacy, "下载勾选的序列") is not None
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tabs.py -k gene_subpage`

预期：FAIL，`StopIteration`（页内没有子 Notebook）。

- [ ] **步骤 3：编写最小实现**

把 `seq_toolkit/gui/tab_search.py` 的 `build()` 开头：

```python
def build(parent: ttk.Frame, app) -> ttk.Frame:
    # 本函数里所有 Tk 变量都显式写 master=parent：不传 master 时 Variable 会挂到
    # tkinter 的 _default_root（进程里第一个根窗口）上，控件与变量就落在两个不同的
    # Tcl 解释器里——输入框里看得见"检索词已填"，而 get() 出来的仍是空串。

    criteria = ttk.LabelFrame(parent, text="检索条件")
```

改为：

```python
def build(parent: ttk.Frame, app) -> ttk.Frame:
    # 本函数里所有 Tk 变量都显式写 master=parent：不传 master 时 Variable 会挂到
    # tkinter 的 _default_root（进程里第一个根窗口）上，控件与变量就落在两个不同的
    # Tcl 解释器里——输入框里看得见"检索词已填"，而 get() 出来的仍是空串。

    # 本页内嵌两个子选项卡：v0.1 的检索流程整体作为第一个子页（下面把它重新绑定为
    # parent 之后，原代码一行不改地落在子页里），「按基因检索」是第二个子页。
    sub = ttk.Notebook(parent)
    sub.pack(fill="both", expand=True)
    legacy = ttk.Frame(sub)
    sub.add(legacy, text=LEGACY_SUBTAB_TITLE)
    gene_page = ttk.Frame(sub)
    sub.add(gene_page, text=tab_gene.TITLE)
    tab_gene.build_subpanel(gene_page, app)
    parent = legacy

    criteria = ttk.LabelFrame(parent, text="检索条件")
```

并把该文件的导入与常量改为（在 `TITLE = "检索与批量下载"` 附近）：

```python
from . import tab_gene

TITLE = "检索与批量下载"
LEGACY_SUBTAB_TITLE = "按物种 / 属名检索"
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tabs.py tests/test_gui_tab_gene.py tests/test_gui_app.py`

预期：全部 PASS（既有 GUI 用例不受影响：它们靠 `_descendants` 在子树里找控件，控件只是换了一层父容器）。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/tab_search.py tests/test_gui_tabs.py
git commit -m "feat(tab_search): 内嵌子选项卡，挂载按基因检索子页（原有流程未改）"
```

---

### 任务 18：整仓回归与真实联网验收

**文件：**
- 修改：`docs/acceptance.md`（追加「周期 1 验收」小节）
- 测试：整仓

**接口：**
- 依赖输入：全部前序任务
- 对外产出：验收记录

- [ ] **步骤 1：跑整仓测试**

运行：`python -m pytest`

预期：全部 PASS，无 FAILED。

- [ ] **步骤 2：真实联网手工验收（必须逐条核对）**

启动 `python main.py`，按规格 §10 的验收表执行：

1. 物种 `Salsola pellucida` + 基因 `ITS` → 检索到 3 条；排除完整基因组后仍 ≥ 1 条；勾选下载得到 `Salsola_pellucida_ITS.fasta`，文件内 header 与文件名一致。
2. 物种 `Nicotiana tabacum` + 基因 `ITS` → 命中 41 条；结果区出现「已排除 N 条完整基因组记录（definition 判据 X 条、长度判据 Y 条）：登录号…」。
3. 基因选 `trnL-F` → 未发起检索；结果区出现「在 GenBank 无可用检索字段，未发起检索」。
4. 物种 `Salsola pellucida` + 基因 `NOTAGENE`（编造名）→ 结果表无行；结果区出现「未检索到 1 个组合：Salsola pellucida × NOTAGENE」。
5. 选择策略切到「取全部候选」，同一组合勾选两条 → 得到 `X_ITS.fasta` 与 `X_ITS_2.fasta`。
6. 下载完成后结果表 GC% 列被回填，未勾选行为空。
7. 「序列拼接」页添加 3 条序列、间隔填 `NNNNNN` → 预览与产物长度 = Σ + 12；上移/下移后重新拼接，内容顺序随之改变。
8. 输出文件已存在时再拼接一次 → 不覆盖，写出 `_1` 且日志有 WARN。

- [ ] **步骤 3：把验收结果写入文档**

在 `docs/acceptance.md` 末尾追加下面这张表，并把「实测」「结论」两列按第 2 步的真实观测结果填满。**任何一条结论不是「通过」的，都必须先修代码、重新验收，不得把不符项原样留在表里。**

```markdown
## 七、周期 1 验收：按基因名检索下载、序列统计、序列拼接

| # | 场景 | 预期 | 实测 | 结论 |
|---|---|---|---|---|
| 1 | Salsola pellucida × ITS | 命中 3 条，排除完整基因组后 ≥1 条，产出 Salsola_pellucida_ITS.fasta | | |
| 2 | Nicotiana tabacum × ITS | 41 条命中、完整质体基因组被排除并报数 | | |
| 3 | trnL-F | 不发请求，给出无可用检索字段说明 | | |
| 4 | NOTAGENE（编造名） | 表格无行，出现「未检索到 1 个组合」 | | |
| 5 | 取全部候选并勾两条 | 产出 X_ITS.fasta 与 X_ITS_2.fasta | | |
| 6 | GC 回填 | 已下载行有 GC，未勾选行为空 | | |
| 7 | 拼接 3 条 + NNNNNN | 长度 = Σ + 12，顺序变更后内容随之改变 | | |
| 8 | 输出已存在 | 让位 _1 并 WARN，不覆盖 | | |
| 9 | 同登录号命中两个基因 | 日志出现「同时命中多个基因」WARN | | |

测试基线：`python -m pytest` 全绿（含任务 1 修好的时间轴用例）。
```

- [ ] **步骤 4：打包验证**

运行：`pyinstaller build.spec`（或仓库现有的 `build_exe.bat`）

预期：打包成功；双击 exe 能启动，六个标签页可见，切到「检索与批量下载」能看到两个子页，无 `ModuleNotFoundError`。比较产物体积与 v0.1 的差异，应无显著增长（新代码全部是标准库）。

- [ ] **步骤 5：提交**

```bash
git add docs/acceptance.md
git commit -m "docs(acceptance): 周期 1 验收记录（按基因检索下载、统计、拼接）"
```

---

### 任务 19：README 更新

**文件：**
- 修改：`README.md`、`README.zh-CN.md`
- 测试：无（文档任务）；收尾跑一次 `python -m pytest` 确认全绿

**接口：**
- 依赖输入：全部前序任务的用户可见行为
- 对外产出：文档

- [ ] **步骤 1：在 README.zh-CN.md 的新增功能章节写入以下内容**

```markdown
### 按基因名检索下载

在「检索与批量下载」页的「按基因检索」子页里填写物种列表（一行一个，
也可从已有的 FASTA / GenBank 文件导入）与基因列表，程序按「物种 × 基因」
逐个组合检索 NCBI，勾选后批量下载为 `物种名_基因名.fasta`。

- **内置基因检索式经过实测标定**：`ITS` 使用 `"internal transcribed spacer"` 短语
  （`ITS[Gene]` 在 GenBank 里命中恒为 0）；`matK` / `rbcL` / `ndhF` / `ycf1`
  使用 `[Gene]` 字段。
- **间隔区类基因（trnL、trnL-F、psbA-trnH、rpl32-trnL）当前无可用检索字段**，
  界面上标注 `⚠` 并直接给出说明，不会发起一次必然为空的检索。
- **完整基因组记录会被自动排除**（definition 命中完整基因组模式，或长度 ≥ 100 kb），
  结果区按两条判据分别报数并列出前 5 个被排除的登录号。需要完整叶绿体/线粒体
  基因组请改用「按物种 / 属名检索」子页，那里支持三种命名模式。
- 命中 0 条的组合**不会**悄悄消失：结果区会明确列出「未检索到 N 个组合」。
- 序列长度在检索阶段即显示；**GC 含量在下载完成后回填**（NCBI 的 esummary
  不提供 GC，只能在拿到序列后计算）。
- 选择策略可切换：「每个组合只取最优一条」（默认，规则为 RefSeq 优先 → 长度最长
  → 发布日期最新）或「取全部候选」（同组合多条会加流水号 `_2`、`_3`）。
- 已知限制：若同一条登录号同时命中两个基因（双位点记录），会各写一份文件，
  两份内容都是该记录的完整序列——本工具不做基因区间提取。

### 序列拼接

「序列拼接」页添加多条序列（可添加文件或整个文件夹），用上移 / 下移 / 置顶 /
置底调整顺序，可选间隔序列（默认 `NNNNNN`，也可留空），实时预览合并后长度，
输出为一条 FASTA。**间隔序列会被下游建树工具当作序列内容，请确认是否需要。**
```

- [ ] **步骤 2：用等价的英文在 README.md 里补上对应章节**

要点与中文版一一对应，至少覆盖：基因检索式经实测标定、间隔区基因不可检索、
完整基因组排除、未命中不静默、GC 下载后回填、两种选择策略、双位点记录的限制、
拼接面板的间隔序列提示。

- [ ] **步骤 3：确认文档没有遗漏外部依赖说明**

README 必须明确：**周期 1 不新增任何外部依赖**（MAFFT、R/V.PhyloMaker2、TNRS
属于后续周期，届时在 README 中说明安装与配置方法）。

- [ ] **步骤 4：跑一次全量测试确认没有被文档之外的东西带坏**

运行：`python -m pytest`

预期：全部 PASS。

- [ ] **步骤 5：提交**

```bash
git add README.md README.zh-CN.md
git commit -m "docs: 补充按基因检索下载与序列拼接的使用说明与已知限制"
```
