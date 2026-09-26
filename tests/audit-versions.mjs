// Version consistency across the release surface.
//
// Why this exists: `package.json`, the git tags, the CHANGELOG and the install
// examples drifted apart more than once, and nobody noticed. `v0.1.1` shipped with
// `"version": "0.1.0"`; `v0.3.0` was tagged while the manifest still said `0.2.0`;
// the README install line was still pinned to `v0.1.1` two releases later. The cause
// was structural — PUBLISHING.md's release steps said "tidy the CHANGELOG" and never
// said "bump the version".
//
// All of it is statically decidable, so it is checked here rather than trusted.
//
//   node tests/audit-versions.mjs
import { readFileSync } from 'node:fs'
import { PKG } from './_pkg.mjs'

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}

const read = (rel) => {
  try { return readFileSync(`${PKG}/${rel}`, 'utf8') } catch { return '' }
}

const pkg = JSON.parse(read('package.json'))
const version = String(pkg.version ?? '')
const changelog = read('CHANGELOG.md')
const readme = read('README.md')
const publishing = read('PUBLISHING.md')

/* ---- 1. the manifest version is a well-formed release ---- */
ok(/^\d+\.\d+\.\d+$/.test(version), 'package.json declares a semver release version', version)

/* ---- 2. the CHANGELOG has a matching release section ---- */
const escaped = version.replaceAll('.', '\\.')
ok(new RegExp(`^## \\[${escaped}\\] - \\d{4}-\\d{2}-\\d{2}$`, 'm').test(changelog),
   `CHANGELOG.md has a "## [${version}] - <date>" section`,
   'a released version must have a dated CHANGELOG section')

/* ---- 3. there is still an Unreleased section above it ---- */
ok(/^## \[未发布\]/m.test(changelog),
   'CHANGELOG.md keeps an empty or populated [未发布] section at the top',
   'PUBLISHING.md tells the maintainer to leave one')

/* ---- 4. every released section has a link definition, and 未发布 points at HEAD ---- */
const sections = [...changelog.matchAll(/^## \[([^\]]+)\](?: - \d{4}-\d{2}-\d{2})?$/gm)]
  .map((m) => m[1])
  .filter((s) => s !== '未发布')
ok(sections.length > 0, 'found released CHANGELOG sections', sections.join(', '))
for (const section of sections) {
  const esc = section.replaceAll('.', '\\.')
  ok(new RegExp(`^\\[${esc}\\]:\\s+\\S+`, 'm').test(changelog),
     `CHANGELOG link table defines [${section}]`)
}

/* ---- 5. the [未发布] compare link does not point at an old tag ---- */
const unreleasedLink = /^\[未发布\]:\s*(\S+)/m.exec(changelog)?.[1] ?? ''
ok(unreleasedLink.includes('...HEAD'),
   '[未发布] compares the newest release to HEAD', unreleasedLink)
if (sections.length > 0) {
  ok(unreleasedLink.includes(`v${sections[0]}`),
     `[未发布]'s base is the newest release (v${sections[0]})`,
     `${unreleasedLink} — a stale base silently compares the wrong range`)
}

/* ---- 6. pinned install examples must not lag behind ---- */
const pinned = new Set()
for (const [file, text] of [['README.md', readme], ['PUBLISHING.md', publishing]]) {
  for (const m of text.matchAll(/@v(\d+\.\d+\.\d+)/g)) pinned.add(`${file}:${m[1]}`)
}
ok(pinned.size > 0, 'found at least one pinned install example', [...pinned].join(', '))
for (const entry of pinned) {
  const [, tagged] = entry.split(':')
  ok(tagged === version,
     `pinned example ${entry} matches package.json (${version})`,
     'an install example pinned to an old tag installs the wrong thing')
}

console.log(problems.length === 0 ? '\nversion consistency OK' : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
