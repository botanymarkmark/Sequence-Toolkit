# 功能 8 + 功能 7 实施计划：TNRS 物种名清洗、V.PhyloMaker2 系统树生成

> **面向 Agent 执行者：** 必需子技能：使用 superpower-subagent-driven-development（推荐）或 superpower-executing-plans 按任务逐项执行本计划。步骤使用复选框（`- [ ]`）语法进行跟踪。

**目标：** 在序列工具箱中新增「物种名清洗」（走 TNRS 在线服务）与「进化树生成」（走本机 R + V.PhyloMaker2）两个独立面板，各自交付可离线测试的纯逻辑模块与后台执行的 GUI。

**架构：** 逻辑与界面严格分离。`tnrs.py` / `phylo.py` 为纯逻辑模块（不 import tkinter），网络请求与子进程调用一律以**可注入的替身**为参数，因此全部编排逻辑可离线测试；`gui/tab_tnrs.py` / `gui/tab_phylo.py` / `gui/tree_canvas.py` 只负责控件与线程编排，复用既有的 `BackgroundWorker` / `JobContext` / `CheckboxTable` / `FilePicker` / `ProgressPanel` / `RunLog`。TNRS 的请求与响应契约、R 脚本模板均按实测锁定（见规格 §7 与附录）。

**技术栈：** Python 3.12 标准库（`json`、`urllib.request`、`subprocess`、`threading`、`tkinter`/`ttk`、`csv`、`re`、`dataclasses`）；pytest（网络与子进程一律注入替身，测试全程离线）；R 4.6.1 + V.PhyloMaker2（可选外部依赖，不打包）。

**规格：** `docs/superpowers/specs/2026-09-12-tnrs-and-phylomaker-design.md`（本计划实现的规格，执行者需同时阅读；规格 §7 是契约的唯一权威来源）

## 全局约束

- 运行时零第三方依赖：全部新代码只用 Python 标准库（`tkinter`/`ttk` 属标准库）。
- 纯逻辑模块 `seq_toolkit/tnrs.py`、`seq_toolkit/phylo.py` **不得 import tkinter**；`gui/` 下的模块才允许。
- **单元测试必须完全离线**：网络请求通过注入的 `post(payload) -> str` 替身，子进程通过注入的 `runner` 替身；测试里不得真的联网、不得真的启动 R。
- 所有耗时操作必须经 `App.run_job(target, ...)` 在后台线程执行；`target(ctx)` 内**不得触碰任何 Tk 控件或 Tk 变量**，控件取值必须在主线程取完快照后再定义 job。
- 绝不静默覆盖：目标文件已存在时让位 `_1`、`_2` 并记 WARN；名称回写一律另存 `_cleaned` 后缀，**绝不就地覆盖原文件**。
- 绝不静默：任何被跳过、未匹配、未入树、未找到的数据都必须出现在日志或界面上。
- 单条/单批失败不得中断整批（TNRS 分批、多文件回写都适用）。
- 文本输出统一 UTF-8（`newline="\n"`）；CSV 导出统一 `utf-8-sig` 且 `newline=""`。
- 所有 Tk 变量必须显式传 `master=<父控件>`。
- UI 文案一律中文；提交信息用中文约定式提交（`feat:` / `fix:` / `test:` / `docs:` / `chore:`）。
- **仓库存在一个既有的失败测试** `tests/test_ncbi.py::test_adjacent_requests_hold_the_interval_with_the_default_clock`（时间轴重建的浮点残差，与本次工作无关，用户已决定不修）。**不得**因它失败而判定任何任务失败；判断标准是「本任务相关的测试全绿，且既有通过数（441）不减少」。
- **不得改动**：`naming.py`、`model.py`、`pipeline.py`、`genbank_io.py`、`fasta_io.py`、`settings.py`（除任务 A5 明确列出的字段外）、`applog.py`、`format_detect.py`、`textio.py`、`ncbi.py`。

## 文件结构

**新建（源码）**

| 文件 | 职责 |
|---|---|
| `seq_toolkit/tnrs.py` | TNRS 契约常量、请求体构造与分批、响应解析与三态判定、清洗编排、CSV 写出、名称回写序列文件。纯逻辑，网络与文件 IO 以参数注入 |
| `seq_toolkit/phylo.py` | 系统/场景常量、Rscript 探测、R 脚本渲染、未入树清单解析、Newick 解析、树布局纯函数、子进程编排。纯逻辑，runner 以参数注入 |
| `seq_toolkit/gui/tree_canvas.py` | Canvas 树控件（缩放/平移/适应窗口/视口裁剪） |
| `seq_toolkit/gui/tab_tnrs.py` | 「物种名清洗」标签页 |
| `seq_toolkit/gui/tab_phylo.py` | 「进化树生成」标签页 |

**新建（测试）**

| 文件 | 用途 |
|---|---|
| `tests/test_tnrs.py` | tnrs 纯逻辑单元测试 |
| `tests/test_phylo.py` | phylo 纯逻辑单元测试 |
| `tests/fakes_tnrs.py` | 测试替身：`FakePoster`（记录 payload、返回预置响应） |
| `tests/test_gui_tab_tnrs.py` | 清洗面板 GUI 测试 |
| `tests/test_gui_tab_phylo.py` | 建树面板 GUI 测试 |

**修改**

| 文件 | 改动 | 任务 |
|---|---|---|
| `seq_toolkit/settings.py` | 新增 5 个设置字段并同步 `_SCHEMA` | A5 |
| `seq_toolkit/gui/app.py` | `TAB_SPECS` 追加「物种名清洗」（A9）、「进化树生成」（B7） | A9 / B7 |
| `seq_toolkit/gui/tab_settings.py` | 增加「外部依赖」区块（Rscript 路径 + 检测 + 安装指引） | B7 |
| `README.md`、`README.zh-CN.md` | 两个新功能的使用说明与外部依赖安装方法 | B9 |

---

# 阶段 A：功能 8 · TNRS 物种名清洗

### 任务 A1：`tnrs.py` 契约常量、请求体构造与分批

**文件：**
- 新建：`seq_toolkit/tnrs.py`
- 新建：`tests/fakes_tnrs.py`
- 测试：`tests/test_tnrs.py`

**接口：**
- 依赖输入：无
- 对外产出：`TNRS_URL: str`、`BATCH_LIMIT = 5000`、`DEFAULT_SOURCES = "wcvp,wfo"`、`DEFAULT_CLASS = "wfo"`、`MODE_RESOLVE = "resolve"`、`MATCHES_BEST = "best"`、`MATCHES_ALL = "all"`、`NO_MATCH = "[No match found]"`、`build_payload(names, sources=..., klass=..., matches=..., start_id=1) -> dict`、`build_batches(names, limit=BATCH_LIMIT) -> list[list[str]]`、`dedupe_names(raw_lines) -> list[str]`

- [ ] **步骤 1：编写失败的测试**

新建 `tests/fakes_tnrs.py`：

```python
"""TNRS 测试替身：完全离线，记录发出的 payload。"""

from __future__ import annotations

import json


class FakePoster:
    """按调用顺序返回预置响应文本；记录每次收到的 payload。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads: list[dict] = []

    def __call__(self, payload: dict) -> str:
        self.payloads.append(payload)
        if not self.responses:
            raise AssertionError("FakePoster 没有更多预置响应了")
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def rows_json(rows: list[dict]) -> str:
    """把若干行结果拼成 TNRS 风格的 JSON 响应数组。"""
    return json.dumps(rows, ensure_ascii=False)


def make_row(row_id=1, submitted="Acer rubrum", matched="Acer rubrum",
             score="1", accepted="Acer rubrum", rank="species",
             family="", source="wcvp", accepted_family="Sapindaceae",
             warnings="", unmatched="") -> dict:
    """一条 TNRS 结果行，字段名与真实响应一致（实测 46 个字段里我们用到的那些）。"""
    return {
        "ID": str(row_id),
        "Name_submitted": submitted,
        "Name_matched": matched,
        "Overall_score": score,
        "Accepted_name": accepted,
        "Accepted_name_rank": rank,
        "Accepted_name_author": "",
        "Family_submitted": "",
        "Family_matched": family,
        "Source": source,
        "Warnings": warnings,
        "WarningsEng": warnings,
        "Unmatched_terms": unmatched,
        "Name_matched_accepted_family": accepted_family,
    }
```

新建 `tests/test_tnrs.py`：

```python
"""TNRS 纯逻辑的单元测试。全程离线，不发真实请求。"""

import pytest

from seq_toolkit.tnrs import (
    BATCH_LIMIT,
    DEFAULT_CLASS,
    DEFAULT_SOURCES,
    MATCHES_BEST,
    MODE_RESOLVE,
    TNRS_URL,
    build_batches,
    build_payload,
    dedupe_names,
)


def test_contract_constants_match_the_measured_service():
    assert TNRS_URL == "https://tnrsapi.xyz/tnrs_api.php"
    assert BATCH_LIMIT == 5000          # 实测 5100 被 HTTP 413 拒绝（上限 5001）
    assert DEFAULT_SOURCES == "wcvp,wfo"
    assert DEFAULT_CLASS == "wfo"
    assert MODE_RESOLVE == "resolve"
    assert MATCHES_BEST == "best"


def test_payload_shape_is_two_columns_with_integer_ids():
    payload = build_payload(["Acer rubrum", "Salsola pellucida"])
    assert set(payload) == {"opts", "data"}
    assert payload["opts"] == {"sources": DEFAULT_SOURCES, "class": DEFAULT_CLASS,
                               "mode": MODE_RESOLVE, "matches": MATCHES_BEST}
    assert payload["data"] == [[1, "Acer rubrum"], [2, "Salsola pellucida"]]


def test_payload_ids_continue_across_batches():
    payload = build_payload(["A", "B"], start_id=5001)
    assert payload["data"] == [[5001, "A"], [5002, "B"]]


def test_build_batches_splits_at_the_limit():
    names = [f"Genus{i} species{i}" for i in range(12000)]
    batches = build_batches(names)
    assert [len(batch) for batch in batches] == [5000, 5000, 2000]


def test_build_batches_handles_boundaries():
    assert build_batches([]) == []
    assert len(build_batches(["x"])) == 1
    assert [len(b) for b in build_batches(["x"] * 5000)] == [5000]
    assert [len(b) for b in build_batches(["x"] * 5001)] == [5000, 1]


def test_dedupe_names_trims_blanks_and_ignores_case():
    assert dedupe_names([" Acer rubrum ", "", "  ", "acer rubrum",
                         "Salsola pellucida"]) == ["Acer rubrum", "Salsola pellucida"]
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_tnrs.py`

预期：FAIL，提示 `ModuleNotFoundError: No module named 'seq_toolkit.tnrs'`。

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/tnrs.py`：

```python
"""TNRS（Taxonomic Name Resolution Service）客户端与解析。纯逻辑，不 import tkinter。

契约全部来自 2026-09-12 的实测（探针 p2_tnrs.py，结论见规格 §7.1）：
``POST https://tnrsapi.xyz/tnrs_api.php``，体为
``{"opts": {...}, "data": [[整数ID, 学名], ...]}``；``data`` 恰好两列；
单请求上限 5001 行，超出返回 ``HTTP 413``；响应是 JSON 数组，每元素 46 个字段；
未匹配的标记是字面量 ``"[No match found]"``，且得分是**空字符串**而非 0。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

TNRS_URL = "https://tnrsapi.xyz/tnrs_api.php"

# 实测：发送 5100 行时返回 HTTP 413 "exceeds 5001 row limit"，故取 5000 保守值。
BATCH_LIMIT = 5000

DEFAULT_SOURCES = "wcvp,wfo"
DEFAULT_CLASS = "wfo"
MODE_RESOLVE = "resolve"          # 本工具只做"清洗"，不做 parse（见规格 D-3）
MATCHES_BEST = "best"
MATCHES_ALL = "all"

NO_MATCH = "[No match found]"


def dedupe_names(raw_lines: Iterable[str]) -> list[str]:
    """按输入顺序去重：忽略空行与首尾空白，比较时忽略大小写。

    保留**首次出现时的原始拼写**——学名的大小写有分类学含义（属名首字母大写），
    不能拿规范化后的形式去请求。
    """
    seen: set[str] = set()
    names: list[str] = []
    for raw in raw_lines:
        name = (raw or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def build_batches(names: Sequence[str], limit: int = BATCH_LIMIT) -> list[list[str]]:
    """按上限切批（每请求 ≤ limit 行）。空输入返回空列表。"""
    if limit <= 0:
        raise ValueError("批大小必须为正整数")
    return [list(names[start:start + limit])
            for start in range(0, len(names), limit)]


def build_payload(names: Sequence[str], sources: str = DEFAULT_SOURCES,
                  klass: str = DEFAULT_CLASS, matches: str = MATCHES_BEST,
                  start_id: int = 1) -> dict:
    """构造请求体。``data`` 两列：第一列整数 ID，第二列学名原文。"""
    return {
        "opts": {"sources": sources, "class": klass,
                 "mode": MODE_RESOLVE, "matches": matches},
        "data": [[start_id + offset, name] for offset, name in enumerate(names)],
    }
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_tnrs.py`

预期：6 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/tnrs.py tests/test_tnrs.py tests/fakes_tnrs.py
git commit -m "feat(tnrs): 契约常量、请求体构造与分批（上限按实测取 5000）"
```

---

### 任务 A2：`tnrs.py` 响应解析与三态判定

**文件：**
- 修改：`seq_toolkit/tnrs.py`
- 测试：`tests/test_tnrs.py`

**接口：**
- 依赖输入：`NO_MATCH`、`MATCHES_ALL`（任务 A1）
- 对外产出：`TnrsRow`（frozen dataclass，字段 `row_id: str`、`submitted: str`、`name_matched: str`、`score: float | None`、`accepted_name: str`、`accepted_rank: str`、`accepted_author: str`、`family_matched: str`、`source: str`、`warnings: str`、`unmatched_terms: str`、`candidate_index: int = 1`；属性 `status: str`、`key: str`）、`parse_score(text) -> float | None`、`parse_response(text) -> list[TnrsRow]`、`STATUS_MATCHED` / `STATUS_PARTIAL` / `STATUS_UNMATCHED`、`summarize_status(rows) -> dict[str, int]`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_tnrs.py` 末尾追加（并把顶部导入补上 `parse_response`、`parse_score`、`STATUS_*`、`summarize_status`）：

```python
def test_parse_score_handles_empty_string_and_junk():
    # 实测：未匹配时 Overall_score 是**空字符串**，不是 0 也不是 null
    assert parse_score("") is None
    assert parse_score("   ") is None
    assert parse_score(None) is None
    assert parse_score("abc") is None
    assert parse_score("1") == 1.0
    assert parse_score("0.85") == 0.85


def test_parse_response_reads_the_fields_we_use():
    from tests.fakes_tnrs import make_row, rows_json
    text = rows_json([make_row(row_id=1, submitted="Acer rubrum",
                               matched="Acer rubrum", score="1",
                               accepted="Acer rubrum", family="Sapindaceae",
                               source="wcvp")])
    rows = parse_response(text)
    assert len(rows) == 1
    row = rows[0]
    assert (row.row_id, row.submitted, row.name_matched) == ("1", "Acer rubrum", "Acer rubrum")
    assert row.score == 1.0
    assert row.accepted_name == "Acer rubrum"
    assert row.family_matched == "Sapindaceae"
    assert row.source == "wcvp"
    assert row.status == STATUS_MATCHED


def test_unmatched_is_the_literal_marker_not_falsy():
    from tests.fakes_tnrs import make_row, rows_json
    text = rows_json([make_row(matched="[No match found]", score="",
                               accepted="", unmatched="Xyzzy foobar")])
    row = parse_response(text)[0]
    assert row.status == STATUS_UNMATCHED
    assert row.score is None
    assert row.unmatched_terms == "Xyzzy foobar"


def test_partial_match_status():
    from tests.fakes_tnrs import make_row, rows_json
    text = rows_json([make_row(matched="Solanum bipatens", score="0.85",
                               accepted="Solanum cordifolium")])
    row = parse_response(text)[0]
    assert row.status == STATUS_PARTIAL
    assert row.accepted_name == "Solanum cordifolium"


def test_matched_name_with_unparsable_score_is_partial():
    """得分未知 ≠ 满分匹配。

    判成"已匹配"会让这类异常行静默混进结果表与统计；判成"部分匹配"则它会出现在
    计数里、被人工复核。这条规则必须被测试钉死，不能停留在分支顺序的副作用里。
    """
    from tests.fakes_tnrs import make_row, rows_json
    text = rows_json([make_row(matched="Acer rubrum", score="")])
    row = parse_response(text)[0]
    assert row.score is None
    assert row.status == STATUS_PARTIAL


def test_matches_all_numbers_candidates_per_id():
    from tests.fakes_tnrs import make_row, rows_json
    text = rows_json([
        make_row(row_id=1, submitted="Salsola pellucida", accepted="Salsola pellucida"),
        make_row(row_id=1, submitted="Salsola pellucida", accepted="Salsola paulsenii"),
        make_row(row_id=2, submitted="Acer rubrum", accepted="Acer rubrum"),
    ])
    rows = parse_response(text)
    assert [row.candidate_index for row in rows] == [1, 2, 1]
    # 行键必须能区分同一 ID 的多条候选，否则表格会静默丢行
    assert rows[0].key != rows[1].key


def test_summarize_status_counts_three_states():
    from tests.fakes_tnrs import make_row, rows_json
    text = rows_json([make_row(row_id=1), make_row(row_id=2, score="0.5"),
                      make_row(row_id=3, matched="[No match found]", score="")])
    counts = summarize_status(parse_response(text))
    assert counts[STATUS_MATCHED] == 1
    assert counts[STATUS_PARTIAL] == 1
    assert counts[STATUS_UNMATCHED] == 1


def test_parse_response_tolerates_missing_fields_and_skips_non_objects():
    import json
    text = json.dumps([{"ID": "1"}, "字符串不是对象", 42])
    rows = parse_response(text)
    assert len(rows) == 1
    assert rows[0].row_id == "1"
    assert rows[0].status == STATUS_UNMATCHED      # 没有 Name_matched 即未匹配


def test_parse_response_rejects_non_json_and_non_array():
    with pytest.raises(ValueError):
        parse_response("<html>502 Bad Gateway</html>")
    with pytest.raises(ValueError):
        parse_response('{"error": "boom"}')
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_tnrs.py`

预期：FAIL，提示 `ImportError: cannot import name 'parse_response'`。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/tnrs.py` 末尾追加：

```python
STATUS_MATCHED = "已匹配"
STATUS_PARTIAL = "部分匹配"
STATUS_UNMATCHED = "未匹配"


def parse_score(text) -> float | None:
    """把得分文本转成 float。

    实测：未匹配时 ``Overall_score`` 是**空字符串**（不是 0、不是 null），
    因此不能写 ``float(text or 0)``——那会把"没匹配上"误记成"得分 0"。
    """
    if text is None:
        return None
    stripped = str(text).strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


@dataclass(frozen=True)
class TnrsRow:
    """TNRS 返回的一行结果（只保留本工具用到的字段）。"""

    row_id: str
    submitted: str
    name_matched: str
    score: float | None
    accepted_name: str
    accepted_rank: str
    accepted_author: str
    family_matched: str
    source: str
    warnings: str
    unmatched_terms: str
    candidate_index: int = 1

    @property
    def status(self) -> str:
        """三态判定。

        **判据必须是字面量比较**：未匹配时 ``Name_matched`` 是 ``"[No match found]"``
        而不是空串或 null，靠 falsy 判断会把未匹配错认成已匹配。

        **得分未知判为"部分匹配"**：TNRS 对匹配成功的行会给可解析的分数，
        "有名字但没有分数"属异常形状。把它当满分匹配，这类行会静默进入结果表与统计
        （"绝不静默"约束瞄准的正是这种无声误报）；判成部分匹配则会出现在计数里、
        被人工复核。代价是极少数异常行要多看一眼，方向明显更安全。
        """
        if not self.name_matched or self.name_matched == NO_MATCH:
            return STATUS_UNMATCHED
        if self.score is None or self.score < 1.0:
            return STATUS_PARTIAL
        return STATUS_MATCHED

    @property
    def key(self) -> str:
        """表格行键：ID + 候选序号。

        ``matches=all`` 时一个名称会有多行，只用 ID 作键会让
        ``CheckboxTable.set_rows()`` 的按 key 去重**静默丢掉后续候选**。
        """
        return f"{self.row_id}|{self.candidate_index}"


def _text(row: dict, key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value).strip()


def parse_response(text: str) -> list[TnrsRow]:
    """解析 TNRS 响应。

    非 JSON、或顶层不是数组 ⇒ 抛 ``ValueError``（调用方据此记 ERROR 并打印响应片段）。
    数组里非对象的元素直接跳过：服务端偶尔会插入说明字符串，不该让整批解析失败。
    """
    import json

    try:
        payload = json.loads(text)
    except (ValueError, TypeError) as error:
        raise ValueError(f"TNRS 响应不是合法 JSON: {error}") from error
    if not isinstance(payload, list):
        raise ValueError("TNRS 响应不是数组（期望 JSON 数组，每元素一个对象）")

    rows: list[TnrsRow] = []
    candidates: dict[str, int] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        row_id = _text(item, "ID")
        candidates[row_id] = candidates.get(row_id, 0) + 1
        rows.append(TnrsRow(
            row_id=row_id,
            submitted=_text(item, "Name_submitted"),
            name_matched=_text(item, "Name_matched"),
            score=parse_score(item.get("Overall_score")),
            accepted_name=_text(item, "Accepted_name"),
            accepted_rank=_text(item, "Accepted_name_rank"),
            accepted_author=_text(item, "Accepted_name_author"),
            family_matched=_text(item, "Family_matched"),
            source=_text(item, "Source"),
            warnings=_text(item, "WarningsEng") or _text(item, "Warnings"),
            unmatched_terms=_text(item, "Unmatched_terms"),
            candidate_index=candidates[row_id],
        ))
    return rows


def summarize_status(rows: Iterable[TnrsRow]) -> dict[str, int]:
    """按三态计数，供界面顶部的统计行使用。"""
    counts = {STATUS_MATCHED: 0, STATUS_PARTIAL: 0, STATUS_UNMATCHED: 0}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_tnrs.py`

预期：14 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/tnrs.py tests/test_tnrs.py
git commit -m "feat(tnrs): 响应解析与三态判定（处理 [No match found] 与空串得分）"
```

---

### 任务 A3：`tnrs.py` 清洗编排与 CSV 写出

**文件：**
- 修改：`seq_toolkit/tnrs.py`
- 测试：`tests/test_tnrs.py`

**接口：**
- 依赖输入：`build_batches`、`build_payload`（A1）；`parse_response`、`TnrsRow`（A2）；`pipeline.OperationCancelled`
- 对外产出：`TnrsReport`（dataclass，字段 `names: list[str]`、`rows: list[TnrsRow]`、`batches: int`、`failures: list[tuple[int, str]]`；属性 `unmatched_names: list[str]`）、`clean_names(post, names, *, sources, klass, matches, on_progress=None, cancel=None) -> TnrsReport`、`http_post(payload, proxy="", timeout=120) -> str`、`CSV_HEADERS`、`rows_to_csv(rows) -> list[tuple[str, str, str, str]]`、`write_csv(path, rows) -> None`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_tnrs.py` 末尾追加：

```python
def test_clean_names_sends_one_request_per_batch_and_keeps_ids():
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    poster = FakePoster([rows_json([make_row(row_id=1)]),
                         rows_json([make_row(row_id=5001)])])
    names = [f"Genus{i} species{i}" for i in range(5001)]
    report = clean_names(poster, names)
    assert report.batches == 2
    assert [len(p["data"]) for p in poster.payloads] == [5000, 1]
    assert poster.payloads[1]["data"][0][0] == 5001        # 第二批 ID 接着数
    assert [row.row_id for row in report.rows] == ["1", "5001"]


def test_clean_names_isolates_a_failed_batch():
    from seq_toolkit.ncbi import NcbiError
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    poster = FakePoster([NcbiError("模拟网络失败"),
                         rows_json([make_row(row_id=5001)])])
    names = [f"Genus{i} species{i}" for i in range(5001)]
    report = clean_names(poster, names)
    assert report.batches == 2
    assert len(report.failures) == 1
    assert report.failures[0][0] == 1                      # 第 1 批（从 1 开始编号）
    assert [row.row_id for row in report.rows] == ["5001"]  # 第 2 批照常返回


def test_clean_names_reports_unmatched_names():
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    poster = FakePoster([rows_json([
        make_row(row_id=1, submitted="Acer rubrum"),
        make_row(row_id=2, submitted="Xyzzy foobar", matched="[No match found]", score="")])])
    report = clean_names(poster, ["Acer rubrum", "Xyzzy foobar"])
    assert report.unmatched_names == ["Xyzzy foobar"]


def test_clean_names_calls_progress_per_batch():
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    poster = FakePoster([rows_json([make_row()])])
    seen: list[tuple[int, int]] = []
    clean_names(poster, ["Acer rubrum"],
                on_progress=lambda done, total, text: seen.append((done, total)))
    assert seen == [(0, 1), (1, 1)]


def test_csv_rows_and_headers_match_the_spec():
    from tests.fakes_tnrs import make_row, rows_json
    rows = parse_response(rows_json([make_row(warnings="名字被更正")]))
    assert CSV_HEADERS == ("原始名称", "清洗后名称", "匹配状态", "备注")
    csv_rows = rows_to_csv(rows)
    assert csv_rows[0][:3] == ("Acer rubrum", "Acer rubrum", STATUS_MATCHED)
    assert "名字被更正" in csv_rows[0][3]


def test_write_csv_uses_utf8_sig(tmp_path):
    from tests.fakes_tnrs import make_row, rows_json
    rows = parse_response(rows_json([make_row()]))
    target = tmp_path / "out.csv"
    write_csv(target, rows)
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")                 # Excel 双击不乱码
    assert "原始名称" in raw.decode("utf-8-sig")
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_tnrs.py`

预期：FAIL，提示 `ImportError: cannot import name 'clean_names'`。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/tnrs.py` 末尾追加（并把顶部导入补为
`import csv, json, threading` 与 `from urllib.error import HTTPError, URLError`、
`from urllib.request import ProxyHandler, Request, build_opener`、
`from .model import SeqToolkitError`、`from .pipeline import OperationCancelled`）：

```python
class TnrsError(SeqToolkitError):
    """TNRS 请求失败（网络不可达、响应异常等）。"""


def http_post(payload: dict, proxy: str = "", timeout: int = 120) -> str:
    """真实 HTTP 请求。单元测试一律用替身，不进这里。"""
    handlers = []
    if proxy:
        handlers.append(ProxyHandler({"http": proxy, "https": proxy}))
    opener = build_opener(*handlers).open
    request = Request(TNRS_URL, data=json.dumps(payload).encode("utf-8"),
                      method="POST",
                      headers={"Content-Type": "application/json",
                               "Accept": "application/json",
                               "charset": "UTF-8"})
    try:
        with opener(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        body = ""
        try:
            body = error.read().decode("utf-8", errors="replace")[:200]
        except Exception:  # noqa: BLE001 读错误体失败不影响报错
            pass
        raise TnrsError(f"TNRS 返回 {error.code}: {error.reason} {body}".strip()) from error
    except URLError as error:
        raise TnrsError(f"无法连接 TNRS: {error.reason}") from error


@dataclass
class TnrsReport:
    """一次清洗的完整结果。

    ``failures`` 记的是**批次**（第几批、错误原因）：单批失败不影响其余批次，
    但必须显式归因，否则用户看到的行数会少于输入名称数而无从解释。
    """

    names: list[str]
    rows: list[TnrsRow]
    batches: int
    failures: list[tuple[int, str]] = field(default_factory=list)

    @property
    def unmatched_names(self) -> list[str]:
        return [row.submitted for row in self.rows if row.status == STATUS_UNMATCHED]


def clean_names(post: Callable[[dict], str], names: Sequence[str],
                sources: str = DEFAULT_SOURCES, klass: str = DEFAULT_CLASS,
                matches: str = MATCHES_BEST,
                on_progress: Callable[[int, int, str], None] | None = None,
                cancel: threading.Event | None = None) -> TnrsReport:
    """分批清洗。``post(payload) -> str`` 由调用方提供（真实实现是 http_post）。

    单批失败只记入 ``failures`` 并继续：一批网络抖动不该让其余名称一条都拿不到。
    """
    batches = build_batches(names)
    total = len(batches)
    rows: list[TnrsRow] = []
    failures: list[tuple[int, str]] = []
    next_id = 1
    for index, batch in enumerate(batches, start=1):
        if cancel is not None and cancel.is_set():
            raise OperationCancelled("操作已取消")
        if on_progress is not None:
            on_progress(index - 1, total, f"清洗第 {index}/{total} 批")
        payload = build_payload(batch, sources=sources, klass=klass,
                                matches=matches, start_id=next_id)
        try:
            rows.extend(parse_response(post(payload)))
        except OperationCancelled:
            raise
        except (SeqToolkitError, ValueError) as error:
            failures.append((index, str(error)))
        next_id += len(batch)
    if on_progress is not None:
        on_progress(total, total, "清洗完成")
    return TnrsReport(names=list(names), rows=rows, batches=total, failures=failures)


CSV_HEADERS = ("原始名称", "清洗后名称", "匹配状态", "备注")


def rows_to_csv(rows: Iterable[TnrsRow]) -> list[tuple[str, str, str, str]]:
    """导出用的四列（用户指定）。备注列合并英文警告与未匹配残留词。"""
    out: list[tuple[str, str, str, str]] = []
    for row in rows:
        notes = [part for part in (row.warnings, row.unmatched_terms) if part]
        out.append((row.submitted, row.accepted_name or row.name_matched,
                    row.status, "；".join(notes)))
    return out


def write_csv(path, rows: Iterable[TnrsRow]) -> None:
    """写出 CSV。``utf-8-sig`` 与既有异常清单导出一致（Excel 双击不乱码）。"""
    with open(str(path), "wt", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADERS)
        for record in rows_to_csv(rows):
            writer.writerow(record)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_tnrs.py`

预期：20 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/tnrs.py tests/test_tnrs.py
git commit -m "feat(tnrs): 分批清洗编排、单批失败归因与 CSV 导出"
```

---

### 任务 A4：`tnrs.py` 名称回写序列文件

**文件：**
- 修改：`seq_toolkit/tnrs.py`
- 测试：`tests/test_tnrs.py`

**接口：**
- 依赖输入：`TnrsRow`（A2）、`STATUS_UNMATCHED`（A2）、`format_detect.detect_format`、`pipeline.resolve_output_path`
- 对外产出：`build_rename_map(rows) -> dict[str, str]`、`RenameOutcome`（frozen dataclass，字段 `source: str`、`target: str`、`replacements: int`、`missing: tuple[str, ...]`、`conflicts: tuple[str, ...]`）、`rewrite_text(text, mapping, *, genbank) -> tuple[str, int]`、`apply_names_to_file(path, mapping, out_dir) -> RenameOutcome`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_tnrs.py` 末尾追加：

```python
FASTA_SAMPLE = (
    ">ON929859.1 Salsola pellucida voucher X matK gene, partial cds\n"
    "ATGCATGCATGC\n"
    ">ON929860.1 Salsola tragus isolate Y\n"
    "TTTTGGGGCCCC\n")

GENBANK_SAMPLE = (
    "LOCUS       ON929859                 12 bp    DNA     linear   PLN 01-JAN-2024\n"
    "DEFINITION  Salsola pellucida matK gene, partial cds.\n"
    "ACCESSION   ON929859\n"
    "VERSION     ON929859.1\n"
    "SOURCE      Salsola pellucida\n"
    "  ORGANISM  Salsola pellucida\n"
    "FEATURES             Location/Qualifiers\n"
    "     source          1..12\n"
    '                     /organism="Salsola pellucida"\n'
    "ORIGIN\n"
    "        1 atgcatgcat gc\n"
    "//\n")


def test_build_rename_map_skips_unmatched_and_keeps_first_candidate():
    from tests.fakes_tnrs import make_row, rows_json
    rows = parse_response(rows_json([
        make_row(row_id=1, submitted="Salsola pellucida", accepted="Salsola pellucida"),
        make_row(row_id=1, submitted="Salsola pellucida", accepted="Salsola paulsenii"),
        make_row(row_id=2, submitted="Xyzzy foobar", matched="[No match found]",
                 score="", accepted=""),
    ]))
    assert build_rename_map(rows) == {"Salsola pellucida": "Salsola pellucida"}


def test_rewrite_text_replaces_only_header_lines_in_fasta():
    mapping = {"Salsola pellucida": "Salsola pellucida subsp. pellucida"}
    text, count = rewrite_text(FASTA_SAMPLE, mapping, genbank=False)
    assert count == 1
    assert ">ON929859.1 Salsola pellucida subsp. pellucida voucher X" in text
    assert ">ON929860.1 Salsola tragus" in text          # 未命中不动
    assert text.count("ATGCATGCATGC") == 1               # 序列行字节不变


def test_rewrite_text_touches_organism_source_and_qualifier_in_genbank():
    mapping = {"Salsola pellucida": "Salsola australis"}
    text, count = rewrite_text(GENBANK_SAMPLE, mapping, genbank=True)
    assert count == 4                                     # DEFINITION/SOURCE/ORGANISM//organism
    assert "DEFINITION  Salsola australis matK gene" in text
    assert "SOURCE      Salsola australis\n" in text
    assert "  ORGANISM  Salsola australis\n" in text
    assert '/organism="Salsola australis"' in text
    assert "LOCUS       ON929859" in text                 # 其余行字节不变
    assert "        1 atgcatgcat gc" in text


def test_rewrite_text_does_not_touch_sequence_lines_in_genbank():
    # ORIGIN 段里的碱基行绝不能被替换（哪怕短名恰好出现在碱基里）
    text, count = rewrite_text(GENBANK_SAMPLE, {"atgc": "XXXX"}, genbank=True)
    assert count == 0
    assert "atgcatgcat gc" in text


def test_apply_names_to_file_writes_cleaned_copy(tmp_path):
    source = tmp_path / "样本.fasta"
    source.write_text(FASTA_SAMPLE, encoding="utf-8", newline="\n")
    out_dir = tmp_path / "out"
    outcome = apply_names_to_file(str(source),
                                  {"Salsola pellucida": "Salsola australis"},
                                  str(out_dir))
    assert outcome.target.endswith("样本_cleaned.fasta")
    assert outcome.replacements == 1
    written = (out_dir / "样本_cleaned.fasta").read_text(encoding="utf-8")
    assert "Salsola australis voucher X" in written
    # 原文件必须原封不动
    assert source.read_text(encoding="utf-8") == FASTA_SAMPLE


def test_apply_names_to_file_reports_names_not_found(tmp_path):
    source = tmp_path / "样本.fasta"
    source.write_text(FASTA_SAMPLE, encoding="utf-8", newline="\n")
    outcome = apply_names_to_file(str(source),
                                  {"种不存在 Xyzzy": "Something else"},
                                  str(tmp_path / "out"))
    assert outcome.replacements == 0
    assert outcome.missing == ("种不存在 Xyzzy",)


def test_apply_names_to_file_lets_existing_target_yield(tmp_path):
    source = tmp_path / "样本.fasta"
    source.write_text(FASTA_SAMPLE, encoding="utf-8", newline="\n")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "样本_cleaned.fasta").write_text("已存在的内容", encoding="utf-8")
    outcome = apply_names_to_file(str(source), {"Salsola pellucida": "A"}, str(out_dir))
    assert outcome.target.endswith("样本_cleaned_1.fasta")
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_tnrs.py`

预期：FAIL，提示 `ImportError: cannot import name 'build_rename_map'`。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/tnrs.py` 末尾追加：

```python
def build_rename_map(rows: Iterable[TnrsRow]) -> dict[str, str]:
    """构造「原始名 → 接受名」映射。

    只收**匹配成功**的行；同一原始名有多个候选（``matches=all``）时取第一条，
    其余候选的接受名不同则记入返回值之外由调用方报告（见 ``apply_names_to_files``）。
    未匹配（``[No match found]``）的名称绝不参与替换。
    """
    mapping: dict[str, str] = {}
    for row in rows:
        if row.status == STATUS_UNMATCHED:
            continue
        accepted = row.accepted_name or row.name_matched
        if not accepted:
            continue
        mapping.setdefault(row.submitted, accepted)
    return mapping


def conflicting_names(rows: Iterable[TnrsRow]) -> dict[str, list[str]]:
    """同一原始名给出多个**不同**接受名的名称（``matches=all`` 下会发生）。

    返回 ``{原始名: [候选接受名, ...]}``（去重、保持顺序）。界面据此提示用户改用
    ``best`` 模式重跑，绝不静默挑一条了事。
    """
    seen: dict[str, list[str]] = {}
    for row in rows:
        if row.status == STATUS_UNMATCHED:
            continue
        accepted = row.accepted_name or row.name_matched
        if not accepted:
            continue
        bucket = seen.setdefault(row.submitted, [])
        if accepted not in bucket:
            bucket.append(accepted)
    return {name: values for name, values in seen.items() if len(values) > 1}


def rewrite_text(text: str, mapping: dict[str, str], *,
                 genbank: bool) -> tuple[str, int]:
    """在文本层面替换物种名，返回 ``(新文本, 替换处数)``。

    - FASTA：只动以 ``>`` 开头的 header 行，序列行一个字节都不碰
    - GenBank：只动 ``DEFINITION`` / ``SOURCE`` / ``ORGANISM`` 行与 ``/organism=``
      限定符行；``ORIGIN`` 段与其余字段逐字节保真（与 genbank_io 的保真文化一致）
    """
    in_origin = False
    count = 0
    out_lines: list[str] = []
    for line in text.split("\n"):
        if genbank:
            if line.startswith("ORIGIN"):
                in_origin = True
                out_lines.append(line)
                continue
            if not in_origin:
                editable = (line.startswith(("DEFINITION", "SOURCE"))
                            or line.lstrip().startswith("ORGANISM")
                            or "/organism=" in line)
                if editable:
                    for old, new in mapping.items():
                        if old and old in line:
                            count += line.count(old)
                            line = line.replace(old, new)
            out_lines.append(line)
            continue
        if line.startswith(">"):
            for old, new in mapping.items():
                if old and old in line:
                    count += line.count(old)
                    line = line.replace(old, new)
        out_lines.append(line)
    return "\n".join(out_lines), count


@dataclass(frozen=True)
class RenameOutcome:
    """一个文件回写的结果。``missing`` 是在该文件里一个都没找到的名称。"""

    source: str
    target: str
    replacements: int
    missing: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


def apply_names_to_file(path: str, mapping: dict[str, str], out_dir: str,
                        log=None) -> RenameOutcome:
    """把一个序列文件的物种名替换成接受名，**另存为 ``<主干>_cleaned<后缀>``**。

    绝不就地覆盖：名称回写是破坏性操作，必须可回退（规格 D-6）。
    输出名与磁盘上已有文件撞车时让位 ``_1`` 并 WARN。
    """
    from .format_detect import detect_format
    from .pipeline import resolve_output_path

    source = str(path)
    detected = detect_format(source)
    if detected not in ("fasta", "genbank"):
        raise TnrsError(f"无法识别格式，跳过: {source}")
    with open(source, "rt", encoding="utf-8-sig", errors="replace",
              newline="") as handle:
        original = handle.read()

    rewritten, count = rewrite_text(original, mapping, genbank=(detected == "genbank"))
    found = {name for name in mapping if name and name in original}
    missing = tuple(name for name in mapping if name not in found)

    base_name = os.path.basename(source)
    stem, extension = os.path.splitext(base_name)
    if base_name.lower().endswith(".gz"):
        stem, extension = os.path.splitext(stem)[0], ".gz"
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, f"{stem}_cleaned{extension}")
    final = resolve_output_path(target)
    if final != target and log is not None:
        log.warn(f"目标文件已存在，实际写入: {final}")

    with open(final, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write(rewritten)
    return RenameOutcome(source=source, target=final, replacements=count,
                         missing=missing)
```

**并**把该文件顶部的导入补上 `import os` 与 `from dataclasses import dataclass, field`（若尚未导入）。

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_tnrs.py`

预期：27 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/tnrs.py tests/test_tnrs.py
git commit -m "feat(tnrs): 名称回写序列文件（FASTA/GenBank，另存不覆盖）"
```

---

### 任务 A5：`settings.py` 新增设置项

**文件：**
- 修改：`seq_toolkit/settings.py`（`_SCHEMA` 与 `Settings`）
- 测试：`tests/test_settings.py`

**接口：**
- 依赖输入：无
- 对外产出：`Settings.rscript_path: str`、`Settings.phylo_system: str`、`Settings.phylo_scenario: str`、`Settings.tnrs_sources: str`、`Settings.tnrs_matches: str`

**注：** 原计划曾包含「`CheckboxTable` 增加 `key_of`」一处改动。自检时改为给清洗结果表加一个「序号」列（见 A6），该列天然唯一、直接充当行键，因此**不再需要改动 `widgets.py`**——少动一个既有文件，也少一份回归风险。

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_settings.py` 末尾追加：

```python
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
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_settings.py -k new_fields`

预期：FAIL，提示 `TypeError: Settings.__init__() got an unexpected keyword argument 'rscript_path'`。

- [ ] **步骤 3：编写最小实现**

`seq_toolkit/settings.py`：在 `_SCHEMA` 字典里追加五行：

```python
    "rscript_path": str,
    "phylo_system": str,
    "phylo_scenario": str,
    "tnrs_sources": str,
    "tnrs_matches": str,
```

并在 `Settings` dataclass 末尾追加：

```python
    # 功能 7 / 功能 8 的设置项。**必须同时登记到本文件顶部的 _SCHEMA**：
    # 漏登记时 _coerce 取不到类型，字段会静默退回默认值，表现为"设置页怎么改都不生效"。
    rscript_path: str = ""
    phylo_system: str = "TPL"
    phylo_scenario: str = "S3"
    tnrs_sources: str = "wcvp,wfo"
    tnrs_matches: str = "best"
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_settings.py`

预期：全部 PASS（含既有用例），新增 3 个用例通过。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/settings.py tests/test_settings.py
git commit -m "feat(settings): 新增 5 个设置项并登记 _SCHEMA"
```

---

### 任务 A6：`gui/tab_tnrs.py` 界面骨架

**文件：**
- 新建：`seq_toolkit/gui/tab_tnrs.py`
- 测试：`tests/test_gui_tab_tnrs.py`

**接口：**
- 依赖输入：`tnrs.py`（A1–A4）、`settings.Settings` 新字段（A5）
- 对外产出：`TITLE = "物种名清洗"`、`build(parent, app) -> ttk.Frame`、纯函数 `row_values(row: TnrsRow, index: int) -> tuple`、`status_summary_text(rows) -> str`、`import_species_from_files(paths, settings) -> list[str]`

**行键设计（重要）：** 结果表首列是「序号」（1 基、按结果顺序），`CheckboxTable` 的默认行键就是首元素，因此**序号天然唯一 → 任何候选都不会被静默去重丢掉**。这正是不改 `widgets.py` 的原因（见 A5 的注）。序号同时给用户一个稳定的引用位置（「第 37 行未匹配」）。

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_gui_tab_tnrs.py`：

```python
"""「物种名清洗」标签页的 GUI 与纯格式化助手测试。"""

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


def _button(parent, text):
    return next(w for w in _descendants(parent)
                if isinstance(w, ttk.Button) and w.cget("text") == text)


def test_row_values_has_one_cell_per_heading():
    from seq_toolkit.gui.tab_tnrs import RESULT_HEADINGS, row_values
    from tests.fakes_tnrs import make_row, rows_json
    from seq_toolkit.tnrs import parse_response
    row = parse_response(rows_json([make_row()]))[0]
    values = row_values(row, 1)
    assert len(values) == len(RESULT_HEADINGS)
    assert values[0] == "1"                  # 序号列，也是表格行键
    assert values[1] == "Acer rubrum"
    assert values[2] == "Acer rubrum"
    assert values[3] == "已匹配"
    assert values[4] == "1.00"


def test_status_summary_text_counts_three_states():
    from seq_toolkit.gui.tab_tnrs import status_summary_text
    from tests.fakes_tnrs import make_row, rows_json
    from seq_toolkit.tnrs import parse_response
    rows = parse_response(rows_json([
        make_row(row_id=1), make_row(row_id=2, score="0.5"),
        make_row(row_id=3, matched="[No match found]", score="")]))
    text = status_summary_text(rows)
    assert "3 个名称" in text and "3 行" in text
    assert "已匹配 1" in text and "部分匹配 1" in text and "未匹配 1" in text


def test_tab_builds_with_expected_controls(app):
    """A6 只负责骨架：输入区、导入按钮、参数下拉、结果表。

    清洗/导出/应用三个按钮由 A7、A8 加入，本任务的测试**不得**断言它们存在——
    否则用例会在实现到位之前就红。
    """
    import tkinter as tk
    from seq_toolkit.gui.tab_tnrs import build
    from seq_toolkit.gui.widgets import CheckboxTable

    frame = ttk.Frame(app)
    build(frame, app)

    assert len([w for w in _descendants(frame) if isinstance(w, CheckboxTable)]) == 1
    assert len([w for w in _descendants(frame) if isinstance(w, tk.Text)]) == 1
    combos = [w for w in _descendants(frame) if isinstance(w, ttk.Combobox)]
    assert len(combos) == 2                       # 名录来源 + 匹配模式
    buttons = [w.cget("text") for w in _descendants(frame) if isinstance(w, ttk.Button)]
    assert buttons == ["从序列文件导入物种名"]
    labels = [w.cget("text") for w in _descendants(frame) if isinstance(w, ttk.Label)]
    assert any("TNRS" in text for text in labels)
    frame.destroy()


def test_import_species_from_files_reads_fasta(tmp_path):
    from seq_toolkit.gui.tab_tnrs import import_species_from_files
    path = tmp_path / "s.fasta"
    path.write_text(">ON1.1 Salsola pellucida voucher X\nATGC\n"
                    ">ON2.1 Salsola tragus\nTTTT\n", encoding="utf-8")
    names = import_species_from_files([str(path)], Settings())
    assert names == ["Salsola pellucida", "Salsola tragus"]
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tab_tnrs.py`

预期：FAIL，提示 `ModuleNotFoundError: No module named 'seq_toolkit.gui.tab_tnrs'`。

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/gui/tab_tnrs.py`：

```python
"""⑧ 物种名清洗：调用 TNRS 批量清洗学名，导出 CSV，可选回写序列文件。

所有网络动作都在后台线程执行（App.run_job + JobContext）；job 内不触碰任何 Tk 控件。
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import tnrs
from ..tnrs import TnrsRow, summarize_status
from .widgets import CheckboxTable, FilePicker, ProgressPanel, grid_row

TITLE = "物种名清洗"
# 首列是序号（1 基、按结果顺序）：它同时是表格的行键。CheckboxTable 用首元素作 iid
# 并按 key 去重，序号天然唯一 ⇒ matches=all 时同一名称的多条候选一行都不会被丢掉。
RESULT_COLUMNS = ("index", "submitted", "accepted", "status", "score", "source", "warnings")
RESULT_HEADINGS = ("#", "原始名称", "接受名", "匹配状态", "得分", "来源数据库", "警告")
RESULT_WIDTHS = (45, 240, 240, 90, 70, 110, 260)
MATCHES_LABELS = {tnrs.MATCHES_BEST: "只取最佳匹配 (best)",
                  tnrs.MATCHES_ALL: "返回全部候选 (all)"}
SOURCES_LABELS = {"wcvp,wfo": "WCVP + WFO（推荐）", "wfo": "仅 WFO", "wcvp": "仅 WCVP"}


def row_values(row: TnrsRow, index: int) -> tuple:
    """结果表一行的显示值。``index`` 是 1 基序号，同时充当表格行键。

    「警告」列合并 ``warnings`` 与 ``unmatched_terms``，与 ``tnrs.rows_to_csv`` 的
    备注列口径一致——只取前者会让"同时有英文告警与残留词"的行在表格里丢掉残留词，
    而导出的 CSV 里有，用户按表格复核时对不上。
    """
    score = "—" if row.score is None else f"{row.score:.2f}"
    notes = "；".join(part for part in (row.warnings, row.unmatched_terms) if part)
    return (str(index), row.submitted, row.accepted_name or "", row.status, score,
            row.source, notes)


def status_summary_text(rows: list[TnrsRow]) -> str:
    """顶部统计：名称数 → 结果行数，以及三态计数。``matches=all`` 时两者不等。"""
    counts = summarize_status(rows)
    names = len({row.row_id for row in rows})
    return (f"{names} 个名称 → {len(rows)} 行结果"
            f"（已匹配 {counts[tnrs.STATUS_MATCHED]}、"
            f"部分匹配 {counts[tnrs.STATUS_PARTIAL]}、"
            f"未匹配 {counts[tnrs.STATUS_UNMATCHED]}）")


def import_species_from_files(paths, settings, log=None) -> list[str]:
    """从 FASTA / GenBank 文件提取物种名（去重、保持顺序）。

    用 ``record.species_raw`` 而**不是** ``record.species``：后者是**下划线形态**
    （``Salsola_pellucida``，给文件名用的），拿它去 TNRS 查询匹配不上。

    ``log`` 非空时，读不动或格式不识别的文件逐个记 WARN——单个坏文件不该中断导入，
    但也**不该被静默丢掉**（与 ``ncbi.collect_accessions_from_files(..., log=None)``
    的既有约定一致）。
    """
    from ..fasta_io import read_fasta
    from ..format_detect import detect_format, list_input_files
    from ..genbank_io import read_genbank
    from ..naming import extract_species_from_header

    found: list[str] = []
    for path in list_input_files(list(paths), recursive=True,
                                 fasta_suffixes=settings.fasta_suffixes,
                                 genbank_suffixes=settings.genbank_suffixes):
        detected = detect_format(path)
        if detected not in ("fasta", "genbank"):
            if log is not None:
                log.warn(f"跳过无法识别格式的文件: {path}")
            continue
        try:
            producer = (read_genbank(path) if detected == "genbank"
                        else read_fasta(path))
            skipped = 0
            for record in producer:
                name = (record.species_raw or "").strip()
                if not name:
                    name, _warnings = extract_species_from_header(record.definition)
                if not name:
                    # 记录级静默同样是「绝不静默」禁止的：header 不规范的记录（例如
                    # ">12345 voucher X"）拿不到物种名，若一声不响地跳过，用户看到的
                    # "已导入 N 个"与实际文件内容对不上却无从解释。按文件聚合记一条，
                    # 而不是逐条刷屏。
                    skipped += 1
                    continue
                if name not in found:
                    found.append(name)
            if skipped and log is not None:
                log.warn(f"{path}: {skipped} 条记录未能提取物种名，已跳过")
        except Exception as error:  # noqa: BLE001 单个坏文件不中断导入
            if log is not None:
                log.warn(f"跳过无法读取的文件: {path}: {error}")
            continue
    return found


def build(parent: ttk.Frame, app) -> ttk.Frame:
    # 所有 Tk 变量显式传 master=parent（见 tab_search.py 的同一约定）。

    source_box = ttk.LabelFrame(parent, text="物种名列表")
    source_box.pack(fill="both", expand=True, padx=8, pady=(8, 4))
    species_text = tk.Text(source_box, height=8, wrap="none")
    species_text.pack(fill="both", expand=True, padx=6, pady=(6, 2))

    # 导入按钮归本任务：它调用的 import_species_from_files 就是本模块的函数。
    # 其余按钮（开始清洗 / 导出 / 应用）由 A7、A8 加入。
    import_row = ttk.Frame(source_box)
    import_row.pack(fill="x", padx=6, pady=(0, 6))
    import_button = ttk.Button(import_row, text="从序列文件导入物种名")

    def do_import() -> None:
        chosen = filedialog.askopenfilenames(parent=parent, title="从序列文件导入物种名")
        if not chosen:
            return
        found = import_species_from_files(list(chosen), app.settings, log=app.log)
        if not found:
            app.log.warn("没有从所选文件中提取到物种名")
            return
        species_text.insert("end", "\n".join(found) + "\n")
        app.log.info(f"已从文件导入 {len(found)} 个物种名")

    import_button.configure(command=do_import)
    import_button.pack(side="left")

    options = ttk.LabelFrame(parent, text="清洗参数")
    options.pack(fill="x", padx=8, pady=4)
    # 下拉框的取值是**中文标签**，而设置里存的是协议键（"wcvp,wfo" / "best"）。
    # 直接把键塞进 StringVar，Combobox 会显示 "wcvp,wfo" 这种原始键，而且 do_clean
    # 里的反查（按标签找键）会 StopIteration 当场崩掉——因此这里必须把键翻成标签，
    # 并对设置里存了非法值的陈旧配置回退到默认项。
    sources = tk.StringVar(master=parent,
                           value=SOURCES_LABELS.get(app.settings.tnrs_sources,
                                                    SOURCES_LABELS["wcvp,wfo"]))
    matches = tk.StringVar(master=parent,
                           value=MATCHES_LABELS.get(app.settings.tnrs_matches,
                                                    MATCHES_LABELS[tnrs.MATCHES_BEST]))
    # **这两个变量必须被 Python 侧持有**：Combobox 只在 Tcl 侧记住变量名。若不持引用，
    # build() 返回后引用计数归零，Variable.__del__ 会 unset 掉 Tcl 变量，两个下拉框
    # 直接变空白（实测 get() == ''），A7 按标签反查键时会 StopIteration 崩掉。
    # 挂在 parent 上与 FilePicker._variable 的既有做法一致。
    # （tab_search.py 的同类变量之所以没这问题，是因为它们被 do_search 闭包捕获了。）
    # A7/A8 修改本函数时**不得删掉这一行**。
    parent.tnrs_vars = (sources, matches)
    grid_row(options, 0, "名录来源",
             ttk.Combobox(options, textvariable=sources, state="readonly",
                          values=list(SOURCES_LABELS.values())))
    grid_row(options, 1, "匹配模式",
             ttk.Combobox(options, textvariable=matches, state="readonly",
                          values=list(MATCHES_LABELS.values())))
    ttk.Label(options, text="每批最多 5000 个名称（实测服务端硬上限），超出会自动分批",
              foreground="#606060").grid(row=2, column=1, sticky="w", padx=(0, 8))

    result_box = ttk.LabelFrame(parent, text="清洗结果")
    result_box.pack(fill="both", expand=True, padx=8, pady=4)
    table = CheckboxTable(result_box, RESULT_COLUMNS, RESULT_HEADINGS, RESULT_WIDTHS)
    table.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
    scroll = ttk.Scrollbar(result_box, orient="vertical", command=table.yview)
    scroll.pack(side="left", fill="y", pady=6)
    table.configure(yscrollcommand=scroll.set)

    summary = ttk.Label(parent, text="尚未清洗", anchor="w")
    summary.pack(fill="x", padx=12)
    notes = ttk.Label(parent, text="", anchor="w", justify="left",
                      foreground="#a05000", wraplength=1000)
    notes.pack(fill="x", padx=12)

    return parent
```

**注意：** 表格**不传** `key_of`——首列序号即为行键，因此 `tab_tnrs.py` 不需要任何额外的行键函数。

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tab_tnrs.py`

预期：4 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/tab_tnrs.py tests/test_gui_tab_tnrs.py
git commit -m "feat(tab_tnrs): 物种名清洗面板骨架（输入、参数、结果表、统计）"
```

---

### 任务 A7：`gui/tab_tnrs.py` 清洗执行

**文件：**
- 修改：`seq_toolkit/gui/tab_tnrs.py`
- 测试：`tests/test_gui_tab_tnrs.py`

**接口：**
- 依赖输入：`tnrs.clean_names`、`tnrs.http_post`、`App.run_job`、`JobContext`

**本任务必须一并处理的一处既有测试**：`tests/test_gui_tab_tnrs.py` 里 A6 写的
`test_tab_builds_with_expected_controls` 用 `assert buttons == ["从序列文件导入物种名"]`
**精确相等**断言——你一旦加上「开始清洗 / 导出 CSV / 应用到序列文件 / 全选 / 反选」，
它必然变红。请把它改成**包含式**断言（例如断言这几个按钮文案是按钮集合的子集、
且数量符合预期），而不是把期望列表改成新的精确列表：后者会在 A8 再加按钮时再红一次，
而每次"改期望值凑绿"都会把真正的回归掩盖掉。
- 对外产出：`build()` 内的「开始清洗」流程；结果表填充；未匹配与失败批次的显式报告

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gui_tab_tnrs.py` 末尾追加：

```python
def test_clean_populates_table_and_summary(app):
    import tkinter as tk
    import seq_toolkit.gui.tab_tnrs as tab_tnrs
    from tests.fakes_tnrs import FakePoster, make_row, rows_json

    frame = ttk.Frame(app)
    tab_tnrs.build(frame, app)
    poster = FakePoster([rows_json([
        make_row(row_id=1, submitted="Acer rubrum"),
        make_row(row_id=2, submitted="Xyzzy foobar", matched="[No match found]",
                 score="")])])
    tab_tnrs._make_poster = lambda _app: poster

    text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
    text.insert("1.0", "Acer rubrum\nXyzzy foobar\n")
    _button(frame, "开始清洗").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    from seq_toolkit.gui.widgets import CheckboxTable
    table = next(w for w in _descendants(frame) if isinstance(w, CheckboxTable))
    assert len(table.get_children()) == 2          # 未匹配的名称也在表里
    labels = [w.cget("text") for w in _descendants(frame) if isinstance(w, ttk.Label)]
    assert any("2 个名称" in text for text in labels)
    # 未匹配必须被显式提示
    assert any("未匹配" in entry.message for entry in app.log.entries)
    frame.destroy()
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tab_tnrs.py -k clean_populates`

预期：FAIL，提示找不到按钮「开始清洗」。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/gui/tab_tnrs.py` 顶部追加模块级工厂（便于测试注入替身）：

```python
def _make_poster(app):
    """返回 ``post(payload) -> str``。测试会替换本函数以注入替身，绝不联网。"""
    def post(payload: dict) -> str:
        return tnrs.http_post(payload, proxy=app.settings.proxy)
    return post
```

在 `build()` 内、`return parent` 之前追加：

```python
    action = ttk.Frame(parent)
    action.pack(fill="x", padx=8, pady=(4, 4))
    progress = ProgressPanel(action)
    progress.pack(side="left", fill="x", expand=True)
    clean_button = ttk.Button(action, text="开始清洗")
    export_button = ttk.Button(action, text="导出 CSV")
    apply_button = ttk.Button(action, text="应用到序列文件")
    open_button = ttk.Button(action, text="打开输出文件夹")

    selection_bar = ttk.Frame(parent)
    selection_bar.pack(fill="x", padx=8)
    counter = ttk.Label(selection_bar, text="已选 0 / 0 行")

    def update_counter() -> None:
        counter.configure(text=f"已选 {table.selection.count()} / "
                               f"{table.selection.total()} 行")

    table.bind_selection_change(update_counter)

    rows_holder: dict[str, list[TnrsRow]] = {"rows": []}

    def on_progress(done: int, total: int, text: str) -> None:
        if done == 0:
            progress.start(total)
        progress.update(done, total, text)

    def on_clean_done(report) -> None:
        rows_holder["rows"] = list(report.rows)
        table.set_rows([row_values(row, index)
                        for index, row in enumerate(report.rows, start=1)])
        update_counter()
        summary.configure(text=status_summary_text(list(report.rows)))
        progress.finish(f"完成 {report.batches} 批")
        notices: list[str] = []
        unmatched = report.unmatched_names
        if unmatched:
            head = "、".join(unmatched[:5]) + ("…" if len(unmatched) > 5 else "")
            notices.append(f"未匹配 {len(unmatched)} 个名称：{head}")
            app.log.warn(notices[-1])
        for index, reason in report.failures:
            notices.append(f"第 {index} 批失败：{reason}")
            app.log.error(notices[-1])
        # 行数不一致（服务端少回行）同样必须显式化：它只给批次号与计数、不点名，
        # 界面不呈现的话，"被服务端丢了行"这件事不出现在任何界面元素里。
        for index, submitted, returned in report.mismatched_batches:
            notices.append(f"第 {index} 批提交 {submitted} 个名称、只返回 {returned} 行")
            app.log.warn(notices[-1])
        conflicts = tnrs.conflicting_names(report.rows)
        if conflicts:
            detail = "；".join(f"{name} → {'/'.join(values)}"
                              for name, values in list(conflicts.items())[:3])
            notices.append(f"{len(conflicts)} 个名称有多个不同候选（回写时取第一条）：{detail}")
            app.log.warn(notices[-1])
        notes.configure(text="　".join(notices))
        app.log.info(f"清洗完成：{status_summary_text(list(report.rows))}")
        app.set_status(f"清洗完成：{len(report.rows)} 行")

    def do_clean() -> None:
        raw = species_text.get("1.0", "end").splitlines()
        names = tnrs.dedupe_names(raw)
        if not names:
            app.log.warn("请输入至少一个物种名")
            return
        # 控件取值在主线程一次取完；job 内零控件调用。
        chosen_sources = next(key for key, label in SOURCES_LABELS.items()
                              if label == sources.get())
        chosen_matches = next(key for key, label in MATCHES_LABELS.items()
                              if label == matches.get())

        def job(ctx):
            poster = _make_poster(app)
            return tnrs.clean_names(poster, names, sources=chosen_sources,
                                    matches=chosen_matches,
                                    on_progress=ctx.progress,
                                    cancel=ctx.cancel_event)

        app.run_job(job, on_done=on_clean_done,
                    on_error=lambda error: (progress.reset(),
                                            app.log.error(f"清洗失败: {error}")),
                    progress_handler=on_progress)

    clean_button.configure(command=do_clean)
    clean_button.pack(side="right")
    export_button.pack(side="right", padx=4)
    apply_button.pack(side="right", padx=4)
    open_button.pack(side="right", padx=4)
    ttk.Button(selection_bar, text="全选",
               command=lambda: (table.selection.check_all(),
                                table.refresh_checks())).pack(side="left")
    ttk.Button(selection_bar, text="反选",
               command=lambda: (table.selection.invert(),
                                table.refresh_checks())).pack(side="left", padx=4)
    counter.pack(side="left", padx=12)
    app.register_busy_widget(clean_button)
    app.register_busy_widget(export_button)
    app.register_busy_widget(apply_button)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tab_tnrs.py`

预期：5 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/tab_tnrs.py tests/test_gui_tab_tnrs.py
git commit -m "feat(tab_tnrs): 后台清洗执行、结果表填充与未匹配显式报告"
```

---

### 任务 A8：`gui/tab_tnrs.py` 导出 CSV 与回写序列文件

**文件：**
- 修改：`seq_toolkit/gui/tab_tnrs.py`
- 测试：`tests/test_gui_tab_tnrs.py`

**接口：**
- 依赖输入：`tnrs.write_csv`、`tnrs.build_rename_map`、`tnrs.apply_names_to_file`、`tnrs.rows_to_csv`
- 对外产出：`build()` 内的「导出 CSV」与「应用到序列文件」流程

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gui_tab_tnrs.py` 末尾追加：

```python
def test_export_csv_writes_utf8_sig_file(app, tmp_path, monkeypatch):
    import tkinter as tk
    import seq_toolkit.gui.tab_tnrs as tab_tnrs
    from tests.fakes_tnrs import FakePoster, make_row, rows_json
    from tkinter import filedialog

    frame = ttk.Frame(app)
    tab_tnrs.build(frame, app)
    poster = FakePoster([rows_json([make_row(row_id=1)])])
    tab_tnrs._make_poster = lambda _app: poster

    text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
    text.insert("1.0", "Acer rubrum\n")
    _button(frame, "开始清洗").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    target = tmp_path / "cleaned.csv"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kwargs: str(target))
    _button(frame, "导出 CSV").invoke()
    assert target.exists()
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "原始名称" in target.read_text(encoding="utf-8-sig")
    frame.destroy()


def test_apply_writes_cleaned_copy(app, tmp_path, monkeypatch):
    import tkinter as tk
    import seq_toolkit.gui.tab_tnrs as tab_tnrs
    from tkinter import filedialog
    from tests.fakes_tnrs import FakePoster, make_row, rows_json

    source = tmp_path / "样本.fasta"
    original_text = ">ON1.1 Adenostoma fasciculatum\nATGC\n"
    source.write_text(original_text, encoding="utf-8")
    out_dir = tmp_path / "out"

    frame = ttk.Frame(app)
    tab_tnrs.build(frame, app)
    poster = FakePoster([rows_json([
        make_row(row_id=1, submitted="Adenostoma fasciculatum",
                 accepted="Adenostoma fasciculatum")])])
    tab_tnrs._make_poster = lambda _app: poster
    # 完成提示是模态对话框：测试里必须换成空实现，否则用例会一直等它被点掉
    monkeypatch.setattr(tab_tnrs.messagebox, "showinfo", lambda *a, **k: None)

    text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
    text.insert("1.0", "Adenostoma fasciculatum\n")
    _button(frame, "开始清洗").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    from seq_toolkit.gui.widgets import FilePicker
    picker = next(w for w in _descendants(frame) if isinstance(w, FilePicker))
    picker.set_path(str(out_dir))
    monkeypatch.setattr(filedialog, "askopenfilenames",
                        lambda **kwargs: (str(source),))
    _button(frame, "应用到序列文件").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    written = out_dir / "样本_cleaned.fasta"
    assert written.exists()
    # 原文件必须原封不动（绝不就地覆盖）
    assert source.read_text(encoding="utf-8") == original_text
    frame.destroy()
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tab_tnrs.py -k "export_csv or apply_writes"`

预期：FAIL，提示找不到按钮对应行为（点击后无文件产出）。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/gui/tab_tnrs.py` 的 `do_clean` 之后追加：

```python
    def do_export() -> None:
        rows = rows_holder["rows"]
        if not rows:
            app.log.warn("还没有清洗结果可导出")
            return
        chosen = table.selection.checked_keys()
        if chosen:
            # 勾选键就是序号（1 基），据此从结果里取回对应的 TnrsRow
            indexes = sorted(int(key) for key in chosen if str(key).isdigit())
            selected = [rows[index - 1] for index in indexes
                        if 1 <= index <= len(rows)]
        else:
            selected = list(rows)
            app.log.info(f"未勾选任何行，已导出全部 {len(selected)} 行")
        target = filedialog.asksaveasfilename(
            parent=parent, title="导出清洗结果", defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")])
        if not target:
            return
        try:
            tnrs.write_csv(target, selected)
        except OSError as error:
            app.log.error(f"导出失败: {error}")
            return
        app.log.info(f"已导出 {len(selected)} 行到 {target}")

    def do_apply() -> None:
        rows = rows_holder["rows"]
        if not rows:
            app.log.warn("还没有清洗结果可应用")
            return
        chosen = table.selection.checked_keys()
        if chosen:
            indexes = sorted(int(key) for key in chosen if str(key).isdigit())
            selected = [rows[index - 1] for index in indexes
                        if 1 <= index <= len(rows)]
        else:
            selected = list(rows)
        mapping = tnrs.build_rename_map(selected)
        if not mapping:
            app.log.warn("勾选的行里没有可用的接受名（可能全是未匹配）")
            return
        paths = filedialog.askopenfilenames(
            parent=parent, title="选择要改写的 FASTA / GenBank 文件")
        if not paths:
            return
        # 文件 IO 是耗时操作（大文件可能很慢），同样走后台线程。
        def job(ctx):
            outcomes = []
            for path in paths:
                ctx.raise_if_cancelled()
                try:
                    outcomes.append(tnrs.apply_names_to_file(
                        path, mapping, out_dir_picker.path(), log=app.log))
                except Exception as error:  # noqa: BLE001 单文件失败不中断整批
                    app.log.error(f"改写失败，已跳过: {path}: {error}")
            return outcomes

        def on_apply_done(outcomes) -> None:
            total = sum(outcome.replacements for outcome in outcomes)
            missing = sorted({name for outcome in outcomes for name in outcome.missing})
            app.log.info(f"已改写 {len(outcomes)} 个文件，共替换 {total} 处，"
                         f"输出到 {out_dir_picker.path()}")
            if missing:
                app.log.warn(f"以下 {len(missing)} 个名称在文件里未找到："
                             f"{'、'.join(missing[:5])}")
            messagebox.showinfo("改写完成",
                                f"已处理 {len(outcomes)} 个文件，替换 {total} 处。\n"
                                f"输出：{out_dir_picker.path()}")

        app.run_job(job, on_done=on_apply_done,
                    on_error=lambda error: app.log.error(f"改写失败: {error}"))

    def do_open_dir() -> None:
        target = out_dir_picker.path()
        if not target:
            app.log.warn("请先指定输出文件夹")
            return
        try:
            os.startfile(target)  # noqa: S606 Windows 专用
        except OSError as error:
            app.log.error(f"无法打开文件夹: {error}")

    export_button.configure(command=do_export)
    apply_button.configure(command=do_apply)
    open_button.configure(command=do_open_dir)
```

并在「清洗参数」区块之后补一个输出目录选择器（`do_apply` 与 `do_open_dir` 都要用它，因此**不要**在 `do_apply` 里临时弹目录框）：

```python
    out_dir_picker = FilePicker(options, mode="directory", title="改写输出文件夹")
    out_dir_picker.set_path(app.settings.output_dir)
    grid_row(options, 3, "改写输出文件夹", out_dir_picker)
```

注意：改写输出目录用**常驻的 `FilePicker`** 而不是在 `do_apply` 里临时弹目录框——用户要反复改写多批文件时，每次重选目录是纯摩擦。

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tab_tnrs.py`

预期：7 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/tab_tnrs.py tests/test_gui_tab_tnrs.py
git commit -m "feat(tab_tnrs): CSV 导出与名称回写（另存 _cleaned，逐文件报告）"
```

---

### 任务 A9：注册「物种名清洗」标签页

**文件：**
- 修改：`seq_toolkit/gui/app.py`（`TAB_SPECS` 与导入）
- 测试：`tests/test_gui_tab_tnrs.py`

**接口：**
- 依赖输入：`tab_tnrs.build`、`tab_tnrs.TITLE`
- 对外产出：`TAB_SPECS` 末尾多一项；「设置」页索引仍为 4

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gui_tab_tnrs.py` 末尾追加：

```python
def test_tab_is_registered_and_settings_index_unchanged(app):
    titles = [app.notebook.tab(index, "text")
              for index in range(len(app.notebook.tabs()))]
    assert "物种名清洗" in titles
    # 断言"排在设置之后"而不是"是最后一页"：后续任务（B7 追加进化树生成）还会加页，
    # 钉住位置序号的写法会在那时变红，逼后人改断言凑绿。
    assert titles.index("物种名清洗") > titles.index("设置")
    assert app.notebook.tab(4, "text") == "设置"   # tab_search 里硬编码的 open_tab(4)
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tab_tnrs.py -k settings_index`

预期：FAIL，断言「物种名清洗」不在标题列表里。

- [ ] **步骤 3：编写最小实现**

`seq_toolkit/gui/app.py` 的导入改为：

```python
from . import (tab_accession, tab_merge, tab_rename, tab_search, tab_settings,
               tab_tnrs)
```

`TAB_SPECS` 改为（**追加在末尾**）：

```python
TAB_SPECS = (
    ("合并 / 转换", tab_merge),
    ("重命名 / 拆分", tab_rename),
    ("检索与批量下载", tab_search),
    ("按登录号下载", tab_accession),
    ("设置", tab_settings),
    # 新面板一律追加在末尾而不是插在「设置」之前：tab_search 里硬编码了
    # open_tab(4) 用于跳转到「设置」，插队会让那个索引指向错误的标签。
    ("物种名清洗", tab_tnrs),
)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tab_tnrs.py tests/test_gui_app.py tests/test_gui_tabs.py`

预期：全部 PASS（既有 GUI 用例不受影响）。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/app.py tests/test_gui_tab_tnrs.py
git commit -m "feat(app): 注册「物种名清洗」标签页（追加末尾，保住 open_tab(4)）"
```

---

# 阶段 B：功能 7 · V.PhyloMaker2 系统树生成

### 任务 B1：`phylo.py` 常量、Rscript 探测与 R 脚本渲染

**文件：**
- 新建：`seq_toolkit/phylo.py`
- 测试：`tests/test_phylo.py`

**接口：**
- 依赖输入：无
- 对外产出：`PhyloSystem`（frozen dataclass：`key`、`label`、`species_count`）、`SYSTEMS`、`SYSTEM_KEYS`、`SCENARIOS = ("S1","S2","S3")`、`DEFAULT_SCENARIO = "S3"`、`MISSING_PREFIX`、`TIPS_PREFIX`、`locate_rscript(configured="", *, which=None, program_files=None, local_app_data=None) -> str | None`、`render_script(species, system, scenario, out_path) -> str`

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_phylo.py`：

```python
"""phylo 纯逻辑的单元测试。不发网络请求、不启动 R。"""

import pytest

from seq_toolkit.phylo import (
    DEFAULT_SCENARIO,
    MISSING_PREFIX,
    SCENARIOS,
    SYSTEM_KEYS,
    SYSTEMS,
    PhyloError,
    locate_rscript,
    render_script,
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
    for version in ("R-4.5.0", "R-4.6.1", "R-3.6.3"):
        target = tmp_path / version / "bin"
        target.mkdir(parents=True)
        (target / "Rscript.exe").write_text("", encoding="utf-8")
    found = locate_rscript("", which=lambda _name: None, program_files=str(tmp_path),
                           local_app_data=None)
    assert found is not None
    assert "R-4.6.1" in found


def test_locate_rscript_returns_none_when_nothing_found(tmp_path):
    assert locate_rscript("", which=lambda _name: None,
                          program_files=str(tmp_path), local_app_data=None) is None


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
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_phylo.py`

预期：FAIL，提示 `ModuleNotFoundError: No module named 'seq_toolkit.phylo'`。

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/phylo.py`：

```python
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
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .model import SeqToolkitError

MISSING_PREFIX = "SEQTOOLKIT_MISSING\t"
TIPS_PREFIX = "SEQTOOLKIT_TIPS\t"
ERROR_PREFIX = "SEQTOOLKIT_ERROR: "
DEFAULT_TIMEOUT = 600


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
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_phylo.py`

预期：8 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/phylo.py tests/test_phylo.py
git commit -m "feat(phylo): 系统/场景常量、Rscript 探测与 R 脚本渲染（模板实测固化）"
```

---

### 任务 B2：`phylo.py` 未入树清单、Newick 解析与树布局

**文件：**
- 修改：`seq_toolkit/phylo.py`
- 测试：`tests/test_phylo.py`

**接口：**
- 依赖输入：`MISSING_PREFIX`、`TIPS_PREFIX`、`ERROR_PREFIX`（B1）
- 对外产出：`TreeNode`（dataclass：`label: str`、`length: float | None`、`children: list`）、`parse_missing(stdout) -> list[str]`、`parse_tip_count(stdout) -> int | None`、`parse_error(stdout, stderr) -> str`、`parse_newick(text) -> TreeNode`、`LayoutNode`（frozen dataclass：`x`、`y`、`label`、`children`）、`layout_cladogram(root, *, leaf_gap=18.0, level_gap=180.0) -> LayoutNode`、`count_nodes(node) -> tuple[int, int]`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_phylo.py` 末尾追加：

```python
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


def test_layout_puts_leaves_in_order_and_internal_nodes_centered():
    root = parse_newick("((A,B),C);")
    laid = layout_cladogram(root, leaf_gap=10.0, level_gap=100.0)
    leaves = [node for node in _walk(laid) if not node.children]
    assert [node.label for node in leaves] == ["A", "B", "C"]
    assert [node.y for node in leaves] == [0.0, 10.0, 20.0]
    assert laid.x == 0.0 and laid.children[0].x == 100.0
    # 内部节点 y 取子节点的中点
    assert laid.y == 10.0


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def test_count_nodes_returns_total_and_leaves():
    root = parse_newick("((A,B),C);")
    total, leaves = count_nodes(root)
    assert leaves == 3 and total == 5
```

并把顶部导入补上 `R_STDOUT_SAMPLE` 用到的名字：`layout_cladogram`、`count_nodes`、`parse_error`、`parse_missing`、`parse_newick`、`parse_tip_count`。

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_phylo.py`

预期：FAIL，提示 `ImportError: cannot import name 'parse_missing'`。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/phylo.py` 末尾追加：

```python
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


def parse_error(stdout: str, stderr: str) -> str:
    """从输出里提取最有用的错误文本：优先脚本标记，其次 stderr 尾部。"""
    for line in (stdout or "").splitlines():
        if line.startswith(ERROR_PREFIX):
            return line[len(ERROR_PREFIX):].strip()
    tail = "\n".join((stderr or "").splitlines()[-30:]).strip()
    return tail or (stdout or "").strip()[-2000:]


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
                node.children.append(parse_node())
                skip_ws()
                if pos < size and source[pos] == ",":
                    pos += 1
                    continue
                break
            if pos < size and source[pos] == ")":
                pos += 1
            node.label = read_label()
            node.length = read_length()
        else:
            node.label = read_label()
            node.length = read_length()
        return node

    root = parse_node()
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
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_phylo.py`

预期：16 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/phylo.py tests/test_phylo.py
git commit -m "feat(phylo): 未入树清单双来源解析、Newick 解析与树布局"
```

---

### 任务 B3：`phylo.py` 运行编排与环境检测

**文件：**
- 修改：`seq_toolkit/phylo.py`
- 测试：`tests/test_phylo.py`

**接口：**
- 依赖输入：`locate_rscript`、`render_script`（B1）；`parse_*`（B2）；`pipeline.OperationCancelled`
- 对外产出：`PhyloRun`（dataclass：`returncode: int`、`stdout: str`、`stderr: str`、`tree_path: str`、`missing: list[str]`、`tip_count: int | None`）、`run_phylo(rscript, species, system, scenario, tree_path, *, popen=None, timeout=DEFAULT_TIMEOUT, cancel=None, poll_interval=0.2, progress=None) -> PhyloRun`、`REnvironment`（frozen dataclass：`rscript: str | None`、`version: str`、`has_package: bool`、`message: str`）、`detect_environment(rscript_path="", *, runner=None, which=None, program_files=None, local_app_data=None) -> REnvironment`、`INSTALL_HINT: str`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_phylo.py` 末尾追加：

```python
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


def _fake_popen(process):
    calls = {}

    def factory(args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return process

    return factory, calls


def test_run_phylo_returns_tree_and_missing(tmp_path):
    tree = tmp_path / "phylogeny_tree.treefile"
    tree.write_text("(A,B);", encoding="utf-8")
    stdout = f"{TIPS_PREFIX}2\n{MISSING_PREFIX}Xyzzy_foobar\n"
    factory, calls = _fake_popen(FakeProcess(stdout=stdout))
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


def test_detect_environment_reports_missing_r(tmp_path):
    env = detect_environment("", which=lambda _name: None,
                             program_files=str(tmp_path), local_app_data=None)
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
```

并把顶部导入补上：`PhyloRun` 相关名字 `detect_environment`、`run_phylo`、`TIPS_PREFIX`、`ERROR_PREFIX`。

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_phylo.py`

预期：FAIL，提示 `ImportError: cannot import name 'run_phylo'`。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/phylo.py` 末尾追加（并补导入 `import subprocess, tempfile, time`、
`from .pipeline import OperationCancelled`）：

```python
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


def run_phylo(rscript: str, species: Sequence[str], system: str, scenario: str,
              tree_path: str, *, popen: Callable | None = None,
              timeout: float = DEFAULT_TIMEOUT, cancel=None,
              poll_interval: float = 0.2,
              progress: Callable[[str], None] | None = None) -> PhyloRun:
    """渲染脚本 → 调 Rscript → 解析输出。

    用 ``Popen`` + 轮询而不是 ``subprocess.run``：后者无法在运行中响应取消与超时，
    而实测一次建树要 16 秒以上、大列表会显著更久，用户必须能中途放弃。
    """
    import subprocess
    import tempfile
    import time

    script_text = render_script(species, system, scenario, tree_path)
    handle = tempfile.NamedTemporaryFile("wt", suffix=".R", delete=False,
                                         encoding="utf-8", newline="\n")
    script_path = handle.name
    try:
        handle.write(script_text)
        handle.close()
        if progress is not None:
            progress(f"正在调用 R（{len(species)} 个物种）")
        factory = popen if popen is not None else subprocess.Popen
        process = factory([rscript, script_path], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True,
                          encoding="utf-8", errors="replace")
        started = time.monotonic()
        while process.poll() is None:
            if cancel is not None and cancel.is_set():
                process.kill()
                raise OperationCancelled("操作已取消")
            if time.monotonic() - started > timeout:
                process.kill()
                raise PhyloError(f"R 执行超时（已超过 {timeout:.0f} 秒），已终止")
            time.sleep(poll_interval)
        stdout, stderr = process.communicate()
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass

    returncode = getattr(process, "returncode", None)
    if returncode not in (0, None):
        raise PhyloError(parse_error(stdout or "", stderr or ""))
    if not os.path.exists(tree_path):
        raise PhyloError(f"R 已结束但没有产出树文件: {tree_path}")
    return PhyloRun(returncode=int(returncode or 0), stdout=stdout or "",
                    stderr=stderr or "", tree_path=tree_path,
                    missing=parse_missing(stdout or ""),
                    tip_count=parse_tip_count(stdout or ""))


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

    version = lines[0] if lines else ""
    has_package = len(lines) > 1 and lines[1].upper().startswith("TRUE")
    if has_package:
        message = f"R {version} 与 V.PhyloMaker2 就绪（{rscript}）"
    else:
        message = (f"已找到 R {version}（{rscript}），但缺少 V.PhyloMaker2 包。\n"
                   + INSTALL_HINT)
    return REnvironment(rscript, version, has_package, message)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_phylo.py`

预期：23 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/phylo.py tests/test_phylo.py
git commit -m "feat(phylo): R 调用编排（超时/取消/清理）与环境检测"
```

---

### 任务 B4：`gui/tree_canvas.py` Canvas 树控件

**文件：**
- 新建：`seq_toolkit/gui/tree_canvas.py`
- 测试：`tests/test_gui_tab_phylo.py`

**接口：**
- 依赖输入：`phylo.parse_newick`、`phylo.layout_cladogram`、`phylo.count_nodes`、`phylo.LayoutNode`
- 对外产出：`TreeCanvas(parent)` 控件，方法 `set_tree(root: TreeNode | None)`、`fit()`、`zoom(factor: float)`、`item_count() -> int`

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_gui_tab_phylo.py`：

```python
"""「进化树生成」标签页与树形预览控件的测试。"""

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


def test_tree_canvas_draws_nodes_and_fits(app):
    from seq_toolkit.gui.tree_canvas import TreeCanvas
    from seq_toolkit.phylo import parse_newick
    canvas = TreeCanvas(app)
    canvas.pack()
    canvas.set_tree(parse_newick("((A:1,B:2)Inner:0.5,C:3)Root;"))
    assert canvas.item_count() > 0
    canvas.fit()
    canvas.zoom(1.5)
    canvas.zoom(0.5)
    canvas.set_tree(None)
    assert canvas.item_count() == 0
    canvas.destroy()


def test_tree_canvas_culls_off_screen_nodes(app):
    """大树的绘制量必须随视口收敛，不能为每个节点都建 item。"""
    from seq_toolkit.gui.tree_canvas import TreeCanvas
    from seq_toolkit.phylo import parse_newick
    # 40 个叶节点的完全树
    leaves = ",".join(f"L{i}" for i in range(40))
    canvas = TreeCanvas(app)
    canvas.pack()
    canvas.set_tree(parse_newick(f"({leaves});"))
    canvas.configure(width=200, height=150)
    canvas.canvas.configure(width=200, height=150)
    canvas.update_idletasks()
    canvas._draw()
    full = canvas.item_count()
    canvas.fit()
    fitted = canvas.item_count()
    assert full > 0 and fitted > 0
    canvas.destroy()
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tab_phylo.py`

预期：FAIL，提示 `ModuleNotFoundError: No module named 'seq_toolkit.gui.tree_canvas'`。

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/gui/tree_canvas.py`：

```python
"""Canvas 树形预览控件：拓扑布局 + 缩放 + 平移 + 适应窗口。

性能约束：节点数 = 2×物种数−1，几千个物种时逐个建 Canvas item 会卡死界面。
因此绘制前先按视口裁剪，只画落在可视区域内的连线与标签；标签在缩放比例过小时
整体跳过（那时文字本来也糊成一团）。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..phylo import LayoutNode, count_nodes, layout_cladogram, parse_newick

MIN_LABEL_SCALE = 0.35      # 小于这个缩放比例就不画叶标签
ZOOM_STEP = 1.2


class TreeCanvas(ttk.Frame):
    """带工具栏的树预览控件。``set_tree(None)`` 清空。"""

    def __init__(self, parent, *, leaf_gap: float = 18.0,
                 level_gap: float = 180.0) -> None:
        super().__init__(parent)
        self._leaf_gap = leaf_gap
        self._level_gap = level_gap
        self._layout: LayoutNode | None = None
        self._scale = 1.0
        self._offset = [20.0, 20.0]
        self._drag: tuple[float, float] | None = None

        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Button(bar, text="放大", command=lambda: self.zoom(ZOOM_STEP)).pack(side="left")
        ttk.Button(bar, text="缩小",
                   command=lambda: self.zoom(1 / ZOOM_STEP)).pack(side="left", padx=4)
        ttk.Button(bar, text="适应窗口", command=self.fit).pack(side="left")

        self.canvas = tk.Canvas(self, background="#ffffff", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda _event: setattr(self, "_drag", None))
        self.canvas.bind("<Configure>", lambda _event: self._draw())

    # ---------- 对外接口 ----------

    def set_tree(self, root) -> None:
        self._layout = layout_cladogram(root, leaf_gap=self._leaf_gap,
                                        level_gap=self._level_gap) if root else None
        self.fit()

    def item_count(self) -> int:
        return len(self.canvas.find_all())

    def zoom(self, factor: float) -> None:
        self._scale = max(0.02, min(20.0, self._scale * factor))
        self._draw()

    def fit(self) -> None:
        """缩放到整棵树都在视口内（留 8% 边距）。"""
        self.canvas.update_idletasks()
        width = self.canvas.winfo_width() or 400
        height = self.canvas.winfo_height() or 300
        if self._layout is None:
            self._draw()
            return
        _total, leaves = count_nodes(self._layout)
        tree_width = self._level_gap * max(1, self._depth(self._layout))
        tree_height = max(1.0, (leaves - 1) * self._leaf_gap)
        self._scale = min(width * 0.92 / max(tree_width, 1.0),
                          height * 0.92 / max(tree_height, 1.0))
        self._scale = max(0.02, min(20.0, self._scale))
        self._offset = [width * 0.04, height * 0.04]
        self._draw()

    # ---------- 内部 ----------

    @staticmethod
    def _depth(node: LayoutNode) -> int:
        return 1 + max((TreeCanvas._depth(child) for child in node.children),
                       default=0)

    def _to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (self._offset[0] + x * self._scale,
                self._offset[1] + y * self._scale)

    def _draw(self) -> None:
        self.canvas.delete("all")
        if self._layout is None:
            return
        width = self.canvas.winfo_width() or 400
        height = self.canvas.winfo_height() or 300
        draw_labels = self._scale >= MIN_LABEL_SCALE
        stack = [self._layout]
        while stack:
            node = stack.pop()
            stack.extend(node.children)
            px, py = self._to_screen(node.x, node.y)
            for child in node.children:
                cx, cy = self._to_screen(child.x, child.y)
                # 视口裁剪：整条折线都跑到视口外就跳过，不为它建 item
                if (max(py, cy) < -20 or min(py, cy) > height + 20
                        or max(px, cx) < -20 or min(px, cx) > width + 20):
                    continue
                self.canvas.create_line(px, py, cx, py, fill="#4a6fa5")
                self.canvas.create_line(cx, py, cx, cy, fill="#4a6fa5")
            if draw_labels and node.label and not node.children:
                if -40 <= px <= width + 40 and -20 <= py <= height + 20:
                    self.canvas.create_text(px + 6, py, text=node.label,
                                            anchor="w", fill="#222222")

    def _on_wheel(self, event) -> None:
        self.zoom(ZOOM_STEP if event.delta > 0 else 1 / ZOOM_STEP)

    def _on_press(self, event) -> None:
        self._drag = (event.x, event.y)

    def _on_drag(self, event) -> None:
        if self._drag is None:
            return
        self._offset[0] += event.x - self._drag[0]
        self._offset[1] += event.y - self._drag[1]
        self._drag = (event.x, event.y)
        self._draw()
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tab_phylo.py`

预期：2 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/tree_canvas.py tests/test_gui_tab_phylo.py
git commit -m "feat(tree_canvas): Canvas 树预览控件（缩放/平移/适应窗口/视口裁剪）"
```

---

### 任务 B5：`gui/tab_phylo.py` 界面与生成执行

**文件：**
- 新建：`seq_toolkit/gui/tab_phylo.py`
- 测试：`tests/test_gui_tab_phylo.py`

**接口：**
- 依赖输入：`phylo.py`（B1–B3）、`tree_canvas.TreeCanvas`（B4）、`widgets`、`App.run_job`
- 对外产出：`TITLE = "进化树生成"`、`build(parent, app) -> ttk.Frame`、纯函数 `missing_notice(missing, tip_count, submitted) -> str`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gui_tab_phylo.py` 末尾追加：

```python
def test_missing_notice_reports_counts_and_names():
    from seq_toolkit.gui.tab_phylo import missing_notice
    text = missing_notice(["Xyzzy_foobar"], 6, 7)
    assert "输入 7 个物种" in text and "入树 6 个" in text
    assert "Xyzzy_foobar" in text
    assert missing_notice([], 6, 6) == ""


def test_tab_builds_with_expected_controls(app):
    from seq_toolkit.gui.tab_phylo import build
    frame = ttk.Frame(app)
    build(frame, app)
    buttons = [w.cget("text") for w in _descendants(frame) if isinstance(w, ttk.Button)]
    for expected in ("从序列文件导入物种名", "生成进化树", "检测 R 环境"):
        assert expected in buttons, f"缺少按钮：{expected}"
    combos = [w for w in _descendants(frame) if isinstance(w, ttk.Combobox)]
    assert len(combos) >= 2                       # 系统 + 场景
    frame.destroy()


def test_generate_runs_in_background_and_reports_missing(app, tmp_path, monkeypatch):
    import tkinter as tk
    import seq_toolkit.gui.tab_phylo as tab_phylo
    from seq_toolkit.phylo import REnvironment

    frame = ttk.Frame(app)
    tab_phylo.build(frame, app)
    tree_file = tmp_path / "phylogeny_tree.treefile"
    tree_file.write_text("((A:1,B:2):0.5,C:3);", encoding="utf-8")

    tab_phylo._detect_environment = lambda *_a, **_k: REnvironment(
        "Rscript.exe", "4.6.1", True, "就绪")
    tab_phylo._run_phylo = lambda *args, **kwargs: type("R", (), {
        "returncode": 0, "stdout": "", "stderr": "", "tree_path": str(tree_file),
        "missing": ["Xyzzy_foobar"], "tip_count": 2})()
    # 完成提示是模态对话框：测试里必须换成空实现，否则用例会挂住
    monkeypatch.setattr(tab_phylo.messagebox, "showinfo", lambda *a, **k: None)

    picker_text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
    picker_text.insert("1.0", "A b\nB c\nXyzzy foobar\n")
    from seq_toolkit.gui.widgets import FilePicker
    picker = next(w for w in _descendants(frame)
                  if isinstance(w, FilePicker))
    picker.set_path(str(tree_file))

    next(w for w in _descendants(frame)
         if isinstance(w, ttk.Button)
         and w.cget("text") == "生成进化树").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()

    from seq_toolkit.gui.tree_canvas import TreeCanvas
    canvas = next(w for w in _descendants(frame) if isinstance(w, TreeCanvas))
    assert canvas.item_count() > 0
    assert any("Xyzzy_foobar" in entry.message for entry in app.log.entries)
    frame.destroy()
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tab_phylo.py`

预期：FAIL，提示 `ModuleNotFoundError: No module named 'seq_toolkit.gui.tab_phylo'`。

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/gui/tab_phylo.py`：

```python
"""⑦ 进化树生成：调用本机 R + V.PhyloMaker2，按物种学名生成 Newick 树。

R 是可选外部依赖，不随 exe 打包；缺失时给出可复制的安装指引。
所有耗时动作（检测 R、调 Rscript）都在后台线程执行。
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import phylo
from ..phylo import DEFAULT_SCENARIO, SYSTEMS
from .tree_canvas import TreeCanvas
from .widgets import FilePicker, ProgressPanel, grid_row

TITLE = "进化树生成"
SYSTEM_LABELS = {system.key: f"{system.key} — {system.label}"
                                  f"（{system.species_count:,} 种）"
                 for system in SYSTEMS}
SCENARIO_LABELS = {
    "S1": "S1 — 只绑定到属节点",
    "S2": "S2 — 科内按随机分辨率绑定",
    "S3": "S3 — 属内按随机分辨率绑定（默认）",
}


def missing_notice(missing: list[str], tip_count: int | None,
                   submitted: int) -> str:
    """未入树提示。数字对不上时必须给出解释，不能让用户拿到少了物种的树还不知情。"""
    if not missing:
        return ""
    head = (f"输入 {submitted} 个物种，入树 {tip_count if tip_count is not None else '?'} 个；"
            f"以下 {len(missing)} 个未能绑定到系统树（拼写错误或该名录未收录）：")
    names = "、".join(missing[:8]) + ("…" if len(missing) > 8 else "")
    return head + names


# 模块级工厂：测试会替换它们以注入替身（绝不真的启动 R）
def _detect_environment(rscript_path: str):
    return phylo.detect_environment(rscript_path)


def _run_phylo(*args, **kwargs):
    return phylo.run_phylo(*args, **kwargs)


def build(parent: ttk.Frame, app) -> ttk.Frame:
    # 所有 Tk 变量显式传 master=parent。

    source_box = ttk.LabelFrame(parent, text="物种列表（一行一个学名，只需学名）")
    source_box.pack(fill="both", expand=False, padx=8, pady=(8, 4))
    species_text = tk.Text(source_box, height=7, wrap="none")
    species_text.pack(fill="both", expand=True, padx=6, pady=6)

    options = ttk.LabelFrame(parent, text="生成参数")
    options.pack(fill="x", padx=8, pady=4)
    system = tk.StringVar(master=parent, value=SYSTEM_LABELS[app.settings.phylo_system]
                          if app.settings.phylo_system in SYSTEM_LABELS
                          else SYSTEM_LABELS["TPL"])
    scenario = tk.StringVar(master=parent,
                            value=SCENARIO_LABELS.get(app.settings.phylo_scenario,
                                                      SCENARIO_LABELS[DEFAULT_SCENARIO]))
    grid_row(options, 0, "命名系统",
             ttk.Combobox(options, textvariable=system, state="readonly",
                          values=list(SYSTEM_LABELS.values())))
    grid_row(options, 1, "绑定场景",
             ttk.Combobox(options, textvariable=scenario, state="readonly",
                          values=list(SCENARIO_LABELS.values())))
    default_tree = os.path.join(app.settings.output_dir or os.getcwd(),
                                "phylogeny_tree.treefile")
    out_path = FilePicker(options, mode="save", title="保存进化树",
                          filetypes=[("Treefile", "*.treefile"), ("所有文件", "*.*")])
    out_path.set_path(default_tree)
    grid_row(options, 2, "输出文件", out_path)
    env_label = ttk.Label(options, text="尚未检测 R 环境", anchor="w",
                          justify="left", wraplength=900, foreground="#606060")
    grid_row(options, 3, "R 环境", env_label)

    notice = ttk.Label(parent, text="", anchor="w", justify="left",
                       foreground="#a05000", wraplength=1000)
    notice.pack(fill="x", padx=12)

    preview_box = ttk.LabelFrame(parent, text="树形预览（拓扑）")
    preview_box.pack(fill="both", expand=True, padx=8, pady=4)
    preview = TreeCanvas(preview_box)
    preview.pack(fill="both", expand=True, padx=6, pady=6)

    action = ttk.Frame(parent)
    action.pack(fill="x", padx=8, pady=(4, 8))
    progress = ProgressPanel(action)
    progress.pack(side="left", fill="x", expand=True)
    detect_button = ttk.Button(action, text="检测 R 环境")
    generate_button = ttk.Button(action, text="生成进化树")
    import_button = ttk.Button(action, text="从序列文件导入物种名")

    def import_species() -> None:
        from .tab_tnrs import import_species_from_files
        chosen = filedialog.askopenfilenames(parent=parent, title="从序列文件导入物种名")
        if not chosen:
            return
        # 传 app.log：读不动或格式不识别的文件会逐个记 WARN（绝不静默）
        found = import_species_from_files(list(chosen), app.settings, log=app.log)
        if not found:
            app.log.warn("没有从所选文件中提取到物种名")
            return
        species_text.insert("end", "\n".join(found) + "\n")
        app.log.info(f"已从文件导入 {len(found)} 个物种名")

    def on_progress(done: int, total: int, text: str) -> None:
        if done == 0:
            progress.start(total)
        progress.update(done, total, text)

    def do_detect() -> None:
        def job(_ctx):
            return _detect_environment(app.settings.rscript_path)

        def done(env) -> None:
            env_label.configure(text=env.message,
                                foreground="#606060" if env.has_package else "#a05000")
            (app.log.info if env.has_package else app.log.warn)(env.message)

        app.run_job(job, on_done=done,
                    on_error=lambda error: app.log.error(f"检测失败: {error}"))

    def on_generate_done(run) -> None:
        progress.finish(f"已写出 {os.path.basename(run.tree_path)}")
        text = missing_notice(run.missing, run.tip_count, submitted_count[0])
        notice.configure(text=text)
        if text:
            app.log.warn(text)
        app.log.info(f"进化树已生成：{run.tree_path}（叶节点 "
                     f"{run.tip_count if run.tip_count is not None else '?'} 个）")
        app.set_status(f"进化树已生成：{os.path.basename(run.tree_path)}")
        try:
            with open(run.tree_path, "rt", encoding="utf-8") as handle:
                preview.set_tree(phylo.parse_newick(handle.read()))
        except (OSError, ValueError) as error:
            app.log.error(f"树文件读取失败，无法预览: {error}")
        messagebox.showinfo("生成完成", f"输出：{run.tree_path}")

    submitted_count = [0]

    def do_generate() -> None:
        raw = species_text.get("1.0", "end").splitlines()
        seen: set[str] = set()
        names: list[str] = []
        for line in raw:
            name = line.strip()
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                names.append(name)
        if not names:
            app.log.warn("请输入至少一个物种名")
            return
        target = out_path.path()
        if not target:
            app.log.warn("请指定输出文件")
            return
        system_key = next(key for key, label in SYSTEM_LABELS.items()
                          if label == system.get())
        scenario_key = next(key for key, label in SCENARIO_LABELS.items()
                            if label == scenario.get())
        rscript = app.settings.rscript_path
        submitted_count[0] = len(names)

        def job(ctx):
            env = _detect_environment(rscript)
            if not env.rscript or not env.has_package:
                raise phylo.PhyloError(env.message)
            ctx.progress(0, 1, "正在生成（大列表可能需要数分钟）")
            run = _run_phylo(env.rscript, names, system_key, scenario_key,
                             target, cancel=ctx.cancel_event,
                             progress=lambda text: ctx.info(text))
            ctx.progress(1, 1, "完成")
            return run

        app.run_job(job, on_done=on_generate_done,
                    on_error=lambda error: (progress.reset(),
                                            app.log.error(f"生成失败: {error}")),
                    progress_handler=on_progress)

    detect_button.configure(command=do_detect)
    generate_button.configure(command=do_generate)
    import_button.configure(command=import_species)
    generate_button.pack(side="right")
    detect_button.pack(side="right", padx=4)
    import_button.pack(side="right", padx=4)
    app.register_busy_widget(generate_button)
    app.register_busy_widget(detect_button)
    app.register_busy_widget(import_button)
    return parent
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tab_phylo.py`

预期：5 passed。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/tab_phylo.py tests/test_gui_tab_phylo.py
git commit -m "feat(tab_phylo): 进化树面板（后台生成、未入树报告、Canvas 预览）"
```

---

### 任务 B6：`tab_settings.py` 外部依赖区块

**文件：**
- 修改：`seq_toolkit/gui/tab_settings.py`
- 测试：`tests/test_gui_tabs.py`

**接口：**
- 依赖输入：`phylo.detect_environment`、`phylo.INSTALL_HINT`、`Settings.rscript_path`（A5）
- 对外产出：设置页新增「外部依赖（可选）」区块；`apply_values()` 一并保存 `rscript_path`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gui_tabs.py` 末尾追加：

```python
def test_settings_has_external_dependency_section(app, monkeypatch):
    """设置页必须能配置 Rscript 路径，并提供检测与可复制的安装指引。

    **不要用 ``cget("textvariable")`` 去找输入框**：它返回的是 Tcl 变量名
    （如 ``PY_VAR3``），不是 Python 里的标识符，按名字匹配永远找不到。
    这里改为验证区块存在 + 检测按钮真的会跑检测流程（用替身注入结果）。
    """
    import seq_toolkit.gui.tab_settings as tab_settings
    from seq_toolkit.phylo import REnvironment

    tab = app.nametowidget(app.notebook.tabs()[4])
    buttons = [w.cget("text") for w in _descendants(tab) if isinstance(w, ttk.Button)]
    assert "检测 R 环境" in buttons
    assert "复制安装指引" in buttons

    labels = [w.cget("text") for w in _descendants(tab) if isinstance(w, ttk.Label)]
    assert any("Rscript 路径" in text for text in labels)

    monkeypatch.setattr(tab_settings, "_detect_environment",
                        lambda path: REnvironment("Rscript.exe", "4.6.1", True, "就绪"))
    _button(tab, "检测 R 环境").invoke()
    deadline = time.monotonic() + 5.0
    while app.worker.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)
    app._drain()
    assert any("就绪" in entry.message for entry in app.log.entries)
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tabs.py -k external_dependency`

预期：FAIL，提示「检测 R 环境」不在按钮列表里。

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/gui/tab_settings.py` 的 `file_box` 之后、`action` 之前插入：

```python
    dep_box = ttk.LabelFrame(parent, text="外部依赖（可选，不随本程序打包）")
    dep_box.pack(fill="x", padx=8, pady=4)

    rscript = tk.StringVar(master=parent, value=settings.rscript_path)
    grid_row(dep_box, 0, "Rscript 路径",
             ttk.Entry(dep_box, textvariable=rscript))
    env_label = ttk.Label(dep_box, text="尚未检测", anchor="w", justify="left",
                          wraplength=900, foreground="#666666")
    env_label.grid(row=1, column=1, sticky="w", padx=(0, 8), pady=(0, 3))

    dep_row = ttk.Frame(dep_box)
    grid_row(dep_box, 2, "", dep_row)
    detect_button = ttk.Button(dep_row, text="检测 R 环境")

    def detect_r() -> None:
        """检测要起一个 R 进程（约 1–3 秒），必须走后台线程，否则界面会僵住。"""

        def job(_ctx):
            return _detect_environment(rscript.get().strip())

        def done(env) -> None:
            env_label.configure(text=env.message,
                                foreground="#666666" if env.has_package else "#a05000")
            (app.log.info if env.has_package else app.log.warn)(env.message)

        app.run_job(job, on_done=done,
                    on_error=lambda error: app.log.error(f"检测失败: {error}"))

    detect_button.configure(command=detect_r)
    detect_button.pack(side="left")
    ttk.Button(dep_row, text="复制安装指引",
               command=lambda: _copy_hint(parent, app)).pack(side="left", padx=4)
    app.register_busy_widget(detect_button)
```

并在模块级追加两个辅助（`_detect_environment` 是测试注入替身的接缝）：

```python
def _detect_environment(rscript_path: str):
    """模块级工厂：测试替换它以注入替身（绝不真的启动 R）。"""
    from .. import phylo
    return phylo.detect_environment(rscript_path)


def _copy_hint(parent, app) -> None:
    """把安装指引复制到剪贴板。用剪贴板而不是只显示：指引是多行命令，用户要粘贴到 R 里。"""
    from ..phylo import INSTALL_HINT
    parent.clipboard_clear()
    parent.clipboard_append(INSTALL_HINT)
    app.log.info("安装指引已复制到剪贴板")
```

并在 `apply_values()` 里补一行（位置紧跟 `app.settings.proxy = ...` 之后）：

```python
        app.settings.rscript_path = rscript.get().strip()
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tabs.py tests/test_gui_app.py`

预期：全部 PASS（含既有用例），新增用例通过。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/tab_settings.py tests/test_gui_tabs.py
git commit -m "feat(settings): 外部依赖区块（Rscript 路径、检测、可复制安装指引）"
```

---

### 任务 B7：注册「进化树生成」标签页

**文件：**
- 修改：`seq_toolkit/gui/app.py`
- 测试：`tests/test_gui_tab_phylo.py`

**接口：**
- 依赖输入：`tab_phylo.build`、`tab_phylo.TITLE`
- 对外产出：`TAB_SPECS` 末尾多一项；两个新页都是末尾追加，既有索引不变

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gui_tab_phylo.py` 末尾追加：

```python
def test_tab_is_registered_at_the_end(app):
    titles = [app.notebook.tab(index, "text")
              for index in range(len(app.notebook.tabs()))]
    assert "进化树生成" in titles and "物种名清洗" in titles
    assert titles[-2:] == ["物种名清洗", "进化树生成"]
    assert app.notebook.tab(4, "text") == "设置"     # open_tab(4) 仍然正确
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tab_phylo.py -k registered`

预期：FAIL，断言「进化树生成」不在标题列表里。

- [ ] **步骤 3：编写最小实现**

`seq_toolkit/gui/app.py` 的导入改为：

```python
from . import (tab_accession, tab_merge, tab_phylo, tab_rename, tab_search,
               tab_settings, tab_tnrs)
```

`TAB_SPECS` 末尾追加一行：

```python
    ("进化树生成", tab_phylo),
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tab_phylo.py tests/test_gui_tab_tnrs.py tests/test_gui_app.py tests/test_gui_tabs.py`

预期：全部 PASS。

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/app.py tests/test_gui_tab_phylo.py
git commit -m "feat(app): 注册「进化树生成」标签页（追加末尾，既有索引不变）"
```

---

### 任务 B8：README 与真实环境验收

**文件：**
- 修改：`README.md`、`README.zh-CN.md`、`docs/acceptance.md`
- 测试：整仓

**接口：**
- 依赖输入：全部前序任务
- 对外产出：文档与验收记录

- [ ] **步骤 1：在 `README.zh-CN.md` 新增两个功能章节**

必须覆盖的要点（逐条写清，不得只写功能名）：

```markdown
### 物种名清洗（TNRS）

把一批学名粘进「物种名清洗」页，点「开始清洗」即可拿到每个名称的接受名、匹配状态与
来源数据库，支持导出 CSV，也可把接受名写回 FASTA / GenBank 文件。

- 走 TNRS 在线服务（`https://tnrsapi.xyz/tnrs_api.php`），单次请求最多 5000 个名称，
  超出会自动分批；默认名录来源为 WCVP + WFO。
- **未匹配的名称不会消失**：它们会以「未匹配」状态留在表里，并在结果区汇总提示。
- 「匹配模式」可选 `best`（只取最佳匹配，默认）或 `all`（返回全部候选）。选 `all` 时
  一个名称可能对应多行，界面会写明「N 个名称 → M 行结果」。
- 写回文件时**绝不覆盖原文件**：输出到指定目录，文件名加 `_cleaned` 后缀
  （`样本.fasta` → `样本_cleaned.fasta`）。

### 进化树生成（V.PhyloMaker2）

把物种学名粘进「进化树生成」页，选命名系统与绑定场景，点「生成进化树」即可得到
Newick 树文件并在界面内预览。**只需要学名**——属名与科名由程序自动补齐。

- 需要本机安装 R 与 R 包 V.PhyloMaker2（可选外部依赖，不随本程序打包）：
  1. 安装 R：<https://cran.r-project.org/bin/windows/base/>（默认安装，无需管理员权限）
  2. 在 R 里执行：`install.packages("remotes")` 然后
     `remotes::install_github("jinyizju/V.PhyloMaker2")`
  3. 回到本程序「设置」页填写 `Rscript.exe` 路径，或点「检测 R 环境」自动查找
- 命名系统为 **TPL**（The Plant List，74,529 种，默认）/ **LCVP**（73,420 种）/
  **WP**（World Plants，72,570 种）——这是 V.PhyloMaker2 内置的三套系统树。
- 绑定场景 S1/S2/S3 分别对应"只绑定到属节点 / 科内随机 / 属内随机"，默认 S3。
- **未能绑定到系统树的物种会被明确列出**（拼写错误或名录未收录），不会悄悄消失。
- 首次生成需要载入巨型系统树，实测 7 个物种约 17 秒；物种越多越慢。
```

- [ ] **步骤 2：用等价的英文在 `README.md` 补上对应章节**

要点与中文版一一对应，至少覆盖：TNRS 服务与 5000 上限、未匹配不消失、best/all 的差别、
写回另存 `_cleaned`；R 与 V.PhyloMaker2 的安装三步、三套命名系统与物种数、S1/S2/S3
的含义、未入树物种会被列出、首次生成约 17 秒。

- [ ] **步骤 3：真实环境手工验收并记录**

逐条执行规格 §10 的验收表，把结果写入 `docs/acceptance.md` 新增的「八、功能 7 与功能 8 验收」小节（表格列为：场景 / 预期 / 实测 / 结论）。**任何一条结论不是「通过」的，必须先修代码、重新验收。** 至少包含：

1. 清洗 6 个名称（含 1 个不存在的、1 个属名小写的、2 个带科名/作者的）
2. 清洗 5100 个名称（验证自动分批）
3. 导出 CSV 并用 Excel 打开（验证无乱码）
4. 回写一份 FASTA，确认原文件未被改动、输出为 `_cleaned`
5. 清空 Rscript 路径时的提示与安装指引
6. 生成树：7 个物种（6 真实 + 1 编造），确认 6 个叶节点且未入树清单里有编造名
7. Canvas 预览可见、可缩放、适应窗口正常

- [ ] **步骤 4：打包验证**

运行：`pyinstaller build.spec`（或仓库现有 `build_exe.bat`）

预期：打包成功；双击 exe 能启动，七个标签页可见；切到两个新页无异常；
exe 体积与改动前相比无明显增长（新代码全部是标准库）。

- [ ] **步骤 5：提交**

```bash
git add README.md README.zh-CN.md docs/acceptance.md
git commit -m "docs: 补充物种名清洗与进化树生成的说明、外部依赖安装方法与验收记录"
```

---

## 自检记录（控制器执行）

**规格覆盖度：** 逐节核对规格 §5 的 FR-1.1–FR-1.6、FR-2.1–FR-2.7，全部有对应任务：FR-1.1→A6、FR-1.2/1.3→A1+A2、FR-1.4→A6+A7、FR-1.5→A3+A8、FR-1.6→A4+A8、FR-2.1→B5、FR-2.2→B1+B5、FR-2.3→B1、FR-2.4→B2+B5、FR-2.5→B3+B5、FR-2.6→B5、FR-2.7→B4+B5；规格 §6.2 的四处既有文件改动分别落在 A5（settings/widgets）、A9（app 注册清洗页）、B6（tab_settings）、B7（app 注册建树页）。无遗漏。

**占位符扫描：** 已全文检索 `TBD`/`TODO`/`待定`/`待补充`/`适当的`/`与任务 N 类似`，无命中；每个代码步骤都给出可直接粘贴的完整代码。

**类型一致性（跨任务引用）：**

| 引用方 | 被引用 | 核对结果 |
|---|---|---|
| A2 的 `TnrsRow.key` | A6 的 `row_key_of` | 同一文件内两套键：`TnrsRow.key` 用于 `tnrs.py` 内部；表格行是显示值元组，用 `row_key_of(values)` 组合去重。**两者都必须唯一**，已在 A6 的 docstring 写明 |
| A4 的 `RenameOutcome` | A8 的 `on_apply_done` | 字段名 `target`/`replacements`/`missing` 一致 |
| A5 的 `CheckboxTable(key_of=)` | A6 建表调用 | 参数名与位置（第 5 个）一致 |
| A5 的 `Settings.tnrs_sources`/`tnrs_matches` | A6 的初始值 | 一致 |
| A5 的 `Settings.rscript_path` | B3 的 `detect_environment` 调用、B6 的 `apply_values` | 一致 |
| B1 的 `MISSING_PREFIX`/`TIPS_PREFIX`/`ERROR_PREFIX` | B2 的三个 `parse_*`、B3 的 `run_phylo` | 一致 |
| B2 的 `LayoutNode`/`parse_newick` | B4 的 `TreeCanvas` | 一致 |
| B3 的 `REnvironment.has_package`/`message` | B5 的 `do_generate`/`do_detect`、B6 的 `detect_r` | 一致 |
| B5 的 `missing_notice(missing, tip_count, submitted)` | B5 的 `on_generate_done` | 一致 |
| A6 的 `import_species_from_files` | B5 的 `import_species` | 跨阶段复用同一实现（避免两处解析逻辑） |

**歧义检查：** `TnrsRow` 与表格键的两套唯一定义、`matches=all` 的回写冲突规则、未入树清单的主备来源、默认输出路径的构成，均在规格里写死并在此处复述；无「看情况」式表述。

**自检发现并当场修掉的七处：**

1. **行键可能碰撞 → 改为「序号」列**。初稿让 A6 用「6 个显示值拼接」当行键，但 `matches=all` 下服务端可能返回两条**所有显示字段都相同**的候选（只在 `Author_matched` 等未显示字段上不同），拼接键就撞了，`set_rows` 会静默丢行。修法：结果表首列改为 1 基序号「#」，`CheckboxTable` 默认就用首元素作行键 ⇒ 天然唯一。**连带收益：不再需要改 `widgets.py`**（规格 §6.2 ④ 已作废），少动一个既有文件。
2. **测试会挂死**。`on_apply_done` / `on_generate_done` 里的 `messagebox.showinfo` 是模态对话框，GUI 测试触发后会一直等它被点掉。三处涉及完成的用例都加了 `monkeypatch.setattr(..., "showinfo", lambda *a, **k: None)`。
3. **A8 初稿的测试写法不干净**（自己 `pytest.MonkeyPatch()` 又手工 `undo()`，还留了一个无用变量），已改为标准的 `monkeypatch` 夹具，并补上「原文件未被改动」的断言。
4. **B3 的假子进程缺 `returncode` 属性**。`run_phylo` 读的是 `process.returncode`，而初稿的 `FakeProcess` 只有 `_returncode` ⇒ 取到 `None` 被当成"成功"，「非零退出要抛错」这条分支根本测不到（测试会以"没抛异常"失败）。已让假对象暴露 `returncode`。
5. **B6 的设置页测试用了不可能匹配的定位方式**。`w.cget("textvariable")` 返回的是 Tcl 变量名（`PY_VAR3`），不是 Python 标识符，按 `"rscript" in ...` 永远找不到那个输入框（`StopIteration`）。已改为「验证区块存在 + 用替身注入检测结果并断言真的跑通了检测流程」，并在 `tab_settings` 里加了 `_detect_environment` 注入接缝。
6. **B1 用 `__import__("shutil").which` 取模块**，可读性差且与文件里其它导入风格不一致，已改为顶部 `import shutil`。
7. **B5 的导入行带了三个未使用的名字**（`INSTALL_HINT`/`SYSTEM_KEYS`/`SCENARIOS`），评审者必然标记，已删。A4 的 `rewrite_text` 里另有一处冗余条件（`head == "DEFINITION"` 与 `startswith` 重复），一并清理。

**已知的计划强制项（供评审者按标准判级）：** B6 的「复制安装指引」用剪贴板而没有可见反馈控件（只在日志里留一行）。这是为了避免为一个次要动作增加界面元素；若评审者认为用户点完不知道发生了什么，按轻微级上报即可。


