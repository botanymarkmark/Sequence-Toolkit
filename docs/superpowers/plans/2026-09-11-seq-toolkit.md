# 序列工具箱（Sequence Toolkit）实施计划

> **面向 Agent 执行者：** 必需子技能：使用 superpower-subagent-driven-development（推荐）或 superpower-executing-plans 按任务逐项执行本计划。步骤使用复选框（`- [ ]`）语法进行跟踪。

**目标：** 交付一个免安装的 Windows 单文件 exe，把"合并 FASTA/GenBank、GenBank 转 FASTA、序列命名规范化、按登录号或按物种/属检索批量下载 NCBI 序列"整合为一个 Tkinter 图形界面工具。

**架构：** 分 5 层单向依赖：`gui/` → `pipeline.py` → `fasta_io.py`/`genbank_io.py` → `model.py`，`naming.py` 为纯函数引擎，`ncbi.py` 独立封装 E-utilities。所有跨层数据都走不可变的 `SequenceRecord`；解析与命名逻辑不依赖 GUI，可在无图形环境下被 pytest 完整覆盖。合并、转换、改名、拆分在 `pipeline.py` 中共享同一套"读 → 去重 → 命名 → 写"流程。

**技术栈：** Python 3.12（用户级安装）、Tkinter（标准库）、`urllib.request`（标准库）。**运行时零第三方依赖**；`pytest` 与 `pyinstaller` 仅用于开发与打包。打包方式 PyInstaller `--onefile --windowed`。

**规格：** `docs/superpowers/specs/2026-09-11-seq-toolkit-design.md`

## 全局约束

- 运行时**不得引入任何第三方库**；仅使用 Python 标准库（`tkinter`、`urllib.request`、`gzip`、`re`、`json`、`dataclasses`、`threading`、`queue`、`pathlib`）。
- 所有文本文件读写必须**显式指定** `encoding="utf-8"`（读入用 `utf-8-sig` 以兼容 BOM）、`newline="\n"` 输出；禁止依赖平台默认编码。
- 必须支持**中文路径与中文文件名**（Windows 上的经典坑，作为一等测试场景）。
- **任何输出文件永不静默覆盖**：目标已存在时递增追加 `_1`、`_2`，并在日志中说明实际写入路径。
- Tkinter 控件**只能在主线程更新**；任何网络或批量文件 IO 必须在后台线程执行，通过 `queue.Queue` 回传进度，主线程用 `root.after(100, ...)` 消费。
- 登录号一律**统一转大写**存储与比较。
- 单条记录失败**不得中断整批**：记入异常清单后继续处理其余记录。
- `SequenceRecord` 为 `frozen=True`，跨层传递时不得就地修改。
- 提交信息使用 Conventional Commits（`feat:` / `fix:` / `test:` / `docs:` / `chore:`）。
- 每个任务结束时测试必须全绿，并单独提交。

---

### Task 1：项目脚手架与测试基线

**文件：**
- 新建：`.gitignore`
- 新建：`requirements.txt`
- 新建：`pytest.ini`
- 新建：`seq_toolkit/__init__.py`
- 新建：`seq_toolkit/gui/__init__.py`
- 新建：`tests/__init__.py`
- 测试：`tests/test_smoke.py`

**接口：**
- 依赖输入：无（起始任务）
- 对外产出：`seq_toolkit` 包可导入，`seq_toolkit.__version__ == "0.1.0"`；后续所有任务都在此包内新增模块

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_smoke.py`：

```python
import sys

import seq_toolkit


def test_package_importable():
    assert seq_toolkit.__version__ == "0.1.0"


def test_python_version_is_supported():
    assert sys.version_info >= (3, 11), "需要 Python 3.11 及以上"
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_smoke.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit'`

- [ ] **步骤 3：建立最小包结构**

新建 `seq_toolkit/__init__.py`：

```python
"""序列工具箱：FASTA/GenBank 合并、转换、命名规范化与 NCBI 批量下载。"""

__version__ = "0.1.0"
```

新建 `seq_toolkit/gui/__init__.py`（空文件，仅用于把 GUI 子包变为可导入包）。

新建 `tests/__init__.py`（空文件，避免测试模块重名冲突）。

新建 `pytest.ini`：

```ini
[pytest]
testpaths = tests
addopts = -q
```

新建 `requirements.txt`：

```
# 运行时零第三方依赖：仅使用 Python 标准库。
# 以下仅用于开发与打包，安装方式：python -m pip install -r requirements.txt
pytest>=8.0
pyinstaller>=6.0
```

新建 `.gitignore`：

```
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
venv/
build/
dist/
*.log
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_smoke.py -v`
预期：PASS（2 passed）

- [ ] **步骤 5：提交**

```bash
git add .gitignore requirements.txt pytest.ini seq_toolkit tests
git commit -m "chore: 初始化项目脚手架与 pytest 基线"
```

---

### Task 2：统一数据模型 `model.py`

**文件：**
- 新建：`seq_toolkit/model.py`
- 测试：`tests/test_model.py`

**接口：**
- 依赖输入：无
- 对外产出：
  - `AccessionParts` —— `NamedTuple`，字段依次为 `accession: str`、`base: str`、`version: int | None`、`well_formed: bool`
  - `parse_accession(raw: str) -> AccessionParts`
  - `SequenceRecord` —— `frozen=True` 的 dataclass，字段顺序为 `accession, accession_base, version, species, species_raw, lineage, definition, seq, source_format, origin_path, origin_line, date="", raw_block="", warnings=()`
  - `SequenceRecord.with_warning(*messages: str) -> SequenceRecord`
  - `SequenceRecord.length -> int`（property）
  - 异常：`SeqToolkitError`（所有自定义异常的基类）

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_model.py`：

```python
import pytest

from seq_toolkit.model import SequenceRecord, parse_accession


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


def test_parse_accession_simple_form_is_uppercased():
    parts = parse_accession("on929859.1")
    assert parts.accession == "ON929859.1"
    assert parts.base == "ON929859"
    assert parts.version == 1
    assert parts.well_formed is True


def test_parse_accession_refseq_underscore_form():
    parts = parse_accession("NC_027224.1")
    assert parts.base == "NC_027224"
    assert parts.version == 1
    assert parts.well_formed is True


def test_parse_accession_without_version():
    parts = parse_accession("ON929859")
    assert parts.accession == "ON929859"
    assert parts.version is None
    assert parts.well_formed is True


def test_parse_accession_multi_digit_version():
    parts = parse_accession("ON929859.12")
    assert parts.base == "ON929859"
    assert parts.version == 12
    assert parts.well_formed is True


def test_parse_accession_ill_formed_still_splits_version():
    parts = parse_accession("scaffold_12.3")
    assert parts.base == "SCAFFOLD_12"
    assert parts.version == 3
    assert parts.accession == "SCAFFOLD_12.3"
    assert parts.well_formed is False


def test_parse_accession_handles_empty_string():
    parts = parse_accession("")
    assert parts.accession == ""
    assert parts.base == ""
    assert parts.version is None
    assert parts.well_formed is False


def test_record_is_hashable_and_immutable():
    record = _rec()
    assert isinstance(hash(record), int)
    with pytest.raises(Exception):
        record.accession = "OTHER.1"


def test_with_warning_returns_new_record():
    record = _rec()
    updated = record.with_warning("a", "b")
    assert record.warnings == ()
    assert updated.warnings == ("a", "b")


def test_length_property():
    assert _rec(seq="ACGTACGT").length == 8
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_model.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit.model'`

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/model.py`：

```python
"""统一数据模型：跨模块传递序列记录的唯一契约。"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import NamedTuple

# 覆盖 ON929859.1 这类常规形式，以及 NC_027224.1 / NZ_CM000001.1 这类 RefSeq 形式
_ACCESSION_RE = re.compile(
    r"^(?:[A-Z]{1,4}[0-9]{5,8}|[A-Z]{2}_[0-9]{6,9})(?:\.[0-9]+)?$"
)


class SeqToolkitError(Exception):
    """本工具所有自定义异常的基类。"""


class AccessionParts(NamedTuple):
    accession: str
    base: str
    version: int | None
    well_formed: bool


def parse_accession(raw: str) -> AccessionParts:
    """把任意来历的登录号拆成 (完整登录号, 基号, 版本号, 是否通过格式校验)。

    统一转大写。即使格式不合规，也尽力拆出版本号，并通过 well_formed 标记异常，
    由调用方决定是记警告还是回退。
    """
    upper = (raw or "").strip().upper()
    if _ACCESSION_RE.match(upper):
        base, _, tail = upper.partition(".")
        version = int(tail) if tail else None
        return AccessionParts(upper, base, version, True)

    base = upper
    version = None
    if "." in upper:
        head, _, tail = upper.rpartition(".")
        if tail.isdecimal():
            base, version = head, int(tail)
    accession = f"{base}.{version}" if version is not None else base
    return AccessionParts(accession, base, version, False)


@dataclass(frozen=True)
class SequenceRecord:
    """一条序列及其元数据。不可变，可哈希（因此可直接用作字典键）。"""

    accession: str
    accession_base: str
    version: int | None
    species: str
    species_raw: str
    lineage: str
    definition: str
    seq: str
    source_format: str
    origin_path: str
    origin_line: int
    date: str = ""
    raw_block: str = ""
    warnings: tuple[str, ...] = ()

    def with_warning(self, *messages: str) -> "SequenceRecord":
        return replace(self, warnings=self.warnings + tuple(messages))

    @property
    def length(self) -> int:
        return len(self.seq)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_model.py -v`
预期：PASS（9 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/model.py tests/test_model.py
git commit -m "feat(model): 增加 SequenceRecord 与登录号解析"
```

---

### Task 3：命名规范化 `sanitize_accession` / `sanitize_species`

**文件：**
- 新建：`seq_toolkit/naming.py`
- 测试：`tests/test_naming.py`

**接口：**
- 依赖输入：`seq_toolkit.model.SequenceRecord`、`parse_accession`
- 对外产出：
  - `sanitize_accession(text: str) -> str` —— 仅保留 `[A-Za-z0-9._-]`，**句点保留**（版本号分隔符）
  - `sanitize_species(text: str) -> str` —— 空格转 `_`、`×` 转 `x`、**句点删除**
  - 模块级常量 `PUNCT_CHARS: str`（供后续任务复用）

> **为什么必须拆成两个函数：** 句点 `ON929859.1` 中是版本号分隔符必须保留，`Salsola sp.` 中是缩写标点必须删除。同一个字符在两个组成部分里处理方式相反，合并成一个函数会把登录号破坏成 `ON9298591`。

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_naming.py`：

```python
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
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_naming.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit.naming'`

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/naming.py`：

```python
"""命名规则引擎：全部为纯函数，不做任何文件或网络 IO。"""

from __future__ import annotations

import re

# 比较停用词、种下标记词时统一剥离的首尾标点
PUNCT_CHARS = ".,;:()[]{}\"'*?<>/\\|`"

_KEEP_ACCESSION = re.compile(r"[^A-Za-z0-9._-]")
_DROP_SPECIES = re.compile(r"[|,;:()\[\]{}\"'*?<>/\\`\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")
_UNDERSCORES = re.compile(r"_+")


def sanitize_accession(text: str) -> str:
    """登录号规范化：删除空白与非法字符，**保留句点**（版本号分隔符）。"""
    stripped = text.replace("\u3000", "").replace(" ", "")
    return _KEEP_ACCESSION.sub("", stripped)


def sanitize_species(text: str) -> str:
    """物种名规范化：空白转下划线、杂交符号转 x、**删除句点**与其余标点。"""
    text = text.replace("\u3000", " ").replace("\t", " ")
    text = _SPACES.sub(" ", text).strip()
    text = text.replace("×", "x").replace(".", "")
    text = _DROP_SPECIES.sub("", text)
    text = text.replace(" ", "_")
    return _UNDERSCORES.sub("_", text).strip("_")
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_naming.py -v`
预期：PASS（12 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/naming.py tests/test_naming.py
git commit -m "feat(naming): 增加登录号与物种名的规范化函数"
```

---

### Task 4：物种名智能提取 `extract_species_from_header`

**文件：**
- 修改：`seq_toolkit/naming.py`（追加常量与函数）
- 修改：`tests/test_naming.py`（追加测试）

**接口：**
- 依赖输入：`seq_toolkit.naming.PUNCT_CHARS`（任务 3 产出）
- 对外产出：
  - `extract_species_from_header(header_body: str) -> tuple[str, tuple[str, ...]]` —— 返回 `(species_raw, warnings)`；提取失败时返回 `("", ("无法从 header 提取物种名",))`
  - 模块级常量 `STOPWORDS: frozenset[str]`、`INFRASPECIFIC: frozenset[str]`、`DISGUISE_PREFIXES: tuple[str, ...]`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_naming.py` 末尾追加：

```python
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
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_naming.py -v`
预期：FAIL，`ImportError: cannot import name 'extract_species_from_header'`

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/naming.py` 的 import 区块之后、`sanitize_accession` 之前插入常量：

```python
# 命中即终止扫描：这些词之后的内容不属于物种名
STOPWORDS = frozenset({
    "chloroplast", "mitochondrion", "mitochondrial", "mitogenome", "plastid",
    "plastome", "genome", "complete", "partial", "sequence", "sequences",
    "chromosome", "contig", "scaffold", "segment", "isolate", "voucher",
    "clone", "strain", "cultivar", "cv", "breed", "culture", "gene", "genes",
    "mrna", "rrna", "trna", "dna", "rna", "its", "whole", "shotgun", "wgs",
    "assembly", "chromosome-level", "complete-genome", "genomic", "dna-sequence",
})

# 命中即吸收进物种名（种下等级标记），随后至多再吸收一个词
INFRASPECIFIC = frozenset({
    "sp", "spp", "cf", "aff", "subsp", "ssp", "var", "fo", "f", "nothosubsp",
    "x", "×",
})

# 伪装成物种名的前缀，须整词剥离。
# 按长度降序排列只是防御性写法：当前 8 个前缀两两之间不存在前缀关系
# （'tpa:' 的第 4 个字符是 ':'，'tpa_exp:' 是 '_'），因此顺序目前不影响正确性，
# 但将来若加入真正互为前缀的项（如 'tpa' 与 'tpa_exp:'），此排序即成为必要。
DISGUISE_PREFIXES = tuple(sorted(
    ("unverified:", "mag:", "tpa:", "tpa_exp:", "tpa_inf:", "tpa_asm:",
     "tsa:", "wgs:"),
    key=len,
    reverse=True,
))

# 物种名最多由几个词构成。硬上限，防止畸形 header 吞掉整行。
# 注意：标记词分支在同一次迭代内会追加 2 个词，因此该分支也必须重复检查此上限，
# 否则实际上界会变成 5（历史上曾有此缺陷）。
MAX_SPECIES_TOKENS = 4
```

在 `sanitize_species` 之后追加：

```python
def _compare_key(token: str) -> str:
    """生成用于和停用词/标记词比较的键：转小写并剥离首尾标点。"""
    return token.strip(PUNCT_CHARS).lower()


def extract_species_from_header(header_body: str) -> tuple[str, tuple[str, ...]]:
    """从 FASTA header（已剥离登录号）或 GenBank DEFINITION 中提取物种名。

    返回 (species_raw, warnings)。species_raw 保持原始拼写，规范化由
    sanitize_species() 负责。提取失败时 species_raw 为空串。
    """
    warnings: list[str] = []

    # 步骤 1：归一化空白
    text = header_body.replace("\u3000", " ").replace("\t", " ").strip()
    # 杂交符号两侧统一补空格：使 '×tragus'、'Salsola×tragus' 与规范写法 'Salsola × tragus'
    # 等价。否则粘连形式下 × 既非大写字母也非可吸收的小写词，扫描直接终止，会静默只取到属名。
    text = _SPACES.sub(" ", text.replace("×", " × ")).strip()

    # 步骤 2：循环剥离伪装前缀
    changed = True
    while changed:
        changed = False
        lowered = text.lower()
        for prefix in DISGUISE_PREFIXES:
            if not lowered.startswith(prefix):
                continue
            remainder = text[len(prefix):]
            if remainder and not remainder[0].isspace():
                continue
            text = remainder.lstrip()
            warnings.append(f"已剥离伪装前缀 {prefix}")
            changed = True
            break

    # 步骤 3：分词
    tokens = [token for token in text.split(" ") if token]

    # 步骤 4：顺序扫描
    absorbed: list[str] = []
    index = 0
    while index < len(tokens) and len(absorbed) < MAX_SPECIES_TOKENS:
        token = tokens[index]
        key = _compare_key(token)
        if not key:
            index += 1
            continue
        if key in STOPWORDS:
            break
        if key in INFRASPECIFIC:
            absorbed.append(token)
            index += 1
            if index < len(tokens) and len(absorbed) < MAX_SPECIES_TOKENS:
                follower = tokens[index]
                follower_key = _compare_key(follower)
                if (follower_key
                        and follower_key not in STOPWORDS
                        and follower_key not in INFRASPECIFIC):
                    absorbed.append(follower)
                    index += 1
            break
        if token[0].isupper():
            absorbed.append(token)
            index += 1
            continue
        if len(absorbed) < 2 and token[0].isalpha():
            absorbed.append(token)
            index += 1
            continue
        break

    # 步骤 5：判据
    if not absorbed:
        return "", ("无法从 header 提取物种名",)
    return " ".join(absorbed), tuple(warnings)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_naming.py -v`
预期：PASS（24 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/naming.py tests/test_naming.py
git commit -m "feat(naming): 增加物种名智能提取与停用词表"
```

---

### Task 5：命名渲染与流水号分配 `render_name` / `build_name_map`

**文件：**
- 修改：`seq_toolkit/naming.py`（追加函数）
- 修改：`tests/test_naming.py`（追加测试）

**接口：**
- 依赖输入：`SequenceRecord`（任务 2）、`sanitize_accession` / `sanitize_species`（任务 3）
- 对外产出：
  - `NAMING_MODES: tuple[str, ...]` = `("keep", "accession", "species", "accession_species")`
  - `species_key(record: SequenceRecord) -> str`
  - `render_name(record: SequenceRecord, mode: str, serial: int | None = None) -> str`
  - `build_name_map(records: Sequence[SequenceRecord], mode: str) -> dict[SequenceRecord, str]`
  - 未知 `mode` 抛 `ValueError`

> **`build_name_map` 以记录本身为键**（`SequenceRecord` 是 frozen 且可哈希），而不是列表下标。下标方案在"读取后经过去重过滤再写出"的流程里极易错位。

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_naming.py` 末尾追加：

```python
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


def test_build_name_map_duplicate_species_gets_serials_in_appearance_order():
    records = [_rec(accession="ON1.1", species="Salsola_pellucida"),
               _rec(accession="MF1.1", species="Kochia_scoparia"),
               _rec(accession="ON2.1", species="Salsola_pellucida")]
    mapping = build_name_map(records, "accession_species")
    assert mapping[records[0]] == "ON1.1_Salsola_pellucida_1"
    assert mapping[records[1]] == "MF1.1_Kochia_scoparia"
    assert mapping[records[2]] == "ON2.1_Salsola_pellucida_2"


def test_build_name_map_species_mode_protects_against_duplicate_names():
    records = [_rec(accession="ON1.1", species="Salsola_pellucida"),
               _rec(accession="ON2.1", species="Salsola_pellucida")]
    mapping = build_name_map(records, "species")
    assert mapping[records[0]] == "Salsola_pellucida_1"
    assert mapping[records[1]] == "Salsola_pellucida_2"


def test_build_name_map_is_deterministic():
    records = [_rec(accession="ON1.1", species="Salsola_pellucida"),
               _rec(accession="ON2.1", species="Salsola_pellucida")]
    assert build_name_map(records, "species") == build_name_map(records, "species")
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_naming.py -v`
预期：FAIL，`ImportError: cannot import name 'NAMING_MODES'`

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/naming.py` 顶部把 model 的导入补上：

```python
from typing import Sequence

from .model import SequenceRecord
```

在文件末尾追加：

```python
NAMING_MODES = ("keep", "accession", "species", "accession_species")


def species_key(record: SequenceRecord) -> str:
    """物种名分组键：用于统计同物种的序列条数。物种名缺失时回退为登录号基号。"""
    key = sanitize_species(record.species)
    if key:
        return key
    return sanitize_accession(record.accession_base) or "unknown"


def render_name(record: SequenceRecord, mode: str,
                serial: int | None = None) -> str:
    """按命名模式渲染序列名；serial 非 None 时追加流水号后缀。"""
    if mode not in NAMING_MODES:
        raise ValueError(f"未知命名模式: {mode}")
    if mode == "keep":
        return record.accession

    accession = sanitize_accession(record.accession)
    species = sanitize_species(record.species)

    if mode == "accession":
        name = accession or species
    elif mode == "species":
        name = species or accession
    else:  # accession_species
        name = "_".join(part for part in (accession, species) if part)

    # 基名为空时不追加流水号：否则名字会变成 "_1"→"1" 这种真值，
    # 使 build_name_map 的 `name or f"sequence_{index}"` 兜底永不生效，
    # 产出 "1"/"2" 这类可能与真实名撞车的裸数字名。
    if serial is not None and name:
        name = f"{name}_{serial}"
    return _UNDERSCORES.sub("_", name).strip("_")


def build_name_map(records: Sequence[SequenceRecord],
                   mode: str) -> dict[SequenceRecord, str]:
    """两遍处理：先统计同物种条数，再按出现顺序分配流水号。"""
    # 模式校验必须在 keep 短路之前：否则空批次下非法模式会被静默当成 keep，
    # 与 render_name 的「未知 mode 抛 ValueError」契约不一致。
    if mode not in NAMING_MODES:
        raise ValueError(f"未知命名模式: {mode}")
    if mode == "keep":
        return {}

    counts: dict[str, int] = {}
    for record in records:
        key = species_key(record)
        counts[key] = counts.get(key, 0) + 1

    seen: dict[str, int] = {}
    mapping: dict[SequenceRecord, str] = {}
    for index, record in enumerate(records, start=1):
        key = species_key(record)
        serial = None
        if counts[key] > 1:
            seen[key] = seen.get(key, 0) + 1
            serial = seen[key]
        name = render_name(record, mode, serial)
        mapping[record] = name or f"sequence_{index}"
    return mapping
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_naming.py -v`
预期：PASS（41 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/naming.py tests/test_naming.py
git commit -m "feat(naming): 增加命名模式渲染与同物种流水号分配"
```

---

### Task 6：统一文本打开 `textio.py`

**文件：**
- 新建：`seq_toolkit/textio.py`
- 测试：`tests/test_textio.py`

**接口：**
- 依赖输入：无
- 对外产出：`open_text(path: str) -> TextIO` —— 上下文管理器，自动处理 `.gz`、UTF-8 BOM、CRLF/LF/CR 三种换行

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_textio.py`：

```python
import gzip

from seq_toolkit.textio import open_text


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
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_textio.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit.textio'`

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/textio.py`：

```python
"""统一的文本打开入口：显式 UTF-8、兼容 BOM、透明解压 .gz、统一换行。"""

from __future__ import annotations

import gzip
from typing import IO


def open_text(path: str) -> IO[str]:
    """按 UTF-8 打开文本文件，供 fasta_io 与 genbank_io 共用。

    - encoding="utf-8-sig"：自动吃掉 BOM，普通 UTF-8 文件不受影响
    - newline=None：把 CRLF / CR / LF 统一翻译为 "\\n"
    - .gz 后缀透明解压
    """
    if str(path).lower().endswith(".gz"):
        return gzip.open(str(path), "rt", encoding="utf-8-sig",
                         errors="replace", newline=None)
    return open(str(path), "rt", encoding="utf-8-sig",
                errors="replace", newline=None)


REPLACEMENT_CHAR = "\ufffd"


def has_decoding_damage(text: str) -> bool:
    """文本中是否出现 U+FFFD 替换字符。

    errors="replace" 让非 UTF-8 文件（例如中文 Windows 上常见的 GBK/cp936）被静默
    解码成一堆 U+FFFD。本函数让调用方能把"文件编码不对"与"序列里有脏字符"区分开，
    给出可操作的提示，而不是让用户去查序列。
    """
    return REPLACEMENT_CHAR in text
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_textio.py -v`
预期：PASS（5 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/textio.py tests/test_textio.py
git commit -m "feat(textio): 增加统一的 UTF-8/gz 文本打开入口"
```

---

### Task 7：FASTA 读取 `read_fasta`

**文件：**
- 新建：`seq_toolkit/fasta_io.py`
- 测试：`tests/test_fasta_io.py`

**接口：**
- 依赖输入：`SequenceRecord` / `parse_accession`（任务 2）、`extract_species_from_header` / `sanitize_species`（任务 3、4）、`open_text`（任务 6）
- 对外产出：
  - `IUPAC_CHARS: frozenset[str]`
  - `FastaParseError(SeqToolkitError)`
  - `read_fasta(path: str) -> Iterator[SequenceRecord]` —— 生成器；文件中不含任何 `>` 记录时抛 `FastaParseError`

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_fasta_io.py`：

```python
import gzip

import pytest

from seq_toolkit.fasta_io import FastaParseError, read_fasta


def _write(tmp_path, name, text, encoding="utf-8"):
    target = tmp_path / name
    target.write_text(text, encoding=encoding)
    return str(target)


def test_read_single_record(tmp_path):
    path = _write(tmp_path, "a.fa", ">ON929859.1 Salsola pellucida chloroplast, complete genome\nACGTACGT\n")
    records = list(read_fasta(path))
    assert len(records) == 1
    record = records[0]
    assert record.accession == "ON929859.1"
    assert record.accession_base == "ON929859"
    assert record.version == 1
    assert record.species == "Salsola_pellucida"
    assert record.species_raw == "Salsola pellucida"
    assert record.seq == "ACGTACGT"
    assert record.source_format == "fasta"
    assert record.origin_line == 1
    assert record.warnings == ()


def test_read_multiline_sequence_is_concatenated(tmp_path):
    path = _write(tmp_path, "multi.fa", ">ON1.1 Salsola pellucida\nACGT\nACGT\nAC\n")
    record = list(read_fasta(path))[0]
    assert record.seq == "ACGTACGTAC"


def test_read_multiple_records_tracks_line_numbers(tmp_path):
    path = _write(tmp_path, "two.fa",
                  ">ON1.1 Salsola pellucida\nACGT\n>MF2.1 Kochia scoparia\nTTTT\n")
    records = list(read_fasta(path))
    assert [r.accession for r in records] == ["ON1.1", "MF2.1"]
    assert records[0].origin_line == 1
    assert records[1].origin_line == 3


def test_read_lowercase_sequence_is_uppercased(tmp_path):
    path = _write(tmp_path, "lower.fa", ">ON1.1 Salsola pellucida\nacgt\n")
    assert list(read_fasta(path))[0].seq == "ACGT"


def test_read_handles_crlf(tmp_path):
    path = _write(tmp_path, "crlf.fa", ">ON1.1 Salsola pellucida\r\nACGT\r\n")
    assert list(read_fasta(path))[0].seq == "ACGT"


def test_read_handles_bom(tmp_path):
    target = tmp_path / "bom.fa"
    target.write_bytes(b"\xef\xbb\xbf>ON1.1 Salsola pellucida\nACGT\n")
    assert list(read_fasta(str(target)))[0].accession == "ON1.1"


def test_read_transparently_handles_gzip(tmp_path):
    target = tmp_path / "gz.fa.gz"
    with gzip.open(str(target), "wt", encoding="utf-8") as handle:
        handle.write(">ON1.1 Salsola pellucida\nACGT\n")
    assert list(read_fasta(str(target)))[0].seq == "ACGT"


def test_read_flags_ill_formed_accession(tmp_path):
    path = _write(tmp_path, "weird.fa", ">scaffold_12.3 Salsola pellucida\nACGT\n")
    record = list(read_fasta(path))[0]
    assert record.accession == "SCAFFOLD_12.3"
    assert any("可疑" in w for w in record.warnings)


def test_read_flags_unparsable_species(tmp_path):
    path = _write(tmp_path, "nospecies.fa", ">ON1.1 chloroplast, complete genome\nACGT\n")
    record = list(read_fasta(path))[0]
    assert record.species == ""
    assert any("物种名" in w for w in record.warnings)


def test_read_flags_non_iupac_characters(tmp_path):
    path = _write(tmp_path, "bad.fa", ">ON1.1 Salsola pellucida\nACGT*NN\n")
    record = list(read_fasta(path))[0]
    assert record.seq == "ACGT*NN"
    assert any("IUPAC" in w for w in record.warnings)


def test_read_raises_on_empty_file(tmp_path):
    path = _write(tmp_path, "empty.fa", "")
    with pytest.raises(FastaParseError):
        list(read_fasta(path))


def test_read_raises_when_no_header_present(tmp_path):
    path = _write(tmp_path, "nohdr.fa", "ACGTACGT\n")
    with pytest.raises(FastaParseError):
        list(read_fasta(path))


def test_read_works_with_chinese_path(tmp_path):
    folder = tmp_path / "中文目录"
    folder.mkdir()
    target = folder / "样本.fa"
    target.write_text(">ON1.1 Salsola pellucida\nACGT\n", encoding="utf-8")
    assert list(read_fasta(str(target)))[0].species == "Salsola_pellucida"
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_fasta_io.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit.fasta_io'`

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/fasta_io.py`：

```python
"""FASTA 读取：支持多行序列、CRLF、BOM、.gz，以及多种后缀名。"""

from __future__ import annotations

import re
from typing import Iterator

from .model import SequenceRecord, SeqToolkitError, parse_accession
from .naming import extract_species_from_header, sanitize_species
from .textio import has_decoding_damage, open_text

IUPAC_CHARS = frozenset("ACGTURYSWKMBDHVN")
_WHITESPACE = re.compile(r"\s+")


class FastaParseError(SeqToolkitError):
    """FASTA 文件无法解析（空文件、缺少记录头等）。"""


def _build_record(path: str, header: str, chunks: list[str],
                  start_line: int) -> SequenceRecord:
    warnings: list[str] = []
    body = header.strip()
    parts = body.split(None, 1)
    token = parts[0] if parts else ""
    remainder = parts[1] if len(parts) > 1 else ""

    accession = parse_accession(token)
    if not accession.well_formed:
        warnings.append(f"accession 格式可疑: {token!r}")

    species_raw, species_warnings = extract_species_from_header(remainder)
    warnings.extend(species_warnings)
    species = sanitize_species(species_raw)
    if not species:
        warnings.append("无法从 header 提取物种名，该记录将不改名")

    sequence = _WHITESPACE.sub("", "".join(chunks)).upper()
    unexpected = sorted(set(sequence) - IUPAC_CHARS)
    if unexpected:
        warnings.append("序列含非 IUPAC 字符: " + "".join(unexpected))

    # 编码损伤必须单独告警：否则 GBK 等非 UTF-8 输入会被报成"序列含非 IUPAC 字符"
    # （用户会去查序列而不是查编码），若乱码只落在定义行尾部则完全无声。
    if has_decoding_damage(header) or has_decoding_damage(sequence):
        warnings.append(
            "文件可能不是 UTF-8 编码（出现替换字符 U+FFFD），请转码为 UTF-8 后重试"
        )

    return SequenceRecord(
        accession=accession.accession or token,
        accession_base=accession.base or token,
        version=accession.version,
        species=species,
        species_raw=species_raw,
        lineage="",
        definition=remainder,
        seq=sequence,
        source_format="fasta",
        origin_path=str(path),
        origin_line=start_line,
        date="",
        raw_block="",
        warnings=tuple(warnings),
    )


def read_fasta(path: str) -> Iterator[SequenceRecord]:
    """逐条产出 FASTA 记录。文件中不含任何 '>' 行时抛 FastaParseError。"""
    header: str | None = None
    chunks: list[str] = []
    start_line = 0
    produced = 0

    with open_text(path) as handle:
        for lineno, raw in enumerate(handle, start=1):
            line = raw.rstrip("\n")
            if line.startswith(">"):
                if header is not None:
                    yield _build_record(path, header, chunks, start_line)
                    produced += 1
                header = line[1:]
                chunks = []
                start_line = lineno
            elif header is not None:
                chunks.append(line)

    if header is not None:
        yield _build_record(path, header, chunks, start_line)
        produced += 1

    if produced == 0:
        raise FastaParseError(f"{path}: 未找到任何 FASTA 记录（缺少 '>' 记录头）")
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_fasta_io.py -v`
预期：PASS（14 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/fasta_io.py tests/test_fasta_io.py
git commit -m "feat(fasta_io): 增加 FASTA 解析器"
```

---

### Task 8：FASTA 写出 `write_fasta`

**文件：**
- 修改：`seq_toolkit/fasta_io.py`（追加函数）
- 修改：`tests/test_fasta_io.py`（追加测试）

**接口：**
- 依赖输入：`read_fasta`（任务 7）、`build_name_map` / `render_name`（任务 5）
- 对外产出：
  - `write_fasta(records: Iterable[SequenceRecord], out_path: str, name_map: Mapping[SequenceRecord, str] | None = None, wrap: int = 0) -> None`
  - `wrap=0` 表示不换行（整条序列一行）；`wrap=60/70/80` 表示每行固定列数

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_fasta_io.py` 末尾追加：

```python
from seq_toolkit.naming import build_name_map
from seq_toolkit.fasta_io import write_fasta


def test_write_fasta_without_name_map_uses_accession(tmp_path):
    source = _write(tmp_path, "in.fa", ">ON1.1 Salsola pellucida\nACGT\n")
    records = list(read_fasta(source))
    out = tmp_path / "out.fa"
    write_fasta(records, str(out))
    assert out.read_text(encoding="utf-8") == ">ON1.1\nACGT\n"


def test_write_fasta_applies_name_map(tmp_path):
    source = _write(tmp_path, "in.fa", ">ON1.1 Salsola pellucida\nACGT\n")
    records = list(read_fasta(source))
    mapping = build_name_map(records, "accession_species")
    out = tmp_path / "out.fa"
    write_fasta(records, str(out), mapping)
    assert out.read_text(encoding="utf-8") == ">ON1.1_Salsola_pellucida\nACGT\n"


def test_write_fasta_wraps_when_requested(tmp_path):
    source = _write(tmp_path, "in.fa", ">ON1.1 Salsola pellucida\nACGTACGT\n")
    records = list(read_fasta(source))
    out = tmp_path / "out.fa"
    write_fasta(records, str(out), wrap=3)
    assert out.read_text(encoding="utf-8") == ">ON1.1\nACG\nTAC\nGT\n"


def test_write_then_read_round_trip_preserves_sequence(tmp_path):
    source = _write(tmp_path, "in.fa", ">ON1.1 Salsola pellucida\nACGTACGTAC\n")
    records = list(read_fasta(source))
    out = tmp_path / "out.fa"
    write_fasta(records, str(out), build_name_map(records, "species"))
    back = list(read_fasta(str(out)))
    assert back[0].seq == "ACGTACGTAC"
    assert back[0].accession == "ON1.1"


def test_write_fasta_uses_lf_line_endings(tmp_path):
    source = _write(tmp_path, "in.fa", ">ON1.1 Salsola pellucida\nACGT\n")
    out = tmp_path / "out.fa"
    write_fasta(list(read_fasta(source)), str(out))
    assert b"\r\n" not in out.read_bytes()
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_fasta_io.py -v`
预期：FAIL，`ImportError: cannot import name 'write_fasta'`

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/fasta_io.py` 的 import 区块把需要的类型补上：

```python
from typing import Iterable, Iterator, Mapping
```

在文件末尾追加：

```python
def write_fasta(records: Iterable[SequenceRecord], out_path: str,
                name_map: Mapping[SequenceRecord, str] | None = None,
                wrap: int = 0) -> None:
    """把记录写成 FASTA。name_map 为 None 时使用登录号作为序列名。

    wrap=0 表示整条序列写在一行；wrap=N 表示每行 N 个碱基。
    输出固定使用 UTF-8 与 LF 换行，保证跨平台一致。
    """
    mapping = name_map or {}
    with open(str(out_path), "wt", encoding="utf-8", newline="\n") as handle:
        for index, record in enumerate(records, start=1):
            name = mapping.get(record) or record.accession or f"sequence_{index}"
            handle.write(f">{name}\n")
            sequence = record.seq
            if wrap and wrap > 0:
                for start in range(0, len(sequence), wrap):
                    handle.write(sequence[start:start + wrap] + "\n")
            else:
                handle.write(sequence + "\n")
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_fasta_io.py -v`
预期：PASS（19 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/fasta_io.py tests/test_fasta_io.py
git commit -m "feat(fasta_io): 增加 FASTA 写出与换行控制"
```

---

### Task 9：GenBank 读取 `read_genbank`

**文件：**
- 新建：`seq_toolkit/genbank_io.py`
- 新建：`tests/fixtures/multi_record.gb`
- 新建：`tests/fixtures/contig_record.gb`
- 测试：`tests/test_genbank_io.py`

**接口：**
- 依赖输入：`SequenceRecord` / `parse_accession`（任务 2）、`extract_species_from_header` / `sanitize_species`（任务 3、4）、`open_text`（任务 6）
- 对外产出：
  - `GenBankParseError(SeqToolkitError)`
  - `ContigRecordError(GenBankParseError)` —— 属性 `line: int`，`str(exc)` 为给用户看的原因
  - `is_top_level_field(line: str, keyword: str) -> bool` —— 容错判定字段行（`ORGANISM` / `SOURCE` 在 GenBank 中缩进 2 空格，**不能**用 `startswith` 直接判断）
  - `read_genbank(path: str, on_skip: Callable[[str, int, str], None] | None = None) -> Iterator[SequenceRecord]`

> **关键格式事实：** GenBank 平文件中 `LOCUS`/`DEFINITION`/`ACCESSION`/`VERSION`/`KEYWORDS`/`SOURCE`/`FEATURES`/`ORIGIN`/`CONTIG` 顶格，但 **`ORGANISM` 缩进 2 空格**，其后的分类谱系缩进 12 空格。因此字段判定必须用"左剥离后以关键字开头且其后为空白"的规则。
>
> `raw_block` 必须逐行保存原始文本（含 `FEATURES` 段与结尾 `//`），否则合并 GenBank 时会摧毁 CDS/rRNA/tRNA 注释。

- [ ] **步骤 1：编写测试夹具**

新建 `tests/fixtures/multi_record.gb`（注意 `ORGANISM` 前有两个空格，谱系行有 12 个空格，`bp` 前的长度列宽不影响解析）：

```
LOCUS       ON929859                60 bp    DNA     circular PLN 12-JAN-2022
DEFINITION  Salsola pellucida chloroplast, complete genome.
ACCESSION   ON929859
VERSION     ON929859.1
KEYWORDS    .
SOURCE      Salsola pellucida
  ORGANISM  Salsola pellucida
            Eukaryota; Viridiplantae; Streptophyta; Caryophyllales;
            Amaranthaceae; Salsola.
FEATURES             Location/Qualifiers
     source          1..60
                     /organism="Salsola pellucida"
                     /db_xref="taxon:151232"
     CDS             1..30
                     /gene="matK"
                     /product="maturase K"
ORIGIN
        1 atgactgact gactgactga ctgactgact gactgactga ctgactgact gactgactga
//
LOCUS       MF123456                24 bp    DNA     linear   PLN 03-MAR-2019
DEFINITION  Kochia scoparia isolate 5 chloroplast, partial
            sequence.
ACCESSION   MF123456
VERSION     MF123456.1
  ORGANISM  Kochia scoparia
            Eukaryota; Viridiplantae; Amaranthaceae; Kochia.
ORIGIN
        1 ttgaccggtt gaccggttga ccgg
//
```

新建 `tests/fixtures/contig_record.gb`：

```
LOCUS       NZ_CM000001             5000 bp    DNA     linear   CON 07-JUL-2015
DEFINITION  Salsola pellucida scaffold1, whole genome shotgun sequence.
ACCESSION   NZ_CM000001
VERSION     NZ_CM000001.1
  ORGANISM  Salsola pellucida
            Eukaryota; Viridiplantae; Amaranthaceae; Salsola.
CONTIG      join(AAAB01000001.1:1..2500,AAAB01000002.1:1..2500)
//
```

- [ ] **步骤 2：编写失败的测试**

新建 `tests/test_genbank_io.py`：

```python
from pathlib import Path

import pytest

from seq_toolkit.genbank_io import (
    ContigRecordError,
    GenBankParseError,
    is_top_level_field,
    read_genbank,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_is_top_level_field_tolerates_organism_indentation():
    assert is_top_level_field("  ORGANISM  Salsola pellucida", "ORGANISM") is True


def test_is_top_level_field_tolerates_locus_indentation():
    assert is_top_level_field("LOCUS       ON929859", "LOCUS") is True


def test_is_top_level_field_rejects_qualifier():
    assert is_top_level_field('                     /organism="x"', "ORGANISM") is False


def test_is_top_level_field_rejects_lineage_line():
    assert is_top_level_field("            Eukaryota; Viridiplantae;", "ORGANISM") is False


def test_read_multiple_records_from_one_file():
    records = list(read_genbank(str(FIXTURES / "multi_record.gb")))
    assert [r.accession for r in records] == ["ON929859.1", "MF123456.1"]


def test_version_line_wins_over_accession():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[0]
    assert record.accession == "ON929859.1"
    assert record.accession_base == "ON929859"
    assert record.version == 1


def test_organism_section_is_authoritative_species_source():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[0]
    assert record.species_raw == "Salsola pellucida"
    assert record.species == "Salsola_pellucida"


def test_lineage_is_captured():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[0]
    assert "Amaranthaceae" in record.lineage


def test_definition_multi_line_continuation_is_joined():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[1]
    assert record.definition == "Kochia scoparia isolate 5 chloroplast, partial sequence."


def test_sequence_is_extracted_without_line_numbers_or_spaces():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[0]
    assert record.length == 60
    assert record.seq.startswith("ATGACTGACT")
    assert record.seq.isalpha()
    assert record.seq == record.seq.upper()


def test_date_is_read_from_locus_line():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[0]
    assert record.date == "12-JAN-2022"


def test_raw_block_preserves_features_section_verbatim():
    raw = list(read_genbank(str(FIXTURES / "multi_record.gb")))[0].raw_block
    assert '/gene="matK"' in raw
    assert '/product="maturase K"' in raw
    assert raw.startswith("LOCUS       ON929859")
    assert raw.rstrip("\n").endswith("//")


def test_origin_line_is_recorded():
    records = list(read_genbank(str(FIXTURES / "multi_record.gb")))
    assert records[0].origin_line == 1
    assert records[1].origin_line == 20


def test_second_record_sequence():
    record = list(read_genbank(str(FIXTURES / "multi_record.gb")))[1]
    assert record.seq == "TTGACCGGTTGACCGGTTGACCGG"
    assert record.length == 24


def test_contig_record_reports_reason_through_callback():
    skipped: list[tuple[str, int, str]] = []
    records = list(
        read_genbank(
            str(FIXTURES / "contig_record.gb"),
            on_skip=lambda path, line, reason: skipped.append((path, line, reason)),
        )
    )
    assert records == []
    assert len(skipped) == 1
    path, line, reason = skipped[0]
    assert path.endswith("contig_record.gb")
    assert line == 1
    assert "CONTIG" in reason


def test_read_raises_on_file_without_locus(tmp_path):
    target = tmp_path / "junk.gb"
    target.write_text("not a genbank file\n", encoding="utf-8")
    with pytest.raises(GenBankParseError):
        list(read_genbank(str(target)))


def test_read_works_with_gzip(tmp_path):
    import gzip
    source = (FIXTURES / "multi_record.gb").read_bytes()
    target = tmp_path / "sample.gb.gz"
    with gzip.open(str(target), "wb") as handle:
        handle.write(source)
    assert len(list(read_genbank(str(target)))) == 2
```

- [ ] **步骤 3：运行测试并确认其失败**

运行：`python -m pytest tests/test_genbank_io.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit.genbank_io'`

- [ ] **步骤 4：编写最小实现**

新建 `seq_toolkit/genbank_io.py`：

```python
"""GenBank 读取：多记录文件、字段回退链、CONTIG 记录识别、原始块保真。"""

from __future__ import annotations

import re
from typing import Callable, Iterator

from .model import SequenceRecord, SeqToolkitError, parse_accession
from .naming import extract_species_from_header, sanitize_species
from .textio import open_text

_LOCUS_DATE = re.compile(r"\b\d{1,2}-[A-Z]{3}-\d{4}\b")
_ORGANISM_QUALIFIER = re.compile(r'/organism="([^"]+)"')
_ORIGIN_DIGITS = re.compile(r"[\s0-9]")

# 顶格字段（ORGANISM / SOURCE 实际缩进 2 空格，因此统一左剥离后判定）
_FIELD_KEYWORDS = (
    "LOCUS", "DEFINITION", "ACCESSION", "VERSION", "KEYWORDS", "SOURCE",
    "ORGANISM", "REFERENCE", "AUTHORS", "TITLE", "JOURNAL", "PUBMED",
    "COMMENT", "FEATURES", "ORIGIN", "CONTIG", "BASE", "PRIMARY",
)


class GenBankParseError(SeqToolkitError):
    """GenBank 记录无法解析。"""


class ContigRecordError(GenBankParseError):
    """记录只有 CONTIG（未组装），没有 ORIGIN 段，无法产出序列。"""

    def __init__(self, line: int, reason: str) -> None:
        super().__init__(reason)
        self.line = line


def is_top_level_field(line: str, keyword: str) -> bool:
    """判断某行是否为指定字段行。

    容忍前导缩进（ORGANISM / SOURCE 缩进 2 空格），并要求关键字之后是空白或行尾，
    因此 '/organism="x"' 与谱系行都不会被误判。
    """
    stripped = line.lstrip()
    if not stripped.startswith(keyword):
        return False
    rest = stripped[len(keyword):]
    return rest == "" or rest[0].isspace()


def _iter_blocks(path: str) -> Iterator[tuple[int, list[str]]]:
    """按 '//' 切分记录块，并跳过块之间的空行（保证 raw_block 从 LOCUS 开始）。"""
    block: list[str] = []
    start = 0
    with open_text(path) as handle:
        for lineno, raw in enumerate(handle, start=1):
            line = raw.rstrip("\n")
            if not block:
                if not line.strip():
                    continue
                start = lineno
            block.append(line)
            if line.strip() == "//":
                yield start, block
                block = []
    if any(line.startswith("LOCUS") for line in block):
        yield start, block


def _collect_field(lines: list[str], index: int, keyword: str) -> str:
    """收集一个可跨行的字段值（续行为缩进行，遇到顶格字段停止）。"""
    first = lines[index].strip()[len(keyword):].strip()
    parts = [first] if first else []
    cursor = index + 1
    while cursor < len(lines):
        current = lines[cursor]
        if not current.strip():
            break
        if not current[:1].isspace():
            break
        parts.append(current.strip())
        cursor += 1
    return " ".join(parts)


def _parse_block(path: str, start_line: int, lines: list[str]) -> SequenceRecord:
    warnings: list[str] = []

    if not any(line.startswith("LOCUS") for line in lines):
        raise GenBankParseError("记录缺少 LOCUS 行")

    locus_name = ""
    date = ""
    for line in lines:
        if line.startswith("LOCUS"):
            tokens = line.split()
            if len(tokens) > 1:
                locus_name = tokens[1]
            match = _LOCUS_DATE.search(line)
            if match:
                date = match.group(0)
            break

    accession_raw = ""
    for line in lines:
        if line.startswith("VERSION"):
            tokens = line.split()
            if len(tokens) > 1:
                accession_raw = tokens[1]
            break
    if not accession_raw:
        for line in lines:
            if line.startswith("ACCESSION"):
                tokens = line.split()
                if len(tokens) > 1:
                    accession_raw = tokens[1]
                break
        if accession_raw:
            warnings.append("缺少 VERSION 行，已回退使用 ACCESSION")
    accession = parse_accession(accession_raw or locus_name)
    if not accession.well_formed:
        warnings.append(f"accession 格式可疑: {accession_raw or locus_name!r}")

    definition = ""
    for index, line in enumerate(lines):
        if line.startswith("DEFINITION"):
            definition = _collect_field(lines, index, "DEFINITION")
            break

    species_raw = ""
    lineage = ""
    for index, line in enumerate(lines):
        if is_top_level_field(line, "ORGANISM"):
            species_raw = line.strip()[len("ORGANISM"):].strip()
            lineage_parts: list[str] = []
            cursor = index + 1
            while cursor < len(lines):
                current = lines[cursor]
                if not current.strip() or not current[:1].isspace():
                    break
                lineage_parts.append(current.strip())
                cursor += 1
            lineage = " ".join(lineage_parts)
            break

    if not species_raw:
        match = _ORGANISM_QUALIFIER.search("\n".join(lines))
        if match:
            species_raw = match.group(1).strip()
            warnings.append("ORGANISM 段缺失，已回退使用 source feature 的 /organism 限定符")

    if not species_raw:
        extracted, extract_warnings = extract_species_from_header(definition)
        if extracted:
            species_raw = extracted
            warnings.extend(extract_warnings)
            warnings.append("ORGANISM 与 /organism 均缺失，已从 DEFINITION 提取物种名")

    if not species_raw:
        species_raw = locus_name
        if locus_name:
            warnings.append("无物种信息，已回退为 LOCUS 名")

    species = sanitize_species(species_raw)
    if not species:
        warnings.append("无法从 GenBank 记录取得物种名，该记录将不改名")

    origin_index = next(
        (i for i, line in enumerate(lines) if line.startswith("ORIGIN")), -1
    )
    if origin_index < 0:
        if any(line.startswith("CONTIG") for line in lines):
            raise ContigRecordError(start_line, "序列未组装（CONTIG 记录），无 ORIGIN 段")
        raise GenBankParseError("记录缺少 ORIGIN 段")

    sequence_parts: list[str] = []
    for line in lines[origin_index + 1:]:
        if line.strip() == "//":
            break
        sequence_parts.append(_ORIGIN_DIGITS.sub("", line))
    sequence = "".join(sequence_parts).upper()
    if not sequence:
        raise GenBankParseError("ORIGIN 段为空")

    raw_block = "".join(line + "\n" for line in lines)

    # 截断检测：GenBank 记录必须以独占一行的 '//' 结束。缺了它说明文件被截断
    # （下载中断、磁盘写满等），此时仍能解析出「登录号正确但序列被截断」的记录——
    # 零信号地污染下游数据集，比直接报错危险得多。
    non_empty = [line for line in lines if line.strip()]
    if not non_empty or non_empty[-1].strip() != "//":
        warnings.append("文件可能被截断（记录未以 // 结束），序列可能不完整")

    return SequenceRecord(
        accession=accession.accession or locus_name,
        accession_base=accession.base or locus_name,
        version=accession.version,
        species=species,
        species_raw=species_raw,
        lineage=lineage,
        definition=definition,
        seq=sequence,
        source_format="genbank",
        origin_path=str(path),
        origin_line=start_line,
        date=date,
        raw_block=raw_block,
        warnings=tuple(warnings),
    )


def read_genbank(
    path: str,
    on_skip: Callable[[str, int, str], None] | None = None,
) -> Iterator[SequenceRecord]:
    """逐条产出 GenBank 记录。

    无法产出序列的记录（CONTIG 型）通过 on_skip(path, line, reason) 上报后跳过，
    绝不静默丢弃；整块解析失败同样上报后继续处理后续记录。
    整个文件都没有 LOCUS 行时抛 GenBankParseError，由调用方按"格式不符"处理。
    """
    saw_locus = False
    for start_line, lines in _iter_blocks(path):
        if not any(line.startswith("LOCUS") for line in lines):
            if on_skip is not None:
                on_skip(str(path), start_line, "记录缺少 LOCUS 行")
            continue
        saw_locus = True
        try:
            yield _parse_block(path, start_line, lines)
        except ContigRecordError as error:
            if on_skip is not None:
                on_skip(str(path), error.line, str(error))
            continue
        except GenBankParseError as error:
            if on_skip is not None:
                on_skip(str(path), start_line, str(error))
            continue

    if not saw_locus:
        raise GenBankParseError(f"{path}: 未找到任何 GenBank 记录（缺少 LOCUS 行）")
```

- [ ] **步骤 5：运行测试并确认其通过**

运行：`python -m pytest tests/test_genbank_io.py -v`
预期：PASS（17 passed）

- [ ] **步骤 6：提交**

```bash
git add seq_toolkit/genbank_io.py tests/test_genbank_io.py tests/fixtures
git commit -m "feat(genbank_io): 增加 GenBank 解析器与原始块保真"
```

---

### Task 10：格式识别与输入展开 `format_detect.py`

**文件：**
- 新建：`seq_toolkit/format_detect.py`
- 测试：`tests/test_format_detect.py`

**接口：**
- 依赖输入：`open_text`（任务 6）
- 对外产出：
  - `DEFAULT_FASTA_SUFFIXES: tuple[str, ...]`、`DEFAULT_GENBANK_SUFFIXES: tuple[str, ...]`
  - `format_from_suffix(path: str) -> str` —— 返回 `"fasta"` / `"genbank"` / `""`
  - `sniff_format(path: str) -> str` —— 读首个非空行判定，无法判定返回 `""`
  - `detect_format(path: str, hint: str = "auto") -> str` —— **内容优先于后缀**；无法判定返回 `""`
  - `natural_key(text: str) -> list[tuple[int, object]]` —— 数字感知排序键
  - `list_input_files(paths, recursive=True, fasta_suffixes=..., genbank_suffixes=...) -> list[str]`

> 用户明确指定的**文件**一律纳入（不按后缀过滤），只有从**文件夹**展开时才按后缀过滤。这样"后缀起错了但内容对"的文件仍然能被处理。

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_format_detect.py`：

```python
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
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_format_detect.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit.format_detect'`

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/format_detect.py`：

```python
"""输入格式识别与输入文件展开。内容嗅探优先于后缀名。"""

from __future__ import annotations

import os
import re
from typing import Iterable, Sequence

from .textio import open_text

DEFAULT_FASTA_SUFFIXES = (".fasta", ".fa", ".fna", ".fas", ".ffn", ".frn", ".fsa", ".seq")
DEFAULT_GENBANK_SUFFIXES = (".gb", ".gbk", ".genbank", ".gbff", ".gp")

_NUMERIC_CHUNK = re.compile(r"(\d+)")
SNIFF_LINE_LIMIT = 50


def format_from_suffix(path: str) -> str:
    """按后缀名猜测格式；.gz 先剥离。无法判定返回空串。"""
    name = os.path.basename(str(path)).lower()
    if name.endswith(".gz"):
        name = name[:-3]
    if any(name.endswith(suffix) for suffix in DEFAULT_GENBANK_SUFFIXES):
        return "genbank"
    if any(name.endswith(suffix) for suffix in DEFAULT_FASTA_SUFFIXES):
        return "fasta"
    return ""


def sniff_format(path: str) -> str:
    """读取首个非空行判定格式：'LOCUS' 开头为 GenBank，'>' 开头为 FASTA。"""
    try:
        with open_text(path) as handle:
            for _ in range(SNIFF_LINE_LIMIT):
                line = handle.readline()
                if not line:
                    return ""
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("LOCUS"):
                    return "genbank"
                if stripped.startswith(">"):
                    return "fasta"
                return ""
    except (OSError, EOFError, zlib.error):
        # 三类异常都必须捕获，且都不是彼此的父类：
        #   BadGzipFile/OSError —— gzip 头损坏
        #   EOFError            —— 文件被截断（gzip 的 EOFError 不是 OSError 子类）
        #   zlib.error          —— deflate 数据体损坏（同样不是 OSError 子类）
        # 任其逃逸会一路穿过 detect_format（它在 run_merge 的 try 之外）中断整批合并。
        return ""
    return ""


def detect_format(path: str, hint: str = "auto") -> str:
    """判定文件格式。hint 为 'fasta'/'genbank' 时强制采用；'auto' 时内容优先于后缀。"""
    if hint in ("fasta", "genbank"):
        return hint
    if hint != "auto":
        raise ValueError(f"未知的输入格式提示: {hint}")
    by_suffix = format_from_suffix(path)
    by_content = sniff_format(path)
    if by_content and by_suffix and by_content != by_suffix:
        return by_content
    return by_content or by_suffix


def natural_key(text: str) -> list[tuple[int, object]]:
    """数字感知排序键：chr2 排在 chr10 之前。混合类型用元组包裹，避免比较时抛 TypeError。"""
    return [
        (0, int(chunk)) if chunk.isdecimal() else (1, chunk.lower())
        for chunk in _NUMERIC_CHUNK.split(str(text))
    ]


def _matches_suffix(name: str, suffixes: Sequence[str]) -> bool:
    lowered = name.lower()
    if lowered.endswith(".gz"):
        lowered = lowered[:-3]
    return any(lowered.endswith(suffix) for suffix in suffixes)


def list_input_files(
    paths: Iterable[str],
    recursive: bool = True,
    fasta_suffixes: Sequence[str] = DEFAULT_FASTA_SUFFIXES,
    genbank_suffixes: Sequence[str] = DEFAULT_GENBANK_SUFFIXES,
) -> list[str]:
    """展开输入：显式文件一律保留；文件夹里的文件按后缀过滤后自然排序。"""
    suffixes = tuple(fasta_suffixes) + tuple(genbank_suffixes)
    collected: list[str] = []
    for raw in paths:
        path = str(raw)
        if os.path.isdir(path):
            if recursive:
                for root, _dirs, files in os.walk(path):
                    for name in sorted(files, key=natural_key):
                        if _matches_suffix(name, suffixes):
                            collected.append(os.path.join(root, name))
            else:
                for name in sorted(os.listdir(path), key=natural_key):
                    full = os.path.join(path, name)
                    if os.path.isfile(full) and _matches_suffix(name, suffixes):
                        collected.append(full)
        elif os.path.isfile(path):
            collected.append(path)
    return collected
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_format_detect.py -v`
预期：PASS（12 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/format_detect.py tests/test_format_detect.py
git commit -m "feat(format_detect): 增加格式识别与输入展开"
```

---

### Task 11：日志与异常清单 `applog.py`

**文件：**
- 新建：`seq_toolkit/applog.py`
- 测试：`tests/test_applog.py`

**接口：**
- 依赖输入：无（不得依赖任何其他 seq_toolkit 模块）
- 对外产出：
  - `LogEntry` —— frozen dataclass：`level: str`、`message: str`
  - `ExceptionEntry` —— frozen dataclass：`path: str`、`line: int`、`header: str`、`reason: str`、`final_name: str = ""`
  - `RunLog` 类：`info/warn/error(message)`、`add_exception(path, line, header, reason, final_name="")`、属性 `entries` / `exceptions`（返回元组快照）、`exception_count()`、`clear()`、`export_text() -> str`、`export_log(path)`、`export_exceptions_csv(path)`
  - 线程安全（内部 `threading.Lock`），因为后台工作线程会写日志而主线程会读

> CSV 使用 `utf-8-sig` 编码，否则 Excel 打开中文列会乱码。

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_applog.py`：

```python
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
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_applog.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit.applog'`

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/applog.py`：

```python
"""运行日志与异常清单收集。线程安全：后台工作线程写、主线程读。"""

from __future__ import annotations

import csv
import threading
from dataclasses import dataclass

INFO = "INFO"
WARN = "WARN"
ERROR = "ERROR"

EXCEPTION_HEADERS = ("文件", "行号", "原始 header", "判定原因", "最终采用的名称")


@dataclass(frozen=True)
class LogEntry:
    level: str
    message: str


@dataclass(frozen=True)
class ExceptionEntry:
    path: str
    line: int
    header: str
    reason: str
    final_name: str = ""


class RunLog:
    """收集一次运行的日志与异常清单。所有变更加锁，读取返回快照元组。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[LogEntry] = []
        self._exceptions: list[ExceptionEntry] = []

    def _add(self, level: str, message: str) -> None:
        with self._lock:
            self._entries.append(LogEntry(level, message))

    def info(self, message: str) -> None:
        self._add(INFO, message)

    def warn(self, message: str) -> None:
        self._add(WARN, message)

    def error(self, message: str) -> None:
        self._add(ERROR, message)

    def add_exception(self, path: str, line: int, header: str, reason: str,
                      final_name: str = "") -> None:
        with self._lock:
            self._exceptions.append(ExceptionEntry(path, line, header, reason, final_name))

    @property
    def entries(self) -> tuple[LogEntry, ...]:
        with self._lock:
            return tuple(self._entries)

    @property
    def exceptions(self) -> tuple[ExceptionEntry, ...]:
        with self._lock:
            return tuple(self._exceptions)

    def exception_count(self) -> int:
        with self._lock:
            return len(self._exceptions)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._exceptions.clear()

    def export_text(self) -> str:
        return "\n".join(f"[{entry.level}] {entry.message}" for entry in self.entries)

    def export_log(self, out_path: str) -> None:
        with open(str(out_path), "wt", encoding="utf-8", newline="\n") as handle:
            handle.write(self.export_text())
            handle.write("\n")

    def export_exceptions_csv(self, out_path: str) -> None:
        with open(str(out_path), "wt", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(EXCEPTION_HEADERS)
            for entry in self.exceptions:
                writer.writerow([entry.path, entry.line, entry.header,
                                 entry.reason, entry.final_name])
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_applog.py -v`
预期：PASS（8 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/applog.py tests/test_applog.py
git commit -m "feat(applog): 增加线程安全的运行日志与异常清单"
```

---

### Task 12：合并编排 `pipeline.run_merge`

**文件：**
- 新建：`seq_toolkit/pipeline.py`
- 测试：`tests/test_pipeline.py`

**接口：**
- 依赖输入：任务 4-11 的全部模块
- 对外产出：
  - `OperationCancelled(SeqToolkitError)`
  - `ProcessPlan` —— dataclass：`inputs: list[str]`、`output_path: str`、`output_format: str = "fasta"`、`input_format: str = "auto"`、`naming_mode: str = "keep"`、`dedup: str = "accession"`、`recursive: bool = True`、`wrap: int = 0`、`log: RunLog | None = None`、`progress: Callable[[int, int, str], None] | None = None`、`cancel: threading.Event | None = None`
  - `ProcessResult` —— dataclass：`records_in: int`、`records_out: int`、`duplicates_removed: int`、`skipped_files: list[str]`、`output_path: str`、`exceptions: list[ExceptionEntry]`
  - `resolve_output_path(path: str) -> str` —— 目标已存在时递增追加 `_1`、`_2`
  - `run_merge(plan: ProcessPlan) -> ProcessResult`
  - 同时在 `genbank_io.py` 中产出 `format_genbank_record(record, name) -> str` 与 `write_genbank(records, out_path, name_map=None) -> None`
  - 模块常量 `BENIGN_WARNING_PREFIXES: tuple[str, ...]`

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_pipeline.py`：

```python
import threading
from pathlib import Path

import pytest

from seq_toolkit.applog import RunLog
from seq_toolkit.model import SeqToolkitError
from seq_toolkit.pipeline import (
    OperationCancelled,
    ProcessPlan,
    resolve_output_path,
    run_merge,
)

FASTA_A = ">ON1.1 Salsola pellucida chloroplast, complete genome\nACGTACGT\n"
FASTA_B = ">MF2.1 Kochia scoparia chloroplast, complete genome\nTTTTGGGG\n"
GENBANK_C = (
    "LOCUS       ON1.1                   8 bp    DNA     linear   PLN 01-JAN-2020\n"
    "DEFINITION  Salsola pellucida chloroplast, complete genome.\n"
    "ACCESSION   ON1\n"
    "VERSION     ON1.1\n"
    "  ORGANISM  Salsola pellucida\n"
    "            Eukaryota; Amaranthaceae; Salsola.\n"
    "FEATURES             Location/Qualifiers\n"
    "     CDS             1..8\n"
    '                     /gene="matK"\n'
    "ORIGIN\n"
    "        1 acgtacgt\n"
    "//\n"
)


def _write(tmp_path, name, text):
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return str(target)


def _plan(tmp_path, inputs, **overrides):
    options = dict(
        inputs=inputs,
        output_path=str(tmp_path / "out.fasta"),
        output_format="fasta",
        input_format="auto",
        naming_mode="keep",
        dedup="accession",
        recursive=True,
        wrap=0,
        log=RunLog(),
    )
    options.update(overrides)
    return ProcessPlan(**options)


def test_resolve_output_path_returns_input_when_free(tmp_path):
    target = tmp_path / "x.fasta"
    assert resolve_output_path(str(target)) == str(target)


def test_resolve_output_path_appends_index_when_taken(tmp_path):
    target = tmp_path / "x.fasta"
    target.write_text("taken", encoding="utf-8")
    resolved = resolve_output_path(str(target))
    assert Path(resolved).name == "x_1.fasta"


def test_resolve_output_path_keeps_incrementing(tmp_path):
    (tmp_path / "x.fasta").write_text("a", encoding="utf-8")
    (tmp_path / "x_1.fasta").write_text("b", encoding="utf-8")
    assert Path(resolve_output_path(str(tmp_path / "x.fasta"))).name == "x_2.fasta"


def test_merge_two_fasta_files(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    b = _write(tmp_path, "b.fasta", FASTA_B)
    result = run_merge(_plan(tmp_path, [a, b]))
    assert result.records_out == 2
    text = Path(result.output_path).read_text(encoding="utf-8")
    assert ">ON1.1" in text and ">MF2.1" in text


def test_merge_mixed_formats_into_fasta(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    c = _write(tmp_path, "c.gbk", GENBANK_C)
    plan = _plan(tmp_path, [a, c], dedup="none")
    result = run_merge(plan)
    assert result.records_out == 2


def test_deduplicate_by_accession(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    b = _write(tmp_path, "copy.fa", FASTA_A)
    result = run_merge(_plan(tmp_path, [a, b]))
    assert result.records_out == 1
    assert result.duplicates_removed == 1


def test_deduplication_keeps_distinct_versions(tmp_path):
    a = _write(tmp_path, "a.fa", ">ON1.1 Salsola pellucida\nACGT\n")
    b = _write(tmp_path, "b.fa", ">ON1.2 Salsola pellucida\nACGT\n")
    result = run_merge(_plan(tmp_path, [a, b]))
    assert result.records_out == 2
    assert result.duplicates_removed == 0


def test_dedup_none_keeps_duplicates(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    b = _write(tmp_path, "copy.fa", FASTA_A)
    result = run_merge(_plan(tmp_path, [a, b], dedup="none"))
    assert result.records_out == 2


def test_naming_mode_applied_to_output(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    result = run_merge(_plan(tmp_path, [a], naming_mode="accession_species"))
    assert Path(result.output_path).read_text(encoding="utf-8").startswith(
        ">ON1.1_Salsola_pellucida\n")


def test_unknown_format_file_is_skipped_and_logged(tmp_path):
    junk = _write(tmp_path, "junk.txt", "hello\n")
    a = _write(tmp_path, "a.fa", FASTA_A)
    log = RunLog()
    result = run_merge(_plan(tmp_path, [junk, a], log=log))
    assert result.records_out == 1
    assert junk in result.skipped_files
    assert any("无法识别" in e.message for e in log.entries)


def test_misleading_suffix_is_resolved_by_content(tmp_path):
    lying = _write(tmp_path, "lying.fa", GENBANK_C)
    log = RunLog()
    result = run_merge(_plan(tmp_path, [lying], log=log))
    assert result.records_out == 1
    assert any("后缀名与内容不符" in e.message for e in log.entries)


def test_existing_output_is_not_overwritten(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    target = tmp_path / "out.fasta"
    target.write_text("原有内容", encoding="utf-8")
    log = RunLog()
    result = run_merge(_plan(tmp_path, [a], log=log))
    assert target.read_text(encoding="utf-8") == "原有内容"
    assert Path(result.output_path).name == "out_1.fasta"
    assert any("已存在" in e.message for e in log.entries)


def test_cancellation_raises_operation_cancelled(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(OperationCancelled):
        run_merge(_plan(tmp_path, [a], cancel=cancel))


def test_empty_input_raises(tmp_path):
    with pytest.raises(SeqToolkitError):
        run_merge(_plan(tmp_path, []))


def test_progress_callback_is_invoked(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    seen: list[tuple[int, int, str]] = []
    run_merge(_plan(tmp_path, [a], progress=lambda d, t, m: seen.append((d, t, m))))
    assert seen and seen[-1][0] == seen[-1][1] == 1


def test_record_without_species_lands_in_exception_list_with_final_name(tmp_path):
    a = _write(tmp_path, "a.fa", ">ON1.1 chloroplast, complete genome\nACGT\n")
    log = RunLog()
    run_merge(_plan(tmp_path, [a], naming_mode="species", log=log))
    assert log.exception_count() >= 1
    entry = [e for e in log.exceptions if "物种名" in e.reason][0]
    assert entry.final_name == "ON1.1"


def test_benign_prefix_stripping_is_logged_as_info_not_exception(tmp_path):
    a = _write(tmp_path, "a.fa",
               ">ON1.1 UNVERIFIED: Salsola pellucida chloroplast, complete genome\nACGT\n")
    log = RunLog()
    run_merge(_plan(tmp_path, [a], log=log))
    assert log.exception_count() == 0
    assert any("伪装前缀" in e.message for e in log.entries)


def test_genbank_input_to_genbank_output_preserves_features(tmp_path):
    c = _write(tmp_path, "c.gbk", GENBANK_C)
    result = run_merge(_plan(tmp_path, [c], output_format="genbank"))
    text = Path(result.output_path).read_text(encoding="utf-8")
    assert '/gene="matK"' in text
    assert "FEATURES" in text


def test_fasta_input_to_genbank_output_is_synthesised_and_re_readable(tmp_path):
    from seq_toolkit.genbank_io import read_genbank
    a = _write(tmp_path, "a.fa", FASTA_A)
    result = run_merge(_plan(tmp_path, [a], output_format="genbank"))
    records = list(read_genbank(result.output_path))
    assert len(records) == 1
    assert records[0].seq == "ACGTACGT"
    assert records[0].species == "Salsola_pellucida"
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_pipeline.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit.pipeline'`

- [ ] **步骤 3：编写最小实现（本任务只实现 `run_merge`）**

新建 `seq_toolkit/pipeline.py`：

```python
"""编排层：把"读 → 去重 → 命名 → 写"串成完整流程。"""

from __future__ import annotations

import os
import threading
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .applog import ExceptionEntry, RunLog
from .fasta_io import FastaParseError, read_fasta, write_fasta
from .format_detect import (
    DEFAULT_FASTA_SUFFIXES,
    DEFAULT_GENBANK_SUFFIXES,
    detect_format,
    format_from_suffix,
    list_input_files,
)
from .genbank_io import GenBankParseError, read_genbank, write_genbank
from .model import SequenceRecord, SeqToolkitError
from .naming import NAMING_MODES, build_name_map

# 这些 warning 表示"已自动处理完毕"，只进日志，不进需要人工复核的异常清单
BENIGN_WARNING_PREFIXES = ("已剥离伪装前缀",)

# 后缀名常量只在 format_detect 中定义一份，这里从那里导入，避免两处定义漂移


class OperationCancelled(SeqToolkitError):
    """用户请求取消。"""


def _is_benign_warning(message: str) -> bool:
    return message.startswith(BENIGN_WARNING_PREFIXES)


def _raise_if_cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise OperationCancelled("操作已取消")


def resolve_output_path(path: str) -> str:
    """返回一个当前不存在的输出路径：已存在时递增追加 _1、_2 …"""
    candidate = Path(path)
    if not candidate.exists():
        return str(candidate)
    for index in range(1, 1000):
        alternative = candidate.with_name(f"{candidate.stem}_{index}{candidate.suffix}")
        if not alternative.exists():
            return str(alternative)
    raise SeqToolkitError(f"无法为目标文件找到可用名称: {path}")


@dataclass
class ProcessPlan:
    inputs: list[str]
    output_path: str
    output_format: str = "fasta"
    input_format: str = "auto"
    naming_mode: str = "keep"
    dedup: str = "accession"
    recursive: bool = True
    wrap: int = 0
    fasta_suffixes: tuple[str, ...] = DEFAULT_FASTA_SUFFIXES
    genbank_suffixes: tuple[str, ...] = DEFAULT_GENBANK_SUFFIXES
    log: RunLog | None = None
    progress: Callable[[int, int, str], None] | None = None
    cancel: threading.Event | None = None

    def __post_init__(self) -> None:
        """在构造时就校验枚举字段。

        否则：output_format 传错值不会报错，而是静默按 FASTA 写出（用户要 GenBank
        却拿到 FASTA 且无任何日志）；naming_mode 传错值要等整批读取跑完才抛
        ValueError，而 ValueError 不在调用方的 SeqToolkitError 捕获集内。
        """
        if self.output_format not in ("fasta", "genbank"):
            raise SeqToolkitError(f"未知输出格式: {self.output_format}")
        if self.input_format not in ("auto", "fasta", "genbank"):
            raise SeqToolkitError(f"未知输入格式: {self.input_format}")
        if self.naming_mode not in NAMING_MODES:
            raise SeqToolkitError(f"未知命名模式: {self.naming_mode}")
        if self.dedup not in ("accession", "none"):
            raise SeqToolkitError(f"未知去重方式: {self.dedup}")


@dataclass
class ProcessResult:
    records_in: int
    records_out: int
    duplicates_removed: int
    skipped_files: list[str]
    output_path: str
    exceptions: list[ExceptionEntry] = field(default_factory=list)


def run_merge(plan: ProcessPlan) -> ProcessResult:
    """合并 / 转换主流程。绝不静默覆盖输出文件，绝不因单条记录失败而中断整批。"""
    log = plan.log if plan.log is not None else RunLog()

    files = list_input_files(
        plan.inputs,
        recursive=plan.recursive,
        fasta_suffixes=plan.fasta_suffixes,
        genbank_suffixes=plan.genbank_suffixes,
    )
    if not files:
        raise SeqToolkitError("没有找到可处理的输入文件")

    records: list[SequenceRecord] = []
    pending_warnings: list[tuple[SequenceRecord, str]] = []
    skipped_files: list[str] = []
    seen_accessions: dict[str, str] = {}
    duplicates = 0
    total = len(files)

    def _on_skip(skip_path: str, line: int, reason: str) -> None:
        log.add_exception(skip_path, line, "", reason, "")
        log.warn(f"{skip_path}:{line} {reason}")

    for index, path in enumerate(files, start=1):
        _raise_if_cancelled(plan.cancel)
        if plan.progress is not None:
            plan.progress(index - 1, total, f"读取 {os.path.basename(path)}")

        detected = detect_format(path, plan.input_format)
        if detected not in ("fasta", "genbank"):
            log.warn(f"跳过无法识别格式的文件: {path}")
            skipped_files.append(path)
            continue

        guessed = format_from_suffix(path)
        if plan.input_format == "auto" and guessed and guessed != detected:
            log.warn(f"后缀名与内容不符，按内容判定为 {detected}: {path}")

        try:
            if detected == "genbank":
                producer = read_genbank(path, on_skip=_on_skip)
            else:
                producer = read_fasta(path)
            for record in producer:
                _raise_if_cancelled(plan.cancel)

                if record.warnings:
                    for warning in record.warnings:
                        log.warn(f"{record.origin_path}:{record.origin_line} {warning}")

                if plan.dedup == "accession":
                    key = record.accession.upper()
                    if key in seen_accessions:
                        duplicates += 1
                        log.info(
                            f"去重：{record.accession} 已出现在 {seen_accessions[key]}，"
                            f"跳过 {path}"
                        )
                        continue
                    seen_accessions[key] = path

                # 待复核项必须在去重判断**之后**登记：被去重丢弃的记录并没有写出，
                # 出现在人工复核清单里会误导用户去核对一个不存在的产物。
                if record.warnings:
                    hard = [w for w in record.warnings if not _is_benign_warning(w)]
                    if hard:
                        pending_warnings.append((record, "; ".join(hard)))
                records.append(record)
        except (FastaParseError, GenBankParseError) as error:
            log.error(f"解析失败: {path}: {error}")
            skipped_files.append(path)
            continue
        except (OSError, EOFError, zlib.error) as error:
            # 必须连 EOFError 与 zlib.error 一起捕获：损坏或截断的 .gz 在**解析阶段**
            # 抛出的正是这两类，而它们都不是 OSError 的子类。漏掉任一，一个坏文件
            # 就会中断整批处理，而不是被记入异常清单后继续。
            log.error(f"无法读取文件: {path}: {error}")
            skipped_files.append(path)
            continue

    _raise_if_cancelled(plan.cancel)
    if not records:
        raise SeqToolkitError("没有任何记录可写出")

    name_map = build_name_map(records, plan.naming_mode)

    for record, reason in pending_warnings:
        log.add_exception(record.origin_path, record.origin_line,
                          record.definition or record.species_raw or record.accession,
                          reason, name_map.get(record) or record.accession)
    for record in records:
        if not record.species:
            log.add_exception(record.origin_path, record.origin_line,
                              record.definition or record.accession,
                              "物种名缺失，名称回退为登录号",
                              name_map.get(record) or record.accession)

    target = resolve_output_path(plan.output_path)
    if target != plan.output_path:
        log.warn(f"目标文件已存在，实际写入: {target}")

    if plan.progress is not None:
        plan.progress(total, total, "写出结果")

    if plan.output_format == "genbank":
        write_genbank(records, target, name_map)
    else:
        write_fasta(records, target, name_map, wrap=plan.wrap)

    log.info(f"完成：读入 {len(records) + duplicates} 条，写出 {len(records)} 条，"
             f"去重 {duplicates} 条，跳过文件 {len(skipped_files)} 个")

    return ProcessResult(
        records_in=len(records) + duplicates,
        records_out=len(records),
        duplicates_removed=duplicates,
        skipped_files=skipped_files,
        output_path=target,
        exceptions=list(log.exceptions),
    )
```

**同一文件 `seq_toolkit/genbank_io.py` 中追加写出函数**（任务 13 会用到它，因此在本任务内一次写全，保证本任务可独立测试）：

```python
import datetime
from typing import Iterable, Mapping

LOCUS_NAME_START = 12
LOCUS_NAME_END = 28
LOCUS_NAME_WIDTH = LOCUS_NAME_END - LOCUS_NAME_START  # 16


def _replace_locus_name(raw_block: str, name: str) -> tuple[str, bool]:
    """把 LOCUS 行第 13-28 列替换为新名称。返回 (新文本, 是否成功替换)。"""
    if len(name) > LOCUS_NAME_WIDTH:
        return raw_block, False
    lines = raw_block.split("\n")
    for index, line in enumerate(lines):
        if line.startswith("LOCUS"):
            padded = name.ljust(LOCUS_NAME_WIDTH)
            lines[index] = line[:LOCUS_NAME_START] + padded + line[LOCUS_NAME_END:]
            return "\n".join(lines), True
    return raw_block, False


def _synthesise_genbank(record: SequenceRecord, name: str) -> str:
    """把 FASTA 来源的记录合成为最小合法 GenBank 记录。"""
    today = datetime.date.today().strftime("%d-%b-%Y").upper()
    locus_name = (name or record.accession or "sequence")[:LOCUS_NAME_WIDTH]
    sequence = record.seq
    lines = [
        f"LOCUS       {locus_name:<16}{len(sequence):>12} bp    DNA     linear   UNK {today}",
        f"DEFINITION  {record.definition or record.accession}.",
        f"ACCESSION   {record.accession_base or record.accession}",
        f"VERSION     {record.accession}",
        "KEYWORDS    .",
        f"SOURCE      {record.species_raw or record.accession}",
    ]
    if record.species_raw:
        lines.append(f"  ORGANISM  {record.species_raw}")
    lines.append("FEATURES             Location/Qualifiers")
    lines.append(f"     source          1..{len(sequence)}")
    if record.species_raw:
        lines.append(f'                     /organism="{record.species_raw}"')
        lines.append('                     /mol_type="genomic DNA"')
    lines.append("ORIGIN")
    for start in range(0, len(sequence), 60):
        chunk = sequence[start:start + 60]
        groups = " ".join(chunk[i:i + 10] for i in range(0, len(chunk), 10))
        lines.append(f"{start + 1:>9} {groups}")
    lines.append("//")
    return "\n".join(lines) + "\n"


def format_genbank_record(record: SequenceRecord, name: str) -> str:
    """产出一条 GenBank 文本。有原始块时逐字节保真，仅替换 LOCUS 名称列。"""
    if record.raw_block:
        if not name or name == record.accession:
            return record.raw_block
        replaced, _ok = _replace_locus_name(record.raw_block, name)
        return replaced
    return _synthesise_genbank(record, name)


def write_genbank(records: Iterable[SequenceRecord], out_path: str,
                  name_map: Mapping[SequenceRecord, str] | None = None) -> None:
    mapping = name_map or {}
    with open(str(out_path), "wt", encoding="utf-8", newline="\n") as handle:
        for index, record in enumerate(records, start=1):
            name = mapping.get(record) or record.accession or f"sequence_{index}"
            handle.write(format_genbank_record(record, name))
```

> **超过 16 字符的名称：** `format_genbank_record` 保持原 `LOCUS` 名不变（不截断、不破坏列对齐），`ACCESSION` 与新名称的对应关系由调用方在日志中记录。

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_pipeline.py -v`
预期：PASS（19 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): 增加合并与转换编排流程"
```

---

### Task 13：GenBank 写出、拆分与磁盘重命名

**文件：**
- 修改：`seq_toolkit/genbank_io.py`（仅在任务 12 遗漏时补齐 `format_genbank_record` / `write_genbank`）
- 修改：`tests/test_genbank_io.py`（追加测试）
- 修改：`seq_toolkit/pipeline.py`（追加 `split_records` / `rename_disk_files`）
- 修改：`tests/test_pipeline.py`（追加测试）

**接口：**
- 依赖输入：`SequenceRecord` / `render_name` / `build_name_map` / `resolve_output_path`，以及任务 12 产出的 `format_genbank_record` / `write_genbank`
- 对外产出：
  - `format_genbank_record(rec: SequenceRecord, name: str) -> str`
  - `write_genbank(records, out_path, name_map=None) -> None`
  - `RenamePlan` —— dataclass：`pairs: list[tuple[str, str]]`、`renamed: int`、`conflicts: list[tuple[str, str]]`
  - `split_records(records, out_dir, naming_mode="accession_species", output_format="fasta", wrap=0, log=None) -> ProcessResult`
  - `rename_disk_files(paths, naming_mode="accession_species", recursive=True, dry_run=True, input_format="auto", log=None) -> RenamePlan`

> **GenBank 改名只改 `LOCUS` 行的名称字段**：`LOCUS` 行的名称占第 13-28 列（共 16 列，0-based 切片 `line[12:28]`）。因此改写方式是 `line[:12] + name.ljust(16)[:16] + line[28:]`，其余列逐字节不变，`ACCESSION` 与 `VERSION` 保持原值。名称超过 16 字符时**不截断写入**（会破坏列对齐并造成下游解析截断），而是保留原 `LOCUS` 名并记 WARN，改名映射写入日志。

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_genbank_io.py` 末尾追加：

```python
from seq_toolkit.genbank_io import format_genbank_record, write_genbank
from seq_toolkit.naming import build_name_map


def test_write_genbank_preserves_raw_block_byte_for_byte(tmp_path):
    records = list(read_genbank(str(FIXTURES / "multi_record.gb")))
    out = tmp_path / "out.gb"
    write_genbank(records, str(out))
    original = (FIXTURES / "multi_record.gb").read_text(encoding="utf-8")
    assert out.read_text(encoding="utf-8") == original


def test_write_genbank_rename_touches_only_locus_name_column(tmp_path):
    records = list(read_genbank(str(FIXTURES / "multi_record.gb")))
    record = records[0]
    block = format_genbank_record(record, "MF999999.1")
    assert block.splitlines()[0][:12] == "LOCUS       "
    assert block.splitlines()[0][12:28] == "MF999999.1      "
    assert block.splitlines()[0][28:] == record.raw_block.splitlines()[0][28:]
    assert "VERSION     ON929859.1" in block
    assert "ACCESSION   ON929859" in block


def test_write_genbank_without_name_map_keeps_original(tmp_path):
    records = list(read_genbank(str(FIXTURES / "multi_record.gb")))
    out = tmp_path / "keep.gb"
    write_genbank(records, str(out), build_name_map(records, "keep"))
    assert "LOCUS       ON929859" in out.read_text(encoding="utf-8")


def test_write_genbank_warns_and_keeps_locus_for_overlong_name(tmp_path, caplog):
    records = list(read_genbank(str(FIXTURES / "multi_record.gb")))
    block = format_genbank_record(records[0], "ON929859.1_Salsola_pellucida")
    assert block.splitlines()[0].startswith("LOCUS       ON929859 ")


def test_synthesised_genbank_is_re_readable(tmp_path):
    from seq_toolkit.fasta_io import read_fasta
    fasta = tmp_path / "in.fa"
    fasta.write_text(">ON1.1 Salsola pellucida chloroplast, complete genome\nACGTACGT\n",
                     encoding="utf-8")
    records = list(read_fasta(str(fasta)))
    out = tmp_path / "synth.gb"
    write_genbank(records, str(out))
    back = list(read_genbank(str(out)))
    assert back[0].seq == "ACGTACGT"
    assert back[0].species == "Salsola_pellucida"
    assert "FEATURES" in out.read_text(encoding="utf-8")
```

在 `tests/test_pipeline.py` 末尾追加：

```python
from seq_toolkit.pipeline import RenamePlan, rename_disk_files, split_records


def test_split_records_writes_one_file_per_record(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A + FASTA_B)
    records = list(read_fasta(a))
    out_dir = tmp_path / "split"
    result = split_records(records, str(out_dir))
    assert result.records_out == 2
    assert sorted(p.name for p in out_dir.iterdir()) == [
        "MF2.1_Kochia_scoparia.fasta", "ON1.1_Salsola_pellucida.fasta"]


def test_split_records_avoids_overwriting(tmp_path):
    a = _write(tmp_path, "a.fa", FASTA_A)
    records = list(read_fasta(a))
    out_dir = tmp_path / "split"
    out_dir.mkdir()
    (out_dir / "ON1.1_Salsola_pellucida.fasta").write_text("原有", encoding="utf-8")
    split_records(records, str(out_dir))
    assert (out_dir / "ON1.1_Salsola_pellucida.fasta").read_text(
        encoding="utf-8") == "原有"
    assert (out_dir / "ON1.1_Salsola_pellucida_1.fasta").exists()


def test_rename_disk_files_dry_run_does_not_touch_disk(tmp_path):
    a = _write(tmp_path, "messy_name.fa", FASTA_A)
    plan = rename_disk_files([a], dry_run=True)
    assert isinstance(plan, RenamePlan)
    assert Path(a).exists()
    assert Path(plan.pairs[0][1]).name == "ON1.1_Salsola_pellucida.fa"


def test_rename_disk_files_actually_renames(tmp_path):
    a = _write(tmp_path, "messy_name.fa", FASTA_A)
    plan = rename_disk_files([a], dry_run=False)
    assert not Path(a).exists()
    assert Path(plan.pairs[0][1]).exists()
    assert plan.renamed == 1


def test_rename_disk_files_avoids_collision(tmp_path):
    a = _write(tmp_path, "messy_a.fa", FASTA_A)
    b = _write(tmp_path, "messy_b.fa", FASTA_A)
    plan = rename_disk_files([a, b], dry_run=False)
    targets = sorted(Path(new).name for _old, new in plan.pairs)
    assert targets == ["ON1.1_Salsola_pellucida.fa", "ON1.1_Salsola_pellucida_1.fa"]
    # conflicts 记的是「被迫改用带序号名称的那个文件自己」，即 b（原路径 → 实际新路径）
    assert plan.conflicts == [(b, str(tmp_path / "ON1.1_Salsola_pellucida_1.fa"))]


def test_rename_disk_files_keeps_gz_suffix(tmp_path):
    import gzip
    target = tmp_path / "messy.fa.gz"
    with gzip.open(str(target), "wt", encoding="utf-8") as handle:
        handle.write(FASTA_A)
    plan = rename_disk_files([str(target)], dry_run=True, input_format="fasta")
    assert Path(plan.pairs[0][1]).name == "ON1.1_Salsola_pellucida.fa.gz"
```

同时确认 `tests/test_pipeline.py` 顶部已导入 `read_fasta`；若没有，在 `from seq_toolkit.pipeline import (...)` 之前补上：

```python
from seq_toolkit.fasta_io import read_fasta
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_genbank_io.py tests/test_pipeline.py -v`
预期：FAIL，`ImportError: cannot import name 'write_genbank'`

- [ ] **步骤 3：确认 `write_genbank` 已可用**

`format_genbank_record` / `write_genbank` 已在任务 12 中实现（连同 `_replace_locus_name`、`_synthesise_genbank`）。本任务不重复实现，直接进入下一步。

若任务 12 因故未包含这段代码，请回到任务 12 的步骤 3 补齐后再继续。

- [ ] **步骤 4：实现 `split_records` 与 `rename_disk_files`**

在 `seq_toolkit/pipeline.py` 末尾追加：

```python
from .naming import render_name  # 合并到文件顶部既有 import 行

_FASTA_OUT_SUFFIX = ".fasta"
_GENBANK_OUT_SUFFIX = ".gb"


@dataclass
class RenamePlan:
    pairs: list[tuple[str, str]]
    renamed: int
    # 因目标文件名已被占用而被迫改用带序号名称的文件，每项为 (原路径, 实际新路径)。
    # 注意：它不是"被让位的文件"，也不保证是 pairs 的子集（重命名中途失败的文件
    # 会进这里而不进 pairs）——调用方不要用 len(pairs) - len(conflicts) 做算术。
    conflicts: list[tuple[str, str]]


def split_records(records: list[SequenceRecord], out_dir: str,
                  naming_mode: str = "accession_species",
                  output_format: str = "fasta", wrap: int = 0,
                  log: RunLog | None = None) -> ProcessResult:
    """把每条序列写成独立文件，文件名为最终序列名。"""
    log = log if log is not None else RunLog()
    os.makedirs(out_dir, exist_ok=True)
    name_map = build_name_map(records, naming_mode)
    suffix = _GENBANK_OUT_SUFFIX if output_format == "genbank" else _FASTA_OUT_SUFFIX
    written = 0
    for record in records:
        name = name_map.get(record) or record.accession or f"sequence_{written + 1}"
        target = resolve_output_path(os.path.join(out_dir, f"{name}{suffix}"))
        if os.path.basename(target) != f"{name}{suffix}":
            log.warn(f"目标文件已存在，实际写入: {target}")
        if output_format == "genbank":
            write_genbank([record], target)
        else:
            write_fasta([record], target, wrap=wrap)
        written += 1
    log.info(f"拆分完成：写出 {written} 个文件到 {out_dir}")
    return ProcessResult(
        records_in=len(records),
        records_out=written,
        duplicates_removed=0,
        skipped_files=[],
        output_path=out_dir,
        exceptions=list(log.exceptions),
    )


def rename_disk_files(paths: list[str], naming_mode: str = "accession_species",
                      recursive: bool = True, dry_run: bool = True,
                      input_format: str = "auto",
                      log: RunLog | None = None) -> RenamePlan:
    """按文件内容重命名磁盘文件本身。dry_run=True 时只返回对照表，不动磁盘。

    多记录文件以第一条记录决定新文件名，并记 INFO。目标同名时追加 _1、_2，
    被让位的文件记入 skipped。
    """
    log = log if log is not None else RunLog()
    files = list_input_files(paths, recursive=recursive)
    pairs: list[tuple[str, str]] = []
    conflicts: list[tuple[str, str]] = []
    renamed = 0
    planned: set[str] = set()

    for path in files:
        detected = detect_format(path, input_format)
        if detected not in ("fasta", "genbank"):
            log.warn(f"跳过无法识别格式的文件: {path}")
            continue
        try:
            producer = (read_genbank(path) if detected == "genbank"
                        else read_fasta(path))
            first = next(iter(producer))
        except (FastaParseError, GenBankParseError, StopIteration) as error:
            log.error(f"无法解析，跳过重命名: {path}: {error}")
            continue

        name = render_name(first, naming_mode) or first.accession
        original = Path(path)
        suffix = original.name[len(original.stem):]

        candidate = original.with_name(f"{name}{suffix}")
        counter = 0
        while candidate.exists() and str(candidate) != str(original):
            counter += 1
            candidate = original.with_name(f"{name}_{counter}{suffix}")
        while str(candidate) in planned:
            counter += 1
            candidate = original.with_name(f"{name}_{counter}{suffix}")
        if counter:
            log.warn(f"目标名已被占用，{original.name} 将改名为 {candidate.name}")
            skipped.append((str(original), str(candidate)))

        pairs.append((str(original), str(candidate)))
        planned.add(str(candidate))

        if not dry_run and str(candidate) != str(original):
            original.rename(candidate)
            renamed += 1

    mode_text = "预览" if dry_run else "执行"
    log.info(f"文件重命名{mode_text}完成：{len(pairs)} 个文件，实际改名 {renamed} 个")
    return RenamePlan(pairs=pairs, renamed=renamed, conflicts=conflicts)
```

- [ ] **步骤 5：运行测试并确认其通过**

运行：`python -m pytest tests/test_genbank_io.py tests/test_pipeline.py -v`
预期：PASS（test_genbank_io 22 passed，test_pipeline 25 passed）

- [ ] **步骤 6：提交**

```bash
git add seq_toolkit/genbank_io.py seq_toolkit/pipeline.py tests
git commit -m "feat(pipeline): 增加 GenBank 写出、按序列拆分与磁盘批量重命名"
```

---

### Task 14：配置持久化 `settings.py`

**文件：**
- 新建：`seq_toolkit/settings.py`
- 测试：`tests/test_settings.py`

**接口：**
- 依赖输入：`format_detect` 的默认后缀常量
- 对外产出：
  - `Settings` —— dataclass：`email: str = ""`、`api_key: str = ""`、`proxy: str = ""`、`output_dir: str = ""`、`wrap: int = 0`、`force_redownload: bool = False`、`fasta_suffixes: tuple[str, ...]`、`genbank_suffixes: tuple[str, ...]`
  - `settings_path() -> str` —— `%APPDATA%/seq_toolkit/settings.json`（无 APPDATA 时回退到用户主目录）
  - `load_settings(path: str | None = None) -> Settings` —— 文件缺失或损坏时返回默认值，绝不抛异常
  - `save_settings(settings: Settings, path: str | None = None) -> str` —— 返回实际写入路径

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_settings.py`：

```python
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
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_settings.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit.settings'`

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/settings.py`：

```python
"""用户配置读写。文件损坏或以任何方式不可读时必须回退到默认值，绝不抛异常。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields

from .format_detect import DEFAULT_FASTA_SUFFIXES, DEFAULT_GENBANK_SUFFIXES

_APP_DIR = "seq_toolkit"
_FILE_NAME = "settings.json"


@dataclass
class Settings:
    email: str = ""
    api_key: str = ""
    proxy: str = ""
    output_dir: str = ""
    wrap: int = 0
    force_redownload: bool = False
    fasta_suffixes: tuple[str, ...] = field(default=DEFAULT_FASTA_SUFFIXES)
    genbank_suffixes: tuple[str, ...] = field(default=DEFAULT_GENBANK_SUFFIXES)


def _base_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, _APP_DIR)


def settings_path() -> str:
    return os.path.join(_base_dir(), _FILE_NAME)


def _coerce(raw: dict, target_type, default, key: str):
    """只接受类型匹配的值，否则退回默认值——配置文件是外部输入，必须防御。"""
    value = raw.get(key, default)
    if target_type is tuple:
        if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
            return tuple(value)
        return default
    if target_type is bool:
        return value if isinstance(value, bool) else default
    if target_type is int:
        return value if isinstance(value, int) and not isinstance(value, bool) else default
    return value if isinstance(value, target_type) else default


def load_settings(path: str | None = None) -> Settings:
    target = path or settings_path()
    defaults = Settings()
    try:
        # 读入用 utf-8-sig：兼容"带 BOM 的 UTF-8"——Windows 记事本存盘默认就是这种。
        # 用普通 utf-8 会让整个文件被判为非法 JSON，8 个字段全部静默回默认值，
        # 用户观感是"配置文件怎么改都不生效"。此举与全局约束"读入用 utf-8-sig"一致。
        with open(target, "rt", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            return defaults
    except (OSError, ValueError, RecursionError, MemoryError):
        # RecursionError 与 MemoryError 必须一并捕获：畸形或超大的配置文件（例如
        # 深度极大的嵌套数组）抛的正是这两类，而它们都不是 ValueError/OSError 的子类。
        # 本函数对外的契约是"任何配置问题都不得抛异常"，否则调用方（GUI 启动、
        # 下载流程）会直接崩掉，而不是退回默认配置。
        return defaults

    values = {}
    for info in fields(Settings):
        default = getattr(defaults, info.name)
        values[info.name] = _coerce(raw, info.type, default, info.name)
    return Settings(**values)


def save_settings(settings: Settings, path: str | None = None) -> str:
    target = path or settings_path()
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = asdict(settings)
    with open(target, "wt", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return target
```

> `_coerce` 的 `info.type` 在 `from __future__ import annotations` 下是字符串。若测试报 `TypeError`，请把 `_coerce` 改为接收显式的类型表：

```python
_SCHEMA = {
    "email": str, "api_key": str, "proxy": str, "output_dir": str,
    "wrap": int, "force_redownload": bool,
    "fasta_suffixes": tuple, "genbank_suffixes": tuple,
}
```
并把循环体改为 `values[name] = _coerce(raw, _SCHEMA[name], getattr(defaults, name), name)`。

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_settings.py -v`
预期：PASS（8 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/settings.py tests/test_settings.py
git commit -m "feat(settings): 增加配置持久化与损坏回退"
```

---

### Task 15：NCBI 客户端骨架（限速与重试）

**文件：**
- 新建：`seq_toolkit/ncbi.py`
- 测试：`tests/test_ncbi.py`

**接口：**
- 依赖输入：`RunLog`（任务 11）、`pipeline.OperationCancelled`
- 对外产出：
  - `NCBI_BASE_URL: str`
  - `NcbiError(SeqToolkitError)`
  - `RateLimiter(rate_per_second, clock=time.monotonic, sleeper=time.sleep)`，方法 `acquire()`
  - `NcbiClient(email, api_key=None, proxy=None, tool="seq_toolkit", log=None, cancel=None, opener=None, sleeper=time.sleep)`
    - 属性 `rate_limit: float`（无 key 3.0，有 key 10.0）
    - 方法 `_request(endpoint: str, params: dict, method: str = "GET", retries: int = 3) -> str`
  - `MAX_SUMMARY_BATCH = 500`、`MAX_FETCH_BATCH = 200`

> `opener` 与 `sleeper` 均为可注入依赖，使整个 NCBI 层可以在**完全不联网、不真实等待**的前提下被测试。

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_ncbi.py`：

```python
import io
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

from seq_toolkit.applog import RunLog
from seq_toolkit.ncbi import NcbiClient, NcbiError, RateLimiter


class FakeClock:
    def __init__(self):
        self.now_value = 0.0
        self.slept = []

    def now(self):
        return self.now_value

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now_value += seconds


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


class RecordingOpener:
    """按调用顺序返回预设结果；记录每个 Request 的 URL/方法/参数。"""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome.encode("utf-8"))

    def params_of(self, index):
        request = self.requests[index]
        raw = request.data.decode("utf-8") if request.data else urlparse(request.full_url).query
        return {k: v[0] for k, v in parse_qs(raw).items()}


def _client(opener, **kwargs):
    return NcbiClient(email="me@example.org", opener=opener, sleeper=lambda s: None, **kwargs)


def test_rate_limiter_spaces_calls_without_api_key():
    clock = FakeClock()
    limiter = RateLimiter(2.0, clock=clock.now, sleeper=clock.sleep)
    limiter.acquire()
    limiter.acquire()
    assert clock.slept == [0.5]


def test_rate_limiter_does_not_sleep_when_clock_advanced():
    clock = FakeClock()
    limiter = RateLimiter(10.0, clock=clock.now, sleeper=clock.sleep)
    limiter.acquire()
    clock.now_value += 1.0
    limiter.acquire()
    assert clock.slept == []


def test_rate_limit_is_three_without_key_and_ten_with_key():
    assert _client(RecordingOpener([])).rate_limit == 3.0
    assert _client(RecordingOpener([]), api_key="K").rate_limit == 10.0


def test_request_sends_tool_email_and_api_key():
    opener = RecordingOpener(["{}"])
    client = _client(opener, api_key="SECRET")
    client._request("esearch.fcgi", {"db": "nuccore"})
    params = opener.params_of(0)
    assert params["tool"] == "seq_toolkit"
    assert params["email"] == "me@example.org"
    assert params["api_key"] == "SECRET"
    assert params["db"] == "nuccore"


def test_request_retries_on_server_error_then_succeeds():
    delays = []
    opener = RecordingOpener([
        HTTPError("u", 500, "boom", {}, None),
        HTTPError("u", 500, "boom", {}, None),
        "OK",
    ])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=delays.append)
    assert client._request("esummary.fcgi", {}) == "OK"
    assert delays == [1, 2]


def test_request_retries_on_network_error():
    opener = RecordingOpener([URLError("offline"), "OK"])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=lambda s: None)
    assert client._request("efetch.fcgi", {}) == "OK"


def test_request_honours_retry_after_on_429():
    delays = []
    error = HTTPError("u", 429, "slow down", {"Retry-After": "7"}, None)
    opener = RecordingOpener([error, "OK"])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=delays.append)
    assert client._request("esearch.fcgi", {}) == "OK"
    assert delays == [7.0]


def test_request_gives_up_after_retries_and_raises_ncbi_error():
    opener = RecordingOpener([URLError("x"), URLError("x"), URLError("x")])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=lambda s: None)
    with pytest.raises(NcbiError):
        client._request("esearch.fcgi", {}, retries=3)


def test_request_raises_immediately_on_client_error():
    opener = RecordingOpener([HTTPError("u", 400, "bad request", {}, None)])
    client = NcbiClient(email="a@b.c", opener=opener, sleeper=lambda s: None)
    with pytest.raises(NcbiError):
        client._request("esearch.fcgi", {})
    assert len(opener.requests) == 1


def test_post_uses_request_body():
    opener = RecordingOpener(["{}"])
    client = _client(opener)
    client._request("efetch.fcgi", {"db": "nuccore", "id": "1,2,3"}, method="POST")
    request = opener.requests[0]
    assert request.get_method() == "POST"
    assert b"id=1%2C2%2C3" in request.data
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_ncbi.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit.ncbi'`

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/ncbi.py`：

```python
"""NCBI E-utilities 客户端：限速、重试、代理、分批。"""

from __future__ import annotations

import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from .applog import RunLog
from .model import SeqToolkitError
from .pipeline import OperationCancelled, resolve_output_path

NCBI_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL_NAME = "seq_toolkit"

RATE_WITHOUT_KEY = 3.0
RATE_WITH_KEY = 10.0

MAX_SUMMARY_BATCH = 500
MAX_FETCH_BATCH = 200


class NcbiError(SeqToolkitError):
    """NCBI 请求失败（网络不可达、被限流、响应异常等）。"""


class RateLimiter:
    """令牌桶限速：保证相邻两次请求至少间隔 1/rate 秒。"""

    def __init__(self, rate_per_second: float,
                 clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self._interval = 1.0 / float(rate_per_second)
        self._clock = clock
        self._sleep = sleeper
        self._last: float | None = None
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last is not None:
                wait = self._interval - (now - self._last)
                if wait > 0:
                    self._sleep(wait)
                    now = self._clock()
            self._last = now


class NcbiClient:
    """封装 E-utilities 调用。opener 与 sleeper 可注入，便于离线测试。"""

    def __init__(self, email: str, api_key: str | None = None,
                 proxy: str | None = None, tool: str = TOOL_NAME,
                 log: RunLog | None = None, cancel: threading.Event | None = None,
                 opener: Callable | None = None,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self.email = email or ""
        self.api_key = api_key or ""
        self.proxy = proxy or ""
        self.tool = tool
        self.log = log
        self.cancel = cancel
        self._sleep = sleeper
        self.rate_limit = RATE_WITH_KEY if self.api_key else RATE_WITHOUT_KEY
        self.limiter = RateLimiter(self.rate_limit, sleeper=sleeper)
        self._opener = opener if opener is not None else self._build_opener()

    def _build_opener(self) -> Callable:
        handlers = []
        if self.proxy:
            handlers.append(ProxyHandler({"http": self.proxy, "https": self.proxy}))
        director = build_opener(*handlers)
        return director.open

    def _check_cancelled(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise OperationCancelled("操作已取消")

    def _request(self, endpoint: str, params: dict, method: str = "GET",
                 retries: int = 3) -> str:
        url = f"{NCBI_BASE_URL}/{endpoint}"
        payload = dict(params)
        payload.setdefault("tool", self.tool)
        if self.email:
            payload.setdefault("email", self.email)
        if self.api_key:
            payload.setdefault("api_key", self.api_key)

        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            self._check_cancelled()
            self.limiter.acquire()
            try:
                if method == "POST":
                    request = Request(url, data=urlencode(payload).encode("utf-8"),
                                      method="POST")
                else:
                    request = Request(f"{url}?{urlencode(payload)}")
                with self._opener(request) as response:
                    return response.read().decode("utf-8", errors="replace")
            except HTTPError as error:
                if error.code == 429:
                    header = error.headers.get("Retry-After") if error.headers else None
                    delay = float(header) if header and str(header).isdecimal() else 5.0
                    last_error = error
                    if self.log is not None:
                        self.log.warn(f"NCBI 限流（429），等待 {delay:.0f} 秒后重试")
                    self._sleep(delay)
                    continue
                if 500 <= error.code < 600:
                    last_error = error
                    self._sleep(float(2 ** (attempt - 1)))
                    continue
                raise NcbiError(f"NCBI 返回 {error.code}: {error.reason}") from error
            except URLError as error:
                last_error = error
                self._sleep(float(2 ** (attempt - 1)))
                continue

        raise NcbiError(f"请求失败（已重试 {retries} 次）: {last_error}")
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_ncbi.py -v`
预期：PASS（10 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/ncbi.py tests/test_ncbi.py
git commit -m "feat(ncbi): 增加带限速与重试的 E-utilities 客户端"
```

---

### Task 16：NCBI 检索与元数据

**文件：**
- 修改：`seq_toolkit/ncbi.py`（追加查询构造、检索、元数据）
- 修改：`tests/test_ncbi.py`（追加测试）

**接口：**
- 依赖输入：任务 15 的 `NcbiClient` / `_request`
- 对外产出：
  - `COMPLETE_GENOME_PATTERNS: tuple[str, ...]`
  - `matches_complete_genome(definition: str) -> bool`
  - `build_query(term, scope="species", min_length=None, max_length=None, refseq_only=False) -> str`
  - `SearchResult` —— dataclass：`query: str`、`total: int`、`ids: list[str]`、`webenv: str`、`query_key: str`
  - `SeqSummary` —— dataclass：`accession: str`、`length: int`、`organism: str`、`definition: str`、`date: str`、`source_db: str`
  - `NcbiClient.search(term, scope="species", retmax=500, min_length=None, max_length=None, refseq_only=False) -> SearchResult`
  - `NcbiClient.summarize(accessions: list[str]) -> list[SeqSummary]`
  - `NcbiClient.search_summaries(term, scope=..., **filters) -> tuple[SearchResult, list[SeqSummary]]` —— 检索并取回全部结果的元数据，顺带应用长度、完整基因组、RefSeq 三个本地筛选

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_ncbi.py` 末尾追加：

```python
import json

from seq_toolkit.ncbi import (
    COMPLETE_GENOME_PATTERNS,
    SeqSummary,
    SearchResult,
    build_query,
    matches_complete_genome,
)


def test_build_query_for_species_quotes_the_term():
    assert build_query("Salsola pellucida") == '"Salsola pellucida"[Organism]'


def test_build_query_for_genus_does_not_quote():
    assert build_query("Salsola", scope="genus") == "Salsola[Organism]"


def test_build_query_adds_length_filter():
    assert build_query("Salsola", scope="genus", min_length=100000,
                       max_length=200000) == "Salsola[Organism] AND 100000:200000[SLEN]"


def test_build_query_adds_refseq_filter():
    assert build_query("Salsola", scope="genus", refseq_only=True) == (
        "Salsola[Organism] AND srcdb_refseq[prop]")


def test_build_query_rejects_empty_term():
    with pytest.raises(ValueError):
        build_query("   ")


def test_build_query_rejects_unknown_scope():
    with pytest.raises(ValueError):
        build_query("Salsola", scope="kingdom")


def test_complete_genome_patterns_are_the_documented_six():
    assert COMPLETE_GENOME_PATTERNS == (
        "complete genome",
        "complete chloroplast genome",
        "complete plastid genome",
        "complete mitochondrial genome",
        "complete plastome",
        "complete mitochondrial dna",
    )


def test_matches_complete_genome_is_case_insensitive():
    assert matches_complete_genome("Salsola pellucida chloroplast, COMPLETE GENOME") is True
    assert matches_complete_genome("Salsola pellucida chloroplast, partial sequence") is False
    assert matches_complete_genome("Salsola pellucida complete chloroplast genome") is True


def _esearch_payload(count, ids, webenv="WE", query_key="1"):
    return json.dumps({"esearchresult": {"count": str(count), "idlist": ids,
                                         "webenv": webenv, "querykey": query_key}})


def test_search_parses_esearch_response():
    opener = RecordingOpener([_esearch_payload(2, ["111", "222"])])
    client = _client(opener)
    result = client.search("Salsola pellucida")
    assert isinstance(result, SearchResult)
    assert result.total == 2
    assert result.ids == ["111", "222"]
    assert result.webenv == "WE"
    assert result.query_key == "1"
    assert result.query == '"Salsola pellucida"[Organism]'


def test_search_uses_history_for_large_result_sets():
    opener = RecordingOpener([_esearch_payload(99999, ["1"])])
    _client(opener).search("Salsola", scope="genus")
    params = opener.params_of(0)
    assert params["usehistory"] == "y"
    assert params["db"] == "nuccore"
    assert params["retmode"] == "json"


def _esummary_payload(mapping):
    return json.dumps({"result": mapping})


def _doc(accession, length, organism, title, date="2022/01/12", srcdb="GenBank"):
    return {"accessionversion": accession, "slen": str(length), "organism": organism,
            "title": title, "createdate": date, "sourcedb": srcdb}


def test_summarize_parses_documents():
    payload = _esummary_payload({
        "uids": ["111"],
        "111": _doc("ON929859.1", 152398, "Salsola pellucida",
                    "Salsola pellucida chloroplast, complete genome"),
    })
    opener = RecordingOpener([payload])
    summaries = _client(opener).summarize(["111"])
    assert len(summaries) == 1
    summary = summaries[0]
    assert isinstance(summary, SeqSummary)
    assert summary.accession == "ON929859.1"
    assert summary.length == 152398
    assert summary.organism == "Salsola pellucida"
    assert summary.source_db == "GenBank"


def test_summarize_splits_into_batches_of_500():
    ids = [str(i) for i in range(1200)]
    payloads = [_esummary_payload({"uids": []}) for _ in range(3)]
    opener = RecordingOpener(payloads)
    _client(opener).summarize(ids)
    assert len(opener.requests) == 3
    assert len(opener.params_of(0)["id"].split(",")) == 500
    assert len(opener.params_of(2)["id"].split(",")) == 200


def test_search_summaries_applies_local_complete_genome_filter():
    search_payload = _esearch_payload(2, ["1", "2"])
    summary_payload = _esummary_payload({
        "uids": ["1", "2"],
        "1": _doc("A.1", 150000, "Salsola pellucida",
                  "Salsola pellucida chloroplast, complete genome"),
        "2": _doc("B.1", 800, "Salsola pellucida",
                  "Salsola pellucida matK gene, partial cds"),
    })
    opener = RecordingOpener([search_payload, summary_payload])
    result, summaries = _client(opener).search_summaries(
        "Salsola pellucida", complete_genome_only=True)
    assert result.total == 2
    assert [s.accession for s in summaries] == ["A.1"]


def test_search_summaries_applies_local_length_filter():
    search_payload = _esearch_payload(2, ["1", "2"])
    summary_payload = _esummary_payload({
        "uids": ["1", "2"],
        "1": _doc("A.1", 150000, "Salsola pellucida", "complete genome"),
        "2": _doc("B.1", 800, "Salsola pellucida", "complete genome"),
    })
    opener = RecordingOpener([search_payload, summary_payload])
    _result, summaries = _client(opener).search_summaries(
        "Salsola pellucida", min_length=100000)
    assert [s.accession for s in summaries] == ["A.1"]


def test_search_summaries_applies_local_refseq_filter():
    search_payload = _esearch_payload(2, ["1", "2"])
    summary_payload = _esummary_payload({
        "uids": ["1", "2"],
        "1": _doc("NC_1.1", 150000, "Salsola pellucida", "complete genome",
                  srcdb="RefSeq"),
        "2": _doc("MF1.1", 150000, "Salsola pellucida", "complete genome",
                  srcdb="GenBank"),
    })
    opener = RecordingOpener([search_payload, summary_payload])
    _result, summaries = _client(opener).search_summaries(
        "Salsola pellucida", refseq_only_local=True)
    assert [s.accession for s in summaries] == ["NC_1.1"]
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_ncbi.py -v`
预期：FAIL，`ImportError: cannot import name 'build_query'`

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/ncbi.py` 顶部 import 区补上：

```python
import json
from dataclasses import dataclass, field
```

在 `NcbiError` 之后追加：

```python
COMPLETE_GENOME_PATTERNS = (
    "complete genome",
    "complete chloroplast genome",
    "complete plastid genome",
    "complete mitochondrial genome",
    "complete plastome",
    "complete mitochondrial dna",
)

KNOWN_SCOPES = ("species", "genus")


def matches_complete_genome(definition: str) -> bool:
    """本地判定"是否完整基因组"。NCBI 服务端没有可信字段，只能按定义行匹配。"""
    lowered = (definition or "").lower()
    return any(pattern in lowered for pattern in COMPLETE_GENOME_PATTERNS)


def build_query(term: str, scope: str = "species", min_length: int | None = None,
                max_length: int | None = None, refseq_only: bool = False) -> str:
    """构造 nuccore 检索式。物种名加引号精确匹配，属名不加引号以覆盖属下所有种。"""
    cleaned = (term or "").strip()
    if not cleaned:
        raise ValueError("检索词不能为空")
    if scope not in KNOWN_SCOPES:
        raise ValueError(f"未知检索范围: {scope}")

    clause = f'"{cleaned}"[Organism]' if scope == "species" else f"{cleaned}[Organism]"
    parts = [clause]
    if min_length is not None or max_length is not None:
        low = 0 if min_length is None else int(min_length)
        high = 1_000_000_000 if max_length is None else int(max_length)
        parts.append(f"{low}:{high}[SLEN]")
    if refseq_only:
        parts.append("srcdb_refseq[prop]")
    return " AND ".join(parts)


@dataclass
class SearchResult:
    query: str
    total: int
    ids: list[str]
    webenv: str = ""
    query_key: str = ""


@dataclass
class SeqSummary:
    accession: str
    length: int
    organism: str
    definition: str
    date: str = ""
    source_db: str = ""
```

在 `NcbiClient` 类中追加方法：

```python
    def search(self, term: str, scope: str = "species", retmax: int = 500,
               min_length: int | None = None, max_length: int | None = None,
               refseq_only: bool = False) -> SearchResult:
        query = build_query(term, scope, min_length, max_length, refseq_only)
        text = self._request("esearch.fcgi", {
            "db": "nuccore", "term": query, "retmode": "json",
            "usehistory": "y", "retmax": str(retmax),
        })
        try:
            payload = json.loads(text)
            result = payload["esearchresult"]
        except (ValueError, KeyError) as error:
            raise NcbiError(f"esearch 响应无法解析: {error}") from error
        return SearchResult(
            query=query,
            total=int(result.get("count", 0) or 0),
            ids=list(result.get("idlist", []) or []),
            webenv=result.get("webenv", "") or "",
            query_key=str(result.get("querykey", "") or ""),
        )

    def summarize(self, accessions: list[str]) -> list[SeqSummary]:
        summaries: list[SeqSummary] = []
        for start in range(0, len(accessions), MAX_SUMMARY_BATCH):
            self._check_cancelled()
            batch = accessions[start:start + MAX_SUMMARY_BATCH]
            text = self._request("esummary.fcgi", {
                "db": "nuccore", "retmode": "json", "id": ",".join(batch),
            })
            summaries.extend(self._parse_summaries(text))
        return summaries

    @staticmethod
    def _parse_summaries(text: str) -> list[SeqSummary]:
        try:
            payload = json.loads(text)
            result = payload["result"]
        except (ValueError, KeyError) as error:
            raise NcbiError(f"esummary 响应无法解析: {error}") from error
        uids = result.get("uids", []) or []
        summaries: list[SeqSummary] = []
        for uid in uids:
            doc = result.get(uid)
            if not isinstance(doc, dict):
                continue
            try:
                length = int(doc.get("slen") or 0)
            except (TypeError, ValueError):
                length = 0
            summaries.append(SeqSummary(
                accession=doc.get("accessionversion") or doc.get("caption") or "",
                length=length,
                organism=doc.get("organism") or "",
                definition=doc.get("title") or "",
                date=doc.get("createdate") or "",
                source_db=doc.get("sourcedb") or "",
            ))
        return summaries

    def search_summaries(self, term: str, scope: str = "species",
                         retmax: int = 500, min_length: int | None = None,
                         max_length: int | None = None, refseq_only: bool = False,
                         complete_genome_only: bool = False,
                         refseq_only_local: bool = False,
                         ) -> tuple[SearchResult, list[SeqSummary]]:
        """检索 + 取元数据 + 本地筛选（长度、完整基因组、RefSeq）。"""
        result = self.search(term, scope, retmax, min_length, max_length, refseq_only)
        if not result.ids:
            return result, []
        summaries = self.summarize(result.ids)
        if min_length is not None:
            summaries = [s for s in summaries if s.length >= min_length]
        if max_length is not None:
            summaries = [s for s in summaries if s.length <= max_length]
        if complete_genome_only:
            summaries = [s for s in summaries if matches_complete_genome(s.definition)]
        if refseq_only_local:
            summaries = [s for s in summaries if s.source_db == "RefSeq"]
        return result, summaries
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_ncbi.py -v`
预期：PASS（23 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/ncbi.py tests/test_ncbi.py
git commit -m "feat(ncbi): 增加检索、元数据与本地筛选"
```

---

### Task 17：序列获取与批量下载编排

**文件：**
- 修改：`seq_toolkit/ncbi.py`（追加 `fetch_fasta` / `fetch_genbank` / `download`）
- 修改：`tests/test_ncbi.py`（追加测试）

**接口：**
- 依赖输入：任务 15、16 的客户端；`fasta_io` / `genbank_io` / `naming` / `pipeline`
- 对外产出：
  - `DownloadOptions` —— dataclass：`out_dir: str`、`want_fasta: bool = True`、`want_genbank: bool = True`、`per_sequence_files: bool = True`、`merged_files: bool = True`、`naming_mode: str = "accession"`、`force_redownload: bool = False`、`wrap: int = 0`
  - `DownloadReport` —— dataclass：`total: int`、`succeeded: int`、`skipped: int`、`failed: int`、`failures: list[tuple[str, str]]`、`out_dir: str`、`merged_fasta: str = ""`、`merged_genbank: str = ""`
  - `NcbiClient.fetch_fasta(accessions) -> str`、`NcbiClient.fetch_genbank(accessions) -> str`
  - `NcbiClient.download(accessions, options, progress=None) -> DownloadReport`

> **只取一次网络数据：** 若 `want_genbank` 为真，只请求 `gbwithparts`，再从解析出的记录同时写出 `.gb`（原始块保真）与 `.fa`（序列来自同一记录）。只有"只要 FASTA"时才请求 `rettype=fasta`。这把网络流量减半，且保证两种格式内容一致。
>
> **单条失败不拖垮整批：** 某一批 `efetch` 在重试后仍失败时，逐条重新尝试；只有该条自身也失败才计入 `failures`。

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_ncbi.py` 末尾追加：

```python
from seq_toolkit.ncbi import DownloadOptions, DownloadReport

GENBANK_TWO = (
    "LOCUS       ON1.1                   8 bp    DNA     linear   PLN 01-JAN-2020\n"
    "DEFINITION  Salsola pellucida chloroplast, complete genome.\n"
    "ACCESSION   ON1\n"
    "VERSION     ON1.1\n"
    "  ORGANISM  Salsola pellucida\n"
    "            Eukaryota; Amaranthaceae; Salsola.\n"
    "FEATURES             Location/Qualifiers\n"
    "     CDS             1..8\n"
    '                     /gene="matK"\n'
    "ORIGIN\n"
    "        1 acgtacgt\n"
    "//\n"
)

FASTA_TWO = ">MF2.1 Kochia scoparia chloroplast, complete genome\nTTTTGGGG\n"

GENBANK_MF2 = (
    "LOCUS       MF2.1                   8 bp    DNA     linear   PLN 01-JAN-2020\n"
    "DEFINITION  Kochia scoparia chloroplast, complete genome.\n"
    "ACCESSION   MF2\n"
    "VERSION     MF2.1\n"
    "  ORGANISM  Kochia scoparia\n"
    "            Eukaryota; Amaranthaceae; Kochia.\n"
    "ORIGIN\n"
    "        1 ttttgggg\n"
    "//\n"
)

# 一个批次只发一次 efetch 请求，响应里含该批全部序列。
# 因此模拟"多序列下载"必须让**一次响应包含多条记录**，
# 而不是给 fake opener 准备多条响应——那会与实际请求次数不符。
GENBANK_TWO_RECORDS = GENBANK_TWO + GENBANK_MF2


def test_fetch_genbank_batches_by_two_hundred():
    opener = RecordingOpener([GENBANK_TWO, GENBANK_TWO])
    client = _client(opener)
    client.fetch_genbank([str(i) for i in range(250)])
    assert len(opener.requests) == 2
    assert opener.params_of(0)["rettype"] == "gbwithparts"
    assert opener.requests[0].get_method() == "POST"


def test_fetch_fasta_uses_fasta_rettype():
    opener = RecordingOpener([FASTA_TWO])
    _client(opener).fetch_fasta(["MF2.1"])
    assert opener.params_of(0)["rettype"] == "fasta"


def test_download_writes_per_sequence_files_and_merged_files(tmp_path):
    # 2 个登录号落在同一个批次（每批上限 200），因此只发生 1 次请求
    opener = RecordingOpener([GENBANK_TWO_RECORDS])
    client = _client(opener)
    options = DownloadOptions(out_dir=str(tmp_path), naming_mode="accession")
    report = client.download(["ON1.1", "MF2.1"], options)
    assert isinstance(report, DownloadReport)
    assert len(opener.requests) == 1
    assert report.succeeded == 2
    assert (tmp_path / "ON1.1.gb").exists()
    assert (tmp_path / "ON1.1.fa").exists()
    assert (tmp_path / "MF2.1.gb").exists()
    assert (tmp_path / "MF2.1.fa").exists()
    assert (tmp_path / "all_sequences.fasta").exists()
    assert (tmp_path / "all_sequences.gb").exists()


def test_downloaded_genbank_keeps_features(tmp_path):
    opener = RecordingOpener([GENBANK_TWO])
    client = _client(opener)
    client.download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path)))
    assert '/gene="matK"' in (tmp_path / "ON1.1.gb").read_text(encoding="utf-8")


def test_download_applies_naming_mode(tmp_path):
    opener = RecordingOpener([GENBANK_TWO])
    client = _client(opener)
    client.download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path),
                                               naming_mode="accession_species"))
    assert (tmp_path / "ON1.1_Salsola_pellucida.gb").exists()
    merged = (tmp_path / "all_sequences.fasta").read_text(encoding="utf-8")
    assert merged.startswith(">ON1.1_Salsola_pellucida\n")


def test_download_skips_existing_files_without_force(tmp_path):
    (tmp_path / "ON1.1.gb").write_text("已存在", encoding="utf-8")
    (tmp_path / "ON1.1.fa").write_text("已存在", encoding="utf-8")
    opener = RecordingOpener([])
    client = _client(opener)
    report = client.download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path)))
    assert report.skipped == 1
    assert opener.requests == []
    assert (tmp_path / "ON1.1.gb").read_text(encoding="utf-8") == "已存在"


def test_download_force_redownload_overwrites(tmp_path):
    (tmp_path / "ON1.1.gb").write_text("旧内容", encoding="utf-8")
    (tmp_path / "ON1.1.fa").write_text("旧内容", encoding="utf-8")
    opener = RecordingOpener([GENBANK_TWO])
    client = _client(opener)
    report = client.download(["ON1.1"], DownloadOptions(out_dir=str(tmp_path),
                                                        force_redownload=True))
    assert report.succeeded == 1
    assert '/gene="matK"' in (tmp_path / "ON1.1.gb").read_text(encoding="utf-8")


def test_download_falls_back_to_per_accession_when_batch_fails(tmp_path):
    opener = RecordingOpener([
        URLError("batch failed"),
        URLError("batch failed"),
        URLError("batch failed"),
        GENBANK_TWO,          # 单条重试成功
        URLError("bad accession"),
        URLError("bad accession"),
        URLError("bad accession"),
    ])
    client = _client(opener)
    report = client.download(["ON1.1", "BAD.9"], DownloadOptions(out_dir=str(tmp_path)))
    assert report.succeeded == 1
    assert report.failed == 1
    assert report.failures[0][0] == "BAD.9"


def test_download_reports_progress(tmp_path):
    opener = RecordingOpener([GENBANK_TWO, FASTA_TWO])
    client = _client(opener)
    seen = []
    client.download(["ON1.1", "MF2.1"], DownloadOptions(out_dir=str(tmp_path)),
                    progress=lambda done, total, message: seen.append((done, total)))
    assert seen[-1] == (2, 2)


def test_download_only_fasta_requests_fasta_endpoint(tmp_path):
    opener = RecordingOpener([FASTA_TWO])
    client = _client(opener)
    client.download(["MF2.1"], DownloadOptions(out_dir=str(tmp_path),
                                               want_genbank=False))
    assert opener.params_of(0)["rettype"] == "fasta"
    assert (tmp_path / "MF2.1.fa").exists()
    assert not (tmp_path / "MF2.1.gb").exists()
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_ncbi.py -v`
预期：FAIL，`ImportError: cannot import name 'DownloadOptions'`

- [ ] **步骤 3：编写最小实现**

在 `seq_toolkit/ncbi.py` 顶部 import 区补上：

```python
import os
import tempfile

from .fasta_io import read_fasta, write_fasta
from .genbank_io import read_genbank, write_genbank
from .naming import build_name_map, sanitize_accession
```

在 `SeqSummary` 之后追加：

```python
@dataclass
class DownloadOptions:
    out_dir: str
    want_fasta: bool = True
    want_genbank: bool = True
    per_sequence_files: bool = True
    merged_files: bool = True
    naming_mode: str = "accession"
    force_redownload: bool = False
    wrap: int = 0


@dataclass
class DownloadReport:
    total: int
    succeeded: int
    skipped: int
    failed: int
    out_dir: str
    failures: list[tuple[str, str]] = field(default_factory=list)
    merged_fasta: str = ""
    merged_genbank: str = ""


def _exists_nonempty(path: str) -> bool:
    """判断文件存在且非空。空文件往往是上次中断留下的残迹，应当重新写入。"""
    return os.path.exists(path) and os.path.getsize(path) > 0
```

在 `NcbiClient` 类中追加方法：

```python
    def _batch(self, accessions: list[str]) -> list[list[str]]:
        return [accessions[i:i + MAX_FETCH_BATCH]
                for i in range(0, len(accessions), MAX_FETCH_BATCH)]

    @staticmethod
    def _write_temp(text: str, suffix: str) -> str:
        handle = tempfile.NamedTemporaryFile(
            "wt", suffix=suffix, delete=False, encoding="utf-8", newline="\n")
        try:
            handle.write(text)
        finally:
            handle.close()
        return handle.name

    @staticmethod
    def _parse_fetched(text: str, fmt: str) -> list:
        suffix = ".gb" if fmt == "genbank" else ".fa"
        temp_path = NcbiClient._write_temp(text, suffix)
        try:
            if fmt == "genbank":
                return list(read_genbank(temp_path))
            return list(read_fasta(temp_path))
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    def fetch_genbank(self, accessions: list[str]) -> str:
        chunks = []
        for batch in self._batch(accessions):
            self._check_cancelled()
            chunks.append(self._request("efetch.fcgi", {
                "db": "nuccore", "id": ",".join(batch),
                "rettype": "gbwithparts", "retmode": "text",
            }, method="POST"))
        return "".join(chunks)

    def fetch_fasta(self, accessions: list[str]) -> str:
        chunks = []
        for batch in self._batch(accessions):
            self._check_cancelled()
            chunks.append(self._request("efetch.fcgi", {
                "db": "nuccore", "id": ",".join(batch),
                "rettype": "fasta", "retmode": "text",
            }, method="POST"))
        return "".join(chunks)

    def download(self, accessions: list[str], options: DownloadOptions,
                 progress=None) -> DownloadReport:
        os.makedirs(options.out_dir, exist_ok=True)
        log = self.log
        total = len(accessions)
        succeeded = 0
        skipped = 0
        failures: list[tuple[str, str]] = []
        collected: list = []

        pending: list[str] = []
        predictable = options.naming_mode == "accession" and options.per_sequence_files
        for accession in accessions:
            if predictable and not options.force_redownload:
                stem = sanitize_accession(accession)
                needed = []
                if options.want_genbank:
                    needed.append(os.path.join(options.out_dir, f"{stem}.gb"))
                if options.want_fasta:
                    needed.append(os.path.join(options.out_dir, f"{stem}.fa"))
                if needed and all(os.path.exists(p) and os.path.getsize(p) > 0
                                  for p in needed):
                    skipped += 1
                    if log is not None:
                        log.info(f"已存在，跳过下载: {accession}")
                    continue
            pending.append(accession)

        done = skipped
        for batch in self._batch(pending):
            self._check_cancelled()
            self._check_cancelled()
            records_for_batch = []
            try:
                if options.want_genbank:
                    text = self.fetch_genbank(batch)
                    records_for_batch = self._parse_fetched(text, "genbank")
                else:
                    text = self.fetch_fasta(batch)
                    records_for_batch = self._parse_fetched(text, "fasta")
            except (NcbiError, SeqToolkitError) as error:
                if log is not None:
                    log.warn(f"批量下载失败，改为逐条重试: {error}")
                records_for_batch = self._retry_individually(
                    batch, options, failures, log)

            collected.extend(records_for_batch)
            succeeded += len(records_for_batch)
            done += len(batch)
            if progress is not None:
                progress(done, total, f"已下载 {succeeded} 条")

        name_map = build_name_map(collected, options.naming_mode)

        # 逐个序列写文件。已存在且非空的文件默认跳过（除非勾选强制重下）：
        # 当命名规则不是登录号时，下载前无法预知文件名，只能在拿到记录后判断，
        # 但同样必须遵守"绝不静默覆盖"。
        skipped_existing = 0
        if options.per_sequence_files:
            for record in collected:
                name = name_map.get(record) or sanitize_accession(record.accession)
                gb_path = os.path.join(options.out_dir, f"{name}.gb")
                fa_path = os.path.join(options.out_dir, f"{name}.fa")
                targets = []
                if options.want_genbank:
                    targets.append(gb_path)
                if options.want_fasta:
                    targets.append(fa_path)
                if (not options.force_redownload and targets
                        and all(_exists_nonempty(target) for target in targets)):
                    skipped_existing += 1
                    if log is not None:
                        log.info(f"文件已存在，跳过写入: {name}")
                    continue
                if options.want_genbank:
                    write_genbank([record], gb_path)
                if options.want_fasta:
                    write_fasta([record], fa_path, wrap=options.wrap)

        merged_fasta = ""
        merged_genbank = ""
        if options.merged_files and collected:
            if options.want_fasta:
                merged_fasta = resolve_output_path(
                    os.path.join(options.out_dir, "all_sequences.fasta"))
                if (os.path.basename(merged_fasta) != "all_sequences.fasta"
                        and log is not None):
                    log.warn(f"all_sequences.fasta 已存在，改写入 {merged_fasta}")
                write_fasta(collected, merged_fasta, name_map, wrap=options.wrap)
            if options.want_genbank:
                merged_genbank = resolve_output_path(
                    os.path.join(options.out_dir, "all_sequences.gb"))
                if (os.path.basename(merged_genbank) != "all_sequences.gb"
                        and log is not None):
                    log.warn(f"all_sequences.gb 已存在，改写入 {merged_genbank}")
                write_genbank(collected, merged_genbank, name_map)

        if log is not None:
            log.info(f"下载完成：成功 {succeeded - skipped_existing} 条，"
                     f"跳过 {skipped + skipped_existing} 条，失败 {len(failures)} 条")

        return DownloadReport(
            total=total,
            succeeded=succeeded - skipped_existing,
            skipped=skipped + skipped_existing,
            failed=len(failures),
            out_dir=options.out_dir,
            failures=failures,
            merged_fasta=merged_fasta,
            merged_genbank=merged_genbank,
        )

    def _retry_individually(self, batch: list[str], options: DownloadOptions,
                            failures: list[tuple[str, str]], log) -> list:
        recovered = []
        for accession in batch:
            self._check_cancelled()
            try:
                if options.want_genbank:
                    text = self.fetch_genbank([accession])
                    records = self._parse_fetched(text, "genbank")
                else:
                    text = self.fetch_fasta([accession])
                    records = self._parse_fetched(text, "fasta")
                if not records:
                    raise NcbiError("返回内容为空")
                recovered.extend(records)
            except (NcbiError, SeqToolkitError) as error:
                failures.append((accession, str(error)))
                if log is not None:
                    log.error(f"下载失败: {accession}: {error}")
        return recovered
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_ncbi.py -v`
预期：PASS（33 passed）

- [ ] **步骤 5：全量回归并提交**

运行：`python -m pytest -v`
预期：全部 PASS（约 150 项）

```bash
git add seq_toolkit/ncbi.py tests/test_ncbi.py
git commit -m "feat(ncbi): 增加序列获取与批量下载编排"
```

---

### Task 18：后台线程与消息泵 `gui/worker.py`

**文件：**
- 新建：`seq_toolkit/gui/worker.py`
- 测试：`tests/test_gui_worker.py`

**接口：**
- 依赖输入：`pipeline.OperationCancelled`
- 对外产出：
  - 消息类型常量 `MSG_PROGRESS`、`MSG_LOG`、`MSG_DONE`、`MSG_FAILED`
  - `WorkerMessage` —— frozen dataclass：`kind: str`、`payload: object = None`
  - `JobContext` —— 方法 `progress(done, total, message="")`、`info/warn/error(message)`、`raise_if_cancelled()`、属性 `cancel_event: threading.Event`
  - `BackgroundWorker` —— 属性 `queue`、`cancel_event`；方法 `start(target: Callable[[JobContext], object])`、`cancel()`、`is_running() -> bool`、`drain() -> list[WorkerMessage]`

> 这是 Tkinter 硬约束的落地点：后台线程只往 `queue.Queue` 投消息，主线程用 `after(100, ...)` 消费。**任何在后台线程里直接碰控件的行为都会导致随机崩溃。**

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_gui_worker.py`：

```python
import time

import pytest

from seq_toolkit.gui.worker import (
    MSG_DONE,
    MSG_FAILED,
    MSG_LOG,
    MSG_PROGRESS,
    BackgroundWorker,
)
from seq_toolkit.pipeline import OperationCancelled


def _wait(worker, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        messages = worker.drain()
        if any(m.kind in (MSG_DONE, MSG_FAILED) for m in messages):
            return messages
        time.sleep(0.01)
    raise AssertionError("worker 未在超时前结束")


def test_worker_reports_done_with_result():
    worker = BackgroundWorker()
    worker.start(lambda ctx: 42)
    messages = _wait(worker)
    assert messages[-1].kind == MSG_DONE
    assert messages[-1].payload == 42


def test_worker_reports_failure_with_exception():
    def boom(ctx):
        raise ValueError("炸了")

    worker = BackgroundWorker()
    worker.start(boom)
    messages = _wait(worker)
    assert messages[-1].kind == MSG_FAILED
    assert isinstance(messages[-1].payload, ValueError)


def test_worker_delivers_progress_and_log_in_order():
    def job(ctx):
        ctx.info("开始")
        ctx.progress(1, 3, "第一")
        ctx.progress(2, 3, "第二")
        ctx.warn("注意")
        return "ok"

    worker = BackgroundWorker()
    worker.start(job)
    payloads = [(m.kind, m.payload) for m in _wait(worker)]
    assert payloads == [
        (MSG_LOG, ("INFO", "开始")),
        (MSG_PROGRESS, (1, 3, "第一")),
        (MSG_PROGRESS, (2, 3, "第二")),
        (MSG_LOG, ("WARN", "注意")),
        (MSG_DONE, "ok"),
    ]


def test_cancel_sets_event_and_job_can_abort():
    worker = BackgroundWorker()

    def job(ctx):
        ctx.cancel_event.set()
        ctx.raise_if_cancelled()
        return "never"

    worker.start(job)
    messages = _wait(worker)
    assert messages[-1].kind == MSG_FAILED
    assert isinstance(messages[-1].payload, OperationCancelled)


def test_cancel_method_sets_event():
    worker = BackgroundWorker()
    worker.cancel()
    assert worker.cancel_event.is_set()


def test_is_running_is_false_before_start_and_after_finish():
    worker = BackgroundWorker()
    assert worker.is_running() is False
    worker.start(lambda ctx: None)
    _wait(worker)
    time.sleep(0.05)
    assert worker.is_running() is False


def test_start_refuses_while_running():
    worker = BackgroundWorker()
    worker.start(lambda ctx: time.sleep(0.3))
    with pytest.raises(RuntimeError):
        worker.start(lambda ctx: None)
    _wait(worker)
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_worker.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit.gui.worker'`

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/gui/worker.py`：

```python
"""后台工作线程与队列消息泵。

Tkinter 控件只能在主线程更新，因此后台线程只往 queue 投消息，
主线程用 App.after(100, ...) 周期消费。
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable

from ..pipeline import OperationCancelled

MSG_PROGRESS = "progress"
MSG_LOG = "log"
MSG_DONE = "done"
MSG_FAILED = "failed"

LEVEL_INFO = "INFO"
LEVEL_WARN = "WARN"
LEVEL_ERROR = "ERROR"


@dataclass(frozen=True)
class WorkerMessage:
    kind: str
    payload: object = None


class JobContext:
    """交给后台任务使用的上下文。任务只能通过它与界面通信。"""

    def __init__(self, out_queue: "queue.Queue[WorkerMessage]",
                 cancel_event: threading.Event) -> None:
        self._queue = out_queue
        self._cancel = cancel_event

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel

    def progress(self, done: int, total: int, message: str = "") -> None:
        self._queue.put(WorkerMessage(MSG_PROGRESS, (done, total, message)))

    def info(self, message: str) -> None:
        self._queue.put(WorkerMessage(MSG_LOG, (LEVEL_INFO, message)))

    def warn(self, message: str) -> None:
        self._queue.put(WorkerMessage(MSG_LOG, (LEVEL_WARN, message)))

    def error(self, message: str) -> None:
        self._queue.put(WorkerMessage(MSG_LOG, (LEVEL_ERROR, message)))

    def raise_if_cancelled(self) -> None:
        if self._cancel.is_set():
            raise OperationCancelled("操作已取消")


class BackgroundWorker:
    """单任务后台执行器。同一时刻只允许一个任务。"""

    def __init__(self) -> None:
        self.queue: "queue.Queue[WorkerMessage]" = queue.Queue()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, target: Callable[[JobContext], object]) -> None:
        if self.is_running():
            raise RuntimeError("已有任务在运行")
        self._cancel.clear()
        context = JobContext(self.queue, self._cancel)

        def _run() -> None:
            try:
                result = target(context)
            except BaseException as error:  # noqa: BLE001 必须捕获后送回主线程
                self.queue.put(WorkerMessage(MSG_FAILED, error))
            else:
                self.queue.put(WorkerMessage(MSG_DONE, result))

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def drain(self) -> list[WorkerMessage]:
        messages: list[WorkerMessage] = []
        while True:
            try:
                messages.append(self.queue.get_nowait())
            except queue.Empty:
                return messages
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_worker.py -v`
预期：PASS（7 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/worker.py tests/test_gui_worker.py
git commit -m "feat(gui): 增加后台线程与队列消息泵"
```

---

### Task 19：复用控件 `gui/widgets.py`

**文件：**
- 新建：`seq_toolkit/gui/widgets.py`
- 测试：`tests/test_gui_widgets.py`

**接口：**
- 依赖输入：无
- 对外产出：
  - `RowSelection` —— **纯逻辑、不依赖 Tk**，方法 `set_keys(keys)`、`toggle(key)`、`check(key)`、`uncheck(key)`、`is_checked(key)`、`checked_keys()`、`check_all()`、`uncheck_all()`、`invert()`、`count()`、`total()`
  - `CheckboxTable(ttk.Treeview)` —— 首列为勾选框，方法 `set_rows(rows: list[tuple])`、`selection` 属性、`refresh_checks()`、`bind_selection_change(callback)`
  - `SortableTable(ttk.Treeview)` —— 支持点击表头排序，方法 `set_rows(rows: list[tuple])`
  - `ProgressPanel(ttk.Frame)` —— 方法 `start(total)`、`update(done, total, text="")`、`finish(text="")`、`reset()`
  - `FilePicker(ttk.Frame)` —— 方法 `set_path(path)`、`path() -> str`
  - `grid_row(parent, row, label, widget)` —— 两列表单排版助手

> 勾选状态逻辑与 Tk 控件分离（`RowSelection`），这样最容易出错的部分可以脱离图形环境被完整测试。

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_gui_widgets.py`：

```python
import pytest

from seq_toolkit.gui.widgets import RowSelection


def test_checked_keys_follow_insertion_order():
    selection = RowSelection()
    selection.set_keys(["c", "a", "b"])
    selection.check("b")
    selection.check("a")
    assert selection.checked_keys() == ["a", "b"]


def test_toggle_switches_state():
    selection = RowSelection()
    selection.set_keys(["a"])
    assert selection.is_checked("a") is False
    selection.toggle("a")
    assert selection.is_checked("a") is True
    selection.toggle("a")
    assert selection.is_checked("a") is False


def test_check_all_and_uncheck_all():
    selection = RowSelection()
    selection.set_keys(["a", "b", "c"])
    selection.check_all()
    assert selection.count() == 3
    selection.uncheck_all()
    assert selection.count() == 0


def test_invert():
    selection = RowSelection()
    selection.set_keys(["a", "b", "c"])
    selection.check("b")
    selection.invert()
    assert selection.checked_keys() == ["a", "c"]


def test_set_keys_drops_stale_checked_entries():
    selection = RowSelection()
    selection.set_keys(["a", "b"])
    selection.check_all()
    selection.set_keys(["b", "c"])
    assert selection.checked_keys() == ["b"]
    assert selection.total() == 2


def test_set_keys_preserves_still_valid_checks():
    selection = RowSelection()
    selection.set_keys(["a", "b"])
    selection.check("a")
    selection.set_keys(["a", "b", "c"])
    assert selection.checked_keys() == ["a"]


def test_toggle_unknown_key_is_ignored():
    selection = RowSelection()
    selection.set_keys(["a"])
    selection.toggle("zzz")
    assert selection.count() == 0
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_widgets.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit.gui.widgets'`

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/gui/widgets.py`：

```python
"""可复用控件。勾选状态逻辑（RowSelection）与 Tk 控件分离，便于测试。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Iterable, Sequence

CHECKED = "\u2611"      # ☑
UNCHECKED = "\u2610"    # ☐
CHECK_COLUMN = "#1"


class RowSelection:
    """表格勾选状态。纯逻辑，不依赖 Tk。"""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._checked: set[str] = set()

    def set_keys(self, keys: Iterable[str]) -> None:
        self._order = [str(key) for key in keys]
        valid = set(self._order)
        self._checked &= valid

    def toggle(self, key: str) -> None:
        key = str(key)
        if key not in self._order:
            return
        if key in self._checked:
            self._checked.discard(key)
        else:
            self._checked.add(key)

    def check(self, key: str) -> None:
        if str(key) in self._order:
            self._checked.add(str(key))

    def uncheck(self, key: str) -> None:
        self._checked.discard(str(key))

    def is_checked(self, key: str) -> bool:
        return str(key) in self._checked

    def checked_keys(self) -> list[str]:
        return [key for key in self._order if key in self._checked]

    def check_all(self) -> None:
        self._checked = set(self._order)

    def uncheck_all(self) -> None:
        self._checked.clear()

    def invert(self) -> None:
        self._checked = set(self._order) - self._checked

    def count(self) -> int:
        return len(self._checked)

    def total(self) -> int:
        return len(self._order)


class CheckboxTable(ttk.Treeview):
    """首列为勾选框的表格。行数据以元组给出，首元素作为行的唯一键。"""

    def __init__(self, parent, columns: Sequence[str], headings: Sequence[str],
                 widths: Sequence[int] | None = None) -> None:
        all_columns = ("check",) + tuple(columns)
        super().__init__(parent, columns=all_columns, show="headings", height=14)
        self.selection = RowSelection()
        self._rows: list[tuple] = []
        self._on_change: Callable[[], None] | None = None

        self.heading("check", text="选")
        self.column("check", width=40, anchor="center", stretch=False)
        for index, column in enumerate(columns):
            self.heading(column, text=headings[index])
            width = widths[index] if widths else 120
            self.column(column, width=width, anchor="w", stretch=True)

        self.bind("<Button-1>", self._on_click)

    def _on_click(self, event) -> None:
        if self.identify_region(event.x, event.y) != "cell":
            return
        if self.identify_column(event.x) != CHECK_COLUMN:
            return
        item = self.identify_row(event.y)
        if not item:
            return
        self.selection.toggle(item)
        self.refresh_checks()

    def set_rows(self, rows: list[tuple]) -> None:
        self.delete(*self.get_children())
        self._rows = list(rows)
        self.selection.set_keys([str(row[0]) for row in self._rows])
        for row in self._rows:
            key = str(row[0])
            self.insert("", "end", iid=key,
                        values=(UNCHECKED,) + tuple(row[1:]))
        self.refresh_checks()

    def refresh_checks(self) -> None:
        for key in self.get_children():
            mark = CHECKED if self.selection.is_checked(key) else UNCHECKED
            values = list(self.item(key, "values"))
            values[0] = mark
            self.item(key, values=values)
        if self._on_change is not None:
            self._on_change()

    def bind_selection_change(self, callback: Callable[[], None]) -> None:
        self._on_change = callback


class SortableTable(ttk.Treeview):
    """支持点击表头排序的只读表格。"""

    def __init__(self, parent, columns: Sequence[str], headings: Sequence[str],
                 widths: Sequence[int] | None = None) -> None:
        super().__init__(parent, columns=tuple(columns), show="headings", height=14)
        self._rows: list[tuple] = []
        self._reverse: dict[str, bool] = {}
        for index, column in enumerate(columns):
            self.heading(column, text=headings[index],
                         command=lambda c=column: self.sort_by(c))
            width = widths[index] if widths else 120
            self.column(column, width=width, anchor="w", stretch=True)

    @staticmethod
    def _sort_value(value) -> tuple[int, object]:
        text = str(value)
        try:
            return (0, float(text.replace(",", "")))
        except ValueError:
            return (1, text.lower())

    def set_rows(self, rows: list[tuple]) -> None:
        self._rows = list(rows)
        self._render(self._rows)

    def _render(self, rows: list[tuple]) -> None:
        self.delete(*self.get_children())
        for index, row in enumerate(rows):
            self.insert("", "end", iid=f"r{index}", values=tuple(row))

    def sort_by(self, column: str) -> None:
        columns = list(self["columns"])
        if column not in columns:
            return
        position = columns.index(column)
        reverse = not self._reverse.get(column, False)
        self._reverse[column] = reverse
        self._render(sorted(self._rows,
                            key=lambda row: self._sort_value(row[position]),
                            reverse=reverse))


class ProgressPanel(ttk.Frame):
    """进度条 + 状态文字。"""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self._bar = ttk.Progressbar(self, mode="determinate", maximum=100)
        self._bar.pack(fill="x", side="left", expand=True)
        self._label = ttk.Label(self, text="就绪", width=24, anchor="w")
        self._label.pack(side="left", padx=(8, 0))

    def start(self, total: int) -> None:
        self._bar.configure(maximum=max(total, 1), value=0)
        self._label.configure(text=f"0 / {total}")

    def update(self, done: int, total: int, text: str = "") -> None:
        self._bar.configure(maximum=max(total, 1), value=done)
        self._label.configure(text=text or f"{done} / {total}")

    def finish(self, text: str = "完成") -> None:
        self._bar.configure(value=self._bar["maximum"])
        self._label.configure(text=text)

    def reset(self) -> None:
        self._bar.configure(value=0)
        self._label.configure(text="就绪")


class FilePicker(ttk.Frame):
    """一行输入框 + 浏览按钮。"""

    def __init__(self, parent, mode: str = "file", title: str = "选择",
                 filetypes=None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._title = title
        self._filetypes = filetypes
        self._variable = tk.StringVar()
        entry = ttk.Entry(self, textvariable=self._variable)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(self, text="浏览…", command=self._browse).pack(side="left", padx=(4, 0))

    def _browse(self) -> None:
        if self._mode == "directory":
            chosen = filedialog.askdirectory(title=self._title)
        else:
            chosen = filedialog.asksaveasfilename if self._mode == "save" else \
                filedialog.askopenfilename
            chosen = chosen(title=self._title, filetypes=self._filetypes or [])
        if chosen:
            self._variable.set(chosen)

    def set_path(self, path: str) -> None:
        self._variable.set(path)

    def path(self) -> str:
        return self._variable.get().strip()


def grid_row(parent, row: int, label: str, widget) -> None:
    """两列表单排版助手：左标签、右控件。"""
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w",
                                       padx=(8, 6), pady=3)
    widget.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=3)
    parent.columnconfigure(1, weight=1)
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_widgets.py -v`
预期：PASS（7 passed）

- [ ] **步骤 5：手工冒烟（必须做，测试无法覆盖 Tk 控件渲染）**

运行：

```bash
python -c "import tkinter as tk; from seq_toolkit.gui.widgets import CheckboxTable, ProgressPanel, SortableTable; r=tk.Tk(); t=CheckboxTable(r,['a'],['A']); t.set_rows([('k1','v1'),('k2','v2')]); t.pack(); p=ProgressPanel(r); p.pack(); p.start(10); p.update(5,10,'半程'); s=SortableTable(r,['x','y'],['X','Y']); s.set_rows([('b','2'),('a','1')]); s.pack(); r.update(); r.destroy(); print('控件冒烟通过')"
```

预期：输出 `控件冒烟通过`，无异常。

- [ ] **步骤 6：提交**

```bash
git add seq_toolkit/gui/widgets.py tests/test_gui_widgets.py
git commit -m "feat(gui): 增加表格、勾选、进度与文件选择控件"
```

---

### Task 20：主窗口与日志面板 `gui/app.py`

**文件：**
- 新建：`seq_toolkit/gui/app.py`
- 测试：`tests/test_gui_app.py`

**接口：**
- 依赖输入：`worker`（任务 18）、`widgets`（任务 19）、`applog.RunLog`、`settings.Settings`
- 对外产出：
  - `App(tk.Tk)` —— 属性 `settings`、`log`、`worker`；方法
    - `run_job(target, on_done=None, on_error=None, progress_handler=None) -> bool` —— 已有任务在跑时返回 `False` 并提示；同时禁用所有已注册的忙碌控件
    - `register_busy_widget(widget) -> None` —— 标签页注册"任务运行期间应禁用"的按钮
    - `cancel_job() -> None`
    - `set_status(text: str) -> None`
    - `refresh_log_view() -> None`、`refresh_exception_view() -> None`
    - `save_settings() -> None`
    - `open_tab(index: int) -> None`
  - 标签页注册表 `TAB_SPECS: tuple[tuple[str, object], ...]`（标题, build 函数）—— 后续任务把自己的 `build` 注册进来

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_gui_app.py`：

```python
import time

import pytest

tk = pytest.importorskip("tkinter")

from seq_toolkit.applog import RunLog  # noqa: E402
from seq_toolkit.settings import Settings  # noqa: E402


@pytest.fixture()
def app():
    from seq_toolkit.gui.app import App
    try:
        instance = App(Settings(), start_polling=False)
    except tk.TclError:  # pragma: no cover - 无图形环境时跳过
        pytest.skip("当前环境没有可用的显示，跳过 GUI 测试")
    yield instance
    instance.destroy()


def test_app_has_log_and_worker(app):
    assert isinstance(app.log, RunLog)
    assert app.worker.is_running() is False


def test_run_job_returns_false_when_busy(app):
    app.worker.start(lambda ctx: time.sleep(0.3))
    assert app.run_job(lambda ctx: None) is False
    app.worker.cancel()
    time.sleep(0.35)


def test_log_view_reflects_run_log_entries(app):
    app.log.info("第一条")
    app.log.warn("第二条")
    app.refresh_log_view()
    content = app.log_text.get("1.0", "end")
    assert "第一条" in content and "WARN" in content


def test_refresh_log_view_is_incremental(app):
    app.log.info("A")
    app.refresh_log_view()
    app.log.info("B")
    app.refresh_log_view()
    content = app.log_text.get("1.0", "end")
    assert content.count("A") == 1
    assert content.count("B") == 1


def test_exception_view_lists_rows(app):
    app.log.add_exception("a.fa", 3, ">ON1.1", "物种名缺失", "ON1.1")
    app.refresh_exception_view()
    children = app.exception_table.get_children()
    assert len(children) == 1
    assert "a.fa" in app.exception_table.item(children[0], "values")


def test_set_status_updates_label(app):
    app.set_status("正在下载")
    assert "正在下载" in app.status_label.cget("text")


def test_tabs_are_registered(app):
    titles = [app.notebook.tab(tab, "text") for tab in app.notebook.tabs()]
    assert titles == ["合并 / 转换", "重命名 / 拆分", "检索与批量下载",
                      "按登录号下载", "设置"]
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_app.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'seq_toolkit.gui.app'`

- [ ] **步骤 3：编写最小实现**

新建 `seq_toolkit/gui/app.py`：

```python
"""主窗口：标签页容器、日志面板、状态栏、后台任务消息泵。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from ..applog import RunLog
from ..pipeline import OperationCancelled
from ..settings import Settings, save_settings
from . import tab_accession, tab_merge, tab_rename, tab_search, tab_settings
from .worker import (
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARN,
    MSG_DONE,
    MSG_FAILED,
    MSG_LOG,
    MSG_PROGRESS,
    BackgroundWorker,
)
from .widgets import SortableTable

POLL_INTERVAL_MS = 100

TAB_SPECS = (
    ("合并 / 转换", tab_merge),
    ("重命名 / 拆分", tab_rename),
    ("检索与批量下载", tab_search),
    ("按登录号下载", tab_accession),
    ("设置", tab_settings),
)


class App(tk.Tk):
    def __init__(self, settings: Settings, start_polling: bool = True) -> None:
        super().__init__()
        self.title("序列工具箱 — FASTA / GenBank 合并、转换、命名与 NCBI 下载")
        self.geometry("1120x780")
        self.minsize(940, 660)

        self.settings = settings
        self.log = RunLog()
        self.worker = BackgroundWorker()

        self._progress_handler: Callable[[int, int, str], None] | None = None
        self._on_done: Callable[[object], None] | None = None
        self._on_error: Callable[[BaseException], None] | None = None
        self._log_cursor = 0
        self._busy_widgets: list = []
        self._log_levels = {LEVEL_INFO: self.log.info,
                            LEVEL_WARN: self.log.warn,
                            LEVEL_ERROR: self.log.error}

        self._build_tabs()
        self._build_log_panel()
        self._build_status_bar()

        if start_polling:
            self.after(POLL_INTERVAL_MS, self._poll)

    # ---------- 构建界面 ----------

    def _build_tabs(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        for title, module in TAB_SPECS:
            frame = ttk.Frame(self.notebook)
            self.notebook.add(frame, text=title)
            module.build(frame, self)

    def _build_log_panel(self) -> None:
        panel = ttk.LabelFrame(self, text="日志")
        panel.pack(fill="both", expand=False, padx=8, pady=4)

        inner = ttk.Notebook(panel)
        inner.pack(fill="both", expand=True, padx=4, pady=4)

        log_frame = ttk.Frame(inner)
        inner.add(log_frame, text="运行日志")
        self.log_text = tk.Text(log_frame, height=9, wrap="none")
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical",
                                  command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set, state="disabled")

        exception_frame = ttk.Frame(inner)
        inner.add(exception_frame, text="异常清单")
        columns = ("path", "line", "header", "reason", "final_name")
        headings = ("文件", "行号", "原始 header", "判定原因", "最终采用的名称")
        self.exception_table = SortableTable(exception_frame, columns, headings,
                                             (240, 60, 300, 260, 180))
        self.exception_table.pack(side="left", fill="both", expand=True)
        exception_scroll = ttk.Scrollbar(exception_frame, orient="vertical",
                                         command=self.exception_table.yview)
        exception_scroll.pack(side="right", fill="y")
        self.exception_table.configure(yscrollcommand=exception_scroll.set)

        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(buttons, text="导出日志", command=self._export_log).pack(side="left")
        ttk.Button(buttons, text="导出异常清单 CSV",
                   command=self._export_exceptions).pack(side="left", padx=4)
        ttk.Button(buttons, text="清空日志", command=self._clear_log).pack(side="left")

    def _build_status_bar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        self.status_label = ttk.Label(bar, text="就绪", anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(bar, text="取消", state="disabled",
                                        command=self.cancel_job)
        self.cancel_button.pack(side="right")

    # ---------- 任务调度 ----------

    def run_job(self, target, on_done=None, on_error=None,
                progress_handler=None) -> bool:
        if self.worker.is_running():
            # 用非模态提示而不是 messagebox：模态对话框会阻塞主循环，
            # 也让自动化测试无法继续执行。
            self.log.warn("已有任务正在运行，请先等待完成或点击取消。")
            self.set_status("已有任务正在运行")
            return False
        self._progress_handler = progress_handler
        self._on_done = on_done
        self._on_error = on_error
        self.cancel_button.configure(state="normal")
        for widget in self._busy_widgets:
            widget.configure(state="disabled")
        self.set_status("正在处理…")
        self.worker.start(target)
        return True

    def register_busy_widget(self, widget) -> None:
        """注册"任务运行期间应被禁用"的控件。由标签页在构建时调用。

        这样按钮的禁用/恢复统一由 App 在任务真正结束时处理，标签页无需自己
        猜测何时恢复——避免出现"任务还在跑但按钮已可点"的时序漏洞。
        """
        self._busy_widgets.append(widget)

    def cancel_job(self) -> None:
        if self.worker.is_running():
            self.worker.cancel()
            self.set_status("正在取消…")

    def _poll(self) -> None:
        try:
            self._drain()
        finally:
            self.after(POLL_INTERVAL_MS, self._poll)

    def _drain(self) -> None:
        for message in self.worker.drain():
            if message.kind == MSG_PROGRESS:
                done, total, text = message.payload
                if self._progress_handler is not None:
                    self._progress_handler(done, total, text)
                self.set_status(text or f"{done} / {total}")
            elif message.kind == MSG_LOG:
                level, text = message.payload
                self._log_levels.get(level, self.log.info)(text)
                self.refresh_log_view()
            elif message.kind == MSG_DONE:
                self._finish()
                handler = self._on_done
                self._on_done = None
                if handler is not None:
                    handler(message.payload)
            elif message.kind == MSG_FAILED:
                self._finish()
                handler = self._on_error
                self._on_error = None
                error = message.payload
                if isinstance(error, OperationCancelled):
                    self.log.warn("操作已取消")
                    self.set_status("已取消")
                elif handler is not None:
                    handler(error)
                else:
                    self.log.error(f"任务失败: {error}")
                    messagebox.showerror("任务失败", str(error))
            self.refresh_log_view()
            self.refresh_exception_view()

    def _finish(self) -> None:
        self.cancel_button.configure(state="disabled")
        for widget in self._busy_widgets:
            widget.configure(state="normal")
        self._progress_handler = None
        if self.status_label.cget("text") == "正在处理…":
            self.set_status("就绪")

    # ---------- 视图刷新 ----------

    def set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def refresh_log_view(self) -> None:
        entries = self.log.entries
        if len(entries) == self._log_cursor:
            return
        self.log_text.configure(state="normal")
        for entry in entries[self._log_cursor:]:
            self.log_text.insert("end", f"[{entry.level}] {entry.message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self._log_cursor = len(entries)

    def refresh_exception_view(self) -> None:
        self.exception_table.set_rows([
            (entry.path, entry.line, entry.header, entry.reason, entry.final_name)
            for entry in self.log.exceptions
        ])

    def _clear_log(self) -> None:
        self.log.clear()
        self._log_cursor = 0
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.refresh_exception_view()

    def _export_log(self) -> None:
        from tkinter import filedialog
        target = filedialog.asksaveasfilename(defaultextension=".log",
                                              filetypes=[("日志文件", "*.log")])
        if target:
            self.log.export_log(target)
            self.log.info(f"日志已导出到 {target}")

    def _export_exceptions(self) -> None:
        from tkinter import filedialog
        target = filedialog.asksaveasfilename(defaultextension=".csv",
                                              filetypes=[("CSV 文件", "*.csv")])
        if target:
            self.log.export_exceptions_csv(target)
            self.log.info(f"异常清单已导出到 {target}")

    def open_tab(self, index: int) -> None:
        self.notebook.select(index)

    def save_settings(self) -> None:
        path = save_settings(self.settings)
        self.log.info(f"设置已保存到 {path}")
```

> **本任务需要 5 个标签页模块都存在**，否则 `from . import tab_accession, ...` 会失败。执行顺序：先按下面任务 21 的代码创建**全部 5 个标签页模块的最小可运行版本**（每个模块只实现 `build(parent, app)` 并放一个占位 Label），跑通本任务测试后再逐个填充。为避免这一顺序陷阱，也可以在每个标签页模块降级处理：

```python
# seq_toolkit/gui/tab_merge.py 等 5 个文件，本任务先写这个最小版本
from __future__ import annotations

from tkinter import ttk

TITLE = "合并 / 转换"


def build(parent: ttk.Frame, app) -> ttk.Frame:
    ttk.Label(parent, text=f"{TITLE}（待实现）").pack(padx=12, pady=12)
    return parent
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_app.py -v`
预期：PASS（7 passed）

- [ ] **步骤 5：手工冒烟**

运行：`python -c "from seq_toolkit.gui.app import App; from seq_toolkit.settings import Settings; app=App(Settings()); app.after(600, app.destroy); app.mainloop(); print('主窗口冒烟通过')"`
预期：窗口一闪而过，输出 `主窗口冒烟通过`

- [ ] **步骤 6：提交**

```bash
git add seq_toolkit/gui/app.py seq_toolkit/gui/tab_*.py tests/test_gui_app.py
git commit -m "feat(gui): 增加主窗口、日志面板与后台任务消息泵"
```

---

### Task 21：合并 / 转换标签页 `gui/tab_merge.py`

**文件：**
- 修改：`seq_toolkit/gui/tab_merge.py`（替换占位实现）
- 测试：`tests/test_gui_tabs.py`

**接口：**
- 依赖输入：`App.run_job`（任务 20）、`pipeline.ProcessPlan` / `run_merge`、`widgets.ProgressPanel`
- 对外产出：`build(parent: ttk.Frame, app) -> ttk.Frame`；模块常量 `TITLE`、`FORMAT_LABELS`、`NAMING_LABELS`、`DEDUP_LABELS`

- [ ] **步骤 1：编写失败的测试**

新建 `tests/test_gui_tabs.py`：

```python
import pytest

pytest.importorskip("tkinter")

from seq_toolkit.settings import Settings  # noqa: E402


@pytest.fixture()
def app():
    from seq_toolkit.gui.app import App
    try:
        instance = App(Settings(), start_polling=False)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"无可用显示: {exc}")
    yield instance
    instance.destroy()


def test_merge_tab_exposes_expected_labels():
    from seq_toolkit.gui import tab_merge
    assert tab_merge.TITLE == "合并 / 转换"
    assert tab_merge.FORMAT_LABELS["auto"] == "自动识别"
    assert set(tab_merge.NAMING_LABELS) == {
        "keep", "accession", "species", "accession_species"}
    assert set(tab_merge.DEDUP_LABELS) == {"accession", "none"}


def test_merge_tab_builds_without_error(app):
    from seq_toolkit.gui import tab_merge
    frame = tab_merge.build(app.notebook.winfo_children()[0], app)
    assert frame is not None
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tabs.py -v`
预期：FAIL，`AttributeError: module 'seq_toolkit.gui.tab_merge' has no attribute 'FORMAT_LABELS'`

- [ ] **步骤 3：编写最小实现**

用以下内容替换 `seq_toolkit/gui/tab_merge.py` 的全部内容：

```python
"""① 合并 / 转换：把"合并 FASTA""合并 GenBank""GenBank 转 FASTA"做成一件事。"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk

from ..pipeline import ProcessPlan, run_merge
from .widgets import FilePicker, ProgressPanel, grid_row

TITLE = "合并 / 转换"
FORMAT_LABELS = {"auto": "自动识别", "fasta": "强制 FASTA", "genbank": "强制 GenBank"}
NAMING_LABELS = {
    "keep": "不改名（保留原始序列名）",
    "accession": "登录号",
    "species": "物种名",
    "accession_species": "登录号_物种名",
}
DEDUP_LABELS = {"accession": "按登录号去重", "none": "不去重"}
OUTPUT_LABELS = {"fasta": "FASTA", "genbank": "GenBank"}


def _label_to_key(labels: dict, text: str) -> str:
    for key, value in labels.items():
        if value == text:
            return key
    raise KeyError(text)


def build(parent: ttk.Frame, app) -> ttk.Frame:
    inputs: list[str] = []

    # ---------- 输入 ----------
    input_box = ttk.LabelFrame(parent, text="输入文件与文件夹")
    input_box.pack(fill="both", expand=False, padx=8, pady=(8, 4))

    listing = tk.Listbox(input_box, height=6, selectmode="extended")
    listing.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
    scroll = ttk.Scrollbar(input_box, orient="vertical", command=listing.yview)
    scroll.pack(side="left", fill="y", pady=6)
    listing.configure(yscrollcommand=scroll.set)

    side = ttk.Frame(input_box)
    side.pack(side="left", fill="y", padx=6, pady=6)
    recursive = tk.BooleanVar(value=True)

    def refresh_listing() -> None:
        listing.delete(0, "end")
        for path in inputs:
            listing.insert("end", path)

    def add_files() -> None:
        chosen = filedialog.askopenfilenames(title="选择序列文件")
        if chosen:
            inputs.extend(str(p) for p in chosen)
            refresh_listing()

    def add_folder() -> None:
        chosen = filedialog.askdirectory(title="选择文件夹")
        if chosen:
            inputs.append(chosen)
            refresh_listing()

    def remove_selected() -> None:
        for index in sorted(listing.curselection(), reverse=True):
            del inputs[index]
        refresh_listing()

    def clear_all() -> None:
        inputs.clear()
        refresh_listing()

    ttk.Button(side, text="添加文件…", command=add_files).pack(fill="x", pady=2)
    ttk.Button(side, text="添加文件夹…", command=add_folder).pack(fill="x", pady=2)
    ttk.Button(side, text="移除选中", command=remove_selected).pack(fill="x", pady=2)
    ttk.Button(side, text="清空", command=clear_all).pack(fill="x", pady=2)
    ttk.Checkbutton(side, text="含子文件夹", variable=recursive).pack(fill="x", pady=(6, 2))

    # ---------- 选项 ----------
    options = ttk.LabelFrame(parent, text="处理选项")
    options.pack(fill="x", padx=8, pady=4)

    input_format = tk.StringVar(value=FORMAT_LABELS["auto"])
    row = ttk.Frame(options)
    grid_row(options, 0, "输入类型", row)
    for key, text in FORMAT_LABELS.items():
        ttk.Radiobutton(row, text=text, value=text,
                        variable=input_format).pack(side="left", padx=(0, 10))

    output_format = tk.StringVar(value=OUTPUT_LABELS["fasta"])
    row = ttk.Frame(options)
    grid_row(options, 1, "输出格式", row)
    for key, text in OUTPUT_LABELS.items():
        ttk.Radiobutton(row, text=text, value=text,
                        variable=output_format).pack(side="left", padx=(0, 10))

    naming = tk.StringVar(value=NAMING_LABELS["keep"])
    combo = ttk.Combobox(options, textvariable=naming, state="readonly",
                         values=list(NAMING_LABELS.values()))
    grid_row(options, 2, "命名规则", combo)

    dedup = tk.StringVar(value=DEDUP_LABELS["accession"])
    combo = ttk.Combobox(options, textvariable=dedup, state="readonly",
                         values=list(DEDUP_LABELS.values()))
    grid_row(options, 3, "重复序列", combo)

    output_picker = FilePicker(options, mode="save", title="选择输出文件",
                               filetypes=[("序列文件", "*.fasta *.fa *.gb *.gbk"),
                                          ("全部文件", "*.*")])
    grid_row(options, 4, "输出文件", output_picker)

    wrap = tk.IntVar(value=app.settings.wrap)
    row = ttk.Frame(options)
    grid_row(options, 5, "FASTA 换行", row)
    ttk.Radiobutton(row, text="不换行", value=0, variable=wrap).pack(side="left")
    for width in (60, 70, 80):
        ttk.Radiobutton(row, text=str(width), value=width,
                        variable=wrap).pack(side="left", padx=(8, 0))

    # ---------- 执行 ----------
    action = ttk.Frame(parent)
    action.pack(fill="x", padx=8, pady=(4, 8))
    progress = ProgressPanel(action)
    progress.pack(side="left", fill="x", expand=True)
    start_button = ttk.Button(action, text="开始处理")

    def on_progress(done: int, total: int, text: str) -> None:
        progress.update(done, total, text)

    def on_done(result) -> None:
        progress.finish(f"完成：写出 {result.records_out} 条")
        app.log.info(f"输出文件：{result.output_path}")
        app.set_status(f"完成，输出 {result.output_path}")

    def on_error(error: BaseException) -> None:
        progress.reset()
        app.log.error(f"处理失败: {error}")

    def start() -> None:
        if not inputs:
            app.log.warn("请先添加输入文件或文件夹")
            return
        target = output_picker.path()
        if not target:
            app.log.warn("请先指定输出文件")
            return
        plan = ProcessPlan(
            inputs=list(inputs),
            output_path=target,
            output_format=_label_to_key(OUTPUT_LABELS, output_format.get()),
            input_format=_label_to_key(FORMAT_LABELS, input_format.get()),
            naming_mode=_label_to_key(NAMING_LABELS, naming.get()),
            dedup=_label_to_key(DEDUP_LABELS, dedup.get()),
            recursive=recursive.get(),
            wrap=wrap.get(),
            fasta_suffixes=app.settings.fasta_suffixes,
            genbank_suffixes=app.settings.genbank_suffixes,
            log=app.log,
            progress=on_progress,
        )

        def job(ctx):
            plan.cancel = ctx.cancel_event
            ctx.progress(0, max(len(inputs), 1), "开始读取")
            return run_merge(plan)

        if not app.run_job(job, on_done=on_done, on_error=on_error,
                           progress_handler=on_progress):
            return

    start_button.configure(command=start)
    start_button.pack(side="right")
    app.register_busy_widget(start_button)
    return parent
```

> 注意三处细节，它们都是容易踩的坑：
> 1. `fasta_suffixes` / `genbank_suffixes` 必须来自 `app.settings`，否则「设置」里自定义的后缀名不会生效。
> 2. 进度条的 `start()` **只能由主线程的 `on_progress` 调用**（见下），后台的 `job(ctx)` 只通过 `ctx.progress` 上报。
> 3. 按钮的禁用与恢复交给 `app.register_busy_widget(start_button)`，**不要**自己写 `app.after(200, ...)` 恢复——那会让按钮在任务仍在运行时就被重新点开。

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tabs.py -v`
预期：PASS（2 passed）

- [ ] **步骤 5：手工验收**

```bash
python -c "from seq_toolkit.gui.app import App; from seq_toolkit.settings import Settings; app=App(Settings()); app.after(800, app.destroy); app.mainloop(); print('OK')"
```
预期：能看到"合并 / 转换"面板包含输入列表、四个按钮、含子文件夹勾选、输入类型/输出格式单选、命名规则与重复序列下拉、输出文件选择、换行选项与进度条。

- [ ] **步骤 6：提交**

```bash
git add seq_toolkit/gui/tab_merge.py tests/test_gui_tabs.py
git commit -m "feat(gui): 实现合并与转换标签页"
```

---

### Task 22：重命名 / 拆分标签页 `gui/tab_rename.py`

**文件：**
- 修改：`seq_toolkit/gui/tab_rename.py`（替换占位实现）
- 修改：`tests/test_gui_tabs.py`（追加测试）

**接口：**
- 依赖输入：`App.run_job`、`pipeline.run_merge` / `split_records` / `rename_disk_files`、`widgets.ProgressPanel`
- 对外产出：`build(parent, app) -> ttk.Frame`；模块常量 `TITLE`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gui_tabs.py` 末尾追加：

```python
def test_rename_tab_builds_without_error(app):
    from seq_toolkit.gui import tab_rename
    assert tab_rename.TITLE == "重命名 / 拆分"
    frame = tab_rename.build(app.notebook.winfo_children()[1], app)
    assert frame is not None
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tabs.py::test_rename_tab_builds_without_error -v`
预期：FAIL，`AttributeError: module 'seq_toolkit.gui.tab_rename' has no attribute 'TITLE'`（当前为占位实现时 TITLE 存在但内容为"合并 / 转换"，同样应失败）

- [ ] **步骤 3：编写最小实现**

用以下内容替换 `seq_toolkit/gui/tab_rename.py` 的全部内容：

```python
"""② 重命名 / 拆分：改 `>` 行序列名、按序列名拆成单文件、重命名磁盘文件。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..fasta_io import read_fasta
from ..format_detect import detect_format, list_input_files
from ..genbank_io import read_genbank
from ..pipeline import ProcessPlan, rename_disk_files, run_merge, split_records
from .tab_merge import NAMING_LABELS, _label_to_key
from .widgets import FilePicker, ProgressPanel, grid_row

TITLE = "重命名 / 拆分"


def build(parent: ttk.Frame, app) -> ttk.Frame:
    inputs: list[str] = []

    source_box = ttk.LabelFrame(parent, text="源文件与文件夹")
    source_box.pack(fill="both", expand=False, padx=8, pady=(8, 4))
    listing = tk.Listbox(source_box, height=6, selectmode="extended")
    listing.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
    scroll = ttk.Scrollbar(source_box, orient="vertical", command=listing.yview)
    scroll.pack(side="left", fill="y", pady=6)
    listing.configure(yscrollcommand=scroll.set)

    side = ttk.Frame(source_box)
    side.pack(side="left", fill="y", padx=6, pady=6)
    recursive = tk.BooleanVar(value=True)

    def refresh_listing() -> None:
        listing.delete(0, "end")
        for path in inputs:
            listing.insert("end", path)

    def add_files() -> None:
        chosen = filedialog.askopenfilenames(title="选择序列文件")
        if chosen:
            inputs.extend(str(p) for p in chosen)
            refresh_listing()

    def add_folder() -> None:
        chosen = filedialog.askdirectory(title="选择文件夹")
        if chosen:
            inputs.append(chosen)
            refresh_listing()

    def clear_all() -> None:
        inputs.clear()
        refresh_listing()

    ttk.Button(side, text="添加文件…", command=add_files).pack(fill="x", pady=2)
    ttk.Button(side, text="添加文件夹…", command=add_folder).pack(fill="x", pady=2)
    ttk.Button(side, text="清空", command=clear_all).pack(fill="x", pady=2)
    ttk.Checkbutton(side, text="含子文件夹", variable=recursive).pack(fill="x", pady=(6, 2))

    options = ttk.LabelFrame(parent, text="操作（可任意组合）")
    options.pack(fill="x", padx=8, pady=4)

    naming = tk.StringVar(value=NAMING_LABELS["accession_species"])
    combo = ttk.Combobox(options, textvariable=naming, state="readonly",
                         values=list(NAMING_LABELS.values()))
    grid_row(options, 0, "命名规则", combo)

    rewrite_headers = tk.BooleanVar(value=True)
    split_files = tk.BooleanVar(value=False)
    rename_disk = tk.BooleanVar(value=False)
    row = ttk.Frame(options)
    grid_row(options, 1, "操作", row)
    ttk.Checkbutton(row, text="改写 > 行序列名", variable=rewrite_headers).pack(side="left")
    ttk.Checkbutton(row, text="按序列名拆分为单文件",
                    variable=split_files).pack(side="left", padx=(10, 0))
    ttk.Checkbutton(row, text="重命名已有磁盘文件",
                    variable=rename_disk).pack(side="left", padx=(10, 0))

    rewritten_picker = FilePicker(options, mode="save", title="改写后的输出文件",
                                  filetypes=[("序列文件", "*.fasta *.fa *.gb *.gbk")])
    grid_row(options, 2, "输出文件", rewritten_picker)

    split_dir_picker = FilePicker(options, mode="directory", title="拆分输出文件夹")
    grid_row(options, 3, "拆分输出目录", split_dir_picker)

    output_format = tk.StringVar(value="fasta")
    row = ttk.Frame(options)
    grid_row(options, 4, "输出格式", row)
    ttk.Radiobutton(row, text="FASTA", value="fasta",
                    variable=output_format).pack(side="left")
    ttk.Radiobutton(row, text="GenBank", value="genbank",
                    variable=output_format).pack(side="left", padx=(10, 0))

    action = ttk.Frame(parent)
    action.pack(fill="x", padx=8, pady=(4, 8))
    progress = ProgressPanel(action)
    progress.pack(side="left", fill="x", expand=True)
    preview_button = ttk.Button(action, text="预览改名对照表")
    start_button = ttk.Button(action, text="开始处理")

    def on_progress(done: int, total: int, text: str) -> None:
        if done == 0:
            progress.start(total)
        progress.update(done, total, text)

    def run_preview() -> None:
        if not inputs:
            app.log.warn("请先添加源文件或文件夹")
            return

        def show_preview(plan) -> None:
            if not plan.pairs:
                messagebox.showinfo("预览", "没有可改名的文件。")
                return
            lines = [f"{old}\n  → {new}" for old, new in plan.pairs[:50]]
            if len(plan.pairs) > 50:
                lines.append(f"…… 其余 {len(plan.pairs) - 50} 个文件省略")
            messagebox.showinfo("改名预览（尚未执行）", "\n\n".join(lines))

        def job(ctx):
            # 预览要读每个文件的头部，文件多时同样会阻塞界面，因此也走后台线程
            return rename_disk_files(
                list(inputs),
                naming_mode=_label_to_key(NAMING_LABELS, naming.get()),
                recursive=recursive.get(),
                dry_run=True,
                log=app.log,
            )

        app.run_job(job, on_done=show_preview,
                    on_error=lambda e: app.log.error(f"预览失败: {e}"))

    def on_done(summary: str) -> None:
        progress.finish("完成")
        app.set_status(summary)

    def on_error(error: BaseException) -> None:
        progress.reset()
        app.log.error(f"处理失败: {error}")

    def start() -> None:
        if not inputs:
            app.log.warn("请先添加源文件或文件夹")
            return
        mode = _label_to_key(NAMING_LABELS, naming.get())
        want_rewrite = rewrite_headers.get()
        want_split = split_files.get()
        want_disk = rename_disk.get()
        target = rewritten_picker.path()
        split_dir = split_dir_picker.path()

        if want_rewrite and not target:
            app.log.warn("勾选「改写 > 行序列名」时必须指定输出文件")
            return
        if want_split and not split_dir:
            app.log.warn("勾选「按序列名拆分为单文件」时必须指定拆分输出目录")
            return

        def job(ctx):
            parts: list[str] = []
            if want_rewrite:
                ctx.progress(0, 2, "改写序列名")
                result = run_merge(ProcessPlan(
                    inputs=list(inputs), output_path=target,
                    output_format=output_format.get(), input_format="auto",
                    naming_mode=mode, dedup="accession",
                    recursive=recursive.get(), log=app.log,
                    progress=None, cancel=ctx.cancel_event,
                ))
                parts.append(f"改写 {result.records_out} 条 → {result.output_path}")

            if want_disk:
                ctx.progress(1, 2, "重命名磁盘文件")
                plan = rename_disk_files(list(inputs), naming_mode=mode,
                                         recursive=recursive.get(), dry_run=False,
                                         log=app.log)
                parts.append(f"磁盘改名 {plan.renamed} 个文件")

            if want_split:
                ctx.progress(1, 2, "拆分序列")
                files = list_input_files(
                    list(inputs), recursive=recursive.get(),
                    fasta_suffixes=app.settings.fasta_suffixes,
                    genbank_suffixes=app.settings.genbank_suffixes)
                records = []
                for path in files:
                    fmt = detect_format(path)
                    if fmt == "genbank":
                        records.extend(read_genbank(path))
                    elif fmt == "fasta":
                        records.extend(read_fasta(path))
                split_records(records, split_dir, naming_mode=mode,
                              output_format=output_format.get(), log=app.log)
                parts.append(f"拆分出 {len(records)} 个文件 → {split_dir}")

            return "；".join(parts) if parts else "未选择任何操作"

        if not app.run_job(job, on_done=on_done, on_error=on_error,
                           progress_handler=on_progress):
            return

    preview_button.configure(command=run_preview)
    preview_button.pack(side="right", padx=(0, 6))
    start_button.configure(command=start)
    start_button.pack(side="right")
    app.register_busy_widget(start_button)
    return parent
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tabs.py -v`
预期：PASS（3 passed）

- [ ] **步骤 5：手工验收**

准备一个内容为 `>ON929859.1 Salsola pellucida chloroplast, complete genome` 的 `乱名.fa`，勾选"重命名已有磁盘文件"与"改写 > 行序列名"，点"预览改名对照表"应看到 `乱名.fa → ON929859.1_Salsola_pellucida.fa`，且此时磁盘文件名**未变**；点"开始处理"后文件名才真正改变。

- [ ] **步骤 6：提交**

```bash
git add seq_toolkit/gui/tab_rename.py tests/test_gui_tabs.py
git commit -m "feat(gui): 实现重命名与拆分标签页"
```

---

### Task 23：检索与批量下载标签页 `gui/tab_search.py`

**文件：**
- 修改：`seq_toolkit/gui/tab_search.py`（替换占位实现）
- 修改：`tests/test_gui_tabs.py`（追加测试）

**接口：**
- 依赖输入：`App.run_job`、`ncbi.NcbiClient` / `DownloadOptions`、`widgets.CheckboxTable` / `ProgressPanel`
- 对外产出：`build(parent, app) -> ttk.Frame`；模块常量 `TITLE`、`RESULT_HEADINGS`、`MAX_DISPLAY_ROWS = 5000`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gui_tabs.py` 末尾追加：

```python
def test_search_tab_builds_without_error(app):
    from seq_toolkit.gui import tab_search
    assert tab_search.TITLE == "检索与批量下载"
    assert tab_search.MAX_DISPLAY_ROWS == 5000
    assert tab_search.RESULT_HEADINGS == ("Accession", "长度", "物种名",
                                          "定义行", "发布日期", "来源")
    frame = tab_search.build(app.notebook.winfo_children()[2], app)
    assert frame is not None
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tabs.py::test_search_tab_builds_without_error -v`
预期：FAIL，`AttributeError: module 'seq_toolkit.gui.tab_search' has no attribute 'MAX_DISPLAY_ROWS'`

- [ ] **步骤 3：编写最小实现**

用以下内容替换 `seq_toolkit/gui/tab_search.py` 的全部内容：

```python
"""③ 检索与批量下载：按物种名/属名检索 nuccore，勾选后批量下载。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..ncbi import DownloadOptions, NcbiClient
from .tab_merge import NAMING_LABELS, _label_to_key
from .widgets import CheckboxTable, FilePicker, ProgressPanel, grid_row

TITLE = "检索与批量下载"
RESULT_HEADINGS = ("Accession", "长度", "物种名", "定义行", "发布日期", "来源")
MAX_DISPLAY_ROWS = 5000
SCOPE_LABELS = {"species": "物种名", "genus": "属名"}


def _make_client(app, cancel_event) -> NcbiClient:
    return NcbiClient(
        email=app.settings.email,
        api_key=app.settings.api_key,
        proxy=app.settings.proxy,
        log=app.log,
        cancel=cancel_event,
    )


def build(parent: ttk.Frame, app) -> ttk.Frame:
    criteria = ttk.LabelFrame(parent, text="检索条件")
    criteria.pack(fill="x", padx=8, pady=(8, 4))

    term = tk.StringVar()
    entry = ttk.Entry(criteria, textvariable=term)
    grid_row(criteria, 0, "检索词", entry)

    scope = tk.StringVar(value=SCOPE_LABELS["species"])
    row = ttk.Frame(criteria)
    grid_row(criteria, 1, "检索范围", row)
    for key, text in SCOPE_LABELS.items():
        ttk.Radiobutton(row, text=text, value=text,
                        variable=scope).pack(side="left", padx=(0, 12))

    minimum = tk.StringVar(value="100000")
    maximum = tk.StringVar(value="200000")
    row = ttk.Frame(criteria)
    grid_row(criteria, 2, "序列长度 (bp)", row)
    ttk.Label(row, text="下限").pack(side="left")
    ttk.Entry(row, textvariable=minimum, width=12).pack(side="left", padx=4)
    ttk.Label(row, text="上限").pack(side="left")
    ttk.Entry(row, textvariable=maximum, width=12).pack(side="left", padx=4)

    complete_only = tk.BooleanVar(value=True)
    refseq_only = tk.BooleanVar(value=False)
    row = ttk.Frame(criteria)
    grid_row(criteria, 3, "筛选", row)
    ttk.Checkbutton(row, text="只要完整基因组",
                    variable=complete_only).pack(side="left")
    ttk.Checkbutton(row, text="只要 RefSeq",
                    variable=refseq_only).pack(side="left", padx=(12, 0))

    search_button = ttk.Button(criteria, text="检索")
    grid_row(criteria, 4, "", search_button)

    results_box = ttk.LabelFrame(parent, text="检索结果")
    results_box.pack(fill="both", expand=True, padx=8, pady=4)
    table = CheckboxTable(results_box, ("accession", "length", "organism",
                                        "definition", "date", "source"),
                          RESULT_HEADINGS, (130, 90, 190, 420, 100, 90))
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
    ttk.Button(selection_bar, text="清空勾选",
               command=lambda: (table.selection.uncheck_all(),
                                table.refresh_checks())).pack(side="left")
    counter.pack(side="left", padx=12)

    download_box = ttk.LabelFrame(parent, text="下载选项")
    download_box.pack(fill="x", padx=8, pady=4)

    want_fasta = tk.BooleanVar(value=True)
    want_genbank = tk.BooleanVar(value=True)
    per_sequence = tk.BooleanVar(value=True)
    merged = tk.BooleanVar(value=True)
    row = ttk.Frame(download_box)
    grid_row(download_box, 0, "产物", row)
    ttk.Checkbutton(row, text="FASTA", variable=want_fasta).pack(side="left")
    ttk.Checkbutton(row, text="GenBank",
                    variable=want_genbank).pack(side="left", padx=(10, 0))
    ttk.Checkbutton(row, text="每序列单文件",
                    variable=per_sequence).pack(side="left", padx=(10, 0))
    ttk.Checkbutton(row, text="同时合并为大文件",
                    variable=merged).pack(side="left", padx=(10, 0))

    naming = tk.StringVar(value=NAMING_LABELS["accession"])
    combo = ttk.Combobox(download_box, textvariable=naming, state="readonly",
                         values=list(NAMING_LABELS.values()))
    grid_row(download_box, 1, "命名规则", combo)

    out_dir = FilePicker(download_box, mode="directory", title="下载输出文件夹")
    out_dir.set_path(app.settings.output_dir)
    grid_row(download_box, 2, "输出文件夹", out_dir)

    action = ttk.Frame(parent)
    action.pack(fill="x", padx=8, pady=(4, 8))
    progress = ProgressPanel(action)
    progress.pack(side="left", fill="x", expand=True)
    download_button = ttk.Button(action, text="下载勾选的序列")

    last_summaries: list = []

    def on_progress(done: int, total: int, text: str) -> None:
        if done == 0:
            progress.start(total)
        progress.update(done, total, text)

    def on_search_done(payload) -> None:
        result, summaries = payload
        # 表格行以 accession 作为唯一 iid，若出现重复 accession 会导致 TclError，
        # 因此展示前先按 accession 去重并保持原有顺序。
        seen: set[str] = set()
        unique = []
        for summary in summaries:
            if summary.accession and summary.accession not in seen:
                seen.add(summary.accession)
                unique.append(summary)
        last_summaries.clear()
        last_summaries.extend(unique)
        shown = unique[:MAX_DISPLAY_ROWS]
        table.set_rows([
            (s.accession, f"{s.length:,}", s.organism, s.definition,
             s.date, s.source_db) for s in shown
        ])
        update_counter()
        progress.finish(f"命中 {result.total} 条，筛后 {len(unique)} 条")
        if len(unique) > MAX_DISPLAY_ROWS:
            app.log.warn(f"结果过多，界面只显示前 {MAX_DISPLAY_ROWS} 条；"
                         f"请用长度区间或「只要完整基因组」缩小范围")
        app.set_status(f"检索完成：命中 {result.total} 条，筛选后 {len(unique)} 条")

    def do_search() -> None:
        text = term.get().strip()
        if not text:
            app.log.warn("请输入检索词")
            return
        if not app.settings.email:
            app.log.warn("请先在「设置」中填写 NCBI 邮箱（NCBI 的合规要求）")
            app.open_tab(4)
            return
        try:
            min_length = int(minimum.get()) if minimum.get().strip() else None
            max_length = int(maximum.get()) if maximum.get().strip() else None
        except ValueError:
            app.log.warn("长度区间必须是整数")
            return

        def job(ctx):
            client = _make_client(app, ctx.cancel_event)
            ctx.progress(0, 1, "正在检索")
            return client.search_summaries(
                text,
                scope=_label_to_key(SCOPE_LABELS, scope.get()),
                min_length=min_length,
                max_length=max_length,
                complete_genome_only=complete_only.get(),
                refseq_only_local=refseq_only.get(),
            )

        app.run_job(job, on_done=on_search_done,
                    on_error=lambda e: (progress.reset(),
                                        app.log.error(f"检索失败: {e}")))

    def on_download_done(report) -> None:
        progress.finish(f"成功 {report.succeeded} / 跳过 {report.skipped} / "
                        f"失败 {report.failed}")
        messagebox.showinfo(
            "下载完成",
            f"成功 {report.succeeded} 条，跳过 {report.skipped} 条，"
            f"失败 {report.failed} 条。\n输出目录：{report.out_dir}")

    def do_download() -> None:
        chosen = table.selection.checked_keys()
        if not chosen:
            app.log.warn("请先在结果表格中勾选要下载的序列")
            return
        target_dir = out_dir.path()
        if not target_dir:
            app.log.warn("请指定下载输出文件夹")
            return
        options = DownloadOptions(
            out_dir=target_dir,
            want_fasta=want_fasta.get(),
            want_genbank=want_genbank.get(),
            per_sequence_files=per_sequence.get(),
            merged_files=merged.get(),
            naming_mode=_label_to_key(NAMING_LABELS, naming.get()),
            force_redownload=app.settings.force_redownload,
            wrap=app.settings.wrap,
        )

        def job(ctx):
            client = _make_client(app, ctx.cancel_event)
            return client.download(chosen, options, progress=ctx.progress)

        app.run_job(job, on_done=on_download_done,
                    on_error=lambda e: (progress.reset(),
                                        app.log.error(f"下载失败: {e}")),
                    progress_handler=on_progress)

    search_button.configure(command=do_search)
    download_button.configure(command=do_download)
    download_button.pack(side="right")
    app.register_busy_widget(search_button)
    app.register_busy_widget(download_button)
    return parent
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tabs.py -v`
预期：PASS（4 passed）

- [ ] **步骤 5：手工验收（需要网络）**

在"设置"里填好邮箱后，检索词填 `Salsola`、范围选"属名"、长度 100000–200000、勾选"只要完整基因组"，点检索。预期结果表格出现若干行，长度列在区间内，定义行都含 `complete genome`。勾选 3 条后点下载，输出文件夹应出现 3 个 `.gb` + 3 个 `.fa` + `all_sequences.fasta` + `all_sequences.gb`。

- [ ] **步骤 6：提交**

```bash
git add seq_toolkit/gui/tab_search.py tests/test_gui_tabs.py
git commit -m "feat(gui): 实现检索与批量下载标签页"
```

---

### Task 24：按登录号下载标签页 `gui/tab_accession.py`

**文件：**
- 修改：`seq_toolkit/gui/tab_accession.py`（替换占位实现）
- 修改：`seq_toolkit/ncbi.py`（追加登录号输入解析）
- 修改：`tests/test_ncbi.py`、`tests/test_gui_tabs.py`（追加测试）

**接口：**
- 依赖输入：`App.run_job`、`ncbi.NcbiClient`、`format_detect.list_input_files`、`fasta_io.read_fasta`、`genbank_io.read_genbank`
- 对外产出：
  - `parse_accession_text(text: str) -> list[str]` —— 按空白/逗号/分号切分，转大写，去重且保持出现顺序
  - `collect_accessions_from_files(paths, recursive=True) -> list[str]` —— 从已有 FASTA/GenBank 文件中提取登录号，去重且保持顺序
  - `build(parent, app) -> ttk.Frame`；模块常量 `TITLE`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_ncbi.py` 末尾追加：

```python
from seq_toolkit.ncbi import collect_accessions_from_files, parse_accession_text


def test_parse_accession_text_splits_on_whitespace_and_punctuation():
    assert parse_accession_text("ON1.1, MF2.1\nKX3.1;AB4.1") == [
        "ON1.1", "MF2.1", "KX3.1", "AB4.1"]


def test_parse_accession_text_uppercases_and_deduplicates():
    assert parse_accession_text("on1.1 ON1.1  on1.1") == ["ON1.1"]


def test_parse_accession_text_ignores_blank_input():
    assert parse_accession_text("   \n  ,, ") == []


def test_collect_accessions_from_files_reads_fasta_and_genbank(tmp_path):
    fasta = tmp_path / "a.fa"
    fasta.write_text(">ON1.1 Salsola pellucida\nACGT\n>MF2.1 Kochia scoparia\nTTTT\n",
                     encoding="utf-8")
    genbank = tmp_path / "b.gb"
    genbank.write_text(GENBANK_TWO, encoding="utf-8")
    found = collect_accessions_from_files([str(fasta), str(genbank)])
    assert found == ["ON1.1", "MF2.1"]


def test_collect_accessions_from_files_deduplicates(tmp_path):
    fasta = tmp_path / "a.fa"
    fasta.write_text(">ON1.1 Salsola pellucida\nACGT\n", encoding="utf-8")
    twice = collect_accessions_from_files([str(fasta), str(fasta)])
    assert twice == ["ON1.1"]
```

在 `tests/test_gui_tabs.py` 末尾追加：

```python
def test_accession_tab_builds_without_error(app):
    from seq_toolkit.gui import tab_accession
    assert tab_accession.TITLE == "按登录号下载"
    frame = tab_accession.build(app.notebook.winfo_children()[3], app)
    assert frame is not None
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_ncbi.py tests/test_gui_tabs.py -v`
预期：FAIL，`ImportError: cannot import name 'collect_accessions_from_files'`

- [ ] **步骤 3：在 `ncbi.py` 追加登录号解析**

在 `seq_toolkit/ncbi.py` 顶部 import 区补上：

```python
import re

from .format_detect import detect_format, list_input_files
```

在 `build_query` 之前追加：

```python
_ACCESSION_SPLITTER = re.compile(r"[\s,;]+")


def parse_accession_text(text: str) -> list[str]:
    """把粘贴的文本切成登录号列表：转大写、去重、保持出现顺序。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for chunk in _ACCESSION_SPLITTER.split(text or ""):
        token = chunk.strip().upper()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def collect_accessions_from_files(paths, recursive: bool = True) -> list[str]:
    """从已有的 FASTA / GenBank 文件中提取登录号，去重并保持顺序。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for path in list_input_files(paths, recursive=recursive):
        detected = detect_format(path)
        try:
            if detected == "genbank":
                records = read_genbank(path)
            elif detected == "fasta":
                records = read_fasta(path)
            else:
                continue
            for record in records:
                if record.accession and record.accession not in seen:
                    seen.add(record.accession)
                    ordered.append(record.accession)
        except SeqToolkitError:
            continue
    return ordered
```

- [ ] **步骤 4：编写标签页实现**

用以下内容替换 `seq_toolkit/gui/tab_accession.py` 的全部内容：

```python
"""④ 按登录号下载：粘贴、读文件、或从已有序列文件里自动提取登录号。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..ncbi import (
    DownloadOptions,
    NcbiClient,
    collect_accessions_from_files,
    parse_accession_text,
)
from .tab_merge import NAMING_LABELS, _label_to_key
from .widgets import FilePicker, ProgressPanel, grid_row

TITLE = "按登录号下载"


def build(parent: ttk.Frame, app) -> ttk.Frame:
    source = ttk.LabelFrame(parent, text="登录号（每行一个，或用空格/逗号/分号分隔）")
    source.pack(fill="both", expand=True, padx=8, pady=(8, 4))
    text = tk.Text(source, height=9, wrap="none")
    text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
    scroll = ttk.Scrollbar(source, orient="vertical", command=text.yview)
    scroll.pack(side="left", fill="y", pady=6)
    text.configure(yscrollcommand=scroll.set)

    side = ttk.Frame(source)
    side.pack(side="left", fill="y", padx=6, pady=6)

    def load_from_file() -> None:
        chosen = filedialog.askopenfilename(title="选择包含登录号的文本文件",
                                            filetypes=[("文本文件", "*.txt"), ("全部文件", "*.*")])
        if not chosen:
            return
        with open(chosen, "rt", encoding="utf-8-sig", errors="replace") as handle:
            content = handle.read()
        text.delete("1.0", "end")
        text.insert("1.0", content)

    def extract_from_sequences() -> None:
        chosen = filedialog.askopenfilenames(title="选择已有的 FASTA / GenBank 文件")
        if not chosen:
            return
        found = collect_accessions_from_files([str(p) for p in chosen])
        text.delete("1.0", "end")
        text.insert("1.0", "\n".join(found))
        app.log.info(f"从文件提取到 {len(found)} 个登录号")

    def clear_text() -> None:
        text.delete("1.0", "end")

    ttk.Button(side, text="从文本文件导入…", command=load_from_file).pack(fill="x", pady=2)
    ttk.Button(side, text="从序列文件提取…", command=extract_from_sequences).pack(fill="x", pady=2)
    ttk.Button(side, text="清空", command=clear_text).pack(fill="x", pady=2)

    download_box = ttk.LabelFrame(parent, text="下载选项")
    download_box.pack(fill="x", padx=8, pady=4)

    want_fasta = tk.BooleanVar(value=True)
    want_genbank = tk.BooleanVar(value=True)
    per_sequence = tk.BooleanVar(value=True)
    merged = tk.BooleanVar(value=True)
    row = ttk.Frame(download_box)
    grid_row(download_box, 0, "产物", row)
    ttk.Checkbutton(row, text="FASTA", variable=want_fasta).pack(side="left")
    ttk.Checkbutton(row, text="GenBank",
                    variable=want_genbank).pack(side="left", padx=(10, 0))
    ttk.Checkbutton(row, text="每序列单文件",
                    variable=per_sequence).pack(side="left", padx=(10, 0))
    ttk.Checkbutton(row, text="同时合并为大文件",
                    variable=merged).pack(side="left", padx=(10, 0))

    naming = tk.StringVar(value=NAMING_LABELS["accession"])
    combo = ttk.Combobox(download_box, textvariable=naming, state="readonly",
                         values=list(NAMING_LABELS.values()))
    grid_row(download_box, 1, "命名规则", combo)

    out_dir = FilePicker(download_box, mode="directory", title="下载输出文件夹")
    out_dir.set_path(app.settings.output_dir)
    grid_row(download_box, 2, "输出文件夹", out_dir)

    action = ttk.Frame(parent)
    action.pack(fill="x", padx=8, pady=(4, 8))
    progress = ProgressPanel(action)
    progress.pack(side="left", fill="x", expand=True)
    start_button = ttk.Button(action, text="开始下载")

    def on_progress(done: int, total: int, text_message: str) -> None:
        if done == 0:
            progress.start(total)
        progress.update(done, total, text_message)

    def on_done(report) -> None:
        progress.finish(f"成功 {report.succeeded} / 跳过 {report.skipped} / "
                        f"失败 {report.failed}")
        messagebox.showinfo(
            "下载完成",
            f"成功 {report.succeeded} 条，跳过 {report.skipped} 条，"
            f"失败 {report.failed} 条。\n输出目录：{report.out_dir}")
        if report.failures:
            app.open_tab(4)

    def start() -> None:
        accessions = parse_accession_text(text.get("1.0", "end"))
        if not accessions:
            app.log.warn("请先填写或导入登录号")
            return
        target_dir = out_dir.path()
        if not target_dir:
            app.log.warn("请指定下载输出文件夹")
            return
        if not app.settings.email:
            app.log.warn("请先在「设置」中填写 NCBI 邮箱（NCBI 的合规要求）")
            app.open_tab(4)
            return

        options = DownloadOptions(
            out_dir=target_dir,
            want_fasta=want_fasta.get(),
            want_genbank=want_genbank.get(),
            per_sequence_files=per_sequence.get(),
            merged_files=merged.get(),
            naming_mode=_label_to_key(NAMING_LABELS, naming.get()),
            force_redownload=app.settings.force_redownload,
            wrap=app.settings.wrap,
        )

        def job(ctx):
            client = NcbiClient(email=app.settings.email, api_key=app.settings.api_key,
                                proxy=app.settings.proxy, log=app.log,
                                cancel=ctx.cancel_event)
            return client.download(accessions, options, progress=ctx.progress)

        app.run_job(job, on_done=on_done,
                    on_error=lambda e: (progress.reset(),
                                        app.log.error(f"下载失败: {e}")),
                    progress_handler=on_progress)

    start_button.configure(command=start)
    start_button.pack(side="right")
    app.register_busy_widget(start_button)
    return parent
```

- [ ] **步骤 5：运行测试并确认其通过**

运行：`python -m pytest tests/test_ncbi.py tests/test_gui_tabs.py -v`
预期：PASS（test_ncbi 33 passed，test_gui_tabs 5 passed）

- [ ] **步骤 6：提交**

```bash
git add seq_toolkit/ncbi.py seq_toolkit/gui/tab_accession.py tests
git commit -m "feat(gui): 实现按登录号下载标签页与登录号解析"
```

---

### Task 25：设置标签页 `gui/tab_settings.py`

**文件：**
- 修改：`seq_toolkit/gui/tab_settings.py`（替换占位实现）
- 修改：`tests/test_gui_tabs.py`（追加测试）

**接口：**
- 依赖输入：`App.settings` / `App.save_settings`、`settings.Settings`
- 对外产出：`build(parent, app) -> ttk.Frame`；模块常量 `TITLE`、`split_suffixes(text) -> tuple[str, ...]`、`join_suffixes(suffixes) -> str`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_gui_tabs.py` 末尾追加：

```python
def test_split_and_join_suffixes_round_trip():
    from seq_toolkit.gui.tab_settings import join_suffixes, split_suffixes
    assert split_suffixes(".fa, .fasta .fna") == (".fa", ".fasta", ".fna")
    assert split_suffixes("") == ()
    assert join_suffixes((".fa", ".fna")) == ".fa, .fna"


def test_settings_tab_builds_and_saves(app, tmp_path, monkeypatch):
    import seq_toolkit.settings as settings_module
    from seq_toolkit.gui import tab_settings
    # 必须把配置路径改到临时目录，否则测试会污染用户真实的 %APPDATA% 配置
    monkeypatch.setattr(settings_module, "settings_path",
                        lambda: str(tmp_path / "settings.json"))
    assert tab_settings.TITLE == "设置"
    frame = tab_settings.build(app.notebook.winfo_children()[4], app)
    assert frame is not None
    app.settings.email = "tester@example.org"
    app.save_settings()
    assert app.log.entries[-1].message.startswith("设置已保存")
    assert (tmp_path / "settings.json").exists()
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_gui_tabs.py -v`
预期：FAIL，`ImportError: cannot import name 'join_suffixes'`

- [ ] **步骤 3：编写最小实现**

用以下内容替换 `seq_toolkit/gui/tab_settings.py` 的全部内容：

```python
"""⑤ 设置：NCBI 凭据、代理、默认输出目录、后缀名与换行策略。"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, ttk

from ..settings import Settings
from .widgets import grid_row

TITLE = "设置"
_SEPARATOR = re.compile(r"[\s,;]+")


def split_suffixes(text: str) -> tuple[str, ...]:
    """把用户输入的后缀串切成元组，缺前导点自动补上。"""
    parts = [chunk.strip() for chunk in _SEPARATOR.split(text or "") if chunk.strip()]
    return tuple(chunk if chunk.startswith(".") else f".{chunk}" for chunk in parts)


def join_suffixes(suffixes) -> str:
    return ", ".join(suffixes)


def build(parent: ttk.Frame, app) -> ttk.Frame:
    settings: Settings = app.settings

    box = ttk.LabelFrame(parent, text="NCBI 访问设置")
    box.pack(fill="x", padx=8, pady=(8, 4))

    email = tk.StringVar(value=settings.email)
    ttk.Entry(box, textvariable=email).grid(
        row=0, column=1, sticky="ew", padx=(0, 8), pady=3)
    ttk.Label(box, text="NCBI 邮箱（必填）").grid(
        row=0, column=0, sticky="w", padx=(8, 6), pady=3)
    ttk.Label(box, text="NCBI 要求所有 E-utilities 请求附带联系邮箱，否则可能被限流。",
              foreground="#666666").grid(row=1, column=1, sticky="w", padx=(0, 8))

    api_key = tk.StringVar(value=settings.api_key)
    ttk.Entry(box, textvariable=api_key).grid(
        row=2, column=1, sticky="ew", padx=(0, 8), pady=3)
    ttk.Label(box, text="NCBI API key（选填）").grid(
        row=2, column=0, sticky="w", padx=(8, 6), pady=3)
    ttk.Label(box, text="填写后请求速率由 3 次/秒提升到 10 次/秒。",
              foreground="#666666").grid(row=3, column=1, sticky="w", padx=(0, 8))

    proxy = tk.StringVar(value=settings.proxy)
    ttk.Entry(box, textvariable=proxy).grid(
        row=4, column=1, sticky="ew", padx=(0, 8), pady=3)
    ttk.Label(box, text="代理服务器（选填）").grid(
        row=4, column=0, sticky="w", padx=(8, 6), pady=3)
    ttk.Label(box, text="例如 http://127.0.0.1:7890。国内直连 NCBI 常常超时，填了更稳。",
              foreground="#666666").grid(row=5, column=1, sticky="w", padx=(0, 8))
    box.columnconfigure(1, weight=1)

    file_box = ttk.LabelFrame(parent, text="文件处理偏好")
    file_box.pack(fill="x", padx=8, pady=4)

    out_dir = tk.StringVar(value=settings.output_dir)
    entry = ttk.Entry(file_box, textvariable=out_dir)
    grid_row(file_box, 0, "默认输出目录", entry)

    fasta_suffixes = tk.StringVar(value=join_suffixes(settings.fasta_suffixes))
    grid_row(file_box, 1, "FASTA 后缀名", ttk.Entry(file_box, textvariable=fasta_suffixes))

    genbank_suffixes = tk.StringVar(value=join_suffixes(settings.genbank_suffixes))
    grid_row(file_box, 2, "GenBank 后缀名", ttk.Entry(file_box, textvariable=genbank_suffixes))

    wrap = tk.IntVar(value=settings.wrap)
    row = ttk.Frame(file_box)
    grid_row(file_box, 3, "FASTA 每行长度", row)
    ttk.Radiobutton(row, text="不换行", value=0, variable=wrap).pack(side="left")
    for width in (60, 70, 80):
        ttk.Radiobutton(row, text=str(width), value=width,
                        variable=wrap).pack(side="left", padx=(8, 0))

    force = tk.BooleanVar(value=settings.force_redownload)
    grid_row(file_box, 4, "重复下载",
             ttk.Checkbutton(file_box, text="强制重新下载（默认跳过已存在的文件）",
                             variable=force))

    action = ttk.Frame(parent)
    action.pack(fill="x", padx=8, pady=(8, 8))

    def apply_values() -> None:
        app.settings.email = email.get().strip()
        app.settings.api_key = api_key.get().strip()
        app.settings.proxy = proxy.get().strip()
        app.settings.output_dir = out_dir.get().strip()
        app.settings.fasta_suffixes = split_suffixes(fasta_suffixes.get())
        app.settings.genbank_suffixes = split_suffixes(genbank_suffixes.get())
        app.settings.wrap = wrap.get()
        app.settings.force_redownload = force.get()

    def save() -> None:
        apply_values()
        if not app.settings.email:
            messagebox.showwarning("提示", "NCBI 邮箱为必填项，缺失会导致下载功能被限流。")
        app.save_settings()
        messagebox.showinfo("已保存", "设置已保存。")

    ttk.Button(action, text="保存设置", command=save).pack(side="right")
    return parent
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_gui_tabs.py -v`
预期：PASS（7 passed）

- [ ] **步骤 5：提交**

```bash
git add seq_toolkit/gui/tab_settings.py tests/test_gui_tabs.py
git commit -m "feat(gui): 实现设置标签页"
```

---

### Task 26：程序入口 `main.py`

**文件：**
- 新建：`main.py`
- 修改：`tests/test_smoke.py`（追加测试）

**接口：**
- 依赖输入：`settings.load_settings`、`gui.app.App`
- 对外产出：`main() -> int`；`install_crash_handler() -> str`（返回崩溃日志路径）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_smoke.py` 末尾追加：

```python
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
```

- [ ] **步骤 2：运行测试并确认其失败**

运行：`python -m pytest tests/test_smoke.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'main'`

- [ ] **步骤 3：编写最小实现**

新建项目根目录下的 `main.py`：

```python
"""序列工具箱入口。

负责：加载设置、安装顶层异常处理、启动 Tk 主循环。
任何未捕获异常都会写入 %APPDATA%/seq_toolkit/crash.log，并弹出可复制的错误对话框，
而不是让窗口静默消失。
"""

from __future__ import annotations

import datetime
import os
import sys
import traceback

from seq_toolkit.settings import load_settings

_APP_DIR = "seq_toolkit"
_CRASH_FILE = "crash.log"


def crash_log_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, _APP_DIR, _CRASH_FILE)


def install_crash_handler() -> str:
    """安装全局异常钩子，返回崩溃日志路径。"""
    target = crash_log_path()

    def _handle(exc_type, exc_value, exc_tb) -> None:
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(target, "at", encoding="utf-8") as handle:
                handle.write(f"\n===== {stamp} =====\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=handle)
        except OSError:
            pass

        try:
            import tkinter.messagebox as messagebox
            messagebox.showerror(
                "程序出现未预期的错误",
                f"{exc_type.__name__}: {exc_value}\n\n"
                f"详细信息已写入：\n{target}",
            )
        except Exception:  # noqa: BLE001 图形环境不可用时退回控制台
            traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)

    sys.excepthook = _handle
    return target


def main() -> int:
    install_crash_handler()
    settings = load_settings()

    from seq_toolkit.gui.app import App

    app = App(settings)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **步骤 4：运行测试并确认其通过**

运行：`python -m pytest tests/test_smoke.py -v`
预期：PASS（4 passed）

- [ ] **步骤 5：手工验收**

运行：`python main.py`
预期：窗口打开，标题为"序列工具箱 — FASTA / GenBank 合并、转换、命名与 NCBI 下载"，五个标签页均可点击，底部日志面板与状态栏正常。

- [ ] **步骤 6：全量回归并提交**

运行：`python -m pytest -v`
预期：全部 PASS

```bash
git add main.py tests/test_smoke.py
git commit -m "feat: 增加程序入口与顶层异常处理"
```

---

### Task 27：打包为单文件 exe

**文件：**
- 新建：`build.spec`
- 新建：`assets/icon.ico`（可选；若暂无图标则删除 spec 中 `icon=` 一行）

**接口：**
- 依赖输入：全部已完成的源码
- 对外产出：`dist/序列工具箱.exe`

- [ ] **步骤 1：编写打包配置**

新建 `build.spec`：

```python
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件、无控制台、剔除未使用的重量级模块。"""

EXCLUDES = [
    "numpy", "pandas", "matplotlib", "scipy", "PIL", "pytest",
    "IPython", "notebook", "PyQt5", "PySide2", "PySide6", "wx",
    "setuptools", "pip", "wheel", "distutils", "unittest", "pydoc",
    "email", "html", "http.server", "xmlrpc", "sqlite3", "bz2", "lzma",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="序列工具箱",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
)
```

> `sqlite3` / `bz2` / `lzma` 被剔除不影响本工具（只用 `gzip`，它是内建 C 模块，不依赖 `bz2`/`lzma`，因为 `gzip` 只走 zlib）。若打包后运行时报 `ModuleNotFoundError`，把对应模块从 `EXCLUDES` 中移除即可。

- [ ] **步骤 2：安装打包依赖并执行打包**

```bash
python -m pip install -r requirements.txt
python -m PyInstaller --clean --noconfirm build.spec
```

- [ ] **步骤 3：验证 exe 可运行**

```bash
start "" "dist\序列工具箱.exe"
```
预期：窗口正常打开，五个标签页齐全。关闭窗口。

- [ ] **步骤 4：验证体积与启动时间**

```bash
powershell -NoProfile -Command "$f=Get-Item 'dist\序列工具箱.exe'; '{0:N1} MB' -f ($f.Length/1MB)"
```

预期：体积 ≤ 25 MB。若超出，从 `EXCLUDES` 继续追加模块（常见可剔除项：`pydoc_data`、`lib2to3`、`asyncio`、`concurrent`、`multiprocessing`）。

启动时间手工确认：双击 exe 到窗口出现应 ≤ 3 秒。

- [ ] **步骤 5：提交**

```bash
git add build.spec
git commit -m "chore: 增加 PyInstaller 打包配置"
```

> `dist/` 与 `build/` 已在 `.gitignore` 中，不提交二进制产物。

---

### Task 28：README 与端到端验收

**文件：**
- 新建：`README.md`
- 新建：`docs/acceptance.md`

**接口：**
- 依赖输入：全部已完成的功能
- 对外产出：可交付的说明文档与验收记录

- [ ] **步骤 1：编写 README**

新建 `README.md`：

```markdown
# 序列工具箱（Sequence Toolkit）

把基因组学日常最琐碎的几件事整合进一个免安装的 Windows 小程序：

1. **合并 / 转换** —— 合并 FASTA、合并 GenBank、GenBank 转 FASTA（后缀名混乱也能自动识别）
2. **重命名 / 拆分** —— 按 `>` 行内容改写序列名，也可把序列拆成单文件、或批量重命名磁盘文件
3. **检索与批量下载** —— 按物种名 / 属名检索 NCBI，筛长度、完整基因组、RefSeq，勾选后批量下载
4. **按登录号下载** —— 粘贴、导入文本、或从已有序列文件里自动提取登录号

## 三种命名规则

| 规则 | 示例 |
|---|---|
| 登录号 | `ON929859.1` |
| 物种名 | `Salsola_pellucida` |
| 登录号_物种名 | `ON929859.1_Salsola_pellucida` |

空格一律替换为 `_`。同一物种有多条序列时自动追加流水号（`_1`、`_2`），避免出现同名序列。

## 安装与运行

直接双击 `序列工具箱.exe`，无需安装 Python 或任何依赖。

首次使用请到「设置」填写 **NCBI 邮箱**（NCBI 的硬性要求）。国内直连 NCBI 经常超时，建议同时填写代理服务器地址。

## 从源码运行

```bash
python -m pip install -r requirements.txt
python main.py
```

## 测试

```bash
python -m pytest -v
```

## 打包为单文件 exe

```bash
python -m pip install -r requirements.txt
python -m PyInstaller --clean --noconfirm build.spec
```

产物为 `dist/序列工具箱.exe`。若杀毒软件误报，请将其加入白名单；也可改用 `--onedir` 模式
（把 `build.spec` 中 `EXE(...)` 的 `onefile` 相关参数去掉），启动更快但产出是一个文件夹。

## 已知限制

- **GenBank 输出的 LOCUS 名称字段只有 16 列。** 当目标名称超过 16 个字符时，输出的 `LOCUS` 名保持原值不变（避免破坏列对齐导致下游解析截断），改名映射会写入日志。
- **未组装记录（只有 `CONTIG`、没有 `ORIGIN`）无法导出序列**，会被列入异常清单并跳过，不会静默丢弃。
- **"只要完整基因组"是本地筛选**：NCBI 服务端没有可信字段，本工具按定义行关键词判断。
- **不做并发下载**：速度瓶颈在 NCBI 的速率限制，单线程顺序下载已足够，且更不容易触发封禁。

## 目录结构

```
main.py                  程序入口
seq_toolkit/
  model.py               统一数据模型 SequenceRecord
  textio.py              UTF-8 / BOM / .gz 文本打开
  format_detect.py       格式识别（内容优先于后缀）
  fasta_io.py            FASTA 读写
  genbank_io.py          GenBank 读写（原始块保真）
  naming.py              命名规则引擎（纯函数）
  pipeline.py            合并 / 转换 / 拆分 / 磁盘改名编排
  ncbi.py                E-utilities 客户端
  settings.py            配置持久化
  applog.py              日志与异常清单
  gui/                   Tkinter 界面
tests/                   pytest 测试
```
```

- [ ] **步骤 2：按验收标准逐项手工验收**

新建 `docs/acceptance.md`，按下表逐项执行并记录结果（每行填「通过 / 不通过 + 证据」）：

| # | 验收项 | 操作 | 结果 |
|---|---|---|---|
| 1 | 混合后缀合并 | 准备 `a.fa` `b.fasta` `c.fna` `d.gbk` 与一个后缀错起的文件（内容为 GenBank 但命名为 `.fa`），合并后记录数正确、错起文件被识别 | |
| 2 | 三种命名规则 | `>ON929859.1 Salsola pellucida chloroplast, complete genome` 分别得到 `ON929859.1` / `Salsola_pellucida` / `ON929859.1_Salsola_pellucida` | |
| 3 | 同物种流水号 | 同物种两条记录在两种含物种名的模式下分别得到 `_1` `_2`，无重名 | |
| 4 | 物种名提取 8 例 | 逐个输入设计规格 §7.4 表格中的 8 个 header，结果与表格一致；失败案例进入异常清单且未改名 | |
| 5 | CONTIG 记录 | 含 CONTIG 记录的多记录 GenBank 转 FASTA，CONTIG 进异常清单，其余全部导出 | |
| 6 | 中文路径 | 在 `D:\中文目录\样本.fa` 上跑全部功能 | |
| 7 | 检索下载 | 检索 `Salsola`（属名）+ 长度 100000–200000 + 完整基因组，勾选 5 条下载，得到 5 组 `.fa`/`.gb` + 两个合并文件，长度与表格一致 | |
| 8 | 断网行为 | 断网后下载，出现明确错误与重试日志，程序不崩溃 | |
| 9 | 防覆盖 | 输出目标已存在时自动加 `_1`，原文件内容不变 | |
| 10 | 取消 | 处理中点击取消，1 秒内响应，已写出的文件完好 | |
| 11 | 体积与性能 | exe ≤ 25 MB，空载内存 ≤ 80 MB，冷启动 ≤ 3 秒（任务管理器观察） | |
| 12 | pytest | `python -m pytest -v` 全绿 | |
| 13 | 磁盘改名预览 | 预览对照表与实际执行结果一致；同 accession 的 `.fa` 与 `.gb` 不互相覆盖 | |
| 14 | 全小写 header | `>AB123456.1 salsola pellucida chloroplast` 正确提取物种名 | |
| 15 | GenBank 注释保真 | 合并 GenBank 后 `FEATURES` 段与原始输入逐字节一致；改名后仅 `LOCUS` 名称列变化 | |
| 16 | 合成记录往返 | FASTA → GenBank 的合成记录能被本工具重新正确解析 | |
| 17 | 异常清单导出 | 导出 CSV 用 Excel 打开中文不乱码 | |

- [ ] **步骤 3：修复验收中发现的问题**

对每个「不通过」项，回到对应任务补充测试并修复，然后重跑该任务与全量测试。**不得跳过任何一项。**

- [ ] **步骤 4：提交**

```bash
git add README.md docs/acceptance.md
git commit -m "docs: 增加使用说明与验收记录"
```

---

## 完成定义

全部 28 个任务的复选框均勾选，且：

- `python -m pytest -v` 全绿
- `docs/acceptance.md` 中 17 项验收全部通过
- `dist/序列工具箱.exe` 可在目标机器上双击运行，体积 ≤ 25 MB
- 工作区无未提交改动
