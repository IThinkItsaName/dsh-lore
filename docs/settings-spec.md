# 设置规格（待实现）

> **状态**：设计已确认，实现未开始。本文是实现的依据。
>
> 前置结论来自对 DSH 插件机制的实测，不是推测；无法确认的地方都标了「**未确认**」。

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

## 二、插件设置页

### 能改什么

| 设置项 | 类型 | 默认 | 位置 | 谁读它 |
|---|---|---|---|---|
| `guidelinesEnabled` | 开关 | 开 | 主区 | **插件**（挂载时） |
| `guidelinesLanguage` | 分段控件：中文 / English | 中文 | 主区 | **插件**（挂载时） |
| `verbose` | 开关 | 关 | 主区 | **插件**（挂载时） |
| `skillDir` | 文本框 | 包内默认 | 高级 | **插件**（挂载时） |
| `guidelinesDir` | 文本框 | 包内默认 | 高级 | **插件**（挂载时） |
| `container` | 文本框 | `work_log` | 高级 | **`journal.py`** —— 插件只存 |
| `lessons` | 文本框 | `lessons` | 高级 | **`journal.py`** —— 插件只存 |
| `mode` | 四档下拉 | `full` | 高级 | **`journal.py`** —— 插件只存 |

**最后三行是项目级设置**，不是插件设置。它们存在插件设置文件里，只是为了让页面能
给新项目提供默认值；**插件自己不读它们**（见 §三）。

> 实现时这条曾被混起来：`effectiveSettings()` 一度返回全部 11 个键，于是
> `apply()` 的 options 里带着三个模块从不读的键，而路由把这三个也报成
> "插件会怎么做"。现在拆开：`KNOWN_CONFIG_KEYS`（挂载时读）与
> `PROJECT_DEFAULT_KEYS`（只存不读）。

### 必须标注的事

1. **靠插件读的那几个：改完需重启 DSH 生效。** 不标就是骗人 —— 它们是 `apply()` 时读的。
2. **上面三行项目级设置不归插件管**，界面必须说清它们写的是项目的 `.config.json`、
   由 `journal.py` 读 —— 否则用户会以为勾一下插件设置就改了某个项目的行为。
3. **改名类（`container`/`lessons`）是破坏性的**：已有项目改名后 `journal.py`
   **找不到记录，而且不会说"你是不是改名了"**，只会报"找不到容器"。这条坑我们踩过同类。
4. **`guidelinesLanguage` 只影响准则那份技能**（`worklog` 技能本身是中文写死的）。

### 设置文件的落点与优先级

| | |
|---|---|
| 落点 | `<DSH_HOME>/worklog/settings.json`（`$DSH_HOME` 否则 `~/.dsh`；`DSH_WORKLOG_SETTINGS` 可整路径覆盖） |
| 优先级 | **设置文件 > row config（`cordis.patch.yml`）> 内置默认** |

**文件必须赢，这不是口味问题**：bundle 补丁里写死了 `guidelinesEnabled` /
`guidelinesLanguage` / `skillDir` / `guidelinesDir` 四个键。如果 row 赢，
**设置页改什么都无效**。

**为什么不放在包旁边**：装进 profile 的是指向 git 工作树的 junction，
写在那里会弄脏工作树、还容易被误提交；而重装/升级会替换那个目录 ——
恰恰是最不该丢设置的时候。`dsh-status-rotator` 也是为这个原因从包内
`config.json` 迁到了 home 目录。


## 三、`mode` 在两个面上的语义（唯一允许重叠的一项）

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

**先只做中文**，跑通后再补英文。

设置页的导航名走 locale 机制（`label: () => st("nav.label")`），
而包内 `locale/` 已经就位（`en.json` / `zh-cn.json` / `zh.json`），补英文是同一个机制。

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

### 配置存取 —— 节点半边起路由

浏览器端碰不到文件系统，所以由**节点半边**把配置服务出去：

```js
ws = ctx.get("webServer")            // 可选服务：用 ctx.get，不要写进 inject
routeDisposer = ws.register({
  kind: "exact",
  path: "/plugins/dsh-worklog/settings.json",
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
请求体用 `for await (const chunk of req)` 读，并设上限。

这解释了为什么以前认为的"硬障碍"不成立 —— 我们一直没法导出 `Config`
（树外插件解析不到 `@deepseek-ai/schemastery`），但**那条路本来就不必走**。

### 验收限制（必须说清）

**设置页是浏览器里的 React，实现者看不到它。** 能机械验证的是：
语法合法、`exports`/`files`/`dsh.client` 齐全、`require` 的每个 specifier 都在那 9 项里、
节点侧路由的 GET/PUT 行为、以及节点半边原有行为不回归。

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

### 6.4 浏览器端怎么读写配置 —— 已确认

**用 `ctx.get("webServer")` 注册自己的路由**（见 §五「配置存取」）。服务契约：

```ts
register(route: WebRoute): () => void
WebRoute = { kind: 'exact'|'prefix', path: string,
             handler: (req: IncomingMessage, res: ServerResponse) => void|Promise<void> }
```

`webServer` 是**可选**服务（`ctx.get("webServer")` + 未定义检查），
所以没有 Web 服务器的 DSH 构建不会因此挂掉。

> 至此 §六 四条**全部确认**。剩下的只是"第一次真跑会不会撞到签名细节" ——
> 所以仍按"最小可用先行"推进。

## 七、实现顺序

1. ~~**项目配置文件 + `journal.py`**~~ —— **已实现**（`config` 子命令；自测 288/288；
   三个真实语料的 `check --strict` 前后完全一致）
2. **插件设置页** —— 先做一个最小可用的（一个开关 + 一个下拉），确认能注册、
   能存取、能显示，再加别的

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


