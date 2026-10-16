"""dsh-lore → 灵枢 记忆卡投影器（只读产卡，不联网、不写灵枢）。

设计契约（用户 2026-10-16 拍板）：
  1. 粒度 = **一条教训一张卡**（flat lessons 优先；记录格式按 §小节 + 不适用条件切分）；
  2. 正文分**两份**：`*.pointer.md`（瘦卡，进灵枢检索面）+ `*.full.md`（全卡，真源仍是工作区）；
  3. node_id 直接用 dsh-lore 的 slug（两边 id 可互查）；
  4. 去重：复用 dsh-lore 自己的 trigram Dice（`memory_similarity`），对**已有卡**与
     **lessons 条目**各算一遍；命中就不产新卡，改产「引用既有卡」的建议；
  5. 灵枢侧写入只做**薄覆盖层**：本脚本永远能在没装灵枢的机器上独跑。

用法：
  python dsh-lore-card.py <work_log 容器> --rec 0099            # 打印投影（零副作用）
  python dsh-lore-card.py <work_log 容器> --rec 0099 --write    # 落两份卡到 <容器>/memory-cards/
  python dsh-lore-card.py <work_log 容器> --lessons 01-插件与宿主契约.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime

# ── 六要素（与灵枢 policy.json 的 required 同口径：行首 `# 要素名`，不要求冒号） ──
CCG_KEYS = ("功能名", "生效条件", "子功能", "执行", "验证方式", "不适用条件")
CCG_RE = {k: re.compile(rf"(?m)^#\s*{k}") for k in CCG_KEYS}

# 与 journal.py 同口径的近似重复阈值（journal.py:5431 `s >= MEMORY_DUP_THRESHOLD`）
DUP_THRESHOLD = 0.72

_ID_SAFE = re.compile(r"[^a-z0-9-]+")
# lessons 条目：`- **标题**：正文…` / `- **标题**：正文` 之后可有 2 空格缩进的子项
# （有些条目写成 `- **id**\n  applies-to: …` 的字段块，不存在于 lessons 正文，留作兼容）
LESSON_RE = re.compile(r"^- \*\*(?P<title>[^*]+)\*\*[：:]\s*(?P<body>.*)$")
# 归档层目录名。`--include-archive` 扫的就是它下面（见 `all_records`）。
ARCHIVE_DIR = "archive"
SOURCE_REF_RE = re.compile(r"`(wl/\d+|wl-\d+|manual:[a-z]+)`")
# 只有这些小节里的话才是「教训」；「遗留 / 下一轮 / 待办」是**未做的事**，不是结论
LESSON_SECTION_RE = re.compile(r"(教训|经验|结论|可复用|踩(到|过)的?坑|why|为什么)")
NOT_LESSON_SECTION_RE = re.compile(r"(遗留|下一轮|待办|未做|TODO|计划|问题：|背景)")
# 记录里明写「本条教训进 lessons」时，才算整篇可投影
LESSON_POINTER_RE = re.compile(r"lessons/|经验层|`wl/\d+`")


# ── 工具 ────────────────────────────────────────────────────────────────
def read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def trigrams(text: str) -> set[str]:
    s = re.sub(r"[\s\W_]+", "", text.lower())
    if len(s) < 3:
        return {s} if s else set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


def similarity(a: str, b: str) -> float:
    """trigram Dice 系数 —— 与 dsh-lore `journal.py:4909 memory_similarity` 同算法。"""
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return 2 * len(ta & tb) / (len(ta) + len(tb))


ID_PREFIX_RE = re.compile(r"^[a-z][a-z0-9-]*$")
# 中文标题的音译表：覆盖本仓经验条目里出现频率最高的字，凑不出拉丁 id 的落到稳定短哈希。
# **不假装能音译所有中文** —— 表外的字进哈希，id 仍然确定、可复现、可互查。
ZH_MAP = {
    "客": "client", "端": "side", "半": "side", "边": "side", "静": "silent", "默": "silent",
    "失": "fail", "效": "fail", "错": "err", "误": "err", "不": "no", "会": "will",
    "抛": "throw", "报": "report", "设": "design", "计": "design", "令": "token",
    "牌": "token", "写": "write", "名": "name", "样": "style", "式": "style",
    "认": "claim", "领": "claim", "宿": "host", "主": "host", "复": "reset",
    "位": "reset", "规": "rule", "则": "rule", "压": "override", "掉": "drop",
    "属": "prop", "性": "prop", "机": "mech", "制": "mech", "省": "save",
    "得": "save", "反": "reverse", "复": "again", "查": "check", "构": "build",
    "建": "build", "步": "step", "骤": "step", "需": "need", "要": "need",
    "树": "tree", "外": "external", "插": "plugin", "件": "plugin", "导": "export",
    "出": "export", "装": "install", "改": "modify", "后": "after", "重": "reload",
    "载": "reload", "页": "page", "面": "page", "记": "record", "录": "record",
    "容": "container", "器": "container", "归": "archive", "档": "archive",
    "区": "area", "合": "merge", "并": "merge", "成": "into", "两": "two",
    "个": "two", "一": "one", "条": "one", "库": "store", "存": "store",
    "真": "true", "源": "source", "落": "landing", "点": "spot", "工": "tool",
    "具": "tool", "自": "auto", "动": "auto", "手": "manual", "住": "stop",
    "禁": "forbid", "止": "forbid", "命": "cmd", "文": "doc", "件": "file",
    "路": "path", "径": "path", "旧": "old", "新": "new", "名": "name",
    "号": "num", "表": "table", "行": "row", "列": "col", "验": "verify",
    "证": "verify", "测": "test", "试": "test", "跑": "run", "过": "pass",
    "门": "gate", "禁": "gate", "曲": "quirk", "坑": "pitfall", "踩": "hit",
    "边": "edge", "界": "bound", "极": "limit", "限": "limit", "例": "case",
    "外": "exception", "先": "first", "后": "then", "时": "when", "候": "when",
    "因": "cause", "为": "because", "所": "so", "以": "so", "但": "but",
    "而": "and", "且": "and", "或": "or", "者": "or", "与": "and", "和": "and",
}


def slugify(title: str, fallback: str) -> str:
    """稳定、可读、可互查的拉丁 id。

    规则（都是为了让 id 能被人读出来 —— 用户拍板「node_id 直接用 slug，两边 id 可互查」）：
      ① 标题里有真标识符就**只取标识符**（`Config` / `data-plugin` / `require` 这类），
         不把整句中文硬塞进来；
      ② 没有标识符时走音译表，取前若干个字，**相邻重复词去重**；
      ③ 表外的字不硬译，落到稳定短哈希；
      ④ 无论如何都带 `fallback` 前缀（工作区 + 篇号），保证唯一且能顺藤摸瓜。
    """
    raw = title.strip()
    ids = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", raw)
           if t.lower() not in ("config",) or True]
    parts: list[str] = []
    if ids:
        ident = max(ids, key=len)
        s = _ID_SAFE.sub("-", ident.lower()).strip("-")
    else:
        for ch in raw:
            if ch in ZH_MAP:
                parts.append(ZH_MAP[ch])
            elif ch.isascii() and ch.isalnum():
                parts.append(ch)
        # 相邻重复词去掉（`design-design-token-token` 那种读起来是噪声）
        dedup: list[str] = []
        for p in parts:
            if not dedup or dedup[-1] != p:
                dedup.append(p)
        s = _ID_SAFE.sub("-", "-".join(dedup).lower()).strip("-")
        s = re.sub(r"-{2,}", "-", s)[:32].strip("-")
    if len(s) < 3:
        s = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:6]
    if not ID_PREFIX_RE.match(s):
        s = "x" + s
    return f"{fallback}-{s}"[:56].strip("-") if fallback else s[:48].strip("-")


def norm_ws(text: str) -> str:
    """折叠换行与多空格 —— 卡片正文是一段，不该把 markdown 的硬换行带进灵枢。"""
    return " ".join(text.split())


def reflow(body: str) -> str:
    """把一条教训的正文（可能多行、含缩进子项）折成**一段**：行间用空格接，段落感靠标点。"""
    return norm_ws(body)


def first_sentence(text: str, limit: int = 400) -> str:
    """第一**完整**句（含收尾标点）。超长就在从句处断，并显式标 `…`，不静默截断。"""
    text = norm_ws(text)
    m = re.search(r"[。！？!?]", text)
    out = text[: m.start() + 1] if m else text
    if len(out) > limit:
        cut = max(out.rfind("，", 0, limit), out.rfind("；", 0, limit), out.rfind("、", 0, limit))
        out = (out[:cut] if cut > limit // 2 else out[: limit - 1]) + "…"
    return out


# ── 解析：记录格式 ──────────────────────────────────────────────────────
REC_META = ("日期", "迭代", "主题", "触发", "范围", "结论")


def parse_record(path: str) -> dict:
    text = read(path)
    lines = text.splitlines()
    name = os.path.basename(path)
    rec_no = (re.match(r"(\d+)", name) or [None, "0000"])[1]
    meta: dict[str, str] = {}
    title = ""
    pending: str = ""            # 上一条还在续行的键（见下）
    for ln in lines[:40]:
        if ln.startswith("# ") and not title:
            title = ln[2:].strip()
            continue
        m = re.match(r"^([^：:]{2,6})[：:]\s*(.+)$", ln)
        if m and m.group(1) in REC_META:
            meta[m.group(1)] = m.group(2).strip()
            pending = m.group(1)
            continue
        # **续行**（2026-10-16 修）：记录头部的值是**硬换行**写的，
        # `结论：…`、`范围：…` 常常横跨两三行，只取第一行会把整句切在逗号上
        # （真实记录 `0077` 的卡名因此退化成 `wl0077-worklog`）。判据不能用缩进：
        # 真实记录里既有缩进续行（`0078` 两格），也有顶格续行（`0097`）。
        # 改成看**上一行有没有写完**：没收在句末标点上，或反引号没配平，就是没写完。
        if pending and ln.strip() and not ln.startswith(("## ", "---", "|", ">", "#")):
            prev = meta.get(pending, "")
            if (prev and not re.search(r"[。！？；：).）]", prev)
                    and prev.count("`") % 2 == 0):
                meta[pending] = (prev + " " + ln.strip()).strip()
                continue
        pending = ""

    # 切「## 小节」；`不适用条件` 一类的小节里逐条抽边界
    sections: list[tuple[str, list[str]]] = []
    cur = ("（前言）", [])
    for ln in lines:
        if ln.startswith("## "):
            sections.append(cur)
            cur = (ln[3:].strip(), [])
        else:
            cur[1].append(ln)
    sections.append(cur)

    verify = [t for h, b in sections if h.startswith(("四、验证", "验证")) for t in b]
    boundary = [t for h, b in sections
                if any(k in h for k in ("不适用", "边界", "遗留", "限制")) for t in b]

    # ── 一条教训的判据（第一版在「遗留与下一轮」里抓半句话，是错的）──────────────
    #   ① 小节必须是**结论性**小节（教训/经验/结论/可复用/坑），排除遗留、下一轮、待办；
    #   ② 这条 bullet 必须**自成一句**（够长、以句号收尾），不是被表/列表切断的碎片；
    #   ③ 整篇记录必须在某处声明过「本条结论进了 lessons / 经验层」——否则这篇的产出
    #      没被作者认定为可复用结论，投影只会造噪声。
    declared = (bool(LESSON_POINTER_RE.search(text))
                or any("教训" in h or "经验" in h for h, _ in sections))
    lessons: list[dict] = []
    for head, body in sections:
        if NOT_LESSON_SECTION_RE.search(head) or not LESSON_SECTION_RE.search(head):
            continue
        for ln in body:
            m = LESSON_RE.match(ln)
            if not m:
                continue
            body_txt = m.group("body").strip()
            title_txt = m.group("title").strip()
            if len(body_txt) < 24 or not re.search(r"[。！？]$", body_txt):
                continue                      # 碎片/半句话：不产卡
            if len(title_txt) < 4:
                continue
            lessons.append({"title": title_txt, "body": body_txt, "section": head})

    # 记录自己声明的结论行：整篇作为**一张**卡（execute 用结论），只有声明过可复用才产
    if not lessons and declared and len(meta.get("结论", "")) >= 24:
        lessons.append({"title": (title.split("·", 1)[-1].strip() or title),
                        "body": meta["结论"], "section": "结论"})
    return {"kind": "record", "path": path, "name": name, "no": rec_no,
            "title": title, "meta": meta, "sections": sections,
            "verify": verify, "boundary": boundary, "lessons": lessons,
            "declared": declared}


# ── 解析：lessons 条目 ──────────────────────────────────────────────────
def parse_lessons(path: str) -> list[dict]:
    """lessons 分册里的**一条经验 = 一条 bullet**（`- **标题**：正文…`）。

    条目 id 不在 lessons 正文里（`id: / applies-to:` 那套是**全局记忆分册**的格式），
    所以 id 由「分册号 + 标题哈希」推出：同一条复现得到同一个 id，不同条不会撞。
    """
    text = read(path)
    lines = text.splitlines()
    volume = os.path.basename(path)
    out: list[dict] = []
    for i, ln in enumerate(lines):
        m = LESSON_RE.match(ln)
        if not m:
            continue
        # 标题可能被硬换行折成两行（markdown 里很常见）：续行既不以 `-` 也不缩进，
        # 取到句读为止，否则后半句会被当成正文的开头（条目的"标题"就变成了半句）。
        title = m.group("title").strip()
        j = i + 1
        while (j < len(lines) and lines[j].strip() and not lines[j].startswith(("-", "  ", "\t", "#"))
               and not re.search(r"[。：:；;！!？?]", title)):
            title = f"{title}{lines[j].strip()}"
            j += 1
        body_lines = [m.group("body").strip()]
        while j < len(lines) and lines[j].startswith(("  ", "\t")):
            body_lines.append(lines[j].strip())
            j += 1
        body = "\n".join(body_lines).strip()
        if len(body) < 24 or len(title) < 4:
            continue
        src = sorted(set(SOURCE_REF_RE.findall(body)))
        out.append({"title": title, "body": body, "sources": src, "volume": volume,
                    "section": volume.split("-", 1)[-1].replace(".md", "")})
    return out


# ── 去重面：已有卡 + lessons 条目 ───────────────────────────────────────
def existing_cards(card_dir: str) -> list[dict]:
    if not os.path.isdir(card_dir):
        return []
    out = []
    for fn in sorted(os.listdir(card_dir)):
        if fn.endswith(".pointer.md"):
            p = os.path.join(card_dir, fn)
            body = read(p)
            m = re.search(r"(?m)^id:\s*(\S+)", body)
            t = re.search(r"(?m)^#\s*功能名\s*\n(.+)$", body)
            out.append({"id": m.group(1) if m else fn[:-11], "path": p, "text": body,
                        "title": t.group(1).strip() if t else ""})
    return out


def record_source(container: str, no: str) -> tuple[str, bool]:
    """`wl/0002` → 容器里那份记录的真实相对路径（记录可能已归档到子目录）。

    找不到就**如实标 unknown**，不编一个看起来像真的路径 —— 卡里的 source 是给人查的。
    """
    for dirpath, dirnames, filenames in os.walk(container):
        dirnames[:] = [d for d in dirnames
                       if d not in ("memory-cards", "logs", "lessons", ".git")]
        for fn in filenames:
            if fn.startswith(f"{no}-") and fn.endswith(".md"):
                rel = os.path.relpath(os.path.join(dirpath, fn), container).replace("\\", "/")
                return f"work_log/{rel}", True
    return f"work_log/{no}-unknown.md", False


# ── 产卡 ────────────────────────────────────────────────────────────────
# 每张卡的第一行放一句可机读的出处标记：卡片是**生成物**，与它替代的真源天然重叠，
# 事后要清理时得一眼认出哪些文件是投影出来的（`grep -rl 'dsh-lore-card.py 生成'`）。
# 放 frontmatter 里当注释：既在文件开头，又不污染六要素正文，也不给 YAML 添字段。
MARK = ("<!-- 本文件由 dsh-lore-card.py 生成（记忆卡投影），不是真源；"
        "真源见 source 字段。整目录可一次性删除重建。 -->")


def build_cards(lesson: dict, ctx: dict, slug: str) -> tuple[str, str]:
    """返回 (pointer 瘦卡, full 全卡) —— 两份都带齐六要素行，缺一灵枢必 REJECT。"""
    title = lesson["title"]
    body = lesson["body"]
    srcs = lesson.get("sources") or []
    applies = ctx.get("applies_to") or ""
    src_ref = srcs[0] if srcs else ctx.get("source", "")

    cond_bits = []
    if applies:
        cond_bits.append(f"适用于 `{applies}`")
    if lesson.get("section"):
        cond_bits.append(f"出自「{lesson['section']}」")
    if ctx.get("scope"):
        cond_bits.append(f"范围：{norm_ws(ctx['scope'])[:120]}")
    cond = "；".join(cond_bits) or "（按来源记录的范围）"

    # 不适用条件：**边界** 只认正文里显式写的边界句（"不含…" "仅…" "仅当…"）；抓不到就如实说没声明。
    # 第一版拿「遗留」小节充数，那讲的是"还没做的事"，不是"这条什么时候不成立"。
    boundary_lines = [b for b in (lesson.get("boundary") or [])
                      if re.search(r"(不含|仅|只在|不适用|例外|极限|边界)", b)]
    if boundary_lines:
        napp = norm_ws(" / ".join(first_sentence(b, 90) for b in boundary_lines[:2]))
    else:
        napp = f"边界未在来源里显式声明；引用前先看 `{src_ref or '来源'}` 的「范围」与「遗留」两节"

    verify = norm_ws(ctx.get("verify_anchor") or "")
    if not verify:
        src_note = f"出处 {src_ref}" if src_ref else "未标出处"
        unknown = "记录未在本容器找到（可能已归档），" if "unknown" in ctx.get("source", "") else ""
        verify = (f"来源 `{ctx.get('source', '')}`（{src_note}）；{unknown}"
                  f"本条未经独立复现，只有来源可追")

    head = {
        "功能名": title,
        "生效条件": cond,
        "子功能": "无下级分解（本条为原子结论）",
        "执行": first_sentence(body, 200),
        "验证方式": verify,
        "不适用条件": napp,
    }

    def ccg(extra_exec: str = "") -> str:
        out = []
        for k in CCG_KEYS:
            out.append(f"# {k}")
            out.append(head[k])
            if k == "执行" and extra_exec:
                # 整卡里「执行」要一次说完，但**别再重复开头那一段**：
                # `head["执行"]` 是正文的 `first_sentence(body, 200)`，通常是正文的**前缀**。
                # 直接追加整段会变成「片段 + 全句」，前 200 字符逐字出现两遍
                # —— 实测 41 张 full 卡里 27 张如此。判据不能写成
                # `norm_ws(extra) != norm_ws(head["执行"])`：正文是**原文换行**、head 是
                # **归一空白**，两者几乎永不相等，所以那个守卫等于没写。
                n_sum, n_body = norm_ws(head["执行"]), norm_ws(extra_exec)
                body = reflow(extra_exec)
                if n_body.startswith(n_sum):
                    rest = body[len(head["执行"]):].lstrip()
                    if rest:
                        out.append(rest)
                else:
                    out.append(body)
            out.append("")
        return "\n".join(out).rstrip() + "\n"

    pointer_id = slug
    full_id = f"{slug}--full"
    src_pointer = ctx.get("pointer_path", "")
    full_rel = ctx.get("full_rel", "")

    # ── 索引面：给灵枢的 `route_key` 喂饱它认的两路 ────────────────────────
    # 它认 `domain:<域>` 标签（优先级最高）或 `condition_space.observation_position`；
    # 只写 `dsh-lore` 这类裸词，条件桶路会一律回落 orphan（实测：分桶表为空）。
    # 两个都写：标签管实体路，condition_space 管条件桶路，互相兜底。
    dom = ctx.get("domain") or "general"
    stale = ctx.get("source_status") == "stale"
    src_status = ('source_status: stale\n' if stale else "")
    ptr_tags = f"[dsh-lore, domain:{dom}]"
    full_tags = f"[dsh-lore, domain:{dom}, full]"
    cond_space = f'condition_space: {{"observation_position": "{dom}"}}\n'

    pointer = (
        "---\n"
        f"{MARK}\n"
        f"id: {pointer_id}\n"
        f"layer: knowledge\n"
        f"tags: {ptr_tags}\n"
        f"{cond_space}"
        f"source: {ctx.get('source', '')}\n"
        f"{src_status}"
        f"cited_by: [{ctx.get('cited_by') or src_ref or '（未标）'}]\n"
        f"parent: {src_pointer}\n"
        "---\n\n"
        f"{ccg()}\n"
        f"（正文真源：工作区 `{full_rel or full_id}`）\n"
    )
    full = (
        "---\n"
        f"{MARK}\n"
        f"id: {full_id}\n"
        f"layer: knowledge\n"
        f"tags: {full_tags}\n"
        f"{cond_space}"
        f"source: {ctx.get('source', '')}\n"
        f"{src_status}"
        f"parent: {src_pointer}\n"
        "---\n\n"
        f"{ccg(extra_exec=body)}\n"
        f"来源：`{ctx.get('source', '')}`（工作区真源；本卡只是它的可检索投影，不作第二真源）\n"
    )
    return pointer, full


def ccg_check(text: str) -> list[str]:
    body = text.split("---\n", 2)[-1]
    return [k for k in CCG_KEYS if not CCG_RE[k].search(body)]


# ── 主流程 ──────────────────────────────────────────────────────────────
def rec_units(full_path: str, domain: str) -> list[tuple[dict, dict]]:
    """一篇记录 → 待投影的「一条教训」列表。`--rec` 与 `--all` 共用这一条路径。"""
    rec = parse_record(full_path)
    vheads = [h for h, _ in rec["sections"] if h.startswith(("四、验证", "验证"))]
    ctx0 = {"domain": domain, "source": f"work_log/{rec['name']}",
            "applies_to": rec["meta"].get("主题", ""),
            "scope": rec["meta"].get("范围", ""),
            "boundary": rec["boundary"],
            "verify_anchor": (f"来源记录 `work_log/{rec['name']}` 的"
                              f"「{vheads[0] if vheads else '验证'}」小节：给出复现步骤与实测结果"),
            # 「真源」= 这张卡替代掉的那份文档（体量闸的尺子就是它）。记录投影用记录本身。
            "src_bytes": os.path.getsize(full_path),
            "source_status": "ok",
            "pointer_path": "", "full_rel": ""}
    return [(les, dict(ctx0)) for les in rec["lessons"]]


def lessons_units(container: str, lp: str, domain: str) -> list[tuple[dict, dict]]:
    """一册 lessons → 待投影列表（条目自带的 `wl/NNNN` 出处才是它的真源）。"""
    out: list[tuple[dict, dict]] = []
    for entry in parse_lessons(lp):
        refs = [s.split("/", 1)[1] for s in entry["sources"] if s.startswith("wl/")]
        # 真源 = 条目自己指的 `wl/NNNN` 那篇记录；指向不明/记录不在容器里，
        # 就退回**它所在的分册**（那才是这条经验真正的落点）。体量闸量的是这个。
        if len(set(refs)) == 1:
            src, found = record_source(container, refs[0])
            cite = f"work_log/{os.path.basename(src)}"
            note = "" if found else "（记录未在本容器找到，可能已归档到别的工作区）"
            if note:
                cite += note
            src_bytes = os.path.getsize(src) if found else 0
            status = "ok" if found else "stale"
        elif refs:
            # 多条出处：**取第一条当主源**，别退回"分册"——分册是落点，不是这篇结论的出处；
            # 拿它当 source，读者会顺手去看整册，指认反而更糊。其余出处留在 cited_by 里。
            src, found = record_source(container, refs[0])
            cite = f"work_log/{os.path.basename(src)}"
            if not found:
                cite += "（记录未在本容器找到，可能已归档到别的工作区）"
            src_bytes = os.path.getsize(src) if found else 0
            status = "ok" if found else "stale"
        else:
            src = f"lessons/{os.path.basename(lp)}"
            cite = ""
            src_bytes = os.path.getsize(lp)
            # 这里的 status 分两种，不能一律 "ok"（2026-10-16 修）：
            #   · 条目**没写出处**（refs 为空）→ 真源就是分册本身，一切正常；
            #   · 出处写了但**指不到**（refs 里没有 `wl/` 形态，或在别的工作区）→
            #     追溯链是断的，必须标 stale；一律 "ok" 会让 INDEX 的「归属」一栏
            #     谎报「全部卡的源记录都在本容器内」，读者以为出处齐全。
            status = "ok" if not entry["sources"] else "stale"
        out.append((entry, {"domain": domain, "source": src, "cited_by": cite,
                            "applies_to": "", "scope": "", "boundary": [],
                            "verify_anchor": "", "src_bytes": src_bytes,
                            "source_status": status,
                            "pointer_path": "", "full_rel": "",
                            "fallback_no": refs[0] if refs else ""}))
    return out


def all_records(container: str, include_archive: bool = False) -> list[str]:
    """容器**顶层**的编号式记录（归档到子目录的不算：那是历史，不重投影）。

    `include_archive=True` 时连 `archive/` 下的记录一起收（按路径排序）。
    2026-10-16 加：已归档记录的卡本来是**孤儿** —— 源搬进 `archive/` 之后生成器
    再也够不着，`--all` 跑一遍它们一张都不会更新（实测 41 张逐字节没变），
    删掉就永久消失。要重建那批卡（例如修了投影格式想全量重投影）就得开这个开关。
    """
    out = []
    for fn in sorted(os.listdir(container)):
        p = os.path.join(container, fn)
        if os.path.isfile(p) and re.match(r"^\d{2,4}-.+\.md$", fn):
            out.append(p)
    if include_archive:
        arch = os.path.join(container, ARCHIVE_DIR)
        for dirpath, dirnames, filenames in os.walk(arch):
            dirnames[:] = sorted(d for d in dirnames if d not in (".git", "node_modules"))
            for fn in sorted(filenames):
                if re.match(r"^\d{2,4}-.+\.md$", fn):
                    out.append(os.path.join(dirpath, fn))
    return out


# ── 索引面：memory-cards/INDEX.md ──────────────────────────────────────────
def _fm(text: str, key: str) -> str:
    m = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
    return m.group(1).strip() if m else ""


def _ccg_line(text: str, key: str) -> str:
    m = re.search(rf"(?m)^#\s*{re.escape(key)}\s*\n(.+?)\s*$", text)
    return m.group(1).strip() if m else ""


def _clip(s: str, n: int) -> str:
    s = norm_ws(s).replace("|", "\\|")
    return s if len(s) <= n else s[:n - 1] + "…"


def index_rows(card_dir: str, container: str = "") -> list[dict]:
    """扫已落盘的瘦卡 → INDEX 的行。确定性：同样的卡目录 → 逐字节同样的表。

    `container` 给定时**当场核一遍源记录还在不在**（2026-10-16 加）：
    卡的 frontmatter 里那句 `source_status: stale` 是**投影那一刻**的判断，之后源记录
    被删/被归档，卡不会自己变旧 —— 于是 INDEX 会一直谎报「全部卡的源记录都在本容器内」。
    索引是读者唯一的入口，这地方必须说实话：所以这里重算，并且**把结论写回卡**，
    让「卡旧了」这件事本身可被发现（`.full.md` 也跟着改，两者是同一张卡的两份）。
    """
    rows: list[dict] = []
    if not os.path.isdir(card_dir):
        return rows
    for fn in sorted(os.listdir(card_dir)):
        if not fn.endswith(".pointer.md"):
            continue
        p = os.path.join(card_dir, fn)
        t = read(p)
        source = _fm(t, "source")
        # 只在真给了容器时才核（容器空串 = 调用方只要表格，不做追溯校验）。
        # 注意路径形态：卡里写的是**工作区相对**路径（`work_log/0001-x.md`），
        # 而 `container` 已经指到容器根了 —— 直接 join 会得到 `…\work_log\work_log\…`，
        # 于是每张卡都被判成 stale（2026-10-16 真踩过）。先把容器名那一段剥掉再核。
        missing = False
        if container and source:
            rel = source
            head = os.path.basename(os.path.abspath(container.rstrip("/\\")))
            if rel == head or rel.startswith(head + "/"):
                rel = rel[len(head) + 1:]
            missing = not os.path.exists(os.path.join(container, *rel.split("/")))
        if missing and "source_status: stale" not in t:
            t = re.sub(r"(?m)^(source:.*)$", r"\1\nsource_status: stale", t, count=1)
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(t)
            full = os.path.join(card_dir, fn[: -len(".pointer.md")] + ".full.md")
            if os.path.isfile(full):
                ft = read(full)
                if "source_status: stale" not in ft:
                    with open(full, "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(re.sub(r"(?m)^(source:.*)$", r"\1\nsource_status: stale",
                                        ft, count=1))
        tags = _fm(t, "tags")
        m = re.search(r"domain:([^,\]]+)", tags)
        napp = _ccg_line(t, "不适用条件")
        rows.append({
            "id": _fm(t, "id") or fn[: -len(".pointer.md")],
            "domain": (m.group(1).strip() if m else "general"),
            "title": _ccg_line(t, "功能名"),
            "exec": _ccg_line(t, "执行"),
            "cond": _ccg_line(t, "生效条件"),
            "source": source,
            "stale": "source_status: stale" in t,
            "bytes": os.path.getsize(p),
            "no_boundary": bool(re.search(r"边界未在来源里显式声明", napp)),
            "path": fn,
        })
    rows.sort(key=lambda r: (r["domain"], r["id"]))
    return rows


def printable_index(rows: list[dict], project: str, domain: str = "") -> str:
    doms: dict[str, int] = {}
    for r in rows:
        doms[r["domain"]] = doms.get(r["domain"], 0) + 1
    dom_txt = "、".join(f"{k} {v}" for k, v in sorted(doms.items())) or "（无）"
    stale = [r for r in rows if r["stale"]]
    nob = [r for r in rows if r["no_boundary"]]
    out = [
        "# 记忆卡索引（memory-cards/INDEX.md）",
        "",
        f"> 自动生成，别手改：`python dsh-lore-card.py <容器> --index-only --write` 重建。",
        f"> 项目 `{project or '（未标注）'}` · 项目域 `{domain or '（未标注）'}` · 卡 {len(rows)} 张 · 域：{dom_txt}",
        "",
        f"- 体量：INDEX 一行 ≈ 150 B，**先读这张表再决定读哪张卡**；一张卡 pointer "
        f"{min((r['bytes'] for r in rows), default=0)}–{max((r['bytes'] for r in rows), default=0)} B，"
        f"真源是它的十几倍到几十倍。",
        f"- 归属：{len(stale)} 张的源记录不在本容器（`[源未找到]`）——卡本身没错，错的是追溯链。"
        if stale else "- 归属：全部卡的源记录都在本容器内。",
        f"- 边界：{len(nob)} 张**没有**显式声明的「不适用条件」（卡里如实写了「边界未在来源里显式声明」，"
        f"引用前先看源记录的「范围」「遗留」两节）。" if nob
        else "- 边界：所有卡都有显式声明的「不适用条件」。",
        "",
        "| id | 域 | 功能名 | 执行（一句） | 生效条件 | 源 | 卡 B |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        src = _clip(r["source"], 34) + (" [源未找到]" if r["stale"] else "")
        out.append(f"| `{r['id']}` | {r['domain']} | {_clip(r['title'], 44)} | "
                   f"{_clip(r['exec'], 56)} | {_clip(r['cond'], 40)} | {src} | {r['bytes']} |")
    return "\n".join(out) + "\n"


def write_index_file(path: str, rows: list[dict], project: str, domain: str = "",
                     write: bool = False) -> bool:
    """只在**内容真的变了**才写盘：否则每次跑都动 git 里的一个文件，纯噪声。"""
    body = printable_index(rows, project, domain)
    old = read(path) if os.path.isfile(path) else None
    if old == body:
        return False
    if write:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
    return True


def read_index_header(path: str) -> tuple[str, str]:
    """从既有 INDEX.md 的表头里读回 `(项目, 项目域)`。

    为什么需要：`--index-only` 只重建表格，但它**没有** `--project/--domain` 这两个开关，
    于是表头会退回按容器路径推的名字 —— 同一个索引被两种模式轮流写就会来回翻脸，
    每次都"已重建"，把幂等性打掉（自测的 `--index-only` 那两条就是这么红的）。
    判据：只在 `--project/--domain` **没显式给**时用它兜底。
    """
    idx_text = ""
    if os.path.isfile(path):
        idx_text = read(path)
    m = re.search(r"^> 项目 `([^`]*)` · 项目域 `([^`]*)`", idx_text, re.M)
    if not m:
        return "", ""
    proj = "" if m.group(1) in ("", "（未标注）") else m.group(1)
    dom = "" if m.group(2) in ("", "（未标注）") else m.group(2)
    return proj, dom


def write_manifest(card_dir: str, container: str, domain: str, rows: list[dict]) -> str:
    """写 `memory-cards/.projection-manifest.json` —— 这次投影产出了什么，供事后清理用。

    为什么不能只靠"卡里的标记"：清理的人是拿着 `rm` 站在目录前，需要的是
    **一份能对账的清单**（多少张、哪些 id、各自多大、哪个是真源目录），
    而不是逐个文件去 grep 注释。清单随整目录一起删，不留残留。
    """
    path = os.path.join(card_dir, ".projection-manifest.json")
    data = {
        "generator": "dsh-lore-card.py",
        "note": "本目录整体是**生成物**（记忆卡投影）：删掉 memory-cards/ 即完全回退，"
                "真源是记录与 lessons 分册，不在本目录内。",
        "rebuilt_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "container": os.path.relpath(container, os.path.dirname(card_dir)).replace("\\", "/"),
        "domain": domain,
        "count": len(rows),
        "cards": [{"id": r["id"], "pointer": r["path"], "bytes": r["bytes"],
                   "stale": bool(r["stale"])} for r in rows],
    }
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


def derive_domain(container: str) -> str:
    """容器所在的项目目录名当域（`…/dsh_manner_space/work_log` → `dsh_manner_space`）。

    域是灵枢条件桶的键，也进卡的标签；拿项目名比自己编一个靠谱。
    """
    parent = os.path.basename(os.path.dirname(os.path.abspath(container.rstrip("/\\"))))
    parent = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]+", "-", parent).strip("-")
    return parent or "general"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="dsh-lore → 灵枢 记忆卡投影（只读）")
    ap.add_argument("container", help="work_log 容器目录")
    ap.add_argument("--rec", help="记录文件名或编号，如 0099 或 0099-xxx.md")
    ap.add_argument("--lessons", help="lessons 分册文件名，如 01-插件与宿主契约.md")
    ap.add_argument("--all", action="store_true",
                    help="容器里所有编号式记录 + lessons/ 下所有分册（INDEX 重建与全量预检走这条）")
    ap.add_argument("--include-archive", action="store_true",
                    help="连同 `archive/` 里的**已归档**记录一起扫（默认不扫：历史不重投影。"
                         "但已归档记录的卡一旦删掉就再也生不出来 —— 要重建那批卡时加这个。"
                         "只影响 `--all`）")
    ap.add_argument("--quiet", action="store_true", help="只打索引行与统计，不打两份卡正文")
    ap.add_argument("--min-source", type=int, default=400, metavar="B",
                    help="真源小于这么多字节就不出卡（原文更省）；默认 400")
    ap.add_argument("--index-only", action="store_true",
                    help="只重建 memory-cards/INDEX.md，不投影任何卡")
    ap.add_argument("--domain", default="",
                    help="灵枢域（条件桶的键）。不给则沿用既有 INDEX 表头，再按容器所在项目目录推，最后退 general")
    ap.add_argument("--project", default="", metavar="名称",
                    help="卡片归属的项目名（写进 INDEX 表头；不参与过滤，纯粹给人看）")
    ap.add_argument("--write", action="store_true", help="落两份卡到 <容器>/memory-cards/")
    ap.add_argument("--list-similar", action="store_true", help="只报已有卡与目标的相似度")
    args = ap.parse_args(argv)

    container = os.path.abspath(args.container)
    if not os.path.isdir(container):
        print(f"ERROR: 容器不存在：{container}")
        return 1

    card_dir = os.path.join(container, "memory-cards")
    index_path = os.path.join(card_dir, "INDEX.md")

    # 域：显式优先 → 既有 INDEX 表头 → 按容器所在项目目录推（避免每篇都要手填）。
    # 用"空"当哨兵而不是 `general`：显式 `--domain general` 也是有效选择，不该被覆盖。
    head_proj, head_dom = read_index_header(index_path)
    project = args.project.strip() or head_proj or ""
    domain = args.domain.strip() or head_dom or project or derive_domain(container) or "general"
    args.domain = domain
    project = project or domain

    if args.index_only:
        rows = index_rows(card_dir, container)
        wrote = write_index_file(index_path, rows, project, domain, write=args.write)
        print(f"容器：{container}")
        print(printable_index(rows, project, domain).rstrip())
        print(f"\n{'已重建' if wrote else '无变化（未写盘）'}：{index_path}")
        return 0
    cards = existing_cards(card_dir)

    # 收集待投影的「一条教训」
    units: list[tuple[dict, dict]] = []   # (lesson, ctx)
    if args.all:
        for rp in all_records(container, include_archive=args.include_archive):
            got = rec_units(rp, args.domain)
            if not got:
                # **不能静默跳过**（2026-10-16 修）：一篇被跳过却一声不吭的记录，
                # 在汇总里只表现为"条数比预期少"，读者会以为它没被算进来源，
                # 于是「体量闸拦住了什么」这件事永远验不到（自测里那条断言就是
                # 靠这句才立起来的）。跳过也要留下能被 grep 的痕迹。
                print(f"（跳过 `{os.path.basename(rp)}`：没有可投影的教训 —— "
                      f"需要结论性小节里以句号收尾的完整 bullet；"
                      f"遗留/待办不算，无出处也不算）")
            units += got
        les_dir = os.path.join(container, "lessons")
        if os.path.isdir(les_dir):
            for fn in sorted(os.listdir(les_dir)):
                if fn.endswith(".md") and fn != "README.md":
                    units += lessons_units(container, os.path.join(les_dir, fn), args.domain)
        if not units:
            print("（容器里没有可投影的教训：记录需有结论性小节里以句号收尾的完整 bullet）")
    elif args.rec:
        rec_path = args.rec
        if not rec_path.endswith(".md"):
            hits = [f for f in os.listdir(container) if f.startswith(args.rec)]
            if not hits:
                print(f"ERROR: 找不到记录 `{args.rec}`")
                return 1
            rec_path = hits[0]
        full_path = rec_path if os.path.isabs(rec_path) else os.path.join(container, rec_path)
        units = rec_units(full_path, args.domain)
        if not units:
            print(f"（记录 `{os.path.basename(full_path)}` 没有可投影的教训：需要结论性小节里"
                  f"以句号收尾的完整 bullet；遗留/待办不算）")
    elif args.lessons:
        lp = args.lessons if os.path.isabs(args.lessons) else os.path.join(container, "lessons", args.lessons)
        if not os.path.isfile(lp):
            print(f"ERROR: 找不到 lessons 分册：{lp}")
            return 1
        units = lessons_units(container, lp, args.domain)
    else:
        print("ERROR: 要么 --rec，要么 --lessons，要么 --all")
        return 1

    print(f"容器：{container}")
    print(f"已有卡：{len(cards)} 张（{card_dir}）" if cards else "已有卡：0 张（首次投影）")
    print(f"待投影教训：{len(units)} 条\n")

    if args.write:
        os.makedirs(card_dir, exist_ok=True)

    # 去重键：① 同一条 lessons 条目（源 + 标题哈希）；② 同一张卡的序列（源 + 主题词 Jaccard）。
    # 这是"避免过多重复性内容"的第一道，也是唯一不依赖灵枢的一道：把重复的**收敛**成一张卡，
    # 而不是先造 N 张再指望灵枢的写入闸门挡下来。
    by_key: dict[str, dict] = {}
    by_source: dict[str, list[dict]] = {}
    for c in cards:
        m = re.search(r"(?m)^source:\s*(\S+)", c["text"])
        if m:
            by_source.setdefault(m.group(1), []).append(c)

    def canon(s: str) -> set[str]:
        s = re.sub(r"[`*_（）()「」【】\[\]：:，,。.、；;！!？?\-—…\s]+", " ", s)
        out: set[str] = set()
        for tok in s.split():
            for run in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", tok.lower()):
                if re.fullmatch(r"[\u4e00-\u9fff]{4,}", run):
                    out.update(run[i:i + 2] for i in range(len(run) - 1))
                else:
                    out.add(run)
        return out

    def title_sig(t: str) -> str:
        return hashlib.sha256(norm_ws(t).encode("utf-8")).hexdigest()[:10]

    any_new = False
    dropped: list[str] = []
    used_slugs: dict[str, int] = {}
    expand: dict[str, int] = {}
    for i, (les, ctx) in enumerate(units, 1):
        # id 前缀：lessons 用「出处篇号」，记录投影用「记录号」——两边都能顺着 id 找回工作区那份 md
        if ctx.get("fallback_no"):
            prefix = f"wl{ctx['fallback_no']}"
        else:
            m_rec = re.match(r"(\d+)", os.path.basename(ctx["source"]))
            prefix = f"wl{m_rec.group(1)}" if m_rec else "vol00"
        slug = slugify(les["title"], fallback=prefix)
        # slug 就是文件名与卡 id：两条不同经验撞出同一个 slug，落盘时会**互相覆盖**。
        # 撞了就加后缀，两个都留得住（`--list-similar` 报的是同源扩写，不走这条）。
        if slug in used_slugs:
            used_slugs[slug] += 1
            slug = f"{slug}-{used_slugs[slug]}"
        used_slugs[slug] = 1
        # 源键：有 wl 编号就用编号（跨分册/跨工作区同一条经验 → 同一个键 → 收敛成一张卡），
        # 否则退回记录路径。
        if ctx.get("fallback_no"):
            key = f"wl#{ctx['fallback_no']}#{title_sig(les['title'])}"
        else:
            key = f"{ctx['source']}#{title_sig(les['title'])}"

        # ── 三道去重 ──────────────────────────────────────────────────
        hit, why = None, ""
        if key in by_key:
            hit, why = by_key[key], "同一条条目（源+标题哈希）已在本轮或已有卡里"
        else:
            for c in by_source.get(ctx["source"], []):
                ov = canon(les["title"]) & canon(c.get("title", ""))
                un = canon(les["title"]) | canon(c.get("title", ""))
                if un and len(ov) / len(un) >= 0.5:
                    hit, why = c, f"与同源卡 `{c['id']}` 标题重合 {len(ov) / len(un):.2f}（同源扩写，应 augment 而非新建）"
                    break
        if hit is None:
            best, best_s = None, 0.0
            for c in cards:
                s = max(similarity(les["body"], c["text"]), similarity(les["title"], c.get("title", "")))
                if s > best_s:
                    best, best_s = c, s
            if best is not None and best_s >= DUP_THRESHOLD:
                hit, why = best, f"与已有卡 `{best['id']}` 正文/标题相似度 {best_s:.2f} ≥ {DUP_THRESHOLD}"

        if hit is not None:
            expand[hit["id"]] = expand.get(hit["id"], 0) + 1
            print(f"[{i}] REUSE {hit['id']}\n    {les['title']}\n    {why}\n")
            continue

        # ── 体量闸：卡不许比它替代的真源更贵 ────────────────────────────────
        src_bytes = ctx.get("src_bytes") or 0
        # 使用者口径（m00788）："记录文件本身至应不大于相关上下文"——否则不如直接读原文。
        # 比的是**整篇记录**，不是单条经验行：单条可能就两句话，而卡要凑齐六要素，
        # 逐条比会把所有卡判死，那就不是"更省"而是"不出卡"了。
        src_bytes = ctx.get("src_bytes") or 0
        if src_bytes and src_bytes < args.min_source:
            print(f"[{i}] DROP 真源太短（{src_bytes} B < {args.min_source} B）："
                  f"读原文更省，不出卡\n    {les['title']}\n")
            dropped.append(f"{les['title']}（真源 {src_bytes} B 太短）")
            continue

        any_new = True
        by_key[key] = {"id": slug, "title": les["title"], "text": "", "path": ""}
        ctx["pointer_path"] = f"memory-cards/{slug}.pointer.md"
        ctx["full_rel"] = f"memory-cards/{slug}.full.md"
        pointer, full = build_cards(les, ctx, slug)
        # 体量复检用**真实字节**（卡写出来才知道多重）。真源未知（lessons 无出处）时不判。
        card_bytes = len(pointer.encode("utf-8")) + len(full.encode("utf-8"))
        if src_bytes and card_bytes >= src_bytes:
            print(f"[{i}] DROP 卡比真源还大（两卡 {card_bytes} B ≥ 真源 {src_bytes} B）："
                  f"直接读原文更省\n    {les['title']}\n")
            del by_key[key]
            dropped.append(f"{les['title']}（两卡 {card_bytes} B ≥ 真源 {src_bytes} B）")
            continue
        by_key[key]["text"] = pointer
        by_source.setdefault(ctx["source"], []).append(by_key[key])
        miss_p, miss_f = ccg_check(pointer), ccg_check(full)
        print(f"[{i}] {'=' * 66}")
        print(f"NEW  {slug}    标题：{les['title']}")
        print(f"六要素自检：pointer {'OK' if not miss_p else '缺 ' + ','.join(miss_p)}"
              f" / full {'OK' if not miss_f else '缺 ' + ','.join(miss_f)}")
        ratio = card_bytes / src_bytes if src_bytes else 0.0
        print(f"体量：pointer {len(pointer.encode('utf-8'))} B / full {len(full.encode('utf-8'))} B"
              f"；真源 {src_bytes or '未知'} B；两卡/真源 "
              f"{f'{ratio:.3f}' if src_bytes else 'n/a'}")
        if not args.quiet:
            print("\n---- pointer（瘦卡：进灵枢检索面）----")
            print(pointer)
            print("---- full（全卡：真源副本，落工作区）----")
            print(full)
        if args.write:
            for fn, body in ((f"{slug}.pointer.md", pointer), (f"{slug}.full.md", full)):
                with open(os.path.join(card_dir, fn), "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(body)
            print(f"→ 已写 {card_dir}\\{slug}.pointer.md / .full.md")
        print()

    print(f"共 {len(units)} 条教训：新增 {sum(1 for _ in by_key) if any_new else 0} 张，"
          f"复用/收敛 {sum(expand.values())} 条，丢弃 {len(dropped)} 条")
    if expand:
        for cid, n in sorted(expand.items(), key=lambda kv: -kv[1]):
            print(f"  · `{cid}` 再吃进 {n} 条（→ 灵枢侧应是把新内容 augment 到同一个 node）")
    for d in dropped:
        print(f"  · DROP {d}")
    print("（dry-run：什么都没写。加 --write 才落盘）" if not args.write else f"卡目录：{card_dir}")
    if args.write:
        rows = index_rows(card_dir, container)
        wrote = write_index_file(index_path, rows, project, domain, write=True)
        # 只在这一轮**真的动过盘**时才重写清单：纯复用的一轮不该动 git 里的文件。
        if wrote or any_new:
            write_manifest(card_dir, container, domain, rows)
        print(f"索引：{index_path}（{len(rows)} 行，{'已重建' if wrote else '无变化未写'}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
