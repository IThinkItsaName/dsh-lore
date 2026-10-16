# 发版清单

[`PUBLISHING.md`](PUBLISHING.md) 讲的是**仓库怎么建**（一次性）。这份讲的是**每次发版要过哪些检查点**。

> **为什么单独一份**：本包有三处"源 / 副本"关系，方向不同，而且**走错方向会静默删东西**。
> 靠记性做这件事，迟早会有一次"改了、测了、忘了同步就发了"。

## 三处源 / 副本，以及各自的固定方向

| 什么 | 源（改这里） | 副本（工具写，别手改） | 同步命令 |
|---|---|---|---|
| 技能 + 工具箱 | `.pi/skills/project-work-log/` | `publish/worklog/skills/project-work-log/` | `python scripts/_package.py` |
| 附带技能（默认关着） | `.pi/skills/client-require-whitelist/` | `publish/worklog/skills/client-require-whitelist/` | 同上（每个技能一项，见 `SKILL_SOURCES`） |
| 测试 harness | `publish/worklog/tests/` | `publish/worklog/tests/` | 同上（2026-10-15 整理后只此一份，故是恒等映射） |
| 纯文档变体 | `skill-only/`（手写源） | `dist/skill-only/`（构建产物） | `node tools/build-skill-only.mjs` |

> **技能那两处源与同步脚本本身都不在本仓库。** `publish/worklog/` 里没有 `scripts/_package.py`，
> 也没有 `.pi/skills/`——技能源都在**工作区**里（本仓库只是它们的下游副本）。
> 所以只拿到本仓库的人跑不了第 1、2 行的同步命令；要发版得先有那份工作区。
>
> 例外是**测试 harness**（第 3 行）：2026-10-15 起它就只有这一份，住在本仓库里
> （源与副本同一处，`_package.py --check` 仍会校验它没缺文件）。在此之前它曾在工作区
> `logs/tests/` 与仓库 `tests/` 各存一份（24 个文件逐字节相同）。

**三条纪律**：

1. **改实现只改源。** 直接改副本不会被发现——直到下一次同步把它覆盖掉。
   本仓库真发生过：整块 `MEMORY_*` 常量写在了副本里，一次常规同步就会**静默删除**。
2. **已经在副本侧改了，就反着搬回来，别手工 copy。** `_package.py --from-repo` 把副本内容
   搬回源（只搬 `SKILL_SOURCES` 清单里的文件，源里多出来的工具不动）。2026-10-16 一次
   真实踩坑：先在副本侧改了 7 个文件、`--check` 立刻报漂移，当时没有这条路，只好手工
   `Copy-Item` —— 手工能成是因为记得住；记不住的那一刻，下一次不带参数跑 `_package.py`
   就把那些改动**静默回退**了。
3. **`dist/` 故意不进 `package.json` 的 `files`**，但**进 git**：它是"直接拷进另一个
   harness 就能用"的现成包。所以它要跟着源一起提交，并由 `--check` 看着。

> **写入是原子的**（2026-10-16 修）：`_package.py` 先写同目录临时文件、再 `os.replace()`
> 换上去。原来用 `shutil.copy2`，它会**先截断目标**再拷内容——目标只要被别的进程 momentary
> 锁住（本工作区的活动 profile 通过联接指向 `publish/worklog`，随时有人在读），
> `[WinError 32]` 一抛，目标就已经是 0 字节了。实测发生过一次：`SKILL.md` 归零、脚本崩在中间。
> 同时 `--check` 现在把"镜像清单里的文件是 0 字节"单独报成漂移 —— 两侧**都**空时内容比较会
> 判"一致"，那正是这次事故里最危险的一幕（内容没了却全绿）。

## 发版前的检查点

全部在 `publish/worklog/` 下执行。

```bash
# 1. 源与副本一致（0 漂移），并且两个镜像都对
python ../../.pi/skills/project-work-log/scripts/_package.py --check

# 2. 插件门禁：16 个 harness
npm run test:plugin

# 3. 端到端审计：清单、导出、注册表契约、加载路径
npm run audit

# 4. 技能自测（断言条数故意不写在这里 —— 它每加一条断言就过期一次）
npm test

# 5. 纯文档变体没漂移
npm run test:skill-only

# 6. 变异驱动（本机约 25 分钟，故意不进 npm 脚本）
python -B tests/reverse-verify.py --root ../../logs/fixtures
```

**判读只有一条**：结尾那行
`101 条变异：N 条如期变红 / M 条没变红 / C 条相跑崩 / K 条替换源对不上或打偏`，
要 **M = 0、C = 0、K = 0**。每个计数含义不同，"不红"有三种，别混：

| 样子 | 含义 | 怎么办 |
|---|---|---|
| `PASS … [N 条断言变红]` | 变异被抓住了 | 正常 |
| `PASS … [N 条断言变红，其中含读不到的文件（…）]` | 同上，且**红的原因正是**变异让某个本该写出来的文件没写出来（断言里读到缺文件） | 正常；括号里那句是"红在哪"的定位信息 |
| `MISS … [替换源不唯一：0 次]` | 那条变异**在空转**：目标代码早被改写过，`replace` 找不到 —— 不是"测试没抓到 bug"，而是"这条检查什么都没测" | 更新它的 old/new 到现文本 |
| `MISTARGET …` | **变异打偏**：`replace()` 命中了同形代码的**另一处**，你要改的函数一点没动。`count(old)==1` **拦不住这种**（它只证明"这段文本唯一"，不证明"它在你以为的那个函数里"） | 把 old 加长到**唯一能命中目标**的上下文（含上一行或注释） |
| `CRASH … [没有任何断言被检验]` | 相在**记下任何断言之前**就崩了（多半是相自己的夹具代码抛异常），所以这条变异没有任何证据 | 先 `--keep` 读变异体代码；再确认不是基线问题；**再查"变异是不是打断了某条断言的前置条件"**（见下面第三次升级那条） |
| `MISS … [期望「…」没变红；红了 0 条]` | 剩下的可能：测试真有缺口，或 new 与 old 效果等价（行为其实没变） | 看 `--only` 单跑，再读自测里是否真有那条断言 |

> **2026-10-14 升级**：`MISTARGET` 与 `CRASH` 这两类是这一轮新加的，因为此前的驱动
> **会把"打偏"报成"没变红"**（实测：`inbox 用文本模式直接写` 的替换命中了 JSON 状态写入器
> 里的同形代码，inbox 的原子写没动，却显示"没变红"，看着像自测缺口）。
> 判据是"施加替换后，old 左右各 6 行的窗口**必须逐行与原来不同**" —— 只看局部，不看整份文件：
> old 在原文出现多次时整份文件必然变，那种判据没有用。详见作者侧 `work_log/0081`。

> **2026-10-14 第二次升级（`collect 改写工作区的清单` 那条从 `CRASH` 变成 `PASS`）**：
> 它此前的"相跑崩"是**误判**。崩点确实是 `fx/memory/mem/feedback/wsA.md`（`FileNotFoundError`），
> 但原因不是"夹具自己有问题"，而是：Python 在**进入函数体之前**就把实参算完，自测里有断言写成
> `ok("…" in read(p), "…", read(p))` —— 变异让 `collect` 不再写镜像，`read(p)` 就在**调用点**
> 抛出，异常发生在"记下这条断言"之前，于是整条相被掀掉。之前我据此断定"与变异无关"，是因为
> **只在自测里做了对照**（怎么改自测都崩）；换成"未变异的干净副本跑同一相"才是对的对照
> （实测：干净副本 208 条断言全过），一试就看出崩溃是变异造成的。
> 修法两处：驱动把 `read` 包成"缺文件返回哨兵文本"（断言自然变红，相继续跑完），
> 加上一层兜异常的 `ok`；判定只认**期望的那条断言红了**且**相没崩**。
> 教训：**别用"改一改自测还崩不崩"来证明变异无关 —— 要用"未变异副本跑同一相"。**

> **2026-10-14 第三次升级（剩下的 3 条 `CRASH` 全部变成 `PASS`）**：
> 同一个病根的第二张脸，这次长在**自测自己**身上 —— 断言的**前置条件**被打断了。
> 例：自测先 `items = os.listdir(inbox)`，再 `items[0]`；变异让条目没落成，`items[0]`
> 就在**调用点**抛 `IndexError`，同样发生在"记下断言"之前，整相照崩。同族的还有
> `open(缺文件)`、`json.loads(读空的配置)`、`subprocess.run(cwd=不存在)`、`write(<父目录不存在>)`。
> 修法：自测里给这些求值加安全包装（缺文件返回空、空列表不取下标、目录不在就跳过），
> **判据一条没放松** —— 坏消息照旧变红，只是不再掀掉整相。
> 你要是又看到 `CRASH`，先按"变异是不是打断了某条断言的前置条件"去查，
> 再用 `--keep` 读变异体、拿**未变异的干净副本**跑同一相做对照。

**三份只读语料**（跨工作区，不许改）：

```bash
python skills/project-work-log/scripts/journal.py check --strict --quiet "<每个语料根>"
```

基线（**数字变了就是回归**）：`comfy` `0/0/0`；`dsh_from_github` `7/0/130`；
`embeding try` 下七条分别为 `_shared 1/0/0`、`1_minimind_main 0/0/9`、
`2_multi_attention 2/0/10`、`3_param_block 0/0/11`、`4_block_math 1/0/0`、
`5_diffusion 0/0/3`、`6_block_wiring 1/0/3`。

> **2026-10-15 复跑的两处上调，都是语料自己长了，不是回归**：
> `2_multi_attention` 的 error `0 → 2` —— `work_log/2026-10-09-过程债清理-评测确定性防覆盖闸与跨线经验.md`
> 里两条死链写的是 `../_lessons/2026-10-0{7,8}-….md`：`_lessons/` 在**上一层**（`embeding try/_lessons`），
> 这个容器自己下面没有，少写了一级；`5_diffusion` 的 info `2 → 3` ——
> `work_log/2026-09-30-阶段复盘-R1到A2b.md` 缺验证类小节。两份记录都写在 09-29 那次记基线之后。
> 语料是只读的（跨工作区不许改），所以这里跟着上调基线；**此后数字再变才是回归**。

> **三份语料的绝对路径**（2026-09-29 补写：原先没记，`embeding try` 一挪窝就得满盘找）：
> `D:\Program Files (x86)\comfy`、`D:\Program Files (x86)\dsh_from_github`、
> `D:\Program Files (x86)\project_of_agent\embeding try`。
> 最后一份**挪过位置**（曾经直接躺在 `Program Files (x86)` 下），按那几个特征子目录名
> （`1_minimind_main` 等）找最快；它下面另有 `_lessons`、`7_jev_decision` 两个**基线没记**的子目录，
> 属于语料后长的部分，不影响上面那七条基线。

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
2. **版本号**：`package.json` 的 `version` 去掉前缀就是 tag —— `v<x.y.z>` ↔ `<x.y.z>`。
   **本文不写死版本号**（写了就会过期，这里从前停在 `v0.5.0` 三个版本没人动）；
   `tests/audit-versions.mjs` 会核对 README / PUBLISHING 里的安装示例与 `package.json` 一致，先同步改再跑门禁。
3. **`skill-only/README.md` 的版本说明**若有，一并跟上。

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
- [ ] 若插件已装进某个 profile，硬刷新页面（必要时重启 DSH）看配置卡片与技能是否正常
- [ ] 在 `work_log/` 写一条记录：这一版发了什么、验证到什么程度、有没有未覆盖的
- [ ] **破坏性改动（改名 / 行名变更）必须在发布说明里写清迁移步骤**：profile 的
      `dependencies` 与 `dsh.profile.bundles` **两处**换成新名 → `pnpm install` → **重启 DSH**。
      不改就**根本加载不上**（比"卡片消失"更彻底）。0.7.0 的改名是第一个例子（`work_log/worklog/07-rename-070/0063`）

## 常见坑（都真发生过）

| 现象 | 原因 |
|---|---|
| `_package.py --check` 报漂移 | 改了源没同步，**或者改了副本**（后者更危险：同步会覆盖它） |
| `_package.py --check` 只报 `__pycache__` | 刚在**副本**目录里跑过自测（`npm test` 或 `skills/.../\_selftest.py`）。它是派生文件、不该随包发（实测过一次：包里躺着一个 398 KB 的陈旧 `.pyc`），同步一下即可清掉 |
| 门禁在开发者机器上变红 | harness 读了真实设置文件或真实记忆根；夹具必须写到系统临时目录 |
| 页面改了没效果 | 客户端半边由 `__ModuleLoader__` 按页会话缓存，**要重载页面**：浏览器 `Ctrl+Shift+R`；**DSH 桌面版没有刷新快捷键/菜单项**（打包版只挂了 F12）——用 F12 → Console `location.reload()`，或重启应用。细则见 `SETTINGS.md`「装/改之后要重载页面」 |
| 配置卡片整页不出现 | 客户端按字段集认领 namespace，两种原因：① `FORM_FIELDS` 与 `lib/index.js` 的 `Config` **漂移**（`tests/audit-client-runtime.mjs` 会对账这两边）；② **改了 `Config` 但宿主没重启** —— 运行中的宿主还发着旧 schema，于是认领失败。两种都会让卡片**消失**。从 2026-09-30 起不再静默：那一行确实是我们的时，浏览器控制台会点名缺哪个字段（`work_log/worklog/07-rename-070/0062`）。修法：重启 DSH + 硬刷新 |
| 在卡片上改完没写进 profile | 那个宿主没有 `configEditor`（headless）—— 配置退回插件自己的 `settings.json`，而**没有程序写它**，那时应手工编辑；卡片底部的「设置位置」一行会说明当前是哪一种 |
| 卡片改了没反应 | 2026-10-14 起只剩**两个键**是装载期读的：`memoryEnabled`、`verbose`（见 `SETTINGS.md` 的「改完需重启到底是不是硬限制」）—— 改的是这两个就重启 DSH；其余 11 个（含 `memoryDir`）都是现读，**"没反应"不是它们的正常症状**。0.8.1 之前的 `memoryDir` 是第三种情况：桌面 profile 上它写进了 patch、插件却读不到，宿主日志里会有一条 `ignoring unsupported config keys: memoryDir` |
| 版本审计失败 | `package.json` 的 `version` 与 tag / CHANGELOG 不一致；三处要同时改 |
| 改了包名却忘了 profile | 新名**加载不上**；`dependencies` 与 `dsh.profile.bundles` **两处**都要改，
再 `pnpm install`、重启 DSH。`npm run audit` 会直接点名缺哪个链接（`work_log/worklog/07-rename-070/0063`） |
| 新加的随包技能当场查不到 | 插件自带技能在**插件挂载时**注册；新文件要**重启宿主**才登记（放进 `<DSH_HOME>/skills/` 的则会被文件系统 provider 活查发现） |
