# dsh-lore

**给 AI 的长期工作记忆。** 把项目里发生过什么、为什么这么做、留下了什么可复用经验，做成一套
可读、可查、可校验的文档体系；换会话、换 agent，甚至接手的 agent **没有这个技能**，也能看懂并继续。

一句话：**过程留证据，索引管导航，经验可复用。**

## 它解决什么问题

一个需要长期维护的项目，最怕的不是代码丢，而是**上下文丢**：

- 三个月后没人记得某个决定为什么这么定；
- 换一个会话/agent，接手者要从头翻聊天记录；
- 踩过的坑换个 agent 再踩一遍；
- 记录越写越多，最后没人找得到"现在做到哪了"。

dsh-lore 把这些问题收进一个容器：

| 层 | 位置 | 职责 |
|---|---|---|
| **技能层** | `work_log/` | 过程记录 + 索引台账 + 经验手册 + `journal.py` 工具箱（纯 Python 标准库，**不需要 DSH**） |
| **记忆层** | 所有工作区之外（默认 `~/dsh-lore-memory`） | 跨工作区的事实：来源分档、索引、收敛、信箱 |
| **插件层** | DSH profile | 技能注册、记忆注入、`worklog_memory` 工具、配置卡片 |

三层可以只用一层；不限编程——软件、研究、写作、运营都能用。

> **技能层已独立成库**（2026-10-19）：`project-work-log` 有自己的仓库与发布节奏；
> 本包保留一份 **vendored 副本**（`skills/project-work-log/`）供插件运行时使用，
> 由 `tools/sync-skill.mjs --check` 守漂移。pi / 其它 Agent Skills 场景请去独立仓库
> （`publish/project-work-log/`，**尚未发布**），不要从本包拿技能层。

> **它不是什么**：不是变更日志（工作区整理、取证、环境变动都记，`变更集` 只是可选字段）；
> 不是任务管理器（待办只是滚动清单）；不是插件专属（技能层可以独立跑）。
> 为什么做、七条不变量与已知缺口，见 [`docs/why.md`](docs/why.md)。

## 快速开始

### DSH 里

```bash
# 装插件：注册技能、注入记忆、提供 worklog_memory 与设置卡片，并登记进 profile 的 bundles
dsh plugin --profile <profile> add dsh-lore@v0.9.5

# 卸插件：依赖、bundles 条目、node_modules 一起清掉
dsh plugin --profile <profile> remove dsh-lore
```

> **桌面端用户**在插件页装/卸：Electron 托管的 profile 会拒绝 CLI 操作
> （`profile "desktop" is managed exclusively by the Electron application`）。
> 另外**不要**用 `dsh plugin … install <本地目录>`：pnpm 会为本地目录建 junction，卸载时删不掉，
> 下一次换装报 `ERR_PNPM_EPERM`。详见 [PUBLISHING.md](PUBLISHING.md) §7。

然后在项目里让 agent「建工作日志 / 留个记录」，或手动跑：

```bash
ROOT=.   # 项目根；下面命令都接受 [ROOT] 或 --root

python <skill>/scripts/journal.py new --title "标题" --insert
python <skill>/scripts/journal.py brief                 # 一屏：状态 + 待办 + 近期记录
python <skill>/scripts/journal.py check --strict --lint # 结构 + 内容，两道门禁
```

> `<skill>` 是安装后的技能目录（例如 `~/.dsh/skills/project-work-log`）。
> 不知道装到哪时，先看 `~/.dsh/skills/` 或工作区的 `.dsh/skills/`。

### 只拿技能层（pi / 任意 Agent Skills）

技能层已拆到独立仓库 **`project-work-log`**（本工作区 `publish/project-work-log/`，
**尚未发布**）：pi 安装、`skill-only/` 无脚本变体、路径与变异门禁都在那边。
本包不再提供 pi 安装入口，也不再声明 `pi` 包元数据；DSH 用户装本插件即可（技能已随包带上）。

> 自带技能的 DSH 包必须打开 `skill-filesystem`；本包已在 [`cordis.patch.yml`](cordis.patch.yml) 里处理。

## 日常怎么用

| 你想做的事 | 用什么 |
|---|---|
| 接手一个项目，先看坐标 | `journal.py brief` |
| 看最近几篇各自做到哪 | `journal.py snapshot --entries 12` |
| 找旧结论 | `journal.py search "关键词"` → `show <篇号>` |
| 开一篇新记录 | `journal.py new --title "…" --insert` |
| 收尾：改状态 / 勾待办 / 抽经验 | `status --set`、`todo`、`lesson add` |
| 归档一阶段 / 索引瘦身 | `archive`、`index compact` |
| 把教训带到别的项目 | `memory publish` → `memory collect`（DSH 里也可用 `worklog_memory`） |
| 定期整理 | `journal.py check --strict --lint`；每月看一次 `_inbox.md` 与 `lessons/` |

DSH 插件还提供：

- **`worklog_memory` 工具**：检索全局记忆、收发信箱、列会话。它只处理**工作区之外**的那一层；
  `work_log/` 台账仍然用 `journal.py` 和普通文件工具，插件不替代它们。
- **记忆注入**：经验层资源提示常驻（英文，与系统提示其余部分一致；含“该记就记”的写入提示）；
  记忆索引进可缓存前缀；未读信箱只在有内容时尾注入。
- **配置卡片**：技能开关、记忆开关与目录、诊断日志等；每个字段的归属与生效时机见
  [`SETTINGS.md`](SETTINGS.md)。

## 仓库结构

```
skills/project-work-log/       # vendored 技能副本（源在独立仓库 project-work-log）
skills/client-require-whitelist/ # 随包技能：客户端 require 白名单检查（默认关着）
lib/index.js                   # 宿主半边：技能 provider、记忆注入、worklog_memory、状态端点
lib/client.js                  # 浏览器半边：本 bundle 那一页的配置卡片
cordis.patch.yml               # DSH bundle 补丁（启用 skill-filesystem、插入本包行）
tools/sync-skill.mjs           # 从独立技能仓库同步 vendored 副本（--check 门禁）
tests/                         # 17 支插件门禁（注册表契约、清单、技能同步、设置、客户端运行时…）
docs/                          # 设计权威（why / worklog / settings / memory / goals）
SETTINGS.md · RELEASING.md · PUBLISHING.md · CHANGELOG.md
```

## 独立性与设计边界

- **技能层不知道 DSH 存在。** 它可以在没有 DSH 的环境单独跑；插件只是把它带进 DSH 的适配器。
- **写给模型看的工具只有一个 `worklog_memory`。** 台账操作留在 CLI/文件层；这样没有插件的
  agent 仍然能读记录，插件不会变成"没有它就打不开台账"的第二套系统。
- **规则只有一个定义处。** 写入、索引、`lint` 都在 `journal.py`；插件不重写格式，只做薄包装
  （例如 `send` 起 `journal.py inbox put`）。
- **`reliability-guidelines` 已拆为独立技能**（2026-10-18，`0.9.3` 起）。本包不再随包提供它，
  也不再提供 `guidelinesEnabled` / `guidelinesLanguage` / `guidelinesDir` 三个设置。
- **技能层已独立成库**（2026-10-19）：`skill-only/` 无脚本变体、pi 安装面、路径/变异门禁都在
  `project-work-log` 仓库；本包只保留 vendored 副本，不再维护这些内容。

完整的分层与依赖方向见 [`docs/plugin-spec.md`](docs/plugin-spec.md)。

## 验证

```bash
npm test                 # 技能层自测（vendored 副本：journal.py 全部命令 + 非编程场景 + 数据安全）
npm run test:plugin      # 17 支插件门禁（含技能副本与独立仓库的同步检查）
npm run audit            # 发版前审计（注册表 / 清单 / ESM / 安装面）
npm run sync:skill:check # 只查 vendored 副本是否与独立技能仓库一致
```

仓库门禁全绿不等于你的项目记录合格：项目自己的容器还要跑
`journal.py check --strict --lint`。门禁的判据、已知误报与渐进原则见
[`references/commands.md`](skills/project-work-log/references/commands.md)。

## 文档

- 设计权威：[`docs/`](docs/README.md) · 为什么做：[`docs/why.md`](docs/why.md)
- 记录约定：[`references/conventions.md`](skills/project-work-log/references/conventions.md)
- 命令与门禁：[`references/commands.md`](skills/project-work-log/references/commands.md)
- 全局记忆：[`docs/memory-spec.md`](docs/memory-spec.md)
- 设置：[`SETTINGS.md`](SETTINGS.md) · 发版：[`RELEASING.md`](RELEASING.md)
- 版本变化：[`CHANGELOG.md`](CHANGELOG.md)

## 版本与状态

本仓库（<https://github.com/IThinkItsaName/dsh-lore>）当前版本是 **0.9.5**（`package.json`）；
安装示例钉的是当前版本。发版与推送步骤见 [`RELEASING.md`](RELEASING.md)。

> 本仓库的约定、文档与脚本由 **DeepSeek Flash 系列模型**整理生成（未经人工逐条校验），
> 使用时请自行甄别。曾用名 `dsh-worklog`（2026-09-30 改名）；环境变量仍是 `DSH_WORKLOG_*`，
> 技能名 `project-work-log`、工具名 `worklog_memory` 未变。

MIT，见 [LICENSE](LICENSE)。
