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
// The document list below is **the whole of `docs/` plus the three root documents**.
// It used to name only `docs/worklog-spec.md`, which left three design specs —
// including the memory spec — outside every gate. That is exactly the shape of
// failure this repository keeps meeting: an authority nobody checks drifts from the
// code, and the drift is found by a human reading carefully rather than by a test.
//
//   node tests/audit-doc-consistency.mjs
import { readFileSync } from 'node:fs'
import { PKG } from './_pkg.mjs'

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}

const ENTRY = `${PKG}/lib/index.js`
const src = readFileSync(ENTRY, 'utf8')

// What counts as "the documentation": every file under `docs/` plus the three root
// documents. `SETTINGS.md` is the plugin-settings reference added alongside the settings
// page; the `docs/*-spec.md` files are the design authorities, and a design authority that
// no gate reads is a design authority that drifts.
//
const DOCS = [
  `${PKG}/README.md`,
  `${PKG}/PUBLISHING.md`,
  `${PKG}/SETTINGS.md`,
  `${PKG}/docs/worklog-spec.md`,
  `${PKG}/docs/settings-spec.md`,
  `${PKG}/docs/memory-spec.md`,
  `${PKG}/docs/goals-spec.md`,
]
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
const docText = DOCS.map((file) => {
  try { return readFileSync(file, 'utf8') } catch { return '' }
}).join('\n')

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

console.log(problems.length === 0 ? '\ndoc/identifier consistency OK' : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
