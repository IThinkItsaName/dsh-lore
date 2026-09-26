// Path-consistency check for the skill docs.
//
// The two skills ship in one bundle and reference each other's paths, so a rename
// can leave one pointing at a directory that no longer exists. That happened once
// (the container moved to work_log/ while the guidelines still said journal/) and
// nothing caught it. This check pins it.
//
//   node tests/audit-paths.mjs
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { PKG } from './_pkg.mjs'

const SKILL = `${PKG}/skills/project-work-log`
const GUIDELINES = `${PKG}/skills/reliability-guidelines`

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

console.log(problems.length === 0 ? '\npath consistency OK' : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
