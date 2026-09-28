# 插件设置

本文记录 **DSH 插件半边**（`lib/`）的设置面。它是 `README.md` 之外新增的一份说明，
因为实现里出现了两个必须被写下来的东西：设置文件的位置，以及两个环境变量。

项目的配置（`<容器>/.config.json`）不在这里 —— 它是 `journal.py` 的事，
见 [docs/settings-spec.md](docs/settings-spec.md) 第一节。

## 两个设置面不许管同一件事

| 设置面 | 管什么 | 存哪 | 改完何时生效 |
|---|---|---|---|
| **插件设置页 / 官方配置表单** | 插件自身的装载行为 | **profile 的 `cordis.patch.yml`**（没有 `configEditor` 的宿主退回 `<DSH_HOME>/worklog/settings.json`） | 需重启 DSH |
| **项目配置文件** | `journal.py` 的行为 | `<容器>/.config.json` | 立即生效 |

**这条规则现在是硬边界，没有例外。** 设置页曾经收集三个项目侧默认值
（`container` / `lessons` / `mode`）并给它们标上「插件不读」；那一组已经整个撤掉 ——
见下面的「项目侧默认值：存着，但不提供控件」。文档里仍留着这套键的名字，
是因为节点半边仍然存它们、也仍然在路由里回报它们。


## 设置存在哪：profile patch 是**正式位置**（2026-09-29 起）

插件现在导出 `Config`（10 个字段全带 `.volatile()`），所以设置归**宿主**管：

| 宿主 | 存哪 | 谁写 |
|---|---|---|
| 有 `configEditor`（桌面 profile 都是） | `<profile>/cordis.patch.yml` 里我们这个条目的 `config:` 块 | 官方配置表单、本插件设置页，**都走 `configEditor.edit()`** |
| 没有 `configEditor`（headless、测试夹具） | `<DSH_HOME>/worklog/settings.json` | 本插件设置页自己写（老路径，**保留**：没有 editor 的宿主没别处可放） |

**为什么换**：`profile patch` 是 DSH 里所有设置面共用的一处，换过去之后**别的界面也认识这些字段**
（官方 Plugins 卡片直接渲染），而不是只有本插件那一页知道。

**一次性迁移**：升上来的第一版会在 `apply()` 时发现旧 `settings.json` 有值、而 profile 里没写我们这些键，
就用官方通道把它写进 patch，然后把旧文件改名成 `settings.json.migrated` 留档。四条规矩：

1. 旧文件不存在或为空 → 什么都不做；
2. **profile 已经写了我们的键 → 不覆盖**（显式配置永远优先），只把旧文件归档；
3. 写 profile 失败 → **文件原样留着**并告警（半迁移比不迁移更糟：下一次挂载会两个副本都不敢信）；
4. 没有可寻址的条目 → 告警并继续读旧文件。

**改完仍需重启**：这些是**装载期**读的选项（技能挂哪个目录、guidelines 开不开、verbose 等），
所以官方表单与本插件页面都只是"把值写对"，生效在下次挂载 —— 两个界面都这么写，没有哪个在偷偷承诺即时生效。

## 装/改之后要**硬刷新页面**

改完客户端半边、重启过宿主之后，**还要在浏览器里硬刷新一次**（Windows/Linux `Ctrl+Shift+R`，macOS `Cmd+Shift+R`）。不刷新可能看到"半加载"的样子：页面出来了但**没有样式**，或少了新加的东西。

**机制**：CSS 注入写在工厂闭包里 —— 无论本插件还是 `dsh-status-rotator`（后者的 `<style>` 在它 `client.js` 的设置面板代码旁创建并挂到 `<head>`）。工厂体在**物化时**执行一次，如果那一轮样式没进到 `<head>`，之后不会再补，直到整页真正重载。

> 2026-09-26 实际踩到：`dsh-status-rotator` 的设置页在重启后显示为无样式（按钮是原生小方块、没有间距），再重启一次就好了。当时先怀疑是新装的插件干扰，方向是错的。

## 已知的宿主缺陷：样式会被别的插件"认领"走（2026-09-26）

**这不是本插件的 bug，但本插件会触发它** —— 记在这里，因为下次它再犯时，从零查会花很久。

### 机制

宿主的客户端模块系统在**工厂体跑完之后**认领样式（`packages/client/modules/src/client/system.ts`）：

```js
const exports = registered.factory(this.makeRequire(ownerId, edges))   // :305 工厂体
const record = { id, exports, styles: claimStyles(ownerId), edges }    // :306 然后认领

const claimStyles = (id) => {                                          // :71
  for (const el of document.querySelectorAll('style:not([data-plugin])'))
    el.setAttribute('data-plugin', id)     // ← 认领【当下所有】无主 <style>
}
```

而模块 **revision 变化**时会清掉"属于它"的样式（`:432-434`，改 `lib/client.js` 就会触发）：

```js
this.invalidate(row.id, row.rev)
removeOwnedStyles(row.id)                  // 删掉 data-plugin === row.id 的 <style>
```

**于是时间顺序决定归属**：谁的模块后物化，谁就认领当时所有无主样式。本插件**不注入任何 `<style>`**，所以当它物化时，它会把别人**尚未标记**的样式认到自己名下 —— 之后本插件每次改动都会把那些样式删掉。

### 为什么偏偏是本插件触发

`dsh-status-rotator` 用 `createElement("style")` 建了 4 个样式标签（它的 `client.js` L1645 / L1712 / L3108 / **L4183**），**全文没有 `data-plugin`**。其中 L4183 那个在**设置面板组件里**创建 —— 首次打开设置页它才诞生，那时两个模块都已物化，**所以它一直是无主的**，谁下次物化就归谁。

### 症状

另一个插件的设置页**失去样式**（按钮变原生小方块、没有间距），再重启宿主一次可能就好 —— 表现为间歇性。

### 责任与修法

| 角色 | 该做什么 |
|---|---|
| `dsh-status-rotator` | 建 `<style>` 后加一行 `el.setAttribute('data-plugin', 'dsh-status-rotator')`。宿主注释写着"预标记的标签会带上它"，说明**打标记是受支持的做法** |
| 宿主 | `claimStyles` 的时间窗太宽：应只认领**工厂体运行期间**新增的标签，而不是"当下所有无主" |
| 本插件 | **保持零 `<style>` 注入** —— 这是能做的最干净的防御，因为不注入就没有可被误认领的东西 |

**不要**在本插件里扫描并"修复"别人的标签：那要写死别的插件的 id，脆弱且越界。

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
| `DSH_HOME` | DSH 用户目录；未设时为 `~/.dsh`。决定设置文件与全局记忆的默认位置。 |
| `DSH_WORKLOG_SETTINGS` | 直接指定设置文件的**完整路径**，压过 `DSH_HOME`。给便携安装与测试用。 |
| `DSH_WORKLOG_MEMORY` | 直接指定**全局记忆根目录**的完整路径，压过 `DSH_HOME`。同样给便携安装与测试用 —— 测试必须能指向临时目录，否则跑一次就会动到用户真实的记忆库。 |
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

## 「改完需重启」到底是不是硬限制

**先纠正本文早先的一个错说法。** 这里原来说「树外插件解析不到 `@deepseek-ai/schemastery`，
所以导不出 `Config`，所以改完必须重启」。**那是推断，不是实测，而且已被反证。**

实测（活体 `Config` inspect）：

| 插件 | Config 状态 |
|---|---|
| `dsh-ds-balance` | **`schema`** —— 完整的 JSON Schema，字段带 `x-cordis.volatile: true` |
| `dsh-status-rotator` | `absent` |
| `dsh-worklog`（我们） | `absent` |

- `require.resolve('@deepseek-ai/schemastery')` 从 profile 与插件目录**都解析不到** ——
  **连 `dsh-ds-balance` 自己也解析不到**。
- 但它把 `@deepseek-ai/schemastery` 声明为 **peerDependency**，且运行时可用。

**结论**：`absent` 是**「没写」而不是「写不了」**。DSH 的 Loader 自己处理这些内建
specifier，不走 Node 的解析。所以「导不出 `Config`」不是硬限制。

**官方那条不重启的路**（`docs/cordis-tutorial/05-config.zh.md`）：给 `Config` schema
的字段加 `.volatile()`，值活在 `apply()` 收到的引用里，变更由 `loader/volatile-update`
事件告知，写回走 `ctx.settings.mutate(id, ops)`，**不重新挂载插件**。
`dsh-ds-balance` 的 `config-service` 一句话总结：**「不缓存 —— 用户改设置要立刻生效」**。

### 我们现在的两种做法

| 做法 | 适用 | 代价 |
|---|---|---|
| **用时现读**：`apply()` 不缓存，需要时再读设置文件 | **任何"读了就用"的开关**（如记忆的三个默认项） | 零。`readStoredSettings()` 本来就是现读，只要别把它缓存进 `apply()` |
| **schema + `.volatile()`** | 必须在 `apply()` 时交给注册表的项（如技能目录） | 要导出 `Config`、要实测那条路通不通 |

**所以「改完需重启」只对第二类成立**，而它是否真的需要重启，取决于 Loader 会不会
重跑 `apply()` —— 这一点**尚未实测**。在那之前，界面按项标明重启要求，**不再整页一句**。

**尚未兑现的待办**：我打算用一个一次性探针插件实测「树外插件能否导出 `Config`
并被认成 `schema`」。计划里记着这件事；**在它验完之前，本文不再声称任何一边是硬限制。**

`dsh-status-rotator` 走的是第三条路：客户端半边 + 自建 HTTP 路由，**不导出 schema**。
那是可行的（它就在跑），只是拿不到 volatile 的即时生效。

## 界面样式走宿主的设计令牌

`lib/client.js` 只用 `--dsw-alias-*` 令牌着色。**令牌名写错不会报错** —— `var()`
会静默回落到 fallback，页面照样渲染，但已经不再跟主题与暗色模式走。所以
`tests/audit-client-tokens.mjs` 把用到的每个令牌对照宿主自己的词表（206 个名字，
由 `tests/tools/refresh-tokens.mjs` 从 DSH 检出里抽取），并拒绝带硬编码 fallback 的写法。
