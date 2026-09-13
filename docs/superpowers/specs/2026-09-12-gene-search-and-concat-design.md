# 序列工具箱 · 周期 1 设计规格：按基因名检索下载、序列统计、序列拼接

| 项目 | 内容 |
|---|---|
| 日期 | 2026-09-12 |
| 状态 | 已通过分节评审，待用户复核书面规格 |
| 交付物 | 周期 1 源码 + pytest 测试 + 更新后的 README |
| 决策来源 | 与用户的头脑风暴（4 轮澄清 + 2 节设计确认 + 3 个实测探针） |
| 覆盖原始需求 | 功能 1（按基因名检索下载）、功能 3 的统计纯函数、功能 6（序列拼接） |
| 上游文档 | `docs/superpowers/specs/2026-09-11-seq-toolkit-design.md`（v0.1 规格） |

---

## 1. 背景与目标

v0.1 已交付「合并 / 转换、重命名 / 拆分、按物种检索下载、按登录号下载」。用户随后提出 8 项新功能，横跨四个子系统。经评估与拆解，8 项功能分成 **4 个交付周期**，每个周期独立走「规格 → 计划 → 实现 → 验收」闭环（路线图见 §13）。

**本规格只覆盖周期 1。**

周期 1 要解决的真实痛点：用户拿到一篇论文的物种列表后，需要为每个物种分别去 NCBI 找 ITS、matK、rbcL，逐个下载、逐个改名成 `物种_基因`，才能进入下游建树流程。这个过程现在必须手工完成，而且极易出错（下载到完整质体基因组当成 ITS 用、改名时把物种名写错、同一物种多条序列互相覆盖）。

### 成功标准

研究者把「物种列表 × 基因列表」粘进界面，点一次检索、勾选、下载，就得到一批文件名规范为 `<物种名>_<基因名>.fasta` 的序列文件，全程不打开命令行、不手工改名。并且：

- 每个（物种 × 基因）组合**命中 0 条**时必须明确告诉他，而不是给一张空表；
- 命中的**完整基因组记录**被排除时必须报数，而不是静默丢弃；
- 下载完成后**长度与 GC 含量**直接显示在结果表里，不需要另开工具核算。

---

## 2. 非目标（YAGNI，明确排除）

以下**不在**周期 1 范围内，实现阶段不得擅自加入：

- 序列浏览器、注释可视化与编辑（周期 2）
- 多条序列统计汇总表 + CSV 导出的**界面**（周期 2 由序列浏览器面板承载；周期 1 只交付 `stats.py` 纯函数与检索结果表的 GC 回填）
- 叶绿体四分体分析与 IR 反向操作（周期 3）
- MAFFT、R/V.PhyloMaker2、TNRS 集成（周期 4）
- 从完整基因组中**提取**目标基因区间（明确不做：见 FR-1.5）
- 并发/多线程检索（沿用现有令牌桶限速的串行实现）
- 自定义基因检索式编辑器（只允许手输基因名，不允许编辑检索子句）
- 修改 v0.1 的任何既有行为

---

## 3. 术语表

| 术语 | 含义 |
|---|---|
| 组合 | 一个（物种 × 基因）对，如 `Salsola pellucida × ITS` |
| 检索子句 | 追加在 `"<物种>"[Organism] AND ` 之后的 NCBI 检索式片段 |
| 规范基因名 | 内置基因表（§7.1）里的名字，如 `ITS`、`matK`。用于文件名 |
| 完整基因组记录 | definition 命中完整基因组模式，或长度 ≥ 100,000 bp 的记录（§7.3） |
| 最优一条 | 同一组合的多个候选中按「RefSeq 优先 → 长度最长 → 发布日期最新」选出的那一条（§7.4） |
| 子页 | 「检索与批量下载」标签页内嵌的子选项卡（§6.2 改动③） |

---

## 4. 运行环境与交付形式

与 v0.1 一致，无变化：

- 开发机：Windows，Python 3.12
- 目标机：Windows 10/11 x64，无需安装 Python 或任何依赖
- 交付：PyInstaller `--onefile --windowed` 单文件 exe
- **运行时零第三方依赖**：周期 1 新增代码全部使用 Python 标准库（`json`、`csv`、`re`、`dataclasses`、`tkinter`）
- 体积预期：周期 1 不引入任何新依赖，exe 体积不变（~10 MB，仍远低于 20 MB 目标）

---

## 5. 功能需求

### FR-1 按基因名检索与下载（覆盖原始需求 1）

#### FR-1.1 输入

- **物种列表**：多行文本框，一行一个物种学名；提供「从 FASTA/GenBank 导入物种名」按钮，复用 `naming.extract_species_from_header()` 与现有读取器
- **基因列表**：内置基因下拉框 + 「添加」按钮构成已选列表；支持直接手输基因名；已选项可删除。**每个已选项显示它将使用的检索子句**（形如 `ITS → "internal transcribed spacer"[All Fields]`），使检索前即可判断可靠性
- **组合预览**：实时显示 `N 物种 × M 基因 = K 个组合`；K > 50 时给出 WARN（每组合 2 次请求，50 组合约 35 秒），但不阻止执行

#### FR-1.2 检索式构造

1. 基因名先做**别名归一化**（大小写不敏感、忽略空格与连字符），命中内置表则使用其规范名与检索子句（§7.1）
2. 未命中内置表 ⇒ 按 `<输入>[All Fields]` 自由检索
3. 最终检索式 = `"<物种>"[Organism] AND <检索子句>`，物种名加引号精确匹配（与 `ncbi.build_query()` 的 species 范围同一约定）
4. 每个已选基因在其列表项里显示将使用的检索子句（见 FR-1.1），让用户在检索前就能判断检索可靠性；自由文本基因显示 `<输入>[All Fields]`

#### FR-1.3 不可检索的基因

内置表中标记为「无可用检索字段」的基因（trnL、trnL-F、psbA-trnH、rpl32-trnL 等）在界面上带 `⚠` 前缀。用户选中它们时：

- **不发起任何网络请求**
- 在结果区给出明确说明：该区间名在 GenBank 中没有可检索字段，实测多种写法命中均为 0，请在 NCBI 网站确认后再手工输入可用检索词
- 该组合计入「未检索到」汇总，**绝不返回一张空表**

#### FR-1.4 未命中组合的呈现

命中 0 条的组合**不进入结果表格**，而是：

- 在表格下方固定显示一行醒目汇总：`以下 3 个组合未检索到任何序列：Salsola pellucida × trnL-F、…`
- 同时写入日志（WARN）

理由：表格只放可操作的行，而未命中信息同样不得静默。

#### FR-1.5 完整基因组记录的排除

- 判据并联两条，**分别计数**：`ncbi.matches_complete_genome(definition)` 为真，或序列长度 ≥ 100,000 bp
- 被排除的记录不进入结果表
- 结果区固定显示汇总：`已排除 N 条完整基因组记录（其中 definition 命中 X 条、长度 ≥ 100 kb 的 Y 条）`，并列出前 5 个被排除的登录号供核对
- 同时写入日志（WARN）

**明确不做**：不下载完整基因组、不从中提取目标基因区间（决策见 §12 决策记录 D-3）。

#### FR-1.6 结果表

- 列（从左到右）：`选 | 物种名 | 基因 | Accession | 长度 | GC% | 来源 | 定义行`
- 无表头排序（沿用 `CheckboxTable`），行序固定为：物种名 → 基因 → 长度降序
- `长度` 来自 esummary 的 `slen`，检索阶段即可显示
- `GC%` 检索阶段为空，下载完成后回填（FR-1.9）
- `来源` 取 esummary 的 `sourcedb`（GenBank / RefSeq）
- 全选 / 反选 / 「已选 N / 共 M」计数

#### FR-1.7 选择策略开关

两种模式，用户可切换：

| 模式 | 行为 |
|---|---|
| **每个组合只取最优一条**（默认） | 结果表列出全部候选，但默认只勾选每个组合的最优一条 |
| **取全部候选** | 结果表列出全部候选并全部勾选 |

无论哪种模式，用户都可以在表里手动增减勾选。切换开关时按新模式重算默认勾选状态（会覆盖用户的手动修改，因此切换时记 INFO 日志说明）。

#### FR-1.8 下载

- 输出目录（复用现有设置项的默认值与 `FilePicker`）
- 格式：`☑ FASTA`（默认勾选）、`☐ GenBank`（可选项，走 `gbwithparts`）
- **按基因分组下载**：把勾选的行按基因分组，**每个基因调用一次 `NcbiClient.download()`**，该次调用的 `name_resolver` 绑定到这一个基因（`record → build_name(record 的物种名, 本组基因, 流水号)`）。这样命名解析不需要"登录号 → 基因"的反查表，天然避免了同一登录号在两个基因下无法区分的问题
- 复用 `NcbiClient.download()`：分批、逐条重试、NCBI 未返回记录的显式归因、原子写出、绝不静默覆盖、失败清单——**一行都不重写**
- 各组报告合并成一个：`succeeded`/`skipped`/`failed`/`total` 求和，`failures` 与 `records` 拼接；汇总复用 `widgets.format_download_summary()`，保持「计数单位为登录号」的既有口径
- 提供「打开输出文件夹」按钮

**已知限制（必须告知用户）**：同一条登录号若在多个基因组合中都被勾选，会被**分别下载并各写出一份文件**（如 `X_matK.fasta` 与 `X_rbcL.fasta`），两份文件的内容都是该记录的**完整序列**——本工具不做基因区间提取（决策 D-3）。出现这种情况时记 WARN 并在结果区提示，用户可通过结果表的「定义行」列识别这类多位点记录。

#### FR-1.9 GC 回填

下载完成后：

- 用 `DownloadReport.records`（§6.2 改动②）在内存里对每条记录调用 `stats.sequence_stats()`
- 按登录号匹配回填结果表对应行的 `GC%` 列
- 未下载的行（未勾选）保持空白，不臆造数据

#### FR-1.10 命名规则

- 特定基因：`<物种名>_<规范基因名>.fasta`，例如 `Salsola_pellucida_ITS.fasta`
- 物种名复用 `naming.sanitize_species()`（空白 → 下划线、去标点、`×` → `x`），与既有三种命名模式**同源**，不另写一套规范化
- 基因名使用内置表的规范名；手输基因名按「空白 → 下划线」处理
- 同一组合有多条被勾选时，按**首次出现顺序**追加流水号 `_2`、`_3`…（不复用 `build_name_map`：它的判据是"渲染出的基名是否撞车"，而这里基名由检索上下文而非记录字段决定）
- 文件名与文件内序列名**逐字一致**（与 `pipeline.split_records` 的既有约定相同）

**已作废的需求原句**：原始需求中「完整叶绿体/线粒体基因组：沿用现有三种命名模式」在基因检索模式下不适用——完整基因组记录已被 FR-1.5 排除。需要完整基因组时走「按物种检索」子页，那里原生支持三种命名模式（决策记录 D-2）。

---

### FR-2 序列统计 `stats.py`（覆盖原始需求 3 的计算部分）

#### FR-2.1 定义

```
length   = len(seq)                       # 含全部字符
gc_count = count(G) + count(C)            # 仅 G/C
at_count = count(A) + count(T)            # 仅 A/T
n_count  = count(N)                       # 仅 N
gc       = gc_count / (gc_count + at_count) * 100   # 分母不含 N 与其它 IUPAC
at       = at_count / (gc_count + at_count) * 100
n_ratio  = n_count / length * 100
```

- **GC/AT 的分母是 A+T+G+C，不含 N 与其它 IUPAC 模糊代码**（R、Y、S、W、K、M、B、D、H、V）。理由：若分母含 N，一条 50% N 的序列 GC 会被腰斩，序列之间失去可比性
- 因此恒有 `gc + at == 100.00`（在分母非 0 时）
- **`n_count` 只数 `N`，不含其它 IUPAC 代码**（按需求原文"模糊碱基（N）"理解）。因此当序列含 R/Y/S/W/K/M/B/D/H/V 时，会出现 `length > A+T+G+C+N` ——这是刻意设计，不是漏算；界面上的四个数字不保证相加等于长度，规格里写明以免用户误以为数据出错
- 大小写不敏感（序列读取时已转大写，但函数自身也做处理）
- 百分比保留两位小数（四舍五入）

#### FR-2.2 边界

| 情况 | 行为 |
|---|---|
| 序列为空 | `length=0`，`gc`/`at`/`n_ratio` 为 `None`（未定义，界面显示 `—`），不抛异常、不产生 `ZeroDivisionError` |
| 全部是 N 或全是 IUPAC 模糊代码 | 分母为 0 ⇒ `gc`/`at` 为 `None`，`n_ratio` 正常计算 |
| 含 U（RNA） | 不计入 A/T/G/C 任一计数，`U` 不是 IUPAC DNA 代码；不报错 |

#### FR-2.3 接口

纯函数、无 IO、无全局状态：

```python
@dataclass(frozen=True)
class SeqStats:
    length: int
    gc: float | None
    at: float | None
    n_count: int
    n_ratio: float | None

def sequence_stats(seq: str) -> SeqStats: ...
def format_stats(stats: SeqStats) -> tuple[str, str, str, str]: ...   # 界面用的四个字符串
```

---

### FR-3 序列拼接（覆盖原始需求 6）

#### FR-3.1 输入与列表

- 添加文件 / 添加文件夹（复用 `format_detect.list_input_files()`），每条记录一行
- 列表列：`序 | 序列名 | 长度 | GC% | 来源文件`
- 行操作按钮：上移 / 下移 / 置顶 / 置底 / 删除 / 清空

#### FR-3.2 合并规则

- 按列表当前顺序**首尾相接**
- 间隔序列：默认 `NNNNNN`，可改为任意字符串；提供「无间隔」选项（空字符串）
- header：默认 `merged_sequence`，可编辑
- 输出格式：FASTA（复用 `write_fasta()`，换行宽度跟随现有设置项 `wrap`）
- **实时预览**：合并后长度 = `Σ 各序列长度 + 间隔长度 × (条数 − 1)`，随顺序、间隔、增删即时更新

#### FR-3.3 输出与提示

- 输出路径由用户指定；已存在时走 `pipeline.resolve_output_path()` 追加 `_1` 并 WARN（与 v0.1 的「绝不静默覆盖」语义一致）
- 界面上固定显示一句提示：**间隔序列会被下游建树工具当作序列内容**，请确认是否需要
- 列表为空时点「开始拼接」⇒ 明确提示「请先添加序列」，不产生空文件

---

## 6. 架构

### 6.1 新增文件（5 个，全部独立模块）

| 文件 | 类型 | 职责 | 依赖 |
|---|---|---|---|
| `seq_toolkit/stats.py` | 纯函数 | 序列统计（FR-2） | 无 |
| `seq_toolkit/gene_query.py` | 纯函数 | 基因表、别名归一、检索式构造、完整基因组判据、组合展开、命名表构造 | `model`、`naming`、`ncbi`（只用 `matches_complete_genome`） |
| `seq_toolkit/concat.py` | 纯函数 | 拼接序列、间隔、header、长度计算 | `model` |
| `seq_toolkit/gui/tab_gene.py` | UI | 「按基因检索」子页 | `gene_query`、`stats`、`ncbi`、`widgets` |
| `seq_toolkit/gui/tab_concat.py` | UI | 「序列拼接」标签页 | `concat`、`widgets`、`pipeline`、`fasta_io`、`format_detect` |

**纯函数与 UI 分离**：`stats.py` / `gene_query.py` / `concat.py` 不 import `tkinter`，全部逻辑可用 pytest 离线验证——这是 v0.1 已验证的分层收益，周期 1 沿用。

### 6.2 对既有文件的增量改动

**①–④ 已获用户批准；⑤ 与 ⑥ 是编写规格与实现计划时发现、且为正确性所必需的改动，尚未逐条确认，请重点复核。**

| # | 文件 | 改动 | 为什么非改不可 | 风险 |
|---|---|---|---|---|
| ① | `ncbi.py` | `DownloadOptions` 增加 `name_resolver: Callable[[SequenceRecord], str] | None = None`；`download()` 的建名字表处改为「有 resolver 用之，否则调用 `build_name_map`」；`_pending_accessions()` 的预跳过判据追加 `and options.name_resolver is None` | `物种_基因.fasta` 无法用现有命名引擎表达（`render_name` 只看记录字段，基因名只存在于检索上下文）。resolver 由 `tab_gene` **按基因绑定**（FR-1.8） | 零：默认 None 时执行路径与现在逐字节相同 |
| ② | `ncbi.py` | `DownloadReport` 增加 `records: list[SequenceRecord] = field(default_factory=list)`，`download()` 填入 `collected` | FR-1.9 的 GC 回填需要在内存里拿到刚下载的记录 | 零：新增字段带默认值；周期 4 的「比对结果送浏览器」也会用到 |
| ③ | `gui/tab_search.py` | 页面顶部包一层 `ttk.Notebook`，原检索流程整体作为第一个子页，新子页调 `tab_gene.build_subpanel(frame, app)` | 用户选定方案 B（内嵌子选项卡） | 既有代码不移动、不重写，只是换了父容器；首个子页的行为与现在完全一致 |
| ④ | `gui/app.py` | `TAB_SPECS` 增加一行 `("序列拼接", tab_concat)` | 这是全项目唯一的标签页注册点 | 一行元组 |
| ⑤ | `gui/widgets.py` | `CheckboxTable` 增加可选参数 `key_of: Callable[[tuple], str] | None = None`：提供时行 iid 与 `RowSelection` 的键改用它，显示值不变 | **不加会出现静默丢行**：`CheckboxTable.set_rows()` 用行首元素当 iid 并按 key 静默去重，而本表首列是物种名（必然重复）。改为「首列放 accession」也不行——一条 `matK gene, partial cds; rbcL gene, complete cds` 形式的双位点记录会在 matK 与 rbcL 两次检索中各出现一次，同一 accession 两行，仍会被静默丢掉一行 | 零：默认 None 时行为与现在完全相同 |

**若 ⑤ 不被接受**，退化方案是：首列放 accession（牺牲"物种名在前"的可读性），并在 `tab_gene` 侧对同一 accession 出现在多个基因的情况显式跳过重复行并记 WARN（不静默）。功能不受影响，但界面可读性与复用性都更差，且该隐患在周期 2 的注释列表里会再次出现。

| # | 文件 | 改动 | 为什么非改不可 | 风险 |
|---|---|---|---|---|
| ⑥ | `ncbi.py` | 新增 `search_raw(query: str, retmax: int = 500) -> tuple[SearchResult, list[SeqSummary]]`；把 `search()` 里解析 esearch 响应的那段**原样抽出**为静态方法 `_parse_esearch()`，`search()` 与新方法共用 | 既有 `search()` / `search_summaries()` 只接受**检索词**并由 `build_query()` 拼成 `"<词>"[Organism]`，基因子句（`matK[Gene]`）没有位置可放——不加这个方法，"按基因检索"会退化成"按物种检索"，功能 1 整体失效 | 抽方法是行为保持的重构（解析逻辑一行未改），既有 `test_ncbi.py` 的 `search()` 用例必须仍然全绿；新方法纯增量 |

其余模块 `naming.py`、`model.py`、`pipeline.py`、`genbank_io.py`、`fasta_io.py`、`settings.py`、`applog.py`、`format_detect.py`、`textio.py` **不做任何改动**。

### 6.3 界面集成

```
App (tk.Tk)
└─ ttk.Notebook                      ← app.py TAB_SPECS
   ├─ 合并 / 转换                      (v0.1，不动)
   ├─ 重命名 / 拆分                    (v0.1，不动)
   ├─ 检索与批量下载                    ← 改动③：顶部包一层子 Notebook
   │   ├─ 按物种 / 属名检索             (v0.1 原流程，整体搬入，逻辑不变)
   │   └─ 按基因检索                    ← tab_gene.build_subpanel()
   ├─ 按登录号下载                      (v0.1，不动)
   ├─ 序列拼接                         ← 改动④：新增标签页
   └─ 设置                            (v0.1，不动)
```

### 6.4 数据流（基因检索模式）

```
物种列表 + 基因列表
  └─ gene_query.expand_combinations() → [(物种, 基因, 检索子句)]
       └─ 每个组合：NcbiClient.search_summaries()          ← 复用限速/重试/代理/取消
            └─ gene_query.classify_hits()                  ← 排除完整基因组并分别计数
                 └─ CheckboxTable 展示 + 默认勾选规则
                      └─ 勾选 → 按「基因」分组 → {基因: [该组被勾选的登录号]}
                           └─ 对每个基因：NcbiClient.download(该组登录号, options, progress)
                                ├─ options.name_resolver = 绑定到本基因的命名函数   ← 改动①
                                └─ DownloadReport.records                          ← 改动②
                                     └─ 各组报告合并 → stats.sequence_stats() → 回填 GC% 列
```

按基因分组下载的理由：命名解析只依赖记录本身（物种名）与本组基因，**不需要**"登录号 → 基因"的反查表；而那条反查表在「同一登录号同时命中两个基因」（双位点记录）时无解。分组后同一登录号在两组里各写一份，行为明确且可解释。

全程在 `BackgroundWorker` 的后台线程内执行，进度、取消、日志、异常清单全部复用现成机制；UI 线程不阻塞。

---

## 7. 检索式与命名规则

### 7.1 内置基因表

**只收录已实测有效的检索式。**标定方法：对 3–5 个代表物种（覆盖稀有物种与常见物种）各跑一次 esearch 并记录命中数，命中数为 0 的检索式不得进入内置表。

已实测（2026-09-12，探针 `gene_query_probe.py`）：

| 规范名 | 检索子句 | Salsola pellucida | 拟南芥 | 烟草 | 状态 |
|---|---|---|---|---|---|
| `ITS` | `"internal transcribed spacer"[All Fields]` | 3 | 28 | 41 | ✅ 已验证 |
| `matK` | `matK[Gene]` | 3 | 43 | 20 | ✅ 已验证 |
| `rbcL` | `rbcL[Gene]` | 4 | 50 | 28 | ✅ 已验证 |
| `ITS1` | `"internal transcribed spacer 1"[All Fields]` | — | — | — | ⏳ 实现首步标定 |
| `ITS2` | `"internal transcribed spacer 2"[All Fields]` | — | — | — | ⏳ 实现首步标定 |
| `ndhF` | `ndhF[Gene]` | — | — | — | ⏳ 实现首步标定 |
| `ycf1` | `ycf1[Gene]` | — | — | — | ⏳ 实现首步标定 |
| `trnL`、`trnL-F`、`psbA-trnH`、`rpl32-trnL` | — | 0 | 0 | 0 | ⛔ 无可用检索字段 |

**标定不通过的处理**：某基因若在全部标定物种上命中均为 0，则不进入内置表的下拉可选分组——用户仍可手输该基因名走自由文本检索，界面上显示 `<输入>[All Fields]` 并在结果为空时提示"该基因名没有内置检索式，请确认检索词"。**绝不允许**一个命中恒为 0 的检索式长期留在内置表里冒充"该物种没有这个基因"。

**关键反直觉结论（实测得出）**：`ITS[Gene]` 在三个物种上命中**全部为 0**，`ITS[All Fields]` 也几乎为 0。ITS 只能通过 `"internal transcribed spacer"` 这个短语检索。若按直觉用 `ITS[Gene]`，功能 1 对 ITS 会完全失效。

### 7.2 别名归一化

归一化键 = 输入转小写、删除空格与连字符，再查表：

| 用户可能输入 | 归一化键 | 解析为 |
|---|---|---|
| `ITS`、`its`、`I.T.S` | `its` | ITS |
| `internal transcribed spacer` | `internaltranscribedspacer` | ITS |
| `matK`、`matk`、`mat K` | `matk` | matK |
| `rbcL`、`rbcl`、`rbc-l` | `rbcl` | rbcL |
| `trnL-F`、`trnlf`、`trnL F` | `trnlf` | trnL-F（⛔ 不可检索） |

未命中任何内置条目 ⇒ 视为自由文本基因名，检索子句 = `<原输入>[All Fields]`。

### 7.3 完整基因组判据

```python
def is_complete_genome(definition: str, length: int) -> tuple[bool, str]:
    """返回 (是否排除, 命中的判据名)。判据名用于分别计数与日志归因。"""
    if matches_complete_genome(definition):      # 复用 ncbi.py 现有函数
        return True, "definition"
    if length >= COMPLETE_GENOME_MIN_LENGTH:     # 100_000
        return True, "length"
    return False, ""
```

两条判据的理由：`matches_complete_genome()` 匹配 definition 里的 `complete genome` / `complete chloroplast genome` 等模式；而部分记录的 definition 措辞不规范（如 `xxx plastid, complete sequence`），长度判据兜底。两者**分别计数**上报，便于用户判断是哪条规则起了作用。

### 7.4 最优一条与命名

**最优一条的排序键**（降序优先级）：

1. `source_db == "RefSeq"` 优先（RefSeq 记录经过人工审校，且登录号稳定）
2. 序列长度最长（基因序列越长通常越完整，`partial cds` 更短）
3. 发布日期最新

**命名构造**：

```python
def build_name(species: str, gene: str, serial: int | None) -> str:
    base = f"{sanitize_species(species)}_{sanitize_gene(gene)}"
    return f"{base}_{serial}" if serial else base
```

- `sanitize_gene()`：内置规范名直接使用（保留 `matK`、`rbcL` 的大小写）；手输名按「空白 → 下划线」处理，并删除文件系统非法字符
- 流水号只在同一组合出现多条时追加，按首次出现顺序从 `_2` 开始（第一条不加号）——与 `build_name_map` 的既有约定一致
- 文件名与文件内 FASTA header **逐字一致**

---

## 8. 并发与错误处理

### 8.1 并发模型

沿用 v0.1 的硬约束：**所有网络与磁盘操作在 `BackgroundWorker` 的后台线程里执行**，通过 `queue.Queue` 把进度/日志/结果送回主线程；Tk 控件只在主线程被触碰。周期 1 不引入任何新的并发原语。

- 进度：`progress(done, total, text)`，total = 组合数（检索阶段）或登录号数（下载阶段）
- 取消：`cancel_event` 在组合之间、批次之间被检查；取消是 `OperationCancelled`，不是错误
- 一次任务未结束时再次点击「开始」⇒ 复用 `App.run_job()` 的既有拒绝逻辑（非模态提示 + 状态栏）

### 8.2 错误场景与处理

| 场景 | 处理 |
|---|---|
| 网络不可达 / DNS 失败 | `NcbiClient._request` 的既有重试（3 次退避）后抛 `NcbiError`；本次组合记 ERROR 并继续下一个组合，不中断整批 |
| 单个组合检索失败 | 记 ERROR + 日志，该组合计入「检索失败」计数，与「未检索到」分开统计 |
| HTTP 429 限流 | 由既有 `NcbiClient` 处理（读 `Retry-After`，退避重试） |
| 全部组合都检索失败 | 结果表为空 + 明确提示「全部 N 个组合检索失败，请检查网络或代理设置」 |
| 全部命中都是完整基因组 | 结果表为空 + 明确提示「命中的 M 条记录全部是完整基因组记录，已按规则排除」 |
| 输出目录不可写 / 磁盘满 | 由 `download()` 的既有原子写出与失败清单处理，失败登录号计入 `failures` |
| NCBI 未返回某个登录号 | 由既有 `download()` 显式归因（`MISSING_RECORD_REASON`） |
| 物种名格式非法（属名小写、含数字等） | 不阻止检索（NCBI 容错），但结果为空时提示检查拼写与属名首字母大小写 |
| 同一登录号在多个基因组合中都被勾选 | 按基因分组各写一份（FR-1.8），记 WARN 并在结果区提示"该记录同时命中 N 个基因，已各写一份，文件内容为完整记录序列" |
| 某组登录号全部写出失败 | 该组报告并入总报告，失败登录号与原因逐条列出（不进静默） |

原则与 v0.1 一致：**单条失败不中断整批；任何跳过的数据都必须出现在日志或界面里，绝不静默。**

---

## 9. 测试策略

### 9.1 离线单元测试（pytest）

| 模块 | 用例 |
|---|---|
| `stats.py` | 只统计 ATGC（含 N/R/Y 的序列 GC 分母不含它们）；空序列 ⇒ `None` 不抛异常；全 N ⇒ `gc`/`at` 为 `None`；含 U 不计入；大小写混合；`gc + at == 100.00`；舍入边界（1/3 → `33.33`） |
| `gene_query.py` | 别名归一（`its`/`internal transcribed spacer`/`mat K`）；组合展开顺序与去重；`is_complete_genome` 用真实 definition 字符串（`Nicotiana tabacum plastid, complete genome.` ⇒ 排除且判据为 definition；`Salsola pellucida matK gene, partial cds` ⇒ 保留；definition 不含关键词但长度 155,943 ⇒ 排除且判据为 length）；最优一条排序；命名构造与流水号 |
| `concat.py` | 顺序拼接；有/无间隔；长度 = Σ + 间隔 × (n−1)；空列表；单条；header 传递 |

### 9.2 GUI 测试（复用 `tests/test_gui_tabs.py` 的既有模式）

- 「按基因检索」子页能在 `App` 上构建，控件齐备，不抛异常
- 选择策略开关切换时默认勾选状态随之变化
- 「序列拼接」面板的上移/下移/删除改变列表顺序，预览长度同步更新
- 空列表点「开始拼接」给出提示且不写文件

### 9.3 集成测试（注入假 opener，完全离线）

- 全流程：假 esearch → 假 esummary → 假 efetch → 结果表行数正确 → 勾选 → 下载 → 文件名与文件内 header 正确、内容正确
- 完整基因组被排除并计入报告（判据分别计数）
- 组合命中 0 条 ⇒ 进入「未检索到」汇总，不产生表格行
- 下载完成后 GC 列被正确回填，未勾选的行保持空白
- 同组合两条都勾选 ⇒ 产出 `X_ITS.fasta` 与 `X_ITS_2.fasta`

### 9.4 顺带修复的既有失败测试

`tests/test_ncbi.py::test_adjacent_requests_hold_the_interval_with_the_default_clock` 在本机稳定失败，实测缺口为 **1.94e-11 秒**（三次运行一致）：

```
gaps = ['1.0', '0.3333333333139308']   min - 1/3 = -1.9402535134105392e-11
```

根因是断言零容差，而该用例用「真实单调时钟 + 仅记录型 sleeper」重建时间轴，重建值与限速器内部使用的 `_clock_source() + _clock_credit` 之间存在浮点/计量残差。**不是限速功能缺陷**——同一场景注入假时钟的版本（`test_adjacent_requests_hold_the_interval_with_an_injected_clock`）精确通过。

处理：给该断言加容差（`>= 1/3 - 1e-9`）并注明理由。否则「测试全绿」无法作为新功能的回归闸门。

### 9.5 真实联网验证（手动、一次性，不进 CI）

用 `Salsola pellucida × {ITS, matK, rbcL}` 与 `Nicotiana tabacum × ITS` 实跑，核对文件名、条数、GC 值与排除计数。

---

## 10. 验收标准

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | `Salsola pellucida × ITS` 检索 | 命中 3 条；排除完整基因组后仍 ≥ 1 条；产出 `Salsola_pellucida_ITS.fasta`，文件内 header 与文件名一致 |
| 2 | `Nicotiana tabacum × ITS` 检索 | 命中 41 条；完整质体基因组记录被排除并在汇总中报数，日志有 WARN |
| 3 | 选中 `trnL-F` | 不发起任何网络请求；给出「无可用检索字段」说明；计入未检索到汇总 |
| 4 | `Salsola pellucida × {NOTAGENE, matK}`（`NOTAGENE` 是刻意编造的、必然无命中的基因名） | 表格无 `NOTAGENE` 行，表格下方出现「以下 1 个组合未检索到任何序列：Salsola pellucida × NOTAGENE」 |
| 5 | 「取全部候选」模式下同一组合勾选两条 | 产出 `X_ITS.fasta` 与 `X_ITS_2.fasta`，内容分别对应各自登录号 |
| 6 | 下载完成后 | 结果表 GC% 列被回填且与手工核算一致；未勾选行保持空白 |
| 7 | 拼接 3 条序列 + 6 个 `N` 间隔 | 预览与产物长度 = Σ + 12；调整顺序后产物内容按新顺序拼接 |
| 8 | 拼接输出文件已存在 | 不覆盖，追加 `_1` 并 WARN |
| 9 | 回归 | `python -m pytest -q` 全部通过（含 §9.4 修复） |
| 10 | 打包 | `build_exe.bat` 产出的 exe 能启动，新标签页可见，无新增依赖导致的 `ModuleNotFoundError` |

---

## 11. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 内置检索式在未标定基因上命中 0 | 用户以为"这个物种没有该基因" | §7.1 强制标定；未标定的不进内置表；结果表显示实际检索子句 |
| 物种名拼写变体导致命中 0 | 同上 | 结果为空时提示检查拼写与属名首字母大小写（NCBI 侧无法自动纠正，TNRS 清洗是周期 4 的能力） |
| 组合数过大导致检索时间过长 | 用户以为程序卡死 | 组合 > 50 时 WARN；进度条按组合数显示；随时可取消 |
| 「完整基因组判据」误杀 | 真实基因序列被排除 | 两条判据分别计数并列出被排除的前 5 个登录号，用户可立即发现误杀；判据阈值集中在 `gene_query.py` 常量，调整只需改一处 |
| 改动 ⑤ 影响既有检索页 | v0.1 检索结果表行为变化 | `key_of` 默认 `None` 时逐字节等价；既有 `test_gui_widgets.py` 必须保持通过 |

---

## 12. 决策记录

| # | 决策 | 结论 | 依据 |
|---|---|---|---|
| D-1 | 基因检索界面挂在哪 | 方案 B：既有「检索与批量下载」页内嵌子选项卡，新逻辑全部放 `tab_gene.py` | 同时满足用户的选项卡规划与"不改原有逻辑"约束 |
| D-2 | 完整基因组在基因模式下是否下载 | 排除，并显式报告排除数；原始需求中"完整基因组沿用三种命名模式"一句作废 | 用户裁决（原需求内部冲突：既要求排除又要求命名） |
| D-3 | 命中的完整基因组是否切出目标基因 | 不切 | 许多记录里目标基因根本没有注释，切取会大量失败且失败方式难以向用户解释 |
| D-4 | GC 何时计算 | 检索阶段只显示长度；下载完成后用内存中的记录回填 GC | esummary 的 27 个字段里没有任何 GC/碱基组成字段（实测确认），提前算需额外一轮 efetch |
| D-5 | 检索结果表的 GC 分母 | A+T+G+C，不含 N 与其它 IUPAC | 分母含 N 会让高 N 序列的 GC 失去可比性 |
| D-6 | 选择策略默认值 | 「每个组合只取最优一条」 | 建树/条形码场景是主要用途；需要全部候选时一个开关即可切换 |
| D-7 | 「序列信息」汇总表与 CSV 导出 | 周期 1 不做界面，只交付 `stats.py` 纯函数 | YAGNI：该表归属周期 2 的序列浏览器面板，现在建等于建一个马上要搬走的临时面板 |

---

## 13. 后续周期路线图（不在本规格范围内）

| 周期 | 覆盖功能 | 前置 |
|---|---|---|
| **2** | 功能 2（序列浏览器与注释编辑）+ 功能 3 的完整界面（多条序列汇总表 + CSV 导出） | 无 |
| **3** | 功能 4（叶绿体四分体分析与 IR 反向操作） | 周期 2 的可视化与注释模型 |
| **4** | 功能 5（MAFFT）+ 功能 7（V.PhyloMaker2）+ 功能 8（TNRS） | 无（三者共用一套"外部依赖"骨架） |

---

## 14. 附录 A：探针实测证据（2026-09-12）

本规格涉及的事实性断言全部来自实测，探针脚本为一次性产物（位于 `%TEMP%\seq-probe`，不属于交付物）。

### A.1 基因检索式（`gene_query_probe.py`，影响 §7.1）

见 §7.1 表格。另外两条：

- `ITS[Gene]` 在三个物种上命中**全部为 0**；`ITS[All Fields]` 为 `0 / 1 / 0`
- `trnL-F[All Fields]`、`"trnL-F"[All Fields]`、`(trnL OR trnF)[All Fields]` 在三个物种上**全部为 0**
- 物种记录总量差异极大：`Salsola pellucida` 全库 **9 条**，拟南芥 **2,706,728 条**，烟草 **1,906,298 条**——「先取该物种全部再本地筛」的策略对常见种不可行

### A.2 完整基因组检索式的坑（`diag_search.py`，影响 §7.3 与既有 `ncbi.py`）

质体基因组的 GenBank 标题形如 `Nicotiana tabacum plastid, complete genome.`，**不含** `complete chloroplast genome` 这一连续短语：

```
"Nicotiana tabacum"[Organism] AND ("complete chloroplast genome"[Title] OR "complete plastid genome"[Title])  → 0
"Nicotiana tabacum"[Organism] AND chloroplast[Title] AND complete[Title]                                        → 89
```

结论：`ncbi.matches_complete_genome()` 之所以仍能用，是因为它的模式表里另有更短的 `complete genome`；新增检索式时不得依赖长短语。

### A.3 叶绿体 IR 边界识别（`ir_probe.py`，影响周期 3）

以 8 个真实质体基因组实测（k-mer 反向互补投票 + 精确匹配前缀）：

| 基因组 | 长度 | 路线B 结果 | 对答案 |
|---|---|---|---|
| 拟南芥 NC_000932 | 154,478 | LSC 84,170 / IR 26,264 | 文献值，**0 bp 误差** |
| 水稻 NC_001320 | 134,525 | LSC 80,592 / IR 20,799 | 文献值，**0 bp 误差** |
| 烟草 NC_001879.2 | 155,943 | LSC 86,686 / IR 25,343 | 记录自带 JLB/JSB/JSA 注释，**0 bp 误差** |
| 菟丝子 NC_052920 | 86,727 | LSC 50,956 / IR 14,354 | repeat_region 注释对，**0 bp 误差** |
| 桉树 NC_014570 | 160,137 | LSC 88,872 / IR 26,395 | 注释差 −4/+5 bp，但**注释本身不铺满全序列**，路线B 铺满 |
| 黑松 NC_001631 | 119,707 | 拒绝（944 票） | 无 IR，**正确拒绝** |
| 蒺藜苜蓿 NC_003119 | 124,033 | 拒绝（54 票） | IRL clade 单拷贝，**正确拒绝** |
| 豌豆属 Pisum abyssinicum NC_037830 | 122,174 | 拒绝（54 票） | 豆科 IR-lacking clade，单拷贝，**正确拒绝** |

**必须写进周期 3 规格的三条**：

1. **`repeat_region` 注释不可信**。烟草 NC_001879.2 把 LSC（`1..86686`）标成 `/rpt_family="IRB"`、把 SSC（`112030..130600`）标成 `/rpt_family="IRA"`。用户原方案中"读 repeat_region 定位 IR"这条路，在用户自己指定的验证材料上会给出错误答案
2. **判据余量极大**：真 IR 票数 28,662–52,744、领先次峰 472–3,767 倍；无 IR 者 54–944 票、领先 1.01–1.9 倍
3. **只能用精确匹配前缀当 IR 长度**：容忍错配的延伸会滑进 SSC 多吃 200–400 bp（烟草 25,343 → 25,718）

性能：单基因组 86–177 ms，纯标准库。

### A.4 TNRS API 契约（`p2_tnrs.py`，影响周期 4）

- `POST https://tnrsapi.xyz/tnrs_api.php`，`Content-Type: application/json`
- 请求体 `{"opts": {sources, class, mode, matches}, "data": [[id, name], …]}`
- `data` **恰好 2 列**：第 1 列整数 ID，第 2 列学名；科名可选，写法为 `"<科名> <学名>"` 且必须以 `-aceae` 结尾
- 响应 **46 个字段**，需要的是：`ID / Name_submitted / Name_matched / Overall_score / Accepted_name / Accepted_name_rank / Family_matched / Source / WarningsEng / Unmatched_terms`
- 坑：① 未匹配的标记是字面量 `"[No match found]"`，得分是**空字符串**而非 0；② `matches=all` 会让一个名称返回多行（2 个名称返回 4 行），表格必须按 ID 聚合；③ `mode=parse` 返回**另外 13 个完全不同的字段**；④ 超限是 **HTTP 413 `exceeds 5001 row limit`**（不是文档所写的 5,000），必须分批
- 实测耗时：单次请求 0.8–1.0 秒

### A.5 R 与 V.PhyloMaker2（`p2_phylo.R`，影响周期 4）

本机已装 R 4.6.1（用户级，`%LOCALAPPDATA%\Programs\R\R-4.6.1`，190 MB，无需管理员）与 `V.PhyloMaker2 0.1.0`（依赖仅 `ape`，Windows 二进制包，无需编译工具链）。端到端实测：

- 命名系统是 **LCVP（73,420 种）/ TPL（74,529 种）/ WP（72,570 种）**，**不是** APG III / APG IV
- R 脚本必须显式 `data(GBOTB.extended.TPL)`：数据集为 lazy-load，`Rscript` 下不显式载入会抛 `object 'GBOTB.extended.TPL' not found`
- `phylo.maker()` 7 个物种耗时 **17.78 秒** ⇒ 必须后台线程
- **未匹配的物种只打印一行 `Note: 1 taxa fail to be binded to the tree` 然后被静默丢弃**（7 个输入 → 6 个叶节点，不报错）⇒ 必须捕获并向用户报告
- `sp.list` 需要 `species` / `genus` / `family` 三列

---

## 15. 附录 B：需求到设计的映射

| 原始需求条目 | 本文档位置 | 状态 |
|---|---|---|
| 功能 1 增加"按基因名检索"模式 | FR-1.1 – FR-1.10 | ✅ 本周期 |
| 功能 1 基因名下拉 + 手输 | FR-1.1、§7.1、§7.2 | ✅ 本周期 |
| 功能 1 结果表格（物种/基因/accession/长度/GC） | FR-1.6、FR-1.9 | ✅ 本周期 |
| 功能 1 同一登录号命中多个基因时的处理 | FR-1.8 已知限制 | ✅ 本周期，按基因分组各写一份 |
| 功能 1 完整基因组沿用三种命名模式 | §FR-1.10 末段 | ⛔ 已作废（D-2） |
| 功能 3 单条序列统计（长度/GC/AT/N） | FR-2 | ✅ 计算部分本周期 |
| 功能 3 多条序列汇总表 + CSV 导出 | — | ⏭ 周期 2（D-7） |
| 功能 6 序列拼接（顺序调整、间隔、预览） | FR-3 | ✅ 本周期 |
| 功能 2、4、5、7、8 | §13 路线图 | ⏭ 周期 2 / 3 / 4 |
