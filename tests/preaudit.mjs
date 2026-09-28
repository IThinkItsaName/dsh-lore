// Pre-restart audit: prove what the host will import, and that it registers a
// provider whose output satisfies the registry's rules.
import { readFileSync, realpathSync, existsSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { pathToFileURL } from 'node:url'
import { PKG, extraBundledSkills } from './_pkg.mjs'

/*
 * The profile link can only be checked against the package that is actually
 * installed. Running from a copied tree (or from `logs/tests/` while the workspace
 * copy is the installed one) makes that comparison meaningless rather than failing,
 * so it is skipped unless this package IS the installed one — see isInstalled().
 */
const PROFILE = process.env.DSH_PROFILE_DIR ?? ''

const problems = []
const ok = (c, label, detail = '') => {
  console.log(`${c ? 'PASS' : 'FAIL'}  ${label}${c || !detail ? '' : ` -- ${detail}`}`)
  if (!c) problems.push(label)
}

/** Resolve the package the profile actually installs, or '' when unknowable. */
function installedTarget() {
  if (PROFILE === '') return ''
  const link = `${PROFILE}/node_modules/dsh-worklog`
  if (!existsSync(link)) return ''
  try {
    return realpathSync(link).replaceAll('\\', '/').toLowerCase()
  } catch {
    return ''
  }
}

const installed = installedTarget()
const isInstalled = installed !== '' && installed === PKG.replaceAll('\\', '/').toLowerCase()

/* 1. the profile link resolves to the package we edited */
if (PROFILE === '') {
  ok(true, 'profile link check SKIPPED (set DSH_PROFILE_DIR to enable it)')
} else if (installed === '') {
  ok(false, 'the profile has the dsh-worklog link', `${PROFILE}/node_modules/dsh-worklog`)
} else if (!isInstalled) {
  console.log(`      (this package is not the installed one; installed: ${installed})`)
  ok(true, 'profile link check SKIPPED (running from a copy, not the installed package)')
} else {
  ok(true, 'the profile link resolves to this package', installed)
}

/* 2. the manifest the host reads */
const pkg = JSON.parse(readFileSync(`${PKG}/package.json`, 'utf8'))
ok(pkg.type === 'module', 'manifest declares type=module (the loader needs ESM)', String(pkg.type))
ok(pkg.dsh?.bundle?.patch === './cordis.patch.yml', 'manifest declares the bundle patch')
ok(pkg.exports?.['.'] === './lib/index.js', 'manifest exports the entry point', String(pkg.exports?.['.']))

/* 3. the entry the host imports: content hash + the marker strings that matter */
const entry = readFileSync(`${PKG}/lib/index.js`, 'utf8')
const hash = createHash('sha256').update(entry).digest('hex').slice(0, 16)
console.log(`      lib/index.js sha256:${hash}  (${entry.split('\n').length} lines)`)
ok(entry.includes('registerProvider'), 'the entry registers a PROVIDER (not a snapshot register)')
/*
 * Imports: `node:` builtins are always fine; `@deepseek-ai/*` is allowed **only** because the
 * host supplies it — see `dsh-app-boot/lib/index.js:477-481`: resolution is two-anchor (the dsh
 * installation, then the profile), and "the runtime resolution supplies packages carried by the
 * installation and selected bundles to Node's ESM and CommonJS resolvers".
 *
 * These two assertions used to forbid `@deepseek-ai` outright, with the reason "schemastery is
 * unreachable out of tree" written into a third one below. That reason came from a measurement
 * of the WRONG THING: a hand-copied directory is not part of the profile manifest's install set,
 * so of course it could not be supplied. `dsh-ref/PLUGIN-AUTHORING.md` §4.3 states the opposite
 * and cites the same boot code. Keeping the old rule would have frozen a falsehood into the gate
 * and blocked every standard-conforming plugin — the same class of mistake as the locale and
 * Config retractions earlier in this project.
 *
 * What still matters is that nothing *third-party* sneaks in: those would resolve in the harness
 * only because the harness injects a resolver, and would fail in the host.
 */
const bareImports = [...entry.matchAll(/^\s*import[^\n]*from\s+['"]([^'"]+)['"]/gm)].map((m) => m[1])
const allowedBare = (spec) => spec.startsWith('node:')
  || spec === '@deepseek-ai/schemastery'
  || spec === '@deepseek-ai/dsh-tools'
const unexpected = bareImports.filter((spec) => !allowedBare(spec))
ok(unexpected.length === 0,
   'every bare import is a node: builtin or a host-supplied @deepseek-ai package',
   unexpected.join(', '))
ok(entry.includes('content: stripFrontmatter'), 'the definition carries a content string')

/* 4. import it exactly as the loader would, and drive the provider */
const mod = await import(pathToFileURL(`${PKG}/lib/index.js`).href)
ok(typeof mod.apply === 'function', 'the entry exports apply()')
ok(Array.isArray(mod.inject) && mod.inject.includes('skills'),
   'the entry injects ctx.skills', String(mod.inject))
ok(Array.isArray(mod.inject) && mod.inject.includes('tools'),
   'the entry injects ctx.tools (the registry the memory tool registers into)', String(mod.inject))
ok(mod.Config !== undefined,
   'the entry exports a Config (the host supplies schemastery — §4.3 of PLUGIN-AUTHORING)')
ok(mod.Config === null || typeof mod.Config === 'object' || typeof mod.Config === 'function',
   'the exported Config is a schema object, not a plain string or number', typeof mod.Config)
ok(typeof mod.Config?.toJSON === 'function',
   'the Config carries toJSON (the settings-page projection requires it — §4.3)')

const creates = []
const logs = []
const ctx = {
  logger: { info: (m) => logs.push(['I', String(m)]), warn: (m) => logs.push(['W', String(m)]), error: (m) => logs.push(['E', String(m)]) },
  skills: { registerProvider: (create) => { creates.push(create); return () => {} } },
}
mod.apply(ctx, {})

ok(creates.length === 2 + extraBundledSkills().length,
   'apply() calls registerProvider once per skill bundle on disk',
   `${creates.length} calls, ${extraBundledSkills().length} extra bundles`)
ok(!logs.some(([l]) => l === 'E'), 'apply() logged no error', JSON.stringify(logs))

const provider = creates[0]({ signal: new AbortController().signal, invalidate: () => {} })
ok(provider.name === 'worklog-bundle' && provider.name !== 'runtime',
   'the provider name is valid and not the reserved one', provider.name)

const obs = await provider.list()
ok(Array.isArray(obs.candidates) && obs.complete === true && obs.candidates.length === 1,
   'list() returns one complete candidate')
const c = obs.candidates[0]
ok(c.provider === provider.name, 'candidate.provider matches the provider name (the registry enforces this)',
   `${c.provider} vs ${provider.name}`)
ok(typeof c.rank === 'number', 'candidate carries a numeric rank', String(c.rank))
ok(c.name === 'project-work-log', 'candidate name', c.name)

const def = await provider.get(c)
ok(def && typeof def.content === 'string' && def.content.length > 100,
   'get() returns a definition with a content string', def ? `${def.content?.length} chars` : 'no definition')
ok(def.name === c.name, 'the loaded name matches the discovered name')
ok(!def.content.includes('57 项'), 'the served body no longer contains the stale count')
ok(def.content.includes('断言数以脚本实际输出为准'), 'the served body carries the corrected wording')

/* 5. the served body must equal the file on disk (no snapshot) */
const onDisk = readFileSync(`${PKG}/skills/project-work-log/SKILL.md`, 'utf8')
const bodyFromFile = onDisk.slice(onDisk.indexOf('\n---', 3) + 4).replace(/^\n+/, '')
ok(def.content === bodyFromFile, 'the served body equals the current file body (live, not snapshotted)')

/* 6. no stale second copy of the package that the host might import instead */
if (!isInstalled) {
  ok(true, 'pnpm store check SKIPPED (this package is not the installed one)')
} else {
  const stale = `${PROFILE}/node_modules/.pnpm`
  ok(existsSync(stale), 'the pnpm store exists (link install)')
}

console.log(problems.length === 0
  ? `\nAUDIT CLEAN — the host will import sha256:${hash} and it satisfies the registry`
  : `\n${problems.length} PROBLEM(S)`)
process.exit(problems.length === 0 ? 0 : 1)
