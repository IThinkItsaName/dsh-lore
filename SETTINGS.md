# 插件设置

本文记录 **DSH 插件半边**（`lib/`）的设置面。它是 `README.md` 之外新增的一份说明，
因为实现里出现了两个必须被写下来的东西：设置文件的位置，以及两个环境变量。

项目的配置（`<容器>/.config.json`）不在这里 —— 它是 `journal.py` 的事，
见 [docs/settings-spec.md](docs/settings-spec.md) 第一节。

## 两个设置面不许管同一件事

| 设置面 | 管什么 | 存哪 | 改完何时生效 |
|---|---|---|---|
| **插件设置页** | 插件自身的装载行为 | `<DSH_HOME>/worklog/settings.json` | 需重启 DSH |
| **项目配置文件** | `journal.py` 的行为 | `<容器>/.config.json` | 立即生效 |

**这条规则现在是硬边界，没有例外。** 设置页曾经收集三个项目侧默认值
（`container` / `lessons` / `mode`）并给它们标上「插件不读」；那一组已经整个撤掉 ——
见下面的「项目侧默认值：存着，但不提供控件」。文档里仍留着这套键的名字，
是因为节点半边仍然存它们、也仍然在路由里回报它们。

## 装/改之后要**硬刷新页面**

改完客户端半边、重启过宿主之后，**还要在浏览器里硬刷新一次**（Windows/Linux `Ctrl+Shift+R`，macOS `Cmd+Shift+R`）。不刷新可能看到"半加载"的样子：页面出来了但**没有样式**，或少了新加的东西。

**机制**（不是玄学，值得知道）：

`window.__ModuleLoader__` 把每个插件的 `factory(require)` 结果**记忆化在 `loadCache` 里**，所以**工厂体一个页面会话只跑一次**。而 CSS 注入正是写在工厂闭包里的 —— 无论本插件还是 `dsh-status-rotator`（后者的 `<style>` 在它 `client.js` 的设置面板代码旁创建并挂到 `<head>`）。

于是：**如果工厂物化那一轮样式没进到 `<head>`，之后不会再补**，直到整页真正重载。看着就像"插件坏了"，其实只是产物没重新执行。

> 2026-09-26 实际踩到：`dsh-status-rotator` 的设置页在重启后显示为无样式（按钮是原生小方块、没有间距），再重启一次就好了 —— 全程与本插件的代码无关。当时先怀疑是新装的插件干扰，方向是错的：**先想到"工厂不再执行"这条机制，比排查插件冲突快得多。**

## 设置文件在哪

```
<DSH_HOME>/worklog/settings.json
```
- `<DSH_HOME>` 是 `$DSH_HOME`，没设时是 `~/.dsh`（与 DSH 本体、`settings.yaml`
  同一个约定）。
- **不放在包目录里**：profile 用 `link:` 把包链到一份 checkout 上，包目录通常就是
  一个 git 工作树 —— 往那儿写会弄脏工作树，还容易被误提交；而升级/重装会替换那个
  目录，恰恰是最不希望丢设置的时候。
- 文件是**可选**的：不存在就是"全用默认值"，第一次保存时创建。
- 文件坏掉（JSON 不合法、不是对象）**永不致命**：报出来，退回内置默认，技能照常挂载。
- 手写进去的、插件不认识的键**会被保留**，不会被一次保存悄悄删掉。

### 优先级

```
设置文件（设置页写的）  >  行配置（cordis.patch.yml 的 config）  >  内置默认
```

设置文件必须压过行配置，否则设置页是死的：本包的补丁行把
`guidelinesEnabled` / `guidelinesLanguage` / `skillDir` / `guidelinesDir`
都写死了，行配置永远有值。

## 环境变量

| 变量 | 作用 |
|---|---|
| `DSH_HOME` | DSH 用户目录；未设时为 `~/.dsh`。决定设置文件的默认位置。 |
| `DSH_WORKLOG_SETTINGS` | 直接指定设置文件的**完整路径**，压过 `DSH_HOME`。给便携安装与测试用。 |
| `DSH_WORKLOG_TRACE` | 诊断日志的目标文件。见 `lib/index.js` 顶部注释。 |

## 已知配置键

插件行配置（`cordis.patch.yml` 的 `config`）与设置文件共用同一套键名。
`skillFile` 只能在行配置里给：设置页没有它的控件，保存也不会把它删掉。
表里其余每个键在设置页上都有控件 —— `verbose` / `modelInvocable` / `userInvocable`
在「其他」页，另外四个在「技能」页。

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `skillDir` | string | `skills/project-work-log` | 工作记录技能目录。相对路径从**包根**算起，绝对路径原样使用。 |
| `skillFile` | string | `SKILL.md` | 技能目录里的指令文件名。仅行配置。 |
| `modelInvocable` | boolean | `true` | 是否允许模型自动调用这两个技能。 |
| `userInvocable` | boolean | `true` | 是否允许用户手动调用。 |
| `verbose` | boolean | `false` | 装载时多打一行日志。 |
| `guidelinesEnabled` | boolean | `true` | 是否登记 `reliability-guidelines` 技能。 |
| `guidelinesDir` | string | `skills/reliability-guidelines` | 准则技能目录，解析规则同 `skillDir`。 |
| `guidelinesLanguage` | `'zh'` / `'en'` | `'zh'` | 只影响准则那一份技能；`project-work-log` 本身固定是中文。 |

设置页还收集过三个**项目侧默认值** —— `container`（`work_log`）、
`lessons`（`lessons`）、`mode`（`full`）。**它们仍然存在设置文件里、路由也仍然回报
它们，但设置页不再为它们提供控件** —— 见下一节。

## 项目侧默认值：存着，但不提供控件

`container` / `lessons` / `mode` 是**项目级**设置：它们描述的是某个项目自己的
`<容器>/.config.json`，那个文件由 `journal.py` 读、由 `journal.py config` 改。

- **仍然存着**：三个键留在插件设置文件里（`knownSettingsKeys()` 里仍然校验它们），
  路由的 `GET` / `POST` 响应里也仍然有 `projectDefaults`，带
  `appliedByPlugin: false`，与 `effective`（插件真正读的键）分开报告。
  这样任何读这层接口的人都无法把它们当成"插件会这么做"。
- **不再提供控件**：设置页既不显示它们，也不把它们发回服务端（请求体只有七个
  装载键）。路由按补丁合并（`sanitizeSettings` 把请求体并进磁盘上的文档），
  所以文件里已有的值原样保留，一次保存不会抹掉它们。
- **为什么不提供**：它们归项目的 `.config.json` 管。让插件设置页也能改同一件事，
  正是上面那条「两个设置面不许管同一件事」要避免的。曾经的做法是显示它们、
  标一句「插件不读」—— 那仍然是把项目级的东西摆在插件设置页上。
- **已经在跑的项目不会被追溯改变**：`journal.py` 始终只读项目文件，不去问插件。

设置页底部留了一句兼容性说明，把这些键指到 `journal.py config`，但页面上没有
任何控件与它们对应（`tests/audit-client-runtime.mjs` 按结构断言这一点）。

## 设置页

设置页是客户端半边 `lib/client.js`，挂在设置面板的 `settings.section` 槽上
（id `dsh-worklog`，导航名走 locale）。它不能碰文件系统，所以通过节点半边起的
一个 HTTP 端点读写设置文件：

```
GET  /plugins/dsh-worklog/settings.json   读；回报三组东西：`settings`（磁盘上的文档）、
                                          `effective`（插件真正读取的键）、
                                          `projectDefaults`（只存不读的项目默认值，
                                          带 `appliedByPlugin: false`；页面**忽略**它）
POST /plugins/dsh-worklog/settings.json   写；整份表单，逐字段校验，返回同一组字段
```

### 两个分页：技能 / 其他

界面用宿主的 `SegmentedTabs`（`@deepseek-ai/dsh-client-ui-primitives`）分两页，
默认停在「技能」。它**只渲染标签栏，面板由页面自己给** —— 所以面板那边自己带
`role="tabpanel"`、自己的 `id`，以及指回对应标签页的 `aria-labelledby`；
一次只渲染被选中的那一个。

| 分页 | 装什么 |
|---|---|
| **技能** | `guidelinesEnabled`（开关）、`guidelinesLanguage`（中文 / English 分段控件），以及收在「路径」折叠区里的 `skillDir` 与 `guidelinesDir` |
| **其他** | `verbose`、`modelInvocable`、`userInvocable` —— 三个开关 |

后三个键一直由 `effectiveSettings()` 读取，但在此之前设置页**没有任何控件**能设它们；
现在每个都配了一句说明。

「路径」用 `DisclosureRow`（默认收起）：两个技能目录是装载参数，只是不常改。
收起时那两行**不在 DOM 里**（该组件只在 `open` 时渲染 children）。

中文文案是完整的；英文词典也已就位（键集与中文一致，
`tests/audit-client.mjs` 会核对）。

## 为什么「改完需重启」是硬限制

Cordis 官方**是支持不重启改配置的** —— 见 `docs/cordis-tutorial/05-config.zh.md`
的 volatile 字段：给 `Config` schema 里的字段加 `.volatile()`，用 `.get()` 读，
字段变化会更新引用并发 `loader/volatile-update`，**不重新挂载插件**。

**但那条路要求插件导出 `Config` schema**，而树外插件解析不到 `@deepseek-ai/schemastery`
（它在应用的 asar 里）。`tests/run.mjs` 专门断言本插件**不导出 `Config`**，
所以界面上那句「改完需重启 DSH」不是偷懒，是这条边界的结果。

`dsh-status-rotator` 面对同一限制，做法也一样：客户端半边 + 自建 HTTP 路由，
而不是 schema。

## 界面样式走宿主的设计令牌

`lib/client.js` 只用 `--dsw-alias-*` 令牌着色。**令牌名写错不会报错** —— `var()`
会静默回落到 fallback，页面照样渲染，但已经不再跟主题与暗色模式走。所以
`tests/audit-client-tokens.mjs` 把用到的每个令牌对照宿主自己的词表（206 个名字，
由 `tests/tools/refresh-tokens.mjs` 从 DSH 检出里抽取），并拒绝带硬编码 fallback 的写法。
