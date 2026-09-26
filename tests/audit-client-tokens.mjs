// Design-token check for the client half.
//
// Why this exists: `var(--dsw-…)` does NOT fail when the token is misspelled. It
// silently falls back to whatever the second argument is, or to nothing, so the page
// still renders and still looks plausible — while every colour has quietly stopped
// following the theme. The first version of lib/client.js used four invented names
// (`--dsw-text-secondary`, `--dsw-border`, `--dsw-danger`, `--dsw-font-mono`); none
// exists in DSH, and nothing anywhere said so. It was found by reading the host's CSS,
// which is not a mechanism.
//
// The authority is the host's own stylesheets. `logs/dsh-src/dsw-tokens.txt` is the
// deduplicated list extracted from deepseek-harness/packages/client/*/src/**/*.css, and
// `tests/tools/refresh-tokens.mjs` regenerates it from a DSH checkout.
//
//   node tests/audit-client-tokens.mjs
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { PKG } from './_pkg.mjs'

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}

/* ---- every --dsw-* name the client half asks for ---- */
const clientPath = join(PKG, 'lib', 'client.js')
const source = readFileSync(clientPath, 'utf8')
const used = [...new Set([...source.matchAll(/var\((--dsw-[A-Za-z0-9-]+)/g)].map((m) => m[1]))].sort()

ok(used.length > 0, 'the client half uses at least one --dsw-* token', String(used.length))
console.log(`      tokens used: ${used.join(', ')}`)

/* ---- the harness must be able to prove it is checking something ---- */
ok(used.every((t) => /^--dsw-[a-z0-9-]+$/.test(t)),
   'every token is named in the documented --dsw-<group>-<role> form',
   used.filter((t) => !/^--dsw-[a-z0-9-]+$/.test(t)).join(', '))

/* ---- compare against the host's own list ---- */
const listPath = join(PKG, '..', '..', 'logs', 'dsh-src', 'dsw-tokens.txt')
if (!existsSync(listPath)) {
  // Skipped rather than failed: the list is generated from a DSH checkout, so a fresh
  // clone legitimately lacks it, and a false red would train people to ignore this.
  ok(true, 'host token list ABSENT — comparison SKIPPED (run tests/tools/refresh-tokens.mjs)')
} else {
  const known = new Set(
    readFileSync(listPath, 'utf8').split(/\r?\n/).map((l) => l.trim()).filter((l) => l.startsWith('--dsw-')),
  )
  ok(known.size > 100, 'the host token list looks real', `${known.size} tokens`)
  const bogus = used.filter((t) => !known.has(t))
  ok(bogus.length === 0,
     'every token the client half uses exists in the host',
     `${bogus.join(', ')} — a misspelled token does not throw; it silently falls back, so the theme stops applying and nothing reports it`)
}

/* ---- the copy-paste fallbacks must not come back ---- */
// A `var(--x, hardcoded)` hides a missing token behind a colour that looks fine in one
// theme and wrong in the other. The host's own CSS never does this for these roles.
const withFallback = [...source.matchAll(/var\(--dsw-[A-Za-z0-9-]+\s*,\s*([^)]+)\)/g)].map((m) => m[1].trim())
ok(withFallback.length === 0,
   'no --dsw-* token carries a hard-coded colour fallback',
   withFallback.join(' | '))

console.log(problems.length === 0 ? '\nclient design tokens OK' : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
