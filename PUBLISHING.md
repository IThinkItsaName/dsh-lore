# 如何发布到 GitHub

本仓库是**独立仓库**（工作区本身不是 git 仓库），可直接 `git init` 后推送；也可先推到私有仓库验证再转公开。

## 0. 发之前先确认三件事

| 项 | 说明 |
|---|---|
| **许可证** | MIT，版权人已署为 `IThinkItsaName`（要改就编辑 `LICENSE`）。若不想用 MIT，换掉整个文件即可。 |
| **仓库名 / OWNER** | 已按 `IThinkItsaName/worklog` 写进下文；若改名，先全局替换这两个值。 |
| **`package.json` 的 `name`** | 现在是 `dsh-worklog`（同时兼容 pi 与 dsh）。**如果只通过 git / 本地路径安装，名字无所谓**；若要 `npm publish`，先去 npm 查是否重名。 |

## 1. 本地初始化并首次提交

```bash
cd <工作区>/publish/worklog

git init -b main
git add .
git status                 # 确认没有 __pycache__ / *.pyc 混进来
git commit -m "feat: project-work-log skill (journal + lessons + toolbox)"
```

## 2. 在 GitHub 建仓

**方式 A · 网页**（无需额外工具）

1. 打开 <https://github.com/new>
2. 填仓库名 `project-work-log`，选 Public / Private
3. **不要**勾选 "Add a README / .gitignore / license"（本地已有，避免冲突）
4. Create repository

**方式 B · GitHub CLI**（本机当前**未安装 `gh`**，需先装）

```bash
gh auth login
gh repo create worklog --public --source=. --remote=origin --push
```

## 3. 推送

```bash
git remote add origin https://github.com/IThinkItsaName/worklog.git
git branch -M main
git push -u origin main
```

## 4. 打 tag（推荐）

pi 安装时可以固定到 tag/commit，用户就不会被上游改动影响：

```bash
git tag -a v0.2.0 -m "project-work-log v0.2.0"
git push origin v0.2.0
```

之后别人可以这样装：

```bash
pi install git:github.com/IThinkItsaName/worklog@v0.2.0
```

## 5. 以后怎么更新

**skill 的唯一源是工作区的 `.pi/skills/project-work-log/`**，本仓库里的 `skills/project-work-log/` 是同步出来的副本。

`lib/index.js`、`cordis.patch.yml`、`package.json`、`README.md`、`CHANGELOG.md` 是**插件自有文件**，
直接在 `publish/worklog/` 里改（它们不参与同步）；`_package.py --check` 只校验它们在位，不比对内容。

改完 skill 后：

```bash
# 1) 同步（会打印新增/修改/删除）
python <工作区>/.pi/skills/project-work-log/scripts/_package.py

# 2) 只检查有没有漂移（有漂移退出码 1，可当提交前门禁）
python <工作区>/.pi/skills/project-work-log/scripts/_package.py --check

# 3) 有面向用户的变更时，先追加 CHANGELOG（见下）
#    把 CHANGELOG.md 里 `## [未发布]` 的内容整理成 `## [x.y.z] - YYYY-MM-DD`

# 4) 提交并推送
cd <工作区>/publish/worklog
git add -A && git commit -m "chore: sync skill from source" && git push
git tag -a v0.2.1 -m "v0.2.1" && git push origin v0.2.1   # 有行为变化时
```

> 不要在 `publish/worklog/skills/` 里直接改脚本——下次同步会被覆盖。改源，再同步。
>
> **发版规矩**：`CHANGELOG.md` **只追加、不改写历史条目**；每次发版更新文末的 compare 链接。
> **tag 推送后不要移动**（别人可能已钉着它安装）—— 要改就发新版本号。

## 6. 发布前自检（建议写进检查清单）

```bash
cd <工作区>/publish/worklog

# 包内路径下也能跑通（验证相对路径没有写死）
python skills/project-work-log/scripts/_selftest.py        # 期望 95/95 passed

# 源与包没有漂移，插件自有文件也都在位
python ../../.pi/skills/project-work-log/scripts/_package.py --check

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

## 7. 别人怎么装（写进 README 的三条路）

```bash
# dsh（本包声明了 dsh.bundle，装进某个 profile）
dsh plugin --profile desktop install /绝对/路径/worklog

# pi 用户
pi install git:github.com/IThinkItsaName/worklog

# 手动 / 其它 harness：把 skills/project-work-log 放进技能搜索路径（Agent Skills 标准布局）
cp -r skills/project-work-log ~/.pi/agent/skills/
```

装进 dsh 时还要确认该 profile 里 `skill` / `skill-filesystem` / `tool-skill` 三行是打开的
（基座 bundle 默认关着，见 README 的 dsh 章节）。

加上 `package.json` 里的 `pi-package` 关键词后，包会被 pi 的软件包画廊 <https://pi.dev/packages> 收录（若公开）。

## 8. 可选：发布到 npm

只有需要 `pi install npm:...` 或独立版本管理时才做：

```bash
npm login
npm publish --access public     # 名字重复就改 package.json 的 name 或加 scope
```
