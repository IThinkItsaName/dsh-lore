# dsh-lore

> **曾用名 `dsh-worklog`**（2026-09-30 改名；GitHub 仓库同时改为 `IThinkItsaName/dsh-lore`，旧链接自动重定向）。
> **环境变量仍是 `DSH_WORKLOG_*`**、技能名 `project-work-log`、工具名 `worklog_memory` 也都没变。

**一条工作记忆链路**，不是一个日志工具。三块能力，依赖**单向向下**：

| 层 | 干什么 | 依赖 |
|---|---|---|
| **技能层** | 把一次会话做过的事**留在项目里**：过程记录 + 索引台账 + 经验手册 + 27 个子命令的工具箱 | 只要 Python 标准库，**不需要 DSH** |
| **记忆层** | 把跨项目学到的东西**存在所有工作区之外**（记忆根可配置，默认 `~/dsh-lore-memory`）：来源分档、索引、收敛、升格、信箱 | 纯文件，不知道插件存在 |
| **插件层** | 在 DSH 上把记忆**送到模型眼前**（索引注入）、给模型读写记忆的工具、把技能注册进宿主、一张配置卡片 | DSH（`dsh.bundle`） |

**三层可以只用一层**：只装技能层，就是一套完整可校验的记录体系（`skill-only/` 那条线更极端 —— 连脚本都不要）。
**不限编程**：软件、研究、写作、设计、运营、教学都能用；术语可换（迭代字段认 `迭代 / 变更集 / 批次 / 阶段 / 版本 / 里程碑`），
验证口径也放宽到"命令 / 数据 / 引用 / 样本"。

> **来源与免责声明**：本仓库的约定、文档与脚本整理自作者使用 **DeepSeek Flash 系列模型**处理内容时的常用操作，
> 并**完全由 DeepSeek Flash 系列模型整理生成**（未经人工逐条校验）。使用时请自行甄别，**不保证效果、正确性与适用性**。

**版本变化见 [CHANGELOG.md](CHANGELOG.md)** —— 最近三版：`0.8.1` 记忆根设置在桌面 profile 上真的生效 ·
`0.8.0` 记忆根可配置、默认移出 `$DSH_HOME` · `0.7.0` 跨工作区消息「取件」。

---

## 一、三层的边界

**技能层**：过程层 `<容器>/NNNN-*.md`（一篇 = 一个迭代：背景 → 事实 → 方案 → 执行 → 验证 → 遗留）、
索引层 `<容器>/README.md`（分阶段索引 + 同主题簇 + 滚动待办 + **唯一**当前状态块）、
经验层 `<容器>/lessons/*.md`（症状 → 根因 → 做法 → 来源）；归档住 `<容器>/<阶段>/`，
容器名与经验目录名可用 `journal.py config` 改（旧布局 `journal/` 仍认）。
配套脚本让代理**少读、少写、可校验**：改台账是行级编辑（保留 CRLF），结构与内容问题（死链、断档、漏索引、
来源悬空、占位符、结论没数字）都能自动查出来。**它不知道 DSH 存在** —— 这是硬边界，也是 `skill-only/` 那条发行线的前提。

**记忆层**：写在 CLI（`journal.py memory …`，要过来源分档、索引重建、`lint`），读在工具（`worklog_memory`，
唯一**不离开会话、不靠 shell** 的读路）。**这条不对称是有意的**：判定只有一处定义（`journal.py`）。

**插件层**另有：待收条数尾注入（只在变化时追加，空信箱零成本）、技能注册（一个 bundle 一个 provider）、配置卡片。
注入为什么分两套接口、"空的东西不产生任何输出"这条规矩，见 [`docs/plugin-spec.md`](docs/plugin-spec.md) §四。

## 二、装完你会得到什么

| 装法 | 得到 | 得不到 |
|---|---|---|
| **DSH 插件包**（本仓库） | 三个技能 + 记忆索引注入 + `worklog_memory` 工具（记忆读写 + 信箱取件）+ 配置卡片 | —— |
| **普通 Agent Skill**（`skills/`） | 只要 `project-work-log`：完整的记录体系与 27 个命令 | 记忆注入、工具、配置卡片 |
| **纯文档变体**（`skill-only/`） | 同一套约定与模板，**没有脚本**（给跑不了 Python 的平台） | 机械门禁、分析命令 |

| 技能 | 默认 | 是什么 |
|---|---|---|
| `project-work-log` | 开 | 本仓库的主体：记录体系 + 工具箱 |
| `reliability-guidelines` | 开（可关） | 八条可靠性工作准则（事实优先 · 不清楚就问 · 假设要确认 · 能复用别新建 · 按既有约定 · 承认不知道 · 改动要验证 · 小步可回退），中英双语 |
| `client-require-whitelist` | **默认关** | 写 DSH 客户端半边时检查 `require(...)` 是否都落在宿主那 9 项浏览器模块表里 —— 表外的名字在浏览器里**解析不到而且不报错**。删掉 frontmatter 里 `disable-model-invocation: true` 那行即可让模型也能用 |

## 三、安装

### DeepSeek Harness（dsh）

本包声明了 `dsh.bundle`，装进某个 profile 后会把自带技能注册进去（不需要复制文件或配置技能搜索路径）：

```bash
dsh plugin --profile <profile> add dsh-lore                # 按包名装（推荐：装 registry 上的发布版）
dsh plugin --profile <profile> add dsh-lore@0.8.1          # 固定到某个版本
dsh plugin --profile <profile> add /绝对/路径/<checkout>   # 从本地装 —— 见下面那条警告
```

也可以让 agent 用 `plugin_manager` 工具装（支持绝对路径 / `file:` / 包名 / git / tarball）。

> ⚠ **本地目录路径装出来的是链接（link / junction），不是拷贝**：`dsh plugin` 把参数原样转发给 pnpm，**源目录一移动、一删除，插件就废了** —— 长期用请按包名或固定 tag 装。

**`cordis.patch.yml` 做两件事**（踩过坑才定下来）：① **打开 `skill-filesystem`**（按 id override 已有行）—— 这一行 `dsh-base` 声明、`dsh-web-app` 关掉，而**插件管理页不把它当可添加插件列出来**；关着时**技能注册表活着，但技能到不了 `skill` 工具**（往 `~/.dsh/skills`、`.dsh/skills` 放多少份都没用），**自带技能的包必须自己打开它**；② 插入本插件自己的行（技能目录等作为行配置）。`skill` 注册表来自 `dsh-base`；技能渲染与 `skill` 工具由你所在 preset 的 `tool-skill` 提供，**本插件不提供**（本插件 `inject: ['skills', 'tools', 'systemPrompt']`）。

**排查：技能查不到怎么办。** 内置一个**默认关闭**的诊断开关（注册表会把提供者的异常吞成宿主日志）：`DSH_WORKLOG_TRACE=<路径>` 或 `<包>/lib/.trace`，记 `apply` / 每次 `list()`（含 scope 与 cwd）/ 每次 `get()`。四种日志各有病根：没有 `apply` = 行没挂载（查补丁）；有 `apply` 没 `list` = `skill-filesystem` 被关；有 `list` 没 `get` = 层/作用域；`list error=…` = 异常原文。

### pi

```bash
pi install git:github.com/IThinkItsaName/dsh-lore            # 全局
pi install git:github.com/IThinkItsaName/dsh-lore@v0.8.1     # 固定到 tag（推荐，避免上游变动）
pi install -l git:github.com/IThinkItsaName/dsh-lore         # 只装到当前项目（写入 .pi/settings.json，可随仓库共享）
```

> ⚠ 别和旧的 `pi-project-work-log` 同装（那是改名前的另一份扩展，提供**同名技能**，二者留一个）。
> pi 侧只拿得到**技能层**：记忆索引注入、`worklog_memory` 工具与配置卡片都是 DSH 专属。

### 手动（任意 harness）

dsh 用不着这一节。要手动放：dsh 用 `<DSH_HOME>/skills/`（未设时为 `~/.dsh`）与项目级 `.dsh/skills/`；pi 用 `~/.pi/agent/skills/` 与项目级 `.pi/skills/`；其它 harness 把 `skills/` 加进它的搜索路径即可（目录结构遵循 [Agent Skills 规范](https://agentskills.io/specification)）：

```bash
cp -r skills/project-work-log "${DSH_HOME:-$HOME/.dsh}/skills/"   # dsh：全局（项目级换成 .dsh/skills/）
cp -r skills/project-work-log ~/.pi/agent/skills/                  # pi：全局（项目级换成 .pi/skills/）
```

> ⚠ **只把文件放进去，可能什么都不出现**（`skill-filesystem` 那一行关着时，`~/.dsh/skills` 与 `.dsh/skills` 里的文件一律不会被发现）。
> **也不要同时装 `skill-only/` 那一份**：技能名相同，同时可见时会有一个被遮蔽。

## 四、用法

代理按「要留记录 / 建工作日志 / 总结踩坑 / 整理台账 / 阶段性复盘 / 归档旧记录」这类意图自动加载本技能，也可显式 `/skill:project-work-log`。脚本可独立使用（只依赖 Python 标准库）：

```bash
cd <你的项目根>   # 目录里应有 journal/ 与 lessons/（SKILL.md 的「工作流 A」会教你建）

python <skill>/scripts/journal.py brief                       # 一屏掌握当前坐标（替代整读索引）
python <skill>/scripts/journal.py new --title "给登录加限流" --iter 42 --insert --stage "B. 迭代"
python <skill>/scripts/journal.py status --set "核对=抽样 30 条全部通过" --date
python <skill>/scripts/journal.py check --strict --lint       # 结构 + 内容，两道门禁一次跑完
```

### 命令一览（27 个）

| 分类 | 命令 |
|---|---|
| 少读 | `brief`（压缩快照）、`snapshot`（最近 N 篇入口）、`outline`（全部一行表）、`show`（单篇大纲）、`search` |
| 少写 | `new --insert`、`status`、`mode`、`config`、`todo`、`index sync`、`lesson add`、`append`（均支持 `--dry-run`） |
| 门禁 | `check`（结构）、`lint`（内容质量）—— 有 ERROR 时退出码 1 |
| 分析生成 | `stats`、`topics`、`digest`（交接摘要）、`retro`（复盘骨架）、`export`（JSON/CSV） |
| 容器维护 | `archive`（篇号区间归档 + 链接重写）、`split`（按年分卷）、`prune`（冷存候选，默认只报告） |
| **记忆（跨工作区）** | `memory publish\|collect\|add\|search\|index\|lint\|status`、`dream`、`inbox put\|list\|take\|sweep\|count`、`promote suggest\|scaffold`（升格为技能） |

完整参数见 [`references/commands.md`](skills/project-work-log/references/commands.md)；记忆层布局与准入规则见 [`docs/memory-spec.md`](docs/memory-spec.md)。

### 记忆层怎么用

```bash
python <skill>/scripts/journal.py memory add --root <项目根> --source wl/0042 "当……先……再……"
python <skill>/scripts/journal.py memory index      # 不建索引就检索不到
python <skill>/scripts/journal.py memory search "样式"   # 子串匹配，不是语义检索
```

**准入靠来源分档，不靠重要性**：一条经验要能追溯到它出自哪篇记录或哪个工作区，否则不进记忆。`inbox` 只在"这条消息对投递方以外的任何人都不该存在"时才用 —— 需检索或长期价值的内容应进记忆，**别为了传一次话去建一套邮政系统**（`docs/plugin-spec.md` §六）。

## 五、配置

**配置只有一个事实源：宿主的设置通道**（profile patch 的 `cordis.patch.yml`，由插件页的配置卡片读写；没有 `configEditor` 的 headless 宿主退回到 `<DSH_HOME>/worklog/settings.json`）。**字段、默认值、哪些改动需要重启、两个设置面的分界，全部在 [`SETTINGS.md`](SETTINGS.md)** —— 这里只给最小示例：

```yaml
- id: dsh-lore
  name: dsh-lore
  config:
    guidelinesLanguage: 'en'
```

> **多 profile 的机器注意**：`<DSH_HOME>/worklog/settings.json` 是**全机一份**，配置卡片是**每个 profile 一份**；两个 profile 都改 `memoryDir` 时以最后一次保存为准（细节见 `SETTINGS.md`）。**新增字段时只挑一个家**：进 `Config` 标 `.volatile()`，同时把名字加进 `lib/client.js` 的 `FORM_FIELDS` —— 两边漂移会让卡片认领不到自己的 namespace、整页消失，**改完要重启 DSH**。

## 六、目录结构

```
.
├── README.md / SETTINGS.md / CHANGELOG.md / RELEASING.md / PUBLISHING.md
├── package.json / cordis.patch.yml        # 三份声明 / DSH 补丁
├── lib/{index.js,client.js} / locale/     # 宿主半边（provider、注入、工具）/ 浏览器半边（卡片）/ 词典
├── docs/                                  # **设计权威**：plugin / worklog / memory / settings / goals spec
├── skills/project-work-log/               # 主技能：SKILL.md + references/ + scripts/{journal.py,_selftest.py,_measure.py}
├── skills/{reliability-guidelines,client-require-whitelist}/
├── skill-only/ → dist/skill-only/         # 第二条发行线：无脚本的纯文档变体（源 → 构建产物）
├── tests/                                 # 常驻回归防线：16 支 .mjs + reverse-verify.py
└── tools/build-skill-only.mjs             # 构建 / 查漂移 skill-only → dist
```

三条纪律：**`dist/` 是产物**（手改会被下次构建覆盖，`audit-paths.mjs` 与 `build-skill-only.mjs --check` 把关）；**`tests/` 与 `skills/` 都是镜像**（源在工作区的 `publish/worklog/tests/` 与 `.pi/skills/`，由 `_package.py` 同步进来，别手改）；**要改这个包先读 [`RELEASING.md`](RELEASING.md)** —— 三处源/副本方向不同，走错方向会**静默删东西**。

## 七、领域适配（不限于编程）

| 你要决定的 | 怎么做 |
|---|---|
| 迭代叫什么 | 入口字段默认 `迭代：N`；也认 `变更集 / 批次 / 阶段 / 版本 / 里程碑` |
| 怎么算"验证" | 小节标题含 `验证 / 复核 / 检查 / 评审 / 结果 / 证据 / 评估 / 确认` 任一即可；"可核对"= 命令、数字、链接、引用、样本（**不**强制可执行命令） |
| 例子 | 研究 `批次：3` + `## 结果`；写作 `版本：v2` + `## 评审`；软件 `变更集：154` + `## 验证`（命令与通过数） |

## 八、环境要求与自测

- **Python**（仅标准库）、**Node**（只有插件 harness 与 `skill-only` 构建需要）；建议把 `journal/`、`lessons/` 纳入版本控制

```bash
python -B skills/project-work-log/scripts/_selftest.py  # 技能：临时工程跑通全部命令 + 断言
npm run test:plugin                                   # 16 支 harness
npm run audit                                         # 端到端审计：宿主会 import 什么、sha256 是否对得上
npm run test:skill-only                               # 纯文档变体没漂移
```

> `-B` 是**不要写 `.pyc`**：自测脚本住在技能包里，Python 默认会把 `__pycache__` 生成在包内，
> 而 `_package.py --check` 把副本里的 `__pycache__` 判成漂移（它会随包发出去）—— 跑过自测就把
> 下一道门禁弄红。`npm test` 与 CI 都带 `-B`。

> 写入受限的环境（沙箱只允许进程写自己创建过的目录）用 `--root <已存在的目录>` 指定夹具父目录。两个可选环境变量让 harness 更完整，**缺省时相应检查自动跳过、不会误报失败**：`DSH_SRC_DIR`、`DSH_PROFILE_DIR`。

## 九、支持矩阵（诚实标注验证情况）

| 维度 | 支持 | 验证情况 |
|---|---|---|
| **Python** | **3.9+** | 用了 PEP 585 注解（`list[str]`）与海象运算符；仅在 **3.12**（CI / Ubuntu）与 **3.14**（Windows 本机）实测 |
| 第三方依赖 / 外部程序 | **无**（纯标准库；git 可选） | 不需要 `pip install`；无 Python / 不能执行命令时退化为纯规范，见 SKILL.md「没有 Python 怎么办」 |
| 操作系统 | Windows / macOS / Linux | 无平台相关 API；CI 在 Ubuntu、本机在 Windows 实测通过 |
| 字符编码 | UTF-8 文件 | 控制台编码无关（脚本自行把 stdout 设为 UTF-8）；非 UTF-8 不崩但标签认不出来 |
| **解析语言** | 中文默认 + **英文别名** | `日期/Date`、`结论/Conclusion`、`迭代/Iteration`、`验证/Verification`、`当前状态/Status`、`待办/TODO`、`文件索引/Index` 均可解析；要英文**写入**得改 `references/templates.md` 与 `journal.py` 的模板字符串 |
| harness | 任何支持 Agent Skills 的；以及 **DeepSeek Harness 插件** | skill frontmatter 仅 `name` + `description`，且 name 与目录名一致 |
| DSH 版本 | 需要 `dsh-base` 已声明 `skill-filesystem` / `tool-skill` 行的版本（**0.1.7 起**） | 本机 0.2.0-rc.1 实测装载正常 |

## 十、设计依据、文档地图与许可

不是凭空设计的约定，而是对一套真实的长期项目记录做实测后总结的：哪些做法有效（编号即地址、三层不互相复制、证据优先），哪些会腐坏（台账漂移、格式漂移、双份数字）。详见 [`references/analysis.md`](skills/project-work-log/references/analysis.md)。**`docs/` 是设计权威**（改实现就要改对应规格），每份都在文档一致性门禁的审计清单里；映射表与三条跨规格规矩见 [`docs/README.md`](docs/README.md)。版本变化见 [CHANGELOG.md](CHANGELOG.md)；MIT，见 [LICENSE](LICENSE)。

## 十一、依赖声明（`peerDependencies` 不是装饰，是**能不能加载**）

`package.json` 里的两条 peer 是**运行必需**：`@deepseek-ai/dsh-tools` 与 `@deepseek-ai/schemastery`。**为什么**：本包通常以 **junction / symlink** 装进 profile（开发时的常态），于是落在 DSH 的 **linked root** 里；宿主对链接目录内的 `import '@deepseek-ai/…'` **只有在该名字出现在 `peerDependencies` 里时**才走拦截、解析到宿主自己那一份，否则退回原生 Node 解析（实测 `MODULE_NOT_FOUND`）。后果不是"少一个字段"，是**条目 `inactive`、插件整体消失**（技能与配置卡片一起）；改完要**重启宿主**。
