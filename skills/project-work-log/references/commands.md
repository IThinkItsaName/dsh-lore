# 命令说明（`scripts/journal.py`）

全部命令：`python scripts/journal.py <命令> [参数]`。
`ROOT` 可省略，默认当前目录；`--journal`（默认 `journal/`，回退 `work-log/`）与 `--lessons`（默认 `lessons/`）用于非标准目录名。
**只读命令**不修改任何文件；**写入命令**都支持 `--dry-run`，做外科式行级编辑（保留 CRLF 与其余字节）。

```bash
python scripts/journal.py --help          # 命令总览
python scripts/_selftest.py               # 自测：临时工程跑通全部命令（含非编程场景、整理能力、英文标签、数据安全）
```

**写入命令的通用规矩**：目标文件必须是 **UTF-8**。不是 UTF-8（GBK 老仓库等）时会**拒绝写入**并返回退出码 2，
文件保持字节不变——这是故意的，避免把解码失败的字节写成 `U+FFFD` 毁掉中文。

## 一、少读：把上下文留给真正要看的内容

| 命令 | 作用 | 典型用法 |
|---|---|---|
| `brief` | **压缩上下文快照**：当前状态（每行截断）+ 未完成待办 + 最近 N 篇。替代整读 50 KB 索引 | `brief --entries 8 --max-status-lines 30 --width 200 --max-todo 10` |
| `show` | **单篇大纲**：元数据 + 触发/范围/结论 + 各小节行数，先看这个再决定要不要读全文 | `show 42` / `show ./proj 42` |
| `search` | **定向检索**：记录 + 经验里按子串/正则只回命中行 | `search "端口冲突"` / `search --regex "E10\d\d" --in journal` / `search "验证" --files`（只列文件） |
| `outline` | 全部记录一行表（编号/日期/迭代/行数/标题），可 `grep` 可排序 | `outline` |

> 用法建议：接手任务先 `brief`；知道大概在哪篇用 `search`；定位到单篇用 `show`；确实需要细节再 `read` 那一个文件。

## 二、少写：外科式维护台账（都支持 `--dry-run`）

| 命令 | 作用 | 典型用法 |
|---|---|---|
| `new` | 生成下一篇记录，可选自动进索引 | `new --title "…" --iter 154 --insert --stage "A. 起步"` |
| `status` | 当前状态块：查看 / 改字段 / 改日期 / 归档旧块 | `status --set "核对=抽样 30 条全部通过" --date` / `status --roll` |
| `todo` | 滚动待办：加 / 勾选 / 清理已完成 | `todo --add "…"` / `todo --done "子串"` / `todo --drop-done` |
| `index sync` | 把漏进索引的根目录记录补成表行（方面取自「结论：」，可用 `--aspect` 覆盖） | `index sync --stage "B. 迭代" --aspect 验证` |
| `lesson add` | 往经验分册追加一条并**校验来源存在** | `lesson add --volume 02-verification.md --source 53 --topic 方法论 --text "…"` |
| `append` | 给某篇追加小节（更正 / 遗留更新） | `append 42 --section 更正 --text "…" --bullet` |

约定要点：
- `status` 永远只维护**唯一**一个 `## 当前状态` 块；`--roll` 会把旧块整段搬进 `journal/archive/STATUS-HISTORY.md` 再写新骨架。
- `status --set "核对=…"` 会落到台账上已有的 `核对 / 验证` 字段（短名可识别），**不会**多长出一个平行字段；
  `阶段` / `交付物` 同理。名字对不上任何既有字段时才会新增。
- `lesson add` 的 `--source` 必须指向真实存在的篇号，否则拒绝写入（防止无主结论）；
  引用会**始终**补上——即使正文里已经提到别的 `wl/NNNN`。
- `append` 若目标小节已存在则追加到该小节末尾，不会重复建标题。
- `new` 的可选参数：`--slug`（文件名后缀；**纯中文标题**会退化成 `<篇号>.md`）、
  `--date`、`--cmd`（写进「方式：」的默认命令）、`--stage`（配合 `--insert` 选索引小节）。

## 三、整理与清理（记录量增长后）

记录本身涨得温和（约 5 KB/篇），**真正膨胀的是索引**（每篇约 600 字符）。下面四个命令把"整理"从人工步骤变成可复现动作，
全部支持 `--dry-run`，而且**只搬不删**：

| 命令 | 作用 | 典型用法 |
|---|---|---|
| `index compact` | **索引瘦身**：把「整节都已归档」的小节折叠成一行区间（`\| [archive/xx/](archive/xx/) \| 0027–0045（19 篇，已归档） \|`）。只动索引；混合小节、含死链的小节、**已折叠过的目录行**都自动跳过（所以可重复跑） | `index compact --dry-run` / `index compact --stage A` |
| `archive` | **归档**：把篇号区间移进 `journal/archive/<stage>/`，自动重写全仓链接（索引 / lessons / **被移动记录自己的出站链接**）、补 `archive/README.md` 一行，并做**死链自检** | `archive --stage 02-research --from 27 --to 45` / `--no-index` 跳过索引行更新 |
| `split` | **按年分卷**：把活跃记录移进 `journal/<YYYY>/`（取自入口行的 `日期：`），重写链接。适合上千篇的超长期项目 | `split --by-year --dry-run` |
| `prune` | **冷存**：列出「已归档 + 未被 lessons 引用 + 超期」的候选；`--zip` 打包（自动建输出目录）；`--apply` 才把原件移出并写 `COLD-STORE.md` 清单。**默认只报告** | `prune` → `prune --zip cold.zip` → `... --apply`；`--stage` 限定阶段、`--cold-store` 指定冷存目录 |

推荐顺序：**`archive` → `index compact` →（很久以后）`prune`**；记录过万再考虑 `split --by-year`。

> 铁律：**证据不删**。`prune --apply` 是"移出到冷存目录 + 留清单"，不是删除；真要删由人工确认后自己动手。
> 搬动前后都会扫一遍 md 链接，有死链直接报错退出（内容仍在，git 可回退）。
> `wl/NNNN` 这类纯编号引用**不受目录变化影响**——这正是"编号即地址"的价值。

## 四、可校验：两道门禁

| 命令 | 检查内容 | 退出码 |
|---|---|---|
| `check` | 结构：编号重复/断档、标题篇号一致、`日期：` 行、验证小节、md 死链、漏索引、状态块唯一且新鲜、lessons 来源可回指 | 有 ERROR → 1 |
| `lint` | 内容：占位符残留（`<命令 / 数据 / 引用 / 样本>`/`TODO`…）、空小节、结论无可核对信息、验证无可核对内容、含糊措辞（"应该没问题"） | 有 ERROR → 1 |

`--strict` 把 WARN 当 ERROR（新项目/CI 建议开）；`--quiet` 不打印 INFO。
旧仓库首次跑会有大量 WARN（缺日期行等）——那正是待回填清单，不是工具坏了。

> ⚠ **默认档位不是门禁**：缺 `日期：`、缺验证小节、漏索引、状态块没日期，默认都只报 **WARN（退出码 0）**。
> 只有 `--strict` 才把它们抬成 ERROR。要当 CI 门禁，必须写 `check --strict && lint --strict`。

> **领域无关**：迭代字段解析时兼容 `迭代 / 变更集 / 批次 / 阶段 / 版本 / 里程碑`（英文 `Iteration / Milestone`）；
> “验证”小节接受 `验证 / 复核 / 检查 / 评审 / 结果 / 证据 / 评估 / 确认 / 实测 / 审查`（英文 `Verification / Review / Results / Evidence / Tests`），
> 标题级别 h2–h4 都认；
> `lint` 的“可核对内容”包括命令、数字、链接——不强制要求可执行命令。

## 五、分析与生成：不止于记账

| 命令 | 作用 | 典型用法 |
|---|---|---|
| `stats` | 语料统计：总量、日期跨度、每周节奏、日期/验证合规率、体积、迭代字段覆盖、经验引用覆盖与 top cited | `stats` |
| `topics` | **同主题簇建议**：自动找"出现在 2–N 篇"的标识符；中文用 `--keywords` 指定 | `topics --limit 15 --max-df 5` / `topics --keywords "关键决策,评审意见"` |
| `digest` | **生成交接摘要文档**：状态 + 待办 + 近期记录表 + 经验要点，`--out` 落盘可直接给新会话/新同事 | `digest --entries 12 --per-volume 3 --out HANDOFF.md` |
| `retro` | **阶段复盘骨架**：给篇号区间，自动生成阶段表 + 汇总区间内未完成项，用于 `lessons/99-retrospectives.md` | `retro --from 100 --to 151 --stage "第三阶段" --out retro.md` |
| `export` | 机器可读导出（JSON 默认 / `--csv`），供其它脚本消费 | `export --csv --out journal.csv` / `export --json` |

`topics` 的自动模式只认 ASCII 标识符（文件名、编号、专有名词、错误码），中文主题请用 `--keywords`——这是无依赖环境下的取舍，已在输出里说明。

## 六、组合套路（省上下文的标准动作）

```bash
# 1. 接手：一屏拿到坐标
python scripts/journal.py brief

# 2. 找旧结论：先检索，再只看那一篇的大纲
python scripts/journal.py search "会话格式" --in journal
python scripts/journal.py show 51

# 3. 收尾一篇：补索引 → 更新状态 → 抽经验 → 过门禁
python scripts/journal.py new --title "…" --iter 154 --insert --stage "新阶段"
python scripts/journal.py status --set "迭代=154" --set "核对=抽样 30 条全部通过" --date
python scripts/journal.py lesson add --volume 04-verification-and-safety.md --source 152 --text "…"
python scripts/journal.py check --strict && python scripts/journal.py lint --strict

# 4. 阶段结束：归档 + 复盘骨架
python scripts/journal.py retro --from 100 --to 151 --out lessons/99-retrospectives.md
python scripts/journal.py digest --out HANDOFF.md
```

## 七、内部脚本

| 文件 | 用途 |
|---|---|
| `_selftest.py` | 自测全部命令（临时目录，含 CRLF 保真、"只改目标行"、非编程场景、非 UTF-8 拒写等断言）。`--root DIR` 指定夹具父目录（写入受限的沙箱里用），`--keep` 保留夹具排查 |
| `_package.py` | 把 skill 源目录同步进可发布仓库（开发工作区专用，不随包发布）；`--check` 兼作漂移与插件文件完整性门禁 |
| `_measure.py` | 对现成 `work-log/`+`lessons/` 做一次性测量，`references/analysis.md` 的数字由它复现 |
