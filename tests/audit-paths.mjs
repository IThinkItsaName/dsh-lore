// Path-consistency check for the skill docs, plus the script-free variant.
//
// The two skills ship in one bundle and reference each other's paths, so a rename
// can leave one pointing at a directory that no longer exists. That happened once
// (the container moved to work_log/ while the guidelines still said journal/) and
// nothing caught it. This check pins it.
//
// The second half audits `skill-only/project-work-log/` — the script-free variant.
// That variant's whole promise is that it carries the METHODOLOGY without the
// toolbox, so what needs pinning is the inverse of the usual check: it must not
// name a script, and it must not silently lose the concepts. It also has to agree
// with the main skill about the container name, for the same reason the guidelines
// do, and `dist/` has to be the rebuild of the source, not a stale copy.
//
//   node tests/audit-paths.mjs
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import { PKG } from './_pkg.mjs'

const SKILL = `${PKG}/skills/project-work-log`
const GUIDELINES = `${PKG}/skills/reliability-guidelines`
const ONLY_SRC = `${PKG}/skill-only/project-work-log`
const ONLY_DIST = `${PKG}/dist/skill-only/project-work-log`

/** Normalise line endings before any byte-level comparison. */
const lf = (text) => text.replace(/\r\n?/g, '\n')

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else out.push(p)
  }
  return out
}

const files = walk(SKILL).filter((f) => /\.(md|py)$/.test(f))
ok(files.length > 5, 'found the skill files to audit', `${files.length} files`)

/*
 * Old-layout paths may legitimately appear, but only as history: in a section that
 * describes back-compat, or on a line that says so itself. Anywhere else they mean
 * a rename was missed. Section context is what decides, because a table row such
 * as `journal/archive/COLD-STORE.md` carries no marker of its own.
 */
const LEGACY_SECTION = /旧|回退|兼容|迁移|back-?compat|legacy|基线|baseline/i
const LEGACY_LINE = /旧|回退|兼容|迁移|不迁移|沿用|保留|baseline|基线|过去|当时|原本/
const STALE = [
  [/journal\/README\.md/, 'journal/README.md'],
  [/journal\/archive\//, 'journal/archive/'],
  [/journal\/NNNN/, 'journal/NNNN'],
  [/journal\/STATUS-HISTORY/, 'journal/STATUS-HISTORY'],
]

for (const file of files) {
  const rel = file.slice(PKG.length + 1)
  const lines = readFileSync(file, 'utf8').split('\n')
  let heading = ''
  lines.forEach((line, i) => {
    if (/^#{1,6}\s/.test(line)) heading = line
    for (const [re, label] of STALE) {
      if (!re.test(line)) continue
      if (LEGACY_LINE.test(line)) continue
      if (LEGACY_SECTION.test(heading)) continue
      ok(false, `${rel}:${i + 1} describes the old layout outside a back-compat section`,
         `${label} :: ${line.trim().slice(0, 70)} (section: ${heading.trim().slice(0, 40)})`)
    }
  })
}
ok(problems.length === 0, 'no stale old-layout references outside back-compat text')

/* The new layout must actually be present where it matters. */
const skillText = readFileSync(`${SKILL}/SKILL.md`, 'utf8')
const declared = /一个容器目录\*\*\s*`([^`]+)`/.exec(skillText)?.[1]
ok(declared === 'work_log/', 'the worklog skill declares work_log/ as the container', String(declared))

for (const [label, file] of [['zh', `${GUIDELINES}/SKILL.md`], ['en', `${GUIDELINES}/en/SKILL.md`]]) {
  const text = readFileSync(file, 'utf8')
  ok(text.includes(`\`${declared}\``),
     `guidelines (${label}) reference the same container the worklog skill declares`)
}

/* ======================================================================
 * The script-free variant (`skill-only/`).
 *
 * This variant deliberately drops the toolbox. Two things therefore need
 * pinning that the checks above do not cover:
 *   1. it must not mention a script or CLI syntax anywhere (one optional
 *      mention of the Python toolbox is allowed, at most once), and
 *   2. it must not lose the methodology in the process.
 * Plus the usual consistency rule: it has to agree with the main skill about
 * the container, and `dist/` has to be the rebuild of the source.
 * ==================================================================== */

/** Exactly these three files; the variant ships nothing else. */
const ONLY_FILES = ['SKILL.md', 'references/conventions.md', 'references/templates.md']

ok(existsSync(ONLY_SRC), 'the script-free variant source tree exists', relative(PKG, ONLY_SRC))

let onlyFound = []
if (existsSync(ONLY_SRC)) {
  onlyFound = walk(ONLY_SRC).map((f) => relative(ONLY_SRC, f).split(sep).join('/')).sort()
  const expected = [...ONLY_FILES].sort()
  ok(onlyFound.join('|') === expected.join('|'),
     'the script-free variant holds exactly the three expected files',
     onlyFound.join(', '))
}

/*
 * Script- and CLI-free text. Each pattern is reported separately so a failure
 * says which rule broke, not just that something did.
 *
 * The `--flag` pattern needs both the dashes and a following letter: an em-dash
 * run (`——`, which Chinese prose uses) and a table rule (`|---|---|`) must not
 * trip it. Case-sensitive on purpose — `npm install` and `NPM` are different
 * strings and only the lowercase tool actually gets typed.
 */
const ONLY_FORBIDDEN = [
  [/journal\.py/, 'journal.py'],
  [/_selftest/, '_selftest'],
  [/_measure/, '_measure'],
  [/_package/, '_package'],
  [/scripts\//, 'scripts/'],
  [/python /, 'python (with a trailing space)'],
  [/npm /, 'npm (with a trailing space)'],
  [/--[A-Za-z]/, 'a --flag CLI form'],
]

/** The one sanctioned exception: a single, clearly optional pointer to the toolbox. */
const ONLY_MENTION = /若环境里有 Python，可用配套的 `journal\.py` 工具箱/

let onlyText = new Map()
if (existsSync(ONLY_SRC)) {
  onlyText = new Map(onlyFound.map((rel) => [rel, lf(readFileSync(join(ONLY_SRC, rel), 'utf8'))]))
}

let onlyMentions = 0
for (const [rel, text] of onlyText) {
  for (const [re, label] of ONLY_FORBIDDEN) {
    for (const [i, line] of text.split('\n').entries()) {
      if (!re.test(line)) continue
      if (ONLY_MENTION.test(line)) { onlyMentions += 1; continue }
      ok(false, `${rel}:${i + 1} names a script or CLI form the variant must not carry`,
         `${label} :: ${line.trim().slice(0, 70)}`)
    }
  }
}
ok(problems.length === 0, 'the script-free variant names no script, package manager, or CLI flag')
ok(onlyMentions <= 1, 'the optional Python-toolbox mention appears at most once', `found ${onlyMentions}`)

/* ---- the methodology must survive the surgery -------------------------- */

const onlySkill = onlyText.get('SKILL.md') ?? ''
const onlyConventions = onlyText.get('references/conventions.md') ?? ''
const onlyAll = [...onlyText.values()].join('\n')

ok(onlyAll.includes('work_log/'), 'the script-free variant keeps the work_log/ container')
ok(onlyAll.includes('精细度'), 'the script-free variant keeps the 精细度 field')

/*
 * The DEFAULT TIER, not merely the word "session".
 *
 * The previous assertion here was `onlyAll.includes('session')`, which was weak and
 * went stale: the tier table legitimately names all four tiers, so that substring is
 * present no matter which one is the default — and when the default was corrected from
 * `session` back to `full` after measuring the real corpora, the assertion happily kept
 * passing while testing nothing. Match the declaration itself, and cross-check it against
 * the running code so doc and behaviour cannot drift apart again.
 */
const declaredDefault = /\*\*`(\w+)`（默认）\*\*/.exec(onlyConventions)?.[1]
ok(declaredDefault !== undefined,
   'the script-free variant declares which tier is the default',
   declaredDefault ?? 'no `**`tier`（默认）**` marker found in references/conventions.md')

const codeDefault = /^MODE_DEFAULT\s*=\s*["'](\w+)["']/m.exec(
  readFileSync(`${PKG}/skills/project-work-log/scripts/journal.py`, 'utf8'),
)?.[1]
ok(codeDefault !== undefined, 'read MODE_DEFAULT from journal.py', String(codeDefault))
ok(declaredDefault === codeDefault,
   `the script-free variant's default tier matches the code (${codeDefault})`,
   `docs say ${declaredDefault}, code says ${codeDefault}`)

ok(/验证|复核|检查|评审|结果|证据|评估|确认|实测|审查/.test(onlyAll),
   'the script-free variant still requires a verification section')

/* ---- it must be honest about what it is -------------------------------- */

ok(onlySkill.includes('没有机械门禁'),
   'the script-free variant states plainly that there is no mechanical gate')
ok(onlySkill.includes('验证靠人工复核'),
   'the script-free variant states that verification is by human review')

/* ---- it must declare the SAME container the main skill declares --------- */

/*
 * Phrased the other way round from the main skill, so this is not a copy of the
 * same regex: the container name precedes the marker here. Accepting either
 * order is fine — what matters is the value it names.
 */
const onlyDeclared = /`([^`]+)`（默认名，可改名）/.exec(onlySkill)?.[1]
  ?? /一个容器目录\*\*\s*`([^`]+)`/.exec(onlySkill)?.[1]
ok(onlyDeclared === declared,
   'the script-free variant declares the same container as the main skill',
   `${onlyDeclared} vs ${declared}`)

/* ---- dist/ must be the rebuild of the source --------------------------- */

ok(existsSync(ONLY_DIST), 'the built copy exists (dist/skill-only/)', relative(PKG, ONLY_DIST))

if (existsSync(ONLY_DIST)) {
  const distFound = walk(ONLY_DIST).map((f) => relative(ONLY_DIST, f).split(sep).join('/')).sort()
  const expected = [...ONLY_FILES].sort()
  ok(distFound.join('|') === expected.join('|'),
     'the built copy holds exactly the three expected files', distFound.join(', '))
  for (const rel of ONLY_FILES) {
    const srcPath = join(ONLY_SRC, rel)
    const distPath = join(ONLY_DIST, rel)
    if (!existsSync(distPath)) {
      ok(false, `the built copy holds ${rel}`)
      continue
    }
    ok(lf(readFileSync(distPath, 'utf8')) === lf(readFileSync(srcPath, 'utf8')),
       `dist/skill-only/ matches the source for ${rel} (line endings normalised)`)
  }
}

console.log(problems.length === 0 ? '\npath consistency OK' : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
