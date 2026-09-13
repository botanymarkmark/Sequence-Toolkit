# 端到端验收记录（Task 28）

- 验收日期：2026-09-11
- 分支：`feature/seq-toolkit`
- 验收环境：Windows，Python 3.12.0，pytest 9.1.1，PyInstaller 6.22.2，tkinter 8.6
- 结论：**17 项中 11 项自动验证通过，1 项部分通过（体积已验、内存/冷启动待人工），5 项需人工复验（联网 2 项、GUI 交互 1 项、性能 1 项、Excel 1 项）**。
  无「不通过」项；自动验收过程中发现并修复 1 个真实缺陷（见 §发现的问题）。

> **验收方式说明**：可自动判定的项目由一次性脚本在真实代码上执行（构造临时输入 → 调 `seq_toolkit` 公开接口 → 断言产物与日志），
> 脚本不留在仓库内；每项的「操作」列已写清复现路径。需要联网、需要人在窗口里点按钮、需要任务管理器观察内存的项目**一律标注「未验证（需人工）」**，
> 不臆造通过结论。

## 一、验收表

| # | 验收项 | 操作 | 结果 |
|---|---|---|---|
| 1 | 混合后缀合并 | 构造 `a.fa` / `b.fasta` / `c.fna` / `d.gbk` 与内容为 GenBank 但命名为 `e.fa` 的错起文件，`run_merge` 合并为 `merged.fasta` | **通过（自动）**：`records_out=7`（1+1+1+2+2），输出实际 7 条；日志含「后缀名与内容不符，按内容判定为 genbank: …e.fa」 |
| 2 | 三种命名规则 | 单条 `>ON929859.1 Salsola pellucida chloroplast, complete genome`，分别取三种模式的 `build_name_map` | **通过（自动）**：`ON929859.1` / `Salsola_pellucida` / `ON929859.1_Salsola_pellucida` |
| 3 | 同物种流水号（**规格已变更**） | 两条同物种（`Salsola pellucida`）、不同登录号的记录，跑 `species` 与 `accession_species` | **通过（自动）**：`['Salsola_pellucida_1','Salsola_pellucida_2']`（仍发号，否则真会重名）、`['ON100001.1_Salsola_pellucida','ON100002.1_Salsola_pellucida']`（**不再发号**，集合大小均为 2，无重名）。判据已由"物种是否重复"改为"渲染出的基名是否会撞车"——登录号天然唯一，`accession_species` 下加了也是多余的（用户反馈 `MZ230595.1_Salsola_heptapotamica_3`）；同一登录号出现两次时仍会发号 |
| 4 | 物种名提取 8 例 | 逐个输入设计规格 §7.4 表格中的 8 个 header，比对 `extract_species_from_header`；另跑一条提取失败的文件 | **通过（自动）**：8/8 与表格逐字一致（含 `sp. A-2019`、`cf. pellucida`、`× tragus`、全属名 `Salsola`、`chloroplast, complete genome`→失败）；失败记录进异常清单且未改名（回退登录号 `ON100004.1`） |
| 5 | CONTIG 记录 | `tests/fixtures/contig_record.gb` + `multi_record.gb` 合并转 FASTA | **通过（自动）**：`records_out=2`，CONTIG 记录原因「序列未组装（CONTIG 记录），无 ORIGIN 段」进异常清单，输出为 `ON929859.1`、`MF123456.1` |
| 6 | 中文路径 | 在含中文的目录/文件名（`…/_acc_work/中文目录/样本.fa`、`合并结果.fasta`、`拆分结果/`）上跑合并、拆分、磁盘改名 | **通过（自动，中文路径）**：合并 2 条、拆分 2 个文件、改名 1 个文件，均正常。**注**：`D:\中文目录` 这一具体位置未测——本机 `D:` 存在但当前沙箱拒绝在工作区外建目录（`访问被拒绝`），非程序限制 |
| 7 | 检索下载 | 检索 `Salsola`（属名）+ 长度 100000–200000 + 完整基因组，勾选 5 条下载，核对 5 组 `.fasta`/`.gb` + 两个合并文件 | **未验证（需人工）**：需要联网 + 在 GUI 里点按钮；本环境无法访问 NCBI。操作步骤见 §二.1。**机制层已自动覆盖**：下载产物后缀为 `.fasta`（`test_download_writes_per_sequence_fasta_with_fasta_suffix`）、检索结果导出登录号为 `.txt`/`.csv`（`test_search_tab_exports_checked_accessions_as_txt` 等 8 项） |
| 8 | 断网行为 | 断网后下载，出现明确错误与重试日志，程序不崩溃 | **未验证（需人工）**：需真实断网操作。可自动验证的部分**已通过**：`test_request_retries_on_network_error`、`test_request_retries_on_server_error_then_succeeds`、`test_request_gives_up_after_retries_and_raises_ncbi_error`、`test_request_raises_immediately_on_client_error`、`test_errors_are_logged_when_a_log_is_injected`、`test_download_continues_and_keeps_merged_output_when_one_write_fails` 均绿。操作步骤见 §二.2 |
| 9 | 防覆盖 | 同一输出路径连跑两次 `run_merge` | **通过（自动）**：第二次实际写入 `merged_1.fasta`，`merged.fasta` 字节不变，日志含「目标文件已存在，实际写入」 |
| 10 | 取消 | 处理中触发取消，测量响应时间与已写出文件的完整性 | **未验证（需人工）**：GUI 按钮点击响应需人工。机制层**已自动通过**：取消信号 1.1 ms 内生效（<1 s），抛 `OperationCancelled`，此前写好的输出字节不变，且不产生半截文件。操作步骤见 §二.3 |
| 11 | 体积与性能 | exe 体积、任务管理器观察空载内存与冷启动 | **部分通过**：体积 **10.38 MB ≤ 25 MB（通过，自动）**；空载内存与冷启动 **未验证（需人工）**，见 §二.4 |
| 12 | pytest | `py -m pytest` | **通过（自动）**：`410 passed`（详见 §三） |
| 13 | 磁盘改名预览 | 同目录内同 accession 的 `x.fa` 与 `y.gb`，先预览后执行，比对两次对照表 | **通过（自动）**：预览与执行结果逐项一致（`x.fa→ON100001.1_Salsola_pellucida.fa`、`y.gb→ON100001.1_Salsola_pellucida.gb`），`.fa`/`.gb` 后缀不同、无互相覆盖，改名后 2 个文件均存在。**首轮验收此项不通过**，已修复（见 §发现的问题） |
| 14 | 全小写 header | `>AB123456.1 salsola pellucida chloroplast` | **通过（自动）**：`species_raw='salsola_pellucida'`，`species` 模式名称 `salsola_pellucida`（按原样保留大小写） |
| 15 | GenBank 注释保真 | 合并 `multi_record.gb` 输出 GenBank，比对 `FEATURES` 段；再按 `species` 模式改名后比对全文 | **通过（自动）**：合并后 `FEATURES` 段与原始输入逐行一致；改名后除 `LOCUS` 行外逐字节一致；`Kochia_scoparia`（15 字符 ≤16 列）确写入 `LOCUS`，`Salsola_pellucida`（17 字符 >16 列）按已知限制保留原名 `ON929859` |
| 16 | 合成记录往返 | FASTA → `write_genbank` 合成记录 → `read_genbank` 重新解析 → 再转回 FASTA | **通过（自动）**：合成记录重解析得 `accession=ON100001.1`、`species='Salsola_pellucida'`、`length=12`、序列 `ACGTACGTACGT`，再转 FASTA 1 条且序列一致 |
| 17 | 异常清单导出 | `export_exceptions_csv` 导出后用 Excel 打开 | **部分通过**：机制已自动验证——CSV 带 UTF-8 BOM（`EF BB BF`，Excel 据此判定编码）、表头 `文件/行号/原始 header/判定原因/最终采用的名称` 完整、中文路径与中文名以 `utf-8-sig` 回读一致、按 GBK 解码会失败（正是无 BOM 时 Excel 乱码的成因）。**Excel 程序本身未打开**（本环境无 Excel），见 §二.5 |

## 二、需人工验收项的操作步骤

1. **第 7 项 检索下载**
   1) 打开「设置」，填写 NCBI 邮箱；网络不畅时填写代理地址并保存。
   2) 切到「检索与批量下载」，范围选「属名」，检索词填 `Salsola`；长度填 100000–200000；勾选「只要完整基因组」；点「检索」。
   3) 在结果表中勾选 5 条，输出格式同时勾 FASTA 与 GenBank，点「下载」。
   4) 预期：得到 5 组 `登录号.fasta` / `登录号.gb` 与两个合并文件（`all_sequences.fasta`、`all_sequences.gb`），表格中每条的长度与下载文件内的实际序列长度一致；日志区无 ERROR。
   5) 附加（批量导出登录号）：点「导出登录号 .txt…」或「导出登录号 .csv…」，预期勾选了行时导出所勾选的那几条（.txt 一行一个、.csv 带表头且列与表格一致），未勾选时导出表格显示的全部并在日志里写明"未勾选"，取消另存对话框则什么都不做。
2. **第 8 项 断网行为**
   1) 先按第 7 项成功下载一次以确认配置可用；随后断开网络（禁用网卡或拔网线）。
   2) 重复下载操作。
   3) 预期：日志区出现明确的网络错误与重试记录，任务结束后程序仍可继续操作，不闪退、不静默无响应。
3. **第 10 项 取消**
   1) 选一个较大的输入（例如合并数十个 FASTA，或勾选较多下载条目）后点「开始」。
   2) 进度条走动时点「取消」。
   3) 预期：1 秒内界面回到空闲态并提示已取消；已写出的文件仍可正常打开（未被截断）。
4. **第 11 项 空载内存与冷启动**
   1) 双击 `dist\序列工具箱.exe`，用秒表（或手机录像）测量「双击 → 窗口出现」的时间，预期 ≤ 3 秒。
   2) 不加载任何文件，打开任务管理器「详细信息」页，查看该进程的「内存（专用工作集）」，预期 ≤ 80 MB。
   3) 本环境无法执行：onefile 程序在本沙箱内解包 DLL 时被拒绝（见 `task-26-28-report.md` §打包验证），只能人工在普通 Windows 会话下双击验证。
5. **第 17 项 Excel 打开 CSV**
   1) 在处理后的「异常清单」面板点「导出 CSV」。
   2) 用 Excel 双击打开导出的文件。
   3) 预期：中文表头与中文文件名/路径正常显示，无「锟斤拷」等乱码。

## 三、测试与构建证据

| 命令 | 结果 |
|---|---|
| `py -m pytest` | `410 passed in 3.49s`（Task 26 新增 2 项 + Task 28 回归测试 1 项 + 用户使用后三项改进新增 16 项） |
| `py -m pytest`（**后续新增「每个输入文件各输出一个文件」之后**) | `439 passed in 3.66s`（本次新增 29 项，见 §六） |
| `py -m PyInstaller --clean --noconfirm build.spec` | 构建成功，产物 `dist\序列工具箱.exe`，10,885,662 字节 = **10.38 MB**（≤ 25 MB） |
| 冻结产物体内模块自查 | 静态比对源码中 19 个标准库导入：`sys`/`time` 为内建，`traceback` 在 `base_library.zip`，其余（含 `csv`、`gzip`、`ssl`、`socket`、`tkinter`、`urllib`）均已在归档中；`numpy`/`pandas`/`matplotlib` 均未被打入 |
| 冻结产物运行自查 | 以同一 `EXCLUDES` 构建的 `--onedir` 产物可启动并显示主窗口（标题「序列工具箱 — FASTA / GenBank 合并、转换、命名与 NCBI 下载」，空载工作集 61.4 MB，无 crash.log），据此确认「剔除清单没有削掉运行期依赖」；`onefile` 在本沙箱内无法运行，原因见报告 |

## 发现的问题（Task 28 步骤 3）

**问题：多记录文件在「批量重命名磁盘文件」的正式执行中被静默跳过（验收项 13 首轮不通过）。**

- 现象：预览对照表列出 `y.gb → ON100001.1_Salsola_pellucida.gb`，但真正执行后 `y.gb` 名字未变，日志只有一行
  `重命名失败，已跳过该文件: … [WinError 32] 另一个程序正在使用此文件`。
- 根因：`pipeline.rename_disk_files` 用 `next(iterator)` 只取第一条记录来判断新文件名（多记录文件以第一条为准）。
  对多记录文件，生成器停在半途、底层文件句柄一直未关闭；Windows 上紧随其后的 `Path.rename` 因共享冲突失败。
  单记录文件因为第二次 `next()` 已把生成器耗尽、句柄自动关闭，恰好掩盖了缺陷。
- 修复：在 `rename` 之前显式 `close()` 生成器释放句柄（含异常路径），并加回归测试
  `test_rename_disk_files_renames_multi_record_file_for_real`（`dry_run=False` + 多记录 GenBank，修复前 `renamed=0`，修复后 `renamed=1`）。
- 验证：`py -m pytest` 全绿（381 passed），验收项 13 转为通过。

**其他观察（非缺陷、未改动）**：物种名提取失败时，异常清单会对同一条记录给出 2 行——一行是记录级警告汇总
（「无法从 header 提取物种名; …该记录将不改名」），一行是合并阶段的「物种名缺失，名称回退为登录号」。
两者原因不同且都成立，验收判据是「进入异常清单且未改名」，故保持现状，仅在此记录以便人工复核时知情。

## 四、任务清单状态

- Task 26（程序入口 `main.py`）：完成，`main.py` + `tests/test_smoke.py` 已提交。
- Task 27（PyInstaller 打包）：完成，`build.spec` 已提交，产物 `dist\序列工具箱.exe` 10.38 MB（二进制产物按 `.gitignore` 不入库）。
- Task 28（README 与验收）：完成，`README.md` 与 `docs/acceptance.md` 已提交。
- 工作区无未提交改动。

## 五、遗留事项

1. 需人工复验的 5 项（表内第 7、8、10、11、17）应在具备网络与图形桌面的普通 Windows 会话下逐项补录，补录后本文件应更新为最终结论。
2. `build.spec` 中 `icon="assets/icon.ico"` 一行已按简报说明删除（仓库无图标文件，保留该行会让 PyInstaller 直接报错中止）；日后放入 `assets/icon.ico` 后恢复该行即可。
3. `EXCLUDES` 中的 `email` / `html` 已移除：`urllib.request` 经 `http.client` 在导入期就需要 `email`，剔除后打包产物启动即抛
   `ModuleNotFoundError: No module named 'email'`（构建期无感知，只在运行期暴露）。此结论已写入 `build.spec` 注释。

## 六、用户使用后新增功能的验收：每个输入文件各输出一个文件

- 分支：`feat/per-file-convert`；实现：`pipeline.ConvertPlan` + `pipeline.convert_each_file()`，GUI 为「合并 / 转换」页新增的
  **输出方式** 单选（`合并为单个文件`（默认）/ `每个输入文件各输出一个文件`）
- 用户原话：「在转换这个部分，genbank 文件转 fasta 文件的时候，无论如何输出的只有一个合并的 fasta 文件，
  请你增加批量将 genbank 文件分别转化为 fasta 文件的功能」。用两个问题确认：输出文件名沿用原文件名只换后缀；
  文件内序列名套用本页「命名规则」

| # | 验收项 | 操作 | 结果 |
|---|---|---|---|
| 18 | 一文件一产物 | `样本.gbk.gz`（gzip 压缩的 GenBank）与 `甲.gbk` 转 FASTA，输出到 `中文 输出目录` | **通过（自动）**：目录里恰好 2 个 `.fasta` = `样本.fasta`、`甲.fasta`（**不是** `样本.gbk.fasta`），各含自己的登录号 |
| 19 | 多记录文件不被拆 | 一个含 2 条记录的 GenBank 文件 | **通过（自动）**：只产出 1 个输出文件，内含 2 条序列（与 `split_records` 的"按记录拆"区分开） |
| 20 | 文件内序列名沿用命名规则 | `accession_species` 模式转 FASTA | **通过（自动）**：header 为 `>ON929859.1_Salsola_pellucida` |
| 21 | 去重作用域 = 单个文件 | 一个文件内含同登录号 2 条记录 + 另一个含同登录号的文件，`按登录号去重` | **通过（自动）**：`duplicates_removed=1`、写出 2 个文件（跨文件不互相去重），日志写明「去重（本文件内）」 |
| 22 | CONTIG 记录 | 只含 CONTIG 记录的 `.gbk` + 一个正常文件 | **通过（自动）**：无输出文件、无空文件、记 WARN、进 `skipped_files`（原因「序列未组装（CONTIG 记录），无 ORIGIN 段」） |
| 23 | 防覆盖 | 同一输入连跑两次 + 把磁盘上那份改成别的内容再跑一次 | **通过（自动）**：内容相同 ⇒ 目录里仍只有 1 个文件（不产生 `_1` 孪生）、旧产物字节不变；内容不同 ⇒ 写出 `样本_1.fasta`，旧的**逐字节未动** |
| 24 | 单文件失败不中断 | 截断的 `.gbk.gz`（抛 `EOFError`/`zlib.error`）+ 一个正常文件 | **通过（自动）**：坏文件进 `skipped_files` 并记 ERROR，正常文件照常产出 |
| 25 | 非法枚举 | `output_format="gb"` / `input_format="genbank2"` / `naming_mode="species_v2"` / `dedup="all"` | **通过（自动）**：构造 `ConvertPlan` 时即抛 `SeqToolkitError`（不是 `ValueError`——后者不在 GUI 捕获集内） |
| 26 | GUI 输出方式切换 | 点「每个输入文件各输出一个文件」后点「浏览…」 | **通过（自动）**：行标签与对话框标题都变成「输出目录」、打开的是目录对话框（另存为对话框一次都没被调用）；切回「合并为单个文件」后恢复"选择输出文件" |
| 27 | GUI 校验与产物 | 批量模式下不填目录直接点「开始处理」；填目录后跑 2 个输入文件 | **通过（自动）**：空目录时只记 WARN、不起后台任务；填好后目录里 2 个 `.fasta`，状态栏显示「完成，转换 2 个文件 → …」 |
| 28 | 离线 | 全部用例是否发起真实网络请求 | **通过（自动）**：新增用例只用本地临时文件，`NcbiClient` 未被触碰 |

## 八、功能 7 与功能 8 验收

- 验收日期：2026-09-13
- 分支：`feat/tnrs-phylomaker`（起点 `517b773`）；被验功能：功能 8 物种名清洗（TNRS）、功能 7 进化树生成（V.PhyloMaker2）
- 验收环境：Windows，Python 3.12.0，pytest 9.1.1，PyInstaller 6.22.2，tkinter 8.6，**R 4.6.1**（`C:\Users\33411\AppData\Local\Programs\R\R-4.6.1\bin\Rscript.exe`，用户级安装）+ `V.PhyloMaker2`
- 本任务**只改文档**（`README.md`、`README.zh-CN.md`、`docs/acceptance.md`），未改任何源码或测试；表内出现的不通过项一律如实记录，不做掩盖（见下方「发现的问题」）。**本节之后的「本轮修复复核」小节是另一次任务，改了源码与测试**，两组数字都已按各自时点注明。
- 「实测」列的证据分三层，逐行注明来源：
  1. **控制器探针**：控制器此前在真实 R / 真实 TNRS 上做过的一次性探针（结论落在规格 `docs/superpowers/specs/2026-09-12-tnrs-and-phylomaker-design.md` §7 与附录，以及 `…-gene-search-and-concat-design.md` 附录 A.4 / A.5）；本任务未重复这些耗时的真实调用。
  2. **本次一次性探针**：脚本写在系统临时目录（`%TEMP%\b8_probe.py` R 端到端、`b8_probe2.py` 离线回写/CSV/分批/未配置分支、`b8_probe3.py` 真实 Tk 标签页枚举），产物只落在临时目录，**不进仓库**（与 §一 的既有做法一致），输出文本留在 `%TEMP%\b8_probe2.txt` 等文件里。
  3. **离线自动化**：`tests/test_tnrs.py`（39 项）、`tests/test_phylo.py`（36 项）、`tests/test_gui_tab_tnrs.py`（18 项）、`tests/test_gui_tab_phylo.py`（12 项）。

| # | 场景 | 预期 | 实测 | 结论 |
|---|---|---|---|---|
| 1 | 清洗 6 个名称（含 1 个不存在、1 个属名小写、2 个带科名/作者） | 5 命中 1 未命中，未匹配不消失 | **未重复联网**（TNRS 是公网服务，契约已实测锁定）。按控制器探针结论：`POST https://tnrsapi.xyz/tnrs_api.php`，6 个名称单次请求 0.85 s；未匹配的标记是字面量 `"[No match found]"`、得分为**空字符串**（不是 0）；科名前缀进 `Family_matched`、作者引证进 `Author_matched`；`matches=all` 下 2 个名称返回 4 行（规格 §7.1、附录 A.4）。本次离线复核了解析链路：`parse_response` → 三态判定 → `summarize_status` 计数，未匹配行以状态「未匹配」留在结果表内、`Unmatched_terms` 写进 CSV「备注」列（探针 2） | 通过（依据控制器探针结论 + 本次离线解析复核） |
| 2 | 清洗 5100 个名称 | 自动切 2 批，无 413 | 本次实跑（探针 2）：`tnrs.build_batches(5100 个名称)` → `[5000, 100]`（`BATCH_LIMIT = 5000`）；离线用例覆盖 0/1/4999/5000/5001/12000 的边界（`test_build_batches_splits_at_the_limit`、`test_build_batches_handles_boundaries`）。服务端硬上限由探针实测：5100 行单请求返回 `HTTP 413 ERROR: Requested 5100 rows exceeds 5001 row limit`（1.95 s，规格 §7.1 / 附录 A.4），所以「无 413」是靠自动分批达成的，不是服务端容忍。本次未再次发起 5100 名称的在线请求 | 通过（分批已实测；在线大请求未重复发起） |
| 3 | 导出 CSV | 4 列、utf-8-sig、Excel 无乱码 | 本次实跑（探针 2）：表头正好 4 列 `原始名称,清洗后名称,匹配状态,备注`；文件前三字节 `EF BB BF`（UTF-8 BOM，Excel 据此判定编码），按 `utf-8-sig` 回读一致；未匹配行的「备注」列有值。单测 `test_write_csv_uses_utf8_sig` / `test_csv_rows_and_headers_match_the_spec` 与 GUI 用例 `test_export_csv_writes_utf8_sig_file` 覆盖同一路径。**Excel 程序本身未打开**（本机无 Excel），与 §一 第 17 项同一口径 | 部分通过（列数与编码已实测；Excel 打开一步未验证——本机无 Excel） |
| 4 | 回写 FASTA | 产出 `样本_cleaned.fasta`、原文件未改、日志报替换处数 | 本次实跑（探针 2）：`样本.fasta`（`>ON929859.1 Salsola pellucida chloroplast, complete genome`）→ 输出目录出现 `样本_cleaned.fasta`，首行变为 `>ON929859.1 Salsola australis chloroplast, complete genome`，`replacements=1`、`missing=()`；原文件 SHA-256 前后一致（**原文件未被改动**）。同一目标再跑一次 → 让位为 `样本_cleaned_1.fasta`（绝不覆盖）。日志面：`on_apply_done` 打出「已改写 N 个文件，共替换 M 处，输出到 …」，未找到的名称单独记 WARN（`test_apply_writes_cleaned_copy`、`test_apply_lets_existing_target_yield_and_warns`、`test_apply_names_to_file_reports_names_not_found`） | 通过 |
| 5 | 回写 .gz / 非 UTF-8 文件 | 显式拒绝并给可执行提示，不产出损坏文件 | 本次实跑（探针 2）：`压缩.fasta.gz` → `TnrsError: 压缩文件暂不支持回写，请先解压后再试: …`；GBK 编码的 `gbk.fasta` → `TnrsError: 文件不是 UTF-8 编码，回写会写出内容损坏的文件，请先转码为 UTF-8: …（'utf-8' codec can't decode byte 0xb5 in position 9）`。两次拒绝后输出目录里**只有先前那两个正常产物，没有半成品、也没有损坏文件**。单测 `test_apply_names_to_file_refuses_gzip_input` / `..._refuses_non_utf8_input` / `..._refuses_replacement_characters` 覆盖同一路径 | 通过 |
| 6 | Rscript 未配置 | 明确提示 + 可复制安装指引，不出现异常栈 | 本次实跑（探针 2，把 `which` 与两个安装根目录都注入为「什么都没有」）：`phylo.detect_environment()` 返回 `has_package=False`、`rscript=None`，消息为「未找到 Rscript。」+ 三步安装指引（R 官网链接 / `install.packages("remotes")` / `remotes::install_github("jinyizju/V.PhyloMaker2")` / 「设置」页填路径或点「检测」自动查找），**没有 traceback**。GUI 侧：同一份 `INSTALL_HINT` 由「设置」页「复制安装指引」按钮写入剪贴板并在日志留一行，生成前也会先检测、把它当普通错误消息显示（`test_detect_environment_reports_missing_r`、`test_generate_runs_in_background_and_reports_missing`）。**注意**：本机确实装了 R 4.6.1，因此「未配置」这一分支是靠注入替身构造出来的场景，不是拔掉本机 R 得到的 | 通过（提示与指引已实测；场景由注入替身构造） |
| 7 | 生成树：7 个物种（6 真实 + 1 编造） | 264 字节 treefile、6 叶节点、未入树清单含 Xyzzy_foobar | 控制器已在真实 R 4.6.1 + V.PhyloMaker2 上端到端验证：退出码 0、`phylogeny_tree.treefile` **264 字节**、`SEQTOOLKIT_TIPS 6`、未入树清单含 `Xyzzy_foobar`。本次用另一组 7 个物种复核（探针 1，2026-09-13）：退出码 0、耗时 **18.88 s**、`tip_count=6`、`missing=['Xyzzy_foobar']`、treefile 281 字节（物种名长短不同，字节数不必等于 264）、stdout 119 字节；R 的原始 `Note: 1 taxa fail to be binded to the tree,` 与 `Xyzzy_foobar` 被完整捕获并解析 | 通过 |
| 8 | 200 个编造物种压测 | 退出码 0、清单 200 条完整（验证管道不死锁） | 控制器实测（真实 R）：stdout **15,050 字节**、**16.8 秒**、退出码 0、未入树清单 **200 条完整**。机制侧：`run_phylo` 用守护线程**并发**排空 stdout/stderr，`test_run_phylo_drains_the_pipe_so_a_chatty_r_cannot_fake_a_timeout` 是这条真实缺陷（R 输出写满管道 → `poll()` 永远返回 None → 成功进程被杀并报假超时）的回归保护。本次未重跑该压测（耗时，且结论已由控制器锁定） | 通过（依据控制器实测 + 管道排空回归用例） |
| 9 | Canvas 预览 | 树可见、可缩放、适应窗口正常 | 离线自动化跑在**真实 Tk 窗口**里：`test_tree_canvas_draws_nodes_and_fits` 建 `TreeCanvas` → `set_tree(parse_newick("((A:1,B:2)Inner:0.5,C:3)Root;"))` 后 `item_count() > 0`、`fit()` 与 `zoom(1.5)`/`zoom(0.5)` 均正常、`set_tree(None)` 后 item 归零；`test_tree_canvas_culls_off_screen_nodes` 用**自证计数**验证 40/200 叶树的绘制量随视口裁剪（整棵树入画约 400 项 vs 单个窄视口内不到 1/4；本轮加强前它只断言 `full > 0 and fitted > 0`，把裁剪整段删掉照样过）。生成完成后 `tab_phylo` 会读回 treefile 并送入预览。**「切回标签页即可见」这一条只在 I1 修复后才成立**：修复前在隐藏页里 `set_tree` 会按 `winfo_width()==1` 自适应成 0.02 倍且永不恢复，本轮新增 `test_tree_canvas_refits_when_a_hidden_page_becomes_visible` 钉住（详见下方「本轮修复复核」）。**鼠标滚轮缩放与拖动平移只走了代码路径，未做人工手感验证**（本会话无法手操窗口） | 通过（自动；人工鼠标操作未做） |
| 10 | 输出文件已存在 | 让位 `_1` 并 WARN | **首轮不通过，修复后通过**。首轮以真实 R 复核（探针 1）：先在目标路径写入内容为 `SENTINEL-PREEXISTING-CONTENT` 的 `phylogeny_tree.treefile`，再调 `phylo.run_phylo(...)` → 生成后哨兵内容**消失**，被 R 的 `write.tree` **直接覆盖**；目录里没有 `_1` 文件，日志里也没有 WARN（`seq_toolkit/phylo.py` 全文未调用 `pipeline.resolve_output_path`）。修复 `4fc212e`（`fix(phylo): 建树输出让位 _1 不覆盖已有文件，并让未入树清单完整进日志`）：`run_phylo` 在**渲染 R 脚本之前**对 `tree_path` 调 `pipeline.resolve_output_path()`，使「渲染进脚本的路径 / 磁盘落点 / `PhyloRun.tree_path` 返回值」三者一致；`tab_phylo.on_generate_done` 在请求路径≠实际路径时记 WARN。控制器随后以**真实 R** 复核同一探针（探针 1 重跑）：预先存在的哨兵文件内容**一字未变**，产物让位为 `phylogeny_tree_1.treefile`（**77 字节**，退出码 0），两文件并存。同一让位规则在**名称回写**产物上早已实现并实测（探针 2：`样本_cleaned.fasta` 已存在 → `样本_cleaned_1.fasta`；`tests/test_tnrs.py::test_apply_names_to_file_lets_existing_target_yield`），回归用例为 `tests/test_phylo.py::test_run_phylo_makes_way_for_an_existing_tree_file`（另有 `tests/test_gui_tab_phylo.py::test_generate_warns_when_the_target_file_had_to_make_way` 覆盖 WARN 面） | 通过 |
| 11 | 回归 | 全量 1 failed / 555 passed（唯一失败为既有 test_ncbi 用例） | 本轮修复完成后实跑 `python -m pytest tests`：**1 failed / 555 passed**（556 collected，`skipped=0`；唯一失败恒为 `tests/test_ncbi.py::test_adjacent_requests_hold_the_interval_with_the_default_clock`——请求时间轴重建的浮点残差，既有、与本功能无关、已决定不修）；对照 `python -m pytest tests --ignore=tests/test_tnrs.py` 为 **1 failed / 514 passed**（515 collected）。本轮修复前基线为 1 failed / 539 passed（540 collected），本轮共新增 16 项（含复审补齐的 2 项与布局回归 2 项）。四个功能文件用例数：`test_tnrs.py` 39、`test_phylo.py` 36、`test_gui_tab_tnrs.py` 18、`test_gui_tab_phylo.py` 12（另 `test_gui_app.py` 13） | 通过 |
| 12 | 打包 | exe 启动、七个标签页可见、无 ModuleNotFoundError | **部分完成**。两轮构建都实跑了 `python -m PyInstaller --clean --noconfirm build.spec`：首轮（修复前）产物 `dist\序列工具箱.exe` = 10,955,548 字节（10.45 MB）；**合并进 main 后（`630b68f`）以最终代码重建为 10,959,572 字节（10.45 MB）**，对比加功能前的 10,885,662 字节（10.38 MB）合计增加 73,910 字节（**+0.68%，无明显增长**，符合「新代码全部是标准库」的预期）。启动冒烟**对重建后的产物重做了一遍**：双击等价地 `Start-Process` 该 exe，**15 秒后引导进程与子进程均存活**（`pid 12900` / `23292`，随后由我主动结束），`%APPDATA%\seq_toolkit\` 下**没有 `crash.log`**（该目录只有 9/11 写入的 `settings.json`，本次启动未改动它）。模块自查：`build\build\warn-build.txt` 共 **10** 条 `missing module named`（`grp`/`pwd`/`_scproxy`/`_posixsubprocess`/`fcntl`/`posix`/`resource`/`termios`/`_frozen_importlib_external`/`_sha512`，另有 2 条 `excluded module named`：`lzma`/`bz2`），全部是 POSIX 专属可选项或 importlib 自举细节，**Windows 上真正需要的模块无缺失**（与 §五.3 记录的 `email` 教训相反的情形）。七个标签页在**源码态**真实 Tk 下枚举（探针 3）：`tab_count=7`、`['合并 / 转换','重命名 / 拆分','检索与批量下载','按登录号下载','设置','物种名清洗','进化树生成']`（清洗为第 6、建树为第 7），`test_tab_is_registered_and_settings_index_unchanged`、`test_tab_is_registered_at_the_end` 亦覆盖注册与索引不变。**未做**：在 exe 内逐个目视确认七个标签页（onefile GUI，本会话无人眼看桌面；§二.4 记载本沙箱曾无法运行 onefile 产物，本次在放宽文件权限后已能启动） | 部分通过（构建、启动冒烟、体积、模块自查、源码态七页枚举均已实测；**exe 内标签页目视待人工**，留待发布前） |

### 下拉框取值只在本会话内有效（裁定，非缺陷）

「进化树生成」页的 **命名系统 / 绑定场景**，以及「物种名清洗」页的 **名录来源 / 匹配模式**，
四个下拉框的取值都只在**构建面板时读取一次**（`seq_toolkit/gui/tab_phylo.py`、
`seq_toolkit/gui/tab_tnrs.py`），**两个面板都不写回** `settings.json`——全仓库唯一写设置的地方是
`tab_settings.apply_values()`，而「设置」页没有这四个字段的控件。因此：**这几个下拉框的选择只在
本次会话内有效，重启回到上次保存的值；需要在启动时就指定，请直接编辑
`%APPDATA%\seq_toolkit\settings.json` 的 `tnrs_sources` / `tnrs_matches` / `phylo_system` /
`phylo_scenario`**。这是既有行为，未在本轮改动。

### 发现的问题（已修复）

**问题：建树产物会覆盖同名文件（验收项 10 首轮不通过，已由 `4fc212e` 修复）。**

- 现象：`phylogeny_tree.treefile` 已存在时再次生成，旧文件被 R 的 `ape::write.tree` 原地覆盖，既不产生 `_1` 让位文件，也没有任何 WARN 或提示。
- 根因：`seq_toolkit/phylo.py` 的 `run_phylo` 把调用方给的 `tree_path` 直接渲染进 R 脚本（`ape::write.tree(res$scenario.N, file = tree_path)`），执行前后都不检查目标是否已存在；`seq_toolkit/gui/tab_phylo.py` 的 `do_generate` 也把用户在 `FilePicker` 里选的路径原样传入。规格 FR-2.6 要求的「已存在时不覆盖：`resolve_output_path()` 让位 `_1` 并 WARN」因此没有落到这条路径上。
- 复现（无需图形界面）：预先在目标路径写入任意内容 → 调 `phylo.run_phylo(rscript, species, "TPL", "S3", tree_path)` → 生成后该文件内容被替换为 Newick 文本，目录中无 `_1` 文件。首轮探针输出：`sentinel_survived=False`、`dir_listing=['phylogeny_tree.treefile']`。
- 实际修法（`4fc212e`）：在 `run_phylo` 内部统一处理，使纯函数层也具备该保证——解析目标路径放在渲染 R 脚本**之前**，让位后的路径才写进脚本，从而「脚本里的路径 = 磁盘真实落点 = 返回值 `tree_path`」三者一致；GUI 层在两者不一致时补一条 WARN，日志与界面都不再静默。
- 复核（真实 R，同一探针重跑）：`sentinel_survived=True`、`dir_listing=['phylogeny_tree.treefile', 'phylogeny_tree_1.treefile']`、让位产物 77 字节、退出码 0；全量 `1 failed / 539 passed`（失败者仍是既有的 `test_ncbi` 计时用例）。
- 影响面：只有「输出路径已存在」这一种情形；名称回写（`_cleaned`）与合并/转换/批量转换的让位规则均已实现并有回归用例。

### 用户使用后报告的缺陷（已修复）：清洗页看不到「开始清洗」

- **现象**：默认窗口下打开「物种名清洗」页，「开始清洗」「导出 CSV」「应用到序列文件」「打开输出文件夹」**一个都看不到**。
- **根因**：按钮建了也 `pack()` 了（`tab_tnrs.py` 的 `clean_button.pack(side="right")` 在 `build()` 的 `return` 之前），问题在**分配顺序**——Tk 的 packer 按 `pack()` 调用的先后分配空间，先调用的先拿到自己请求的高度，排在后面的只能分剩下的。清洗页请求高度 **797 px**，而笔记本页在默认窗口（1120×780）里只有 **740 px**，于是最后 `pack` 的按钮条、进度条、选择条被挤成 **1 px**（真实 Tk 实测四个按钮 `mapped=0 / w=1 / h=1`）。窗口只要再高 57 px 按钮就出现——因此「控件不可见」在本会话里一直没暴露：所有 GUI 用例都用 `invoke()`，不看几何。
- **修法**（`1c86d89`）：底部固定行改为**最先** `pack(side="bottom")` 占位，被压缩的变成可伸缩的输入框与结果表（两者自带滚动条），按钮条在任何窗口高度下都在。同一根因在「进化树生成」页也成立（请求高度 680 px，最小窗口下页面只有 620 px，实测该尺寸下 3 个按钮同时消失），一并修好。
- **回归保护**：`tests/test_gui_tabs.py::test_cleaning_tab_shows_all_of_its_buttons`（默认 1120×780）与 `::test_both_new_tabs_keep_their_buttons_at_the_minimum_window_size`（940×660，两个新面板都查）。两条都做了改坏实验：把修复还原后分别报 `AssertionError: 「开始清洗」按钮没有显示出来`（`winfo_ismapped() == 0`）而失败，修复后通过。
- **同源但已裁定不修**：既有面板「检索与批量下载」请求高度 715 px，在**最小窗口尺寸**（940×660）下同样有 1 个按钮被裁；默认尺寸与放大后均正常。它不属于本次新增的两个功能，已把该情形报给用户，用户明确裁定**不修**，故保持原样。
- **教训**：`invoke()` 级测试全绿 ≠ 用户看得见；这两条用例第一次把**真实几何**写进断言。

### 本轮修复复核（2026-09-13 广域评审后，分支 `feat/tnrs-phylomaker`）

评审在真实环境找到 2 个 Important + 若干 Minor，逐项修复如下；每项都先在测试里复现（修复前红、修复后绿）。
TNRS（物种名清洗）功能的行为本轮未改，「绝不覆盖已有文件」的让位规则保持原样。

| # | 缺陷 | 修复与证据 |
|---|---|---|
| I1 | 隐藏页里 `set_tree` 按 `winfo_width()==1` 自适应成 0.02 倍，切回该页后永不恢复 | `tree_canvas.py`：`_viewport()` 把 `<= 1` 视为未布局并用 400×300 兜底（**Tk 未映射时返回 1，不是 0**，旧代码的 `or 400` 拿不到兜底）；`<Configure>` 改为 `_on_configure`，上一次 `fit()` 是按兜底尺寸算的就补算一次。新增 `test_tree_canvas_refits_when_a_hidden_page_becomes_visible`（真实 Tk + Notebook）：修复前 `scale=0.02` 失败，修复后 `scale≈0.70`、树高占视口一半以上。`test_tree_canvas_culls_off_screen_nodes` 同时加强为自证计数（把裁剪关掉即失败） |
| I2 | 取消/超时只杀 `Rscript.exe` 启动器，孤儿 R 继续跑完并落盘；临时 `.R` 删除失败被 `except OSError: pass` 吞掉 | `phylo.py`：新增模块级接缝 `_spawn()`（Windows 加 `CREATE_NEW_PROCESS_GROUP`）与 `_kill_process_tree()`（`taskkill /F /T /PID` → 失败退回 `process.kill()` → `wait(timeout=)`）；`_remove_script()` 返回失败原因，`run_phylo` 新增 `warn` 回调（GUI 传 `ctx.warn`）与 `PhyloRun.leaked_script`。离线：`test_kill_process_tree_calls_taskkill_with_the_tree_flag`、`..._falls_back_when_taskkill_is_unavailable`、`test_run_phylo_cancel_kills_the_whole_process_tree`（真实子进程 + 孙子进程心跳文件）、`test_run_phylo_reports_a_temp_script_that_could_not_be_removed`。**真实 R 4.6.1 三次实测见下表** |
| I3 | 两条管道都空时 `parse_error("", "")` 返回空串，界面只剩「生成失败: 」 | `phylo.py`：`parse_error` 增加 `returncode` 参数并兜底成「R 以退出码 N 结束且没有任何输出」；`_drain` 的 `except Exception` 把异常文本并进 stderr。`test_parse_error_never_returns_an_empty_string`、`test_run_phylo_reports_the_exit_code_when_r_prints_nothing`、`test_run_phylo_keeps_the_reason_when_draining_the_pipe_fails`（修复前 `str(PhyloError('')) == ''`） |
| M2 | 取消后进度标签永远停在「正在生成（大列表可能需要数分钟）」 | `app.py`：`run_job` 新增可选关键字参数 `on_cancel=None`，在 `OperationCancelled` 分支调用；`tab_phylo.do_generate` 传 `on_cancel`（复位进度 + 记 WARN）。`test_run_job_calls_on_cancel_and_not_on_error`、`test_cancelled_job_without_on_cancel_still_works`（既有调用方行为不变）、`test_generate_resets_the_progress_panel_when_cancelled`（修复前实测停在「正在生成…」） |
| M3 | 超深 Newick 的 `RecursionError` 从 after 回调冒出，完成弹窗不再出现 | `tab_phylo.py:154` 的 `except` 元组加上 `RecursionError`，并给一条中文提示「树太深/文件异常，无法预览（分支嵌套层数超出递归上限）；树文件本身已正常写出」。`test_deep_tree_preview_failure_keeps_the_completion_notice`（3000 叶毛毛虫树；修复前 `app._drain()` 直接抛 RecursionError，`messagebox.showinfo` 一次都没被调用）。未改编 `parse_newick` / `layout_cladogram` 的递归算法 |

**I2 的真实 R 人工验证（R 4.6.1 + V.PhyloMaker2，7 个物种含 1 个编造名，中途取消）：**

| 检查项 | 修复前（HEAD `7d80af6` 的 `phylo.py`） | 修复后 |
|---|---|---|
| 退出后 `tasklist` 里 Rscript.exe | 取消返回时 **1 个**（孤儿），5 秒后仍 1 个，13 秒后 0 个 | 取消返回时 **0 个**，5 秒、13 秒后均为 0 个 |
| 应用报「操作已取消」之后是否还有 treefile 落盘 | **有**：13 秒后 `cancel_tree.treefile` 出现（孤儿跑完了整棵树，无人告知） | **没有**：取消返回、+5 秒、+13 秒均不存在 |
| `%TEMP%` 是否新增 `.R` | **新增** `tmp51okrhfp.R` | **未新增** |
| 置位取消到抛出 `OperationCancelled` 的耗时 | 5.02 s（孤儿占着管道，`reader.join(timeout=5.0)` 被打满） | 0.12 s |

同一探针在成功路径上抓到 R 的 **两行**输出（这也修正了 README 里「只打一行」的说法）：
`[1] "Note: 1 taxa fail to be binded to the tree,"` 与 `[1] "Xyzzy_foobar"`；`tip_count=6`、
`missing=['Xyzzy_foobar']`、treefile 258 字节、耗时 17.2～18.5 s。

#### 复审补记（限定范围复审 `4964e41..56123e4`，2026-09-13）

六项修复经复审确认**都真的达成**（复审以真实 R 4.6.1 复测：`_kill_process_tree` 把 3 个
Rscript.exe 清到 0、`.R` 可删、取消 2.61 s 且零残留；把 taskkill 删掉则剩 2 个孤儿 +
WinError 32 + 7.52 s + `%TEMP%` 多一个 `.R`；隐藏页探针 0.0771→0.1400；手动缩放后
resize/切走切回不被重置）。但复审指出**两条用例是空转的**——改坏实现照样通过，这类假绿
比缺用例更危险，本轮已补齐：

- `test_run_phylo_cancel_kills_the_whole_process_tree`：`_sweep()` 原先在 `finally` 里**先**
  把孤儿杀掉，而三条断言写在 `try/finally` **之后**，于是"取消到底有没有杀掉整棵树"根本没被
  测到。改为**先观测、后清理**（断言在 `try` 内、扫尾留在 `finally`）。改坏实验：把
  `_kill_process_tree` 的 taskkill 段短路成修复前行为后，该用例由 **1 passed 变为 FAILED**
  （`AssertionError: 取消后孙子进程仍在写心跳（50 → 58 字节）：进程树没被杀干净`），
  还原实现后 1 passed，且失败路径也不残留孤儿进程。
- `test_tree_canvas_refits_when_a_hidden_page_becomes_visible`：40 叶树在 400x300 兜底下
  scale≈0.39、本就过了 `MIN_LABEL_SCALE`，把 `_on_configure` 的补算分支退回「只重画」仍
  1 passed。改用 **200 叶**树（兜底 0.0771／树高 276px＝视口 51%；补算后 0.1400／505px＝93%），
  断言收紧为「未布局时 `_viewport()` 等于文档兜底值、兜底 scale∈(0.05, MIN_LABEL_SCALE)、
  切回后 scale>0.1 且 >兜底×1.5、树高占视口 ≥75%、`_fitted_with_fallback` 转假」，并加一组
  叶间距压小的同规模树把判据落到 `scale > MIN_LABEL_SCALE`（0.2774 → 0.5039，叶标签
  item 数 400 → 600）。改坏实验：去掉补算分支后由 **1 passed 变为 FAILED**
  （`AssertionError: 切回该页后 scale 仍是 0.07705192629815745`），还原后 1 passed。

同一轮另有 3 处 Minor 修掉：取消「任务不理会取消信号而是照常跑完」时状态栏不再永久卡在
「正在取消…」（`App._finish()` 现在把两种进行中状态都复位；真正被取消的路径仍写「已取消」）、
`tab_phylo.do_detect` 补上 `on_cancel`（并在 job 返回前看一眼取消标记，否则该回调永远不会执行）、
M3 的提示断言收紧到必须含「已正常写出 + 树文件路径」（删掉这半句即失败）；`seq_toolkit/phylo.py`
注释里 Rscript.exe 的实测数量由「两个」改为**三个**（`tasklist` 复核）。

### 未验证项（留待人工）

1. 验收项 3 的「用 Excel 打开 CSV」：本机无 Excel，只验证到「4 列 + UTF-8 BOM + 中文按 `utf-8-sig` 回读一致」。
2. 验收项 9 的鼠标滚轮缩放 / 拖动平移手感：只验证了同名代码路径（`fit()`、`zoom()`、视口裁剪）。
3. 验收项 12 的「exe 内七个标签页可见」：构建、启动冒烟、体积与模块自查已实测，逐页目视未做。

