# dsh-lore

**一条工作记忆链路**，不是一个日志工具。三块能力，依赖**单向向下**：

| 层 | 干什么 | 依赖 |
|---|---|---|
| **技能层** | 把一次会话做过的事**留在项目里**：过程记录 + 索引台账 + 经验手册 + 27 个子命令的工具箱 | 只要 Python 标准库，**不需要 DSH** |
| **记忆层** | 把跨项目学到的东西**存在所有工作区之外**（记忆根可配置，默认 `~/dsh-lore-memory`）：来源分档、索引、收敛、升格、信箱 | 纯文件，不知道插件存在 |
| **插件层** | 在 DSH 上把记忆**送到模型眼前**（索引注入）、给模型读写记忆的工具、把技能注册进宿主、一张配置卡片 | DSH（`dsh.bundle`） |

**三层可以只用一层**：只装技能层，就是一套完整可校验的记录体系（`skill-only/` 那条线更极端 —— 连脚本都不要）。
**不限编程**：软件、研究、写作、设计、运营、教学都能用（术语与验证口径怎么换，见
[`references/conventions.md`](skills/project-work-log/references/conventions.md)）。

> **来源与免责声明**：本仓库的约定、文档与脚本整理自作者使用 **DeepSeek Flash 系列模型**处理内容时的常用操作，
> 并**完全由 DeepSeek Flash 系列模型整理生成**（未经人工逐条校验）。使用时请自行甄别，**不保证效果、正确性与适用性**。

> **曾用名 `dsh-worklog`**（2026-09-30 改名；GitHub 仓库同时改为 `IThinkItsaName/dsh-lore`，旧链接自动重定向）。
> **环境变量仍是 `DSH_WORKLOG_*`**、技能名 `project-work-log`、工具名 `worklog_memory` 也都没变。

版本变化见 [CHANGELOG.md](CHANGELOG.md)（最近三版：`0.9.0` 信箱发信与主动送达 · `0.8.1` 记忆根设置在桌面 profile 上真的生效 ·
`0.8.0` 记忆根可配置）。

## 一、三层的边界

- **技能层**：过程层 `<容器>/NNNN-*.md`（一篇 = 一个迭代）· 索引层 `<容器>/README.md`（分阶段索引 + 同主题簇 +
  滚动待办 + **唯一**当前状态块）· 经验层 `<容器>/lessons/*.md`（症状 → 根因 → 做法 → 来源）· 已归档的住 `<容器>/archive/`。
  容器名与经验目录名可用 `journal.py config` 改（旧布局 `journal/` 仍认）。配套脚本让代理**少读、少写、可校验**：
  改台账是行级编辑（保留 CRLF），死链、断档、漏索引、来源悬空、占位符、结论没数字都能自动查出来。
  **它不知道 DSH 存在** —— 这是硬边界，也是 `skill-only/` 那条发行线的前提。
- **记忆层**：写在 CLI（`journal.py memory …`，要过来源分档、索引重建、`lint`），读在工具（`worklog_memory`，
  唯一**不离开会话、不靠 shell** 的读路）。**这条不对称是有意的**：判定只有一处定义。
  信箱也在这层：`send` 发信、`inbox` 取件、`sessions` 列**本工作区**的会话标题；主动送达要
  收件方先在**自己**的工作区 `inbox subscribe`（默认关，会在收件人不在场时花额度）。
- **插件层**另有：待收条数尾注入（只在变化时追加，空信箱零成本）、主动送达的提醒推送、技能注册、配置卡片。

## 二、装完你会得到什么

| 装法 | 得到 | 得不到 |
|---|---|---|
| **DSH 插件包**（本仓库） | 三个技能 + 记忆索引注入 + `worklog_memory` 工具（记忆读写 + 信箱收发 + 本工作区会话清单）+ 配置卡片 | —— |
| **普通 Agent Skill**（`skills/`） | 只要 `project-work-log`：完整的记录体系与 27 个命令 | 记忆注入、工具、配置卡片 |
| **纯文档变体**（`skill-only/`） | 同一套约定与模板，**没有脚本**（给跑不了 Python 的平台） | 机械门禁、分析命令 |

| 技能 | 默认 | 是什么 |
|---|---|---|
| `project-work-log` | 开 | 本仓库的主体：记录体系 + 工具箱 |
| `reliability-guidelines` | 开（可关） | 八条可靠性工作准则（事实优先 · 不清楚就问 · 假设要确认 · 能复用别新建 · 按既有约定 · 承认不知道 · 改动要验证 · 小步可回退），中英双语 |
| `client-require-whitelist` | **默认关** | 写 DSH 客户端半边时检查 `require(...)` 是否都落在宿主那 9 项浏览器模块表里 —— 表外的名字在浏览器里**解析不到而且不报错**。删掉 frontmatter 里 `disable-model-invocation: true` 那行即可让模型也能用 |

## 三、安装

**DSH**（本包声明了 `dsh.bundle`，装进 profile 后自动注册自带技能）：

```bash
dsh plugin --profile <profile> add dsh-lore                # 按包名装（推荐：装 registry 上的发布版）
dsh plugin --profile <profile> add dsh-lore@v0.9.0        # 固定到某个版本（tag 形态，`audit-versions` 会核对）
dsh plugin --profile <profile> add /绝对/路径/<checkout>   # 从本地装 —— 见下面那条警告
```

也可以让 agent 用 `plugin_manager` 工具装（支持绝对路径 / `file:` / 包名 / git / tarball）。

> ⚠ **本地目录路径装出来的是链接（link / junction），不是拷贝**：`dsh plugin` 把参数原样转发给 pnpm，
> **源目录一移动、一删除，插件就废了** —— 长期用请按包名或固定 tag 装。

> ⚠ **自带技能的包必须自己打开 `skill-filesystem`**：那一行关着时，技能注册表活着但技能到不了 `skill` 工具 ——
> 往 `~/.dsh/skills`、`.dsh/skills` 放多少份都没用。本包在 `cordis.patch.yml` 里按 id override 打开它。
> **技能查不到怎么排查**（有个默认关闭的诊断开关）：见 [`SETTINGS.md`](SETTINGS.md) §「已知配置键」的 `verbose` 与 `DSH_WORKLOG_TRACE`。

**pi**（只拿得到技能层）：

```bash
pi install git:github.com/IThinkItsaName/dsh-lore            # 全局
pi install git:github.com/IThinkItsaName/dsh-lore@v0.9.0     # 固定到 tag（推荐）
pi install -l git:github.com/IThinkItsaName/dsh-lore         # 只装到当前项目（写入 .pi/settings.json，可随仓库共享）
```

**手动（任意 harness）**：把 `skills/project-work-log` 放进它的搜索路径（目录结构遵循
[Agent Skills 规范](https://agentskills.io/specification)）—— dsh 用 `<DSH_HOME>/skills/`（未设时为 `~/.dsh`）
与项目级 `.dsh/skills/`；pi 用 `~/.pi/agent/skills/` 与 `.pi/skills/`。

> ⚠ 别和旧扩展 `pi-project-work-log` 同装，也别同时装 `skill-only/` 那一份：技能名相同，同时可见时会被遮蔽。

## 四、用法

代理按「要留记录 / 建工作日志 / 总结踩坑 / 整理台账 / 阶段性复盘 / 归档旧记录」这类意图自动加载本技能，
也可显式 `/skill:project-work-log`。脚本可独立使用（只依赖 Python 标准库）：

```bash
cd <你的项目根>   # 目录里应有 work_log/ 与 lessons/（SKILL.md 的「工作流 A」会教你建）

python <skill>/scripts/journal.py brief                       # 一屏掌握当前坐标（替代整读索引）
python <skill>/scripts/journal.py new --title "给登录加限流" --iter 42 --insert --stage "B. 迭代"
python <skill>/scripts/journal.py status --set "核对=抽样 30 条全部通过" --date
python <skill>/scripts/journal.py check --strict --lint       # 结构 + 内容，两道门禁一次跑完
```

**命令一览（27 个）**

| 分类 | 命令 |
|---|---|
| 少读 | `brief`（压缩快照）、`snapshot`（最近 N 篇入口）、`outline`（全部一行表）、`show`（单篇大纲）、`search` |
| 少写 | `new --insert`、`status`、`mode`、`config`、`todo`、`index sync`、`lesson add`、`append`（均支持 `--dry-run`） |
| 门禁 | `check`（结构）、`lint`（内容质量）—— 有 ERROR 时退出码 1 |
| 分析生成 | `stats`、`topics`、`digest`（交接摘要）、`retro`（复盘骨架）、`export`（JSON/CSV） |
| 容器维护 | `archive`（篇号区间归档 + 链接重写）、`split`（按年分卷）、`prune`（冷存候选，默认只报告） |
| **记忆（跨工作区）** | `memory publish\|collect\|add\|search\|index\|lint\|status`、`dream`、`inbox put\|list\|take\|sweep\|count`、`inbox subscribe\|unsubscribe\|status`（主动送达授权）、`promote suggest\|scaffold`（升格为技能） |

完整参数见 [`references/commands.md`](skills/project-work-log/references/commands.md)；记忆层布局与准入规则见
[`docs/memory-spec.md`](docs/memory-spec.md)。

**记忆层怎么用**

```bash
python <skill>/scripts/journal.py memory add --root <项目根> --source wl/0042 "当……先……再……"
python <skill>/scripts/journal.py memory index            # 不建索引就检索不到
python <skill>/scripts/journal.py memory search "样式"     # 子串匹配，不是语义检索
```

**准入靠来源分档，不靠重要性**：一条经验要能追溯到它出自哪篇记录或哪个工作区，否则不进记忆。`inbox` 只在
"这条消息对投递方以外的任何人都不该存在"时才用 —— 需检索或长期价值的内容应进记忆，**别为了传一次话去建一套邮政系统**。

## 五、配置

**配置只有一个事实源：宿主的设置通道**（profile patch 的 `cordis.patch.yml`，由插件页的配置卡片读写；没有
`configEditor` 的 headless 宿主退回到 `<DSH_HOME>/worklog/settings.json`）。**字段、默认值、哪些改动需要重启、
多 profile 的注意事项，全部在 [`SETTINGS.md`](SETTINGS.md)**。最小示例：

```yaml
- id: dsh-lore
  name: dsh-lore
  config:
    guidelinesLanguage: 'en'
```

> **新增字段时只挑一个家**：进 `Config` 标 `.volatile()`，同时把名字加进 `lib/client.js` 的 `FORM_FIELDS` ——
> 两边漂移会让卡片认领不到自己的 namespace、整页消失，**改完要重启 DSH**。

## 六、环境要求与自测

- **Python**（仅标准库）、**Node**（只有插件 harness 与 `skill-only` 构建需要）；建议把 `work_log/`、`lessons/` 纳入版本控制
- harness 认 `DSH_SRC_DIR`、`DSH_PROFILE_DIR` 两个环境变量，**缺省时相应检查自动跳过、不会误报失败**

```bash
python -B skills/project-work-log/scripts/_selftest.py  # 技能：临时工程跑通全部命令 + 断言
npm run test:plugin                                    # 16 支 harness
npm run audit                                          # 端到端审计：宿主会 import 什么、sha256 是否对得上
npm run test:skill-only                                # 纯文档变体没漂移
```

> `-B` 是**不要写 `.pyc`**：自测脚本住在技能包里，Python 默认会把 `__pycache__` 生成在包内，而副本里的
> `__pycache__` 会被判成漂移（它会随包发出去）—— 跑过自测就把下一道门禁弄红。`npm test` 与 CI 都带 `-B`。
> 写入受限的环境（沙箱只允许进程写自己创建过的目录）加 `--root <已存在的目录>` 指定夹具父目录。

## 七、支持矩阵（诚实标注验证情况）

| 维度 | 支持 | 验证情况 |
|---|---|---|
| **Python** | **3.9+** | 用了 PEP 585 注解（`list[str]`）与海象运算符；仅在 **3.12**（CI / Ubuntu）与 **3.14**（Windows 本机）实测 |
| 第三方依赖 / 外部程序 | **无**（纯标准库；git 可选） | 不需要 `pip install`；无 Python 时退化为纯规范，见 SKILL.md「没有 Python 怎么办」 |
| 操作系统 | Windows / macOS / Linux | 无平台相关 API；CI 在 Ubuntu、本机在 Windows 实测通过 |
| 字符编码 | UTF-8 文件 | 控制台编码无关（脚本自行把 stdout 设为 UTF-8）；非 UTF-8 不崩但标签认不出来 |
| **解析语言** | 中文默认 + **英文别名** | `日期/Date`、`结论/Conclusion`、`迭代/Iteration`、`验证/Verification`、`当前状态/Status`、`待办/TODO`、`文件索引/Index` 均可解析；要英文**写入**得改 `references/templates.md` 与模板字符串 |
| harness | 任何支持 Agent Skills 的；以及 **DeepSeek Harness 插件** | skill frontmatter 仅 `name` + `description`，且 name 与目录名一致 |
| DSH 版本 | 需要 `dsh-base` 已声明 `skill-filesystem` / `tool-skill` 行的版本（**0.1.7 起**） | 本机 **0.2.0-rc.2** 实测装载正常 |

## 八、文档地图与许可

**`docs/` 是设计权威**（改实现就要改对应规格），每份都在文档一致性门禁的审计清单里，映射表见
[`docs/README.md`](docs/README.md)。这套约定不是凭空设计的，而是对一套真实的长期项目记录做实测后总结的：
哪些做法有效、哪些会腐坏，见 [`references/analysis.md`](skills/project-work-log/references/analysis.md)。
**改这个包之前先读 [`RELEASING.md`](RELEASING.md)** —— 源与副本的方向不止一处，走错方向会静默删东西。

> **`peerDependencies` 的两条不是装饰，是"能不能加载"**：本包通常以 junction / symlink 装进 profile，
> 落在 DSH 的 linked root 里；宿主对链接目录内的 `import '@deepseek-ai/…'` **只有在该名字出现在
> `peerDependencies` 里时**才走拦截、解析到宿主自己那一份。后果不是"少一个字段"，是**条目 `inactive`、
> 插件整体消失**（技能与配置卡片一起）。

MIT，见 [LICENSE](LICENSE)。
