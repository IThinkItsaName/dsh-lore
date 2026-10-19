# 发版清单

[`PUBLISHING.md`](PUBLISHING.md) 讲的是**仓库怎么建**（一次性）。这份讲的是**每次发版要过哪些检查点**。

> **为什么单独一份**：本包有两处"源 / 副本"关系，方向不同，而且**走错方向会静默删东西**。
> 靠记性做这件事，迟早会有一次"改了、测了、忘了同步就发了"。

## 两处源 / 副本，以及各自的固定方向

| 什么 | 源（改这里） | 副本（工具写，别手改） | 同步命令 |
|---|---|---|---|
| 技能 + 工具箱（vendored） | `publish/project-work-log/skills/project-work-log/`（独立仓库） | `publish/worklog/skills/project-work-log/` | `npm run sync:skill` |
| 附带技能（默认关着） | `.pi/skills/client-require-whitelist/` | `publish/worklog/skills/client-require-whitelist/` | `python ../../.pi/tools/_package.py` |
| 测试 harness | `publish/worklog/tests/` | `publish/worklog/tests/` | 无（只此一份） |

> **`project-work-log` 已独立成库**（2026-10-19）：自己的 git 史、自己的发布节奏、自己的
> `skill-only/` + `dist/` 与路径/变异门禁。本仓库只保留 vendored 副本，由
> `tools/sync-skill.mjs` 单向同步；`--check` 发现漂移就失败（独立仓库不在本机时 SKIP）。
> 只拿到本仓库的人跑不了技能侧的发版；要改技能得先有独立仓库。
>
> 附带技能 `client-require-whitelist` 仍住在工作区 `.pi/skills/`，同步脚本
> `.pi/tools/_package.py`（2026-10-19 从技能目录搬出，不再随技能发布）。

**两条纪律**：

1. **改实现只改源。** 直接改 vendored 副本不会被发现——直到下一次同步把它覆盖掉。
2. **已经在副本侧改了，就去源仓库改回来，别手工 copy。** `sync-skill.mjs` 只做单向覆盖：
   副本里多出来的改动会在下一次同步时**静默消失**。

> **同步是原子的**：`sync-skill.mjs` 先写临时文件再 rename，避免目标被读时截断。

## 发版前的检查点

全部在 `publish/worklog/` 下执行。

```bash
# 1. vendored 技能与独立仓库一致（0 漂移；独立仓库不在时 SKIP）
npm run sync:skill:check

# 2. client-require-whitelist 与插件文件在位
python ../../.pi/tools/_package.py --check

# 3. 插件门禁：17 个 harness
npm run test:plugin

# 4. 端到端审计：清单、导出、注册表契约、加载路径
npm run audit

# 5. 技能自测（断言条数故意不写在这里 —— 它每加一条断言就过期一次）
npm test
```

技能层的变异驱动（`reverse-verify.py`）、`skill-only/` + `dist/` 与三份只读语料的基线
都随独立仓库搬走了；改技能时在那里跑，不在本仓库的发版链里。

技能层的变异驱动（`reverse-verify.py`）、`skill-only/` + `dist/`、三份只读语料的基线，
以及"本容器自己也要干净"的 `check --lint` 检查，都随独立仓库搬走了 —— 那些是技能层的
发布检查，改技能时在 `publish/project-work-log/` 里跑；本仓库的发版链只到上面第 5 步。

## 版本号与 CHANGELOG

1. **CHANGELOG 先写**：把 `## [未发布]` 下的内容整理进 `## [x.y.z] - YYYY-MM-DD`，
   顶部再留一个空的 `## [未发布]`。
   - 每条写**为什么**，不只写改了什么。理由比改动更容易过期，也更有用。
   - **只追加，不改写历史条目。**
   - 撤回过的结论**留着并写明撤回**，不要抹掉——否则读者会重新踩一次。
2. **版本号**：`package.json` 的 `version` 去掉前缀就是 tag —— `v<x.y.z>` ↔ `<x.y.z>`。
   **本文不写死版本号**（写了就会过期，这里从前停在 `v0.5.0` 三个版本没人动）；
   `tests/audit-versions.mjs` 会核对 README / PUBLISHING 里的安装示例与 `package.json` 一致，先同步改再跑门禁。
   （技能仓库有自己的版本号与 CHANGELOG；本包不发技能版本。）

## 打 tag 与推送

> **推送与打 tag 需要用户显式点头。** 默认不发。
> 本机的沙箱历史上禁止程序创建管道（`git push` 走 SSH 会 `Win32 error 5`），
> 是否需要提权取决于当时的文件策略。

```bash
V=x.y.z                      # 用 package.json 里那个版本，别照抄这一行
git tag -a "v$V" -m "v$V"
git push origin main
git push origin "v$V"
```

**tag 一旦推送就不要移动**——别人可能已经钉着它安装。
发错了的正确做法是**再发一个版本**，不是改 tag。

## 发完之后

- [ ] `git tag --sort=-v:refname | head -4` 确认新 tag 在列表里且指向预期提交
- [ ] 从 tag 拉一份到临时目录，跑一次 `npm run test:plugin` 与 `npm test`：
      **验证发布物本身完整**，而不是验证工作树
- [ ] 若插件已装进某个 profile，重载页面看配置卡片与技能是否正常；宿主半边由 HMR 在
      profile 重组时替换（没有 HMR 的宿主才需要重启 DSH）
- [ ] 在 `work_log/` 写一条记录：这一版发了什么、验证到什么程度、有没有未覆盖的
- [ ] **破坏性改动（改名 / 行名变更）必须在发布说明里写清迁移步骤**：profile 的
      `dependencies` 与 `dsh.profile.bundles` **两处**换成新名 → `pnpm install` → **重启 DSH**。
      不改就**根本加载不上**（比"卡片消失"更彻底）。0.7.0 的改名是第一个例子（`work_log/worklog/07-rename-070/0063`）

## 常见坑（都真发生过）

| 现象 | 原因 |
|---|---|
| `sync-skill.mjs --check` 报漂移 | 独立技能仓库更新了但没同步，**或者改了 vendored 副本**（后者更危险：同步会覆盖它） |
| vendored 副本里混进 `__pycache__` | 跑过自测（`npm test` 或 `skills/.../\_selftest.py`）。`sync-skill.mjs` 会忽略它，但 npm 打包会带上（实测过一次 398 KB 的陈旧 `.pyc`）；`git clean -fdx skills/` 即可 |
| 门禁在开发者机器上变红 | harness 读了真实设置文件或真实记忆根；夹具必须写到系统临时目录 |
| 页面改了没效果 | 客户端半边由 `__ModuleLoader__` 按页会话缓存，**要重载页面**：浏览器 `Ctrl+Shift+R`；**DSH 桌面版没有刷新快捷键/菜单项**（打包版只挂了 F12）——用 F12 → Console `location.reload()`，或重启应用。细则见 `SETTINGS.md`「装/改之后要重载页面」 |
| 配置卡片整页不出现 | 客户端按字段集认领 namespace，两种原因：① `FORM_FIELDS` 与 `lib/index.js` 的 `Config` **漂移**（`tests/audit-client-runtime.mjs` 会对账这两边）；② **改了 `Config` 的字段集而宿主还跑着旧插件**——运行中的宿主发着旧 schema，于是认领失败。本机 HMR 会在下一次 profile 重组时替换插件；没有 HMR 的宿主只能重启。两种都要硬刷新页面。从 2026-09-30 起不再静默：那一行确实是我们的时，浏览器控制台会点名缺哪个字段（`work_log/worklog/07-rename-070/0062`） |
| 在卡片上改完没写进 profile | 那个宿主没有 `configEditor`（headless）—— 配置退回插件自己的 `settings.json`，而**没有程序写它**，那时应手工编辑；卡片底部的「设置位置」一行会说明当前是哪一种 |
| 卡片改了没反应 | 2026-10-19 起**没有装载期读的设置了**，11 个键都是现读（见 `SETTINGS.md`「改完需重启到底是不是硬限制」）——所以"重启试试"不该再是排查手段。先确认保存成功（卡片显示「已保存」且 profile patch 里有值）；技能目录相关再看宿主日志里 provider 的读失败；仍不对就当缺陷查。0.8.1 之前的 `memoryDir` 是历史缺陷：patch 写了、插件读不到，宿主日志里会有一条 `ignoring unsupported config keys: memoryDir` |
| 版本审计失败 | `package.json` 的 `version` 与 tag / CHANGELOG 不一致；三处要同时改 |
| 改了包名却忘了 profile | 新名**加载不上**；`dependencies` 与 `dsh.profile.bundles` **两处**都要改，
再 `pnpm install`、重启 DSH。`npm run audit` 会直接点名缺哪个链接（`work_log/worklog/07-rename-070/0063`） |
| 新加的随包技能当场查不到 | 插件自带技能在**插件装载时**登记；新目录要等插件重新装载（没有 HMR 的宿主 = 重启；放进 `<DSH_HOME>/skills/` 的则会被文件系统 provider 活查发现） |
