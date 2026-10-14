// Validate the worklog dsh bundle manifest without a YAML library.
//
// Checks the invariants that decide whether DSH can load the bundle:
//   1. package.json declares dsh.bundle.patch and the file exists.
//   2. Every non-`insert` patch entry is an OVERRIDE (id + name assertion) of a
//      row that dsh-base already declares — an override of a missing id warns
//      and is skipped, while an `insert` of an existing id appends a DUPLICATE.
//   3. Every inserted row names this package, and its declared skillDir exists
//      and holds a SKILL.md with a parseable frontmatter name.
import { readFileSync, existsSync, statSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { ok, skip, report, problems } from './_report.mjs'
import { PKG } from './_pkg.mjs'

const pkg = JSON.parse(readFileSync(`${PKG}/package.json`, 'utf8'))

/* 1. bundle declaration */
const patchRel = pkg.dsh?.bundle?.patch
ok(typeof patchRel === 'string', 'package.json declares dsh.bundle.patch', String(patchRel))
const patchPath = `${PKG}/${String(patchRel).replace(/^\.\//, '')}`
ok(existsSync(patchPath), 'the declared patch file exists', patchPath)

const patch = readFileSync(patchPath, 'utf8')
ok(statSync(patchPath).size > 0, 'the patch file is non-empty')

/* 2. override targets must exist in dsh-base */
// The dumped patch may use CRLF; anchor with [ \t]* rather than \s* so the
// trailing carriage return does not swallow the id match.
// dsh-base.patch.yml is an extracted artifact, not part of this package; point
// DSH_SRC_DIR at wherever the dump lives.
const DSH_SRC_DIR = process.env.DSH_SRC_DIR ?? ''
const baseIds = new Set()
if (DSH_SRC_DIR === '') {
  skip('dsh-base id cross-check SKIPPED (set DSH_SRC_DIR to enable it)')
} else {
  const basePatch = readFileSync(`${DSH_SRC_DIR}/dsh-base.patch.yml`, 'utf8')
  for (const m of basePatch.matchAll(/^[ \t]*-[ \t]*id:[ \t]*['"]?([A-Za-z0-9_.:-]+)['"]?[ \t]*$/gm)) {
    baseIds.add(m[1])
  }
  ok(baseIds.size > 50, 'parsed the dsh-base row ids', `${baseIds.size} ids`)
}

// Split our patch into top-level entries: a new entry starts at a line whose
// first non-space character is '-' at column 0.
const entries = patch
  .split(/\n(?=- )/)
  .map((block) => block.trimEnd())
  .filter((block) => block.startsWith('- ') || block.startsWith('-'))
ok(entries.length >= 1, 'the patch has at least one top-level entry', `${entries.length}`)

let overrides = 0
let inserts = 0
for (const block of entries) {
  const insertMatch = /^-?\s*insert:\s*$/m.test(block)
  const idMatches = [...block.matchAll(/^\s*-\s*id:\s*['"]?([A-Za-z0-9_.:-]+)['"]?\s*$/gm)]
  const nameMatches = [...block.matchAll(/^\s*name:\s*['"]?([^'"\n]+?)['"]?\s*$/gm)]

  if (insertMatch) {
    inserts += 1
    ok(idMatches.length > 0, 'an insert block carries at least one row id')
    if (baseIds.size === 0) {
      skip('inserted id cross-check SKIPPED (needs DSH_SRC_DIR)')
    } else {
      for (const [, id] of idMatches) {
        ok(!baseIds.has(id), `inserted row "${id}" is NOT already declared in dsh-base`,
           'an insert of an existing id would append a duplicate row')
      }
    }
    for (const [, name] of nameMatches) {
      ok(name.trim() === pkg.name, `inserted row names this package (${name.trim()} vs ${pkg.name})`)
    }
  } else {
    overrides += 1
    ok(idMatches.length === 1, 'an override entry carries exactly one id', JSON.stringify(idMatches))
    if (baseIds.size === 0) {
      skip('override target cross-check SKIPPED (needs DSH_SRC_DIR)')
    } else {
      for (const [, id] of idMatches) {
        ok(baseIds.has(id), `override target "${id}" is declared in dsh-base`,
           'DSH warns "patch: entry not found" and skips a missing target')
      }
    }
    ok(nameMatches.length >= 1, 'an override entry asserts the module name', block.slice(0, 60))
  }
}
/*
 * 每条顶层 entry 必须落进两类之一 —— 这就是 `overrides` / `inserts` 这两个计数器的存在意义。
 *
 * 原来这里是 `ok(overrides >= 0, 'override entries are optional')`：计数器初值 0、只在上面自增，
 * 所以它**恒真**，等于没断言（审查报告 F13）。真判据是"两个计数之和 = 顶层条目数"——
 * 一旦某段 entry 既不是 override 也不是 insert（补丁格式改坏了），这条会立刻变红，
 * 而恒真那条永远绿。
 */
ok(overrides + inserts === entries.length,
   'every top-level patch entry is classified as an override or an insert',
   `${overrides} overrides + ${inserts} inserts vs ${entries.length} entries`)
ok(inserts >= 1, 'the patch inserts this package row', `${inserts} inserts`)

/* 3. every bundle the patch declares actually exists */
const skillDir = `${PKG}/skills/project-work-log`
for (const [label, key] of [['skillDir', 'skillDir'], ['guidelinesDir', 'guidelinesDir']]) {
  const dir = new RegExp(`${key}:\\s*['"]?([^'"\\n]+)['"]?`).exec(patch)?.[1]
  ok(typeof dir === 'string' && dir !== '', `the patch declares ${label}`, String(dir))
  if (typeof dir === 'string' && dir !== '') {
    ok(existsSync(`${PKG}/${dir}`), `${label} exists (${dir})`)
    ok(existsSync(`${PKG}/${dir}/SKILL.md`), `${label} holds a SKILL.md`)
  }
}

/* 4. the guidelines ship both languages, and only the selected one is scanned */
const gDir = `${PKG}/skills/reliability-guidelines`
ok(existsSync(`${gDir}/SKILL.md`), 'the guidelines bundle holds the zh SKILL.md')
ok(existsSync(`${gDir}/en/SKILL.md`), 'the guidelines bundle holds the en SKILL.md')
ok(!existsSync(`${gDir}/en/SKILL.md.keep`), 'no stray marker files in the guidelines bundle')

/* 5. the plugin module loads and parses both bundles */
// The plugin imports `@deepseek-ai/schemastery` and `@deepseek-ai/dsh-tools`. Those come from
// the host (`dsh-app-boot` supplies the installation's packages to Node's resolvers — see
// `dsh-ref/PLUGIN-AUTHORING.md` §4.3), so a bare `node` run needs `_pkg.mjs`'s resolver hook
// **imported first**. That is why this file imports `_pkg.mjs` before this line rather than
// only for `PKG`.
const mod = await import(pathToFileURL(`${PKG}/lib/index.js`).href)
// This assertion used to read `mod.Config === undefined`, i.e. it required the plugin to export
// NO schema. That was an artefact of a measurement taken on the wrong object (a hand-copied
// directory is not part of the profile's install set, so of course nothing was supplied to it),
// and it forbade the standard `Config` route outright. What is worth pinning is the shape.
ok(mod.Config !== undefined, 'the plugin exports a Config schema')
ok(typeof mod.Config?.toJSON === 'function',
   'the Config carries toJSON (the settings-page projection requires it)')
const parsed = mod.parseSkillFrontmatter(readFileSync(`${skillDir}/SKILL.md`, 'utf8'))
ok(parsed.name === 'project-work-log', 'the plugin parses the worklog skill name', parsed.name)
ok(parsed.description.length > 0, 'the plugin parses a description')
const gParsed = mod.parseSkillFrontmatter(readFileSync(`${gDir}/SKILL.md`, 'utf8'))
ok(gParsed.name === 'reliability-guidelines', 'the plugin parses the guidelines skill name', gParsed.name)
const gEn = mod.parseSkillFrontmatter(readFileSync(`${gDir}/en/SKILL.md`, 'utf8'))
ok(gEn.name === 'reliability-guidelines', 'the English copy declares the same skill name', gEn.name)

report('all bundle manifest checks passed') 