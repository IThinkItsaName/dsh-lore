#!/usr/bin/env python3
"""_selftest.py — journal.py 的自测（内部工具，不参与日常使用）。

在临时目录里搭一个最小项目（`work_log/` 容器 + 容器内的 `lessons/`），跑通全部子命令并断言行为，
最后删除临时目录。另有一个旧布局（`journal/` + 顶层 `lessons/`）夹具，验证只读回退。
    python scripts/_selftest.py                 # 全过退出码 0
    python scripts/_selftest.py --root DIR      # 在指定的**已存在**目录下建夹具
    python scripts/_selftest.py --keep          # 跑完保留夹具目录，便于排查

`--root` 是为写入受限的环境准备的：某些沙箱只允许进程写它自己创建过的目录，
这时用系统临时目录会在 `os.makedirs` 上直接 `PermissionError`。
指定 `--root` 时夹具建在 `DIR/journal-selftest-<pid>/` 下（DIR 必须已存在且可写）。
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import locale
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "journal.py")


def _load_journal():
    """把 journal.py 当模块载进来：自测要断言它自己的常量（如 `MODE_DEFAULT`），
    而不是从输出里倒推——输出可能恰好和常量不一致。"""
    spec = importlib.util.spec_from_file_location("journal_selftest_subject", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


JOURNAL = _load_journal()
MODE_DEFAULT_CONST = JOURNAL.MODE_DEFAULT

# 夹具用的容器名：默认名，正是新布局要求的 `work_log/`。
CONTAINER = "work_log"

INDEX = """# P 工作记录

## 文件索引

### A. 起步

| 文件 | 方面 |
|---|---|
| [0001-seed.md](0001-seed.md) | 起步 |

## 待办（滚动清单）

- [ ] keep me

## 当前状态（2026-09-13）

- 分支 / HEAD：main
- 变更集：-
- 构建：
- 测试：
- 交付物与指纹：
- 环境：
- 阻塞 / 等待：
"""

SEED = """# 0001 · Seed entry

日期：2026-09-13
变更集：1
触发：selftest
范围：none
结论：0 改动

---

## 一、背景与事实核查

seed

## 二、验证

- 命令：`true`
- 结果：0
- 未覆盖：none
"""

LESSONS_INDEX = """# 经验手册

| 分册 | 内容 |
|---|---|
| [01-topic.md](01-topic.md) | x |
"""

# 非编程场景：用“批次”别名 + “结果”小节 + 数据（没有命令）
RESEARCH = """# 0003 · 用户访谈结论

日期：2026-09-15
批次：3
触发：访谈
范围：12 位用户
结论：8/12 提到价格敏感

---

## 一、背景与事实核查

12 位用户访谈记录见访谈纪要。

## 二、结果

- 8/12 提到价格敏感（67%）
- 3 人主动提到竞品 A
"""

VOLUME = """# 01 · Seed topic

来源：wl/0001。

## 子主题

- **seed**：a。根因：b。做法：c。（`wl/0001`）
"""

CLEAN_INDEX = """# P2

## 文件索引

### A. 归档

| 文件 | 方面 |
|---|---|
| [stageA/0005-old.md](stageA/0005-old.md) | a |
| [stageA/0006-old.md](stageA/0006-old.md) | b |

### B. 当前

| 文件 | 方面 |
|---|---|
| [0001-alpha.md](0001-alpha.md) | c |
| [0002-beta.md](0002-beta.md) | d |

## 待办（滚动清单）

- [ ] x

## 当前状态（2026-09-14）

- 阶段 / 版本：v1
"""


# 只含规范字段的台账：用来验证 status --set 的短名解析（阶段/核对/交付物）
CANON_INDEX = """# Canon

## 文件索引

### A. 起步

| 文件 | 方面 |
|---|---|

## 待办（滚动清单）

- [ ] keep me

## 当前状态（2026-09-13）

- 阶段 / 版本：v1
- 迭代：-
- 产出：
- 核对 / 验证：
- 交付物与指纹：
- 环境：
- 阻塞 / 等待：
"""


def entry(num: str, title: str, date: str, itr: str = "-") -> str:
    return (f"# {num} · {title}\n\n日期：{date}\n变更集：{itr}\n结论：1 项通过\n\n"
            f"## 四、验证\n\n- 方式：`true`\n- 结果：1 passed\n")


# ---- 精细度（记录档位）夹具 ------------------------------------------------
# 台账模板多了一行 `- 精细度：`（`## 当前状态` 的第八个固定字段）。老台账没有
# 这一行也必须照常工作——`MODE_INDEX` 是「有这一栏」，`MODE_LEGACY_INDEX` 是
# 「没有这一栏」（模拟改动之前写下的项目）。
MODE_INDEX = """# M

## 文件索引

### A. 起步

| 文件 | 方面 |
|---|---|
| [0001-work.md](0001-work.md) | 起步 |

## 待办（滚动清单）

- [ ] keep me

## 当前状态（2026-09-13）

- 阶段 / 版本：v1
- 迭代：-
- 产出：
- 核对 / 验证：
- 交付物与指纹：
- 环境：
- 阻塞 / 等待：
- 精细度：session
"""

MODE_LEGACY_INDEX = """# M legacy

## 文件索引

### A. 起步

| 文件 | 方面 |
|---|---|
| [0001-work.md](0001-work.md) | 起步 |

## 待办（滚动清单）

- [ ] keep me

## 当前状态（2026-09-13）

- 阶段 / 版本：v1
- 迭代：-
- 产出：
- 核对 / 验证：
- 交付物与指纹：
- 环境：
- 阻塞 / 等待：
"""

# 精细度不改变验证要求：任何档位下这篇都必须带可核对内容的验证小节。
MODE_WORK = """# 0001 · Work

日期：2026-09-13
迭代：1
触发：selftest
范围：none
结论：312 项测试通过

---

## 一、背景与事实核查

seed

## 四、验证

- 方式：`pytest -q`
- 结果：312 passed
"""

MODE_ROLL_ENTRY = """# 0002 · More work

日期：2026-09-14
迭代：2
触发：selftest
范围：none
结论：1 项通过

## 四、验证

- 方式：`true`
- 结果：1 passed
"""

results: list[tuple[bool, str]] = []
skipped: list[str] = []


def decode_output(raw) -> str:
    """把子进程输出解成人看的样子。

    **不能**直接 `text=True, encoding="utf-8"`：被测命令可能按本机编码（Windows 上是 GBK）输出，
    硬按 UTF-8 解会在**读线程**里抛 UnicodeDecodeError —— 而 `subprocess.run` 不把它抛给调用方，
    只是把 `.stdout` 留成 `None`，于是"解码失败"会在很远的地方以
    `TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'` 的形式爆出来
    （2026-10-17 实测：cp936 控制台下 card_phase 必崩，三个新相位一条也跑不到）。
    所以：捕**字节**，按 UTF-8 严格试、退回本机编码容错替换，与 `journal.py` 的 `decode()` 同口径。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(locale.getpreferredencoding(False), errors="replace")


def run(root: str, *argv: str, tool: str = TOOL) -> subprocess.CompletedProcess:
    # 项目根默认取 cwd；journal/ 与 lessons/ 名字走默认解析。
    # `tool=` 是给同目录的其它脚本（如 dsh-lore-card.py）用的：它们共用同一套夹具与调用约定。
    # 捕字节而不是 text=True（见 `decode_output` 的注释），再把两份输出换成 str 交回调用方，
    # 这样 `r.stdout + r.stderr` 这类拼接永远是 str —— 不给 None 流进断言留缝。
    r = subprocess.run([sys.executable, tool, *argv],
                       cwd=root, capture_output=True, text=False)
    r.stdout = decode_output(r.stdout)
    r.stderr = decode_output(r.stderr)
    if r.stdout is None or r.stderr is None:      # 理论上不可达；真到了要立刻炸，别静默
        raise RuntimeError("子进程输出解码失败（%s）：stdout=%r stderr=%r"
                           % (" ".join(argv), r.stdout, r.stderr))
    return r


def make_tmp(prefix: str) -> str:
    """建一个**能继续往下建目录**的临时根。

    为什么不直接用 `tempfile.mkdtemp`：它内部写死 `os.mkdir(file, 0o700)`，而 **Windows 上
    Python 会把 mode 翻成 ACL** —— 新建目录只允许"所有者"写。在受限沙箱（DSH 的
    workspace-write）里，随后的 `os.makedirs(<tmp>/work_log/lessons)` 就被内核拒了：

        PermissionError: [WinError 5] 拒绝访问。: '...\\journal-selftest-xxxx\\work_log'

    2026-10-15 实测：同一个父目录下 `os.mkdir(p)` 建的目录能继续往下建，`os.mkdir(p, 0o700)`
    建的不能；`C:\\Users\\...\\Temp\\dsh-<会话>\\` 与工作区里的目录**都一样**，所以不是某一处
    的权限坏了，是这个 mode 本身。`tempfile.mkdtemp()` 也没有 `mode=` 参数（3.14 都没有），
    所以这里自己挑名字 + `os.mkdir(..., 0o755)`（POSIX 上临时目录本来也该可读可进）。
    """
    base = tempfile.gettempdir()
    if not os.path.isdir(base):
        raise RuntimeError(f"临时目录不存在：{base}")
    for _ in range(64):
        cand = os.path.join(base, prefix + secrets.token_hex(4))
        try:
            os.mkdir(cand, 0o755)
        except FileExistsError:
            continue
        return cand
    raise RuntimeError(f"在 {base} 下连试 64 次都没抢到临时目录名")


def harness_fixture(name: str) -> str:
    """找 JS harness 的夹具文件（`tests/fixtures/<name>`），找不到返回空串。

    **为什么要找而不是写死一个相对路径**：这份 `_selftest.py` 同时活在两种布局里 ——
    工作区源码树（`.pi/skills/project-work-log/scripts/`）与发布包
    （`<包>/skills/project-work-log/scripts/`）。2026-10-15 整理把 harness 塌成了一份：
    源就在发布仓库里（`<工作区>/publish/worklog/tests/`），发布包那份是它自己
    （`<包>/tests/`），顶层 `logs/` 下不再有 `tests/`。另外从 npm 装出来的副本可能
    **根本没有** `tests/`（它不属于插件运行时）。
    所以这里按候选顺序找，找不到就由调用方记一条 `SKIP` —— 不假装验过。
    """
    for cand in (
        os.path.join(HERE, "..", "..", "..", "tests", "fixtures", name),                              # 发布包布局
        os.path.join(HERE, "..", "..", "..", "..", "publish", "worklog", "tests", "fixtures", name),   # 工作区源码树
        os.path.join(HERE, "..", "..", "..", "..", "..", "publish", "worklog", "tests", "fixtures", name),
    ):
        path = os.path.normpath(cand)
        if os.path.isfile(path):
            return path
    return ""


def ok(cond: bool, label: str, detail: str = "") -> None:
    results.append((bool(cond), label))
    print(("PASS  " if cond else "FAIL  ") + label + (f"   [{detail[:200]}]" if detail and not cond else ""))


def note(label: str, why: str = "") -> None:
    """一条**该验却没验**的断言：打印 `SKIP`，单独计数，既不算 PASS 也不算 FAIL。

    存在理由与 JS 半边 `tests/_report.mjs` 的 `skip()` 完全相同（审查报告 F13）：
    以前这种局面靠 `ok(True, "… SKIPPED")` 表达，于是在输出里与真跑过的断言**长得一模一样** ——
    "590/590 通过"这句话分不清哪几条其实什么都没验。**只在环境里根本没有可比对的东西时用**；
    能写的断言必须写。
    """
    skipped.append(label)
    print("SKIP  " + label + (f"   [{why}]" if why else ""))


# --- 让"坏消息"还能被记成一条失败断言（2026-10-14 加）---------------------------------
#
# 为什么需要这两个小东西：`ok(cond, label, detail)` 的三个实参在**调用点**求值。
# 自测里有些表达式只有在"上一句断言成立"的前提下才安全，比如
#     ok(json.loads(read(cfg_path)) == {...}, "config --write records …")
#     read_block = [b for b in orig_vol.split("\n\n") if "id: read-ok" in b][0]
# 一旦被测代码坏了（配置文件没写出来、分册里没有那一条），这两行会先抛
# `JSONDecodeError` / `IndexError`，异常发生在"记下这条断言"**之前** —— 整相被掀掉，
# 后面的断言一条都不跑。后果不是"多报一条红"，而是**这条变异反而变成了不构成证据的 CRASH**：
# 变异明明抓得住，报告里却看不出抓没抓住（2026-10-14 的变异整跑就报过 3 条这样的 CRASH）。
#
# `safe()` 把"可能抛"的表达式变成"要么值、要么一句坏消息"，于是断言照常变红、相继续跑。
# 判据不放松：坏消息与期望值不相等，该红的仍然红。
def safe(fn, default=""):
    """求值 `fn()`；抛异常就返回一句说明性文本（于是下游断言自然变红，而不是把相掀掉）。"""
    try:
        return fn()
    except Exception as exc:                      # noqa: BLE001 - 就是要兜住一切，见上
        return f"<求值就抛了：{type(exc).__name__}: {exc}>"


def block_with(text: str, needle: str) -> str:
    """取含 `needle` 的那个"以空行分隔的块"；没有就返回空串（调用方会据此变红）。"""
    for block in str(text).split("\n\n"):
        if needle in block:
            return block
    return ""


def under(root: str, *parts: str, empty=""):
    """`os.path.join(root, *parts)`，但**目录不存在**时返回 `empty` 而不是抛异常。

    同一个坑的第三张脸：变异让某个目录没被建出来之后，`subprocess.run(cwd=那儿)` 抛
    `NotADirectoryError`、`os.listdir(那儿)` 抛 `FileNotFoundError` —— 又一次在"记下断言"
    之前把整相带走。这里只兜"路径根本不在"，其它 OS 错误照抛。
    """
    path = os.path.join(root, *parts)
    if not os.path.exists(path):
        return empty
    return path


EN_INDEX = """# English journal

## Index

### A. Stage

| File | Note |
|---|---|
| [0001-alpha.md](0001-alpha.md) | a |

## TODO

- [ ] ship it

## Status (2026-01-01)

- Stage: v1
"""

EN_ENTRY = """# 0001 · Alpha

Date: 2026-01-01
Iteration: 5
Trigger: kickoff
Scope: none
Conclusion: 312 tests green

---

## Verification

- Command: `pytest -q`
- Result: 312 passed
"""


def english_phase(parent: str) -> None:
    """英文标签应能被解析（跨语言解析能力，P1）。"""
    tmp = os.path.join(parent, "english")
    os.makedirs(os.path.join(tmp, CONTAINER, "lessons"))
    write(os.path.join(tmp, CONTAINER, "README.md"), EN_INDEX)
    write(os.path.join(tmp, CONTAINER, "0001-alpha.md"), EN_ENTRY)
    write(os.path.join(tmp, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(tmp, CONTAINER, "lessons", "01-topic.md"),
          "# 01 · T\n\nSource: wl/0001.\n\n- **s**: a. cause: b. fix: c. (`wl/0001`)\n")

    r = run(tmp, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "english labels: check --strict clean", r.stdout + r.stderr)
    r = run(tmp, "lint", "--strict", "--quiet")
    ok(r.returncode == 0, "english labels: lint --strict clean", r.stdout + r.stderr)
    r = run(tmp, "outline")
    ok("\t2026-01-01\t5\t" in r.stdout, "english labels: Date/Iteration parsed", r.stdout)
    r = run(tmp, "brief", "--entries", "1")
    ok("Status (2026-01-01)" in r.stdout, "english labels: Status block found", r.stdout)


def cleanup_phase(parent: str) -> None:
    """A/B/C/D 四项整理能力：索引瘦身 / 归档 / 分卷 / 冷存（全部按新布局）。"""
    tmp = os.path.join(parent, "cleanup")
    os.makedirs(os.path.join(tmp, CONTAINER, "stageA"))
    os.makedirs(os.path.join(tmp, CONTAINER, "lessons"))
    write(os.path.join(tmp, CONTAINER, "README.md"), CLEAN_INDEX)
    write(os.path.join(tmp, CONTAINER, "0001-alpha.md"), entry("0001", "Alpha", "2020-01-01"))
    write(os.path.join(tmp, CONTAINER, "0002-beta.md"), entry("0002", "Beta", "2026-09-14"))
    # 已归档记录：阶段目录直接建在容器下（不再有 archive/ 一层）。
    write(os.path.join(tmp, CONTAINER, "stageA", "0005-old.md"), entry("0005", "Old5", "2020-01-01"))
    write(os.path.join(tmp, CONTAINER, "stageA", "0006-old.md"), entry("0006", "Old6", "2020-01-02"))
    write(os.path.join(tmp, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(tmp, CONTAINER, "lessons", "01-topic.md"),
          "# 01 · T\n\n来源：wl/0002。\n\n- **s**：a。根因：b。做法：c。（`wl/0002`）\n")
    jidx = os.path.join(tmp, CONTAINER, "README.md")

    # 新布局回归：容器根放记录、lessons/ 是容器子目录
    r = run(tmp, "outline")
    ok("01-topic" not in r.stdout, "a volume under lessons/ is not read as a record", r.stdout)
    ok(re.search(r"^0002\t", r.stdout, re.M) is not None,
       "records live at the container root", r.stdout)
    r = run(tmp, "brief", "--entries", "9")
    ok("active 2 / archive 2" in r.stdout, "brief counts root records as active and <stage>/ as archived", r.stdout)

    # A) index compact
    r = run(tmp, "index", "compact", "--dry-run")
    ok(r.returncode == 0 and "折叠 1 个小节" in r.stdout, "compact dry-run reports", r.stdout)
    before = read(jidx)
    ok(read(jidx) == before, "compact dry-run changes nothing")
    run(tmp, "index", "compact")
    idx = read(jidx)
    ok("stageA/0005-old.md" not in idx and "[stageA/](stageA/)" in idx,
       "compact folds archived rows into one (stage dirs under the container)", idx)
    ok("0001-alpha.md" in idx, "compact keeps active rows")

    # B) archive
    r = run(tmp, "archive", "--stage", "stageB", "--from", "1", "--to", "1")
    ok(os.path.exists(os.path.join(tmp, CONTAINER, "stageB", "0001-alpha.md")),
       "archive moves the file into <container>/<stage>/", r.stdout)
    idx = read(jidx)
    ok("stageB/0001-alpha.md" in idx, "archive rewrites index link", idx)
    ok(not os.path.exists(os.path.join(tmp, CONTAINER, "archive", "ARCHIVE.md")),
       "archive writes no archive index (只写不读的产物已退场，归档信息归 README 索引)")
    ok(not os.path.exists(os.path.join(tmp, CONTAINER, "ARCHIVE.md")),
       "and none at the container root either")

    # D) split --by-year
    r = run(tmp, "split", "--by-year")
    ok(os.path.exists(os.path.join(tmp, CONTAINER, "2026", "0002-beta.md")),
       "split moves entry under its year volume", r.stdout)
    ok("2026/0002-beta.md" in read(jidx), "split rewrites index link", read(jidx))
    r = run(tmp, "outline")
    ok("0002" in r.stdout and "0005" in r.stdout,
       "both year-volume and stage records stay discoverable", r.stdout)

    # C) prune（报告 → 打包 → 移出）
    r = run(tmp, "prune")
    ok(r.returncode == 0 and "冷存候选" in r.stdout, "prune reports candidates", r.stdout)
    before = read(jidx)
    ok(read(jidx) == before, "prune report-only changes nothing")
    zpath = os.path.join(tmp, "cold.zip")
    r = run(tmp, "prune", "--zip", zpath)
    ok(os.path.exists(zpath), "prune --zip writes archive", r.stdout)
    ok(os.path.exists(os.path.join(tmp, CONTAINER, "stageA", "0005-old.md")),
       "prune --zip keeps originals")
    r = run(tmp, "prune", "--zip", zpath, "--apply")
    ok(not os.path.exists(os.path.join(tmp, CONTAINER, "stageA", "0005-old.md")),
       "prune --apply moves originals out", r.stdout)
    ok(os.path.exists(os.path.join(tmp, CONTAINER, "COLD-STORE.md")),
       "prune writes a manifest at the container root")
    ok(os.path.exists(os.path.join(tmp, CONTAINER, "2026", "0002-beta.md")),
       "prune keeps cited/active entry")

    r = run(tmp, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "check --strict clean after cleanup ops", r.stdout + r.stderr)

    # E) compact 幂等：折叠出来的目录行不能再被折一次 ------------------------
    jidx = os.path.join(tmp, CONTAINER, "README.md")
    run(tmp, "index", "compact")
    once = read(jidx)
    r = run(tmp, "index", "compact")
    ok(read(jidx) == once, "index compact is idempotent", read(jidx))
    ok("折叠 0 个小节" in r.stdout, "second compact folds nothing", r.stdout)

    # F) 经验目录不是「归档阶段」：只有已归档记录的节才折叠 ----------------
    mix = os.path.join(parent, "mixfix")
    os.makedirs(os.path.join(mix, CONTAINER, "lessons"))
    os.makedirs(os.path.join(mix, CONTAINER, "stageZ"))
    write(os.path.join(mix, CONTAINER, "README.md"),
          "# Mix\n\n## 文件索引\n\n### A. 经验\n\n| 文件 | 方面 |\n|---|---|\n"
          "| [lessons/01-topic.md](lessons/01-topic.md) | 经验 |\n\n"
          "### B. 归档\n\n| 文件 | 方面 |\n|---|---|\n"
          "| [stageZ/0007-old.md](stageZ/0007-old.md) | a |\n"
          "| [stageZ/0008-old.md](stageZ/0008-old.md) | b |\n\n"
          "## 待办（滚动清单）\n\n- [ ] x\n\n## 当前状态（2026-09-13）\n\n- 阶段 / 版本：v1\n")
    write(os.path.join(mix, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(mix, CONTAINER, "lessons", "01-topic.md"),
          "# 01 · T\n\n来源：wl/0007。\n\n## 子主题\n\n- **s**：a。根因：b。做法：c。（`wl/0007`）\n")
    write(os.path.join(mix, CONTAINER, "stageZ", "0007-old.md"), entry("0007", "Old7", "2020-01-01"))
    write(os.path.join(mix, CONTAINER, "stageZ", "0008-old.md"), entry("0008", "Old8", "2020-01-02"))
    r = run(mix, "index", "compact")
    midx = read(os.path.join(mix, CONTAINER, "README.md"))
    ok("折叠 1 个小节" in r.stdout, "only the all-archived section folds", r.stdout)
    ok("[lessons/01-topic.md](lessons/01-topic.md)" in midx and "| [lessons/]" not in midx,
       "a lessons row is never folded as an archived stage", midx)
    ok("[stageZ/](stageZ/)" in midx, "the all-archived section folded to a stage row", midx)
    r = run(mix, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "check --strict clean on the mixed fixture", r.stdout + r.stderr)


def nested_stage_phase(parent: str) -> None:
    """多级归档（`<主题>/<阶段>`）与 `index compact --depth`。

    2026-10-14 新增：`--stage` 不再只收单层名字（长期容器里"一阶段一个平铺目录"会平铺一大片），
    于是归档路径可以带主题层；随之而来两件必须钉住的事：
      - 归档表与索引里写的都是**完整相对路径**，且同一个目录分几次归档**只占一行**（区间求并集）；
      - `index compact` 的幂等不能再用"目标是目录就跳过"（多级归档里指向**主题目录**的行要能折），
        改成"已经是区间行才跳过"；`--depth N` 用来指定折第几层。
    """
    tmp = os.path.join(parent, "nested")
    os.makedirs(os.path.join(tmp, CONTAINER, "lessons"))
    write(os.path.join(tmp, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(tmp, CONTAINER, "README.md"),
          "# N\n\n## 文件索引\n\n| 文件 | 方面 |\n|---|---|\n"
          "| [0001-a.md](0001-a.md) | a |\n| [0002-b.md](0002-b.md) | b |\n| [0003-c.md](0003-c.md) | c |\n\n"
          "## 待办（滚动清单）\n\n- [ ] x\n\n## 当前状态（2026-10-03）\n\n- 阶段 / 版本：v1\n")
    write(os.path.join(tmp, CONTAINER, "0001-a.md"), entry("0001", "A", "2026-10-01"))
    write(os.path.join(tmp, CONTAINER, "0002-b.md"), entry("0002", "B", "2026-10-02"))
    write(os.path.join(tmp, CONTAINER, "0003-c.md"), entry("0003", "C", "2026-10-03"))
    jidx = os.path.join(tmp, CONTAINER, "README.md")

    # A) 两级归档：落点、索引链接、归档表里的完整相对路径
    r = run(tmp, "archive", "--stage", "theme-a/01-first", "--from", "1", "--to", "2")
    ok(os.path.exists(os.path.join(tmp, CONTAINER, "theme-a", "01-first", "0001-a.md")),
       "nested --stage puts records under <theme>/<stage>/", r.stdout)
    ok("theme-a/01-first/0001-a.md" in read(jidx), "nested archive rewrites the index link", read(jidx))
    ok(not os.path.exists(os.path.join(tmp, CONTAINER, "archive", "ARCHIVE.md")),
       "nested archiving writes no archive index either", r.stdout)

    # B) 同一个目录再归档一次：仍然不写归档索引（归档信息只在 README 索引里）
    r = run(tmp, "archive", "--stage", "theme-a/01-first", "--from", "3", "--to", "3")
    ok(not os.path.exists(os.path.join(tmp, CONTAINER, "archive", "ARCHIVE.md")),
       "re-archiving keeps writing no archive index", r.stdout)
    ok("0003-c.md" in read(jidx), "and the index link for the third record is rewritten", read(jidx))
    r = run(tmp, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "check --strict clean after nested archiving", r.stdout + r.stderr)

    # C) 非法 --stage 一律挡下（含"容器外"这一类）
    for stage, label in (("2026/01-x", "a year segment"), ("theme/../escape", "a .. segment"),
                         # `C:/elsewhere` 在 Windows 上测的是"绝对路径"，在 Linux 上它落在
                         # "非法目录名"那一档 —— 两边都该拒，所以这条不用按平台分叉。
                         ("theme/logs", "a non-record dir"), ("C:/elsewhere", "an absolute path"),
                         ("/tmp/x", "a leading slash")):
        r = run(tmp, "archive", "--stage", stage, "--from", "9", "--to", "9")
        ok(r.returncode != 0 and "ERROR" in r.stdout, f"archive rejects {label}", r.stdout)
    ok(not os.path.exists(os.path.join(tmp, "escape"))
       and not os.path.exists(os.path.join(parent, "escape")),
       "a rejected --stage leaves nothing outside the container")

    # D) index compact --depth：2 级行能折、1 级行不动、再跑幂等、无可折记录的目录不折
    tmp2 = os.path.join(parent, "depth")
    os.makedirs(os.path.join(tmp2, CONTAINER, "lessons"))
    os.makedirs(os.path.join(tmp2, CONTAINER, "theme-a", "01-first"))
    os.makedirs(os.path.join(tmp2, CONTAINER, "theme-b", "01-second"))
    os.makedirs(os.path.join(tmp2, CONTAINER, "stage-c"))
    write(os.path.join(tmp2, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(tmp2, CONTAINER, "README.md"),
          "# D\n\n## 文件索引\n\n"
          "### 主题 A\n\n| [theme-a/01-first/](theme-a/01-first/) | 这一阶段的记录 |\n\n"
          "### theme-b/01-second\n\n| [theme-b/01-second/](theme-b/01-second/) | 这一阶段的记录 |\n\n"
          "### stage-c\n\n| 文件 | 方面 |\n|---|---|\n"
          "| [stage-c/0006-c1.md](stage-c/0006-c1.md) | 六 |\n"
          "| [stage-c/0007-c2.md](stage-c/0007-c2.md) | 七 |\n\n"
          "## 待办（滚动清单）\n\n- [ ] x\n\n## 当前状态（2026-10-07）\n\n- 阶段 / 版本：v1\n")
    write(os.path.join(tmp2, CONTAINER, "theme-a", "01-first", "0001-a.md"), entry("0001", "A", "2026-10-01"))
    write(os.path.join(tmp2, CONTAINER, "theme-b", "01-second", "0004-d.md"), entry("0004", "D", "2026-10-04"))
    write(os.path.join(tmp2, CONTAINER, "theme-b", "01-second", "0005-e.md"), entry("0005", "E", "2026-10-05"))
    write(os.path.join(tmp2, CONTAINER, "stage-c", "0006-c1.md"), entry("0006", "C1", "2026-10-06"))
    write(os.path.join(tmp2, CONTAINER, "stage-c", "0007-c2.md"), entry("0007", "C2", "2026-10-07"))
    didx = os.path.join(tmp2, CONTAINER, "README.md")

    r = run(tmp2, "index", "compact", "--depth", "2")
    dtext = read(didx)
    ok("[theme-b/01-second/](theme-b/01-second/) | 0004–0005（2 篇，已归档）" in dtext,
       "compact --depth 2 folds a nested directory row and counts its records", dtext)
    ok("[stage-c/0006-c1.md](stage-c/0006-c1.md)" in dtext,
       "compact --depth 2 leaves 1-level sections alone", dtext)
    once = read(didx)
    r = run(tmp2, "index", "compact", "--depth", "2")
    ok(read(didx) == once and "折叠 0 个小节" in r.stdout,
       "compact --depth 2 is idempotent on an already-folded row", r.stdout)
    r = run(tmp2, "index", "compact")
    dtext = read(didx)
    ok("[stage-c/](stage-c/) | 0006–0007（2 篇，已归档）" in dtext,
       "a plain --depth 1 compact still folds ordinary stage sections", dtext)
    ok("[theme-a/01-first/](theme-a/01-first/)" in dtext,
       "a theme directory holding no records of its own is never folded", dtext)





def archive_index_check(parent: str) -> None:
    """遗留的归档索引 `ARCHIVE.md`：只认、只提示，不再写（2026-10-16）。

    这一版判据换过一次方向。初版把它做成**被校验的一等文件**（表里列了磁盘没有 = ERROR），
    后来量出它是**只写不读**的产物：`index compact` 折归档行读的是 README 索引的小节 +
    直接数磁盘篇号（`stage_numbers`），从不读这张表；而它记的目录/区间/篇数，README 索引里
    早有一行。于是让它退场 —— `archive` 不再写它，`check` 只出 INFO 提示它可删。

    这里钉三件事：
      - 没有它时，`check` 一句都不说（绝大多数容器都该是这样）；
      - 有它时只报 INFO，**不报** ERROR/WARN（可选产物不该让容器变红），
        且那条 INFO 要点出「表指空」与「目录没登记」两类漂移；
      - `archive` 之后两处落点都不该冒出这个文件，已有文件也不被改写。
    """
    tmp = os.path.join(parent, "archidx")
    os.makedirs(os.path.join(tmp, CONTAINER, "archive", "st1"))
    os.makedirs(os.path.join(tmp, CONTAINER, "archive", "ghost2"))
    write(os.path.join(tmp, CONTAINER, "README.md"),
          "# N\n\n## 文件索引\n\n### A. 阶段\n\n| 文件 | 方面 |\n|---|---|\n")
    write(os.path.join(tmp, CONTAINER, "archive", "st1", "0001-a.md"), entry("0001", "A", "2026-10-01"))
    write(os.path.join(tmp, CONTAINER, "archive", "ghost2", "0002-b.md"), entry("0002", "B", "2026-10-02"))

    # A) 没有遗留文件时：一句都不说
    r = run(tmp, "check", "--strict")
    ok("ARCHIVE.md" not in (r.stdout + r.stderr),
       "without a legacy index file, check says nothing about it", r.stdout + r.stderr)

    # B) 放一份遗留表（一行指空 + 一个没登记的目录）：只出 INFO
    atext = ("# 归档区\n\n| 目录 | 篇号 | 时间 | 内容 | 归档判据 |\n|---|---|---|---|---|\n"
             "| `archive/st1/` | 0001–0001 | 2026-10-01 ~ 2026-10-01 | 1 篇 | 阶段收口 |\n"
             "| `archive/ghost/` | 0009–0009 | - | 1 篇 | 阶段收口 |\n")
    write(os.path.join(tmp, CONTAINER, "archive", "ARCHIVE.md"), atext)
    r = run(tmp, "check", "--strict")
    out = r.stdout + r.stderr
    ok(r.returncode == 0, "a legacy index file does not fail --strict", out)
    ok("[INFO]" in out and "遗留的归档索引" in out, "it is reported as INFO", out)
    ok("1 个目录在磁盘上不存在" in out and "`archive/ghost/`" in out,
       "the INFO names the table row pointing nowhere", out)
    ok("1 个归档目录没登记" in out and "`archive/ghost2`" in out,
       "the INFO names the unregistered stage directory", out)
    ok("[ERROR]" not in out and "[WARN]" not in out,
       "and nothing at ERROR/WARN level (可选产物不该让容器变红)", out)

    # C) 旧落点（容器根）也认；归档**不**更新它、也不新建一份
    os.remove(os.path.join(tmp, CONTAINER, "archive", "ARCHIVE.md"))
    write(os.path.join(tmp, CONTAINER, "ARCHIVE.md"), atext)
    r = run(tmp, "archive", "--stage", "st1", "--from", "1", "--to", "1")
    ok(os.path.exists(os.path.join(tmp, CONTAINER, "ARCHIVE.md"))
       and not os.path.exists(os.path.join(tmp, CONTAINER, "archive", "ARCHIVE.md")),
       "a legacy root ARCHIVE.md stays where it is (never split into two tables)", r.stdout)
    ok(read(os.path.join(tmp, CONTAINER, "ARCHIVE.md")) == atext,
       "archiving leaves the legacy table untouched", read(os.path.join(tmp, CONTAINER, "ARCHIVE.md")))
    # D) 归档目录**自己的**索引（`archive/README.md`）不能被当成旧 `ARCHIVE.md`。
    #    两张表都带「目录」列，光看列名分不开；区分点是标题 —— 新索引
    #    `# work_log/archive/ —— 已归档记录`，旧表 `# 归档区`。而且它住在 `archive/` 里，
    #    正好是旧布局的落点，位置上更分不开。2026-10-16 踩过：不加这个判据，
    #    `check` 会把新索引的 N 行读成「N 个路径全错 + N 个目录全没登记」，两条读数全是假的。
    os.remove(os.path.join(tmp, CONTAINER, "ARCHIVE.md"))
    new_style = ("# work_log/archive/ —— 已归档记录\n\n"
                 "| 目录 | 篇号 | 时间 | 内容 | 归档判据 |\n|---|---|---|---|---|\n"
                 "| `st1/` | 0001 | 2026-10-01 | 1 篇 · 探针 | 阶段收口 |\n"
                 # `ghost2/` 也登记上：这一段要验的是"新索引不被认成遗留表"，
                 # 留着一个真漏行会让**另一条**检查（反向核对）如实报红，两件事混在一起。
                 # 漏行本身另有断言专门验（见下面 D2）。
                 "| `ghost2/` | 0002 | 2026-10-02 | 1 篇 · 探针 | 阶段收口 |\n")
    write(os.path.join(tmp, CONTAINER, "archive", "README.md"), new_style)
    r = run(tmp, "check", "--strict")
    out = r.stdout + r.stderr
    ok("遗留的归档索引" not in out,
       "the archive directory's own index is not read as the legacy table", out)
    ok(r.returncode == 0, "and it does not turn the gate red", out)
    ok(os.path.isfile(os.path.join(tmp, CONTAINER, "archive", "README.md")),
       "the new-style index file is left in place", out)

    # D2) **反向核对**：磁盘上有归档目录、表里却没有它这一行（2026-10-17 补）。
    #     上面两条只查"表 → 磁盘"，整个阶段漏登记时它们都不响 —— 而漏行是最常见的漂移。
    write(os.path.join(tmp, CONTAINER, "archive", "README.md"),
          new_style.replace("| `ghost2/` | 0002 | 2026-10-02 | 1 篇 · 探针 | 阶段收口 |\n", ""))
    r = run(tmp, "check", "--strict")
    out = r.stdout + r.stderr
    ok(r.returncode != 0 and "却没有这一行" in out and "ghost2" in out,
       "a stage directory with no row in the table is reported (reverse check)", out)
    # 表头在、**数据行为零**也不能短路反向核对（空表正是"全漏登记"的样子）
    write(os.path.join(tmp, CONTAINER, "archive", "README.md"),
          "# work_log/archive/ —— 已归档记录\n\n"
          "| 目录 | 篇号 | 时间 | 内容 | 归档判据 |\n|---|---|---|---|---|\n")
    r = run(tmp, "check", "--strict")
    out = r.stdout + r.stderr
    ok("却没有这一行" in out and r.returncode != 0,
       "an empty table still gets the reverse check (not short-circuited)", out)




def archive_dir_index_phase(parent: str) -> None:
    """归档目录**自己的**索引（`<容器>/archive/README.md`）：`archive --stage` 维护它。

    2026-10-16 起归档索引的落点从容器根的 `ARCHIVE.md` 换成这份 —— 一份给**人**读的
    目录索引（一行一个阶段）。关键约束是「工具只补行，正文一个字都不动」：这份文件
    人写为主，自述、备注、尾巴都可能有，工具不许整篇重写。这里钉六件事：

      · 新容器首次归档：建骨架（标题 + 表头 + 第一行），别的地方不冒文件；
      · 文件已存在且有正文：只**追加一行**，正文与既有行原样保留，且追加在表末；
      · 同一阶段再归档：**原地更新那一行**（日期区间取并集；**篇号与篇数按磁盘重算**，
       见 `journal.py` 的 `name_number()`），不新增行；
      · 归档到 `archive/` 直属层：表里没有可写的行 —— 不写、不崩、不改动那份文件；
      · 文件在、但认不出我们的表头：**不猜不动**（悄悄另起一张表会留下两张，人不知道该信哪张）；
      · 认表头只认同名的行，文件里别处的表格不被当数据行（新骨架的标题也不能用旧表的
        `# 归档区`——那正是 `_is_legacy_archive_index` 判「这是遗留 ARCHIVE.md」的判据）。
    """
    nl = "\n"
    head = ("| 目录 | 篇号 | 时间 | 内容 | 归档判据 |" + nl
            + "|---|---|---|---|---|" + nl)

    # 纯函数：`--stage` 的两种写法换算成表里那个相对路径
    rel = JOURNAL.archive_index_rel
    ok(rel("archive/probe-s3") == "probe-s3/", "archive_index_rel strips a leading archive/", rel("archive/probe-s3"))
    # **平铺布局没有可写的行**（2026-10-17）：`--stage probe-s3` 落的是 `<容器>/probe-s3`，
    # `archive/` 下没有这个目录 —— 写一行 `| `probe-s3/` |` 会指向不存在的目录，
    # 而检查侧只能静默跳过（表按相对 `archive/` 解释），于是留下一条永远没人核的行。
    ok(rel("probe-s3") == "", "a bare stage name has no row (flat layout, not under archive/)", rel("probe-s3"))
    ok(rel("archive/a/b") == "a/b/", "archive_index_rel keeps multi-level stages", rel("archive/a/b"))
    ok(rel("archive") == "", "archive/ itself has no row (nothing to write)", rel("archive"))
    ok(rel("") == "", "an empty stage has no row", rel(""))

    def mk(name: str, with_prose: str | None = None) -> str:
        root = os.path.join(parent, "archdir-" + name)
        os.makedirs(os.path.join(root, CONTAINER, "lessons"))
        write(os.path.join(root, CONTAINER, "lessons", "README.md"), "# L\n")
        write(os.path.join(root, CONTAINER, "README.md"),
              "# N\n\n## 文件索引\n\n### A. 阶段\n\n| 文件 | 方面 |\n|---|---|\n")
        if with_prose is not None:
            write(os.path.join(root, CONTAINER, "archive", "README.md"), with_prose)
        return root

    def add_entry(root: str, num: int, date: str) -> None:
        name = f"{num:04d}-a{num}.md"
        write(os.path.join(root, CONTAINER, name), entry(f"{num:04d}", f"A{num}", date))
        idx_path = os.path.join(root, CONTAINER, "README.md")
        rows = [ln for ln in read(idx_path).splitlines() if ln.startswith("| [")]
        rows.append(f"| [{name}]({name}) | 探针 {num} |")
        write(idx_path, ("# N\n\n## 文件索引\n\n### A. 阶段\n\n| 文件 | 方面 |\n|---|---|" + nl
                         + nl.join(rows) + nl))

    # A) 新容器：建骨架，且只落在 archive/ 里（容器根不再冒 ARCHIVE.md）
    tmp = mk("new")
    add_entry(tmp, 1, "2026-10-01")
    r = run(tmp, "archive", "--stage", "archive/st1", "--from", "1", "--to", "1")
    ok(r.returncode == 0, "archive --stage exits 0 with the new index", r.stdout + r.stderr)
    p = os.path.join(tmp, CONTAINER, "archive", "README.md")
    text = read(p)
    ok("| `st1/` | 0001–0001 | 2026-10-01 ~ 2026-10-01 | 1 篇 |" in text,
       "the first archive writes one row for the stage", text)
    ok("目录 | 篇号 | 时间 | 内容 | 归档判据" in text, "the skeleton carries the 5-column head", text)
    ok(not os.path.exists(os.path.join(tmp, CONTAINER, "ARCHIVE.md")),
       "no legacy ARCHIVE.md appears at the container root", r.stdout)
    ok("work_log/archive/README.md" in (r.stdout + r.stderr),
       "the hint names where the index went", r.stdout)
    # `check` 不该把这份新索引读成遗留表
    r = run(tmp, "check", "--strict")
    ok("遗留的归档索引" not in (r.stdout + r.stderr),
       "check does not read the new index as the legacy table", r.stdout + r.stderr)

    # B) 文件已存在且有正文：只追加一行，正文与旧行原样保留
    prose = ("# `work_log/archive/` —— 已归档记录" + nl + nl
             + "**这里只放告一段落的内容。** 人写的自述，工具不许动。" + nl + nl
             + head
             + "| `st0/` | 0001–0001 | 2026-10-01 ~ 2026-10-01 | 1 篇 | 人工 |" + nl + nl
             + "## 尾注" + nl + nl + "这段也必须在。" + nl)
    tmp = mk("prose", prose)
    add_entry(tmp, 2, "2026-10-02")
    run(tmp, "archive", "--stage", "archive/st2", "--from", "2", "--to", "2")
    after = read(os.path.join(tmp, CONTAINER, "archive", "README.md"))
    ok("人写的自述，工具不许动" in after and "这段也必须在" in after,
       "archiving leaves the hand-written prose alone", after)
    ok("| `st0/` | 0001–0001 | 2026-10-01 ~ 2026-10-01 | 1 篇 | 人工 |" in after,
       "and leaves the rows it did not write alone", after)
    ok(after.index("`st0/`") < after.index("`st2/`"), "the new row is appended below the old", after)
    ok(after.index("`st2/`") < after.index("## 尾注"),
       "the new row lands inside the table, not at the end of the file", after)

    # C) 同一阶段再归档：原地更新，日期取并集、篇号与篇数按磁盘重算，不新增行
    add_entry(tmp, 3, "2026-10-03")
    run(tmp, "archive", "--stage", "archive/st2", "--from", "3", "--to", "3")
    after = read(os.path.join(tmp, CONTAINER, "archive", "README.md"))
    rows = [ln for ln in after.splitlines() if ln.startswith("| `st2/`")]
    ok(len(rows) == 1, "archiving the same stage twice updates its row instead of adding one",
       "\n".join(rows))
    if rows:
        ok("0002–0003" in rows[0] and "2 篇" in rows[0], "the row merges entry numbers and counts", rows[0])
        ok("2026-10-02 ~ 2026-10-03" in rows[0], "the row merges the date span", rows[0])

    # D) 归档到 archive/ 直属层：表里没有可写的行（不写、不崩、不动那份文件）
    tmp = mk("flat", prose)
    add_entry(tmp, 4, "2026-10-04")
    r = run(tmp, "archive", "--stage", "archive", "--from", "4", "--to", "4")
    ok(r.returncode == 0 and not r.stderr.strip(),
       "archiving into archive/ itself is not an error", r.stdout + r.stderr)
    ok(read(os.path.join(tmp, CONTAINER, "archive", "README.md")) == prose,
       "and it writes nothing into the index", read(os.path.join(tmp, CONTAINER, "archive", "README.md")))

    # E) 文件在、但没有我们的表头：不猜不动（宁可什么都不写）
    prose2 = "# 某个自述" + nl + nl + "| 别的表 | 呢 |" + nl + "|---|---|" + nl + "| x | y |" + nl
    tmp = mk("notable", prose2)
    add_entry(tmp, 5, "2026-10-05")
    r = run(tmp, "archive", "--stage", "archive/st5", "--from", "5", "--to", "5")
    ok(r.returncode == 0 and read(os.path.join(tmp, CONTAINER, "archive", "README.md")) == prose2,
       "an index without our table is left alone (no second table is started)",
       read(os.path.join(tmp, CONTAINER, "archive", "README.md")))

    # F) 并入既有行**不丢旧信息**：同一阶段归档两次（第二批是后来的篇号），
    #    那一行必须是两批的并集，且不碰表里别人写的行。
    tmp = mk("onerow", prose)
    add_entry(tmp, 6, "2026-10-06")
    run(tmp, "archive", "--stage", "archive/st2", "--from", "6", "--to", "6")
    add_entry(tmp, 7, "2026-10-07")
    run(tmp, "archive", "--stage", "archive/st2", "--from", "7", "--to", "7")
    merged = read(os.path.join(tmp, CONTAINER, "archive", "README.md"))
    ok(merged.count("| `st2/`") == 1, "a stage archived twice still has exactly one row", merged)
    ok("0006–0007" in merged and "2 篇" in merged,
       "the row it replaces is merged, not overwritten (0006 + 0007 = 0006–0007 / 2 篇)", merged)
    ok("2026-10-06 ~ 2026-10-07" in merged, "the merged row spans both dates", merged)
    ok("| `st0/` | 0001–0001 | 2026-10-01 ~ 2026-10-01 | 1 篇 | 人工 |" in merged,
       "merging one row leaves its neighbours alone", merged)
    ok(merged.index("`st0/`") < merged.index("`st2/`") < merged.index("## 尾注"),
       "and the merged row stays inside the table", merged)

    # G) 篇号与篇数**按磁盘重算**，且断档写穷举（2026-10-17 改口径）。
    #    这一段的历史：旧实现拿"区间展开后的集合长度"当篇数（跨度为 34，报「34 篇」），
    #    篇号格还会写成 `0071–0104`，把没归档的号也算进去 —— 真实归档首跑就是这么暴露的；
    #    之后的修法是"两批各自的篇数相加、篇号取并集"，但那样仍有两个洞（本次修掉）：
    #      · 旧行写着区间时 `l_entry_nums()` 展开成**跨度**，加法仍以跨度为基；
    #      · 调用方传进来的 `nums` 只是**本次选中**的那批，同目录里别的记录（手工搬进去的、
    #        上次归档的）它看不见 —— 于是写出一行与磁盘不符的数字，而检查正照磁盘核。
    #    现在的口径只有一句：**目标目录里现在有几篇编号式记录**（`name_number()` 扫盘），
    #    与检查侧同一个函数、同一份判据；`nums`/`dates` 只在建新文件时用来起骨架。
    #    ⚠ 夹具别只用连续编号：连续时跨度恰好等于个数，这两个洞结构上都测不出来。
    gap = mk("gaprow", prose)
    gap_index = os.path.join(gap, CONTAINER, "archive", "README.md")
    write(gap_index, read(gap_index).replace(
        "| `st0/` | 0001–0001 | 2026-10-01 ~ 2026-10-01 | 1 篇 | 人工 |",
        "| `ops/lore-tooling/` | 0071–0076 | 2026-10-12 ~ 2026-10-14 | 6 篇 · 自家工具 "
        "| 按插件拆主题线（`0079`/`0080`） |"))
    # **直接摆盘**，不走 `archive --from 71 --to 76`：`add_entry()` 只能加比现有行更大的
    # 篇号，而这里要的正是"同目录里还有 71–76 这六篇"这个事实。写出六篇，让磁盘说真话。
    # ⚠ 只摆这六篇：`0103` / `0104` 要**真的走一遍 archive**（它们是本次选中的那批），
    # 提前摆进目录的话磁盘就成 10 篇了 —— 这个夹具要验的是"选中 2 篇、而目录里共 8 篇"。
    stage_dir = os.path.join(gap, CONTAINER, "archive", "ops", "lore-tooling")
    os.makedirs(stage_dir, exist_ok=True)
    for n in (71, 72, 73, 74, 75, 76):
        write(os.path.join(stage_dir, f"{n:04d}-gap{n}.md"), entry(f"{n:04d}", f"G{n}", "2026-10-16"))
    for n in (103, 104):
        add_entry(gap, n, "2026-10-16")
        run(gap, "archive", "--stage", "archive/ops/lore-tooling",
            "--from", str(n), "--to", str(n))
    got = read(gap_index)
    row = next((l for l in got.splitlines() if "lore-tooling" in l), "")
    ok("0071、0072、0073、0074、0075、0076、0103、0104" in row,
       "a sparse row lists every entry (no range swallowing the gap)", row)
    ok("| 8 篇" in row, "and the count is the 8 records on disk, not the span 34", row)
    ok("0071–0104" not in row, "nor is the numbers cell collapsed into one range", row)
    # 判据要能从**行本身**看出来：把这行的篇号格解回编号，个数必须等于磁盘篇数。
    # 旧实现在这里给 34（区间展开成跨度）—— 逐字比"8 篇"会漏掉这一半。
    ok(len(JOURNAL.l_entry_nums(row)) == 8,
       "the numbers cell parses back to exactly the 8 records on disk",
       f"{len(JOURNAL.l_entry_nums(row))} 个编号：{row}")

    # H) **写在册数之内的那一批**：同目录磁盘上另有记录、而本次没选中它们
    #    （手工搬进去的、上一轮归档的）。写入侧从前只看得见"本次选中"的那几个号，
    #    于是把这一行改写成 2 篇，而磁盘上是 10 篇 —— 它自己写下一行让 `check` 判红的记录。
    #    判据：数字必须跟着**磁盘**走（10），不跟本次选中的走（2）。
    tmp = mk("diskdrift", prose)
    dd_index = os.path.join(tmp, CONTAINER, "archive", "README.md")
    dd_dir = os.path.join(tmp, CONTAINER, "archive", "st9")
    os.makedirs(dd_dir, exist_ok=True)
    for n in (1, 2, 3, 4, 5, 6, 7, 8):          # 已经在册、但本次不会选中
        write(os.path.join(dd_dir, f"{n:04d}-old{n}.md"), entry(f"{n:04d}", f"O{n}", "2026-10-01"))
    for n in (9, 10):                            # 本次要归档的
        add_entry(tmp, n, "2026-10-02")
    run(tmp, "archive", "--stage", "archive/st9", "--from", "9", "--to", "10")
    dd = read(dd_index)
    ddrow = next((l for l in dd.splitlines() if "`st9/`" in l), "")
    ok("| 10 篇" in ddrow,
       "the count follows what is on disk, not just the batch that was picked", ddrow)
    ok("0001–0010" in ddrow, "and the numbers cell covers the whole directory", ddrow)
    r = run(tmp, "check", "--strict")
    ok("标着" not in (r.stdout + r.stderr) and "篇号格" not in (r.stdout + r.stderr),
       "the row the tool just wrote is not one check would flag", r.stdout + r.stderr)

    ok("按插件拆主题线" in row,
       "the human-written 归档判据 cell survives the merge (not reset to the default)", row)
    ok(got.count("lore-tooling") == 1, "the sparse stage still occupies exactly one row", got)
    ok("人写的自述，工具不许动" in got and "这段也必须在" in got,
       "and the prose around the table is still untouched", got)

    # J) 归档目录里全是**日期式**记录：那一行不参与篇号/篇数两条核对（2026-10-17 修）。
    #    判据从前拿 `NUM_NAME_RE` 自己匹配磁盘文件名，把 `2026-09-01-a.md` 读成「编号 2026」，
    #    `set()` 一去重恒为 1 —— 于是在一个**正确**的容器上报「标着 3 篇，磁盘上是 1 篇」，
    #    `--strict` 直接判红（H5）。日期式记录没有篇号、`archive` 也搬不动它们（它只认编号式），
    #    所以这一节只数编号式：目录里一篇编号式都没有时，没有可比的东西，跳过。
    #    ⚠ 夹具必须**只有**日期式记录：混着编号式时 `on_disk` 非空，走的不是这条分支。
    datefix = mk("datedir", prose)
    date_index = os.path.join(datefix, CONTAINER, "archive", "README.md")
    date_dir = os.path.join(datefix, CONTAINER, "archive", "dates")
    os.makedirs(date_dir, exist_ok=True)
    for i, slug in enumerate(("alpha", "beta", "gamma"), 1):
        day = f"2026-09-0{i}"
        write(os.path.join(date_dir, f"{day}-{slug}.md"), entry(day, slug.title(), day))
    write(date_index, read(date_index).replace(
        "| `st0/` | 0001–0001 | 2026-10-01 ~ 2026-10-01 | 1 篇 | 人工 |",
        "| `st0/` | 0001–0001 | 2026-10-01 ~ 2026-10-01 | 1 篇 | 人工 |\n"
        "| `dates/` | 2026-09-01 ~ 2026-09-03 | 2026-09-01 ~ 2026-09-03 | 3 篇 | 阶段收口 |"))
    r = run(datefix, "check", "--strict")
    out = r.stdout + r.stderr
    ok("标着" not in out and "篇号格" not in out,
       "a date-form-only stage directory is not counted against its table row", out)
    ok("却没有这一行" not in out,
       "and the row that does mention it keeps the reverse check quiet", out)


def status_blocks_phase(parent: str) -> None:
    """台账里**两个**「当前状态」块时，写命令（`status --roll` / `--set`）不许动（2026-10-16）；
    只读的 `status` 照常打印（2026-10-17 补 —— 守卫从前连读一起挡了）。

    真实踩坑：给台账加了一块新的「当前状态（第二轮）」之后，台账里就有了两个块。
    `status --roll` 按"第一个块"操作 —— 把**老的那块**搬进历史、原地留一个**空骨架**；
    再跑一次又把刚写的空骨架搬一遍。两次跑完两块真状态都不见了，台账里只剩空模板，
    而每条命令都报成功。`check` 会拦住这个状态（ERROR：只能有一个状态块），
    但**入口**不该把容器推进去 —— 所以两条路都先拒、并指名那块旧块该去哪。
    """
    root = os.path.join(parent, "statusblocks")
    os.makedirs(os.path.join(root, CONTAINER, "lessons"))
    write(os.path.join(root, CONTAINER, "lessons", "README.md"), "# L\n")
    idx = os.path.join(root, CONTAINER, "README.md")

    # ① 只有一个块：命令照常工作（别把正常路径一起挡了）
    write(idx, "# N\n\n## 文件索引\n\n| 文件 | 方面 |\n|---|---|\n\n"
               "## 当前状态（2026-10-01）\n\n- 阶段 / 版本：旧\n")
    r = run(root, "status", "--roll", "--dry-run")
    ok(r.returncode == 0, "one status block: --roll still works", r.stdout + r.stderr)

    # ② 两个块：两条路都拒，且**不动文件**
    two = ("# N\n\n## 文件索引\n\n| 文件 | 方面 |\n|---|---|\n\n"
           "## 当前状态（2026-10-01）\n\n- 阶段 / 版本：旧\n\n"
           "## 当前状态（2026-10-02）\n\n- 阶段 / 版本：新\n")
    write(idx, two)
    before_text = read(idx)
    r = run(root, "status", "--roll")
    ok(r.returncode != 0 and "2 个" in (r.stdout + r.stderr),
       "two status blocks: --roll refuses instead of cycling them", r.stdout + r.stderr)
    r2 = run(root, "status", "--set", "阶段=测试")
    ok(r2.returncode != 0 and "2 个" in (r2.stdout + r2.stderr),
       "two status blocks: --set refuses too", r2.stdout + r2.stderr)
    ok(read(idx) == before_text, "and neither of them touched the ledger", read(idx))
    ok(not os.path.exists(os.path.join(root, CONTAINER, "STATE-HISTORY.md")),
       "nor did they start a state-history file")

    # ③ 但**只读**的那条路不许一起挡（2026-10-17 修）：`status` 不带参数只打印，
    # 而"怎么会有两个块"第一步正是想看看到底是哪两块。从前守卫在读之前无条件退 1，
    # 于是最需要这条命令的那个人看不到任何东西。判据三条：退 0、印出来的是**第一块**、
    # 文件一个字节没动（已由上面 after 那次读取证明，这里再钉一次"就是没写"）。
    r3 = run(root, "status")
    ok(r3.returncode == 0,
       "two status blocks: the read-only `status` still prints instead of refusing",
       r3.stdout + r3.stderr)
    ok("阶段 / 版本：旧" in r3.stdout,
       "and it prints the first block (which is the one find_labeled_section picks)",
       r3.stdout)
    ok(read(idx) == before_text, "reading status does not write the ledger", read(idx))


def appendix_phase(parent: str) -> None:
    """审查报告 §附录那几条的常驻判据（2026-10-15）。

    附录那几条的共同点是"看着像问题"：光读代码只能得出"代码是这样写的"，得不出
    "这件事会不会真的发生"。所以那时先把每一条写成可执行判据（`work_log/logs/eng/checks/probe-appendix-5.py`），
    该修的修掉，再把判据钉成这里的行为断言：

      ① `status --set` 命中重复字段时**每一行**都要改（原来命中第一行就 break，
         块里同时印着新旧两个值，命令却报成功）；空手而归还**不许**改文件、不许报成功。
      ② `todo --done ""` 要报错退 1（空串是假值，原来会静默掉进列清单分支并退 0）。
      ③ `index compact` 跳过任何一个小节都要说明原因（层级不符 / 目录里有活跃记录）——
         只打印「折叠 0 个小节」等于告诉用户"没得折"。
      ④ `memory add` 撞上已存在的 id 只拒绝，**不去改**那条已存在条目的 `cited-by`。
    """
    def make_fixture(name: str, ledger: str, extra=None) -> str:
        root = os.path.join(parent, name)
        os.makedirs(os.path.join(root, CONTAINER))
        for rel, text in (extra or {}).items():
            write(os.path.join(root, CONTAINER, rel), text)
        write(os.path.join(root, CONTAINER, "README.md"), ledger)
        return root

    def skeleton(index: str = "", todos: str = "- [ ] x", status: str = "- 阶段：v1") -> str:
        return (f"# P\n\n## 文件索引\n\n{index}\n"
                f"## 待办（滚动清单）\n\n{todos}\n\n"
                f"## 当前状态（2026-10-15）\n\n{status}\n")

    def ledger_text(root: str) -> str:
        return read(os.path.join(root, CONTAINER, "README.md"))

    # ① 状态块里的重复字段 + "空手而归" ------------------------------------
    dup = make_fixture("appendix-dup-status",
                       skeleton(status="- 阶段：v1\n- 阶段：v0（手滑复制的那行）\n- 版本：1.0"))
    r = run(dup, "status", "--set", "阶段=v2")
    ok(r.returncode == 0 and ledger_text(dup).count("- 阶段：v2") == 2,
       "status --set 改掉重复字段的每一行", r.stdout + ledger_text(dup))
    ok("v0" not in ledger_text(dup),
       "块里不留旧值（不会再同时印着新旧两个状态）", ledger_text(dup))

    # ① 多行字段：--set 换值时**旧续行必须一起清掉**（2026-10-18 实测：只换首行会把
    #    旧值的尾巴留在新值下面，块里同时印着新旧两段状态）。
    cont = make_fixture("appendix-status-continuation",
                        skeleton(status="- 阶段：v1\n  旧值的第二行续写\n  旧值的第三行\n- 迭代：1"))
    r = run(cont, "status", "--set", "阶段=一句话的新状态")
    txt = ledger_text(cont)
    ok(r.returncode == 0 and txt.count("- 阶段：一句话的新状态") == 1,
       "status --set replaces a multi-line field's value", r.stdout + txt)
    ok("旧值的第二行" not in txt and "旧值的第三行" not in txt,
       "status --set drops the old continuation lines (no stale tail under the new value)",
       txt)
    ok("- 迭代：1" in txt and txt.index("- 迭代：1") > txt.index("- 阶段："),
       "the next field survives the continuation cleanup and keeps its order", txt)

    noop = make_fixture("appendix-noop-status", skeleton(status="- 阶段：v1"))
    before = ledger_text(noop)
    r = run(noop, "status", "--set", "阶段")
    ok(r.returncode == 1 and "没有任何字段被更新" in r.stdout and ledger_text(noop) == before,
       "status --set 空手而归：退 1、明说、文件一字不动", r.stdout)
    r = run(noop, "status", "--date", "2026-10-16")
    ok(r.returncode == 0 and "（2026-10-16）" in ledger_text(noop),
       "status --date 单独给（字段没变）照样写盘", r.stdout + ledger_text(noop))

    # ① 的后半：dry-run 与真跑**同判**（第二轮审查 §附录 (a) 的小瑕疵）--------
    now = ledger_text(noop)
    r = run(noop, "status", "--dry-run", "--set", "阶段")
    ok(r.returncode == 1 and "没有任何字段会被更新" in r.stdout and "将更新：" not in r.stdout,
       "status --dry-run 空手而归：也退 1，不再打印一句空的「将更新」", r.stdout)
    r = run(noop, "status", "--dry-run", "--set", "阶段=v3")
    ok(r.returncode == 0 and "[dry-run] 将更新：阶段" in r.stdout and ledger_text(noop) == now,
       "status --dry-run 真会改的那种照旧退 0、并且不写盘", r.stdout)

    # ② `--done` 的空串 ----------------------------------------------------
    todo_root = make_fixture("appendix-empty-done", skeleton(todos="- [ ] alpha\n- [ ] beta"))
    r = run(todo_root, "todo", "--done", "")
    ok(r.returncode == 1 and "ERROR" in r.stdout and "[x]" not in ledger_text(todo_root),
       'todo --done "" 报错退 1：不静默列清单、也不乱勾', r.stdout)
    r = run(todo_root, "todo", "--done", "alpha")
    ok(r.returncode == 0 and "- [x] alpha" in ledger_text(todo_root),
       "todo --done 给了子串照旧勾得上", r.stdout)

    # ③ `index compact` 的每一次跳过都要有说明 -----------------------------
    nested = ("### stage-one/stage-two\n\n"
              "| [stage-one/stage-two/](stage-one/stage-two/) | 两级归档 |\n\n"
              "### stage-three\n\n"
              "| [stage-three/](stage-three/) | 目录里有一篇不是记录 |\n\n"
              "### stage-four\n\n"
              "| [0009-live.md](0009-live.md) | 活跃记录（住在容器根上） |\n\n")
    comp = make_fixture("appendix-compact-silent", skeleton(index=nested), extra={
        os.path.join("stage-one", "stage-two", "0001-a.md"): entry("0001", "A", "2020-01-01"),
        os.path.join("stage-three", "notes.md"): "不是记录。\n",
        "0009-live.md": entry("0009", "Live", "2026-10-15"),
    })
    r = run(comp, "index", "compact")
    ok("折叠 0 个小节" in r.stdout, "默认 --depth 1 下这三节一个都折不动", r.stdout)
    ok("stage-one/stage-two" in r.stdout and "--depth 2" in r.stdout,
       "层级不符的小节说清要加 --depth 2（原来完全静默）", r.stdout)
    ok("stage-three" in r.stdout,
       "目录里有活跃记录的那一节也说了原因（原来静默）", r.stdout)
    ok("stage-four" in r.stdout, "文件目标是活跃记录的那一节照旧说原因", r.stdout)
    r = run(comp, "index", "compact", "--dry-run", "--depth", "2")
    ok("折叠 1 个小节" in r.stdout and "stage-one/stage-two" in r.stdout,
       "加上 --depth 2 之后它确实折得动（证明上面那节不是「没得折」）", r.stdout)

    # ③ 的后半：一个都没折时也要有话说（第二轮审查 §附录 (d) 的小瑕疵）------
    bare = make_fixture("appendix-compact-bare", skeleton(index=""))
    bare_before = ledger_text(bare)
    r = run(bare, "index", "compact")
    ok(r.returncode == 0 and "没有可折叠的小节" in r.stdout and "多行小节" in r.stdout,
       "index compact 这层深度下没有可折的小节：说清是「没有」而不是只说「折叠 0 个」，退 0（幂等）",
       r.stdout)
    ok(ledger_text(bare) == bare_before, "index compact 空手而归时也不写盘", ledger_text(bare))

    # ④ `memory add` 撞上已存在的 id ---------------------------------------
    mem = os.path.join(parent, "appendix-mem")
    write(os.path.join(mem, "01-general.md"),
          "# 01 · general\n\n"
          "- id: dup-claim\n  applies-to: ws\n  state: active\n  source: manual:tested\n"
          "  cited-by: [wl/0001]\n  一条已有引用的教训。\n")
    mem_before = read(os.path.join(mem, "01-general.md"))
    # `--memory` 必须显式给：第一个位置参数是**容器根**（用来认 `--source wl/0001` 这类来源），
    # 不给 `--memory` 时记忆根会落到宿主的真实记忆库上 —— 自测绝不许碰它。
    r = run(mem, "memory", "add", mem, "新的东西。", "--source", "manual:tested",
            "--id", "dup-claim", "--memory", mem)
    ok(r.returncode == 1 and "已经存在" in r.stdout,
       "memory add 撞上已存在的 id：拒绝", r.stdout + r.stderr)
    ok(read(os.path.join(mem, "01-general.md")) == mem_before,
       "而且一个字节都没动（尤其那条的 cited-by）", read(os.path.join(mem, "01-general.md")))
def review2_phase(parent: str) -> None:
    """第二轮审查（`_tmp/worklog-review-2026-10-15.md`）里 CLI 侧的常驻判据（2026-10-15）。

    那一轮的 JS 半边（N1 门禁要无条件钉 `$DSH_HOME`、N2 take 的并发占号）判据在 `publish/worklog/tests/`；
    这里收 CLI 半边：

      · N5-① `reserve_new_record` 不再把"目录根本写不进去"当成"名字被占"（原来要空转一千轮，
        最后在兜底 `write_raw` 抛一个没人接的 `PermissionError`）；`main` 统一报成一句。
      · N5-② `$DSH_WORKLOG_SETTINGS` 现在 CLI 也读 —— 两个进程对"设置文件在哪"同一个口径，
        所以"设置文件里的 `memoryDir` 生效"这条链路能端到端验。
      · N5-③ `write_raw` 保住目标原有的权限位。
      · N5-④ `prune` 跳过坏日期要说出来 —— 断言在 `safety_phase` 的 F9 夹具里。
      · F8     `12-.md` 这种退化名**不再是记录名**（判据与取号对齐），另有一条 WARN 兜着。
    """
    ledger = ("# P\n\n## 文件索引\n\n### 当前\n\n| 文件 | 方面 |\n|---|---|\n"
              "| [0001-a.md](0001-a.md) | 样例 |\n\n"
              "## 待办（滚动清单）\n\n- [ ] x\n\n"
              "## 当前状态（2026-10-15）\n\n- 阶段：v1\n")

    def make_fixture(name: str, extra=None) -> str:
        root = os.path.join(parent, name)
        os.makedirs(os.path.join(root, CONTAINER))
        for rel, text in (extra or {}).items():
            write(os.path.join(root, CONTAINER, rel), text)
        write(os.path.join(root, CONTAINER, "README.md"), ledger)
        return root

    # F8：退化名 `12-.md` 的三处判据必须**同口径** ---------------------------
    deg = make_fixture("review2-degenerate", {
        "12-.md": "# 12 · 退化名\n",
        "0001-a.md": entry("0001", "A", "2026-10-01"),
    })
    ok(JOURNAL.NUM_FILE_RE.match("12-.md") is None
       and not JOURNAL.is_record_name("12-.md")
       and JOURNAL.name_number("12-.md") is None,
       "F8：`12-.md` 在「是不是记录名」与「取不取得出号」上口径一致（都不是/都取不出）",
       f"NUM_FILE_RE={JOURNAL.NUM_FILE_RE.match('12-.md')} "
       f"is_record_name={JOURNAL.is_record_name('12-.md')} "
       f"name_number={JOURNAL.name_number('12-.md')}")
    r = run(deg, "check")
    ok("12-.md" in r.stdout and r.returncode == 0,
       "F8：`check` 点出这种名字（WARN，默认不改退出码）—— 不再静默不可见", r.stdout)
    r = run(deg, "check", "--strict")
    ok(r.returncode == 1, "F8：`--strict` 下它升级成 ERROR，门禁真的拦得住", r.stdout)
    for cmd in ("brief", "stats", "topics"):
        r = run(deg, cmd)
        ok(r.returncode == 0 and "Traceback" not in r.stderr,
           f"F8：`{cmd}` 碰到退化名不崩（原先 TypeError 让 11 个命令全线崩）", (r.stdout + r.stderr)[-200:])

    # N5-①：写不进去 ≠ 名字被占 --------------------------------------------
    try:
        JOURNAL.reserve_new_record(os.path.join(parent, "review2-no-such-dir"), 1, "x", "body\n")
        lifted = None
    except OSError as exc:  # FileNotFoundError 也是 OSError
        lifted = exc
    ok(isinstance(lifted, OSError),
       "N5-①：占名时「目录写不进去」原样抛出去（原来吞成 None，于是空转一千轮）", repr(lifted))

    def boom(_args):
        raise OSError(28, "No space left on device", "x.md")

    saved, JOURNAL.cmd_brief = JOURNAL.cmd_brief, boom
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = JOURNAL.main(["brief", "--root", parent])
    finally:
        JOURNAL.cmd_brief = saved
    out = buf.getvalue()
    ok(rc == 2 and "写不进去" in out and "Traceback" not in out,
       "N5-①：`main` 把 OSError 报成一句「写不进去」并退 2（不再是一屏 traceback）",
       f"rc={rc} out={out!r}")

    # N5-②：`$DSH_WORKLOG_SETTINGS` 决定的设置文件里的 `memoryDir` 要生效 ----
    ws = make_fixture("review2-settings-root", {"0001-a.md": entry("0001", "A", "2026-10-01")})
    from_settings = os.path.join(parent, "review2-mem-from-settings")
    decoy = os.path.join(parent, "review2-mem-decoy")
    os.makedirs(from_settings)
    settings = os.path.join(parent, "review2-settings.json")
    write(settings, json.dumps({"memoryDir": from_settings}, ensure_ascii=False))
    old_env = os.environ.get("DSH_WORKLOG_SETTINGS")
    os.environ["DSH_WORKLOG_SETTINGS"] = settings
    try:
        ok(JOURNAL.host_settings_file() == settings,
           "N5-②：`host_settings_file()` 认 `$DSH_WORKLOG_SETTINGS`（与 lib/index.js 同口径）",
           JOURNAL.host_settings_file())
        ok(JOURNAL.memory_root() == os.path.abspath(from_settings),
           "N5-②：`memory_root()` 因此读到设置文件里的 `memoryDir`", JOURNAL.memory_root())
    finally:
        if old_env is None:
            os.environ.pop("DSH_WORKLOG_SETTINGS", None)
        else:
            os.environ["DSH_WORKLOG_SETTINGS"] = old_env
    # 端到端：真跑一条 `memory add`，不给 `--memory`，让 CLI 自己去设置文件里找根；
    # 同时摆一个 `$DSH_WORKLOG_MEMORY` 诱饵，证明优先级是"设置文件 > 环境变量"。
    r = run_env(ws, {"DSH_WORKLOG_SETTINGS": settings, "DSH_WORKLOG_MEMORY": decoy},
                "memory", "add", ws, "从设置文件里读到根的一条。",
                "--source", "manual:tested", "--id", "settings-root-probe")
    volume = os.path.join(from_settings, "01-general.md")
    ok(r.returncode == 0 and os.path.isfile(volume) and "settings-root-probe" in read(volume),
       "N5-②：条目落进设置文件指定的根（不给 `--memory` 也行）", r.stdout + r.stderr)
    ok(not os.path.exists(decoy),
       "N5-②：并且压过了 `$DSH_WORKLOG_MEMORY`（优先级 2 > 3）", decoy)

    # N5-③：`write_raw` 不该顺手改掉目标的权限位 ---------------------------
    if os.name == "posix":
        target = os.path.join(parent, "review2-mode.md")
        write(target, "原文\n")
        os.chmod(target, 0o600)
        JOURNAL.write_raw(target, "改过的\n")
        mode = stat.S_IMODE(os.stat(target).st_mode)
        ok(mode == 0o600 and read(target) == "改过的\n",
           "N5-③：`chmod 600` 的记录被改写后仍是 600（原来会变成 644）", oct(mode))
    else:
        note("N5-③ write_raw 保住权限位", "本机是 Windows：chmod 只有只读位，这条件验不出来")


def safety_phase(tmp: str) -> None:
    """数据安全：不能静默毁掉非 UTF-8 文件，也不能把 LF 掺进 CRLF 台账。"""
    # 1) 非 UTF-8 目标必须**拒绝写入**，而不是写成 U+FFFD ------------------
    enc = os.path.join(tmp, "encfix")
    os.makedirs(os.path.join(enc, CONTAINER))
    raw = ("# 0001 · A\n\n日期：2026-09-13\n迭代：1\n结论：ok\n\n## 验证\n\n- 方式：x\n- 结果：1\n")
    gbk = os.path.join(enc, CONTAINER, "0001-a.md")
    with open(gbk, "wb") as fh:
        fh.write(raw.encode("gbk"))
    before = read_bytes(gbk)
    r = run(enc, "append", "1", "--section", "更正", "--text", "changed")
    ok(r.returncode != 0, "writing a non-UTF-8 file is refused", r.stdout)
    ok("UTF-8" in r.stdout, "the refusal names the encoding", r.stdout)
    ok("Traceback" not in r.stderr, "the refusal is not a traceback", r.stderr[:200])
    ok(read_bytes(gbk) == before, "the non-UTF-8 file is left byte-identical")

    # 2) status --roll：旧块进**容器根**的 STATE-HISTORY.md，且不掺 LF --------
    crlf = os.path.join(tmp, "crlffix")
    os.makedirs(os.path.join(crlf, CONTAINER))
    idx = ("# P\n\n## 文件索引\n\n### A. St\n\n| 文件 | 方面 |\n|---|---|\n"
           "| [0001-a.md](0001-a.md) | x |\n\n## 待办（滚动清单）\n\n- [ ] x\n\n"
           "## 当前状态（2026-09-13）\n\n- 阶段 / 版本：v1\n- 迭代：1\n")
    ipath = os.path.join(crlf, CONTAINER, "README.md")
    with open(ipath, "wb") as fh:
        fh.write(idx.replace("\n", "\r\n").encode("utf-8"))
    with open(os.path.join(crlf, CONTAINER, "0001-a.md"), "wb") as fh:
        fh.write(entry("0001", "A", "2026-09-13", "1").replace("\n", "\r\n").encode("utf-8"))
    r = run(crlf, "status", "--roll")
    ok(r.returncode == 0, "status --roll exits 0", r.stderr)
    data = read_bytes(ipath)
    ok(data.replace(b"\r\n", b"").count(b"\n") == 0, "status --roll injects no lone LF into a CRLF ledger")
    hist = os.path.join(crlf, CONTAINER, "STATE-HISTORY.md")
    ok(os.path.exists(hist), "status --roll writes STATE-HISTORY.md at the container root", r.stdout)
    ok(not os.path.exists(os.path.join(crlf, CONTAINER, "archive", "STATUS-HISTORY.md")),
       "status --roll does not create an archive/ subdirectory")
    ok("## 当前状态（2026-09-13）" in read(hist), "the replaced status block was moved verbatim", read(hist))

    # 3) 半角括号的状态标题不能被叠加日期 --------------------------------
    en = os.path.join(tmp, "enfix")
    os.makedirs(os.path.join(en, CONTAINER))
    en_idx = ("# English\n\n## Index\n\n### A\n\n| File | Note |\n|---|---|\n"
              "| [0001-a.md](0001-a.md) | a |\n\n## TODO\n\n- [ ] x\n\n"
              "## Status (2026-01-01)\n\n- Stage: v1\n")
    eip = os.path.join(en, CONTAINER, "README.md")
    write(eip, en_idx)
    r = run(en, "status", "--date", "2026-10-01")
    ok(r.returncode == 0, "status --date on a half-width heading exits 0", r.stderr)
    txt = read(eip)
    ok("2026-01-01" not in txt, "the old date is replaced, not nested", txt)
    ok("2026-10-01" in txt, "the new date landed", txt)

    # 4) 归档后，被移动记录自己的出站链接必须仍然有效 --------------------
    arch = os.path.join(tmp, "archfix")
    os.makedirs(os.path.join(arch, CONTAINER))
    os.makedirs(os.path.join(arch, "docs"))
    j = os.path.join(arch, CONTAINER)
    write(os.path.join(j, "README.md"),
          "# P\n\n## 文件索引\n\n### A. St\n\n| 文件 | 方面 |\n|---|---|\n"
          "| [0001-a.md](0001-a.md) | x |\n| [0002-b.md](0002-b.md) | y |\n\n"
          "## 待办（滚动清单）\n\n- [ ] x\n\n## 当前状态（2026-09-13）\n\n- 阶段 / 版本：v1\n")
    write(os.path.join(j, "0001-a.md"),
          "# 0001 · A\n\n日期：2026-09-13\n迭代：1\n结论：ok\n\n"
          "见 [b](0002-b.md)、[idx](README.md)、[设计](../docs/design.md)。\n\n"
          "## 验证\n\n- 方式：`true`\n- 结果：1 passed\n")
    write(os.path.join(j, "0002-b.md"), entry("0002", "B", "2026-09-14", "2"))
    write(os.path.join(arch, "docs", "design.md"), "# design\n")
    r = run(arch, "archive", "--stage", "S", "--from", "1", "--to", "1")
    ok(r.returncode == 0, "archive with outbound links reports no dead link", r.stdout + r.stderr)
    moved = os.path.join(j, "S", "0001-a.md")
    ok(os.path.exists(moved), "the record was archived into <container>/S/")
    targets = re.findall(r"\]\(([^)\s]+)\)", read(moved))
    bad = [t for t in targets
           if not t.startswith(("http", "#", "mailto"))
           and not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(moved), t)))]
    ok(not bad, "every rewritten link from the moved record resolves", f"targets={targets} bad={bad}")

    # 5) lesson add 必须保留 --source，即使正文里提到了别的 wl/ ----------
    lsn = os.path.join(tmp, "lsnfix")
    os.makedirs(os.path.join(lsn, CONTAINER, "lessons"))
    write(os.path.join(lsn, CONTAINER, "README.md"),
          "# L\n\n## 文件索引\n\n### A. St\n\n| 文件 | 方面 |\n|---|---|\n"
          "| [0001-a.md](0001-a.md) | x |\n\n## 待办（滚动清单）\n\n- [ ] x\n\n"
          "## 当前状态（2026-09-13）\n\n- 阶段 / 版本：v1\n")
    write(os.path.join(lsn, CONTAINER, "0001-a.md"), entry("0001", "A", "2026-09-13", "1"))
    write(os.path.join(lsn, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(lsn, CONTAINER, "lessons", "01-topic.md"), "# 01\n\n来源：x。\n\n## 子主题\n\n- a\n")
    r = run(lsn, "lesson", "add", "--volume", "01-topic.md", "--source", "1",
            "--text", "沿用 wl/9999 的写法")
    ok(r.returncode == 0, "lesson add exits 0", r.stderr)
    vol = read(os.path.join(lsn, CONTAINER, "lessons", "01-topic.md"))
    ok("wl/0001" in vol, "lesson add keeps the --source citation", vol)

    # 6) 手写的**不存在的日期**不许把命令掀掉，也不许被说成"文件不是 UTF-8" ----
    #    `ISO_DATE_RE` 只验数字形状（四个数字-两个-两个），`2026-02-30` 能过；真解析要到
    #    `date.fromisoformat` 才失败，而它抛的 `ValueError` 原先被 `main` 一律翻译成
    #    "记录文件必须是 UTF-8" —— 用户照着去转编码，永远修不好（审查报告 F9）。
    badd = os.path.join(tmp, "baddate")
    os.makedirs(os.path.join(badd, CONTAINER, "stage-old"))
    write(os.path.join(badd, CONTAINER, "README.md"),
          "# B\n\n## 文件索引\n\n### A. 归档\n\n| 文件 | 方面 |\n|---|---|\n"
          "| [stage-old/0001-bad.md](stage-old/0001-bad.md) | x |\n"
          "| [stage-old/0002-good.md](stage-old/0002-good.md) | x |\n\n"
          "## 待办（滚动清单）\n\n- [ ] x\n\n## 当前状态（2026-09-13）\n\n- 阶段 / 版本：v1\n")
    write(os.path.join(badd, CONTAINER, "stage-old", "0001-bad.md"),
          entry("0001", "bad", "2026-02-30", "1"))
    write(os.path.join(badd, CONTAINER, "stage-old", "0002-good.md"),
          entry("0002", "good", "2020-01-01", "1"))
    r = run(badd, "prune", "--older-than", "30")
    ok(r.returncode == 0, "prune survives a record whose 日期 does not exist", r.stdout + r.stderr)
    # 同目录里那篇日期合法的老记录必须在候选里 —— 这证明循环真的走到了日期解析那一行，
    # 所以"没崩"不是因为它提前被过滤掉了（否则这条断言是空的）。
    ok("#0002" in r.stdout and "#0001  2026-02-30" not in r.stdout,
       "the neighbour with a valid old date is still a cold-storage candidate", r.stdout)
    ok("UTF-8" not in r.stdout,
       "the impossible date is NOT reported as an encoding problem (F9's wrong diagnosis)", r.stdout)
    ok("Traceback" not in r.stderr, "the impossible date does not traceback", r.stderr[:200])
    # 跳过要说出来（第二轮审查 N5-④）：静默跳过会让"没进候选"看着像"判据说不该进"。
    ok("! 跳过 #0001" in r.stdout and "解析不出来" in r.stdout,
       "prune says out loud why the impossible date was skipped (N5-④)", r.stdout)
    ok(JOURNAL.parse_iso_date("2026-02-30") is None
       and JOURNAL.parse_iso_date("2026-02-28") is not None
       and JOURNAL.parse_iso_date("") is None,
       "parse_iso_date: 形状对但日期不存在 → None；真日期照常解出；空串 → None")
    ok(issubclass(JOURNAL.WriteRefused, ValueError),
       "WriteRefused 继承 ValueError（既有调用方的 `except ValueError` 语义不变）")


def legacy_phase(parent: str) -> None:
    """旧布局只读回退：`journal/` + 顶层 `lessons/` 不迁移、不改名、照样能用。"""
    lg = os.path.join(parent, "legacy")
    os.makedirs(os.path.join(lg, "journal", "archive", "stageL"))
    os.makedirs(os.path.join(lg, "lessons"))
    write(os.path.join(lg, "journal", "README.md"),
          "# L\n\n## 文件索引\n\n### A. 归档\n\n| 文件 | 方面 |\n|---|---|\n"
          "| [archive/stageL/0002-old.md](archive/stageL/0002-old.md) | y |\n\n"
          "### B. 当前\n\n| 文件 | 方面 |\n|---|---|\n"
          "| [0001-a.md](0001-a.md) | x |\n\n"
          "## 待办（滚动清单）\n\n- [ ] x\n\n## 当前状态（2026-09-13）\n\n- 阶段 / 版本：v1\n")
    write(os.path.join(lg, "journal", "0001-a.md"), entry("0001", "A", "2026-09-13", "1"))
    write(os.path.join(lg, "journal", "archive", "stageL", "0002-old.md"),
          entry("0002", "Old", "2020-01-01", "-"))
    write(os.path.join(lg, "journal", "archive", "STATUS-HISTORY.md"),
          "# 状态历史\n\n## 当前状态（2026-01-01）\n\n- 阶段 / 版本：v0\n")
    write(os.path.join(lg, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(lg, "lessons", "01-topic.md"),
          "# 01 · T\n\n来源：wl/0001。\n\n- **s**：a。根因：b。做法：c。（`wl/0001`）\n")

    r = run(lg, "outline")
    ok(r.returncode == 0 and re.search(r"^0001\t", r.stdout, re.M) is not None
       and "01-topic" not in r.stdout,
       "legacy: journal/ is picked up as the container, lessons/ is not a record", r.stdout)
    r = run(lg, "brief", "--entries", "9")
    ok("active 1 / archive 1" in r.stdout,
       "legacy: archive/<stage>/ still counts as archived", r.stdout)
    r = run(lg, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "legacy: check --strict clean", r.stdout + r.stderr)
    r = run(lg, "lesson", "add", "--volume", "01-topic.md", "--source", "1",
            "--text", "旧布局也能写经验")
    ok(r.returncode == 0, "legacy: the top-level lessons/ is resolved", r.stdout + r.stderr)
    r = run(lg, "index", "compact")
    ok("[archive/stageL/](archive/stageL/)" in read(os.path.join(lg, "journal", "README.md")),
       "legacy: archive/<stage>/ rows still fold", r.stdout)

    r = run(lg, "status", "--roll")
    ok(os.path.exists(os.path.join(lg, "journal", "archive", "STATUS-HISTORY.md"))
       and "2026-09-13" in read(os.path.join(lg, "journal", "archive", "STATUS-HISTORY.md")),
       "legacy: the existing archive/STATUS-HISTORY.md is reused, not forked", r.stdout)
    ok(not os.path.exists(os.path.join(lg, "journal", "STATE-HISTORY.md")),
       "legacy: no second history file is created at the container root")

    # 旧名与显式命名都要能指到容器
    for flag in ("--journal", "--work-log"):
        r = run(lg, "outline", flag, "journal")
        ok(re.search(r"^0001\t", r.stdout, re.M) is not None,
           f"legacy: {flag} names the container explicitly", r.stdout + r.stderr)
    named = os.path.join(parent, "named")
    os.makedirs(os.path.join(named, "records"))
    write(os.path.join(named, "records", "README.md"),
          "# N\n\n## 文件索引\n\n### A\n\n| 文件 | 方面 |\n|---|---|\n"
          "| [0001-a.md](0001-a.md) | x |\n\n## 待办（滚动清单）\n\n- [ ] x\n\n"
          "## 当前状态（2026-09-13）\n\n- 阶段 / 版本：v1\n")
    write(os.path.join(named, "records", "0001-a.md"), entry("0001", "A", "2026-09-13", "1"))
    r = run(named, "outline", "--work-log", "records")
    ok(re.search(r"^0001\t", r.stdout, re.M) is not None,
       "--work-log accepts a custom container name", r.stdout + r.stderr)
    # 容器名与经验目录名都改名后，经验分册仍不能被当成记录
    os.makedirs(os.path.join(named, "records", "notes"))
    write(os.path.join(named, "records", "notes", "01-topic.md"), "# 01 · T\n\n来源：wl/0001。\n")
    r = run(named, "outline", "--work-log", "records", "--lessons", "notes")
    ok(re.search(r"^0001\t", r.stdout, re.M) is not None and "01-topic" not in r.stdout,
       "a renamed --lessons dir is still excluded from record discovery", r.stdout + r.stderr)


def doc_phase(tmp: str) -> None:
    """文档与代码一致性：模板落盘后必须能被自己的门禁接受，且引用的数字不许过期。

    `references/templates.md` 里的台账模板是给人复制的，一旦里面的示例行被
    `check` 判成死链，照文档初始化出来的项目第一次 `check` 就是红的——而
    SKILL.md 承诺"0 篇记录也应通过"。这条用例把那个承诺钉住。

    同时校验文档里"自测 N 项"的 N 与实际断言数一致：本技能自己就有一条
    "改一处漏一处"的反模式，文档写死一个过期数字正是同一个毛病（实测踩过：
    SKILL.md 停在 57，实际已经 95）。
    """
    templates = os.path.join(os.path.dirname(HERE), "references", "templates.md")
    if not os.path.isfile(templates):
        # 只装了 scripts/ 的部署（例如从发布包单独取脚本）没有文档可校验。
        return

    # 文档里的"自测 N 项"由 main() 在所有用例跑完后核对（见 doc_count_claims
    # 与 main 末尾）——放这里数不出总数，只会自指。

    text = read(templates)
    blocks = re.findall(r"```markdown\n(.*?)```", text, re.S)
    ledger = next((b for b in blocks if "## 文件索引" in b), None)
    ok(ledger is not None, "templates.md still publishes a ledger template")
    if ledger is None:
        return

    # 模板里的示例索引行指向不存在的文件；照文档说明删掉它。
    sample = re.search(r"^\|\s*\[[^\]]+\]\([^)]+\.md\)\s*\|.*$", ledger, re.M)
    ok(sample is not None, "ledger template still shows an index-row example")
    cleaned = ledger if sample is None else ledger.replace(sample.group(0), "")
    date = re.search(r"当前状态（([^）]+)）", cleaned)
    cleaned = cleaned.replace("<项目>", "Demo").replace("<阶段名>", "A. Stage")
    if date:
        cleaned = cleaned.replace(date.group(1), "2026-09-13")
    cleaned = re.sub(r"<[^>\n]+>", "x", cleaned)
    cleaned = re.sub(r"^- \[x\].*$", "", cleaned, flags=re.M)

    root = os.path.join(tmp, "docfix")
    os.makedirs(os.path.join(root, CONTAINER, "lessons"), exist_ok=True)
    write(os.path.join(root, CONTAINER, "README.md"), cleaned.rstrip("\n") + "\n")
    # 工作流 A 要求同时落 lessons/README.md；台账模板会链接到它。
    write(os.path.join(root, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    # 分册里不写 `wl/NNNN` 引用：此夹具一篇记录都没有，--strict 会判来源悬空。
    # 但要带一句「来源」说明，否则 --strict 判它连来源口径都没有。
    write(os.path.join(root, CONTAINER, "lessons", "01-topic.md"),
          "# 01 · 起步约定\n\n来源：本册在项目初始化时建立，等第一篇记录收口后再回填 `wl/NNNN`。\n"
          "\n## 子主题\n\n- **尚未提炼**：暂无条目。\n")

    r = run(root, "check", "--quiet")
    ok(r.returncode == 0, "a ledger built from templates.md passes a plain check",
       r.stdout + r.stderr)
    r = run(root, "check", "--strict", "--quiet", "--legacy", "")
    ok(r.returncode == 0, "and also passes check --strict", r.stdout + r.stderr)

    # 骨架里日期还是 `YYYY-MM-DD` 占位符时，也必须过得了 --strict
    fresh = os.path.join(tmp, "docfresh")
    os.makedirs(os.path.join(fresh, CONTAINER, "lessons"), exist_ok=True)
    write(os.path.join(fresh, CONTAINER, "README.md"),
          cleaned.replace("2026-09-13", "YYYY-MM-DD").rstrip("\n") + "\n")
    write(os.path.join(fresh, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(fresh, CONTAINER, "lessons", "01-topic.md"),
          "# 01 · 起步约定\n\n来源：初始化时建立，等第一篇记录收口后回填。\n\n## 子主题\n\n- 暂无条目。\n")
    r = run(fresh, "check", "--strict", "--quiet", "--legacy", "")
    ok(r.returncode == 0, "a brand-new skeleton with the YYYY-MM-DD placeholder passes --strict",
       r.stdout + r.stderr)


def mode_phase(parent: str) -> None:
    """记录精细度（`mode`）：默认档 / 切换 / 拒绝未知值 / 四档都在 / 老台账不受影响。

    最关键的一条是最后一组：**精细度只放宽「要不要另起一篇」，不放宽验证要求**——
    四档下「缺验证小节」都必须是 WARN，不能被粗档位放行。粗档位额外担一条义务
    （写明「未记录」什么），这条只在显式设成粗档位时才要求。
    """
    # 老台账（没有 `精细度` 字段）：默认档 + 不出新错 ----------------------
    legacy = os.path.join(parent, "modelegacy")
    os.makedirs(os.path.join(legacy, CONTAINER, "lessons"))
    write(os.path.join(legacy, CONTAINER, "README.md"), MODE_LEGACY_INDEX)
    write(os.path.join(legacy, CONTAINER, "0001-work.md"), MODE_WORK)
    write(os.path.join(legacy, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(legacy, CONTAINER, "lessons", "01-topic.md"),
          "# 01 · T\n\n来源：wl/0001。\n\n## 子主题\n\n- **s**：a。根因：b。做法：c。（`wl/0001`）\n")
    lidx = os.path.join(legacy, CONTAINER, "README.md")

    r = run(legacy, "mode")
    ok(r.returncode == 0 and r.stdout.startswith("full"),
       "mode: a ledger without 精细度 reports the default full", r.stdout + r.stderr)
    ok("默认" in r.stdout, "mode: the report says the value is the default", r.stdout)
    ok("精细度" not in read(lidx), "mode (read-only) writes nothing to the ledger")
    # 默认档是 `full`，不是 `session`：实测原型有 34 篇落在同一天，`session` 会把它们
    # 并成一篇、埋掉 34 个可独立查阅的单元（见 references/analysis.md 与 worklog 规格书 §十一）。
    ok(MODE_DEFAULT_CONST == "full", "MODE_DEFAULT is full (one entry = one deliverable unit)",
       MODE_DEFAULT_CONST)

    r = run(legacy, "check", "--strict", "--quiet", "--legacy", "")
    ok(r.returncode == 0, "a ledger without 精细度 still passes check --strict", r.stdout + r.stderr)
    r = run(legacy, "lint", "--strict", "--quiet", "--legacy", "")
    ok(r.returncode == 0, "a ledger without 精细度 still passes lint --strict", r.stdout + r.stderr)

    # 切换：写入 / 读回 / 原因 ---------------------------------------------
    r = run(legacy, "mode", "--set", "digest", "--why", "阶段收口")
    ok(r.returncode == 0, "mode --set exits 0", r.stdout + r.stderr)
    ok("- 精细度：digest（原因：阶段收口）" in read(lidx),
       "mode --set writes the value and the reason onto the status field", read(lidx))
    r = run(legacy, "mode")
    ok(r.stdout.startswith("digest"), "mode reads the value back", r.stdout)
    ok("阶段收口" in r.stdout, "mode prints the recorded reason", r.stdout)
    # 提示行里的"当前"必须是**生效档位**：曾经写成常量 `full`，于是台账是 digest 时
    # 同一条输出自相矛盾（上一行 digest、下一行"当前 full"）——整体功能实跑抓到的。
    ok("（当前 digest）" in r.stdout and "（当前 full）" not in r.stdout,
       "mode's hint line names the effective tier, not the built-in default", r.stdout)

    # brief / outline 带着这个多出来的字段照常渲染
    r = run(legacy, "brief", "--entries", "1")
    ok("精细度：digest（原因：阶段收口）" in r.stdout, "brief renders the extra status field", r.stdout)
    r = run(legacy, "outline")
    ok(r.returncode == 0, "outline still runs with the extra field present", r.stdout + r.stderr)

    # 反复切换只改那一行，不长出第二个字段
    for value in ("full", "milestone", "session"):
        run(legacy, "mode", "--set", value)
    ok(read(lidx).count("- 精细度") == 1, "repeated mode --set keeps exactly one 精细度 field")
    fields_n = [l for l in read(lidx).splitlines() if l.startswith("- ") and "：" in l]
    ok(len(fields_n) == 8, "the status block has 8 fields after mode --set", f"{fields_n}")

    # `--why` 只补原因，不动档位
    r = run(legacy, "mode", "--why", "这次记详细点")
    ok(r.returncode == 0 and "- 精细度：session（原因：这次记详细点）" in read(lidx),
       "mode --why records the reason without changing the mode", r.stdout + read(lidx))

    # 四档都收；中文别名规范化成拉丁值 --------------------------------
    for value in ("full", "session", "digest", "milestone"):
        r = run(legacy, "mode", "--set", value)
        ok(r.returncode == 0 and f"- 精细度：{value}" in read(lidx),
           f"mode --set accepts {value}", r.stdout + r.stderr)
        r = run(legacy, "mode")
        ok(r.stdout.startswith(value), f"mode reads {value} back", r.stdout)
    r = run(legacy, "mode", "--set", "摘要")
    ok(r.returncode == 0 and "- 精细度：digest" in read(lidx),
       "mode --set accepts the Chinese alias and normalises it to the latin value",
       r.stdout + read(lidx))

    # 未知值必须拒绝，且非零退出 ------------------------------------------
    before = read(lidx)
    r = run(legacy, "mode", "--set", "详细点")
    ok(r.returncode != 0, "mode --set rejects an unknown value with a non-zero exit", r.stdout)
    ok(r.returncode == 2, "the rejection uses exit code 2 (same as a bad argument)", r.stdout)
    ok("认不出的精细度" in r.stdout and "full" in r.stdout and "milestone" in r.stdout,
       "the rejection names the bad value and lists the accepted modes", r.stdout)
    ok("Traceback" not in r.stderr, "the rejection is not a traceback", r.stderr[:200])
    ok(read(lidx) == before, "the rejected value changes nothing")
    r = run(legacy, "mode", "--set", "session", "--dry-run")
    ok(r.returncode == 0 and read(lidx) == before, "mode --set --dry-run changes nothing", r.stdout)

    # 没有容器时 `mode --set` 必须报错退出 ---------------------------------
    r = run(parent, "mode", "--set", "full", os.path.join(parent, "no-such-project"))
    ok(r.returncode != 0 and "找不到记录容器" in r.stdout,
       "mode --set on a missing container reports the same missing-container error",
       r.stdout + r.stderr)

    # `精细度` 就是状态块字段：`status --set` 直接改它也落到同一行 ----------
    idx_path = lidx
    write(idx_path, MODE_INDEX)
    r = run(legacy, "status", "--set", "精细度=full")
    ok(r.returncode == 0 and "- 精细度：full" in read(idx_path),
       "status --set 精细度 lands on the existing field", r.stdout + read(idx_path))
    ok(read(idx_path).count("- 精细度") == 1, "status --set 精细度 adds no parallel field",
       read(idx_path))
    r = run(legacy, "mode")
    ok(r.stdout.startswith("full"), "mode reads a value written by status --set", r.stdout)

    # status --roll 的新骨架必须有 8 个固定字段（含 `精细度`）--------------
    write(idx_path, MODE_INDEX)
    write(os.path.join(legacy, CONTAINER, "0002-more.md"), MODE_ROLL_ENTRY)
    r = run(legacy, "status", "--roll", "--date", "2026-09-15")
    ok(r.returncode == 0, "status --roll exits 0 with 精细度 in the block", r.stdout + r.stderr)
    rolled = read(idx_path)
    fields = [l.split("：")[0].removeprefix("- ").strip()
              for l in rolled.splitlines() if l.startswith("- ") and "：" in l]
    ok(len(fields) == 8, "the rolled status skeleton carries 8 fixed fields", f"{fields}")
    ok("精细度" in fields, "精细度 is one of them", f"{fields}")
    ok("- 精细度：" in rolled, "the new skeleton leaves 精细度 empty, not pre-filled", rolled)

    # ---- 关键不变量：验证要求在**每一档**都成立 --------------------------
    # 在 MODE_WORK 上删掉验证小节，四档逐个确认 `check` 仍报「缺验证」。
    for value in ("full", "session", "digest", "milestone"):
        probe = os.path.join(parent, f"modeverify-{value}")
        os.makedirs(os.path.join(probe, CONTAINER, "lessons"))
        write(os.path.join(probe, CONTAINER, "README.md"),
              MODE_INDEX.replace("- 精细度：session", f"- 精细度：{value}"))
        # 正文里连「验证」二字都不留，确保报的是「缺验证小节」而不是别的原因。
        write(os.path.join(probe, CONTAINER, "0001-work.md"),
              MODE_WORK.replace("## 四、验证", "## 四、收尾"))
        write(os.path.join(probe, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
        write(os.path.join(probe, CONTAINER, "lessons", "01-topic.md"),
              "# 01 · T\n\n来源：wl/0001。\n\n## 子主题\n\n- **s**：a。根因：b。做法：c。（`wl/0001`）\n")
        r = run(probe, "check", "--quiet", "--legacy", "")
        ok("缺验证类小节" in r.stdout,
           f"verify section is still required at mode={value}", r.stdout + r.stderr)
        r = run(probe, "check", "--strict", "--quiet", "--legacy", "")
        ok(r.returncode != 0, f"and it still fails --strict at mode={value}", r.stdout + r.stderr)

    # ---- 粗档位的额外义务：写明「未记录」什么 ----------------------------
    coarse = os.path.join(parent, "modecoarse")
    os.makedirs(os.path.join(coarse, CONTAINER, "lessons"))
    write(os.path.join(coarse, CONTAINER, "README.md"),
          MODE_INDEX.replace("- 精细度：session", "- 精细度：digest"))
    write(os.path.join(coarse, CONTAINER, "0001-work.md"), MODE_WORK)
    write(os.path.join(coarse, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(coarse, CONTAINER, "lessons", "01-topic.md"),
          "# 01 · T\n\n来源：wl/0001。\n\n## 子主题\n\n- **s**：a。根因：b。做法：c。（`wl/0001`）\n")
    cidx = os.path.join(coarse, CONTAINER, "README.md")

    r = run(coarse, "lint")
    ok("未记录" in r.stdout, "lint: a coarse-mode record without 未记录 is flagged", r.stdout)
    ok(r.returncode == 0, "lint: that flag is a WARN, not an ERROR", r.stdout)
    r = run(coarse, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "check --strict ignores the 未记录 obligation (no new hard error)",
       r.stdout + r.stderr)

    # 补上「未记录」（条目式）后放行
    write(os.path.join(coarse, CONTAINER, "0001-work.md"), MODE_WORK + """
## 五、未记录

- 本轮的两处配置调整，见提交 abc1234。
""")
    r = run(coarse, "lint", "--quiet")
    ok(r.returncode == 0, "lint: 未记录 as its own section satisfies the obligation", r.stdout + r.stderr)

    # 换成行内一句也认
    write(os.path.join(coarse, CONTAINER, "0001-work.md"),
          MODE_WORK + "\n未记录：本轮的两处配置调整，见提交 abc1234。\n")
    r = run(coarse, "lint", "--quiet")
    ok(r.returncode == 0, "lint: an inline 未记录 line satisfies it too", r.stdout + r.stderr)

    # milestone 同样要求
    write(cidx, MODE_INDEX.replace("- 精细度：session", "- 精细度：milestone"))
    write(os.path.join(coarse, CONTAINER, "0001-work.md"), MODE_WORK)
    r = run(coarse, "lint")
    ok("未记录" in r.stdout, "lint: milestone carries the same 未记录 obligation", r.stdout)

    # 细档位不管这条：同一篇在 session / full 下都不该被要求
    for value in ("full", "session"):
        write(cidx, MODE_INDEX.replace("- 精细度：session", f"- 精细度：{value}"))
        r = run(coarse, "lint", "--quiet")
        ok(r.returncode == 0, f"lint: mode={value} does not demand 未记录", r.stdout + r.stderr)
        ok("未记录" not in r.stdout, f"lint: mode={value} says nothing about 未记录", r.stdout)

    # 文档一致性：templates.md 的台账模板里那一行 `- 精细度：…` 必须是 mode 认得的规范值，
    # 否则照文档初始化出来的项目一上来就是「值认不出」。（台账模板排在状态历史模板之前，
    # 所以 re.search 命中的就是台账里那一行。）
    templates = os.path.join(os.path.dirname(HERE), "references", "templates.md")
    if os.path.isfile(templates):
        m = re.search(r"^-\s*精细度\s*[：:]\s*([A-Za-z0-9]+)\s*$", read(templates), re.M)
        ok(m is not None, "templates.md: the ledger template carries a canonical 精细度 value")
        if m:
            ok(m.group(1) in ("full", "session", "digest", "milestone"),
               "templates.md: the template's 精细度 value is one of the four modes", m.group(1))


# ---- 格式放宽与两种命名（本次规格改动的回归）-------------------------------
# 两种命名实测并存：编号式 237 篇（原型 + comfy）、日期式 71 篇（embeding try）。
# 这里每条断言都对应规格里的一条改动；夹具刻意做小，但**形状**取自真实语料。
FMT_DATE_INDEX = """# D

## 文件索引

### A. 起步

| 文件 | 方面 |
|---|---|
| [2026-09-02-迷你transformer实验.md](2026-09-02-迷你transformer实验.md) | 实验 |
| [2026-09-06-R21-slot悬崖机制.md](2026-09-06-R21-slot悬崖机制.md) | 机制 |

## 待办（滚动清单）

- [ ] x

## 当前状态（2026-09-06）

- 阶段 / 版本：v1
- 精细度：full
"""

# 日期式：日期在文件名与 H1 里，**没有** `日期：` 入口行，小节结构也是自由的。
FMT_DATE_ENTRY = """# 2026-09-02 迷你 transformer 实验

## 0. 总览

手写注意力，对照基线。

## 评测设置

`mini_bert.py --variant 2`，4×256×8，MLM 10k。

## 结果

| 项 | ρ |
|---|---|
| 门控 | 0.4973 |
| 双通路 | 0.5093 |
"""

# 日期式 + 行内实验号（`R21：`），H1 日期必须与文件名一致。
FMT_DATE_TAG_ENTRY = """# 2026-09-06 R21：`slot` 悬崖的机制

> 状态：**已完成**。两轮：6000 步筛 + 20000 步定论。
> 工具：`code/diag_slot_cliff.py`
> 产物：`exp/exp-sloteta-budget-*.json`

## 判定

ρ 从 0.4973 → 0.5093（+0.012），结论成立。
"""

# 自由结构 + **没有** `变更集` 字段：两者都不该报错。
FMT_FREE_ENTRY = """# 0002 · 自由结构的一篇

日期：2026-09-03
触发：selftest
范围：none
结论：3 组对照全部通过

## 我自己的第一节

随内容长出来的结构，没有模板。

## 复核

- 方式：`true`
- 结果：3 passed
"""

# 只有设置、没有结果的验证小节——规格 §十一 待确认项 1 的漏判，本次要报出来。
FMT_THIN_ENTRY = """# 0003 · 只有设置

日期：2026-09-04
触发：selftest
范围：none
结论：见正文

## 评测设置

本次用 `mini_bert.py --variant 2` 跑一遍。
"""

# 编号式记录**完全没有日期**：文件名没有、H1 没有、入口行也没有 → 真该报缺日期。
FMT_NODATE_ENTRY = """# 0004 · 没有日期

迭代：4
结论：1 项通过

## 验证

- 方式：`true`
- 结果：1 passed
"""

# 台账**没有** `## 当前状态` 块（实测五条线里四条如此，第五条也没有状态块）。
FMT_NOSTATUS_INDEX = """# N

## 文件索引

### A. 起步

| 文件 | 方面 |
|---|---|
| [2026-09-02-迷你transformer实验.md](2026-09-02-迷你transformer实验.md) | 实验 |

## 待办（滚动清单）

- [ ] x
"""

FMT_NOENTRY_ENTRY = """# 2026-09-05 没有入口元信息块

## 结果

3 组对照全部通过（见 `exp/a.json`）。
"""


def fmt_ledger(files: list[str], status: str = "2026-09-06", mode: str | None = "full") -> str:
    """按**实际存在的文件**生成一份自洽的台账（索引行 + 状态块）。

    夹具里最容易犯的错是「索引列了一个不存在的文件」——那会判成死链，把用例
    要测的东西盖掉。所以索引行由这一个函数统一生成，不手写。

    `mode=None` 时**不写** `精细度` 字段：那是「改动之前写下的台账」，
    也正是验证「配置文件的 mode 只是初始值」所需要的形状。
    """
    nl = "\n"
    rows = "".join(f"| [{f}]({f}) | 说明 |{nl}" for f in files)
    head = (f"# D{nl}{nl}## 文件索引{nl}{nl}### A. 起步{nl}{nl}"
            f"| 文件 | 方面 |{nl}|---|---|{nl}{rows}{nl}"
            f"## 待办（滚动清单）{nl}{nl}- [ ] x{nl}")
    if not status:
        return head
    fields = f"- 阶段 / 版本：v1{nl}" + (f"- 精细度：{mode}{nl}" if mode else "")
    return head + f"{nl}## 当前状态（{status}）{nl}{nl}{fields}"


def gate_phase(parent: str) -> None:
    """`check --lint`：两道门禁能并成一次运行，而**默认不合并**。

    这一节的起因是一次真实的漏检：本工作区自己的容器攒了 7 条 lint ERROR 没人看见，
    因为发版清单里只写了 `check`。修法不是"让 check 默认带上 lint"——九个真实语料实测，
    那会把今天全绿的项目当场变红（`dsh_from_github` 7 → 94 条、`3_param_block` 0 → 30 条）。
    所以并进来的是**选项**，而"另一道门存在"这件事必须在 check 通过时说出来。

    断言分四组：前提（两门各自独立成立）、合并（发现与退出码都并进来）、
    提示（只在通过且没跑 lint 时出现）、以及合并的两处易错点（去重与降级下标）。
    """
    root = os.path.join(parent, "gates")
    os.makedirs(os.path.join(root, CONTAINER))
    # 0001 干净；0002 结构没问题，但小节下面直接接子标题 —— 只有内容门禁看得见。
    write(os.path.join(root, CONTAINER, "0001-clean.md"), entry("0001", "干净", "2026-09-06"))
    write(os.path.join(root, CONTAINER, "0002-hollow.md"),
          entry("0002", "空心", "2026-09-06") + "\n## 五、补充\n\n### 子节\n\n- 有内容。\n")
    write(os.path.join(root, CONTAINER, "README.md"),
          fmt_ledger(["0001-clean.md", "0002-hollow.md"]))

    # 1) 前提：结构门禁过、内容门禁不过 ------------------------------------
    r = run(root, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "gates: the fixture passes the structure gate alone", r.stdout + r.stderr)
    r = run(root, "lint", "--strict", "--quiet")
    ok(r.returncode != 0 and "空小节" in r.stdout,
       "gates: and fails the content gate alone", r.stdout)

    # 2) 合并：发现与退出码都并进同一次运行 ---------------------------------
    r = run(root, "check", "--strict", "--quiet", "--lint")
    ok(r.returncode != 0, "gates: check --lint takes the content gate's verdict", r.stdout)
    ok("空小节" in r.stdout, "gates: check --lint prints the content finding", r.stdout)
    r = run(root, "check", "--strict", "--quiet")
    ok("空小节" not in r.stdout,
       "gates: without --lint the content gate stays out (the default is unchanged)", r.stdout)

    # 3) 干净容器：一起跑也不许报错（防"合并即误报"）-------------------------
    clean = os.path.join(parent, "gatesclean")
    os.makedirs(os.path.join(clean, CONTAINER))
    write(os.path.join(clean, CONTAINER, "0001-clean.md"), entry("0001", "干净", "2026-09-06"))
    write(os.path.join(clean, CONTAINER, "README.md"), fmt_ledger(["0001-clean.md"]))
    r = run(clean, "check", "--strict", "--quiet", "--lint")
    ok(r.returncode == 0, "gates: a clean container passes both gates in one run", r.stdout + r.stderr)

    # 4) 提示：只在「结构门禁通过」且「没跑 --lint」且「不是 --quiet」时出现 ----
    r = run(clean, "check", "--strict")
    ok("--lint" in r.stdout, "gates: a passing check points at the second gate", r.stdout)
    r = run(clean, "check", "--strict", "--quiet")
    ok("--lint" not in r.stdout, "gates: --quiet silences the pointer", r.stdout)
    r = run(clean, "check", "--strict", "--lint")
    ok("另一道" not in r.stdout,
       "gates: --lint does not point at the gate it just ran", r.stdout)

    # 5) 结构发现不许被合并挤掉 --------------------------------------------
    both = os.path.join(parent, "gatesboth")
    os.makedirs(os.path.join(both, CONTAINER))
    write(os.path.join(both, CONTAINER, "0001-both.md"),
          entry("0001", "两门都错", "2026-09-06").replace("## 四、验证", "[死链](nope.md)\n\n## 四、验证")
          + "\n## 五、补充\n\n### 子节\n\n- 有内容。\n")
    write(os.path.join(both, CONTAINER, "README.md"), fmt_ledger(["0001-both.md"]))
    r = run(both, "check", "--strict", "--quiet", "--lint")
    ok("死链" in r.stdout and "空小节" in r.stdout,
       "gates: --lint keeps the structure findings next to the content ones", r.stdout)

    # 6) 同一件事两门都报时只留一条 ----------------------------------------
    # 容器不存在是最典型的：两门各自都会报同一句话，文案一字不差才会去重。
    missing = os.path.join(parent, "gatesmissing")
    os.makedirs(missing)
    r = run(missing, "check", "--strict", "--quiet", "--lint")
    ok(r.stdout.count("找不到记录容器") == 1,
       "gates: a finding both gates report is listed once, not twice", r.stdout)

    # 7) 渐进原则穿得过合并（`legacy_rows` 存的是行号，合并后必须换算）-------
    # 用「验证小节没有可核对的内容」这条：它是**格式类**规则，旧记录才降级。
    # （「结论没有可核对的信息」不降级——内容含糊不随记录新旧改变，这是有意的，
    #  别拿它当夹具，否则测的是另一件事。）
    legacy = os.path.join(parent, "gateslegacy")
    os.makedirs(os.path.join(legacy, CONTAINER))
    write(os.path.join(legacy, CONTAINER, "0001-thin.md"),
          "# 0001 · 验证很薄\n\n日期：2026-09-06\n迭代：-\n结论：见正文（1 处）。\n\n"
          "## 四、验证\n\n- 结果：测试通过\n")
    write(os.path.join(legacy, CONTAINER, "README.md"), fmt_ledger(["0001-thin.md"]))
    r = run(legacy, "check", "--strict", "--quiet", "--lint")
    ok(r.returncode != 0 and "验证小节" in r.stdout,
       "gates: a thin verify section reaches check --lint", r.stdout)
    r = run(legacy, "check", "--strict", "--quiet", "--lint", "--legacy", "*")
    ok(r.returncode == 0,
       "gates: the gradual rule survives the merge (a legacy finding stays info)", r.stdout + r.stderr)

    # 8) 降级规则的**中央清单**不许与代码漂移 --------------------------------
    #
    # 这是 `0020` 的遗留：哪些规则参与渐进原则，原先只能读代码才知道（实跑时还按错假设写过
    # 断言——「结论为空」降级、「结论没有可核对的信息」不降级）。现在 `commands.md` 的
    # 「渐进原则」小节里有一张表，表里点名 `RULE_*` 常量；两边对账是机械可判的，
    # 所以放进自测，而不是指望下一个人记得同步。
    skill_dir = os.path.dirname(HERE)
    tool_src = read(os.path.join(HERE, "journal.py"))
    doc_src = read(os.path.join(skill_dir, "references", "commands.md"))
    constants = dict(re.findall(r'^(RULE_\w+) = "([^"]+)"', tool_src, re.M))
    ok(len(constants) >= 3, "gates: found the downgrade rule constants in the code",
       ", ".join(sorted(constants)))
    for name, value in sorted(constants.items()):
        ok(f"`{name}`" in doc_src,
           f"gates: the central list names `{name}`", f"value = {value}")
    listed = set(re.findall(r"`(RULE_\w+)`", doc_src))
    ok(listed <= set(constants),
       "gates: the central list names no rule the code no longer has",
       f"doc-only: {', '.join(sorted(listed - set(constants))) or '(none)'}")
    # `(?<!def )` 把函数定义那一行排除掉——它的形参与调用长得一样，第一版就把它算成了调用点。
    calls = [m.group(0) for m in re.finditer(r"(?<!def )_mark_legacy\([^)]*\)", tool_src)]
    ok(len(calls) >= 5, "gates: found the _mark_legacy call sites", str(len(calls)))
    bad_calls = [c for c in calls if not re.search(r"\bRULE_\w+\s*\)", c)]
    ok(not bad_calls,
       "gates: every _mark_legacy call passes a RULE_* constant, never a literal",
       "; ".join(c.strip() for c in bad_calls) or "(all good)")

    # 9) `ROOT` 位置矩阵必须与解析树一致 --------------------------------------
    #
    # 这张表以前是手写的，而手写会漂：`0021` 那版就把 `memory add` 的顺序写反过，
    # 于是下一个人照文档写就撞上误导性报错。现在表由**解析树推导**，自测逐条对账。
    # 顺带把"两种位置能不能同时支持"钉住——实测结论是不能（见 commands.md 的三类说明）。
    from argparse import _SubParsersAction  # 只有这条断言需要它，故局部导入

    def root_sets() -> tuple[set[str], set[str], set[str], set[str]]:
        leaf: set[str] = set()
        on_parent: set[str] = set()
        no_root: set[str] = set()
        with_option: set[str] = set()

        def walk(parser, path: list[str], ancestor_has_root: bool) -> None:
            own = any(a.dest == "root" and not a.option_strings for a in parser._actions)
            helper = any(
                not a.option_strings and a.dest != "root"
                and getattr(a, "nargs", None) in ("*", "+")
                for a in parser._actions
            )
            # 同时钉**拼写**（`--root` 是写进文档的对外接口）与 **dest**（`main()` 靠它合并）：
            # 只查 dest 的话，把选项改名成 `--root-path` 这种破坏就漏过去了（实测漏过一次）。
            has_option = any(
                "--root" in a.option_strings and a.dest == "root_opt" for a in parser._actions
            )
            if path and callable(parser._defaults.get("func")):
                key = " ".join(path)
                if own or helper:
                    leaf.add(key)
                elif ancestor_has_root:
                    on_parent.add(key)
                else:
                    no_root.add(key)
                if has_option:
                    with_option.add(key)
            for action in parser._actions:
                if isinstance(action, _SubParsersAction):
                    for name, sub in action.choices.items():
                        walk(sub, path + [name], ancestor_has_root or own or helper)

        walk(JOURNAL.build_parser(), [], False)
        return leaf, on_parent, no_root, with_option

    leaf_set, parent_set, none_set, opt_set = root_sets()
    ok(len(leaf_set) + len(parent_set) + len(none_set) >= 30,
       "gates: walked the command tree for the ROOT matrix",
       f"叶子 {len(leaf_set)} / 父级 {len(parent_set)} / 无根 {len(none_set)}")

    def documented(kind: str) -> set[str]:
        found: set[str] = set()
        for line in doc_src.splitlines():
            m = re.match(r"^\|\s*\*\*(叶子|父级|没有根)\*\*\s*\|\s*(.+?)\s*\|\s*$", line)
            if m and m.group(1) == kind:
                found |= set(re.findall(r"`([^`]+)`", m.group(2)))
        return found

    for kind, derived in (("叶子", leaf_set), ("父级", parent_set), ("没有根", none_set)):
        listed = documented(kind)
        ok(listed == derived,
           f"gates: the ROOT matrix lists exactly the {kind}-root commands",
           f"文档独有 {sorted(listed - derived)}；解析树独有 {sorted(derived - listed)}")

    # 10) `--root` 选项：与位置根**同落点**，且不许空承诺 ----------------------
    #
    # 位置根挂的层不一样（`index <ROOT> sync` 而不是 `index sync <ROOT>`），叶子再加一个位置根
    # 又做不到（见上面那段实测）。`--root` 选项不受这个限制，出现在哪儿都算——这就是加它的理由。
    # 不变量：**有 `--root`  ⟺  有位置根**（自己的或父级的）。两种破法都要红：
    #   该有的缺了（子命令族仍然只能把根写在前面）、给做不到的命令发了空头支票（记忆侧那些）。
    positional_root_set = leaf_set | parent_set
    ok(opt_set == positional_root_set,
       "gates: `--root` exists exactly where a positional root does",
       f"缺选项 {sorted(positional_root_set - opt_set)}；空承诺 {sorted(opt_set - positional_root_set)}")

    neutral = os.path.join(parent, "root-opt-neutral")
    os.makedirs(neutral, exist_ok=True)
    ws = mem_ws(parent, "root-opt-ws", "# 01 · 主题\n\n- **教训**：根要能指定。做法：加选项。（`wl/0001`）\n")

    # ① 子命令族：根写在**子命令之后**也能到位（加这个选项的全部意义）
    #    判据取"从**非工作区**目录跑、退出码为 0"——这正是"根被用上了"的证据
    #    （根若没被采纳，cwd 不是工作区就会报错）。口径不要绑在某句提示文案上。
    r = run(neutral, "index", "sync", "--root", ws)
    ok(r.returncode == 0,
       "gates: `index sync --root <ROOT>` reaches the workspace", r.stdout + r.stderr)
    r = run(neutral, "index", "sync", "--root", neutral)
    err = r.stdout + r.stderr
    ok(r.returncode != 0 and "ERROR" in err,
       "gates: and a --root that is not a workspace is refused", err)
    # ② 同一个根写成位置参数（父级）仍然可用
    r = run(neutral, "index", ws, "sync")
    ok(r.returncode == 0, "gates: `index <ROOT> sync` still works", r.stdout + r.stderr)
    # ③ 两者都给时**选项优先**：位置参数指向一个不是工作区的目录，仍应成功
    r = run(neutral, "check", "--strict", "--quiet", "--root", ws, neutral)
    ok(r.returncode == 0, "gates: `--root` beats the positional root", r.stdout + r.stderr)
    # ④ 空承诺：没有工作区根概念的命令**不该**接受它（拒绝了才是对的）
    for argv in (("promote", "suggest", "--root", ws), ("inbox", "count", "--root", ws),
                 ("memory", "index", "--root", ws)):
        r = run(neutral, *argv)
        ok(r.returncode != 0 and "--root" in (r.stdout + r.stderr),
           f"gates: `{' '.join(argv[:2])}` refuses --root (it has no workspace root to honour)",
           r.stdout + r.stderr)


def link_phase(parent: str) -> None:
    """链接目标的三种写法必须走**同一套**解析：裸、尖括号（含空格）、百分号转义。

    起因是一次整体功能实跑：`archive --stage "A. 起步"` 这类带空格的阶段目录，工具
    **自己就会写出** `](A. 起步/x.md)` 这种目标，而旧正则 `\\]\\(([^)\\s]+)\\)` 排除空白，
    于是同一个事实在三处各错一次——死链检查看不见（漏报）、归档重写改不到（静默留旧链接）、
    `index compact` 抛 `AttributeError`（崩）。所以这一节测的不是"某个函数返回值"，
    而是**三处口径一致**：写出来的、检查得到的、折叠得动的，必须是同一批目标。
    """
    stage = "A. 起步"
    root = os.path.join(parent, "links")
    os.makedirs(os.path.join(root, CONTAINER, stage))
    # 阶段目录里的一个真实文件：链接指向它时**不许**报死链（两种写法都不许）。
    write(os.path.join(root, CONTAINER, stage, "真.md"),
          "# 真\n\n## 四、验证\n\n- 方式：`true`\n- 结果：1 passed\n")
    write(os.path.join(root, CONTAINER, "0001-links.md"),
          "# 0001 · 链接写法\n\n日期：2026-09-06\n迭代：-\n结论：四种写法各测一次，2 死 2 活。\n\n"
          "## 一、写法\n\n"
          "- 裸目标、含空格、不存在：[死](A. 起步/nope.md)\n"
          "- 尖括号、含空格、不存在：[死](<A. 起步/nope2.md>)\n"
          "- 百分号转义、指向真实文件：[真](A.%20起步/真.md)\n"
          "- 尖括号、指向真实文件：[真](<A. 起步/真.md>)\n\n"
          "## 二、验证\n\n- 方式：`journal.py check --strict`\n- 结果：死链 2 条\n")
    write(os.path.join(root, CONTAINER, "README.md"), fmt_ledger(["0001-links.md"]))

    r = run(root, "check", "--strict", "--quiet")
    ok("死链：A. 起步/nope.md" in r.stdout,
       "links: a dead link with a space in a bare target is reported", r.stdout)
    ok("死链：A. 起步/nope2.md" in r.stdout,
       "links: a dead link inside angle brackets is reported", r.stdout)
    ok("真.md" not in r.stdout,
       "links: an existing file is not a dead link, in either written form", r.stdout)
    ok(r.returncode != 0, "links: the two dead links make the gate fail", r.stdout)

    # 归档 + 索引瘦身：写出来的链接、检查、折叠必须一致 ------------------------
    both = os.path.join(parent, "linksarchive")
    os.makedirs(os.path.join(both, CONTAINER))
    write(os.path.join(both, CONTAINER, "0001-a.md"),
          "# 0001 · 指向 b\n\n日期：2026-09-06\n迭代：-\n结论：见 `wl/0002` 的 1 处结论。\n\n"
          "## 一、正文\n\n- 见 [b](0002-b.md)\n\n"
          "## 二、验证\n\n- 方式：`true`\n- 结果：1 passed\n")
    write(os.path.join(both, CONTAINER, "0002-b.md"), entry("0002", "b", "2026-09-06"))
    # 索引里故意留一行**坏的**：有 `](` 却没有闭合括号（手改索引很容易留下这种行）。
    # 它正是 `index compact` 那条守卫要挡的东西：旧实现在这一行上抛 AttributeError，
    # 整条命令崩掉。检查端看不见它（匹配不上），折叠端必须扛得住它。
    ledger = fmt_ledger(["0001-a.md", "0002-b.md"]).replace(
        "| [0001-a.md](0001-a.md) | 说明 |",
        "| [0001-a.md](0001-a.md) | 指向 b |\n| [坏行]( | 手抖留下的 |")
    write(os.path.join(both, CONTAINER, "README.md"), ledger)
    r = run(both, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "links: the fixture starts clean", r.stdout + r.stderr)

    r = run(both, "archive", "--stage", stage, "--from", "2", "--to", "2")
    ok(r.returncode == 0, "links: archive exits 0", r.stdout + r.stderr)
    moved = read(os.path.join(both, CONTAINER, "0001-a.md"))
    # 含空格的新目标必须写成尖括号形式，否则 markdown 截断 + 自家匹配又漏掉。
    ok("](<A. 起步/0002-b.md>)" in moved,
       "links: archive writes a space-containing target in the angle form", moved)
    r = run(both, "check", "--strict", "--quiet")
    ok(r.returncode == 0 and "死链" not in r.stdout,
       "links: what archive wrote is what the checker can see (0 dead links)", r.stdout)

    r = run(both, "index", "compact", "--stage", stage)
    ok(r.returncode == 0 and "Traceback" not in (r.stdout + r.stderr),
       "links: index compact survives a row it cannot parse", r.stdout + r.stderr)
    ok("含活跃记录" in r.stdout,
       "links: and it refuses to fold a section that still holds an active record", r.stdout)

    # 两篇都归档之后才该折叠（整节已归档是折叠的前提，不是可选项）-------------
    r = run(both, "archive", "--stage", stage, "--from", "1", "--to", "1")
    ok(r.returncode == 0, "links: archiving the second record exits 0", r.stdout + r.stderr)
    r = run(both, "index", "compact", "--stage", stage)
    ok(r.returncode == 0 and "Traceback" not in (r.stdout + r.stderr),
       "links: index compact does not crash on an all-archived section", r.stdout + r.stderr)
    ok("已归档）" in read(os.path.join(both, CONTAINER, "README.md")),
       "links: and it folds the section once every row is archived",
       read(os.path.join(both, CONTAINER, "README.md")))
    r = run(both, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "links: still clean after folding", r.stdout)


def format_phase(parent: str) -> None:
    """两种命名 + 放宽后的格式 + 实质验证 + 渐进原则 + `snapshot`。

    这一节把规格里那十条改动逐条钉住，尤其是那条**假错误**：
    日期式文件名曾被 `^(\\d+)-` 半解析成「编号 2026」，于是同一容器里
    11 个日期式文件互相重号、报出「编号 2026 重复」。
    """
    root = os.path.join(parent, "fmt")
    os.makedirs(os.path.join(root, CONTAINER, "lessons"))
    write(os.path.join(root, CONTAINER, "README.md"), FMT_DATE_INDEX)
    write(os.path.join(root, CONTAINER, "2026-09-02-迷你transformer实验.md"), FMT_DATE_ENTRY)
    write(os.path.join(root, CONTAINER, "2026-09-06-R21-slot悬崖机制.md"), FMT_DATE_TAG_ENTRY)
    write(os.path.join(root, CONTAINER, "0002-自由结构.md"), FMT_FREE_ENTRY)
    write(os.path.join(root, CONTAINER, "0003-只有设置.md"), FMT_THIN_ENTRY)
    write(os.path.join(root, CONTAINER, "0004-没有日期.md"), FMT_NODATE_ENTRY)
    write(os.path.join(root, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(root, CONTAINER, "lessons", "01-topic.md"),
          "# 01 · T\n\n来源：wl/0002。\n\n## 子主题\n\n- **s**：a。根因：b。做法：c。（`wl/0002`）\n")
    ipath = os.path.join(root, CONTAINER, "README.md")

    # 1) 两种命名都被认出来 -------------------------------------------------
    # 第一列：纯编号容器是 4 字符，出现日期式就展宽到 10（`2026-09-02` 的长度）。
    r = run(root, "outline")
    ok(re.search(r"^2026-09-02\t2026-09-02\t", r.stdout, re.M) is not None,
       "a date-named file is recognised as a record (date style)", r.stdout)
    ok(re.search(r"^0002\s+\t", r.stdout, re.M) is not None,
       "a numbered file is still recognised (numbered style)", r.stdout)
    ok(re.search(r"^2026-09-06\t2026-09-06\tR21\t", r.stdout, re.M) is not None,
       "an inline experiment id (R21) becomes the iteration tag, date stays the identity", r.stdout)
    r = run(root, "stats")
    ok("编号式 3 篇 / 日期式 2 篇" in r.stdout,
       "stats counts both naming styles separately", r.stdout)
    # 日期式容器同一天有多篇（实测一天 18 篇）：合规率必须按**篇**数，不能被同一天的
    # 记录互相覆盖（曾经按身份做键，11 篇只数成 4 篇）。
    r = run(root, "stats")
    ok("编号式 3 篇 / 日期式 2 篇" in r.stdout,
       "stats counts both naming styles separately", r.stdout)
    # 日期式容器同一天有多篇（实测一天 18 篇）：合规率必须按**篇**数，不能被同一天的
    # 记录互相覆盖（曾经按身份做键，11 篇只数成 4 篇）。
    sameday = os.path.join(parent, "fmtsameday")
    os.makedirs(os.path.join(sameday, CONTAINER))
    files = ["2026-09-01-alpha.md", "2026-09-01-beta.md", "2026-09-01-gamma.md"]
    write(os.path.join(sameday, CONTAINER, "README.md"), fmt_ledger(files, status="2026-09-01"))
    for f in files:
        write(os.path.join(sameday, CONTAINER, f),
              f"# 2026-09-01 {f[11:-3]}\n\n## 结果\n\n| 项 | ρ |\n|---|---|\n| A | 0.4973 |\n")
    r = run(sameday, "stats")
    ok("日期 3/3" in r.stdout and "验证 3/3" in r.stdout,
       "stats counts every record on the same day, not one per day", r.stdout)
    ok("entries     : 3" in r.stdout and "3 dated" in r.stdout,
       "stats counts 3 entries on one day", r.stdout)
    # `topics` 也必须**按路径**做键。它曾经按 `rid` 统计，而日期式记录的 `rid` 就是
    # `f[:10]`（那一天）：同一天的 3 篇被折成"1 篇"，而且只显示最后一份。同一个文件里
    # `cmd_stats` 早把这条规则写死在注释里了，`cmd_topics` 漏了（审查报告 F10）。
    for f in files:
        write(os.path.join(sameday, CONTAINER, f),
              read(os.path.join(sameday, CONTAINER, f)) + "- marker: samedaycluster\n")
    r = run(sameday, "topics")
    topic_row = next((ln for ln in r.stdout.splitlines() if ln.startswith("samedaycluster")), "")
    ok(re.search(r"^samedaycluster\s+3 篇", r.stdout, re.M) is not None,
       "topics counts all 3 records of one day (keyed by path, not by rid)", r.stdout)
    ok("alpha" in topic_row and "beta" in topic_row and "gamma" in topic_row,
       "topics lists every record of that day, not just the last one", topic_row)
    # 纯编号容器：第一列保持 4 字符（老输出与老脚本按这个对齐）。
    numbered = os.path.join(parent, "fmtnumbered")
    os.makedirs(os.path.join(numbered, CONTAINER))
    write(os.path.join(numbered, CONTAINER, "README.md"), CANON_INDEX)
    write(os.path.join(numbered, CONTAINER, "0002-自由结构.md"), FMT_FREE_ENTRY)
    r = run(numbered, "outline")
    ok(re.search(r"^0002\t2026-09-03\t", r.stdout, re.M) is not None,
       "a numbered-only container keeps the 4-char first column", r.stdout)

    # 2) 日期式文件不被半解析成「编号 2026」（本次要修的假错误）--------------
    r = run(root, "check", "--quiet", "--legacy", "")
    ok("编号 2026 重复" not in r.stdout and "编号 2026 重复" not in r.stderr,
       "a date-named file is NOT misparsed as record number 2026", r.stdout + r.stderr)
    ok("编号重复" not in r.stdout, "no bogus duplicate-number error at all", r.stdout)
    ok("编号断档" not in r.stdout,
       "date-style files do not create bogus numbering gaps either", r.stdout)

    # 3) H1 必须与文件名一致（两种形制各自的口径）--------------------------
    bad = os.path.join(parent, "fmtbad")
    os.makedirs(os.path.join(bad, CONTAINER))
    write(os.path.join(bad, CONTAINER, "README.md"), FMT_DATE_INDEX)
    write(os.path.join(bad, CONTAINER, "2026-09-02-迷你transformer实验.md"),
          FMT_DATE_ENTRY.replace("# 2026-09-02 ", "# 2026-09-09 "))
    r = run(bad, "check", "--quiet", "--legacy", "")
    ok("标题日期 2026-09-09 与文件名 2026-09-02 不一致" in r.stdout,
       "a date-style H1 that disagrees with its filename is an ERROR", r.stdout)
    ok(r.returncode != 0, "and it fails the gate", r.stdout)
    bad2 = os.path.join(parent, "fmtbad2")
    os.makedirs(os.path.join(bad2, CONTAINER))
    write(os.path.join(bad2, CONTAINER, "README.md"), FMT_DATE_INDEX)
    write(os.path.join(bad2, CONTAINER, "0007-x.md"), "# 0008 · 编号不对\n\n日期：2026-09-02\n\n## 验证\n\n- 结果：1 passed\n")
    r = run(bad2, "check", "--quiet", "--legacy", "")
    ok("标题篇号 0008 与文件名 7 不一致" in r.stdout,
       "a numbered H1 that disagrees with its filename is an ERROR", r.stdout)
    # 4) 一个容器里两种命名混用：允许，但要提示 -----------------------------
    r = run(root, "check", "--legacy", "")
    ok("[INFO]" in r.stdout and "两种命名混用" in r.stdout,
       "mixing both styles is allowed, and only reported as info", r.stdout)

    # 5) `日期：` 字段在日期式里可以没有；真正没有日期才报 -------------------
    ok("迷你transformer实验.md: 缺" not in r.stdout,
       "a date-style entry with no 日期： line is not flagged as missing a date", r.stdout)
    ok("缺 `日期：YYYY-MM-DD` 入口行" in r.stdout and "0004-没有日期.md" in r.stdout,
       "an entry with no date anywhere IS flagged", r.stdout)

    # 6) 自由小节结构被接受（没有六段式也不报错）----------------------------
    ok("缺验证类小节" not in r.stdout or "0002-自由结构.md" not in r.stdout,
       "free section structure is accepted; only the verification section is required", r.stdout)

    # 7) 验证小节要**实质**内容：只有设置不算 ---------------------------------
    ok("0003-只有设置.md" in r.stdout and "验证小节" in r.stdout,
       "a setup-only verification section is reported", r.stdout)
    r1 = run(root, "check", "--quiet", "--legacy", "")
    ok(r1.returncode == 0,
       "and by default it is a WARN, not an ERROR (advisory heuristic)", r1.stdout)
    r2 = run(root, "check", "--quiet", "--strict", "--legacy", "")
    ok(r2.returncode != 0, "under --strict the same finding becomes an ERROR", r2.stdout)
    # 有数字有表格的验证小节不该被误报：报的是「验证小节 `…` 只有…」，
    # 而不是这一篇本身另有问题。
    ok("验证小节" not in r2.stdout or "迷你transformer实验.md: 验证小节" not in r2.stdout,
       "a table-with-numbers verification section is not flagged", r2.stdout)

    # 8) `变更集` 缺省不算错（它只是迭代字段的一个别名，实测 146/162 篇写「无」）--
    ok("变更集" not in r.stdout or "0002-自由结构.md" not in r.stdout,
       "a record without any 变更集 field is not an error", r.stdout)
    r = run(root, "show", "0002-自由结构.md")
    ok(r.returncode == 0 and "迭代" in r.stdout, "show accepts a filename as the key", r.stdout)

    # 9) 台账没有 `## 当前状态` 块：只报 info，不报错 ------------------------
    ns = os.path.join(parent, "fmtnostatus")
    os.makedirs(os.path.join(ns, CONTAINER))
    write(os.path.join(ns, CONTAINER, "README.md"), FMT_NOSTATUS_INDEX)
    write(os.path.join(ns, CONTAINER, "2026-09-02-迷你transformer实验.md"), FMT_DATE_ENTRY)
    # 不要加 `--quiet`：这条断言要看的正是 INFO 行本身。
    r = run(ns, "check", "--legacy", "")
    ok(r.returncode == 0, "a ledger without a status block passes the gate", r.stdout + r.stderr)
    ok("[INFO]" in r.stdout and "没有 `## 当前状态` 块" in r.stdout,
       "and it is reported as info, not as an error", r.stdout)
    r = run(ns, "check", "--strict", "--legacy", "")
    ok(r.returncode == 0, "even --strict keeps the missing status block non-fatal", r.stdout)
    # 有状态块的容器照旧校验新鲜度（两种形态都过得去）。
    stale = os.path.join(parent, "fmtstale")
    os.makedirs(os.path.join(stale, CONTAINER))
    write(os.path.join(stale, CONTAINER, "README.md"),
          fmt_ledger(["2026-09-02-迷你transformer实验.md"], status="2026-01-01"))
    write(os.path.join(stale, CONTAINER, "2026-09-02-迷你transformer实验.md"), FMT_DATE_ENTRY)
    r = run(stale, "check", "--legacy", "")
    ok("早于最新记录" in r.stdout,
       "a present status block is still checked for freshness", r.stdout)
    # 10) 渐进原则：旧记录只报 info，新记录照报 error ------------------------
    # `--legacy` 的显式清单与规模兜底要分开测：这里先**关掉兜底**（给显式清单），
    # 把"清单怎么生效"单独钉住，规模兜底在第 10b 组。
    lg = os.path.join(parent, "fmtlegacy")
    os.makedirs(os.path.join(lg, CONTAINER))
    write(os.path.join(lg, CONTAINER, "README.md"),
          fmt_ledger(["2026-09-02-迷你transformer实验.md", "0003-只有设置.md"]))
    write(os.path.join(lg, CONTAINER, "2026-09-02-迷你transformer实验.md"), FMT_DATE_ENTRY)
    write(os.path.join(lg, CONTAINER, "0003-只有设置.md"), FMT_THIN_ENTRY)
    r = run(lg, "check", "--strict", "--quiet", "--legacy", "")
    ok(r.returncode != 0, "with no legacy declared, a new record's finding is an ERROR", r.stdout)
    r = run(lg, "check", "--strict", "--legacy", "**")
    ok(r.returncode == 0, "an explicit list covering everything turns old-format findings into info",
       r.stdout)
    ok("[INFO]" in r.stdout and "0003-只有设置.md" in r.stdout,
       "the finding is still visible, just downgraded", r.stdout)
    r = run(lg, "check", "--strict", "--quiet", "--legacy", "0003-*")
    ok(r.returncode == 0, "--legacy accepts a glob", r.stdout)
    r = run(lg, "check", "--strict", "--legacy", "2026-*")
    ok(r.returncode != 0, "a glob that does not match leaves the finding an ERROR", r.stdout)
    # 规模兜底：记录还少 ⇒ 当新项目（照报 error）；记录已多 ⇒ 整批当旧记录（只报 info）。
    ok(JOURNAL.LEGACY_AUTO_MIN_RECORDS == 5, "the auto fallback threshold is 5 records",
       str(JOURNAL.LEGACY_AUTO_MIN_RECORDS))
    small = os.path.join(parent, "fmtsmall")
    os.makedirs(os.path.join(small, CONTAINER))
    write(os.path.join(small, CONTAINER, "README.md"), fmt_ledger(["0003-只有设置.md"]))
    write(os.path.join(small, CONTAINER, "0003-只有设置.md"), FMT_THIN_ENTRY)
    r = run(small, "check", "--strict", "--quiet")
    ok(r.returncode != 0,
       "a small container (looks new) reports the finding as an ERROR", r.stdout)
    big = os.path.join(parent, "fmtbig")
    os.makedirs(os.path.join(big, CONTAINER))
    names = [f"000{i}-x.md" for i in range(1, 6)] + ["0006-只有设置.md"]
    write(os.path.join(big, CONTAINER, "README.md"), fmt_ledger(names))
    for f in [f"000{i}-x.md" for i in range(1, 6)]:
        write(os.path.join(big, CONTAINER, f),
              f"# {f[:4]} · X\n\n日期：2026-09-01\n\n## 验证\n\n- 结果：1 passed\n")
    write(os.path.join(big, CONTAINER, "0006-只有设置.md"),
          FMT_THIN_ENTRY.replace("# 0003 · ", "# 0006 · "))
    r = run(big, "check", "--strict", "--quiet")
    ok(r.returncode == 0,
       "a container past the threshold (looks established) only reports info", r.stdout)
    r = run(big, "check", "--strict", "--legacy", "")
    ok(r.returncode != 0, "--legacy \"\" overrides the fallback: everything is judged as new",
       r.stdout)
    # 兜底生效时要**自己说出来**（门禁之外的提示行：不算发现、不计入 error/warn/info、不改退出码）。
    # 否则一个成熟容器里"新写的记录不再被判 ERROR"这件事是静默的 —— 而它恰恰发生在长期项目上。
    r = run(big, "check", "--strict")
    ok("新写的记录不会被判 ERROR" in r.stdout,
       "the auto fallback announces itself (it is silent otherwise)", r.stdout)
    ok(r.returncode == 0, "the announcement does not change the verdict", r.stdout)
    r = run(big, "check", "--strict", "--quiet")
    ok("新写的记录不会被判 ERROR" not in r.stdout,
       "--quiet suppresses the announcement as well", r.stdout)
    r = run(big, "check", "--strict", "--legacy", "")
    ok("新写的记录不会被判 ERROR" not in r.stdout,
       "an explicit --legacy silences the announcement", r.stdout)
    r = run(small, "check", "--strict")
    ok("新写的记录不会被判 ERROR" not in r.stdout,
       "a container below the threshold never announces it", r.stdout)
    # 死链从来就有，**不**受渐进原则影响：旧记录也得照报。
    dl = os.path.join(parent, "fmtdead")
    os.makedirs(os.path.join(dl, CONTAINER))
    write(os.path.join(dl, CONTAINER, "README.md"),
          fmt_ledger(["2026-09-02-迷你transformer实验.md"]))
    write(os.path.join(dl, CONTAINER, "2026-09-02-迷你transformer实验.md"),
          FMT_DATE_ENTRY + "\n见 [没了](no-such-file.md)。\n")
    r = run(dl, "check")
    ok(r.returncode != 0 and "死链" in r.stdout,
       "a dead link stays an ERROR even under the default opt-in list", r.stdout)

    # 11) `LEGACY.md`：显式声明文件（跟着容器进版本控制，团队共用）-----------
    dec = os.path.join(parent, "fmtdecl")
    os.makedirs(os.path.join(dec, CONTAINER))
    write(os.path.join(dec, CONTAINER, "README.md"),
          fmt_ledger(["2026-09-02-迷你transformer实验.md", "0003-只有设置.md"]))
    write(os.path.join(dec, CONTAINER, "2026-09-02-迷你transformer实验.md"), FMT_DATE_ENTRY)
    write(os.path.join(dec, CONTAINER, "0003-只有设置.md"), FMT_THIN_ENTRY)
    write(os.path.join(dec, CONTAINER, "LEGACY.md"), "# 旧记录\n\n- 0003-*\n")
    r = run(dec, "check", "--strict", "--quiet")
    ok(r.returncode == 0,
       "a container-root LEGACY.md narrows the opt-in list (unlisted records are new)", r.stdout)
    write(os.path.join(dec, CONTAINER, "LEGACY.md"), "# 旧记录\n\n- 2026-*\n")
    r = run(dec, "check", "--strict", "--quiet")
    ok(r.returncode != 0,
       "the declaration is actually read: listing the other record flips the verdict", r.stdout)
    # `LEGACY.md` 是显式声明 ⇒ 兜底不生效 ⇒ 也不该有那句提示
    write(os.path.join(dec, CONTAINER, "LEGACY.md"), "# 旧记录\n\n- 0003-*\n")
    r = run(dec, "check", "--strict")
    ok("新写的记录不会被判 ERROR" not in r.stdout,
       "a container-root LEGACY.md silences the fallback announcement", r.stdout)

    # 12) `snapshot`：只读汇总最近 N 篇的入口元信息，缺入口块也不失败 --------
    snap = os.path.join(parent, "fmtsnap")
    os.makedirs(os.path.join(snap, CONTAINER))
    # 纯编号的 `0001` 日期最老，`--entries 2` 时它应该被排除在外。
    write(os.path.join(snap, CONTAINER, "README.md"),
          fmt_ledger(["2026-09-02-迷你transformer实验.md", "2026-09-05-没有入口块.md",
                      "0001-自由结构.md"]))
    write(os.path.join(snap, CONTAINER, "2026-09-02-迷你transformer实验.md"), FMT_DATE_ENTRY)
    write(os.path.join(snap, CONTAINER, "2026-09-05-没有入口块.md"), FMT_NOENTRY_ENTRY)
    write(os.path.join(snap, CONTAINER, "0001-自由结构.md"),
          FMT_FREE_ENTRY.replace("# 0002 · ", "# 0001 · ").replace("日期：2026-09-03", "日期：2026-09-01"))
    before_state = sorted((f, read(os.path.join(snap, CONTAINER, f)))
                          for f in os.listdir(os.path.join(snap, CONTAINER)))
    r = run(snap, "snapshot", "--entries", "9")
    ok(r.returncode == 0, "snapshot exits 0", r.stdout + r.stderr)
    ok("SNAPSHOT" in r.stdout, "snapshot prints a header", r.stdout)
    ok("没有入口元信息块" in r.stdout,
       "a record with no entry block does not fail the command", r.stdout)
    ok("日期：2026-09-01" in r.stdout and "结论：3 组对照全部通过" in r.stdout,
       "the field-line style entry block is aggregated", r.stdout)
    after_state = sorted((f, read(os.path.join(snap, CONTAINER, f)))
                         for f in os.listdir(os.path.join(snap, CONTAINER)))
    ok(before_state == after_state, "snapshot is READ-ONLY: it changed no file in the container")
    r = run(snap, "snapshot", "--entries", "2")
    ok("2026-09-05-没有入口块.md" in r.stdout and "2026-09-02-迷你transformer实验.md" in r.stdout
       and "自由结构" not in r.stdout,
       "snapshot honours --entries over the newest records", r.stdout)
    r = run(snap, "snapshot", "--entries", "9", "--out", os.path.join(snap, "SNAP.md"))
    ok(r.returncode == 0 and os.path.exists(os.path.join(snap, "SNAP.md")),
       "snapshot --out writes where it is told", r.stdout)

    # 13) 日期式容器里 `mode` 照常读默认档 -----------------------------------
    r = run(root, "mode")
    ok(r.returncode == 0 and r.stdout.startswith("full"),
       "mode reads the default full on a date-style container", r.stdout)


# ---- 项目配置文件（`<容器>/.config.json`）-----------------------------------
# 优先级只有三层：命令行 > <容器>/.config.json > 内置默认。
# 两个名字字段（container / lessons）是例外：它们命名的正是配置文件自己所在的目录，
# 所以读配置之前就得先知道它们——只能按目录发现，配置里的值只作备注。
def config_phase(parent: str) -> None:
    """项目配置文件：三层优先级、来源可见、`--write` / `--set`、名字字段的不对称。"""

    def cfg_line(out: str, key: str) -> str:
        """取 `config` 视图里某个字段那一行。"""
        return next((l for l in out.splitlines() if l.startswith(key)), "")

    def dump(data: dict, nl: str = "\n") -> str:
        body = json.dumps(data, ensure_ascii=False, indent=2)
        return body.replace("\n", nl) + nl

    proj = os.path.join(parent, "configproj")
    os.makedirs(os.path.join(proj, CONTAINER, "lessons"))
    # 台账**没有** `精细度` 字段：正好验证「配置的 mode 只提供初始值」。
    # 0003 是「只有设置、没有结果」的旧格式记录，用来验证配置里的 legacy 真的参与判定。
    write(os.path.join(proj, CONTAINER, "README.md"),
          fmt_ledger(["0001-work.md", "0002-more.md", "0003-只有设置.md"],
                     status="2026-09-14", mode=None))
    write(os.path.join(proj, CONTAINER, "0001-work.md"), MODE_WORK)
    write(os.path.join(proj, CONTAINER, "0002-more.md"), MODE_ROLL_ENTRY)
    write(os.path.join(proj, CONTAINER, "0003-只有设置.md"), FMT_THIN_ENTRY)
    write(os.path.join(proj, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(proj, CONTAINER, "lessons", "01-topic.md"),
          "# 01 · T\n\n来源：wl/0001。\n\n## 子主题\n\n- **s**：a。根因：b。做法：c。（`wl/0001`）\n")
    cfg_path = os.path.join(proj, CONTAINER, ".config.json")
    ledger = os.path.join(proj, CONTAINER, "README.md")

    # 1) 没有配置文件 = 全部内置默认，而且只读视图什么都不建 ------------------
    r = run(proj, "config")
    ok(r.returncode == 0, "config: a missing config file is not an error", r.stdout + r.stderr)
    ok("不存在" in r.stdout and not os.path.exists(cfg_path),
       "config: the read-only view says the file is absent and creates nothing",
       r.stdout + str(os.path.exists(cfg_path)))
    ok(r.stdout.count("← 内置默认") == 5,
       "config: every field reports the built-in default without a config file", r.stdout)
    ok(cfg_line(r.stdout, "mode").split("=")[1].split("←")[0].strip() == "full",
       "config: the effective mode falls back to the built-in full", r.stdout)

    # 没有配置文件时，`mode` 的默认档也一样是内置的 `full`
    r = run(proj, "mode")
    ok(r.stdout.startswith("full") and "内置默认" in r.stdout,
       "mode: without 精细度 and without a config the default is the built-in full", r.stdout)

    # 2) `--write`：按当前生效值落盘，已存在时拒绝覆盖 ------------------------
    r = run(proj, "config", "--write")
    ok(r.returncode == 0 and os.path.isfile(cfg_path),
       "config --write creates <container>/.config.json", r.stdout + r.stderr)
    ok(safe(lambda: json.loads(read(cfg_path))) == {"mode": "full", "container": CONTAINER,
                                                    "lessons": "lessons", "legacy": [],
                                                    "snapshotEntries": 12},
       "config --write records the current effective values",
       safe(lambda: read(cfg_path)))
    before_bytes = read_bytes(cfg_path)
    r = run(proj, "config", "--write")
    ok(r.returncode != 0 and "已存在" in r.stdout,
       "config --write refuses to clobber an existing file", r.stdout)
    # 先取一次再比：`read_bytes` 现在"文件不在 → 空字节"，两次调用都安全；但取一次更省，
    # 而且失败时 detail 就是真读到的内容。
    after_refused = read_bytes(cfg_path)
    ok(after_refused == before_bytes,
       "config --write (refused) leaves the file byte-identical", repr(after_refused[:60]))
    r = run(proj, "config", "--write", "--force")
    ok(r.returncode == 0, "config --write --force overwrites", r.stdout + r.stderr)

    # 3) 逐字段来源：配置文件里写了的字段来自文件，容器/经验目录仍来自目录发现
    r = run(proj, "config")
    ok(r.returncode == 0, "config: a config file with default values reads clean",
       r.stdout + r.stderr)
    ok("← .config.json" in cfg_line(r.stdout, "mode"), "config: mode comes from the file", r.stdout)
    ok("← .config.json" in cfg_line(r.stdout, "snapshotEntries"),
       "config: snapshotEntries comes from the file", r.stdout)
    # `container` 永远来自目录发现：配置文件管不了自己所在的目录（这正是不对称之处）。
    ok("← 内置默认" in cfg_line(r.stdout, "container"),
       "config: container still comes from directory discovery, never from the file", r.stdout)
    ok(cfg_line(r.stdout, "legacy").split("=")[1].split("←")[0].strip() == "（空）",
       "config: an empty legacy list is shown as empty, not as a fallback", r.stdout)

    # 4) 配置文件压过内置默认：mode / snapshotEntries / legacy -----------------
    write(cfg_path, dump({"mode": "digest", "container": CONTAINER, "lessons": "lessons",
                          "snapshotEntries": 2, "legacy": ["0001-*"]}))
    r = run(proj, "mode")
    ok(r.stdout.startswith("digest") and "配置文件的 `mode`" in r.stdout,
       "mode: without a 精细度 field the config's mode is the initial tier", r.stdout)
    r = run(proj, "snapshot")
    ok("最近 2 / 共 3 篇" in r.stdout,
       "snapshot: the entries default comes from the config's snapshotEntries", r.stdout)
    r = run(proj, "config")
    ok("0001-*" in cfg_line(r.stdout, "legacy") and "← .config.json" in cfg_line(r.stdout, "legacy"),
       "config: legacy comes from the file", r.stdout)

    # 5) 命令行压过配置文件 --------------------------------------------------
    r = run(proj, "snapshot", "--entries", "1")
    ok("最近 1 / 共 3 篇" in r.stdout, "snapshot --entries beats the config's snapshotEntries",
       r.stdout)
    r = run(proj, "config", "--legacy", "0002-*")
    ok("0002-*" in cfg_line(r.stdout, "legacy") and "← 命令行" in cfg_line(r.stdout, "legacy"),
       "config --legacy beats the config file and says so", r.stdout)
    write(cfg_path, dump({"legacy": []}))
    r = run(proj, "check", "--strict", "--quiet", "--legacy", "0003-*")
    ok(r.returncode == 0, "check --legacy beats the config's legacy list", r.stdout + r.stderr)

    # 配置文件里的 legacy 真的参与判定：显式空清单 = 没有旧记录 = 照新格式判
    write(cfg_path, dump({"legacy": ["0003-*"]}))
    r = run(proj, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "config: the config's legacy list really narrows the opt-in",
       r.stdout + r.stderr)
    write(cfg_path, dump({"legacy": []}))
    r = run(proj, "check", "--strict", "--quiet")
    ok(r.returncode != 0,
       "config: an explicit empty legacy list means every record is judged as new", r.stdout)
    os.remove(cfg_path)
    r = run(proj, "check", "--strict", "--quiet")
    ok(r.returncode != 0 and os.path.isfile(cfg_path) is False,
       "config: without a config file the small container is judged as a new project (unchanged)",
       r.stdout)

    # 6) `config --set`：只改目标行，CRLF 与其余字段都不动 --------------------
    write(cfg_path, dump({"mode": "full", "container": CONTAINER, "lessons": "lessons",
                          "legacy": ["0003-*"], "snapshotEntries": 2}, nl="\r\n"))
    before_bytes = read_bytes(cfg_path)
    r = run(proj, "config", "--set", "mode=摘要")
    ok(r.returncode == 0, "config --set exits 0", r.stdout + r.stderr)
    after_bytes = read_bytes(cfg_path)
    ok(b"\r\n" in after_bytes and after_bytes.replace(b"\r\n", b"").count(b"\n") == 0,
       "config --set preserves CRLF")
    changed = [i for i, (a, b) in enumerate(zip(before_bytes.split(b"\r\n"),
                                               after_bytes.split(b"\r\n"))) if a != b]
    # 只在"真的改了一行"时才去看那一行：`changed[0]` 在 changed 为空时是空的，直接取下标会在
    # 调用点抛 IndexError、把整相带走（同族的坑见 `safe` / `block_with` 上面那段注释）。
    if changed:
        ok(len(changed) == 1 and b'"digest"' in after_bytes.split(b"\r\n")[changed[0]],
           "config --set changes only the target line", f"changed lines={changed}")
    else:
        ok(False, "config --set changes only the target line", "一行都没变")
    data = safe(lambda: json.loads(read(cfg_path)), {})
    ok(isinstance(data, dict) and data.get("mode") == "digest" and data.get("legacy") == ["0003-*"]
       and data.get("snapshotEntries") == 2 and data.get("lessons") == "lessons",
       "config --set keeps every other field (and normalises 摘要 to digest)", str(data))
    ok("mode=digest" in r.stdout, "config --set reports what it wrote", r.stdout)

    # 一次改两个字段也认
    r = run(proj, "config", "--set", "snapshotEntries=5", "--set", "legacy=0001-*,0002-*")
    data = safe(lambda: json.loads(read(cfg_path)), {})
    ok(r.returncode == 0 and isinstance(data, dict) and data.get("snapshotEntries") == 5
       and data.get("legacy") == ["0001-*", "0002-*"],
       "config --set accepts several fields at once", read(cfg_path))

    # 7) 校验：未知值 / 未知字段 / 非正整数 各自非零退出，且不改文件 --------------
    before_bytes = read_bytes(cfg_path)
    r = run(proj, "config", "--set", "mode=详细点")
    ok(r.returncode == 2 and "认不出的精细度" in r.stdout and "milestone" in r.stdout,
       "config --set rejects an unknown mode with exit 2 and lists the values", r.stdout)
    r = run(proj, "config", "--set", "没那么个字段=x")
    ok(r.returncode == 2 and "认不出的字段" in r.stdout and "snapshotEntries" in r.stdout,
       "config --set rejects an unknown field and lists the valid ones", r.stdout)
    r = run(proj, "config", "--set", "snapshotEntries=0")
    ok(r.returncode == 2 and "正整数" in r.stdout,
       "config --set rejects a non-positive snapshotEntries", r.stdout)
    r = run(proj, "config", "--set", "snapshotEntries=abc")
    ok(r.returncode == 2, "config --set rejects a non-numeric snapshotEntries", r.stdout)
    r = run(proj, "config", "--set", "lessons=a/b")
    ok(r.returncode == 2, "config --set rejects a lessons value that is not a directory name",
       r.stdout)
    r = run(proj, "config", "--set", "mode=session", "--dry-run")
    ok(r.returncode == 0 and "[dry-run]" in r.stdout,
       "config --set --dry-run writes nothing", r.stdout)
    ok(read_bytes(cfg_path) == before_bytes,
       "every rejected (or dry-run) --set leaves the file byte-identical")

    # 8) 名字字段的不对称：不一致时**报出来**，但以实际目录为准，且不失败 ----------
    write(cfg_path, dump({"container": "archive_log", "lessons": "nosuch"}))
    r = run(proj, "config")
    ok(r.returncode == 0, "a config whose name fields disagree is reported, not fatal",
       r.stdout + r.stderr)
    ok("archive_log" in r.stdout and "管不了自己所在的目录" in r.stdout,
       "config: a container field that disagrees with its own directory is reported", r.stdout)
    ok("nosuch" in r.stdout and "按实际目录走" in r.stdout,
       "config: a lessons field that disagrees with the existing directory is reported", r.stdout)
    ok(cfg_line(r.stdout, "container").split("=")[1].split("←")[0].strip() == CONTAINER,
       "config: the disagreeing container field is NOT obeyed", r.stdout)
    ok(cfg_line(r.stdout, "lessons").split("=")[1].split("←")[0].strip() == "lessons",
       "config: the discovered lessons directory wins over the disagreeing field", r.stdout)
    r = run(proj, "check", "--legacy", "0003-*")
    ok(r.returncode == 0 and "[ERROR]" not in r.stdout,
       "the advisory mismatch does not raise check's level (info at most)", r.stdout + r.stderr)
    ok("[INFO] work_log/.config.json" in r.stdout,
       "check surfaces the advisory mismatch as info", r.stdout)

    # 9) 台账的 `精细度` 压过配置的 `mode` ------------------------------------
    write(cfg_path, dump({"mode": "digest"}))
    write(ledger, fmt_ledger(["0001-work.md", "0002-more.md", "0003-只有设置.md"],
                             status="2026-09-14", mode="session"))
    r = run(proj, "mode")
    ok(r.stdout.startswith("session"),
       "the ledger's 精细度 wins over the config's mode", r.stdout)
    ok("配置文件的 `mode`" not in r.stdout,
       "and the config's mode is not reported once the ledger carries the field", r.stdout)

    # 台账没有那一栏时，粗档位（来自配置）照样担它的额外义务
    write(ledger, fmt_ledger(["0001-work.md", "0002-more.md", "0003-只有设置.md"],
                             status="2026-09-14", mode=None))
    r = run(proj, "lint", "--legacy", "")
    ok("未记录" in r.stdout,
       "lint: a coarse mode coming from the config carries the 未记录 obligation", r.stdout)
    ok(r.returncode == 0, "lint: that obligation is a WARN, not an ERROR", r.stdout)

    # 10) `--set` 没有配置文件时拒绝，并指路 `--write` --------------------------
    os.remove(cfg_path)
    r = run(proj, "config", "--set", "mode=full")
    ok(r.returncode != 0 and "--write" in r.stdout,
       "config --set refuses when there is no config file and points at --write",
       r.stdout + r.stderr)
    ok(not os.path.exists(cfg_path), "the refused --set created nothing")

    # 11) 配置文件跟着容器走：命令行指定哪个容器，读的就是哪一份 ----------------
    alt = os.path.join(parent, "configalt")
    os.makedirs(os.path.join(alt, "work_log"))
    os.makedirs(os.path.join(alt, "journal"))
    # 空容器的台账：没有记录，只为让容器被发现（`config` 只看目录与配置文件）。
    for name, mode in (("work_log", "session"), ("journal", "milestone")):
        write(os.path.join(alt, name, "README.md"), fmt_ledger([], status="2026-09-14"))
        write(os.path.join(alt, name, ".config.json"), dump({"mode": mode}))
    r = run(alt, "config")
    ok("session" in cfg_line(r.stdout, "mode") and "work_log" in r.stdout,
       "config: the default container's config is the one that is read", r.stdout)
    r = run(alt, "config", "--work-log", "journal")
    ok("milestone" in cfg_line(r.stdout, "mode"),
       "--work-log selects the container, and that container's config is read", r.stdout)

    # 12) 坏配置文件：不致命，但报清楚（`config` 退出码 2，`check` 报 INFO 不进退出码）----
    write(cfg_path, "{ 这不是 JSON\n")
    r = run(proj, "config")
    ok(r.returncode == 2 and "不是合法 JSON" in r.stdout,
       "config: a malformed config file is reported with a non-zero exit", r.stdout)
    ok(r.stdout.count("← 内置默认") == 5,
       "config: a malformed config file falls back to the built-in defaults", r.stdout)
    r = run(proj, "outline")
    ok(r.returncode == 0, "a malformed config file does not break the other commands",
       r.stdout + r.stderr)
    r = run(proj, "check", "--legacy", "0003-*")
    ok("[INFO] work_log/.config.json" in r.stdout and r.returncode == 0,
       "check surfaces a malformed config file as info, without failing", r.stdout)
    r = run(proj, "check", "--strict", "--quiet", "--legacy", "0003-*")
    ok(r.returncode == 0, "a malformed config file never fails check --strict", r.stdout + r.stderr)
    r = run(proj, "config", "--set", "mode=full")
    ok(r.returncode != 0, "config --set refuses to edit a malformed config file", r.stdout)

    # 认不出的字段名：文件里多一个键，`config` 报出来（退出码 2），但不影响生效值
    write(cfg_path, dump({"mode": "full", "typo": 1}))
    r = run(proj, "config")
    ok(r.returncode == 2 and "认不出的字段 `typo`" in r.stdout,
       "config: an unknown field in the file is reported with the valid field list", r.stdout)
    ok("full" in cfg_line(r.stdout, "mode"),
       "config: the known fields still take effect next to an unknown one", r.stdout)


# ---- 目标文件（`<容器>/目标.md`，可选）-------------------------------------
# 只校验三条机械规则：引用的篇号必须存在、状态是那四个之一、一个目标的第一行必须写目标名。
# **缺这个文件是正常的**（三个真实语料里一个都没有），缺它必须报 0 个问题；
# 它也**不进任何必填清单**（不进索引、不改 `is_record_name`）。
GOALS_HEAD = """# 目标

| 目标 | 阶段 | 状态 | 相关记录 |
|---|---|---|---|
"""


def goals_file(*rows: str) -> str:
    """目标文件的正文；`rows` 逐行给数据行（行号因此可预期：首行数据在第 5 行）。"""
    return GOALS_HEAD + "".join(r + "\n" for r in rows)


def goals_phase(parent: str) -> None:
    """目标表：三条机械规则各自报什么、什么不报、缺文件零发现。"""

    proj = os.path.join(parent, "goalsproj")
    os.makedirs(os.path.join(proj, CONTAINER))
    files = ["0001-work.md", "0002-more.md", "0003-third.md"]
    for i, fname in enumerate(files, 1):
        write(os.path.join(proj, CONTAINER, fname), entry(f"{i:04d}", f"第 {i} 篇", "2026-09-20"))
    write(os.path.join(proj, CONTAINER, "README.md"), fmt_ledger(files, status="2026-09-20"))
    gpath = os.path.join(proj, CONTAINER, "目标.md")

    def gfind() -> str:
        """只取目标文件那几条发现：夹具里别的问题（断档之类）不该混进断言。"""
        r = run(proj, "check", "--strict", "--quiet")
        return "\n".join(l for l in r.stdout.splitlines() if "目标.md" in l)

    def clean() -> tuple[bool, str]:
        """整份 `check --strict --quiet` 是否 0 发现（`--quiet` 只留 ERROR/WARN 与汇总行）。"""
        r = run(proj, "check", "--strict", "--quiet")
        return (r.returncode == 0 and "[ERROR]" not in r.stdout and "[WARN]" not in r.stdout,
                r.stdout + r.stderr)

    # 0) 四个状态就是约定的那四个（断言常量本身，不从输出倒推）
    ok(JOURNAL.GOALS_STATUSES == ("未开始", "进行中", "已完成", "已放弃"),
       "goals: 状态 is exactly the documented four-value set", str(JOURNAL.GOALS_STATUSES))
    # `目标.md` 不是记录：判据只有 `is_record_name` 一处，不用给常量加名字。
    ok(not JOURNAL.is_record_name(JOURNAL.GOALS_FILE),
       "goals: 目标.md is not a record name (no constant needs changing)",
       JOURNAL.GOALS_FILE)

    # 1) 没有这个文件：0 个发现，整份 check --strict 也干净
    ok(not os.path.exists(gpath), "goals: the fixture starts without a goals file")
    okay, detail = clean()
    ok(okay, "goals: a missing 目标.md produces no findings at all", detail)
    ok(gfind() == "", "goals: and nothing is reported about the absent file", gfind())

    # 2) 合法两层表：续行为空、单阶段写 `—`、四个状态各出现一次 → 0 个发现
    write(gpath, goals_file("| 让 worklog 可公开发布 | 规范重写 | 已完成 | 0001, 0002 |",
                            "|  | 设置页 | 进行中 | 0003 |",
                            "|  | 文档收尾 | 未开始 | — |",
                            "| 支持多语言 | — | 进行中 | 0001 |",
                            "| 已经放弃的旧目标 | 第一版 | 已放弃 | — |"))
    ok(gfind() == "", "goals: a valid two-level table produces no findings", gfind())
    okay, detail = clean()
    ok(okay, "goals: a valid goals file keeps check --strict clean", detail)

    # 3) 引用的篇号必须真实存在——这是这三条规则的核心价值
    write(gpath, goals_file("| 目标甲 | 阶段一 | 进行中 | 0001, 0099 |"))
    ok("`0099`" in gfind() and "不存在" in gfind() and "[ERROR]" in gfind(),
       "goals: a cited record that does not exist is reported as an ERROR", gfind())
    ok("`0001`" not in gfind(),
       "goals: the citations that do exist are not reported", gfind())
    # 整格不是篇号的 token（`—`、自由文字、日期式文件名）一律跳过——误报比漏报贵
    write(gpath, goals_file("| 目标甲 | 阶段一 | 进行中 | — |",
                            "| 目标乙 | — | 未开始 | 2026-09-06-门控两段式.md |",
                            "| 目标丙 | — | 未开始 | 待定 |"))
    ok(gfind() == "",
       "goals: cells that are not a bare 篇号 (—, a date-style filename, prose) are skipped",
       gfind())

    # 4) 四个状态逐个接受，第五个（拼错）报出来
    for st in ("未开始", "进行中", "已完成", "已放弃"):
        write(gpath, goals_file(f"| 目标甲 | 阶段一 | {st} | 0001 |"))
        ok(gfind() == "", f"goals: 状态 {st} is accepted", gfind())
    write(gpath, goals_file("| 目标甲 | 阶段一 | 进行重 | 0001 |"))
    ok("进行重" in gfind() and "认不出" in gfind(),
       "goals: an invalid 状态 is reported", gfind())
    write(gpath, goals_file("| 目标甲 | 阶段一 |  | 0001 |"))
    ok("状态为空" in gfind(), "goals: an empty 状态 is reported as such", gfind())

    # 5) 首行为空 = 续行没有父行 → 报；同名表格里紧跟其后的续行不重复报
    write(gpath, goals_file("|  | 阶段一 | 进行中 | 0001 |",
                            "|  | 阶段二 | 未开始 | — |",
                            "| 目标乙 | — | 进行中 | — |"))
    ok("第 5 行" in gfind() and "第 6 行" in gfind(),
       "goals: goal cells that are empty before any goal name are reported", gfind())
    ok("第 7 行" not in gfind(),
       "goals: a goal name anywhere above keeps a later empty cell legal", gfind())

    # 6) 目标文件**不需要**进索引：索引覆盖只遍历真记录，不该刷出「未出现在索引中」
    write(gpath, goals_file("| 目标甲 | 阶段一 | 进行中 | 0001 |"))
    r = run(proj, "check", "--strict", "--quiet")
    ok(r.returncode == 0 and "未出现在索引中" not in r.stdout,
       "goals: 目标.md is never required to appear in the index", r.stdout + r.stderr)

    # 7) 认不出表头 = 没有可校验的表 → 不报（校验只覆盖那三条，不给文件加第四条义务）
    write(gpath, "# 目标\n\n还没写成表，先记一句。\n")
    ok(gfind() == "", "goals: a file without a recognisable table header produces no findings",
       gfind())



def run_env(root: str, env: dict, *argv: str) -> subprocess.CompletedProcess:
    """带环境变量跑一次。全局记忆的隔离钩子（`DSH_WORKLOG_MEMORY`）靠它验。"""
    e = dict(os.environ)
    e.update(env)
    r = subprocess.run([sys.executable, TOOL, *argv],
                       cwd=root, capture_output=True, text=False, env=e)
    r.stdout, r.stderr = decode_output(r.stdout), decode_output(r.stderr)
    return r


# ---- 全局记忆（跨工作区）---------------------------------------------------
# 规格：publish/worklog/docs/memory-spec.md。**每一条命令都带 `--memory <临时目录>`**：
# 绝不能碰用户真实的记忆库 —— 这正是 `DSH_WORKLOG_MEMORY` 那一档存在的理由
# （这个坑我们在设置文件上已经踩过一次）。
MEM_LEDGER = """# 记录

## 文件索引

### A. 起步

| 文件 | 方面 |
|---|---|
| [0001-seed.md](0001-seed.md) | 起步 |

## 待办（滚动清单）

- [ ] keep

## 当前状态（2026-09-20）

- 阶段 / 版本：v1
"""


def mem_rec(num: str, title: str, date: str = "2026-09-20") -> str:
    return (f"# {num} · {title}\n\n日期：{date}\n迭代：1\n触发：t\n范围：n\n"
            f"结论：312 tests green\n\n---\n\n## 一、背景与事实核查\n\nx\n\n"
            f"## 二、验证\n\n- 方式：`pytest -q`\n- 结果：312 passed\n- 未覆盖：-\n")


def mem_ws(base: str, name: str, lessons: str, nums: tuple[str, ...] = ("0001", "0002")) -> str:
    """搭一个最小工作区：容器 + 若干记录 + 一份经验分册。"""
    ws = os.path.join(base, name)
    os.makedirs(os.path.join(ws, "work_log", "lessons"))
    write(os.path.join(ws, "work_log", "README.md"), MEM_LEDGER)
    for n in nums:
        write(os.path.join(ws, "work_log", f"{n}-seed.md"), mem_rec(n, f"第 {n} 篇"))
    write(os.path.join(ws, "work_log", "lessons", "README.md"),
          "# 经验手册\n\n| 分册 | 内容 |\n|---|---|\n| [01-topic.md](01-topic.md) | x |\n")
    write(os.path.join(ws, "work_log", "lessons", "01-topic.md"), lessons)
    return ws


def mem_snapshot(root: str) -> dict[str, bytes]:
    """整棵记忆根的快照（相对路径 → 字节）。幂等就是"再跑一次，这棵树一个字节都没变"。"""
    out: dict[str, bytes] = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            p = os.path.join(dp, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = fh.read()
    return out


def memory_phase(parent: str) -> None:
    """隔离包装：整相把 `DSH_HOME` 与 `USERPROFILE`/`HOME` 一起指进夹具，再跑 `_memory_phase`。

    **为什么只靠 `--memory` 与 `$DSH_WORKLOG_MEMORY` 不够**：记忆根是四级解析
    （`--memory` > 设置文件里的 `memoryDir` > `$DSH_WORKLOG_MEMORY` > 默认 `<用户主目录>/dsh-lore-memory`），
    而这一相里前两档 **都被专门测过** —— 变异驱动正是拿它们开刀：`reverse-verify.py` 的 memory 相里
    「`--memory` 不再覆盖路径」与「环境变量那一档失效」两条，就是把前两档打断。
    两条一断，兜底就落到第四级：**用户真实的**那个默认根。

    **2026-10-17：这道兜底曾经静默失效过，而且没人发现。** 2026-09-28 的老事故（真实记忆库里
    留下 8 条 `wsA` 夹具条目、并被注入每个请求，清理记录见 `work_log/06-release-060/0051`）
    当时的修法是钉 `DSH_HOME` —— 那时第四级还是 `$DSH_HOME/memory`，钉得住。
    **0.8.0 把第四级换成了 `<用户主目录>/dsh-lore-memory`（走 `os.path.expanduser("~")`），
    `DSH_HOME` 从那天起就罩不住它**：同一种事故在 2026-10-15 ~ 10-17 又发生了 9 次，
    真实库里攒下 54 条夹具工作区路径（`workspaces.json` 里一条真工作区都没有），
    并且被当成"跨工作区记忆"注入每场会话。`ntpath.expanduser` 认 `USERPROFILE`
    （POSIX 认 `HOME`），所以两个都钉，第四级才真正落在夹具里。

    最后那条**前置断言**是这一课的重点：钉不住就**当场**红，而不是等事后发现库里多了东西 ——
    事后发现意味着泄漏已经写进用户真实的库、而且已经进了注入。变异要红的那两条断言都是
    **进程内**比对，不受这里影响。
    """
    saved = {name: os.environ.get(name)
             for name in ("DSH_HOME", "USERPROFILE", "HOME", "DSH_WORKLOG_SETTINGS")}
    fixture_home = os.path.join(parent, "home")
    os.environ["DSH_HOME"] = fixture_home
    os.environ["USERPROFILE"] = fixture_home
    os.environ["HOME"] = fixture_home
    # 设置文件那一档（第二级）也要落在夹具里：用户真实环境里若设了 `$DSH_WORKLOG_SETTINGS`
    # 或 `memoryDir`，它会把根指回真实库 —— 子测试各自显式传这个变量，不靠继承。
    os.environ.pop("DSH_WORKLOG_SETTINGS", None)
    try:
        default_root = JOURNAL.memory_root(None)
        ok(os.path.abspath(default_root).startswith(os.path.abspath(fixture_home) + os.sep),
           "memory: 第四级兜底钉在夹具里（不给 --memory 也落不到用户真实的库）", default_root)
        _memory_phase(parent)
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _memory_phase(parent: str) -> None:
    """全局记忆：来源分档 / 清单往返 / 收集幂等 / 索引 / 门禁 / 收敛 / 信箱 / 升格。"""
    base = os.path.join(parent, "memory")
    mem = os.path.join(base, "mem")
    os.makedirs(mem)

    def jr(cwd: str, *argv: str) -> subprocess.CompletedProcess:
        return run(cwd, *argv)

    def m(cwd: str, *argv: str) -> subprocess.CompletedProcess:
        """记忆命令：一律显式 `--memory`，把真实记忆库挡在门外。"""
        return run(cwd, *argv, "--memory", mem)

    def ments() -> list[dict]:
        return JOURNAL.load_memory_entries(mem)

    # --- 0) 常量与路径：断言常量本身，不从输出倒推 ---------------------------
    ok(JOURNAL.MEMORY_SOURCES_IN_INDEX == ("tested", "read"),
       "memory: 进索引的 manual 档就是 tested / read", str(JOURNAL.MEMORY_SOURCES_IN_INDEX))
    ok("inferred" not in JOURNAL.MEMORY_SOURCES_IN_INDEX,
       "memory: manual:inferred 永远不在进索引的档里")
    ok(JOURNAL.MEMORY_STATES == ("active", "stale", "retired"),
       "memory: 三态就是约定那三个", str(JOURNAL.MEMORY_STATES))
    ok(JOURNAL.MEMORY_INDEX_SOFT_CHARS < JOURNAL.MEMORY_INDEX_HARD_CHARS,
       "memory: 软目标小于硬上限（否则那句提醒没有意义）")
    ok(JOURNAL.memory_root(mem) == os.path.abspath(mem), "memory: --memory 覆盖整条路径")
    ok(JOURNAL.memory_root().endswith(JOURNAL.MEMORY_DIR_NAME),
       "memory: 不给 --memory 时落在默认根（用户主目录下的 MEMORY_DIR_NAME）", JOURNAL.memory_root())
    ok(JOURNAL.MEMORY_DIR_NAME == "dsh-lore-memory",
       "memory: 默认根目录名是 dsh-lore-memory（2026-10-14 起不再挂在 $DSH_HOME 下）",
       JOURNAL.MEMORY_DIR_NAME)

    # --- 宿主设置里的 memoryDir 那一档（2026-10-14 加）------------------------
    # 为什么必须测：卡片把记忆根改到别处之后，CLI 若不认这个字段，写入会落在旧根、
    # 而插件从新根读 —— 写进去的东西读不出来，且**不报错**。这是最坏的一类失效。
    fake_home = os.path.join(base, "fake-dsh-home")
    os.makedirs(os.path.join(fake_home, "worklog"), exist_ok=True)
    settings = os.path.join(fake_home, "worklog", "settings.json")
    saved_dsh_home = os.environ.get("DSH_HOME")
    os.environ["DSH_HOME"] = fake_home
    try:
        ok(JOURNAL.memory_root().endswith(JOURNAL.MEMORY_DIR_NAME),
           "memory: 没有设置文件时仍落默认根", JOURNAL.memory_root())
        # 绝对路径这一档必须**按平台现算**：写死 `C:/tmp/...` 在 Windows 上是绝对路径，
        # 在 Linux 上却会被 `os.path.isabs` 判成相对路径，于是拼到 `~` 下变成
        # `/home/runner/C:/tmp/lore-from-settings` —— CI（ubuntu）上就是这条断言红过。
        abs_dir = os.path.abspath(os.path.join(os.sep, "tmp", "lore-from-settings"))
        with open(settings, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"memoryDir": abs_dir}))
        ok(JOURNAL.memory_root() == abs_dir,
           "memory: 设置里的 memoryDir（绝对路径）说了算", JOURNAL.memory_root())
        with open(settings, "w", encoding="utf-8") as fh:
            fh.write('{"memoryDir": "lore-relative"}')
        ok(JOURNAL.memory_root() == os.path.join(os.path.expanduser("~"), "lore-relative"),
           "memory: 相对路径按**用户主目录**解析（与技能目录的包根口径不同）",
           JOURNAL.memory_root())
        with open(settings, "w", encoding="utf-8") as fh:
            fh.write('{not json at all')
        ok(JOURNAL.memory_root().endswith(JOURNAL.MEMORY_DIR_NAME),
           "memory: 设置文件坏了就退回默认根，不抛异常", JOURNAL.memory_root())
        with open(settings, "w", encoding="utf-8") as fh:
            fh.write('{"memoryDir": "from-settings"}')
        os.environ["DSH_WORKLOG_MEMORY"] = mem
        try:
            ok(JOURNAL.memory_root() == os.path.join(os.path.expanduser("~"), "from-settings"),
               "memory: 设置里的 memoryDir 压过 $DSH_WORKLOG_MEMORY（卡片 > 环境变量）",
               JOURNAL.memory_root())
        finally:
            os.environ.pop("DSH_WORKLOG_MEMORY", None)
    finally:
        if saved_dsh_home is None:
            os.environ.pop("DSH_HOME", None)
        else:
            os.environ["DSH_HOME"] = saved_dsh_home

    saved_env = os.environ.get("DSH_WORKLOG_MEMORY")
    os.environ["DSH_WORKLOG_MEMORY"] = mem
    try:
        ok(JOURNAL.memory_root() == os.path.abspath(mem),
           "memory: $DSH_WORKLOG_MEMORY 覆盖整条路径（harness 的隔离钩子）")
    finally:
        if saved_env is None:
            os.environ.pop("DSH_WORKLOG_MEMORY", None)
        else:
            os.environ["DSH_WORKLOG_MEMORY"] = saved_env
    r = run_env(base, {"DSH_WORKLOG_MEMORY": mem}, "memory", "status")
    ok(r.returncode == 0 and os.path.abspath(mem) in r.stdout,
       "memory: 环境变量那一档在真进程里也生效（不必每次传 --memory）", r.stdout + r.stderr)

    # --- 1) 来源分档：五档逐条过 ---------------------------------------------
    ok(JOURNAL.memory_source_tier("wl/0001") == "record", "memory: `wl/NNNN` 是记录档")
    ok(JOURNAL.memory_source_tier("wsA/wl/0001") == "record",
       "memory: `<工作区>/wl/NNNN` 也是记录档")
    ok(JOURNAL.memory_source_tier("manual:tested") == "tested", "memory: manual:tested 分得出")
    ok(JOURNAL.memory_source_tier("manual:read") == "read", "memory: manual:read 分得出")
    ok(JOURNAL.memory_source_tier("manual:inferred") == "inferred",
       "memory: manual:inferred 分得出（它被**允许**，只是不进索引）")
    ok(JOURNAL.memory_source_tier("") == "" and JOURNAL.memory_source_tier("wiki:x") == "",
       "memory: 认不出的来源一律空档（那一档就是「拒绝」）")
    ok(JOURNAL.memory_source_in_index("manual:inferred") is False
       and JOURNAL.memory_source_in_index("manual:tested") is True
       and JOURNAL.memory_source_in_index("wl/1") is True,
       "memory: 进不进索引由档位决定，不由人判断")

    wsA = mem_ws(base, "wsA",
                 "# 01 · 构建与环境\n\n"
                 "- **样式被别的插件认领**：注册表按名去重。根因：先到先得。"
                 "做法：注册前先查。（`wl/0001`）\n"
                 "- **构建缓存串味**：缓存键少了一维。根因：键没带环境。"
                 "做法：键里加环境。（`wl/0002`）\n")
    wsB = mem_ws(base, "wsB", "# 01 · 构建与环境\n\n- 无来源的结论不进经验层。\n")

    # 位置参数顺序：根目录在**正文之前**（与全 CLI 一致）-------------------------
    #
    # 起因：整体功能实跑时按"根在前"的直觉写，拿到一个指错方向的报错——`memory add` 当时把
    # `text` 声明在 `root` 之前。改顺序本身有个**静默陷阱**：旧写法下 `text` 收到的是路径，
    # 而 `manual:*` 来源根本用不到根目录，于是它会安静地成功、把路径写成正文（实测过）。
    # 所以三条都要钉住，且单独用一个记忆根，免得扰动后面的条目计数。
    mem2 = os.path.join(base, "mem-order")
    os.makedirs(mem2)

    def m2(cwd: str, *argv: str) -> subprocess.CompletedProcess:
        return run(cwd, *argv, "--memory", mem2)

    # ① 根在前是**有效**的：用 `wl/NNNN` 来源逼出根目录的解析（manual 档不看根，测不出来）
    r = m2(parent, "memory", "add", wsA, "指向本工作区记录的一条。", "--source", "wl/0001",
           "--id", "root-first")
    ok(r.returncode == 0,
       "memory: the root argument comes before the text, and it is honoured", r.stdout + r.stderr)
    entries = JOURNAL.load_memory_entries(mem2)
    ok(any(e["id"] == "root-first" and e["body"] == ["指向本工作区记录的一条。"] for e in entries),
       "memory: the prose lands in the entry, the root does not",
       str([e for e in entries if e["id"] == "root-first"]))
    # ② 旧写法（文本在前、根在后）必须被拦下，而不是把路径存成正文
    r = m2(parent, "memory", "add", "一句教训文本", wsA,
           "--source", "manual:tested", "--id", "root-last")
    ok(r.returncode != 0 and "根目录" in r.stdout,
       "memory: the old order is refused instead of silently storing the path", r.stdout + r.stderr)
    ok(all(e["id"] != "root-last" for e in JOURNAL.load_memory_entries(mem2)),
       "memory: and the refused call wrote nothing")
    # ③ 只给一个路径（把根当成正文）同样拦下，并给出正确写法
    r = m2(parent, "memory", "add", wsA, "--source", "manual:tested", "--id", "only-a-path")
    ok(r.returncode != 0 and "正文" in r.stdout,
       "memory: a bare path as the only positional is refused as well", r.stdout + r.stderr)

    # 认不出的来源 → 拒绝
    r = m(wsA, "memory", "add", "来源认不出的东西。", "--source", "wiki:something",
          "--id", "bad-source")
    ok(r.returncode != 0 and "认不出" in r.stdout, "memory: 认不出的来源被拒绝", r.stdout + r.stderr)
    r = m(wsA, "memory", "add", "没写来源。", "--source", "", "--id", "empty-source")
    ok(r.returncode != 0, "memory: 空来源也被拒绝", r.stdout)
    # `wl/NNNN` 指向不存在的记录 → 拒绝（这一条走的是 lesson add 那条既有解析路径）
    r = m(wsA, "memory", "add", "指向删掉的记录。", "--source", "wl/0009", "--id", "gone-rec")
    ok(r.returncode != 0 and "不存在" in r.stdout,
       "memory: wl/NNNN 指向不存在的记录被拒绝", r.stdout)
    # 裸 `wl/NNNN`：本工作区的真实记录
    r = m(wsA, "memory", "add", "构建缓存要带上环境维度。", "--source", "wl/0002",
          "--id", "cache-key-env", "--applies-to", "python-stdlib-tooling")
    ok(r.returncode == 0, "memory: 裸 wl/NNNN 来源被接受（核到真实记录）", r.stdout + r.stderr)
    # 带工作区前缀的记录来源：核到那个工作区的**发布清单**
    r = m(wsA, "memory", "publish", wsA, "--applies-to", "dsh-plugin", "--upload")
    ok(r.returncode == 0, "memory: publish 写清单并登记名册", r.stdout + r.stderr)
    mpath = os.path.join(wsA, "work_log", "发布.md")
    ok(os.path.isfile(mpath), "memory: 发布清单落在容器根（<容器>/发布.md）")
    parsed = JOURNAL.parse_manifest(read(mpath))
    ok(parsed["applies-to"] == ["dsh-plugin"], "memory: 清单往返 applies-to",
       str(parsed["applies-to"]))
    ok(parsed["upload"] is True, "memory: 清单往返 upload")
    ok([i["ref"] for i in parsed["items"]] == ["wl/0001", "wl/0002"],
       "memory: 清单往返条目（按经验层里出现的顺序）", str([i["ref"] for i in parsed["items"]]))
    ok(parsed["items"][0]["id"] == "wl-0001",
       "memory: 没写 `→ id:` 时按引用机械兜底", parsed["items"][0]["id"])
    # 手改 id 之后再 publish，不能把手写的 id 抹掉
    write(mpath, read(mpath).replace("→  id: wl-0001", "→  id: host-style-claiming"))
    r = m(wsA, "memory", "publish", wsA)
    ok("→  id: host-style-claiming" in read(mpath),
       "memory: 再 publish 时保留手写的 id（草稿只是起点）", read(mpath))
    r = m(wsA, "memory", "add", "样式的注册顺序决定谁赢。", "--source", "wsA/wl/0001",
          "--id", "host-style-claiming", "--applies-to", "dsh-plugin", "--volume",
          "01-dsh-plugin.md")
    ok(r.returncode == 0,
       "memory: 带工作区前缀的来源（就是本工作区）核到真实记录", r.stdout)
    # 真正走**清单**那条路：从别的工作区引用它 —— 那时全局层读不到 wsA 的记录，
    # 唯一能核的就是 wsA 的发布清单。这三条把"清单是唯一的跨工作区凭据"钉住。
    r = m(wsB, "memory", "add", "别的工作区确证过的教训。", "--source", "wsA/wl/0001",
          "--id", "cited-from-wsa")
    ok(r.returncode == 0, "memory: `<工作区>/wl/NNNN` 来源核到那份发布清单", r.stdout)
    r = m(wsB, "memory", "add", "清单没点名的引用。", "--source", "wsA/wl/0003",
          "--id", "not-named")
    ok(r.returncode != 0 and "没有点名" in r.stdout,
       "memory: 清单没点名的记录引用被拒绝（清单是双向白名单）", r.stdout)
    r = m(wsB, "memory", "add", "没登记的工作区。", "--source", "wsGhost/wl/0001",
          "--id", "ghost-ws")
    ok(r.returncode != 0 and "不在名册里" in r.stdout,
       "memory: 来源里的工作区没登记时被拒绝", r.stdout)
    # manual:tested 要有可核对结果（add 只准入，判据在 lint）
    r = m(wsA, "memory", "add", "跑过 `pytest -q`，312 passed。", "--source", "manual:tested",
          "--id", "tested-ok", "--applies-to", "python-stdlib-tooling")
    ok(r.returncode == 0, "memory: manual:tested 被接受", r.stdout)
    r = m(wsA, "memory", "add", "做过，没问题。", "--source", "manual:tested",
          "--id", "tested-bare", "--applies-to", "python-stdlib-tooling")
    ok(r.returncode == 0, "memory: manual:tested 缺结果也**能进**（判据交给 lint）", r.stdout)
    r = m(wsA, "memory", "add", "见 `docs/conventions.md` 的目录布局一节。",
          "--source", "manual:read", "--id", "read-ok", "--applies-to", "python-stdlib-tooling")
    ok(r.returncode == 0, "memory: manual:read 被接受", r.stdout)
    r = m(wsA, "memory", "add", "某处提到过这件事。", "--source", "manual:read",
          "--id", "read-bare", "--applies-to", "python-stdlib-tooling")
    ok(r.returncode == 0, "memory: manual:read 缺出处也**能进**（判据交给 lint）", r.stdout)
    r = m(wsA, "memory", "add", "推断：注册表大概按名去重。", "--source", "manual:inferred",
          "--id", "infer-bare")
    ok(r.returncode != 0 and "未经证实" in r.stdout,
       "memory: manual:inferred 不标注「未经证实」被拒绝"
       "（堵死推断的结果是推断被伪装成「读过」）", r.stdout)
    r = m(wsA, "memory", "add", "未经证实：注册表大概按名去重。", "--source", "manual:inferred",
          "--id", "infer-ok")
    ok(r.returncode == 0, "memory: manual:inferred 标注了就允许进", r.stdout)
    # id 合法性与重复
    r = m(wsA, "memory", "add", "x", "--source", "manual:tested", "--id", "Bad Id")
    ok(r.returncode != 0 and "不合法" in r.stdout, "memory: 非法 id 被拒绝", r.stdout)
    r = m(wsA, "memory", "add", "x", "--source", "manual:tested", "--id", "host-style-claiming")
    ok(r.returncode != 0 and "已经存在" in r.stdout,
       "memory: 重复 id 被拒绝（id 全局唯一）", r.stdout)
    r = m(wsA, "memory", "add", "x", "--source", "manual:tested", "--id", "bad-tag",
          "--applies-to", "Bad-Tag")
    ok(r.returncode != 0 and "不合法" in r.stdout, "memory: 非法 applies-to 标签被拒绝", r.stdout)

    # --- 2) 索引：inferred 不进；tested/read 的附加要求交给 lint -----------
    def drop_entry(volume_path: str, eid: str) -> None:
        """从分册里删掉一条（**只给夹具用**；工具本身没有「删条目」这个动作）。"""
        lines = read(volume_path).splitlines(keepends=True)
        for s, e in reversed([(s, e) for s, e in JOURNAL.memory_blocks(read(volume_path))
                              if JOURNAL._memory_block_fields(lines[s:e])[0].get("id") == eid]):
            del lines[s:e]
        write(volume_path, "".join(lines))

    r = m(wsA, "memory", "index")
    ok(r.returncode == 0 and "已重建" in r.stdout, "memory: index 重建索引", r.stdout)
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok("怎么验的" in r.stdout and "指名出处" in r.stdout and r.returncode != 0,
       "memory: tested / read 的附加要求由 lint 判（add 只做准入）", r.stdout)
    volpy = os.path.join(mem, "01-python-stdlib-tooling.md")
    drop_entry(volpy, "tested-bare")
    drop_entry(volpy, "read-bare")
    m(wsA, "memory", "index")
    idx = read(JOURNAL.memory_index_path(mem))
    ok("infer-ok" not in idx, "memory: manual:inferred 不出现在索引里（这是它的准入代价）", idx)
    ok("host-style-claiming" in idx and "tested-ok" in idx and "read-ok" in idx,
       "memory: 记录档 / tested / read 都进索引", idx)
    ok(idx.startswith("# 全局记忆索引"),
       "memory: 索引第一行自证是生成物（手写就会分叉）",
       (idx.splitlines() or [""])[0])
    r = m(wsA, "memory", "index", "--check")
    ok(r.returncode == 0 and "一致" in r.stdout, "memory: index --check 一致时通过", r.stdout)
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok(r.returncode == 0, "memory: 合法语料 lint --strict 干净", r.stdout + r.stderr)

    # --- 3) 门禁：每一条都见过红 -------------------------------------------
    # manual:read 没指名出处 / manual:tested 没可核对结果
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok("[ERROR]" not in r.stdout, "memory: 上面这批条目过得了门禁", r.stdout)
    write(JOURNAL.memory_index_path(mem), idx.replace("- read-ok：", "- read-nope："))
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok("索引与正文不一致" in r.stdout and r.returncode != 0,
       "memory: 索引与正文不一致报 ERROR（漏生成 / 多出条目都算）", r.stdout)
    r = m(wsA, "memory", "index", "--check")
    ok(r.returncode != 0, "memory: index --check 在不一致时非零退出", r.stdout)
    write(JOURNAL.memory_index_path(mem), idx)
    # inferred 混进索引 → ERROR
    write(JOURNAL.memory_index_path(mem), idx + "- infer-ok：推断的东西（x）\n")
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok("不得出现在索引" in r.stdout and r.returncode != 0,
       "memory: manual:inferred 出现在索引里是 ERROR", r.stdout)
    write(JOURNAL.memory_index_path(mem), idx)
    # 手改分册：cited-by 指向没登记的工作区 / 非法标签 / 重复 id
    vol = os.path.join(mem, "01-python-stdlib-tooling.md")
    orig_vol = read(vol)
    write(vol, orig_vol.replace("cited-by: []", "cited-by: [ghost-ws]"))
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok("不是名册里已登记的工作区" in r.stdout, "memory: cited-by 引用不存在的工作区是 ERROR",
       r.stdout)
    write(vol, orig_vol.replace("applies-to: python-stdlib-tooling", "applies-to: Bad Tag"))
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok("applies-to 标签" in r.stdout, "memory: 非法 applies-to 是 ERROR", r.stdout)
    read_block = block_with(orig_vol, "id: read-ok")
    write(vol, orig_vol + "\n\n" + read_block + "\n")
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok("id `read-ok` 重复" in r.stdout, "memory: 重复 id 是 ERROR", r.stdout)
    write(vol, orig_vol)
    # 分册标题与文件名对不上 → WARN（不是 ERROR）
    vol2 = os.path.join(mem, "02-别的领域.md")
    write(vol2, "# 02 · 完全不同的领域\n\n- id: other-one\n  applies-to: x-tag\n"
                "  state: active\n  source: manual:tested\n  cited-by: []\n  跑了 `x`，3 次。\n")
    r = m(wsA, "memory", "lint", wsA)
    ok("对不上" in r.stdout and "[WARN]" in r.stdout,
       "memory: 分册标题与文件名不一致是 WARN", r.stdout)
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok("对不上" in r.stdout and "[ERROR]" in r.stdout,
       "memory: 但 --strict 把它抬成 ERROR（判不准的不判死刑，由人开 --strict）", r.stdout)
    os.remove(vol2)
    # 近似重复 → WARN / --strict ERROR
    vol3 = os.path.join(mem, "03-dup.md")
    write(vol3, "# 03 · dup\n\n"
                "- id: dup-a\n  applies-to: x-tag\n  state: active\n  source: manual:tested\n"
                "  cited-by: []\n  注册表按名去重，先到先得；做法是注册前先查名字。跑了 `x`，1 次。\n\n"
                "- id: dup-b\n  applies-to: x-tag\n  state: active\n  source: manual:tested\n"
                "  cited-by: []\n  注册表按名去重，先到先得；做法是注册前先查名字！跑了 `x`，1 次。\n")
    r = m(wsA, "memory", "lint", wsA)
    ok("近似重复" in r.stdout and "[WARN]" in r.stdout, "memory: 近似重复是 WARN", r.stdout)
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok("近似重复" in r.stdout and "[ERROR]" in r.stdout,
       "memory: --strict 下近似重复抬成 ERROR", r.stdout)
    ok(JOURNAL.memory_similarity("注册表按名去重先到先得", "注册表按名去重先到先得") == 1.0,
       "memory: 完全相同的正文相似度为 1")
    ok(JOURNAL.memory_similarity("注册表按名去重", "完全不同的一件事情") <
       JOURNAL.MEMORY_DUP_THRESHOLD, "memory: 不相干的正文在阈值以下")
    os.remove(vol3)
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok(r.returncode == 0, "memory: 清掉临时夹具后门禁回到干净", r.stdout + r.stderr)

    # --- 4) 收集：清单往返 + 幂等 + upload:false -----------------------------
    r = m(wsA, "memory", "collect", wsA)
    ok(r.returncode == 0 and "host-style-claiming" in r.stdout,
       "memory: collect 按清单收集", r.stdout + r.stderr)
    ok("memory index" in r.stdout,
       "memory: collect 提醒索引要重建（索引是生成物，collect 不代劳）", r.stdout)
    before = mem_snapshot(mem)
    # 隔一秒再收一次：`.state.json` 里的时间戳是秒级的，不隔开的话"没写"与
    # "写了但内容碰巧一样"就分不出来，而这条断言要的正是前者。
    time.sleep(1.05)
    r = m(wsA, "memory", "collect", wsA)
    after = mem_snapshot(mem)
    ok(r.returncode == 0 and "没有新东西" in r.stdout, "memory: 第二次 collect 说「没有新东西」",
       r.stdout)
    ok(before == after, "memory: collect 幂等 —— 再跑一次，整棵记忆树一个字节都没变",
       str(sorted(set(before) ^ set(after))) + str([k for k in before if before[k] != after.get(k)]))
    # 认的是**逐工作区那一行**（`- wsA（清单没变）`），不是末尾那句总结 ——
    # 总结里也有「清单没变」四个字，认错了这条断言就永远是绿的。
    ok("（清单没变）" in r.stdout, "memory: 幂等靠 .state.json 里的清单摘要", r.stdout)
    collect_entries = ments()
    ok(any(e["id"] == "host-style-claiming" and e["source"] == "wsA/wl/0001"
           for e in collect_entries),
       "memory: 收集来的条目 source 写成 `<工作区>/wl/NNNN`",
       str([(e["id"], e["source"]) for e in collect_entries]))
    ok(all(e["cited_by"] == ["wsA"] for e in collect_entries
           if e["id"] == "host-style-claiming"), "memory: cited-by 记下是哪个工作区")
    # upload: false 的工作区：一条都不收
    wsC = mem_ws(base, "wsC", "# 01 · T\n\n- **不该外流**：x。根因：y。做法：z。（`wl/0001`）\n")
    r = m(wsC, "memory", "publish", wsC, "--applies-to", "x-tag")
    ok(r.returncode == 0 and "false（只读不传）" in r.stdout,
       "memory: publish 默认 upload: false（只看不给，合法且常见）", r.stdout)
    r = m(wsC, "memory", "collect", wsC)
    ok(r.returncode == 0 and "upload: false" in r.stdout, "memory: upload:false 的工作区被跳过",
       r.stdout)
    ok(not any("不该外流" in JOURNAL.memory_body_line(e) for e in ments()),
       "memory: upload:false 时一条都没进记忆库")

    # --- 4b) 使用评价（`feedback:`）：镜像 / 幂等 / upload:false 不收 / 不被 search 命中 ----
    # 评价是"给改进用的"，不是知识：它**不进正文分册**，只镜像到 <记忆根>/feedback/。
    fb_src = os.path.join(wsA, "work_log", "评价-worklog.md")
    write(fb_src, "# 使用评价\n\n- 卡住的：collect 的幂等断言写得太紧。\n- 建议：镜像用覆盖式，历史交给 git。\n")
    write(mpath, read(mpath).replace("upload: true", "upload: true\nfeedback: 评价-worklog.md"))
    r = m(wsA, "memory", "collect", wsA)
    ok(r.returncode == 0 and "feedback/wsA.md" in r.stdout,
       "memory: collect 把 feedback: 声明的评价镜像进来", r.stdout + r.stderr)
    fb_dst = os.path.join(mem, "feedback", "wsA.md")
    ok(os.path.isfile(fb_dst), "memory: 镜像落在 <记忆根>/feedback/<工作区名>.md")
    ok("幂等断言写得太紧" in read(fb_dst), "memory: 评价正文逐字镜像", read(fb_dst))
    ok("这不是记忆条目" in read(fb_dst),
       "memory: 镜像文件自己声明「这不是记忆条目」（否则下一个人会以为它被检索）")
    ok(not any("幂等断言写得太紧" in JOURNAL.memory_body_line(e) for e in ments()),
       "memory: 评价**不进正文分册**（不是记忆条目）")
    # 评价没变 → 一个字节都不动（连"收集时间"那行也不许变）
    before_fb = mem_snapshot(mem)
    time.sleep(1.05)
    r = m(wsA, "memory", "collect", wsA)
    ok(before_fb == mem_snapshot(mem),
       "memory: 评价没变时 collect 不重写镜像（收集时间也不动）",
       str([k for k in before_fb if before_fb[k] != mem_snapshot(mem).get(k)]))
    # 只改评价源（清单不变）→ 也要收到：幂等判定必须把评价摘要算进去
    write(fb_src, read(fb_src) + "- 又一条：清单没变但评价改了，collect 得跟上。\n")
    r = m(wsA, "memory", "collect", wsA)
    ok(r.returncode == 0 and "清单没变但评价改了" in read(fb_dst),
       "memory: 清单没变、只改评价源时 collect 也会跟上", r.stdout + r.stderr)
    r = m(wsA, "memory", "search", "幂等断言写得太紧")
    ok(r.returncode == 0 and "0 条命中" in r.stdout,
       "memory: 评价里的内容**不被 memory search 命中**（它不是记忆条目）", r.stdout)
    # 声明了 feedback 但文件不在 → 报问题（与"坏引用"同规格）
    write(mpath, read(mpath).replace("feedback: 评价-worklog.md", "feedback: 不存在.md"))
    r = m(wsA, "memory", "collect", wsA)
    ok(r.returncode != 0 and "不存在" in r.stdout,
       "memory: 声明了 feedback 但文件不在 → collect 报问题", r.stdout)
    write(mpath, read(mpath).replace("feedback: 不存在.md", "feedback: 评价-worklog.md"))
    # upload:false 的工作区：评价也不收（同一个双向白名单）
    write(os.path.join(wsC, "work_log", "评价.md"), "不该外流的评价。\n")
    cpath = os.path.join(wsC, "work_log", "发布.md")
    # 只替换**第一处**：注释块里也有「upload: false」这串字，不限定次数会把它插进注释中间，
    # 清单随即解析失败（第一版就是这么挂的：collect 返回 1，后面依赖返回码的断言跟着红）。
    write(cpath, read(cpath).replace("upload: false", "upload: false\nfeedback: 评价.md", 1))
    r = m(wsC, "memory", "collect", wsC)
    ok(not os.path.isfile(os.path.join(mem, "feedback", "wsC.md")),
       "memory: upload:false 的工作区，评价也不收（双向白名单对评价同样生效）", r.stdout)

    # 登记了、但没有清单的工作区：只读不传（工具**无法自行发现工作区**，
    # 所以名册里没有它 = 它不参与；名册里有它但清单不在 = 它声明"不给"）
    wsR = mem_ws(base, "wsR", "# 01 · T\n\n- **没清单**：x。（`wl/0001`）\n")
    reg = JOURNAL.load_registry(mem)
    reg[os.path.abspath(wsR)] = {"applies-to": [], "read": True, "upload": False,
                                 "last-publish": "2026-09-20T00:00:00"}
    JOURNAL.save_registry(mem, reg)
    r = m(wsR, "memory", "collect", wsR)
    ok(r.returncode == 0 and "无清单" in r.stdout,
       "memory: 登记了但没清单 = 只读不传（缺清单是合法且常见的默认）", r.stdout)
    ok(not any("没清单" in JOURNAL.memory_body_line(e) for e in ments()),
       "memory: 没清单的工作区一条都没进记忆库")
    # 跨工作区同名 id：不同领域 = 冲突，拒绝
    wsD = mem_ws(base, "wsD", "# 01 · T\n\n- 另一件事。（`wl/0001`）\n")
    r = m(wsD, "memory", "publish", wsD, "--applies-to", "another-tag", "--upload")
    write(os.path.join(wsD, "work_log", "发布.md"),
          read(os.path.join(wsD, "work_log", "发布.md")).replace("id: wl-0001",
                                                                 "id: host-style-claiming"))
    r = m(wsD, "memory", "collect", wsD)
    ok(r.returncode != 0 and "全局唯一" in r.stdout,
       "memory: 两个工作区发布同名 id 被拒绝", r.stdout)
    # 同一领域里同名 id = 引用（cited-by 累计），不是冲突
    wsE = mem_ws(base, "wsE", "# 01 · T\n\n- 同一条教训。（`wl/0001`）\n")
    r = m(wsE, "memory", "publish", wsE, "--applies-to", "dsh-plugin", "--upload")
    write(os.path.join(wsE, "work_log", "发布.md"),
          read(os.path.join(wsE, "work_log", "发布.md")).replace("id: wl-0001",
                                                                 "id: host-style-claiming"))
    r = m(wsE, "memory", "collect", wsE)
    cited = [e for e in ments() if e["id"] == "host-style-claiming"]
    ok(r.returncode == 0 and cited and sorted(cited[0]["cited_by"]) == ["wsA", "wsE"],
       "memory: 同一领域的同名 id 是「被别的工作区引用」，累计进 cited-by",
       r.stdout + str([c["cited_by"] for c in cited]))

    # --- 5) 候选：只提示，不自动收录 ----------------------------------------
    # 候选 = **有清单但不是名册成员**。工具无法自行发现工作区，所以候选只来自
    # "有人把它指给我们看"（命令行给的那个 ROOT）。
    wsQ = mem_ws(base, "wsQ", "# 01 · T\n\n- **候选里的教训**：x。（`wl/0001`）\n")
    write(os.path.join(wsQ, "work_log", "发布.md"),
          "applies-to: q-tag\nupload: false\n\n- wl/0001  **候选里的教训**  →  id: from-candidate\n")
    ok(os.path.abspath(wsQ) not in JOURNAL.load_registry(mem),
       "memory: wsQ 有清单但还没登记")
    r = m(wsQ, "memory", "status", wsQ)
    ok("候选" in r.stdout, "memory: status 报候选与其它计数", r.stdout)
    cands = JOURNAL.load_candidates(mem)
    ok(os.path.abspath(wsQ) in cands,
       "memory: 有清单但没登记的工作区被记成候选（只提示）", str(cands))
    before = mem_snapshot(mem)
    r = m(wsQ, "memory", "collect", wsQ)
    after = mem_snapshot(mem)
    ok(not any(e["id"] == "from-candidate" for e in ments()),
       "memory: 候选的教训一条都没被收进来（候选只提示，绝不自动收录）")
    ok(r.returncode == 0, "memory: collect 在只有候选时也正常结束", r.stdout)
    ok("host-style-claiming" in read(mpath) and "wl/0002" in read(mpath),
       "memory: collect 绝不改写工作区的清单（那份文件是只读的）", read(mpath))
    r = m(wsQ, "memory", "publish", wsQ)
    ok(os.path.abspath(wsQ) not in JOURNAL.load_candidates(mem),
       "memory: publish 登记后候选里就不再有它", r.stdout)

    # --- 6) wl/NNNN 指向被删掉的记录：lint 要抓得到 ------------------------
    m(wsA, "memory", "index")
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok(r.returncode == 0, "memory: 收集并重建索引之后门禁干净", r.stdout + r.stderr)
    victim = os.path.join(wsA, "work_log", "0001-seed.md")
    os.replace(victim, victim + ".bak")
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok(r.returncode != 0 and "wl/0001" in r.stdout and "不存在" in r.stdout,
       "memory: wl/NNNN 指向被删掉的记录被抓住", r.stdout)
    os.replace(victim + ".bak", victim)
    r = m(wsA, "memory", "lint", wsA, "--strict")
    ok(r.returncode == 0, "memory: 记录恢复后门禁回到干净", r.stdout + r.stderr)

    # --- 6b) 来源工作区**被移除**：路径没了就当它没了（只提示，不拦）---------
    # 政策见 journal.py 的 `registry_state`：**登记过 + 路径不在 = gone（只提示）**；
    # **从没登记 = unknown（仍 ERROR）** —— 后者由上面的 wsGhost 用例覆盖。
    # 用户 2026-09-30 的原话："发现移除工作区（目标路径找不到）就当是没了，
    # 不对用户在 agent 以外的行为负责。"
    gone = mem_ws(base, "wsGone", "# 01 · gone\n\n- **走了就别管**：路径没了就当它没了。（`wl/0001`）\n")
    r = m(gone, "memory", "publish", gone, "--applies-to", "dsh-plugin", "--upload")
    ok(r.returncode == 0, "memory: wsGone 发布并登记进名册", r.stdout + r.stderr)
    r = m(wsB, "memory", "add", "来自一个后来被删掉的工作区。", "--source", "wsGone/wl/0001",
          "--id", "from-gone-ws")
    ok(r.returncode == 0, "memory: 登记过的工作区可以当来源（它还在）", r.stdout)
    m(wsB, "memory", "index")
    r = m(wsB, "memory", "lint", wsB, "--strict")
    ok(r.returncode == 0, "memory: 来源工作区还在时门禁干净", r.stdout + r.stderr)
    os.rename(gone, gone + "-moved")          # 工作区被移走：agent 管不着的那种事
    r = m(wsB, "memory", "lint", wsB, "--strict")
    ok(r.returncode == 0 and "已被移除" in r.stdout,
       "memory: 登记过的来源工作区没了 → 只提示，不拦（路径没了就当它没了）", r.stdout + r.stderr)

    # --- 6c) 退役条目只判结构：来源与内容要求都不再判（`0060` A 项）-----------
    # 规格 §三 说退役是"默认搜不到、**文件永不删**"。若内容要求照判，一条退役条目会因为
    # 来源工作区消失（正常生命周期）或正文本就不合格而**永久报错** —— 那条非破坏性出路
    # 就等于不存在，用户只剩删文件一条路。同一条**改成现役**后必须照旧报错：跳过是按
    # `state` 判的，不是"不判了"。
    retire_root = os.path.join(base, "memretire")
    os.makedirs(retire_root)
    vol_ret = os.path.join(retire_root, "01-t.md")
    bad = ("- id: t-one\n  applies-to: t\n  state: {state}\n"
           "  source: Ghost/wl/0001\n  cited-by: []\n  做过，没问题。\n\n")
    write(vol_ret, "# 01 · t\n\n" + bad.format(state="retired"))
    run(base, "memory", "index", "--memory", retire_root)
    r = run(base, "memory", "lint", base, "--strict", "--memory", retire_root)
    ok(r.returncode == 0,
       "memory: 退役条目只判结构 —— 坏来源与不合格正文都不再报错", r.stdout + r.stderr)
    write(vol_ret, "# 01 · t\n\n" + bad.format(state="active"))
    run(base, "memory", "index", "--memory", retire_root)
    r = run(base, "memory", "lint", base, "--strict", "--memory", retire_root)
    ok(r.returncode != 0 and "不在名册里" in r.stdout,
       "memory: 同一条改成现役后照旧报错（跳过是按 state 判的）", r.stdout)

    # --- 7) 硬上限：超限报错，绝不截断 --------------------------------------
    cap = os.path.join(base, "memcap")
    os.makedirs(cap)
    long_body = "症状很长很长的一段话，用来把索引撑过上限。" * 4
    volcap = os.path.join(cap, "01-cap.md")
    write(volcap, "# 01 · cap\n\n")
    for i in range(30):
        write(volcap, read(volcap) +
              f"- id: cap-{i:02d}\n  applies-to: cap-tag\n  state: active\n"
              f"  source: manual:tested\n  cited-by: []\n  {long_body}跑了 `x`，{i} 次。\n\n")
    r = run(base, "memory", "index", "--memory", cap)
    ok(r.returncode != 0 and "硬上限" in r.stdout,
       "memory: 索引超硬上限报错（超限报错，绝不静默截断）", r.stdout)
    # `getsize` 在文件不在时会抛（变异正是让索引没写出来）—— 包一层，让它变成一条红断言。
    # 注意 default 必须是数字：`safe` 兜底返回的是**字符串**说明，拿它去 `>` 又会抛 TypeError。
    idx_size = safe(lambda: os.path.getsize(os.path.join(cap, JOURNAL.MEMORY_INDEX_NAME)), -1)
    ok(isinstance(idx_size, int) and idx_size > 0,
       "memory: 而且索引照写完整 —— 报错不等于截断", str(idx_size))
    r = run(base, "memory", "lint", base, "--memory", cap)
    ok("硬上限" in r.stdout and r.returncode != 0, "memory: 硬上限在 lint 里是 ERROR", r.stdout)
    ok(JOURNAL.memory_index_size(cap) > JOURNAL.MEMORY_INDEX_HARD_CHARS,
       "memory: 这个夹具确实超过了硬上限", str(JOURNAL.memory_index_size(cap)))

    # --- 8) 检索：默认档位 / 标签 / personal --------------------------------
    r = m(wsA, "memory", "search", "缓存")
    ok(r.returncode == 0 and "cache-key-env" in r.stdout, "memory: search 按正文命中", r.stdout)
    r = m(wsA, "memory", "search", "host-style-claiming")
    ok("host-style-claiming" in r.stdout, "memory: search 按 id 命中", r.stdout)
    r = m(wsA, "memory", "search", "", "--tags", "dsh-plugin")
    ok("host-style-claiming" in r.stdout and "tested-ok" not in r.stdout,
       "memory: search --tags 按 applies-to 过滤", r.stdout)
    r = m(wsA, "memory", "add", "个人备忘：先记着。", "--source", "manual:tested",
          "--id", "personal-note", "--personal")
    ok(r.returncode == 0, "memory: --personal 写进 personal/", r.stdout)
    r = m(wsA, "memory", "search", "个人备忘")
    ok("personal-note" not in r.stdout, "memory: personal 默认不检索", r.stdout)
    r = m(wsA, "memory", "search", "个人备忘", "--include-personal")
    ok("personal-note" in r.stdout, "memory: --include-personal 才检索 personal", r.stdout)
    r = m(wsA, "memory", "index")
    ok("personal-note" not in read(JOURNAL.memory_index_path(mem)),
       "memory: personal 永不进索引")
    # retired 默认搜不到
    volr = os.path.join(mem, "01-dsh-plugin.md")
    keep = read(volr)
    write(volr, keep.replace("state: active", "state: retired", 1))
    r = m(wsA, "memory", "search", "样式")
    ok("host-style-claiming" not in r.stdout, "memory: retired 默认搜不到", r.stdout)
    r = m(wsA, "memory", "search", "样式", "--include-retired")
    ok("host-style-claiming" in r.stdout, "memory: --include-retired 能搜到", r.stdout)
    write(volr, keep)
    r = m(wsA, "memory", "index", "--check")
    ok(r.returncode == 0, "memory: 改回来之后索引仍与正文一致", r.stdout)

    # --- 9) status：计数 ----------------------------------------------------
    r = m(wsA, "memory", "status", wsA)
    ok(r.returncode == 0 and "MEMORY" in r.stdout, "memory: status 给出状态块", r.stdout)
    for needle in ("分册", "名册", "候选", "索引", "信箱", "personal"):
        ok(needle in r.stdout, f"memory: status 报了「{needle}」这一项", r.stdout)
    ok(wsA not in r.stdout,
       "memory: status 只列工作区名字、不铺满路径（名册隔离）", r.stdout)
    r = m(wsA, "memory", "status", wsA, "--verbose")
    ok(wsA in r.stdout, "memory: status --verbose 才把路径列出来", r.stdout)

    # --- 9b) promote：条件③看「跨天复发」，不看次数（`0034` 量出来的洞）---------
    #
    # 洞是这样：`hits` 记的是"检索命中过"，而**为了验证门禁去搜两次**就能把它凑到 2 ——
    # 一条刚写下的条目在同一分钟里两次检索就成了"够格"。同一份数据在 `memory search` 那边
    # 被注释成"弱且危险、绝不据此降级"，拿它当门槛是自相矛盾。现在门槛落在 `.state.json`
    # 记的 `days`（命中发生在哪些日子）上：同一天搜十次也只算一天。
    entry_proc = {"id": "proc-demo", "source": "manual:tested", "cited_by": [], "applies_to": [],
                  "state": "active", "personal": False, "title": "",
                  "body": ["当遇到 X 时，先做 A，再做 B，最后跑一次检查命令验证；"]}
    _, same_day_marks = JOURNAL.promote_conditions(
        entry_proc, {"proc-demo": {"hits": 9, "days": ["2026-09-29"]}})
    repeat_same_day = next(m for m in same_day_marks if m[0].startswith("有重复需求"))
    ok(not repeat_same_day[1],
       "memory: 同一天命中 9 次**不算**重复需求（次数能被验证动作凑出来）", repeat_same_day[2])
    _, two_day_marks = JOURNAL.promote_conditions(
        entry_proc, {"proc-demo": {"hits": 2, "days": ["2026-09-28", "2026-09-29"]}})
    repeat_two_day = next(m for m in two_day_marks if m[0].startswith("有重复需求"))
    ok(repeat_two_day[1], "memory: 跨 2 天命中才算重复需求", repeat_two_day[2])
    ok(JOURNAL.promote_conditions(entry_proc, {})[0] is False,
       "memory: 旧数据（没有 days）不因历史 hits 而算够格")

    # 命中时真的把「日子」记下来（且同一天只算一天）
    mem_days = os.path.join(base, "mem-days")
    os.makedirs(mem_days, exist_ok=True)
    JOURNAL.note_usage(mem_days, "proc-demo", hit=True)
    JOURNAL.note_usage(mem_days, "proc-demo", hit=True)
    days_now = JOURNAL.usage_hit_days(JOURNAL.load_state(mem_days)["usage"]["proc-demo"])
    ok(len(days_now) == 1, "memory: 同一天命中两次只记一个日子", str(days_now))
    # 用 `... if days_now else ""` 而不是直接取 `[0]`：变异把"记下日子"打掉之后 days_now 是空的，
    # 直接取下标会在**调用点**抛 IndexError，整相就此结束（2026-10-14 的变异整跑里，这条正是
    # 三条 CRASH 之一 —— 变异本来抓得住，却因为相崩了而报成"不构成证据"）。上面的断言已经
    # 报了红，这里只需要别把相带走。
    healthy_day = days_now[0] if days_now else ""
    state = JOURNAL.load_state(mem_days)
    state["usage"]["proc-demo"]["days"] = ["2026-09-01", healthy_day]
    JOURNAL.save_state(mem_days, state)
    ok(len(JOURNAL.usage_hit_days(state["usage"]["proc-demo"])) == 2,
       "memory: usage_hit_days 能读出跨天")

    # 命令行口径：够格判据的文案要写明「天命中」（次数不再是门槛）
    r = m(wsA, "promote", "suggest", "--all")
    ok("天命中" in r.stdout, "memory: 够格判据的文案写明「天命中」", r.stdout)
    ok("命中" in r.stdout, "memory: 并报出命中次数与跨天数", r.stdout)

    # --- 9c) promote scaffold：生成骨架，**先红后绿** -------------------------
    scaffold_out = os.path.join(base, "scaffold-out")
    r = m(wsA, "promote", "scaffold", "host-style-claiming", "--out", scaffold_out)
    ok(r.returncode == 0, "memory: promote scaffold 生成骨架", r.stdout + r.stderr)
    for rel in ("SKILL.md", "selftest.py", "verify-command.txt"):
        ok(os.path.isfile(os.path.join(scaffold_out, rel)), f"memory: 骨架里有 {rel}")
    ok(os.path.isdir(os.path.join(scaffold_out, "fixtures", "ok"))
       and os.path.isdir(os.path.join(scaffold_out, "fixtures", "bad")),
       "memory: 骨架里建好了两个夹具目录")
    ok("[骨架待改]" in read(os.path.join(scaffold_out, "SKILL.md")),
       "memory: description 留了显式待改标记，而不是自动编一句像成品的话")
    # 骨架默认**不进模型目录**：`disable-model-invocation: true` 是宿主真读的字段
    # （`dsh-tool-skill` 的 `isModelInvocable`），而技能的名字+描述曝光面最大，
    # 没写完的骨架不该进去。写完、验完再由作者删掉这一行。
    #
    # 断言只认 **frontmatter**：正文里也提到了这个字段名（在解释"为什么默认关着"），
    # 在整份文件里找子串会漏掉"frontmatter 那行被删掉"这种情况（实测漏过一次）。
    scaffold_md = read(os.path.join(scaffold_out, "SKILL.md"))
    front = scaffold_md.split("---")[1] if scaffold_md.startswith("---") else ""
    ok("disable-model-invocation: true" in front,
       "memory: 骨架默认关着（frontmatter 的 disable-model-invocation），避免半成品进模型目录",
       front.strip())

    # `--out` 必填、且不覆盖非空目录
    r = m(wsA, "promote", "scaffold", "host-style-claiming")
    ok(r.returncode != 0, "memory: scaffold 的 --out 是必填的", r.stdout + r.stderr)
    r = m(wsA, "promote", "scaffold", "host-style-claiming", "--out", scaffold_out)
    ok(r.returncode != 0 and "非空" in (r.stdout + r.stderr),
       "memory: scaffold 拒绝覆盖非空目录", r.stdout + r.stderr)

    # **生成即红**：缺命令 / 缺夹具时自测必须红，并说清缺什么
    # `under`：变异若让骨架没生成出来，`scaffold_out` 就不是目录，`subprocess.run(cwd=…)`
    # 会抛 NotADirectoryError、把整相带走（这条变异因此报成 CRASH）。路径不在就传空串，
    # subprocess 会自己报"没有这个可执行文件"，断言照红。
    r = subprocess.run([sys.executable, under(scaffold_out, "selftest.py")],
                       capture_output=True, cwd=under(scaffold_out, empty=None))
    red_out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    ok(r.returncode != 0 and "verify-command.txt" in red_out,
       "memory: 骨架生成出来就是红的，并指出缺哪样", red_out)

    # 作者补齐之后必须变绿（用一份最小样本走完整条路）
    write(os.path.join(scaffold_out, "check.py"),
          'import sys\n'
          'text = open(sys.argv[1], encoding="utf-8").read()\n'
          'sys.exit(1 if "BAD" in text else 0)\n')
    write(os.path.join(scaffold_out, "verify-command.txt"),
          "# 示例：{fixture} 会被替换成样本路径\npython check.py {fixture}\n")
    write(os.path.join(scaffold_out, "fixtures", "ok", "good.txt"), "干净\n")
    write(os.path.join(scaffold_out, "fixtures", "bad", "bad.txt"), "这里有 BAD\n")
    r = subprocess.run([sys.executable, os.path.join(scaffold_out, "selftest.py")],
                       capture_output=True, cwd=scaffold_out)
    green_out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    ok(r.returncode == 0 and "2/2 passed" in green_out,
       "memory: 补齐命令与夹具之后骨架变绿（先红后绿闭环）", green_out)

    # 名字不合法要拒（技能名与记忆 id 同一套形状）
    r = m(wsA, "promote", "scaffold", "host-style-claiming", "--out", scaffold_out + "-x",
          "--name", "Bad Name")
    ok(r.returncode != 0 and "不合法" in (r.stdout + r.stderr),
       "memory: scaffold 拒绝不合法的技能名", r.stdout + r.stderr)

    # --- 10) dream：回指校验是机械的 ----------------------------------------
    wsT = mem_ws(base, "wsT", "# 01 · T\n\n- x。（`wl/0001`）\n")
    r = jr(wsT, "dream")
    ok(r.returncode == 0 and "待收敛" in r.stdout, "dream: 默认模式发骨架", r.stdout + r.stderr)
    draft = os.path.join(wsT, "work_log", JOURNAL.MEMORY_DREAM_DRAFT)
    ok(os.path.isfile(draft), "dream: 骨架落在 <容器>/摘要.draft.md")
    ok(JOURNAL.MEMORY_DREAM_SLOT in read(draft), "dream: 骨架里每条断言都留了回指占位符")
    ok("| [0001-seed.md](0001-seed.md) |" in read(draft),
       "dream: 骨架列出这一组要读哪些记录（模型照着读）", read(draft))
    r = jr(wsT, "dream")
    ok(r.returncode == 0 and JOURNAL.MEMORY_DREAM_SLOT in read(draft),
       "dream: 还没填的骨架可以安全重发", r.stdout)
    r = jr(wsT, "dream", "--accept")
    ok(r.returncode != 0 and "占位符" in r.stdout,
       "dream: 没填的骨架被拒绝写回", r.stdout)
    ok(not os.path.isfile(os.path.join(wsT, "work_log", JOURNAL.MEMORY_DREAM_SUMMARY)),
       "dream: 拒绝时 摘要.md 不会出现")
    # 把骨架填对：一条断言 + 一个指向记录的链接
    text = read(draft).replace(f"- <在此写一句话断言>（回指：{JOURNAL.MEMORY_DREAM_SLOT}）",
                               "- 结论是 312 项测试全绿（证据：[0001-seed.md](0001-seed.md)）")
    write(draft, text)
    r = jr(wsT, "dream")
    ok(r.returncode != 0 and "已经填过" in r.stdout,
       "dream: 骨架看起来填过时不覆盖（避免把写好的总结冲掉）", r.stdout)
    r = jr(wsT, "dream", "--force")
    ok(r.returncode == 0 and JOURNAL.MEMORY_DREAM_SLOT in read(draft),
       "dream: --force 才重发骨架", r.stdout)
    write(draft, text)
    # 断言缺回指 → 红
    write(draft, text.replace("（证据：[0001-seed.md](0001-seed.md)）", "（我确定）"))
    r = jr(wsT, "dream", "--accept")
    ok(r.returncode != 0 and "没有回指" in r.stdout,
       "dream: 断言不带回指被拒绝（摘要必须能下钻一层）", r.stdout)
    write(draft, text)
    r = jr(wsT, "dream", "--accept")
    ok(r.returncode == 0, "dream: 回指全对时写回", r.stdout + r.stderr)
    summary = os.path.join(wsT, "work_log", JOURNAL.MEMORY_DREAM_SUMMARY)
    ok(os.path.isfile(summary), "dream: 成品是 <容器>/摘要.md")
    ok("覆盖范围" in read(summary), "dream: 成品带生成的覆盖范围（标记哪些记录已收敛）")
    r = jr(wsT, "dream", "--check")
    ok(r.returncode == 0, "dream --check 复查通过", r.stdout + r.stderr)
    r = jr(wsT, "dream")
    ok("没有待收敛" in r.stdout, "dream: 已收敛的记录不再重复挑出来（标记生效）", r.stdout)
    # 来源记录被删 → 回指校验变红（复用既有的死链检查器）
    victim = os.path.join(wsT, "work_log", "0001-seed.md")
    os.replace(victim, victim + ".bak")
    r = jr(wsT, "dream", "--check")
    ok(r.returncode != 0 and "死链" in r.stdout,
       "dream: 来源记录被删后 --check 变红（回指是机械校验的）", r.stdout)
    os.replace(victim + ".bak", victim)
    r = jr(wsT, "dream", "--check")
    ok(r.returncode == 0, "dream: 记录恢复后 --check 回到绿", r.stdout + r.stderr)

    # --- 11) inbox：原子写 / 头部 / 上限 / 转移为记录 -----------------------
    inbox = JOURNAL.memory_inbox_dir(mem)
    # 两行：用文本模式写盘会把 \n 翻成 \r\n，这条断言就是为那类 bug 准备的
    msg = "另一条会话留下的消息：样式表要加前缀。\n第二行。"
    r = m(base, "inbox", "put", msg)
    ok(r.returncode == 0 and "已投入信箱" in r.stdout, "inbox: put 投入一条", r.stdout)
    # 这条相会专门制造"inbox 目录不存在"的局面（变异让 inbox 写到别处去了），
    # 直接 `os.listdir(inbox)` 会抛 FileNotFoundError、把相带走（同族的坑见 `safe` / `under`）。
    # 目录不在就当"一个条目都没有"：下面的断言自然变红，而相继续跑。
    items = sorted(os.listdir(inbox)) if os.path.isdir(inbox) else []
    first_item = items[0] if items else ""      # 空列表时不再取下标（否则相会崩在调用点）
    ok(bool(items) and len(items) == 1 and first_item.endswith(".md"),
       "inbox: 落成一个 .md 条目", str(items))
    ok(not any(n.endswith(".tmp") for n in items),
       "inbox: 原子写之后不留临时文件（先写临时名再 rename）", str(items))
    ok(bool(first_item) and not first_item.startswith("."),
       "inbox: 也没有留下隐藏的临时名", first_item)
    # 条目名可能是空的（目录不在 / 没落成条目）—— 那就别去开文件，当成空内容：
    # 下面的断言照样会红，而相不会因为 `open(目录)` 抛异常而结束。
    raw = b""
    if first_item:
        with open(os.path.join(inbox, first_item), "rb") as fh:
            raw = fh.read()
    meta, body = JOURNAL.inbox_split(raw.decode("utf-8"))
    ok(meta.get("from") and meta.get("at") and meta.get("id") and "不可信输入" in meta.get("note", ""),
       "inbox: 落盘时写下 from / at / id /「不可信输入」那句（头部由工具渲染）", str(meta))
    ok(meta.get("from") == JOURNAL.memory_workspace_name(base),
       "inbox: from 取的是**命令运行所在目录**的名字（不提供能随便填的字段）", str(meta))
    ok(body == msg + "\n",
       "inbox: 正文与投进去的一模一样（二进制写，不翻译换行；头部之外不多不少）", repr(body))
    # --- 黄金夹具逐字节对账（审查报告 F14）------------------------------------
    # `tests/fixtures/inbox-item-from-cli.md` 是**另一份实现**（`lib/index.js` 的 `inboxSplit`）
    # 用来对账的样本，可是 python 侧从来不重放它：`inbox put` 的头部措辞改了，JS 那边照样绿
    # （它读的是那份**没变**的夹具），CLI 这边也没有任何断言碰过头部格式。这里补上两件事：
    #   1) 夹具能被 `inbox_header` + 解析出的正文**逐字节重放**（钉住渲染函数的形状）；
    #   2) 真跑一次 `inbox put`，归一 `at:` 那一行之后与夹具**逐字节相同**（钉住整条落盘路径，
    #      于是"夹具过期"从此会红，而不是继续假装两边一致）。
    fixture = harness_fixture("inbox-item-from-cli.md")
    if not fixture:
        note("inbox 黄金夹具逐字节对账", "树上没有 tests/fixtures（只装了 skills/ 的副本）")
    else:
        golden = read_bytes(fixture)
        gmeta, gbody = JOURNAL.inbox_split(golden.decode("utf-8"))
        replay = (JOURNAL.inbox_header(gmeta.get("from", ""), gmeta.get("at", ""),
                                       gmeta.get("id", ""), gmeta.get("thread"))
                  + gbody).encode("utf-8")
        ok(replay == golden,
           "inbox: 夹具能被 inbox_header 逐字节重放（头部措辞/那句 note 不许悄悄改）",
           f"replay={replay[:120]!r} golden={golden[:120]!r}")
        # `from:` 取命令运行所在目录的名字，所以在一个**就叫这个名**的目录里跑；
        # `at:` 是当下时钟，唯一允许归一的一行（归一它不削弱判据：其余每个字节都要对上）。
        # **另开一个记忆根**：投进这一相共用的 `mem` 会让后面的
        # `inbox count 的第一行就是一个整数` 从 1 变成 2 —— 夹具的副产品不许污染被测契约。
        golden_mem = os.path.join(base, "golden-mem")
        golden_inbox = JOURNAL.memory_inbox_dir(golden_mem)
        golden_dir = os.path.join(base, gmeta.get("from") or "wsA-cli-golden")
        os.makedirs(golden_dir, exist_ok=True)
        r = run(golden_dir, "inbox", "put", gbody.rstrip("\n"), "--memory", golden_mem)
        ok(r.returncode == 0, "inbox: 黄金样本能被 CLI 重新投出", r.stdout + r.stderr)
        fresh = sorted(os.listdir(golden_inbox)) if os.path.isdir(golden_inbox) else []
        produced = read_bytes(os.path.join(golden_inbox, fresh[0])) if len(fresh) == 1 else b""
        produced = re.sub(rb"^at: .*$",
                          b"at: " + (gmeta.get("at") or "").encode("utf-8"),
                          produced, count=1, flags=re.M)
        ok(produced == golden,
           "inbox: 真跑一次 inbox put，除 at: 外与黄金夹具逐字节相同（夹具不会悄悄过期）",
           f"produced={produced[:160]!r} golden={golden[:160]!r}")
    # --- id / thread：2026-10-17 定的两个字段 -----------------------------------
    # 用**独立记忆根**：投进上面的 `mem` 会把 `inbox count 的第一行就是一个整数` 从 1 变成 3。
    field_mem = os.path.join(base, "field-mem")
    field_inbox = JOURNAL.memory_inbox_dir(field_mem)
    same = "去重键的正文"
    r1 = run(base, "inbox", "put", same, "--memory", field_mem)
    r2 = run(base, "inbox", "put", same, "--memory", field_mem)
    ok(r1.returncode == 0 and r2.returncode == 0, "inbox: 同一条正文可以重投", r1.stdout + r2.stdout)
    fmetas = []
    # 目录可能整个不在（变异"`--memory` 不再覆盖路径"会让信写到别的根）：当"一个条目都没有"，
    # 下面的断言自然变红，而相不会带着 FileNotFoundError 结束（同族的坑见 3680 那段注释）。
    field_names = sorted(os.listdir(field_inbox)) if os.path.isdir(field_inbox) else []
    for name in field_names:
        fmetas.append(JOURNAL.inbox_split(
            read_bytes(os.path.join(field_inbox, name)).decode("utf-8"))[0])
    # 空列表时也别取下标：变异"`--memory` 不再覆盖路径"会让这个目录不存在、fmetas 为空，
    # `fmetas[0]` 就是 IndexError —— 那会**带走整相**（C>0），而不是让断言变红
    # （2026-10-17 全量跑就在这里崩过）。
    f0 = fmetas[0] if fmetas else {}
    f1 = fmetas[1] if len(fmetas) > 1 else {}
    ok(len(fmetas) == 2 and f0.get("id") and f0.get("id") == f1.get("id"),
       "inbox: id 是正文的稳定摘要 —— 同一条重投得到同一个 id（去重 / 幂等）", str(fmetas))
    ok(JOURNAL.inbox_message_id(same + "\n") == f0.get("id"),
       "inbox: id 就是正文的 sha256 前 16 位（换一条正文就换一个 id）", str(fmetas))
    ok(not f0.get("thread") and not f1.get("thread"),
       "inbox: 不给 --thread 就不写这个字段（不塞空字段）", str(fmetas))
    # 用 `.get()` 而不是 `["id"]`：变异"文本模式直接写"会把这封信用 CRLF 落盘，
    # `inbox_split` 于是解析不出头部（meta 为空），取下标就是 KeyError —— 同样是相崩。
    reply = run(base, "inbox", "put", "这是一封回信", "--thread", f0.get("id") or "",
                "--memory", field_mem)
    ok(reply.returncode == 0, "inbox: --thread 可以指向一条消息 id", reply.stdout + reply.stderr)
    r = run(base, "inbox", "list", "--memory", field_mem)
    ok(f"thread={f0.get('id')}" in r.stdout,
       "inbox: list 里能看到 thread（来回可对）", r.stdout)
    bad_thread = run(base, "inbox", "put", "x", "--thread", "not-a-hex-id", "--memory", field_mem)
    ok(bad_thread.returncode == 1 and "十六进制" in bad_thread.stdout,
       "inbox: 不是消息 id 的 --thread 被拒绝（不是静默忽略）", bad_thread.stdout)
    # `--text` 与位置参数等价，且**不许**和 `--file` 一起给（递文件就把整份文件当正文）。
    via_flag = run(base, "inbox", "put", "--text", "用选项传的正文", "--memory", field_mem)
    ok(via_flag.returncode == 0, "inbox: --text 可以替代位置参数", via_flag.stdout + via_flag.stderr)
    whole = os.path.join(base, "payload.txt")
    write(whole, "整份文件的内容\n第二行\n")
    via_file = run(base, "inbox", "put", "--file", whole, "--memory", field_mem)
    ok(via_file.returncode == 0, "inbox: --file 把整份文件当正文投进去", via_file.stdout + via_file.stderr)
    both = run(base, "inbox", "put", "x", "--file", whole, "--memory", field_mem)
    ok(both.returncode == 1 and "只能给一个" in both.stdout,
       "inbox: 文本与 --file 同时给会被拒绝（别猜作者想投哪个）", both.stdout)
    # `--outbox DIR`：同工作区直投 —— 写进给定目录，**不进共享信箱**（也不受信箱总量上限约束）。
    outbox = os.path.join(base, "direct-outbox")
    before_shared = len(JOURNAL._inbox_items(field_mem))
    r = run(base, "inbox", "put", "直投正文", "--outbox", outbox, "--memory", field_mem)
    ok(r.returncode == 0 and "已写入工作区收件夹" in r.stdout,
       "inbox: --outbox 写进给定目录（不是共享信箱）", r.stdout + r.stderr)
    direct_files = [n for n in os.listdir(outbox) if n.endswith(".md")] if os.path.isdir(outbox) else []
    ok(len(direct_files) == 1,
       "inbox: --outbox 目录里落了一封信", str(direct_files))
    ok(len(JOURNAL._inbox_items(field_mem)) == before_shared,
       "inbox: --outbox 不往共享信箱里写一条", str(before_shared))
    ok(JOURNAL.inbox_split(read(os.path.join(outbox, direct_files[0])))[1].strip() == "直投正文",
       "inbox: --outbox 的信仍是同一份头部 + 正文")
    # --- 直投信的来源（2026-10-18 用户提出）：from-session + 直投专用 note ---------
    source_meta = None
    r = run(base, "inbox", "put", "带来源的直投", "--outbox", outbox,
            "--from-session", "session-abc123", "--memory", field_mem)
    ok(r.returncode == 0, "inbox: --from-session 被接受", r.stdout + r.stderr)
    for name in sorted(n for n in os.listdir(outbox) if n.endswith(".md")):
        meta, letter_body = JOURNAL.inbox_split(read(os.path.join(outbox, name)))
        if letter_body.strip() == "带来源的直投":
            source_meta = meta
    ok(source_meta is not None and source_meta.get("from-session") == "session-abc123",
       "inbox: 直投信头写了发件会话（归档后仍能追溯来源）", str(source_meta))
    ok(source_meta is not None and "同工作区" in source_meta.get("note", ""),
       "inbox: 直投信的 note 不再谎称『另一个工作区』", str(source_meta))
    bad_from = run(base, "inbox", "put", "x", "--outbox", outbox,
                   "--from-session", "not a session id", "--memory", field_mem)
    ok(bad_from.returncode == 1 and "from-session" in bad_from.stdout,
       "inbox: 不像会话 id 的 --from-session 被拒绝", bad_from.stdout)
    # --- 主动送达的授权（2026-10-17）：默认关，开/关都要落盘，status 能读回来 ----
    sub_mem = os.path.join(base, "sub-mem")
    sub_path = os.path.join(sub_mem, JOURNAL.MEMORY_SUBSCRIPTIONS_NAME)
    r = run(base, "inbox", "status", "--root", base, "--memory", sub_mem)
    ok("关（未授权）" in r.stdout, "inbox: 主动送达默认关（未授权）", r.stdout)
    r = run(base, "inbox", "subscribe", "--root", base, "--memory", sub_mem)
    ok(r.returncode == 0 and os.path.isfile(sub_path),
       "inbox: subscribe 落下授权表（不是只打印一句话）", r.stdout + r.stderr)

    # 授权表可能压根没落盘（变异"`--memory` 不再覆盖路径"会让 subscribe 写到别处，
    # `read_bytes` 拿到的是哨兵文本）—— 解析失败就当空表，让断言自然变红，别让相崩掉。
    def _read_subs(path: str) -> dict:
        try:
            return json.loads(read_bytes(path).decode("utf-8"))
        except (OSError, ValueError):
            return {}

    subs = _read_subs(sub_path)
    ws = subs.get("workspaces", {})
    entry = ws.get(JOURNAL.subscriptions_key(base), {})
    ok(bool(entry) and entry.get("active") is True and str(entry.get("session", "")).startswith("session-"),
       "inbox: 授权按规范化工作区路径记，收件会话有固定 id（有就 resume、没有才 create）",
       str(subs))
    r = run(base, "inbox", "status", "--root", base, "--memory", sub_mem)
    ok("主动送达：开" in r.stdout and entry.get("session", "") in r.stdout,
       "inbox: status 读回授权与收件会话", r.stdout)
    r = run(base, "inbox", "unsubscribe", "--root", base, "--memory", sub_mem)
    ok(r.returncode == 0 and "已撤销" in r.stdout, "inbox: unsubscribe 撤销授权", r.stdout)
    subs = _read_subs(sub_path)
    ok(subs.get("workspaces", {}).get(JOURNAL.subscriptions_key(base), {}).get("active") is False,
       "inbox: 撤销是落盘的（active: false），不是把记录删掉", str(subs))
    # 授权表与记忆根平级、**不进**记忆条目（`memory_volumes` 只认 `NN-*.md` 目录）。
    ok(JOURNAL.load_memory_entries(sub_mem) == [],
       "inbox: 授权表不是记忆条目（不索引、不参与 lint）")
    r = m(base, "inbox", "list")
    ok(f"from={meta.get('from')}" in r.stdout and "样式表要加前缀" in r.stdout,
       "inbox: list 显示发件方与原消息首行", r.stdout)
    r = m(base, "inbox", "list", "--json")
    ok('"from"' in r.stdout, "inbox: list --json 里也有 from", r.stdout)
    r = m(base, "inbox", "take", first_item, "--keep")
    ok("不可信输入" in r.stdout and f"from: {meta.get('from')}" in r.stdout,
       "inbox: take 把发件方与那句「不可信输入」渲染出来（不靠作者自觉）", r.stdout)
    r = m(base, "inbox", "count")
    ok(r.stdout.strip() == "1",
       "inbox: count 的第一行就是一个整数（插件调用它的契约）", repr(r.stdout))
    ok(len(r.stdout.strip().splitlines()) == 1,
       "inbox: count 不打印别的字（多一行调用方就要开始猜）", repr(r.stdout))
    # 读者侧：半截的临时文件必须被忽略 —— 这才是原子写保护到的那一半
    tmpfile = os.path.join(inbox, ".half-written.123.tmp")
    write(tmpfile, "半截")
    ok(JOURNAL._inbox_items(mem) and len(JOURNAL._inbox_items(mem)) == 1,
       "inbox: 读到 .tmp 半截文件时当它不存在（清单不把它算一条）")
    os.remove(tmpfile)
    # 符号链接同样要被挡掉：`os.path.isfile` **会跟随链接**，于是信箱目录里一个
    # `note.md -> 别处某个文件` 就能让 `inbox list` / 取件 / `--into-record` 读到链接目标
    # （审查报告：安全面唯一一处偏软，低危，修法一行 `os.path.islink`）。
    # 建链接需要权限（Windows 上要开发者模式），建不出来就记 SKIP —— 不假装验过。
    link = os.path.join(inbox, "linked-note.md")
    outside = os.path.join(base, "outside-the-inbox.md")
    write(outside, "信箱外的内容，不该被读出来\n")
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError, AttributeError) as exc:
        note("inbox 不跟随符号链接", f"这台机器建不了符号链接（{type(exc).__name__}）")
    else:
        try:
            listed = [i["name"] for i in JOURNAL._inbox_items(mem)]
            ok("linked-note.md" not in listed,
               "inbox: 符号链接不算条目（`isfile` 会跟随链接，必须单独挡）", str(listed))
            r = m(base, "inbox", "list")
            ok("信箱外的内容" not in r.stdout, "inbox: list 读不到链接目标的内容", r.stdout)
        finally:
            os.remove(link)
    r = m(base, "inbox", "list")
    ok(r.returncode == 0 and "样式表要加前缀" in r.stdout, "inbox: list 列出条目", r.stdout)
    r = m(base, "inbox", "list", "--json")
    ok(r.returncode == 0 and '"name"' in r.stdout, "inbox: list --json 给机器读", r.stdout)
    # 上限：单条 / 条数 / 总量。单条这一条用**文件**投 —— 64 KiB 的正文塞不进 Windows
    # 的命令行（`CreateProcess` 有长度上限，实测 `[WinError 206] 文件名或扩展名太长`），
    # 用 `--file` 才测得到"上限"本身，而不是"命令行长度"。
    oversized = os.path.join(base, "oversized.txt")
    write(oversized, "x" * (JOURNAL.MEMORY_INBOX_ITEM_MAX_BYTES + 1))
    r = m(base, "inbox", "put", "--file", oversized)
    ok(r.returncode != 0 and "单条" in r.stdout,
       "inbox: 单条超上限被拒绝（写满报错，不静默堆积）", r.stdout[:120])
    r = m(base, "inbox", "put", "")
    ok(r.returncode != 0, "inbox: 空消息被拒绝", r.stdout)
    full = os.path.join(base, "memfull")
    os.makedirs(os.path.join(full, JOURNAL.MEMORY_INBOX_DIR))
    for i in range(JOURNAL.MEMORY_INBOX_MAX_ITEMS):
        write(os.path.join(full, JOURNAL.MEMORY_INBOX_DIR, f"fill-{i:04d}.md"), "x")
    r = run(base, "inbox", "put", "再多一条", "--memory", full)
    ok(r.returncode != 0 and "已满" in r.stdout,
       "inbox: 条数到顶后写满拒绝", r.stdout)
    r = run(base, "inbox", "count", "--memory", full)
    ok(r.stdout.strip() == str(JOURNAL.MEMORY_INBOX_MAX_ITEMS),
       "inbox: 到顶时一条都没多写", r.stdout)
    # 转移为记录（`first_item`：目录不在时它是空串，于是下面的断言红，而相不崩）
    name = first_item
    r = m(wsA, "inbox", "take", name, "--into-record", "信箱转来的样式问题", wsA)
    ok(r.returncode == 0 and "created" in r.stdout, "inbox: take --into-record 建一篇记录", r.stdout)
    rec2 = os.path.join(wsA, "work_log", "0003-信箱转来的样式问题.md")
    ok(not os.path.exists(rec2), "inbox: 纯中文标题退化成 <篇号>.md（与 new 一致）")
    rec2 = os.path.join(wsA, "work_log", "0003.md")
    ok(os.path.isfile(rec2), "inbox: 记录真的建出来了", os.listdir(os.path.join(wsA, "work_log")))
    rtxt = read(rec2)
    ok("# 0003 · 信箱转来的样式问题" in rtxt, "inbox: 记录 H1 用的是 --into-record 的标题")
    ok("样式表要加前缀" in rtxt, "inbox: 信箱原文被搬进记录（原样，不重新表述）")
    # 发件方是**投递时**记下的（put 跑在 base 里），取件方在 wsA —— 两者不是一回事
    ok("（来自信箱 `" + name + "`，发件方 `" + JOURNAL.memory_workspace_name(base) + "`）" in rtxt,
       "inbox: 记录里标明它来自信箱哪一条、谁发的", rtxt[:200])
    ok("不可信输入" not in rtxt and rtxt.lstrip().startswith("# 0003"),
       "inbox: 搬进记录的是**正文** —— 头部与那句提醒不跟着进（那是渲染出来的，不是内容）",
       rtxt[:80])
    ok(all(i["name"] != name for i in JOURNAL._inbox_items(mem)),
       "inbox: 转移之后原件被删掉（阅后即删 / 转移）", str(JOURNAL._inbox_items(mem)))
    # take --keep 不删（同样不取空列表的下标：信箱可能一条都没落成）
    m(base, "inbox", "put", "留着看的一条。")
    _kept = [i["name"] for i in JOURNAL._inbox_items(mem)]
    keepname = _kept[0] if _kept else ""
    r = m(base, "inbox", "take", keepname, "--keep")
    ok(r.returncode == 0 and any(i["name"] == keepname for i in JOURNAL._inbox_items(mem)),
       "inbox: take --keep 只打印不删", r.stdout)
    # sweep 默认只报告
    r = m(base, "inbox", "sweep", "--older-than", "0")
    ok(r.returncode == 0 and "只报告" in r.stdout and JOURNAL._inbox_items(mem),
       "inbox: sweep 默认只报告（先让人看一眼）", r.stdout)
    r = m(base, "inbox", "sweep", "--older-than", "0", "--apply")
    ok(r.returncode == 0 and JOURNAL._inbox_items(mem) == [],
       "inbox: sweep --apply 才真删", r.stdout)
    r = m(base, "inbox", "take", "不存在的东西")
    ok(r.returncode != 0, "inbox: take 找不到条目时报错", r.stdout)

    # --- 11b) 并发窗口：列目录之后、读/删之前，条目被别的进程取走 ------------- #
    #
    # `inbox list` / `take` / `sweep` 都是"先列目录、再逐条读或删"，两件事之间没有原子性：
    # 并发的 `inbox take` 正好能在这个窗口里把条目删掉。2026-10-15 的全量一轮里，上面那组
    # 六路并发 `take --into-record` 就报过 `rc=[0, 0, 0, 2, 0, 0]` + `缺=[4]`；单独复现
    # （四路并行、240 轮）抓到 3 次，收场都是
    # `ERROR: 写不进去：[WinError 2] 系统找不到指定的文件。: '…payload-5.md'`
    # —— 出错的进程连自己那条都没取到（`os.remove` 失败被 `main` 的 OSError 兜成"写不进去"）。
    #
    # 窗口只有几十微秒，靠撞是测不出来的（240 轮里 3 次）。所以这里**故意把窗口拉开**：
    # 临时替换一个函数，让"另一个进程在这一刻把它取走"确定发生。五条判据跑的都是真代码，
    # 只是时间点被钉住了。
    def steal(path: str) -> bool:
        """把条目从信箱里删掉（模拟并发的取件）；返回它此前在不在。"""
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False

    def out_of(argv: list[str]) -> tuple[int, str]:
        """在**进程内**跑一遍 `main()`、收下它的 stdout（子进程里替换不了函数）。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = JOURNAL.main(argv)
        return rc, buf.getvalue()

    race = os.path.join(base, "memrace")
    race_inbox = JOURNAL.memory_inbox_dir(race)
    ghost = os.path.join(race_inbox, "20260101-000000-1-已经被取走.md")
    os.makedirs(race_inbox, exist_ok=True)

    def seed(stamp: str, text: str) -> str:
        """直接写文件布一条信箱条目，返回文件名。

        **不走 CLI**：这几条判据问的是"列目录之后它没了会怎样"，与"记忆根怎么解析"无关 ——
        用 `--memory` 布夹具的话，别的变异（例如「`--memory` 不再覆盖路径」）会把这一段直接
        带崩（`os.listdir` 一个不存在的目录），而不是让它红一条。
        """
        name = f"{stamp}-seed.md"
        write(os.path.join(race_inbox, name), text + "\n")
        return name

    def with_ghost(fn):
        """在 `_inbox_items()` 的结果后面塞一条**文件已经不在**的条目，再跑 `fn()`。

        那条条目的状态正是"另一个进程在列目录之后把它取走"留在盘上的样子（名字在列表里、
        文件没了）。这里只是把窗口从几十微秒拉成确定，没有伪造任何"不可能出现的状态"。
        """
        real = JOURNAL._inbox_items

        def patched(memory: str) -> list[dict]:
            return real(memory) + [{"name": os.path.basename(ghost), "path": ghost,
                                    "size": 12, "mtime": 0.0}]
        JOURNAL._inbox_items = patched
        try:
            return fn()
        finally:
            JOURNAL._inbox_items = real

    # ① 列目录与**读属性**之间被取走：`size` 那边一直有 `_file_size` 兜着"读不出来算 0"，
    #    紧挨着的 `mtime` 没有 —— 这是那次复现里真正抛出来的那一条。
    victim = seed("20260101-000000-1", "窗口①的那一条。")
    real_mtime = os.path.getmtime

    def vanish(path, *a, **kw):
        if os.path.basename(path) == victim:
            steal(path)
        return real_mtime(path, *a, **kw)

    os.path.getmtime = vanish
    try:
        names, boom = [i["name"] for i in JOURNAL._inbox_items(race)], None
    except FileNotFoundError as exc:
        names, boom = [], exc
    finally:
        os.path.getmtime = real_mtime
    ok(boom is None and victim not in names,
       "inbox: 列目录之后被取走的那条不算出错，只是不在列表里（读属性那个窗口）",
       f"err={boom!r} names={names}")

    # ② 列表：条目列出来了，读正文那一步它没了 —— 跳过去，别把整条 `list` 带走
    seed("20260102-000000-1", "窗口②留下来的那一条。")
    rc, out = with_ghost(lambda: out_of(["inbox", "list", "--memory", race]))
    ok(rc == 0 and "窗口②留下来的那一条" in out and "已经被取走" not in out,
       "inbox: list 撞上刚被取走的条目时跳过去，别的照列（不是把 [WinError 2] 抛上去）", out)

    # ③ 取件：名字匹配上了、读之前被取走 —— 说清是"被取走了"，不是"写不进去"
    seed("20260103-000000-1", "窗口③留下来的那一条。")
    rc, out = with_ghost(lambda: out_of(
        ["inbox", "take", os.path.basename(ghost), "--memory", race]))
    ok(rc == 1 and "刚被别的进程取走了" in out and "写不进去" not in out,
       "inbox: take 撞上刚被取走的那条时说「被取走了」并以 1 退出（不是 [WinError 2]）", out)

    # ④ 取件的**收尾**：正文读了、记录也建好了，删之前那条没了
    racews = os.path.join(base, "race-ws")
    os.makedirs(os.path.join(racews, "work_log"))
    write(os.path.join(racews, "work_log", "README.md"), INDEX)
    victim4 = seed("20260104-000000-1", "窗口④要被取走的那一条。")
    real_gone = JOURNAL._inbox_read_or_none

    def read_then_steal(path: str):
        got = real_gone(path)                 # 正常读（内容拿得到）
        if os.path.basename(path) == victim4:
            steal(path)                       # 读完那一瞬，另一个进程把它取走了
        return got

    JOURNAL._inbox_read_or_none = read_then_steal
    try:
        rc, out = out_of(["inbox", "take", victim4, "--into-record", "窗口④的记录",
                          "--memory", race, "--root", racews])
    finally:
        JOURNAL._inbox_read_or_none = real_gone
    ok(rc == 0 and "created" in out and "已经不在信箱里了" in out,
       "inbox: take 的收尾撞上「已经被别人取走」时说一句就完（记录已建，不算失败）", out)

    # ⑤ sweep：报告与删除两步都容得下"已经被取走"
    seed("20260105-000000-1", "窗口⑤留下来的那一条。")
    rc, out = with_ghost(lambda: out_of(
        ["inbox", "sweep", "--older-than", "0", "--apply", "--memory", race]))
    ok(rc == 0 and "（已不在信箱里）" in out and "已被别的进程取走，跳过" in out,
       "inbox: sweep 报告与删除两步都容得下「已经被取走」（不是把 [WinError 2] 抛上去）", out)

    # --- 12) promote：三条件同时满足才报候选 --------------------------------
    pm = os.path.join(base, "mempromote")
    os.makedirs(pm)
    write(os.path.join(pm, "01-proc.md"), "# 01 · proc\n\n"
          "- id: all-three\n  applies-to: x-tag\n  state: active\n  source: manual:tested\n"
          "  cited-by: [wsA, wsB]\n"
          "  遇到样式冲突时先查名字。步骤：先查注册表，再注册，最后验证一遍。"
          "  验证方式：跑 `pytest -q`，3 passed。\n\n"
          "- id: no-procedure\n  applies-to: x-tag\n  state: active\n  source: manual:tested\n"
          "  cited-by: [wsA, wsB]\n  注册表按名去重。跑了 `x`，1 次。\n\n"
          "- id: not-executed\n  applies-to: x-tag\n  state: active\n  source: manual:read\n"
          "  cited-by: [wsA, wsB]\n"
          "  遇到冲突先查名字。步骤：先查，再注册。验证：跑 `x`。\n\n"
          "- id: not-needed\n  applies-to: x-tag\n  state: active\n  source: manual:tested\n"
          "  cited-by: []\n"
          "  遇到冲突先查名字。步骤：先查，再注册。验证：跑 `pytest -q`，1 passed。\n")
    r = run(pm, "promote", "suggest", "--memory", pm)
    ok(r.returncode == 0 and "all-three" in r.stdout and "1 条够格" in r.stdout,
       "promote: 三条件全满足的才被列出来", r.stdout)
    for bad in ("no-procedure", "not-executed", "not-needed"):
        ok(bad not in r.stdout, f"promote: 少一条就不列 `{bad}`", r.stdout)
    r = run(pm, "promote", "suggest", "--memory", pm, "--all")
    ok("not-executed" in r.stdout and "已真实执行过" in r.stdout,
       "promote: --all 连未够格的一起列，并写明缺哪一条", r.stdout)
    good, marks = JOURNAL.promote_conditions(
        {"id": "x", "source": "manual:tested", "cited_by": ["a", "b"], "body": ["验证：跑 `x`"]},
        {})
    ok(good is False and len(marks) == 5,
       "promote: 三条判据（触发 / 步骤 / 验证 / 已执行 / 重复需求）缺一不可",
       str([m[0] for m in marks]))
    ok("只报候选" in r.stdout, "promote: 明说只报候选、不自动打包", r.stdout)


def numbering_phase(parent: str) -> None:
    """写盘原义性、两条占号路径、`new --dry-run` 的预报（F6/F7、第三轮 N-A/N-B）。

    **为什么单独一个相**：这些断言原来内联在 `main()` 里，而
    `publish/worklog/tests/reverse-verify.py` 只按 `PHASES` 里登记的函数跑相 ——
    内联断言它根本跑不到。第三轮新加的三条变异因此只能报
    "MISS：期望的标签没变红；红了 0 条"，测了等于没测。
    搬出来登记进 `PHASES`，变异才算真的被覆盖。
    """


    # ---- 写盘的原子性（审查报告 F6/F7）-------------------------------- #
    #
    # 这两条护的是容器最核心的那句承诺："文件永不删、只会丢"。`write_raw()` 原来是
    # `open(path, "w")`——先截断再写，中途失败就留下一份**残缺的记录**；`cmd_new`
    # 原来是"先问再写"，两个进程同时建记录会**静默覆盖**。两条各用一个便宜的手法钉住：
    # 前者看"临时文件收不收得干净 + 内容换不换得掉"，后者看"同时起 6 个进程会不会少一份"。
    fx = os.path.join(parent, "_f67")
    os.makedirs(fx)
    target = os.path.join(fx, "note.md")
    write(target, "old\n")
    JOURNAL.write_raw(target, "new\n")
    leftovers = [f for f in os.listdir(fx) if f != "note.md"]
    ok(read(target) == "new\n" and leftovers == [],
       "write_raw: 换掉内容且不留临时文件", f"leftovers={leftovers}")

    # 真正的判据是"占名与写入之间没有窗口"，而窗口只在并发下才看得见：
    # 6 个进程同时 `new`（`--title` 各不相同，便于分辨谁是谁）。
    con = os.path.join(fx, "con")
    os.makedirs(os.path.join(con, CONTAINER))
    write(os.path.join(con, CONTAINER, "README.md"), INDEX)
    procs = [subprocess.Popen(
        [sys.executable, TOOL, "new", "--root", con, "--title", f"race {i}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=HERE)
        for i in range(6)]
    outs = []
    for p in procs:
        try:
            o, e = p.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            p.kill()
            o, e = p.communicate()
        outs.append((p.returncode, decode_output(o), decode_output(e)))
    made = sorted(f for f in os.listdir(os.path.join(con, CONTAINER))
                  if f != "README.md")
    ok(all(rc == 0 for rc, _, _ in outs) and len(made) == 6,
       "6 个进程同时 new：一人一份，没有静默覆盖",
       f"rc={[rc for rc, _, _ in outs]} files={made}")
    bodies = [read(os.path.join(con, CONTAINER, f)) for f in made]
    ok(all(f"race {i}" in "\n".join(bodies) for i in range(6)),
       "6 个进程同时 new：每份正文都在，没有谁被谁吃掉",
       f"{[b.splitlines()[3] if len(b.splitlines()) > 3 else '?' for b in bodies]}")
    # 条数对**不等于**号不重：六份文件全叫 `0001-race-i.md` 时上面两条照样全绿，
    # 而"编号永不复用"正是容器承诺过的那条不变量（审查报告 §附录 N2 就是这么漏的）。
    # 判据是**号两两不同**，不是"恰好 1..6"：顺序密集是正常时序的巧合，不是不变量
    # （第三轮复查 N-A 指出这条断言写窄了，真撞号时它反而看不出区别）。
    nums = sorted(JOURNAL.name_number(f) for f in made)
    ok(len(set(nums)) == 6,
       "6 个进程同时 new：篇号互不相同（判据是「号不重」，不是「文件数对」）", str(nums))

    # ---- `inbox take --into-record` 是**另一条**占号路径（2026-10-15 修）------------ #
    #
    # 它原来自己算号 + `os.path.exists` + `write_raw`：6 个进程同时 take、且目标标题相同
    # 时，六份都算到同一个文件名 —— `write_raw` 用的是 `os.replace`，后写者**静默覆盖**
    # 先写者，而且每个进程都把自己取走的那条信箱消息删掉了（那条消息就此永久消失）。
    # 判据与上面 `new` 那条同源，但刻意用**同一个标题**：不同标题只会撞号（号重的记录
    # 还都在），相同标题才会撞名 —— 撞名才是覆盖，也才是"只会丢"里最坏的那一种。
    take_con = os.path.join(fx, "take")
    take_mem = os.path.join(fx, "take-mem")
    os.makedirs(os.path.join(take_con, CONTAINER))
    write(os.path.join(take_con, CONTAINER, "README.md"), INDEX)
    for i in range(6):
        r = run(take_con, "inbox", "put", f"payload {i}", "--memory", take_mem)
        ok(r.returncode == 0, f"concurrency fixture: inbox put {i}", r.stdout + r.stderr)
    take_inbox = JOURNAL.memory_inbox_dir(take_mem)
    # 同上：`--memory` 被变异弄失效时这个目录根本不会建出来，listdir 会带走整相。
    items = sorted(os.listdir(take_inbox)) if os.path.isdir(take_inbox) else []
    procs = [subprocess.Popen(
        [sys.executable, TOOL, "inbox", "take", items[i], "--into-record", "same title",
         "--memory", take_mem, "--root", take_con],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=HERE)
        for i in range(len(items))]
    outs2 = []
    for p in procs:
        try:
            o, e = p.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            p.kill()
            o, e = p.communicate()
        outs2.append((p.returncode, decode_output(o), decode_output(e)))
    made2 = sorted(f for f in os.listdir(os.path.join(take_con, CONTAINER))
                   if f != "README.md")
    ok(all(rc == 0 for rc, _, _ in outs2) and len(made2) == 6,
       "6 个进程同时 take 同一个标题：一人一份，没有静默覆盖",
       f"rc={[rc for rc, _, _ in outs2]} files={made2} "
       f"err={[e.strip().splitlines()[-1:] for _, _, e in outs2 if e.strip()]}")
    nums2 = sorted(JOURNAL.name_number(f) for f in made2)
    ok(len(set(nums2)) == 6,
       "6 个进程同时 take：篇号互不相同（原来六份都算在 0001 上）", str(nums2))
    taken = "\n".join(read(os.path.join(take_con, CONTAINER, f)) for f in made2)
    ok(taken.count("（来自信箱") == 6 and all(f"payload {i}" in taken for i in range(6)),
       "6 个进程同时 take：六条正文都在，没有哪一条被覆盖掉",
       f"（来自信箱 ×{taken.count('（来自信箱')}；"
       f"缺={[i for i in range(6) if f'payload {i}' not in taken]}）")
    take_left = sorted(os.listdir(take_inbox)) if os.path.isdir(take_inbox) else []
    ok(not take_left,
       "6 个进程同时 take：取走的六条都从信箱里删干净了", str(take_left))

    # ---- 占号对账：**确定性**地撞号（第三轮复查 N-A）------------------- #
    #
    # 上面那两条并发用例要"真撞上"才算数，而正常时序下六个进程拿到的是 1..6 ——
    # 也就是说它们**测不到**对账逻辑本身（N-A 就是这么漏过去的）。这里不靠运气：
    # 直接把两/三份同号记录摆好，再像"每个进程各对账一次"那样各调用一次
    # `settle_number_collision()`。判据三条：号两两不同、正文首行的篇号等于文件名、
    # 旧实现（一轮只搬一份）在三路时会留下重号，所以三路这条是**必然**变红的。
    def same_number(cnt: int, tag: str) -> tuple[str, list[str], list[str]]:
        d = os.path.join(fx, f"settle-{tag}")
        os.makedirs(os.path.join(d, CONTAINER))
        write(os.path.join(d, CONTAINER, "README.md"), INDEX)
        slugs = [f"{tag}-{i}" for i in range(cnt)]
        paths = []
        for slug in slugs:
            p = JOURNAL.reserve_new_record(
                os.path.join(d, CONTAINER), 1, slug,
                f"# 0001 · 同号 {slug}\n\n日期：2026-09-14\n迭代：12\n触发：\n范围：\n结论：\n")
            paths.append(p)
        return d, paths, slugs

    for cnt in (2, 3):
        d, paths, slugs = same_number(cnt, f"{cnt}way")
        jd = os.path.join(d, CONTAINER)
        for p, s in zip(paths, slugs):
            JOURNAL.settle_number_collision(jd, p, s)
        files = sorted(f for f in os.listdir(jd) if f != "README.md")
        got = sorted(JOURNAL.name_number(f) for f in files)
        ok(len(set(got)) == len(got),
           f"{cnt} 路同号各对账一次：篇号互不相同（一轮只搬一份会留下重号）",
           f"files={files} nums={got}")
        heads = []
        for f in files:
            m = JOURNAL.HEADING_RE.match(read(os.path.join(jd, f)).splitlines()[0])
            heads.append(int(m.group(1)) if m else None)
        ok(heads == got,
           f"{cnt} 路同号：正文首行的篇号 == 文件名里的号（改名要连正文一起改）",
           f"heads={heads} nums={got}")

    # ---- 两条"标题"正则各管各的（2026-10-15 性能复核补的守卫）---------------------- #
    #
    # `HEADING_RE`（`journal.py:155`，管**首行篇号**，上面刚用过、`renumber_body` 也在用）
    # 与小节标题的 `_SECTION_HEADING_RE`（`heading_level()` 在用）一旦重名，后定义的那个会
    # **静默覆盖**前一个：症状是 `check` 直接
    # `ERROR: … invalid literal for int() with base 10: '#'`、退出 2 —— 性能补丁的第一版
    # 就这么撞过一次，靠 A/B 比对 exit code 才发现（当时还差点信了一个假的 62×）。
    # 这里把两条的**行为**各钉一句：覆盖掉任一条，这条断言都会红。
    num_hit = JOURNAL.HEADING_RE.match("# 0001 · 标题")
    ok(num_hit is not None and num_hit.group(1) == "0001"
       and JOURNAL.heading_level("## 验证") == (2, "验证")
       and JOURNAL.heading_level("## 验证 \t\n") == (2, "验证")
       and JOURNAL.heading_level("正文一行，不是标题") is None
       and JOURNAL.heading_level("#") is None,
       "两条标题正则各管各的：`HEADING_RE` 仍取得到首行篇号，`heading_level` 仍认 `## 验证`",
       f"HEADING_RE={JOURNAL.HEADING_RE.pattern!r} "
       f"小节={JOURNAL._SECTION_HEADING_RE.pattern!r}")

    # ---- 短路的等价性（2026-10-15 复核 L2）：等价变换，变异法盯不住，只能对拍 ---------- #
    #
    # `heading_level()` 的第一句 `if not line.startswith("#"): return None` 是**等价**的加速：
    # 拆掉它结果不变、只是变慢 —— 没有哪条变异能让它变红（变异法证明不了等价变换）。
    # 所以把改动之前那条字面量正则留在断言里，对一段样例逐行比 `heading_level()` 与它的判定：
    # 以后谁再动短路条件或正则，只要有一行结果不同，这条就红（样例含 CRLF、行尾空白、制表符、
    # 行首缩进、单个 `#` 与七级井号这些边界）。
    legacy_section = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*\r?\n?$")
    heading_sample = [
        "# 0001 · 标题", "## 验证", "## 验证 \t\n", "### 三级   ", "#### 四级\r\n",
        "###### 六级", "#\t制表符分隔", "####### 七级不算", "# 无空格不算", "#",
        "", "正文一行，不是标题", "  ## 缩进不算（原来那条正则也不认）",
    ]
    heading_mismatch = []
    for line in heading_sample:
        m = legacy_section.match(line)
        want = (len(m.group(1)), m.group(2)) if m else None
        got = JOURNAL.heading_level(line)
        if got != want:
            heading_mismatch.append((line, got, want))
    ok(not heading_mismatch,
       "标题扫描的短路与改动前那条字面量正则逐行同判（等价变换：变异法盯不住，只能对拍）",
       f"对不上={heading_mismatch}")

    # ---- 对账的另一半：先收工的那一份，不许被"名字更小"顶掉（2026-10-15 补）-------- #
    #
    # 上面那两条是**顺序**调用的：每份都还没收工就被叫来对账。真实并发下还有另一半时序 ——
    # 先跑完对账的进程那一份**先收工**（它那时只看得见自己，留下是应该的），后到的那份若按
    # "名字最小者留下"判，可能因为名字恰好排前面而**也**留下：两边都以为自己赢了，重号就
    # 留在盘上。这不是推演出来的：起飞前检查跑未变异自测时真冒出来过一次
    # `[1, 2, 3, 4, 5, 5]`（重号率很低，靠并发用例撞是撞不出来的）。这里不靠运气：
    # 先让一份单独对完账（模拟"先收工"），再塞一份**名字更小**的同号记录进去。
    early = os.path.join(fx, "settle-early")
    os.makedirs(os.path.join(early, CONTAINER))
    write(os.path.join(early, CONTAINER, "README.md"), INDEX)
    ed = os.path.join(early, CONTAINER)
    late = "# 0005 · 后到的\n\n日期：2026-09-14\n迭代：12\n触发：\n范围：\n结论：\n"
    mine = JOURNAL.reserve_new_record(ed, 5, "mine", late.replace("后到的", "先收工的"))
    JOURNAL.settle_number_collision(ed, mine, "mine")        # 只看得见自己：留着 5 收工
    also = JOURNAL.reserve_new_record(ed, 5, "also", late)   # 同号，名字排在 "mine" 前面
    _path, also_num = JOURNAL.settle_number_collision(ed, also, "also")
    early_files = sorted(f for f in os.listdir(ed) if f != "README.md")
    early_nums = sorted(JOURNAL.name_number(f) for f in early_files)
    ok(len(set(early_nums)) == len(early_nums) and also_num != 5,
       "同号对账：先收工的那一份留下，后到的让路（名字排前面也不算赢）",
       f"files={early_files} nums={early_nums}")

    # `new --dry-run` 的预报必须与真跑**同判**（第三轮复查 N-B）：真跑每次尝试都重问
    # `taken_numbers()`，而只看名字会预报出被**别的 slug** 占着的号。窗口用"把号快照
    # 钉在旧的一刻"来复现 —— 那是唯一确定性复现它的办法，且不改被测代码路径。
    drift = os.path.join(fx, "dryrun-drift")
    os.makedirs(os.path.join(drift, CONTAINER))
    write(os.path.join(drift, CONTAINER, "README.md"), INDEX)
    jd = os.path.join(drift, CONTAINER)
    JOURNAL.reserve_new_record(jd, 1, "first", "# 0001 · 先来的\n")
    real_find = JOURNAL.find_entries
    stale = JOURNAL.find_entries(jd, JOURNAL.lessons_skip(None))
    JOURNAL.reserve_new_record(jd, 2, "others", "# 0002 · 窗口里插进来的\n")

    def dry_run_number(dry: bool) -> str:
        JOURNAL.find_entries = lambda *a, **k: {n: list(v) for n, v in stale.items()}
        try:
            argv = ["new", "--root", drift, "--title", "drift", "--slug", "mine"]
            if dry:
                argv.append("--dry-run")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                JOURNAL.main(argv)
        finally:
            JOURNAL.find_entries = real_find
        key = "将创建" if dry else "created"
        hit = [l.split(key, 1)[1].strip() for l in buf.getvalue().splitlines() if key in l]
        return hit[0] if hit else ""

    pred = dry_run_number(True)
    real = dry_run_number(False)
    ok(bool(pred) and pred == real,
       "new --dry-run 的篇号 == 真跑的篇号（别的 slug 抢在窗口里占了那个号时也一样）",
       f"dry-run={pred!r} 真跑={real!r}")

    # 兜底名字也得是**合法记录名**，否则连撞一千次之后会造出一个 `brief` 看不见的文件。
    fb = JOURNAL.new_record_fallback_name(42, "some-slug")
    ok(JOURNAL.NUM_FILE_RE.match(fb) is not None and fb.startswith("0042-"),
       "兜底记录名仍然是记录（NUM_FILE_RE 认它）", fb)


# ── 记忆卡投影（dsh-lore-card.py）────────────────────────────────────────
# 这一相要守的是三条**设计不变量**，不是"命令能跑"：
#   ① 卡不许比它替代的真源更贵（体量闸）；② 复跑幂等（零新增、索引字节不变）；
#   ③ 卡带 `domain:` / `condition_space`（给灵枢条件桶路），但**不依赖**灵枢——
#      这个工具在没装灵枢的机器上必须照样跑得完。
CARD_QUOTE = "本条结论已进 lessons，可复用。"


def card_record(no: str, title: str, bar: str, second: str) -> str:
    return (f"# {no} · {title}\n\n"
            f"日期：2026-10-16\n迭代：{int(no)}\n触发：自测夹具\n范围：卡投影相\n结论：{bar}\n\n"
            f"---\n\n## 一、背景\n\n自测夹具造的记录。\n\n"
            f"## 二、核心教训\n\n- **{bar}**：{second}\n\n"
            f"## 三、验证\n\n- 命令：`python -B scripts/_selftest.py`\n- 结果：见本相断言\n"
            f"- 未覆盖：无\n\n## 四、遗留与下一轮\n\n- 无。\n")


def card_record_with_bulk(no: str, title: str, bar: str, second: str) -> str:
    """和 `card_record` 同一篇，只是**原文够厚**（> 两卡之和）。

    为什么需要一厚一薄两种：体量闸有两条腿——「真源 < `--min-source`」和
    「两卡 ≥ 真源」。薄记录只能触发前者；要触发后者（卡比真源还贵）得让真源够厚，
    否则测出来的永远是那条 400 B 的底线，`--min-source` 一改断言就假绿。
    """
    filler = "".join(
        f"\n第 {i} 段：这一节是夹具的正文，用来把真源撑到远远超过两卡之和，"
        f"让体量闸走到「卡比真源还大」那条分支上，而不是只测 400 B 的底线。\n"
        for i in range(1, 31))
    return (f"# {no} · {title}\n\n"
            f"日期：2026-10-16\n迭代：{int(no)}\n触发：自测夹具\n范围：卡投影相\n结论：{bar}\n\n"
            f"---\n\n## 一、背景\n{filler}\n"
            f"## 二、核心教训\n\n- **{bar}**：{second}\n\n"
            f"## 三、验证\n\n- 命令：`python -B scripts/_selftest.py`\n- 结果：见本相断言\n"
            f"- 未覆盖：无\n\n## 四、遗留与下一轮\n\n- 无。\n")


def card_record_mid(no: str, title: str, bar: str, second: str) -> str:
    """第三档：**够出卡又够薄**（`--min-source` < 真源 < 两卡之和）。

    为什么需要这一档（2026-10-16 连踩三次）：
      · 只有「厚」「薄」两种时，凡是指向薄记录的**分册条目**都会被体量闸整条丢掉
        （分册的条目也按 `wl/NNNN` 去量那篇记录），于是依赖这些卡的断言验的是空集；
      · 但也不能直接把薄记录加厚——`0002-short` 的存在意义就是**卡在 400 B 线以下**，
        加厚等于把「真源太短 → 不出卡」那条断言废掉；
      · 这一档的尺寸被两个下上界夹着：下限是 `--min-source` 默认 400 B，
        上限是「两张卡」——而卡里有 id/tags/source 这些**跟正文无关的固定开销**，
        实测两卡约 2.2–2.6 KB，所以真源得写到 3 KB 上下才过闸。
    """
    filler = "".join(
        f"\n第 {i} 段：这一节是夹具的正文，用来把真源撑到**超过两卡之和**，"
        f"但又要明显薄于 `0001-long`，这样「同册不同出处」两档都测得着；"
        f"体量闸量的是两卡/真源的比值，不是字面长度，所以这一段必须写够。\n"
        for i in range(1, 13))
    return (f"# {no} · {title}\n\n"
            f"日期：2026-10-16\n迭代：{int(no)}\n触发：自测夹具\n范围：卡投影相\n结论：{bar}\n\n"
            f"---\n\n## 一、背景\n{filler}\n"
            f"## 二、核心教训\n\n- **{bar}**：{second}\n\n"
            f"## 三、验证\n\n- 命令：`python -B scripts/_selftest.py`\n- 结果：见本相断言\n"
            f"- 未覆盖：无\n\n## 四、遗留与下一轮\n\n- 无。\n")


def card_record_long_sentence(no: str, title: str, bar: str) -> str:
    """第四档：**第一句就超过 200 字**（通篇只在最后收一个句号）。

    为什么非要这一档（2026-10-17 复核指出"投影器那条修法没有断言盯着"）：
    `first_sentence(text, 200)` 只在"第一句超长"时才走截断分支，而截断时它会**自己补一个 `…`**
    —— 那个字符正文里根本没有。`ccg()` 里"正文以摘要开头就去掉那一段"的守卫要是带着这个 `…`
    去比前缀，就永远比不中，于是整段被追加在摘要后面，「执行」小节的开头逐字出现两遍。
    夹具里没有长句记录，这条守卫在真实卡上就永远测不到 —— 而它恰恰是真卡上先暴露的
    （实测 42 张 full 卡里 5 张重复）。所以这一档是那条断言的**靶子**，别删。
    """
    # 真源必须**厚到"重复版"的卡也能过体量闸**：这一档要验的正是"「执行」小节重复开头"，
    # 而重复会把卡撑大约 600 B —— 真源贴着两卡之和时，变异一打，卡会**先被体量闸丢掉**，
    # 于是断言看到的是"没有卡"，永远等不到变红（第一版就是这么假绿的，实测两卡 3845 B
    # 对真源 3797 B，刚好越线）。所以这里堆到真源的五六倍。
    filler = "".join(
        f"\n第 {i} 段：这一节把真源撑得足够厚，好让体量闸放行，与长句本身无关 ——"
        f"它存在的唯一理由是让「重复版」的卡也过得了闸，"
        f"否则变异打上去之后卡先被丢掉，那条断言就永远没有机会变红。\n"
        for i in range(1, 31))
    # 那条教学 bullet：**一个句末标点都没有，直到最后那个 `。`**（`first_sentence()` 因此
    # 先把整段当成"第一句"，再发现它超过 200 字，于是从句处截断并补 `…`）。
    # ⚠ 结尾必须真的落一个 `。`：抽教训那一步只收"以句号收尾的完整 bullet"，
    # 少了它整篇会被当成"没有可投影的教训"跳过 —— 这一档就白加了（第一次就是这么跳过的）。
    long_body = (
        "这一条结论的第一句就必须明显超过两百个字，中间只用顿号、逗号与分号这些停顿连着，"
        "一直不落句号、不落问号、也不落感叹号，好让摘要那条分支真的走到超长截断上去，"
        "真的在摘要尾巴上补出一个正文里根本没有的省略号，"
        "再让「执行」小节拿着那个带省略号的摘要去比前缀，看看它到底认不认得出来；"
        "后面这一截是故意加长的尾巴，用来保证整段正文明显长于那两百字的摘要，"
        "也只有这样开头重复才看得出来、这条守卫才算真的被人盯着，"
        "否则夹具里全是短句、截断那条分支永远走不到，"
        "这条断言就会变成一条永远不会红的摆设。")
    return (f"# {no} · {title}\n\n"
            f"日期：2026-10-16\n迭代：{int(no)}\n触发：自测夹具\n范围：卡投影相\n结论：{bar}\n\n"
            f"---\n\n## 一、背景\n{filler}\n"
            f"## 二、核心教训\n\n- **{bar}**：{long_body}\n\n"
            f"## 三、验证\n\n- 命令：`python -B scripts/_selftest.py`\n- 结果：见本相断言\n"
            f"- 未覆盖：无\n\n## 四、遗留与下一轮\n\n- 无。\n")


def card_phase(tmp: str) -> None:
    """记忆卡投影：体量闸 / 幂等 / 索引 / 归属 / 独立性（不需要灵枢在）。"""
    croot = os.path.join(tmp, "cards")
    cont = os.path.join(croot, CONTAINER)
    write(os.path.join(cont, "0001-long.md"), card_record_with_bulk(
        "0001", "长记录", "长记录这条结论够长，够产出一张卡。",
        "正文足够长，说明白根因、做法、验证方式，让它成为一条可复用结论，不是半句话。"))
    # 真源 < 400 B（--min-source 默认 400）：读原文更省，闸门该拦在**出卡之前**。
    write(os.path.join(cont, "0002-short.md"), card_record(
        "0002", "极短", "极短记录", "一句话，但得长到能被当成一条教训抽出来，否则它根本走不到体量闸。"))
    # 第三档：够出卡但很薄。给 `lessons/03-cite.md` 当出处用 —— 那边要验的是
    # 「同册不同出处」「出处指得到」「源被删后那张卡才 stale」，
    # 拿 `0001-long` 当出处会让这些卡跟着它一起变 stale，反而验不出「只有该 stale 的 stale」。
    write(os.path.join(cont, "0003-mid.md"), card_record_mid(
        "0003", "中等", "够出卡但很薄的那档。", "一句话结论，凑不出第二句。"))
    # 第四档：第一句超长（> 200 字、通篇不落句号）—— 专给「执行」小节那条去重断言当靶子，
    # 详见 `card_record_long_sentence()` 的说明。别删：删了那条断言就没有反例可抓。
    write(os.path.join(cont, "0004-longsentence.md"), card_record_long_sentence(
        "0004", "长句", "长句这条结论要被摘要截断。"))
    # 第五档：正文**两句以上**（第一句带句号，后面还有正文）—— 专给「卡正文行不许以
    # 『。』开头」那条断言当靶子（2026-10-17 复核）。`ccg()` 拿 `_trim_ellipsis(摘要)` 的
    # 长度去切正文，而它把句末「。」剥掉了 → 剩下的正文以那个「。」开头，落进卡里就是
    # 一行「。 后半句」。只有"第一句有句号 + 后面还有字"的正文才触发，单句记录的卡测不到
    # （夹具里其余几档的正文都是单句，所以从前这条缺陷一个断言也没有）。
    write(os.path.join(cont, "0005-two-sentences.md"), card_record_with_bulk(
        "0005", "两句正文", "两句正文的靶子",
        "第一句先把根因说完。第二句接着给做法与验证方式，让摘要后面确实还留着正文。"))
    # 第六档：**文件名够长**，让 `work_log/…` 这条源路径超过 34 字节。索引「源」列那条
    # 「不截断」的断言（连同反向变异「源列又截断」）靠它才有靶子 —— 其余夹具的源路径
    # 都短于 34 字节，`_clip(…, 34)` 在它们身上根本不触发，断言与变异都会空转。
    write(os.path.join(cont, "0006-long-source-path-for-the-index-source-column.md"),
          card_record_with_bulk(
              "0006", "长源路径", "长源路径的靶子",
              "文件名写得够长，索引里的源路径才会被旧实现截成半截，拼不回这篇记录。"))
    write(os.path.join(cont, "lessons", "README.md"), LESSONS_INDEX)
    # 另一册：出处指向**本容器里那篇长记录**，验「出处指得到」这一档；
    # 它的源记录在下面会被删掉，用来验「源没了 → 卡要标 stale」。
    # 两个坑都踩过：① 文件名必须是 `NN-*.md` —— 平铺的 `lessons/*.md` 会被**记录路**
    # 先当成一篇记录吃掉（那正是 `outline` 要排除的形态），走不到分册路；
    # ② 分册自己也得过体量闸（`--min-source` 默认 400 B），太短的话卡根本不生成，
    # 于是那条断言验的是**空集**——看着绿，其实什么都没验。
    write(os.path.join(cont, "lessons", "02-aging.md"),
          "# 经验手册 · 02-aging\n\n"
          "- **出处指得到时才谈得上追溯**：卡的 `source` 必须落在本容器里那篇记录上，"
          "指不到就别写成一个看着像真的路径。（`wl/0001`；本条结论已进 lessons，可复用。）\n"
          "- **追踪链要能被验证**：一篇记录被删掉之后，指向它的卡应当变成可发现的旧账，"
          "而不是继续显示得像新鲜结论。（`wl/0001`；本条结论已进 lessons，可复用。）\n"
          "- **追溯的成本要压住**：读者顺着卡找原文只该多花一两次读取，"
          "所以指针卡不给第二真源、只给一条路径。（`wl/0001`；本条结论已进 lessons，可复用。）\n")
    write(os.path.join(cont, "lessons", "01-topic.md"),
          "# 经验手册 · 01-topic\n\n" + "".join(
              f"- **{t}**：{b}（`{s}`；{CARD_QUOTE}）\n"
              for t, b, s in [
                  ("有效收件箱的命名约定", "有效收件箱必须用固定前缀，否则扫描会把夹具自己吞进来。", "wl/0001"),
                  ("离线工具的退出码语义", "离线工具用退出码 2 表示用法错误，用 1 表示内容不合格，两者不许混。", "wl/0001"),
                  ("索引是生成物", "索引一律由脚本重建，手写的那份必然与正文分叉。", "wl/0001"),
                  ("断言要断到整句", "子串比对会放过语义错误，断言要断到整条语句。", "wl/0001"),
                  ("退出码先定后写", "先把退出码的语义定下来再写实现，否则下游分不清两类失败。", "wl/0001"),
                  ("空目录不是错误", "空目录是合法输入，报错会把首次运行变成故障。", "wl/0001"),
                  ("日志先归位再落盘", "任何产出先想好归位目录，否则工作区根会一点一点被堆满。", "wl/0001"),
                  ("先记录后动手", "方案类改动先把要解决什么写下来，再动手实现。", "wl/0001"),
                  ("复跑必须幂等", "凡生成物都要能复跑，且第二次不产生任何新文件。", "wl/0001"),
                  ("真源必须可追", "每条结论都要留得下出处，指不到出处的结论不要沉淀。", "wl/0001"),
                  ("边界要显式写", "不适用条件必须显式声明，拿遗留事项充数会把检索面污染。", "wl/0001"),
                  ("体量也是判据", "记录若比它替代的上下文更贵，就不该存在。", "wl/0001"),
                  ("引用要能落地", "引用写成别人点得开的路径，别写只有自己懂的短号。", "wl/0001"),
                  ("临时产物的寿命", "临时目录里的东西跑完就该清掉，别让它长成第二份真源。", "wl/0001"),
              ]))

    # 再一册：出处指向**另一篇短记录**（`wl/0002`），与 02-aging 指向的不是同一篇。
    # 为什么要在第一轮投影**之前**落盘：晚落盘的话第一轮看不到它，
    # 第二轮才把它投影出来 → 「复跑幂等」那条断言会以"卡变多了"的形式假红
    # （2026-10-16 真踩过：18 vs 21）。夹具的规则是**投影开始前把料备齐**。
    #
    # 每条正文都要长过 400 B：分册的**条目**也按它自己指的 `wl/NNNN` 去量那篇记录
    # （见上面的 ①/②），出处指向 `0002-short`（370 B）的话这三条会被体量闸整条
    # 丢掉，于是「此刻没有 stale」那条断言验的是空集——卡根本没生成，看着绿其实
    # 什么都没验（2026-10-16 踩过两次）。所以这里指 `0003-mid`，
    # 顺带把「同册不同出处」这条分支坐实。
    write(os.path.join(cont, "lessons", "03-cite.md"),
          "# 经验手册 · 03-cite\n\n"
          "- **出处要指得着**：卡的 `source` 必须落在本容器里真实存在的那篇记录上，"
          "指不到就别写成一个看着像真的路径，宁可如实标 unknown，让人一眼看出这条"
          "追溯链是断的。（`wl/0003`；本条结论已进 lessons，可复用。）\n"
          "- **出处要指得准**：一册里不同条目的出处可以不同，别把整册的落点当成"
          "每条结论的出处，那样追溯会指到整本书而不是那一页，等于没指。"
          "（`wl/0003`；本条结论已进 lessons，可复用。）\n"
          "- **引用是双向承诺**：写下一条引用就等于承诺那篇记录还在，"
          "记录被归档时指向它的卡应当能被查出来，而不是继续显示得像一条新鲜结论。"
          "（`wl/0003`；本条结论已进 lessons，可复用。）\n")

    # 卡式条目（`0127`）：三字段必须被投影进「生效条件 / 验证方式 / 卡尾「别再来」」，
    # 而且**不许**再作为正文留在「执行」里（2026-10-18 审查 M3 的端到端靶子）。
    # 第二条「薄卡」专打体量闸：主行只有 12 字符、三字段齐全 —— 只量 body 的实现会把它丢掉。
    topic_path = os.path.join(cont, "lessons", "01-topic.md")
    write(topic_path, read(topic_path) +
          "- **卡式条目的三字段**：正文说明这条经验为什么值得三个字段，以及它们各自该被"
          "投影到哪里，而不是连成一行塞进「执行」。（`wl/0001`；" + CARD_QUOTE + "）\n"
          "  - 触发：改完插件产物后邻居界面丢样式\n"
          "  - 验证：querySelectorAll('style:not([data-plugin])').length === 0\n"
          "  - 别再来：把标记写成 data-plugin-css（不在宿主判据里）\n"
          "- **薄卡也有内容**：短。（`wl/0001`）\n"
          "  - 触发：薄卡的触发条件刻意写长一点，确保断言的余量明显而不是一个字符\n"
          "  - 验证：薄卡的验证方式也写长一点，确保体量闸不是靠一个字符过关\n"
          "  - 别再来：薄卡的反面清单同样写长一点，避免断言在门槛附近翻面\n"
          "```markdown\n"
          "- **围栏里的示例条目**：这段在围栏代码块里，只是示例，不该被投影成卡。（`wl/0001`；"
          + CARD_QUOTE + "）\n"
          "  - 触发：示例触发\n"
          "  - 验证：示例验证\n"
          "```\n"
          "* **星号条目也要投影**：星号写的条目与短横线写法同义，检查认它、投影也必须认它。"
          "（`wl/0001`；" + CARD_QUOTE + "）\n")

    tool = os.path.join(HERE, "dsh-lore-card.py")
    ok(os.path.isfile(tool), "dsh-lore-card.py ships next to journal.py", tool)

    if os.path.isdir(os.path.join(cont, "memory-cards")):
        shutil.rmtree(os.path.join(cont, "memory-cards"), ignore_errors=True)

    r = run(croot, CONTAINER, "--all", "--write", "--project", "selftest-project", tool=tool)
    # 调试落盘写在**夹具目录里**，跟随 `--keep` 的生命周期（2026-10-17 清理）：
    # 从前落在 `dirname(tmp)`（也就是 `--root`）里，而 `--root` 是**共享的夹具父目录**，
    # 跑完谁也不删它 —— 每跑一次自测就在那儿留一份 57 KB 的输出，与 `-B` 那条规矩
    # （"跑过自测不该弄脏下一道门禁"）是同一件事的两个面。加 `--keep` 才会保留。
    with open(os.path.join(tmp, "cardphase-run1.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(r.stdout + "\n[stderr]\n" + r.stderr)
    ok(r.returncode == 0, "card projection exits 0", r.stdout + r.stderr)
    ok("DROP" in r.stdout,
       "the size gate drops what costs more than the source it replaces", r.stdout)
    ok("0002-short" not in r.stdout,
       "the too-short record is never projected", r.stdout)

    cards = os.path.join(cont, "memory-cards")
    ptrs = sorted(f for f in os.listdir(cards) if f.endswith(".pointer.md")) if os.path.isdir(cards) else []
    fulls = sorted(f for f in os.listdir(cards) if f.endswith(".full.md")) if os.path.isdir(cards) else []
    ok(len(ptrs) >= 8, "cards are projected from records and lessons", f"{len(ptrs)} pointers")
    ok(len(ptrs) == len(fulls), "every card has both the pointer and the full copy",
       f"{len(ptrs)} vs {len(fulls)}")
    ok(all(os.path.getsize(os.path.join(cards, f)) > 300 for f in ptrs),
       "cards are not empty stubs")

    # 卡正文**不许有一行以「。」开头**（2026-10-17 复核）：`ccg()` 算剩余正文时用的是
    # `_trim_ellipsis(摘要)` 的长度，而那个函数把句末「。」剥掉了 —— 切出来的 `rest`
    # 就以那个句号开头，落进卡里变成「。 七条缺陷…」这样一行。真容器里 8 张 full 卡
    # 实测如此（`wl0107-*`、`wl0108`），`0005-two-sentences` 是本断言的靶子。
    lead_period = []
    for fn in fulls:
        for ln in read(os.path.join(cards, fn)).splitlines():
            if ln.startswith("。"):
                lead_period.append(f"{fn}: {ln[:40]}")
    ok(not lead_period,
       "no card body line starts with a stray 「。」（摘要后的句号不该被切成新行）",
       "；".join(lead_period[:3]) or f"{len(fulls)} 张 full 卡逐行查过")

    # 「执行」小节**不许把开头说两遍**（2026-10-17 第二轮修全的那条）。
    # 卡里那一节是"摘要 + 正文剩余"，而摘要是正文的 `first_sentence(…, 200)`；
    # 第一句超长时那个函数会**自己补一个 `…`**，而 `…` 不在正文里 —— 前缀守卫一旦带着它
    # 就永远比不中，于是整段正文被追加在摘要后面，开头逐字出现两遍（实测真卡里 5 张如此）。
    # 判据取**归一后**的开头 80 字，数它在整节里出现几次：一次才对。
    # `0004-longsentence` 就是为这条断言造的靶子（它第一句超过 200 字、尾巴被补了 `…`）。
    dup_exec = []
    for fn in fulls:
        sec = re.search(r"(?m)^#\s*执行\s*$\n(.*?)(?=\n#\s|\Z)", read(os.path.join(cards, fn)), re.S)
        flat = " ".join(sec.group(1).split()) if sec else ""
        if len(flat) >= 80 and flat.count(flat[:80]) > 1:
            dup_exec.append(fn)
    ok(not dup_exec,
       "the 执行 section never says its opening twice (truncated `…` included)",
       "、".join(dup_exec) or f"{len(fulls)} 张 full 卡逐张查过")
    ok(not any(p.startswith("wl0002") for p in ptrs),
       "no card slug derives from the too-short record", " ".join(ptrs)[:200])

    # 卡式三字段（`0127` × 2026-10-18 审查 M3 + 复核 medium/low）：各归其位，
    # 「别再来」单独成节、不污染「不适用条件」；薄主行靠三字段撑过体量闸。
    card_sec: dict[str, str] = {}
    thin_card = False
    for fn in fulls:
        text = read(os.path.join(cards, fn))
        if "卡式条目的三字段" in text:
            for key in ("生效条件", "执行", "验证方式", "不适用条件", "别再来"):
                m = re.search(rf"(?m)^#\s*{key}\s*$\n(.*?)(?=\n#\s|\Z)", text, re.S)
                card_sec[key] = " ".join(m.group(1).split()) if m else ""
        if "功能名" in text and "薄卡也有内容" in text:
            thin_card = True
    ok(bool(card_sec), "a lesson card carrying 触发/验证/别再来 is projected",
       f"{len(fulls)} full 卡里没找到靶子")
    ok("触发：改完插件产物后邻居界面丢样式" in card_sec.get("生效条件", ""),
       "the lesson's 触发 is projected into 生效条件", card_sec.get("生效条件", "")[:200])
    ok("querySelectorAll('style:not([data-plugin])')" in card_sec.get("验证方式", ""),
       "the lesson's 验证 is projected into 验证方式 (not the generic fallback)",
       card_sec.get("验证方式", "")[:200])
    ok("把标记写成 data-plugin-css" in card_sec.get("别再来", ""),
       "the lesson's 别再来 is projected into its own section",
       card_sec.get("别再来", "")[:200])
    ok("别再来" not in card_sec.get("不适用条件", ""),
       "别再来 no longer pollutes 不适用条件（它不是适用性边界）",
       card_sec.get("不适用条件", "")[:200])
    ok("边界未在来源里显式声明" in card_sec.get("不适用条件", ""),
       "a card without a real boundary keeps the honest fallback",
       card_sec.get("不适用条件", "")[:200])
    ok(thin_card,
       "a thin main line with all three fields still produces a card (size gate counts fields)",
       f"{len(fulls)} full 卡里没找到薄卡靶子")
    ok("触发：" not in card_sec.get("执行", "") and "验证：" not in card_sec.get("执行", ""),
       "the card fields no longer leak into the 执行 section", card_sec.get("执行", "")[:200])
    all_cards = "\n".join(read(os.path.join(cards, fn)) for fn in fulls)
    ok("围栏里的示例条目" not in all_cards,
       "a fenced example lesson is not projected into a card", all_cards[:100])
    ok("星号条目也要投影" in all_cards,
       "a star-bullet lesson is projected too (same marker set as check)", all_cards[:100])

    body = read(os.path.join(cards, ptrs[0])) if ptrs else ""
    ok("domain:selftest-project" in body and "condition_space" in body,
       "cards carry the domain tag and condition_space (for the Lingshu bucket path)", body[:200])
    ok("边界未在来源里显式声明" in body,
       "an undeclared boundary is reported honestly instead of being faked", body[:200])

    idx = os.path.join(cards, "INDEX.md")
    idx1 = read(idx)
    ok(bool(idx1) and "| id | 域 | 功能名 |" in idx1, "INDEX.md is rebuilt with the one-line-per-card table")
    ok(idx1.count("\n| `") == len(ptrs), "INDEX has exactly one row per card",
       f"rows={idx1.count(chr(10) + '| `')} cards={len(ptrs)}")
    if "源未找到" in idx1:
        # 断了才把整份 INDEX 落盘，方便直接翻（断言详情会被截断，看不着全貌）。
        # 同样写在夹具目录里（见上面 `cardphase-run1.txt` 那段）：**加 `--keep` 才留得下**。
        with open(os.path.join(tmp, "cardphase-index.txt"), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(idx1)
    stale_detail = "全文见夹具目录里的 cardphase-index.txt（不加 --keep 跑完即删，出这条就加 --keep 重跑）"
    ok("源未找到" not in idx1,
       "nothing is stale while every source record is still there", stale_detail)
    # "表头不许漏卡正文"要断在**整行**上：正文里某个短语本身可能就出现在表头文档里
    # （「边界未在来源里显式声明」就是这样 —— 表头在**说明**这件事，不是泄漏）。
    head_block = idx1.split("| id |")[0]
    ok(not any(ln.startswith("| `") for ln in head_block.splitlines()),
       "the index header carries no card rows (bodies stay in the table only)")

    # 「源」列必须**能定位到记录**（2026-10-17 复核）：从前是 `_clip(r["source"], 34)`，
    # 真容器 50 行里 46 行被截成 `work_log/0108-review-r6-half-fixe…` —— 只看索引找不到
    # 那篇记录，读者被迫开卡，索引的一半意义就没了。两条一起钉：源不截断、拼回去真存在。
    src_cells = [ln.split("|")[6].strip() for ln in idx1.splitlines() if ln.startswith("| `")]
    clipped_src = [c for c in src_cells if "…" in c]
    ok(src_cells and not clipped_src,
       "the index's 源 column is not truncated (the index alone locates the record)",
       "；".join(clipped_src[:3]) or f"{len(src_cells)} 行源路径都完整")
    unresolved_src = []
    for c in src_cells:
        rel = c[len(CONTAINER) + 1:] if c.startswith(f"{CONTAINER}/") else c
        if not os.path.exists(os.path.join(cont, *rel.split("/"))):
            unresolved_src.append(c)
    ok(not unresolved_src,
       "every 源 in the index resolves to a real file (a clipped path cannot be joined back)",
       "；".join(unresolved_src[:3]) or f"{len(src_cells)} 行逐行 resolve 过")

    r2 = run(croot, CONTAINER, "--all", "--write", "--project", "selftest-project", tool=tool)
    ptrs2 = sorted(f for f in os.listdir(cards) if f.endswith(".pointer.md"))
    ok(r2.returncode == 0 and len(ptrs2) == len(ptrs),
       "re-running is idempotent: no duplicate cards", f"{len(ptrs2)} vs {len(ptrs)}")
    ok(read(idx) == idx1, "re-running leaves INDEX.md byte-identical")
    ok("已重建" not in r2.stdout or "无变化未写" in r2.stdout,
       "the index rebuild reports 'no change' on the second run", r2.stdout)

    r3 = run(croot, CONTAINER, "--index-only", "--write", tool=tool)
    ok(r3.returncode == 0 and "无变化" in r3.stdout,
       "--index-only rebuilds nothing when the index is already current", r3.stdout)
    # 只重建表格**不该**把表头（项目 / 项目域）退回按容器路径推的名字：
    # 两种模式轮流写会让同一个索引来回翻脸，每次都"已重建"，幂等就没了
    # （2026-10-16 真踩过：`--index-only` 把 `fixture-worklog` 改写成容器名）。
    ok(read(idx) == idx1,
       "--index-only keeps the project and domain recorded in the header", read(idx)[:160])

    # 源记录没了 → 指向它的卡必须变成可发现的旧账（`source_status: stale` + INDEX 标记）。
    # 这一步只重建索引、不重投影：重投影会把 lost 的源退化成"分册当源"再判一次体量，
    # 反而不一定留得下那张卡；而"卡还在、源没了"正是读者真会遇到的局面。
    # 源记录没了 → 指向它的卡必须变成可发现的旧账（`source_status: stale` + INDEX 标记）。
    # 这一步只重建索引、不重投影：重投影会把 lost 的源退化成"分册当源"再判一次体量，
    # 反而不一定留得下那张卡；而"卡还在、源没了"正是读者真会遇到的局面。
    # 用改名而不是删除：删掉会让记录路在**下一次**扫描里少一篇，干扰后续断言；
    # 改名等价于"这篇没了"，但夹具的其余部分原封不动。
    os.rename(os.path.join(cont, "0001-long.md"),
              os.path.join(cont, "0001-long.md.archived"))
    r4 = run(croot, CONTAINER, "--index-only", "--write", tool=tool)
    idx4 = read(idx)
    ok(r4.returncode == 0 and "已重建" in r4.stdout,
       "the index is rebuilt once a source record disappears", r4.stdout)
    ok("源未找到" in idx4,
       "the disappeared source is flagged stale in the index", idx4[:200])
    ok(any("source_status: stale" in read(os.path.join(cards, f)) for f in ptrs),
       "the card itself carries source_status: stale")
    r5 = run(croot, CONTAINER, "--index-only", "--write", tool=tool)
    ok("无变化" in r5.stdout and read(idx) == idx4,
       "a stale index is stable too: rebuilding it again changes nothing", r5.stdout)

    # 另一种断链：**出处编号写错**（`wl/9999` 在本容器里不存在）。
    # 它和上面"源记录被改名"是两种不同形态 —— 那个是"本来有、后来没了"，
    # 这个是"一开始就指不到"；后者不该让整轮投影报错，只该让那张卡带上 stale。
    # 之所以另开一个容器：它必然产生 stale，混进 card 容器会把
    # 「此刻没有 stale」（第一轮）与「第二遍字节相同」（复跑）两条断言一起推红。
    chain = os.path.join(croot, "chain")
    chcont = os.path.join(chain, CONTAINER)
    write(os.path.join(chcont, "lessons", "01-broken.md"),
          "# 经验手册 · 01-broken\n\n"
          + "".join(f"\n第 {i} 段：夹具正文，把真源撑过两卡之和，免得被体量闸先拦掉。\n"
                   for i in range(1, 13))
          + "- **出处写错就该露馅**：指向容器里不存在的编号，卡必须是可发现的旧账，"
            "而不是继续装作出处齐全。（`wl/9999`；本条结论已进 lessons，可复用。）\n"
          + "- **断链不影响同册其他条目**：一册里一条指出处写错，不该牵连别的条目，"
            "别的条目该照常出卡。（`wl/0001`；本条结论已进 lessons，可复用。）\n")
    write(os.path.join(chcont, "0001-long.md"), card_record_with_bulk(
        "0001", "长记录", "长记录这条结论够长，够产出一张卡。",
        "正文足够长，说明白根因、做法、验证方式，让它成为一条可复用结论，不是半句话。"))
    r6 = run(chain, CONTAINER, "--all", "--write", "--project", "chain-project", tool=tool)
    ok(r6.returncode == 0, "a broken citation does not fail the whole run", r6.stdout + r6.stderr)
    idx6 = read(os.path.join(chcont, "memory-cards", "INDEX.md"))
    ok("[源未找到]" in idx6,
       "a citation pointing nowhere lands in the index as stale", idx6[idx6.find("| id |"):][:400])
    # 只数**表格行**里的标记：表头还有一行「N 张的源记录不在本容器（`[源未找到]`）」的
    # 汇总，把那行算进来会得到 count=2，断言就永远红（2026-10-16 踩过）。
    stale_rows = [ln for ln in idx6.splitlines()
                  if ln.startswith("| `") and "[源未找到]" in ln]
    ok(len(stale_rows) == 1,
       "only the broken citation is stale, its siblings are not",
       f"stale_rows={len(stale_rows)}")

    # 头部元信息是**硬换行**写的：`结论：`/`范围：` 横跨两三行是真实记录的常态
    # （`0077`/`0078` 缩进两格、`0097` 顶格）。只取第一行会把整句切在逗号上，
    # 真实数据上表现为卡名退化成 `wl0077-worklog`、`# 执行` 只剩半句
    # （2026-10-16 在真容器上量到并修）。这里两种续行形态各验一遍。
    wrap = os.path.join(croot, "wrap")
    wpcont = os.path.join(wrap, CONTAINER)
    # 真源也得够厚，否则体量闸先把它拦掉（两卡之和 ≈2 KB），断言就成了空集。
    write(os.path.join(wpcont, "0001-wrapped.md"),
          "# 0001 · 换行夹具\n\n"
          "日期：2026-10-16\n迭代：1\n触发：自测夹具\n"
          "范围：第一段写到一半，\n  缩进两格的续行接上后半句。\n"
          "结论：结论也会横跨两行，\n顶格续行接着把话说完，收在句号上。\n\n"
          "---\n\n## 一、背景\n"
          + "".join(f"\n第 {i} 段：这一节是夹具的正文，用来把真源撑到**超过两卡之和**；"
                   f"体量闸量的是两卡/真源的比值，不是字面长度，所以这一段必须写够。\n"
                   for i in range(1, 13))
          + "\n## 二、核心教训\n\n"
            "- **换行要接回去**：元信息的值是硬换行写的，只读第一行会把句子切在半截。\n\n"
            "## 三、验证\n\n- 命令：`python -B scripts/_selftest.py`\n- 结果：见本相断言\n")
    r7 = run(wrap, CONTAINER, "--all", "--write", "--project", "wrap-project", tool=tool)
    ok(r7.returncode == 0, "the wrapped-metadata fixture projects", r7.stdout + r7.stderr)
    idx7 = read(os.path.join(wpcont, "memory-cards", "INDEX.md"))
    # `范围：` 那两行是**缩进**续行（`0078` 的形态），它进卡片的「生效条件」栏。
    # 断言用**合并后的完整值**，这样"切在逗号上"也会被抓到（子串只看后半句会假绿）。
    ok("范围：第一段写到一半， 缩进两格的续行接上后半句。" in idx7,
       "an indented continuation line is joined onto its key", idx7[idx7.find("| id |"):][:300])
    # `结论：` 那两行是**顶格**续行（`0097` 的形态）。它只在"记录没有任何 bullet 教训"
    # 时才会被当成那张卡，所以端到端验不到；这里直接量 `parse_record` 的合并结果
    # （2026-10-16：一开始只断言 INDEX，假红了一次 —— 卡片走的是 bullet 路，
    #  `结论` 根本不进卡）。
    card_mod = importlib.util.module_from_spec(
        importlib.util.spec_from_file_location("card_mod_wrap", tool))
    importlib.util.spec_from_file_location("card_mod_wrap", tool).loader.exec_module(card_mod)
    meta7 = card_mod.parse_record(os.path.join(wpcont, "0001-wrapped.md"))["meta"]
    ok(meta7.get("结论") == "结论也会横跨两行， 顶格续行接着把话说完，收在句号上。",
       "a flush-left continuation line is joined too", repr(meta7.get("结论"))[:200])
    ok(meta7.get("范围") == "第一段写到一半， 缩进两格的续行接上后半句。",
       "the indented continuation is joined exactly once", repr(meta7.get("范围"))[:200])

    # 独立性：这个工具只许用标准库，不许 import 灵枢（插件名 @furongjun1999/dsh-memory）。
    spec = importlib.util.spec_from_file_location("card_selftest_subject", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ok(not any("dsh-memory" in n for n in sys.modules),
       "the card tool imports nothing from the Lingshu plugin (runs standalone)")

    # ── 音译表与 slug（2026-10-17 补）────────────────────────────────────────
    #
    # 走的是 `card_phase`，不是内联在 `main()` 里：`tests/reverse-verify.py` 的变异
    # 只能打到 `*_phase` 函数（见那份脚本里 `PHASES` 上方的注释）—— 内联的断言
    # 变异永远等不到它变红，等于没测。这里离"投影器"最近，就放这儿。
    #
    # 为什么值得三条断言：`ZH_MAP` 是**手写**的字表，而 Python 对字典字面量里
    # 重复的键**不报错**，后一个静默顶掉前一个。2026-10-17 查表时发现 7 个字被写了
    # 两遍（其中 6 个两个值不同）—— 先写的那条一辈子没生效过，读代码的人却以为它在生效。
    # 表本身已修成一字一值；这里钉住"不再长回来"，并顺带钉住旧值仍能推出同一个 slug。
    ok(len(mod.ZH_MAP) == 125,
       "the transliteration table has no shadowed duplicate keys", str(len(mod.ZH_MAP)))
    bad_vals = {k: v for k, v in mod.ZH_MAP.items()
                if not v or not v.isascii() or not v.islower() or not v.isalpha()}
    ok(not bad_vals, "every transliteration value is a plain lowercase ascii word", repr(bad_vals)[:200])
    ok(mod._zh_dup_keys('"边": "side", "边": "edge",') == ["边"],
       "the duplicate-key detector still fires on a table that repeats a key")
    ok(mod._zh_dup_keys('"边": "edge", "后": "then",') == [],
       "the detector stays quiet on a clean table")
    # 曾经被顶掉的那 6 个字，取值必须与**旧表实际生效**的那个一致：`slugify` 是 id 的来源，
    # 值一变，已经投出去的卡 id 就换了人（`wl/209` 那类回指会指到别的卡）。
    keep = {"复": "again", "件": "file", "禁": "gate", "边": "edge", "外": "exception", "后": "then"}
    moved = {k: (mod.ZH_MAP.get(k), v) for k, v in keep.items() if mod.ZH_MAP.get(k) != v}
    ok(not moved, "consolidating the table kept the value that used to win", repr(moved)[:200])
    ok(mod.slugify("复位之后的边件", "wl0001") == "wl0001-again-reset-then-edge-file",
       "the slug of a title using the merged characters is unchanged",
       mod.slugify("复位之后的边件", "wl0001"))
    ok(mod.slugify("…前导省略号不该让首段判重失效…", "wl0001").startswith("wl0001-"),
       "a title starting with an ellipsis still yields a prefixed slug")

    # ── 别把别人的 pointer 当自家卡（2026-10-17 补）────────────────────────────
    #
    # `*.pointer.md` 这个后缀不是本工具专有的：`memory-cards/` 里可能有别的工具投的卡
    # （灵枢插件自己也投）。从前一律当自家卡收进去 —— 外部卡会参与三道去重、还会在
    # slug 撞名时被当成冲突。判据换成"frontmatter 里有没有本工具写的那行标签"。
    # 这里放一张**外部卡**进卡目录，再跑一遍投影，钉三件事：不崩、不被当自家卡
    # （不会出现在复用统计里）、**一个字节都不被改**。
    foreign = os.path.join(cont, "memory-cards", "foreign.pointer.md")
    foreign_body = ("---\nid: foreign\nlayer: knowledge\ntags: [other-tool]\n---\n\n"
                    "# 功能名\n别的工具写的卡\n")
    write(foreign, foreign_body)
    r8 = run(croot, CONTAINER, "--all", "--write", "--project", "selftest-project", tool=tool)
    ok(r8.returncode == 0, "a foreign pointer in the card dir does not break the run",
       r8.stdout + r8.stderr)
    ok(read(foreign) == foreign_body,
       "and the run does not rewrite somebody else's card", read(foreign)[:200])
    ok("foreign" not in r8.stdout.replace("foreign.pointer.md", ""),
       "nor does it count as one of ours (only the skip notice may name it)",
       r8.stdout[-400:])
    # 自家卡照旧认得出来：上面那张是外部卡，而这一轮仍应把自己的卡当"已有卡"。
    ok(mod.existing_cards(os.path.join(cont, "memory-cards")) != [],
       "our own cards are still collected", str(len(mod.existing_cards(os.path.join(cont, "memory-cards")))))

    # ── **撞名**那种外来卡：不许覆盖（2026-10-17 复核 H-2）─────────────────────
    #
    # 上面那张叫 `foreign.pointer.md`，与自家任何 slug 都不撞 —— 读的一侧跳过它就完了。
    # 真正会出事的是**文件名一样**：读的一侧照旧打一行 `[skip]`，写的一侧却按同一个名字
    # `os.replace()`，于是"报着跳过、实际覆盖"。灵枢插件正是往同一个目录投同形制的卡，
    # 撞名是会发生的（卡可重建，所以不算 critical，但两句话自相矛盾是最坏的一种）。
    # 判据：外来卡逐字节不变 + 我们的卡改到 `-dsh` 名字下落盘 + 输出里说明白为什么。
    cards_dir_ = os.path.join(cont, "memory-cards")
    our_names = sorted(p for p in os.listdir(cards_dir_)
                       if p.endswith(".pointer.md") and mod.is_our_card(os.path.join(cards_dir_, p)))
    ok(bool(our_names), "there is at least one of our own cards to collide with", str(our_names)[:200])
    victim = our_names[0]
    victim_path = os.path.join(cards_dir_, victim)
    victim_body = ("---\nid: foreign-collide\nlayer: knowledge\ntags: [other-tool]\n---\n\n"
                   "# 功能名\n另一件工具写的卡，谁也不许动\n")
    write(victim_path, victim_body)
    r9 = run(croot, CONTAINER, "--all", "--write", "--project", "selftest-project", tool=tool)
    ok(read(victim_path) == victim_body,
       "a foreign card sitting on one of our names is not overwritten", read(victim_path)[:200])
    renamed = victim[: -len(".pointer.md")] + "-dsh.pointer.md"
    ok(os.path.isfile(os.path.join(cards_dir_, renamed)),
       "our card goes to a non-colliding name instead of over it", renamed)
    ok("不覆盖它" in r9.stdout, "and the run says so out loud", r9.stdout[-700:])

    # ── 轮六的三条 low：许可了却不做 / 说话不像人话 / 记错自己在哪（2026-10-17）──
    #
    # L-1：`--list-similar` 从前**只出现在 `--help` 里**（全文件没读过它），等于 `--help`
    #      许了一个不做的事。现在它是一条真路：只报相似度、**不写盘**。
    before = sorted(os.listdir(cards_dir_))
    r10 = run(croot, CONTAINER, "--all", "--list-similar", "--project", "selftest-project", tool=tool)
    ok(r10.returncode == 0, "--list-similar runs", r10.stdout + r10.stderr)
    ok("没出卡、没写盘" in r10.stdout, "and says out loud that it wrote nothing", r10.stdout[-600:])
    ok(sorted(os.listdir(cards_dir_)) == before, "and really writes nothing",
       str(sorted(set(os.listdir(cards_dir_)) ^ set(before))))

    # L-2：指到不存在的记录时给人话，不给回溯（从前是裸 `FileNotFoundError`，栈顶在 `read()`）。
    r11 = run(croot, CONTAINER, "--rec", "9999-nope.md", "--project", "selftest-project", tool=tool)
    ok(r11.returncode != 0, "a --rec that points nowhere fails", str(r11.returncode))
    ok("Traceback" not in r11.stderr, "without a Python traceback", r11.stderr[-300:])
    ok("找不到记录" in r11.stdout + r11.stderr,
       "but with a sentence a human can act on", (r11.stdout + r11.stderr)[-400:])

    # L-4：manifest 里的 `container` 从前恒是 `"."` —— 它写过 `relpath(container, card_dir)`，
    # 而卡目录就在容器里面，于是恒等。改成相对**容器父目录**（容器叫 `work_log` 就写 `work_log`）。
    man = json.loads(read(os.path.join(cards_dir_, ".projection-manifest.json")))
    ok(man.get("container") == CONTAINER,
       "the manifest names the container relative to its parent, not '.'",
       repr(man.get("container")))

    # ── 索引那条路也得认人（2026-10-17 轮七 H-2b）──────────────────────────────
    #
    # H-2 那一轮只收口了**两条**路：`existing_cards()` 认 tags（读入）、`avoid_foreign()`
    # 写盘前查一次（撞名）。第三条路漏了 —— `index_rows()` 从前只看后缀，于是
    # `--index-only --write` 会把 `source_status: stale` 写进**别人的卡**（实测 sha 变了），
    # 它们的行还会混进 INDEX 与"归属"统计（连"源找不到"都算在我们头上）。
    # 这里钉四件事：外来卡逐字节不变、不进 INDEX 行、我们的卡照旧进、
    # 且我们那张同样是脏源的卡**照样**被打 stale（别为了挡外人把自家也挡了）。
    fidx = os.path.join(tmp, "foreignidx")
    fcards = os.path.join(fidx, CONTAINER, "memory-cards")
    os.makedirs(fcards)

    def _raw_card(cid: str, tags: str, source: str) -> str:
        fm = f"---\nid: {cid}\nlayer: knowledge\ntags: [{tags}]\n"
        if source:
            fm += f"source: {source}\n"
        return (fm + "---\n\n"
                "## 功能名\n\n某功能\n\n## 执行\n\n先这样再那样。\n\n## 生效条件\n\n需要时。\n\n"
                "## 不适用条件\n\n不需要时。\n\n## 验证\n\n做一遍就知道。\n\n## 出处\n\n某处。\n")

    write(os.path.join(fcards, "wl900-ours-gone.pointer.md"),
          _raw_card("wl900-ours-gone", "dsh-lore, domain:general", f"{CONTAINER}/9999-gone.md"))
    write(os.path.join(fcards, "foreign-dangling.pointer.md"),
          _raw_card("foreign-dangling", "other-tool", f"{CONTAINER}/9998-nope.md"))
    write(os.path.join(fcards, "foreign-plain.pointer.md"),
          _raw_card("foreign-plain", "other-tool", ""))
    dangling_path = os.path.join(fcards, "foreign-dangling.pointer.md")
    dangling_before = read(dangling_path)
    r12 = run(fidx, CONTAINER, "--index-only", "--write", "--project", "selftest-project", tool=tool)
    ok(r12.returncode == 0, "--index-only --write runs on a dir with foreign cards",
       r12.stdout + r12.stderr)
    ok(read(dangling_path) == dangling_before,
       "a foreign card with a dangling source is not stamped stale", read(dangling_path)[:300])
    idx2 = read(os.path.join(fcards, "INDEX.md"))
    ok("foreign-dangling" not in idx2 and "foreign-plain" not in idx2,
       "foreign cards stay out of the index rows", idx2[:500])
    ok("wl900-ours-gone" in idx2, "while our own card is listed", idx2[:500])
    # 表头必须说清这是**谁的**张数（2026-10-17 轮八的观察）：不写清，
    # 看索引的人会把 `卡 N 张` 当成"目录里有几个文件"，而外来卡恰恰不在表里。
    ok("卡 1 张（只算本工具投的）" in idx2,
       "and the header says whose count it is (ours, not the directory's)", idx2[:400])
    ok("source_status: stale" in read(os.path.join(fcards, "wl900-ours-gone.pointer.md")),
       "and our own card with a dangling source is still stamped",
       read(os.path.join(fcards, "wl900-ours-gone.pointer.md"))[:300])
    ok("不收录进 INDEX" in r12.stderr,
       "the skip goes to stderr, same channel as existing_cards()", r12.stderr[-400:])

    # ── 同名目录不许让整次投影中止（2026-10-17 轮九）──────────────────────────
    #
    # 轮八给 `index_rows()` 加了 `isfile` 守卫，**兄弟路径没跟上**：一个叫
    # `zz-weird.pointer.md` 的**目录**（断链同理）会让 `existing_cards()` 的 `read()`
    # 抛 `PermissionError` —— 整次投影中止、rc=1、**stdout 为空**：用户看到的是一条裸栈，
    # 而不是"这张跳过了"。两个入口现在各钉一条。
    os.makedirs(os.path.join(fcards, "zz-weird.pointer.md"))
    r13 = run(fidx, CONTAINER, "--all", "--write", "--project", "selftest-project", tool=tool)
    ok(r13.returncode == 0, "a directory named like a card does not abort the whole projection",
       (r13.stdout + r13.stderr)[-500:])
    ok("Traceback" not in r13.stderr, "and it does not surface as a bare traceback",
       r13.stderr[-300:])
    r14 = run(fidx, CONTAINER, "--index-only", "--write", "--project", "selftest-project", tool=tool)
    ok(r14.returncode == 0 and "zz-weird" not in read(os.path.join(fcards, "INDEX.md")),
       "nor does the index path list it", read(os.path.join(fcards, "INDEX.md"))[:400])

    # ── 分册目录里也有同一个形状（2026-10-17 轮十）────────────────────────────
    #
    # 三处枚举点要过**同一道** `isfile`：卡目录的两处（`existing_cards()` / `index_rows()`）
    # 前两轮补过了，而 `--all` 那条路上的**分册扫描**（`for fn in os.listdir(les_dir)`）
    # 只是按 `.md` 后缀收 —— 一个叫 `01-weird.md` 的目录照样让 `--all --write`
    # 整次中止（rc=1、裸 `PermissionError`）。轮十的穷举扫描漏了它。
    ldir = os.path.join(fidx, CONTAINER, "lessons")
    os.makedirs(os.path.join(ldir, "01-weird.md"))
    write(os.path.join(ldir, "02-ok.md"),
          "# 分册\n\n- **一条能用的经验**：正文化，句号收尾。出处：`wl/0001`。\n")
    r15 = run(fidx, CONTAINER, "--all", "--write", "--project", "selftest-project", tool=tool)
    ok(r15.returncode == 0,
       "a directory named like a lesson volume does not abort the projection",
       (r15.stdout + r15.stderr)[-500:])
    ok("Traceback" not in r15.stderr, "and it does not surface as a bare traceback",
       r15.stderr[-300:])


def lesson_phase(parent: str) -> None:
    """卡式经验条目：三个 CLI 字段、2 空格缩进、dry-run 一致、CRLF，以及 `check` 的配对形制。

    为什么单独一相：`lesson add` 的旧断言内联在 `main()` 里，变异驱动跑不到（见
    reverse-verify 的「起飞前检查」）。这一相把卡式形制的四条断言收进可执行的函数，
    `PHASES` 里登记 `lesson` 之后才有"没见它红过不算数"的资格。
    """
    proj = os.path.join(parent, "lessoncard")
    os.makedirs(os.path.join(proj, CONTAINER, "lessons"))
    write(os.path.join(proj, CONTAINER, "README.md"),
          fmt_ledger(["0001-work.md"], status="2026-09-20"))
    write(os.path.join(proj, CONTAINER, "0001-work.md"),
          entry("0001", "work", "2026-09-20", "1"))
    write(os.path.join(proj, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    vol_path = os.path.join(proj, CONTAINER, "lessons", "01-topic.md")
    write(vol_path, "# 01 · T\n\n来源：wl/0001。\n\n## 子主题\n\n"
                    "- **s**：a。根因：b。做法：c。（`wl/0001`）\n")

    # 1) 三个字段 → 主行 + 三条缩进 2 空格的子条目（`--avoid` 重复用「；」连接） -----
    r = run(proj, "lesson", "add", "--volume", "01-topic.md", "--source", "1",
            "--text", "样式会被认领",
            "--trigger", "改完 lib/client.js，邻居界面丢样式",
            "--verify", "无主 style 计数为 0",
            "--avoid", "写成 data-plugin-css（不在宿主判据里）",
            "--avoid", "改别人的 style 标签（要写死别人的 id）")
    ok(r.returncode == 0, "lesson add with card flags exits 0", r.stdout + r.stderr)
    vol = read(vol_path)
    lines = vol.splitlines()
    ok("- 样式会被认领（`wl/0001`）" in lines,
       "lesson add keeps the source citation on the main line", vol)
    ok("  - 触发：改完 lib/client.js，邻居界面丢样式" in lines,
       "lesson add writes the 触发 sub-item with a 2-space indent", vol)
    ok("  - 验证：无主 style 计数为 0" in lines,
       "lesson add writes the 验证 sub-item with a 2-space indent", vol)
    ok("  - 别再来：写成 data-plugin-css（不在宿主判据里）；改别人的 style 标签（要写死别人的 id）" in lines,
       "repeated --avoid values are joined with 全角分号", vol)

    # 2) 不传卡式参数 → 输出与旧行为一致（只有主行，引用照样补上） ------------------
    r = run(proj, "lesson", "add", "--volume", "01-topic.md", "--source", "1",
            "--text", "旧形状")
    vol = read(vol_path)
    ok(r.returncode == 0 and "- 旧形状（`wl/0001`）" in vol.splitlines(),
       "lesson add without card flags still appends the legacy one-liner", vol)
    ok("  - 触发：旧形状" not in vol, "no card sub-items are invented when no flags are given", vol)

    # 3) `--dry-run`：不写盘，且打印的载荷与真实写入逐字一致 ----------------------
    before = read(vol_path)
    card_args = ("lesson", "add", "--volume", "01-topic.md", "--source", "1",
                 "--text", "卡二", "--trigger", "t2", "--verify", "v2")
    r = run(proj, *card_args, "--dry-run")
    ok(read(vol_path) == before, "lesson add --dry-run leaves the volume unchanged",
       read(vol_path)[-300:])
    printed = r.stdout.split("\n", 1)[1].strip() if "\n" in r.stdout else ""
    run(proj, *card_args)
    appended = read(vol_path)[len(before):].strip()
    # 比**行内容**，不比换行风格：Windows 的 `print` 会把 `\n` 翻成 `\r\n`，
    # 而文件里是 `nl_of()` 决定的换行 —— 拿 stdout 的字节直接和文件字节比，
    # 验的其实是控制台翻译层，不是本命令的载荷。缩进与中文标点仍逐字比。
    ok(bool(printed) and printed.splitlines() == appended.splitlines(),
       "the --dry-run payload is line-for-line identical to what a real write appends",
       f"printed={printed!r} appended={appended!r}")

    # 4) CRLF 保真：写入的那几行也不许把整份文件改成 LF ---------------------------
    write(vol_path, read(vol_path).replace("\n", "\r\n"))
    r = run(proj, "lesson", "add", "--volume", "01-topic.md", "--source", "1",
            "--text", "crlf卡", "--trigger", "t3", "--verify", "v3")
    raw = read_bytes(vol_path)
    ok(r.returncode == 0 and b"\r\n" in raw,
       "lesson add keeps a CRLF volume CRLF", raw[-300:])
    ok(raw.replace(b"\r\n", b"").count(b"\n") == 0,
       "lesson add introduces no lone LF into a CRLF volume", raw[-300:])

    # 5) 来源校验不因卡式参数而放松 ---------------------------------------------
    r = run(proj, "lesson", "add", "--volume", "01-topic.md", "--source", "999",
            "--text", "bad", "--trigger", "t", "--verify", "v")
    ok(r.returncode != 0, "lesson add still rejects an unknown source with card flags",
       r.stdout + r.stderr)

    # 5b) 空白 / 多行卡式值：落盘前拒绝（审查 M2 / L2）---------------------------
    before = read(vol_path)
    r = run(proj, "lesson", "add", "--volume", "01-topic.md", "--source", "1",
            "--text", "空白触发", "--trigger", "   ")
    ok(r.returncode != 0, "lesson add rejects a whitespace-only --trigger", r.stdout + r.stderr)
    ok(read(vol_path) == before, "and it writes nothing when the card value is blank",
       read(vol_path)[-200:])
    r = run(proj, "lesson", "add", "--volume", "01-topic.md", "--source", "1",
            "--text", "多行验证", "--trigger", "t", "--verify", "a\nb")
    ok(r.returncode != 0, "lesson add rejects a multi-line --verify", r.stdout + r.stderr)
    ok(read(vol_path) == before, "and it writes nothing when the card value has a newline",
       read(vol_path)[-200:])
    # `splitlines()` 还认 U+2028 / VT 这些；只查 CR/LF 会让它们漏过去（复核 nit）。
    r = run(proj, "lesson", "add", "--volume", "01-topic.md", "--source", "1",
            "--text", "分隔符触发", "--trigger", "a\u2028b")
    ok(r.returncode != 0, "lesson add rejects U+2028 inside a card value", r.stdout + r.stderr)
    ok(read(vol_path) == before, "and it writes nothing when the separator is U+2028",
       read(vol_path)[-200:])
    r = run(proj, "lesson", "add", "--volume", "01-topic.md", "--source", "1",
            "--text", "只有反面", "--avoid", "只给反面（没有触发/验证）")
    ok(r.returncode == 0 and "  - 别再来：只给反面（没有触发/验证）" in read(vol_path),
       "a lone --avoid is allowed (it is not part of the pairing rule)", read(vol_path)[-300:])

    # 6) `check` 的形制检查：只认缩进子条目，且触发 / 验证必须**按条目**成对 ------
    cproj = os.path.join(parent, "cardcheck")
    os.makedirs(os.path.join(cproj, CONTAINER, "lessons"))
    write(os.path.join(cproj, CONTAINER, "README.md"),
          fmt_ledger(["0001-work.md"], status="2026-09-20"))
    write(os.path.join(cproj, CONTAINER, "0001-work.md"),
          entry("0001", "work", "2026-09-20", "1"))
    write(os.path.join(cproj, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(cproj, CONTAINER, "lessons", "01-topic.md"),
          "# 01 · T\n\n- **成对**：x。（`wl/0001`）\n  - 触发：t\n  - 验证：v\n")
    write(os.path.join(cproj, CONTAINER, "lessons", "02-trig.md"),
          "# 02 · T\n\n- **缺一半**：x。（`wl/0001`）\n  - 触发：只有触发\n")
    write(os.path.join(cproj, CONTAINER, "lessons", "03-verify.md"),
          "# 03 · T\n\n- **缺另一半**：x。（`wl/0001`）\n  - 验证：只有验证\n")
    write(os.path.join(cproj, CONTAINER, "lessons", "04-old.md"),
          "# 04 · T\n\n- **旧条**：x。（`wl/0001`）\n  - **触发条件（最容易忽略的一条）**：y。\n")
    # 05：同一份分册里「完整卡 + 半边卡」。按整份文件 `search` 的实现会静默放行（M1）。
    mixed = ("# 05 · T\n\n- **完整**：x。（`wl/0001`）\n  - 触发：t\n  - 验证：v\n\n"
             "- **半边**：y。（`wl/0001`）\n  - 触发：只有触发\n")
    write(os.path.join(cproj, CONTAINER, "lessons", "05-mixed.md"), mixed)
    # 06：围栏代码块里的示例不是条目，别报 WARN。
    write(os.path.join(cproj, CONTAINER, "lessons", "06-fence.md"),
          "# 06 · T\n\n```markdown\n- **示例**：x。（`wl/0001`）\n  - 触发：示例里的触发\n```\n")
    # 07：星号列表写的半边卡也要被认出来（只认顶格 `-` 的实现会把它并进上一条）。
    write(os.path.join(cproj, CONTAINER, "lessons", "07-star.md"),
          "# 07 · T\n\n* **星号半边**：x。（`wl/0001`）\n  - 触发：只有触发\n")
    # 08：单 tab 缩进与 2 空格同权（check 与投影器用同一条判据）。
    write(os.path.join(cproj, CONTAINER, "lessons", "08-tab.md"),
          "# 08 · T\n\n- **tab 卡**：x。（`wl/0001`）\n\t- 触发：t\n\t- 验证：v\n")
    r = run(cproj, "check")
    ok(r.returncode == 0, "check passes when a card misses one half (it is only a WARN)",
       r.stdout)
    ok("02-trig.md" in r.stdout and "条目有 `触发：` 却缺 `验证：`" in r.stdout,
       "check warns when a card has 触发 but no 验证", r.stdout)
    ok("03-verify.md" in r.stdout and "条目有 `验证：` 却缺 `触发：`" in r.stdout,
       "check warns in the other direction too", r.stdout)
    ok("05-mixed.md" in r.stdout,
       "a half card is caught even when the same volume also has a complete card (M1)",
       r.stdout)
    half_line = mixed.splitlines().index("- **半边**：y。（`wl/0001`）") + 1
    ok(f"第 {half_line} 行起的条目有 `触发：` 却缺 `验证：`" in r.stdout,
       "the warning names the line where the offending entry starts", r.stdout)
    ok("06-fence.md" not in r.stdout,
       "a fenced example is not treated as an entry", r.stdout)
    ok("07-star.md" in r.stdout,
       "a star-bullet half card is still caught", r.stdout)
    ok("08-tab.md" not in r.stdout,
       "a single-tab indent counts as a card indent (same rule as the projector)", r.stdout)
    ok("04-old.md" not in r.stdout,
       "the old-style 触发条件 sub-item is not mistaken for the card format", r.stdout)
    ok("01-topic.md" not in r.stdout,
       "a complete card is not flagged", r.stdout)
    r = run(cproj, "check", "--strict")
    ok(r.returncode != 0 and "条目有 `触发：` 却缺 `验证：`" in r.stdout,
       "check --strict turns the card WARN into an ERROR", r.stdout)


def main() -> int:
    ap = argparse.ArgumentParser(description="journal.py 自测")
    ap.add_argument("--root", default=None,
                    help="夹具父目录（必须已存在且可写）；默认用系统临时目录")
    ap.add_argument("--keep", action="store_true", help="跑完保留夹具目录")
    args = ap.parse_args()

    if args.root:
        base = os.path.abspath(args.root)
        if not os.path.isdir(base):
            print(f"ERROR: --root 不是一个已存在的目录：{base}")
            return 2
        tmp = os.path.join(base, f"journal-selftest-{os.getpid()}")
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        # 受限沙箱下，进程可能连自己刚建的父目录都写不进去；早失败、给准话。
        probe = os.path.join(tmp, ".write-probe")
        try:
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
            os.remove(probe)
        except OSError as exc:
            print(f"ERROR: --root 目录不可写：{tmp}（{exc}）")
            return 2
    else:
        tmp = make_tmp(prefix="journal-selftest-")
    try:
        os.makedirs(os.path.join(tmp, CONTAINER, "lessons"))
        write(os.path.join(tmp, CONTAINER, "README.md"), INDEX)
        write(os.path.join(tmp, CONTAINER, "0001-seed.md"), SEED)
        write(os.path.join(tmp, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
        write(os.path.join(tmp, CONTAINER, "lessons", "01-topic.md"), VOLUME)

        # 新布局：容器根放台账与记录、lessons/ 是容器子目录 -----------------
        ok(os.path.isdir(os.path.join(tmp, CONTAINER, "lessons")),
           "lessons/ is a subdirectory of the container")
        ok(os.path.isfile(os.path.join(tmp, CONTAINER, "README.md"))
           and os.path.isfile(os.path.join(tmp, CONTAINER, "0001-seed.md")),
           "the container root holds the ledger and the records")
        r = run(tmp, "outline")
        ok("01-topic" not in r.stdout and "01-topic" not in r.stderr,
           "a lessons volume is never listed as a record", r.stdout + r.stderr)

        # <容器>/logs/ 里的文件名与记录同形（`2026-01-01-run.md`），但**不是记录**。
        # 注意是容器**自己的** `logs/`（`<容器>/logs/`），不是 `<容器>/work_log/logs/` ——
        # 后者会造出一个嵌套的 `work_log/`，让这条断言在错误的路径上通过（2026-10-15 修正）。
        os.makedirs(os.path.join(tmp, CONTAINER, "logs", "build"))
        write(os.path.join(tmp, CONTAINER, "logs", "build", "2026-01-01-run.md"),
              "# 构建日志\n\n构建于 2026-01-01，产物见项目根的 dist/。\n")
        r = run(tmp, "outline")
        ok(r.stdout.count("\n") == 1 and "2026-01-01" not in r.stdout,
           "a <container>/logs/ file shaped like a record is not read as one", r.stdout)

        numbering_phase(tmp)

        # new --insert -----------------------------------------------------
        r = run(tmp, "new", "--title", "Add login rate limit", "--iter", "12",
                "--date", "2026-09-14", "--insert", "--stage", "A. 起步")
        ok(r.returncode == 0, "new --insert exits 0", r.stderr)
        entry = os.path.join(tmp, CONTAINER, "0002-add-login-rate-limit.md")
        ok(os.path.exists(entry), "new --insert created 0002 at the container root")
        idx = read(os.path.join(tmp, CONTAINER, "README.md"))
        ok("0002-add-login-rate-limit.md" in idx, "index row auto-inserted")

        # index sync idempotent -------------------------------------------
        r = run(tmp, "index", "sync")
        ok(r.returncode == 0 and "已覆盖" in r.stdout, "index sync idempotent", r.stdout + r.stderr)

        # brief / outline / show / search ---------------------------------
        r = run(tmp, "brief", "--entries", "2", "--width", "120")
        ok(r.returncode == 0 and "BRIEF" in r.stdout and "Add login rate limit" in r.stdout,
           "brief shows recent entry", r.stdout)
        ok(len(r.stdout) < 2000, "brief stays compact", f"{len(r.stdout)} chars")
        r = run(tmp, "outline")
        ok(r.returncode == 0 and "0002" in r.stdout and "Add login rate limit" in r.stdout, "outline runs", r.stdout)
        ok(r.stdout.count("\t") >= 4, "outline has 5 columns")
        r = run(tmp, "show", "2")
        ok("Add login rate limit" in r.stdout and "sections:" in r.stdout, "show prints outline", r.stdout)
        r = run(tmp, "search", "rate limit")
        ok(r.returncode == 0 and "0002" in r.stdout, "search finds entry", r.stdout)

        # 纯中文标题：文件名退化为 `<篇号>.md`，而且仍能被识别与索引 --------
        cjk = os.path.join(tmp, "cjkfix")
        os.makedirs(os.path.join(cjk, CONTAINER))
        write(os.path.join(cjk, CONTAINER, "README.md"),
              "# C\n\n## 文件索引\n\n### A. 起步\n\n| 文件 | 方面 |\n|---|---|\n\n"
              "## 待办（滚动清单）\n\n- [ ] x\n\n## 当前状态（2026-09-15）\n\n- 阶段 / 版本：v1\n")
        r = run(cjk, "new", "--title", "第三轮用户访谈结论", "--iter", "3",
                "--date", "2026-09-15", "--insert", "--stage", "A. 起步")
        ok(r.returncode == 0, "new accepts a pure-CJK title", r.stdout + r.stderr)
        bare = os.path.join(cjk, CONTAINER, "0001.md")
        ok(os.path.exists(bare), "a pure-CJK title yields <num>.md, not <num>-entry.md", r.stdout)
        r = run(cjk, "outline")
        ok("0001" in r.stdout and "第三轮用户访谈结论" in r.stdout,
           "a bare-numbered entry is recognised", r.stdout)
        r = run(cjk, "check", "--strict", "--quiet")
        ok(r.returncode == 0, "the bare-numbered entry passes check --strict", r.stdout + r.stderr)
        r = run(tmp, "search", "[", "--regex")
        ok(r.returncode == 2 and "ERROR" in r.stdout, "search rejects an invalid regex cleanly",
           r.stdout + r.stderr[:200])
        ok("Traceback" not in r.stderr, "invalid regex does not traceback", r.stderr[:200])
        r = run(tmp, "brief", "--width", "0")
        ok(r.returncode == 0 and "BRIEF" in r.stdout, "brief survives --width 0", r.stdout[:120])

        # status -----------------------------------------------------------
        r = run(tmp, "status", "--set", "分支 / HEAD=main @ abc123", "--set", "测试=312 PASS", "--date", "2026-09-14")
        ok(r.returncode == 0, "status --set exits 0", r.stderr)
        idx = read(os.path.join(tmp, CONTAINER, "README.md"))
        ok("分支 / HEAD：main @ abc123" in idx and "测试：312 PASS" in idx, "status values updated")
        ok("## 当前状态（2026-09-14）" in idx, "status date updated")
        ok(idx.count("## 当前状态") == 1, "still exactly one status block")
        r = run(tmp, "status")
        ok("main @ abc123" in r.stdout, "status prints block")

        # status --set：短名要落到规范字段上，而不是新增一个平行字段 --------------
        # 用一个只含规范字段的独立夹具，避免依赖上面那个迷你项目的字段集。
        sdir = os.path.join(tmp, "statusfix")
        os.makedirs(os.path.join(sdir, CONTAINER))
        write(os.path.join(sdir, CONTAINER, "README.md"), CANON_INDEX)
        r = run(sdir, "status", "--set", "核对=抽样 30 条全部通过",
                "--set", "交付物=app.zip", "--set", "阶段=v2")
        ok(r.returncode == 0, "status --set accepts short field names", r.stderr)
        sidx = read(os.path.join(sdir, CONTAINER, "README.md"))
        ok("- 核对 / 验证：抽样 30 条全部通过" in sidx, "short name 核对 lands on 核对 / 验证", sidx)
        ok("- 交付物与指纹：app.zip" in sidx, "short name 交付物 lands on 交付物与指纹", sidx)
        ok("- 阶段 / 版本：v2" in sidx, "short name 阶段 lands on 阶段 / 版本", sidx)
        sfields = [l for l in sidx.splitlines() if l.startswith("- ") and "：" in l]
        ok(len(sfields) == 7, "canonical status block keeps exactly 7 fields", f"{sfields}")
        ok("(新增)" not in r.stdout, "short names appended no field", r.stdout)
        r = run(sdir, "status", "--set", "对不上的字段=x")
        ok("(新增)" in r.stdout and "- 对不上的字段：x" in read(os.path.join(sdir, CONTAINER, "README.md")),
           "an unknown field name is still appended", r.stdout)

        # 台账末行没有换行时，--set 不能把新字段拼到上一行 ---------------
        idx_path = os.path.join(sdir, CONTAINER, "README.md")
        write(idx_path, read(idx_path).rstrip("\r\n"))
        r = run(sdir, "status", "--set", "环境=py3.14")
        ok(r.returncode == 0, "status --set works on a ledger without a trailing newline", r.stderr)
        sidx = read(idx_path)
        ok("- 环境：py3.14" in sidx.splitlines(), "new field starts on its own line", sidx)
        ok("：py3.14" not in sidx.replace("- 环境：py3.14", ""), "new field did not glue onto the previous line", sidx)

        # todo -------------------------------------------------------------
        run(tmp, "todo", "--add", "ship the thing")
        r = run(tmp, "todo", "--done", "ship the thing")
        ok(r.returncode == 0, "todo --done exits 0", r.stdout + r.stderr)
        idx = read(os.path.join(tmp, CONTAINER, "README.md"))
        ok("- [x] ship the thing" in idx, "todo marked done")
        r = run(tmp, "todo", "--drop-done")
        ok("- [x] ship the thing" not in read(os.path.join(tmp, CONTAINER, "README.md")), "todo --drop-done works")
        # 多行待办：删勾选行时必须**连带缩进续行**（否则续行留下变孤儿，2026-10-18 实测）
        run(tmp, "todo", "--add", "multi line todo")
        idx_path = os.path.join(tmp, CONTAINER, "README.md")
        write(idx_path, read(idx_path).replace(
            "- [ ] multi line todo",
            "- [ ] multi line todo\n  continuation line of the todo\n  another continuation"))
        run(tmp, "todo", "--done", "multi line todo")
        r = run(tmp, "todo", "--drop-done")
        ok("continuation line of the todo" not in read(idx_path),
           "todo --drop-done removes the indented continuation lines too", r.stdout)

        # append -----------------------------------------------------------
        r = run(tmp, "append", "2", "--section", "更正", "--text", "2026-09-14: changed mind", "--bullet")
        ok(r.returncode == 0 and "## 更正" in read(entry), "append creates section", r.stderr)
        r = run(tmp, "append", "2", "--section", "更正", "--text", "second note", "--bullet")
        ok(read(entry).count("## 更正") == 1 and "- second note" in read(entry),
           "append reuses existing section", r.stderr)

        # lesson add -------------------------------------------------------
        r = run(tmp, "lesson", "add", "--volume", "01-topic.md", "--source", "2",
                "--topic", "子主题", "--text", "**429 storm**：x。根因：y。做法：z")
        ok(r.returncode == 0 and "wl/0002" in read(os.path.join(tmp, CONTAINER, "lessons", "01-topic.md")),
           "lesson add appends with citation", r.stderr)
        r = run(tmp, "lesson", "add", "--volume", "01-topic.md", "--source", "999", "--text", "bad")
        ok(r.returncode != 0, "lesson add rejects unknown source", r.stdout)

        # analysis / generation -------------------------------------------
        for argv, needle in ((("stats",), "compliance"), (("digest",), "交接摘要"),
                             (("topics", "--keywords", "seed"), "seed:"),
                             (("retro", "--from", "1", "--to", "2"), "阶段复盘"),
                             (("export",), '"num"')):
            r = run(tmp, *argv)
            ok(r.returncode == 0 and needle in r.stdout, f"{argv[0]} runs", r.stdout + r.stderr)

        # lint: placeholder present, then cleaned -------------------------
        r = run(tmp, "lint")
        ok("占位符" in r.stdout, "lint flags template placeholder", r.stdout)
        text = read(entry)
        text = text.replace("- 方式：`<命令 / 数据 / 引用 / 样本>`", "- 方式：`pytest -q`").replace(
            "- 结果：", "- 结果：312 passed").replace("结论：", "结论：312 项测试全绿")
        text = text.replace("## 一、背景与事实核查\n\n## 二、方案与取舍",
                            "## 一、背景与事实核查\n\nneed\n\n## 二、方案与取舍\n\nchoice")
        write(entry, text)

        # 领域无关：非编程记录（批次别名 + 结果小节 + 数据）-----------------
        write(os.path.join(tmp, CONTAINER, "0003-research-note.md"), RESEARCH)
        r = run(tmp, "index", "sync")
        ok("0003" in r.stdout, "index sync picks up non-coding entry", r.stdout)
        run(tmp, "status", "--date", "2026-09-15")   # 新记录带来更新的日期，台账要跟上
        r = run(tmp, "outline")
        ok("0003\t2026-09-15\t3\t" in r.stdout, "outline reads \u201c批次\u201d alias", r.stdout)
        r = run(tmp, "check", "--strict", "--quiet")
        ok(r.returncode == 0, "check --strict clean (coding + non-coding)", r.stdout + r.stderr)
        r = run(tmp, "lint", "--strict")
        ok(r.returncode == 0, "lint clean (coding + non-coding)", r.stdout + r.stderr)

        # A/B/C/D 整理能力（独立夹具，避免干扰上面的用例）---------------------------
        cleanup_phase(tmp)

        # 多级归档与 index compact --depth（2026-10-14）
        nested_stage_phase(tmp)
        archive_index_check(tmp)
        archive_dir_index_phase(tmp)
        status_blocks_phase(tmp)

        # 跨语言解析：英文标签（P1）-----------------------------------------
        english_phase(tmp)

        # 文档一致性：模板落盘后要能被自己的门禁接受 ------------------------
        doc_phase(tmp)

        # 数据安全与幂等 ----------------------------------------------------
        safety_phase(tmp)

        # 旧布局只读回退（journal/ + 顶层 lessons/）--------------------------
        legacy_phase(tmp)

        # 记录精细度（默认档 / 切换 / 验证不变量 / 老台账不受影响）------------
        mode_phase(tmp)

        # 两种命名 + 放宽后的格式 + 实质验证 + 渐进原则 + snapshot -------------
        format_phase(tmp)

        # 两道门禁：check --lint 会合并，默认不合并 ---------------------------
        gate_phase(tmp)

        # 链接目标的三种写法（裸 / 尖括号 / %转义）走同一套解析 ----------------
        link_phase(tmp)

        # 项目配置文件（<容器>/.config.json）---------------------------------
        config_phase(tmp)

        # 卡式经验条目（三字段 / 缩进 / dry-run / CRLF / check 配对）------------
        lesson_phase(tmp)

        # 目标文件（<容器>/目标.md，可选）------------------------------------
        goals_phase(tmp)

        # 审查报告 §附录那几条：判据先行的常驻断言 ---------------------------
        appendix_phase(tmp)

        # 第二轮审查（2026-10-15）CLI 侧：N5 四条 + F8 的根因 ----------------
        review2_phase(tmp)

        # 全局记忆（跨工作区：分档 / 清单 / 收集 / 索引 / 门禁 / 收敛 / 信箱 / 升格）--
        memory_phase(tmp)

        # 记忆卡投影（体量闸 / 幂等 / 索引 / 归属 / 不依赖灵枢）----------------
        card_phase(tmp)

        # CRLF fidelity ----------------------------------------------------
        index_path = os.path.join(tmp, CONTAINER, "README.md")
        before = read(index_path).replace("\n", "\r\n")
        write(index_path, before)
        snapshot = read_bytes(index_path)
        r = run(tmp, "status", "--set", "测试=999 PASS")
        after = read_bytes(index_path)
        ok(r.returncode == 0, "status --set on CRLF file exits 0", r.stderr)
        ok(b"\r\n" in after, "CRLF preserved")
        ok(after.replace(b"\r\n", b"").count(b"\n") == 0, "no lone LF introduced")
        changed = [i for i, (a, b) in enumerate(zip(snapshot.split(b"\r\n"), after.split(b"\r\n"))) if a != b]
        ok(len(changed) == 1 and b"999 PASS" in after.split(b"\r\n")[changed[0]],
           "only the target line changed", f"changed lines={changed}")
    finally:
        if args.keep:
            print(f"夹具保留在：{tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    # 文档里若写了当前自测规模（"共 N 项" / "N/N 通过"），必须等于真正跑过的
    # 断言数。历史叙述（"由 34 项增至 57 项"）不在此列——所以只认下面两种写法。
    # 放在这里是因为只有跑完才知道总数；在 doc_phase 里数等于自指。
    total_ran = len(results)
    docs = [os.path.join(os.path.dirname(HERE), "SKILL.md"),
            os.path.join(os.path.dirname(HERE), "references", "analysis.md"),
            os.path.join(os.path.dirname(HERE), "references", "commands.md")]
    for path in docs:
        if not os.path.isfile(path):
            continue
        text = read(path)
        claims = set()
        for pattern in (r"共\s*(\d+)\s*项", r"(\d+)\s*项\s*(?:通过|passed)",
                        r"(\d+)\s*/\s*(\d+)\s*(?:通过|passed)"):
            for m in re.finditer(pattern, text):
                for g in m.groups():
                    if g is not None:
                        claims.add(int(g))
        for claimed in sorted(claims):
            ok(claimed == total_ran,
               f"{os.path.basename(path)} quotes the current self-test count",
               f"says {claimed}, ran {total_ran}")

    failed = [label for good, label in results if not good]
    # 跳过单独报：`N/N passed` 这句话必须自带"其中几条其实没验"的注解（审查报告 F13）。
    tail = f"（{len(skipped)} 条跳过，未计入）" if skipped else ""
    print(f"\n{len(results) - len(failed)}/{len(results)} passed{tail}")
    for label in skipped:
        print(f"      SKIPPED: {label}")
    return 1 if failed else 0


def read(path: str) -> str:
    """读文本；**文件不在**时返回空串（与 `read_bytes` 同一个理由，见那里）。

    这样"文件没写出来"会走成"内容对不上"→ 断言变红，而不是在**调用点**抛异常把整相带走
    （变异驱动把这种情况记成"相跑崩"，于是那条变异反而不构成证据）。除"不在"之外的
    OS 错误照旧抛 —— 不把权限之类的真问题静音掉。
    """
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.read()
    except (FileNotFoundError, IsADirectoryError):
        return ""


def read_bytes(path: str) -> bytes:
    """读字节；文件不在时返回空字节。

    为什么不能直接抛：`before_bytes = read_bytes(cfg_path)` 这种写法在
    "配置文件本该被创建、变异让它没被创建"时会抛 FileNotFoundError，异常发生在
    记下断言之前 → 整相结束。判据不放松：空字节与真实内容不相等，断言该红还是红。
    """
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except (FileNotFoundError, IsADirectoryError):
        return b""


def write(path: str, text: str) -> None:
    # 父目录不在就先建：自测里的 write 基本都发生在**被测命令本该建好目录**之后，
    # 变异让目录没建出来时，`open(..., "w")` 会抛 FileNotFoundError 并把整相带走
    # （2026-10-14：`promote scaffold --out` 那条路就是这样崩的）。
    # 建目录不改变判定：文件写下去了，后面的断言照样能看出"被测命令没建目录"。
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


if __name__ == "__main__":
    sys.exit(main())
