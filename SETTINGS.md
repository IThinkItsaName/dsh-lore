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

唯一的例外是 `mode` 的"默认档"，靠语义而不是靠两处都读来避免冲突：
设置页里的 `mode` 只是"**新项目**初始化的默认档"，`journal.py` **始终只读项目文件**。

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

设置页还收集三个**项目侧默认值** —— `container`（`work_log`）、
`lessons`（`lessons`）、`mode`（`full`）。它们存在同一个设置文件里，但插件**不读**：
它们是"新项目该叫什么、该用哪档"的初始值，由项目初始化写进
`<容器>/.config.json`，之后以项目文件为准。**已经在跑的项目不会被追溯改变**，
`journal.py` 也不会去问插件。

## 设置页

设置页是客户端半边 `lib/client.js`，挂在设置面板的 `settings.section` 槽上
（id `dsh-worklog`，导航名走 locale）。它不能碰文件系统，所以通过节点半边起的
一个 HTTP 端点读写设置文件：

```
GET  /plugins/dsh-worklog/settings.json   读；回报三组东西：`settings`（磁盘上的文档）、
                                          `effective`（插件真正读取的键）、
                                          `projectDefaults`（只存不读的项目默认值，
                                          带 `appliedByPlugin: false`）
POST /plugins/dsh-worklog/settings.json   写；整份表单，逐字段校验，返回同一组字段
```

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
