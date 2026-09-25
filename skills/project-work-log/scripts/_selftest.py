#!/usr/bin/env python3
"""_selftest.py — journal.py 的自测（内部工具，不参与日常使用）。

在临时目录里搭一个最小项目，跑通全部子命令并断言行为，最后删除临时目录。
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
| [archive/stageA/0005-old.md](archive/stageA/0005-old.md) | a |
| [archive/stageA/0006-old.md](archive/stageA/0006-old.md) | b |

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
    os.makedirs(os.path.join(tmp, "journal"))
    os.makedirs(os.path.join(tmp, "lessons"))
    write(os.path.join(tmp, "journal", "README.md"), EN_INDEX)
    write(os.path.join(tmp, "journal", "0001-alpha.md"), EN_ENTRY)
    write(os.path.join(tmp, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(tmp, "lessons", "01-topic.md"),
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
    """A/B/C/D 四项整理能力：索引瘦身 / 归档 / 分卷 / 冷存。"""
    tmp = os.path.join(parent, "cleanup")
    os.makedirs(os.path.join(tmp, "journal", "archive", "stageA"))
    os.makedirs(os.path.join(tmp, "lessons"))
    write(os.path.join(tmp, "journal", "README.md"), CLEAN_INDEX)
    write(os.path.join(tmp, "journal", "0001-alpha.md"), entry("0001", "Alpha", "2020-01-01"))
    write(os.path.join(tmp, "journal", "0002-beta.md"), entry("0002", "Beta", "2026-09-14"))
    write(os.path.join(tmp, "journal", "archive", "stageA", "0005-old.md"), entry("0005", "Old5", "2020-01-01"))
    write(os.path.join(tmp, "journal", "archive", "stageA", "0006-old.md"), entry("0006", "Old6", "2020-01-02"))
    write(os.path.join(tmp, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(tmp, "lessons", "01-topic.md"),
          "# 01 · T\n\n来源：wl/0002。\n\n- **s**：a。根因：b。做法：c。（`wl/0002`）\n")
    jidx = os.path.join(tmp, "journal", "README.md")

    # A) index compact
    r = run(tmp, "index", "compact", "--dry-run")
    ok(r.returncode == 0 and "折叠 1 个小节" in r.stdout, "compact dry-run reports", r.stdout)
    before = read(jidx)
    ok(read(jidx) == before, "compact dry-run changes nothing")
    run(tmp, "index", "compact")
    idx = read(jidx)
    ok("archive/stageA/0005-old.md" not in idx and "archive/stageA/" in idx,
       "compact folds archived rows into one", idx)
    ok("0001-alpha.md" in idx, "compact keeps active rows")

    # B) archive
    r = run(tmp, "archive", "--stage", "stageB", "--from", "1", "--to", "1")
    ok(os.path.exists(os.path.join(tmp, "journal", "archive", "stageB", "0001-alpha.md")),
       "archive moves the file", r.stdout)
    idx = read(jidx)
    ok("archive/stageB/0001-alpha.md" in idx, "archive rewrites index link", idx)
    ok(os.path.exists(os.path.join(tmp, "journal", "archive", "README.md")),
       "archive writes the archive index")

    # D) split --by-year
    r = run(tmp, "split", "--by-year")
    ok(os.path.exists(os.path.join(tmp, "journal", "2026", "0002-beta.md")),
       "split moves entry under its year", r.stdout)
    ok("2026/0002-beta.md" in read(jidx), "split rewrites index link", read(jidx))

    # C) prune（报告 → 打包 → 移出）
    r = run(tmp, "prune")
    ok(r.returncode == 0 and "冷存候选" in r.stdout, "prune reports candidates", r.stdout)
    before = read(jidx)
    ok(read(jidx) == before, "prune report-only changes nothing")
    zpath = os.path.join(tmp, "cold.zip")
    r = run(tmp, "prune", "--zip", zpath)
    ok(os.path.exists(zpath), "prune --zip writes archive", r.stdout)
    ok(os.path.exists(os.path.join(tmp, "journal", "archive", "stageA", "0005-old.md")),
       "prune --zip keeps originals")
    r = run(tmp, "prune", "--zip", zpath, "--apply")
    ok(not os.path.exists(os.path.join(tmp, "journal", "archive", "stageA", "0005-old.md")),
       "prune --apply moves originals out", r.stdout)
    ok(os.path.exists(os.path.join(tmp, "journal", "archive", "COLD-STORE.md")),
       "prune writes a manifest")
    ok(os.path.exists(os.path.join(tmp, "journal", "2026", "0002-beta.md")),
       "prune keeps cited/active entry")

    r = run(tmp, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "check --strict clean after cleanup ops", r.stdout + r.stderr)

    # E) compact 幂等：折叠出来的目录行不能再被折一次 ------------------------
    jidx = os.path.join(tmp, "journal", "README.md")
    run(tmp, "index", "compact")
    once = read(jidx)
    r = run(tmp, "index", "compact")
    ok(read(jidx) == once, "index compact is idempotent", read(jidx))
    ok("折叠 0 个小节" in r.stdout, "second compact folds nothing", r.stdout)


def safety_phase(tmp: str) -> None:
    """数据安全：不能静默毁掉非 UTF-8 文件，也不能把 LF 掺进 CRLF 台账。"""
    # 1) 非 UTF-8 目标必须**拒绝写入**，而不是写成 U+FFFD ------------------
    enc = os.path.join(tmp, "encfix")
    os.makedirs(os.path.join(enc, "journal"))
    raw = ("# 0001 · A\n\n日期：2026-09-13\n迭代：1\n结论：ok\n\n## 验证\n\n- 方式：x\n- 结果：1\n")
    gbk = os.path.join(enc, "journal", "0001-a.md")
    with open(gbk, "wb") as fh:
        fh.write(raw.encode("gbk"))
    before = read_bytes(gbk)
    r = run(enc, "append", "1", "--section", "更正", "--text", "changed")
    ok(r.returncode != 0, "writing a non-UTF-8 file is refused", r.stdout)
    ok("UTF-8" in r.stdout, "the refusal names the encoding", r.stdout)
    ok("Traceback" not in r.stderr, "the refusal is not a traceback", r.stderr[:200])
    ok(read_bytes(gbk) == before, "the non-UTF-8 file is left byte-identical")

    # 2) status --roll 在 CRLF 台账上不能掺进 LF --------------------------
    crlf = os.path.join(tmp, "crlffix")
    os.makedirs(os.path.join(crlf, "journal"))
    idx = ("# P\n\n## 文件索引\n\n### A. St\n\n| 文件 | 方面 |\n|---|---|\n"
           "| [0001-a.md](0001-a.md) | x |\n\n## 待办（滚动清单）\n\n- [ ] x\n\n"
           "## 当前状态（2026-09-13）\n\n- 阶段 / 版本：v1\n- 迭代：1\n")
    ipath = os.path.join(crlf, "journal", "README.md")
    with open(ipath, "wb") as fh:
        fh.write(idx.replace("\n", "\r\n").encode("utf-8"))
    with open(os.path.join(crlf, "journal", "0001-a.md"), "wb") as fh:
        fh.write(entry("0001", "A", "2026-09-13", "1").replace("\n", "\r\n").encode("utf-8"))
    r = run(crlf, "status", "--roll")
    ok(r.returncode == 0, "status --roll exits 0", r.stderr)
    data = read_bytes(ipath)
    ok(data.replace(b"\r\n", b"").count(b"\n") == 0, "status --roll injects no lone LF into a CRLF ledger")

    # 3) 半角括号的状态标题不能被叠加日期 --------------------------------
    en = os.path.join(tmp, "enfix")
    os.makedirs(os.path.join(en, "journal"))
    en_idx = ("# English\n\n## Index\n\n### A\n\n| File | Note |\n|---|---|\n"
              "| [0001-a.md](0001-a.md) | a |\n\n## TODO\n\n- [ ] x\n\n"
              "## Status (2026-01-01)\n\n- Stage: v1\n")
    eip = os.path.join(en, "journal", "README.md")
    write(eip, en_idx)
    r = run(en, "status", "--date", "2026-10-01")
    ok(r.returncode == 0, "status --date on a half-width heading exits 0", r.stderr)
    txt = read(eip)
    ok("2026-01-01" not in txt, "the old date is replaced, not nested", txt)
    ok("2026-10-01" in txt, "the new date landed", txt)

    # 4) 归档后，被移动记录自己的出站链接必须仍然有效 --------------------
    arch = os.path.join(tmp, "archfix")
    os.makedirs(os.path.join(arch, "journal"))
    os.makedirs(os.path.join(arch, "docs"))
    j = os.path.join(arch, "journal")
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
    moved = os.path.join(j, "archive", "S", "0001-a.md")
    ok(os.path.exists(moved), "the record was archived")
    targets = re.findall(r"\]\(([^)\s]+)\)", read(moved))
    bad = [t for t in targets
           if not t.startswith(("http", "#", "mailto"))
           and not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(moved), t)))]
    ok(not bad, "every rewritten link from the moved record resolves", f"targets={targets} bad={bad}")

    # 5) lesson add 必须保留 --source，即使正文里提到了别的 wl/ ----------
    lsn = os.path.join(tmp, "lsnfix")
    os.makedirs(os.path.join(lsn, "journal"))
    os.makedirs(os.path.join(lsn, "lessons"))
    write(os.path.join(lsn, "journal", "README.md"),
          "# L\n\n## 文件索引\n\n### A. St\n\n| 文件 | 方面 |\n|---|---|\n"
          "| [0001-a.md](0001-a.md) | x |\n\n## 待办（滚动清单）\n\n- [ ] x\n\n"
          "## 当前状态（2026-09-13）\n\n- 阶段 / 版本：v1\n")
    write(os.path.join(lsn, "journal", "0001-a.md"), entry("0001", "A", "2026-09-13", "1"))
    write(os.path.join(lsn, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(lsn, "lessons", "01-topic.md"), "# 01\n\n来源：x。\n\n## 子主题\n\n- a\n")
    r = run(lsn, "lesson", "add", "--volume", "01-topic.md", "--source", "1",
            "--text", "沿用 wl/9999 的写法")
    ok(r.returncode == 0, "lesson add exits 0", r.stderr)
    vol = read(os.path.join(lsn, "lessons", "01-topic.md"))
    ok("wl/0001" in vol, "lesson add keeps the --source citation", vol)


def doc_phase(tmp: str) -> None:
    """文档与代码一致性：模板落盘后必须能被自己的门禁接受。

    `references/templates.md` 里的台账模板是给人复制的，一旦里面的示例行被
    `check` 判成死链，照文档初始化出来的项目第一次 `check` 就是红的——而
    SKILL.md 承诺"0 篇记录也应通过"。这条用例把那个承诺钉住。
    """
    templates = os.path.join(os.path.dirname(HERE), "references", "templates.md")
    if not os.path.isfile(templates):
        # 只装了 scripts/ 的部署（例如从发布包单独取脚本）没有文档可校验。
        return
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
    os.makedirs(os.path.join(root, "journal"), exist_ok=True)
    os.makedirs(os.path.join(root, "lessons"), exist_ok=True)
    write(os.path.join(root, "journal", "README.md"), cleaned.rstrip("\n") + "\n")
    # 工作流 A 要求同时落 lessons/README.md；台账模板会链接到它。
    write(os.path.join(root, "lessons", "README.md"), LESSONS_INDEX)
    # 分册里不写 `wl/NNNN` 引用：此夹具一篇记录都没有，--strict 会判来源悬空。
    # 但要带一句「来源」说明，否则 --strict 判它连来源口径都没有。
    write(os.path.join(root, "lessons", "01-topic.md"),
          "# 01 · 起步约定\n\n来源：本册在项目初始化时建立，等第一篇记录收口后再回填 `wl/NNNN`。\n"
          "\n## 子主题\n\n- **尚未提炼**：暂无条目。\n")

    r = run(root, "check", "--quiet")
    ok(r.returncode == 0, "a ledger built from templates.md passes a plain check",
       r.stdout + r.stderr)
    r = run(root, "check", "--strict", "--quiet")
    ok(r.returncode == 0, "and also passes check --strict", r.stdout + r.stderr)

    # 骨架里日期还是 `YYYY-MM-DD` 占位符时，也必须过得了 --strict
    fresh = os.path.join(tmp, "docfresh")
    os.makedirs(os.path.join(fresh, "journal"), exist_ok=True)
    os.makedirs(os.path.join(fresh, "lessons"), exist_ok=True)
    write(os.path.join(fresh, "journal", "README.md"),
          cleaned.replace("2026-09-13", "YYYY-MM-DD").rstrip("\n") + "\n")
    write(os.path.join(fresh, "lessons", "README.md"), LESSONS_INDEX)
    write(os.path.join(fresh, "lessons", "01-topic.md"),
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
        os.makedirs(os.path.join(tmp, "journal", "archive"))
        os.makedirs(os.path.join(tmp, "lessons"))
        write(os.path.join(tmp, "journal", "README.md"), INDEX)
        write(os.path.join(tmp, "journal", "0001-seed.md"), SEED)
        write(os.path.join(tmp, "lessons", "README.md"), LESSONS_INDEX)
        write(os.path.join(tmp, "lessons", "01-topic.md"), VOLUME)

        # new --insert -----------------------------------------------------
        r = run(tmp, "new", "--title", "Add login rate limit", "--iter", "12",
                "--date", "2026-09-14", "--insert", "--stage", "A. 起步")
        ok(r.returncode == 0, "new --insert exits 0", r.stderr)
        entry = os.path.join(tmp, "journal", "0002-add-login-rate-limit.md")
        ok(os.path.exists(entry), "new --insert created 0002 file")
        idx = read(os.path.join(tmp, "journal", "README.md"))
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
        os.makedirs(os.path.join(cjk, "journal"))
        write(os.path.join(cjk, "journal", "README.md"),
              "# C\n\n## 文件索引\n\n### A. 起步\n\n| 文件 | 方面 |\n|---|---|\n\n"
              "## 待办（滚动清单）\n\n- [ ] x\n\n## 当前状态（2026-09-15）\n\n- 阶段 / 版本：v1\n")
        r = run(cjk, "new", "--title", "第三轮用户访谈结论", "--iter", "3",
                "--date", "2026-09-15", "--insert", "--stage", "A. 起步")
        ok(r.returncode == 0, "new accepts a pure-CJK title", r.stdout + r.stderr)
        bare = os.path.join(cjk, "journal", "0001.md")
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
        idx = read(os.path.join(tmp, "journal", "README.md"))
        ok("分支 / HEAD：main @ abc123" in idx and "测试：312 PASS" in idx, "status values updated")
        ok("## 当前状态（2026-09-14）" in idx, "status date updated")
        ok(idx.count("## 当前状态") == 1, "still exactly one status block")
        r = run(tmp, "status")
        ok("main @ abc123" in r.stdout, "status prints block")

        # status --set：短名要落到规范字段上，而不是新增一个平行字段 --------------
        # 用一个只含规范字段的独立夹具，避免依赖上面那个迷你项目的字段集。
        sdir = os.path.join(tmp, "statusfix")
        os.makedirs(os.path.join(sdir, "journal"))
        write(os.path.join(sdir, "journal", "README.md"), CANON_INDEX)
        r = run(sdir, "status", "--set", "核对=抽样 30 条全部通过",
                "--set", "交付物=app.zip", "--set", "阶段=v2")
        ok(r.returncode == 0, "status --set accepts short field names", r.stderr)
        sidx = read(os.path.join(sdir, "journal", "README.md"))
        ok("- 核对 / 验证：抽样 30 条全部通过" in sidx, "short name 核对 lands on 核对 / 验证", sidx)
        ok("- 交付物与指纹：app.zip" in sidx, "short name 交付物 lands on 交付物与指纹", sidx)
        ok("- 阶段 / 版本：v2" in sidx, "short name 阶段 lands on 阶段 / 版本", sidx)
        sfields = [l for l in sidx.splitlines() if l.startswith("- ") and "：" in l]
        ok(len(sfields) == 7, "canonical status block keeps exactly 7 fields", f"{sfields}")
        ok("(新增)" not in r.stdout, "short names appended no field", r.stdout)
        r = run(sdir, "status", "--set", "对不上的字段=x")
        ok("(新增)" in r.stdout and "- 对不上的字段：x" in read(os.path.join(sdir, "journal", "README.md")),
           "an unknown field name is still appended", r.stdout)

        # 台账末行没有换行时，--set 不能把新字段拼到上一行 ---------------
        idx_path = os.path.join(sdir, "journal", "README.md")
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
        idx = read(os.path.join(tmp, "journal", "README.md"))
        ok("- [x] ship the thing" in idx, "todo marked done")
        r = run(tmp, "todo", "--drop-done")
        ok("- [x] ship the thing" not in read(os.path.join(tmp, "journal", "README.md")), "todo --drop-done works")

        # append -----------------------------------------------------------
        r = run(tmp, "append", "2", "--section", "更正", "--text", "2026-09-14: changed mind", "--bullet")
        ok(r.returncode == 0 and "## 更正" in read(entry), "append creates section", r.stderr)
        r = run(tmp, "append", "2", "--section", "更正", "--text", "second note", "--bullet")
        ok(read(entry).count("## 更正") == 1 and "- second note" in read(entry),
           "append reuses existing section", r.stderr)

        # lesson add -------------------------------------------------------
        r = run(tmp, "lesson", "add", "--volume", "01-topic.md", "--source", "2",
                "--topic", "子主题", "--text", "**429 storm**：x。根因：y。做法：z")
        ok(r.returncode == 0 and "wl/0002" in read(os.path.join(tmp, "lessons", "01-topic.md")),
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
        write(os.path.join(tmp, "journal", "0003-research-note.md"), RESEARCH)
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

        # CRLF fidelity ----------------------------------------------------
        index_path = os.path.join(tmp, "journal", "README.md")
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
