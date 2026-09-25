# worklog

> 给长期项目用的**工作记录体系**（Agent Skill，技能名 `project-work-log`）：过程记录 + 索引台账 + 经验手册，外加一套 20 个子命令的管理 / 分析 / 清理工具箱。

**不限编程**：软件、研究、写作、设计、运营、教学……任何跳会话或跨周持续投入的项目都能用。
术语可换（迭代字段接受 `迭代 / 变更集 / 批次 / 阶段 / 版本 / 里程碑`），验证口径也放宽到“命令 / 数据 / 引用 / 样本”。

同一个包可以两种方式装：作为 **DeepSeek Harness 插件包**（`dsh.bundle`），或作为普通 **Agent Skill**（[agentskills.io 规范](https://agentskills.io/specification)，pi、Claude Code 等通用）。

> **来源与免责声明**：本仓库的约定、文档与脚本整理自作者使用 **DeepSeek Flash 系列模型**处理内容时的常用操作，
> 并**完全由 DeepSeek Flash 系列模型整理生成**（未经人工逐条校验）。
> 使用时请自行甄别，**不保证效果、正确性与适用性**；建议先小范围试用，再按项目的实际情况调整。

## 它解决什么问题

长期项目里，真正难的不是写代码，而是三件事：

1. **下次接手时找不到上下文**——"当时为什么这么改？验证过没有？"
2. **经验留不下来**——踩过的坑换个人（或换一次会话）再踩一遍。
3. **台账会漂移**——状态、待办、索引越写越乱，最后没人信。

这套 skill 把它固化成**三层结构 + 一套约定 + 可机器校验的门禁**：

| 层 | 位置 | 职责 |
|---|---|---|
| 过程层 | `journal/NNNN-*.md` | 一篇 = 一个迭代：背景 → 事实 → 方案 → 执行 → 验证 → 遗留 |
| 索引层 | `journal/README.md` | 分阶段索引 + 同主题簇 + 滚动待办 + **唯一**当前状态块 |
| 经验层 | `lessons/*.md` | 可复用知识：症状 → 根因 → 做法 → 来源 |

配套脚本让代理**少读、少写、可校验**：不用整读几十 KB 的索引，改台账是外科式行级编辑（保留 CRLF），
结构问题（死链、断档、漏索引、来源悬空）和内容问题（占位符没清、结论没数字、"应该没问题"）都能自动查出来。

## 安装

### DeepSeek Harness（dsh）

本包声明了 `dsh.bundle`，是一个 **DSH 插件包**：装进某个 profile 后，它会把自带的
`project-work-log` 技能注册进该 profile 的技能目录，不需要复制文件、也不需要配置技能搜索路径。

```bash
# 从本地目录装进某个 profile（先改路径）
dsh plugin --profile desktop install /绝对/路径/worklog

# 或直接用 agent 的 plugin_manager 工具装（spec 支持绝对路径 / file: / 包名 / git / tarball）
```

本包的 `cordis.patch.yml` **只插一行**（它自己）。技能注册表 `skill` 本来就在 host 层活动着
（`dsh-base` 声明、`dsh-web-app` 保留），本插件把技能注册进它的 global 层，所以每个 agent 作用域都看得到。

**故意没有碰** `skill-filesystem` 和 `tool-skill`：`dsh-web-app` 明确把这两行关掉，理由是
「local discovery 归 preset 所有」——由 preset 把这两行挂进**该 preset 的层**，基础 host 行保持关闭。
从 bundle 层重新打开它们，等于给**每个 agent** 在 host 层装上本地技能发现和第二个 `skill` 工具，
这是全局构图改动，不该由一个技能包来做。本包也不需要它们：技能内容自带、`resourceBase` 自带，
不需要从磁盘发现任何东西。

| 依赖 | 谁提供 | 说明 |
|---|---|---|
| `skill` 注册表 | `dsh-base`（活动） | 本插件 `inject: ['skills']`，注册进它的 global 层 |
| 技能渲染 / `skill` 工具 | 你所在 preset 挂的 `tool-skill` | **本插件不提供**。若构图里没有任何技能消费端，注册了也没有渲染路径 |

| 配置项 | 默认 | 作用 |
|---|---|---|
| `skillDir` | `skills/project-work-log` | 技能 bundle 目录（相对本包根目录或绝对路径） |
| `skillFile` | `SKILL.md` | bundle 内的指令文件名 |
| `modelInvocable` | `true` | 是否允许模型侧目录 / `skill` 工具加载 |
| `userInvocable` | `true` | 是否允许人侧入口加载 |
| `verbose` | `false` | 挂载时打一行日志 |

> ⚠ **本插件故意不导出 `Config`**，所以上面的字段**没有 schema 校验**：值由插件自己做类型兜底
> （类型不对就用默认值），认不出的键会在日志里 warn 一行。
>
> 原因是硬约束：插件装进 profile 后，`import` 是按**它自己的真实路径**解析的，而
> `@deepseek-ai/schemastery` 只存在于应用的 `app.asar` 里 —— 树外插件**根本 import 不到它**。
> 一在模块顶层 import 它，整个模块就加载失败（实测：`ERR_MODULE_NOT_FOUND`，DSH 报 `failed to import`）。
> 与其带一份自己的 schemastery（版本要跟宿主对齐，很容易漂），不如不要这个可选能力，
> 换来**零依赖、放哪都能加载**。

### pi

```bash
# 全局
pi install git:github.com/IThinkItsaName/worklog

# 固定到 tag（推荐，避免上游变动）
pi install git:github.com/IThinkItsaName/worklog@v0.1.1

# 只装到当前项目（写入 .pi/settings.json，可随仓库共享给团队）
pi install -l git:github.com/IThinkItsaName/worklog
```

### 手动（任意 harness）

```bash
# 全局
cp -r skills/project-work-log ~/.pi/agent/skills/

# 项目级（项目受信任后生效）
mkdir -p <project>/.pi/skills && cp -r skills/project-work-log <project>/.pi/skills/
```

Claude Code 等其它 harness：把本仓库的 `skills/` 目录加入它的 skill 搜索路径即可（目录结构遵循 Agent Skills 标准）。

## 用法

代理在匹配到「开始新任务要留记录」「建工作日志」「总结踩坑/经验」「整理台账/当前状态」「阶段性复盘」「归档旧记录」
这类意图时会自动加载本 skill；也可以显式触发：

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
python <skill>/scripts/journal.py check --strict && python <skill>/scripts/journal.py lint --strict
```

## 目录结构

```
.
├── README.md
├── LICENSE
├── CHANGELOG.md
├── package.json                 # pi 包声明 + dsh.bundle（DSH 插件包声明）
├── cordis.patch.yml             # DSH 插件补丁：插入 dsh-worklog 与 skill-filesystem 两行
├── lib/
│   └── index.js                 # DSH 插件入口：把自带技能注册进 ctx.skills
└── skills/
    └── project-work-log/
        ├── SKILL.md             # 技能入口：三层模型、铁律、工作流、反模式
        ├── references/
        │   ├── conventions.md   # 目录 / 编号 / 生命周期 / 台账 / 经验层的硬约定
        │   ├── templates.md     # 记录、台账、归档、经验分册、复盘 全套模板
        │   ├── commands.md      # 20 个子命令的完整说明与组合套路
        │   └── analysis.md      # 设计依据：对一套真实记录的实测分析与改进对照
        └── scripts/
            ├── journal.py       # 工具箱（唯一入口，纯标准库）
            ├── _selftest.py     # 自测：临时工程跑通全部命令 + CRLF 保真
            └── _measure.py      # 对现成记录目录做一次性测量（analysis.md 的数字可复现）
```

> `lib/index.js` 在挂载时读取 `skills/project-work-log/SKILL.md` 的 YAML frontmatter，
> 然后用 `ctx.skills.registerProvider(...)` 注册一个**技能提供者**：`list()` 报目录、`get()` 每次
> **重新读文件**给正文——所以改 Markdown 不需要重启，也不需要重建。
> （对比：`ctx.skills.register()` 在挂载时就把正文快照下来，改文件要重启才生效。）
>
> 它**只 import `node:` 内置模块**，没有任何第三方依赖 ——
> 这是硬要求：插件装进 profile 后按自己的真实路径解析 import，而宿主包都在 `app.asar` 里，
> 树外插件解析不到（详见下方配置表的说明）。
> 技能本身仍是一份标准 Agent Skill 目录 bundle，`.pi/skills/` 之类的安装方式照旧可用。

## 命令一览

| 分类 | 命令 |
|---|---|
| 少读 | `brief`（压缩快照）、`show`（单篇大纲）、`search`（定向检索）、`outline`（全部一行表） |
| 少写 | `new --insert`、`status`、`todo`、`index sync`、`lesson add`、`append`（均支持 `--dry-run`） |
| 门禁 | `check`（结构）、`lint`（内容质量）——有 ERROR 时退出码 1 |
| 分析生成 | `stats`（语料统计）、`topics`（同主题簇建议）、`digest`（交接摘要）、`retro`（复盘骨架）、`export`（JSON/CSV） |

完整参数与套路见 [`skills/project-work-log/references/commands.md`](skills/project-work-log/references/commands.md)。

## 领域适配（不限于编程）

| 你要决定的 | 怎么做 |
|---|---|
| 迭代叫什么 | 入口字段默认 `迭代：N`；也认 `变更集 / 批次 / 阶段 / 版本 / 里程碑` |
| 怎么算“验证” | 小节标题含 `验证 / 复核 / 检查 / 评审 / 结果 / 证据 / 评估 / 确认` 任一即可 |
| 什么算“可核对” | 命令、数字、链接、引用、样本都算（**不**强制要求可执行命令） |
| 例子 | 研究：`批次：3` + `## 结果`（样本量、结论、反例）；写作：`版本：v2` + `## 评审`（编辑意见与处理）；软件：`变更集：154` + `## 验证`（命令与通过数） |

## 环境要求

- **Python**（仅标准库，无第三方依赖；开发与自测环境为 3.14）
- 脚本会读写 Markdown 文件；建议把 `journal/`、`lessons/` 纳入版本控制

## 自测

```bash
python skills/project-work-log/scripts/_selftest.py
```

会在临时目录里搭一个最小项目，跑通全部命令，并断言：CRLF 保真、**只改目标行**、来源校验会拒绝不存在的篇号、
`status --set` 的短名解析（`核对` → `核对 / 验证`）不新增字段、以及**文档模板落盘后能被自己的门禁接受**。

> 写入受限的环境（某些沙箱只允许进程写自己创建过的目录）用 `--root <已存在的目录>` 指定夹具父目录，
> 例如 `python scripts/_selftest.py --root ./.scratch`。

## 设计依据

不是凭空设计的约定，而是对一套真实的长期项目记录做实测后总结的：
哪些做法有效（编号即地址、三层不互相复制、证据优先）、哪些会腐坏（台账漂移、格式漂移、双份数字）。
详见 [`references/analysis.md`](skills/project-work-log/references/analysis.md)。

## 支持矩阵（诚实标注验证情况）

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
| 外部程序 | 无（git 可选） | — |

## 更新日志

版本变化见 [CHANGELOG.md](CHANGELOG.md)。

## 许可

MIT，见 [LICENSE](LICENSE)。
