// Documentation consistency for the plugin entry.
//
// Motivated by a real defect: `lib/index.js` carried two contradictory design
// notes at once — the module docstring said `register` was deliberate and that a
// provider would have to re-implement parsing, while the code registered a
// provider and two other comments said the opposite. Nothing caught it, because
// no test can read a comment.
//
// This checks only the part that is mechanically decidable and will not
// false-positive: every identifier the entry reads from its environment, and every
// config key it honours, must be documented. Both are concrete strings with one
// correct answer.
//
// Deliberately NOT attempted: asserting that every identifier named in a comment
// still exists. Measured false-positive rate was unusable — comments legitimately
// name things that must NOT exist here (`createRequire`, absent from an ESM entry),
// names from the registry it depends on (`waitWithAbort`), and plain language or
// keywords (`skill`, `runtime`, `undefined`, `async`). A check that noisy teaches
// people to ignore it.
//
// There are two document corpora, and they are audited against different authorities:
//
//   - the PLUGIN documents (`docs/` plus the three root documents) are the authority on
//     the plugin: the env vars it reads, the config keys it honours;
//   - the SKILL documents (`skills/project-work-log/SKILL.md` + `references/`) are the
//     authority on the toolbox: they are what a reader copies commands out of, so they
//     are audited against the CLI they describe (`scripts/journal.py`).
//
// Both corpora get the "listed document exists" check. The skill corpus used to be in
// neither list — five documents of paths and commands, drifting with no gate at all,
// which is the same shape of failure the plugin corpus was rescued from.
//
// Every check added for the skill corpus was measured against the current documents
// before it was kept, and all three came back at zero false positives:
//
//   - all 21 `journal.py <cmd>` invocations in the skill documents name a registered
//     subcommand (a rename such as `retro` → something else is what this catches);
//   - all 21 top-level subcommands are named in `references/commands.md`, so a command
//     added without documentation goes red here rather than unnoticed;
//   - every cross-document link resolves (the only non-resolving targets are template
//     placeholders such as `NNN-slug.md`, which are not in the sibling set and are
//     therefore skipped rather than reported).
//
// Deliberately NOT attempted for the skill corpus: checking the `--flags` the documents
// mention. Measured rate was three false positives on today's text — argparse's own
// `--help`, `_selftest.py`'s `--root`, and a user script's `--variant` used as an
// example — because a flag name is not enough to say which program it belongs to.
//
//   node tests/audit-doc-consistency.mjs
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { PKG } from './_pkg.mjs'

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}

const ENTRY = `${PKG}/lib/index.js`
const src = readFileSync(ENTRY, 'utf8')

// What counts as "the plugin documentation": every file under `docs/` plus the three root
// documents. `SETTINGS.md` is the plugin-settings reference added alongside the settings
// page; the `docs/*-spec.md` files are the design authorities, and a design authority that
// no gate reads is a design authority that drifts. `docs/why.md` is the goal authority
// (what the tool must guarantee) — added 2026-09-30 for the same reason.
//
const PLUGIN_DOCS = [
  `${PKG}/README.md`,
  `${PKG}/PUBLISHING.md`,
  `${PKG}/SETTINGS.md`,
  `${PKG}/docs/why.md`,
  `${PKG}/docs/worklog-spec.md`,
  `${PKG}/docs/settings-spec.md`,
  `${PKG}/docs/memory-spec.md`,
  `${PKG}/docs/goals-spec.md`,
  `${PKG}/docs/plugin-spec.md`,
]

// The skill corpus. `SKILL.md` is included next to the five `references/` files: it is the
// entry a reader meets first, it carries the same paths and commands, and it links into
// `references/` — auditing one without the other would leave the links unchecked.
const SKILL = `${PKG}/skills/project-work-log`
const SKILL_DOCS = [
  `${SKILL}/SKILL.md`,
  `${SKILL}/references/analysis.md`,
  `${SKILL}/references/commands.md`,
  `${SKILL}/references/conventions.md`,
  `${SKILL}/references/memory.md`,
  `${SKILL}/references/templates.md`,
]

const DOCS = [...PLUGIN_DOCS, ...SKILL_DOCS]

// Reading a listed document must never throw. A missing document is already reported by the
// loop below, and crashing on it would take the rest of the audit down with it: the first
// version of the skill checks read the files directly, so renaming one `references/` file
// produced a FAIL line followed by an ENOENT stack trace and never ran the remaining
// sections. Exit code 1 either way — but the audit surface had silently shrunk, which is the
// exact failure this file exists to prevent.
const readDoc = (file) => {
  try { return readFileSync(file, 'utf8') } catch { return '' }
}

// A listed document that has been renamed or deleted must be reported, not silently skipped:
// reading a missing file as `''` would quietly shrink the surface this audit covers, which is
// the very failure it exists to prevent.
for (const file of DOCS) {
  try {
    readFileSync(file, 'utf8')
  } catch {
    problems.push(`listed document exists: ${file}`)
    console.log(`FAIL  listed document exists -- ${file}`)
  }
}

// The identifier checks below read the plugin corpus only. Adding the skill documents to
// this text would not make those checks stronger — it would make them weaker, because a
// name that appears anywhere in five documents of examples would satisfy them by accident.
const docText = PLUGIN_DOCS.map(readDoc).join('\n')

/* ---- 1. every env var the entry reads must be documented ---- */
const envRead = [...new Set([...src.matchAll(/process\.env\.([A-Z0-9_]+)/g)].map((m) => m[1]))]
ok(envRead.length > 0, 'the entry reads at least one env var', envRead.join(', '))
for (const name of envRead) {
  ok(docText.includes(name), `env var ${name} is documented`)
}

/* ---- 2. every config key the entry honours must be documented ---- */
const knownBlock = /const KNOWN_CONFIG_KEYS = \[([\s\S]*?)\]/.exec(src)?.[1] ?? ''
const configKeys = [...knownBlock.matchAll(/'([A-Za-z][A-Za-z0-9]*)'/g)].map((m) => m[1])
ok(configKeys.length >= 5, 'parsed the config keys', configKeys.join(', '))
for (const key of configKeys) {
  ok(docText.includes(`\`${key}\``) || docText.includes(key),
     `config key ${key} appears in the docs`)
}

/* ---- 3. the config keys named in the row patch must be honoured ---- */
const patch = readFileSync(`${PKG}/cordis.patch.yml`, 'utf8')
for (const key of configKeys) {
  if (!patch.includes(`${key}:`)) continue
  ok(true, `patch config key ${key} is a known key`)
}
for (const [, key] of patch.matchAll(/^\s{8}([A-Za-z][A-Za-z0-9]*):/gm)) {
  ok(configKeys.includes(key), `patch sets only known config keys (${key})`)
}

/* ---- 4. the CLI the skill documents describe must really have those subcommands ---- */
//
// The two registration forms, both static: the top level goes through the local `add()`
// helper inside `build_parser()`, the nested levels call `add_parser` on their own
// subparsers. Parsing the source rather than shelling out to `--help` is deliberate: this
// harness is run from a sandbox that forbids spawning a captured child process, and a
// check that cannot run in the environment it is meant to protect is not a gate.
//
// If the registration style is ever refactored, the `>= 15` guard below fails rather than
// the name checks silently passing over an empty set.
const cli = readDoc(`${SKILL}/scripts/journal.py`)
const topLevel = [...new Set([...cli.matchAll(/\badd\(\s*"([a-z][a-z0-9-]*)"/g)].map((m) => m[1]))]
const nested = [...new Set([...cli.matchAll(/\.add_parser\(\s*"([a-z][a-z0-9-]*)"/g)].map((m) => m[1]))]
const subcommands = new Set([...topLevel, ...nested])
ok(topLevel.length >= 15, 'parsed the CLI subcommands', `${topLevel.length} top-level, ${nested.length} nested`)

// Only invocations written as `journal.py <cmd>` are read. A bare `` `brief` `` inside a
// table says nothing about which program it belongs to, and reading it as a command would
// be the same mistake the flag check was dropped for.
//
// One assertion per document, with the offending names in the failure line. Per-name
// assertions were tried first and produced 80-odd PASS lines for six documents — an audit
// whose output cannot be scanned is one whose failures get skimmed too.
for (const file of SKILL_DOCS) {
  const rel = file.slice(SKILL.length + 1)
  const body = readDoc(file)
  const named = [...new Set([...body.matchAll(/journal\.py\s+([A-Za-z][A-Za-z0-9_-]*)/g)].map((m) => m[1]))]
  const unknown = named.filter((name) => !subcommands.has(name))
  ok(unknown.length === 0, `${rel} names only real subcommands`,
     unknown.length === 0 ? `${named.length} named` : `not in the CLI: ${unknown.join(', ')}`)
}

/* ---- 5. every top-level command is documented in the command reference ---- */
//
// The direction that actually drifts: a command is added, the code works, and the document
// that lists "全部命令" quietly falls behind. Only the backticked form counts, so the
// command has to be named as a command rather than appearing as an ordinary word.
const commandsDoc = readDoc(`${SKILL}/references/commands.md`)
for (const name of [...topLevel].sort()) {
  ok(commandsDoc.includes(`\`${name}\``), `top-level command ${name} is documented in commands.md`)
}

/* ---- 6. a link between skill documents must resolve ---- */
//
// Only links whose target names one of the sibling documents are resolved. The documents
// are full of template examples — `NNN-slug.md`, `0001-示例.md`, `lessons/README.md` — which
// are placeholders for a user's project, not links into this skill. Restricting the check to
// the sibling set keeps it at zero false positives while still catching a rename that
// updates six files and forgets the seventh.
const siblings = new Set(SKILL_DOCS.map((file) => file.split('/').pop()))
for (const file of SKILL_DOCS) {
  const rel = file.slice(SKILL.length + 1)
  const body = readDoc(file)
  const links = [...body.matchAll(/\]\(([^)\s]+)\)/g)]
    .map((m) => m[1])
    .filter((target) => siblings.has(target.split('/').pop()))
  const dead = [...new Set(links.filter((target) => !existsSync(resolve(dirname(file), target))))]
  ok(dead.length === 0, `${rel} cross-references resolve`,
     dead.length === 0 ? `${links.length} sibling links` : `dead: ${dead.join(', ')}`)
}

console.log(problems.length === 0 ? '\ndoc/identifier consistency OK' : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
