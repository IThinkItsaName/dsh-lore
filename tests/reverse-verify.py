#!/usr/bin/env python3
"""reverse-verify.py — 把自测里每个阶段的断言**先弄红一次**。

本项目的硬规矩：**没见它红过的断言不算数**。这条工具把变异表逐条跑一遍 ——
每次按一个字面替换把 journal.py 改坏，只跑那一条变异所属的**那一相**，检查"期望的
那条断言"确实变红。真实源码一个字节都不动：改的是临时目录里的**副本**。

**为什么要按相分**：最初这张表只覆盖 `memory_phase`。但"没见它红过"这条规矩对**每一相**
都成立，只覆盖一相等于只在很小一部分地方守规矩。变异行的第一个字段就是它属于哪一相，
新增一相只要在 `PHASES` 里登记它的函数名。

**起飞前先查一遍"这条断言到底跑没跑"**（2026-10-15 加的）：跑变异之前先跑一遍**未变异**
的自测，把标签全收进来；某条变异的期望字样要是在里面找不到，它**不可能**变红（不是
"没测到"，是"压根没执行"）。三条占号变异就是这么白跑一轮的：断言内联在 `main()` 里，
而本脚本只跑 `PHASES` 登记的函数。这种局面现在当场报错（`--no-preflight` 可跳过）。

    python publish/worklog/tests/reverse-verify.py                  # 逐条变异，全中退出码 0
    python publish/worklog/tests/reverse-verify.py --list           # 只列变异表
    python publish/worklog/tests/reverse-verify.py --phase config   # 只跑某一相
    python publish/worklog/tests/reverse-verify.py --keep           # 留下临时目录便于排查
    python publish/worklog/tests/reverse-verify.py --root DIR       # 夹具父目录（须已存在）
    python publish/worklog/tests/reverse-verify.py --skill-dir DIR  # 技能源 scripts/ 目录（默认自动解析）
    python publish/worklog/tests/reverse-verify.py --no-preflight   # 跳过起飞前检查（急着看某一条时）
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys

# 本驱动会**执行**技能脚本（直接 import，以及起子进程跑自测），而 Python 默认会在被执行的
# `.py` 旁边写 `__pycache__` —— 技能脚本住在包内（`skills/project-work-log/scripts/`），
# 于是「跑过本驱动」会把 `_package.py --check` 弄红（副本里遗留的 `__pycache__` 会随包发
# 出去）。跑之前先关掉字节码写入：本进程这一句，子进程再加一条环境变量（见 unmutated_labels）。
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(HERE))

# 技能源在哪：2026-10-15 起测试 harness 只有**一份**（就是本目录所在的 `tests/`，
# 从前还有一份 `logs/tests/` 镜像，已收并）。所以正常布局下命中第二条 —— 包内的
# `skills/project-work-log/scripts/`。第一条是历史遗留下来的"作者工作区布局"，留着是为了
# 兼容别的 checkout（顶层带 `.pi/` 的那种）；`--skill-dir` 覆盖这两者。
SKILL_CANDIDATES = (
    os.path.join(WORKSPACE, ".pi", "skills", "project-work-log", "scripts"),
    os.path.join(os.path.dirname(HERE), "skills", "project-work-log", "scripts"),
)


def default_skill_dir() -> str:
    for candidate in SKILL_CANDIDATES:
        if os.path.isdir(candidate):
            return candidate
    return SKILL_CANDIDATES[0]


SKILL = default_skill_dir()

# 相名 → `_selftest.py` 里那个阶段函数的函数名。新增一相就在这里登记。
#
# **登记是硬要求**：本脚本只跑这里的函数。断言要是内联在 `main()` 里（那个函数本脚本
# 调不了：它自己解析 argv），变异就永远等不到它变红 —— 会报
# "MISS：期望的标签没变红；红了 0 条"，也就是"测了等于没测"。2026-10-15 那三条占号
# 变异就是这么报的：断言内联在 `main()` 里，直到把整段搬成 `numbering_phase()` 才通。
PHASES: dict[str, str] = {
    "memory": "memory_phase",
    "numbering": "numbering_phase",
    "config": "config_phase",
    "lesson": "lesson_phase",
    "gates": "gate_phase",
    "links": "link_phase",
    "mode": "mode_phase",
    # 下面三相是 2026-10-17 复核补的（M-2）：本轮修的恰恰是它们的逻辑，
    # 而它们当时一条变异都没有 —— 「没有断言/变异盯着」正是 H-1 那种洞的产地。
    "archive_index": "archive_index_check",
    "archive_dir_index": "archive_dir_index_phase",
    "card": "card_phase",
}

# 变异能打在哪个源文件上。默认 `journal.py`（绝大多数变异）；投影器的变异打在
# `dsh-lore-card.py` 上 —— 两者都住在同一个 `scripts/` 里，宿主相（`card_phase`）自己
# 按 `HERE/dsh-lore-card.py` 起子进程，所以把改过的那份照布局放进副本就生效。
JOURNAL_SRC = "journal.py"
CARD_SRC = "dsh-lore-card.py"


def m6(m: tuple) -> tuple:
    """变异表的一项 → `(相, 名字, 原文, 改成, 期望字样, 目标源文件)`。

    第 6 项可省（省了就是 `journal.py`）—— 表里五十几条旧条目因此不用逐个改，
    而新加的投影器变异只要多写一个字段就能指到另一个文件。
    """
    return (m[0], m[1], m[2], m[3], m[4], m[5] if len(m) > 5 else JOURNAL_SRC)


# (相, 名字, 原文, 改成, 期望变红的那条断言里的字样[, 目标源文件，默认 journal.py])
MUTATIONS: list[tuple] = [
    ("memory", "进索引的档位放宽到含 inferred",
     'MEMORY_SOURCES_IN_INDEX = ("tested", "read")',
     'MEMORY_SOURCES_IN_INDEX = ("tested", "read", "inferred")',
     "memory: 进索引的 manual 档就是 tested / read"),
    ("memory", "三态少一个",
     'MEMORY_STATES = ("active", "stale", "retired")',
     'MEMORY_STATES = ("active", "retired")',
     "memory: 三态就是约定那三个"),
    ("memory", "软目标设得比硬上限还大",
     "MEMORY_INDEX_SOFT_CHARS = 800",
     "MEMORY_INDEX_SOFT_CHARS = 9000",
     "memory: 软目标小于硬上限"),
    ("memory", "硬上限放到够不着",
     "MEMORY_INDEX_HARD_CHARS = 1500",
     "MEMORY_INDEX_HARD_CHARS = 150000",
     "memory: 索引超硬上限报错"),
    ("memory", "--memory 不再覆盖路径",
     "    if explicit:\n        return os.path.abspath(explicit)",
     "    if False:\n        return os.path.abspath(explicit)",
     "memory: --memory 覆盖整条路径"),
    ("memory", "环境变量那一档失效",
     '    env = os.environ.get("DSH_WORKLOG_MEMORY", "").strip()\n    if env:',
     '    env = ""\n    if env:',
     "memory: $DSH_WORKLOG_MEMORY 覆盖整条路径"),
    ("memory", "inbox 头部不带那句不可信提示",
     '    lines.append(f"note: {INBOX_NOTE}")',
     '',
     "inbox: 落盘时写下 from / at / id /「不可信输入」那句（头部由工具渲染）"),
    ("memory", "登记过的来源工作区没了也当错",
     '    if state == "gone":\n'
     '        where = registry_names(registry)[ws][0]\n'
     '        return None, tier, f"来源工作区 `{ws}` 已被移除（名册里的路径不存在：{where}）"',
     '    if state == "gone":\n'
     '        where = registry_names(registry)[ws][0]\n'
     '        return False, tier, f"来源工作区 `{ws}` 已被移除（名册里的路径不存在：{where}）"',
     "memory: 登记过的来源工作区没了 → 只提示，不拦（路径没了就当它没了）"),
    ("memory", "退役条目也照判来源与内容",
     '        if e["state"] == "retired":\n            continue\n',
     '        if False:\n            continue\n',
     "memory: 退役条目只判结构 —— 坏来源与不合格正文都不再报错"),
    ("memory", "现役条目也被跳过（跳过不是按 state 判的）",
     '        if e["state"] == "retired":\n            continue\n',
     '        continue\n',
     "memory: 同一条改成现役后照旧报错（跳过是按 state 判的）"),
    ("memory", "来源分档不再细看 manual: 的后缀",
     '    if s.startswith("manual:"):\n'
     '        name = s.split(":", 1)[1].strip()\n'
     '        return name if name in MEMORY_SOURCE_MANUAL else ""',
     '    if s.startswith("manual:"):\n        return "tested"',
     "memory: manual:inferred 分得出"),
    ("memory", "索引准入不再看档位",
     '    tier = memory_source_tier(source)\n'
     '    return tier == "record" or tier in MEMORY_SOURCES_IN_INDEX',
     "    return True",
     "memory: 进不进索引由档位决定"),
    ("memory", "applies-to 标签正则放宽",
     'MEMORY_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")',
     'MEMORY_TAG_RE = re.compile(r"^.+$")',
     "memory: 非法 applies-to 标签被拒绝"),
    ("memory", "id 正则放宽",
     'MEMORY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")',
     'MEMORY_ID_RE = re.compile(r"^.+$")',
     "memory: 非法 id 被拒绝"),
    ("memory", "manual:tested 的「可核对结果」判据失效",
     '    return bool(re.search(r"`[^`]+`", body) or re.search(r"\\d", body))',
     "    return True",
     "memory: tested / read 的附加要求由 lint 判"),
    ("memory", "manual:read 的「指名出处」判据失效",
     '    if re.search(r"`[^`]+`", body):\n        return True',
     "    if True:\n        return True",
     "memory: tested / read 的附加要求由 lint 判"),
    ("memory", "manual:inferred 不再强制标注",
     '    if tier == "inferred":\n        note = "未经证实"\n        if note not in args.text:',
     '    if False:\n        note = "未经证实"\n        if note not in args.text:',
     "memory: manual:inferred 不标注「未经证实」被拒绝"),
    ("memory", "wl/NNNN 不再核到真实记录",
     '        paths = find_entries(journal, lessons_skip(lessons)).get(num)\n'
     '        if not paths:\n'
     '            return None, f"`{r}` 在记录目录里不存在"\n'
     '        return paths[0], ""',
     '        paths = find_entries(journal, lessons_skip(lessons)).get(num)\n'
     '        if True:\n'
     '            return (paths[0] if paths else os.path.join(journal, "ghost.md")), ""',
     "memory: wl/NNNN 指向不存在的记录被拒绝"),
    ("memory", "清单的 upload 一律当 true",
     '                if low in ("true", "yes", "1", "是", "开"):\n'
     '                    header["upload"] = True',
     '                if True:\n                    header["upload"] = True',
     "memory: upload:false 的工作区被跳过"),
    ("memory", "清单渲染时丢掉 `→ id:`",
     '        out.append(f"- {it[\'ref\']}  {it[\'title\']}  →  id: {it[\'id\']}")',
     '        out.append(f"- {it[\'ref\']}  {it[\'title\']}")',
     "memory: 再 publish 时保留手写的 id"),
    ("memory", "publish 不保留手写的 id",
     '        it["id"] = old_ids.get(it["ref"], it["id"])',
     "        pass",
     "memory: 再 publish 时保留手写的 id"),
    ("memory", "publish 的 upload 默认变成 true",
     '    upload = bool(args.upload) if args.upload is not None else bool(old["upload"] or False)',
     '    upload = bool(args.upload) if args.upload is not None else True',
     "memory: publish 默认 upload: false"),
    ("memory", "collect 不再按清单摘要跳过",
         '        if isinstance(st, dict) and st.get("digest") == digest and st_fb == fb_digest:\n'
         '            skipped.append(f"{name}（清单没变）")\n'
         '            continue',
         '        if False:\n'
         '            skipped.append(f"{name}（清单没变）")\n'
         '            continue',
         "memory: 幂等靠 .state.json 里的清单摘要"),
    ("memory", "collect 每次都往名册里写点会变的东西",
     '    if registry_dirty and not args.dry_run:\n        save_registry(memory, registry)',
     '    if not args.dry_run:\n'
     '        registry["_touched"] = str(_dt.datetime.now().timestamp())\n'
     '        save_registry(memory, registry)',
     "memory: collect 幂等"),
    ("memory", "collect 改写工作区的清单",
         '        text = read_raw(memory_manifest_path(ws))',
         '        text = read_raw(memory_manifest_path(ws))\n'
         '        if not args.dry_run:\n'
         '            write_raw(memory_manifest_path(ws), "clobbered\\n")',
         "memory: collect 绝不改写工作区的清单"),
    ("memory", "cited-by 直接覆盖而不是累计",
     '                entry["cited_by"] = sorted(set(existing[0]["cited_by"]) | {name})',
     '                entry["cited_by"] = [name]',
     "memory: 同一领域的同名 id 是「被别的工作区引用」"),
    ("memory", "add 不再查重复 id",
     '    if any(e["id"] == eid for e in load_memory_entries(memory)):',
     "    if False:",
     "memory: 重复 id 被拒绝（id 全局唯一）"),
    ("memory", "跨工作区同名 id 不再算冲突",
     "                if other:\n"
     '                    problems.append(f"{name}: id `{eid}` 已被分册 `{other[0][\'volume\']}` 占用"',
     "                if False:\n"
     '                    problems.append(f"{name}: id `{eid}` 已被分册 `{other[0][\'volume\']}` 占用"',
     "memory: 两个工作区发布同名 id 被拒绝"),
    ("memory", "候选不再被记下来",
     '    cands = load_candidates(memory)\n    if ws in cands:\n        return ""',
     '    cands = load_candidates(memory)\n    if True:\n        return ""',
     "memory: 有清单但没登记的工作区被记成候选（只提示）"),
    ("memory", "publish 不清掉候选",
     "    cands = load_candidates(memory)\n"
     "    if cands.pop(root, None) is not None:\n"
     "        save_candidates(memory, cands)",
     "    cands = load_candidates(memory)",
     "memory: publish 登记后候选里就不再有它"),
    ("memory", "lint 不再比对索引与正文",
     "        have = read(ipath)\n        if have != want:\n            want_ids = set(",
     "        have = read(ipath)\n        if False:\n            want_ids = set(",
     "memory: 索引与正文不一致报 ERROR"),
    ("memory", "lint 不再管 inferred 混进索引",
     '            if memory_source_tier(e["source"]) == "inferred" and re.search(',
     "            if False and re.search(",
     "memory: manual:inferred 出现在索引里是 ERROR"),
    ("memory", "lint 不再查 cited-by",
         '        for c in e["cited_by"]:\n'
         '            st = registry_state(registry, c)\n'
         '            if st == "unknown":',
         '        for c in e["cited_by"]:\n'
         '            st = registry_state(registry, c)\n'
         '            if False:',
         "memory: cited-by 引用不存在的工作区是 ERROR"),
    ("memory", "lint 不再查分册标题与文件名",
     "        elif domain not in m.group(1):",
     "        elif False:",
     "memory: 分册标题与文件名不一致是 WARN"),
    ("memory", "lint 不再查近似重复",
     "            if s >= MEMORY_DUP_THRESHOLD:",
     "            if False:",
     "memory: 近似重复是 WARN"),
    ("memory", "近似重复的阈值放到够不着",
     "MEMORY_DUP_THRESHOLD = 0.7",
     "MEMORY_DUP_THRESHOLD = 2.0",
     "memory: 近似重复是 WARN"),
    ("memory", "lint 不再查硬上限",
     "        if size > MEMORY_INDEX_HARD_CHARS:\n            rep.add",
     "        if False:\n            rep.add",
     "memory: 硬上限在 lint 里是 ERROR"),
    ("memory", "index --check 不再报不一致",
     '        if have != want:\n            print(f"ERROR: {MEMORY_INDEX_NAME} 与正文分册不一致（跑 `memory index` 重建）")',
     '        if False:\n            print(f"ERROR: {MEMORY_INDEX_NAME} 与正文分册不一致（跑 `memory index` 重建）")',
     "memory: index --check 在不一致时非零退出"),
    ("memory", "index 不再报硬上限",
     "\n    if size > MEMORY_INDEX_HARD_CHARS:",
     "\n    if False:",
     "memory: 索引超硬上限报错"),
    ("memory", "collect 不再提醒重建索引",
     '    if changed and not args.dry_run:\n'
     '        print("  提示：跑 `memory index` 重建索引（索引是生成物，collect 不代劳）")',
     '    if False:\n        print("  提示")',
     "memory: collect 提醒索引要重建"),
    ("memory", "status 不再铺开名字、一律给路径",
     '              f"{gone}{\'  \' + ws if args.verbose else \'\'}")',
     '              f"{gone}  {ws}")',
     "memory: status 只列工作区名字、不铺满路径"),
    ("memory", "search 忽略 --include-personal",
     "    for e in load_memory_entries(memory, include_personal=args.include_personal):",
     "    for e in load_memory_entries(memory, include_personal=False):",
     "memory: --include-personal 才检索 personal"),
    ("memory", "search 默认连 retired 一起搜",
     '    states = ("active", "stale", "retired") if args.include_retired else ("active", "stale")',
     '    states = ("active", "stale", "retired")',
     "memory: retired 默认搜不到"),
    ("memory", "add 忽略 --personal",
     '             "cited_by": [], "body": [" ".join(args.text.split())], "personal": args.personal,',
     '             "cited_by": [], "body": [" ".join(args.text.split())], "personal": False,',
     "memory: personal 默认不检索"),
    ("memory", "`<工作区>/wl/NNNN` 不再核到清单",
     '        if any(it["ref"] == ref for it in parsed["items"]):',
     "        if False:",
     "memory: `<工作区>/wl/NNNN` 来源核到那份发布清单"),
    ("memory", "dream 不再查占位符",
     "        if MEMORY_DREAM_SLOT in s:",
     "        if False:",
     "dream: 没填的骨架被拒绝写回"),
    ("memory", "dream 不再查断言有没有回指",
     "        elif not dream_record_links(s):",
     "        elif False:",
     "dream: 断言不带回指被拒绝"),
    ("memory", "dream 不再查死链",
     "    _check_links(root or os.path.dirname(path), path, rep)",
     "    pass",
     "dream: 来源记录被删后 --check 变红"),
    ("memory", "dream 不再拦填过的骨架",
     "        if MEMORY_DREAM_SLOT not in old:",
     "        if False:",
     "dream: 骨架看起来填过时不覆盖"),
    ("memory", "dream accept 跳过校验直接写",
     "    dream_validate(root, src, rep)\n    if rep.errors():",
     "    if rep.errors():",
     "dream: 没填的骨架被拒绝写回"),
    ("memory", "dream 不再认已收敛的记录",
     "    return dream_record_links(read(path))",
     "    return []",
     "dream: 已收敛的记录不再重复挑出来（标记生效）"),
    ("memory", "inbox 不再查单条上限",
     "    if len(body_bytes) > MEMORY_INBOX_ITEM_MAX_BYTES:",
     "    if False:",
     "inbox: 单条超上限被拒绝"),
    ("memory", "inbox 不再查条数上限",
     "    if len(items) >= MEMORY_INBOX_MAX_ITEMS:",
     "    if False:",
     "inbox: 条数到顶后写满拒绝"),
    ("memory", "inbox 不再忽略半截的 .tmp",
     '        if name.endswith(".tmp") or os.path.islink(path) or not os.path.isfile(path):',
     "        if os.path.islink(path) or not os.path.isfile(path):",
     "inbox: 读到 .tmp 半截文件时当它不存在"),
    ("memory", "inbox 用文本模式直接写（不先临时名再 rename）",
         '    tmp = os.path.join(d, f".{name}.{os.getpid()}.tmp")\n'
         '    with open(tmp, "wb") as fh:\n'
         '        fh.write(data)\n'
         '    os.replace(tmp, path)', 
         '    with open(path, "w", encoding="utf-8") as fh:\n'
         '        fh.write(text)',
         "inbox: 正文与投进去的一模一样（二进制写，不翻译换行；头部之外不多不少）"),
    ("memory", "inbox take 不删原件",
     '    try:\n        os.remove(path)\n    except FileNotFoundError:\n        return False\n    return True',
     '    try:\n        pass\n    except FileNotFoundError:\n        return False\n    return True',
     "inbox: 转移之后原件被删掉"),
    ("memory", "inbox take 不搬原文",
         '            if span:\n'
         '                insert_at_end_of_section(lines, span[1], span[2], payload)\n'
         '                return "".join(lines)\n'
         '            return (body.rstrip("\\n") + nl + nl + "## 来源（信箱）" + nl + nl\n'
         '                    + "".join(payload[1:]))',
         '            if span:\n'
         '                return "".join(lines)\n'
         '            return body.rstrip("\\n") + nl',
         "inbox: 信箱原文被搬进记录（原样，不重新表述）"),
    ("memory", "sweep 不 --apply 也删",
     "    if not args.apply:\n"
     '        print("（默认只报告；确认后加 `--apply` 才真删）")\n'
     "        return 0",
     "    if False:\n        return 0",
     "inbox: sweep 默认只报告"),
    ("memory", "inbox count 多打印几个字",
     "    print(len(_inbox_items(memory_root(args.memory))))",
     '    print(f"共 {len(_inbox_items(memory_root(args.memory)))} 条")',
     "inbox: count 的第一行就是一个整数"),
    ("memory", "promote 只看后两条条件",
     "    return all(m[1] for m in marks), marks",
     "    return marks[3][1] and marks[4][1], marks",
     "promote: 三条件全满足的才被列出来"),
    ("memory", "promote 少记一条判据",
     '    marks.append(("已真实执行过", executed, entry["source"] or "(无来源)"))',
     "    pass",
     "promote: 三条判据"),

    # ── memory 续：`memory add` 的位置参数顺序（根在正文之前）──────────────────
    # 这一对不变量必须同时成立：**根在前是有效的**，且**旧写法要被拦下**——
    # 旧写法下 `text` 收到的是路径，而 manual 档根本不看根，于是它会静默写成正文。
    ("memory", "memory add 的根目录又挪回正文之后",
     '    _add_common(p)\n    _add_root(p)\n'
     '    p.add_argument("text", help="一句话教训（症状 → 根因 → 做法）")',
     '    p.add_argument("text", help="一句话教训（症状 → 根因 → 做法）")\n'
     '    _add_common(p)\n    _add_root(p)',
     "memory: the root argument comes before the text, and it is honoured"),
    ("memory", "防呆判据又去用 abspath 之后的值（于是永远不触发）",
     "    if _looks_like_path(raw_text) and not _looks_like_path(raw_root):",
     "    if _looks_like_path(raw_text) and not _looks_like_path(root):",
     "memory: the old order is refused instead of silently storing the path"),

    # ── memory 续：升格（条件③看跨天 + scaffold 先红后绿）────────────────────
    # 这一组钉的是 `0034` 量出来的洞：`hits` 是"检索命中过"，为了验证门禁搜两次就能凑够，
    # 所以门槛必须落在**日子**上；而骨架的"先红"是它的定义性质，不能悄悄变绿。
    ("memory", "条件③又只看命中次数（同一天搜两次也算复发）",
     "    repeat = cited >= MEMORY_PROMOTE_CITES or len(days) >= MEMORY_PROMOTE_DAYS",
     "    repeat = cited >= MEMORY_PROMOTE_CITES or hits >= MEMORY_PROMOTE_HITS",
     "memory: 同一天命中 9 次**不算**重复需求（次数能被验证动作凑出来）"),
    ("memory", "命中时不再记下『哪一天』",
     "            days.append(day)",
     "            pass",
     "memory: 同一天命中两次只记一个日子"),
    ("memory", "生成的骨架不再先红（缺东西也返回 0）",
     '        print("\\\\n补完之后再跑一次：python selftest.py")\n        return 1',
     '        print("\\\\n补完之后再跑一次：python selftest.py")\n        return 0',
     "memory: 骨架生成出来就是红的，并指出缺哪样"),
    ("memory", "骨架默认进模型目录（半成品也能被模型捡走）",
     'description: __DESC__\ndisable-model-invocation: true',
     'description: __DESC__',
     "memory: 骨架默认关着（frontmatter 的 disable-model-invocation），避免半成品进模型目录"),
    # ── 信箱的并发窗口（2026-10-15：全量一轮里抓到 `[WinError 2] …payload-5.md`）────
    # `inbox list` / `take` / `sweep` 都是"先列目录、再逐条读或删"，中间没有原子性；
    # 并发的取件正好能在这个窗口里把条目删掉。窗口只有几十微秒（四路并行 240 轮才撞到
    # 3 次），所以自测那边是**把窗口拉开**验的（`_selftest.py` 的 11b 段）。下面每条各拆掉
    # 一处兜底，让对应的那条判据变红。
    ("memory", "列属性那处的兜底不再认 FileNotFoundError（等于退回没有兜底）",
     '        except FileNotFoundError:\n            # "列目录"与"读属性"之间没有原子性',
     '        except ZeroDivisionError:\n            # "列目录"与"读属性"之间没有原子性',
     "inbox: 列目录之后被取走的那条不算出错"),
    ("memory", "列目录之后被取走的条目又当成一条真消息（存在性检查没了）",
     '    if not os.path.isfile(path):\n        return None\n    try:\n        return inbox_read(path)',
     '    if False:\n        return None\n    try:\n        return inbox_read(path)',
     "inbox: list 撞上刚被取走的条目时跳过去"),
    ("memory", "取件撞上被取走的条目时不再算「找不到」（退出码退回 2）",
     "        print(f\"ERROR: `{item['name']}` 刚被别的进程取走了（`inbox list` 再看一眼）\")\n"
     "        return 1",
     "        print(f\"ERROR: `{item['name']}` 刚被别的进程取走了（`inbox list` 再看一眼）\")\n"
     "        return 2",
     "inbox: take 撞上刚被取走的那条时说"),
    ("memory", "删除条目时不再容得下「已经被别人取走」（sweep 那一步会带走整条命令）",
     '    except FileNotFoundError:\n        return False\n    return True',
     '    except ZeroDivisionError:\n        return False\n    return True',
     "inbox: sweep 报告与删除两步都容得下"),
    ("memory", "取件的收尾不再容得下「已经被别人取走」（又去裸删）",
     '    if not _remove_inbox_item(item["path"]):\n        # 我们读完正文、记录也建好之后',
     '    if False:\n        # 我们读完正文、记录也建好之后',
     "inbox: take 的收尾撞上"),

    # ── config：项目配置文件（三层优先级：命令行 > .config.json > 内置默认）──────────
    # 这一相的核心不变量就是那条优先级。下面几条各破坏它的一面。
    ("config", "配置文件里的 mode 不再标成来自文件",
     "            cfg.src[CFG_MODE] = SRC_FILE",
     "            cfg.src[CFG_MODE] = SRC_DEFAULT",
     "config: mode comes from the file"),
    ("config", "配置文件里的 mode 干脆不生效",
     "        raw = data[CFG_MODE]",
     "        raw = None",
     "config: mode comes from the file"),
    ("config", "配置文件里的 snapshotEntries 不再标成来自文件",
     "            cfg.src[CFG_SNAPSHOT_ENTRIES] = SRC_FILE",
     "            cfg.src[CFG_SNAPSHOT_ENTRIES] = SRC_DEFAULT",
     "config: snapshotEntries comes from the file"),
    ("config", "配置文件的路径判断反过来（存在反而当不存在）",
     "    if not os.path.isfile(cfg.path):",
     "    if os.path.isfile(cfg.path):",
     "config: a missing config file is not an error"),

    # ── lesson：卡式经验条目（缩进形制 / check 配对）────────────────────────────
    # 这一相守的是"卡式条目是**缩进 2 空格**的子条目"与"触发 / 验证必须成对"两条形制。
    # 前者错了会让 `check` 的正则认不出来（静默失效），后者错了会让半边线索溜进门禁。
    ("lesson", "卡式子条目缩进从 2 空格缩成 1（check 的正则就认不到了）",
     'f"  - 触发：{trig}{nl}"', 'f"  -触发：{trig}{nl}"',
     "lesson add writes the 触发 sub-item with a 2-space indent"),
    ("lesson", "check 不再管触发 / 验证是否成对",
     'if has_t != has_v:', 'if False:',
     "check warns when a card has 触发 but no 验证"),
    ("lesson", "空白卡式值不再被拒绝（会写出空子条目）",
     "        if not raw.strip():", "        if False:",
     "lesson add rejects a whitespace-only --trigger"),
    ("card", "卡式条目的「别再来」不再进不适用条件",
     '    if avoid:\n        bounds.append(f"别再来：{avoid}")',
     '    if False:\n        bounds.append(f"别再来：{avoid}")',
     "the lesson's 别再来 is projected into 不适用条件", CARD_SRC),

    # ── gates：两道门禁（`check --lint` 合并 / 默认不合并 / 提示 / 合并的两处易错点）──
    # 这一相的核心不变量：**默认判决不变，合并只在显式要求时发生**，且合并后
    # 去重与降级下标都不能坏。下面几条各破坏它的一面。
    ("gates", "check --lint 不再合并内容门禁",
     "        if args.lint:\n            rep.merge(",
     "        if False:\n            rep.merge(",
     "gates: check --lint takes the content gate's verdict"),
    ("gates", "结构门禁通过时不再提第二道门",
     '        print("（这是结构门禁。内容质量是另一道：加 `--lint` 一起跑，或单跑 `lint`）")',
     "        pass",
     "gates: a passing check points at the second gate"),
    ("gates", "提示连 `--quiet` 都不认",
         '    if not getattr(args, "quiet", False):\n'
         '        for text in built[0].notes if built else ():\n'
         '            print(text)\n'
         '        if not args.lint and code == 0:',
         '    if True:\n'
         '        for text in built[0].notes if built else ():\n'
         '            print(text)\n'
         '        if not args.lint and code == 0:',
         "gates: --quiet silences the pointer"),
    ("gates", "合并时不再去重（同一件事报两遍）",
     "            if row in self._seen:",
     "            if False:",
     "gates: a finding both gates report is listed once, not twice"),
    ("gates", "合并时丢掉降级下标（渐进原则静默失效）",
     "            if i in other.legacy_rows:\n                self.legacy_rows.add(len(self.rows) - 1)",
     "            if False:\n                self.legacy_rows.add(len(self.rows) - 1)",
     "gates: the gradual rule survives the merge (a legacy finding stays info)"),
    ("gates", "新增一条降级规则却不进中央清单",
     'RULE_TITLE = "标题形制"',
     'RULE_TITLE = "标题形制"\nRULE_UNLISTED = "没进清单的新规则"',
     "gates: the central list names `RULE_UNLISTED`"),
    ("gates", "降级调用不再传常量（硬编码规则名）",
     '                                       + " / ".join(VERIFY_WORDS[:12]) + " 之一，h2–h4 都算）")\n'
     '            _mark_legacy(rep, i, legacy_rec, RULE_VERIFY)',
     '                                       + " / ".join(VERIFY_WORDS[:12]) + " 之一，h2–h4 都算）")\n'
     '            _mark_legacy(rep, i, legacy_rec, "验证小节")',
     "gates: every _mark_legacy call passes a RULE_* constant, never a literal"),
    ("gates", "给一条「没有根」的命令偷偷加上根",
     '    p = psub.add_parser("suggest", help="列出够格升格的条目")\n    _add_memory(p)',
     '    p = psub.add_parser("suggest", help="列出够格升格的条目")\n    _add_root(p)\n    _add_memory(p)',
     "gates: the ROOT matrix lists exactly the 没有根-root commands"),
    ("gates", "把 `lesson` 父级的根删掉（该命令族就没有根了）",
     '    _add_root(p_lesson)\n',
     '',
     "gates: the ROOT matrix lists exactly the 父级-root commands"),
    ("gates", "`--root` 选项改名（有位置根的地方就没有根选项了）",
     '    p.add_argument("--root", dest="root_opt", default=None, metavar="P",',
     '    p.add_argument("--root-path", dest="root_opt", default=None, metavar="P",',
     "gates: `--root` exists exactly where a positional root does"),
    ("gates", "给一条没有工作区根的命令也发 `--root`（空承诺）",
     '    p = psub.add_parser("suggest", help="列出够格升格的条目")\n    _add_memory(p)',
     '    p = psub.add_parser("suggest", help="列出够格升格的条目")\n    _add_common(p)\n    _add_memory(p)',
     "gates: `--root` exists exactly where a positional root does"),

    # ── links：链接目标的三种写法（裸 / 尖括号 / %转义）走同一套解析 ──────────────
    # 这一相的核心不变量：**写出来的、检查得到的、折叠得动的，必须是同一批目标**。
    # 下面每条各破坏它的一面（旧口径 `\\]\\(([^)\\s]+)\\)` 就是三处一起错的那版）。
    ("links", "链接匹配退回排除空白的旧口径",
     'LINK_RE = re.compile(r"\\]\\(\\s*(<[^>\\n]*>|[^)\\n]*?)\\s*\\)")',
     'LINK_RE = re.compile(r"\\]\\(([^)\\s]+)\\)")',
     "links: a dead link with a space in a bare target is reported"),
    ("links", "尖括号目标不再去括号",
     "    if len(t) >= 2 and t.startswith(\"<\") and t.endswith(\">\"):",
     "    if False:",
     "links: a dead link inside angle brackets is reported"),
    ("links", "链接目标不再做百分号解码",
     "    return unquote(t)",
     "    return t",
     "links: an existing file is not a dead link, in either written form"),
    ("links", "index compact 又对解析不出的行硬取 group(1)",
     "            if m is not None:",
     "            if True:",
     "links: index compact survives a row it cannot parse"),

    # ── mode：精细度档位（提示行里的"当前"必须是生效档位）───────────────────────
    ("mode", "mode 的提示行又拿内置默认当当前值",
     "（当前 {cur}）",
     "（当前 {MODE_DEFAULT}）",
     "mode's hint line names the effective tier, not the built-in default"),

    # ── 占号对账（第三轮复查 N-A / N-B）────────────────────────────────────────
    # 这一组护的是"编号永不复用"这条承诺：改名不改正文会让记录被自己的 `check` 判 ERROR
    # （N-A 后半），只看名字的 dry-run 会预报出被别的 slug 占着的号（N-B）。下面三条各破坏
    # 其中一面。
    # 它们挂在 `numbering` 相上 —— 那几条断言 2026-10-15 从 `main()` 内联段搬进了
    # `numbering_phase()`，因为内联断言本脚本跑不到（见 `PHASES` 上的说明）。
    # 头一条 2026-10-15 换过锚点：对账规则本身也从"名字最小的留下"改成了"只剩我一份才算数"
    # （旧规则在并发下漏掉一整边：先收工的只看得见自己、后到的若名字排前面也会留下 —— 自测
    # 里真冒出来过一次 `[1, 2, 3, 4, 5, 5]`）。所以这里改回**旧规则**，红的是那条新断言。
    ("numbering", "占号对账退回「名字最小的留下」（并发下先收工的会被顶掉）",
     "        if len(peers) < 2:",
     "        if len(peers) < 2 or os.path.basename(path) == peers[0]:",
     "先收工的那一份留下，后到的让路"),
    ("numbering", "对账改名之后不再改正文首行的篇号",
     "        if not renumber_body(dst, target):",
     "        if not True:  # 变异：改名不改正文",
     "路同号：正文首行的篇号 == 文件名里的号"),
    ("numbering", "new --dry-run 又只看名字、不看号",
     "        while (os.path.exists(_record_name(journal, n, slug)) or n in taken_numbers(journal)) \\\n"
     "                and n - num < NEW_RECORD_TRIES:",
     "        while (os.path.exists(_record_name(journal, n, slug))) \\\n"
     "                and n - num < NEW_RECORD_TRIES:",
     "new --dry-run 的篇号 == 真跑的篇号"),
    # 2026-10-15 性能复核：`heading_level()` 从"每行现编正则"改成"先短路、再用预编译的
    # `_SECTION_HEADING_RE`"。这一改只有"行尾空白与换行要不要去掉"这一处语义，去掉它
    # 就是另一条解析结果（`(2, '验证  ')` 而不是 `(2, '验证')`），红的正是新加的那条
    # "两条标题正则各管各的"。
    ("numbering", "小节标题不再去掉行尾空白与换行",
     '_SECTION_HEADING_RE = re.compile(r"^(#{1,6})[ \\t]+(.*?)[ \\t]*\\r?\\n?$")',
     '_SECTION_HEADING_RE = re.compile(r"^(#{1,6})[ \\t]+(.*?)$")',
     "两条标题正则各管各的"),

    # ---- 2026-10-17 复核 M-2 补的三相 -------------------------------------------------
    #
    # 这三相的**逻辑正是本轮改的**，而它们此前一条变异都没有：`PHASES` 里没登记，
    # `test:plugin` 报的"96 mutations"也就从不经过它们。H-1（「执行」小节重复开头）
    # 就是这么活下来的 —— 不是没人写断言，是没有任何东西**逼着**断言去死一次。
    #
    # 1) 归档目录的篇数不再排除日期式（H5 的原样回退）。旧行为拿 `NUM_NAME_RE` 自己
    #    匹配磁盘文件名，把 `2026-09-01-a.md` 读成「编号 2026」，`set()` 一去重恒为 1，
    #    于是一份**正确**的表被判「标着 3 篇，磁盘上是 1 篇」。
    ("archive_dir_index", "归档目录的篇数又把日期式读成「编号 2026」",
     '        on_disk = sorted({n for n in (name_number(f) for f in os.listdir(stage_dir))\n'
     '                          if n is not None})',
     '        on_disk = sorted({(re.match(r"(\\d+)", f) or [None, "0"])[1]\n'
     '                          for f in os.listdir(stage_dir)\n'
     '                          if re.match(r"(\\d+)", f)})',
     "a date-form-only stage directory is not counted against its table row"),

    # 2) 反向核对整条拆掉（磁盘上有目录、表里没那一行，从此没人报）。
    #    这条守的是"整个阶段漏登记"—— 表→磁盘那两条核对对它一声不吭。
    ("archive_index", "反向核对被拆掉（漏行不再报）",
     "            if has_records:",
     "            if False:",
     "a stage directory with no row in the table is reported (reverse check)"),

    # 3) 投影器「执行」小节那道前缀守卫退回**带 `…` 去比**（H-1 的原样回退）。
    #    摘要以 `…` 结尾时前缀永远比不中，于是整段正文被追加在摘要后面，开头出现两遍。
    #    靶子在 `card_phase` 的 `0004-longsentence`（第一句超 200 字、尾巴被补 `…`）。
    ("card", "「执行」去重又带着截断的 `…` 去比前缀",
     '                n_sum = _trim_ellipsis(norm_ws(head["执行"]))',
     '                n_sum = norm_ws(head["执行"])',
     "the 执行 section never says its opening twice (truncated `…` included)",
     CARD_SRC),

    # 4) 写盘准入退回"不查撞名"（H-2 的原样回退）：读的一侧照旧打 `[skip]`，
    #    写的一侧按同一个文件名 `os.replace()` —— 于是"报着跳过、实际覆盖"。
    ("card", "写盘又不查同名外来卡（撞名即覆盖）",
     '    ptr = os.path.join(card_dir, f"{slug}.pointer.md")\n'
     '    if not os.path.exists(ptr) or is_our_card(ptr):\n'
     '        return slug, ""',
     '    ptr = os.path.join(card_dir, f"{slug}.pointer.md")\n'
     '    if True:\n'
     '        return slug, ""',
     "a foreign card sitting on one of our names is not overwritten",
     CARD_SRC),

    # 5) 第三条路退回"只看后缀"（H-2b 的原样回退）：`index_rows()` 又不认 tags，
    #    于是 `--index-only --write` 把 `source_status: stale` 写进别人的卡。
    ("card", "索引与陈旧标记又不认自家卡（外来卡被写 stale）",
     '        if not is_our_card(p, t):\n'
     '            skipped.append(fn[: -len(".pointer.md")])\n'
     '            continue\n',
     '',
     "a foreign card with a dangling source is not stamped stale",
     CARD_SRC),

    # 6) 兄弟路径的守卫又拆掉（轮九的原样回退）：一个叫 `*.pointer.md` 的**目录**
    #    就能让 `--all --write` 抛 PermissionError、整次投影中止、stdout 为空。
    ("card", "同名目录又让整次投影中止（少一道 isfile 守卫）",
     '            if not os.path.isfile(p):\n'
     '                continue\n'
     '            body = read(p)',
     '            body = read(p)',
     "a directory named like a card does not abort the whole projection",
     CARD_SRC),

    # 7) 另一侧的同名守卫也拆掉（与上一条**对称**：两条路各钉一条，
    #    免得下次又只修一边 —— 轮八修 `index_rows()` 时正是漏了 `existing_cards()`）。
    ("card", "索引那条路的同名守卫也拆掉（整目录被读成卡）",
     '        if not os.path.isfile(p):\n'
     '            continue                      # 目录/断链叫这个名字：既不是卡，也没什么可报的\n',
     '',
     "nor does the index path list it",
     CARD_SRC),

    # 8) 三处枚举点的**第三处**（轮十）：卡目录那两处前两轮各补了一道守卫，
    #    而 `--all` 那条路上的**分册扫描**只按 `.md` 后缀收 —— 一个叫 `01-weird.md`
    #    的目录让整次投影中止（rc=1、裸 `PermissionError`）。轮十的穷举扫描漏了它。
    ("card", "分册扫描又只按后缀收（同名目录让整次投影中止）",
     '                    if not os.path.isfile(lp_):\n'
     '                        continue\n',
     '',
     "a directory named like a lesson volume does not abort the projection",
     CARD_SRC),

    # 9) 切剩余正文时又把被剥掉的句号留在行首（2026-10-17 复核的原样回退）：
    #    `_trim_ellipsis` 剥掉了句末「。」，切片长度却按剥掉之后的算 —— 于是卡里多出
    #    一行「。 后半句」。靶子在 `card_phase` 的 `0005-two-sentences`（正文两句、
    #    第一句带句号且后面还有正文；其余夹具都是单句，测不到）。
    ("card", "剩余正文又把句号留在行首（卡里多一行「。 …」）",
     '                    rest = n_body[len(n_sum):].lstrip("。…").lstrip()',
     '                    rest = n_body[len(n_sum):].lstrip()',
     "no card body line starts with a stray 「。」（摘要后的句号不该被切成新行）",
     CARD_SRC),

    # 10) 索引「源」列又截断（2026-10-17 复核的原样回退）：真容器 50 行里 46 行被切到
    #     34 字节，`work_log/0108-review-r6-half-fixe…` 拼不回记录 —— 只看索引定位不到。
    ("card", "索引的源列又被截断（截出来的路径拼不回记录）",
     '        src = (r["source"] or "（未标）") + (" [源未找到]" if r["stale"] else "")',
     '        src = _clip(r["source"] or "（未标）", 34) + (" [源未找到]" if r["stale"] else "")',
     "the index's 源 column is not truncated (the index alone locates the record)",
     CARD_SRC),
]


def load_module(path: str, tag: str):
    spec = importlib.util.spec_from_file_location(f"rv_{tag}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def unmutated_labels(selftest_path: str, pre_root: str) -> tuple[set[str], list[str]]:
    """跑一遍**未变异**的自测，收下它打印的每一条断言标签。

    为什么要走"跑真入口的子进程"而不是 import 进来调相：标签就是它**打印的那一行**，
    判据与下面 `expect in label` 的匹配方式同源；顺带用上自测自己的夹具播种和 `--root`
    纪律，不必在这里重搭一套（重搭的那一套一旦与自测脱节，检查本身就不可信了）。

    返回（标签集合, 问题清单）。退出码非 0 时问题清单里会写明"未变异的自测本身就没过"——
    那时标签是**残缺**的，调用方不能把"找不到"直接当成"断言没执行"。
    """
    os.makedirs(pre_root, exist_ok=True)
    # `PYTHONDONTWRITEBYTECODE`：子进程同样不能在被执行的技能脚本旁边留 `__pycache__`
    # （本进程那句 `sys.dont_write_bytecode` 不会继承给子进程）。
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    try:
        proc = subprocess.run([sys.executable, selftest_path, "--root", pre_root],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=1800)
    except (OSError, subprocess.SubprocessError) as exc:   # 起不来或超时，都算"这一关没过"
        return set(), [f"未变异的自测没跑起来：{type(exc).__name__}: {exc}"]
    labels = {line[6:].strip() for line in proc.stdout.splitlines()
              if line.startswith("PASS  ")}
    problems: list[str] = []
    if proc.returncode != 0:
        fails = [line.strip() for line in proc.stdout.splitlines() if line.startswith("FAIL  ")]
        problems.append(f"未变异的自测本身就没过（exit {proc.returncode}，"
                        f"{len(fails)} 条失败）——先让它全绿再看变异")
        problems.extend("  " + f for f in fails[:5])
    return labels, problems


def phase_ranges(selftest_src: str) -> dict[str, tuple[int, int]]:
    """每个**登记过的相**函数的行区间（1-based 闭区间）。"""
    tree = ast.parse(selftest_src)
    want = set(PHASES.values())
    return {n.name: (n.lineno, n.end_lineno or n.lineno)
            for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want}


def top_level_ranges(selftest_src: str) -> list[tuple[str, int, int]]:
    """所有顶层函数的行区间：用来回答"这个字样落在哪个函数里"。"""
    tree = ast.parse(selftest_src)
    return [(n.name, n.lineno, n.end_lineno or n.lineno)
            for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def phase_templates(selftest_src: str, ranges: dict[str, tuple[int, int]]) -> list[re.Pattern]:
    """登记过的相里所有"能拼出标签"的字符串模板，插值处换成 `.*`。

    为什么需要这一步：标签不都是字面量。`f"gates: the central list names `{name}`"` 在
    未变异时生成的是**别的**规则名，变异之后才轮到 `RULE_UNLISTED` —— 这种"动态标签"既
    问不出"字面量在不在相里"，也问不出"未变异时标签在不在"（第一次跑起飞前检查就被它
    绊了一下：差点把一条**一直好好的**变异判成不可达）。

    只收字面部分 ≥ 8 个字符的模板：`f"{x}"` 这种纯插值转成正则就是 `.*`，能匹配一切，
    留着只会把这一关废掉。
    """
    tree = ast.parse(selftest_src)
    want = set(PHASES.values())
    patterns: list[re.Pattern] = []
    for node in tree.body:
        if not (isinstance(node, ast.FunctionDef) and node.name in want):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.JoinedStr):
                parts: list[str] = []
                literal = 0
                for value in sub.values:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        parts.append(re.escape(value.value))
                        literal += len(value.value)
                    else:
                        parts.append(".*")
                if literal >= 8:
                    patterns.append(re.compile("".join(parts), re.S))
            elif (isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                    and len(sub.value) >= 8):
                patterns.append(re.compile(re.escape(sub.value), re.S))
    return patterns


def reachability(expect: str, labels: set[str], selftest_src: str) -> str:
    """这条变异的期望字样**有没有可能**被某条登记过的相产生？返回 ""（可能）或一句原因。

    四种情形，按可信度排：
      1. 未变异的相里**已经**有这么一条标签 —— 最直接；
      2. 字样就写在某个登记过的相的源码里（这次的值不同而已）；
      3. 以上都不是，但字样出现在 `_selftest.py` 的**相之外**（多半是 `main()` 里）——
         就是 2026-10-15 那个洞：驱动跑不到那里；
      4. 相里的模板也拼不出来 —— 期望字样多半写错了。
    """
    if any(expect in label for label in labels):
        return ""
    hits = [i + 1 for i, line in enumerate(selftest_src.split("\n")) if expect in line]
    ranges = phase_ranges(selftest_src)
    if any(any(a <= n <= b for a, b in ranges.values()) for n in hits):
        return ""
    if hits:
        owner = next((name for name, a, b in top_level_ranges(selftest_src) if a <= hits[0] <= b),
                     "模块层")
        return f"字样只出现在相之外：`{owner}()` 第 {hits[0]} 行"
    if any(pattern.search(expect) for pattern in phase_templates(selftest_src, ranges)):
        return ""
    return "字样既不在任何相的源码里，也不在任何标签里（期望字样写错了？）"


# 真实记忆库里不参与指纹的东西。`.git` 会被提交改变（与本次运行无关）；
# `personal/` 与 `inbox/` 是用户自己的东西，跑驱动的这二十几分钟里用户完全可能动它们，
# 算进去只会变成假警报 —— 而金丝雀一旦会误报，就会被当成噪声关掉。
CANARY_SKIP = (".git", "personal", "inbox")


def real_memory_fingerprint() -> tuple:
    """用户**真实**记忆库的指纹（相对路径 + 大小 + mtime + 内容的 sha256）。

    为什么驱动要盯这个：**它是唯一一个故意去打断记忆根隔离的东西**。memory 相里
    「`--memory` 不再覆盖路径」与「环境变量那一档失效」两条变异，干的就是让命令找不到
    覆盖、掉到第四级默认根上。2026-10-17 就是这么漏的：0.8.0 把第四级从
    `$DSH_HOME/memory` 换成了 `<用户主目录>/dsh-lore-memory`，而 `memory_phase` 的兜底
    还停在钉 `DSH_HOME` —— **连着 9 次全量跑往用户真实库里灌了 54 条夹具工作区路径，
    一条门禁都没发现**（`npm test`、`test:plugin`、`audit` 全绿）。断言只能证明"该红的红了"，
    证明不了"没顺手改坏别人家的东西"—— 这件事得由这条金丝雀自己说。

    库不存在时返回 `None`：那种情况下要验的是"跑完仍然不存在"（别把它建出来）。
    """
    root = os.path.join(os.path.expanduser("~"), "dsh-lore-memory")
    if not os.path.isdir(root):
        return None
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in CANARY_SKIP]
        for fn in sorted(filenames):
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()
            except OSError as exc:
                digest = f"<读不到：{exc.__class__.__name__}>"
            rows.append((os.path.relpath(path, root).replace("\\", "/"), digest))
    return tuple(sorted(rows))


def main() -> int:
    ap = argparse.ArgumentParser(description="把 memory_phase 的断言逐条弄红一次")
    ap.add_argument("--root", default=os.path.join(WORKSPACE, "logs", "fixtures"),
                    help="夹具父目录（必须已存在）。默认是作者工作区顶层那个 logs/fixtures（属于"
                         "可丢弃的运行产物，不进记录容器；夹具不随包发布，所以在仓库镜像里跑"
                         "必须显式给这一项，例如 --root <pkg>/tests/fixtures）")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--phase", choices=sorted(PHASES), default=None,
                    help="only one phase (default: all)")
    ap.add_argument("--only", default=None, metavar="SUBSTR",
                    help="只跑名字里含这段字的一条/几条变异。整相跑一遍要几十分钟，"
                         "改了一处想当场确认那一条时用它（名字用 --list 看）")
    ap.add_argument("--no-preflight", action="store_true",
                    help="跳过起飞前检查（默认先跑一遍未变异的自测，确认每条变异的期望"
                         "字样真的有人记下来；找不到就当场退出，不白跑一整轮）")
    ap.add_argument("--skill-dir", default=None, metavar="DIR",
                    help="技能源所在的 scripts/ 目录。默认自动解析：先试工作区布局 "
                         "`<工作区>/.pi/skills/project-work-log/scripts`，再试镜像布局 "
                         "`<仓库>/skills/project-work-log/scripts`")
    args = ap.parse_args()

    global SKILL
    if args.skill_dir is not None:
        SKILL = os.path.abspath(args.skill_dir)

    if args.list:
        for row in MUTATIONS:
            phase, name, _old, _new, expect, src = m6(row)
            # `--only` 对列表也生效：列出来的是"这次会跑的"，不是"全部"，免得误读。
            if args.only is not None and args.only not in name:
                continue
            print(f"[{phase}] {name}\n    打在 {src} 上\n    → 期望变红：{expect}")
        return 0

    # 金丝雀的第一半：**在任何变异跑起来之前**给用户真实的记忆库拍一张指纹。
    # 这一句必须留在这儿（`--list` 之后、任何夹具与子进程之前），否则"改动前"就不是改动前了。
    canary_before = real_memory_fingerprint()

    src_path = os.path.join(SKILL, "journal.py")
    st_path = os.path.join(SKILL, "_selftest.py")
    if not os.path.isfile(src_path):
        # 报清楚"我在哪儿找过"，而不是让 open() 抛一个光秃秃的 FileNotFoundError：
        # 这个文件会被同步到另一个布局下运行，路径没解析对是它最常见的失败方式。
        print(f"ERROR: 找不到技能源：{src_path}")
        print(f"       自动解析试过：{'；'.join(SKILL_CANDIDATES)}")
        print("       用 --skill-dir <技能 scripts/ 目录> 指定。")
        return 2
    with open(src_path, encoding="utf-8", newline="") as fh:
        original = fh.read()
    with open(st_path, encoding="utf-8", newline="") as fh:
        selftest_src = fh.read()
    # 变异能打在两个源上（`journal.py` 与 `dsh-lore-card.py`），所以两份都读进来。
    # 副本目录里**两份都要在位**：`card_phase` 按 `HERE/dsh-lore-card.py` 起子进程，
    # 缺了它那一相直接跑不起来（"跑不起来"与"如期变红"是两回事，看着像通过其实什么都没验）。
    sources: dict[str, str] = {JOURNAL_SRC: original}
    for name in (CARD_SRC,):
        p = os.path.join(SKILL, name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8", newline="") as fh:
                sources[name] = fh.read()

    base = os.path.abspath(args.root)
    if not os.path.isdir(base):
        print(f"ERROR: --root 不是一个已存在的目录：{base}")
        print("       夹具是作者工作区的数据，不随包发布；在仓库镜像里跑要显式指定，例如")
        print("       python tests/reverse-verify.py --root <夹具父目录>（见 RELEASING.md 的检查点 6）。")
        return 2
    # 按 PID 隔离：同一时刻只跑一相时无所谓，但"后台跑着整相、前台再跑一相"就会撞——
    # 实测撞过（`os.makedirs` 报 FileExistsError，因为两边共用同一个目录）。
    # 夹具本来就是可再生的，按 PID 分开互不影响，跑完各自清理自己那份。
    scratch_root = os.path.join(base, f"reverse-verify-{os.getpid()}")
    shutil.rmtree(scratch_root, ignore_errors=True)
    os.makedirs(scratch_root)

    missed: list[str] = []
    broken: list[str] = []
    crashed: list[str] = []
    hits = 0
    selected = [m for m in MUTATIONS if args.phase in (None, m[0])
                and (args.only is None or args.only in m[1])]
    if args.only is not None and not selected:
        print(f"没有名字含 `{args.only}` 的变异（用 --list 看全部名字）")
        return 2
    if len(selected) != len(MUTATIONS):
        print(f"（只跑选中的 {len(selected)} 条变异）")

    # ---- 起飞前的检查：期望的那条断言，未变异时也得真有人记下来 -------------------
    #
    # 为什么（2026-10-15，第三条踩过的坑）：`expect` 是程序化匹配的字符串 —— 只有当
    # **登记过的相**记下过这个标签时，"变异之后它变红"才可能发生。断言要是内联在
    # `main()` 里（本脚本调不了那个函数：它自己解析 argv），跑完一整轮才看到
    # `MISS … 期望「…」没变红；红了 0 条`，而真实原因与自测内容无关：那条断言从头到尾
    # 没被执行过。三条占号变异就是这么白跑一轮的（见 `PHASES` 上面的说明）。
    #
    # 判据：先跑一遍未变异的自测，把标签全收进来；期望字样不在其中就当场报出来，
    # 一条变异都不用跑。这不是"没测到"，是"根本没有机会"。
    #
    # 但"不在标签里"不等于"不可达"：标签可以是拼出来的。`gates: the central list names
    # `{name}`` 在未变异时拼的是**别的**规则名，变异之后才轮到那条没登记进清单的规则 ——
    # 第一次跑这一关时它差点把一条**一直好好的**变异判成不可达。所以这里交给
    # `reachability()` 分情形判（见那个函数的说明），不是拿 `in` 硬比。
    if not args.no_preflight:
        labels, pre_problems = unmutated_labels(st_path, os.path.join(scratch_root, "preflight"))
        unreachable: list[str] = []
        for row in selected:
            phase, name, _old, _new, expect, _src = m6(row)
            if phase not in PHASES:
                unreachable.append(f"{name}：相 `{phase}` 没登记进 PHASES")
                continue
            why = reachability(expect, labels, selftest_src)
            if why:
                unreachable.append(f"{name}（相 {PHASES[phase]}）：{why} —— 期望「{expect}」")
        for p in pre_problems:
            print("[起飞前检查] " + p)
        if unreachable:
            print(f"\n[起飞前检查] {len(unreachable)} 条变异的期望字样，未变异的自测里"
                  f"没有任何断言标签含它：")
            for u in unreachable:
                print("  ! " + u)
            print("  → 这种变异**不可能**变红（不是「没测到」，是「没执行」）。最常见的原因"
                  "是断言内联在 `main()` 里：本脚本只跑 `PHASES` 登记的函数。")
            print("     把它搬进某一相、在 `PHASES` 里登记，再跑。想跳过这一关用 --no-preflight。")
            return 1

    for i, row in enumerate(selected):
        phase, name, old, new, expect, src = m6(row)
        if src not in sources:
            broken.append(f"{name}：找不到要变异的源文件 {src}（技能源目录里没有它）")
            print(f"MISS  {name}   [源文件不在：{src}]")
            continue
        original = sources[src]
        n = original.count(old)
        if n != 1:
            broken.append(f"{name}：替换源在 {src} 里出现 {n} 次（应恰好 1 次）")
            print(f"MISS  {name}   [替换源不唯一：{n} 次]")
            continue
        mutated = original.replace(old, new)

        # ---- 变异后自检：这次替换到底改到东西了没有 ------------------------
        #
        # 为什么必须有这一步（2026-10-14 加的，吃过一次亏）：
        # `count(old) == 1` **只能说明"这段文本唯一"**，不能说明"它就在你想改的那个函数里"。
        # 真实案例：`inbox 用文本模式直接写` 的 old 是原子写那四行，而 `os.replace(tmp, path)`
        # 在 JSON 状态写入器里也有一份同样的四行 —— `replace()` 改了**另一处**，inbox 的写法
        # 一点没动，于是那条变异显示"没变红"。它看起来像"自测有缺口"，其实是**变异打偏**，
        # 两者含义完全不同，却报同一个词，于是没人会去查变异体本身（那次我查了十几分钟）。
        #
        # 判据（只看局部，不要求整体变了 —— old 出现多次时整体一定变，所以整体判据没用）：
        # 取 old 左右各 CONTEXT 行，替换后这段窗口里的行必须与原来不同。
        # 打偏的替换窗口一定逐行相同（那处本来就没有 old 的结构）。
        CONTEXT = 6
        md_old, md_new = mutated, original
        if md_old == md_new:
            mistarget = "替换后与原文逐字节相同"
        else:
            ol = original.split("\n")
            nl_ = mutated.split("\n")
            pos = original.find(old)
            line0 = original.count("\n", 0, pos)
            span_old = old.count("\n") + 1
            span_new = new.count("\n") + 1
            lo = max(0, line0 - CONTEXT)
            hi_old = min(len(ol), line0 + span_old + CONTEXT)
            hi_new = min(len(nl_), line0 + span_new + CONTEXT)
            mistarget = ""
            if ol[lo:hi_old] == nl_[lo:hi_new]:
                mistarget = (f"替换落在第 {line0 + 1} 行，但那 {hi_old - lo} 行窗口"
                             f"逐行没变 —— 与 old 长得一样的那段在别处")
        if mistarget:
            broken.append(f"{name}：{mistarget}")
            print(f"MISTARGET  {name}   [{mistarget}]")
            if not args.keep:
                shutil.rmtree(os.path.join(scratch_root, f"rev{i:02d}"), ignore_errors=True)
            continue

        d = os.path.join(scratch_root, f"rev{i:02d}")
        # 副本要**照真实技能布局**建：`scripts/` 放代码、`references/` 放文档。
        # 平铺（代码直接放 rev00/）会让 `os.path.dirname(HERE)` 少一层——
        # 相里按 `../references/` 找文档的断言就会抛 FileNotFoundError，
        # 于是变异"跑不起来"而不是"如期变红"，看着像通过其实什么都没验。
        os.makedirs(os.path.join(d, "scripts"))
        os.makedirs(os.path.join(d, "references"))
        # 把**所有**技能源都照原样放进副本，只有被测的那一份换成变异后的文本：
        # 少了 `dsh-lore-card.py` 时 `card_phase` 会直接抛 FileNotFoundError ——
        # 那看着像"没变红"，其实这一相根本没跑（与"如期变红"是两回事）。
        for name_, text in sources.items():
            with open(os.path.join(d, "scripts", name_), "w", encoding="utf-8", newline="") as fh:
                fh.write(mutated if name_ == src else text)
        with open(os.path.join(d, "scripts", "_selftest.py"), "w", encoding="utf-8", newline="") as fh:
            fh.write(selftest_src)
        shutil.copyfile(
            os.path.join(os.path.dirname(SKILL), "references", "commands.md"),
            os.path.join(d, "references", "commands.md"),
        )
        fx = os.path.join(d, "fx")
        os.makedirs(fx)
        mod = load_module(os.path.join(d, "scripts", "_selftest.py"), f"m{i}")
        # 只留结论：把子进程逐条 PASS/FAIL 的打印静音，否则每跑一条变异都会倒出
        # 一整份自测输出（五十几条变异就是几万行），真正要看的那行会被埋掉。
        def _quiet(cond, label, detail="", _mod=mod):
            _mod.results.append((bool(cond), label))
        mod.ok = _quiet

        # ---- 断言求值也要包住（2026-10-14 加的，第二条踩过的坑）-----------------
        #
        # `ok(cond, label)` 的两个参数在**调用前**求值。自测里有些断言写成
        # `ok("…" in read(p), "…", read(p))` —— 一旦前置条件不成立，`read(p)` 会抛，
        # 异常在"记下这条断言"之前就冒出来，**整条相被掀掉**，后面几十条断言不再执行。
        #
        # 真实案例：`collect 改写工作区的清单` 那条变异确实让 6 条断言该红，但自测先崩在
        # `read(fb_dst)` 上，驱动只看到"相崩了"，于是把一条**本来抓得住**的变异报成
        # "不构成证据"。上面那次"基线对照"证明了崩溃来自变异（干净副本 208 条全过）。
        #
        # 修法：把"求值 + 记录"整段包进一层 `ok`，抛异常就当成**一条失败的断言**记下来
        # （文案里带上异常），相继续往下跑。这样"因为崩溃而漏掉的断言"不会再吞掉结论。
        raw_ok = mod.ok

        def _guarded(cond_factory, label, detail_factory=None, _mod=mod, _raw=raw_ok):
            # `cond` 多数是"已经算好的 bool"，但也可能是"算出来才知道"的表达式（这里两者都接）。
            try:
                cond = cond_factory() if callable(cond_factory) else cond_factory
                detail = detail_factory() if callable(detail_factory) else detail_factory
                _raw(cond, label, detail)
            except Exception as exc:                 # noqa: BLE001 - 就是要兜住一切
                _mod.results.append((False, f"{label}（断言求值就抛了：{type(exc).__name__}: {exc}）"))

        mod.ok = _guarded

        # `ok(cond, label, detail)` 的实参在**调用点**求值，所以 `ok` 再早也拦不住
        # `read(缺文件)` 抛出来的异常（2026-10-14 实测：guard 确实被调到了，异常仍从调用点
        # 冒出来 —— 参数求值发生在进入函数体之前）。真正的收口在"读文件"这个出入口：
        # 文件不在就返回一个哨兵文本，让断言自然变红，而不是把整条相掀掉。
        # 哨兵命中次数单独记账，只作为 PASS 行后面的**说明**（红的原因），不参与判定。
        raw_read = mod.read

        def _safe_read(path, *a, **kw):
            try:
                return raw_read(path, *a, **kw)
            except FileNotFoundError:
                sentinel_hits.append(str(path))
                return f"<缺文件：{path}>"

        mod.read = _safe_read
        start = len(mod.results)
        sentinel_hits: list[str] = []
        crash = ""
        try:
            getattr(mod, PHASES[phase])(fx)
        except Exception as exc:                     # 相级崩溃（不再是断言级）
            crash = f"{type(exc).__name__}: {exc}"
        fails = [label for good, label in mod.results[start:] if not good]
        # 判定顺序：**期望的那条断言红了**才是唯一算数的事（`expect` 是程序化匹配，
        # 不是我的判断）。相级崩溃另算 —— 崩了就没跑完，任何结论都不作数。
        # `sentinel_hits` 只作为**说明**附在 PASS 后面：它表示"红了，而且红的原因正是
        # 变异让某个本该存在的文件没被写出来"。这正是检测生效的形态，不该反而降级。
        if any(expect in label for label in fails) and not crash:
            hits += 1
            extra = f"，其中含读不到的文件（{sentinel_hits[0]}）" if sentinel_hits else ""
            print(f"PASS  {name}   [{len(fails)} 条断言变红{extra}]")
        elif crash:
            # 相跑崩 ≠ "没变红"。崩了就没有任何断言被检验过，这条变异**不构成证据**：
            # 可能是变异把代码改坏了（值得修变异），也可能是夹具缺目录（值得补夹具）。
            crashed.append(f"{name}：{crash}")
            print(f"CRASH  {name}   [相跑崩了，没有任何断言被检验：{crash}]")
        else:
            missed.append(name)
            print(f"MISS  {name}   [期望「{expect}」没变红；红了 {len(fails)} 条]")
        if not args.keep:
            shutil.rmtree(d, ignore_errors=True)

    print(f"\n{len(selected)} 条变异：{hits} 条如期变红 / {len(missed)} 条没变红"
          f" / {len(crashed)} 条相跑崩 / {len(broken)} 条替换源对不上或打偏")
    for b in broken:
        print("  ! 替换源：" + b)
    for c in crashed:
        print("  ! 相跑崩：" + c)
    for m_ in missed:
        print("  ! 没变红：" + m_)
    if not args.keep:
        shutil.rmtree(scratch_root, ignore_errors=True)
    else:
        print(f"（临时目录保留在 {scratch_root}）")

    # 金丝雀的第二半：用户真实的记忆库动没动过。
    #
    # 这一条**必须能盖过"全绿"**：一条变异都没漏、却把用户真实的库改了，那是更坏的结果 ——
    # 断言证明不了"没有副作用"，只有前后指纹能。2026-10-17 那次就是这样：9 轮全绿，
    # 库里攒了 54 条夹具路径。
    canary_after = real_memory_fingerprint()
    if canary_after != canary_before:
        print("\nCANARY  隔离失效：本次运行**改动了用户真实的记忆库**"
              f"（{os.path.join(os.path.expanduser('~'), 'dsh-lore-memory')}）")
        if canary_before is None:
            print("  ! 它原本不存在，现在被建出来了 —— 有命令掉到了第四级默认根上")
        else:
            old, new = dict(canary_before), dict(canary_after)
            for key in sorted(set(old) | set(new)):
                if old.get(key) != new.get(key):
                    how = "新增" if key not in old else ("消失" if key not in new else "被改写")
                    print(f"  ! {how}：{key}")
        print("  ! 先查 `_selftest.py` 的 `memory_phase`：四级解析里每一级都钉住夹具了吗？")
        print("  ! 变异跑红是**结果**，污染真实库是**代价** —— 两者不能相抵。")
        return 1

    return 1 if (missed or broken or crashed) else 0


if __name__ == "__main__":
    sys.exit(main())
