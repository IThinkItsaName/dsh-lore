# 设置规格

> **状态**：设置界面与 `journal.py config` 都已实现。
>
> **2026-09-29 的两次改动（本规格的 §二/§四/§五 已按结果校正）**：
> 1. **事实源换成 profile patch**（`work_log/0039` 的 A1）：有 `configEditor` 的宿主以
>    `<profile>/cordis.patch.yml` 为准，写回由宿主校验；headless 仍读插件自己的文件。
> 2. **界面换成官方配置卡片**（`work_log/0040` 的 A2+A3）：客户端半边注册进
>    **`plugins.item`**（插件页条目）而不再是设置页的 `settings.section`；
>    读写走 `ctx.configForms`，自建 HTTP 路由**只剩一个只读状态端点**。
>    分页也从两个变成**三个**（技能 / 记忆 / 高级）—— 记忆那三个键此前在规格里根本
>    没被登记。
>
> 前置结论来自对 DSH 插件机制的实测，不是推测；无法确认的地方都标了「**未确认**」。
> **被推翻过的结论留在原处并标明推翻**（见 §五 末尾与 §六.5）——抹掉它们会让下一个人重踩。

## 零、为什么要有两个设置面

这个插件有两种配置，**生效时机完全不同**：

| 类型 | 何时读 | 改完何时生效 |
|---|---|---|
| 插件装载参数 | `apply()` 挂载时 | **需重启宿主** |
| journal.py 行为 | 每次执行脚本时 | **立即生效** |

把它们混在一个界面里，就会出现「点了开关没反应」这类坏体验。所以分成两面：

| 设置面 | 管什么 | 存哪 | 生效 |
|---|---|---|---|
| **插件设置页** | 插件自身的装载行为 | 插件读写的配置文件 | 改完**需重启** |
| **项目配置文件** | `journal.py` 的行为 | `<容器>/.config.json`（随项目进版本控制） | **立即生效** |

### 一条不许破的规则

**两个设置面不许管同一件事。**

唯一的例外是「默认档」，而它靠**语义**而不是靠"两处都读"来避免冲突 —— 见 §三。

## 一、项目配置文件（`<容器>/.config.json`）

### 形式

```json
{
  "mode": "digest",
  "container": "work_log",
  "lessons": "lessons",
  "legacy": ["0007-*", "archive/**"],
  "snapshotEntries": 12
}
```

### 字段

| 字段 | 类型 | 内置默认 | 说明 |
|---|---|---|---|
| `mode` | `full` / `session` / `digest` / `milestone` | `full` | 默认精细度档 |
| `container` | string | `work_log` | 容器目录名 |
| `lessons` | string | `lessons` | 经验目录名 |
| `legacy` | string[] | `[]` | 渐进原则的旧记录清单 |
| `snapshotEntries` | number | `12` | `snapshot` 默认显示篇数 |

### 优先级

```
命令行参数  >  <容器>/.config.json  >  内置默认
```

**但这条严格三级只对 `mode` / `legacy` / `snapshotEntries` 成立。**
`container` 与 `lessons` 是例外，它们**命名配置文件自己所住的目录** ——
不可能靠读配置文件得知自己在哪。所以：

| 字段 | 实际顺序 |
|---|---|
| `container` | `--work-log`/`--journal` → **目录发现**（`work_log/` → `journal/` → `work-log/`） |
| `lessons` | `--lessons` → 配置 → `<容器>/lessons/` → `<根>/lessons/`，**只认实际存在的目录** |

- 配置里的 `container` **改不了生效值**：它连自己所在的目录都指不动。
  与实际目录不符时**报出来、但不失败**（`config` 里打印 `!`，`check` 里是 INFO）。
- 配置里的 `lessons` 与实际存在的目录不符时，**按实际目录走**，同样报出来。
- 两个字段的正确理解是「**新项目该叫什么**」—— 这正是插件在初始化时写它们的原因。

> 这些不对称**必须是 INFO、绝不进退出码**：配置文件写错一个字段，不该让记录的
> CI 变红 —— 那个错的原因不在记录里。

### `legacy` 的"空数组"与"不写"不同

| 写法 | 含义 |
|---|---|
| `"legacy": []` | **显式声明"没有旧记录"** —— 会关掉按容器规模兜底的规则 |
| 不写 `legacy` | 回落到 `LEGACY.md`，再回落到按规模兜底 |

与命令行 `--legacy ""` 的语义一致。

### 配置文件坏掉时

**永不致命。** 具体分级：

| 场景 | `config` | 其它命令 |
|---|---|---|
| JSON 坏 / 有未知字段 / 值非法 | 报出并**退出码 2** | 退回内置默认继续干活 |
| 字段与实际不符（`container`/`lessons`） | 打印 `!`，退出码 0 | `check` 报 INFO |

### 为什么档位仍然存在台账里

档位有**两个不同的问题**，不要混：

- 「**这个项目当前用哪档**」—— 已存在，在台账 `## 当前状态` 的 `精细度` 字段
- 「**新项目默认用哪档**」—— 本次新增，在 `.config.json` 的 `mode`

`journal.py mode` 读写的是前者（台账）；`.config.json` 的 `mode` 只提供**初始值**。
用户在项目里显式切过档之后，台账就是权威。

## 二、插件配置卡片

> **2026-09-29 起**：界面是**插件页上的一张卡片**（槽位 `plugins.item`），
> 不再是设置页的分区。理由见 `SETTINGS.md` §「配置界面」：这一页管的是插件自己的
> 配置，归属就在插件条目下面，也与官方那几个宿主侧插件的配置页同构。

### 三个分页：技能 / 记忆 / 高级

界面用宿主的 `SegmentedTabs` 分三页，默认停在「技能」。它**只渲染标签栏，面板由
调用方持有** —— 面板自己带 `role="tabpanel"`、自己的 `id`，以及指回对应标签页的
`aria-labelledby`；一次只渲染被选中的那一个。

| 分页 | 装什么 |
|---|---|
| **技能** | `guidelinesEnabled`、`guidelinesLanguage`，以及收在「路径」折叠区里的 `skillDir` / `guidelinesDir` |
| **记忆** | `memoryEnabled`、`memoryInjectIndex`、`memoryPersonalSearchable`，外加一个只读的「当前状态」折叠区 |
| **高级** | `verbose`、`modelInvocable`、`userInvocable` |

### 能改什么

| 设置项 | 类型 | 默认 | 位置 | 谁读它 |
|---|---|---|---|---|
| `guidelinesEnabled` | 开关 | 开 | 技能 | **插件**（挂载时） |
| `guidelinesLanguage` | 分段控件：中文 / English | 中文 | 技能 | **插件**（挂载时） |
| `skillDir` | 文本框 | 包内默认 | 技能 › 路径（默认收起） | **插件**（挂载时） |
| `guidelinesDir` | 文本框 | 包内默认 | 技能 › 路径（默认收起） | **插件**（挂载时） |
| `memoryEnabled` | 开关 | 开 | 记忆 | **插件**（挂载时） |
| `memoryInjectIndex` | 开关 | 开 | 记忆 | **插件**（用时现读） |
| `memoryPersonalSearchable` | 开关 | 关 | 记忆 | **插件**（用时现读） |
| `verbose` | 开关 | 关 | 高级 | **插件**（挂载时） |
| `modelInvocable` | 开关 | 开 | 高级 | **插件**（挂载时） |
| `userInvocable` | 开关 | 开 | 高级 | **插件**（挂载时） |
| `skillFile` | — | `SKILL.md` | **界面不提供控件** | **插件**（挂载时）—— 只由行配置给 |
| ~~`container`~~ | — | `work_log` | **界面不提供** | **`journal.py`** —— 插件不读 |
| ~~`lessons`~~ | — | `lessons` | **界面不提供** | **`journal.py`** —— 插件不读 |
| ~~`mode`~~ | — | `full` | **界面不提供** | **`journal.py`** —— 插件不读 |

**记忆那三个键此前没有登记在规格里** —— 这是规格与实际的一处遗漏，2026-09-29 补上。
它们都由 `apply()`/工具调用读取，`memoryEnabled` 是装载期，另两个用时现读。

**最后三行是项目级设置**，不是插件设置。它们**不在 `Config` 里**，所以既不进
profile patch，也没有任何界面展示或提交它们；`projectDefaults()` 仍会解析它们
（`appliedByPlugin: false`），但那从来不是给页面用的 —— 它的作用是让"存着的项目
默认值"与"插件设置"不可能被混为一谈（`tests/audit-settings.mjs` 钉着这一点）。

> 实现时这条曾被混起来：`effectiveSettings()` 一度返回全部 11 个键，于是
> `apply()` 的 options 里带着三个模块从不读的键，而路由把这三个也报成
> "插件会怎么做"。当时拆成：`KNOWN_CONFIG_KEYS`（挂载时读）与
> `PROJECT_DEFAULT_KEYS`（只存不读）。
>
> 后来又走了一步：页面连控件也不给了。"标着插件不读"仍然是**把项目级的东西
> 摆在插件设置页上** —— 用户的注意力、以及"改这里试试"的直觉，都被引到了错误的
> 那一面。节点半边的 `PROJECT_DEFAULT_KEYS`、`projectDefaults()` 与路由的
> `projectDefaults` 字段**一个都没删**：它们的作用从来不是给页面用，而是让
> "存着的项目默认值"与"插件设置"不可能被混为一谈
> （`tests/audit-settings.mjs` 钉着这一点）。

### 必须标注的事

1. **靠插件读的那几个：改完需重启 DSH 生效。** 不标就是骗人 —— 它们是 `apply()` 时读的。
2. **项目级设置（`container` / `lessons` / `mode`）不在这两页里**，界面只在页脚留一句
   兼容性说明，把它们指向 `journal.py config`。用户不会以为勾一下插件设置就改了
   某个项目的行为，因为那些键根本不出现。
3. **改名类（`container`/`lessons`）是破坏性的**：已有项目改名后 `journal.py`
   **找不到记录，而且不会说"你是不是改名了"**，只会报"找不到容器"。这条坑我们踩过同类。
   （页脚那句说明保留了这个警告，因为改动它们的地方是 `journal.py config`。）
4. **`guidelinesLanguage` 只影响准则那份技能**（`worklog` 技能本身是中文写死的）。

### 设置存在哪：两种宿主，两个落点

| 宿主 | 落点 | 谁写 |
|---|---|---|
| 有 `configEditor`（桌面 profile） | `<profile>/cordis.patch.yml` 里我们这个条目的 `config:` 块 | **官方通道**：客户端 `ctx.configForms` → 宿主校验 → `dsh-config-editor` |
| 没有 `configEditor`（headless、测试夹具） | `<DSH_HOME>/worklog/settings.json`（`$DSH_HOME` 否则 `~/.dsh`；`DSH_WORKLOG_SETTINGS` 可整路径覆盖） | 没有程序写它 —— **手工编辑** |

**有 editor 时分层由宿主解析**：profile patch（用户层）> 本包行配置 > 内置默认。

**没有 editor 时插件自己合**：`设置文件 > 行配置 > 内置默认`。**文件必须赢，这不是
口味问题**：bundle 补丁里写死了 `guidelinesEnabled` / `guidelinesLanguage` / `skillDir` /
`guidelinesDir` 四个键，如果行配置赢，那个文件就是死的。

**旧文件一次性迁进 patch**（四条规矩见 `SETTINGS.md`），然后改名成
`settings.json.migrated` 留档。

**为什么不放在包旁边**：装进 profile 的是指向 git 工作树的 junction，
写在那里会弄脏工作树、还容易被误提交；而重装/升级会替换那个目录 ——
恰恰是最不该丢设置的时候。`dsh-status-rotator` 也是为这个原因从包内
`config.json` 迁到了 home 目录。


## 三、`mode` 在两个面上的语义（唯一允许重叠的一项）

> **现状**：设置页已经不再提供 `mode` 的控件（见 §二），所以下面这条"唯一允许重叠"
> 的通路目前**没有界面入口** —— `.config.json` 的 `mode` 只能由 `journal.py config` 写。
> 语义没变，保留在这里是因为它解释了为什么插件**不读** `mode`，以及为什么它
> **不能**被并进插件设置页：那样 `journal.py` 就得依赖插件。

讨论中最容易出错的地方，所以写清楚。

```
设置页（插件级）                项目文件（项目级）                运行时
默认档 = digest   ──初始化时写入──▶  .config.json: mode=digest  ──▶  journal.py 读它
```

- 设置页的 `mode` 是「**新项目初始化的默认档**」
- 插件在**项目初始化时**把这个值写进 `.config.json`
- `journal.py` **始终只读项目文件**，不去问插件
- **而插件自己完全不读 `mode`** —— 它只是替项目记住这个默认值

### 为什么不让 journal.py 直接读插件配置

那样 `journal.py` 会**依赖插件**，于是：
- 别的 agent 平台（没有 DSH）用不了这个默认
- 违背它「纯标准库、哪里都能跑」的定位

### 代价（要写进文档）

**已在跑的项目不会被追溯改变。** 设置页改默认档，只影响之后初始化的项目。
这是刻意的 —— 否则会出现"我改了插件设置，老项目行为突然变了"。

## 四、界面文案

**先只做中文**，跑通后再补英文 —— 英文词典现已就位（键集与中文一致，
`tests/audit-client.mjs` 会对账）。

插件页条目名走 locale 机制（注册声明里的 `label: () => t("title")` thunk +
`locale: SETTINGS_NS`），卡片上每个字段的文案都从同一份词典取。
包内 `locale/` 是**另一件事**（插件在插件管理器里的显示名与描述，
`en.json` / `zh-cn.json` / `zh.json`），与界面词典无关。

## 五、实现约束（实测得来）

### 客户端半边的形态

设置页面板是一个 **React 函数组件**（`dsh-status-rotator` 的 `SettingsPanel` 用
`useState`/`useRef`，且它对 `require` 的唯一调用是 `require("react")`）。

客户端半边的发布形态是被包装过的：

```js
window.__ModuleLoader__.load({
  id: "<plugin-id>",
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports
    …
    return module.exports
  },
})
```

`require` 由 DSH 的浏览器模块加载器注入，`react` 从中取得 —— **不需要把它列进依赖**。

### 需要新增的声明

```jsonc
// package.json
"exports": { "./client": "./lib/client.js", … },
"dsh": {
  "bundle": { "patch": "./cordis.patch.yml" },
  "client": { "platform": "web", "inject": [], "immediately": true }
}
```

`files` 里也要加客户端产物。

### 挂载点

> **已被取代（2026-09-29）**：下面这段是**旧**设计（设置页分区）。现在的挂载点是
> 插件页的 `plugins.item`，而且**不是写死 namespace 的** —— 卡片按 schema 字段集
> 认领自己那一行（`ns` 是部署相关的）。现行写法见 `lib/client.js` 的 `apply()`。
> 旧写法留在这里，是因为"当初为什么那么挂"与"后来为什么换"是两条不同的信息。

```js
ctx.slots.inject("settings.section", () => ctx.slots.register({
  name: "settings.section",
  id: "dsh-worklog",
  order: 50,
  label: () => st("nav.label"),   // 走 locale
  locale: SETTINGS_NS,
}, SettingsPanel))
```

### 界面组件 —— 用官方的，不要手搓

`@deepseek-ai/dsh-client-ui-primitives`（在那 9 项 baseline 里）提供现成组件，
**只用 `--dsw-*` 令牌着色、Cordis-free**。已核实的签名：

```ts
Switch({ checked, onChange, label, disabled?, title?, className? })
  // label 必填 —— 组件设计上不允许交出没有无障碍名的开关
Input({ icon?, className?, ...inputAttributes })          // 外层 span，原生属性透传
SegmentedControl<V extends string>({ id, value, options, onChange, label, disabled?, className? })
  // options: { value, label, disabled?, title? }[]，至少两段
DisclosureRow({ icon, title, open, expandable, onToggle, …, children? })
  // 折叠区用它
```

另有 `Button` / `Pill` / `Tag` / `Checkbox` / `Menu` / `Modal` / `RiskConfirmation` /
`StateDot` / `SegmentedTabs` / `PathLabel` / `TextShimmer`。

> 这解释了 `dsh-status-rotator` 的 259 KB：它自带了整套 CSS。**我们不必重蹈** ——
> 用官方组件就自动跟着主题与语言走。

### 配置存取 —— 现在走官方通道，路由只读

> **已被取代（2026-09-29）**：这一段原本是"节点半边起路由"的完整设计。现在
> **配置的读写走 `ctx.configForms`**（宿主自己的设置通道），HTTP 上只剩一个
> **只读状态端点** `GET /plugins/dsh-worklog/status.json`，用来报记忆规模与
> "设置落在哪"。下面关于路由的两个坑**仍然成立**，只是现在只有那一个只读端点还用它。

浏览器端碰不到文件系统，所以由**节点半边**把运行时状态服务出去：

```js
ws = ctx.get("webServer")            // 可选服务：用 ctx.get，不要写进 inject
routeDisposer = ws.register({
  kind: "exact",
  path: "/plugins/dsh-worklog/status.json",
  handler: (req, res) => { … },      // 标准 Node http handler
})
return () => routeDisposer()          // 必须交回 disposer
```

**两个坑**（都在 `dsh-status-rotator` 里印证过）：

1. **必须交回 route disposer。** 重复的 `(kind, path)` 会抛错，所以插件重载时
   没释放的路由会让**激活直接失败**。
2. **`webServer` 可能在 `apply()` 时还不存在**，需要轮询等待（它用的是
   500ms × 最多 20 次）。用 `ctx.get("webServer")` 而不是 `inject`，
   这样没有 Web 服务器的 DSH 构建也不会让插件挂掉。

`WebRoute = { kind: 'exact'|'prefix', path, handler: (req, res) => void|Promise<void> }`。

**这个端点不接受写**：`GET`/`HEAD` 以外一律 405。原因见 `SETTINGS.md`：
配置已经有一个事实源，再开一个写入口就是本项目按缺陷处理的那类东西。
（旧设计里"请求体用 `for await (const chunk of req)` 读，并设上限"因此不再适用 ——
没有请求体要读了。）

**旧结论已作废**：这一段原先接着写「这解释了为什么以前认为的"硬障碍"不成立 ——
我们一直没法导出 `Config`（树外插件解析不到 `@deepseek-ai/schemastery`），
但**那条路本来就不必走**」。前半句**被推翻**（`Config` 是能导出的，条件是声明
peerDependencies），后半句"不必走"也只是当年的权宜 —— 现在正是走那条路。
见 §六.5 的更正。

### 验收限制（必须说清）

**配置卡片是浏览器里的 React，实现者看不到它。** 能机械验证的是：
语法合法、`exports`/`files`/`dsh.client` 齐全、`require` 的每个 specifier 都在那 9 项里、
状态端点的行为、以及节点半边原有行为不回归。

> **2026-09-29 补**：客户端这一面的机械验证**比这段写的时候强得多**了。
> `tests/audit-client-runtime.mjs` 用桩 `window.__ModuleLoader__` + 自制 React hook
> 运行时**真的把卡片挂起来跑**：认领 namespace（含对抗性输入）、开关写出的 mutation
> 形状、路径框"输入不写/失焦才写"、被拒写入的提示与回退、状态读取失败时的降级，
> 全都断言得到（152 条）。仍属于"只能由人看"的只剩**排版与视觉**。

**渲染效果只能由人刷新页面确认。** 所以按"最小可用先行"推进：
先只做 `guidelinesEnabled` + `guidelinesLanguage` 两个控件，跑通再加别的。

## 六、机制查证结果

以下三条原本是「实现前必须验」的未知项。查了 DSH 源码（`dsh_from_github/deepseek-harness`
的 `packages/client/`）之后，两条已确认，一条降级为局部问题。

### 6.1 `require("react")` 可用 —— 已确认

`packages/client/web/src/seed.ts` 是权威清单，原文说这是
「the ONLY entities the shell shares into the frozen module table」：

```ts
export function getStaticModules(): Record<string, unknown> {
  return {
    'react': React, 'react/jsx-runtime': ReactJsxRuntime,
    'react-dom': ReactDom, 'react-dom/client': ReactDomClient,
    '@deepseek-ai/cordis': Cordis,
    '@deepseek-ai/dsh-client-store': ClientStore,
    '@deepseek-ai/dsh-client-ui-slots': UiSlots,
    '@deepseek-ai/dsh-client-ui-primitives': UiPrimitives,
    '@deepseek-ai/dsh-client-ui-dockkit': UiDockkit,
  }
}
```

**固定的 9 项，任何客户端半边都能 `require` 到，无需声明、无需装依赖。**

> **意外收获**：`dsh-client-ui-primitives` 与 `ui-slots` 也在清单里 ——
> DSH 提供现成的 UI 组件基元，不必从零写表单控件。
> （`dsh-status-rotator` 那 259 KB 大部分是它自带的 CSS，我们不需要重蹈。）

`require` 是 `factory(require)` 的参数、由模块系统注入，**不是 Node 的 require**。

### 6.2 不需要自己的打包步骤 —— 已确认

`packages/client/tsdown.client.ts` 里的包装就是三行：

```js
banner: `window.__ModuleLoader__.load({ id: "…", factory: (require) => {`
intro : `var module = { exports: {} }; var exports = module.exports;`
footer: `return module.exports; } });`
```

`intro`/`footer` 只造一个 CJS 外壳，中间是普通模块代码 —— **手写即可，不需要 tsdown**。

宿主侧也只是把文件当字节服务（`packages/client/modules/src/index.ts:847`）：

```js
throw new Error(`client-modules: ${packageName} declares dsh.client but exports no "./client" bundle`)
clientPath: join(dirname(pkgPath), clientRel)   // 路径直接来自 exports["./client"]
```

**唯一约束：不能用 JSX**（语法需转译）。用 `React.createElement` 直接写 → 零构建。

### 6.3 客户端模块的形态 —— 已确认

客户端半边就是一个**普通 Cordis 插件模块**，导出 `apply`：

```js
// packages/client/ui-approval/src/index.ts 全文的核心就这一行：
export function apply(): void {}
```

`inject` 作为具名导出（`packages/client/ui-chat/src/client/apply.ts`）：

```js
export const inject = [ … ]
export function apply(ctx) { … }
```

所以浏览器半边与我们节点半边的 `lib/index.js` **是同一个形状** ——
都是 `export const inject` + `export function apply(ctx)`。

### 6.4 浏览器端怎么读写配置 —— **已按 2026-09-29 的实现更正**

**配置读写现在走官方的 `ctx.configForms`**：客户端从槽位注册的 `inject` 面拿到
宿主给的表单控制器（`getSnapshot` / `subscribe` / `set` / `unset` / `mutate`），
**不自己发 HTTP**。宿主的写回路径由 `dsh-config-editor` 落到 profile patch。

**HTTP 只剩一个只读状态端点**（`ctx.get("webServer")` 注册，见 §五「配置存取」）。
服务契约未变：

```ts
register(route: WebRoute): () => void
WebRoute = { kind: 'exact'|'prefix', path: string,
             handler: (req: IncomingMessage, res: ServerResponse) => void|Promise<void> }
```

`webServer` 是**可选**服务（`ctx.get("webServer")` + 未定义检查），
所以没有 Web 服务器的 DSH 构建不会因此挂掉。

> 至此 §六 四条**全部确认**。剩下的只是"第一次真跑会不会撞到签名细节" ——
> 所以仍按"最小可用先行"推进。

### 6.5 「树外插件导不出 `Config`」—— **这条结论是错的**

`docs/plugin-spec.md` 与本文早先都写过：树外插件解析不到 `@deepseek-ai/schemastery`
（它只在 `app.asar` 里），所以 `Config` 导不出来，配置只能自建通道。

**它是拿"手放目录"测出来的** —— 量错了对象。装进 profile 的插件由宿主按自己的
锚点解析依赖，`Config` 照常工作；条件是把宿主包声明成 **`peerDependencies`**
（不声明时链接安装下会 `MODULE_NOT_FOUND`，那是另一回事，见 `work_log/0021`）。

实测终点（`work_log/0022`、`0031`）：`Config.listConfigs{name:"dsh-worklog"}` →
`schema`，11 个字段全带 `x-cordis.volatile: true`。
教训写在 `work_log/0016`：**一条错误结论会被固化进门禁与文档，并且很难再被发现**。

## 七、实现顺序

1. ~~**项目配置文件 + `journal.py`**~~ —— **已实现**（`config` 子命令；自测 288/288；
   三个真实语料的 `check --strict` 前后完全一致）
2. ~~**插件配置界面** —— 先做一个最小可用的（一个开关 + 一个下拉），确认能注册、
   能存取、能显示，再加别的~~ —— **已实现**，并且走完了一条更长的路：
   自建设置页 → 换事实源到 profile patch → 换成官方 `configForms` 驱动的插件页卡片
   （`work_log/0038`、`0039`、`0040`）。

> 第一次真跑仍可能撞到意外（`ctx.slots.inject` 的签名细节、`ctx.effect` 的清理语义）。
> 上面的结论来自**读源码，不是实跑** —— 所以第 2 步按"最小可用先行"推进。

## 八、实现后发现的遗留

### 8.1 无脚本版还没提配置文件

`skill-only/project-work-log/`（手写的无脚本变体）与 `dist/skill-only/` 目前
**一个字都没提 `.config.json`**。它不读配置（它本来就不跑脚本），但既然项目里
会出现这么一个文件，**它应该告诉读者这是干什么的** —— 否则接手的人会看到一个
来历不明的 `.config.json`。

构建命令是 `node tools/build-skill-only.mjs`；`_package.py` 不管这两个产物。

### 8.2 `_measure.py` 曾各自抄了一份默认值 —— 已修

它原先自己写了 `MODE_DEFAULT = "full"` 且**不读 `.config.json`**，于是同一个项目
`_measure.py` 与 `journal.py mode` 会报出**不同的精细度**。同一个问题两个答案，
正是这个体系最想避免的那一类缺陷。

现在它 `import journal` 并复用同一份常量与配置；不能再 import 时（文件被单独拷走）
退回字面量。来源措辞也据实区分「取配置 `mode` `X`」与「取内置默认 `X`」——
`Config.mode` 无论有没有配置文件都会被填成默认值，所以判断来源**看的是文件里是否
真的写了 `mode` 这一项**，不是看那个字段的值。

### 8.3 `lint` 的粗档位义务跟随配置的 `mode`

粗档位（`digest`/`milestone`）要求记录写「未记录：…」。当台账**没有** `精细度`
字段时，`lint` 会采用配置里的 `mode` 作为生效档位 —— 也就是**配置说了算**。

**这是有意的**：配置的 `mode` 本来就是"这个容器该用哪档"，在没有更具体声明时它
就是最具体的声明。若要改成只看台账，是 `lint` 里一行的事。


