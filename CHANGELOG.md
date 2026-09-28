# 更新日志

本文件记录 **worklog**（技能名 `project-work-log`）的版本变化。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

> **规矩**：只追加，不改写历史条目。发版时把 `## [未发布]` 下的内容整理成 `## [x.y.z] - YYYY-MM-DD`，
> 顶部再留一个空的 `## [未发布]`；tag 一旦推送就**不要移动**（别人可能已经钉着它安装）。

## [未发布]

### 修复（`peerDependencies`：不补这一条，下次加载插件会整体消失）

- `package.json` 补上 `@deepseek-ai/dsh-tools` 与 `@deepseek-ai/schemastery` 两条 peer 声明。
- **为什么是"必需"而不是"规范"**：本包以 junction / symlink 链接进 profile，落在 DSH 的 **linked root**
  里；宿主对链接目录内的 `import '@deepseek-ai/…'` **只在该名字出现在 `peerDependencies` 里时才拦截**
  到宿主自己那一份，否则退回原生解析。实测：这两个包在链接包内部与 profile 目录下都 `MODULE_NOT_FOUND`
  （`dsh-worklog` 自身能解析，所以问题只出在这两个名字上）。
- 后果：`lib/index.js` 现在 import 这两个包，没有 peer 声明 → 加载即 `MODULE_NOT_FOUND` →
  条目 `inactive`，**技能与设置页一起消失**。这不是理论风险：本机另一处探针插件日志里就有同一句
  `ERR_MODULE_NOT_FOUND Cannot find package '@deepseek-ai/schemastery'`。
- 依据：`@deepseek-ai/dsh-app-boot/README.zh.md`「链接目录」（peer 包名命中才用运行时包）、
  `PLUGIN-AUTHORING.md` 的 `peerDependencies` 条；对照同 profile 的 `dsh-ds-balance`（声明了同组 peer）。
- **要重启宿主进程才生效**：`fiber.runtime`（含插件拿到的 `Config`）在首次挂载时固定，Node 的 ESM
  缓存按 URL 复用模块实例——禁用/启用那一行拿到的还是同一个旧实例。

### 修复（链接解析：同一个事实在三处各错一次，其中一处是静默漏报）

- `LINK_RE` 曾排除空白，于是**含空格的链接目标整个匹配不上**——而 `archive --stage "A. 起步"`
  这类带空格的阶段目录，**工具自己就会写出**这种目标。三处后果：
  - `check` 的死链检查**看不见**它 → 链接断了也报 0 死链（静默漏报，最严重的一条）；
  - `archive` 的链接重写改不到它 → 搬完留下旧链接，而检查还说"死链 0"；
  - `index compact` 在它上面抛 `AttributeError` → **整条命令崩**（工作流 D 里紧接 `archive` 的那条）。
- 现在三种写法（裸 / `<尖括号>` / `%20` 转义）走**同一套**解析；`archive` 写出的含空格目标一律用
  尖括号形式；`index compact` 遇到解析不出的行**跳过而不是崩**（自测夹具里特意留了一行坏索引行）。
- 实测两个方向都错了：指向**真实存在**文件的 `](A.%20起步/真实存在.md)` 被报成死链（误报），
  而 `](<A. 起步/真实存在.md>)` 在检查与重写里都看不见（漏报）。
- 放宽匹配时踩到并写进注释的负向约束：**不跨行**——允许跨行会把下一行的 `)` 当成本行的收尾，
  凭空造出"死链"，宽松写法自己给自己制造误报。

### 修复（两处小缺陷，都由整体功能实跑抓到）

- `mode` 的提示行拿常量 `MODE_DEFAULT` 当"当前值"：台账是 `digest` 时，同一份输出上一行说 digest、
  下一行说"当前 full"。改成**生效档位**。
- `resolve_record_ref` 找不到容器时一律报"当前目录不是工作区"——调用方给的可能是**根目录**
  （`memory add` 就是），现在报出**用的是哪个根**，否则会去错的地方找问题。

### 新增（`check --lint`：两道门禁能一起跑，但**默认不合并**）

- `check` 与 `lint` 是两道门：前者管结构，后者管内容质量。它们此前**只能分两次跑**，
  于是"另一道门存在"这件事得靠人记得住——本项目的检查点就没记住，容器里攒了 7 条
  lint ERROR 无人看见（见下一条）。
- `check --lint` 把两道并进**同一次运行**：一份报告、一个退出码。
- **为什么不是默认合并**（这是量出来的，不是口味问题）：拿九个真实语料各跑一遍，
  `lint` 在既有项目上的判决严得多——`dsh_from_github` 从 7 条涨到 **94** 条、
  `3_param_block` 从 **0** 涨到 30 条、`2_multi_attention` 从 **0** 涨到 9 条。
  默认合并等于**替别人的仓库改判决**，而理由只是"我们的检查点想少跑一条命令"。
- **但绿灯必须说一声**：结构门禁通过且没加 `--lint` 时留一行提示（`--quiet` 下不打印）。
  人最容易在读到一个绿色 Summary 时以为"检查完了"——这正是那 7 条欠账的形成方式。
- 合并里有两处容易写错，都由自测钉住、并由变异驱动验证过：
  **同一件事两门都报时只留一条**（这要求两门的文案一字不差——实测过：文案差一句
  "先按 templates.md 初始化"，容器不存在时就会列出两条一模一样的错）；
  **渐进原则的降级下标要换算**（`legacy_rows` 存的是行号，合并后不换算，
  旧记录的降级会静默失效）。

### 文档（发版清单补上第二道容器门禁：`lint --strict`）

- `RELEASING.md` 的「本容器自己也要干净」原先只跑 `check --strict`。**结果是一个真实缺口**：
  写这份技能的那个工作区，自己的容器里攒了 **7 条** `lint` ERROR（6 条"结论没有可核对的信息"
  + 1 个空小节），**从没有人看见**——因为 `check` 与 `lint` 是两道门，前者只管结构。
- 现在两道一起跑：清单里是一条 `check --strict --lint`（见上一条——合并是**选项**，
  默认行为不变，所以别人不会因为这次改动变红）。代价照旧写明：**记录写得含糊会让发版变红**。
  "结论：已完成"这类句子本来就该在发版前被拦住，而不是靠人碰巧去跑一次 lint。

### 测试（把技能文档拉进门禁：它们此前不在任何一份清单里）

- `tests/audit-doc-consistency.mjs` 原先只审计 `docs/` + 三份根文档。技能层的
  `SKILL.md` 与 `references/` 下的五份——满是路径与命令示例、最容易被改动带着走——
  **不在任何门禁里**。这与 `docs/` 当初被落下的形状完全一样，只是换了一层。
- 两套语料现在**按各自的权威**审：插件文档对插件（入口读的环境变量、认的配置键），
  技能文档对它描述的那个 CLI。把技能文档并进前者的文本里不会更强，只会更弱——
  一个名字出现在五份满是示例的文档里任何一处，都算"有文档"。
- 新增三项检查，**每一项都先量过误报率再留下**（当日全部 0 误报）：
  - **文档点名的子命令必须真实存在**：读 `journal.py <命令>` 这种写法（21/21 命中），
    防的是改名 —— 命令改了、文档没跟上；
  - **反向：CLI 的 21 个顶层命令必须在 `references/commands.md` 里以 `` `命令` `` 出现**，
    防的是新增命令忘了写文档（这个方向才是真正会漂的）；
  - **技能文档之间的互链必须解析得到**：只认兄弟文档名，模板占位符（`NNN-slug.md`、
    `0001-示例.md`、`lessons/README.md`）不参与，所以今天唯一一条不解析的示例链接不会误报，
    而某份文档改名后其它文档没跟上会红。
- **刻意不做**：检查文档里提到的 `--flag`。今天就有 3 条误报——argparse 自带的 `--help`、
  `_selftest.py` 的 `--root`、示例里用户自己脚本的 `--variant`；仅凭一个名字判不出它属于哪个程序。
  "宁可漏报也不要吵"是本仓库的门禁规矩。
- 修掉新检查自己引入的一个缺陷：它们直接读文档，于是**文档被改名时先报一条 FAIL，
  再用 ENOENT 把整个 harness 崩掉**，后面三段根本不跑——退出码同样是 1，从 CI 上看不出区别，
  但审计面已经静默缩小了（正是这份文件存在的理由）。改成安全读取：缺失只报、不崩。
  重跑变异验证，改名一份 `references/` 文档现在如实红 3 条（存在性 + 两处互链）。

## [0.5.0] - 2026-09-28

### 新增（全局记忆：一个工作区学到的东西，别的能用上）

这是这一版最实质的东西，也是**记录体系从"单个项目"变成"跨项目"**的那一步。
规格在 [`docs/memory-spec.md`](docs/memory-spec.md)。

- **记忆放在所有工作区之外**：`$DSH_HOME/memory/`（`DSH_WORKLOG_MEMORY` 可整条路径覆盖）。
  **为什么不在某个工作区里**：它要服务的是"另一个工作区"，放在任何一个里面都会让那个
  工作区变成特权方，也让别的都要读它 —— 而 `read`/`grep` 本来就被限制在各自工作区内。
- **准入靠来源分档，不靠"看起来重要吗"**：

  | 来源 | 准入 | 进索引 |
  |---|---|---|
  | `wl/NNNN` | 允许 | 是（本工作区能核到该记录真实存在） |
  | `manual:tested` | 允许 | 是（**必须写清怎么验的**：命令 / 数字 / 结果） |
  | `manual:read` | 允许 | 是 |
  | `manual:inferred` | 允许 | **否**，且**强制标注「未经证实」** |

  **为什么留 `inferred` 一档而不是堵死**：堵死的结果不是"没有推断"，而是推断被
  **伪装成"读过"**。留一档、让它可见、且不进索引，比假装它不存在安全。
- **七个记忆子动作**：`memory publish | collect | add | search | index | lint | status`。
  `collect` 靠 `.state.json` 里的清单摘要做到**幂等**；`index` 是生成物，**`collect` 不代劳**
  （一个命令只做一件事），跑完会提示。
- **`dream`：把记录收敛成摘要，且回指机械可校验**。脚本做机械的一半（挑未收敛的记录、
  按主题分组、发骨架），模型做归纳的一半。`--accept` **先校验再写回**，`--check` 以后复查。
  回指引用的**就是既有的死链检查器** —— 所以"摘要能不能下钻到记录"与"文档链接有没有断"
  用的是同一把尺。**删掉被引记录，`--check` 会红。**
- **`inbox`：跨工作区传一条消息**：`put | list | take | sweep | count`，原子写
  （先临时文件再 rename）、有单条/总量/条数上限、默认 30 天过期清扫。
  **`count` 只打印一个整数** —— 它是给插件按行取的契约。
- **`promote suggest`：够格升格为技能的候选**。只报候选，**不自动打包**：
  升格是人的动作，且必须同时满足「是一套过程 + 已真实执行过 + 有重复需求」，
  **并且要交一个能变红能变绿的最简自测**。
- **`memory publish` 默认 `upload: false`**：要显式 `--upload` 才允许外流。
  「只看不给」是合法且常见的状态。
- 新增 [`references/memory.md`](skills/project-work-log/references/memory.md)；
  `commands.md` 补四个命令族的真实调用与输出；`conventions.md` 补「经验层之外：全局记忆」。

### 新增（记忆进提示词：两套接口，按易变性分工）

- **全局记忆索引**经 `ctx.systemPrompt.section()` 注入 —— 它是**稳定**文本，进可缓存前缀，
  所以按**字符预算**限制（软 800；超预算**丢弃而不是截断**——截断会把子集伪装成全集）。
- **待收消息条数**经 `ctx.systemPrompt.context()` 注入 —— 它是**可变**的，走尾注入，
  **只在内容变化时**追加，所以**空信箱零成本**。
- 两条规矩写进代码：**空就是空**（根不存在 / 索引不存在 / 索引只有标题，三种都注入空串；
  一条"这里是空的"会被每个请求永远付费），以及**正文永不进注入**（只放 id 与一句话，
  要正文就调工具）。
- 工具面 `worklog_memory`（`defineTool`）：`status | search | get | list`。
  **为什么记忆必须有工具**：代理自己的 `read`/`grep` 被限制在工作区内，碰不到
  `$DSH_HOME`；工具体跑在宿主进程里，这是**唯一**的路。
- **一个已知限制，写在规格里而不是藏着**：索引按设计应当与该工作区的 `applies-to` 取交集，
  但**装配期拿不到工作区根**（实测 `process.cwd()` 是 profile 目录，
  `sandboxPolicy.resolve({})` 无会话时回同一个兜底根），所以目前**注入全集**。
  索引本身按设计极小，全集可接受；要真过滤得先证明装配上下文里能拿到工作区。

### 新增（设置页：三个页签，且按页说明重启）

- 页签从两个变三个：**技能 / 记忆 / 高级**。
- **「改完要不要重启」原先写错了一半**：节点半边每次用时都重读设置文件，所以
  `技能` / `高级` 两页需要重启，而记忆的**另外两项即时生效**——只有总开关需要重启
  （它决定提示段与工具**是否注册**）。现在按页说明，而不是一句一刀切。
- 记忆页带一块**只读状态**（已登记工作区数 / 信箱条数 / 索引字数），并写明
  **上传许可在各工作区自己的 `发布.md` 里**。**这句话比再加一个开关重要**：
  没有它，读者会在这一页找一个**故意没做**的开关——上传许可是**每工作区**的事实，
  而这一页是全局的。
- 记忆根不存在时显示「尚未读取」而不是 `0`：**"0 个工作区"和"没读"是两回事**，
  而只有一个是真的。

### 变更（插件按宿主标准重建：`Config` 与 `defineTool`）

- **导出 `Config`**，11 个字段**全部 `.volatile()`**。这是官方"改配置不重启"那条路的机制。
  **为什么现在才能做**：早先本包写的是"树外插件导不出 `Config`"——那个结论**测错了对象**
  （把一个目录手拷进 profile 不等于把它装进 profile，所以没人给它供给包）。
  依据见 `dsh-ref/PLUGIN-AUTHORING.md` §4.3 与 `dsh-app-boot` 的两锚点解析。
- **工具面改用 `defineTool`**（`@deepseek-ai/dsh-tools`），`inject` 补 `tools`。
- **`.volatile()` 字段交给 `apply()` 的是引用，不是值**，所以每次读都经
  `plainConfigValue()` 解包 —— 把引用当字符串读**不抛错，只会静默出错**。
- **`Config` 不替代设置文件**：补丁写死了装载期那几个键、设置页写的是 JSON 文件，
  所以 `mergeSettings()` 保留两层并让**文件赢**——否则设置页改什么都无效。

### 变更（记录体系：目标文件、项目配置）

- **`<容器>/目标.md`（可选）**：长期目标 → 阶段的两层表，规格见
  [`docs/goals-spec.md`](docs/goals-spec.md)。缺它是正常的，不是错误。
- **`<容器>/.config.json`**：项目级偏好（`mode` / `container` / `lessons`），
  `journal.py` 每次执行时读，**改完立即生效**，不需要重启任何东西。

### 修正（本轮抓出的缺陷与错误论断）

- **设置页的设计令牌写错过**（`--dsw-text-secondary` 等四个名字不存在）。`var()` 名字不存在时
  **静默回落到 fallback**，页面照样渲染而主题已经失效。已修，并加
  `tests/audit-client-tokens.mjs` 对着权威词表（206 个）审计。
- **设置页有一处从不折叠的折叠区**：`DisclosureRow` 渲染时没把内容作为 children 传下去，
  所以它永远展开。已修。
- **测试套件读了开发者自己的设置文件**：正常使用就会让套件变红。已改为
  `_pkg.mjs` 把设置文件与记忆根都指向隔离路径。
- **两条"永远无法失败"的断言**：一条数渲染文本里的 `（默认）`，而测试运行时只展开顶层组件，
  所以恒为 0；另一条依赖英文文案碰巧包含某个词。都已改为断言**词典文案本身**
  或元素属性。
- **撤回两条我推断而非实测的论断**（写进 `docs/settings-spec.md`）：
  「树外插件导不出 `Config`」与一处关于 schema 的说明。**推断写进文档会被后来的读者当成事实。**
- **`locale/` 子路径不在 `exports` 里**导致语言包静默回落英文 —— 已修，并加
  `tests/audit-locale.mjs`。

### 内部（测试、文档与纪律）

- **新增 6 个 harness**（共 13 个）：`audit-locale`、`audit-client-tokens`、
  `audit-client-runtime`、`audit-settings`、`audit-doc-consistency`、`audit-memory-injection`。
- **`tests/reverse-verify.py`**：57 条变异，逐条破坏源码再断言"具名断言会变红"。
  **一个没见它红过的断言不算数** —— 这个脚本就是为此存在的，它当场抓出过两条我自己写的
  弱断言（一条幂等性断言被无关句子满足；一条测试根本没走到清单那条代码路径）。
- **`_selftest.py`：308 → 464 条断言**（新增 `memory_phase`）。
- **文档审计从 1 份扩到 6 份**：原先只有 `docs/worklog-spec.md` 受门禁，另外几份设计规格
  **不受任何约束**——而"规格说 A、实现是 B"这种事，本仓库已经靠人读发现过两次。
  现在 `docs/` 全部 + 三份根文档都在清单里，并检查**列出的文档必须存在**。
- **`docs/plugin-spec.md`（新）**：管边界与权威（四层与依赖方向、记忆为什么读写在两处、
  `Config` 与 `settings.json` 谁说了算、注入的两套接口）。
- **`docs/README.md`（新）**：设计文档地图 —— 哪份规格管什么、各守住哪条不变量。
- **新增纪律：空承诺是缺陷，不是待办。** 设置页上任何能点但无效的控件，要么实现、
  要么撤掉、要么显式标注「尚未实现」。这一版的记忆注入就是为了兑现两个这样的开关。

## [0.4.0] - 2026-09-26

> **从 0.3.0 直接看这一版即可**：`0.3.1` 从未单独发布（见该条目的说明）。

### 新增（项目配置文件）

- **`<容器>/.config.json`**：项目级偏好，`journal.py` 每次执行时读，**改完立即生效**。

  | 字段 | 默认 | 说明 |
  |---|---|---|
  | `mode` | `full` | 新项目的精细度默认档 |
  | `container` | `work_log` | 容器目录名 |
  | `lessons` | `lessons` | 经验目录名 |
  | `legacy` | 空 | 旧记录清单（同 `LEGACY.md`） |
  | `snapshotEntries` | `12` | 摘要默认篇数 |

  优先级：**命令行 > `.config.json` > 内置默认**。

  > **`container` / `lessons` 是例外**：它们命名配置文件自己所住的目录，不可能靠读文件
  > 得知自己在哪。所以容器仍**只按目录发现**；配置里这两个字段与实际不符时**报出来但不改
  > 生效值**，也不失败。它们的正确含义是「**新项目该叫什么**」。

- **`config` 子命令**：显示每个字段的**生效值**以及**它来自哪**（`命令行` / `.config.json`
  / `内置默认`）—— 在此之前用户无法知道一个值为什么是这个值。
  `--write` 生成、`--set key=value` 改一项、`--force` 才覆盖已有文件。

### 新增（插件设置页）

- **插件设置页**，与 `dsh-status-rotator` 同一栏，导航名「工作记录」。可改
  `guidelinesEnabled` / `guidelinesLanguage` / `verbose` / `skillDir` / `guidelinesDir`，
  以及三个**新项目默认值**（`container` / `lessons` / `mode`）。

  - 设置文件在 **`<DSH_HOME>/worklog/settings.json`**（`DSH_WORKLOG_SETTINGS` 可整路径覆盖）。
    不放在包旁边，是因为装进 profile 的是指向 git 工作树的 junction（写进去会弄脏工作树），
    而重装会替换那个目录 —— 恰恰最不该丢设置的时候。
  - 优先级 **设置文件 > row config > 内置默认**。这不是口味问题：bundle 补丁里写死了四个
    准则相关的键，如果 row 赢，**设置页改什么都无效**。
  - **不用手搓 UI**：表单控件取自 `@deepseek-ai/dsh-client-ui-primitives`
    （`Switch` / `Input` / `SegmentedControl` / `DisclosureRow`…），只用 `--dsw-*` 令牌着色。
    所以这个半边只有 **485 行**，而同类插件的客户端半边是 259 KB —— 那个自带了整套 CSS。
  - **无构建步骤**：`lib/client.js` 是手写的普通 JS，包装与 `require`（只有 `react` 与
    `dsh-client-ui-primitives`，都在宿主固定的 9 项 baseline 里）都手写，不用 JSX。
  - **三个项目级键不归插件管**：插件只**存**它们，**不读**它们。界面把它们放在
    「新项目默认值（插件不读）」下并注明写的是项目自己的 `.config.json`、由 `journal.py` 读。

### 变更（仓库改名）

- **仓库由 `worklog` 改名为 `dsh-worklog`**，与 npm 包名一致。文档里的 13 处引用
  （`README.md` / `PUBLISHING.md` / `CHANGELOG.md` 的链接表）与两个本地 remote 已同步。
  > GitHub 会对旧名做重定向，所以漏改**不会报错** —— 只是链接与安装命令里留着旧名。
  > 正因为静默，`tests/audit-versions.mjs` 现在断言**所有仓库引用彼此一致**
  > （可选地由 `DSH_WORKLOG_SLUG` 钉住期望值），半途而废的改名会被抓出来。
  >
  > 这条检查**不读 git remote**：读 remote 要捕获 git 输出，而本沙箱禁止程序开管道，
  > 所以进程内调不到 `git config`。改为让文件互相比对 —— 仍能抓住真正会出事的
  > "改了一半"，只是不能自动得知远端真名。

### 修复（插件页显示的文字不跟随语言设置）


- **插件管理页里的标题与描述现在跟随 DSH 的语言设置。** 此前无论切到哪种语言，
  那一行永远是英文的 `package.json` 顶层 `description`。原因不是"没做本地化"，而是两处
  各自都会**静默失败**的配置：

  1. **`package.json` 顶层 `meta` 根本不被插件管理器读取。** 它只取
     `name` / `version` / `description`，再拼上 `readPluginMeta()` 的结果。所以之前写在
     顶层 `meta` 里的中文从未显示过。
  2. **`exports` 没放行 `locale` 子路径。** DSH 用 Node 的模块解析器读
     `<包名>/locale/<语言>.json`，而我们的 `exports` 只有 `.` / `./cordis.patch.yml` /
     `./package.json` —— 解析抛 `ERR_PACKAGE_PATH_NOT_EXPORTED`，调用方把它当成"没有语言文件"，
     **不报错、不提示**，直接退回英文。

  现在：`exports` 新增 `"./locale/*"`，`files` 新增 `"locale"`（否则 npm 发布时整个目录
  不会进包，别人装上仍然只有英文），并新增 `locale/{en,zh-cn,zh}.json`
  （`{ meta: { title, description } }`）。

  > `en.json` 是**锚点**：它用来定位目录，缺了它**所有**其它语言文件都会被忽略，
  > 不只是英文失效。`zh-cn` 与 `zh` 两个 id 都放了，因为 DSH 文档里的 id 形如 `en`
  > （小写、短），而 `zh` 与 `zh-cn` 都是合法 BCP-47、都会被收进语言表 —— 命中哪个都行。

- 新增 `tests/audit-locale.mjs`：钉住 `exports` 子路径、`files` 覆盖、`en.json` 锚点、
  语言 id 合法且不重复、每个文件的结构，并**复现 DSH 的 `readPluginMeta`** 确认它真能拿到
  多语言映射而不是裸字符串。三种静默失败都已验证会被抓到（去掉 `exports`、去掉 `files`、
  删掉 `en.json`）。

## [0.3.1] - 2026-09-26

> **为什么是 0.3.1 而不是 0.3.0**：`v0.3.0` 这个 tag 先打了出去，但它指向的
> `package.json` 里还写着 `0.2.0` —— 包清单与 tag 不一致。按本文件顶部"tag 一旦推送
> 就不要移动"的规矩，tag 保持不动，改用 0.3.1 承载这批内容。
> 0.3.0 与 0.3.1 之间没有代码差异。
>
> ⚠ **0.3.1 没有单独发布过**：它的内容与 `v0.3.0` 的 tag 之间只差版本号本身，
> 随后插件继续演进（0.4.0 补上了这一版真正缺的那一块 —— 插件页显示文字跟随语言）。
> 从 0.3.0 直接升到 0.4.0 的读者，两版内容都在 0.4.0 里。

### 修复（发布面的版本一致性）

- **`package.json` 的 `version` 与 tag 对齐**（`0.2.0` → `0.3.1`）。这两处此前长期
  不一致：`v0.1.1` 的包里写着 `0.1.0`，`v0.3.0` 的包里写着 `0.2.0`。
  根因是**流程缺了一步** —— `PUBLISHING.md` 的发布步骤写了"整理 CHANGELOG"，
  **没写"提升版本号"**。已补进流程，并加了一条静态检查（见下）。
- **README 的安装示例不再落后**（`@v0.1.1` → `@v0.3.1`）；`PUBLISHING.md` 里的
  tag 示例同步更新。
- **CHANGELOG 的版本链接表补全**：`[未发布]` 的比较基准此前停在 `v0.2.0`（指向错误的区间），
  现在指向最新发布；并补上 `[0.3.1]` / `[0.3.0]` 两条定义。

### 新增（检查）

- `tests/audit-versions.mjs`：钉住发布面的一致性 —— 清单版本是规范 semver、
  CHANGELOG 有对应的带日期小节、顶部保留 `[未发布]`、每个已发布小节在链接表里有定义、
  `[未发布]` 的比较基准是最新发布、以及**所有钉住 tag 的安装示例都等于当前版本**。
- `tests/audit-ranks.mjs`：钉住 catalog rank 的关系（见下「修复」一节的说明）。
- `tests/audit-doc-consistency.mjs`：入口读的**每个环境变量**与认的**每个配置键**
  必须在文档里，且 `cordis.patch.yml` 只设已声明的键。

### 修复（插件入口的健壮性与诊断）

- **`ctx.logger` 缺失/残缺/抛异常时，插件不再崩在挂载阶段。** 此前 `apply()` 与
  provider 的 `list()` 直接调 `ctx.logger.warn/error/info`，而 `logger` 并不在
  `inject` 声明的契约里（只声明了 `skills`）——一条日志就能把整行插件带崩。
  现在统一走一个兜底：方法不可用或抛异常时退到 `console.error`（**不吞消息** ——
  诊断没人看得见正是这个插件自带 trace 要绕开的毛病）。
- **`ctx.skills.registerProvider` 缺失时不再抛栈**，改为报一条说明性错误并跳过该技能。
  与上一条同一规则：`skills` 不在契约里也不算插件能修的问题，但"哪个技能没注册上、
  缺的是什么"比一条穿过 `mount` 的栈更有用。
- **缺失 bundle 的报错变得可操作**：以前是一条裸 `ENOENT … SKILL.md`，分不清是
  "行配置写错路径"还是"包里没发布这个 bundle"。现在点明是哪个技能、按什么路径解析的、
  由哪个配置项决定，并说明后果。非法 frontmatter 的报错也去掉了重复的路径与冗余
  `Error:` 前缀。
- 新增回归 12 条（`run.mjs` 96 → **118**）：4 种残缺 logger、2 种缺失注册表、
  以及错误信息的可操作性（含"不泄漏原始 ENOENT"、"路径只出现一次"）。
  已用"把修复退化掉"的方式验证这些断言会真的变红。

### 修复（注释与行为不一致）

- **模块说明声称用 `register`（不是 `registerProvider`）**，并说 provider"得自己重新实现
  frontmatter 解析与目录排序"。实际早就用 provider 了 —— 那正是"改 `SKILL.md` 不需要重启"
  的原因。更糟的是**同一文件里另两处注释说的正好相反**，文件自我矛盾。
- **`readFrontmatter` 的说明说块标量（`|` / `>`）会被拒绝**，而代码就在下方**实现了它**
  （实测 `|` 解析为 `"第一行\n第二行"`）。改为如实描述三种值形式，并讲清嵌套映射的
  真实行为（缩进行跳过、键进 `unknown` 列表被报出来，而不是被静默吞掉）。
- **删掉未记录的 `DSH_WORKLOG_BASE` 后门**：全仓只有它自己那一处读取，行补丁、harness、
  文档都没设过。删而不补文档，是因为它提供的能力**已经是被文档化的那个** ——
  `skillDir` 接受绝对路径且 README 配置表写明。相应的 `ctx` 参数也从签名和两处调用点移除。
- **catalog rank 的注释是错的，而且机制比注释重要**。原文说 `350` 让本包"低于项目本地发现"。
  读注册表后确认：候选按 rank **升序**排（小的赢），但 **rank 只在同一层内决定同名归属**；
  跨层由**层级优先级**决定（项目 > runtime > 用户），rank 不参与。所以"用 rank 低于项目根"
  是无意义的。`350` 真正的位置在**同层的**文件系统根之间：项目本地 100/200、
  `customSkillDirs` 300、本包 350、用户级 400/500；而最要紧的是它**高于**注册表的
  `RUNTIME_RANK`（250），所以同层的 `ctx.skills.register()` 会在同名冲突中赢过本插件。
  这些关系现在由 `tests/audit-ranks.mjs` 对着注册表源码钉住，并写明它**测不了**跨层优先级
  （那是组合装配的性质，从包里观测不到）。已用改常量双向验证：`700` 会输给用户级根、
  `150` 会输给 `RUNTIME_RANK` 与项目根。

### 变更（格式规格：以三个真实语料为准重写）

> 依据：`docs/worklog-spec.md`。这一版**推翻了本文件下方几处基于二手数据的判断**，
> 因为实测三个真实语料后结论相反。

- **两种命名约定都认**（此前只认编号式）：
  - **编号式** `NNN-<slug>.md` + `# NNN · <标题>` —— 原型 207 篇、`comfy` 30 篇在用
  - **日期式** `YYYY-MM-DD-<slug>.md` + `# YYYY-MM-DD <标题>` —— `embeding try` 71 篇在用
  - 两种都不降级；一个容器建议只用一种，但混用不报错
  - **修复**：日期式文件此前被半解析成「编号 2026」，在 11–28 个文件间报**假重号**。
    这是实测语料一片红的主因（日期式容器 162 error 里 68 条是它）
- **格式放宽**：`日期：` 字段行与六段式模板**都从必填降为可选**。
  唯一硬性内容要求是**一个验证类小节**（日期式把日期写在文件名/H1 即可）
- **验证小节必须有实质内容**（新增检查）：`评测设置` 这类只有设置、没有结果的标题不再算数。
  默认 **WARN**，`--strict` 抬为 ERROR —— 宁可漏报，避免误报让人忽略这个工具
- **`变更集` 降为可选字段**：162 篇里有 146 篇写「无」，它不该是主字段。
  这份东西是**工作记录**，不是变更日志
- **`## 当前状态` 块改为容器自选**：有则校验新鲜度，没有只报 info
- **渐进原则**：老记录只报 `INFO`，新记录才判 error。依据是显式清单
  （`--legacy` / 容器根 `LEGACY.md`），都没有时按**容器规模**兜底（≥5 篇算已成规模）。
  **不用日期启发式** —— 实测日期字段只覆盖一半记录
- **默认精细度退回 `full`**（此前一轮改成了 `session`）。实测原型**一天最多 34 篇**、
  平均 9.2 篇/天，`session` 会把 34 个可独立查阅的单元压进一个文件。四个档位都保留
- **新增 `snapshot` 命令**：把最近 N 篇的入口元信息汇总成**只读**快照。
  状态分散在各篇开头后，这是"现在到哪了"的统一入口
- **定位修正**：本技能是**工作记录**（含工作区整理、取证复核、环境变动），
  不是变更日志。`analysis.md` 里"记录太多"的动机来自原型**早期**数据（引用率 19%），
  实测 `comfy` 已达 **25/30 = 83%**，故本版**不引入任何让记录变少的机制**

**实测效果**（`check --strict`，只读）：

| 语料 | 篇数 | 改前 | 改后 |
|---|---|---|---|
| 原型 `dsh_from_github` | 207 编号 | **135 error** | **7 error** / 130 info |
| `comfy` | 30 编号 | 0 error | **0 error** ✅ |
| `embeding try`（5 容器） | 68 日期 | **162 error** | **1 error** / 36 info |

剩下的 error 逐条核过，**全是真的**（编号断档、日期字段尾带注释、死链、真缺验证小节）。
自测 **179 → 228** 条断言。

### 新增（记录精细度）

- **记录精细度档位**，默认 **`full`（一篇 = 一个可交付单元）**。
  （本版曾一度把默认改成 `session`，实测后已退回 —— 见上方「格式规格」一节。）

  | 档位 | 一篇 = | 典型产出 |
  |---|---|---|
  | `full` | 一个可交付的子单元 | 一次会话可能 2–3 篇 |
  | **`session`（默认）** | 一次会话（或一个可交付成果） | 一次会话最多一篇；同一会话里的第二件事**追加**到同一篇 |
  | `digest` | 一个阶段 / 跨多次会话 | 多轮会话并成一篇 |
  | `milestone` | 一个阶段收口 | 只留决策与教训 |

  动因：`analysis.md` 的基线实测里，106 篇活跃记录只有 24 篇被经验层引用过 ——
  大部分记录写完就再没被读过。问题不是存储，是密度。

- **不可让的不变式：验证小节在**任何**档位都必须有。** 档位放松的是"要不要单开一篇"，
  不是"要不要写验证"；粗档位下缺验证仍然让 `check --strict` 报 error。
- **粗档位的新义务**：`digest` / `milestone` 下每篇必须写明**这轮没记什么**
  （`未记录：…` 一行，或 `## 未记录` 小节），否则粗粒度会静默丢信息。
  在 `lint` 里以 **WARN** 提示 —— 不会让记录变红，也不会破坏 `check --strict`。
- **档位存放**：`## 当前状态` 的**第 8 个固定字段 `精细度`**（老台账没有这个字段也照常工作，
  取默认档）。随容器进版本控制，`brief` / `status` 里可见，不新增文件。
- **切换命令**（`--why` 的原因直接写在同一字段里，不另起文件）：

  ```bash
  python scripts/journal.py mode                  # 看当前档位 + 一句含义
  python scripts/journal.py mode --set digest     # 切换
  python scripts/journal.py mode --why "阶段收口"  # 只记原因，不改档位
  ```

  只认 `full` / `session` / `digest` / `milestone`（也认中文别名：完整、会话、摘要、里程碑等），
  认不出的值退出码 2。写入复用已验证的 `status --set` 路径，因此继承 CRLF 保真、
  "只改目标行"、短名解析与非 UTF-8 拒写。
- 自测 122 → **179** 条断言：四个档位各自被接受、默认档、读写回环、非法值退出码、
  **每个档位下验证要求都不被放松**、粗档位的「未记录」义务、以及缺 `精细度` 的老台账
  仍能通过 `check --strict`。

### 变更（破坏性：目录布局）

- **记录体系收进单一容器目录 `work_log/`**。此前是**两个平行的顶层目录**（`journal/` +
  顶层 `lessons/`），现在统一到一个容器，内部再分类：

  | 旧位置 | 新位置 |
  |---|---|
  | `journal/README.md` | `work_log/README.md`（唯一台账，位置不变、角色不变） |
  | `journal/NNNN-*.md` | `work_log/NNNN-*.md`（编号记录住**容器根**，不再套一层 `journal/`） |
  | `journal/<YYYY>/NNNN-*.md` | `work_log/<YYYY>/NNNN-*.md`（按年分卷） |
  | `journal/archive/<stage>/NNNN-*.md` | `work_log/<stage>/NNNN-*.md`（**取消 `archive/` 中间层**） |
  | `journal/archive/STATUS-HISTORY.md` | `work_log/STATE-HISTORY.md` |
  | `journal/archive/README.md` | `work_log/ARCHIVE.md` |
  | `journal/archive/COLD-STORE.md` | `work_log/COLD-STORE.md` |
  | `lessons/`（顶层） | `work_log/lessons/` |

  容器名可配置：新增 `--work-log NAME`；`--journal NAME` 保留为等价的弃用别名。

- **归档判据不再依赖字面量 `archive/`**：改为「相对容器的第一段是 4 位年份 ⇒ 活跃（分卷），
  是别的子目录 ⇒ 已归档」。新旧布局因此共用一条规则，旧布局的 `archive/<stage>/` 无需特判。
  代价见 `conventions.md` 的 ⚠：容器下**任何**临时子目录里的 `NNNN-*.md` 都会被算作已归档。

- **旧布局只读回退，不迁移、不改名、不告警**：容器按 `--work-log`/`--journal` →
  `work_log/` → `journal/` → `work-log/` 顺序解析；经验目录先看容器内再回退项目根。
  `status --roll` / `archive` / `prune` 若发现旧布局的 `archive/{STATUS-HISTORY,README,COLD-STORE}.md`
  已存在，就**继续沿用原文件** —— 不把同一段历史劈成两份文件（历史只搬运、不改写）。

### 新增

- **「日志归位」要求**：项目产生的持久日志 / 运行产物一律放进容器并分类 ——
  `work_log/logs/<来源>/`，一个来源一个子目录（如 `work_log/logs/build/`、`work_log/logs/bench/`）。
  不许散落在项目根，更不许写到项目之外；日志内只写相对路径。
  **测试夹具与一次性样本不算记录**，不进容器。
  这条同时写进了 `SKILL.md`（独立小节 + 工作流 A/C 引用）、`conventions.md`（完整表述）与反模式表。

- `_selftest.py` 断言 96 → **122**：新增容器根放记录、`lessons/` 属容器子目录、归档落
  `work_log/<stage>/`、`STATE-HISTORY.md` 落容器根、`lessons/` 不被当成归档阶段、
  `logs/` 下同形文件名不算记录、`--lessons` 改名后仍被排除、以及整套旧布局回退的回归。
- 文档里的自测数字**不再硬编码**（`analysis.md` 原写 `95/95`，且因计数时机差一本来就错）。
  约束仍在：`_selftest.py` 会核对文档里出现的任何统计数字，写死过期数字会被判 FAIL。

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

- **`reliability-guidelines` 技能（八条可靠性工作准则，中英双语）**：随本包装载，在装了本插件的
  项目里作为**默认强约束**生效。经用户显式要求可以推翻，但要求先说明"放弃了哪条 + 什么风险"
  并在 `journal/` 留一句理由 —— 即"不许悄悄违反"，而不是"不许推翻"。
  - 中文版在 bundle 根（`skills/reliability-guidelines/SKILL.md`），英文版在其 `en/` 子目录。
    放子目录是因为 `skill-filesystem` 只扫描一层，这样一份 bundle 携带两种语言而目录里只出现一个技能。
  - 与 worklog 打通验证口径：准则第 7 条的证据＝记录里的验证小节，门禁＝`check --strict` / `lint --strict`。
  - 新增配置 `guidelinesEnabled`（默认 `true`）、`guidelinesDir`、`guidelinesLanguage`（`'zh'` 默认 / `'en'`）。
  - **与原始文档相比的实质修改**：原稿前言写"用户请求违反规则就礼貌拒绝、用户确认不能豁免"，
    与它自己的原则 3（用户确认才算数）**直接冲突**，且把"拒绝用户"写成了授权。已改写为
    "默认强约束 + 用户可显式推翻 + 推翻须记录"。原稿纯英文，现以中文为准并补英文版。
  - 本包**没有**把它做成"每轮注入的系统提示词段落"：`ctx.systemPrompt.section()` 能做到，
    但那样它对所有请求生效，与"只在装了插件的项目里生效"的定位不符。
- **插件现在提供两个技能**（两个 provider：`worklog-bundle` / `worklog-guidelines`）。
  注册表要求 provider 名唯一，且候选与定义的 `provider` 字段都必须与之一致。

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

[未发布]: https://github.com/IThinkItsaName/dsh-worklog/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/IThinkItsaName/dsh-worklog/compare/v0.4.0...v0.5.0
[0.3.1]: https://github.com/IThinkItsaName/dsh-worklog/compare/v0.3.0...v0.3.1
[0.4.0]: https://github.com/IThinkItsaName/dsh-worklog/compare/v0.3.1...v0.4.0
[0.3.0]: https://github.com/IThinkItsaName/dsh-worklog/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/IThinkItsaName/dsh-worklog/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/IThinkItsaName/dsh-worklog/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/IThinkItsaName/dsh-worklog/tree/v0.1.0
