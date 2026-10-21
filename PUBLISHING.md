# 如何发布到 GitHub

本仓库是**独立仓库**（工作区本身不是 git 仓库），可直接 `git init` 后推送；也可先推到私有仓库验证再转公开。

## 0. 发之前先确认三件事

| 项 | 说明 |
|---|---|
| **许可证** | MIT，版权人已署为 `IThinkItsaName`（要改就编辑 `LICENSE`）。若不想用 MIT，换掉整个文件即可。 |
| **仓库名 / OWNER** | 已按 `IThinkItsaName/dsh-lore` 写进下文；若改名，先全局替换这两个值。 |
| **`package.json` 的 `name`** | 现在是 `dsh-lore`（DSH 插件；pi 安装面已随技能层拆到独立仓库）。**如果只通过本地路径安装，名字无所谓**；若要 `npm publish`，先去 npm 查是否重名。 |

## 1. 本地初始化并首次提交

```bash
cd <工作区>/publish/worklog

git init -b main
git add .
git status                 # 确认没有 __pycache__ / *.pyc 混进来
git commit -m "feat: dsh-lore plugin (skill provider + global memory + settings card)"
```

## 2. 在 GitHub 建仓

**方式 A · 网页**（无需额外工具）

1. 打开 <https://github.com/new>
2. 填仓库名 `dsh-lore`，选 Public / Private
3. **不要**勾选 "Add a README / .gitignore / license"（本地已有，避免冲突）
4. Create repository

**方式 B · GitHub CLI**（本机当前**未安装 `gh`**，需先装）

```bash
gh auth login
gh repo create worklog --public --source=. --remote=origin --push
```

## 3. 推送

```bash
git remote add origin https://github.com/IThinkItsaName/dsh-lore.git
git branch -M main
git push -u origin main
```

## 4. 打 tag（推荐）

安装示例可以固定到 tag/commit，用户就不会被上游改动影响：

```bash
git tag -a v0.9.4 -m "dsh-lore v0.9.4"
git push origin v0.9.4
```

之后别人可以这样装（npm 发布后；`<profile>` 换成对方自己的 profile，桌面端的 `desktop` 是例外，见 §7）：

```bash
dsh plugin --profile <profile> add dsh-lore@v0.9.4
```

> ⚠ **打 tag 之前先改 `package.json` 的 `version`，并确认它等于 tag 去掉 `v`。**
> 这两处曾经长期不一致（`v0.1.1` 的包里写着 `0.1.0`，`v0.3.0` 的包里写着 `0.2.0`），
> 因为下面的流程只写了"整理 CHANGELOG"，**没写"提升版本号"**。现在补上了。

## 5. 以后怎么更新

**技能层的唯一源是独立仓库 `publish/project-work-log/`**（自己的 git 史、自己的发布节奏）；
本仓库里的 `skills/project-work-log/` 是 **vendored 副本**，用 `tools/sync-skill.mjs` 同步。
不要直接改副本 —— 下一次同步会覆盖；要改技能就改独立仓库，再同步。

`lib/index.js`、`cordis.patch.yml`、`package.json`、`README.md`、`CHANGELOG.md` 是**插件自有文件**，
直接在 `publish/worklog/` 里改（它们不参与同步）。

改完技能后：

```bash
# 1) 从独立技能仓库同步 vendored 副本（会打印新增/修改/删除）
cd <工作区>/publish/worklog
npm run sync:skill

# 2) 只检查有没有漂移（有漂移退出码 1；独立仓库缺席时 SKIP/0）
npm run sync:skill:check

# 3) 有面向用户的变更时，先追加 CHANGELOG（见下）
#    把 CHANGELOG.md 里 `## [未发布]` 的内容整理成 `## [x.y.z] - YYYY-MM-DD`
#    同时：改 package.json 的 version，并补上 CHANGELOG 底部的版本链接

# 4) 提交并推送
git add -A && git commit -m "chore: sync skill from its repo" && git push
git tag -a v0.9.4 -m "v0.9.4" && git push origin v0.9.4   # 有行为变化时
```

> 不要在 `publish/worklog/skills/` 里直接改脚本——下次同步会被覆盖。改源，再同步。
> `client-require-whitelist` 仍住在工作区 `.pi/skills/`，由 `.pi/tools/_package.py` 同步。
>
> **发版规矩**：`CHANGELOG.md` **只追加、不改写历史条目**；每次发版更新文末的 compare 链接。
> **tag 推送后不要移动**（别人可能已钉着它安装）—— 要改就发新版本号。

## 6. 发布前自检（建议写进检查清单）

```bash
cd <工作区>/publish/worklog

# vendored 技能与独立仓库没有漂移（独立仓库不在时这一步 SKIP）
node tools/sync-skill.mjs --check

# client-require-whitelist 与插件文件仍在位（这个工具只管还住在 .pi 的技能）
python ../../.pi/tools/_package.py --check

# 包内路径下也能跑通（验证相对路径没有写死）
# 断言条数故意不写在这里 —— 它每加一条断言就过期一次（见 RELEASING.md 的检查点 4）
# `-B` 不能省：脚本住在包里，Python 会把 __pycache__ 生成在**包内**（实测 498 KB 派生文件），
# `tools/sync-skill.mjs` 会忽略它，但 npm 打包会带上。
python -B skills/project-work-log/scripts/_selftest.py

# 插件清单自洽：dsh.bundle.patch 指向的文件存在、补丁是合法 YAML、入口能解析出技能 frontmatter
node -e "const p=require('./package.json'); const f=require('fs'); \
  if(!p.dsh?.bundle?.patch) throw new Error('missing dsh.bundle.patch'); \
  if(!f.existsSync(p.dsh.bundle.patch)) throw new Error('patch file missing'); \
  if(!f.existsSync('./lib/index.js')) throw new Error('plugin entry missing'); \
  console.log('dsh bundle manifest OK');"
node --input-type=module -e "const m=await import('./lib/index.js'); console.log('exports:', Object.keys(m).join(', '));"

# 没有把缓存/临时文件带进仓库
git status --porcelain
```

> **顺序是有讲究的：先 `--check`，后跑自测。** `_selftest.py` 会在
> `skills/project-work-log/scripts/` 下留下 `__pycache__/` —— 它被 `.gitignore` 盖着，
> `git status` 看不见，但 npm 打包会带上（实测过一次 498 KB 的陈旧 `.pyc`）。
> 跑一次 `git clean -fdx skills/` 或同步一次技能副本即可清掉。

## 7. 别人怎么装

```bash
# 装：从 npm 取，落成真实目录，并自动登记进 profile 的 dsh.profile.bundles
dsh plugin --profile <profile> add dsh-lore@v0.9.4

# 卸：依赖、bundles 条目、node_modules、lockfile 一并清掉
dsh plugin --profile <profile> remove dsh-lore
```

桌面端用户在插件页装/卸。**Electron 托管的 profile（例如 `desktop`）拒绝 CLI 操作**：
`dsh plugin` 会直接报 `profile "desktop" is managed exclusively by the Electron application`。

> **为什么不再给"本地路径装法"。** `dsh plugin` 把参数原样转给 pnpm，而 pnpm 对本地目录建的是
> **junction**：卸载时 pnpm 删不掉它（unlink 语义删不了重解析点），条目就留在 `node_modules` 里，
> 下一次换装直接 `ERR_PNPM_EPERM`（实测踩过一次，记在 CHANGELOG 的 `[未发布]`）。要验证本地
> 构建产物，先 `pnpm pack`，再用 `add ./dsh-lore-0.9.4.tgz` —— 它落成真实目录，卸载干净。

装进 dsh 时还要确认该 profile 里 `skill` / `skill-filesystem` / `tool-skill` 三行是打开的
（基座 bundle 默认关着，见 README 的 dsh 章节；本包的 bundle patch 会自己打开 `skill-filesystem`）。

本包**不再声明** `pi` 字段与 `pi-package` 关键词；pi 的安装/画廊入口属于独立技能仓库。

## 8. 可选：发布到 npm

只有需要 `dsh plugin … add dsh-lore` 走 npm 或独立版本管理时才做：

```bash
npm login
npm publish --access public     # 名字重复就改 package.json 的 name 或加 scope
```
