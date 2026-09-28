#!/usr/bin/env python3
"""reverse-verify.py — 把 `memory_phase` 的每条断言**先弄红一次**。

本项目的硬规矩：**没见它红过的断言不算数**。这条工具把那张变异表逐条跑一遍 ——
每次按一个字面替换把 journal.py 改坏，只跑全局记忆那一相，检查"期望的那条断言"
确实变红。真实源码一个字节都不动：改的是临时目录里的**副本**。

    python logs/tests/reverse-verify.py               # 逐条变异，全中退出码 0
    python logs/tests/reverse-verify.py --list        # 只列变异表
    python logs/tests/reverse-verify.py --keep        # 留下临时目录便于排查
    python logs/tests/reverse-verify.py --root DIR    # 夹具父目录（须已存在）
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(HERE))
SKILL = os.path.join(WORKSPACE, ".pi", "skills", "project-work-log", "scripts")

# (名字, 原文, 改成, 期望变红的那条断言里的字样)
MUTATIONS: list[tuple[str, str, str, str]] = [
    ("进索引的档位放宽到含 inferred",
     'MEMORY_SOURCES_IN_INDEX = ("tested", "read")',
     'MEMORY_SOURCES_IN_INDEX = ("tested", "read", "inferred")',
     "memory: 进索引的 manual 档就是 tested / read"),
    ("三态少一个",
     'MEMORY_STATES = ("active", "stale", "retired")',
     'MEMORY_STATES = ("active", "retired")',
     "memory: 三态就是约定那三个"),
    ("软目标设得比硬上限还大",
     "MEMORY_INDEX_SOFT_CHARS = 800",
     "MEMORY_INDEX_SOFT_CHARS = 9000",
     "memory: 软目标小于硬上限"),
    ("硬上限放到够不着",
     "MEMORY_INDEX_HARD_CHARS = 1500",
     "MEMORY_INDEX_HARD_CHARS = 150000",
     "memory: 索引超硬上限报错"),
    ("--memory 不再覆盖路径",
     "    if explicit:\n        return os.path.abspath(explicit)",
     "    if False:\n        return os.path.abspath(explicit)",
     "memory: --memory 覆盖整条路径"),
    ("环境变量那一档失效",
     '    env = os.environ.get("DSH_WORKLOG_MEMORY", "").strip()\n    if env:',
     '    env = ""\n    if env:',
     "memory: $DSH_WORKLOG_MEMORY 覆盖整条路径"),
    ("来源分档不再细看 manual: 的后缀",
     '    if s.startswith("manual:"):\n'
     '        name = s.split(":", 1)[1].strip()\n'
     '        return name if name in MEMORY_SOURCE_MANUAL else ""',
     '    if s.startswith("manual:"):\n        return "tested"',
     "memory: manual:inferred 分得出"),
    ("索引准入不再看档位",
     '    tier = memory_source_tier(source)\n'
     '    return tier == "record" or tier in MEMORY_SOURCES_IN_INDEX',
     "    return True",
     "memory: 进不进索引由档位决定"),
    ("applies-to 标签正则放宽",
     'MEMORY_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")',
     'MEMORY_TAG_RE = re.compile(r"^.+$")',
     "memory: 非法 applies-to 标签被拒绝"),
    ("id 正则放宽",
     'MEMORY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")',
     'MEMORY_ID_RE = re.compile(r"^.+$")',
     "memory: 非法 id 被拒绝"),
    ("manual:tested 的「可核对结果」判据失效",
     '    return bool(re.search(r"`[^`]+`", body) or re.search(r"\\d", body))',
     "    return True",
     "memory: tested / read 的附加要求由 lint 判"),
    ("manual:read 的「指名出处」判据失效",
     '    if re.search(r"`[^`]+`", body):\n        return True',
     "    if True:\n        return True",
     "memory: tested / read 的附加要求由 lint 判"),
    ("manual:inferred 不再强制标注",
     '    if tier == "inferred":\n        note = "未经证实"\n        if note not in args.text:',
     '    if False:\n        note = "未经证实"\n        if note not in args.text:',
     "memory: manual:inferred 不标注「未经证实」被拒绝"),
    ("wl/NNNN 不再核到真实记录",
     '        paths = find_entries(journal, lessons_skip(lessons)).get(num)\n'
     '        if not paths:\n'
     '            return None, f"`{r}` 在记录目录里不存在"\n'
     '        return paths[0], ""',
     '        paths = find_entries(journal, lessons_skip(lessons)).get(num)\n'
     '        if True:\n'
     '            return (paths[0] if paths else os.path.join(journal, "ghost.md")), ""',
     "memory: wl/NNNN 指向不存在的记录被拒绝"),
    ("清单的 upload 一律当 true",
     '                if low in ("true", "yes", "1", "是", "开"):\n'
     '                    header["upload"] = True',
     '                if True:\n                    header["upload"] = True',
     "memory: upload:false 的工作区被跳过"),
    ("清单渲染时丢掉 `→ id:`",
     '        out.append(f"- {it[\'ref\']}  {it[\'title\']}  →  id: {it[\'id\']}")',
     '        out.append(f"- {it[\'ref\']}  {it[\'title\']}")',
     "memory: 再 publish 时保留手写的 id"),
    ("publish 不保留手写的 id",
     '        it["id"] = old_ids.get(it["ref"], it["id"])',
     "        pass",
     "memory: 再 publish 时保留手写的 id"),
    ("publish 的 upload 默认变成 true",
     '    upload = bool(args.upload) if args.upload is not None else bool(old["upload"] or False)',
     '    upload = bool(args.upload) if args.upload is not None else True',
     "memory: publish 默认 upload: false"),
    ("collect 不再按清单摘要跳过",
     '        st = state["workspaces"].get(ws)\n'
     '        if isinstance(st, dict) and st.get("digest") == digest:\n'
     '            skipped.append(f"{name}（清单没变）")\n'
     "            continue",
     '        st = state["workspaces"].get(ws)\n'
     '        if False:\n'
     '            skipped.append(f"{name}（清单没变）")\n'
     "            continue",
     "memory: 幂等靠 .state.json 里的清单摘要"),
    ("collect 每次都往名册里写点会变的东西",
     '    if registry_dirty and not args.dry_run:\n        save_registry(memory, registry)',
     '    if not args.dry_run:\n'
     '        registry["_touched"] = str(_dt.datetime.now().timestamp())\n'
     '        save_registry(memory, registry)',
     "memory: collect 幂等"),
    ("collect 改写工作区的清单",
     "        text = read_raw(memory_manifest_path(ws))",
     "        text = read_raw(memory_manifest_path(ws))\n"
     "        if not args.dry_run:\n"
     '            write_raw(memory_manifest_path(ws), "clobbered\\n")',
     "memory: collect 绝不改写工作区的清单"),
    ("cited-by 直接覆盖而不是累计",
     '                entry["cited_by"] = sorted(set(existing[0]["cited_by"]) | {name})',
     '                entry["cited_by"] = [name]',
     "memory: 同一领域的同名 id 是「被别的工作区引用」"),
    ("add 不再查重复 id",
     '    if any(e["id"] == eid for e in load_memory_entries(memory)):',
     "    if False:",
     "memory: 重复 id 被拒绝（id 全局唯一）"),
    ("跨工作区同名 id 不再算冲突",
     "                if other:\n"
     '                    problems.append(f"{name}: id `{eid}` 已被分册 `{other[0][\'volume\']}` 占用"',
     "                if False:\n"
     '                    problems.append(f"{name}: id `{eid}` 已被分册 `{other[0][\'volume\']}` 占用"',
     "memory: 两个工作区发布同名 id 被拒绝"),
    ("候选不再被记下来",
     '    cands = load_candidates(memory)\n    if ws in cands:\n        return ""',
     '    cands = load_candidates(memory)\n    if True:\n        return ""',
     "memory: 有清单但没登记的工作区被记成候选（只提示）"),
    ("publish 不清掉候选",
     "    cands = load_candidates(memory)\n"
     "    if cands.pop(root, None) is not None:\n"
     "        save_candidates(memory, cands)",
     "    cands = load_candidates(memory)",
     "memory: publish 登记后候选里就不再有它"),
    ("lint 不再比对索引与正文",
     "        have = read(ipath)\n        if have != want:\n            want_ids = set(",
     "        have = read(ipath)\n        if False:\n            want_ids = set(",
     "memory: 索引与正文不一致报 ERROR"),
    ("lint 不再管 inferred 混进索引",
     '            if memory_source_tier(e["source"]) == "inferred" and re.search(',
     "            if False and re.search(",
     "memory: manual:inferred 出现在索引里是 ERROR"),
    ("lint 不再查 cited-by",
     '        for c in e["cited_by"]:\n            if c not in names:',
     "        for c in []:\n            if c not in names:",
     "memory: cited-by 引用不存在的工作区是 ERROR"),
    ("lint 不再查分册标题与文件名",
     "        elif domain not in m.group(1):",
     "        elif False:",
     "memory: 分册标题与文件名不一致是 WARN"),
    ("lint 不再查近似重复",
     "            if s >= MEMORY_DUP_THRESHOLD:",
     "            if False:",
     "memory: 近似重复是 WARN"),
    ("近似重复的阈值放到够不着",
     "MEMORY_DUP_THRESHOLD = 0.7",
     "MEMORY_DUP_THRESHOLD = 2.0",
     "memory: 近似重复是 WARN"),
    ("lint 不再查硬上限",
     "        if size > MEMORY_INDEX_HARD_CHARS:\n            rep.add",
     "        if False:\n            rep.add",
     "memory: 硬上限在 lint 里是 ERROR"),
    ("index --check 不再报不一致",
     '        if have != want:\n            print(f"ERROR: {MEMORY_INDEX_NAME} 与正文分册不一致（跑 `memory index` 重建）")',
     '        if False:\n            print(f"ERROR: {MEMORY_INDEX_NAME} 与正文分册不一致（跑 `memory index` 重建）")',
     "memory: index --check 在不一致时非零退出"),
    ("index 不再报硬上限",
     "\n    if size > MEMORY_INDEX_HARD_CHARS:",
     "\n    if False:",
     "memory: 索引超硬上限报错"),
    ("collect 不再提醒重建索引",
     '    if changed and not args.dry_run:\n'
     '        print("  提示：跑 `memory index` 重建索引（索引是生成物，collect 不代劳）")',
     '    if False:\n        print("  提示")',
     "memory: collect 提醒索引要重建"),
    ("status 不再铺开名字、一律给路径",
     '              f"{gone}{\'  \' + ws if args.verbose else \'\'}")',
     '              f"{gone}  {ws}")',
     "memory: status 只列工作区名字、不铺满路径"),
    ("search 忽略 --include-personal",
     "    for e in load_memory_entries(memory, include_personal=args.include_personal):",
     "    for e in load_memory_entries(memory, include_personal=False):",
     "memory: --include-personal 才检索 personal"),
    ("search 默认连 retired 一起搜",
     '    states = ("active", "stale", "retired") if args.include_retired else ("active", "stale")',
     '    states = ("active", "stale", "retired")',
     "memory: retired 默认搜不到"),
    ("add 忽略 --personal",
     '             "cited_by": [], "body": [" ".join(args.text.split())], "personal": args.personal,',
     '             "cited_by": [], "body": [" ".join(args.text.split())], "personal": False,',
     "memory: personal 默认不检索"),
    ("`<工作区>/wl/NNNN` 不再核到清单",
     '        if any(it["ref"] == ref for it in parsed["items"]):',
     "        if False:",
     "memory: `<工作区>/wl/NNNN` 来源核到那份发布清单"),
    ("dream 不再查占位符",
     "        if MEMORY_DREAM_SLOT in s:",
     "        if False:",
     "dream: 没填的骨架被拒绝写回"),
    ("dream 不再查断言有没有回指",
     "        elif not dream_record_links(s):",
     "        elif False:",
     "dream: 断言不带回指被拒绝"),
    ("dream 不再查死链",
     "    _check_links(root or os.path.dirname(path), path, rep)",
     "    pass",
     "dream: 来源记录被删后 --check 变红"),
    ("dream 不再拦填过的骨架",
     "        if MEMORY_DREAM_SLOT not in old:",
     "        if False:",
     "dream: 骨架看起来填过时不覆盖"),
    ("dream accept 跳过校验直接写",
     "    dream_validate(root, src, rep)\n    if rep.errors():",
     "    if rep.errors():",
     "dream: 没填的骨架被拒绝写回"),
    ("dream 不再认已收敛的记录",
     "    return dream_record_links(read(path))",
     "    return []",
     "dream: 已收敛的记录不再重复挑出来（标记生效）"),
    ("inbox 不再查单条上限",
     "    if len(data) > MEMORY_INBOX_ITEM_MAX_BYTES:",
     "    if False:",
     "inbox: 单条超上限被拒绝"),
    ("inbox 不再查条数上限",
     "    if len(items) >= MEMORY_INBOX_MAX_ITEMS:",
     "    if False:",
     "inbox: 条数到顶后写满拒绝"),
    ("inbox 不再忽略半截的 .tmp",
     '        if name.endswith(".tmp") or not os.path.isfile(path):',
     "        if not os.path.isfile(path):",
     "inbox: 读到 .tmp 半截文件时当它不存在"),
    ("inbox 用文本模式直接写（不先临时名再 rename）",
     '    tmp = os.path.join(d, f".{name}.{os.getpid()}.tmp")\n'
     '    with open(tmp, "wb") as fh:\n'
     "        fh.write(data)\n"
     "    os.replace(tmp, path)",
     '    with open(path, "w", encoding="utf-8") as fh:\n        fh.write(text)',
     "inbox: 落盘字节与投进去的一模一样"),
    ("inbox take 不删原件",
     '    os.remove(item["path"])\n    print(f"已删除 {item[\'name\']}")',
     '    print(f"已删除 {item[\'name\']}")',
     "inbox: 转移之后原件被删掉"),
    ("inbox take 不搬原文",
     '        payload += [l + nl for l in text.replace("\\r\\n", "\\n").splitlines()]',
     "        payload += []",
     "inbox: 信箱原文被搬进记录"),
    ("sweep 不 --apply 也删",
     "    if not args.apply:\n"
     '        print("（默认只报告；确认后加 `--apply` 才真删）")\n'
     "        return 0",
     "    if False:\n        return 0",
     "inbox: sweep 默认只报告"),
    ("inbox count 多打印几个字",
     "    print(len(_inbox_items(memory_root(args.memory))))",
     '    print(f"共 {len(_inbox_items(memory_root(args.memory)))} 条")',
     "inbox: count 的第一行就是一个整数"),
    ("promote 只看后两条条件",
     "    return all(m[1] for m in marks), marks",
     "    return marks[3][1] and marks[4][1], marks",
     "promote: 三条件全满足的才被列出来"),
    ("promote 少记一条判据",
     '    marks.append(("已真实执行过", executed, entry["source"] or "(无来源)"))',
     "    pass",
     "promote: 三条判据"),
]


def load_module(path: str, tag: str):
    spec = importlib.util.spec_from_file_location(f"rv_{tag}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description="把 memory_phase 的断言逐条弄红一次")
    ap.add_argument("--root", default=os.path.join(WORKSPACE, "logs", "fixtures"),
                    help="夹具父目录（必须已存在）")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        for name, _old, _new, expect in MUTATIONS:
            print(f"{name}\n    → 期望变红：{expect}")
        return 0

    src_path = os.path.join(SKILL, "journal.py")
    st_path = os.path.join(SKILL, "_selftest.py")
    with open(src_path, encoding="utf-8", newline="") as fh:
        original = fh.read()
    with open(st_path, encoding="utf-8", newline="") as fh:
        selftest_src = fh.read()

    base = os.path.abspath(args.root)
    if not os.path.isdir(base):
        print(f"ERROR: --root 不是一个已存在的目录：{base}")
        return 2
    scratch_root = os.path.join(base, "reverse-verify")
    shutil.rmtree(scratch_root, ignore_errors=True)
    os.makedirs(scratch_root)

    missed: list[str] = []
    broken: list[str] = []
    hits = 0
    for i, (name, old, new, expect) in enumerate(MUTATIONS):
        n = original.count(old)
        if n != 1:
            broken.append(f"{name}：替换源在 journal.py 里出现 {n} 次（应恰好 1 次）")
            print(f"MISS  {name}   [替换源不唯一：{n} 次]")
            continue
        d = os.path.join(scratch_root, f"rev{i:02d}")
        os.makedirs(d)
        with open(os.path.join(d, "journal.py"), "w", encoding="utf-8", newline="") as fh:
            fh.write(original.replace(old, new))
        with open(os.path.join(d, "_selftest.py"), "w", encoding="utf-8", newline="") as fh:
            fh.write(selftest_src)
        fx = os.path.join(d, "fx")
        os.makedirs(fx)
        mod = load_module(os.path.join(d, "_selftest.py"), f"m{i}")
        # 只留结论：把子进程逐条 PASS/FAIL 的打印静音，否则每跑一条变异都会倒出
        # 一整份自测输出（五十几条变异就是几万行），真正要看的那行会被埋掉。
        def _quiet(cond, label, detail="", _mod=mod):
            _mod.results.append((bool(cond), label))
        mod.ok = _quiet
        start = len(mod.results)
        crash = ""
        try:
            mod.memory_phase(fx)
        except Exception as exc:                     # 变异本身可能直接把相跑崩
            crash = f"{type(exc).__name__}: {exc}"
        fails = [label for good, label in mod.results[start:] if not good]
        if any(expect in label for label in fails):
            hits += 1
            print(f"PASS  {name}   [{len(fails)} 条断言变红]")
        else:
            missed.append(name)
            print(f"MISS  {name}   [期望「{expect}」没变红；红了 {len(fails)} 条"
                  f"{'；相跑崩了：' + crash if crash else ''}]")
        if not args.keep:
            shutil.rmtree(d, ignore_errors=True)

    print(f"\n{len(MUTATIONS)} 条变异：{hits} 条如期变红 / {len(missed)} 条没变红"
          f" / {len(broken)} 条替换源对不上")
    for b in broken:
        print("  ! " + b)
    for m_ in missed:
        print("  ! 没变红：" + m_)
    if not args.keep:
        shutil.rmtree(scratch_root, ignore_errors=True)
    else:
        print(f"（临时目录保留在 {scratch_root}）")
    return 1 if (missed or broken) else 0


if __name__ == "__main__":
    sys.exit(main())
