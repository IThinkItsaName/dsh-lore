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
import io
import json
import os
import re
import sys
from datetime import datetime

try:  # Windows 控制台默认码页可能不是 UTF-8（cp936）。必须自己钉住，理由见 journal.py:104：
    # 调用方（如 _selftest.py 的 run()）多按 UTF-8 解子进程输出；本脚本不钉，输出就是 GBK 字节，
    # 读线程解码失败后 stdout 会变成 None，把**调用方的断言**炸成 TypeError —— 症状离病根很远。
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:  # pragma: no cover
    pass

# ── 六要素（与灵枢 policy.json 的 required 同口径：行首 `# 要素名`，不要求冒号） ──
CCG_KEYS = ("功能名", "生效条件", "子功能", "执行", "验证方式", "不适用条件")
CCG_RE = {k: re.compile(rf"(?m)^#\s*{k}") for k in CCG_KEYS}

# 近似重复阈值。journal.py 那份 `MEMORY_DUP_THRESHOLD` 是 0.7 —— 它是**门禁**（报错要拦人），
# 宁可漏也不误报；这里的 0.72 是**投影器**的判断（同一张卡投两次只是噪音），略宽一点免得把
# 改了措辞的同一条拆成两张卡。故意不同口径，不是抄漏了。
# 引用只给常量名与函数名，不写行号：行号会随任何一次编辑漂走，而漂走的注释比没有注释更坏。
DUP_THRESHOLD = 0.72

_ID_SAFE = re.compile(r"[^a-z0-9-]+")
# lessons 条目：`- **标题**：正文…` / `- **标题**：正文` 之后可有 2 空格缩进的子项
# （有些条目写成 `- **id**\n  applies-to: …` 的字段块，不存在于 lessons 正文，留作兼容）
LESSON_RE = re.compile(r"^(?:[-*+]|\d{1,9}[.)]) \*\*(?P<title>[^*]+)\*\*[：:]\s*(?P<body>.*)$")
# 围栏代码块：里面的示例不是条目（与 `journal.py` 的 `card_shape_issues` 同一套规则）。
FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
# 卡式条目的三个子字段（`0127` 起）。缩进 ≥2、字段名后接全/半角冒号。
# 字段行与它的续行都**不进 body** —— 否则 full 卡的「执行」会把
# `… - 触发：… - 验证：… - 别再来：…` 连成一行（2026-10-18 审查 M3）。
CARD_FIELD_RE = re.compile(r"^(?:[ \t]{2,}|\t)- (?P<field>触发|验证|别再来)[ \t]*[：:][ \t]*(?P<text>.*)$")
# 旧写法（卡式字段出现之前）：缩进的 `- **触发条件…**：…`。标签带粗体，卡式正则不命中；
# 以前这类子条目会被整段并进 body、最后压进卡的「执行」（`0130` 相邻项，2026-10-18 修）。
LEGACY_FIELD_RE = re.compile(
    r"^(?:[ \t]{2,}|\t)- \*\*(?P<label>[^*]+?)\*\*[ \t]*[：:][ \t]*(?P<text>.*)$")
LEGACY_FIELD_MAP = (("触发", "触发"), ("验证", "验证"), ("别再来", "别再来"),
                    ("避免", "别再来"), ("宿主判据", "验证"), ("判据", "验证"))
CARD_FIELDS = ("触发", "验证", "别再来")
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


def write_atomic(path: str, text: str) -> None:
    """先写同目录临时文件再 `os.replace`（同卷上是原子的）。

    2026-10-17 补：这里从前一律 `open(path, "w")` —— 它先把目标截成 0 字节，
    中途断电/被 kill 就留下一份**残缺的卡或 INDEX**。投影器的产物可以重建，
    但"读到半份 INDEX"会让人以为卡真的少了（INDEX 是导航，断了比没有更坏）。
    `journal.py` 的 `write_raw()` 早就是这个写法（还带非 UTF-8 拒写与权限位保留）；
    卡的正文是工具自己生成的 UTF-8，所以**非 UTF-8 拒写**那条在这里用不上。但**权限位保留**
    那条用得上一一 `_mark_stale()` 改写的正是**已经存在**的卡：目标被设过只读或特殊 ACL 时，
    新 tmp 是 `0666 & ~umask`，直接 replace 会把权限悄悄换掉（或直接被拒），
    而"这份文件的权限被人特意调过"本身是有意的状态（2026-10-17 复核）。所以照搬那三条。
    """
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        try:
            os.chmod(tmp, os.stat(path).st_mode)
        except OSError:
            pass  # 首次创建（目标还不存在）或平台不支持（Windows 只有只读位）：按默认
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def trigrams(text: str) -> set[str]:
    s = re.sub(r"[\s\W_]+", "", text.lower())
    if len(s) < 3:
        return {s} if s else set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


def similarity(a: str, b: str) -> float:
    """trigram Dice 系数 —— 与 dsh-lore `journal.py` 的 `memory_similarity` 同算法。"""
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return 2 * len(ta & tb) / (len(ta) + len(tb))


ID_PREFIX_RE = re.compile(r"^[a-z][a-z0-9-]*$")
# 中文标题的音译表：覆盖本仓经验条目里出现频率最高的字，凑不出拉丁 id 的落到稳定短哈希。
# **不假装能音译所有中文** —— 表外的字进哈希，id 仍然确定、可复现、可互查。
#
# ⚠ 一个字只许出现一次。**字典字面量里重复的键不报错，后一个静默顶掉前一个**
# （2026-10-17 查出 6 个：`复`/`件`/`禁`/`边`/`外`/`后`，每个都有两个值在抢同一个字，
# 先写的那条一辈子没生效过，读代码的人却以为它在生效）。合并同义项、只留一个值，
# 下面 `_zh_dup_keys()` 会在导入时把"顶掉"这件事说出来 —— 不抛异常，但不再沉默。
ZH_MAP = {
    "客": "client", "端": "side", "半": "side", "边": "edge", "静": "silent", "默": "silent",
    "失": "fail", "效": "fail", "错": "err", "误": "err", "不": "no", "会": "will",
    "抛": "throw", "报": "report", "设": "design", "计": "design", "令": "token",
    "牌": "token", "写": "write", "名": "name", "样": "style", "式": "style",
    "认": "claim", "领": "claim", "宿": "host", "主": "host", "复": "again",
    "位": "reset", "规": "rule", "则": "rule", "压": "override", "掉": "drop",
    "属": "prop", "性": "prop", "机": "mech", "制": "mech", "省": "save",
    "得": "save", "反": "reverse", "查": "check", "构": "build",
    "建": "build", "步": "step", "骤": "step", "需": "need", "要": "need",
    "树": "tree", "外": "exception", "插": "plugin", "件": "file", "导": "export",
    "出": "export", "装": "install", "改": "modify", "后": "then", "重": "reload",
    "载": "reload", "页": "page", "面": "page", "记": "record", "录": "record",
    "容": "container", "器": "container", "归": "archive", "档": "archive",
    "区": "area", "合": "merge", "并": "merge", "成": "into", "两": "two",
    "个": "two", "一": "one", "条": "one", "库": "store", "存": "store",
    "真": "true", "源": "source", "落": "landing", "点": "spot", "工": "tool",
    "具": "tool", "自": "auto", "动": "auto", "手": "manual", "住": "stop",
    "禁": "gate", "止": "forbid", "命": "cmd", "文": "doc",
    "路": "path", "径": "path", "旧": "old", "新": "new",
    "号": "num", "表": "table", "行": "row", "列": "col", "验": "verify",
    "证": "verify", "测": "test", "试": "test", "跑": "run", "过": "pass",
    "门": "gate", "曲": "quirk", "坑": "pitfall", "踩": "hit",
    "界": "bound", "极": "limit", "限": "limit", "例": "case",
    "先": "first", "时": "when", "候": "when",
    "因": "cause", "为": "because", "所": "so", "以": "so", "但": "but",
    "而": "and", "且": "and", "或": "or", "者": "or", "与": "and", "和": "and",
}


def _zh_dup_keys(block: str) -> list[str]:
    """把映射表里**重复的键**找出来（Python 只留最后一个，且一声不吭）。

    判据是"这一行出现了一个已经在表里的键"，所以别的字面量不会被算进来；
    只扫映射表那一段，不是整份源码。不抛异常：真正该拦的是"同键两个值"，
    那是上表该修的东西，而这里只是让沉默失效 —— 为一个错别字把整支工具停掉，
    对投影器的代价比收益大。
    """
    seen: set[str] = set()
    dups: list[str] = []
    for ln in block.splitlines():
        for k in re.findall(r'"([^"]+)"\s*:\s*"[^"]*"', ln):
            if k in seen:
                dups.append(k)
            seen.add(k)
    return dups


_ZH_BLOCK = re.search(r"^ZH_MAP = \{(.*?)^\}", open(__file__, encoding="utf-8").read(),
                      re.S | re.M)
for _dup in _zh_dup_keys(_ZH_BLOCK.group(1) if _ZH_BLOCK else ""):
    print(f"[WARN] ZH_MAP 里 {_dup!r} 出现了两次，前一个值被静默丢弃 —— 表该修了",
          file=sys.stderr)


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


def _trim_ellipsis(text: str) -> str:
    """去掉尾部的截断标记与空白（`…`, `...`, `。`, 空格）。

    `first_sentence()` 截断时会**自己补一个 `…`** 告诉读者"这里断了"。那个字不在正文里，
    所以拿它当"正文开头"去比前缀永远比不中（2026-10-17 实测：7 条超 200 字的执行段里
    5 条因此走了 else 分支，把整段追加在摘要后面 → 开头逐字出现两遍）。
    只去尾部、只去这几样：正文中间的 `…` 是作者自己写的省略，不能动。
    """
    return text.rstrip().rstrip("…").rstrip(".。 ").rstrip()


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
    # 围栏代码块整段丢掉：里面是**示例**，不是条目（否则示例会被投影成真卡、进 INDEX）。
    # 与 `journal.py` 的 `card_shape_issues` 同一套规则；两个消费者的判据不能再分叉。
    lines: list[str] = []
    fence: str | None = None
    for raw in text.splitlines():
        fm = FENCE_RE.match(raw)
        if fence is None and fm:
            fence = fm.group(1)[0]
            continue
        if fence is not None:
            if fm and fm.group(1)[0] == fence:
                fence = None
            continue
        lines.append(raw)
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
        fields: dict[str, list[str]] = {k: [] for k in CARD_FIELDS}
        current = ""
        while j < len(lines) and lines[j].startswith(("  ", "\t")):
            fm = CARD_FIELD_RE.match(lines[j])
            lm = LEGACY_FIELD_RE.match(lines[j])
            if fm:
                current = fm.group("field")
                fields[current].append(fm.group("text").strip())
            elif lm:
                # 旧式字段：按标签前缀归到卡式字段；认不出的仍留在 body（不静默丢字）。
                target = ""
                for prefix, field in LEGACY_FIELD_MAP:
                    if lm.group("label").strip().startswith(prefix):
                        target = field
                        break
                if target:
                    current = target
                    fields[target].append(lm.group("text").strip())
                else:
                    body_lines.append(lines[j].strip())
                    current = ""
            elif current and lines[j].startswith(("    ", "\t\t")):
                # 字段的续行（比字段缩进更深）：并进那个字段，别当正文。
                fields[current].append(lines[j].strip())
            else:
                body_lines.append(lines[j].strip())
                current = ""
            j += 1
        body = "\n".join(body_lines).strip()
        # 体量闸量的是"这条经验有多少可读内容"，不是"主行多长"：三字段已经从 body 移走，
        # 只量 body 会让「短主行 + 三字段齐全」的卡被静默丢掉（2026-10-18 复核 low）。
        # 标题门槛 2：中文两字标题（「薄卡」）是合法结论；1 字多半是噪声（2026-10-18）。
        field_size = sum(len(norm_ws(" ".join(fields[k]))) for k in CARD_FIELDS)
        if len(body) + field_size < 24 or len(title) < 2:
            continue
        src = sorted(set(SOURCE_REF_RE.findall(body)))
        out.append({"title": title, "body": body, "sources": src, "volume": volume,
                    "section": volume.split("-", 1)[-1].replace(".md", ""),
                    "trigger": norm_ws(" ".join(fields["触发"])),
                    "verify": norm_ws(" ".join(fields["验证"])),
                    "avoid": norm_ws(" ".join(fields["别再来"]))})
    return out


# ── 去重面：已有卡 + lessons 条目 ───────────────────────────────────────
# 本工具投出来的卡，frontmatter 里一定有这一行（`pointer` 与 `full` 都写）。
# 它是**认亲的唯一判据**：`*.pointer.md` 这个后缀不是本工具专有的 —— 灵枢插件自己也
# 往 `memory-cards/` 投卡、命名规则相同。读的一侧与写的一侧都用它，才不会一边跳过、
# 一边 `os.replace` 把人家的卡盖掉（2026-10-17 修，写侧从前漏了这道）。
OURS_RE = re.compile(r"(?m)^tags:\s*\[\s*dsh-lore\b")


def is_our_card(path: str, text: str | None = None) -> bool:
    """这个文件是不是本工具投出来的卡（看 frontmatter 的 `tags: [dsh-lore, …]`）。

    `text` 给定时直接拿它判，不再读盘（2026-10-17 轮八的观察）：调用方往往**已经读过**
    这个文件了（`existing_cards()` 要解析标签、`index_rows()` 要算陈旧），再读一遍是白读。
    判据本身仍然只有这一处 —— 传文本是为了省一次 I/O，不是为了在别处再写一遍正则。
    """
    if text is None:
        if not os.path.isfile(path):
            return False
        text = read(path)
    return bool(OURS_RE.search(text))


def existing_cards(card_dir: str) -> list[dict]:
    """`memory-cards/` 里**本工具投出来的**卡（`.pointer.md`）。

    ⚠ `*.pointer.md` 这个后缀不是本工具专有的：`memory-cards/` 里可能有别的工具写的
    pointer（灵枢插件自己也投卡）。从前一律当自家卡收进去，于是外部卡会参与三道去重、
    还会在"slug 撞名"时被当成冲突 —— 而它没有本工具写的那行标签。
    判据是**本工具写在 frontmatter 里的那一行**（`tags: [dsh-lore, …]`，见 `OURS_RE`）：
    认它，没有就当外人，只报一行、不进去重面（2026-10-17 修）。不按文件名判是因为
    slug 的形制两边可能一样；不按 `id:` 判是因为两边都有 `id:`。
    """
    if not os.path.isdir(card_dir):
        return []
    out = []
    for fn in sorted(os.listdir(card_dir)):
        if fn.endswith(".pointer.md"):
            p = os.path.join(card_dir, fn)
            # 目录（或断链）叫这个名字时**不是卡**（2026-10-17 轮九）：与 `index_rows()`
            # 的同一道守卫对称。从前这里没有它，而 `read()` 打在目录上会抛
            # `PermissionError`（Windows）—— 于是**整次投影中止**、rc=1、stdout 为空，
            # 用户看到的是一条裸栈，而不是"这张跳过了"。一个同名目录就能造成这个后果。
            if not os.path.isfile(p):
                continue
            body = read(p)
            m = re.search(r"(?m)^id:\s*(\S+)", body)
            if not is_our_card(p, body):
                print(f"[skip] {fn} 的 frontmatter 没有 `tags: [dsh-lore, …]` —— "
                      f"不是这份投影投出来的卡，不参与去重", file=sys.stderr)
                continue
            t = re.search(r"(?m)^#\s*功能名\s*\n(.+)$", body)
            out.append({"id": m.group(1) if m else fn[:-11], "path": p, "text": body,
                        "title": t.group(1).strip() if t else ""})
    return out


def avoid_foreign(card_dir: str, slug: str, ours: set[str],
                  used_slugs: dict[str, int]) -> tuple[str, str]:
    """写盘**准入**：目标文件名上若压着一张外来卡，别覆盖它，换个名字写。

    返回 `(最终 slug, 说明)`；没撞上返回 `(原 slug, "")`。

    读的一侧（`existing_cards()`）早就把外来卡跳过了，但**写的一侧从前不查** ——
    投影出的卡按同一套文件名直接 `write_atomic()`（`os.replace`），于是文件名一撞，
    人家的卡就被悄悄换掉：实测量到 sha 变了，而同一轮还打印着"不参与去重"，两句话
    自相矛盾（2026-10-17 复核发现）。灵枢插件也往同一个目录投卡、命名规则相同，撞名
    是会发生的；那些卡可重建，所以不算 critical，但"报着跳过、实际覆盖"是最坏的一种。

    `ours` 是**本工具已有卡的 id 全集**（`existing_cards()` 收上来的），`used_slugs` 是本轮
    已经分配出去的名字。两者分工不同，混用会出事：

      · `ours` 回答"**这个名字我们已经有卡了**" —— 有的话，这条教训走到去重那一步就会
        REUSE、根本不会写盘，**不该改名也不该报改名**；但要连**改过名的那些**一起看
        （`slug-dsh` / `slug-dsh2` …），因为改名之后原名在磁盘上永远压着那张外来卡，
        只看 `slug in ours` 会让每一轮都重新预告一遍新名字（2026-10-17 实测）。
      · `used_slugs` 回答"**本轮这个名字已经分给别人了**" —— 那**不是**"我们已有卡"，
        此时盘上还什么都没有，该照常查外人不该跳过。第一版把这条也算进"自己的"，
        于是外来卡在它第一次撞名的时刻被直接覆盖 —— 正是要防的那件事（实测踩到）。
    """
    if not os.path.isdir(card_dir):
        return slug, ""
    if slug in ours or any(s.startswith(f"{slug}-dsh") for s in ours):
        return slug, ""
    ptr = os.path.join(card_dir, f"{slug}.pointer.md")
    if not os.path.exists(ptr) or is_our_card(ptr):
        return slug, ""
    why = f"`{slug}.pointer.md` 已存在、且不是本工具投的卡（没有 `tags: [dsh-lore, …]`）"
    for i in range(1, 100):
        cand = f"{slug}-dsh" if i == 1 else f"{slug}-dsh{i}"
        if not os.path.exists(os.path.join(card_dir, f"{cand}.pointer.md")):
            used_slugs[cand] = 1
            return cand, (f"{why} —— **不覆盖它**，本卡改写到 `{cand}.pointer.md` / "
                          f"`{cand}.full.md`。要合成就先把它挪走或改名"
                          f"（它的 `id:` 与本卡不同时，那本来就是两张卡）")
    return slug, f"{why} —— 换了 99 个名字都不空（这目录不对劲），仍按原名写"


def record_rel(container: str, no: str) -> tuple[str, bool]:
    """`wl/0002` → 记录**相对容器**的真实路径（记录可能已归档到子目录），找不到给 (`0002-unknown.md`, False)。

    返回的是**相对容器**的路径，这是本文件里唯一的口径：它既能拼回真路径
    （`os.path.join(container, *rel.split("/"))`），也能显示（`display_source()` 加前缀）。
    **别**在这里返回显示用路径 —— `work_log/x.md` 在本机只是碰巧能当相对路径用，
    换个 cwd 就 FileNotFoundError，或者更糟：撞上**另一个容器**里的同名文件（2026-10-17 实测）。
    """
    for dirpath, dirnames, filenames in os.walk(container):
        dirnames[:] = [d for d in dirnames
                       if d not in ("memory-cards", "logs", "lessons", ".git")]
        for fn in filenames:
            if fn.startswith(f"{no}-") and fn.endswith(".md"):
                return os.path.relpath(os.path.join(dirpath, fn), container).replace("\\", "/"), True
    return f"{no}-unknown.md", False


def display_source(rel: str, container: str = "") -> str:
    """容器相对路径 → 卡里/索引里给人看的 `<容器名>/…` 形态。**只用于显示。**

    前缀取**容器的真实目录名**（容器总是工作区根下的一级目录，所以这个名字就是它在工作区
    里的相对路径）。从前这里写死 `work_log/`：容器叫 `journal/`、`ops/` 时，卡里的 `source:`
    / `cited_by:` 指着一个**不存在**的路径 —— 读的人不受影响（`index_rows()` 会把前缀剥掉），
    但 grep 与人眼会当真，与 H2 刚消灭的"两处各自拼路径"是同一味道（2026-10-17 复核）。
    没给容器时退回 `work_log`：那是默认容器名，也是"不知道"时唯一说得通的显示。
    """
    if not rel:
        return ""
    prefix = os.path.basename(container.rstrip("/\\")) if container else "work_log"
    return f"{prefix or 'work_log'}/{rel}"


def abs_in(container: str, rel: str) -> str:
    """容器相对路径 → 绝对路径（读正文、量体量一律走它，不靠 cwd）。"""
    return os.path.join(container, *rel.split("/")) if rel else ""


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
    # 卡式条目的「触发」就是**生效条件**的第一手材料：它写的是"任务里会出现什么现象"。
    trig = norm_ws(lesson.get("trigger") or "")
    if trig:
        cond_bits.append(f"触发：{trig}")
    if applies:
        cond_bits.append(f"适用于 `{applies}`")
    if lesson.get("section"):
        cond_bits.append(f"出自「{lesson['section']}」")
    if ctx.get("scope"):
        cond_bits.append(f"范围：{norm_ws(ctx['scope'])[:120]}")
    cond = "；".join(cond_bits) or "（按来源记录的范围）"

    # 不适用条件 = 正文里**显式写的边界句**（"不含…" "仅…" "仅当…"）；抓不到就如实说没声明。
    # 「别再来」**不能**塞进这里：它讲的是"试过不通的路 + 原因"，不是"这条何时不成立"；
    # 塞进来还会让 INDEX 的 `no_boundary` 把"没声明边界"误报成"有边界"（2026-10-18 复核 medium）。
    # 它单独成卡尾一节，见下面的 `ccg()`。
    boundary_lines = [b for b in (lesson.get("boundary") or [])
                      if re.search(r"(不含|仅|只在|不适用|例外|极限|边界)", b)]
    avoid = norm_ws(lesson.get("avoid") or "")
    if boundary_lines:
        napp = norm_ws(" / ".join(first_sentence(b, 90) for b in boundary_lines[:2]))
    else:
        napp = f"边界未在来源里显式声明；引用前先看 `{src_ref or '来源'}` 的「范围」与「遗留」两节"

    # 卡式条目的「验证」优先于 ctx 的通用兜底（lessons 的 `verify_anchor` 由它填）。
    verify = norm_ws(lesson.get("verify") or "") or norm_ws(ctx.get("verify_anchor") or "")
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
                # —— 实测 42 张 full 卡里 5 张如此（`wl0006` / `wl0098` / `wl0100`–`wl0102`）。
                #
                # **两道守卫，缺一条就漏**（2026-10-17 两轮才修全）：
                #   ① 摘要是 `…` 结尾时，`n_body.startswith(n_sum)` 必为假 ——
                #      `…` 是 `first_sentence()` 截断时**自己补的标记**，正文里没有这个字，
                #      于是走了 else 分支把整段追加在摘要后面。实测 7 条超 200 字的执行段里
                #      5 条命中这一条。所以比较前先把尾部的 `…` 去掉（`_trim_ellipsis`）。
                #   ② 真命中时切片必须与比较**同源**：从前切 `n_body`、长度却取未归一的
                #      `len(head["执行"])`，正文里有换行/连续空格时两个长度不同，切偏几个
                #      字符就把 `…` 留在开头，拿去重判的串非空 —— 真重复反而不报。
                #   ③ 切片起点要**跳过被剥掉的标点**（2026-10-17 复核）：`_trim_ellipsis`
                #      把句末 `。` 去掉了，而 `len(n_sum)` 是去掉之后的长度 —— 于是
                #      `rest` 以那个 `。` 开头，写进卡里变成一行孤零零的「。 七条缺陷…」
                #      （真卡 `wl0107-*` / `wl0108` 上实测存在）。只吃**开头**的这几个
                #      标点，正文中间的不动 —— 与 `_trim_ellipsis` 只去尾部是同一条理由。
                n_sum = _trim_ellipsis(norm_ws(head["执行"]))
                n_body = norm_ws(extra_exec)
                if n_sum and n_body.startswith(n_sum):
                    # `_trim_ellipsis` 去掉了句末的 `。`/`.`；切片起点要跳过它，
                    # 否则卡里会多出一行孤零零的句号（L1：半角 `.` 以前漏了，2026-10-18）
                    rest = n_body[len(n_sum):].lstrip("。….").lstrip()
                    if rest:
                        out.append(rest)
                else:
                    out.append(n_body)
            out.append("")
        # 「别再来」独立成节：它是反面清单，不是适用性边界（见上面 napp 的注释）。
        # 六要素校验只查六个键**存在**，多这一节不会被判缺；INDEX 也不读它。
        if avoid:
            out.append("# 别再来")
            out.append(avoid)
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
def rec_units(full_path: str, domain: str, container: str = "") -> list[tuple[dict, dict]]:
    """一篇记录 → 待投影的「一条教训」列表。`--rec` 与 `--all` 共用这一条路径。

    `container` 给了就用**容器相对**路径当 source（与 `record_rel` 同一口径）；
    不给只能退回文件名 —— 那种 source 只在"记录就住在容器根"时才对得上。
    """
    rec = parse_record(full_path)
    vheads = [h for h, _ in rec["sections"] if h.startswith(("四、验证", "验证"))]
    if container:
        rel = os.path.relpath(full_path, container).replace("\\", "/")
    else:
        rel = rec["name"]
    shown = display_source(rel, container)
    ctx0 = {"domain": domain, "source": shown,
            "applies_to": rec["meta"].get("主题", ""),
            "scope": rec["meta"].get("范围", ""),
            "boundary": rec["boundary"],
            "verify_anchor": (f"来源记录 `{shown}` 的"
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
            rel, found = record_rel(container, refs[0])
            cite = display_source(os.path.basename(rel), container)
            note = "" if found else "（记录未在本容器找到，可能已归档到别的工作区）"
            if note:
                cite += note
            src = display_source(rel, container)
            src_bytes = os.path.getsize(abs_in(container, rel)) if found else 0
            status = "ok" if found else "stale"
        elif refs:
            # 多条出处：**取第一条当主源**，别退回"分册"——分册是落点，不是这篇结论的出处；
            # 拿它当 source，读者会顺手去看整册，指认反而更糊。其余出处留在 cited_by 里。
            rel, found = record_rel(container, refs[0])
            cite = display_source(os.path.basename(rel), container)
            if not found:
                cite += "（记录未在本容器找到，可能已归档到别的工作区）"
            src = display_source(rel, container)
            src_bytes = os.path.getsize(abs_in(container, rel)) if found else 0
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
                            # 卡式条目的「验证」作为锚点；没有就留空，由 build_cards 走通用兜底。
                            "verify_anchor": norm_ws(entry.get("verify") or ""),
                            "src_bytes": src_bytes,
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


def index_rows(card_dir: str, container: str = "", write: bool = False) -> list[dict]:
    """扫已落盘的瘦卡 → INDEX 的行。确定性：同样的卡目录 → 逐字节同样的表。

    两件事与 cwd 无关，也都**只在真的允许写盘时**才落盘（`write`）：
      · `container` 给定时当场核源记录还在不在（不在就把 `source_status: stale` 补进卡里）；
      · 卡里写的是**工作区相对**路径（容器叫 `work_log` 就是 `work_log/0001-x.md`，
        叫 `ops` 就是 `ops/0001-x.md`），核之前把那一层前缀剥掉，再 `join(container, …)`。

    `write=False` 时只**报告**（返回行里带 `stale_now`），一个字节都不改：只读语义得住。

    **只收本工具投的卡**（2026-10-17 轮七，H-2b）：`*.pointer.md` 不是本工具专有的后缀
    （灵枢插件自己也往这里投卡），所以这里的判据必须与 `existing_cards()` **同一个**
    （`is_our_card()`）。从前只看后缀，于是第三条路漏了 —— `--index-only --write` 会把
    `source_status: stale` 写进**别人的卡**（实测 sha 变了），它们的行还会混进 INDEX
    与"归属"统计（连"源找不到"都算在我们头上）。H-2 那一轮只收口了"读入/撞名"两条路。
    """
    rows: list[dict] = []
    if not os.path.isdir(card_dir):
        return rows
    skipped: list[str] = []
    for fn in sorted(os.listdir(card_dir)):
        if not fn.endswith(".pointer.md"):
            continue
        p = os.path.join(card_dir, fn)
        if not os.path.isfile(p):
            continue                      # 目录/断链叫这个名字：既不是卡，也没什么可报的
        t = read(p)
        if not is_our_card(p, t):
            skipped.append(fn[: -len(".pointer.md")])
            continue
        source = _fm(t, "source")
        # 只在真给了容器时才核（容器空串 = 调用方只要表格，不做追溯校验）。
        # 卡里写的是 `work_log/0001-x.md`（工作区相对），而 `container` 已经指到容器根，
        # 直接 join 会得到 `…\work_log\work_log\…`，于是每张卡都被判成 stale（2026-10-16 真踩过）。
        # 剥前缀的判据取**容器自己的目录名**（2026-10-17 起 `display_source()` 写的就是它）；
        # 固定的 `work_log/` 也要认 —— 容器不叫 work_log 时，**已经落盘的旧卡**写的正是那个前缀，
        # 不认它那些卡就会集体"出生即 stale"（H2 修的是写入侧，读侧得两边都认）。
        missing = False
        if container and source:
            rel = source
            for prefix in (os.path.basename(container.rstrip("/\\")), "work_log"):
                if prefix and rel.startswith(f"{prefix}/"):
                    rel = rel[len(prefix) + 1:]
                    break
            missing = not os.path.exists(os.path.join(container, *rel.split("/")))
        if missing and "source_status: stale" not in t:
            if write:
                _mark_stale(p, t)
                full = os.path.join(card_dir, fn[: -len(".pointer.md")] + ".full.md")
                if os.path.isfile(full) and "source_status: stale" not in read(full):
                    _mark_stale(full, read(full))
                t = read(p)          # 改写后再读，后面解析标签用的是盘上那份
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
            "stale": ("source_status: stale" in t),
            "stale_now": missing,
            "napp": napp,
            "bytes": os.path.getsize(p),
            "no_boundary": bool(re.search(r"边界未在来源里显式声明", napp)),
            "path": fn,
        })
    rows.sort(key=lambda r: (r["domain"], r["id"]))
    if skipped:
        # 与 `existing_cards()` 同一路（stderr）同一口气：这是"这张不是我们的"，
        # 不是产物的一部分。走 stdout 会把外来卡的 id 混进"索引重建"的正文里 ——
        # 而自测里那条断言正是钉"别把它算成自家卡（只有 skip 提示可以点它的名）"。
        shown = "、".join(skipped[:3]) + ("…" if len(skipped) > 3 else "")
        print(f"[skip] {len(skipped)} 张卡不是本工具投的（frontmatter 没有 `tags: [dsh-lore, …]`）："
              f"{shown} —— 不收录进 INDEX，也不碰它们", file=sys.stderr)
    return rows


def _mark_stale(path: str, text: str) -> None:
    """把 `source_status: stale` 插进 frontmatter（只在真正允许写盘时调用）。"""
    write_atomic(path, re.sub(r"(?m)^(source:.*)$", r"\1\nsource_status: stale", text, count=1))


def printable_index(rows: list[dict], project: str, domain: str = "") -> str:
    """渲染 `memory-cards/INDEX.md`。

    「源」列**不截断**：从前这里是 `_clip(r["source"], 34)`，真容器 50 行里 46 行被切成
    `work_log/0108-review-r6-half-fixe…` —— 顺着索引定位不到记录，等于强迫读者开卡，
    索引的一半意义就这么没了（2026-10-17 复核）。路径本身不过一两百字节，换来的可定位性
    值得这几列宽度。

    头部「一行 ≈ N B」取**本份表格的实测均值**：从前写死 `150 B`（实测 300 B 上下，差一倍），
    「真源是它的十几倍到几十倍」也是没有分母的话 —— 一并改成指回「源」列，让读者自己看。
    """
    doms: dict[str, int] = {}
    for r in rows:
        doms[r["domain"]] = doms.get(r["domain"], 0) + 1
    dom_txt = "、".join(f"{k} {v}" for k, v in sorted(doms.items())) or "（无）"
    stale = [r for r in rows if r["stale"]]
    nob = [r for r in rows if r["no_boundary"]]
    table = []
    for r in rows:
        # 源列不截断，但**必须**转义管道：`_clip` 会转义，而这里绕过了它（N1，2026-10-18）
        src = (r["source"] or "（未标）") + (" [源未找到]" if r["stale"] else "")
        src = src.replace("|", "\\|")
        table.append(f"| `{r['id']}` | {r['domain']} | {_clip(r['title'], 44)} | "
                     f"{_clip(r['exec'], 56)} | {_clip(r['cond'], 40)} | {src} | {r['bytes']} |")
    avg = round(sum(len(l.encode("utf-8")) for l in table) / len(table)) if table else 0
    body_line = (
        f"- 体量：INDEX 一行 ≈ {avg} B（本表实测），**先读这张表再决定读哪张卡**；一张卡 pointer "
        f"{min((r['bytes'] for r in rows), default=0)}–{max((r['bytes'] for r in rows), default=0)} B，"
        f"真源在「源」列那一行。"
        if rows else "- 体量：还没有卡（本目录里没有本工具投的卡）。"
    )
    out = [
        "# 记忆卡索引（memory-cards/INDEX.md）",
        "",
        f"> 自动生成，别手改：`python dsh-lore-card.py <容器> --index-only --write` 重建。",
        f"> 项目 `{project or '（未标注）'}` · 项目域 `{domain or '（未标注）'}` · "
        f"卡 {len(rows)} 张（只算本工具投的） · 域：{dom_txt}",
        "",
        body_line,
    ]
    if not rows:
        # 空目录不再写「所有卡都…」这种对 0 张卡恒真的话（N2，2026-10-18）
        return "\n".join(out + ["- 归属与边界：还没有卡。"]) + "\n"
    out += [
        f"- 归属：{len(stale)} 张的源记录不在本容器（`[源未找到]`）——卡本身没错，错的是追溯链。"
        if stale else "- 归属：全部卡的源记录都在本容器内。",
        f"- 边界：{len(nob)} 张**没有**显式声明的「不适用条件」（卡里如实写了「边界未在来源里显式声明」，"
        f"引用前先看源记录的「范围」「遗留」两节）。" if nob
        else "- 边界：所有卡都有显式声明的「不适用条件」。",
        "",
        "| id | 域 | 功能名 | 执行（一句） | 生效条件 | 源 | 卡 B |",
        "|---|---|---|---|---|---|---|",
    ]
    return "\n".join(out + table) + "\n"


def write_index_file(path: str, rows: list[dict], project: str, domain: str = "",
                     write: bool = False) -> bool:
    """只在**内容真的变了**才写盘：否则每次跑都动 git 里的一个文件，纯噪声。"""
    body = printable_index(rows, project, domain)
    old = read(path) if os.path.isfile(path) else None
    if old == body:
        return False
    if write:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_atomic(path, body)
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
        # 容器**相对工作区根**的路径（`work_log`）。从前写的是
        # `os.path.relpath(container, os.path.dirname(card_dir))`，而 `card_dir` 就是
        # `<container>/memory-cards` —— 两者同一个目录，relpath 恒等于 `"."`（2026-10-17
        # 复核发现：真实容器里那份清单也写着 `container: "."`，看的人会以为容器在
        # `memory-cards/` 那一层）。容器总是工作区根下的一级目录，所以拿它的父目录当基准。
        "container": os.path.relpath(container, os.path.dirname(container)).replace("\\", "/"),
        "domain": domain,
        "count": len(rows),
        "cards": [{"id": r["id"], "pointer": r["path"], "bytes": r["bytes"],
                   "stale": bool(r["stale"])} for r in rows],
    }
    buf = io.StringIO()
    json.dump(data, buf, ensure_ascii=False, indent=2)
    write_atomic(path, buf.getvalue() + "\n")
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
        # `write` 透传进去（2026-10-17 修 H3）：不给 `--write` 时这条命令**一个字节都不改** ——
        # 从前陈旧标记是无条件写盘的，于是 `--index-only` 会改写卡、却又不写 INDEX.md，
        # 还打印"已重建"：只读语义破了，盘上留下"卡说 stale、索引说新鲜"的持久不一致。
        rows = index_rows(card_dir, container, write=args.write)
        wrote = write_index_file(index_path, rows, project, domain, write=args.write)
        stale_now = [r for r in rows if r.get("stale_now")]
        print(f"容器：{container}")
        print(printable_index(rows, project, domain).rstrip())
        if stale_now:
            print(f"\n注意：{len(stale_now)} 张卡的源记录不在本容器"
                  f"（{'、'.join(r['id'] for r in stale_now[:5])}"
                  f"{'…' if len(stale_now) > 5 else ''}）"
                  f"{'，已把 source_status: stale 写回卡' if args.write else '；加 --write 才写回卡'}")
        print(f"\n{'已重建' if wrote else ('无变化（写了，内容没变）' if args.write else '未写盘（没给 --write）')}"
              f"：{index_path}")
        return 0
    cards = existing_cards(card_dir)

    # 收集待投影的「一条教训」
    units: list[tuple[dict, dict]] = []   # (lesson, ctx)
    if args.all:
        for rp in all_records(container, include_archive=args.include_archive):
            got = rec_units(rp, args.domain, container)
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
                    lp_ = os.path.join(les_dir, fn)
                    # 与卡目录那两处**同一道守卫**（2026-10-17 轮十）：只按后缀收，
                    # 会把**目录**（断链同理）也当成一册收进来，`parse_lessons()`
                    # 的 `read()` 打在目录上抛 `PermissionError` —— 整次投影中止、
                    # rc=1，用户看到的是一条裸栈。三处枚举点现在过同一道 `isfile`。
                    if not os.path.isfile(lp_):
                        continue
                    units += lessons_units(container, lp_, args.domain)
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
        if not os.path.isfile(full_path):
            # 从前这里直接把路径交给 `rec_units()`，于是 `read()` 抛出裸的
            # `FileNotFoundError` 回溯（栈顶在 `read()`），不是给人看的
            # （2026-10-17 复核）。记录**已经归档**是最常见的原因 —— 归档后它不在容器根了，
            # 所以顺手用 `record_rel()` 找一下它在哪，直接把路指出来。
            hint = ""
            m_no = re.match(r"(\d+)", os.path.basename(rec_path))
            if m_no:
                rel, found = record_rel(container, m_no.group(1))
                if found:
                    hint = f"；它在 `{display_source(rel, container)}`（记录可能已归档到子目录）"
            print(f"ERROR: 找不到记录 `{args.rec}` —— 找过 `{full_path}`{hint}")
            return 1
        units = rec_units(full_path, args.domain, container)
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
    similar_only = 0
    used_slugs: dict[str, int] = {}
    # 本工具已有卡的 id 全集：`avoid_foreign()` 用它区分"这个名字是我们的"与"是外人的"。
    our_ids = {c["id"] for c in cards}
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
        # 第二道撞名：磁盘上这个名字压着一张**外来卡**（别的工具投的 pointer，命名规则可能
        # 一样）。读的一侧早就跳过它了，写的一侧从前不查 —— 那就成了"报着跳过、实际覆盖"。
        # 这一查必须在 `ctx["pointer_path"]` / `full_rel` 落定**之前**：卡里写的正文真源
        # 路径是从 slug 拼的，改名要两个文件一起改（2026-10-17 复核发现）。
        # 不给 `--write` 时也照样报：预演与实际落盘得是同一个名字，否则预演没有意义。
        slug, why = avoid_foreign(card_dir, slug, our_ids, used_slugs)
        if why:
            print(f"[{i}] 改名 {why}\n")
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
            # 第三道（**兜底**，2026-10-17 轮七写明）：比对面是**整份卡文件**（`c["text"]`，
            # 含 frontmatter、出处、标题那一行），而手里这个只是正文 `les["body"]` ——
            # 分母天生比分子大得多，所以 `≥ 0.72` 在真数据上基本打不中（实测不同卡
            # 0.15 上下，同源命中实际靠的是标题 Jaccard 1.00 那条）。留着它是为了
            # "改了措辞的同一条"那种长正文，别指望它在日常数据上响。
            best, best_s = None, 0.0
            for c in cards:
                s = max(similarity(les["body"], c["text"]), similarity(les["title"], c.get("title", "")))
                if s > best_s:
                    best, best_s = c, s
            if best is not None and best_s >= DUP_THRESHOLD:
                hit, why = best, f"与已有卡 `{best['id']}` 正文/标题相似度 {best_s:.2f} ≥ {DUP_THRESHOLD}"

        # ── `--list-similar`：只报相似度，一张卡也不出、一个字节也不写 ────────
        # 这个开关从前只声明、没人读（`--help` 许了一个不做的事，2026-10-17 复核发现）。
        # 实现放在这三道去重**之后**：`hit` 已经把"会不会 REUSE、为什么"算出来了，
        # 这里只是把"离阈值还有多远"补给人看 —— 调卡的时候要的正是这个距离。
        if args.list_similar:
            ranked = sorted(
                ((max(similarity(les["body"], c["text"]), similarity(les["title"], c.get("title", ""))), c)
                 for c in cards), key=lambda t: -t[0])[:3]
            print(f"[{i}] {les['title']}")
            print(f"    {'会 REUSE `' + hit['id'] + '`（' + why + '）' if hit is not None else '会新建一张卡'}")
            if not ranked:
                print("    （还没有已有卡可比）")
            for s, c in ranked:
                print(f"    {s:.2f} {'≥' if s >= DUP_THRESHOLD else '<'} {DUP_THRESHOLD}"
                      f"  {c['id']}   {c.get('title', '')}")
            print()
            similar_only += 1
            continue

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
                write_atomic(os.path.join(card_dir, fn), body)
            print(f"→ 已写 {card_dir}\\{slug}.pointer.md / .full.md")
        print()

    if args.list_similar:
        print(f"共 {len(units)} 条教训：报了 {similar_only} 条的相似度，"
              f"**没出卡、没写盘**（这是只读的对照模式）")
        return 0
    print(f"共 {len(units)} 条教训：新增 {sum(1 for _ in by_key) if any_new else 0} 张，"
          f"复用/收敛 {sum(expand.values())} 条，丢弃 {len(dropped)} 条")
    if expand:
        for cid, n in sorted(expand.items(), key=lambda kv: -kv[1]):
            print(f"  · `{cid}` 再吃进 {n} 条（→ 灵枢侧应是把新内容 augment 到同一个 node）")
    for d in dropped:
        print(f"  · DROP {d}")
    print("（dry-run：什么都没写。加 --write 才落盘）" if not args.write else f"卡目录：{card_dir}")
    if args.write:
        rows = index_rows(card_dir, container, write=True)
        wrote = write_index_file(index_path, rows, project, domain, write=True)
        # 只在这一轮**真的动过盘**时才重写清单：纯复用的一轮不该动 git 里的文件。
        if wrote or any_new:
            write_manifest(card_dir, container, domain, rows)
        print(f"索引：{index_path}（{len(rows)} 行，{'已重建' if wrote else '无变化未写'}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
