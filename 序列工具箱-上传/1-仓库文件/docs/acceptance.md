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

