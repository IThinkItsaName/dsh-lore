# 命令说明（`scripts/journal.py`）

全部命令：`python scripts/journal.py <命令> [参数]`。
`ROOT` 可省略，默认当前目录。目录参数：

| 参数 | 含义 | 默认与回退 |
|---|---|---|
| `--work-log NAME` | **容器目录**名（台账 + 记录 + 经验 + 日志都收在它下面） | 默认 `work_log/`；回退旧名 `journal/`、`work-log/`。配置文件里的 `container` 改不了它 |
| `--journal NAME` | 上一个参数的旧名，**等价**（已弃用但保留） | 同上 |
| `--lessons NAME` | 容器内的**经验目录**名 | 默认 `lessons/`；再认配置文件里的 `lessons`；顺序 `命令行 → 配置 → <容器>/lessons/ → <根>/lessons/` |

> 旧项目（`journal/` + 顶层 `lessons/`）**不改名、不迁移、不警告**，直接就能用；
> 解析顺序见 [conventions.md](conventions.md)「旧布局的读取回退」。
> **只读命令**不修改任何文件；**写入命令**都支持 `--dry-run`，做外科式行级编辑（保留 CRLF 与其余字节）。

**优先级只有三层**：`命令行参数 > <容器>/.config.json > 内置默认`。
缺 `.config.json` 不是错误，它等于"全部取内置默认"。逐字段看生效值与来源用 `config`（见下）。

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
| `snapshot` | **入口元信息快照**：把最近 N 篇开头的元信息汇总成一份**只读**清单（见下） | `snapshot --entries 12` / `snapshot --entries 5 --out SNAP.md` |
| `show` | **单篇大纲**：元数据 + 入口 + 触发/范围/结论 + 各小节行数，先看这个再决定要不要读全文 | `show 42` / `show 2026-09-06` / `show 2026-09-06-门控两段式.md` / `show ./proj 42` |
| `search` | **定向检索**：记录 + 经验里按子串/正则只回命中行 | `search "端口冲突"` / `search --regex "E10\d\d" --in work_log` / `search "验证" --files`（只列文件） |
| `outline` | 全部记录一行表（身份/日期/迭代/行数/标题），可 `grep` 可排序 | `outline` |

> 用法建议：接手任务先 `brief`；想知道"最近几篇各自做到哪"用 `snapshot`；知道大概在哪篇用 `search`；
> 定位到单篇用 `show`；确实需要细节再 `read` 那一个文件。

### snapshot：最近 N 篇的入口元信息汇总（只读）

```bash
python scripts/journal.py snapshot --entries 12
python scripts/journal.py snapshot --entries 5 --width 160
python scripts/journal.py snapshot --entries 20 --out SNAP.md
```

为什么要它：**状态的位置由容器自己决定**。`comfy` 把状态放在台账的 `## 当前状态` 块里，
`embeding try` 把它写在**每篇开头的引用块**里（`> 状态：… ｜ 工具：… ｜ 产物：…`），
原型写在入口字段行里（`日期：/触发：/范围：/结论：`）。集中式有 `brief` 可看，分散式没有对应命令——
`snapshot` 就是补这个缺口。

- **只读**：只往 stdout 打印，**绝不改动容器里的任何文件**。`--out` 是给调用方自己落盘用的。
- 两种入口都认：**引用块式**（`> 状态：… ｜ 工具：…`）与**字段行式**（`日期：…`），
  也认 `### 入口` / `### 元信息` 小节式。只输出确实有值的字段，缺的不占位。
- **没有入口块不是错误**：那一行显示「（没有入口元信息块）」，末尾统计几篇没写，命令照常退出 0。
- `--entries`（默认 12）按**身份降序**取最近 N 篇：日期式容器按日期、编号式容器按篇号。
  默认值可以被 `.config.json` 的 `snapshotEntries` 改掉；命令行给了 `--entries` 就以命令行为准。

输出样例（实测 `embeding try/3_param_block`，去掉了一部分）：

```
# SNAPSHOT  work_log  （最近 5 / 共 28 篇；只读快照，不改任何文件）

2026-09-20  2026-09-20-R21-slot悬崖机制.md  `slot` 悬崖的机制 —— 是超参缩放伪影，不是容量极限
    状态：**已完成**。两轮：6000 步筛（6 配置）+ 20000 步定论（4 配置），各 3 种子。 ｜ 工具：`code/diag_slot_cliff.py` ｜ 产物：`exp/exp-sloteta-budget-*.json`（6）
2026-09-19  2026-09-19-R18-历史结论重验与预算外推.md  历史排名结论全量重验 + 10000 步排名能否外推
    （没有入口元信息块）

（2/5 篇没有入口元信息块——不是错误，只是这层没写）
```

## 二、少写：外科式维护台账（都支持 `--dry-run`）

| 命令 | 作用 | 典型用法 |
|---|---|---|
| `new` | 生成下一篇记录，可选自动进索引 | `new --title "…" --iter 154 --insert --stage "A. 起步"` |
| `mode` | **记录精细度**（一篇 = 什么）：查看 / 切换档位 | `mode` / `mode --set digest --why "阶段收口"` |
| `config` | **项目配置文件**（`<容器>/.config.json`）：看生效值与来源 / 写出 / 改一项 | `config` / `config --write` / `config --set mode=digest` |
| `status` | 当前状态块：查看 / 改字段 / 改日期 / 归档旧块 | `status --set "核对=抽样 30 条全部通过" --date` / `status --roll` |
| `todo` | 滚动待办：加 / 勾选 / 清理已完成 | `todo --add "…"` / `todo --done "子串"` / `todo --drop-done` |
| `index sync` | 把漏进索引的根目录记录补成表行（方面取自「结论：」，可用 `--aspect` 覆盖） | `index sync --stage "B. 迭代" --aspect 验证` |
| `lesson add` | 往经验分册追加一条并**校验来源存在** | `lesson add --volume 02-verification.md --source 53 --topic 方法论 --text "…"` |
| `append` | 给某篇追加小节（更正 / 遗留更新） | `append 42 --section 更正 --text "…" --bullet` |

约定要点：
- `status` 永远只维护**唯一**一个 `## 当前状态` 块；`--roll` 会把旧块整段搬进 `work_log/STATE-HISTORY.md`
  再写新骨架（旧布局已有 `archive/STATUS-HISTORY.md` 时沿用它，不另起一份）。
- `status --set "核对=…"` 会落到台账上已有的 `核对 / 验证` 字段（短名可识别），**不会**多长出一个平行字段；
  `阶段` / `交付物` 同理。名字对不上任何既有字段时才会新增。- `lesson add` 的 `--source` 必须指向真实存在的篇号，否则拒绝写入（防止无主结论）；
  引用会**始终**补上——即使正文里已经提到别的 `wl/NNNN`。
- `append` 若目标小节已存在则追加到该小节末尾，不会重复建标题。
- `new` 的可选参数：`--slug`（文件名后缀；**纯中文标题**会退化成 `<篇号>.md`）、
  `--date`、`--cmd`（写进「方式：」的默认命令）、`--stage`（配合 `--insert` 选索引小节）。

### mode：记录精细度（一篇 = 什么）

```bash
python scripts/journal.py mode                    # 打印当前档位 + 一行释义
python scripts/journal.py mode --set digest       # 切换档位
python scripts/journal.py mode --why "阶段收口"    # 只补一行切换原因，不改档位
python scripts/journal.py mode --set full --dry-run
```

档位存在台账 `## 当前状态` 的第八个固定字段 `精细度`：

| 档位 | 一篇 = | 一次会话的预期产出 |
|---|---|---|
| **`full`（默认）** | 一个可交付的子单元 | 2–3 篇；同一天多篇很正常 |
| `session` | 一次会话，或一个可交付成果 | 最多 1 篇；同一会话的第二件事追加到同一篇 |
| `digest` | 一个阶段（跨多次会话） | 多次会话并成一篇 |
| `milestone` | 一个阶段收口 | 只留决策与经验 |

输出：

```
full   一段可交付的子单元就是一篇，一次会话可能开出 2–3 篇。
（台账里没有 `精细度` 字段：当前取内置默认 `full`）
切换：`journal.py mode --set full|session|digest|milestone`（当前 full）
```

要点：

- **没有 `精细度` 字段不算错**：报默认档并明说它的来源。来源是 `.config.json` 的 `mode`（有就取），
  否则是内置默认 `full`。这次改动之前写下的台账照样能跑。
- **配置的 `mode` 只是初始值**：台账有 `精细度` 时一切以台账为准（`mode` 读写的一直是台账那一栏）。
- **默认档为什么是 `full`**：实测原型 111 篇带日期的记录分布在 12 个日期上（平均 9.2 篇/天，
  最多一天 **34 篇**）。`session` 会把那 34 篇压成一篇，埋掉 34 个可独立查阅的单元。
  粗档位用于确实低强度、以阶段为单位的项目（写作、调研、运维）。
- **值一律写拉丁规范值**；`--set` 也认中文别名（`完整` / `会话` / `摘要` / `里程碑`），并忽略大小写，写入时规范化。
- `--set` 的取值在这里手工校验：**未知值报 `ERROR: 认不出的精细度 …` 并退出码 2**，不改任何文件。
- `--why` 把原因写进同一个字段值：`- 精细度：digest（原因：阶段收口）`。之后 `mode` / `brief` / `status` 都能看到。
- `--set --dry-run` 只打印将写入的值，与其它写入命令一致。
- 没有容器时报「找不到记录容器」并退出 1，与 `status` / `todo` 一致。
- **档位不放宽验证**：任何档位下 `check` 都照报验证类小节的问题。`digest` / `milestone` 另有一条义务——
  写明这一轮**刻意没记什么**（`未记录：…`），缺了由 `lint` 报 WARN（**不是** ERROR，老项目不会因此变红）。
  档位来自台账或配置文件的 `mode` 时，这条义务一样成立。

### config：项目配置文件（`<容器>/.config.json`）

```bash
python scripts/journal.py config                       # 看每个字段的生效值与来源
python scripts/journal.py config --write               # 按当前生效值写出配置文件
python scripts/journal.py config --write --force       # 覆盖已存在的那份
python scripts/journal.py config --set mode=digest     # 只改一个字段，保留其余字段与换行风格
python scripts/journal.py config --set legacy=0007-*,archive/**
python scripts/journal.py config --legacy "0007-*"     # 看命令行把 legacy 压成了什么
```

配置文件的字段（都可以缺；缺就是内置默认）：

| 字段 | 类型 | 内置默认 | 生效在 |
|---|---|---|---|
| `mode` | `full` / `session` / `digest` / `milestone` | `full` | 台账**没有** `精细度` 字段时的默认档 |
| `container` | string | `work_log` | **只是备注**，见下 |
| `lessons` | string | `lessons` | 经验目录的候选名（目录存在才作数） |
| `legacy` | string[] | `[]` | 同 `--legacy`（渐进原则的旧记录清单） |
| `snapshotEntries` | number | `12` | `snapshot` 的默认 `--entries` |

**优先级只有三层**：`命令行参数 > <容器>/.config.json > 内置默认`。
每一层都能单独压过下一层，`config` 会把每个字段实际来自哪一层打出来：

```
# CONFIG  work_log/.config.json  （存在）
mode            = digest           ← .config.json
container       = work_log         ← 内置默认
lessons         = lessons          ← .config.json
legacy          = （空）           ← 内置默认
snapshotEntries = 12               ← .config.json
```

**两个名字字段要单独理解。** `container` 与 `lessons` 命名的正是配置文件**自己所在的目录**，
所以读配置文件之前就得先知道它们——只能按目录发现。于是：

- `container`：按目录发现（`--work-log` → `work_log/` → `journal/` → `work-log/`）。配置文件里写的
  `container` **改不了生效值**，它连自己所在的目录都指不动。**只报，不用，也不报错**。
- `lessons`：顺序是 `--lessons` → 配置里的 `lessons` → `<容器>/lessons/` → `<根>/lessons/`。
  配置里的名字只是"上哪儿找"的提示，**目录真的存在才算数**；不一致时以实际目录为准并报出来。

所以这两个字段最好理解成"**新项目该叫什么**"——这也正是插件在项目初始化时把它们写进配置文件的原因。
已建好的项目改名不会被追认：真正决定读哪儿的一直是目录本身。

要点：

- **缺配置文件不是错误**：全部取内置默认，`config` 照常退出 0。
- `container` / `lessons` 的值必须是目录名（非空、不含 `/` 与 `\`）。
- `--set` **就地改一行**：保留 CRLF 与其余字段（含工具不认识的字段）。改不动时才整体重排，重排也保留换行风格。
- `--set` 的取值手工校验：**未知档位 / 未知字段 / 非正整数各自退出码 2**，不改任何文件。
  未知字段会把 5 个合法字段连取值说明一起列出来。
- 配置文件**不存在**时 `--set` 拒绝（先 `config --write`）；`--write` 对已存在的文件拒绝覆盖（除非 `--force`）。
- 配置**读不动**（不是合法 JSON、值非法、字段名认不出）时：其它命令一律按内置默认继续跑，
  `config` 逐条打印并以退出码 2 收场，`check` 也提一句（INFO，不进退出码）。
- 没有容器时：只读视图照常打印（等于全部内置默认），`--write` / `--set` 报「找不到记录容器」退出 1。

## 三、整理与清理（记录量增长后）

记录本身涨得温和（约 5 KB/篇），**真正膨胀的是索引**（每篇约 600 字符）。下面四个命令把"整理"从人工步骤变成可复现动作，
全部支持 `--dry-run`，而且**只搬不删**：

| 命令 | 作用 | 典型用法 |
|---|---|---|
| `index compact` | **索引瘦身**：把「整节都已归档」的小节折叠成一行区间（`\| [02-research/](02-research/) \| 0027–0045（19 篇，已归档） \|`）。只动索引；混合小节、含死链的小节、`lessons/` 这类非记录行、**已折叠过的目录行**都自动跳过（所以可重复跑） | `index compact --dry-run` / `index compact --stage A` |
| `archive` | **归档**：把篇号区间移进 `<容器>/<stage>/`（不再是 `archive/<stage>/`），自动重写全仓链接（索引 / lessons / **被移动记录自己的出站链接**）、补 `ARCHIVE.md` 一行，并做**死链自检** | `archive --stage 02-research --from 27 --to 45` / `--no-index` 跳过索引行更新 |
| `split` | **按年分卷**：把活跃记录移进 `<容器>/<YYYY>/`（取自入口行的 `日期：`），重写链接。适合上千篇的超长期项目 | `split --by-year --dry-run` |
| `prune` | **冷存**：列出「已归档 + 未被 lessons 引用 + 超期」的候选；`--zip` 打包（自动建输出目录）；`--apply` 才把原件移出并写 `COLD-STORE.md` 清单。**默认只报告** | `prune` → `prune --zip cold.zip` → `... --apply`；`--stage` 限定阶段、`--cold-store` 指定冷存目录 |

推荐顺序：**`archive` → `index compact` →（很久以后）`prune`**；记录过万再考虑 `split --by-year`。

> 铁律：**证据不删**。`prune --apply` 是"移出到冷存目录 + 留清单"，不是删除；真要删由人工确认后自己动手。
> 搬动前后都会扫一遍 md 链接，有死链直接报错退出（内容仍在，git 可回退）。
> `wl/NNNN` 这类纯编号引用**不受目录变化影响**——这正是"编号即地址"的价值。

## 四、可校验：两道门禁

| 命令 | 检查内容 | 退出码 |
|---|---|---|
| `check` | 结构：标题与文件名一致（两种命名）、验证小节（含实质内容）、md 死链、漏索引、状态块唯一且新鲜、lessons 来源可回指、目标表（可选文件，见下） | 有 ERROR → 1 |
| `lint` | 内容：占位符残留（`<命令 / 数据 / 引用 / 样本>`/`TODO`…）、空小节、结论无可核对信息、验证无可核对内容、含糊措辞（"应该没问题"）、粗档位记录缺 `未记录：…` | 有 ERROR → 1 |

`--strict` 把 WARN 当 ERROR（新项目/CI 建议开）；`--quiet` 不打印 INFO。

> **老仓库第一次跑不再是一片红**：默认按容器规模兜底（记录 ≥ 5 篇就整批算旧记录），
> 因旧格式而失败的发现只报 `[INFO]`；记录还少的新项目不受兜底，照报 error。见下「渐进原则」。

> **领域无关**：迭代字段解析时兼容 `迭代 / 变更集 / 批次 / 阶段 / 版本 / 里程碑`（英文 `Iteration / Milestone`）；
> “验证”小节接受 `验证 / 复核 / 检查 / 评审 / 结果 / 证据 / 评估 / 确认 / 实测 / 审查 / 实验 / 判定 / 评测`
> （英文 `Verification / Review / Results / Evidence / Tests`），标题级别 h2–h4 都认；
> `lint` 的“可核对内容”包括命令、数字、链接——不强制要求可执行命令。
> 精细度档位（`mode`）**不改变这两道门禁的判据**：验证小节在所有档位下都必填；
> 只有“粗档位要写明未记录什么”这一条随档位增加。

### 验证小节实质要求（新）

**光有标题不够，只有设置也不算。** `check` 会看验证类小节里**有没有可核对的结果**：

| 档 | 判据 | 例 |
|---|---|---|
| **通用** | 2 个以上独立数字、或 2 个以上反引号内容、或 3 行以上表格/列表，**或者**正文 ≥120 字符（散文论述） | `- 结果：312 passed` ✅ / `- 结果：测试通过` ❌ |
| **设置类标题**（含 `设置 / 目的 / 方法 / 计划 / 步骤 / 待办 / 框架 / 准备 / 背景 / 口径`） | **必须有 2 个以上数字，或有表格** —— 命令不算数 | `## 评测设置`＋一句 `python x.py --variant 2` ❌（只有做法，没有结果） |

报出来的样子：

```
[WARN] work_log/0003-只有设置.md: 验证小节 `评测设置` 只有长度 35 字符、只有设置没有结果——要数字 / 百分比 / 命令 / 引用输出 / 表格 / 对照
```

**默认 WARN，`--strict` 下才是 ERROR。** 这是刻意的：判据是启发式的，不该由它下判决。

**已知误报与漏报（写在这里是因为它一定会有）：**

- **误报**：讲方法的散文（"方法对比"、"口径讨论"）如果标题里带了上述设置类词、又不落数字，会被报出来。
  同类还有：非常短但确实有效的验证小节（例如只写"`check --strict` 0 error / 0 warn"）。
- **漏报**：`## 验证：本次未独立验证，见 wl/0009` 这种**诚实的否定**因为带数字会被放过去。
- **取舍**：漏报比误报便宜——漏报只是少提醒一句，误报会让人开始忽略这个工具。
  真实语料上的命中量很小，可作为"敏感度"参照：`comfy` 30 篇 **0 命中**、
  原型 207 篇 **3 命中**、`embeding try` 71 篇 **1 命中**。
- **想绕开它**：把结果写进同一个验证小节即可（数字/表格/命令输出都算）；或者把该记录放进 `LEGACY.md`。

### 渐进原则（老记录只报不拦）

新写的记录按新规格判 error；**改动之前写下的记录只报 info**，避免"第一次跑就是一片红、然后学会忽略它"。

判定依据是**显式清单**，不是日期启发式（日期不可靠）。四处来源，**优先级从高到低**——
命令行给了就以它为准（连空串也算给了），否则看 `.config.json` 的 `legacy`，再看 `LEGACY.md`，
都没有才用规模兜底：

```bash
# 1) 命令行（最高优先级；显式给了就以它为准，连空串也算显式）
python scripts/journal.py check --legacy "0007-*,archive/**"
python scripts/journal.py check --legacy ""          # 没有旧记录：全部按新格式判
python scripts/journal.py lint  --legacy "comfy-*"   # lint 同样支持
```

```jsonc
// 2) <容器>/.config.json 的 legacy（跟着项目进版本控制；--legacy 仍可压过它）
{ "legacy": ["0007-*", "archive/**"] }
```

```markdown
<!-- 3) 容器根的 LEGACY.md（跟着容器进版本控制，团队共用） -->
# 旧记录

- 0001-*
- archive/**
```

4. **规模兜底**（最低优先级）：前三者都没有时，**记录 ≥ 5 篇**的容器整批算旧记录，
   **少于 5 篇**的容器算新项目。所以老项目零配置也是干净输出，而新项目里写坏的记录照报 error。
   这条兜底**宁可多报也不放过新记录**：体量小的老项目会被当成新项目，用 `LEGACY.md` 收准即可。

受影响的**只有**这三类旧格式规则：**H1 形制**、**入口 `日期：` 行 / 空 `结论：`**、**验证小节**。
**死链、漏索引、编号重复/断档、lessons 来源**永远照报（它们是改动之前就有的客观规则）。

降级的条目照样打印（级别 `[INFO]`），并在末尾提示降了几条：

```
Summary: 7 error / 0 warn / 130 info  (--strict)
（其中 127 条按渐进原则降为 info：命中的是旧记录，见 commands.md「渐进原则」）
```

### 目标表（`<容器>/目标.md`，可选）

**缺这个文件是正常的**（三个真实语料里一个都没有），`check` 报 **0 个问题**。
有它时只校验三条机械规则，三条都是 **ERROR**（机械判据，不必开 `--strict`）：

```text
[ERROR] work_log/目标.md: 第 5 行：「目标」为空，而它前面没有一行写出过目标名（一个目标的第一行必须写目标名，续行只能跟在这种行后面）
[ERROR] work_log/目标.md: 第 8 行：状态「进行重」认不出，只能是 未开始 / 进行中 / 已完成 / 已放弃
[ERROR] work_log/目标.md: 第 9 行：状态为空，必须是 未开始 / 进行中 / 已完成 / 已放弃 之一
[ERROR] work_log/目标.md: 第 8 行：相关记录 `0009` 指向的篇号在记录目录里不存在
```

| 规则 | 判据 |
|---|---|
| 引用的篇号必须真实存在 | 「相关记录」格里**整格就是一篇号**（`0007`，也可写 `wl/0007`）才判；`—`、自由文字、日期式文件名一律跳过 |
| 状态必须是那四个之一 | `未开始` / `进行中` / `已完成` / `已放弃`，拼错或为空都报 |
| 一个目标的第一行必须写目标名 | 在第一个目标名之前出现空的目标格就报：那一行没有父行 |

**明确不校验**：阶段名与索引里的 `### <阶段名>` 是否一致、状态与记录内容是否相符、目标是否重复。
判定不了，或者校验了只会教人忽略告警。状态**人工维护**，不从引用的记录推导。

这个文件不是记录，所以**不进索引**（索引覆盖只遍历真记录），也**不是必填项**；
表里出现的 md 链接照样按通用规则查死链。

## 五、分析与生成：不止于记账

| 命令 | 作用 | 典型用法 |
|---|---|---|
| `stats` | 语料统计：总量、日期跨度、每周节奏、日期/验证合规率、体积、迭代字段覆盖、经验引用覆盖与 top cited | `stats` |
| `topics` | **同主题簇建议**：自动找"出现在 2–N 篇"的标识符；中文用 `--keywords` 指定 | `topics --limit 15 --max-df 5` / `topics --keywords "关键决策,评审意见"` |
| `digest` | **生成交接摘要文档**：状态 + 待办 + 近期记录表 + 经验要点，`--out` 落盘可直接给新会话/新同事 | `digest --entries 12 --per-volume 3 --out HANDOFF.md` |
| `retro` | **阶段复盘骨架**：给篇号区间，自动生成阶段表 + 汇总区间内未完成项，用于 `work_log/lessons/99-retrospectives.md` | `retro --from 100 --to 151 --stage "第三阶段" --out retro.md` |
| `export` | 机器可读导出（JSON 默认 / `--csv`），供其它脚本消费 | `export --csv --out work_log.csv` / `export --json` |

`topics` 的自动模式只认 ASCII 标识符（文件名、编号、专有名词、错误码），中文主题请用 `--keywords`——这是无依赖环境下的取舍，已在输出里说明。

## 六、组合套路（省上下文的标准动作）

```bash
# 0. 新项目（可选）：把默认档与旧记录清单写进项目配置文件，之后每次执行都立即生效
python scripts/journal.py config --write                  # 先按当前生效值落盘
python scripts/journal.py config --set mode=digest        # 再改要改的那一项
python scripts/journal.py config                         # 随时确认每个值来自哪一层

# 1. 接手：一屏拿到坐标
python scripts/journal.py brief

# 2. 找旧结论：先检索，再只看那一篇的大纲
python scripts/journal.py search "会话格式" --in work_log   # 旧写法 --in journal 等价
python scripts/journal.py show 51

# 3. 收尾一篇：补索引 → 更新状态 → 抽经验 → 过门禁
python scripts/journal.py mode                     # 先确认档位：默认 full = 一个可交付单元一篇
python scripts/journal.py new --title "…" --iter 154 --insert --stage "新阶段"
python scripts/journal.py status --set "迭代=154" --set "核对=抽样 30 条全部通过" --date
python scripts/journal.py lesson add --volume 04-verification-and-safety.md --source 152 --text "…"
python scripts/journal.py check --strict && python scripts/journal.py lint --strict

# 3b. 老仓库第一次接手：先看整体情况，不要急着修
python scripts/journal.py snapshot --entries 12    # 最近 12 篇各自做到哪（只读）
python scripts/journal.py check                     # 旧记录只报 info，输出是干净的
python scripts/journal.py check --strict --legacy ""  # 想看"全按新格式"会红多少

# 4. 阶段结束：切档位 → 归档 → 复盘骨架
python scripts/journal.py mode --set digest --why "阶段收口"
python scripts/journal.py retro --from 100 --to 151 --out work_log/lessons/99-retrospectives.md
python scripts/journal.py digest --out HANDOFF.md
```

## 七、内部脚本

| 文件 | 用途 |
|---|---|
| `_selftest.py` | 自测全部命令（临时目录，含 CRLF 保真、"只改目标行"、非编程场景、非 UTF-8 拒写、新布局与旧布局回退、精细度档位与"验证不随档位放宽"、**两种命名约定、渐进原则、实质验证、snapshot 只读、项目配置文件与其三层优先级、目标表的三条规则**等断言）。`--root DIR` 指定夹具父目录（写入受限的沙箱里用），`--keep` 保留夹具排查 |
| `_package.py` | 把 skill 源目录同步进可发布仓库（开发工作区专用，不随包发布）；`--check` 兼作漂移与插件文件完整性门禁 |
| `_measure.py` | 对现成 `work_log/`（或旧 `work-log/`）+ `lessons/` 做一次性测量，`references/analysis.md` 的数字由它复现；同时报出台账的 `精细度`（缺字段则报默认档） |

## 八、容器根上的辅助文件

| 文件 | 谁写 | 作用 |
|---|---|---|
| `README.md` | 人 / `index sync` / `status` | 台账（索引 + 待办 + 可选状态块）。**缺它只报 info**，不是错误 |
| `STATE-HISTORY.md` | `status --roll` | 被替换下来的旧状态块（只搬运，不改写） |
| `ARCHIVE.md` | `archive --stage` | 归档索引，每次归档补一行 |
| `COLD-STORE.md` | `prune --zip --apply` | 冷存清单 |
| `LEGACY.md` | **人**（工具只读） | 旧记录声明（见「渐进原则」）；工具**从不写**它 |
| `目标.md` | **人 / agent**（工具只读） | 长期目标 → 阶段的两层表（见 §四「目标表」）；**需要时才建**，缺它是正常的 |
| `.config.json` | `config --write` / `config --set` | 项目配置文件（见 §二「config」）；**缺它等于全部内置默认** |
