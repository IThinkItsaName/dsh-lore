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

        # 项目配置文件（<容器>/.config.json）---------------------------------
        config_phase(tmp)

        # 目标文件（<容器>/目标.md，可选）------------------------------------
        goals_phase(tmp)

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
