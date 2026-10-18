# dsh-lore

**给 AI 的长期工作记忆。** 三块能力，依赖单向向下：

| 层 | 是什么 |
|---|---|
| **技能层** | 过程记录 + 索引台账 + 经验手册 + `journal.py` 工具箱（纯 Python 标准库，**不需要 DSH**） |
| **记忆层** | 跨工作区的事实，存在所有工作区之外（默认 `~/dsh-lore-memory`）：来源分档、索引、收敛、信箱 |
| **插件层** | DSH 集成：记忆注入、`worklog_memory` 工具、技能注册、配置卡片 |

三层可以只用一层；不限编程（软件、研究、写作、运营都能用）。术语与验证口径见
[`references/conventions.md`](skills/project-work-log/references/conventions.md)。

> **2026-10-18 起，`reliability-guidelines` 已拆为独立技能**，不再随本包分发，也不再由插件
> 注册或提供 `guidelinesEnabled` / `guidelinesLanguage` / `guidelinesDir` 设置。本包仍带
> `project-work-log` 与 `client-require-whitelist` 两个技能。

> 本仓库的约定、文档与脚本由 **DeepSeek Flash 系列模型**整理生成（未经人工逐条校验），使用时请自行甄别。
> 曾用名 `dsh-worklog`（2026-09-30 改名）；环境变量仍是 `DSH_WORKLOG_*`，技能名 `project-work-log`、
> 工具名 `worklog_memory` 未变。

## 安装

```bash
# DSH 插件（带记忆注入、工具与配置卡片）
dsh plugin --profile <profile> add dsh-lore@v0.9.3

# pi / 任意 Agent Skills harness（只拿技能层）
pi install git:github.com/IThinkItsaName/dsh-lore@v0.9.3
```

> 本地目录装出来的是**链接**，源目录一移动就废 —— 长期用请钉 tag。自带技能的包必须打开
> `skill-filesystem`，本包已在 `cordis.patch.yml` 里处理。

## 用法

代理按「留记录 / 建工作日志 / 总结 / 复盘 / 归档」这类意图自动加载技能，也可以直接跑脚本：

```bash
python <skill>/scripts/journal.py brief                 # 当前坐标（替代整读索引）
python <skill>/scripts/journal.py new --title "…" --insert
python <skill>/scripts/journal.py check --strict --lint # 结构 + 内容，两道门禁
python <skill>/scripts/journal.py memory add --source wl/0042 "…"   # 跨工作区记忆
```

DSH 里另有 `worklog_memory` 工具：检索记忆、收发信箱（同工作区直投 `work_log/.lore-inbox/`，
跨工作区走共享信箱）。

## 文档

- 命令与约定：[`references/commands.md`](skills/project-work-log/references/commands.md)
- 设计权威：[`docs/`](docs/README.md) · 记忆层：[`docs/memory-spec.md`](docs/memory-spec.md)
- 设置：[`SETTINGS.md`](SETTINGS.md) · 发版：[`RELEASING.md`](RELEASING.md) · 版本：[`CHANGELOG.md`](CHANGELOG.md)

MIT，见 [LICENSE](LICENSE)。
