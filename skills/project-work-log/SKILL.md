---
name: project-work-log
description: 为长期项目建立并维护工作记录体系（过程记录 + 索引台账 + 经验手册，统一收在 work_log/ 容器里），不限编程——软件、研究、写作等跳会话或跨周持续投入的项目都适用。当用户要「开始新任务」「留下记录 / 建工作日志」「总结经验 / 复盘」「整理台账 / 待办」「归档旧记录」时使用。
---

# 项目长期工作记录（project-work-log）

> **来源与免责声明**：本技能的约定、文档与脚本整理自作者使用 **DeepSeek Flash 系列模型**处理内容时的常用操作，
> 并**完全由 DeepSeek Flash 系列模型整理生成**（未经人工逐条校验）。
> 使用时请自行甄别，**不保证效果、正确性与适用性**；建议先小范围试用，再按项目的实际情况调整。

## 这是什么

把"项目里发生过什么、怎么验证的、留下了什么可复用经验"沉淀成**三层、可检索、可校验**的文档体系。
三层同住**一个容器目录** `work_log/`（默认名，可配置），内部各有分工：

| 层 | 位置 | 职责 | 生命周期 |
|---|---|---|---|
| **过程层** | `work_log/NNNN-*.md`（容器根；分卷后 `work_log/<YYYY>/NNNN-*.md`） | 一篇 = 一次会话（默认档；档位可调，见下「记录精细度」）：背景 → 事实 → 方案 → 执行 → 验证 → 遗留 | append-only，收口后不改写 |
| **索引层** | `work_log/README.md` | 分阶段索引 + 同主题簇 + 滚动待办 + **唯一**当前状态块 | 每次收尾更新 |
| **经验层** | `work_log/lessons/*.md` | 提炼后的可复用知识：症状 → 根因 → 做法 → 来源 | 持续追加，每条必须有来源 |

一句话：**过程留证据，索引管导航，经验可复用**。三层不互相复制内容。

容器里的其他固定位置：归档记录在 `work_log/<stage>/NNNN-*.md`（阶段目录直接建在容器下，
**没有** `archive/` 一层）、旧状态块在 `work_log/STATE-HISTORY.md`、归档索引在 `work_log/ARCHIVE.md`、
日志与运行产物在 `work_log/logs/<来源>/`。完整布局与「日志归位要求」见
[references/conventions.md](references/conventions.md)。

> **领域无关**：这套结构不限于编程。
> 迭代字段接受 `迭代 / 变更集 / 批次 / 阶段 / 版本 / 里程碑`（英文 `Iteration / Milestone`）；
> 验证小节接受 `验证 / 复核 / 检查 / 评审 / 结果 / 证据 / 评估 / 确认 / 实测 / 审查`
> （英文 `Verification / Review / Results / Evidence / Tests`），标题级别 h2–h4 都认；
> “可核对的内容”可以是命令、数据、引用或样本。
> 例：研究项目用 `批次：3` + `## 结果`（样本量、结论、反例）；写作项目用 `版本：v2` + `## 评审`（编辑意见与处理）；
> 软件项目用 `变更集：154` + `## 验证`（测试命令与通过数）。
> ⚠ 一个标签一个值：写 `迭代：3`，**不要**写 `迭代 / 批次：3`（解析不出来）。

这套体系来自一个真实项目的 `work-log/` + `lessons/` 实践；基线分析（哪些沿用、哪些坑要避开）见
[references/analysis.md](references/analysis.md)。

## 何时用

- 用户说"开始一个新任务"——先确认/建立这套结构，再开工。
- 一项工作 / 一个迭代完成后要"收尾/留记录/更新台账"。
- 要"总结经验/整理踩坑/做复盘/归档旧东西"。
- 接手一个已有 `work_log/`、`journal/`、`work-log/`、`lessons/`、`docs/` 记录体系的项目，要按既有约定续写
  （旧名 `journal/`、`work-log/` 与顶层 `lessons/` 都能被识别，**只读取、不迁移**）。

## 铁律（先看这 8 条）

1. **先记录、后动手**（方案类）：先写清"要解决什么 + 选项 + 建议默认值"，用户确认后再实施；有疑问先记录，不擅自改。
2. **一篇 = 一次会话**（默认档 `session`；档位可调，见下「记录精细度」）。
   一次会话里做了几件可交付的事，都并进同一篇。只有两种情况另起一篇：
   **一件事跨了多次会话**，或者**它本身足够大、值得单独成篇**。
   纯调研/一次性记录把迭代字段写 `-`。
3. **篇号与迭代号分开**：篇号是文件名/标题/回指用的地址（`wl/NNNN`）；迭代号只写在迭代字段（默认 `迭代：`，也认 `变更集/批次/阶段/版本/里程碑`）。
4. **历史不改写**：收口后不抹旧结论；被推翻时**追加** `## 更正`（日期 / 原结论 / 新证据 / 现结论）。
5. **验证要有可核对的内容**（命令 / 数据 / 引用 / 样本）与结果；没做的必须写明"未覆盖 + 原因"。光说"完成了""应该没问题"不算验证。
6. **经验必有来源**：lessons 每条带 `（wl/NNNN）`，来源不存在就不许写。
7. **台账只有一个 `## 当前状态`**，字段固定（见下）；换新块时旧块整段剪到 `work_log/STATE-HISTORY.md`。
8. **编号永不复用，归档不改号**；归档只 move + 改链接。

完整约定见 [references/conventions.md](references/conventions.md)；模板见 [references/templates.md](references/templates.md)。

## 记录精细度（一篇 = 什么）

默认档是 `session`：**一次会话一篇**。档位存在台账 `## 当前状态` 的 `精细度` 字段里。
字段随容器走、进版本控制，不需要新配置文件。

| 档位 | 一篇 = | 一次会话的预期产出 |
|---|---|---|
| `full` | 一个可交付的子单元 | 2–3 篇 |
| **`session`（默认）** | 一次会话，或一个可交付成果 | 最多 1 篇；同一会话里的第二件事**追加到同一篇**；只有一件事跨会话、或它本身够大，才另起一篇 |
| `digest` | 一个阶段 / 跨多次会话 | 多次会话并成一篇 |
| `milestone` | 一个阶段收口 | 只留决策与经验 |

档位只决定**要不要另起一篇**，以及可选叙述写多细。**验证要求不随档位放宽**：任何档位下，一篇记录都必须有可核对的验证小节（铁律 5）。

`digest` / `milestone` 还多一条义务：**写明这一轮刻意没有记录什么**，例如
`未记录：本轮的两处配置调整，见提交 abc1234`。粗粒度合并了多轮会话，不写这一句就等于静默丢信息。

怎么切档：

- **在会话里说一句**（临时）："这次记详细点" / "按阶段汇总就行" → 本轮按 `full` / `digest` 写。
  口头说的只管这一轮，工具不知道。
- **改台账**（持久）：`python scripts/journal.py mode --set digest --why "阶段收口"`。
  之后所有会话都按新档位走，`brief` 里直接看得到。

查看当前档位：`python scripts/journal.py mode`。台账里没有 `精细度` 字段的老项目按默认档 `session` 处理，不会报错。

## 工作流 A · 初始化（项目第一次用）

1. 先查已有体系：`ls` 项目根，找 `work_log/` `journal/` `work-log/` `lessons/` `docs/` 以及根 `README.md` / `CLAUDE.md` / `AGENTS.md` 里的记录约定。
   **已有体系就沿用它的命名与编号，不新建平行目录。**
2. 没有则按 `references/templates.md` 落盘（容器名默认 `work_log/`，可用 `--work-log NAME` 改）：
   - `work_log/README.md`（台账模板）
   - `work_log/lessons/README.md` + `work_log/lessons/01-<topic>.md`（先建 3–5 个与本项目相关的分册）
   - `work_log/STATE-HISTORY.md`、`work_log/ARCHIVE.md`
   - 有日志/运行产物的项目同时建 `work_log/logs/<来源>/`（见下「日志归位」）
   - 在项目根 `README.md` 加一行指向 `work_log/README.md`
3. 跑一次 `journal.py check --strict` 确认骨架自洽（此时 0 篇记录也应通过）。
   台账模板里的**示例索引行**要先删掉或换成真实文件名，否则被判死链。

## 工作流 B · 一项工作（日常）

```
记录 → 确认 → 执行 → 验证 → 收尾
```

1. **记录**：先看档位——`python scripts/journal.py mode <项目根>`。
   默认档 `session` 下，**同一会话已有记录就追加到那一篇**（`append`），不要新开；
   确实要新开时用 `python scripts/journal.py new <项目根> --title "标题" [--iter N]`，把入口 5 行（日期/迭代/触发/范围/结论）先填上。
2. **确认**：方案、口径、取舍写进记录；等用户拍板（涉及数据/破坏性操作必须确认）。
3. **执行**：小步做、每步可回退；做了什么记进「执行」表。
4. **验证**：用该项目能给出的核对方式（测试、数据、引用、样本、评审），把**依据 + 结果 + 未覆盖**写进验证小节。
5. **收尾**：见工作流 C。

## 工作流 C · 收尾清单（每篇记录都走一遍）

1. 记录补齐：`日期/迭代/触发/范围/结论` + 验证小节 + `## 遗留与下一步`。
   档位是 `digest` / `milestone` 时，再加一句「未记录：…」（见上「记录精细度」）。
2. 台账：索引表加一行；涉及跨篇主题就更新「同主题簇」；滚动待办增删。
3. **状态：更新 `## 当前状态` 的 8 个固定字段**：
   `阶段 / 版本`、`迭代`、`产出`、`核对 / 验证`、`交付物与指纹`、`环境`、`阻塞 / 等待`、`精细度`。
   字段名按台账写法原样保留 —— `--set "核对=…"` 会落到 `核对 / 验证` 上（短名可识别），不要手改成新字段。
4. **经验**：本轮若有可复用结论，写进 `work_log/lessons/` 对应分册并回填 `（wl/NNNN）`。
5. **校验**：`python scripts/journal.py check --strict <项目根>` 必须 **0 error**。
   档位是 `digest` / `milestone` 时，再跑一次 `lint`：缺「未记录」那句会报 WARN。
   ⚠ 默认档位的 `check` 把"缺日期 / 缺验证小节 / 漏索引"报成 **WARN（退出码 0）**，
   只有 `--strict` 才把 warning 抬成 error —— 当门禁用必须加 `--strict`。
6. **日志归位**：本轮产生的持久日志 / 运行产物放进 `work_log/logs/<来源>/`，别留在项目根（见下「日志归位」）。
7. 提交：代码与文档一起提交；提交信息引用篇号（如 `work_log: 0042 ...`）。

## 工作流 D · 归档、瘦身与复盘

- **归档判据 = 阶段收口**（某个阶段结束、索引表不再增长），不用"多少天没引用"这类经验值。
- 归档 → 瘦身 → 复盘，三步都是命令，不再手工搬文件：

```bash
python scripts/journal.py archive --stage 02-research --from 27 --to 45   # 搬 + 全仓链接重写 + 死链自检
python scripts/journal.py index compact --stage 02-research               # 已归档小节折叠成一行区间
python scripts/journal.py retro --from 27 --to 45 --out /tmp/retro.md     # 阶段复盘骨架
```

- 很久以后，已归档、又没人引用的记录可以**冷存**（默认只报告，打包后才移出，**绝不直接删**）：
  `prune` → `prune --zip cold.zip` → `prune --zip cold.zip --apply`
- 记录成千上万时用 `split --by-year` 按年分卷（`wl/NNNN` 回指不受目录变化影响）。
- 复盘写进 `work_log/lessons/99-retrospectives.md`（阶段表 / 成果 / 可复用发现 / 遗留），**不要**另建 SUMMARY 文档到处写同一批数字。
- 铁律：**证据不删**——整理永远是"移走 + 汇总 + 留清单"；搬动后必跑 `check` 确认 0 死链。

## 日志归位（任何产出都要归位）

- **持久日志 / 运行产物一律进容器并分类**：`work_log/logs/<来源>/`，一个来源一个子目录
  （例 `work_log/logs/build/`、`work_log/logs/bench/`）。**别散落在项目根，更别写到项目之外。**
- **测试夹具、一次性样本不是记录**，不进 `work_log/`。
- 日志里**不写绝对机器路径**，只写相对项目根的路径（脱敏后再落盘）。

完整表述见 [references/conventions.md](references/conventions.md) 的「日志归位要求」。

## 工具（`scripts/journal.py`，纯标准库）

**核心用法：少读、少写、可校验。** 完整命令说明见 [references/commands.md](references/commands.md)。

```bash
ROOT  # 可省略，默认当前目录

# —— 少读：别整读 50 KB 索引 ——
python scripts/journal.py brief                 # 一屏：当前状态 + 待办 + 近期记录
python scripts/journal.py show 42               # 单篇大纲（先看它再决定读不读全文）
python scripts/journal.py search "会话格式"      # 定向检索（记录+经验，只回命中行）
python scripts/journal.py outline               # 全部记录一行表

# —— 少写：外科式编辑，支持 --dry-run，保留 CRLF ——
python scripts/journal.py new --title "…" --iter 154 --insert --stage "A. 起步"
python scripts/journal.py status --set "迭代=154" --set "核对=抽样 30 条全部通过" --date   # 改状态块（--roll 归档旧块）
python scripts/journal.py mode                                                                  # 当前精细度（默认 session）
python scripts/journal.py mode --set digest --why "阶段收口"                                      # 切档位，附一行原因
python scripts/journal.py todo --add "…" | --done "子串" | --drop-done
python scripts/journal.py index sync --stage "B. 迭代"            # 补漏掉的索引行
python scripts/journal.py lesson add --volume 04-verification-and-safety.md --source 152 --text "…"
python scripts/journal.py append 42 --section 更正 --text "…" --bullet

# —— 整理与清理：只搬不删，全部支持 --dry-run ——
python scripts/journal.py archive --stage 02-research --from 27 --to 45   # 归档 + 链接重写 + 死链自检
python scripts/journal.py index compact --stage 02-research               # 索引瘦身（已归档小节→一行）
python scripts/journal.py split --by-year --dry-run                       # 按年分卷（超长期）
python scripts/journal.py prune                                           # 冷存候选（只报告）

# —— 可校验：两道门禁（有 ERROR 退出码 1）——
python scripts/journal.py check --strict        # 结构：编号/日期/验证/死链/漏索引/状态/来源
python scripts/journal.py lint --strict         # 内容：占位符/空小节/结论无可核对信息/含糊措辞

# —— 分析与生成 ——
python scripts/journal.py stats                 # 语料统计（节奏/合规率/引用覆盖）
python scripts/journal.py topics --limit 15     # 同主题簇建议（中文用 --keywords）
python scripts/journal.py digest --out HANDOFF.md          # 交接摘要
python scripts/journal.py retro --from 100 --to 151 --out r.md  # 阶段复盘骨架
python scripts/journal.py export --csv --out work_log.csv   # 机器可读导出
```

自测：`python scripts/_selftest.py`（临时工程跑通全部命令 + CRLF 保真 + 非编程场景 + 整理能力 + 英文标签 + 数据安全 + 新/旧布局 + 精细度档位；**断言数以脚本实际输出为准**，全绿即通过）。

> 典型接手动作：`brief` → `search` → `show` → 需要细节才 `read` 那一个文件。
> 典型收尾动作：`new --insert` → 补正文 → `status` → `lesson add` → `check --strict` && `lint --strict`。

## 没有 Python 怎么办（降级路径）

**本技能的核心是约定，脚本只是加速器。** 环境里没有 Python 也能完整使用，只是费手：

1. **建结构**：按 [references/templates.md](references/templates.md) 手工落 `work_log/README.md`、`work_log/ARCHIVE.md`、`work_log/STATE-HISTORY.md`、`work_log/lessons/README.md`（已有旧体系就沿用旧名，见「目录布局」的回退顺序）。
2. **写记录**：按记录模板写入口 5 行 + 验证小节 + 遗留；标题固定 `# NNNN · 标题`。
3. **收尾**：把「工作流 C 收尾清单」当人工检查表逐条走；把 `check` / `lint` 的判据（见 [references/commands.md](references/commands.md)）当核对清单。
4. **检索导航**：用 `grep` / `rg` 代替 `search`，用索引表代替 `brief` / `outline`。
5. **整理**：归档就是"移文件 + 改链接"（容器根 → `<stage>/`），手工做时**先全仓 grep 链接再改**——脚本的价值主要就在这里（自动重写 + 死链自检）。

脚本全部只用 Python 标准库，**不需要 `pip install`**；只要 Python 3.9+ 在 PATH 里就能跑
（更精确的实测范围见下方「环境边界」）。若连命令都不能执行（纯聊天环境），技能退化为一份
"怎么写记录"的规范——三层结构、收尾清单、归档判据仍然成立。

## 环境边界

- **纯标准库**，不需要 `pip install`。代码用了 PEP 585 泛型注解（`list[str]`）与海象运算符，
  所以实际下限是 **Python 3.9**；实测 **3.12**（CI / Ubuntu）与 **3.14**（Windows 本机）。
- Windows / macOS / Linux 均可（脚本无平台相关 API）。
- 记录文件用 **UTF-8**。控制台编码无关（脚本自行把 stdout 设为 UTF-8）。
  非 UTF-8 的老仓库**不会让工具崩**（按 `errors="replace"` 读，坏字节变 `�`），
  但中文标签会因此认不出来、`check` 会报一串 WARN —— 那是编码问题，不是记录坏了，先用编辑器转成 UTF-8。
- **解析中英双语**（写入默认中文）：`日期/Date`、`结论/Conclusion`、`触发/Trigger`、`范围/Scope`、
  `迭代/Iteration`（及 `变更集/批次/阶段/版本/里程碑/Milestone`）、
  `验证/Verification`（及 `复核/检查/审查/评审/结果/证据/评估/确认/实测`）、
  `当前状态/Status`、`待办/TODO`、`文件索引/Index` 都能解析。
- 无 Python 或不能执行命令时，按上一节降级为纯规范使用。

## 反模式（本工作区实测踩过的，别再来）

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| 台账靠人肉同步、长期不更 | "当前状态"过期，看板不可信（基线项目实测） | 收尾必更状态块，并用 `check` 判新鲜度 |
| **一次会话里每件事都另起一篇** | 记录按"发生了几件事"增长：基线 151 篇里 127 篇从没被 lessons 引用过 | 默认档 `session`：同一会话并进一篇（`append`）；真要细就 `mode --set full`，别默默多开 |
| 粗档位合并多轮会话，却不写漏了什么 | 粗粒度静默丢信息，事后无处查 | `digest` / `milestone` 下必写一句 `未记录：…` |
| 当前状态 + 一堆历史状态堆在索引 | 索引膨胀、改一处分多处 | 只有一块当前状态，旧块进 `STATE-HISTORY.md` |
| 有的记录写日期、有的不写 | 无法机器校验、审计困难（基线 41/106） | `日期：` 必填，**用 `check --strict` 判 error**（默认档位只是 WARN） |
| 篇号当迭代号引用 | 引用歧义 | 迭代号只写迭代字段，回指一律 `wl/NNNN` |
| README 与 SUMMARY 各写一份数字 | 改一处漏一处 | 复盘并入 `work_log/lessons/99-retrospectives.md`，数字只留一份 |
| lessons 写结论不带来源 | 追不回证据、无法证伪 | 每条带 `（wl/NNNN）`，`check` 校验来源存在 |
| 直接抹掉被推翻的旧结论 | 丢失演进与纠错价值 | 追加 `## 更正` 段 |
| 把软件术语当成通用要求（如"验证必须有命令"） | 研究/写作类项目无法满足，规则被架空 | 验证口径是"可核对的内容"：命令、数据、引用、样本都算 |
| 一次性调研随手建新目录 | 编号体系分裂 | 沿用既有 `work_log/`（或旧名 `journal/`），不编号就写 `迭代: -` |
| 日志、trace、导出文件散在项目根（或写到项目外） | 证据游离在版本控制与备份之外，接手时找不到 | 一律归位到 `work_log/logs/<来源>/`；夹具不进容器；日志只写相对路径 |

## 参考文件

- [references/analysis.md](references/analysis.md) · 基线实测分析与改进对照
- [references/conventions.md](references/conventions.md) · 容器目录布局（含旧布局回退）/编号/生命周期/台账/经验层/日志归位 的硬约定
- [references/commands.md](references/commands.md) · `journal.py` 全部命令与组合套路
- [references/templates.md](references/templates.md) · 记录、台账、归档、经验分册、复盘 全套模板
