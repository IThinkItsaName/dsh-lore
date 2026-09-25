#!/usr/bin/env python3
"""一次性测量：统计一个 journal/ + lessons/ 的现状（供 references/analysis.md 复现数字）。

不属于技能运行时；随包发布只为让 analysis.md 里的数字可复现。

    python scripts/_measure.py [ROOT] [--journal NAME] [--lessons NAME]

ROOT 默认为当前目录；`--journal` 默认自动在 `journal/` 与 `work-log/` 之间挑一个。
与 journal.py 一致：标签解析同时接受中文默认与英文别名。
"""
from __future__ import annotations

import argparse
import collections
import glob
import os
import re

DATE_KEYS = ("日期", "Date")
VERIFY_WORDS = ("验证", "实测", "复核", "检查", "审查", "评审", "结果", "证据", "评估", "确认",
                "Verification", "Review", "Results", "Evidence", "Tests")
STATUS_KEYS = ("当前状态", "Status", "Current Status")
HISTORY_KEYS = ("历史状态", "Status History")


def _any(aliases: tuple[str, ...]) -> str:
    return "|".join(re.escape(a) for a in aliases)


def read_text(path: str) -> str:
    """读文本文件，**不因编码问题崩掉**。

    测量对象是别人仓库里既有的记录，难免混进 GBK / UTF-16 存档或坏字节。
    这里按 UTF-8 读、坏字节替换掉（`errors="replace"`），统计照做，
    顶多个别字符标签认不出来——比整趟测量中断强。
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        print(f"WARN: 读不了 {path}（{exc}）")
        return ""


def resolve_journal(name: str | None, root: str) -> str:
    if name:
        return os.path.join(root, name)
    for cand in ("journal", "work-log"):
        if os.path.isdir(os.path.join(root, cand)):
            return os.path.join(root, cand)
    return os.path.join(root, "journal")


def main() -> int:
    ap = argparse.ArgumentParser(description="统计 journal/ + lessons/ 现状（一次性测量工具）")
    ap.add_argument("root", nargs="?", default=".", help="项目根，默认当前目录")
    ap.add_argument("--journal", default=None, help="记录目录名；默认自动识别 journal/ 或 work-log/")
    ap.add_argument("--lessons", default="lessons", help="经验目录名（默认 lessons）")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    wl = resolve_journal(args.journal, root)
    ls = os.path.join(root, args.lessons)
    print(f"root    : {root}")
    print(f"journal : {wl}" + ("" if os.path.isdir(wl) else "   (不存在)"))
    print(f"lessons : {ls}" + ("" if os.path.isdir(ls) else "   (不存在)"))
    print()

    nums: dict[int, list[str]] = {}
    for dp, _dn, fn in os.walk(wl):
        for f in fn:
            m = re.match(r"^(\d+)(?:-.*)?\.md$", f)
            if m:
                nums.setdefault(int(m.group(1)), []).append(
                    os.path.relpath(os.path.join(dp, f), root).replace(os.sep, "/"))
    ks = sorted(nums)
    if not ks:
        print("没有找到编号记录。")
        return 0
    print("entries:", len(ks), "range", ks[0], "-", ks[-1])
    print("duplicate numbers:", {k: v for k, v in nums.items() if len(v) > 1})
    print("gaps:", [n for n in range(ks[0], ks[-1] + 1) if n not in nums])

    files = [f for f in glob.glob(os.path.join(wl, "*.md"))
             if re.match(r"^\d+(?:-.*)?$", os.path.basename(f))]
    print("root entries:", len(files))
    with_date = with_sec = with_ver = 0
    for f in files:
        t = read_text(f)
        with_date += bool(re.search(rf"^(?:{_any(DATE_KEYS)})[：:]", t, re.M))
        with_sec += bool(re.search(r"^##\s", t, re.M))
        with_ver += bool(re.search(rf"^##.*(?:{_any(VERIFY_WORDS)})", t, re.M))
    print("with date:", with_date, "with ## section:", with_sec, "with verify section:", with_ver)

    index = os.path.join(wl, "README.md")
    if os.path.isfile(index):
        idx = read_text(index)
        links = re.findall(r"\]\(([^)]+\.md)\)", idx)
        dead = [l for l in links if not os.path.exists(os.path.normpath(os.path.join(wl, l)))]
        print("index links:", len(links), "dead:", dead)
        print("has status block:", bool(re.search(rf"^#{{2,3}}\s*.*(?:{_any(STATUS_KEYS)}).*$", idx, re.M)))
        print("has history block:", any(("## " + h) in idx for h in HISTORY_KEYS))
        print("index size chars:", len(idx))

        # 状态块本身的体量：analysis.md 里「3,508 字符的当前状态块」就是这个数
        m = re.search(rf"^#{{2,3}}\s*.*(?:{_any(STATUS_KEYS)}).*$", idx, re.M)
        if m:
            after = idx[m.end():]
            nxt = re.search(r"^#{2,3}\s", after, re.M)
            print("status block chars:", len(m.group(0) + (after[: nxt.start()] if nxt else after)))
        print("status blocks in index:",
              len(re.findall(rf"^#{{2,3}}\s*.*(?:{_any(STATUS_KEYS)}).*$", idx, re.M)))
        print("history blocks in index:",
              sum(len(re.findall(rf"^#{{2,3}}\s*{re.escape(h)}", idx, re.M)) for h in HISTORY_KEYS))

    # 项目级复盘文档：skill 主张取消 SUMMARY，把数字收进复盘分册
    for name in ("SUMMARY.md", os.path.join("docs", "SUMMARY.md")):
        p = os.path.join(root, name)
        if os.path.isfile(p):
            print(f"{name} size chars:", len(read_text(p)))

    # 标题里写迭代号的篇数：基线把「变更集号」混进标题的次数
    titled = 0
    for dp, _dn, fn in os.walk(wl):
        for f in fn:
            if not re.match(r"^\d+(?:-.*)?\.md$", f):
                continue
            head = re.search(r"^#\s+(.+)$", read_text(os.path.join(dp, f)), re.M)
            if head and re.search(r"(?:变更集|批次|迭代|阶段|版本|里程碑)\s*\d", head.group(1)):
                titled += 1
    print("titles carrying an iteration number:", titled)

    vols = sorted(glob.glob(os.path.join(ls, "*.md"))) if os.path.isdir(ls) else []
    cites: collections.Counter[int] = collections.Counter()
    for v in vols:
        t = read_text(v)
        for m in re.finditer(r"wl/(\d+)", t):
            cites[int(m.group(1))] += 1
    print("lessons files:", [os.path.basename(v) for v in vols])
    print("citation refs:", sum(cites.values()), "distinct:", len(cites),
          "missing targets:", sorted(n for n in cites if n not in nums))
    print("entries never cited from lessons:", len([n for n in ks if n not in cites]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
