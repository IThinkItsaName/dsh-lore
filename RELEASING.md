# 发版清单

[`PUBLISHING.md`](PUBLISHING.md) 讲的是**仓库怎么建**（一次性）。这份讲的是**每次发版要过哪些检查点**。

> **为什么单独一份**：本包有三处"源 / 副本"关系，方向不同，而且**走错方向会静默删东西**。
> 靠记性做这件事，迟早会有一次"改了、测了、忘了同步就发了"。

## 三处源 / 副本，以及各自的固定方向

| 什么 | 源（改这里） | 副本（工具写，别手改） | 同步命令 |
|---|---|---|---|
| 技能 + 工具箱 | `.pi/skills/project-work-log/` | `publish/worklog/skills/project-work-log/` | `python scripts/_package.py` |
| 测试 harness | `logs/tests/` | `publish/worklog/tests/` | 同上（一次跑完两处） |
| 纯文档变体 | `skill-only/`（手写源） | `dist/skill-only/`（构建产物） | `node tools/build-skill-only.mjs` |

**两条纪律**：

1. **改实现只改源。** 直接改副本不会被发现——直到下一次同步把它覆盖掉。
   本仓库真发生过：整块 `MEMORY_*` 常量写在了副本里，一次常规同步就会**静默删除**。
2. **`dist/` 故意不进 `package.json` 的 `files`**，但**进 git**：它是"直接拷进另一个
   harness 就能用"的现成包。所以它要跟着源一起提交，并由 `--check` 看着。

## 发版前的检查点

全部在 `publish/worklog/` 下执行。

```bash
# 1. 源与副本一致（0 漂移），并且两个镜像都对
python ../../.pi/skills/project-work-log/scripts/_package.py --check

# 2. 插件门禁：13 个 harness
npm run test:plugin

# 3. 端到端审计：清单、导出、注册表契约、加载路径
npm run audit

# 4. 技能自测（464 条断言）
npm test

# 5. 纯文档变体没漂移
npm run test:skill-only

# 6. 变异驱动（约 10 分钟，故意不进 npm 脚本）
python ../logs/tests/reverse-verify.py --root ../../logs/fixtures
```

**三份只读语料**（跨工作区，不许改）：

```bash
python skills/project-work-log/scripts/journal.py check --strict --quiet "<每个语料根>"
```

基线（**数字变了就是回归**）：`comfy` `0/0/0`；`dsh_from_github` `7/0/130`；
`embeding try` 下六条分别为 `_shared 1/0/0`、`1_minimind_main 0/0/9`、
`2_multi_attention 0/0/10`、`3_param_block 0/0/11`、`4_block_math 1/0/0`、
`5_diffusion 0/0/2`、`6_block_wiring 1/0/3`。

**本容器自己也要干净**（在装了这套东西的工作区里）：

```bash
python skills/project-work-log/scripts/journal.py check --strict --lint "<该工作区根>"
```

> **两道门禁要一起跑，所以用 `--lint`。** `check` 管结构（章节、死链、编号），
> `lint` 管内容质量（结论有没有可核对的信息、有没有空小节）。**两道门是分开的**，
> 只跑一道，另一道的错就会一直攒着——那个工作区自己的容器就攒了 **7 条** lint ERROR
> 无人看见，因为这份清单原先只写了 `check`。
>
> **为什么不用"让 check 默认带上 lint"来解决**：九个真实语料实测，那会让今天全绿的项目
> 当场变红（`dsh_from_github` 7 → **94** 条、`3_param_block` 0 → **30** 条）。合并是**选项**，
> 检查点自己加；`check` 单独跑时会留一行提示，免得下一个人又以为"绿灯就是检查完了"。
>
> 加这一行的代价：**记录写得含糊会让发版变红**。这正是想要的——否则"结论：已完成"
> 这种句子会一直混过去，而它恰好是本项目记录里最没用的那种。

## 版本号与 CHANGELOG

1. **CHANGELOG 先写**：把 `## [未发布]` 下的内容整理进 `## [x.y.z] - YYYY-MM-DD`，
   顶部再留一个空的 `## [未发布]`。
   - 每条写**为什么**，不只写改了什么。理由比改动更容易过期，也更有用。
   - **只追加，不改写历史条目。**
   - 撤回过的结论**留着并写明撤回**，不要抹掉——否则读者会重新踩一次。
2. **版本号**：`package.json` 的 `version` 与 tag 一致（`v0.5.0` ↔ `0.5.0`）。
   `tests/audit-versions.mjs` 会检查这件事，所以先同步改再跑门禁。
3. **`skill-only/README.md` 的版本说明**若有，一并跟上。

## 打 tag 与推送

> **推送与打 tag 需要用户显式点头。** 默认不发。
> 本机的沙箱历史上禁止程序创建管道（`git push` 走 SSH 会 `Win32 error 5`），
> 是否需要提权取决于当时的文件策略。

```bash
git tag -a v0.5.0 -m "v0.5.0"
git push origin main
git push origin v0.5.0
```

**tag 一旦推送就不要移动**——别人可能已经钉着它安装。
发错了的正确做法是**再发一个版本**，不是改 tag。

## 发完之后

- [ ] `git tag --sort=-v:refname | head -4` 确认新 tag 在列表里且指向预期提交
- [ ] 从 tag 拉一份到临时目录，跑一次 `npm run test:plugin` 与 `npm test`：
      **验证发布物本身完整**，而不是验证工作树
- [ ] 若插件已装进某个 profile，硬刷新页面（必要时重启 DSH）看设置页与技能是否正常
- [ ] 在 `work_log/` 写一条记录：这一版发了什么、验证到什么程度、有没有未覆盖的

## 常见坑（都真发生过）

| 现象 | 原因 |
|---|---|
| `_package.py --check` 报漂移 | 改了源没同步，**或者改了副本**（后者更危险：同步会覆盖它） |
| 门禁在开发者机器上变红 | harness 读了真实设置文件或真实记忆根；夹具必须写到系统临时目录 |
| 页面改了没效果 | 客户端半边由 `__ModuleLoader__` 按页会话缓存，**要硬刷新**（`Ctrl+Shift+R`） |
| 设置页改了没反应 | 那个键是**装载期**读的（见 `SETTINGS.md` 的「改完需重启」）；或该字段只在一处声明却没被读 |
| 版本审计失败 | `package.json` 的 `version` 与 tag / CHANGELOG 不一致；三处要同时改 |
