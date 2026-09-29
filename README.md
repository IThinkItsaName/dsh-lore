# worklog

> **一条工作记忆链路**，不是一个日志工具。三块能力，依赖**单向向下**：
>
> | 层 | 干什么 | 依赖 |
> |---|---|---|
> | **技能层** | 把一次会话做过的事**留在项目里**：过程记录 + 索引台账 + 经验手册 + 27 个子命令的工具箱 | 只要 Python 标准库，**不需要 DSH** |
> | **记忆层** | 把跨项目学到的东西**存在所有工作区之外**（`$DSH_HOME/memory`）：来源分档、索引、收敛、升格、信箱 | 纯文件，不知道插件存在 |
> | **插件层** | 在 DSH 上把记忆**送到模型眼前**（索引注入）、给模型读写记忆的工具、把技能注册进宿主、一张配置卡片 | DSH（`dsh.bundle`） |
>
> **三层可以只用一层**：只装技能层，就是一套完整可校验的记录体系（`skill-only/` 那条线更极端 ——
> 连脚本都不要）；装上插件，才多出记忆与注入。

**不限编程**：软件、研究、写作、设计、运营、教学……任何跳会话或跨周持续投入的项目都能用。
术语可换（迭代字段接受 `迭代 / 变更集 / 批次 / 阶段 / 版本 / 里程碑`），验证口径也放宽到"命令 / 数据 / 引用 / 样本"。

> **来源与免责声明**：本仓库的约定、文档与脚本整理自作者使用 **DeepSeek Flash 系列模型**处理内容时的常用操作，
> 并**完全由 DeepSeek Flash 系列模型整理生成**（未经人工逐条校验）。
> 使用时请自行甄别，**不保证效果、正确性与适用性**；建议先小范围试用，再按项目的实际情况调整。

---

## 一、三块能力，各自的边界

### 技能层：记录体系本身

长期项目真正难的三件事：**下次接手找不到上下文**、**踩过的坑换个人再踩一遍**、**台账越写越乱最后没人信**。
这一层把它固化成**三层结构 + 一套约定 + 可机器校验的门禁**：

| 层 | 位置 | 职责 |
|---|---|---|
| 过程层 | `journal/NNNN-*.md` | 一篇 = 一个迭代：背景 → 事实 → 方案 → 执行 → 验证 → 遗留 |
| 索引层 | `journal/README.md` | 分阶段索引 + 同主题簇 + 滚动待办 + **唯一**当前状态块 |
| 经验层 | `lessons/*.md` | 可复用知识：症状 → 根因 → 做法 → 来源 |

配套脚本让代理**少读、少写、可校验**：不用整读几十 KB 的索引，改台账是外科式行级编辑（保留 CRLF），
结构问题（死链、断档、漏索引、来源悬空、目标表引用了不存在的篇号）和内容问题（占位符没清、
结论没数字、"应该没问题"）都能自动查出来。

**它不知道 DSH 存在**——这是硬边界，也是第二条发行线（`skill-only/`）能活的前提。

### 记忆层：跨工作区的那一半

一条在项目 A 里确证过的教训，写进记忆后**所有**工作区都能读到：

- **写在 CLI**（`journal.py memory …`）：写要经过来源分档、索引重建、`lint` —— 这些是技能层的能力，
  必须在没有 DSH 时也能做；
- **读在工具**（`worklog_memory`）：记忆在 `$DSH_HOME` 下，而代理自己的 `read`/`grep` 被
  `ctx.workspaceFiles` 限制在工作区内，碰不到它——工具体在宿主进程里跑，那是**唯一**的路。

**这条不对称是有意的**：模型能*读*记忆，但要*写*就得跑 CLI。判定只有一处定义（`journal.py`），
工具不自己发明一套。

### 插件层：把记忆送到模型眼前

装了插件才有：**索引注入**（稳定前缀，按字符预算）、**待收条数尾注入**（只在变化时追加，空信箱零成本）、
**`worklog_memory` 工具**、**技能注册**（一个 bundle 一个 provider）、**插件页上的一张配置卡片**。

注入为什么分两套接口，以及"空的东西不产生任何输出"这条规矩，见
[`docs/plugin-spec.md`](docs/plugin-spec.md) §四——那是设计权威，这里不复制第二遍。

## 二、装完你会得到什么

| 装法 | 得到 | 得不到 |
|---|---|---|
| **DSH 插件包**（本仓库） | 三个技能（见下）+ 记忆索引注入 + `worklog_memory` 工具 + 插件页配置卡片 | —— |
| **普通 Agent Skill**（`skills/`） | 只要 `project-work-log`：完整的记录体系与 27 个命令 | 记忆注入、工具、配置卡片 |
| **纯文档变体**（`skill-only/`） | 同一套约定与模板，**没有脚本**——给跑不了 Python 的平台 | 机械门禁（改成人手复核清单）、分析命令 |

三个技能：

| 技能 | 默认 | 是什么 |
|---|---|---|
| `project-work-log` | 开 | 本仓库的主体：记录体系 + 工具箱 |
| `reliability-guidelines` | 开（可关） | 八条可靠性工作准则（事实优先 · 不清楚就问 · 假设要确认 · 能复用别新建 · 按既有约定 · 承认不知道 · 改动要验证 · 小步可回退），中英双语 |
| `client-require-whitelist` | **默认关** | 写 DSH 客户端半边时检查 `require(...)` 是否都落在宿主那 9 项浏览器模块表里——表外的名字在浏览器里解析不到**而且不报错**。删掉 frontmatter 里那行 `disable-model-invocation: true` 即可让模型也能用；`node scripts/check-requires.mjs --彩蛋 <file>` 附一支叠词「诊断签」 |

## 三、安装

### DeepSeek Harness（dsh）

本包声明了 `dsh.bundle`，装进某个 profile 后会把自带技能注册进去，不需要复制文件、也不需要配置技能搜索路径。

> ⚠ **先说代价最大的那条**：**用本地目录路径装，装出来是一个链接（link / junction），不是拷贝。**
> `dsh plugin` 把参数**原样转发给 pnpm**，而 pnpm 对本地目录建链接 —— 于是
> **源目录一移动、一删除，插件就废了**（profile 里那条链接指向空气）。
> 实测：本仓库以 `link:` 装进本机 profile 后，`node_modules/dsh-worklog` 就是一个
> `<JUNCTION>`。**要长期用，就按包名/固定 tag 装**（下面第一、二条），或者把 checkout
> 放到一个不会挪窝的位置再接受这个代价。

```bash
# 1) 按包名装（推荐；装的是 registry 上的发布版，真文件）
dsh plugin --profile <profile> add dsh-worklog

# 2) 固定到某个版本
dsh plugin --profile <profile> add dsh-worklog@0.6.0

# 3) 从本地 checkout 装 —— 记住上面那条：这是链接安装
dsh plugin --profile <profile> add /绝对/路径/worklog
```

也可以让 agent 用 `plugin_manager` 工具装（spec 支持绝对路径 / `file:` / 包名 / git / tarball）。

**本包的 `cordis.patch.yml` 做两件事**（都是踩过坑才定下来的）：

1. **打开 `skill-filesystem`**（按 id override 已有行，不新增）。这一行 `dsh-base` 声明、`dsh-web-app` 关掉，
   而**插件管理页不把它当可添加插件列出来** —— 用户在 UI 里根本找不到这个开关。
   实测：这一行关着时，**技能注册表虽然活着，但技能到不了 `skill` 工具** —— 放多少份技能文件进
   `~/.dsh/skills`、`.dsh/skills` 都不会被发现，插件自己注册的技能也查不到。
   **自带技能的包必须自己把这一行打开。**
2. **插入本插件自己的行**，并把技能目录等信息作为行配置写进去。

**`tool-skill` 依然不碰**：它决定"技能能不能被模型加载"，属于消费端，由你所在的 preset 提供。
若构图里没有任何技能消费端，注册了也没有渲染路径。

| 依赖 | 谁提供 | 说明 |
|---|---|---|
| `skill` 注册表 | `dsh-base`（活动） | 本插件 `inject: ['skills', 'tools', 'systemPrompt']` |
| `skill-filesystem` | **本包打开** | 本地技能发现；关着则整条技能通道失效 |
| 技能渲染 / `skill` 工具 | 你所在 preset 挂的 `tool-skill` | **本插件不提供** |

**排查：技能查不到怎么办。** 插件内置一个**默认关闭**的诊断开关，用来回答"宿主到底有没有调我"
（注册表会把提供者的异常吞成一条宿主日志，树外插件读不到）：

```bash
# 方式一：环境变量指向一个日志文件
DSH_WORKLOG_TRACE=/tmp/worklog-trace.log

# 方式二：把目标路径写进 <包>/lib/.trace
echo /tmp/worklog-trace.log > <包>/lib/.trace
```

它会记录 `apply`（含 `ctx.skills` 是否可用）、每次 `list()`（含注册表传来的 **scope 与 cwd**，
这是识别调用者的关键）、每次 `get()`。典型判读：

| 日志 | 含义 |
|---|---|
| 完全没有 `apply` | 行没挂载 → 查 bundle 补丁是否生效 |
| 有 `apply` 没 `list` | 挂了但没人问目录 → 检查 `skill-filesystem` 是否被关掉 |
| 有 `list` 没 `get` | 目录里有、但查名字失败 → 层/作用域问题 |
| `list error=...` | 直接拿到异常原文 |

### pi

```bash
# 全局
pi install git:github.com/IThinkItsaName/dsh-worklog

# 固定到 tag（推荐，避免上游变动）
pi install git:github.com/IThinkItsaName/dsh-worklog@v0.6.0

# 只装到当前项目（写入 .pi/settings.json，可随仓库共享给团队）
pi install -l git:github.com/IThinkItsaName/dsh-worklog
```

### 手动（任意 harness）

```bash
# 全局
cp -r skills/project-work-log ~/.pi/agent/skills/

# 项目级（项目受信任后生效）
mkdir -p <project>/.pi/skills && cp -r skills/project-work-log <project>/.pi/skills/
```

Claude Code 等其它 harness：把 `skills/` 加入它的 skill 搜索路径即可（目录结构遵循
[Agent Skills 规范](https://agentskills.io/specification)）。
**不要同时装 `skill-only/` 那一份**：两者技能名相同，同时可见时会有一个被遮蔽，行为取决于平台。

## 四、用法

代理在匹配到「开始新任务要留记录」「建工作日志」「总结踩坑/经验」「整理台账/当前状态」「阶段性复盘」
「归档旧记录」这类意图时会自动加载本技能；也可以显式触发：

```
/skill:project-work-log
```

脚本可以独立使用（只依赖 Python 标准库）：

```bash
cd <你的项目根>   # 目录里应有 journal/ 与 lessons/（SKILL.md 的「工作流 A」会教你建）

# 一屏掌握当前坐标（替代整读索引）
python <skill>/scripts/journal.py brief

# 生成下一篇记录并自动补索引行
python <skill>/scripts/journal.py new --title "给登录加限流" --iter 42 --insert --stage "B. 迭代"
# 非编程项目完全一样用：标题写“第三轮用户访谈结论”，迭代字段也可写 批次/阶段/版本
python <skill>/scripts/journal.py new --title "第三轮用户访谈结论" --iter 3

# 收尾：更新状态 → 抽经验 → 过门禁
python <skill>/scripts/journal.py status --set "核对=抽样 30 条全部通过" --date
python <skill>/scripts/journal.py lesson add --volume 02-verification.md --source 42 --text "…"
python <skill>/scripts/journal.py check --strict --lint   # 结构 + 内容，两道门禁一次跑完
```

### 命令一览（27 个）

| 分类 | 命令 |
|---|---|
| 少读 | `brief`（压缩快照）、`snapshot`（最近 N 篇入口）、`outline`（全部一行表）、`show`（单篇大纲）、`search`（定向检索） |
| 少写 | `new --insert`、`status`、`mode`、`config`、`todo`、`index sync`、`lesson add`、`append`（均支持 `--dry-run`） |
| 门禁 | `check`（结构）、`lint`（内容质量）—— 有 ERROR 时退出码 1 |
| 分析生成 | `stats`、`topics`、`digest`（交接摘要）、`retro`（复盘骨架）、`export`（JSON/CSV） |
| 容器维护 | `archive`（篇号区间归档 + 链接重写）、`split`（按年分卷）、`prune`（冷存候选，默认只报告） |
| **记忆（跨工作区）** | `memory publish\|collect\|add\|search\|index\|lint\|status`、`dream`（把一个项目的记录收敛成摘要）、`inbox put\|list\|take\|sweep\|count`、`promote suggest\|scaffold`（升格为技能） |

完整参数与组合套路见 [`references/commands.md`](skills/project-work-log/references/commands.md)；
记忆层的目录布局与准入规则见 [`docs/memory-spec.md`](docs/memory-spec.md)。

### 记忆层怎么用

```bash
# 把一个项目的教训收进全局记忆（已在所有工作区之外）
python <skill>/scripts/journal.py memory add --root <项目根> --source wl/0042 "当……先……再……"

# 建索引 —— 不建索引就检索不到（子串匹配，不是语义检索）
python <skill>/scripts/journal.py memory index

# 别处查得到：CLI 是给人和脚本的，模型在会话里用 worklog_memory 工具
python <skill>/scripts/journal.py memory search "样式"
```

**准入靠来源分档，不靠重要性**：一条经验要能追溯到它出自哪篇记录或哪个工作区，否则不进记忆。
`inbox` 只在"这条消息对投递方以外的任何人都不该存在"时才用 —— 需要检索或长期价值的内容应该进记忆，
**不要为了传一次话去建一套邮政系统**（`docs/plugin-spec.md` §六）。

## 五、配置

**配置只有一个事实源：宿主的设置通道**（profile patch 的 `cordis.patch.yml`，由插件页的配置卡片读写；
没有 `configEditor` 的 headless 宿主退回到 `<DSH_HOME>/worklog/settings.json`）。

**字段、默认值、哪些改动需要重启、两个设置面的分界，全部在 [`SETTINGS.md`](SETTINGS.md)** ——
这里只给最小示例，不复制那张表。

改语言/关掉准则，可以在**本插件自己的那一页**上点（插件页 → `dsh-worklog` → 描述与行列表之间那张卡片），
也可以写进 profile 补丁（profile 层在所有 bundle 层之后应用，所以能盖住包内默认值）：

```yaml
- id: dsh-worklog
  name: dsh-worklog
  config:
    guidelinesLanguage: 'en'
```

> 本插件导出 `Config`（11 个字段全带 `.volatile()`），所以官方配置通道认识它们，写回前由宿主校验一次。
> **新增字段时只挑一个家**：进 `Config` 标 `.volatile()`，同时把名字加进客户端 `lib/client.js` 的
> `FORM_FIELDS` —— 两边漂移会让卡片**认领不到自己的 namespace**，整页静默消失。

## 六、目录结构

```
.
├── README.md                    # 本文件：这是什么、怎么装、怎么用
├── SETTINGS.md                  # 插件配置的权威：字段、默认值、要不要重启
├── CHANGELOG.md                 # 版本变化（只追加）
├── RELEASING.md                 # 发版清单：源/副本方向、检查点、打 tag
├── PUBLISHING.md                # 仓库怎么建（一次性）
├── package.json                 # npm / pi / dsh.bundle 三份声明
├── cordis.patch.yml             # DSH 补丁：打开 skill-filesystem + 插入本插件的行
├── lib/
│   ├── index.js                 # 宿主半边：技能 provider、记忆注入、worklog_memory 工具、只读状态端点
│   └── client.js                # 浏览器半边：插件页上那张配置卡片（三个页签）
├── locale/                      # 卡片词典（zh / zh-cn / en）
├── docs/                        # **设计权威**（给维护者）：见下
│   ├── README.md                # 文档地图与三条跨规格规矩
│   ├── plugin-spec.md           # 边界与权威：分几层、设置谁说了算、注入怎么进提示词
│   ├── worklog-spec.md          # 记录格式、精细度档位、check/lint 判定
│   ├── memory-spec.md           # 全局记忆：目录、来源分档、索引、dream、inbox、升格
│   ├── settings-spec.md         # 配置卡片：三页签、字段归属、写回通路
│   └── goals-spec.md            # 目标.md：长期目标 → 阶段的两层表
├── skills/
│   ├── project-work-log/        # 主技能
│   │   ├── SKILL.md             # 技能入口：三层模型、铁律、工作流、反模式
│   │   ├── references/          # conventions / templates / commands / memory / analysis
│   │   └── scripts/
│   │       ├── journal.py       # 工具箱（唯一入口，纯标准库）
│   │       ├── _selftest.py     # 自测：临时工程跑通全部命令 + CRLF 保真
│   │       └── _measure.py      # 对现成记录目录做一次性测量（analysis.md 的数字可复现）
│   ├── reliability-guidelines/  # 八条准则：SKILL.md（中文）+ en/SKILL.md
│   └── client-require-whitelist/ # 客户端 require 白名单检查（默认关）
├── skill-only/                  # **第二条发行线**：无脚本的纯文档变体（手写源）
├── dist/skill-only/             # 上面那份的构建产物（别手改，见 tools/）
├── tests/                       # 常驻回归防线：16 支 .mjs + reverse-verify.py
└── tools/
    └── build-skill-only.mjs     # 构建 / 查漂移 skill-only → dist
```

三条纪律：

- **`dist/` 是产物**，手改会被下次构建覆盖；一致性由 `tests/audit-paths.mjs` 与
  `build-skill-only.mjs --check` 把关。
- **`tests/` 是镜像**：harness 的源在工作区的 `logs/tests/`，由 `_package.py` 同步进来，**不要手改**。
- **技能源在一个位置**：`.pi/skills/` 是源，`skills/` 是镜像（同一道漂移门禁）。

## 七、领域适配（不限于编程）

| 你要决定的 | 怎么做 |
|---|---|
| 迭代叫什么 | 入口字段默认 `迭代：N`；也认 `变更集 / 批次 / 阶段 / 版本 / 里程碑` |
| 怎么算"验证" | 小节标题含 `验证 / 复核 / 检查 / 评审 / 结果 / 证据 / 评估 / 确认` 任一即可 |
| 什么算"可核对" | 命令、数字、链接、引用、样本都算（**不**强制要求可执行命令） |
| 例子 | 研究：`批次：3` + `## 结果`（样本量、结论、反例）；写作：`版本：v2` + `## 评审`（编辑意见与处理）；软件：`变更集：154` + `## 验证`（命令与通过数） |

## 八、环境要求与自测

- **Python**（仅标准库，无第三方依赖）
- **Node**（只有插件 harness 与 `skill-only` 构建需要，同样不装任何依赖）
- 脚本会读写 Markdown 文件；建议把 `journal/`、`lessons/` 纳入版本控制

```bash
# 技能：临时工程跑通全部命令 + 断言
python skills/project-work-log/scripts/_selftest.py

# 插件门禁：13 支 harness（注册表契约、补丁清单、版本/文档/路径/本地化一致性、客户端运行期、设置、记忆注入）
npm run test:plugin

# 端到端审计：宿主将会 import 什么、sha256 是否为当前工作树
npm run audit

# 纯文档变体没漂移
npm run test:skill-only
```

自测断言的内容包括：CRLF 保真、**只改目标行**、来源校验会拒绝不存在的篇号、`status --set` 的
短名解析（`核对` → `核对 / 验证`）不新增字段、以及**文档模板落盘后能被自己的门禁接受**。

> 写入受限的环境（某些沙箱只允许进程写自己创建过的目录）用 `--root <已存在的目录>` 指定夹具父目录，
> 例如 `python scripts/_selftest.py --root ./.scratch`。

两个可选环境变量让插件 harness 更完整，**缺省时相应检查自动跳过、不会误报失败**：

| 变量 | 作用 |
|---|---|
| `DSH_SRC_DIR` | 指向抽取出的 DSH 源码目录，用于核对补丁里的 id 是否真在 `dsh-base` 里声明 |
| `DSH_PROFILE_DIR` | 指向 dsh profile，用于核对链接安装是否指向本包、pnpm store 是否在位 |

## 九、支持矩阵（诚实标注验证情况）

| 维度 | 支持 | 验证情况 |
|---|---|---|
| **Python** | **3.9+** | 代码用了 PEP 585 注解（`list[str]`）与海象运算符；仅在 **3.12**（CI / Ubuntu）与 **3.14**（Windows 本机）实测 |
| 第三方依赖 | **无**（纯标准库） | 不需要 `pip install` |
| 操作系统 | Windows / macOS / Linux | 无平台相关 API；CI 在 Ubuntu、本机在 Windows 实测通过 |
| 字符编码 | UTF-8 文件 | 控制台编码无关（脚本自行把 stdout 设为 UTF-8）；非 UTF-8 文件不崩但标签会认不出来（按 `errors="replace"` 读），建议先转为 UTF-8 |
| **解析语言** | 中文默认 + **英文别名** | `日期/Date`、`结论/Conclusion`、`迭代/Iteration`、`验证/Verification`、`当前状态/Status`、`待办/TODO`、`文件索引/Index` 均可解析（英文 fixture 下 `check --strict` 与 `lint --strict` 均 0 error） |
| 写入语言 | 中文（模板默认） | 要英文写入，改 `references/templates.md` 与 `journal.py` 的模板字符串 |
| 命令执行 | 可选 | 无 Python / 不能执行命令时退化为纯规范，见 SKILL.md「没有 Python 怎么办」 |
| harness | 任何支持 Agent Skills 的；以及 **DeepSeek Harness 插件** | skill frontmatter 仅 `name` + `description`，且 name 与目录名一致；DSH 侧另由 `lib/index.js` 注册 |
| DSH 版本 | 需要 `dsh-base` 已声明 `skill-filesystem` / `tool-skill` 行的版本（**0.1.7 起**） | 本机 0.2.0-rc.1 实测装载正常 |
| 外部程序 | 无（git 可选） | — |

## 十、设计依据与文档地图

不是凭空设计的约定，而是对一套真实的长期项目记录做实测后总结的：哪些做法有效（编号即地址、
三层不互相复制、证据优先），哪些会腐坏（台账漂移、格式漂移、双份数字）。
详见 [`references/analysis.md`](skills/project-work-log/references/analysis.md)。

**`docs/` 是设计权威**（改实现就要改对应规格），每份都在文档一致性门禁的审计清单里；
映射表与三条跨规格规矩见 [`docs/README.md`](docs/README.md)。
**要改这个包**，先读 [`RELEASING.md`](RELEASING.md) 的发版清单（三处源/副本的固定方向 ——
走错方向会**静默删东西**）。

## 十一、依赖声明（`peerDependencies` 不是装饰，是**能不能加载**）

`package.json` 里的两条 peer 是**运行必需**：

```json
"peerDependencies": {
  "@deepseek-ai/dsh-tools": ">=0.1.7-alpha.1",
  "@deepseek-ai/schemastery": "^3.18.3"
}
```

**为什么**：本包通常以 **junction / symlink 链接**的方式装进 profile（开发时的常态），
于是它落在 DSH 的 **linked root** 里。宿主对链接目录内的 `import '@deepseek-ai/…'`
**只有在该名字出现在 `peerDependencies` 里时**才走拦截、把它解析到宿主自己那一份；
否则退回原生 Node 解析，而在链接包内部与 profile 目录下都解析不到（实测 `MODULE_NOT_FOUND`）。

后果不是"少一个字段"，是**条目 `inactive`、插件整体消失**（技能与配置卡片一起）。

> 改完这条要**重启宿主进程**才生效：插件的 `fiber.runtime`（含它拿到的 `Config`）在首次挂载时
> 就固定下来，Node 的 ESM 模块缓存也按 URL 复用；只禁用/启用那一行拿到的是同一个旧实例。

## 十二、更新日志与许可

版本变化见 [CHANGELOG.md](CHANGELOG.md)。MIT，见 [LICENSE](LICENSE)。
