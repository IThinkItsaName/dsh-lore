# skill-only —— 无脚本版

`project-work-log` 的**纯文档变体**：只有约定与模板，没有 `journal.py` 工具箱。
给**不能跑脚本**的环境用 —— 纯聊天界面、别人的 agent 平台、临时机器。

> 这不是带工具箱那版的「轻量版」，是**另一件东西**。
> 带脚本那版的可校验性由 `check --strict` / `lint --strict` 机械保证；
> 这一版把同样的约定写成人能执行的规程，**每一道检查都要人亲手做**。
> 保住的是方法论，丢掉的是执行力。

## 内容

```
skill-only/
├── README.md                        ← 本文件（不随技能分发）
└── project-work-log/                ← 这一整个目录才是技能
    ├── SKILL.md
    └── references/
        ├── conventions.md           ← 含「手工操作规程」11 节 + 手工复核清单
        └── templates.md
```

`project-work-log/` 是一个标准 **Agent Skill 目录 bundle**，与主版本的技能同名。
把它整个拷进目标平台的技能搜索路径即可，例如：

| 平台 | 放这里 |
|---|---|
| 通用（agentskills.io 规范） | 该平台的 skills 目录下 `project-work-log/` |
| Claude Code | `~/.claude/skills/project-work-log/` |
| 跟主版本同机、按项目走 | `<项目>/.agents/skills/project-work-log/` |

> ⚠ **不要和主版本同时装**：两者技能名相同（`project-work-log`），
> 同时可见时会有一个被遮蔽，行为取决于平台。按环境选一个。

## 与主版本的差别

| | 主版本（带脚本） | 本版本 |
|---|---|---|
| 文件 | 8 个（含 3 个 Python 脚本） | **3 个** |
| 结构 / 日期 / 死链 / 漏索引 | `check` 机械校验 | **人工复核清单**（`conventions.md` §十一） |
| 内容质量 | `lint` 机械校验 | **人工复核清单** |
| 改文件 | 外科式编辑，保 CRLF，拒写非 UTF-8 | 你自己编辑 |
| 归档 | 一条命令：搬 + 全仓链接重写 + 死链自检 | **9 步手工规程**（`conventions.md` §八） |
| 分析 | `stats` / `topics` / `digest` / `export` | **没有** —— 用你平台自带的搜索 |
| 编号复用风险 | 工具扫全部目录 | 靠复核清单，**归档目录容易漏看**，务必按 §二.1 扫全 |

**一处本版本更强**：人工清单能要求「验证小节里不是『应该没问题』」这类**实质判断**，
而机械校验只能看措辞。机器无法知道写得对不对。

## 生成产物

`dist/skill-only/project-work-log/` 是 `skill-only/project-work-log/` 的构建副本，
供直接拷走。**别手改 `dist/`** —— 它是产物，改动会在下次构建时被覆盖：

```bash
node tools/build-skill-only.mjs            # 构建
node tools/build-skill-only.mjs --check     # 查漂移（有差异退出码 1）
node tools/build-skill-only.mjs --out DIR   # 输出到别处
```

一致性由 `tests/audit-paths.mjs` 把关：文件集固定为三个、**不许出现任何脚本或 CLI 引用**、
必须保留核心概念（容器名、精细度四档、验证小节），且容器名与主版本一致。
