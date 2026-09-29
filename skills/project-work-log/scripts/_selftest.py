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
import importlib.util
import json
import os
import re
import shutil
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


def run(root: str, *argv: str) -> subprocess.CompletedProcess:
    # 项目根默认取 cwd；journal/ 与 lessons/ 名字走默认解析
    return subprocess.run([sys.executable, TOOL, *argv],
                          cwd=root, capture_output=True, text=True, encoding="utf-8")


def ok(cond: bool, label: str, detail: str = "") -> None:
    results.append((bool(cond), label))
    print(("PASS  " if cond else "FAIL  ") + label + (f"   [{detail[:200]}]" if detail and not cond else ""))


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
    ok(os.path.exists(os.path.join(tmp, CONTAINER, "ARCHIVE.md")),
       "archive writes the archive index at the container root")
    ok(not os.path.isdir(os.path.join(tmp, CONTAINER, "archive")),
       "no literal archive/ subdirectory is created")

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
    ok(json.loads(read(cfg_path)) == {"mode": "full", "container": CONTAINER,
                                      "lessons": "lessons", "legacy": [], "snapshotEntries": 12},
       "config --write records the current effective values", read(cfg_path))
    before_bytes = read_bytes(cfg_path)
    r = run(proj, "config", "--write")
    ok(r.returncode != 0 and "已存在" in r.stdout,
       "config --write refuses to clobber an existing file", r.stdout)
    ok(read_bytes(cfg_path) == before_bytes,
       "config --write (refused) leaves the file byte-identical")
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
    ok(len(changed) == 1 and b'"digest"' in after_bytes.split(b"\r\n")[changed[0]],
       "config --set changes only the target line", f"changed lines={changed}")
    data = json.loads(read(cfg_path))
    ok(data["mode"] == "digest" and data["legacy"] == ["0003-*"] and data["snapshotEntries"] == 2
       and data["lessons"] == "lessons",
       "config --set keeps every other field (and normalises 摘要 to digest)", str(data))
    ok("mode=digest" in r.stdout, "config --set reports what it wrote", r.stdout)

    # 一次改两个字段也认
    r = run(proj, "config", "--set", "snapshotEntries=5", "--set", "legacy=0001-*,0002-*")
    data = json.loads(read(cfg_path))
    ok(r.returncode == 0 and data["snapshotEntries"] == 5 and data["legacy"] == ["0001-*", "0002-*"],
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
    return subprocess.run([sys.executable, TOOL, *argv],
                          cwd=root, capture_output=True, text=True, encoding="utf-8", env=e)


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
    """隔离包装：整相把 `DSH_HOME` 指进夹具，再跑 `_memory_phase`。

    **为什么只靠 `--memory` 与 `$DSH_WORKLOG_MEMORY` 不够**：记忆根是三级解析
    （`--memory` > `$DSH_WORKLOG_MEMORY` > `$DSH_HOME/memory`），而这一相里前两档
    **都被专门测过** —— 变异驱动正是拿它们开刀：`reverse-verify.py` 的 memory 相里
    「`--memory` 不再覆盖路径」与「环境变量那一档失效」两条，就是把前两档打断。
    两条一断，兜底就落到**用户真实的** `~/.dsh/memory`。2026-09-28 真发生过：
    真实记忆库里留下 8 条 `wsA` 夹具条目，并且被注入了每个请求（清理记录见 `work_log/0051`）。
    `DSH_HOME` 在那两条变异之外，所以拿它兜底 —— 变异要红的那两条断言都是**进程内**比对，
    不受这里影响。
    """
    saved_home = os.environ.get("DSH_HOME")
    os.environ["DSH_HOME"] = os.path.join(parent, "home")
    try:
        _memory_phase(parent)
    finally:
        if saved_home is None:
            os.environ.pop("DSH_HOME", None)
        else:
            os.environ["DSH_HOME"] = saved_home


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
       "memory: 不给 --memory 时落在 <DSH_HOME>/memory", JOURNAL.memory_root())
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
       "memory: 索引第一行自证是生成物（手写就会分叉）", idx.splitlines()[0])
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
    read_block = [b for b in orig_vol.split("\n\n") if "id: read-ok" in b][0]
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
    ok(os.path.getsize(os.path.join(cap, JOURNAL.MEMORY_INDEX_NAME)) > 0,
       "memory: 而且索引照写完整 —— 报错不等于截断")
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
    state = JOURNAL.load_state(mem_days)
    state["usage"]["proc-demo"]["days"] = ["2026-09-01", days_now[0]]
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
    r = subprocess.run([sys.executable, os.path.join(scaffold_out, "selftest.py")],
                       capture_output=True, cwd=scaffold_out)
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

    # --- 11) inbox：原子写 / 上限 / 转移为记录 -----------------------------
    inbox = JOURNAL.memory_inbox_dir(mem)
    # 两行：用文本模式写盘会把 \n 翻成 \r\n，这条断言就是为那类 bug 准备的
    msg = "另一条会话留下的消息：样式表要加前缀。\n第二行。"
    r = m(base, "inbox", "put", msg)
    ok(r.returncode == 0 and "已投入信箱" in r.stdout, "inbox: put 投入一条", r.stdout)
    items = sorted(os.listdir(inbox))
    ok(len(items) == 1 and items[0].endswith(".md"), "inbox: 落成一个 .md 条目", str(items))
    ok(not any(n.endswith(".tmp") for n in items),
       "inbox: 原子写之后不留临时文件（先写临时名再 rename）", str(items))
    ok(not items[0].startswith("."), "inbox: 也没有留下隐藏的临时名", items[0])
    with open(os.path.join(inbox, items[0]), "rb") as fh:
        raw = fh.read()
    ok(raw == msg.encode("utf-8"),
       "inbox: 落盘字节与投进去的一模一样（二进制写，不翻译换行）", str(raw[:60]))
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
    r = m(base, "inbox", "list")
    ok(r.returncode == 0 and "样式表要加前缀" in r.stdout, "inbox: list 列出条目", r.stdout)
    r = m(base, "inbox", "list", "--json")
    ok(r.returncode == 0 and '"name"' in r.stdout, "inbox: list --json 给机器读", r.stdout)
    # 上限：单条 / 条数 / 总量
    r = m(base, "inbox", "put", "x" * (JOURNAL.MEMORY_INBOX_ITEM_MAX_BYTES + 1))
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
    # 转移为记录
    name = items[0]
    r = m(wsA, "inbox", "take", name, "--into-record", "信箱转来的样式问题", wsA)
    ok(r.returncode == 0 and "created" in r.stdout, "inbox: take --into-record 建一篇记录", r.stdout)
    rec2 = os.path.join(wsA, "work_log", "0003-信箱转来的样式问题.md")
    ok(not os.path.exists(rec2), "inbox: 纯中文标题退化成 <篇号>.md（与 new 一致）")
    rec2 = os.path.join(wsA, "work_log", "0003.md")
    ok(os.path.isfile(rec2), "inbox: 记录真的建出来了", os.listdir(os.path.join(wsA, "work_log")))
    rtxt = read(rec2)
    ok("# 0003 · 信箱转来的样式问题" in rtxt, "inbox: 记录 H1 用的是 --into-record 的标题")
    ok("样式表要加前缀" in rtxt, "inbox: 信箱原文被搬进记录（原样，不重新表述）")
    ok("（来自信箱 `" + name + "`）" in rtxt, "inbox: 记录里标明它来自信箱哪一条")
    ok(all(i["name"] != name for i in JOURNAL._inbox_items(mem)),
       "inbox: 转移之后原件被删掉（阅后即删 / 转移）", str(JOURNAL._inbox_items(mem)))
    # take --keep 不删
    m(base, "inbox", "put", "留着看的一条。")
    keepname = [i["name"] for i in JOURNAL._inbox_items(mem)][0]
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
        tmp = tempfile.mkdtemp(prefix="journal-selftest-")
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

        # logs/ 里的文件名与记录同形（`2026-01-01-run.md`），但**不是记录**
        os.makedirs(os.path.join(tmp, CONTAINER, "logs", "build"))
        write(os.path.join(tmp, CONTAINER, "logs", "build", "2026-01-01-run.md"),
              "# 构建日志\n\n构建于 2026-01-01，产物见项目根的 dist/。\n")
        r = run(tmp, "outline")
        ok(r.stdout.count("\n") == 1 and "2026-01-01" not in r.stdout,
           "a logs/ file shaped like a record is not read as one", r.stdout)

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

        # 目标文件（<容器>/目标.md，可选）------------------------------------
        goals_phase(tmp)

        # 全局记忆（跨工作区：分档 / 清单 / 收集 / 索引 / 门禁 / 收敛 / 信箱 / 升格）--
        memory_phase(tmp)

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
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


if __name__ == "__main__":
    sys.exit(main())
