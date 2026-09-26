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
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "journal.py")

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
    r = run(root, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "and also passes check --strict", r.stdout + r.stderr)

    # 骨架里日期还是 `YYYY-MM-DD` 占位符时，也必须过得了 --strict
    fresh = os.path.join(tmp, "docfresh")
    os.makedirs(os.path.join(fresh, CONTAINER, "lessons"), exist_ok=True)
    write(os.path.join(fresh, CONTAINER, "README.md"),
          cleaned.replace("2026-09-13", "YYYY-MM-DD").rstrip("\n") + "\n")
    write(os.path.join(fresh, CONTAINER, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(fresh, CONTAINER, "lessons", "01-topic.md"),
          "# 01 · 起步约定\n\n来源：初始化时建立，等第一篇记录收口后回填。\n\n## 子主题\n\n- 暂无条目。\n")
    r = run(fresh, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "a brand-new skeleton with the YYYY-MM-DD placeholder passes --strict",
       r.stdout + r.stderr)


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
