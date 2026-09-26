#!/usr/bin/env python3
"""journal.py — 项目长期工作记录（work_log 容器：台账 + 过程记录 + lessons）的工具箱。

目录布局（唯一源：references/conventions.md「目录布局」）
--------------------------------------------------------
    工作记录容器 = <项目根>/work_log/   （默认名，可配置；旧名 journal/、work-log/ 仍被识别）

        README.md            台账（唯一）：索引 + 同主题簇 + 待办 + 当前状态（状态块可选）
        NNN-*.md             过程记录（编号式），直接放在容器根
        YYYY-MM-DD-*.md      过程记录（日期式），直接放在容器根
        <YYYY>/…             按年分卷后的记录
        <stage>/…            归档记录，阶段目录直接建在容器下（不再有 archive/ 一层）
        STATE-HISTORY.md     被替换下来的旧「当前状态」块
        ARCHIVE.md           归档索引
        LEGACY.md            旧记录声明（可选，见「渐进原则」）
        目标.md              长期目标 → 阶段的两层表（可选，见 references/conventions.md「目标」）
        lessons/             经验层（分册），是容器的子目录
        logs/<来源>/         日志与运行产物（见 conventions.md「日志归位要求」）
        .config.json         项目配置文件（可选）：默认档位 / 容器名 / 经验目录名 / 旧记录清单 / 快照篇数

项目配置文件（`<容器>/.config.json`，可选）
------------------------------------------
优先级只有三层：**命令行 > `<容器>/.config.json` > 内置默认**。
缺这个文件不是错误，它等于"全部取内置默认"。
两个**名字**字段（`container` / `lessons`）是例外：它们命名的正是配置文件自己所在的目录，
所以读配置文件之前就得先知道它们——只能按目录发现，配置里的值只当"新项目该叫什么"的备注。
`mode`（配置里的）只提供**新项目的初始档位**；项目里显式切过档之后，台账的 `精细度` 才是权威。

两种记录命名**都认**（实测 237 篇编号式 + 71 篇日期式）：
- 编号式 `NNN-<slug>.md`，H1 必须 `# NNN · <标题>`；编号永不复用、归档不改号。
- 日期式 `YYYY-MM-DD-<slug>.md`，H1 必须 `# YYYY-MM-DD <标题>`（日期后可接一个行内实验号，如 `R21：`）。
- 两种都要求 H1 与文件名一致。**两种都不匹配的文件不是记录，一律忽略**，不做半解析。

设计目标：**少读、少写、可校验**。
- 少读：brief / show / search / outline / snapshot 只吐出需要的那点内容，不必读 50 KB 的索引。
- 少写：status / todo / index / append / lesson 做外科式行级编辑（保留 CRLF 与其余字节）。
- 可校验：check 查结构，lint 查内容质量；渐进原则让旧记录只报 info，不制造一片红。

命令分组
--------
读写 · 上下文
    brief     压缩上下文快照（当前状态 + 待办 + 近期记录），替代整读索引
    snapshot  最近 N 篇的入口元信息汇总（只读，不改任何文件）
    show      单篇大纲（元数据 + 小节 + 行数），决定要不要读全文
    search    定向检索（记录 + 经验），只回命中行
    outline   全部记录的一行表（编号/日期/迭代/标题）

读写 · 维护
    new       生成下一篇记录（--insert 自动补索引行）
    status    当前状态块：show / set / date / roll
    mode      记录精细度（一篇 = 什么）：show / --set / --why
    config    项目配置文件（<容器>/.config.json）：show / --write / --set
    todo      待办清单：list / add / done / drop-done
    index     索引：sync 补漏行
    lesson    经验：add 追加带来源的条目
    append    向某篇记录追加小节（更正 / 遗留）

读写 · 分析与生成
    check     结构门禁（编号/标题、验证、死链、漏索引、状态、来源、目标表；旧记录只报 info）
    lint      内容质量（占位符残留、空小节、含糊措辞、结论缺数字、验证小节只有设置）
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
import fnmatch
import json
import os
import re
import sys
import unicodedata
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
# `变更集` 是**可选**字段（实测 146/162 篇写「无」），它是迭代字段的一个别名，不是一个必填项。
L_ITER = ("迭代", "变更集", "批次", "阶段", "版本", "里程碑", "Iteration", "Milestone")
# 验证类小节词表。`实验 / 判定 / 评测` 是给研究类项目的（见 references/conventions.md）。
L_VERIFY = ("验证", "实测", "复核", "检查", "审查", "评审", "结果", "证据", "评估", "确认",
            "实验", "判定", "评测",
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
K_INDEX = L_INDEX[0]
# 兼容旧名（内部与自测都在用）
K_ITER_ALIASES = L_ITER
VERIFY_WORDS = L_VERIFY

# ---- 记录文件名：两种约定都认（见 references/conventions.md「两种命名约定」）----
# `^\d{4}-\d{2}-\d{2}-` 必须先于编号式判断：否则 `2026-09-02-x.md` 会被
# `^(\d+)-` 半解析成「编号 2026」，于是 11 个日期式文件互相重号、报出假错误。
DATE_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$", re.I)
NUM_NAME_RE = re.compile(r"^(\d{1,4})-(.+)\.md$")
# 编号式也允许纯编号名（纯中文标题的退化形式，见 slugify）。
NUM_BARE_RE = re.compile(r"^(\d{1,4})\.md$")
# 记录文件（两种约定之一）。`is_record_name` 是唯一的判据，别在别处另写一套。
NUM_FILE_RE = re.compile(r"^(?:\d{1,4}(?:-[^/\\]*)?)\.md$", re.I)

# 按年分卷后的目录名：**恰好 4 位数字**才算年份卷，所以 `02-research` 这类阶段名不会被误认。
YEAR_DIR_RE = re.compile(r"^\d{4}$")
# 编号式 H1：`# 209 · 标题`（分隔符也认 `.`、`、`、`:`、`：`）。
HEADING_RE = re.compile(r"^#\s*(\d{1,4})\s*[·.、:：]")
# 日期式 H1：`# 2026-09-06 标题`；日期与标题之间可空一格，也可直接写标题。
DATE_HEAD_RE = re.compile(r"^#\s*(\d{4}-\d{2}-\d{2})\b[ \t]*[·.、:：]?[ \t]*(.*)$")
# 行内实验号（`R21：`）——日期式标题上允许的可选增补，不参与身份。
INLINE_TAG_RE = re.compile(r"^\**([A-Za-z]{1,4}\d{1,4})\**\s*[：:]\s*(.+)$")
H1_RE = re.compile(r"^#\s+(.+)$", re.M)
DATE_LINE_RE = re.compile(rf"^(?:{_any(L_DATE)})\s*[：:]\s*(\S+)", re.M)
CONCLUSION_RE = re.compile(rf"^(?:{_any(L_CONCLUSION)})\s*[：:]\s*(.*)$", re.M)
TRIGGER_RE = re.compile(rf"^(?:{_any(L_TRIGGER)})\s*[：:]\s*(.+)$", re.M)
SCOPE_RE = re.compile(rf"^(?:{_any(L_SCOPE)})\s*[：:]\s*(.+)$", re.M)
STATUS_HEAD_RE = re.compile(
    rf"^#{{2,3}}[ \t]*(?:{_any(L_STATUS)})[ \t]*(?:[（(][^）)\r\n]*[）)])?[ \t]*$", re.M)
ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# 一个「数字 / 百分比」记号：允许 `%`、千分位与小数，但**不允许**前面紧跟字母数字
# （否则 `R21`、`v4`、`0029` 会各自算一个数字记号，把「只有一个编号」的散文判成有数据）。
NUM_TOKEN_RE = re.compile(r"(?<![0-9A-Za-z])\d+(?:[.,]\d+)?%?")
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
MODE_DEFAULT = "full"
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
# 旧记录声明（可选）：容器里已有的记录写在里面，逐条列出，只有它列到的记录才降级。
LEGACY_DECL = "LEGACY.md"
# 目标表（可选，见 references/conventions.md「目标」）：容器根的一个文件，两张表合一。
# 落点是**既有容器里的一个文件**，不是新目录、也不是新容器：再开一个容器会破坏
# 「一个项目一个容器」这条告诉 journal.py 去哪找东西的约定，还会把目标的进展与
# 作为证据的记录劈成两处——同一件事两个答案，正是本项目反复在修的那类缺陷。
GOALS_FILE = "目标.md"
# 四个状态**人工维护**，不从引用的记录推导：推导规则一旦复杂就会算错，
# 而算错的目标表比手写的更不可信。
GOALS_STATUSES = ("未开始", "进行中", "已完成", "已放弃")
# 目标表的列。表头认得出哪几列就校验哪几列（见 parse_goals）。
GOALS_COLUMNS = ("目标", "阶段", "状态", "相关记录")

# ---- 渐进原则（老记录只报不拦）----
# 依据是**显式清单**，不是日期启发式：日期不可靠（实测同一份语料里日期字段只覆盖一半），
# 而「这条记录是改动之前写的」只有人能确定。三处来源，优先级从高到低：
#   1. `--legacy <glob|name|…>`（命令行，逗号分隔；显式给了就以它为准，空串也算显式）
#   2. 容器根的 `LEGACY.md`（跟着容器进版本控制，团队共用）
#   3. 都没有时按**容器规模**兜底（见 `LEGACY_AUTO_MIN_RECORDS`）：
#      够大的容器按「整批都是旧记录」处理，小容器按「新项目」处理。
LEGACY_DEFAULT: tuple[str, ...] = ("**",)

# 兜底判据的规模门槛：容器里**少于**这么多篇记录时，不吃兜底，按新格式判 error。
#
# 为什么用规模、而不是日期：日期不可靠（实测同一份语料里日期字段只覆盖一半），
# 而"记录还很少"是"这个容器刚起步"的一个客观信号（实测三个语料是 30 / 71 / 207 篇）。
# 于是：
#   - 新项目（记录还少）：写坏的记录照报 error —— 新规格该红就红；
#   - 老项目（记录已多）：旧格式问题只报 info —— 零配置也不是一片红；
#   - 一个**体量小**的老项目会被当成新项目（多报几条），用 `LEGACY.md` 一次就能收准。
#
# 代价写清楚：这条兜底是"宁可多报，也不放过新记录"。想彻底按新格式判就用 `--legacy ""`。
LEGACY_AUTO_MIN_RECORDS = 5

# 只有「因旧格式而失败」的发现才受渐进原则影响。判据是这条：新格式要求它吗？
# 索引覆盖、死链、lessons 来源这些**从来就有**的客观规则不在内，永远照报。
RULE_TITLE = "标题形制"       # H1 必须与文件名一致（编号式带篇号 / 日期式带日期）
RULE_ENTRY_DATE = "入口日期行"  # 旧技能要求 `日期：` 字段行
RULE_VERIFY = "验证小节"       # 旧技能要求六段式里的验证小节

LEGACY_RULES = (RULE_TITLE, RULE_ENTRY_DATE, RULE_VERIFY)

# ---- 项目配置文件（`<容器>/.config.json`，见 references/conventions.md「项目配置文件」）----
# 优先级只有三层，不重叠：命令行 > <容器>/.config.json > 内置默认。
# 两个**名字**字段（container / lessons）是例外，见 load_project_config 的说明。
CONFIG_NAME = ".config.json"
CFG_MODE = "mode"
CFG_CONTAINER = "container"
CFG_LESSONS = "lessons"
CFG_LEGACY = "legacy"
CFG_SNAPSHOT_ENTRIES = "snapshotEntries"
# 配置文件的字段顺序（写文件时按它排，读文件时不要求）
CONFIG_FIELDS = (CFG_MODE, CFG_CONTAINER, CFG_LESSONS, CFG_LEGACY, CFG_SNAPSHOT_ENTRIES)
# `snapshot --entries` 的内置默认（配置文件里叫 snapshotEntries）
SNAPSHOT_ENTRIES_DEFAULT = 12
# 每个值的来源标签，`config` 逐字段打印
SRC_CLI = "命令行"
SRC_FILE = ".config.json"
SRC_DEFAULT = "内置默认"

# 每个字段的取值说明（`config --set` 的报错与 `config --show` 都引用它）
CONFIG_FIELD_HELP = {
    CFG_MODE: "full / session / digest / milestone（也认中文别名）",
    CFG_CONTAINER: "目录名，如 work_log",
    CFG_LESSONS: "目录名，如 lessons",
    CFG_LEGACY: "逗号分隔的 glob 清单，如 0007-*,archive/**（留空 = 没有旧记录）",
    CFG_SNAPSHOT_ENTRIES: "正整数",
}


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


def resolve_lessons(root: str, container: str | None, name: str | None,
                    extra: tuple[str, ...] = ()) -> str | None:
    """经验目录：先看容器内（新布局 `<容器>/lessons/`），再看项目根（旧布局 `<根>/lessons/`）。

    `extra` 是 `.config.json` 里 `lessons` 字段给的候选名（见 load_project_config）：
    它排在命令行之后、内置默认之前。**只有目录真的存在才算数**，所以配置里的名字
    只是"上哪儿找"的提示，不是"就把目录叫这个"的命令。
    """
    seq: list[str] = []
    for c in (*([name] if name else ()), *extra, LESSONS_DEFAULT):
        if c and c not in seq:
            seq.append(c)
    for base in (container, root):
        if not base:
            continue
        for c in seq:
            if os.path.isdir(os.path.join(base, c)):
                return os.path.join(base, c)
    return None


# --------------------------------------------------------------------------- #
# 项目配置文件（`<容器>/.config.json`）：生效值 + 每个值的来源
# --------------------------------------------------------------------------- #
class Config:
    """一次解析出来的项目配置：生效值、每个值的来源、以及读配置时发现的问题。

    三个来源标签只有三个（`命令行` / `.config.json` / `内置默认`）。容器的 `LEGACY.md`
    是第四处**声明**（它本来就是这套体系的一部分，不是这次新增的），它的来源照实打印。
    `notes` 放"字段与实际不符"的提示，`problems` 放"配置文件读不动 / 值非法"——
    两者都**不改生效值**，只让 `config` 把话说清楚。
    """

    def __init__(self) -> None:
        self.mode = MODE_DEFAULT
        self.container = CONTAINER_DEFAULT
        self.lessons = LESSONS_DEFAULT
        self.legacy: list[str] = []
        self.legacy_declared = False          # 有没有显式清单（命令行 / 配置 / LEGACY.md）
        self.snapshot_entries = SNAPSHOT_ENTRIES_DEFAULT
        self.src = {k: SRC_DEFAULT for k in CONFIG_FIELDS}
        self.path = ""                        # 配置文件的绝对路径（不存在时也给）
        self.exists = False
        self.problems: list[str] = []
        self.notes: list[str] = []

    def value_text(self, key: str) -> str:
        """字段值的一行显示。"""
        if key == CFG_LEGACY:
            return "、".join(self.legacy) if self.legacy else "（空）"
        if key == CFG_SNAPSHOT_ENTRIES:
            return str(self.snapshot_entries)
        return str({CFG_MODE: self.mode, CFG_CONTAINER: self.container,
                    CFG_LESSONS: self.lessons}[key])

    def as_data(self) -> dict:
        """按配置文件的字段顺序给出当前生效值（`config --write` 用）。"""
        return {CFG_MODE: self.mode, CFG_CONTAINER: self.container, CFG_LESSONS: self.lessons,
                CFG_LEGACY: list(self.legacy), CFG_SNAPSHOT_ENTRIES: self.snapshot_entries}


def is_dir_name(name: object) -> bool:
    """是不是一个合法的目录名（非空、不含路径分隔符、不是 `.` / `..`）。"""
    return (isinstance(name, str) and bool(name.strip())
            and not re.search(r"[/\\]", name) and name.strip() not in (".", ".."))


def _pad(text: str, width: int) -> str:
    """按**显示宽度**补空格：中文一个字占两列，按字符数补会让整张表歪掉。"""
    w = sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)
    return text + " " * max(0, width - w)


def _read_config_file(cfg: Config) -> dict:
    """读配置文件填进 cfg，返回解析结果（不存在或读不动时给空 dict）。

    读不动**不是致命错误**：整个文件按"没写"处理，理由记进 `cfg.problems`，
    由 `config` / `check` 报出来。别的命令照常跑——一个坏配置文件不该让工具没法用。
    说明文字里**不带路径**：`config` 的表头与 `check` 的发现位置都已经写明是哪个文件。
    """
    if not os.path.isfile(cfg.path):
        return {}
    cfg.exists = True
    try:
        data = json.loads(read_raw(cfg.path))
    except ValueError as exc:
        cfg.problems.append(f"不是合法 JSON（{exc}）；本次全部按内置默认")
        return {}
    if not isinstance(data, dict):
        cfg.problems.append("顶层必须是对象（`{…}`）；本次全部按内置默认")
        return {}
    for key in data:
        if key not in CONFIG_FIELDS:
            cfg.problems.append(f"有认不出的字段 `{key}`；只认 {' / '.join(CONFIG_FIELDS)}"
                                f"（忽略它，不影响生效值）")
    return data


def load_project_config(root: str, container_arg: str | None = None, lessons_arg: str | None = None,
                        legacy_arg: str | None = None) -> tuple[str | None, str | None, Config]:
    """一次解析出（容器目录, 经验目录, 配置）。

    容器**只按目录发现**（`--work-log` → `work_log/` → `journal/` → `work-log/`）：
    配置文件就住在容器里，读它之前先得找到容器。所以配置里的 `container` 字段
    **改不了生效值**——它连自己所在的目录都指不动，只说明"新项目该叫什么"。
    发现到的容器名也不等于配置说的名字时，照实际目录走，并在 `config` 里报出来。
    """
    cfg = Config()
    container = resolve_dir(root, container_arg, CONTAINER_FALLBACKS)
    if container is None:
        if container_arg:
            cfg.container = container_arg
            cfg.src[CFG_CONTAINER] = SRC_CLI
        return None, None, cfg
    cfg.container = os.path.basename(os.path.normpath(container))
    cfg.src[CFG_CONTAINER] = SRC_CLI if container_arg else SRC_DEFAULT
    cfg.path = os.path.join(container, CONFIG_NAME)
    data = _read_config_file(cfg)

    # container：备注字段，绝不改生效值
    if CFG_CONTAINER in data:
        want = data[CFG_CONTAINER]
        if not is_dir_name(want):
            cfg.problems.append(f"`{CFG_CONTAINER}` 必须是目录名：{want!r}")
        elif want.strip() != cfg.container:
            cfg.notes.append(f"配置里的 `{CFG_CONTAINER}` 是 `{want.strip()}`，但它所在的目录是 "
                             f"`{cfg.container}/`——配置文件管不了自己所在的目录，按实际目录走")

    # mode：只提供**新项目的初始档位**（台账有 `精细度` 时以台账为准，见 _mode_and_why）
    if CFG_MODE in data:
        raw = data[CFG_MODE]
        canon = MODE_ALIASES.get(raw.strip().lower()) if isinstance(raw, str) else None
        if canon is None:
            cfg.problems.append(f"`{CFG_MODE}` 只认 full / session / digest / milestone：{raw!r}")
        else:
            cfg.mode = canon
            cfg.src[CFG_MODE] = SRC_FILE

    # snapshotEntries：`snapshot` 的默认篇数
    if CFG_SNAPSHOT_ENTRIES in data:
        raw = data[CFG_SNAPSHOT_ENTRIES]
        n = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
        if n is None or n < 1:
            cfg.problems.append(f"`{CFG_SNAPSHOT_ENTRIES}` 必须是正整数：{raw!r}")
        else:
            cfg.snapshot_entries = n
            cfg.src[CFG_SNAPSHOT_ENTRIES] = SRC_FILE

    # lessons：文件里的值只作候选名（见 resolve_lessons 的 extra）
    file_lessons = None
    if CFG_LESSONS in data:
        raw = data[CFG_LESSONS]
        if is_dir_name(raw):
            file_lessons = raw.strip()
        else:
            cfg.problems.append(f"`{CFG_LESSONS}` 必须是目录名：{raw!r}")

    # legacy：命令行 > 配置 > LEGACY.md > 规模兜底
    if CFG_LEGACY in data:
        raw = data[CFG_LEGACY]
        if isinstance(raw, list) and all(isinstance(x, str) for x in raw):
            cfg.legacy = [x.strip() for x in raw if x.strip()]
            cfg.legacy_declared = True
            cfg.src[CFG_LEGACY] = SRC_FILE
        else:
            cfg.problems.append(f"`{CFG_LEGACY}` 必须是字符串数组"
                                f"（如 [\"0007-*\", \"archive/**\"]）：{raw!r}")
    if legacy_arg is not None:
        cfg.legacy = [p.strip() for p in legacy_arg.split(",") if p.strip()]
        cfg.legacy_declared = True
        cfg.src[CFG_LEGACY] = SRC_CLI
    elif not cfg.legacy_declared and os.path.isfile(legacy_decl_path(container)):
        cfg.legacy = legacy_decl_patterns(container)
        cfg.legacy_declared = True
        cfg.src[CFG_LEGACY] = LEGACY_DECL

    extra = (file_lessons,) if file_lessons else ()
    lessons = resolve_lessons(root, container, lessons_arg, extra)
    if lessons is None:
        cfg.lessons = lessons_arg or file_lessons or LESSONS_DEFAULT
        cfg.src[CFG_LESSONS] = (SRC_CLI if lessons_arg
                                else (SRC_FILE if file_lessons else SRC_DEFAULT))
    else:
        found = os.path.basename(os.path.normpath(lessons))
        cfg.lessons = found
        if lessons_arg and found == lessons_arg:
            cfg.src[CFG_LESSONS] = SRC_CLI
        elif file_lessons and found == file_lessons:
            cfg.src[CFG_LESSONS] = SRC_FILE
        else:
            cfg.src[CFG_LESSONS] = SRC_DEFAULT
        if file_lessons and found != file_lessons and not lessons_arg:
            cfg.notes.append(f"配置里的 `{CFG_LESSONS}` 是 `{file_lessons}/`，但 `<容器>/` 下"
                             f"实际存在的是 `{found}/`——按实际目录走")
    return container, lessons, cfg


def config_notes_for_report(cfg: Config) -> list[tuple[str, str]]:
    """把配置的问题与提示转成 (级别, 文字) 供 `check` 报出来。没有配置文件就什么都不报。

    一律 **INFO**：配置文件是输入提示，不是记录本身。它坏了，工具照旧按内置默认跑，
    `check` 只提醒一句、不进退出码——否则一个手滑的字段会让 CI 红，而根因不在记录里。
    真正要拍板的是 `config` 命令：它把问题逐条打印，并以退出码 2 收场。
    """
    if not cfg.exists:
        return []
    rows = [("INFO", p) for p in cfg.problems]
    rows.extend(("INFO", n) for n in cfg.notes)
    return rows


# --------------------------------------------------------------------------- #
# 两种命名约定：判据只写在这一处
# --------------------------------------------------------------------------- #
def is_record_name(name: str) -> bool:
    """文件名是不是一条记录（编号式或日期式）。两者都不匹配就不是记录。

    `README.md`、`ARCHIVE.md`、`INDEX.md`、`模型效果总表.md`、`归档-…md`
    都落在这里返回 False —— 它们**不是**记录，不做半解析。
    """
    return bool(DATE_NAME_RE.match(name) or NUM_FILE_RE.match(name))


def name_style(name: str) -> str:
    """记录文件名的形制：`date` / `num` / `""`（不是记录）。"""
    if DATE_NAME_RE.match(name):
        return "date"
    if NUM_FILE_RE.match(name):
        return "num"
    return ""


def name_number(name: str) -> int | None:
    """编号式文件名的篇号；日期式与其它返回 None。"""
    if DATE_NAME_RE.match(name):
        return None
    m = NUM_NAME_RE.match(name) or NUM_BARE_RE.match(name)
    return int(m.group(1)) if m else None


def name_date(name: str) -> str:
    """日期式文件名里的日期（`YYYY-MM-DD`）；不是日期式就返回空串。"""
    return name[:10] if DATE_NAME_RE.match(name) else ""


def legacy_decl_path(container: str) -> str:
    """容器根的 `LEGACY.md` 落点。"""
    return os.path.join(container, LEGACY_DECL)


def goals_path(container: str) -> str:
    """容器根的 `目标.md` 落点。**缺它是正常的**——三个真实语料里一个都没有。"""
    return os.path.join(container, GOALS_FILE)


def legacy_decl_patterns(container: str) -> list[str]:
    """读容器根 `LEGACY.md` 里的旧记录清单：一行一条 glob。

    跳过空行与 `#` 注释，容忍列表符号与反引号（手写时很常见）。
    文件不存在返回空列表；**文件存在但一条都没有**也算"有声明"（见 legacy_explicit），
    那等于说"没有旧记录"，不是"没声明"。
    """
    path = legacy_decl_path(container)
    if not os.path.isfile(path):
        return []
    pats = []
    for line in read(path).splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        s = re.sub(r"^[-*+]\s*", "", s).strip().strip("`")
        if s:
            pats.append(s)
    return pats


def legacy_explicit(container: str, cli: str | None, cfg: "Config | None" = None
                    ) -> tuple[bool, list[str]]:
    """返回 (是否用了显式清单, 清单)。

    显式清单的四个来源，优先级从高到低：命令行 `--legacy`、`.config.json` 的 `legacy`、
    容器根的 `LEGACY.md`。都没有时返回 `(False, [])`——调用方使用**兜底判据**
    （见 `LEGACY_AUTO_MIN_RECORDS`）。

    `cfg` 是 `load_project_config` 的结果：给了就用它（前三处来源在那边已经合并好），
    没给就照旧只读 `LEGACY.md` —— 那条路留着，是为"只装了脚本、没走配置解析"的调用方。
    """
    if cfg is not None:
        if cli is not None:
            return True, [p.strip() for p in cli.split(",") if p.strip()]
        return (True, list(cfg.legacy)) if cfg.legacy_declared else (False, [])
    if cli is not None:
        return True, [p.strip() for p in cli.split(",") if p.strip()]
    if os.path.isfile(legacy_decl_path(container)):
        return True, legacy_decl_patterns(container)
    return False, []


def _legacy_match(pat: str, path: str, container: str, name: str) -> bool:
    """一条 glob 是否命中这条记录。支持容器相对路径、纯文件名、`**`、`<stage>/*`。

    `**` 与 `*` 都当"全部命中"：用户写 `*` 的本意几乎一定是"全库"，
    而在 fnmatch 里 `*` 不跨 `/`，对归档记录里的 `archive/<stage>/x.md` 会落空——
    那会让人以为"我明明写了 * 却没生效"。宁可当全命中，也不要这种静默落空。
    """
    if pat in ("**", "*"):
        return True
    relp = rel(container, path)
    for cand in (relp, name, f"**/{relp}", f"**/{name}"):
        if fnmatch.fnmatch(cand, pat):
            return True
    # 目录前缀写法：`archive/**`、`archive/`、`archive`
    for suffix in ("", "/", "/**"):
        for base in (pat.rstrip("/"),):
            d = (base + suffix).rstrip("/")
            if d and d != "**" and (relp == d or relp.startswith(d + "/")):
                return True
    return False


def is_legacy(container: str, path: str, patterns: list[str]) -> bool:
    """这条记录算不算「改动之前写的」——决定它的旧格式问题是 info 还是 WARN/ERROR。"""
    name = os.path.basename(path)
    return any(_legacy_match(p, path, container, name) for p in patterns)


def old_format_hits(text: str, style: str, num: int | None, date: str) -> list[str]:
    """一篇记录踩中了几条**旧格式**规则（用于说明与自测，不参与判定）。

    只看会受渐进原则影响的那几条：H1 形制、入口 `日期：` 行、验证小节。
    与 `check` 里的实际判定必须**同一口径**——两边说的是同一件事，不能各判一套。
    """
    hits: list[str] = []
    h1 = H1_RE.search(text)
    if not h1:
        hits.append(RULE_TITLE)
    elif style == "num":
        m = HEADING_RE.match("# " + h1.group(1))
        if not m or int(m.group(1)) != num:
            hits.append(RULE_TITLE)
    else:
        m = DATE_HEAD_RE.match("# " + h1.group(1))
        if not m or m.group(1) != date:
            hits.append(RULE_TITLE)
    dm = DATE_LINE_RE.search(text)
    if not dm and not date and not date_from_h1(h1.group(1) if h1 else ""):
        hits.append(RULE_ENTRY_DATE)
    if not find_verify_section(text.splitlines()):
        hits.append(RULE_VERIFY)
    return hits


def auto_legacy_paths(recs: list[dict]) -> set[str]:
    """兜底判据：没有显式清单时，把**够大的**容器整批当旧记录。

    只有一条规则：记录数 ≥ `LEGACY_AUTO_MIN_RECORDS` ⇒ 全部命中。
    小容器返回空集 —— 那是新项目，按新格式判（理由与代价见那个常量的注释）。
    """
    if len(recs) < LEGACY_AUTO_MIN_RECORDS:
        return set()
    return {r["path"] for r in recs}


def resolve_layout(root: str, container_arg: str | None, lessons_arg: str | None
                   ) -> tuple[str | None, str | None]:
    """一次解析出（容器目录, 经验目录）。

    容器回退顺序 `work_log/` → `journal/` → `work-log/`：新项目用 `work_log/`；
    旧项目只要还在用旧名就照旧被认出来，**不迁移、不改名、不警告**。
    要拿生效配置（来源、`mode`、`legacy`、`snapshotEntries`）就用 `load_project_config`。
    """
    container, lessons, _cfg = load_project_config(root, container_arg, lessons_arg)
    return container, lessons


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
    """容器下所有**编号式**记录（含归档与分卷），按篇号分组。

    只收编号式：日期式记录没有篇号，进了这个表就会互相覆盖。需要两种都遍历时用
    `find_records`；需要篇号（归档 / 分卷 / `wl/NNNN` 回指）时才用本函数。

    `skip_dirs` 用来排除容器内**不是记录**的子目录：经验层（`--lessons` 改名后
    要显式传进来，见 `lessons_skip`）与日志目录（`logs/`）。它们里面的
    `01-topic.md`、`2026-01-01-run.md` 与记录文件名形状相同，不排除就会被当成记录。
    """
    skip = {".git", "node_modules", *NON_RECORD_DIRS, *skip_dirs}
    found: dict[int, list[str]] = {}
    for dp, dn, fn in os.walk(container):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            if not NUM_FILE_RE.match(f) or DATE_NAME_RE.match(f):
                continue
            n = name_number(f)
            if n is not None:
                found.setdefault(n, []).append(os.path.join(dp, f))
    return found


def find_records(container: str, skip_dirs: tuple[str, ...] = ()) -> list[dict]:
    """容器下**全部**记录（编号式 + 日期式），按身份排序。

    每条是一个 dict：`{rid, kind, num, date, style, name, path, label, prefix}`。
    `rid` 是稳定身份，也是排序键 —— 编号式零填充成 5 位（`00046`），日期式就是
    `YYYY-MM-DD`，两者字典序即时间序。文件名不匹配任何约定的文件**不在结果里**。
    """
    skip = {".git", "node_modules", *NON_RECORD_DIRS, *skip_dirs}
    out: list[dict] = []
    for dp, dn, fn in os.walk(container):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            style = name_style(f)
            if not style:
                continue
            path = os.path.join(dp, f)
            if style == "date":
                rid, num, date = f[:10], None, f[:10]
            else:
                num = name_number(f)
                rid, date = f"{num:05d}", ""
            out.append({"rid": rid, "kind": "num" if style == "num" else "date",
                        "num": num, "date": date, "style": style, "name": f,
                        "path": path, "prefix": ""})
    out.sort(key=lambda r: (r["rid"], r["name"]))
    for r in out:
        r["path"] = r["path"]
    return out


def display_of(rec: dict) -> str:
    """一行表 / 标题里显示的身份（编号式给篇号，日期式给日期）。"""
    return f"{rec['num']:04d}" if rec["kind"] == "num" else rec["date"]


def entry_label(rec: dict) -> str:
    """面向人的标签：编号式 `#0007`，日期式给文件名。"""
    return f"#{rec['num']:04d}" if rec["kind"] == "num" else rec["name"]


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
    if not (NUM_FILE_RE.match(os.path.basename(path)) and not DATE_NAME_RE.match(os.path.basename(path))):
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


def strip_title_prefix(title: str, style: str, fname_date: str = "") -> str:
    """去掉 H1 里属于「身份」的那一段，只留标题文字。

    编号式去掉 `NNN · `；日期式去掉行首的日期，以及紧随其后的行内实验号（`R21：`）。
    """
    s = title.strip()
    if style == "num":
        return re.sub(r"^\d{1,4}\s*[·.、:：]\s*", "", s).strip()
    if style == "date":
        s = re.sub(r"^\d{4}-\d{2}-\d{2}\s*[·.、:：]?\s*", "", s).strip()
        m = INLINE_TAG_RE.match(s)
        if m:
            s = m.group(2).strip()
    return s


def meta_of(path: str) -> dict:
    """解析一篇记录的元数据（不全量保留正文）。

    两种命名都认：形制从**文件名**判定，`date` 优先取入口的 `日期：` 行，
    日期式记录没有那一行时退回文件名里的日期（实测 71 篇里 68 篇靠文件名）。
    """
    text = read(path)
    name = os.path.basename(path)
    style = name_style(name) or "num"
    fdate = name_date(name)
    h1 = H1_RE.search(text)
    h1_text = h1.group(1).strip() if h1 else ""
    title = strip_title_prefix(h1_text, style, fdate) if h1 else name
    dm = DATE_LINE_RE.search(text)
    # `日期：` 是可选的：没有它时用文件名 / H1 上的日期顶上，别让「两个地方都写了
    # 日期」的记录反而报缺日期。
    date = dm.group(1) if dm else (fdate or date_from_h1(h1_text))
    iv = parse_iter(text)
    if not iv and style == "date":
        iv = inline_tag_of(h1_text)
    cm = CONCLUSION_RE.search(text)
    sections = re.findall(r"^(#{2,3})\s+(.+?)\s*$", text, re.M)
    return {
        "title": title,
        "date": date,
        "iter": iv,
        "conclusion": (cm.group(1).strip() if cm else ""),
        "sections": [s[1] for s in sections],
        # 用 splitlines 而不是 count("\n")+1：后者对每个以换行结尾的文件都多算一行。
        "lines": len(text.splitlines()),
        # 磁盘上的真实字节数；不能用 len(text.encode())，因为 read() 会归一换行，
        # CRLF 文件会因此少算一半换行。
        "bytes": _file_size(path),
        "has_date": bool(date),
        "has_verify": bool(VERIFY_HEAD_RE.search(text)),
        "style": style,
    }


def date_from_h1(h1_text: str) -> str:
    """H1 里的日期（日期式）。`h1_text` 是 `# ` 之后的那段。"""
    m = DATE_HEAD_RE.match("# " + h1_text) if h1_text else None
    return m.group(1) if m else ""


def inline_tag_of(h1_text: str) -> str:
    """日期式 H1 上可选的线内实验号（`R21`）；没有就返回空串。"""
    m = DATE_HEAD_RE.match("# " + h1_text) if h1_text else None
    if not m:
        return ""
    # H1 已经去掉 `# ` 这一层，所以拿第 2 组（日期之后的那段）当标题。
    t = INLINE_TAG_RE.match(m.group(2).strip().lstrip("*").strip())
    return t.group(1) if t else ""


# 入口元信息的两族写法：引用块式（`> 状态：… ｜ 工具：…`）与字段行式（`日期：…`）。
# 只认实义字段名：`结论 / 触发 / 范围 / 日期 / 状态 / 工具 / 产物 / 迭代 / 变更集 …`。
# 不认 `说明`、`注` 这类太泛的词，否则正文里的普通行会被当成入口块。
ENTRY_KEYS = ("日期", "Date", "状态", "Status", "工具", "Tool", "产物", "Output", "Artifact",
              "触发", "Trigger", "Context", "范围", "Scope", "结论", "Conclusion", "Result",
              "迭代", "变更集", "批次", "阶段", "版本", "里程碑", "Iteration", "Milestone",
              "来源", "Source", "环境", "Environment")
FIELD_RE = re.compile(rf"^[ \t]*[-*+]?[ \t]*(?:{_any(ENTRY_KEYS)})\s*[：:]\s*(.*\S)?[ \t]*$")
ENTRY_H3_RE = re.compile(r"^#{3,4}[ \t]*.*(?:入口|元信息|头部|概要)[ \t]*$")


def entry_block_of(text: str) -> tuple[dict[str, str], str]:
    """读一篇记录**已在手上的正文**，返回 (字段表, 原始块文本)。

    参数是正文本身（调用方已经 `read` 过），不是路径 —— 少读一次盘，也免得把
    正文当路径传进来（那会静默返回空表）。

    认两种风格，也认它们混写：
    - **引用块式**（实测 `embeding try` 在用）：`> 状态：… ｜ 工具：… ｜ 产物：…`
    - **字段行式**（实测原型与 `comfy` 在用）：`日期：…` / `触发：…` / `范围：…` / `结论：…`
    - 另有一个可选的小节式：`### 入口` 下写字段行。

    **没有入口块不是错**：返回空表，调用方照常输出（`snapshot` 靠这条不炸）。
    """
    lines = text.splitlines()
    fields: dict[str, str] = {}
    first, last = None, None

    def take(i: int, raw: str) -> None:
        nonlocal first, last
        m = FIELD_RE.match(raw)
        if not m:
            return
        key = raw.strip().lstrip("-*+ ").split("：")[0].split(":")[0].strip()
        val = (m.group(1) or "").strip()
        if key and val and key not in fields:
            fields[key] = val
        if first is None:
            first = i
        last = i

    # 1) 前 40 行里的引用块式与字段行式（入口元信息总在开头）。
    for i, raw in enumerate(lines[:40]):
        s = raw.strip()
        if s.startswith(">"):
            for part in re.split(r"[｜|]", s.lstrip("> ").strip()):
                m = FIELD_RE.match(part)
                if m:
                    key = part.strip().split("：")[0].split(":")[0].strip()
                    val = (m.group(1) or "").strip()
                    if key and val:
                        fields.setdefault(key, val)
                    if first is None:
                        first = i
                    last = i
            continue
        take(i, raw)

    # 2) `### 入口` / `### 元信息` 小节（可选写法）。只在开头那一段找。
    if not fields:
        for i, raw in enumerate(lines[:60]):
            if ENTRY_H3_RE.match(raw):
                f2, l2 = None, None
                for j in range(i + 1, min(i + 20, len(lines))):
                    if re.match(r"^#{1,4}\s", lines[j]):
                        break
                    if FIELD_RE.match(lines[j]):
                        key = lines[j].strip().split("：")[0].split(":")[0].strip()
                        val = (FIELD_RE.match(lines[j]).group(1) or "").strip()
                        if key and val:
                            fields.setdefault(key, val)
                        f2 = j if f2 is None else f2
                        l2 = j
                if fields:
                    first, last = f2, l2
                break
    block = "\n".join(lines[first:last + 1]) if first is not None and last is not None else ""
    return fields, block


def entry_line(fields: dict[str, str], order: tuple[str, ...], width: int = 120) -> str:
    """把入口字段压成一行（只输出确实有的字段，缺的不占位）。"""
    parts = []
    seen = set()
    for key in order:
        if key in fields and fields[key] and key not in seen:
            seen.add(key)
            parts.append(f"{key}：{_clip(fields[key], width)}")
    for key, val in fields.items():
        if key not in seen and val:
            parts.append(f"{key}：{_clip(val, width)}")
    return " ｜ ".join(parts)


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
    """按各领域的叫法找「验证 / 复核」小节（验证、评审、检查、结果、证据…）。

    返回 `(标题行下标, 正文起, 正文止, 标题文字, 标题形制)`；最后一项目前只有
    `verify_gap` 用得上——标题里带「设置 / 目的 / 方法 / 计划」的多半只写了做法。
    找不到返回 None。
    """
    for level in (4, 3, 2):
        for word in VERIFY_WORDS:
            span = find_section(lines, level, word)
            if span:
                head = re.sub(r"^#+\s*", "", lines[span[0]].strip()).strip()
                return (span[0], span[1], span[2], head, _head_kind(head))
    return None


SETUP_WORDS = ("设置", "目的", "方法", "计划", "步骤", "待办", "框架", "准备", "背景", "口径")


def _head_kind(head: str) -> str:
    """标题是不是「只交代做法」的那一类（设置 / 目的 / 方法 / 计划…）。"""
    return "设置" if any(w in head for w in SETUP_WORDS) else ""


def verify_gap(body: str, head: str = "") -> str:
    """验证小节「实质内容」口径：只有设置、没有结果时返回一句人话，否则空串。

    两档判据，都是保守的「宁可漏报、别误报」：

    1. **通用档**：正文里必须有 2 个以上独立数字（`NUM_TOKEN_RE`）、或 2 个以上
       反引号包起来的命令/路径、或 3 行以上表格/列表；都不满足时，只要正文够长
       （≥120 字符）也算过——那是散文式论述，不是空架子。
    2. **设置档**（标题含「设置 / 目的 / 方法 / 计划 / 步骤 / 待办 / 框架 / 准备 /
       背景 / 口径」）：`## 评测设置` 这类标题**只交代做法**，所以不能拿命令顶数：
       必须有 2 个以上数字，或有表格。规格 §十一 待确认项 1 点的就是这条。

    已知误报风险（都写进了 references/commands.md「验证小节实质要求」）：
    - 「方法对比」式散文（讲方法的取舍、不落数字）会被报出来。所以默认只报 **WARN**，
      只有 `--strict` 才抬成 ERROR——工具不下判决，人来判。
    - `## 验证：本次未独立验证，见 wl/0009` 这种**诚实的否定**因为带数字会被放过去
      （漏报）。漏报比误报便宜：漏报只是少提一句，误报会让人开始忽略这个工具。
    - 真实语料上的命中量：comfy 30 篇 0 命中、原型 207 篇 3 命中、`embeding try`
      71 篇 1 命中（见 scripts/_selftest.py 的 format_phase 与本次改动的实测）。
    """
    t = body.strip()
    if len(t) < 10:
        return "空小节"
    nums = len(NUM_TOKEN_RE.findall(t))
    backs = t.count("`")
    rows = len(re.findall(r"(?m)^\s*\|", t))
    bullets = len(re.findall(r"(?m)^\s*[-*+]\s", t))
    if _head_kind(head):
        return "" if (nums >= 2 or rows >= 3) else f"长度 {len(t)} 字符、只有设置没有结果"
    if nums >= 2 or backs >= 2 or rows >= 3 or bullets >= 3:
        return ""
    if len(t) >= 120:
        return ""
    return f"长度 {len(t)} 字符的散文"


def _mark_legacy(rep: "Report", idx: int | None, legacy: bool, rule: str) -> None:
    """把刚加的那条发现标成「旧格式规则」，必要时由渐进原则降为 info。

    只降级 `LEGACY_RULES` 里那几条（H1 形制 / 入口日期行 / 验证小节）：死链、
    漏索引、lessons 来源这些**从来就有**的客观规则不受影响，永远照报。
    """
    if rule not in LEGACY_RULES:
        return
    rep.mark_legacy(idx, legacy, rule)


def _checkable(text: str) -> bool:
    """是否含可核对的信息：命令（反引号）/ 数字 / 链接。用于 lint 的领域无关口径。

    数字用 `NUM_TOKEN_RE` 而不是 `\\d`：`R21`、`v4`、`wl/0009` 里的数字是**引用**，
    不是数据，不该被当成「有可核对的信息」（否则「见 wl/0009」会被判成有数据）。
    """
    return ("`" in text) or bool(NUM_TOKEN_RE.search(text)) or ("http" in text)


# --------------------------------------------------------------------------- #
# 目标文件（`<容器>/目标.md`，可选）：长期目标 → 阶段的两层表
# --------------------------------------------------------------------------- #
# 三层分工写清楚，免得又出现"同一件事两处维护"：
#   - 目标表：**多个并行长期目标**各自的阶段与状态（现有体系只有状态块里一个
#     `阶段 / 版本` 字段，装不下并行目标）；
#   - 记录：证据，目标表靠「相关记录」指过去；
#   - 台账：容器当前坐标，与目标表无关。
# 缺这个文件是正常的，一个发现都不报；它**不进任何必填清单**。
def _split_table_row(line: str) -> list[str]:
    """切一行 markdown 表：去掉首尾竖线后按 `|` 分格，逐格去空白。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_table_sep(cells: list[str]) -> bool:
    """是不是 `|---|---|` 那行分隔行。"""
    return bool(cells) and all(re.fullmatch(r":?-{1,}:?", c) for c in cells if c != "")


def parse_goals(text: str) -> list[tuple[int, dict[str, str]]]:
    """解析目标表，返回 `[(行号, {列名: 单元格}), …]`，行号从 1 起。

    表头行决定各列的位置，所以**列序可以不一样**；四个列名认得出哪几列就校验哪几列。
    认不出表头（没有同时含「目标」与「状态」的一行）就当这份文件没有可校验的表——
    缺文件是正常的，认不出的文件同样不报：校验只覆盖那三条机械规则，不给它加义务。
    """
    header: dict[str, int] | None = None
    rows: list[tuple[int, dict[str, str]]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            if header is not None and rows:
                break          # 表格在第一个非表格行结束
            continue
        cells = _split_table_row(line)
        if header is None:
            found = {c: j for j, c in enumerate(cells) if c in GOALS_COLUMNS}
            if "目标" in found and "状态" in found:
                header = found
            continue
        if _is_table_sep(cells):
            continue
        rows.append((lineno, {name: (cells[j] if j < len(cells) else "")
                              for name, j in header.items()}))
    return rows


# 「相关记录」里的一格就是一篇号（可带本体系通用的 `wl/` 回指前缀）。
GOALS_CITE_RE = re.compile(r"^(?:wl/)?(\d{1,4})$")


def _cited_numbers(cell: str) -> list[tuple[str, int]]:
    """相关记录单元格里的篇号，返回 `[(原始写法, 篇号), …]`。

    只认**整格就是一篇号**的 token；`—`、空、自由文字一律跳过。这是刻意的保守：
    日期式容器会在这儿写文件名（`2026-09-06-x.md`），若改成"抠出数字"来判，
    就会被误报成「篇号 2026 不存在」——误报比漏报贵。
    """
    out: list[tuple[str, int]] = []
    for tok in re.split(r"[,，、;；\s]+", cell.strip()):
        m = GOALS_CITE_RE.match(tok.strip().strip("`*").strip())
        if m:
            out.append((tok.strip(), int(m.group(1))))
    return out


def check_goals(root: str, container: str, entries: dict[int, list[str]], rep: "Report") -> None:
    """校验目标表的**三条机械规则**（见 references/conventions.md「目标」）。

    1. 「相关记录」引用的篇号必须真实存在——这是核心价值：否则目标表会悄悄腐化成
       一张写着不存在篇号的清单；
    2. 「状态」必须是 `未开始` / `进行中` / `已完成` / `已放弃` 之一；
    3. 一个目标的第一行必须写出目标名（空目标名 = 续行跑到了没有父行的地方）。

    **明确不校验**：阶段名与索引里的 `### <阶段名>` 是否一致、状态与记录内容是否相符、
    目标是否重复。前两条判定不了，第三条校验了只会教人忽略告警。
    """
    path = goals_path(container)
    if not os.path.isfile(path):
        return                 # 缺这个文件是正常的：一个发现都不报
    where = rel(root, path)
    # `seen_goal`：这张表里出现没出现过目标名。续行的「目标」为空是正常写法（两层表），
    # 前提是它前面已经有行写出了目标名；在第一个目标名之前出现空行，那一行就没有父行。
    # 这个标志**只往前、不重置**：一个目标的第二、第三行续行都算合法续行。
    seen_goal = False
    for lineno, row in parse_goals(read(path)):
        goal = row.get("目标", "")
        status = row.get("状态", "")
        if "目标" in row:
            if goal:
                seen_goal = True
            elif not seen_goal:
                rep.add("ERROR", where,
                        f"第 {lineno} 行：「目标」为空，而它前面没有一行写出过目标名"
                        f"（一个目标的第一行必须写目标名，续行只能跟在这种行后面）")
        if "状态" in row and status not in GOALS_STATUSES:
            if status:
                rep.add("ERROR", where,
                        f"第 {lineno} 行：状态「{status}」认不出，"
                        f"只能是 未开始 / 进行中 / 已完成 / 已放弃")
            else:
                rep.add("ERROR", where,
                        f"第 {lineno} 行：状态为空，必须是 未开始 / 进行中 / 已完成 / 已放弃 之一")
        if "相关记录" in row:
            for raw, num in _cited_numbers(row["相关记录"]):
                if num not in entries:
                    rep.add("ERROR", where,
                            f"第 {lineno} 行：相关记录 `{raw}` 指向的篇号在记录目录里不存在")


# --------------------------------------------------------------------------- #
# check：结构门禁
# --------------------------------------------------------------------------- #
class Report:
    def __init__(self, strict: bool) -> None:
        self.strict = strict
        self.rows: list[tuple[str, str]] = []
        self._seen: set[tuple[str, str]] = set()
        # 每条发现属于哪条「规则」（渐进原则只降级旧格式那几条）。按行号对齐 storage。
        self.rules: list[str] = []
        self.legacy_rows: set[int] = set()

    def add(self, level: str, where: str, msg: str, rule: str = "") -> int | None:
        """加一条发现，返回行号；重复（同级别同文字）被吞掉时返回 None。"""
        if self.strict and level == "WARN":
            level = "ERROR"
        key = (level, f"{where}: {msg}")
        if key in self._seen:
            return None
        self._seen.add(key)
        self.rows.append((level, f"{where}: {msg}"))
        self.rules.append(rule)
        return len(self.rows) - 1

    def mark_legacy(self, idx: int | None, legacy: bool, rule: str) -> None:
        """这条发现是「旧格式规则」；`legacy` 为真时降级为 info。

        在 `prune_legacy` 里统一做，是因为降级必须在**所有**发现加完之后 ——
        否则汇总行会先数出一个已经不存在的 ERROR。
        """
        if idx is None or idx >= len(self.rules):
            return
        if rule:
            self.rules[idx] = rule
        if legacy:
            self.legacy_rows.add(idx)

    def prune_legacy(self) -> int:
        """把 legacy 行降到 INFO，返回降级条数。"""
        n = 0
        for i in sorted(self.legacy_rows):
            lv, text = self.rows[i]
            if lv != "INFO":
                self.rows[i] = ("INFO", text)
                n += 1
        return n

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


def check(root: str, journal_arg: str | None, lessons_arg: str | None, strict: bool,
          legacy: str | None = None) -> Report:
    rep = Report(strict)
    journal, lessons, cfg = load_project_config(root, journal_arg, lessons_arg, legacy)
    if not journal:
        rep.add("ERROR", root, "找不到记录容器（work_log/；旧名 journal/、work-log/ 也认）；先按 templates.md 初始化")
        return rep
    jname = rel(root, journal)
    # 配置文件的问题与提示只在这里报一次（不改退出码：提示是 INFO，值非法是 WARN）。
    for lv, msg in config_notes_for_report(cfg):
        rep.add(lv, rel(root, cfg.path) if cfg.path else jname, msg)
    index = os.path.join(journal, "README.md")
    if not os.path.isfile(index):
        # 台账是**建议**不是门槛：实测五条线里有四条根本没有台账文件，记录照样在写。
        # 缺它只报 info（索引层缺位），不像以前那样一上来就一条 ERROR。
        rep.add("INFO", jname, f"没有台账 `{os.path.basename(index)}`（索引层可选；"
                               f"要导航与状态就按 templates.md 补一份）")
    explicit, pats = legacy_explicit(journal, legacy, cfg)

    entries = find_entries(journal, lessons_skip(lessons))
    recs = find_records(journal, lessons_skip(lessons))
    # 兜底判据只在**没有**显式清单时生效；显式给了就完全按它判（含 `--legacy ""`）。
    auto_paths = set() if explicit else auto_legacy_paths(recs)
    nums = sorted(entries)
    if not recs:
        rep.add("INFO", jname, "目录里还没有记录（新项目正常）")
    for n, paths in sorted(entries.items()):
        if len(paths) > 1:
            rep.add("ERROR", jname, f"编号 {n} 重复：{[rel(root, p) for p in paths]}")
    if nums:
        gaps = [n for n in range(nums[0], nums[-1] + 1) if n not in entries]
        if gaps:
            shown = ", ".join(str(g) for g in gaps[:10]) + (" …" if len(gaps) > 10 else "")
            rep.add("WARN", jname, f"编号断档 {len(gaps)} 处：{shown}")

    total = len(recs)
    style_count = {"num": sum(1 for r in recs if r["kind"] == "num"),
                   "date": sum(1 for r in recs if r["kind"] == "date")}
    date_missing = verify_missing = 0
    for rec in recs:
        text = read(rec["path"])
        where = rel(root, rec["path"])
        legacy_rec = rec["path"] in auto_paths or is_legacy(journal, rec["path"], pats)
        rec_style = rec["kind"]
        sect = find_verify_section(text.splitlines())

        h1 = H1_RE.search(text)
        if not h1:
            want = "`# NNN · 标题`" if rec_style == "num" else "`# YYYY-MM-DD 标题`"
            i = rep.add("WARN", where, f"缺一级标题（应为 {want}）")
            _mark_legacy(rep, i, legacy_rec, RULE_TITLE)
        elif rec_style == "num":
            m = HEADING_RE.match("# " + h1.group(1))
            if not m:
                i = rep.add("WARN", where, "一级标题未带篇号（应为 `# NNN · 标题`）")
                _mark_legacy(rep, i, legacy_rec, RULE_TITLE)
            elif int(m.group(1)) != rec["num"]:
                rep.add("ERROR", where, f"标题篇号 {m.group(1)} 与文件名 {rec['num']} 不一致")
        else:
            m = DATE_HEAD_RE.match("# " + h1.group(1))
            if not m:
                i = rep.add("WARN", where, "一级标题未带日期（应为 `# YYYY-MM-DD 标题`）")
                _mark_legacy(rep, i, legacy_rec, RULE_TITLE)
            elif m.group(1) != rec["date"]:
                rep.add("ERROR", where, f"标题日期 {m.group(1)} 与文件名 {rec['date']} 不一致")

        # `日期：` 入口行**可选**：日期式记录的日期在文件名与 H1 上，两处都有就不该报缺。
        dm = DATE_LINE_RE.search(text)
        if dm and not ISO_DATE_RE.fullmatch(dm.group(1)):
            rep.add("WARN", where, f"日期格式不是 YYYY-MM-DD：{dm.group(1)}")
        elif not dm and not rec["date"] and not date_from_h1(h1.group(1) if h1 else ""):
            date_missing += 1
            i = rep.add("WARN", where,
                        f"缺 `{K_DATE}：YYYY-MM-DD` 入口行（日期式记录也可把日期写在文件名里）")
            _mark_legacy(rep, i, legacy_rec, RULE_ENTRY_DATE)

        if not sect:
            verify_missing += 1
            i = rep.add("WARN", where, "缺验证类小节（标题含 "
                                       + " / ".join(VERIFY_WORDS[:12]) + " 之一，h2–h4 都算）")
            _mark_legacy(rep, i, legacy_rec, RULE_VERIFY)
        else:
            body = "".join(text.splitlines()[sect[1]:sect[2]]).strip()
            bad = verify_gap(body, sect[3])
            if bad:
                i = rep.add("WARN", where, f"验证小节 `{sect[3]}` 只有{bad}——"
                                           f"要数字 / 百分比 / 命令 / 引用输出 / 表格 / 对照")
                _mark_legacy(rep, i, legacy_rec, RULE_VERIFY)
                if sect[4] == "设置":
                    rep.add("INFO", where, "标题是「设置 / 目的 / 方法」这类，验证要求的是**结果**："
                                           "把实测数字或命令输出补上（见 commands.md「验证小节实质要求」）")
    if total:
        if date_missing:
            rep.add("INFO", jname, f"{date_missing}/{total} 篇缺日期行")
        if verify_missing:
            rep.add("INFO", jname, f"{verify_missing}/{total} 篇缺验证小节")
        if style_count["num"] and style_count["date"]:
            rep.add("INFO", jname, f"两种命名混用（编号式 {style_count['num']} 篇 / "
                                   f"日期式 {style_count['date']} 篇）；容器内建议只用一种")

    # 覆盖检查**要先有索引表**。容器整份没有 `## 文件索引` 时，逐篇报一次
    # 「未出现在索引中」只会刷出几十行同一件事（实测 `embeding try` 的四条线
    # 正是这样），真正缺的是那一节。所以整节缺失只报一次。
    has_index_section = any(f"## {a}" in read(index) for a in L_INDEX) if os.path.isfile(index) else False
    if has_index_section:
        for rec in recs:
            if is_active_entry(journal, rec["path"]) and entry_link(journal, rec["path"]) not in read(index):
                rep.add("WARN", jname, f"记录 {entry_link(journal, rec['path'])} 未出现在索引中")
    elif recs:
        rep.add("INFO", jname, f"台账没有「{K_INDEX}」一节——索引层缺位，"
                               f"{len(recs)} 篇记录都没有索引行（要导航就补一节 `## {K_INDEX}`）")

    # 目标表（`<容器>/目标.md`，可选）：缺它是正常的，报 0 个问题。三条机械规则见 check_goals。
    check_goals(root, journal, entries, rep)

    if os.path.isfile(index):
        idx_text = read(index)
        _check_links(root, index, rep)
        blocks = STATUS_HEAD_RE.findall(idx_text)
        if not blocks:
            # 状态块**容器自选**：没有不算错。分散状态的容器（实测 5 条线里 4 条）
            # 根本不该看到红字，所以这里只给一条 info 建议。
            rep.add("INFO", jname, f"台账没有 `## {K_STATUS}` 块（容器自选；"
                                   f"加一块则由 check 校验新鲜度，不加不报错）")
        elif len(blocks) > 1:
            rep.add("ERROR", jname, f"索引有 {len(blocks)} 个「{K_STATUS}」块"
                                    f"（只能有一个，旧块移入 {rel(root, status_history_path(journal))}）")
        else:
            after = idx_text.split(blocks[0], 1)[1]
            nxt = re.search(r"^#{2,3}\s", after, re.M)
            block = blocks[0] + (after[: nxt.start()] if nxt else after)
            sd = max_date_in(block)
            newest = None
            for rec in recs:
                d = max_date_in(read(rec["path"]))
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
def lint(root: str, journal_arg: str | None, lessons_arg: str | None, strict: bool,
         legacy: str | None = None) -> Report:
    rep = Report(strict)
    journal, lessons, cfg = load_project_config(root, journal_arg, lessons_arg, legacy)
    if not journal:
        rep.add("ERROR", root, "找不到记录容器（work_log/；旧名 journal/、work-log/ 也认）")
        return rep
    # 档位只在台账里读一次（台账没有 `精细度` 时退回配置文件的 `mode`）：
    # 粗档位的额外义务按它判（默认档不加要求）。
    mode, _mode_why, _mode_default = _mode_and_why(journal, cfg.mode)
    recs = find_records(journal, lessons_skip(lessons))
    explicit, pats = legacy_explicit(journal, legacy, cfg)
    auto_paths = set() if explicit else auto_legacy_paths(recs)
    for rec in recs:
        path = rec["path"]
        where = rel(root, path)
        legacy_rec = path in auto_paths or is_legacy(journal, path, pats)
        text = read(path)
        lines = text.splitlines()
        for token in PLACEHOLDERS:
            if token in text:
                rep.add("WARN", where, f"占位符未清理：`{token}`")
        cm = CONCLUSION_RE.search(text)
        if not cm or not cm.group(1).strip():
            # `结论：` 也是旧格式的入口字段之一；老记录没它就只报 info。
            i = rep.add("WARN", where, "「结论：」为空")
            _mark_legacy(rep, i, legacy_rec, RULE_ENTRY_DATE)
        elif not _checkable(cm.group(1)):
            rep.add("WARN", where, "结论没有可核对的信息（数字 / 引用 / 链接）")
        span = find_verify_section(lines)
        if span:
            body = "".join(lines[span[1]:span[2]]).strip()
            if len(body) < 10:
                i = rep.add("WARN", where, "验证小节为空")
                _mark_legacy(rep, i, legacy_rec, RULE_VERIFY)
            elif not _checkable(body):
                i = rep.add("WARN", where, "验证小节没有可核对的内容（命令 / 数据 / 引用 / 样本）")
                _mark_legacy(rep, i, legacy_rec, RULE_VERIFY)
            for w in VAGUE:
                if w in body:
                    rep.add("WARN", where, f"验证含含糊措辞：`{w}`")
        else:
            # check 已经报过「缺验证小节」；lint 只在旧记录上补一句同样的 info 口径。
            i = rep.add("WARN", where, "缺验证小节（无法判断内容质量）")
            _mark_legacy(rep, i, legacy_rec, RULE_VERIFY)
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


def _mode_and_why(journal: str, cfg_mode: str | None = None) -> tuple[str, str, bool]:
    """返回 (生效档位, 原因, 是否来自默认值)。

    档位有**两个不同的问题**，不要混：
    - 「这个项目当前用哪档」= 台账 `## 当前状态` 的 `精细度` 字段，台账说了算；
    - 「新项目默认用哪档」= `.config.json` 的 `mode`，只在台账**没有**这一栏时兜底。

    所以这里的顺序是：台账 → `cfg_mode` → `MODE_DEFAULT`。缺字段或值认不出来都算默认值。
    """
    mode, why = mode_of(read(os.path.join(journal, "README.md")))
    if mode:
        return mode, why, False
    return (cfg_mode or MODE_DEFAULT), "", True


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


def snapshot_of(rec: dict, root: str) -> dict:
    """汇总一篇记录的入口元信息（供 `snapshot` 用）。

    编号式取入口的 `日期：` 行（没有就退回 H1 里的日期），日期式直接取文件名日期。
    **没有入口块不是错**：字段表就是空的，照常返回，调用方照常输出。
    """
    text = read(rec["path"])
    m = meta_of(rec["path"])
    fields, _block = entry_block_of(text)
    date = m["date"] or rec["date"]
    ref = f"wl/{rec['num']:04d}" if rec["kind"] == "num" else rec["name"]
    return {"rec": rec, "where": rel(root, rec["path"]), "date": date, "ref": ref,
            "title": m["title"], "fields": fields}


def cmd_snapshot(args: argparse.Namespace) -> int:
    """把最近 N 篇的入口元信息汇总成一份**只读**快照。

    补的是「状态分散在每篇开头」这件事（实测 `embeding try` 把 `> 状态：… ｜ 工具：…`
    写在每篇开头，台账里根本没有状态块）。**只读**：只打印，绝不写容器里的任何文件；
    `--out` 是给调用方自己落盘用的，路径由调用方给。
    """
    root = os.path.abspath(args.root)
    journal, lessons, cfg = load_project_config(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器")
        return 1
    recs = find_records(journal, lessons_skip(lessons))
    if not recs:
        print("没有记录")
        return 0
    # `--entries` 不给时用配置文件的 `snapshotEntries`（再不给是内置默认 12）。
    entries = args.entries if args.entries is not None else cfg.snapshot_entries
    picked = list(reversed(recs))[: entries]
    out = [f"# SNAPSHOT  {rel(root, journal)}"
           f"  （最近 {len(picked)} / 共 {len(recs)} 篇；只读快照，不改任何文件）", ""]
    without = 0
    for item in picked:
        s = snapshot_of(item, root)
        out.append(f"{s['date'] or '(无日期)':10s}  {s['ref']}  {_clip(s['title'], args.width - 30)}")
        if s["fields"]:
            out.append("    " + entry_line(s["fields"], (), args.width))
        else:
            without += 1
            out.append("    （没有入口元信息块）")
    if without:
        out.append("")
        out.append(f"（{without}/{len(picked)} 篇没有入口元信息块——不是错误，只是这层没写）")
    body = "\n".join(out)
    if args.out:
        write_raw(os.path.abspath(args.out), body.rstrip("\n") + "\n")
        print(f"wrote {args.out} ({len(picked)} entries)")
    else:
        print(body)
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器")
        return 1
    recs = find_records(journal, lessons_skip(lessons))
    active = [r for r in recs if is_active_entry(journal, r["path"])]
    span = f"{display_of(recs[0])}–{display_of(recs[-1])}" if recs else "-"
    print(f"# BRIEF  {rel(root, journal)}  ({len(recs)} entries {span};"
          f" active {len(active)} / archive {len(recs) - len(active)})")
    sb = status_block_text(journal)
    if sb:
        lines = sb.splitlines()
        cap = args.max_status_lines
        print("")
        print("\n".join(_clip(l, args.width) for l in lines[:cap]))
        if len(lines) > cap:
            print(f"… (+{len(lines) - cap} lines, use `status`)")
    else:
        print(f"\n(!) 台账里没有状态块（容器自选，不是错误）")
    open_items, _ = todo_items(journal)
    print(f"\n## {K_TODO}（未完成 {len(open_items)}）")
    for it in open_items[: args.max_todo]:
        print(_clip(it, args.width))
    if len(open_items) > args.max_todo:
        print(f"… (+{len(open_items) - args.max_todo} more, use `todo`)")
    print(f"\n## 近期记录（{args.entries}）")
    for rec in list(reversed(recs))[: args.entries]:
        m = meta_of(rec["path"])
        it = f"迭代 {m['iter']}" if m["iter"] and m["iter"] != "-" else "不编号"
        print(f"{display_of(rec):<10s} {m['date'] or '(无日期)':10s} [{it}] "
              f"{'OK ' if m['has_verify'] else 'NO '} {m['title'][:52]}")
    return 0


def cmd_outline(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器")
        return 1
    # 第一列：编号式给篇号，日期式给日期。列宽按容器实际情况取——
    # 纯编号容器保持 4 字符（老输出与老测试都按这个对齐），出现日期式才展宽到 10。
    recs = find_records(journal, lessons_skip(lessons))
    width = 10 if any(r["kind"] == "date" for r in recs) else 4
    for rec in recs:
        m = meta_of(rec["path"])
        tag = m["iter"] if m["iter"] and m["iter"] != "-" else "-"
        print(f"{display_of(rec):<{width}s}\t{m['date'] or '-':10s}\t{tag}\t{m['lines']:4d}L\t{m['title'][:64]}")
    return 0


def _find_record(journal: str, key: str) -> dict | None:
    """按 `show` / `append` 给的身份找一篇记录：篇号、日期、或文件名。

    编号式向后兼容（`show 42`）；日期式按日期或文件名找（`show 2026-09-06`）。
    """
    recs = find_records(journal)
    key = key.strip()
    if key.isdigit():
        n = int(key)
        for r in recs:
            if r["kind"] == "num" and r["num"] == n:
                return r
    for r in recs:
        if r["name"] == key or r["name"] == key + ".md":
            return r
    for r in recs:
        if r["kind"] == "date" and r["date"] == key[:10]:
            return r
    return None


def cmd_show(args: argparse.Namespace) -> int:
    root_arg, key = _root_and_num(args.paths)
    root = os.path.abspath(root_arg)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    rec = _find_record(journal, key) if journal else None
    if rec is None:
        print(f"ERROR: 找不到记录 #{key}")
        return 1
    path = rec["path"]
    m = meta_of(path)
    text = read(path)
    print(f"{display_of(rec)}  {rel(root, path)}")
    print(f"title : {m['title']}")
    print(f"date  : {m['date'] or '-'}   迭代: {m['iter'] or '-'}   {m['lines']} lines / {m['bytes']} B"
          f"   verify: {'yes' if m['has_verify'] else 'no'}")
    for label, pat in (("触发", TRIGGER_RE), ("范围", SCOPE_RE), ("结论", CONCLUSION_RE)):
        mm = pat.search(text)
        if mm:
            print(f"{label:<6}: {mm.group(1).strip()[:100]}")
    fields, _ = entry_block_of(text)
    if fields:
        print("入口  : " + entry_line(fields, (), 60))
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
        nums = [n for t in targets
                if (n := name_number(os.path.basename(t))) is not None]
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
    journal, lessons, cfg = load_project_config(root, args.journal, args.lessons)
    if not journal:
        print("ERROR: 找不到记录容器（work_log/；旧名 journal/、work-log/ 也认），"
              "先按 templates.md 初始化")
        return 1
    text, lines = _index_lines(journal)
    if not find_labeled_section(lines, 2, L_STATUS):
        print(f"ERROR: 索引里没有 `## {K_STATUS}` 块")
        return 1
    cur, why, is_default = _mode_and_why(journal, cfg.mode)

    if args.set is None and not args.why:
        print(f"{cur}    {MODE_MEANING[cur]}")
        if is_default:
            cell = mode_cell(text)
            tail = (f"认不出 `{cell}`（只认 full/session/digest/milestone），按默认档处理"
                    if cell else "台账里没有 `精细度` 字段")
            where = ("配置文件的 `mode`" if cfg.src[CFG_MODE] == SRC_FILE else "内置默认")
            print(f"（{tail}：当前取{where} `{cfg.mode}`）")
        if why:
            print(f"原因：{why}")
        print(f"切换：`journal.py mode --set full|session|digest|milestone`（当前 {MODE_DEFAULT}）")
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


# --------------------------------------------------------------------------- #
# config：项目配置文件（`<容器>/.config.json`）
# --------------------------------------------------------------------------- #
def _set_in_text(text: str, key: str, value_json: str) -> str | None:
    """只改 `"key": <值>` 那一处，其余字节原样不动；改不动返回 None。

    值的结束位置交给 `json.JSONDecoder.raw_decode`，比自己写扫描器可靠。
    匹配要求键**独占行首**（`--write` 写出的是缩进两格、一字段一行），
    所以不会误伤嵌套对象里同名的键。
    """
    m = re.search(rf'^([ \t]*"{re.escape(key)}"[ \t]*:[ \t]*)', text, re.M)
    if not m:
        return None
    start = m.end()
    try:
        _obj, end = json.JSONDecoder().raw_decode(text, start)
    except ValueError:
        return None
    return text[:start] + value_json + text[end:]


def _set_field_surgical(text: str, key: str, value: object) -> str | None:
    """就地把一个字段改成 value；改完解析回来对不上就返回 None（调用方改用整体重排）。

    对不上时**绝不写出去**：宁可重排全文，也不能把一份序列化失败的值留在磁盘上。
    """
    edited = _set_in_text(text, key, json.dumps(value, ensure_ascii=False))
    if edited is None:
        return None
    try:
        return edited if json.loads(edited).get(key) == value else None
    except ValueError:
        return None


def _dump_config_text(data: dict, nl: str, trailing: bool) -> str:
    """把配置对象编回 JSON 文本：字段按固定顺序，未知字段附在后面，换行风格照传入的。"""
    ordered = {k: data[k] for k in CONFIG_FIELDS if k in data}
    ordered.update({k: v for k, v in data.items() if k not in ordered})
    body = json.dumps(ordered, ensure_ascii=False, indent=2)
    if nl != "\n":
        body = body.replace("\n", nl)
    return body + (nl if trailing else "")


def parse_config_sets(pairs: list[str]) -> tuple[list[tuple[str, object]], int]:
    """解析并校验 `--set key=value`，返回 ([(字段, 规范值)], 退出码)。

    取值一律在这里手工校验（与 `mode --set` 同一套口径），不用 argparse 的 choices：
    choices 会把别名表原样倒进报错里，既长又难读。
    """
    out: list[tuple[str, object]] = []
    for pair in pairs:
        if "=" not in pair:
            print(f"ERROR: 认不出的 --set `{pair}`（应写成 key=value）")
            return [], 2
        key, raw = pair.split("=", 1)
        key, raw = key.strip(), raw.strip()
        if key not in CONFIG_FIELDS:
            print(f"ERROR: 认不出的字段 `{key}`；只认 {' / '.join(CONFIG_FIELDS)}：")
            for k in CONFIG_FIELDS:
                print(f"       {k}：{CONFIG_FIELD_HELP[k]}")
            return [], 2
        if key == CFG_MODE:
            canon = MODE_ALIASES.get(raw.lower())
            if canon is None:
                print(f"ERROR: 认不出的精细度 `{raw}`；只认 full / session / digest / milestone"
                      f"（也认中文：{'、'.join(MODES[m][1] for m in MODES)}）")
                return [], 2
            out.append((key, canon))
        elif key in (CFG_CONTAINER, CFG_LESSONS):
            if not is_dir_name(raw):
                print(f"ERROR: `{key}` 必须是目录名（非空、不含 / 与 \\）：`{raw}`")
                return [], 2
            out.append((key, raw))
        elif key == CFG_LEGACY:
            out.append((key, [p.strip() for p in raw.split(",") if p.strip()]))
        else:
            try:
                n = int(raw)
            except ValueError:
                n = 0
            if n < 1:
                print(f"ERROR: `{CFG_SNAPSHOT_ENTRIES}` 必须是正整数：`{raw}`")
                return [], 2
            out.append((key, n))
    return out, 0


def _print_config_view(root: str, cfg: Config, container: str | None) -> None:
    """只读视图：逐字段打印生效值与来源。"""
    shown = rel(root, cfg.path) if cfg.path else CONFIG_NAME
    if container is None:
        state = "找不到容器：全部取内置默认"
    else:
        state = "存在" if cfg.exists else "不存在：全部取内置默认"
    print(f"# CONFIG  {shown}  （{state}）")
    width = max(len(k) for k in CONFIG_FIELDS)
    for key in CONFIG_FIELDS:
        print(f"{key:<{width}} = {_pad(cfg.value_text(key), 16)} ← {cfg.src[key]}")
    if cfg.src[CFG_LEGACY] == SRC_DEFAULT and not cfg.legacy_declared:
        print(f"{'':<{width}}   （没有显式清单时按规模兜底：记录 ≥ "
              f"{LEGACY_AUTO_MIN_RECORDS} 篇的容器整批算旧记录）")
    notes = list(cfg.problems) + list(cfg.notes)
    if notes:
        print("\n提示：")
        for n in notes:
            print(f"! {n}")
    if container is None:
        print("\n提示：找不到记录容器，全部按内置默认；`--write` / `--set` 需要先有容器。")
    print("\n（`config --write` 按当前生效值写出配置文件；`config --set key=value` 改一项。）")


def cmd_config(args: argparse.Namespace) -> int:
    """项目配置文件：查看生效值与来源 / 写出 / 改一项。

    这个命令存在的理由只有一个：**让解析看得见**。同一个值可能来自命令行、配置文件或
    内置默认，光看行为分不出来——改了命令行参数却没生效，很可能是因为配置文件把它定死了。
    """
    root = os.path.abspath(args.root)
    container, _lessons, cfg = load_project_config(root, args.journal, args.lessons, args.legacy)

    if args.set:
        pairs, rc = parse_config_sets(args.set)
        if rc:
            return rc
        if container is None:
            print("ERROR: 找不到记录容器（work_log/；旧名 journal/、work-log/ 也认）——"
                  "配置文件住在容器里，先按 templates.md 建容器")
            return 1
        if not cfg.exists:
            print(f"ERROR: {rel(root, cfg.path)} 还不存在；先跑 `config --write` 建它，再 `--set`")
            return 1
        text = read_raw(cfg.path)
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            print(f"ERROR: {rel(root, cfg.path)} 读不出来（不是合法 JSON 对象）；"
                  f"先修好它，或者删掉它重新 `config --write`。")
            return 2
        nl = nl_of(text)
        trailing = text.endswith(("\n", "\r"))
        for key, value in pairs:
            data[key] = value
        if args.dry_run:
            print("[dry-run] 将写入：" + "、".join(f"{k}={v}" for k, v in pairs))
            return 0
        # 首选"只改那一行"：其余字节（含 CRLF、缩进、排版）原样保留。
        # 改不动（键不在一行行首、值跨多行且对不上）才整体重排——重排仍保留换行风格与其余字段。
        new_text = text
        for key, value in pairs:
            edited = _set_field_surgical(new_text, key, value)
            new_text = edited if edited is not None else _dump_config_text(data, nl, trailing)
        write_raw(cfg.path, new_text)
        print(f"config 已更新：{rel(root, cfg.path)}：" + "、".join(f"{k}={v}" for k, v in pairs))
        _after = load_project_config(root, args.journal, args.lessons, args.legacy)[2]
        for n in _after.problems:
            print(f"WARN: {n}")
        for n in _after.notes:
            print(f"! {n}")
        return 0

    if args.write:
        if container is None:
            print("ERROR: 找不到记录容器（work_log/；旧名 journal/、work-log/ 也认）——"
                  "配置文件住在容器里，先按 templates.md 建容器")
            return 1
        if cfg.exists and not args.force:
            print(f"ERROR: {rel(root, cfg.path)} 已存在；要覆盖就加 `--force`")
            print("       改一个字段用 `config --set key=value`（会保留其余字段）。")
            return 1
        text = read_raw(cfg.path) if cfg.exists else ""
        nl = nl_of(text) if text else "\n"
        body = _dump_config_text(cfg.as_data(), nl, True)
        if args.dry_run:
            print(f"[dry-run] 将写入 {rel(root, cfg.path)}：")
            print(body.rstrip("\r\n"))
            return 0
        write_raw(cfg.path, body)
        print(f"config 已写出：{rel(root, cfg.path)}")
        return 0

    # 只读视图：`--show` 与"什么标志都不给"是同一个行为。
    _print_config_view(root, cfg, container)
    return 2 if cfg.problems else 0


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
    root_arg, key = _root_and_num(args.paths)
    root = os.path.abspath(root_arg)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    rec = _find_record(journal, key) if journal else None
    if rec is None:
        print(f"ERROR: 找不到记录 #{key}")
        return 1
    path = rec["path"]
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
    recs = find_records(journal, lessons_skip(lessons)) if journal else []
    if not recs:
        print("没有记录")
        return 0
    # **按路径**做键，不能按 rid：日期式容器里同一天有多篇（实测一天 18 篇），
    # 按身份做键会让它们互相覆盖，合规率因此算少一大截。
    metas = {r["path"]: meta_of(r["path"]) for r in recs}
    active = [r for r in recs if is_active_entry(journal, r["path"])]
    dates = [max_date_in(read(r["path"])) for r in recs]
    dates = [d for d in dates if d]
    total_bytes = sum(m["bytes"] for m in metas.values())
    total_lines = sum(m["lines"] for m in metas.values())
    biggest = max(recs, key=lambda r: metas[r["path"]]["bytes"])
    # 两种命名各自算一下，混用的容器一眼看得出来。
    n_num = sum(1 for r in recs if r["kind"] == "num")
    n_date = len(recs) - n_num
    span = (f"{display_of(recs[0])}–{display_of(recs[-1])}")
    print(f"entries     : {len(recs)}  ({span}; active {len(active)} / archive {len(recs) - len(active)})")
    print(f"naming      : 编号式 {n_num} 篇 / 日期式 {n_date} 篇")
    if dates:
        span_days = (max(dates) - min(dates)).days + 1
        print(f"date span   : {min(dates)} .. {max(dates)}  ({span_days} days, {len(dates)} dated)")
        buckets: dict[str, int] = {}
        for d in dates:
            wk = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
            buckets[wk] = buckets.get(wk, 0) + 1
        print("per week    : " + "  ".join(f"{k}:{v}" for k, v in sorted(buckets.items())))
    print(f"compliance  : 日期 {sum(1 for m in metas.values() if m['has_date'])}/{len(recs)}"
          f"   验证 {sum(1 for m in metas.values() if m['has_verify'])}/{len(recs)}")
    print(f"size        : {total_lines} lines / {total_bytes / 1024:.0f} KB"
          f"   avg {total_lines // len(recs)} lines   largest {display_of(biggest)}"
          f" ({metas[biggest['path']]['bytes'] / 1024:.0f} KB)")
    iters = [m["iter"] for m in metas.values() if m["iter"] and m["iter"] != "-"]
    print(f"迭代字段    : {len(iters)}/{len(recs)} 有值（`变更集` 只是它的一个别名，可选）")
    if lessons:
        cites: dict[int, int] = {}
        for f in sorted(os.listdir(lessons)):
            if f.endswith(".md") and f != "README.md":
                for c in CITE_RE.findall(read(os.path.join(lessons, f))):
                    cites[int(c)] = cites.get(int(c), 0) + 1
        print(f"lessons     : {len([f for f in os.listdir(lessons) if f.endswith('.md') and f != 'README.md'])} volumes,"              f" {sum(cites.values())} citations → {len(cites)} sources")
        top = sorted(cites.items(), key=lambda kv: -kv[1])[:8]
        print("top cited   : " + "  ".join(f"#{n}({c})" for n, c in top))
    return 0


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{3,}")


def cmd_topics(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    recs = find_records(journal, lessons_skip(lessons)) if journal else []
    if args.keywords:
        kws = [k.strip() for k in args.keywords.split(",") if k.strip()]
        for kw in kws:
            hit = [r for r in recs if kw.lower() in read(r["path"]).lower()]
            print(f"{kw}: " + (", ".join(entry_label(r) for r in hit) if hit else "(no hit)"))
        return 0
    df: dict[str, set[str]] = {}
    for rec in recs:
        for tok in set(TOKEN_RE.findall(read(rec["path"]))):
            t = tok.lower()
            if t in STOPWORDS or len(t) < 4:
                continue
            df.setdefault(t, set()).add(rec["rid"])
    cand = [(t, ns) for t, ns in df.items() if 2 <= len(ns) <= args.max_df]
    cand.sort(key=lambda kv: (-len(kv[1]), kv[0]))
    by_rid = {r["rid"]: r for r in recs}
    print(f"同主题簇建议（出现 2–{args.max_df} 篇的标识符；用 `--keywords` 可查中文词）\n")
    for t, ns in cand[: args.limit]:
        shown = sorted(ns)
        print(f"{t:28s} {len(shown):2d} 篇  "
              + ", ".join(entry_label(by_rid[r]) for r in shown[:10])
              + (" …" if len(shown) > 10 else ""))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    root = os.path.abspath(args.root)
    journal, lessons = resolve_layout(root, args.journal, args.lessons)
    recs = find_records(journal, lessons_skip(lessons)) if journal else []
    rows = []
    for rec in recs:
        m = meta_of(rec["path"])
        # `id` 是统一身份（编号式 `0007` / 日期式 `2026-09-06`），`num` 只在编号式有值。
        rows.append({"id": display_of(rec), "num": rec["num"], "style": rec["kind"],
                     "path": rel(root, rec["path"]),
                     **{k: m[k] for k in
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
    recs = find_records(journal, lessons_skip(lessons)) if journal else []
    lines = [f"# 交接摘要（生成于 {today()}）", ""]
    sb = status_block_text(journal) if journal else ""
    lines += ["## " + K_STATUS, "", sb or "(台账里没有状态块)", ""]
    open_items, _ = todo_items(journal) if journal else ([], [])
    lines += ["## " + K_TODO, ""] + (open_items or ["(无未完成项)"]) + [""]
    lines += [f"## 近期记录（最近 {args.entries} 篇）", "",
              "| 身份 | 日期 | 迭代 | 标题 |", "|---|---|---|---|"]
    for rec in list(reversed(recs))[: args.entries]:
        m = meta_of(rec["path"])
        lines.append(f"| {display_of(rec)} | {m['date'] or '-'} | {m['iter'] or '-'} | {m['title']} |")
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
    # 区间按篇号给：编号式照旧，日期式整篇收进来（它没有篇号，只能按日期排）。
    recs = find_records(journal, lessons_skip(lessons)) if journal else []
    picked = [r for r in recs
              if r["kind"] == "num" and args.from_num <= (r["num"] or 0) <= args.to_num]
    if not picked:
        # 日期式容器：区间给不出篇号，退回「按日期区间」——`--from` 传年份或日期前缀。
        lo, hi = str(args.from_num), str(args.to_num)
        dated = [r for r in recs if r["kind"] == "date"
                 and lo <= r["date"].replace("-", "")[:len(lo)] <= hi]
        picked = dated
    if not picked:
        print("ERROR: 区间内没有记录")
        return 1
    stage = args.stage or "阶段"

    def link_for(path: str) -> str:
        base = lessons if lessons else journal
        return os.path.relpath(path, base).replace(os.sep, "/")

    out = [f"# 99 · 阶段复盘", "", f"## 一、阶段表（{stage}）", "",
           "| 迭代 | 日期 | 记录 | 产出 |", "|---|---|---|---|"]
    for rec in picked:
        m = meta_of(rec["path"])
        out.append(f"| {m['iter'] or '-'} | {m['date'] or '-'} | "
                   f"[{entry_label(rec)}]({link_for(rec['path'])}) | {m['title']} |")
    out += ["", "## 二、核心成果", "", "## 三、最有价值的可复用发现", ""]
    out += ["## 四、遗留事项", ""]
    leaves = 0
    for rec in picked:
        text = read(rec["path"])
        for line in text.splitlines():
            if re.match(r"^\s*-\s*\[ \]", line):
                # 固定切 5 个字符会在 `-  [ ] x`（多一个空格）或裸 `- [ ]` 上切错，
                # 用正则把复选框前缀整段吃掉。
                item = re.sub(r"^\s*-\s*\[ \]\s*", "", line).strip()
                out.append(f"- {item}（`{entry_label(rec).lstrip('#')}`）")
                leaves += 1
    if not leaves:
        out.append("- （区间内记录没有未完成项）")
    out.append("")
    body = "\n".join(out)
    if args.out:
        write_raw(os.path.abspath(args.out), body)
        print(f"wrote {args.out} ({len(picked)} entries, {leaves} open items)")
    else:
        print(body)
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--work-log", dest="work_log", default=None,
                   help="工作记录容器目录名；默认按目录回退发现 work_log/ → journal/ → work-log/"
                        "（配置文件里的 container 字段改不了这里，它管不了自己所在的目录）")
    p.add_argument("--journal", default=None,
                   help="已弃用：--work-log 的旧名，等价（现在它命名的是**容器**）")
    p.add_argument("--lessons", default=None,
                   help="容器内的经验目录名，默认 lessons/（也认配置文件里的 lessons；"
                        "目录实际存在才作数，顺序：命令行 → 配置 → <容器>/lessons/ → <根>/lessons/）")


def _add_legacy(p: argparse.ArgumentParser) -> None:
    p.add_argument("--legacy", default=None, metavar="GLOB[,GLOB…]",
                   help="旧记录清单（逗号分隔的 glob / 文件名 / 相对路径）；命中的记录只报 info。"
                        "不给则读 `.config.json` 的 legacy，再读容器根的 LEGACY.md，"
                        "再不给默认按规模兜底（记录 ≥ 5 篇整批算旧记录）。"
                        "传空串 `--legacy \"\"` 表示没有旧记录（全部按新格式判）")


def _add_root(p: argparse.ArgumentParser) -> None:
    p.add_argument("root", nargs="?", default=".", help="项目根，默认当前目录")


def _root_and_num(paths: list[str]) -> tuple[str, str]:
    """支持 `show 42` 与 `show <root> 42` 两种写法。

    返回的第二个值**保持字符串**：编号式给篇号（`42`），日期式给日期或文件名
    （`2026-09-06` / `2026-09-06-门控两段式.md`）——两种身份都由 `_find_record` 解析。
    """
    if len(paths) == 1:
        root, key = ".", paths[0]
    elif len(paths) == 2:
        root, key = paths[0], paths[1]
    else:
        raise SystemExit("用法：[ROOT] KEY（例如 `show 42` 或 `show 2026-09-06` 或 `show ./proj 42`）")
    return root, key


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="journal.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="项目长期工作记录工具箱：少读（brief/show/search）、少写（status/mode/todo/index/append/lesson）、可校验（check/lint）。",
        epilog="约定见 skill 的 references/conventions.md；完整命令说明见 references/commands.md。",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name: str, func, help_text: str, root: bool = True, epilog: str | None = None):
        kw = {"epilog": epilog, "formatter_class": argparse.RawDescriptionHelpFormatter} if epilog else {}
        p = sub.add_parser(name, help=help_text, **kw)
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

    p = add("check", lambda a: _run(Report(a.strict),
                                    lambda: check(os.path.abspath(a.root), a.journal, a.lessons,
                                                  a.strict, a.legacy), a), "结构门禁")
    p.add_argument("--strict", action="store_true", help="把 WARN 当 ERROR")
    _add_legacy(p)
    p.add_argument("--quiet", action="store_true")

    p = add("lint", lambda a: _run(Report(a.strict),
                                   lambda: lint(os.path.abspath(a.root), a.journal, a.lessons,
                                                a.strict, a.legacy), a), "内容质量门禁")
    p.add_argument("--strict", action="store_true")
    _add_legacy(p)
    p.add_argument("--quiet", action="store_true")

    p = add("brief", cmd_brief, "压缩上下文快照")
    p.add_argument("--entries", type=int, default=8, help="近期记录条数（默认 8）")
    p.add_argument("--max-status-lines", type=int, default=30)
    p.add_argument("--max-todo", type=int, default=10)
    p.add_argument("--width", type=int, default=200, help="每行截断宽度（默认 200 字符）")

    p = add("snapshot", cmd_snapshot, "最近 N 篇的入口元信息汇总（只读）")
    p.add_argument("--entries", type=int, default=None,
                   help=f"汇总最近多少篇（默认取配置文件的 snapshotEntries，"
                        f"再不给是内置默认 {SNAPSHOT_ENTRIES_DEFAULT}）")
    p.add_argument("--width", type=int, default=200, help="每行截断宽度（默认 200 字符）")
    p.add_argument("--out", default=None, help="写到文件（不给就只打印；容器本身永不改动）")

    p = add("outline", cmd_outline, "全部记录一行表")

    p = add("show", cmd_show, "单篇记录大纲", root=False)
    p.add_argument("paths", nargs="+", metavar="[ROOT] KEY",
                   help="KEY 是篇号（`42`）或日期 / 文件名（`2026-09-06`）")

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
    p.add_argument("--from", dest="from_num", type=int, required=True, help="起始篇号（编号式）/ 起始日期前缀（日期式，如 20260901）")
    p.add_argument("--to", dest="to_num", type=int, required=True, help="结束篇号（编号式）/ 结束日期前缀（日期式）")
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

    p = add("config", cmd_config,
            "项目配置文件（<容器>/.config.json）：查看生效值与来源 / 写出 / 改一项",
            epilog="""\
优先级只有三层，不重叠：
    命令行参数  >  <容器>/.config.json  >  内置默认
缺这个文件**不是错误**，它等于「全部取内置默认」。

两个名字字段（container / lessons）与其他字段不一样，要单独理解：
它们命名的正是配置文件**自己所在的目录**，所以读配置文件之前就得先知道它们——
只能按目录发现。于是配置文件里的值只是「新项目该叫什么」的备注，
**写进去不代表这次生效**：目录实际存在才作数，不一致时以实际目录为准并报出来。
这也正是插件在项目初始化时把这两个名字写进配置文件的原因。

mode 同样只提供**新项目的初始档位**：台账 `## 当前状态` 有 `精细度` 字段时，
一切以台账为准（`mode` 命令读写的一直是台账那一栏）。

例：
    python scripts/journal.py config                     # 看生效值与来源
    python scripts/journal.py config --write             # 按当前生效值写出配置文件
    python scripts/journal.py config --set mode=digest   # 只改一个字段（保留其余）
    python scripts/journal.py config --set legacy=0007-*,archive/**
""")
    p.add_argument("--show", action="store_true", help="只读视图（默认行为）")
    p.add_argument("--write", action="store_true",
                   help="按当前生效值写出配置文件；已存在时拒绝覆盖（除非 --force）")
    p.add_argument("--force", action="store_true", help="配合 --write：覆盖已存在的文件")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help=f"就地改一个字段（可重复）；字段只认 {' / '.join(CONFIG_FIELDS)}")
    _add_legacy(p)
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
    p.add_argument("paths", nargs="+", metavar="[ROOT] KEY",
                   help="KEY 是篇号（`42`）或日期 / 文件名（`2026-09-06`）")
    p.add_argument("--section", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--bullet", action="store_true", help="每行自动加 `- ` 前缀")
    p.add_argument("--dry-run", action="store_true")

    return ap


def _run(rep: Report, fn, args: argparse.Namespace) -> int:
    rep = fn()
    n = rep.prune_legacy()
    rep.print(getattr(args, "quiet", False))
    if n and not getattr(args, "quiet", False):
        # 明说降级了几条，免得用户以为「旧记录的问题消失了」。
        print(f"（其中 {n} 条按渐进原则降为 info：命中的是旧记录，见 commands.md「渐进原则」）")
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
