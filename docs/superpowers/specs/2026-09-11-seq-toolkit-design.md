# 序列工具箱（Sequence Toolkit）· 设计规格

| 项目 | 内容 |
|---|---|
| 日期 | 2026-09-11 |
| 状态 | 已通过分节评审，待用户复核书面规格 |
| 交付物 | Windows 单文件 exe + 源码 + 测试 |
| 决策来源 | 与用户的分节头脑风暴（8 轮澄清 + 2 节设计确认） |

---

## 1. 背景与目标

用户（基因组学研究者）日常需要在本地反复完成以下工作：把散落在多个目录、后缀名不统一的 FASTA 与 GenBank 文件合并；把下载到的 GenBank 记录转成 FASTA；把序列头部改成下游建树软件可用的规范名称；以及从 NCBI 按物种名/属名检索并批量下载序列。

这些工作用命令行工具（seqkit、biopython 脚本）能做，但对非程序员门槛高、易错，且每个环节都要重写一遍脚本。本项目把这些操作整合为一个**体积小、占用低、免安装的 Windows 图形化 exe**。

### 成功标准

一个不写代码的生物学研究者拿到 exe 后，能独立完成"检索物种序列 → 批量下载 → 规范化命名 → 合并成建树可用的数据集"的完整流程，且中途不需要打开命令行。

---

## 2. 非目标（YAGNI，明确排除）

以下内容**不在**本设计范围内，实现阶段不得擅自加入：

- 序列比对、建树、注释、BLAST
- GenBank feature（CDS/rRNA/tRNA/gene）的结构化解析与导出
- 本地序列数据库、索引、去冗余聚类
- 多线程/异步并发下载
- macOS / Linux 支持
- 自动更新、遥测、云同步
- 可配置的通用流水线编辑器（"读→筛选→改名→写"自由组合）

---

## 3. 术语表

| 术语 | 含义 |
|---|---|
| accession | 登录号，如 `ON929859` |
| accession version | 带版本号的完整登录号，如 `ON929859.1`。**本工具中"登录号"默认指此形式** |
| species | 物种名（属+种），如 `Salsola pellucida` |
| 序列名 | FASTA 中 `>` 后第一个字段；GenBank 中对应 LOCUS/VERSION 名 |
| 记录 | 一条序列及其元数据，对应 `SequenceRecord` |
| 批次 | 一次"开始处理"所覆盖的全部输入文件 |

---

## 4. 运行环境与交付形式

- 开发机：Windows，Python 3.12（用户级安装，免管理员权限）
- 目标机：Windows 10/11 x64，**无需安装 Python 或任何依赖**
- 交付：PyInstaller `--onefile --windowed` 单文件 exe，预期 15-25 MB
- 同时提供 `--onedir` 版本（启动无解压延迟，体积略大），由用户在实现阶段二选一或两者都出
- 源码以模块化包形式组织，附 pytest 测试与 `README.md`（含使用说明与打包命令）

---

## 5. 功能需求

### FR-1 合并 / 转换（覆盖原始需求 1、2、3）

单一面板完成"合并 FASTA""合并 GenBank""GenBank 转 FASTA"三件事：

- 输入：可添加多个文件、可添加文件夹；文件夹可选是否含子文件夹
- 输入类型：`自动识别` / `强制 FASTA` / `强制 GenBank`
- 输出格式：`FASTA` / `GenBank`
- **输出方式**：`合并为单个文件`（默认）/ `每个输入文件各输出一个文件`（**用户使用后新增**，见下）
- 输出路径：用户指定；已存在时**不覆盖**，自动追加 `_1`、`_2` 并记日志
- 命名规则：`不改名` / `登录号` / `物种名` / `登录号_物种名`（详见 §8）
- 去重：`按登录号去重` / `不去重`（详见 §9）
- 进度条 + 可取消

**输出方式：每个输入文件各输出一个文件（用户使用后新增）。** 用户原话是「genbank 文件转 fasta
文件的时候，无论如何输出的只有一个合并的 fasta 文件，请你增加批量将 genbank 文件分别转化为
fasta 文件的功能」——原有实现只有"合并成一个"（`run_merge`）与"按**记录**拆"（`split_records`），
缺"按**输入文件**逐个输出"这一档。约定：

- 输出目标是一个**目录**（不是文件）：每个输入文件单独处理、单独写盘，多记录文件仍只产出 1 个文件
- 输出文件名沿用原文件主干、只换目标格式后缀：`样本.gbk` → `样本.fasta`，`样本.gbk.gz` → `样本.fasta`
  （格式后缀与 `.gz` 一起剥掉；不可用裸 `Path.stem`，那会得到 `样本.gbk.fasta`）
- 文件内序列名套用本页「命名规则」；**流水号与重名保护的作用域在单个文件内**
- 「按登录号去重」在单个文件内部生效（默认 `不去重`），日志写明作用域为"本文件内"
- 某文件 0 条可用记录（如全部为 `CONTIG`）⇒ WARN 并跳过，**不产出空文件**；单文件失败不中断整批
- 目标已存在时与 `split_records` 同一语义：逐字节相同 ⇒ 跳过（不加 `_1`），不同 ⇒ 让位 `_1` 并 WARN
- 接口：`pipeline.ConvertPlan` + `pipeline.convert_each_file()`（字段用 `out_dir` 而非 `output_path`，
  以免与"单个输出文件"的语义混淆）


### FR-2 重命名 / 拆分（覆盖原始需求 4、5）

对既有文件做头部改写与文件拆分，三个开关正交、可任意组合：

- `☑ 改写 > 行序列名`：把输出文件中的 `>` 行按命名规则重写
- `☑ 按序列名拆分为单文件`：每条序列写入独立文件，文件名为最终序列名；扩展名随输出格式（FASTA → `.fasta`，GenBank → `.gb`）
- `☑ 重命名已有磁盘文件`：读取每个文件内容，据其中的登录号/物种名重命名磁盘上的文件本身
  - 多个文件解析出**同名**时（例如同一 accession 的 FASTA 与 GenBank 副本），按 `§9` 步骤 7 的规则追加 `_1` `_2`，**绝不覆盖**
  - 提供"预览"按钮：先列出 `原文件名 → 新文件名` 的完整对照表供确认，确认后才实际执行
- `☑ 异常清单待复核`：把无法可靠解析的记录汇总供人工确认
- 拆分与磁盘重命名以 `pipeline.split_records()` / `pipeline.rename_disk_files(dry_run=...)` 实现，复用同一套命名规则引擎，不重复实现

### FR-3 检索与批量下载（覆盖原始需求 6 前半）

- 检索词 + 模式选择（`物种名` / `属名`）
- 筛选：长度区间（bp）、`只要完整基因组`、`只要 RefSeq`
- 结果表格列：勾选框、Accession、长度、物种名、定义行、发布日期、来源（GenBank/RefSeq）
- 全选 / 反选 / 计数显示；显示上限 5000 行（超出提示用筛选条件缩小范围）
- 下载选项：`☑FASTA` `☑GenBank` `☑每序列单文件` `☑同时合并为大文件` `☑套用命名规则`
- 输出：每个序列一个 `.fasta` 和一个 `.gb`（文件名可套用命名规则），**并且**额外生成 `all_sequences.fasta` 与 `all_sequences.gb`
  - FASTA 产物后缀统一为 `.fasta`（**用户使用后提出的调整**）；读取侧仍接受 `.fa`、`.fna` 等老后缀，不受影响
- 批量导出登录号：勾选结果可导出为 `.txt`（一行一个登录号）或 `.csv`（带表头，列为 Accession / 长度 / 物种名 / 定义行 / 发布日期 / 来源）；**未勾选时导出表格显示的全部并在日志中说明**（**用户使用后新增**）

### FR-4 按登录号下载（覆盖原始需求 6 后半）

登录号来源三选一：粘贴文本（每行一个，或空格/逗号/分号分隔）、从 txt 文件读取、**从已有的 FASTA 或 GenBank 文件中自动提取**（提取结果自动去重并保持出现顺序）。
下载选项与产物组织同 FR-3。

### FR-5 设置

持久化到 `%APPDATA%/seq_toolkit/settings.json`：

- NCBI 邮箱（必填，NCBI 合规要求）
- NCBI API key（选填，速率 3 次/秒 → 10 次/秒）
- 代理服务器（HTTP/HTTPS，选填）
- 默认输出目录
- 自定义后缀名列表（FASTA / GenBank 各自一份）
- FASTA 每行长度（`不换行` / 60 / 70 / 80，默认不换行）

### FR-6 日志与异常清单

窗口底部常驻面板，两个子标签：

- **运行日志**：分级（INFO/WARN/ERROR）、可滚动、可导出 `.log`
- **异常清单**：表格（文件、行号、原始 header、判定原因、最终采用的名称），可导出 CSV

---

## 6. 架构

### 6.1 目录结构

```
一些非常实用的基因组分析数据小插件/
├─ main.py                     # 入口：初始化设置、构建主窗口
├─ requirements.txt
├─ README.md
├─ build.spec                  # PyInstaller 打包配置
├─ seq_toolkit/
│  ├─ __init__.py
│  ├─ model.py                 # SequenceRecord：唯一跨层契约
│  ├─ textio.py                # 统一的文本打开（显式 UTF-8 + BOM + .gz 透明解压）
│  ├─ format_detect.py         # 格式识别（后缀 + 内容嗅探）
│  ├─ fasta_io.py              # FASTA 读 / 写
│  ├─ genbank_io.py            # GenBank 读 / 写
│  ├─ naming.py                # 命名规则引擎（纯函数，无 IO）
│  ├─ pipeline.py              # 编排：合并 / 转换 / 拆分 / 改磁盘文件名
│  ├─ ncbi.py                  # E-utilities 客户端
│  ├─ settings.py              # 配置读写
│  ├─ applog.py                # 日志与异常清单收集
│  └─ gui/
│     ├─ __init__.py
│     ├─ app.py                # 主窗口、标签页容器、日志面板
│     ├─ worker.py             # 后台线程 + 队列消息泵 + 取消
│     ├─ widgets.py            # 可排序表格、带勾选框表格、文件选择器、进度条
│     ├─ tab_merge.py          # ① 合并 / 转换
│     ├─ tab_rename.py         # ② 重命名 / 拆分
│     ├─ tab_search.py         # ③ 检索与批量下载
│     ├─ tab_accession.py      # ④ 按登录号下载
│     └─ tab_settings.py       # ⑤ 设置
├─ tests/
│  ├─ fixtures/                # 真实片段样本
│  ├─ test_format_detect.py
│  ├─ test_fasta_io.py
│  ├─ test_genbank_io.py
│  ├─ test_naming.py
│  ├─ test_pipeline.py
│  └─ test_ncbi.py
└─ docs/superpowers/specs/2026-09-11-seq-toolkit-design.md
```

### 6.2 分层与依赖方向

```
gui/  ──▶  pipeline.py ──▶ fasta_io.py / genbank_io.py ──▶ model.py
  │              │                                          ▲
  │              └──▶ naming.py ────────────────────────────┘
  └──▶  ncbi.py  ──▶ model.py
```

**依赖只允许自上而下。** `naming.py` 与两个 `*_io.py` 不得 import 任何 GUI 模块，不得依赖 `pipeline.py`。这使得核心逻辑可以在无图形环境下被 pytest 完整测试。

### 6.3 数据模型 `SequenceRecord`

```python
@dataclass(frozen=True)
class SequenceRecord:
    accession: str          # 完整登录号，如 "ON929859.1"
    accession_base: str     # "ON929859"
    version: int | None     # 1
    species: str            # 规范化： "Salsola_pellucida"（下划线形式）
    species_raw: str        # 原始串："Salsola pellucida"
    lineage: str            # GenBank 分类谱系行；FASTA 来源时为空串
    definition: str         # 完整定义行
    seq: str                # 大写、无空白的纯序列
    source_format: str      # "fasta" | "genbank"
    origin_path: str        # 来源文件绝对路径
    origin_line: int        # 记录起始行号（1-based）
    date: str = ""          # GenBank LOCUS 日期；FASTA 来源时为空串
    raw_block: str = ""     # GenBank 记录的原始文本块（含 FEATURES 等全部注释）；FASTA 来源时为空串
    warnings: tuple[str, ...] = ()   # 该记录的解析异常
```

不可变（`frozen=True`），保证跨层传递时不会被意外改写。

### 6.4 模块接口

```python
# format_detect.py
def detect_format(path: str, content_format_hint: str = "auto") -> str  # "fasta"|"genbank"
def list_input_files(paths: list[str], recursive: bool, suffixes: SuffixConfig) -> list[str]

# fasta_io.py
def read_fasta(path: str) -> Iterator[SequenceRecord]
def write_fasta(records: Iterable[SequenceRecord], out_path: str,
                name_map: Mapping[SequenceRecord, str] | None = None, wrap: int = 0) -> None

# genbank_io.py
def read_genbank(path: str,
                 on_skip: Callable[[str, int, str], None] | None = None) -> Iterator[SequenceRecord]
def write_genbank(records: Iterable[SequenceRecord], out_path: str,
                  name_map: Mapping[SequenceRecord, str] | None = None) -> None
def format_genbank_record(rec: SequenceRecord, name: str) -> str

# naming.py  —— 全部为纯函数
def sanitize_accession(text: str) -> str      # 保留句点（版本号）
def sanitize_species(text: str) -> str        # 删除句点与其他标点
def species_key(record: SequenceRecord) -> str
def render_name(record: SequenceRecord, mode: str, serial: int | None = None) -> str
def build_name_map(records: Sequence[SequenceRecord], mode: str) -> dict[SequenceRecord, str]
def extract_species_from_header(header_body: str) -> tuple[str, tuple[str, ...]]

# pipeline.py
@dataclass
class ProcessPlan:
    inputs: list[str]
    recursive: bool
    input_format: str        # "auto"|"fasta"|"genbank"
    output_format: str       # "fasta"|"genbank"
    output_path: str
    naming_mode: str         # "keep"|"accession"|"species"|"accession_species"
    dedup: str               # "accession"|"none"
    progress: Callable[[int, int, str], None]
    cancel: threading.Event

def run_merge(plan: ProcessPlan) -> ProcessResult
def split_records(records, out_dir, naming_mode, out_format) -> ProcessResult
def rename_disk_files(paths, naming_mode, dry_run: bool) -> ProcessResult

# ncbi.py
class NcbiClient:
    def __init__(self, email: str, api_key: str | None, proxy: str | None)
    def search(self, term: str, retmax: int, progress) -> SearchResult
    def summarize(self, ids: list[str]) -> list[SeqSummary]
    def fetch_fasta(self, ids: list[str]) -> str
    def fetch_genbank(self, ids: list[str]) -> str
    def download(self, accessions: list[str], out_dir: str, opts: DownloadOptions,
                 progress, cancel: threading.Event) -> DownloadReport
```

---

## 7. 解析规则

### 7.1 格式识别 `format_detect.py`

1. 若用户指定 `强制 FASTA` / `强制 GenBank`，直接采用，不做嗅探
2. 否则先看后缀（大小写不敏感，`.gz` 先剥离再匹配）：
   - FASTA：`.fasta .fa .fna .fas .ffn .frn .fsa .seq`
   - GenBank：`.gb .gbk .genbank .gbff .gp`
3. 后缀无法判定或与内容冲突时，读首个非空行嗅探：以 `LOCUS` 开头 → GenBank；以 `>` 开头 → FASTA
4. **内容嗅探优先级高于后缀**：若两者冲突，采用内容判定，并写入一条 WARN 日志（后缀名混乱是用户的常见情况）
5. 两者都不匹配 → 跳过该文件并记入异常清单

后缀名列表可在设置中扩展。

### 7.2 FASTA 解析 `fasta_io.py`

- 编码：显式 UTF-8，`errors="replace"`；支持 UTF-8 BOM；支持 CRLF / LF / CR
- `.gz` 用 `gzip.open(..., "rt", encoding="utf-8")` 透明解压
- 记录边界：行首为 `>` 的行
- 头部拆分：
  - `accession_candidate` = `>` 后第一个空白前的 token
  - 校验正则：`^[A-Z]{1,4}[0-9]{5,8}(\.[0-9]+)?$` 或 `^[A-Z]{2}_[0-9]{6,9}(\.[0-9]+)?$`（后者覆盖 `NC_027224.1`、`NZ_CM000001.1` 等 RefSeq 形式）
  - 不通过校验：仍沿用该 token 作为 accession，并追加 warning `"accession 格式可疑"`
  - `accession_base` / `version` 由 `accession` 拆出；无版本号时 `version=None`
- 序列行：拼接所有非 `>` 行，删除全部空白字符，转大写
- 出现非 IUPAC 字符（`ACGTURYSWKMBDHVN` 之外，含 `*`、数字）→ 该记录追加 warning，但**不改动序列内容**
- 空文件、无任何 `>` 记录 → 抛 `FastaParseError`，由 pipeline 捕获并记入异常清单

### 7.3 GenBank 解析 `genbank_io.py`

- 编码与 `.gz` 处理同 FASTA
- 一个文件可含多条记录，以独占一行的 `//` 为记录结束符（允许行尾空白）；逐条 `yield`，不整体载入内存
- 字段提取：

| 字段 | 来源 | 说明 |
|---|---|---|
| `accession` | `VERSION` 行的首个 token | **优先于 `ACCESSION`**，因为它带版本号；`VERSION` 缺失时回退 `ACCESSION` |
| `accession_base` / `version` | 由 `accession` 拆出 | |
| `definition` | `DEFINITION` | 支持跨行续行拼接（续行为缩进行，遇到下一个顶层关键字停止） |
| `species_raw` | `ORGANISM` 行 | 取 `ORGANISM` 之后的整行内容并 trim |
| `lineage` | `ORGANISM` 之后的缩进行 | 直到下一个顶层关键字 |
| `date` | `LOCUS` 行 | 形如 `12-JAN-2022` 的 token |
| `seq` | `ORIGIN` 之后的全部内容 | 删除行首行号与所有空白，转大写 |

- 区段边界判定：顶层关键字**顶格**（无缩进）出现在行首，如 `^ORIGIN`、`^LOCUS`、`^FEATURES`、`^//`。`FEATURES` 段内的限定符一律缩进 ≥5 空格，因此不会误判。
- `FEATURES` 段**不做结构化解析**，仅做一次廉价的文本扫描，提取 source feature 的 `/organism="..."` 限定符作为兜底（见下）。这**取代**了"完全跳过 FEATURES"的早期表述，是实现阶段唯一允许触碰 FEATURES 的地方。
- 物种名取值优先级：
  1. `ORGANISM` 段
  2. source feature 的 `/organism="..."` 限定符
  3. 对 `DEFINITION` 复用 §7.4 的智能提取
  4. `LOCUS` 名（并追加 warning `"无物种信息，已回退为 LOCUS 名"`）
- **`CONTIG` 型记录**（未完成基因组：存在 `CONTIG` 行、无 `ORIGIN` 段）→ 无法产出序列，跳过该记录并向异常清单写入原因 `"序列未组装（CONTIG 记录），无 ORIGIN 段"`。**不静默丢弃。**
- 写出：**必须区分两种来源，否则会静默摧毁注释数据**
  - `raw_block` 非空（输入即 GenBank）→ **原样输出原始文本块**，保留 `FEATURES` 等全部注释。改名时只改写 `LOCUS` 行的名称字段；`ACCESSION` 与 `VERSION` **保持原值不变**（它们是序列的事实标识，篡改会造成数据失真），实际映射关系写入日志。
  - `raw_block` 为空（输入为 FASTA）→ 合成最小合法记录（`LOCUS` / `ACCESSION` / `VERSION` / `DEFINITION` / `ORGANISM` / `ORIGIN` / `//`），并在日志中声明"该记录为合成记录，不含 feature 注释"。
    - 合成 `LOCUS` 行的长度字段取 `len(seq)`，分子类型固定 `DNA`，拓扑 `linear`，日期取当天。

> **为何要保留 `raw_block`：** 若合并 GenBank 时只持有解析后的字段，`FEATURES` 段（CDS、rRNA、tRNA、gene 等全部注释）将无法还原，输出文件会变成"有序列无注释"的空壳——这是不可接受的数据丢失。因此 GenBank 记录必须携带原始文本块。

### 7.4 物种名智能提取算法

输入为已剥离 accession token 的 header 剩余文本（或 GenBank 的 `DEFINITION`），输出 `(species_raw, warnings)`。

**步骤 1 · 归一化**：全角空格 → 半角；制表符 → 空格；连续空白压缩为单个空格；去除首尾空白。**除此之外不改动任何字符**，`species_raw` 因此保持可读。

> 与停用词表、标记词表比较时，另做一次**仅用于比较**的归一化：转小写 + 去除首尾标点（含句点）。因此 `sp.` 与 `sp` 等价、`Chloroplast,` 与 `chloroplast` 等价，但输出中仍保留原始拼写。

**步骤 2 · 剥离伪装前缀**：循环删除位于开头的下列前缀词（大小写不敏感，须后跟空白或行尾）：
`UNVERIFIED:`、`MAG:`、`TPA:`、`TPA_exp:`、`TPA_inf:`、`TPA_asm:`、`TSA:`、`WGS:`
每删除一个记一条 INFO warning。

**步骤 3 · 分词**：按空白切分。

**步骤 4 · 顺序扫描**：

- 停用词表（比较时转小写并去除首尾标点后匹配），命中即**终止**：

```
chloroplast, mitochondrion, mitochondrial, mitogenome, plastid, plastome,
genome, complete, partial, sequence, sequences, chromosome, contig, scaffold,
segment, isolate, voucher, clone, strain, cultivar, cv, breed, culture,
gene, genes, mrna, rrna, trna, dna, rna, its, whole, shotgun, wgs,
assembly, chromosome-level, complete-genome, genomic, dna-sequence
```

> 该表中 `cv` / `cultivar` / `breed` / `culture` 属于**终止词**而非吸收标记：品种名、培养物编号不属于物种名，一旦出现即认为物种名已结束（如 `Salsola cv. Xyz` → 物种名为 `Salsola`）。这与 `subsp` / `var` / `f` 等种下标记的处理方式不同，后者会被吸收进物种名。

- 种下标记词（命中即**吸收**该词，并继续尝试取下一个词）：`sp`, `spp`, `cf`, `aff`, `subsp`, `ssp`, `var`, `fo`, `f`, `nothosubsp`, `x`, `×`
- 一般规则（按顺序判定，命中即执行并进入下一个词）：
  1. 该词命中停用词表 → **终止**
  2. 该词为种下标记词 → 吸收该标记；随后**至多再吸收一个词**（如 `sp. A-2019` 中的 `A-2019`），随即终止
  3. 该词首字母大写 → 吸收
  4. 该词首字母小写、**不在停用词表中**、且当前吸收结果长度 **< 2** → 吸收（兼容全小写 header，如 `salsola pellucida chloroplast`；长度阈值 2 同时防止小写噪声词被无限吞入）
  5. 其余情况（前两个词之外的小写普通词、数字开头词）→ 终止
- 硬上限：最多吸收 4 个词，防止畸形 header 吞掉整行
- 判定顺序至关重要：规则 1（停用词）**优先于**规则 4，否则小写停用词会被误吸收

**步骤 5 · 判据**：

- 吸收结果为空 → 提取失败，返回 `("", ("无法从 header 提取物种名",))`，调用方保留原 token 作为序列名
- 仅有 1 个词 → 接受（视为仅属名，如 `Salsola`），记 INFO
- 规范化交给 `naming.sanitize_species()`（见 §8.2）

**已核实的行为示例**：

| 输入 header（已剥离 accession） | 输出 `species_raw` |
|---|---|
| `Salsola pellucida chloroplast, complete genome` | `Salsola pellucida` |
| `UNVERIFIED: Salsola pellucida chloroplast, complete genome` | `Salsola pellucida` |
| `Salsola sp. A-2019 voucher Smith 123 chloroplast` | `Salsola sp. A-2019` |
| `Salsola cf. pellucida isolate 5 chloroplast` | `Salsola cf. pellucida` |
| `Salsola × tragus chloroplast, complete genome` | `Salsola × tragus` |
| `Salsola pellucida isolate 5 chloroplast, partial sequence` | `Salsola pellucida` |
| `Salsola` | `Salsola`（仅属名，记 INFO） |
| `chloroplast, complete genome` | 提取失败 → 异常清单 |

---

## 8. 命名规则引擎 `naming.py`

### 8.1 三种模式

| 模式 | 输出示例 | 规则 |
|---|---|---|
| `accession` | `ON929859.1` | 直接用完整登录号 |
| `species` | `Salsola_pellucida` | 用物种名；**渲染出的基名重复时追加 `_1` `_2` `_3`** |
| `accession_species` | `ON929859.1_Salsola_pellucida` | 登录号 + `_` + 物种名；**渲染出的基名重复时**才追加 `_1` `_2` `_3` |

另有 `keep`（不改名），仅在 pipeline 内部使用。

**关于流水号判据（用户使用后提出的调整）：** 流水号的唯一目的是**防止最终文件名撞车**，因此判据是
「该模式渲染出的基名是否会重复」，而**不是**「物种是否重复」。`accession_species` / `accession`
模式的基名以登录号开头，登录号天然唯一 ⇒ 基名不可能重复 ⇒ 加号纯属多余。旧判据按物种计数，
用户因此下载到 `MZ230595.1_Salsola_heptapotamica_3` 这种名字（同一物种有 3 条不同登录号的序列，
第 3 条被发了 `_3`）。原表格中「`accession_species` 同物种多条时追加 `_1` `_2` `_3`」一句即此调整的对象。

**关于 `species` 模式的重名保护（仍然有效）：** 若两个不同登录号属于同一物种，仅输出物种名会产生
两条**同名序列**，下游建树工具会报错或静默丢弃序列。因此 `species` 模式必须继续发号——它的基名里
没有登录号，不发号就真的会重名。判据同样是"渲染出的基名是否会撞车"，只是它恰好总在撞车。

真正的撞车（去重关闭时同一登录号出现两次、两条记录渲染出同一基名）仍然照常发号，
详见 §8.3。

### 8.2 名称规范化

**规范化必须拆成两个函数**，分别作用于名称的不同组成部分。原因：句点 `ON929859.1` 中是必须保留的版本号分隔符，而 `sp.` 中是应当删除的缩写标点——同一个字符在不同组成部分里的处理方式相反，用一个函数会导致登录号被破坏成 `ON9298591`。

**`sanitize_accession(text)` —— 用于登录号部分**

1. 所有空白（含全角空格、制表符）→ 删除（登录号内不应有空格）
2. 仅保留 `[A-Za-z0-9._-]`，其余字符一律删除
3. **句点保留**（版本号分隔符）

**`sanitize_species(text)` —— 用于物种名部分**

1. 所有空白（含全角空格、制表符）→ `_`
2. 杂交符号 `×`（U+00D7）→ `x`
3. **删除句点 `.`**（使 `Salsola sp. A-2019` 变成 `Salsola_sp_A-2019`，避免下游工具把点当扩展名分隔符）
4. 删除下列字符：`| , ; : ( ) [ ] { } " ' * ? < > / \`、反引号、以及 ASCII 控制字符
5. 连续 `_` 压缩为单个 `_`；去除首尾 `_`

**拼接后**

- 各组成部分先分别规范化，再以 `_` 连接，最后整体压缩一次连续 `_` 并去除首尾 `_`
- 保留 Unicode 字母数字与连字符 `-`（中文文件名合法），但**不含路径分隔符**
- 最终结果为空 → 回退为 `sequence_<批次内序号>`

### 8.3 流水号分配（两遍处理）

流水号依赖**整批数据**里"渲染出的基名"的频次，因此流程为：

1. 第一遍：读取全部输入，得到记录列表（去重之后）
2. 统计 `render_name(record, mode)`（**不带 serial 的基名**）的频次
3. 为每个基名维护计数器；按记录在批次中的出现顺序分配 `_1` `_2` `_3`（**稳定、可复现**），
   **只在频次 > 1 时才发号**
4. 第二遍：按 `name_map` 写出

> **判据变更（用户使用后提出的调整）**：原设计统计的是 `species_key(record)`，与命名模式无关。
> 那会让 `accession_species` 模式在其文件名根本不可能重复时也发号。现在计数键就是"该模式渲染出的
> 基名"，判据与实际文件名一一对应。

`species_key()` 仍作为公开 API 保留（物种分组统计另有用途），但**不再参与流水号分配**。

内存评估：叶绿体基因组场景（数百条 × 约 150 kb）总量为几十 MB，完全可接受。若记录数超过 20000 条，日志给出提示但仍继续。

### 8.4 异常与回退

- `accession` 为空 → 用原始 header 首个 token
- `species` 为空 → 该记录**不改名**，保留原 token，写入异常清单
- 最终名称仍为空 → `sequence_<批次内序号>`

---

## 9. 合并与去重语义 `pipeline.run_merge`

1. **展开输入**：文件按用户添加顺序；文件夹展开后的文件按**自然排序**（数字感知，`chr2` 在 `chr10` 之前）
2. **逐文件识别格式**（§7.1），不匹配的文件跳过并记日志
3. **逐记录解析**，`origin_path` / `origin_line` 如实记录
4. **去重**（`dedup="accession"` 时）：键为**完整登录号**（含版本号，统一转大写）。`ON929859.1` 与 `ON929859.2` 视为**两条不同记录**。保留首次出现者，被丢弃者写入日志（含两个来源文件路径）
5. **分配名称**（§8.3）
6. **写出**：`naming_mode="keep"` 时输出原始 header；否则输出 `name_map` 中的名称
7. **输出保护**：目标已存在 → 依次尝试 `<name>_1`、`<name>_2` … 并记日志说明实际写入路径
8. **返回 `ProcessResult`**：`records_in`、`records_out`、`duplicates_removed`、`skipped_files`、`warnings`、`output_path`

---

## 10. NCBI 客户端 `ncbi.py`

### 10.1 端点与查询构造

基址 `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`

| 用途 | 端点 | 关键参数 |
|---|---|---|
| 检索 | `esearch.fcgi` | `db=nuccore`、`retmode=json`、`usehistory=y`、`retmax` |
| 元数据 | `esummary.fcgi` | `db=nuccore`、`retmode=json`、`id` 列表 |
| 取序列 | `efetch.fcgi` | `db=nuccore`、`rettype=fasta`／`rettype=gbwithparts`、`retmode=text` |

查询词构造：

- 物种名：`"Salsola pellucida"[Organism]`
- 属名：`Salsola[Organism]`（会匹配所有 Organism 层级含该属的序列，即"该属下所有种"）
- 长度区间：`AND 100000:200000[SLEN]`
- 仅 RefSeq：`AND srcdb_refseq[prop]`
- "只要完整基因组"：**服务端没有可信字段**，只在客户端对 `DEFINITION` 做关键词匹配，大小写不敏感，命中下列任一子串即保留：

```
complete genome
complete chloroplast genome
complete plastid genome
complete mitochondrial genome
complete plastome
complete mitochondrial dna
```

  这样既不漏也不误：核对条件写在 `ncbi.py` 顶部的单一常量 `COMPLETE_GENOME_PATTERNS` 中，测试直接断言该常量，便于日后增补。

大结果集：用 `usehistory=y` 取 `WebEnv` + `QueryKey`，后续 `esummary` / `efetch` 通过 `query_key` + `retstart` 翻页。

### 10.2 限速、重试、合规

- 令牌桶限速：无 API key → 3 次/秒；有 key → 10 次/秒。**严格执行，不触碰 NCBI 封禁线。**
- 重试：网络异常与 5xx → 指数退避重试 3 次（间隔 1s / 2s / 4s）；HTTP 429 → 等待 `Retry-After` 或 5s 后重试
- 单条失败不中断整批，记入 `DownloadReport`
- 所有请求附带 `tool=seq_toolkit` + `email` + `api_key`
- 代理：`urllib.request.ProxyHandler`，来自设置
- 取序列用 **POST**，避免 id 列表过长超出 URL 长度上限
- 分批：`esummary` 每批 ≤500 个 id；`efetch` 每批 ≤200 条序列

### 10.3 下载产物组织

```
<输出目录>/
├─ ON929859.1.fa
├─ ON929859.1.gb
├─ MF123456.1.fa
├─ MF123456.1.gb
├─ all_sequences.fasta
└─ all_sequences.gb
```

- 勾选"套用命名规则"时，单文件名与合并文件内的序列名同时按 §8 规则生成
- 目标文件已存在且非空 → 跳过（可勾选"强制重下"覆盖）
- 每成功一条即落盘，取消或崩溃不丢失已下载内容
- 下载完成后弹出汇总：成功 / 跳过 / 失败条数，失败清单可导出

---

## 11. 并发模型（Tkinter 硬约束）

Tkinter 控件**只能在主线程更新**。任何网络或批量文件 IO 都不得在按钮回调里同步执行，否则窗口假死。

- **主线程**：仅处理界面事件与消息泵，通过 `root.after(100, self._poll_queue)` 周期消费队列
- **后台**：单个工作线程执行全部网络与文件 IO；通过 `queue.Queue` 回传三类消息：`Progress(done, total, text)`、`Log(level, text)`、`Done(result)` / `Failed(exc)`
- **取消**：`threading.Event`；工作线程在每批次边界与每条记录之间检查，可干净中断并保留已下载文件。取消响应应在 1 秒内
- **不做并发下载**：速度瓶颈在 NCBI 的速率限制而非本地并发；单线程顺序处理省去限速同步、进度竞态、取消逻辑三处 bug 来源
- 处理期间禁用会引发冲突的控件（开始按钮、输入选择），完成后恢复

---

## 12. 错误处理与日志 `applog.py`

- 三级日志：`INFO` / `WARN` / `ERROR`，界面滚动显示，可导出 `.log`
- **异常清单**独立表格：`文件`、`行号`、`原始 header`、`判定原因`、`最终采用的名称`，可导出 CSV
- **任何输出文件永不静默覆盖**（§9 步骤 7）
- 单条记录解析失败 → 记录 warning、跳过、继续处理其余，**绝不整批中断**
- 文件级失败（不存在、无权限、编码异常）→ 记入清单并继续下一个文件
- 所有路径与文件名使用显式 UTF-8；**中文路径与中文文件名在 Windows 上是经典坑，必须作为一等测试场景**
- 顶层异常处理器：未捕获异常写入 `%APPDATA%/seq_toolkit/crash.log` 并弹出可复制的错误对话框，而不是静默退出

---

## 13. 打包与分发

- `PyInstaller --onefile --windowed --name 序列工具箱`
- 通过 `--exclude-module` 显式剔除 `numpy`、`pandas`、`matplotlib`、`scipy`、`PIL`、`pytest` 等未被引入但可能被误收集的重量级模块，把体积压到 15-25 MB
- 提供 `build.spec` 以便复现；`README.md` 记录完整打包命令
- 自定义图标 `.ico`
- `--onefile` 冷启动需解压到临时目录，约 1-3 秒；同时给出 `--onedir` 配置作为启动速度优先的备选

---

## 14. 测试策略

### 14.1 pytest 单元测试（选择分层架构的核心收益）

| 测试文件 | 覆盖内容 |
|---|---|
| `test_format_detect.py` | 后缀与内容一致／冲突／都无法判定；`.gz`；自定义后缀列表 |
| `test_fasta_io.py` | 多行序列、CRLF、BOM、空文件、无记录、accession 格式可疑、非 IUPAC 字符、`.gz` |
| `test_genbank_io.py` | 多记录文件、`CONTIG` 记录跳过、`VERSION` 优先于 `ACCESSION`、`DEFINITION` 跨行拼接、`ORGANISM` 缺失回退链、`/organism=` 兜底、合成 GenBank 写出、**`raw_block` 原样保真（`FEATURES` 段逐字节不变）、改名只动 `LOCUS` 名称而 `ACCESSION`/`VERSION` 不变** |
| `test_naming.py` | 三种模式逐条断言、§7.4 表格中全部 8 个示例、流水号只在渲染基名撞车时分配（`species` 模式发号 / `accession_species` 与 `accession` 模式不发号 / 同一登录号两次仍发号）、`sanitize_accession` 保留版本号句点、`sanitize_species` 删除句点与 `×`→`x`、全角空格、标点、空结果回退 |
| `test_pipeline.py` | 混合格式输入合并、按登录号去重、自然排序、输出覆盖保护、`records_in/out` 计数正确 |
| `test_ncbi.py` | 用本地构造的假响应测查询词构造、限速时间间隔、重试次数、分页解析、429 处理。**不依赖真实网络** |

### 14.2 手工验收

GUI 层无自动化测试，提供手工清单：中文路径、大文件（>100 条记录）、取消操作、断网、输出目标已存在、勾选框组合。

---

## 15. 验收标准

实现完成须逐条验证：

1. 混合输入（`.fa` + `.fasta` + `.fna` + `.gbk` + 一个后缀错起的文件）合并后，输出记录数 = 去重后应有数，后缀错起的文件被正确识别
2. `>ON929859.1 Salsola pellucida chloroplast, complete genome` 在三种模式下分别得到 `ON929859.1`、`Salsola_pellucida`、`ON929859.1_Salsola_pellucida`
3. 同一物种两条记录：`species` 模式得到 `_1` `_2`（不重名）；`accession_species` 模式**不**加号，
   得到 `ON100001.1_Salsola_pellucida` 与 `ON100002.1_Salsola_pellucida`（登录号已保证唯一）。
   同一登录号出现两次（去重关闭）时，`accession_species` 模式仍得到 `_1` `_2`
   ——**判据是"渲染出的文件名是否会撞车"，不是"物种是否重复"**（用户使用后提出的调整）
4. §7.4 表格中全部 8 个示例的行为与表格一致；提取失败的记录出现在异常清单中且未被改名
5. 含 `CONTIG` 记录的多记录 GenBank 文件转 FASTA：`CONTIG` 记录出现在异常清单，其余全部导出，记录数吻合
6. 中文路径与中文文件名下全部功能正常
7. 检索 `Salsola`（属名）返回结果表；勾选 5 条下载 → 得到 5×(`.fasta` + `.gb`) + `all_sequences.fasta` + `all_sequences.gb`，且下载序列长度与结果表列出的长度一致。
   逐序列 FASTA 产物统一用 `.fasta` 后缀（原为 `.fa`，用户使用后提出的调整）；**读取侧不变**，
   `DEFAULT_FASTA_SUFFIXES` 继续接受 `.fa`/`.fna` 等老后缀。结果表的登录号还可批量导出为
   `.txt`（一行一个）或 `.csv`（带表头，列与表格一致）
8. 断网执行下载：给出明确错误提示与重试日志，程序不崩溃
9. 输出目标已存在时不覆盖，自动加后缀并在日志中说明
10. 处理过程中点击取消：1 秒内界面响应，已下载/已写出的文件保留完好
11. exe 体积 ≤ 25 MB，空载内存 ≤ 80 MB，冷启动 ≤ 3 秒
12. `pytest` 全绿
13. "重命名已有磁盘文件"的预览对照表与实际执行结果完全一致；同一 accession 的 `.fa` 与 `.gb` 副本不会互相覆盖
14. 全小写 header（如 `>AB123456.1 salsola pellucida chloroplast`）能正确提取物种名，不被误判为异常
15. **合并多个 GenBank 文件后，输出文件中的 `FEATURES` 段与原始输入逐字节一致**（CDS/rRNA/tRNA 注释无任何丢失）；执行改名后仅 `LOCUS` 名称字段变化，`ACCESSION` 与 `VERSION` 保持原值
16. 输出格式为 GenBank 但输入为 FASTA 时，合成记录包含 `LOCUS`/`ACCESSION`/`VERSION`/`DEFINITION`/`ORGANISM`/`ORIGIN`/`//` 且能被本工具自身重新正确解析（往返一致性）

---

## 16. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 物种名启发式在罕见 header 上出错 | 输出错误物种名，污染下游分析 | 不改名回退 + 异常清单人工复核（§8.4）；§7.4 示例表纳入回归测试 |
| NCBI 接口变更或限流 | 检索/下载不可用 | 全部集中在 `ncbi.py` 单模块；重试 + 明确报错；严格执行官方限速 |
| 国内网络直连 E-utilities 超时 | 功能不可用 | 内置代理设置（§FR-5） |
| PyInstaller exe 被杀毒软件误报 | 用户无法运行 | 同时提供 `--onedir` 版本；README 说明加白名单 |
| 大结果集导致表格卡顿或内存增长 | 界面无响应 | 显示上限 5000 行 + 提示用筛选缩小范围；`usehistory` 分页 |
| 输出文件被静默覆盖导致数据丢失 | 数据丢失 | §9 步骤 7 强制防覆盖 |
| Tkinter 在后台线程更新控件导致崩溃 | 随机崩溃 | 严格遵循 §11 队列消息泵 |

---

## 17. 附：需求到设计的映射

| 用户原始需求 | 对应设计 |
|---|---|
| 1. 合并 FASTA（多种后缀） | FR-1 + §7.1 + §9 |
| 2. 合并 GenBank（多种后缀） | FR-1 + §7.1 + §7.3 + §9 |
| 3. GenBank 转 FASTA | FR-1（输出格式=FASTA）+ §7.3 |
| 4. 按 `>` 行改名（三种方式，空格→`_`） | FR-2 + §7.4 + §8 |
| 5. GenBank 按 accession 与 ORGANISM 改名 | FR-2 + §7.3 物种名优先级 + §8 |
| 6. 按登录号下载 + 按物种/属检索批量下载 | FR-3 + FR-4 + §10 |
| 图形化、易操作 | §5、§11、§12 |
| 体积小、占用低 | §4、§13 |
