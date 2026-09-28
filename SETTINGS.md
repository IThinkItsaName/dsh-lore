# 插件设置

本文记录 **DSH 插件半边**（`lib/`）的设置面：设置存在哪、谁能编辑、什么时候生效。

项目的配置（`<容器>/.config.json`）不在这里 —— 它是 `journal.py` 的事，
见 [docs/settings-spec.md](docs/settings-spec.md) 第一节。

## 两个设置面不许管同一件事

| 设置面 | 管什么 | 存哪 | 改完何时生效 |
|---|---|---|---|
| **本插件的配置卡片**（插件页 → 本 bundle 的页面） | 插件自身的装载行为 | **profile 的 `cordis.patch.yml`**；没有 `configEditor` 的宿主退回 `<DSH_HOME>/worklog/settings.json` | 见「改完需重启到底是不是硬限制」 |
| **项目配置文件** | `journal.py` 的行为 | `<容器>/.config.json` | 立即生效 |

**这条规则是硬边界，没有例外。** 卡片曾经收集三个项目侧默认值
（`container` / `lessons` / `mode`）并给它们标上「插件不读」；那一组已经整个撤掉 ——
见下面的「项目侧默认值：不提供控件」。文档里仍留着这三个键的名字，是因为
`projectDefaults()` 仍会解析它们（供别处引用），只是**没有任何界面再展示或提交它们**。

## 配置存在哪：profile patch 是**正式位置**（2026-09-29 起）

插件导出 `Config`（**11 个**字段，全部 `.volatile()`），所以设置归**宿主**管：

| 宿主 | 存哪 | 谁写 |
|---|---|---|
| 有 `configEditor`（桌面 profile 都是） | `<profile>/cordis.patch.yml` 里我们这个条目的 `config:` 块 | **官方通道**：客户端 `ctx.configForms` 的 `set`/`unset` → 宿主校验后由 `dsh-config-editor` 落盘 |
| 没有 `configEditor`（headless、测试夹具） | `<DSH_HOME>/worklog/settings.json` | **没有程序写它** —— 手工编辑（headless 的正当路径，不是待删的兼容层） |

**为什么换**：profile patch 是 DSH 里所有设置面共用的一处。换过去之后别的界面也认识这些
字段，写回也由宿主校验（`configEditor` 拿 `Config` 校验一次 mutation 才落盘），
而不是靠插件自己写文件。

**一次性迁移**：升上来的第一版会在 `apply()` 时发现旧 `settings.json` 有值、而 profile 里没写我们这些键，
就用官方通道把它写进 patch，然后把旧文件改名成 `settings.json.migrated` 留档。四条规矩：

1. 旧文件不存在或为空 → 什么都不做；
2. **profile 已经写了我们的键 → 不覆盖**（显式配置永远优先），只把旧文件归档；
3. 写 profile 失败 → **文件原样留着**并告警（半迁移比不迁移更糟：下一次挂载会两个副本都不敢信）；
4. 没有可寻址的条目 → 告警并继续读旧文件。

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
| 本插件 | **保持零 `<style>` 注入** —— 这是能做的最干净的一种防御，因为不注入就没有可被误认领的东西 |

**不要**在本插件里扫描并"修复"别人的标签：那要写死别的插件的 id，脆弱且越界。

## 设置文件在哪（headless 那条路）

```
<DSH_HOME>/worklog/settings.json
```
- `<DSH_HOME>` 是 `$DSH_HOME`，没设时是 `~/.dsh`（与 DSH 本体、`settings.yaml`
  同一个约定）。
- **不放在包目录里**：profile 用 `link:` 把包链到一份 checkout 上，包目录通常就是
  一个 git 工作树 —— 往那儿写会弄脏工作树，还容易被误提交；而升级/重装会替换那个
  目录，恰恰是最不希望丢设置的时候。
- 文件是**可选**的：不存在就是"全用 row config 与内置默认值"。
- 文件坏掉（JSON 不合法、不是对象）**永不致命**：报出来（状态接口的 `error`、宿主日志一条 warn），
  退回 row config 与内置默认，技能照常挂载。
- 手写进去的、插件不认识的键会被忽略但**不会被删** —— 插件现在不写这个文件了。

### 优先级

**有 `configEditor` 时，分层是宿主的**：profile patch（用户层）> 本包的行配置 > 内置默认，
由 DSH 自己解析完交给 `apply()`。

**没有 `configEditor` 时**（headless），插件自己合：

```
设置文件  >  行配置（cordis.patch.yml 的 config）  >  内置默认
```

设置文件必须压过行配置，否则那个文件是死的：本包的补丁行把
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

`Config` 声明了 **11 个**字段，全部 `.volatile()`。卡片上有控件的是其中 **10 个**：
`skillFile` 只能由行配置给（卡片没有它的控件，所以任何界面都不会把它改掉或删掉）。

| 键 | 类型 | 默认 | 卡片上 | 说明 |
|---|---|---|---|---|
| `skillDir` | string | `skills/project-work-log` | 「技能 › 路径」 | 工作记录技能目录。相对路径从**包根**算起，绝对路径原样使用。 |
| `skillFile` | string | `SKILL.md` | **无控件** | 技能目录里的指令文件名。仅行配置。 |
| `modelInvocable` | boolean | `true` | 「高级」 | 是否允许模型自动调用这两个技能。 |
| `userInvocable` | boolean | `true` | 「高级」 | 是否允许用户手动调用。 |
| `verbose` | boolean | `false` | 「高级」 | 装载时多打一行日志。 |
| `guidelinesEnabled` | boolean | `true` | 「技能」 | 是否登记 `reliability-guidelines` 技能。 |
| `guidelinesDir` | string | `skills/reliability-guidelines` | 「技能 › 路径」 | 准则技能目录，解析规则同 `skillDir`。 |
| `guidelinesLanguage` | `'zh'` / `'en'` | `'zh'` | 「技能」 | 只影响准则那一份技能；`project-work-log` 本身固定是中文。 |
| `memoryEnabled` | boolean | `true` | 「记忆」 | 全局记忆总开关：关闭后索引不注入、`worklog_memory` 工具也不注册。 |
| `memoryInjectIndex` | boolean | `true` | 「记忆」 | 是否默认把索引段注入提示词（用时现读）。 |
| `memoryPersonalSearchable` | boolean | `false` | 「记忆」 | 个人目录是否可被检索（用时现读）。 |

## 项目侧默认值：不提供控件

`container` / `lessons` / `mode` 是**项目级**设置：它们描述的是某个项目自己的
`<容器>/.config.json`，那个文件由 `journal.py` 读、由 `journal.py config` 改。

- **不在 `Config` 里**：它们不是插件配置，所以既不进 profile patch，也不出现在卡片上。
- **不再有控件**：卡片既不显示它们，也不提交它们。
  `projectDefaults()` 仍然会解析这三个键（带 `appliedByPlugin: false`），
  任何读到它的代码都无法把它们当成"插件会这么做"。
- **为什么不提供**：它们归项目的 `.config.json` 管。让插件配置卡片也能改同一件事，
  正是上面那条「两个设置面不许管同一件事」要避免的。曾经的做法是显示它们、
  标一句「插件不读」—— 那仍然是把项目级的东西摆在插件设置页上。
- **已经在跑的项目不会被追溯改变**：`journal.py` 始终只读项目文件，不去问插件。

卡片底部留了一句兼容性说明，把这些键指到 `journal.py config`，但页面上**没有任何控件**
与它们对应（`tests/audit-client-runtime.mjs` 按结构断言这一点：断言的是"没有名为容器 /
经验目录 / 精细度的控件"，不是"页面文本里没有这些字"—— 兼容性说明里本来就有）。

## 配置界面：**本 bundle 自己那一页**上的一张卡片

界面是客户端半边 `lib/client.js`。它注册进 **`plugins.bundle.config`**，`key` = **本包的包名**
（`dsh-worklog`）—— 插件管理页就是这么寻址的：`configured: ledger.bundles.has(openPkg.name)`，
渲染在 bundle 页的**描述与行列表之间**。同工作区的 `dsh-ds-balance` 与官方那支
`@deepseek-ai/dsh-experimental-voice-input-bundle` 都挂在这里。

它**不是**设置页的分区（那属于产品设置），也**不是** `plugins.item` —— 后者是插件页的
**官方那一组**，槽位说明原文就是 *"One **official** plugin the Plugins page lists in its
**Official group**"*，它的 catalog 还写着 *"a bundle's configuration belongs in
`plugins.bundle.config` or `plugins.row.config` instead"*。**我们是 bundle，所以挂在这里。**
（第一版挂错了 `plugins.item`，于是它出现在官方那一组里；见 `work_log/0043`。）

### 认领自己的 namespace：按字段集，不按 id

宿主给每个带 `.volatile()` 字段的插件投影一份"设置命名空间"，id 是
`entry.options.id` —— 那是**部署相关**的：本机是 `include:dsh-worklog`，换个挂法就变。
所以卡片不写死 id，而是**按字段集认领**：看这一行投影出来的 **`value`**（那份生效配置）
是否同时带齐我们那 11 个名字（`lib/client.js` 的 `FORM_FIELDS`）。

> **为什么是 `value` 而不是 `schema`（2026-09-29 在真实宿主上量出来的）**：宿主发的 `schema`
> 是 schemastery 的**重水合信封** `{uid, refs}`，字段名躺在 `refs[<uid>].dict` 里 ——
> **顶层根本没有 `properties`**。第一版读的就是 `schema.properties`，于是判据在真机上恒为假、
> 卡片一次都没注册过（而当时的 harness 照着自己的假设造假行，所以 151 条断言全绿）。
> 详见 `work_log/0042`。

- 认领不到 → **什么都不注册**（宁可这一页不出现，也不要在别人的命名空间上挂一张会写错地方的卡片）。
- 命名空间消失 → 卡片撤下；再出现 → 重新挂上。
- **`FORM_FIELDS` 与 `Config` 会漂移**：少一个字段就永远认领不到、卡片静默消失。
  所以 `tests/audit-client-runtime.mjs` 从 `lib/index.js` 的源码里重新解析一遍
  `Config` 的 `.volatile()` 字段，与 `FORM_FIELDS` 对账。

### 写回：`ctx.configForms`

卡片通过槽位注册的 `inject` 面拿到宿主给的表单控制器（`getSnapshot` / `subscribe` /
`set` / `unset`），**不自己发 HTTP**。三条后果值得知道：

1. **显示的是宿主的真实值**：开关读的是生效值；路径框读的是**用户层**
   （profile patch）里的值，留空即"用下层的值"，右侧出现「已覆盖 / 恢复默认」。
2. **被拒绝的写入会说出来**：`set`/`unset` 返回"宿主有没有接受"，被拒（含 revision
   冲突）时卡片显示失败原因，并**把输入框退回真实存着的值** —— 不留"看着保存成功了"的假象。
3. **路径框是敲完才写**：输入过程只更新草稿，失焦或回车才提交。逐字符写会让宿主把
   patch 文件原子重写几十遍（以及编辑器的备份文件）。

### 三个页签

界面用宿主的 `SegmentedTabs`（`@deepseek-ai/dsh-client-ui-primitives`）分三页，
默认停在「技能」。它**只渲染标签栏，面板由页面自己给** —— 所以面板那边自己带
`role="tabpanel"`、自己的 `id`，以及指回对应标签页的 `aria-labelledby`；
一次只渲染被选中的那一个。

| 页签 | 装什么 |
|---|---|
| **技能** | `guidelinesEnabled`（开关）、`guidelinesLanguage`（中文 / English 分段控件），以及收在「路径」折叠区里的 `skillDir` 与 `guidelinesDir` |
| **记忆** | `memoryEnabled`、`memoryInjectIndex`、`memoryPersonalSearchable` 三个开关；再收一个「当前状态」折叠区（只读，见下） |
| **高级** | `verbose`、`modelInvocable`、`userInvocable` —— 三个开关 |

「路径」与「当前状态」用 `DisclosureRow`（默认收起）：前者是装载参数（不常改），
后者不属于这一页的语义但很有用（"我到底登记没登记"）。收起时内容**不在渲染树里**。

中文文案是完整的；英文词典也已就位（键集与中文一致，
`tests/audit-client.mjs` 会核对）。

### 只读状态端点

卡片上唯一还会发 HTTP 的地方，是「记忆」页的只读状态块：

```
GET /plugins/dsh-worklog/status.json   → { source, path, memory, error }
```

- `source` / `path`：设置**落在哪**（profile patch，还是插件自己的文件）。卡片把它显示出来 ——
  官方通道下用户否则只能猜该改哪个文件。
- `memory`：记忆系统的规模（已登记工作区 / 待收 / 索引字数）。读不到就是 `null`，
  卡片显示"未读取"而**不是 0**："0 个工作区"和"没读"是两个不同的断言。
- `error`：只在文件那条路上有意义（文件坏了会在这里报出来）。
- **没有写动词**：`GET`/`HEAD` 以外一律 405（`allow: GET, HEAD`）。配置不再走 HTTP ——
  留着 POST 就是给同一个事实源开第二个写入口，那正是本项目按缺陷处理的那类东西。

这个端点**是可选的**：没有 web server 的宿主照样挂载技能；状态读不到时卡片照常可编辑，
只在状态块里说"读不到"。

## 「改完需重启」到底是不是硬限制

**本节早先有一个错说法**：原来说「树外插件解析不到 `@deepseek-ai/schemastery`，
所以导不出 `Config`，所以改完必须重启」。**那是推断，不是实测，而且已被反证** ——
正确的做法是把它声明成 peerDependency（见 `work_log/0016`、`0021`、`0022`）。
反过来，本文件更早还写过「完全没有 `Config` 导出」，同样作废。

现在的实测状态：

| 事实 | 状态 |
|---|---|
| `Config` 被宿主认成 `schema`（字段带 `x-cordis.volatile: true`） | **已验证**（活体 `Config.listConfigs{name:"dsh-worklog"}`） |
| 值能被官方通道写进 profile patch 并读回 | **已验证**（`apply()` 的选项、卡片显示的值同源） |
| 我们的选项**改完即时生效** | **没有**。这些选项是**装载期**读的（技能挂哪个目录、guidelines 开不开、记忆总开关），所以界面按页标明"需重启" |

**两条读法要分清**：

| 类 | 例 | 改完 |
|---|---|---|
| 装载期读的（`apply()` 里读一次就交给注册表） | `skillDir`、`guidelinesEnabled`、`verbose`、`modelInvocable`、`userInvocable`、`memoryEnabled` | 需重启 DSH |
| 用时现读的（每次工具调用现读） | `memoryInjectIndex`、`memoryPersonalSearchable` | 即时生效 |

**未兑现的待办**：要真正做到"全部即时"，需要监听 `loader/volatile-update` 并重建
provider（当前 `mount()` 丢掉了 `registerProvider` 的 disposer，重建前必须先收集，
否则同层重名会让注册表抛错）。台账里记着这件事，**在那之前本文不声称任何一项即时生效**。

## 界面样式走宿主的设计令牌

`lib/client.js` 只用 `--dsw-alias-*` 令牌着色。**令牌名写错不会报错** —— `var()`
会静默回落到 fallback，页面照样渲染，但已经不再跟主题与暗色模式走。所以
`tests/audit-client-tokens.mjs` 把用到的每个令牌对照宿主自己的词表（206 个名字，
由 `tests/tools/refresh-tokens.mjs` 从 DSH 检出里抽取），并拒绝带硬编码 fallback 的写法。
