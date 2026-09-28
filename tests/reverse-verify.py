#!/usr/bin/env python3
"""reverse-verify.py — 把自测里每个阶段的断言**先弄红一次**。

本项目的硬规矩：**没见它红过的断言不算数**。这条工具把变异表逐条跑一遍 ——
每次按一个字面替换把 journal.py 改坏，只跑那一条变异所属的**那一相**，检查"期望的
那条断言"确实变红。真实源码一个字节都不动：改的是临时目录里的**副本**。

**为什么要按相分**：最初这张表只覆盖 `memory_phase`。但"没见它红过"这条规矩对**每一相**
都成立，只覆盖一相等于只在很小一部分地方守规矩。变异行的第一个字段就是它属于哪一相，
新增一相只要在 `PHASES` 里登记它的函数名。

    python logs/tests/reverse-verify.py                  # 逐条变异，全中退出码 0
    python logs/tests/reverse-verify.py --list           # 只列变异表
    python logs/tests/reverse-verify.py --phase config   # 只跑某一相
    python logs/tests/reverse-verify.py --keep           # 留下临时目录便于排查
    python logs/tests/reverse-verify.py --root DIR       # 夹具父目录（须已存在）
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

# 相名 → `_selftest.py` 里那个阶段函数的函数名。新增一相就在这里登记。
PHASES: dict[str, str] = {
    "memory": "memory_phase",
    "config": "config_phase",
    "gates": "gate_phase",
    "links": "link_phase",
    "mode": "mode_phase",
}

# (相, 名字, 原文, 改成, 期望变红的那条断言里的字样)
MUTATIONS: list[tuple[str, str, str, str, str]] = [
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
     '        st = state["workspaces"].get(ws)\n'
     '        if isinstance(st, dict) and st.get("digest") == digest:\n'
     '            skipped.append(f"{name}（清单没变）")\n'
     "            continue",
     '        st = state["workspaces"].get(ws)\n'
     '        if False:\n'
     '            skipped.append(f"{name}（清单没变）")\n'
     "            continue",
     "memory: 幂等靠 .state.json 里的清单摘要"),
    ("memory", "collect 每次都往名册里写点会变的东西",
     '    if registry_dirty and not args.dry_run:\n        save_registry(memory, registry)',
     '    if not args.dry_run:\n'
     '        registry["_touched"] = str(_dt.datetime.now().timestamp())\n'
     '        save_registry(memory, registry)',
     "memory: collect 幂等"),
    ("memory", "collect 改写工作区的清单",
     "        text = read_raw(memory_manifest_path(ws))",
     "        text = read_raw(memory_manifest_path(ws))\n"
     "        if not args.dry_run:\n"
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
     '        for c in e["cited_by"]:\n            if c not in names:',
     "        for c in []:\n            if c not in names:",
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
     "    if len(data) > MEMORY_INBOX_ITEM_MAX_BYTES:",
     "    if False:",
     "inbox: 单条超上限被拒绝"),
    ("memory", "inbox 不再查条数上限",
     "    if len(items) >= MEMORY_INBOX_MAX_ITEMS:",
     "    if False:",
     "inbox: 条数到顶后写满拒绝"),
    ("memory", "inbox 不再忽略半截的 .tmp",
     '        if name.endswith(".tmp") or not os.path.isfile(path):',
     "        if not os.path.isfile(path):",
     "inbox: 读到 .tmp 半截文件时当它不存在"),
    ("memory", "inbox 用文本模式直接写（不先临时名再 rename）",
     '    tmp = os.path.join(d, f".{name}.{os.getpid()}.tmp")\n'
     '    with open(tmp, "wb") as fh:\n'
     "        fh.write(data)\n"
     "    os.replace(tmp, path)",
     '    with open(path, "w", encoding="utf-8") as fh:\n        fh.write(text)',
     "inbox: 落盘字节与投进去的一模一样"),
    ("memory", "inbox take 不删原件",
     '    os.remove(item["path"])\n    print(f"已删除 {item[\'name\']}")',
     '    print(f"已删除 {item[\'name\']}")',
     "inbox: 转移之后原件被删掉"),
    ("memory", "inbox take 不搬原文",
     '        payload += [l + nl for l in text.replace("\\r\\n", "\\n").splitlines()]',
     "        payload += []",
     "inbox: 信箱原文被搬进记录"),
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
     '    if not args.lint and code == 0 and not getattr(args, "quiet", False):',
     "    if not args.lint and code == 0:",
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
    ap.add_argument("--phase", choices=sorted(PHASES), default=None,
                    help="only one phase (default: all)")
    args = ap.parse_args()

    if args.list:
        for phase, name, _old, _new, expect in MUTATIONS:
            print(f"[{phase}] {name}\n    → 期望变红：{expect}")
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
    selected = [m for m in MUTATIONS if args.phase in (None, m[0])]
    for i, (phase, name, old, new, expect) in enumerate(selected):
        n = original.count(old)
        if n != 1:
            broken.append(f"{name}：替换源在 journal.py 里出现 {n} 次（应恰好 1 次）")
            print(f"MISS  {name}   [替换源不唯一：{n} 次]")
            continue
        d = os.path.join(scratch_root, f"rev{i:02d}")
        # 副本要**照真实技能布局**建：`scripts/` 放代码、`references/` 放文档。
        # 平铺（代码直接放 rev00/）会让 `os.path.dirname(HERE)` 少一层——
        # 相里按 `../references/` 找文档的断言就会抛 FileNotFoundError，
        # 于是变异"跑不起来"而不是"如期变红"，看着像通过其实什么都没验。
        os.makedirs(os.path.join(d, "scripts"))
        os.makedirs(os.path.join(d, "references"))
        with open(os.path.join(d, "scripts", "journal.py"), "w", encoding="utf-8", newline="") as fh:
            fh.write(original.replace(old, new))
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
        start = len(mod.results)
        crash = ""
        try:
            getattr(mod, PHASES[phase])(fx)
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

    print(f"\n{len(selected)} 条变异：{hits} 条如期变红 / {len(missed)} 条没变红"
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
