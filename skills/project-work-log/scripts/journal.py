#!/usr/bin/env python3
"""journal.py — 项目长期工作记录（work_log 容器：台账 + 过程记录 + lessons）的工具箱。

目录布局（唯一源：references/conventions.md「目录布局」）
--------------------------------------------------------
    工作记录容器 = <项目根>/work_log/   （默认名，可配置；旧名 journal/、work-log/ 仍被识别）

        README.md            台账（唯一）：索引 + 同主题簇 + 待办 + 当前状态
        NNNN-*.md            过程记录，直接放在容器根
        <YYYY>/NNNN-*.md     按年分卷后的记录
        <stage>/NNNN-*.md    归档记录，阶段目录直接建在容器下（不再有 archive/ 一层）
        STATE-HISTORY.md     被替换下来的旧「当前状态」块
        ARCHIVE.md           归档索引
        lessons/             经验层（分册），是容器的子目录
        logs/<来源>/         日志与运行产物（见 conventions.md「日志归位要求」）

设计目标：**少读、少写、可校验**。
- 少读：brief / show / search / outline 只吐出需要的那点内容，不必读 50 KB 的索引。
- 少写：status / todo / index / append / lesson 做外科式行级编辑（保留 CRLF 与其余字节）。
- 可校验：check 查结构，lint 查内容质量，两者都可当门禁（退出码 1）。

命令分组
--------
读写 · 上下文
    brief     压缩上下文快照（当前状态 + 待办 + 近期记录），替代整读索引
    show      单篇大纲（元数据 + 小节 + 行数），决定要不要读全文
    search    定向检索（记录 + 经验），只回命中行
    outline   全部记录的一行表（编号/日期/迭代/标题）

读写 · 维护
    new       生成下一篇记录（--insert 自动补索引行）
    status    当前状态块：show / set / date / roll
    mode      记录精细度（一篇 = 什么）：show / --set / --why
    todo      待办清单：list / add / done / drop-done
    index     索引：sync 补漏行
    lesson    经验：add 追加带来源的条目
    append    向某篇记录追加小节（更正 / 遗留）

读写 · 分析与生成
    check     结构门禁（编号、日期、验证、死链、漏索引、状态、来源）
    lint      内容质量（占位符残留、空小节、含糊措辞、结论缺数字）
    stats     语料统计（节奏、长度、合规率、引用覆盖）
    topics    同主题簇建议（关键词共现 / --keywords 指定）
    digest    生成交接摘要文档（--out 落盘）
    retro     阶段复盘骨架（篇号区间 → 阶段表 + 遗留汇总）
    export    机器可读导出（--json / --csv）

只用 Python 标准库。约定见 references/conventions.md，模板见 references/templates.md。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import zipfile

try:  # Windows 控制台默认码页可能不是 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

# ---- 解析标签（与 references/conventions.md 保持一致）----
# 约定：**写入时用每组的第一项**（中文默认），**解析时接受全部别名**。
# 这样非中文项目只要用别名（Date/Conclusion/Status/TODO…）就能被正确解析。
L_DATE = ("日期", "Date")
L_CONCLUSION = ("结论", "Conclusion", "Result")
L_TRIGGER = ("触发", "Trigger", "Context")
L_SCOPE = ("范围", "Scope")
L_ITER = ("迭代", "变更集", "批次", "阶段", "版本", "里程碑", "Iteration", "Milestone")
L_VERIFY = ("验证", "实测", "复核", "检查", "审查", "评审", "结果", "证据", "评估", "确认",
            "Verification", "Review", "Results", "Evidence", "Tests")
L_STATUS = ("当前状态", "Status", "Current Status")
L_TODO = ("待办", "TODO", "Todo", "Tasks")
L_INDEX = ("文件索引", "Index", "Contents", "File Index")


def _any(aliases: tuple[str, ...]) -> str:
    """把别名表编成正则的可选分支（非捕获），供解析用。"""
    return "|".join(re.escape(a) for a in aliases)


# 写入 / 显示用的默认名（各取第一个）
K_DATE = L_DATE[0]
K_ITER_DEFAULT = L_ITER[0]
K_VERIFY = L_VERIFY[0]
K_STATUS = L_STATUS[0]
K_TODO = L_TODO[0]
# 兼容旧名（内部与自测都在用）
K_ITER_ALIASES = L_ITER
VERIFY_WORDS = L_VERIFY

ENTRY_RE = re.compile(r"^(\d+)(?:-.*)?\.md$")
# 按年分卷后的目录名：**恰好 4 位数字**才算年份卷，所以 `02-research` 这类阶段名不会被误认。
YEAR_DIR_RE = re.compile(r"^\d{4}$")
HEADING_RE = re.compile(r"^#\s*(\d+)\s*[·.、:：]")
H1_RE = re.compile(r"^#\s+(.+)$", re.M)
DATE_LINE_RE = re.compile(rf"^(?:{_any(L_DATE)})\s*[：:]\s*(\S+)", re.M)
CONCLUSION_RE = re.compile(rf"^(?:{_any(L_CONCLUSION)})\s*[：:]\s*(.*)$", re.M)
TRIGGER_RE = re.compile(rf"^(?:{_any(L_TRIGGER)})\s*[：:]\s*(.+)$", re.M)
SCOPE_RE = re.compile(rf"^(?:{_any(L_SCOPE)})\s*[：:]\s*(.+)$", re.M)
STATUS_HEAD_RE = re.compile(
    rf"^#{{2,3}}[ \t]*(?:{_any(L_STATUS)})[ \t]*(?:[（(][^）)\r\n]*[）)])?[ \t]*$", re.M)
ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
VERIFY_HEAD_RE = re.compile(rf"^#{{2,4}}\s*.*(?:{_any(L_VERIFY)})", re.M)
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
CITE_RE = re.compile(r"wl/(\d+)")
# 状态块标题后面的日期括号：全角 `（…）` 与半角 `(…)` 都要认（英文台账用半角）。
DATE_PAREN_RE = re.compile(r"[（(][^）)\r\n]*[）)]")
# 模板里的日期占位符：识别它是为了"刚初始化"和"真的没写日期"能分开。
STATUS_DATE_PLACEHOLDER = re.compile(r"YYYY-MM-DD")

STATUS_KEYS = ["阶段 / 版本", "迭代", "产出", "核对 / 验证", "交付物与指纹", "环境", "阻塞 / 等待",
               "精细度"]

# 记录精细度（台账 `## 当前状态` 的第八个固定字段 `精细度`）。
# 字段值一律写**拉丁规范值**；下面这张表同时是中文别名表与人类可读释义。
# 精细度只放宽「要不要另起一篇」，**不放宽验证要求**：任何档位都必须有验证小节。
MODES: dict[str, tuple[str, ...]] = {
    "full": ("full", "完整", "详细", "细"),
    "session": ("session", "会话", "一次会话", "单次会话"),
    "digest": ("digest", "摘要", "汇总", "归并"),
    "milestone": ("milestone", "里程碑", "收口", "阶段收口"),
}
MODE_DEFAULT = "session"
MODE_MEANING = {
    "full": "一段可交付的子单元就是一篇，一次会话可能开出 2–3 篇。",
    "session": "一次会话最多一篇；同一会话里的第二件事追加到同一篇。",
    "digest": "一篇覆盖一个阶段（跨多次会话），把多轮会话并成一篇。",
    "milestone": "阶段收口才写，只留决策与经验。",
}
# 粗档位（digest / milestone）必须写明「这一轮刻意没有记录什么」，否则粗粒度会静默丢信息。
# 认「未记录 / 未记 / 未收录」三种写法，标题或正文里出现都算。
MODE_COARSE = ("digest", "milestone")
UNRECORDED_KEY = "未记录"
UNRECORDED_WORDS = ("未记录", "未记", "未收录")
MODE_ALIASES = {a: canon for canon, aliases in MODES.items() for a in aliases}

# ---- 容器布局 ----
# 记录体系收在**一个**容器目录里（过程记录 + 台账 + 经验层 + 日志）。
# 容器名可配置，默认 `work_log/`；旧名 `journal/`、`work-log/` 仍按回退顺序识别——
# 只解析、不迁移、不警告、不自动改名。见 references/conventions.md。
CONTAINER_DEFAULT = "work_log"
CONTAINER_FALLBACKS = ("work_log", "journal", "work-log")
LESSONS_DEFAULT = "lessons"
# 容器内**不属于过程记录**的子目录：经验层与日志。
# `--lessons` 改名后由调用方把实际名字并进来（见 lessons_skip）。
NON_RECORD_DIRS = ("lessons", "logs")
# 容器根上的辅助文档（旧布局里它们住在 archive/ 下）
ARCHIVE_INDEX = "ARCHIVE.md"
STATUS_HISTORY = "STATE-HISTORY.md"
COLD_STORE = "COLD-STORE.md"


def _status_key_parts(key: str) -> list[str]:
    """把字段名切成可比较的片段：先按 `/`，再按 `与`（`交付物与指纹` 的两种写法）。"""
    parts: list[str] = []
    for chunk in key.split("/"):
        parts.extend(p for p in chunk.split("与") if p)
    return [p.strip() for p in parts if p.strip()]


def resolve_status_key(key: str) -> str:
    """把用户写的字段名解析成 `## 当前状态` 里的规范字段名，认不出就原样返回。

    约定里字段名固定（见 STATUS_KEYS），但写法有长有短：`核对` 对应 `核对 / 验证`，
    `交付物` 对应 `交付物与指纹`。只做**唯一**匹配——`阶段` 同时命中 `阶段 / 版本` 的
    片段，而 `版本` 单独出现时只命中它自己，所以两者都能用；歧义时保守不改。
    """
    want = _status_key_parts(key)
    if not want:
        return key
    exact = [k for k in STATUS_KEYS if k == key.strip()]
    if exact:
        return exact[0]
    hits = [k for k in STATUS_KEYS if set(want) & set(_status_key_parts(k))]
    return hits[0] if len(hits) == 1 else key


PLACEHOLDERS = ["<命令 / 数据 / 引用 / 样本>", "<验证命令>", "<一句话", "<标题", "<对象>", "<项目>", "TODO", "TBD", "XXX", "待填", "待补充"]
VAGUE = ["应该没问题", "应该可以", "大概", "可能没问题", "似乎", "估计", "应该是"]

STOPWORDS = {
    "this", "that", "with", "from", "http", "https", "true", "false", "null", "none",
    "test", "tests", "todo", "readme", "index", "file", "files", "line", "lines",
    "data", "path", "name", "type", "value", "list", "item", "items", "https",
}

ENTRY_TEMPLATE = """# {num:04d} · {title}

日期：{date}
迭代：{iter}
触发：
范围：
结论：

---

## 一、背景与事实核查

## 二、方案与取舍

## 三、执行

| 对象 | 改动 |
|---|---|
|  |  |

## 四、验证

- 方式：`{cmd}`
- 结果：
- 未覆盖：

## 五、遗留与下一步

- [ ] 
"""

STATUS_SKELETON = """## {head}（{date}）

{fields}
"""


# --------------------------------------------------------------------------- #
# IO / 通用工具
# --------------------------------------------------------------------------- #
def read(path: str) -> str:
    """读取并归一换行（仅用于解析，不用于回写）。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def read_raw(path: str) -> str:
    """保留原始换行读取（外科式编辑用）。"""
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as fh:
            return fh.read()
    except OSError:
        return ""


def utf8_problem(path: str) -> str | None:
    """目标文件不是合法 UTF-8 时返回原因，否则 None（文件不存在也算 None）。

    读的时候用 `errors="replace"` 是为了"读不崩"，但**写**回去会把那些被替换成
    `U+FFFD` 的字节永久固化——一个 GBK 老仓库会在第一次 `status --set` 时丢掉所有中文。
    这里在写之前先严格解一遍：解不开就拒绝写，宁可报错也不静默毁数据。
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as fh:
            if fh.read() == b"":
                return None
        with open(path, encoding="utf-8", newline="") as fh:
            fh.read()
    except UnicodeDecodeError as exc:
        return (f"目标文件不是 UTF-8（第 {exc.start} 字节起）：{exc.reason}")
    except OSError as exc:
        return f"目标文件读不出来：{exc}"
    return None


def write_raw(path: str, text: str) -> None:
    """外科式写回。非 UTF-8 目标会抛 `ValueError`，绝不把坏字节写成 `U+FFFD`。"""
    problem = utf8_problem(path)
    if problem is not None:
        raise ValueError(problem)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def _file_size(path: str) -> int:
    """磁盘上的真实字节数（读不出来就算 0，别让统计炸掉）。"""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def nl_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def resolve_dir(root: str, name: str | None, fallbacks: tuple[str, ...]) -> str | None:
    for c in ([name] if name else list(fallbacks)):
        if c and os.path.isdir(os.path.join(root, c)):
            return os.path.join(root, c)
    return None


def resolve_lessons(root: str, container: str | None, name: str | None) -> str | None:
    """经验目录：先看容器内（新布局 `<容器>/lessons/`），再看项目根（旧布局 `<根>/lessons/`）。"""
    for base in (container, root):
        if not base:
            continue
        found = resolve_dir(base, name, (LESSONS_DEFAULT,))
        if found:
            return found
    return None


def resolve_layout(root: str, container_arg: str | None, lessons_arg: str | None
                   ) -> tuple[str | None, str | None]:
    """一次解析出（容器目录, 经验目录）。

    容器回退顺序 `work_log/` → `journal/` → `work-log/`：新项目用 `work_log/`；
    旧项目只要还在用旧名就照旧被认出来，**不迁移、不改名、不警告**。
    """
    container = resolve_dir(root, container_arg, CONTAINER_FALLBACKS)
    return container, resolve_lessons(root, container, lessons_arg)


def lessons_skip(lessons: str | None) -> tuple[str, ...]:
    """`find_entries` 的排除项：经验目录即使被 `--lessons` 改名也不是过程记录。

    `lessons/01-topic.md`、`99-retrospectives.md` 的文件名与记录编号形状相同，
    不排除就会变成 #1 / #99 两条假记录。
    """
    name = os.path.basename((lessons or "").rstrip("/\\"))
    return (name,) if name else ()


def _aux_path(container: str, legacy_name: str, name: str) -> str:
    """辅助文档落点：新布局在容器根；旧布局已存在 `archive/<legacy_name>` 就沿用它。

    沿用而不是另起一份，是为了不把同一段历史（状态块 / 归档索引 / 冷存清单）
    劈成两个文件——历史只搬运、不改写，也不该被搬家。
    """
    legacy = os.path.join(container, "archive", legacy_name)
    if os.path.exists(legacy):
        return legacy
    return os.path.join(container, name)


def status_history_path(container: str) -> str:
    """旧「当前状态」块的落点（新布局：`<容器>/STATE-HISTORY.md`）。"""
    return _aux_path(container, "STATUS-HISTORY.md", STATUS_HISTORY)


def archive_index_path(container: str) -> str:
    """归档索引落点（新布局：`<容器>/ARCHIVE.md`）。"""
    return _aux_path(container, "README.md", ARCHIVE_INDEX)


def cold_store_path(container: str) -> str:
    """冷存清单落点（新布局：`<容器>/COLD-STORE.md`）。"""
    return _aux_path(container, "COLD-STORE.md", COLD_STORE)


def find_entries(container: str, skip_dirs: tuple[str, ...] = ()) -> dict[int, list[str]]:
    """容器下所有编号记录（含归档与分卷）。

    `skip_dirs` 用来排除容器内**不是记录**的子目录：经验层（`--lessons` 改名后
    要显式传进来，见 `lessons_skip`）与日志目录（`logs/`）。它们里面的
    `01-topic.md`、`2026-01-01-run.md` 与记录文件名形状相同，不排除就会被当成记录。
    """
    skip = {".git", "node_modules", *NON_RECORD_DIRS, *skip_dirs}
    found: dict[int, list[str]] = {}
    for dp, dn, fn in os.walk(container):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            m = ENTRY_RE.match(f)
            if m:
                found.setdefault(int(m.group(1)), []).append(os.path.join(dp, f))
    return found


def _rel_parts(container: str, path: str) -> list[str]:
    """path 相对容器的路径分段（不同盘符时返回空表）。"""
    try:
        relp = os.path.relpath(os.path.abspath(path), os.path.abspath(container))
    except ValueError:
        return []
    return relp.split(os.sep)


def is_active_entry(container: str, path: str) -> bool:
    """活跃记录 = 在容器根，或在按年分卷的 `<YYYY>/` 下。

    归档不再是字面量 `archive/` 子目录：阶段目录直接建在容器下（`<stage>/NNNN-*.md`），
    所以判据是「相对路径的第一段是 4 位年份 ⇒ 活跃，是别的子目录 ⇒ 已归档」。
    旧布局的 `archive/<stage>/NNNN-*.md` 走同一条规则即可（`archive` 不是年份目录），
    不需要为它特判；旧版的 `journal/<YYYY>/` 分卷也仍然是活跃记录。
    """
    parts = _rel_parts(container, path)
    return len(parts) < 2 or bool(YEAR_DIR_RE.match(parts[0]))


def is_archived_entry(container: str, path: str, skip_dirs: tuple[str, ...] = ()) -> bool:
    """已归档记录 = 编号记录文件，且位于容器下的阶段目录里。

    `lessons/01-topic.md`、`lessons/99-retrospectives.md` 的文件名与编号记录同形，
    `logs/<来源>/2026-01-01-run.md` 也是；`README.md`、`STATE-HISTORY.md`、`ARCHIVE.md`
    同样住在容器里。它们**都不是记录**：一律先按路径与文件名挡掉，
    否则 `index compact` 会把经验分册折成一个「归档阶段」（`--lessons` 改名后
    由 `skip_dirs` 补上实际名字，见 `lessons_skip`）。
    """
    if not ENTRY_RE.match(os.path.basename(path)):
        return False
    parts = _rel_parts(container, path)
    if len(parts) < 2:
        return False
    if parts[0] in NON_RECORD_DIRS or parts[0] in skip_dirs or YEAR_DIR_RE.match(parts[0]):
        return False
    return True


def entry_link(container: str, path: str) -> str:
    """索引行里用的链接（相对容器根），天然支持 `<YYYY>/` 与 `<stage>/` 两种子目录。"""
    return rel(container, path)


def _under(path: str, parent: str) -> bool:
    """path 是否在 parent 目录内（大小写无关，Windows 友好）。"""
    p = os.path.normcase(os.path.abspath(path))
    q = os.path.normcase(os.path.abspath(parent))
    return p == q or p.startswith(q + os.sep)


def scan_bases(container: str | None, lessons: str | None) -> list[str]:
    """需要扫描 / 改链接的目录：容器 +（只在旧布局下才单列的）经验目录。

    新布局里 `lessons/` 就在容器内，重复列入会把同一批文件扫两遍——
    链接改写被重复计数、死链被重复上报。
    """
    bases = [container] if container else []
    if lessons and not (container and _under(lessons, container)):
        bases.append(lessons)
    return bases


def rewrite_links(base_dirs: list[str], moves: dict[str, str], dry_run: bool = False
                  ) -> list[tuple[str, str, str]]:
    """把指向被移动文件的相对链接改指到新位置，返回 [(文件, 旧链接, 新链接)]。

    `moves` = {**旧绝对路径**: 新绝对路径}。只改 .md 里的 markdown 链接；
    `wl/NNNN` 这类纯编号引用不受目录变化影响，故意不动。

    关键点：链接是**相对于写它的那个文件**的，脚本在移动**之后**才改写，所以
    被移动文件自己的正文必须按**它原来的目录**来解析（否则 `[b](0002-b.md)`
    会被当成"相对新目录"，算出 `0002-b.md` 这种原地不动的错链）。
    """
    changed: list[tuple[str, str, str]] = []
    # 规范化后的 旧路径 → 新绝对路径。再用它反查 新路径 → 旧路径，
    # 这样"这个文件原来在哪儿"和"这个链接目标搬没搬"都能回答。
    lookup = {os.path.normcase(os.path.abspath(old)): new for old, new in moves.items()}
    was_at = {os.path.normcase(os.path.abspath(new)): old for old, new in moves.items()}

    def fixer(path: str, base: str, frame_dir: str):
        def sub(m: re.Match) -> str:
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                return m.group(0)
            anchor = ""
            if "#" in target:
                target, anchor = target.split("#", 1)
                anchor = "#" + anchor
            if not target:
                return m.group(0)
            # 在"书写者坐标系"里还原链接指向的真实文件。
            real = os.path.normpath(os.path.join(frame_dir, target.replace("/", os.sep)))
            new_path = lookup.get(os.path.normcase(real))
            if new_path is None and os.path.normcase(frame_dir) != os.path.normcase(os.path.dirname(path)):
                # 书写者被移动了、目标没搬：按老坐标反算新的相对路径，
                # 否则 `[b](0002-b.md)` 从 `archive/S/` 看过去就断了。
                if not os.path.exists(real):
                    return m.group(0)
                new_path = real
            elif new_path is None:
                # 书写者就在原地、目标也没搬：链接本来就对，一个字都别动。
                return m.group(0)
            new_target = os.path.relpath(new_path, os.path.dirname(path)).replace(os.sep, "/") + anchor
            if new_target != m.group(1):
                changed.append((rel(base, path), m.group(1), new_target))
            return f"]({new_target})"
        return sub

    for base in base_dirs:
        if not base or not os.path.isdir(base):
            continue
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in (".git", "node_modules")]
            for f in fn:
                if not f.endswith(".md"):
                    continue
                path = os.path.join(dp, f)
                # 被移动过的文件：正文按它**原来**的目录解析；没移动过的：就地解析。
                frame_dir = os.path.dirname(was_at.get(os.path.normcase(path), path))
                text = read_raw(path)
                new_text = LINK_RE.sub(fixer(path, base, frame_dir), text)
                if new_text != text and not dry_run:
                    write_raw(path, new_text)
    return changed


def max_date_in(text: str) -> _dt.date | None:
    best = None
    for m in ISO_DATE_RE.finditer(text):
        try:
            d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if best is None or d > best:
            best = d
    return best


def today() -> str:
    return _dt.date.today().isoformat()


def slugify(title: str) -> str:
    """把标题压成文件名后缀；**纯中文标题**返回空串。

    返回空串而不是 "entry"：中文项目的每篇都会叫 `entry`，`0027-entry.md` 这种名字
    既没有信息量又容易撞。空后缀会生成 `0027.md`——篇号本来就是地址（`wl/NNNN`），
    文件名里只留编号是完全可以接受的，想要 ASCII slug 就用 `--slug` 自己指定。
    """
    s = re.sub(r"[^0-9a-zA-Z]+", "-", title).strip("-").lower()
    return re.sub(r"-{2,}", "-", s)[:48]


def parse_iter(text: str) -> str:
    """从记录入口行读迭代标识，兼容各领域的叫法（迭代/变更集/批次/阶段/版本/里程碑）。"""
    for key in K_ITER_ALIASES:
        m = re.search(rf"^{re.escape(key)}\s*[：:]\s*(\S+)", text, re.M)
        if m:
            return m.group(1)
    return ""


def meta_of(path: str) -> dict:
    """解析一篇记录的元数据（不全量保留正文）。"""
    text = read(path)
    h1 = H1_RE.search(text)
    title = re.sub(r"^\d+\s*[·.、:：]\s*", "", h1.group(1)).strip() if h1 else os.path.basename(path)
    dm = DATE_LINE_RE.search(text)
    iv = parse_iter(text)
    cm = CONCLUSION_RE.search(text)
    sections = re.findall(r"^(#{2,3})\s+(.+?)\s*$", text, re.M)
    return {
        "title": title,
        "date": dm.group(1) if dm else "",
        "iter": iv,
        "conclusion": (cm.group(1).strip() if cm else ""),
        "sections": [s[1] for s in sections],
        # 用 splitlines 而不是 count("\n")+1：后者对每个以换行结尾的文件都多算一行。
        "lines": len(text.splitlines()),
        # 磁盘上的真实字节数；不能用 len(text.encode())，因为 read() 会归一换行，
        # CRLF 文件会因此少算一半换行。
        "bytes": _file_size(path),
        "has_date": bool(dm),
        "has_verify": bool(VERIFY_HEAD_RE.search(text)),
    }


def all_metas(entries: dict[int, list[str]]) -> dict[int, dict]:
    return {n: meta_of(paths[0]) for n, paths in entries.items()}


# --------------------------------------------------------------------------- #
# 行级小节工具（保留换行与其余内容）
# --------------------------------------------------------------------------- #
def heading_level(line: str):
    m = re.match(r"^(#{1,6})[ \t]+(.*?)[ \t]*\r?\n?$", line)
    return (len(m.group(1)), m.group(2)) if m else None


def find_section(lines: list[str], level: int, keyword: str):
    """返回 (head_idx, body_start, body_end_exclusive)；body_end 为下一个同级或更高级标题。"""
    for i, line in enumerate(lines):
        h = heading_level(line)
        if h and h[0] == level and keyword in h[1]:
            j = i + 1
            while j < len(lines):
                hj = heading_level(lines[j])
                if hj and hj[0] <= level:
                    break
                j += 1
            return i, i + 1, j
    return None


def find_labeled_section(lines: list[str], level: int, aliases: tuple[str, ...]):
    """按别名表找小节（任一别名命中即可）——用于跨语言解析。"""
    for name in aliases:
        span = find_section(lines, level, name)
        if span:
            return span
    return None


def last_content_line(lines: list[str], start: int, end: int) -> int:
    """[start, end) 内最后一个非空行的下标；全空返回 start-1。"""
    for i in range(end - 1, start - 1, -1):
        if lines[i].strip():
            return i
    return start - 1


def insert_at_end_of_section(lines: list[str], start: int, end: int, new_lines: list[str]) -> None:
    pos = last_content_line(lines, start, end) + 1
    lines[pos:pos] = new_lines


def find_verify_section(lines: list[str]):
    """按各领域的叫法找「验证 / 复核」小节（验证、评审、检查、结果、证据…）。"""
    for level in (4, 3, 2):
        for word in VERIFY_WORDS:
            span = find_section(lines, level, word)
            if span:
                return span
    return None


def _checkable(text: str) -> bool:
    """是否含可核对的信息：命令（反引号）/ 数字 / 链接。用于 lint 的领域无关口径。"""
    return ("`" in text) or bool(re.search(r"\d", text)) or ("http" in text)


# --------------------------------------------------------------------------- #
# check：结构门禁
# --------------------------------------------------------------------------- #
class Report:
    def __init__(self, strict: bool) -> None:
        self.strict = strict
        self.rows: list[tuple[str, str]] = []
        self._seen: set[tuple[str, str]] = set()

    def add(self, level: str, where: str, msg: str) -> None:
        if self.strict and level == "WARN":
            level = "ERROR"
        key = (level, f"{where}: {msg}")
        if key in self._seen:
            return
        self._seen.add(key)
        self.rows.append((level, f"{where}: {msg}"))

    def errors(self) -> int:
        return sum(1 for lv, _ in self.rows if lv == "ERROR")

    def print(self, quiet: bool) -> None:
        order = {"ERROR": 0, "WARN": 1, "INFO": 2}
        for lv, text in sorted(self.rows, key=lambda r: order[r[0]]):
            if quiet and lv == "INFO":
                continue
            print(f"[{lv}] {text}")
        n = {lv: sum(1 for l, _ in self.rows if l == lv) for lv in ("ERROR", "WARN", "INFO")}
        print(f"\nSummary: {n['ERROR']} error / {n['WARN']} warn / {n['INFO']} info"
              + ("  (--strict)" if self.strict else ""))


def _check_links(root: str, path: str, rep: Report) -> None:
    base = os.path.dirname(path)
    where = rel(root, path)
    seen = set()
    for target in LINK_RE.findall(read(path)):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        # 先去掉 `#锚点` 再判断是不是 .md —— 否则 `x.md#part` 会被整条跳过，
        # 死链检查漏掉所有带锚点的链接。
        clean = target.split("#", 1)[0].strip()
        if not clean.endswith(".md") or clean in seen:
            continue
        seen.add(clean)
        if not os.path.exists(os.path.normpath(os.path.join(base, clean))):
            rep.add("ERROR", where, f"死链：{target}")


def check(root: str, journal_arg: str | None, lessons_arg: str | None, strict: bool) -> Report:
    rep = Report(strict)
    journal, lessons = resolve_layout(root, journal_arg, lessons_arg)
    if not journal:
        rep.add("ERROR", root, "找不到记录容器（work_log/；旧名 journal/、work-log/ 也认）；先按 templates.md 初始化")
        return rep
    jname = rel(root, journal)
    index = os.path.join(journal, "README.md")
    if not os.path.isfile(index):
        rep.add("ERROR", jname, "缺索引 README.md（台账）")

    entries = find_entries(journal, lessons_skip(lessons))
    nums = sorted(entries)
    if not entries:
        rep.add("INFO", jname, "目录里还没有编号记录（新项目正常）")
    for n, paths in sorted(entries.items()):
        if len(paths) > 1:
            rep.add("ERROR", jname, f"编号 {n} 重复：{[rel(root, p) for p in paths]}")
    if nums:
        gaps = [n for n in range(nums[0], nums[-1] + 1) if n not in entries]
        if gaps:
            shown = ", ".join(str(g) for g in gaps[:10]) + (" …" if len(gaps) > 10 else "")
            rep.add("WARN", jname, f"编号断档 {len(gaps)} 处：{shown}")

    total = sum(len(v) for v in entries.values())
    date_missing = verify_missing = 0
    for n in nums:
        for path in entries[n]:
            text = read(path)
            where = rel(root, path)
            h1 = H1_RE.search(text)
            if not h1:
                rep.add("WARN", where, "缺一级标题（应为 `# NNNN · 标题`）")
            else:
                m = HEADING_RE.match("# " + h1.group(1))
                if not m:
                    rep.add("WARN", where, "一级标题未带篇号（应为 `# NNNN · 标题`）")
                elif int(m.group(1)) != n:
                    rep.add("ERROR", where, f"标题篇号 {m.group(1)} 与文件名 {n} 不一致")
            dm = DATE_LINE_RE.search(text)
            if not dm:
                date_missing += 1
                rep.add("WARN", where, f"缺 `{K_DATE}：YYYY-MM-DD` 入口行")
            elif not ISO_DATE_RE.fullmatch(dm.group(1)):
                rep.add("WARN", where, f"日期格式不是 YYYY-MM-DD：{dm.group(1)}")
            if not VERIFY_HEAD_RE.search(text):
                verify_missing += 1
                rep.add("WARN", where, "缺「验证」小节（命令 + 结果 + 未覆盖）")
    if total:
        if date_missing:
            rep.add("INFO", jname, f"{date_missing}/{total} 篇缺日期行")
        if verify_missing:
            rep.add("INFO", jname, f"{verify_missing}/{total} 篇缺验证小节")

    if os.path.isfile(index):
        idx_text = read(index)
        _check_links(root, index, rep)
        for n in nums:
            if is_active_entry(journal, entries[n][0]) and entry_link(journal, entries[n][0]) not in idx_text:
                rep.add("WARN", jname, f"记录 {entry_link(journal, entries[n][0])} 未出现在索引中")
        blocks = STATUS_HEAD_RE.findall(idx_text)
        if not blocks:
            rep.add("WARN", jname, f"索引缺 `## {K_STATUS}` 块")
        elif len(blocks) > 1:
            rep.add("ERROR", jname, f"索引有 {len(blocks)} 个「{K_STATUS}」块"
                                    f"（只能有一个，旧块移入 {rel(root, status_history_path(journal))}）")
        else:
            after = idx_text.split(blocks[0], 1)[1]
            nxt = re.search(r"^#{2,3}\s", after, re.M)
            block = blocks[0] + (after[: nxt.start()] if nxt else after)
            sd = max_date_in(block)
            newest = None
            for n in nums:
                d = max_date_in(read(entries[n][0]))
                if d and (newest is None or d > newest):
                    newest = d
            if not sd:
                if STATUS_DATE_PLACEHOLDER.search(block):
                    # 刚按模板建好的骨架：日期还是 `YYYY-MM-DD`，填上就好，不算漂移。
                    rep.add("INFO", jname, f"「{K_STATUS}」日期还是模板占位符（`YYYY-MM-DD`），填上真实日期")
                else:
                    rep.add("WARN", jname, f"「{K_STATUS}」块没有日期（标题写 `## {K_STATUS}（YYYY-MM-DD）`）")
            elif newest and sd < newest:
                rep.add("WARN", jname, f"「{K_STATUS}」({sd}) 早于最新记录 ({newest})，台账可能过期")
        if not any(f"## {a}" in idx_text for a in L_TODO):
            rep.add("INFO", jname, f"索引没有「{K_TODO}」小节（滚动清单建议保留）")

    # 容器内的 md 逐个查链接；经验目录在下面单独查一遍，这里跳过它免得同一处死链报两次。
    in_container = set(lessons_skip(lessons))
    for dp, dn, fn in os.walk(journal):
        dn[:] = [d for d in dn if d not in (".git", "node_modules") and d not in in_container]
        for f in fn:
            if f.endswith(".md"):
                _check_links(root, os.path.join(dp, f), rep)

    if lessons:
        lname = rel(root, lessons)
        if not os.path.isfile(os.path.join(lessons, "README.md")):
            rep.add("ERROR", lname, "缺经验手册索引 README.md")
        for dp, dn, fn in os.walk(lessons):
            dn[:] = [d for d in dn if d not in (".git", "node_modules")]
            for f in fn:
                if not f.endswith(".md") or f == "README.md":
                    continue
                path = os.path.join(dp, f)
                where = rel(root, path)
                _check_links(root, path, rep)
                text = read(path)
                if not re.search(r"^#\s", text, re.M):
                    rep.add("WARN", where, "缺一级标题")
                cites = CITE_RE.findall(text)
                if not cites and "来源" not in text:
                    rep.add("WARN", where, "既没有 `wl/NNNN` 来源引用，也没有「来源」说明")
                for c in cites:
                    if int(c) not in entries:
                        rep.add("WARN", where, f"来源 `wl/{c}` 在记录目录里不存在")
    return rep


# --------------------------------------------------------------------------- #
# lint：内容质量门禁
# --------------------------------------------------------------------------- #
def lint(root: str, journal_arg: str | None, lessons_arg: str | None, strict: bool) -> Report:
    rep = Report(strict)
    journal, lessons = resolve_layout(root, journal_arg, lessons_arg)
    if not journal:
        rep.add("ERROR", root, "找不到记录容器（work_log/；旧名 journal/、work-log/ 也认）")
        return rep
    # 档位只在台账里读一次：粗档位的额外义务按它判（默认档 = session，不加要求）。
    mode, _mode_why, _mode_default = _mode_and_why(journal)
    for n, paths in sorted(find_entries(journal, lessons_skip(lessons)).items()):
        path = paths[0]
        where = rel(root, path)
        text = read(path)
        lines = text.splitlines()
        for token in PLACEHOLDERS:
            if token in text:
                rep.add("WARN", where, f"占位符未清理：`{token}`")
        cm = CONCLUSION_RE.search(text)
        if not cm or not cm.group(1).strip():
            rep.add("WARN", where, "「结论：」为空")
        elif not _checkable(cm.group(1)):
            rep.add("WARN", where, "结论没有可核对的信息（数字 / 引用 / 链接）")
        span = find_verify_section(lines)
        if span:
            body = "".join(lines[span[1]:span[2]]).strip()
            if len(body) < 10:
                rep.add("WARN", where, "验证小节为空")
            elif not _checkable(body):
                rep.add("WARN", where, "验证小节没有可核对的内容（命令 / 数据 / 引用 / 样本）")
            for w in VAGUE:
                if w in body:
                    rep.add("WARN", where, f"验证含含糊措辞：`{w}`")
        # 粗档位的额外义务：写明这一轮**刻意没有记录**什么。
        # 只出 WARN，且只在台账显式设成粗档位时生效——默认档（含没有 `精细度`
        # 字段的老台账）一句都不多说，所以老项目不会因为这条突然变红。
        if mode in MODE_COARSE and not any(w in text for w in UNRECORDED_WORDS):
            rep.add("WARN", where, f"精细度是 `{mode}`，但没写「{UNRECORDED_KEY}」——"
                                   f"补一行 `{UNRECORDED_KEY}：这一轮没记什么，见 …`，"
                                   f"否则粗档位会静默丢信息")
        for i, line in enumerate(lines):
            h = heading_level(line)
            if not h or h[0] < 2:
                continue
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j >= len(lines) or heading_level(lines[j]):
                rep.add("WARN", where, f"空小节：`{h[1]}`")
    return rep


# --------------------------------------------------------------------------- #
# 精细度（记录档位）：存在台账 `## 当前状态` 的 `精细度` 字段里
# --------------------------------------------------------------------------- #
# 字段值形如 `session` 或 `session（原因：阶段收口）`：规范值 + 可选的一行原因。
# 原因跟在同一条字段行里，是因为它随容器走、进版本控制、并复用已经测过的
# `status --set` 写入路径；另起文件或另开字段都不划算。
MODE_CELL_RE = re.compile(r"^\s*([A-Za-z0-9]+)\s*(.*)$")
MODE_WHY_RE = re.compile(r"^[（(]\s*(?:原因|理由)\s*[：:]\s*(.*?)\s*[）)]\s*$")


def mode_cell(text: str) -> str | None:
    """读出台账状态块里的 `精细度` 字段值；没有这个字段返回 None。"""
    lines = text.splitlines()
    span = find_labeled_section(lines, 2, L_STATUS)
    if not span:
        return None
    for line in lines[span[1]: span[2]]:
        m = re.match(r"^(\s*-\s*)([^：:\r\n]+)[：:][ \t]*(.*?)[ \t]*$", line)
        if m and m.group(2).strip() == "精细度":
            return m.group(3).strip()
    return None


def mode_of(text: str) -> tuple[str | None, str]:
    """从台账全文解析 (档位, 原因)。

    没有字段、或者值认不出来时返回 `(None, "")`——**不猜、不当作默认值**，
    好让调用方把「没有这一栏」和「写了一栏但写错了」分开处理。
    """
    cell = mode_cell(text)
    if not cell:
        return None, ""
    m = MODE_CELL_RE.match(cell)
    if not m:
        return None, ""
    canon = MODE_ALIASES.get(m.group(1).lower())
    if not canon:
        return None, ""
    wm = MODE_WHY_RE.match(m.group(2))
    return canon, (wm.group(1) if wm else "")


def mode_value(mode: str, why: str = "") -> str:
    """把档位（+可选原因）编成字段值。"""
    return f"{mode}（原因：{why}）" if why else mode


def _mode_and_why(journal: str) -> tuple[str, str, bool]:
    """返回 (生效档位, 原因, 是否来自默认值)。缺字段或值认不出来都算默认值。"""
    mode, why = mode_of(read(os.path.join(journal, "README.md")))
    return (mode, why, False) if mode else (MODE_DEFAULT, "", True)


# --------------------------------------------------------------------------- #
# brief / outline / show / search
# --------------------------------------------------------------------------- #
def status_block_text(journal: str) -> str:
    index = os.path.join(journal, "README.md")
    lines = read_raw(index).splitlines(keepends=True)
    span = find_labeled_section(lines, 2, L_STATUS)
    return "".join(lines[span[0]:span[2]]).strip() if span else ""


def todo_items(journal: str) -> tuple[list[str], list[str]]:
    index = os.path.join(journal, "README.md")
    lines = read_raw(index).splitlines()
    span = find_labeled_section(lines, 2, L_TODO)
    open_items, done_items = [], []
    if span:
        for line in lines[span[1]:span[2]]:
            if re.match(r"^\s*-\s*\[ \]", line):
                open_items.append(line.strip())
            elif re.match(r"^\s*-\s*\[[xX]\]", line):
                done_items.append(line.strip())
    return open_items, done_items


def _clip(text: str, width: int) -> str:
    text = text.rstrip()
    if len(text) <= width or width <= 1:
        # width <= 1 时再截就只剩 "…" 甚至倒扣一个字符，不如原样返回。
        return text
    return text[: width - 1] + "…"


def cmd_brief(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器")
        return 1
    entries = find_entries(journal, lessons_skip(lessons))
    nums = sorted(entries)
    root_nums = [n for n in nums if is_active_entry(journal, entries[n][0])]
    print(f"# BRIEF  {rel(root, journal)}  ({len(nums)} entries #{nums[0] if nums else '-'}–#{nums[-1] if nums else '-'};"
          f" active {len(root_nums)} / archive {len(nums) - len(root_nums)})")
    sb = status_block_text(journal)
    if sb:
        lines = sb.splitlines()
        cap = args.max_status_lines
        print("")
        print("\n".join(_clip(l, args.width) for l in lines[:cap]))
        if len(lines) > cap:
            print(f"… (+{len(lines) - cap} lines, use `status`)")
    else:
        print(f"\n(!) 索引里没有状态块")
    open_items, _ = todo_items(journal)
    print(f"\n## {K_TODO}（未完成 {len(open_items)}）")
    for it in open_items[: args.max_todo]:
        print(_clip(it, args.width))
    if len(open_items) > args.max_todo:
        print(f"… (+{len(open_items) - args.max_todo} more, use `todo`)")
    print(f"\n## 近期记录（{args.entries}）")
    for n in sorted(nums, reverse=True)[: args.entries]:
        m = meta_of(entries[n][0])
        it = f"迭代 {m['iter']}" if m["iter"] and m["iter"] != "-" else "不编号"
        print(f"#{n:<4d} {m['date'] or '(无日期)':10s} [{it}] {'OK ' if m['has_verify'] else 'NO '} {m['title'][:52]}")
    return 0


def cmd_outline(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器")
        return 1
    entries = find_entries(journal, lessons_skip(lessons))
    for n in sorted(entries):
        m = meta_of(entries[n][0])
        tag = m["iter"] if m["iter"] and m["iter"] != "-" else "-"
        print(f"{n:04d}\t{m['date'] or '-'}\t{tag}\t{m['lines']:4d}L\t{m['title'][:64]}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    root_arg, num = _root_and_num(args.paths)
    root = os.path.abspath(root_arg)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    entries = find_entries(journal, lessons_skip(lessons)) if journal else {}
    if num not in entries:
        print(f"ERROR: 找不到记录 #{num}")
        return 1
    path = entries[num][0]
    m = meta_of(path)
    text = read(path)
    print(f"#{num:04d}  {rel(root, path)}")
    print(f"title : {m['title']}")
    print(f"date  : {m['date'] or '-'}   迭代: {m['iter'] or '-'}   {m['lines']} lines / {m['bytes']} B"
          f"   verify: {'yes' if m['has_verify'] else 'no'}")
    for label, pat in (("触发", TRIGGER_RE), ("范围", SCOPE_RE), ("结论", CONCLUSION_RE)):
        mm = pat.search(text)
        if mm:
            print(f"{label:<6}: {mm.group(1).strip()[:100]}")
    print("sections:")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        h = heading_level(line)
        if h and h[0] >= 2:
            j = i + 1
            while j < len(lines) and not heading_level(lines[j]):
                j += 1
            print(f"  {h[1]}  ({j - i - 1} lines)")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    # `--in journal`（旧写法，等价于新写法 `--in work_log`）= 容器里的**过程记录**，
    # 不含容器内的 `lessons/`；`--in all` = 整个容器（含 lessons/）。
    targets: list[str] = []
    exclude: set[str] = set()
    if args.in_ == "lessons":
        targets = [lessons] if lessons else []
    elif args.in_ == "all":
        targets = scan_bases(journal, lessons)
    else:
        targets = [journal] if journal else []
        exclude = set(lessons_skip(lessons))
    try:
        pat = re.compile(args.pattern, re.I) if args.regex else None
    except re.error as exc:
        print(f"ERROR: --regex 不是合法的正则：{exc}")
        return 2
    needle = args.pattern.lower()
    hits = 0
    for base in targets:
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in (".git", "node_modules") and d not in exclude]
            for f in sorted(fn):
                if not f.endswith(".md"):
                    continue
                path = os.path.join(dp, f)
                for i, line in enumerate(read(path).splitlines(), 1):
                    ok = bool(pat.search(line)) if pat else needle in line.lower()
                    if not ok:
                        continue
                    hits += 1
                    if hits > args.limit:
                        continue
                    if args.files:
                        print(rel(root, path))
                        break
                    print(f"{rel(root, path)}:{i}: {line.strip()[:160]}")
    tail = f"  (showing first {args.limit})" if hits > args.limit else ""
    print(f"\n{hits} hit(s){tail}")
    return 0 if hits else 1


# --------------------------------------------------------------------------- #
# new / index sync
# --------------------------------------------------------------------------- #
def _table_rows_span(lines: list[str], start: int, end: int):
    rows = [i for i in range(start, end) if lines[i].lstrip().startswith("|")]
    return (rows[0], rows[-1]) if rows else None


def index_sync(journal: str, lessons: str | None = None, only: list[int] | None = None,
               stage: str | None = None, aspect: str | None = None,
               dry_run: bool = False) -> tuple[list[int], str]:
    """把漏进索引的活跃记录补成表行。

    `lessons` 只用于把经验目录从记录扫描里排除（`--lessons` 改名后尤其需要）。
    """
    index = os.path.join(journal, "README.md")
    text = read_raw(index)
    lines = text.splitlines(keepends=True)
    nl = nl_of(text)
    entries = find_entries(journal, lessons_skip(lessons))
    root_nums = [n for n in sorted(entries) if is_active_entry(journal, entries[n][0])]
    missing = [n for n in root_nums if entry_link(journal, entries[n][0]) not in text]
    if only is not None:
        missing = [n for n in missing if n in only]
    if not missing:
        return [], "索引已覆盖全部根目录记录"

    idx_span = find_labeled_section(lines, 2, L_INDEX)
    if not idx_span:
        # 没有 `## 文件索引` 就别猜：回退到整篇会把记录行写进任何一张表里
        # （例如 `### 结算`），静默污染无关小节。
        return [], "索引里没有 `## 文件索引` 小节，先把台账结构补齐"
    search_from = idx_span[1]
    search_to = idx_span[2]
    subs = [(i, heading_level(lines[i])[1]) for i in range(search_from, search_to) if heading_level(lines[i]) and heading_level(lines[i])[0] == 3]
    if stage:
        chosen = next((s for s in subs if stage in s[1]), None)
    else:
        chosen = subs[-1] if subs else None
    if chosen is None:
        return [], "索引里找不到可写入的表格小节（先在 `## 文件索引` 下加 `### <阶段>` 与表头）"
    _, sub_title = chosen
    sub_end = next((i for i in range(chosen[0] + 1, len(lines))
                    if heading_level(lines[i]) and heading_level(lines[i])[0] <= 2), len(lines))
    span = _table_rows_span(lines, chosen[0] + 1, sub_end)
    new_lines = []
    for n in missing:
        m = meta_of(entries[n][0])
        fname = entry_link(journal, entries[n][0])
        label = aspect or m["conclusion"] or m["title"]
        label = re.sub(r"\s+", " ", label).strip()[:60] or m["title"][:60]
        new_lines.append(f"| [{fname}]({fname}) | {label} |{nl}")
    if dry_run:
        return missing, f"[dry-run] 将写入 `{sub_title}` {len(missing)} 行：" + "; ".join(f"#{n:04d}" for n in missing)
    if span:
        lines[span[1] + 1: span[1] + 1] = new_lines
    else:
        lines[chosen[0] + 1: chosen[0] + 1] = [f"| 文件 | 方面 |{nl}", f"|---|---|{nl}"] + new_lines + [nl]
    write_raw(index, "".join(lines))
    return missing, f"已写入 `{sub_title}`：{', '.join(f'#{n:04d}' for n in missing)}"


def cmd_new(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器（work_log/；旧名 journal/、work-log/ 也认），先按 templates.md 初始化")
        return 1
    entries = find_entries(journal, lessons_skip(lessons))
    num = (max(entries) + 1) if entries else 1
    date = args.date or today()
    slug = args.slug or slugify(args.title)
    fname = f"{num:04d}-{slug}.md" if slug else f"{num:04d}.md"
    path = os.path.join(journal, fname)
    body = ENTRY_TEMPLATE.format(num=num, title=args.title, date=date,
                                 iter=args.iter if args.iter is not None else "-",
                                 cmd=args.cmd or "<命令 / 数据 / 引用 / 样本>")
    if os.path.exists(path):
        print(f"ERROR: 已存在 {rel(root, path)}")
        return 1
    if args.dry_run:
        print(f"[dry-run] 将创建 {rel(root, path)}\n")
        print(body)
        return 0
    write_raw(path, body)
    print(f"created {rel(root, path)}")
    if args.insert:
        _, msg = index_sync(journal, lessons, only=[num], stage=args.stage, dry_run=False)
        print(f"index: {msg}")
    else:
        print("索引建议行：")
        print(f"| [{fname}]({fname}) | {args.title} |")
    if not slug:
        print("提示：纯中文标题没有可用的 ASCII slug，已生成 `<篇号>.md`；"
              "想要带描述的文件名就加 `--slug <ascii-slug>`。")
    return 0


def cmd_index_compact(args: argparse.Namespace) -> int:
    """把「整节都已归档」的索引小节折叠成一行区间——治索引的线性膨胀。

    只动索引，不动任何记录；混合（含活跃记录）或有死链的小节一律跳过。
    """
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器")
        return 1
    index = os.path.join(journal, "README.md")
    text = read_raw(index)
    lines = text.splitlines(keepends=True)
    nl = nl_of(text)
    span = find_labeled_section(lines, 2, L_INDEX)
    if not span:
        print("ERROR: 索引里没有 `## 文件索引` 小节")
        return 1

    stages: list[tuple[int, int, str]] = []
    i = span[1]
    while i < span[2]:
        h = heading_level(lines[i])
        if h and h[0] == 3:
            j = i + 1
            while j < span[2]:
                hj = heading_level(lines[j])
                if hj and hj[0] <= 3:
                    break
                j += 1
            stages.append((i, j, h[1]))
            i = j
        else:
            i += 1

    done: list[tuple[str, str, str]] = []
    skipped: list[tuple[str, str]] = []
    for head_i, end_i, title in reversed(stages):
        if args.stage and args.stage not in title:
            continue
        rows = [k for k in range(head_i + 1, end_i)
                if lines[k].lstrip().startswith("|") and "](" in lines[k]]
        if not rows:
            continue
        targets = [LINK_RE.search(lines[k]).group(1).split("#")[0] for k in rows]
        resolved = [os.path.normpath(os.path.join(journal, t)) for t in targets]
        if any(os.path.isdir(p) for p in resolved):
            # 已经折叠过的行：目标是个目录。再折一次会把 `5–6（2 篇）` 变成 `1 篇`，
            # 所以这里必须跳过，保证 `index compact` 幂等。
            continue
        if not all(is_archived_entry(journal, p, lessons_skip(lessons)) for p in resolved):
            # 「已归档」= 编号记录 + 在容器的阶段目录里；经验分册、README、
            # STATE-HISTORY、年份卷这些同样在容器内但不是归档记录，落进这一支被跳过。
            skipped.append((title, "含活跃记录或非记录文件"))
            continue
        if not all(os.path.exists(p) for p in resolved):
            skipped.append((title, "有死链，先修链接"))
            continue
        dirs = {os.path.dirname(t).replace(os.sep, "/") for t in targets}
        if len(dirs) != 1:
            skipped.append((title, "跨多个归档目录"))
            continue
        nums = [int(m.group(1)) for t in targets
                if (m := ENTRY_RE.match(os.path.basename(t)))]
        common = dirs.pop()
        label = (f"{min(nums):04d}–{max(nums):04d}（{len(rows)} 篇，已归档）" if nums
                 else f"{len(rows)} 篇，已归档")
        new_row = f"| [{common}/]({common}/) | {label} |{nl}"
        old_block = "".join(lines[rows[0]:rows[-1] + 1])
        done.append((title, old_block, new_row))
        if not args.dry_run:
            lines[rows[0]:rows[-1] + 1] = [new_row]

    before = len(text)
    after = before - sum(len(o) - len(n) for _, o, n in done)
    print(f"{'[dry-run] ' if args.dry_run else ''}折叠 {len(done)} 个小节、"
          f"{sum(o.count(chr(10)) for _, o, _ in done)} 行 → {len(done)} 行；"
          f"索引 {before} → {after} 字符（省 {before - after}）")
    for title, old_block, _ in done:
        print(f"  · {title}：{old_block.count(chr(10))} 行 → 1 行")
    for title, why in skipped:
        print(f"  ! 跳过 {title}：{why}")
    if done and not args.dry_run:
        write_raw(index, "".join(lines))
        print("已写入；建议接着跑 `check` 确认 0 死链。")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器")
        return 1
    missing, msg = index_sync(journal, lessons, stage=args.stage, aspect=args.aspect, dry_run=args.dry_run)
    print(msg)
    for n in missing:
        print(f"  #{n:04d}")
    # 索引小节缺失 / 找不到可写入的表格时 index_sync 会空手而归，别报成功。
    return 0 if missing or msg.startswith("索引已覆盖") else 1


# --------------------------------------------------------------------------- #
# status / todo / append
# --------------------------------------------------------------------------- #
def _index_lines(journal: str) -> tuple[str, list[str]]:
    index = os.path.join(journal, "README.md")
    text = read_raw(index)
    return text, text.splitlines(keepends=True)


def cmd_status(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器")
        return 1
    text, lines = _index_lines(journal)
    span = find_labeled_section(lines, 2, L_STATUS)
    if not span:
        print(f"ERROR: 索引里没有 `## {K_STATUS}` 块")
        return 1

    if args.roll:
        head_line = lines[span[0]].rstrip("\r\n")
        hist = status_history_path(journal)
        block = "".join(lines[span[0]:span[2]]).strip()
        if args.dry_run:
            print(f"[dry-run] 将当前状态块移入 {rel(root, hist)}，并写入新骨架")
            print(block)
            return 0
        os.makedirs(os.path.dirname(hist), exist_ok=True)
        htext = read_raw(hist) if os.path.exists(hist) else ""
        if not htext:
            htext = f"# 状态历史{nl_of(text)}{nl_of(text)}"
        hl = htext.splitlines(keepends=True)
        h1 = next((i for i, l in enumerate(hl) if heading_level(l) and heading_level(l)[0] == 1), -1)
        insert_at = h1 + 1
        while insert_at < len(hl) and not hl[insert_at].strip():
            insert_at += 1
        hl[insert_at:insert_at] = [nl_of(htext), block + nl_of(htext), nl_of(htext)]
        write_raw(hist, "".join(hl))
        head = re.sub(DATE_PAREN_RE, "", head_line).strip()
        new_block = STATUS_SKELETON.format(head=head.lstrip("# ").strip(), date=args.date or today(),
                                           fields="\n".join(f"- {k}：" for k in STATUS_KEYS))
        # 新骨架是 LF 字面量，必须按台账原本的换行风格改写，否则 CRLF 台账被掺进 LF。
        new_block = new_block.replace("\n", nl_of(text))
        lines[span[0]:span[2]] = new_block.splitlines(keepends=True) + [nl_of(text)]
        write_raw(os.path.join(journal, "README.md"), "".join(lines))
        print(f"已归档旧状态块 → {rel(root, hist)}，并写入新骨架")
        return 0

    if args.set or args.date:
        head_line = lines[span[0]]
        if args.date:
            if DATE_PAREN_RE.search(head_line):
                head_line = DATE_PAREN_RE.sub(f"（{args.date}）", head_line, count=1)
            else:
                head_line = head_line.rstrip("\r\n") + f"（{args.date}）" + (nl_of(text))
            lines[span[0]] = head_line
        changed = []
        for pair in args.set:
            if "=" not in pair:
                print(f"WARN: 忽略无法解析的 --set '{pair}'（应为 key=value）")
                continue
            key, val = pair.split("=", 1)
            key = key.strip()
            found = False
            for i in range(span[1], span[2]):
                m = re.match(r"^(\s*-\s*)([^：:\r\n]+)[：:][ \t]*(.*?)(\r?\n?)$", lines[i])
                if not m:
                    continue
                existing = m.group(2).strip()
                if existing != key and resolve_status_key(key) != existing:
                    continue
                # 命中已有字段时**沿用台账上的写法**，避免把 `核对 / 验证` 改写成 `核对`。
                lines[i] = f"{m.group(1)}{existing}：{val}{m.group(4)}"
                found = True
                changed.append(existing)
                break
            if not found:
                end = last_content_line(lines, span[1], span[2]) + 1
                # 行尾可能没有换行符（手写台账常见）；补一个，否则新字段会粘到上一行末尾。
                if end > 0 and not lines[end - 1].endswith(("\n", "\r")):
                    lines[end - 1] = lines[end - 1] + nl_of(text)
                    end += 1
                lines.insert(end, f"- {key}：{val}{nl_of(text)}")
                span = (span[0], span[1], span[2] + 1)
                changed.append(key + "(新增)")
        if args.dry_run:
            print("[dry-run] 将更新：" + ", ".join(changed))
            return 0
        write_raw(os.path.join(journal, "README.md"), "".join(lines))
        print("status 已更新：" + ", ".join(changed))
        return 0

    print("".join(lines[span[0]:span[2]]).strip())
    return 0


def cmd_mode(args: argparse.Namespace) -> int:
    """查看 / 切换记录精细度（台账 `## 当前状态` 的 `精细度` 字段）。

    只读时缺字段不算错：报默认档位，并说明它是默认。写入时复用 `status --set`
    那条已经测过的外科式路径，不另造写文件逻辑。
    """
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器（work_log/；旧名 journal/、work-log/ 也认），"
              "先按 templates.md 初始化")
        return 1
    text, lines = _index_lines(journal)
    if not find_labeled_section(lines, 2, L_STATUS):
        print(f"ERROR: 索引里没有 `## {K_STATUS}` 块")
        return 1
    cur, why, is_default = _mode_and_why(journal)

    if args.set is None and not args.why:
        print(f"{cur}    {MODE_MEANING[cur]}")
        if is_default:
            cell = mode_cell(text)
            tail = (f"认不出 `{cell}`（只认 full/session/digest/milestone），按默认档处理"
                    if cell else "台账里没有 `精细度` 字段")
            print(f"（{tail}：当前取默认档 `{MODE_DEFAULT}`）")
        if why:
            print(f"原因：{why}")
        print(f"切换：`journal.py mode --set {MODE_DEFAULT}|full|digest|milestone`")
        return 0

    # `--why` 不带 `--set` 时只补原因，档位不动（沿用现有原因；没有就新建）。
    mode = cur
    if args.set is not None:
        # 取值在这里手工校验，不用 argparse 的 choices：choices 会把 16 个别名
        # 原样倒进报错里，既长又不合本文件的语气。
        mode = MODE_ALIASES.get(args.set.strip().lower())
        if mode is None:
            print(f"ERROR: 认不出的精细度 `{args.set}`；只认 full / session / digest / milestone"
                  f"（也认中文：{'、'.join(MODES[m][1] for m in MODES)}）")
            print("       例：`mode --set digest --why \"阶段收口\"`")
            return 2
    value = mode_value(mode, args.why or why)
    if args.dry_run:
        print(f"[dry-run] 精细度 → {value}")
        return 0
    ns = argparse.Namespace(root=args.root, journal=args.journal, lessons=args.lessons,
                            set=[f"精细度={value}"], date=None, roll=False, dry_run=False)
    rc = cmd_status(ns)
    if rc == 0:
        print(f"精细度：{value}    {MODE_MEANING[mode]}")
    return rc


def cmd_todo(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器")
        return 1
    text, lines = _index_lines(journal)
    index = os.path.join(journal, "README.md")
    span = find_labeled_section(lines, 2, L_TODO)
    if not span:
        print(f"ERROR: 索引里没有 `## {K_TODO}` 小节")
        return 1
    nl = nl_of(text)

    if args.add:
        end = last_content_line(lines, span[1], span[2]) + 1
        if args.dry_run:
            print(f"[dry-run] 将追加：- [ ] {args.add}")
            return 0
        lines.insert(end, f"- [ ] {args.add}{nl}")
        write_raw(index, "".join(lines))
        print(f"已追加待办：{args.add}")
        return 0

    if args.done:
        for i in range(span[1], span[2]):
            if re.match(r"^\s*-\s*\[ \]", lines[i]) and args.done in lines[i]:
                lines[i] = re.sub(r"\[ \]", "[x]", lines[i], count=1)
                if args.dry_run:
                    print(f"[dry-run] 将勾选：{lines[i].strip()}")
                    return 0
                write_raw(index, "".join(lines))
                print(f"已勾选：{lines[i].strip()}")
                return 0
        print(f"ERROR: 找不到匹配的未完成待办：{args.done}")
        return 1

    if args.drop_done:
        kept = [l for i, l in enumerate(lines) if not (span[1] <= i < span[2] and re.match(r"^\s*-\s*\[[xX]\]", l))]
        removed = len(lines) - len(kept)
        if args.dry_run:
            print(f"[dry-run] 将删除 {removed} 条已完成待办")
            return 0
        write_raw(index, "".join(kept))
        print(f"已删除 {removed} 条已完成待办")
        return 0

    open_items, done_items = todo_items(journal)
    print(f"未完成（{len(open_items)}）")
    for it in open_items:
        print(it)
    print(f"\n已完成（{len(done_items)}）")
    for it in done_items:
        print(it)
    return 0


def cmd_append(args: argparse.Namespace) -> int:
    root_arg, num = _root_and_num(args.paths)
    root = os.path.abspath(root_arg)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    entries = find_entries(journal, lessons_skip(lessons)) if journal else {}
    if num not in entries:
        print(f"ERROR: 找不到记录 #{num}")
        return 1
    path = entries[num][0]
    text = read_raw(path)
    nl = nl_of(text)
    lines = text.splitlines(keepends=True)
    span = find_section(lines, 2, args.section)
    body = args.text.strip("\n").splitlines()
    if args.bullet:
        body = ["- " + b if not b.lstrip().startswith("-") else b for b in body]
    if span:
        add = [b + nl for b in body]
        insert_at_end_of_section(lines, span[1], span[2], [nl] + add)
        action = f"追加到已有小节 `{args.section}`"
    else:
        if lines and lines[-1].strip():
            lines.append(nl)
        lines.append(f"## {args.section}{nl}")
        lines.append(nl)
        lines.extend(b + nl for b in body)
        action = f"新建小节 `{args.section}`"
    if args.dry_run:
        print(f"[dry-run] {rel(root, path)}：{action}")
        print("".join(body))
        return 0
    write_raw(path, "".join(lines))
    print(f"{rel(root, path)}：{action}")
    return 0


# --------------------------------------------------------------------------- #
# archive / split / prune：记录量增长后的整理
# --------------------------------------------------------------------------- #
def _dead_links(root: str, bases: list[str]) -> list[str]:
    """扫一遍 md 链接，返回死链描述（用于搬文件后的自检）。"""
    rep = Report(False)
    for base in bases:
        if not base or not os.path.isdir(base):
            continue
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in (".git", "node_modules")]
            for f in fn:
                if f.endswith(".md"):
                    _check_links(root, os.path.join(dp, f), rep)
    return [txt for lv, txt in rep.rows if lv == "ERROR"]


def _update_archive_index(container: str, stage: str, nums: list[int], dates: list[str]) -> None:
    """在归档索引（新布局 `<容器>/ARCHIVE.md`，旧布局 `archive/README.md`）里补一行。"""
    path = archive_index_path(container)
    text = read_raw(path) if os.path.exists(path) else ""
    nl = nl_of(text) if text else "\n"
    lines = text.splitlines(keepends=True)
    if not text:
        lines = [f"# 归档区{nl}", nl,
                 f"| 目录 | 篇号 | 时间 | 内容 | 归档判据 |{nl}",
                 f"|---|---|---|---|---|{nl}"]
    ds = sorted(d for d in dates if d)
    span = f"{ds[0]} ~ {ds[-1]}" if ds else "-"
    entry = (f"| `{stage}/` | {min(nums):04d}–{max(nums):04d} | {span} | "
             f"{len(nums)} 篇 | 阶段收口 |{nl}")
    rows = [i for i, l in enumerate(lines) if l.lstrip().startswith("|")]
    if rows:
        lines.insert(rows[-1] + 1, entry)
    else:
        if lines and lines[-1].strip():
            lines.append(nl)
        lines.append(entry)
    write_raw(path, "".join(lines))


def cmd_archive(args: argparse.Namespace) -> int:
    """把一个篇号区间归档到 `<容器>/<stage>/`，并重写全仓链接。

    搬完自动做一次死链自检；有死链就报错退出（内容都在，可 git 回退）。
    """
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器")
        return 1
    stage = args.stage.strip()
    if not stage or re.search(r"[/\\:]", stage):
        print("ERROR: --stage 只能是不含路径分隔符的名字，如 02-research")
        return 1
    if YEAR_DIR_RE.match(stage) or stage in NON_RECORD_DIRS:
        # 4 位数字的目录会被当成按年分卷（记录仍是「活跃」），lessons/logs 是容器内
        # 的非记录目录：两种名字都会让归档记录被错误分类，直接挡掉。
        print(f"ERROR: --stage 不能用「{stage}」：4 位数字是年份卷、"
              f"{'、'.join(NON_RECORD_DIRS)} 是容器内的非记录目录")
        return 1
    entries = find_entries(journal, lessons_skip(lessons))
    picked = [(n, p[0]) for n, p in sorted(entries.items())
              if args.from_num <= n <= args.to_num and is_active_entry(journal, p[0])]
    if not picked:
        print(f"ERROR: {args.from_num}–{args.to_num} 区间内没有活跃记录")
        return 1
    target_dir = os.path.join(journal, stage)
    moves = {os.path.abspath(p): os.path.join(target_dir, os.path.basename(p))
             for _, p in picked}
    for dst in moves.values():
        if os.path.exists(dst):
            print(f"ERROR: 目标已存在，先处理冲突：{rel(root, dst)}")
            return 1
    bases = scan_bases(journal, lessons)
    nums = [n for n, _ in picked]
    dates = [meta_of(p)["date"] for _, p in picked]

    if args.dry_run:
        changed = rewrite_links(bases, moves, dry_run=True)
        print(f"[dry-run] 将移动 {len(picked)} 篇 → {rel(root, target_dir)}：")
        for n, p in picked:
            print(f"  #{n:04d}  {os.path.basename(p)}")
        print(f"将重写 {len(changed)} 处链接：")
        for f, a, b in changed[:20]:
            print(f"  {f}: {a} → {b}")
        if len(changed) > 20:
            print(f"  … 另 {len(changed) - 20} 处")
        return 0

    os.makedirs(target_dir, exist_ok=True)
    for _, p in picked:
        os.rename(p, os.path.join(target_dir, os.path.basename(p)))
    changed = rewrite_links(bases, moves, dry_run=False)
    if not args.no_index:
        _update_archive_index(journal, stage, nums, dates)

    dead = _dead_links(root, bases)
    print(f"移动 {len(picked)} 篇 → {rel(root, target_dir)}；"
          f"重写 {len(changed)} 处链接；死链 {len(dead)}")
    for txt in dead[:10]:
        print("  " + txt)
    if dead:
        print("⚠️ 仍有死链：内容都在，检查上面的链接（可用 git 回退）")
        return 1
    print(f"完成。建议接着跑 `index compact --stage {stage}` 折叠索引行，再跑 `check`。")
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    """按年分卷：把活跃记录移进 `<容器>/<YYYY>/`（取自入口行的 `日期：`），并重写链接。

    适合超长期项目（上千篇）；纯编号引用 `wl/NNNN` 不受影响。
    """
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器")
        return 1
    if not args.by_year:
        print("ERROR: 目前只支持 `--by-year`")
        return 1
    entries = find_entries(journal, lessons_skip(lessons))
    plan: list[tuple[int, str, str, str]] = []
    skipped: list[tuple[int, str]] = []
    moves: dict[str, str] = {}
    for n, paths in sorted(entries.items()):
        p = paths[0]
        if not is_active_entry(journal, p):
            continue
        d = meta_of(p)["date"]
        if not ISO_DATE_RE.fullmatch(d or ""):
            skipped.append((n, d or "(无日期)"))
            continue
        year = d[:4]
        target = os.path.join(journal, year, os.path.basename(p))
        if os.path.abspath(os.path.dirname(p)) == os.path.abspath(os.path.join(journal, year)):
            continue
        if os.path.exists(target):
            print(f"ERROR: 目标已存在，先处理冲突：{rel(root, target)}")
            return 1
        moves[os.path.abspath(p)] = target
        plan.append((n, p, target, year))

    if not plan:
        print("没有需要移动的记录" + (f"（{len(skipped)} 篇无日期已跳过）" if skipped else ""))
        for n, d in skipped:
            print(f"  ! 跳过 #{n:04d}（{d}）")
        return 0

    bases = scan_bases(journal, lessons)
    by_year: dict[str, int] = {}
    for _, _, _, y in plan:
        by_year[y] = by_year.get(y, 0) + 1
    summary = "、".join(f"{y}/（{c} 篇）" for y, c in sorted(by_year.items()))

    if args.dry_run:
        changed = rewrite_links(bases, moves, dry_run=True)
        print(f"[dry-run] 将把 {len(plan)} 篇分卷到 {summary}")
        for n, p, _, y in plan[:20]:
            print(f"  #{n:04d}  {os.path.basename(p)} → {y}/")
        if len(plan) > 20:
            print(f"  … 另 {len(plan) - 20} 篇")
        print(f"将重写 {len(changed)} 处链接")
        return 0

    for _, p, target, _ in plan:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.rename(p, target)
    changed = rewrite_links(bases, moves, dry_run=False)
    dead = _dead_links(root, bases)
    print(f"分卷 {len(plan)} 篇 → {summary}；重写 {len(changed)} 处链接；死链 {len(dead)}")
    for n, d in skipped:
        print(f"  ! 跳过 #{n:04d}（{d}）")
    for txt in dead[:10]:
        print("  " + txt)
    if dead:
        print("⚠️ 仍有死链：内容都在，可用 git 回退")
        return 1
    print("完成。建议跑 `check` 确认。")
    return 0


def _remove_index_rows(journal: str, basenames: set[str]) -> int:
    """删掉索引里指向这些文件的行（冷存移出后用）。返回删除行数。"""
    index = os.path.join(journal, "README.md")
    text = read_raw(index)
    if not text:
        return 0
    kept, removed = [], 0
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("|") and "](" in line:
            m = LINK_RE.search(line)
            if m and os.path.basename(m.group(1).split("#")[0]) in basenames:
                removed += 1
                continue
        kept.append(line)
    if removed:
        write_raw(index, "".join(kept))
    return removed


def _append_row_after_table(path: str, default_text: str, row: str) -> None:
    """给一个 markdown 表格追加一行（文件不存在则用 default_text 建表）。"""
    text = read_raw(path) if os.path.exists(path) else ""
    nl = nl_of(text) if text else "\n"
    lines = text.splitlines(keepends=True)
    if not text:
        lines = default_text.replace("\n", nl).splitlines(keepends=True)
    rows = [i for i, l in enumerate(lines) if l.lstrip().startswith("|")]
    if rows:
        lines.insert(rows[-1] + 1, row + nl)
    else:
        if lines and lines[-1].strip():
            lines.append(nl)
        lines.append(row + nl)
    write_raw(path, "".join(lines))


def cmd_prune(args: argparse.Namespace) -> int:
    """冷存候选：默认**只报告**；`--zip` 打包；`--apply` 才把原件移出并写清单。

    判据：已归档 + 未被 lessons 引用 + 日期早于 `--older-than` 天。
    绝不直接删除：移出到冷存目录，并在 `<容器>/COLD-STORE.md` 留行。
    """
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器")
        return 1
    if args.apply and not args.zip:
        print("ERROR: --apply 必须配合 --zip（先打包再移出，保证有备份）")
        return 1
    cited: set[int] = set()
    if lessons:
        for f in sorted(os.listdir(lessons)):
            if f.endswith(".md"):
                cited |= {int(x) for x in CITE_RE.findall(read(os.path.join(lessons, f)))}
    cutoff = _dt.date.today() - _dt.timedelta(days=args.older_than)
    cands: list[tuple[int, str, str, int]] = []
    for n, paths in sorted(find_entries(journal, lessons_skip(lessons)).items()):
        p = paths[0]
        if is_active_entry(journal, p) or n in cited:
            continue
        d = meta_of(p)["date"]
        if not ISO_DATE_RE.fullmatch(d or "") or _dt.date.fromisoformat(d) > cutoff:
            continue
        if args.stage and args.stage not in rel(journal, p):
            continue
        cands.append((n, p, d, os.path.getsize(p)))
    total = sum(c[3] for c in cands)
    print(f"冷存候选（已归档 + 未被 lessons 引用 + 早于 {cutoff}）：{len(cands)} 篇 / {total} B")
    for n, p, d, sz in cands:
        print(f"  #{n:04d}  {d}  {sz:>7} B  {rel(root, p)}")
    if not cands:
        print("没有候选，无需处理。")
        return 0
    if not args.zip:
        print("\n（只报告，未改动任何文件。加 `--zip OUT.zip` 打包；再加 `--apply` 才移出原件。）")
        return 0

    zp = os.path.abspath(args.zip)
    out_dir = os.path.dirname(zp)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for _, p, _, _ in cands:
            z.write(p, rel(root, p))
    print(f"已打包 → {rel(root, zp) if _under(zp, root) else zp}（{os.path.getsize(zp)} B）")
    if not args.apply:
        print("（原件未动。加 `--apply` 才会移出并写清单。）")
        return 0

    cold = os.path.abspath(args.cold_store or os.path.join(root, "_coldstore", today()))
    for _, p, _, _ in cands:
        dst = os.path.join(cold, rel(root, p).replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.rename(p, dst)
    removed = _remove_index_rows(journal, {os.path.basename(p) for _, p, _, _ in cands})
    _append_row_after_table(
        cold_store_path(journal),
        "# 冷存清单\n\n| 执行日期 | 篇号 | 篇数 | 冷存目录 | 打包文件 | 判据 |\n|---|---|---|---|---|---|\n",
        f"| {today()} | {min(n for n, _, _, _ in cands):04d}–{max(n for n, _, _, _ in cands):04d} "
        f"| {len(cands)} | `{cold}` | `{zp}` | 阶段收口 + 未被 lessons 引用 + 超期 |")
    dead = _dead_links(root, scan_bases(journal, lessons))
    print(f"已移出 {len(cands)} 篇 → {cold}；索引删行 {removed}；死链 {len(dead)}")
    for txt in dead[:10]:
        print("  " + txt)
    if dead:
        print("⚠️ 仍有死链：检查索引里是否还指向冷存文件")
        return 1
    print(f"完成。清单见 {rel(root, cold_store_path(journal))}。")
    return 0


# --------------------------------------------------------------------------- #
# lesson add
# --------------------------------------------------------------------------- #
def cmd_lesson(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not lessons:
        print("ERROR: 找不到 lessons/ 目录")
        return 1
    volumes = [f for f in sorted(os.listdir(lessons)) if f.endswith(".md") and f != "README.md"]
    if args.volume:
        match = [v for v in volumes if v == args.volume] or [v for v in volumes if args.volume in v]
        if not match:
            print(f"ERROR: 找不到分册 `{args.volume}`，可选：{', '.join(volumes)}")
            return 1
        if len(match) > 1:
            print(f"ERROR: 分册名不唯一：{', '.join(match)}")
            return 1
        volume = match[0]
    elif len(volumes) == 1:
        volume = volumes[0]
    else:
        print(f"ERROR: 用 --volume 指定分册，可选：{', '.join(volumes)}")
        return 1

    entries = find_entries(journal, lessons_skip(lessons)) if journal else {}
    if args.source is None:
        print("ERROR: 必须用 --source <篇号> 标注来源")
        return 1
    if args.source not in entries:
        print(f"ERROR: 来源 `wl/{args.source}` 在记录目录里不存在")
        return 1

    path = os.path.join(lessons, volume)
    text = read_raw(path)
    nl = nl_of(text)
    lines = text.splitlines(keepends=True)
    line = args.text.strip()
    if not line.startswith("-"):
        line = "- " + line
    # 只要正文里没引用**本篇**来源，就把 `--source` 的引用补上。
    # 旧逻辑是"正文里出现任何 wl/ 就不补"，于是 `--source 1` 配上一段提到
    # `wl/9999` 的文字，会把 0001 这个来源静默吞掉，check 转头去校验 9999。
    cite = f"`wl/{args.source:04d}`"
    if cite not in line:
        line = line.rstrip("。.") + f"（{cite}）"
    payload = line + nl
    if args.topic:
        span = find_section(lines, 2, args.topic)
        if span:
            insert_at_end_of_section(lines, span[1], span[2], [payload])
            action = f"追加到 `{args.topic}`"
        else:
            if lines and lines[-1].strip():
                lines.append(nl)
            lines += [f"## {args.topic}{nl}", nl, payload]
            action = f"新建小节 `{args.topic}`"
    else:
        if lines and lines[-1].strip():
            lines.append(nl)
        lines.append(payload)
        action = "追加到文件末尾"
    if args.dry_run:
        print(f"[dry-run] {rel(root, path)}：{action}\n{payload.strip()}")
        return 0
    write_raw(path, "".join(lines))
    print(f"{rel(root, path)}：{action}")
    print(payload.strip())
    return 0


# --------------------------------------------------------------------------- #
# stats / topics / export / digest / retro
# --------------------------------------------------------------------------- #
def cmd_stats(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    entries = find_entries(journal, lessons_skip(lessons)) if journal else {}
    nums = sorted(entries)
    if not nums:
        print("没有记录")
        return 0
    metas = all_metas(entries)
    root_nums = [n for n in nums if is_active_entry(journal, entries[n][0])]
    dates = [max_date_in(read(entries[n][0])) for n in nums]
    dates = [d for d in dates if d]
    total_bytes = sum(m["bytes"] for m in metas.values())
    total_lines = sum(m["lines"] for m in metas.values())
    biggest = max(nums, key=lambda n: metas[n]["bytes"])
    print(f"entries     : {len(nums)}  (#{nums[0]}–#{nums[-1]}; active {len(root_nums)} / archive {len(nums) - len(root_nums)})")
    if dates:
        span_days = (max(dates) - min(dates)).days + 1
        print(f"date span   : {min(dates)} .. {max(dates)}  ({span_days} days, {len(dates)} dated)")
        buckets: dict[str, int] = {}
        for d in dates:
            wk = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
            buckets[wk] = buckets.get(wk, 0) + 1
        print("per week    : " + "  ".join(f"{k}:{v}" for k, v in sorted(buckets.items())))
    print(f"compliance  : 日期 {sum(1 for m in metas.values() if m['has_date'])}/{len(nums)}"
          f"   验证 {sum(1 for m in metas.values() if m['has_verify'])}/{len(nums)}")
    print(f"size        : {total_lines} lines / {total_bytes / 1024:.0f} KB"
          f"   avg {total_lines // len(nums)} lines   largest #{biggest} ({metas[biggest]['bytes'] / 1024:.0f} KB)")
    iters = [m["iter"] for m in metas.values() if m["iter"] and m["iter"] != "-"]
    print(f"迭代字段    : {len(iters)}/{len(nums)} 有值")
    if lessons:
        cites: dict[int, int] = {}
        for f in sorted(os.listdir(lessons)):
            if f.endswith(".md") and f != "README.md":
                for c in CITE_RE.findall(read(os.path.join(lessons, f))):
                    cites[int(c)] = cites.get(int(c), 0) + 1
        print(f"lessons     : {len([f for f in os.listdir(lessons) if f.endswith('.md') and f != 'README.md'])} volumes,"
              f" {sum(cites.values())} citations → {len(cites)} sources")
        top = sorted(cites.items(), key=lambda kv: -kv[1])[:8]
        print("top cited   : " + "  ".join(f"#{n}({c})" for n, c in top))
    return 0


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{3,}")


def cmd_topics(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    entries = find_entries(journal, lessons_skip(lessons)) if journal else {}
    nums = sorted(entries)
    if args.keywords:
        kws = [k.strip() for k in args.keywords.split(",") if k.strip()]
        for kw in kws:
            hit = [n for n in nums if kw.lower() in read(entries[n][0]).lower()]
            print(f"{kw}: " + (", ".join(f"#{n}" for n in hit) if hit else "(no hit)"))
        return 0
    df: dict[str, set[int]] = {}
    for n in nums:
        for tok in set(TOKEN_RE.findall(read(entries[n][0]))):
            t = tok.lower()
            if t in STOPWORDS or len(t) < 4:
                continue
            df.setdefault(t, set()).add(n)
    cand = [(t, ns) for t, ns in df.items() if 2 <= len(ns) <= args.max_df]
    cand.sort(key=lambda kv: (-len(kv[1]), kv[0]))
    print(f"同主题簇建议（出现 2–{args.max_df} 篇的标识符；用 `--keywords` 可查中文词）\n")
    for t, ns in cand[: args.limit]:
        shown = sorted(ns)
        print(f"{t:28s} {len(shown):2d} 篇  " + ", ".join(f"#{n}" for n in shown[:10])
              + (" …" if len(shown) > 10 else ""))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    entries = find_entries(journal, lessons_skip(lessons)) if journal else {}
    rows = []
    for n in sorted(entries):
        m = meta_of(entries[n][0])
        rows.append({"num": n, "path": rel(root, entries[n][0]), **{k: m[k] for k in
                     ("title", "date", "iter", "lines", "bytes", "has_date", "has_verify")}})
    if args.csv and args.json:
        print("ERROR: `--csv` 与 `--json` 只能选一个（`--json` 本来就是默认）")
        return 2
    if args.csv:
        import csv
        import io
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["num"])
        w.writeheader()
        w.writerows(rows)
        out = buf.getvalue()
    else:
        out = json.dumps(rows, ensure_ascii=False, indent=2)
    if args.out:
        write_raw(os.path.abspath(args.out), out + ("" if out.endswith("\n") else "\n"))
        print(f"wrote {args.out} ({len(rows)} rows)")
    else:
        print(out)
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    entries = find_entries(journal, lessons_skip(lessons)) if journal else {}
    nums = sorted(entries)
    lines = [f"# 交接摘要（生成于 {today()}）", ""]
    sb = status_block_text(journal) if journal else ""
    lines += ["## " + K_STATUS, "", sb or "(索引里没有状态块)", ""]
    open_items, _ = todo_items(journal) if journal else ([], [])
    lines += ["## " + K_TODO, ""] + (open_items or ["(无未完成项)"]) + [""]
    lines += [f"## 近期记录（最近 {args.entries} 篇）", "", "| 篇号 | 日期 | 迭代 | 标题 |", "|---|---|---|---|"]
    for n in sorted(nums, reverse=True)[: args.entries]:
        m = meta_of(entries[n][0])
        lines.append(f"| {n:04d} | {m['date'] or '-'} | {m['iter'] or '-'} | {m['title']} |")
    lines.append("")
    if lessons:
        lines += ["## 经验要点", ""]
        for f in sorted(os.listdir(lessons)):
            if not f.endswith(".md") or f == "README.md":
                continue
            text = read(os.path.join(lessons, f))
            h1 = H1_RE.search(text)
            bullets = [l.strip() for l in text.splitlines() if l.strip().startswith("- ")][: args.per_volume]
            lines += [f"### {h1.group(1).strip() if h1 else f}", ""] + bullets + [""]
    out = "\n".join(lines).rstrip() + "\n"
    if args.out:
        write_raw(os.path.abspath(args.out), out)
        print(f"wrote {args.out} ({len(out)} B)")
    else:
        print(out)
    return 0


def cmd_retro(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    entries = find_entries(journal, lessons_skip(lessons)) if journal else {}
    nums = [n for n in sorted(entries) if args.from_num <= n <= args.to_num]
    if not nums:
        print("ERROR: 区间内没有记录")
        return 1
    stage = args.stage or "阶段"

    def link_for(path: str) -> str:
        base = lessons if lessons else journal
        return os.path.relpath(path, base).replace(os.sep, "/")

    out = [f"# 99 · 阶段复盘", "", f"## 一、阶段表（{stage}）", "",
           "| 迭代 | 日期 | 记录 | 产出 |", "|---|---|---|---|"]
    for n in nums:
        m = meta_of(entries[n][0])
        out.append(f"| {m['iter'] or '-'} | {m['date'] or '-'} | [wl/{n:04d}]({link_for(entries[n][0])}) | {m['title']} |")
    out += ["", "## 二、核心成果", "", "## 三、最有价值的可复用发现", ""]
    out += ["## 四、遗留事项", ""]
    leaves = 0
    for n in nums:
        text = read(entries[n][0])
        for line in text.splitlines():
            if re.match(r"^\s*-\s*\[ \]", line):
                # 固定切 5 个字符会在 `-  [ ] x`（多一个空格）或裸 `- [ ]` 上切错，
                # 用正则把复选框前缀整段吃掉。
                item = re.sub(r"^\s*-\s*\[ \]\s*", "", line).strip()
                out.append(f"- {item}（`wl/{n:04d}`）")
                leaves += 1
    if not leaves:
        out.append("- （区间内记录没有未完成项）")
    out.append("")
    body = "\n".join(out)
    if args.out:
        write_raw(os.path.abspath(args.out), body)
        print(f"wrote {args.out} ({len(nums)} entries, {leaves} open items)")
    else:
        print(body)
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--work-log", dest="work_log", default=None,
                   help="工作记录容器目录名，默认 work_log/（回退旧名 journal/、work-log/）")
    p.add_argument("--journal", default=None,
                   help="已弃用：--work-log 的旧名，等价（现在它命名的是**容器**）")
    p.add_argument("--lessons", default=None,
                   help="容器内的经验目录名，默认 lessons/（旧布局也认 <根>/lessons/）")


def _add_root(p: argparse.ArgumentParser) -> None:
    p.add_argument("root", nargs="?", default=".", help="项目根，默认当前目录")


def _root_and_num(paths: list[str]) -> tuple[str, int]:
    """支持 `show 42` 与 `show <root> 42` 两种写法。"""
    if len(paths) == 1:
        root, num = ".", paths[0]
    elif len(paths) == 2:
        root, num = paths[0], paths[1]
    else:
        raise SystemExit("用法：[ROOT] NUM（例如 `show 42` 或 `show ./proj 42`）")
    try:
        return root, int(num)
    except ValueError:
        raise SystemExit(f"NUM 必须是篇号（整数），收到：{num!r}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="journal.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="项目长期工作记录工具箱：少读（brief/show/search）、少写（status/mode/todo/index/append/lesson）、可校验（check/lint）。",
        epilog="约定见 skill 的 references/conventions.md；完整命令说明见 references/commands.md。",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name: str, func, help_text: str, root: bool = True):
        p = sub.add_parser(name, help=help_text)
        _add_common(p)
        if root:
            _add_root(p)
        p.set_defaults(func=func)
        return p

    p = add("new", cmd_new, "生成下一篇记录")
    p.add_argument("--title", required=True)
    p.add_argument("--iter", type=str, default=None, help=f"迭代编号（默认 -；解析时兼容变更集/批次/阶段/版本/里程碑，也接受 v2/批次B 这类非数字标签）")
    p.add_argument("--slug", default=None)
    p.add_argument("--date", default=None)
    p.add_argument("--cmd", default=None, help="预填验证依据（命令 / 数据 / 引用 / 样本）")
    p.add_argument("--insert", action="store_true", help="自动补进索引表")
    p.add_argument("--stage", default=None, help="配合 --insert 指定阶段小节")
    p.add_argument("--dry-run", action="store_true")

    p = add("check", lambda a: _run(Report(a.strict), lambda: check(os.path.abspath(a.root), a.journal, a.lessons, a.strict), a), "结构门禁")
    p.add_argument("--strict", action="store_true", help="把 WARN 当 ERROR")
    p.add_argument("--quiet", action="store_true")

    p = add("lint", lambda a: _run(Report(a.strict), lambda: lint(os.path.abspath(a.root), a.journal, a.lessons, a.strict), a), "内容质量门禁")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--quiet", action="store_true")

    p = add("brief", cmd_brief, "压缩上下文快照")
    p.add_argument("--entries", type=int, default=8, help="近期记录条数（默认 8）")
    p.add_argument("--max-status-lines", type=int, default=30)
    p.add_argument("--max-todo", type=int, default=10)
    p.add_argument("--width", type=int, default=200, help="每行截断宽度（默认 200 字符）")

    p = add("outline", cmd_outline, "全部记录一行表")

    p = add("show", cmd_show, "单篇记录大纲", root=False)
    p.add_argument("paths", nargs="+", metavar="[ROOT] NUM")

    p = add("search", cmd_search, "定向检索")
    p.add_argument("pattern")
    p.add_argument("--in", dest="in_", choices=["journal", "work_log", "lessons", "all"], default="all",
                   help="检索范围：work_log（=旧写法 journal）只查过程记录，lessons 只查经验，all 查整个容器")
    p.add_argument("--regex", action="store_true")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--files", action="store_true", help="只列命中文件")

    p = add("stats", cmd_stats, "语料统计")
    p = add("topics", cmd_topics, "同主题簇建议")
    p.add_argument("--keywords", default=None, help="逗号分隔的中文/任意关键词")
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--max-df", type=int, default=12, help="最多出现在多少篇里（默认 12）")

    p = add("export", cmd_export, "机器可读导出")
    p.add_argument("--json", action="store_true", help="JSON（默认）")
    p.add_argument("--csv", action="store_true")
    p.add_argument("--out", default=None)

    p = add("digest", cmd_digest, "生成交接摘要")
    p.add_argument("--entries", type=int, default=12)
    p.add_argument("--per-volume", type=int, default=3)
    p.add_argument("--out", default=None)

    p = add("retro", cmd_retro, "阶段复盘骨架")
    p.add_argument("--from", dest="from_num", type=int, required=True)
    p.add_argument("--to", dest="to_num", type=int, required=True)
    p.add_argument("--stage", default=None)
    p.add_argument("--out", default=None)

    p = add("status", cmd_status, "当前状态块")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("--date", default=None, nargs="?", const="today")
    p.add_argument("--roll", action="store_true", help="旧块归档到 STATE-HISTORY.md（旧布局 archive/STATUS-HISTORY.md）并写新骨架")
    p.add_argument("--dry-run", action="store_true")

    p = add("mode", cmd_mode, "记录精细度：查看 / 切换")
    p.add_argument("--set", default=None,
                   help="切换档位：full / session / digest / milestone"
                        "（也认中文别名：完整 / 会话 / 摘要 / 里程碑，写入时一律规范化）")
    p.add_argument("--why", default=None,
                   help="附一行切换原因（写进 `精细度` 字段：`session（原因：…）`）")
    p.add_argument("--dry-run", action="store_true")

    p = add("todo", cmd_todo, "待办清单")
    p.add_argument("--add", default=None)
    p.add_argument("--done", default=None, help="按子串勾选第一条匹配的未完成项")
    p.add_argument("--drop-done", action="store_true")
    p.add_argument("--dry-run", action="store_true")

    p_arch = add("archive", cmd_archive, "把篇号区间归档到 <stage>/（含链接重写）")
    p_arch.add_argument("--stage", required=True)
    p_arch.add_argument("--from", dest="from_num", type=int, required=True)
    p_arch.add_argument("--to", dest="to_num", type=int, required=True)
    p_arch.add_argument("--no-index", action="store_true", help="不更新归档索引（ARCHIVE.md）")
    p_arch.add_argument("--dry-run", action="store_true")

    p_split = add("split", cmd_split, "按年分卷（把记录移进 <YYYY>/）")
    p_split.add_argument("--by-year", action="store_true", required=True,
                         help="目前只支持按年分卷（必须显式指定）")
    p_split.add_argument("--dry-run", action="store_true")

    p_prune = add("prune", cmd_prune, "冷存候选：报告 / 打包 / 移出（默认只报告）")
    p_prune.add_argument("--older-than", dest="older_than", type=int, default=180,
                         help="只考虑早于 N 天的记录（默认 180）")
    p_prune.add_argument("--stage", default=None, help="只处理归档路径含该子串的记录")
    p_prune.add_argument("--zip", default=None, help="把候选打包成 zip")
    p_prune.add_argument("--apply", action="store_true", help="打包后把原件移出（必须配合 --zip）")
    p_prune.add_argument("--cold-store", dest="cold_store", default=None,
                         help="冷存目录，默认 <项目>/_coldstore/<日期>/")

    p_index = sub.add_parser("index", help="索引维护")
    _add_common(p_index)
    _add_root(p_index)
    isub = p_index.add_subparsers(dest="index_cmd", required=True)
    p_sync = isub.add_parser("sync", help="把漏掉的记录补进索引表")
    _add_common(p_sync)
    p_sync.add_argument("--stage", default=None)
    p_sync.add_argument("--aspect", default=None)
    p_sync.add_argument("--dry-run", action="store_true")
    p_sync.set_defaults(func=cmd_index)

    p_compact = isub.add_parser("compact", help="把已归档阶段的逐条行折叠成区间行（索引瘦身）")
    _add_common(p_compact)
    p_compact.add_argument("--stage", default=None, help="只处理标题含该子串的小节")
    p_compact.add_argument("--dry-run", action="store_true")
    p_compact.set_defaults(func=cmd_index_compact)

    p_lesson = sub.add_parser("lesson", help="经验层维护")
    _add_common(p_lesson)
    _add_root(p_lesson)
    lsub = p_lesson.add_subparsers(dest="lesson_cmd", required=True)
    p_ladd = lsub.add_parser("add", help="追加一条带来源的经验")
    _add_common(p_ladd)
    p_ladd.add_argument("--volume", default=None)
    p_ladd.add_argument("--topic", default=None)
    p_ladd.add_argument("--source", type=int, required=True, help="篇号（wl/NNNN）")
    p_ladd.add_argument("--text", required=True)
    p_ladd.add_argument("--dry-run", action="store_true")
    p_ladd.set_defaults(func=cmd_lesson)

    p = add("append", cmd_append, "向记录追加小节", root=False)
    p.add_argument("paths", nargs="+", metavar="[ROOT] NUM")
    p.add_argument("--section", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--bullet", action="store_true", help="每行自动加 `- ` 前缀")
    p.add_argument("--dry-run", action="store_true")

    return ap


def _run(rep: Report, fn, args: argparse.Namespace) -> int:
    rep = fn()
    rep.print(getattr(args, "quiet", False))
    return 1 if rep.errors() else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # `--work-log` 是 `--journal` 的正式名；两者同名一个 dest，这里统一。
    if getattr(args, "work_log", None):
        args.journal = args.work_log
    if getattr(args, "date", None) == "today":
        args.date = today()
    try:
        result = args.func(args)
    except ValueError as exc:
        # write_raw 对非 UTF-8 目标主动抛错，避免把坏字节写成 U+FFFD。
        print(f"ERROR: 拒绝写入：{exc}")
        print("       记录文件必须是 UTF-8；请先用编辑器把该文件转成 UTF-8 再重试。")
        return 2
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
