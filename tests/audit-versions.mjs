// Version and repository-name consistency across the release surface.
//
// Why this exists: `package.json`, the git tags, the CHANGELOG and the install
// examples drifted apart more than once, and nobody noticed. `v0.1.1` shipped with
// `"version": "0.1.0"`; `v0.3.0` was tagged while the manifest still said `0.2.0`;
// the README install line was still pinned to `v0.1.1` two releases later. The cause
// was structural — PUBLISHING.md's release steps said "tidy the CHANGELOG" and never
// said "bump the version".
//
// The repository name drifts the same way, and did: the repo was renamed to
// `dsh-lore` while three files and two local remotes still pointed at the old
// name. A rename is also the moment PUBLISHING.md warns about ("if you rename,
// replace these two values first"), so it is worth gating rather than remembering.
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

/* ---- 7. every repository mention must name the same repo ----
   The canonical value is read from the files themselves rather than from the git
   remote: reading a remote needs a pipe to capture git's output, and this sandbox
   forbids a program opening a pipe, so `git config` cannot be called from inside
   the test. Cross-checking the files against each other still catches the real
   failure — one file updated on rename and another missed — and
   DSH_WORKLOG_SLUG, when set, additionally pins the expected value. */
const mentions = new Map()
for (const [file, text] of [['README.md', readme], ['PUBLISHING.md', publishing], ['CHANGELOG.md', changelog]]) {
  const found = new Set(
    [...text.matchAll(/github\.com[/:]([^/\s)"'<>]+)\/([^/\s)"'<>#@]+?)(?:\.git)?(?:[/@)\s"'<>#]|$)/g)]
      .map((m) => `${m[1]}/${m[2]}`),
  )
  ok(found.size > 0, `${file} names the repository at least once`, [...found].join(', '))
  for (const slug of found) {
    if (!mentions.has(slug)) mentions.set(slug, [])
    mentions.get(slug).push(file)
  }
}

ok(mentions.size > 0, 'collected the repository names used by the docs')
if (mentions.size > 1) {
  for (const [slug, where] of mentions) {
    ok(false, `every repository mention names the same repo (saw ${slug})`,
       `also named in: ${where.join(', ')} — a half-finished rename leaves links and install lines on the old name, and GitHub's redirect hides it`)
  }
} else {
  const [slug] = [...mentions.keys()]
  console.log(`      repository slug in docs: ${slug}`)
  ok(true, `all ${[...mentions.values()].flat().length} repository mentions agree (${slug})`)
}

const expected = process.env.DSH_WORKLOG_SLUG ?? ''
if (expected === '') {
  ok(true, 'expected-slug check SKIPPED (set DSH_WORKLOG_SLUG to pin it)')
} else {
  ok(mentions.has(expected), `the docs name the expected repository (${expected})`,
     `docs name: ${[...mentions.keys()].join(', ')}`)
}

console.log(problems.length === 0 ? '\nversion consistency OK' : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
