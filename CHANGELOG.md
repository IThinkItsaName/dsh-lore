# 更新日志

本文件记录 **worklog**（技能名 `project-work-log`）的版本变化。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

> **规矩**：只追加，不改写历史条目。发版时把 `## [未发布]` 下的内容整理成 `## [x.y.z] - YYYY-MM-DD`，
> 顶部再留一个空的 `## [未发布]`；tag 一旦推送就**不要移动**（别人可能已经钉着它安装）。

## [未发布]

## [0.2.0] - 2026-09-25

本版把它变成**一个包、两种装法**：既是原来的 Agent Skill，也是一个 **DeepSeek Harness 插件包**。
同时修掉一轮实测出来的数据安全与幂等缺陷。

> **实装踩坑记录（供参考）**：0.2.0 的插件部分是**真装进 dsh profile 才调通的**，
> 期间暴露了 4 个只有实装才会发现的问题，都已修复：
> 1. **模块顶层 import `@deepseek-ai/schemastery` 导致加载失败**。插件按自己的真实路径解析 import，
>    而宿主包都在应用的 `app.asar` 里，树外插件**根本解析不到**。改为不导出 `Config`，
>    自己兜底读配置 —— 现在只 import `node:` 内置模块。
> 2. **`skillDir` 相对路径基准错**：`import.meta.url` 指向 `<包>/lib/`，当基准会去找
>    `<包>/lib/skills/...`。改为从包根解析。
> 3. **`ctx.skills.register()` 缺 `content`**：注册表会把注册对象**原样当作已加载的定义**交回，
>    再校验 `content` 必须是字符串 —— 注册成功、列表里有名字、**加载时才炸**。
>    且 `register` 会在挂载时快照正文，改 Markdown 要重启。改用 `registerProvider`：
>    `list()`/`get()` 每次重读文件，正文始终是活的。
> 4. **`skill-filesystem` 被关着导致整条技能通道失效**（最隐蔽的一条）。这一行 `dsh-base` 声明、
>    `dsh-web-app` 关掉，且**插件管理页不把它列为可添加插件**，用户在 UI 里找不到这个开关。
>    它关着的时候：注册表活着、插件正常挂载、`list()` 被正常调用并返回候选，
>    但技能**到不了 `skill` 工具**；往 `~/.dsh/skills`、`.dsh/skills` 放多少份文件也不被发现。
>    现在本包的补丁自行按 id override 打开这一行。

### 新增

- **DSH 插件包**：`package.json` 增加 `dsh.bundle.patch`，新增 `cordis.patch.yml` 与 `lib/index.js`。
  装进某个 dsh profile 后，插件会读取自带的 `skills/project-work-log/SKILL.md` frontmatter，
  用 `ctx.skills.registerProvider(...)` 注册一个技能提供者——**不用复制文件，也不用配技能搜索路径**。
  `list()`/`get()` 每次重读文件，所以改 Markdown 立刻生效，不需要重启或重建。
  - `resourceBase` 指向真实 bundle 目录，`references/*.md` 与 `scripts/journal.py` 的提示词路径因此可用。
  - 补丁同时按 id override **打开 `skill-filesystem`** —— 这一行默认关闭且 UI 不可见，
    关着则技能无法到达 `skill` 工具（详见上方踩坑记录第 4 条）。
  - 内置**默认关闭的诊断开关**（`DSH_WORKLOG_TRACE` 或 `<包>/lib/.trace`）：记录 `apply`/`list`/`get`，
    以及注册表传来的 **scope 与 cwd**。提供者的异常会被注册表吞成宿主日志，树外插件读不到，
    所以排障必须有这样一个开关（README「排查」一节有判读表）。
  - 可配置：`skillDir` / `skillFile` / `modelInvocable` / `userInvocable` / `verbose`。
  - 仓库名沿用 `worklog`；npm 包名改为 **`dsh-worklog`**（旧名 `pi-project-work-log` 从未发布到 npm）。
- `skills/project-work-log/SKILL.md` 的「环境边界」补全：明确真实 Python 下限、UTF-8 要求、
  以及中英双语标签的**完整**别名表（此前正文只举了 7 个词，漏了 `实测`/`审查` 等实际支持的别名）。
- `scripts/_measure.py` 增加 `status block chars`、`status blocks in index`、`history blocks in index`、
  `SUMMARY.md size chars`、`titles carrying an iteration number`——`references/analysis.md` 引用的数字
  现在**逐条**都能复现（此前 `_measure.py` 对其中几项只打印 True/False）。
- `scripts/_selftest.py` 新增 `--root DIR`（写入受限的沙箱里指定夹具父目录）与 `--keep`（保留夹具排查）。

### 修复

- **数据安全（严重）**：非 UTF-8 的台账会被静默毁掉。读取用 `errors="replace"`，写回时把替换出来的
  `U+FFFD` 固化成文件内容——一个 GBK 老仓库第一次 `status --set` 就会丢掉全部中文。
  现在写回前先严格解一遍，不是 UTF-8 就**拒绝写入**并说明原因（退出码 2），文件保持字节不变。
- **`status --roll` 把 LF 掺进 CRLF 台账**（违反"保留 CRLF"的承诺）。新骨架先按台账原本的换行风格改写。
- **`archive` / `split` 会弄死被移动记录自己的出站链接**：`rewrite_links` 在移动**之后**才改写，
  却按新目录解释链接，于是 `[b](0002-b.md)` 原样留着变成死链。现在先按**原目录**还原链接目标，
  再反算新相对路径；跨目录链接（如 `../docs/design.md`）也一并处理。
  `moves` 的键从"文件名"改为"旧绝对路径"，避免同名文件撞车。
- **`index compact` 不幂等**：第二次运行把已折叠的目录行当成数据行，`0005–0006（2 篇，已归档）`
  被改写成 `1 篇，已归档`。现在目标为目录的行直接跳过。折叠标签同时补齐 4 位零（与 `commands.md` 一致）。
- **`index sync` 会往无关表格里写行**：缺 `## 文件索引` 时回退到整篇搜索，记录行可能被插进
  `### 结算` 之类的表。现在缺小节就报错返回，`cmd_index` 也随之返回非零。
- **`lesson add` 静默吞掉 `--source`**：正文里只要出现任何 `wl/` 就不补引用，于是
  `--source 1` + 正文提到 `wl/9999` 会写成只引用 9999。现在只在**本篇来源**已出现时才跳过。
- **死链门禁漏掉带锚点的链接**：`x.md#part` 因为先判 `.endswith(".md")` 而被整条跳过。现在先剥锚点。
- **`lint` 把"正文是小节标题"误判成空小节**：`## 一、背景` 下接 `### 1.1 细节`（有内容）会报空小节。
- **`check` 与 `lint` 对验证小节的标题级别不一致**：`check` 只认 h2–h3，`lint` 认 h2–h4。
  现在统一为 h2–h4。
- **`STATUS_HEAD_RE` 过度匹配**：英文索引里出现 `## Status of lessons` 之类标题会被判成"两个状态块" ERROR。
  现在锚定整行标题（允许后面跟日期括号）。
- **半角括号的状态标题被叠加日期**：`## Status (2026-01-01)` 上跑 `--date` 会变成
  `## Status (2026-01-01)（2026-10-01）`。现在全角/半角括号都认。
- **`prune --zip` 输出目录不存在时崩栈**：现在先建目录。
- **`search --regex` 遇到非法正则崩栈**：现在给出干净报错并返回退出码 2。
- **`new --iter` 只接受整数**：`--iter -`（模板里的默认写法）与 `--iter v2` / `批次B` 都进不来，
  与"迭代字段接受任意标签"的约定矛盾。现在按字符串收。
- **`brief` 提示了不存在的参数**：输出里的 `status --show` / `todo --list` 两个子命令都不存在
  （照做会得到 `unrecognized arguments`）。现在提示 `status` / `todo`。
- **`brief --width 0` 会吃掉最后一个字符**并加省略号。小宽度直接原样输出。
- **`meta_of` 统计不准**：行数对每个以换行结尾的文件都多算一行；字节数因为 `read()` 归一了换行而低估 CRLF 文件。
  现在分别用 `splitlines()` 与磁盘上的真实字节数。
- `CITE_RE` 只认 1–4 位篇号（`wl/(\d{1,4})`），5 位篇号会被截断成前 4 位。现在接受任意位数。

### 变更

- 自测 **57 → 95** 项：新增短字段名解析、台账末行无换行、`index compact` 幂等、
  文档模板可被自身门禁接受、非 UTF-8 拒写、CRLF 不被掺 LF、归档后链接仍有效、
  纯中文标题的文件名等断言。
- `references/templates.md` 的台账模板：示例索引行不再指向一个不存在的文件（照抄会导致首次 `check`
  直接 ERROR 死链，与"初始化后 0 error"的承诺矛盾）。
- `references/conventions.md`：修正入口行写法——`迭代 / 变更集 / 批次 / 阶段：N` 这类**多标签并排**
  是解析不出来的，必须只写一个标签；补齐 `日期：`/验证小节在默认档位是 **WARN**、`--strict` 才是 ERROR。
- `references/analysis.md`：修正"日期/验证由 check 直接判 ERROR"、"验证必须有命令与输出"、
  入口行字段列表、"20 个子命令"与自身表格（21/23）等与实际行为不符的表述；自测数改为 90。
- `SKILL.md`：工作流 C 的校验步骤改为 `check --strict`，并说明默认档位只报 WARN；
  状态字段给出 7 个规范名并说明短名会被解析；工作流 A 补一句"先删模板里的示例索引行"。
- `README.md`：新增 dsh 安装章节（含需要一并打开的三个 profile 行）、DSH 配置表、插件布局说明；
  支持矩阵的 Python 下限改为 **3.9**（代码用了 PEP 585 注解与海象运算符），并说明非 UTF-8 文件的行为。
- `PUBLISHING.md`：补 dsh 侧的安装与自检步骤，自测数改为 90。

## [0.1.1] - 2026-09-14

> 说明：本次按 **patch** 号发布，但包含向后兼容的**新能力**（英文别名解析）；
> 所有原有中文用法完全不受影响。

### 新增

- **跨语言解析**：解析标签集中为常量并支持**英文别名**（写入仍默认中文）：
  `日期/Date`、`结论/Conclusion`、`触发/Trigger`、`范围/Scope`、`迭代/Iteration`、
  `验证/Verification`、`当前状态/Status`、`待办/TODO`、`文件索引/Index`——英文项目现在也能用 `check`/`lint`/`brief`
- SKILL.md 新增「**没有 Python 怎么办**（降级路径）」：把 Python 从硬依赖降为可选加速器
- README 新增「**支持矩阵**」：诚实标注验证范围（Python 3.12/3.14 实测、跨平台、UTF-8、双语解析）
- `_measure.py` 参数化：`[ROOT] [--journal NAME] [--lessons NAME]`（默认自动识别 `journal/` 或 `work-log/`）

### 变更

- 自测 53 → **57** 项（新增 4 项英文标签用例）
- `references/analysis.md` 的“验证小节”统计随词表放宽重测：88 → **95** / 106

## [0.1.0] - 2026-09-13

首次发布。

### 新增

- **三层记录体系**：`journal/`（过程记录）+ `journal/README.md`（索引台账）+ `lessons/`（经验手册）
- **工具箱 `journal.py`**：20 个子命令，纯 Python 标准库、零依赖、零配置
  - 少读：`brief` / `show` / `search` / `outline`
  - 少写：`new --insert` / `status` / `todo` / `index sync` / `lesson add` / `append`
  - 可校验：`check`（结构门禁）/ `lint`（内容质量门禁）
  - 分析生成：`stats` / `topics` / `digest` / `retro` / `export`
  - 整理清理：`archive` / `index compact` / `split` / `prune`
- **领域无关（不限于编程）**：迭代字段接受 `迭代 / 变更集 / 批次 / 阶段 / 版本 / 里程碑`；
  验证小节接受 `验证 / 复核 / 检查 / 评审 / 结果 / 证据 / 评估 / 确认`；
  "可核对的内容"包括命令 / 数据 / 引用 / 样本
- **整理能力只搬不删**：`archive` 移文件 + 重写全仓链接 + 死链自检；`index compact` 把已归档小节折叠成一行；
  `split --by-year` 按年分卷；`prune` 默认只报告，打包后才移出并留清单
- **自测** `scripts/_selftest.py`：53 项，覆盖 CRLF 保真、"只改目标行"、非编程场景与整理能力
- **文档**：`SKILL.md` + `references/`（`conventions` / `templates` / `commands` / `analysis`）
- **CI**：push / PR 触发，跑 53 项自测 + `SKILL.md` frontmatter + `package.json` 校验

### 说明

- 硬规则（目录与编号约定、"证据不删"、生命周期）见 `references/conventions.md`
- 设计依据（对一套真实长期项目记录的实测分析与改进对照）见 `references/analysis.md`
- 本技能整理自作者使用 **DeepSeek Flash 系列模型**处理内容时的常用操作，并**完全由该系列模型整理生成**；
  使用时请自行甄别，**不保证效果与适用性**

[未发布]: https://github.com/IThinkItsaName/worklog/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/IThinkItsaName/worklog/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/IThinkItsaName/worklog/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/IThinkItsaName/worklog/tree/v0.1.0
