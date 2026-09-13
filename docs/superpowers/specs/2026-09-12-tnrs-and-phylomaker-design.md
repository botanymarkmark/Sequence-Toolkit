# 序列工具箱 · 设计规格：TNRS 物种名清洗（功能 8）与 V.PhyloMaker2 系统树生成（功能 7）

| 项目 | 内容 |
|---|---|
| 日期 | 2026-09-12 |
| 状态 | 已通过分节评审，待用户复核书面规格 |
| 交付物 | 两个新标签页源码 + pytest 测试 + 更新后的 README |
| 决策来源 | 与用户的头脑风暴（设计总览一轮确认 + 探针实测）；用户改向：优先实现功能 7、8 |
| 上游文档 | `docs/superpowers/specs/2026-09-12-gene-search-and-concat-design.md`（附录 A 的探针结论被本文档直接引用） |
| 范围外 | 原需求的其余 6 项功能（含已暂停的周期 1） |

---

## 1. 背景与目标

用户在日常工作中需要两件事，现在都只能离开本工具手工完成：

1. 手上有一批从文献、测序报告或 FASTA header 里抄来的**物种学名**，拼写、异名、科属归属各不相同，需要统一到某个权威名录的接受名，才能进入下游分析；
2. 拿到整理好的物种清单后，需要一个**有依据的系统发育树骨架**把物种放上去，才能做后续的比较分析。

本规格把这两件事做成两个独立面板：**「物种名清洗」**（走 TNRS 在线服务）与**「进化树生成」**（走本机 R + V.PhyloMaker2）。

### 成功标准

研究者把物种名单粘进界面，点一次按钮，就得到：

- 一张清洗结果表（原始名 / 接受名 / 匹配状态 / 得分 / 来源）与一份可交给 Excel 的 CSV，必要时把接受名**写回序列文件**；
- 一棵 Newick 树文件 + 界面内的树形预览，且**未被放进树的物种被明确列出**，不会让用户拿到一棵悄悄少了物种的树。

两次操作都不需要打开命令行。R 与 R 包若缺失，界面给出**可复制的安装指引**而不是报错退出。

---

## 2. 非目标（YAGNI，明确排除）

- 原需求的功能 1–6（含已暂停的周期 1：按基因检索、序列拼接、MAFFT）
- **`mode=parse`（只解析不匹配）**：实测其响应是**另外 13 个完全不同的字段**、不含接受名，"应用到文件"无从谈起，与"清洗"这一用途无关
- 自建分类学数据库、离线匹配、缓存持久化
- Canvas 树上显示分支长度刻度（只画拓扑）
- 把 R / V.PhyloMaker2 打包进 exe（体积与许可都不允许）
- 编辑系统树拓扑、导出图片、树的美化
- TNRS 的名称拼写建议（`Phonetic` 等字段仅原样显示）

---

## 3. 术语表

| 术语 | 含义 |
|---|---|
| TNRS | Taxonomic Name Resolution Service，`https://tnrsapi.xyz/tnrs_api.php` |
| 接受名 | `Accepted_name`——该学名在所选名录下当前被接受的名称 |
| 匹配状态 | 由 `Name_matched` 与 `Overall_score` 推出的三态：`已匹配` / `未匹配` / `部分匹配` |
| 系统 | V.PhyloMaker2 内置的巨型系统树与分类标准：`TPL` / `LCVP` / `WP` |
| 场景 | `phylo.maker` 的物种绑定方式：`S1` / `S2` / `S3` |
| 入树 | 物种被绑定到系统树并出现在输出树的叶节点上 |

---

## 4. 运行环境与交付形式

- 目标机：Windows 10/11 x64，**运行 exe 本身仍无需任何外部依赖**
- **功能 8**：只需外网可达 `tnrsapi.xyz`（实测单次请求 0.8–1.0 秒）
- **功能 7**：需要用户自备 **R + V.PhyloMaker2**（可选外部依赖，不打包）。本机已完成实测环境：R 4.6.1 用户级安装（`%LOCALAPPDATA%\Programs\R\R-4.6.1`，190 MB，无需管理员）、依赖仅 `ape`（Windows 二进制包，无需编译工具链）、`remotes::install_github("jinyizju/V.PhyloMaker2")` 可装
- 新增代码全部使用 Python 标准库（`json`、`urllib.request`、`subprocess`、`threading`、`tkinter`、`csv`、`re`）
- exe 体积不变（不引入任何新依赖）

---

## 5. 功能需求

### FR-1 物种名清洗（TNRS）

#### FR-1.1 输入

- 多行文本框，一行一个学名；空行与首尾空白自动忽略；保持输入顺序
- 提供「从 FASTA/GenBank 导入物种名」：复用 `format_detect.detect_format()` + `fasta_io.read_fasta()` / `genbank_io.read_genbank()`，物种名取 `SequenceRecord.species`，为空时回退 `naming.extract_species_from_header(record.definition)`
- 输入去重（大小写不敏感、忽略首尾空白），但**表格按输入顺序展示去重后的名称**
- 支持科名前缀写法「`Amaranthaceae Salsola pellucida`」与作者引证「`Solanaceae Solanum bipatens Dunal`」——由 TNRS 侧解析（实测：科名会填入 `Family_matched`，作者会填入 `Author_matched`）

#### FR-1.2 请求构造（契约已实测锁定）

- `POST https://tnrsapi.xyz/tnrs_api.php`，头 `Content-Type: application/json`、`Accept: application/json`、`charset=UTF-8`
- 请求体：`{"opts": {...}, "data": [[id, name], ...]}`
- `data` **恰好两列**：第 1 列是**整数 ID**（我们自己编号，从 1 开始），第 2 列是学名原文
- `opts`：`sources`（默认 `"wcvp,wfo"`）、`class`（默认 `"wfo"`）、`mode`（固定 `"resolve"`）、`matches`（下拉：`best` 默认 / `all`）
- **分批**：每批最多 **5000** 个名称（实测 5100 个返回 `HTTP 413 ERROR: Requested 5100 rows exceeds 5001 row limit`——硬上限），自动切批、批间检查取消
- 走设置里的代理（`Settings.proxy`），与 `ncbi.py` 的代理用法一致

#### FR-1.3 响应解析

- 只取以下字段（实测响应共 46 个字段）：
  `ID`、`Name_submitted`、`Name_matched`、`Overall_score`、`Accepted_name`、`Accepted_name_rank`、`Accepted_name_author`、`Family_submitted`、`Family_matched`、`Source`、`Warnings`、`WarningsEng`、`Unmatched_terms`
- **必须处理的三个实测陷阱**：
  1. **所有数值字段都是字符串**（`ID: "1"`、`Overall_score: "1"`），未匹配时是**空字符串**而非 0 或 null
  2. **未匹配的标记是字面量 `"[No match found]"`**，不能靠 falsy 判断
  3. `matches=all` 会让**一个名称返回多行**（实测 2 个名称返回 4 行），表格必须按 ID 聚合展示并显式标注"N 个名称 → M 行"
- 匹配状态三态判定：
  | 状态 | 判据 |
  |---|---|
  | `未匹配` | `Name_matched == "[No match found]"`（或 `Name_matched` 为空） |
  | `部分匹配` | **`Overall_score` 缺失/无法解析**，或能解析为数且 **< 1.0** |
  | `已匹配` | 已匹配且得分为 `1`（或 > 1，异常情形） |

  **「得分未知」判为部分匹配，不判已匹配**：TNRS 正常会对匹配成功的行返回可解析的分数，因此「有名字但没有分数」属于异常形状。把它当成"满分匹配"会让这类行静默进入结果表与统计（"绝不静默"约束瞄准的正是这种无声误报），而判成"部分匹配"会让它出现在计数里、被人工复核。代价是极少数异常行需要用户多看一眼——这个方向的代价明显更小。

#### FR-1.4 结果表

- 列：`原始名称 | 接受名 | 匹配状态 | 得分 | 来源数据库 | 警告`
- 保留 TNRS 回传的 `ID` 作为行身份（与输入行一一对应）。表格行键用 `f"{ID}|{该 ID 下第几条候选}"`（候选序号从 1 开始）：`matches=all` 时同一 ID 会返回多行，若只用 ID 作键，`CheckboxTable.set_rows()` 的按 key 去重会**静默丢掉后续候选行**
- 顶部计数：`N 个名称 → M 行结果，其中已匹配 X、部分匹配 Y、未匹配 Z`
- 未匹配的名称**必须出现在表里**（状态列写"未匹配"），不得从表格消失

#### FR-1.5 CSV 导出

- 列（用户指定）：`原始名称`、`清洗后名称`、`匹配状态`、`备注`
- 备注列 = `WarningsEng` 与 `Unmatched_terms` 的非空拼接
- 编码 `utf-8-sig`（Excel 双击不乱码），换行 `newline=""`（`csv` 模块要求），与既有 `write_accessions_csv` 同一先例
- 全选/反选与「导出勾选行 / 未勾选则导出全部并记日志」沿用 `tab_search.py` 的既有语义

#### FR-1.6 应用到序列文件

- 把**匹配成功**的名称对应的**原始字符串**在文件中原样替换为**接受名**
- FASTA：改写 header 行中命中的子串（`>` 之后的部分），其余字节保真
- GenBank：改写 `ORGANISM` 行、`SOURCE` 行、`/organism="..."` 限定符中的命中子串，其余字节保真（与 `genbank_io.py` 的「raw_block 逐字节保真」文化一致）
- **绝不就地覆盖**：输出到用户指定的**输出目录**，文件名加 `_cleaned` 后缀（如 `样本.fasta` → `样本_cleaned.fasta`）；目标已存在时走 `pipeline.resolve_output_path()` 让位 `_1` 并 WARN
- 逐文件报告：替换了几处、哪些名称未在文件中找到
- 未匹配（`未匹配` 状态）的名称**不参与替换**，且必须计入报告
- **同一原始名称出现多条候选时的冲突规则**（`matches=all` 下会发生）：只使用**被勾选行中该名称的第一条**的接受名；若同一原始名称的其它勾选行给出了**不同的**接受名，在报告中列出该名称与全部候选接受名，由用户决定是否改用 `best` 模式重跑。绝不静默挑一条了事

---

### FR-2 系统树生成（V.PhyloMaker2）

#### FR-2.1 输入

- 多行文本框，一行一个学名；提供「从 FASTA/GenBank 导入物种名」（与 FR-1.1 同一实现）
- 去重，保持顺序

#### FR-2.2 参数

- **系统**（下拉，默认 `TPL`）：
  | 值 | 名称 | 物种数 | 数据集 |
  |---|---|---|---|
  | `TPL` | The Plant List | 74,529 | `GBOTB.extended.TPL` + `nodes.info.1.TPL` + `tips.info.TPL` |
  | `LCVP` | Leipzig Catalogue of Vascular Plants | 73,420 | 同名 `.LCVP` 数据集 |
  | `WP` | World Plants | 72,570 | 同名 `.WP` 数据集 |
- **场景**（下拉，默认 `S3`）：`S1`（绑定到属节点）/ `S2`（科内按随机分辨率绑定）/ `S3`（属内按随机分辨率绑定），界面注明差异
- R 脚本路径：只读显示当前探测结果 + 「检测」按钮 + 「打开设置」链接（路径在「设置」页编辑）

#### FR-2.3 R 脚本（模板已实测跑通）

Python 侧渲染一份 R 脚本并交给 `Rscript` 执行，脚本必须包含：

1. `suppressMessages(library(V.PhyloMaker2))`
2. **显式 `data()` 载入**三个数据集——实测这是必须的：`Rscript` 下数据集是 lazy-load，不显式载入会抛 `object 'GBOTB.extended.TPL' not found`
3. **自动补齐 `genus` / `family`**，使界面**只要求用户输入学名**：
   - `genus` = 学名的第一个词
   - `family`：把学名按空格转下划线后在 `tips.info.<系统>$species` 里精确查找；未命中则**属级回退**（`tips.info.<系统>$genus` 匹配后取第一个非 `NA` 的 `family`）；仍未命中则为 `NA`
   - 实测：`Salsola pellucida` 经属级回退得到 `Amaranthaceae`，7 个物种（含 1 个编造名）产出与手工填 family **逐字节一致**的 treefile
4. `tryCatch` 包住 `phylo.maker`，失败时 `quit(status = 1)` 并打印 `conditionMessage`
5. `ape::write.tree(res$scenario.<N>, file = <输出路径>)`
6. 脚本末尾打印一段**机器可读的汇总**（物种数、入树叶节点数、未入树清单），供 Python 侧核对

#### FR-2.4 未入树物种的报告

`phylo.maker` 对无法绑定的物种**只打印一行 `Note: 1 taxa fail to be binded to the tree,` 后跟物种名，然后静默丢弃、不报错**（实测 7 个输入 → 6 个叶节点）。因此未入树清单有**两条来源，以第一条为准**：

1. **主来源：R 脚本自己算出的差集**（可信度更高）。脚本在 `write.tree` 之后读回 treefile 的叶标签，与输入学名（空格归一为下划线后）求差集，按固定前缀逐行打印，例如 `SEQTOOLKIT_MISSING<TAB>Xyzzy_foobar`。这比解析 R 的提示文本可靠——提示文本是给人看的，格式可能随包版本变化
2. **兜底：解析 `Note: N taxa fail to be binded to the tree,` 及其后紧随的物种名行**。仅在脚本未产出上述汇总行时使用（例如 R 版本差异导致脚本中途出错的情况）

无论来自哪条来源，该清单都必须：

- 在**界面**上显式列出（醒目样式）
- 写入**日志（WARN）**
- 与「输入 N 个物种 / 入树 M 个叶节点」一起显示，数字不一致时必须给出解释

#### FR-2.5 执行

- `subprocess.run([rscript, script_path], capture_output=True, timeout=...)`，超时上限 **600 秒**（实测 7 物种 16.6–17.8 秒；大列表会显著更久）
- 全程在后台线程执行，进度条显示阶段（写脚本 → 调 R → 解析 → 完成），可取消（取消时终止子进程并清理临时文件）
- R 的 stdout/stderr **原样写入日志**（用户需要看到 R 的警告）
- 临时 R 脚本写入系统临时目录，执行结束后删除；失败时保留路径并告知用户

#### FR-2.6 输出

- 默认输出路径：`<Settings.output_dir>\phylogeny_tree.treefile`；`output_dir` 为空时填 `<当前工作目录>\phylogeny_tree.treefile`。用户可改（`FilePicker` 的 `save` 模式）
- Newick 文本，UTF-8 + LF
- 已存在时不覆盖：`resolve_output_path()` 让位 `_1` 并 WARN
- 完成后界面显示路径，并提供「在文件夹中显示」

#### FR-2.7 Canvas 树形预览

- 用 `tkinter.Canvas` 绘制**拓扑树**（cladogram，分支长度不影响水平间距），叶节点标签右对齐排在右侧
- 支持：鼠标滚轮缩放、拖动平移、「适应窗口」按钮
- **不为每个节点创建大量 Canvas item**：节点数 = 2×物种数−1，几千个物种时需按可视区域裁剪，只绘制落在视口内的连线与标签
- Newick 解析为纯函数（`parse_newick(text) -> TreeNode`），支持：分支长度、内部节点标签、单引号包裹的标签、`;` 结尾

---

## 6. 架构

### 6.1 新增文件

| 文件 | 类型 | 职责 |
|---|---|---|
| `seq_toolkit/tnrs.py` | 纯逻辑 | 契约常量、请求体构造、响应解析、分批清洗编排、CSV 写出、名称回写文件 |
| `seq_toolkit/phylo.py` | 纯逻辑 | 系统/场景常量、Rscript 探测、R 脚本渲染、`Note:` 行解析、Newick 解析、subprocess 编排 |
| `seq_toolkit/gui/tab_tnrs.py` | UI | 「物种名清洗」标签页 |
| `seq_toolkit/gui/tab_phylo.py` | UI | 「进化树生成」标签页 |
| `seq_toolkit/gui/tree_canvas.py` | UI 控件 | Canvas 树绘制（缩放/平移/适应窗口） |

`tnrs.py` / `phylo.py` 不 import `tkinter`，全部逻辑可用 pytest 离线验证（网络与子进程通过参数注入，便于测试替身）。

### 6.2 对既有文件的增量改动

| # | 文件 | 改动 | 为什么 |
|---|---|---|---|
| ① | `settings.py` | `Settings` 增加 `rscript_path: str = ""`、`phylo_system: str = "TPL"`、`phylo_scenario: str = "S3"`、`tnrs_sources: str = "wcvp,wfo"`、`tnrs_matches: str = "best"`，**并同步加入 `_SCHEMA` 类型表** | 不加 `_SCHEMA` 会被静默重置为默认值（该文件注释里已记录过这个坑） |
| ② | `gui/app.py` | `TAB_SPECS` **追加两行**（末尾）：`("进化树生成", tab_phylo)`、`("物种名清洗", tab_tnrs)` | 全项目唯一的标签页注册点；**追加在末尾**以保住 `tab_search.py` 中硬编码的 `open_tab(4)` 仍指向「设置」 |
| ③ | `gui/tab_settings.py` | 增加「外部依赖」区块：Rscript 路径输入 + 「检测」按钮（显示探测结果与版本）+ V.PhyloMaker2 是否已装 + 可复制的安装指引 | 功能 7 需要用户在设置里指定路径（用户需求原文如此） |
| ④ | ~~`gui/widgets.py`~~ | ~~`CheckboxTable` 增加 `key_of`~~ **本改动已作废** | 编写实现计划时发现更简单的解法：清洗结果表**首列放 1 基序号「#」**，而 `CheckboxTable` 默认就以首元素作行键，序号天然唯一 ⇒ `matches=all` 的多行候选一行都不会被静默去重。既解决了问题，又少动一个既有文件 |

### 6.3 界面集成

```
ttk.Notebook
├─ 合并 / 转换            (v0.1，不动)
├─ 重命名 / 拆分          (v0.1，不动)
├─ 检索与批量下载          (v0.1，不动)
├─ 按登录号下载            (v0.1，不动)
├─ 设置                  (v0.1 + 改动③ 的外部依赖区块)
├─ 进化树生成             ← 新增（功能 7）
└─ 物种名清洗             ← 新增（功能 8）
```

### 6.4 数据流

```
功能 8：物种名列表
  └─ tnrs.build_batches(names, 5000) → 每批 payload
       └─ urllib POST（后台线程，批间检查取消）
            └─ tnrs.parse_response() → [TnrsRow]
                 └─ 表格（按 ID 聚合）+ 状态三态统计
                      ├─ 导出 CSV（utf-8-sig）
                      └─ 回写序列文件（另存 _cleaned，绝不覆盖）

功能 7：物种名列表 + 系统 + 场景
  └─ phylo.locate_rscript() → 路径或 None（None 时给安装指引并终止）
       └─ phylo.render_script() → 临时 .R 文件
            └─ subprocess Rscript（后台线程，超时 600s，可取消）
                 ├─ stdout/stderr → 日志
                 └─ phylo.missing_species() → 未入树清单（脚本汇总行优先、Note: 行兜底）
                      └─ WARN + 界面显式列出
                           └─ treefile → phylo.parse_newick() → Canvas 预览
```

---

## 7. 外部契约（实测锁定，实现时照此写）

### 7.1 TNRS

| 项 | 值 |
|---|---|
| URL | `https://tnrsapi.xyz/tnrs_api.php`（POST，JSON） |
| 请求体 | `{"opts": {"sources": "wcvp,wfo", "class": "wfo", "mode": "resolve", "matches": "best"}, "data": [[1, "Acer rubrum"], ...]}` |
| data 列 | 第 1 列整数 ID，第 2 列学名（可含科名前缀与作者引证） |
| 上限 | 每请求 ≤ 5000 行，超出返回 `HTTP 413` |
| 响应 | JSON 数组，每元素 46 个字段 |
| 未匹配标记 | `Name_matched == "[No match found]"`；`Overall_score` 为空字符串 |
| 耗时 | 6 个名称 0.85 s；5100 个名称被拒 1.95 s |

### 7.2 R 环境

| 项 | 值 |
|---|---|
| Rscript 探测顺序 | 设置项 → `PATH` → `%ProgramFiles%\R\R-*\bin\Rscript.exe` → `%LOCALAPPDATA%\Programs\R\R-*\bin\Rscript.exe`（多版本时取版本号最大者） |
| 包检测 | `Rscript -e "cat(requireNamespace('V.PhyloMaker2', quietly=TRUE))"` |
| 安装指引 | R：`https://cran.r-project.org/bin/windows/base/`；包：`install.packages("remotes")` + `remotes::install_github("jinyizju/V.PhyloMaker2")` |
| 实测耗时 | 7 个物种 16.61–17.78 秒（含 74,529 物种系统树载入） |

---

## 8. 并发与错误处理

沿用既有硬约束：所有网络与子进程操作在 `BackgroundWorker` 后台线程执行，`job(ctx)` 内不触碰任何 Tk 控件；控件取值在主线程取完快照。

| 场景 | 处理 |
|---|---|
| TNRS 网络不可达 / 超时 | 该批记 ERROR 并继续下一批；全部失败时给出「请检查网络或代理」提示 |
| TNRS 返回非 JSON / 结构异常 | 记 ERROR 并报告响应前 200 字符，不崩溃 |
| TNRS 超限 413 | 不应发生（已按 5000 分批）；若发生，记 ERROR 并提示这是工具缺陷 |
| 名称全是中文或空 | 照常请求，未匹配的进"未匹配"行（实测中文名不报错，回填 `Unmatched_terms`） |
| 回写序列文件时名称未在文件中出现 | 计入报告的「未找到」计数，不修改该文件内容 |
| Rscript 未找到 | 终止并在界面给出安装指引与「打开设置」入口，不弹错误栈 |
| R 缺 V.PhyloMaker2 | 同上，指引里带上 `install_github` 命令 |
| R 脚本执行失败 | 展示 `conditionMessage` 与 stderr 尾部 30 行；保留临时脚本路径 |
| R 执行超时（>600 s） | 终止子进程、清理临时文件、报告已耗时与物种数 |
| 用户取消 | 终止子进程；已写出的 treefile 若完整则保留，否则删除半截文件 |
| 全部物种未入树 | 明确提示「N 个物种全部未能绑定到系统树」，不产出空树文件 |

原则与 v0.1 一致：**单条失败不中断整批；任何被跳过、未匹配、未入树的数据都必须出现在日志或界面上。**

---

## 9. 测试策略

### 9.1 离线单元测试

| 模块 | 用例 |
|---|---|
| `tnrs.py` | 请求体结构（两列、整数 ID、opts 键名）；分批（0/1/4999/5000/5001/12000 个名称 → 批数）；`parse_response` 处理 `"[No match found]"`、空串得分、`matches=all` 的多行、缺字段、非 JSON；状态三态判定（分数 `"1"` / `"0.85"` / `""`）；CSV 列与 `utf-8-sig`；名称回写的 FASTA/GenBank 替换（命中/未命中/多命中） |
| `phylo.py` | Rscript 探测（注入假的文件系统与 PATH）；脚本渲染包含 `data()` 三处载入、`library()`、scenario 名、属级回退逻辑、`SEQTOOLKIT_MISSING` 汇总行；未入树清单的两条来源（脚本汇总行优先、`Note:` 行兜底；两者都缺失时返回空）；Newick 解析（分支长度、内部标签、引号标签、空树、畸形输入不抛异常）；输出文件名与让位规则 |
| `tree_canvas.py` | 布局纯函数：叶节点 y 坐标均匀分布、内部节点 y 居中、视口裁剪只返回可见节点 |

### 9.2 GUI 测试（沿用 `tests/test_gui_tabs.py` 的单根窗口夹具）

- 两个新标签页能构建、控件齐备、不抛异常
- 「设置」页索引仍是 4（回归：`open_tab(4)`）
- 清洗结果表的默认勾选与计数；`matches=all` 时多行不被静默去重
- 树预览在给定 Newick 后产生 Canvas item，且「适应窗口」不抛异常

### 9.3 集成测试（注入假 opener / 假 subprocess，完全离线）

- 清洗全流程：假 HTTP 客户端 → 表格行 → CSV 文件内容 → 回写 FASTA 的 header 变化
- 分批：12000 个名称 → 3 批请求，ID 连续不重复
- 树流程：假 `subprocess.run` 返回预置 stdout（含 `Note:` 行）与 treefile → 未入树清单正确、日志有 WARN

### 9.4 真实联网/真实 R 的手工验收

见 §10，一次性执行，不进 CI。

---

## 10. 验收标准

| # | 场景 | 预期结果 |
|---|---|---|
| 1 | 清洗 6 个名称（含 1 个不存在的、1 个属名小写的、2 个带科名/作者的） | 表格 6 行；不存在的显示"未匹配"且 `Unmatched_terms` 有值；`quercus robur` 被匹配为 `Quercus robur`；带科名的行 `Family_matched` 有值 |
| 2 | 清洗 5100 个名称 | 自动切成 2 批（5000 + 100），全部返回；无 413 |
| 3 | 导出 CSV | 4 列；Excel 双击无乱码；未匹配行的"备注"列有值 |
| 4 | 把接受名回写到一份 FASTA | 目标目录出现 `样本_cleaned.fasta`；原文件未被改动；日志报告替换处数 |
| 5 | Rscript 未配置（设置项清空且 PATH 无 R） | 明确提示 + 可复制安装指引；不出现异常栈 |
| 6 | 生成树：7 个物种（6 真实 + 1 编造） | 产出 `phylogeny_tree.treefile`；6 个叶节点；界面与日志列出未入树的 `Xyzzy_foobar` |
| 7 | 与手工填 family 的结果对比 | treefile 逐字节一致（264 bytes，实测） |
| 8 | Canvas 预览 | 树可见、可缩放、「适应窗口」正常 |
| 9 | 输出文件已存在 | 让位 `_1` 并 WARN |
| 10 | 回归 | 新增测试全绿；既有 441 passed 不变（`tests/test_ncbi.py` 的 1 个既有失败与本次无关） |

---

## 11. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| TNRS 服务变更契约 | 功能 8 全部失效 | 契约集中在 `tnrs.py` 顶部常量与 `parse_response` 一处；响应结构异常时报告原始响应前 200 字符 |
| `matches=all` 的多行被误当成多名称 | 统计与 CSV 行数错乱 | 表格按 ID 聚合展示 + 显式"N 名称 → M 行"；CSV 保留全部行并在备注注明候选序号 |
| 用户机器上的 R 版本/包版本差异 | 脚本行为不一致 | 脚本只用 `phylo.maker` 的稳定参数；执行前检测包是否存在并报告版本；stdout 原样进日志 |
| 大物种列表（数千种）导致 R 极慢 | 用户以为卡死 | 进度条 + 600 秒超时 + 可取消；界面提示预期耗时随物种数增长 |
| 树预览在数千物种时卡顿 | 界面假死 | 视口裁剪只画可见节点；叶标签在缩放小于阈值时不逐个绘制 |
| 回写序列文件时改写错位置 | 数据损坏 | 只做**命中的原始字符串**的原样替换；绝不就地覆盖（另存 `_cleaned`）；逐文件报告替换处数；有 pytest 覆盖 |

---

## 12. 决策记录

| # | 决策 | 结论 | 依据 |
|---|---|---|---|
| D-1 | 命名系统下拉的取值 | 列出 **TPL / LCVP / WP** 三个真实系统，默认 TPL；界面不出现"APG III/APG IV" | 用户确认；包内不存在 APG 选项（实测 3 个系统 / 3 个数据集） |
| D-2 | 是否要求用户提供科名 | **不要求**，用户只输学名；genus 由第一词推出，family 从 `tips.info.<系统>` 自动补齐（物种级 → 属级回退） | 实测跑通且与手工填 family 结果逐字节一致 |
| D-3 | `mode=parse` | 不做 | 其响应是另外 13 个字段、无接受名，与"清洗"用途无关 |
| D-4 | `matches=all` | 做 | 成本低（表格按 ID 聚合 + 计数提示），价值是让用户看到多个候选 |
| D-5 | 一份规格覆盖两个功能 | 一份规格、两阶段计划（先 8 后 7） | 两者互不耦合但共用骨架（新标签页/设置/后台任务/外部依赖引导）；分开写两份规格的边际收益低于协调成本。**先做功能 8**：它只需网络，能更早交付可用产物；功能 7 依赖用户机器的 R 环境 |
| D-6 | 回写序列文件的覆盖策略 | 一律另存 `_cleaned` 后缀，绝不就地覆盖 | 与 v0.1「绝不静默覆盖」一致；名称回写是破坏性操作，必须可回退 |
| D-7 | Canvas 树的形态 | 只画拓扑（cladogram），不做分支长度刻度 | 用户需求原文是"简单 Canvas 树形视图预览"；YAGNI |

---

## 13. 附录：本规格引用的探针证据

完整证据见 `docs/superpowers/specs/2026-09-12-gene-search-and-concat-design.md` 附录 A.4（TNRS 契约）与 A.5（R 与 V.PhyloMaker2）。本规格新增的两次探针（2026-09-12，一次性脚本 `p3_family.R` / `p3_auto.R`）：

- `tips.info.<系统>` 的列为 `group, species, genus, family`，**`species` 是下划线形式**（如 `Stylotrichium_rotundifolium`）——按空格查找会全部落空，必须归一化
- 属级回退可用：`genus == "Salsola"` 命中 20 条，`family` 存在 `Amaranthaceae`（并有 `NA` 行，需过滤）
- 只给学名的 7 个物种（含 1 个编造名）自动补齐后生成的 treefile 与手工填 family **逐字节一致（264 bytes）**，耗时 16.61 秒；未收录物种得到 `<未找到>` 并被 `Note: 1 taxa fail to be binded to the tree,` + 物种名显式报出
