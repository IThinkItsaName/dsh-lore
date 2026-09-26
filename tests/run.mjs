// Harness: exercise the worklog DSH plugin against the real bundles and a
// stubbed `ctx.skills` registry, asserting the provider contract the registry
// actually enforces (candidate fields, definition fields, content type).
//
//   node logs/tests/run.mjs
import { readFileSync, writeFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { PKG } from './_pkg.mjs'
const results = []
function ok(condition, label, detail = '') {
  results.push([Boolean(condition), label, detail])
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : `  -- ${detail}`}`)
}

const mod = await import(pathToFileURL(`${PKG}/lib/index.js`).href)

function fakeCtx() {
  const providers = []
  const logs = []
  return {
    providers,
    logs,
    skills: { registerProvider: (create) => { providers.push(create); return () => {} } },
    logger: {
      info: (m) => logs.push(['info', String(m)]),
      warn: (m) => logs.push(['warn', String(m)]),
      error: (m) => logs.push(['error', String(m)]),
    },
  }
}
const control = { signal: new AbortController().signal, invalidate: () => {} }
const mountAll = (ctx) => ctx.providers.map((create) => create(control))
const errorsIn = (ctx) => ctx.logs.filter(([l]) => l === 'error')

/**
 * A faithful copy of the registry's own `waitWithAbort`.
 *
 * This helper exists because the earlier harness called provider methods with
 * `await` directly, which silently wraps a synchronous return value — so a
 * NON-promise `list()`/`get()` looked fine here while crashing the real host
 * with `promise.then is not a function`. Reproducing the registry's exact call
 * shape is the whole point.
 */
function waitWithAbort(promise, signal) {
  if (signal === undefined) return promise
  if (signal.aborted === true) throw new Error('aborted')
  return new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true })
    promise.then(resolve, reject)
  })
}

/** Call a provider method exactly the way the registry does (always with a signal). */
async function registryCall(fn, ...args) {
  const signal = new AbortController().signal
  return await waitWithAbort(fn(...args), signal)
}

/** Assert that a provider method hands back a real promise. */
function isPromise(value) {
  return value !== null && typeof value === 'object' && typeof value.then === 'function'
}

/* ---------------------------------------------------------------- exports */

ok(typeof mod.name === 'string' && mod.name.length > 0, 'exports a plugin name', String(mod.name))
ok(Array.isArray(mod.inject) && mod.inject.includes('skills'), 'injects the skills service')
ok(typeof mod.apply === 'function', 'exports apply()')
ok(mod.Config === undefined, 'exports NO Config (an out-of-tree plugin cannot build a Schemastery schema)')

/* ------------------------------------------------- frontmatter parsing */

const worklogText = readFileSync(`${PKG}/skills/project-work-log/SKILL.md`, 'utf8')
const parsed = mod.parseSkillFrontmatter(worklogText, 'SKILL.md')
ok(parsed.name === 'project-work-log', 'parses the worklog skill name', parsed.name)
ok(parsed.description.length > 20, 'parses a non-trivial description', `${parsed.description.length} chars`)
ok(!parsed.description.includes('---'), 'description excludes the closing fence')

const zhText = readFileSync(`${PKG}/skills/reliability-guidelines/SKILL.md`, 'utf8')
const enText = readFileSync(`${PKG}/skills/reliability-guidelines/en/SKILL.md`, 'utf8')
const zh = mod.parseSkillFrontmatter(zhText, 'guidelines zh')
const en = mod.parseSkillFrontmatter(enText, 'guidelines en')
ok(zh.name === 'reliability-guidelines', 'parses the zh guidelines name', zh.name)
ok(en.name === 'reliability-guidelines', 'parses the en guidelines name', en.name)
ok(zh.description !== en.description, 'the two language copies are different documents')
ok(zh.description.includes('八条'), 'the zh copy is Chinese', zh.description.slice(0, 30))
ok(/[Ee]ight/.test(en.description), 'the en copy is English', en.description.slice(0, 40))

const good = (front) => `---\n${front}\n---\n\n# body\n`
ok(mod.parseSkillFrontmatter(good('name: a-b\ndescription: d')).name === 'a-b', 'accepts a minimal block')
ok(mod.parseSkillFrontmatter('\ufeff---\nname: a-b\ndescription: d\n---\n').name === 'a-b', 'tolerates a BOM')
ok(mod.parseSkillFrontmatter(good('name: a-b\ndescription: "say \\"hi\\""')).description === 'say "hi"',
   'unescapes double-quoted scalars')
ok(mod.parseSkillFrontmatter(good("name: a-b\ndescription: 'it''s fine'")).description === "it's fine",
   'unescapes single-quoted scalars')
ok(mod.parseSkillFrontmatter(good('name: a-b\ndescription: |\n  one\n  two')).description === 'one\ntwo',
   'folds a block scalar')
for (const [boolText, expected] of [['true', true], ['no', false], ['1', true], ['0', false]]) {
  const text = good(`name: a-b\ndescription: d\ndisable-model-invocation: ${boolText}`)
  ok(mod.parseSkillFrontmatter(text).invocation.modelInvocable === !expected,
     `disable-model-invocation: ${boolText} -> modelInvocable ${!expected}`)
}
for (const [label, text] of [
  ['a missing frontmatter block', '# just a heading\n'],
  ['an unclosed frontmatter block', '---\nname: a-b\ndescription: d\n'],
  ['a non-kebab-case name', good('name: Not_Kebab\ndescription: d')],
  ['a missing name', good('description: d')],
  ['an empty description', good('name: a-b\ndescription: ""')],
  ['an invalid boolean', good('name: a-b\ndescription: d\nuser-invocable: maybe')],
]) {
  let threw = false
  try { mod.parseSkillFrontmatter(text) } catch { threw = true }
  ok(threw, `rejects ${label}`)
}

/* -------------------------------------------------- stripFrontmatter */

ok(!mod.stripFrontmatter(worklogText).startsWith('---'), 'stripFrontmatter removes the frontmatter')
ok(mod.stripFrontmatter(worklogText).startsWith('# 项目长期工作记录'), 'stripFrontmatter keeps the body')
ok(mod.stripFrontmatter('no frontmatter here') === 'no frontmatter here',
   'stripFrontmatter is a no-op without frontmatter')

/* ------------------------------------------- default mount: two providers */

const ctxA = fakeCtx()
mod.apply(ctxA, {})
ok(ctxA.providers.length === 2, 'default config mounts both skills (worklog + guidelines)',
   String(ctxA.providers.length))
ok(errorsIn(ctxA).length === 0, 'no error logged on a healthy bundle', JSON.stringify(ctxA.logs))

const [pWorklog, pGuidelines] = mountAll(ctxA)
ok(pWorklog.name === 'worklog-bundle', 'the worklog provider has its own name', String(pWorklog.name))
ok(pGuidelines.name === 'worklog-guidelines', 'the guidelines provider has its own name',
   String(pGuidelines.name))
ok(pWorklog.name !== pGuidelines.name, 'the two provider names are distinct (the registry requires it)')
ok(pWorklog.name !== 'runtime' && pGuidelines.name !== 'runtime', 'neither uses the reserved "runtime"')

/* ---- REGRESSION: the registry wraps these calls in `waitWithAbort`, which does
   `value.then(...)` whenever a signal is present. A synchronous `list()`/`get()`
   therefore crashes the run with `promise.then is not a function` — the bug that
   broke the random_solve workspace. These two checks pin the fix. ---- */
for (const [label, provider] of [['worklog', pWorklog], ['guidelines', pGuidelines]]) {
  const listValue = provider.list({ cwd: 'X', scope: {} })
  ok(isPromise(listValue), `${label}: list() returns a promise (the registry calls .then on it)`,
     `got ${typeof listValue}`)
  const candidate = (await listValue).candidates[0]
  const getValue = provider.get(candidate, { cwd: 'X', scope: {} })
  ok(isPromise(getValue), `${label}: get() returns a promise (the registry calls .then on it)`,
     `got ${typeof getValue}`)
}

// And the full round trip through the registry's exact call shape must not throw.
let contractThrew = ''
try {
  for (const provider of [pWorklog, pGuidelines]) {
    const obs = await registryCall(provider.list.bind(provider), { cwd: 'X', scope: {} })
    ok(obs.complete === true, `${provider.name}: list() survives waitWithAbort`)
    const def = await registryCall(provider.get.bind(provider), obs.candidates[0], { cwd: 'X', scope: {} })
    ok(typeof def?.content === 'string', `${provider.name}: get() survives waitWithAbort`)
  }
} catch (error) {
  contractThrew = `${error.constructor.name}: ${error.message}`
}
ok(contractThrew === '', 'the registry call shape does not throw', contractThrew)

/* ---- a stale-name get() must still return a promise (not `undefined`) ---- */
{
  const stale = { name: 'no-such-skill' }
  const value = pWorklog.get(stale, { cwd: 'X', scope: {} })
  ok(isPromise(value), 'a stale-name get() returns a promise, not undefined',
     `got ${typeof value}`)
  const def = await value
  ok(def?.name === 'project-work-log',
     'the stale-name get() returns a definition the registry can reject by name', def?.name)
}

/* ---- candidate and definition contract, for each provider ---- */
for (const [label, provider, expectedName] of [
  ['worklog', pWorklog, 'project-work-log'],
  ['guidelines', pGuidelines, 'reliability-guidelines'],
]) {
  const obs = await provider.list()
  ok(Array.isArray(obs.candidates) && obs.complete === true,
     `${label}: list() returns a complete observation`)
  const c = obs.candidates[0] ?? {}
  ok(c.name === expectedName, `${label}: candidate name`, c.name)
  ok(typeof c.description === 'string' && c.description.length > 0, `${label}: description is a string`)
  ok(typeof c.source === 'string', `${label}: source is a string`, typeof c.source)
  ok(c.provider === provider.name, `${label}: candidate.provider matches the provider name`,
     `${c.provider} vs ${provider.name}`)
  ok(typeof c.rank === 'number' && Number.isFinite(c.rank), `${label}: rank is a finite number`)
  ok(c.invocation?.modelInvocable === true && c.invocation?.userInvocable === true,
     `${label}: invocation permits both surfaces`)

  const def = await provider.get(c)
  ok(def !== undefined, `${label}: get() returns a definition`)
  ok(def.name === c.name, `${label}: loaded name matches discovered name`)
  ok(typeof def.content === 'string' && def.content.length > 100,
     `${label}: definition content is a non-trivial string`, `${def.content?.length} chars`)
  ok(!def.content.startsWith('---'), `${label}: content excludes the frontmatter`)
  ok(def.resourceBase?.kind === 'directory', `${label}: resourceBase is a directory`)
  ok(typeof def.path === 'string' && norm(def.path).endsWith('SKILL.md'), `${label}: path points at SKILL.md`)
}

function norm(p) { return String(p ?? '').replaceAll('\\', '/') }

/* ---- CROSS-SKILL CONSISTENCY -------------------------------------------
   Both skills ship in one bundle, and the guidelines point at the record
   container that project-work-log owns. When the layout changed to work_log/,
   the guidelines kept saying `journal/` — a real drift nothing caught. These
   checks make the two files agree. */
{
  const zhText = readFileSync(`${PKG}/skills/reliability-guidelines/SKILL.md`, 'utf8')
  const enText = readFileSync(`${PKG}/skills/reliability-guidelines/en/SKILL.md`, 'utf8')
  const worklogText = readFileSync(`${PKG}/skills/project-work-log/SKILL.md`, 'utf8')

  // The worklog skill's declared container name, taken from the doc itself.
  const declared = /一个容器目录\*\*\s*`([^`]+)`/.exec(worklogText)?.[1]
  ok(declared === 'work_log/', 'project-work-log declares work_log/ as the container',
     String(declared))

  // The guidelines must name that same container, in both languages.
  ok(zhText.includes(`\`${declared}\``),
     'guidelines (zh) reference the container project-work-log declares',
     `looking for \`${declared}\``)
  ok(enText.includes(`\`${declared}\``),
     'guidelines (en) reference the container project-work-log declares')

  // And must not present the OLD container as the place to write.
  ok(!/工作记录（`journal\/`）/.test(zhText),
     'guidelines (zh) no longer tell you to write into journal/')
  ok(!/work record \(`journal\/`\)/.test(enText),
     'guidelines (en) no longer tell you to write into journal/')
  // `journal.py` is a script name, not a directory, so it may still appear.
  ok(zhText.includes('journal.py'), 'guidelines still name the journal.py tool correctly')
}

/* ---- language selection ---- */
async function guidelinesBodyFor(config) {
  const ctx = fakeCtx()
  mod.apply(ctx, config)
  const provider = mountAll(ctx)[1]
  if (provider === undefined) return undefined
  return (await provider.get((await provider.list()).candidates[0])).content
}

const bodyEn = await guidelinesBodyFor({ guidelinesLanguage: 'en' })
ok(bodyEn?.includes('Facts over guesses') === true, 'guidelinesLanguage=en serves the English copy',
   bodyEn?.slice(0, 60))
const bodyZh = await guidelinesBodyFor({ guidelinesLanguage: 'zh' })
ok(bodyZh?.includes('事实优先') === true, 'guidelinesLanguage=zh serves the Chinese copy')
ok(bodyZh?.includes('八条准则') === true, 'the Chinese copy is the cleaned-up rewrite')
const bodyTypo = await guidelinesBodyFor({ guidelinesLanguage: 'eng' })
ok(bodyTypo?.includes('事实优先') === true,
   'an unrecognized language falls back to Chinese rather than serving nothing')

/* ---- the rewritten authority clause ---- */
// Markdown wraps lines and the guidelines open with a blockquote, so compare on
// text with quote markers and whitespace normalized away.
const flat = (s) => String(s ?? '')
  .split('\n').map((l) => l.replace(/^\s*>\s?/, '')).join('\n')
  .replace(/\s+/g, ' ')
ok(flat(bodyZh).includes('默认强约束'), 'the zh copy frames itself as a strong default')
ok(flat(bodyZh).includes('你的显式决定优先于这些默认值'), 'the zh copy states the user outranks it')
ok(flat(bodyZh).includes('不是"拒绝用户"的授权'), 'the zh copy drops the refuse-the-user licence')
ok(flat(bodyEn).includes('strong default'), 'the en copy frames itself as a strong default')
ok(flat(bodyEn).includes('Your explicit decision outranks these defaults'),
   'the en copy states the user outranks it')
ok(flat(bodyEn).includes('not a licence to refuse the user'),
   'the en copy drops the refuse-the-user licence')

/* ---- disabling the guidelines ---- */
const ctxOff = fakeCtx()
mod.apply(ctxOff, { guidelinesEnabled: false })
ok(ctxOff.providers.length === 1, 'guidelinesEnabled=false mounts only the worklog skill',
   String(ctxOff.providers.length))

/* ---- liveness: a provider re-reads, so an edit changes the body ---- */
const guidPath = `${PKG}/skills/reliability-guidelines/SKILL.md`
const before = (await pGuidelines.get((await pGuidelines.list()).candidates[0])).content.length
try {
  writeFileSync(guidPath, `${zhText}\n<!-- liveness probe -->\n`)
  const after = (await pGuidelines.get((await pGuidelines.list()).candidates[0])).content.length
  ok(after > before, 'get() re-reads the file, so an edit appears without a host restart',
     `${before} -> ${after}`)
} finally {
  writeFileSync(guidPath, zhText)
}
ok(readFileSync(guidPath, 'utf8') === zhText, 'the harness restored the guidelines file')

/* ---- config coercion ---- */
const ctxB = fakeCtx()
mod.apply(ctxB, { userInvocable: false })
const pB = mountAll(ctxB)[0]
const defB = await pB.get((await pB.list()).candidates[0])
ok(defB.invocation.userInvocable === false, 'config can withdraw the user surface')
ok(defB.invocation.modelInvocable === true, 'config leaves the model surface intact')

const ctxC = fakeCtx()
mod.apply(ctxC, { modelInvocable: 'yes', bogusKey: 1 })
ok(ctxC.providers.length === 2, 'a non-boolean / unknown config value does not break the mount')
ok(ctxC.logs.some(([level, m]) => level === 'warn' && m.includes('bogusKey')),
   'unknown config keys are reported', JSON.stringify(ctxC.logs))

const ctxD = fakeCtx()
mod.apply(ctxD, null)
ok(ctxD.providers.length === 2, 'a null config does not break the mount')

const ctxE = fakeCtx()
mod.apply(ctxE, { skillDir: `${PKG}/no/such/dir`, guidelinesDir: `${PKG}/no/such/dir` })
ok(ctxE.providers.length === 0, 'missing bundles mount no provider')
ok(errorsIn(ctxE).length === 2, 'both missing bundles are reported, not swallowed',
   JSON.stringify(ctxE.logs))

const ctxF = fakeCtx()
mod.apply(ctxF, { skillDir: `${PKG}/no/such/dir` })
ok(ctxF.providers.length === 1, 'a missing worklog bundle does not stop the guidelines mounting',
   String(ctxF.providers.length))

const ctxG = fakeCtx()
mod.apply(ctxG, { verbose: true })
ok(ctxG.logs.some(([level, m]) => level === 'info' && m.includes('project-work-log')),
   'verbose logs the worklog skill')
ok(ctxG.logs.some(([level, m]) => level === 'info' && m.includes('reliability-guidelines')),
   'verbose logs the guidelines skill')

/* ------------------------------------------------------------------ total */

const failed = results.filter(([good]) => !good)
console.log(`\n${results.length - failed.length}/${results.length} passed`)
process.exit(failed.length === 0 ? 0 : 1)
