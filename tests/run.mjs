// Harness: exercise the worklog DSH plugin against the real bundles and a
// stubbed `ctx.skills` registry, asserting the provider contract the registry
// actually enforces (candidate fields, definition fields, content type).
//
//   node publish/worklog/tests/run.mjs
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { PKG, extraBundledSkills } from './_pkg.mjs'
const results = []
function ok(condition, label, detail = '') {
  results.push([Boolean(condition), label, detail])
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : `  -- ${detail}`}`)
}

const mod = await import(pathToFileURL(`${PKG}/lib/index.js`).href)

function fakeCtx() {
  const providers = []
  const logs = []
  const registeredTools = []
  const listeners = new Map()
  return {
    providers,
    logs,
    registeredTools,
    listeners,
    // `apply()` watches `loader/volatile-update` to refresh the skill catalog cache and the
    // diagnostics switch. Record listeners so a test can emit the same event the Loader emits.
    on: (event, listener) => {
      const list = listeners.get(event) ?? []
      list.push(listener)
      listeners.set(event, list)
    },
    emit: (event, ...args) => {
      for (const listener of listeners.get(event) ?? []) listener(...args)
    },
    skills: { registerProvider: (create) => { providers.push(create); return () => {} } },
    // The tools registry, recorded rather than stubbed away.
    //
    // Why this must exist here: `mountMemoryTools` guards on `ctx.tools.register` being a
    // function and otherwise **returns quietly**, and it wraps the real `defineTool` call in a
    // try/catch that turns a schema error into a host log line nobody can read. With no `tools`
    // in the fake context, both paths were dead in this harness and the registration was never
    // exercised — which is exactly how an invalid `output.schema` shipped: the injected prompt
    // told the model to call `worklog_memory`, and no such tool existed.
    tools: { register: (definition) => { registeredTools.push(definition); return () => {} } },
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

/*
 * `Config` — optional, but if present it must be a real schema.
 *
 * This assertion USED to read `mod.Config === undefined` with the reason "an out-of-tree
 * plugin cannot build a Schemastery schema". That reason was wrong, and it was wrong in a
 * way that mattered: it was an inference, never measured, and `dsh-ds-balance` disproves it
 * (live Config inspect reports it as `status: schema`, with all fields marked
 * `x-cordis.volatile`). `require.resolve('@deepseek-ai/schemastery')` fails for THIS plugin
 * **and for that one too** — the host's Loader handles those builtin specifiers itself, so
 * `absent` means "not written", not "cannot be written".
 *
 * Asserting the absence would therefore freeze stale knowledge into the gate, and the
 * gate's own message would then explain itself with a falsehood. What is actually worth
 * pinning is that a Config, IF one appears, is a validator rather than a plain object —
 * because the tutorial is explicit that exporting a plain object does NOT work.
 */
if (mod.Config === undefined) {
  // 这条分支按 `preaudit.mjs` 的断言（`Config` 必须存在）是不可达的。原来写 `ok(true, …)`
  // 把"没验"记成 PASS；改记 SKIP —— 空转就去掉实义，别假装验过（审查报告 F13）。
  skip('Config is absent — the validator shape could not be checked (preaudit requires it to exist)')
} else {
  // The tutorial is explicit that exporting a plain object does NOT work, so the one thing
  // worth pinning here is that whatever appears is not merely a data literal.
  const plainObject = mod.Config !== null
    && typeof mod.Config === 'object'
    && !Array.isArray(mod.Config)
    && Object.getPrototypeOf(mod.Config) === Object.prototype
    && typeof mod.Config.parse !== 'function'
  ok(!plainObject,
     'an exported Config is a validator, not a plain object',
     'the tutorial states a plain object does not work as a Config')
}

/* ------------------------------------------------- frontmatter parsing */

const worklogText = readFileSync(`${PKG}/skills/project-work-log/SKILL.md`, 'utf8')
const parsed = mod.parseSkillFrontmatter(worklogText, 'SKILL.md')
ok(parsed.name === 'project-work-log', 'parses the worklog skill name', parsed.name)
ok(parsed.description.length > 20, 'parses a non-trivial description', `${parsed.description.length} chars`)
ok(!parsed.description.includes('---'), 'description excludes the closing fence')

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

/* ------------------------------- default mount: one explicit provider + extras */

const ctxA = fakeCtx()
mod.apply(ctxA, {})
ok(ctxA.providers.length === 1 + extraBundledSkills().length,
   'default config mounts one provider for the configured skill plus every extra bundle',
   `${ctxA.providers.length} providers, ${extraBundledSkills().length} extra bundles`)
ok(errorsIn(ctxA).length === 0, 'no error logged on a healthy bundle', JSON.stringify(ctxA.logs))

/* ---- REGRESSION: the memory tool must actually reach the tools registry ----
   The plugin registers it through `ctx.tools.register(defineTool({...}))` inside a try/catch that
   reports a failure only as a host log line. `defineTool` rejects an `output.schema` written in
   plain JSON Schema (a root-level `required` array, no explicit `additionalProperties`), so the
   call threw, the warning was swallowed, and the tool never existed — while the injected prompt
   told the model to read memory bodies *with that tool*. Nothing noticed, because this harness's
   fake context had no `tools` at all and the guard returned quietly. These two assertions make
   the registration itself the thing under test. */
const memoryTool = ctxA.registeredTools.find((tool) => tool?.name === 'worklog_memory')
ok(memoryTool !== undefined, 'the memory tool reaches the tools registry',
   `registered: ${ctxA.registeredTools.map((t) => t?.name).join(', ') || '(none)'}`)
ok(ctxA.logs.every(([, message]) => !message.includes('could not register the memory tool')),
   'and no registration failure is logged', JSON.stringify(ctxA.logs))
// `defineTool` compiles the authored per-field `required: true` into a root-level `required`
// array, so these read the **normalized** definition — which is the point: it proves the whole
// authoring form was accepted, not just that some object was stored.
ok(Array.isArray(memoryTool?.parameters?.required)
   && memoryTool.parameters.required.includes('operation')
   && memoryTool.parameters.required.includes('workspace'),
   'the memory tool declares its two required parameters',
   JSON.stringify(memoryTool?.parameters?.required ?? null))
ok(memoryTool?.output?.schema?.additionalProperties === false
   && Array.isArray(memoryTool?.output?.schema?.required)
   && memoryTool.output.schema.required.includes('text'),
   'its output schema compiles (explicit additionalProperties, text required)',
   JSON.stringify(memoryTool?.output?.schema ?? null))

const [pWorklog, ...pExtras] = mountAll(ctxA)
ok(pWorklog.name === 'worklog-bundle', 'the worklog provider has its own name', String(pWorklog.name))
ok(pWorklog.name !== 'runtime', 'it does not use the reserved "runtime"')
ok(pExtras.length === extraBundledSkills().length,
   'every extra bundle got its own provider', `${pExtras.length} providers`)
ok(pExtras.every((provider) => provider.name !== pWorklog.name),
   'the worklog and extra provider names are distinct (the registry requires it)')

/* ---- Bundled skills: one provider per bundle in `skills/`, and each bundle's own
   frontmatter invocation policy survives this path.

   Why this is the assertion worth having: `apply()` used to mount exactly the two bundles it
   named, so a third bundle shipped under `skills/` was **inert** — `npm pack` shipped it, nothing
   registered it, and a host restart never helped (the filesystem provider scans
   `<DSH_HOME>/skills`, not a package's own directory). The count is derived from the package
   directory (`extraBundledSkills()`), and the policy check pins the part that would silently
   break the "off by default" promise: `createProvider` ANDs the config switches with the
   *frontmatter*, so `disable-model-invocation: true` must still come through as
   `modelInvocable: false` on the candidate the registry sees. ---- */
const extraProviders = mountAll(ctxA).slice(1)
ok(extraProviders.length === extraBundledSkills().length,
   'every extra bundle on disk got its own provider',
   `${extraProviders.length} providers for ${extraBundledSkills().join(', ') || '(none)'}`)
for (const provider of extraProviders) {
  const obs = await provider.list({ cwd: 'X', scope: {} })
  const candidate = obs.candidates[0]
  const text = readFileSync(candidate.path, 'utf8')
  const declaresOff = /^disable-model-invocation:\s*true\s*$/m.test(text.split('---')[1] ?? '')
  ok(candidate.invocation.modelInvocable === !declaresOff,
     `${provider.name}: the bundle's own frontmatter decides modelInvocable`,
     `frontmatter says off=${declaresOff}, candidate says modelInvocable=${candidate.invocation.modelInvocable}`)
}

/* ---- REGRESSION: the registry wraps these calls in `waitWithAbort`, which does
   `value.then(...)` whenever a signal is present. A synchronous `list()`/`get()`
   therefore crashes the run with `promise.then is not a function` — the bug that
   broke the random_solve workspace. These two checks pin the fix. ---- */
for (const [label, provider] of [
  ['worklog', pWorklog],
  ...pExtras.map((provider) => [provider.name, provider]),
]) {
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
  for (const provider of [pWorklog, ...pExtras]) {
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

/* ---- disabling the work-log skill itself (the memory half stays up) ---- */
const ctxSkillOff = fakeCtx()
mod.apply(ctxSkillOff, { skillEnabled: false })
ok(ctxSkillOff.providers.length === 1 + extraBundledSkills().length,
   'skillEnabled=false keeps the work-log provider registered too',
   String(ctxSkillOff.providers.length))
{
  const [skillOffMain] = mountAll(ctxSkillOff)
  const catalog = await skillOffMain.list({ cwd: 'X', scope: {} })
  ok(catalog.candidates.length === 0,
     'and that provider serves nothing while the switch is off',
     JSON.stringify(catalog))
}
ok(ctxSkillOff.registeredTools.length === 1,
   'and the memory tool still mounts — the skill half and the memory half are independent',
   String(ctxSkillOff.registeredTools.length))

/* ---- REGRESSION: 配置是**现读**的，不是装载时快照的 ----
   这条是"改完即时生效"的全部意义所在。生产里的机制是：Loader 对 volatile-only 的改动**不重挂载**，
   它把新值提交进运行中的 `.volatile()` 引用。所以这里用一个**带 `.get()` 的引用桩**（`volatile()`）
   模拟真实形状 —— 用普通对象会测不到那条路（`live()` 只对引用优先现读）。 */
{
  const cell = (initial) => {
    let value = initial
    return { get: () => value, set: (next) => { value = next } }
  }
  const skillEnabled = cell(true)
  const ctxLive = fakeCtx()
  mod.apply(ctxLive, { skillDir: 'skills/project-work-log', skillEnabled })
  const [liveMain] = mountAll(ctxLive)
  const before = await liveMain.list({ cwd: 'X', scope: {} })
  ok(before.candidates.length === 1, 'live: the skill is served before the change')

  skillEnabled.set(false)             // ← Loader 的 volatile-only 提交 = 改引用里的值
  const after = await liveMain.list({ cwd: 'X', scope: {} })
  ok(after.candidates.length === 0,
     'live: flipping skillEnabled takes effect on the NEXT list() — no restart',
     JSON.stringify(after.candidates.map((c) => c.name)))

  skillEnabled.set(true)
  const back = await liveMain.list({ cwd: 'X', scope: {} })
  ok(back.candidates.length === 1, 'live: flipping it back works too', JSON.stringify(back))
}

/* ---- REGRESSION: 注册表的目录缓存必须有失效路径（2026-10-19） ----
   `registerProvider(create)` 把注册作用域的 `invalidate()` 作为参数交给 create；丢掉它，
   provider 读得再新，模型侧（`dsh-tool-skill` 每步 `skills.snapshot()`）还是旧目录 ——
   注册表按 cwd/scope/revision 缓存且**没有 TTL**。 */
{
  const cell = (initial) => {
    let value = initial
    return { get: () => value, set: (next) => { value = next } }
  }
  let invalidationCalls = 0
  const control = {
    signal: new AbortController().signal,
    invalidate: () => { invalidationCalls += 1 },
  }
  const ctxCache = fakeCtx()
  mod.apply(ctxCache, { skillDir: 'skills/project-work-log' })
  const [derived] = ctxCache.providers.map((create) => create(control))
  ok(typeof derived.retryProbe === 'function',
     'a provider exposes retryProbe() so a corrected path can recover')

  ctxCache.emit('loader/volatile-update', [['skillEnabled']])
  ok(invalidationCalls === ctxCache.providers.length,
     'a skill-related volatile update invalidates every provider registration',
     `${invalidationCalls} vs ${ctxCache.providers.length} providers`)

  const afterSkill = invalidationCalls
  ctxCache.emit('loader/volatile-update', [['memoryInjectIndex']])
  ok(invalidationCalls === afterSkill,
     'an unrelated (memory) update leaves the skill catalog cache alone',
     String(invalidationCalls))
}

/* ---- REGRESSION: 装载探针失败不该把 provider 永久钉死（2026-10-19） ---- */
{
  const cell = (initial) => {
    let value = initial
    return { get: () => value, set: (next) => { value = next } }
  }
  const skillDir = cell('does/not/exist')
  const ctxRetry = fakeCtx()
  mod.apply(ctxRetry, { skillDir })
  const [provider] = ctxRetry.providers.map((create) => create(control))
  const blocked = await provider.list({ cwd: 'X', scope: {} })
  ok(blocked.candidates.length === 0 && blocked.complete === false,
     'a mount-time probe failure serves nothing and reports incomplete', JSON.stringify(blocked))

  skillDir.set('skills/project-work-log')   // ← Loader 的 volatile-only 提交 = 改引用里的值
  ctxRetry.emit('loader/volatile-update', [['skillDir']])
  const recovered = await provider.list({ cwd: 'X', scope: {} })
  ok(recovered.candidates.length === 1,
     'fixing skillDir recovers on the next list() — the probe is re-armed, no restart',
     JSON.stringify(recovered.candidates.map((c) => c.name)))
}

/* ---- REGRESSION: 诊断开关也是现读的（2026-10-19） ---- */
{
  const cell = (initial) => {
    let value = initial
    return { get: () => value, set: (next) => { value = next } }
  }
  const verbose = cell(false)
  const ctxDiag = fakeCtx()
  mod.apply(ctxDiag, { verbose, skillDir: 'skills/project-work-log' })
  const [provider] = ctxDiag.providers.map((create) => create(control))
  const quietMark = ctxDiag.logs.length
  await provider.list({ cwd: 'X', scope: {} })
  ok(!ctxDiag.logs.slice(quietMark).some((entry) => String(entry[1]).startsWith('worklog[trace] ')),
     'verbose=false emits no trace after the mount')

  verbose.set(true)                         // ← Loader 的 volatile-only 提交 = 改引用里的值
  ctxDiag.emit('loader/volatile-update', [['verbose']])
  const loudMark = ctxDiag.logs.length
  await provider.list({ cwd: 'X', scope: {} })
  ok(ctxDiag.logs.slice(loudMark).some((entry) => String(entry[1]).startsWith('worklog[trace] ')),
     'flipping verbose takes effect on the next trace() — no restart')

  verbose.set(false)                        // 别把 module 级诊断状态留给后面的用例
  ctxDiag.emit('loader/volatile-update', [['verbose']])
}

/* ---- diagnostics: one switch decides WHETHER, the environment decides WHERE ---- */
const ctxVerbose = fakeCtx()
mod.apply(ctxVerbose, { verbose: true })
ok(ctxVerbose.logs.some((entry) => String(entry[1]).startsWith('worklog[trace] ')),
   'verbose=true sends the trace to the host log when no trace file is armed',
   JSON.stringify(ctxVerbose.logs.slice(0, 3)))
const ctxQuiet = fakeCtx()
mod.apply(ctxQuiet, {})
ok(!ctxQuiet.logs.some((entry) => String(entry[1]).startsWith('worklog[trace] ')),
   'verbose=false emits no trace at all', JSON.stringify(ctxQuiet.logs))
{
  // Fixtures stay outside the repo: a harness must not leave things in the tree it verifies.
  const dir = mkdtempSync(join(tmpdir(), 'dsh-lore-trace-'))
  const target = join(dir, 'trace.log')
  const saved = process.env.DSH_WORKLOG_TRACE
  process.env.DSH_WORKLOG_TRACE = target
  try {
    const ctxFiled = fakeCtx()
    mod.apply(ctxFiled, { verbose: true })
    const written = readFileSync(target, 'utf8')
    ok(written.includes('apply'),
       'with DSH_WORKLOG_TRACE set the same lines go to that file instead', written.slice(0, 80))
    ok(!ctxFiled.logs.some((entry) => String(entry[1]).startsWith('worklog[trace] ')),
       'and not to the host log — the env var decides where, it does not decide whether')
  } finally {
    if (saved === undefined) delete process.env.DSH_WORKLOG_TRACE
    else process.env.DSH_WORKLOG_TRACE = saved
    rmSync(dir, { recursive: true, force: true })
  }
}

/* ---- liveness: a provider re-reads, so an edit changes the body ---- */
const worklogPath = `${PKG}/skills/project-work-log/SKILL.md`
const before = (await pWorklog.get((await pWorklog.list()).candidates[0])).content.length
try {
  writeFileSync(worklogPath, `${worklogText}\n<!-- liveness probe -->\n`)
  const after = (await pWorklog.get((await pWorklog.list()).candidates[0])).content.length
  ok(after > before, 'get() re-reads the file, so an edit appears without a host restart',
     `${before} -> ${after}`)
} finally {
  writeFileSync(worklogPath, worklogText)
}
ok(readFileSync(worklogPath, 'utf8') === worklogText, 'the harness restored the worklog file')

/* ---- config coercion ---- */
const ctxB = fakeCtx()
mod.apply(ctxB, { userInvocable: false })
const pB = mountAll(ctxB)[0]
const defB = await pB.get((await pB.list()).candidates[0])
ok(defB.invocation.userInvocable === false, 'config can withdraw the user surface')
ok(defB.invocation.modelInvocable === true, 'config leaves the model surface intact')

const ctxC = fakeCtx()
mod.apply(ctxC, { modelInvocable: 'yes', bogusKey: 1 })
ok(ctxC.providers.length === 1 + extraBundledSkills().length,
   'a non-boolean / unknown config value does not break the mount')
ok(ctxC.logs.some(([level, m]) => level === 'warn' && m.includes('bogusKey')),
   'unknown config keys are reported', JSON.stringify(ctxC.logs))

const ctxD = fakeCtx()
mod.apply(ctxD, null)
ok(ctxD.providers.length === 1 + extraBundledSkills().length,
   'a null config does not break the mount')

const ctxE = fakeCtx()
mod.apply(ctxE, { skillDir: `${PKG}/no/such/dir` })
// 2026-10-14 起 provider **常驻注册**（开关与路径现读），所以"文件不在"不再表现为
// "一个 provider 都没有"，而是"显式 provider 还在、但服务 0 个 + 装载期报一条错"。
// 注意随包 bundle 那一路：`skills/` 是**按 `skillDir` 的父目录**枚举的，目录不存在，
// 于是 extras 自然为 0（这是 `listBundledSkills` 的既有行为）。
ok(ctxE.providers.length === 1,
   'a missing bundle still registers its provider (registration is not file-gated)',
   String(ctxE.providers.length))
{
  const catalogs = []
  for (const provider of mountAll(ctxE)) catalogs.push((await provider.list({})).candidates.length)
  ok(catalogs[0] === 0,
     'and it serves no skill when its directory does not exist',
     JSON.stringify(catalogs))
}
ok(errorsIn(ctxE).length === 1, 'the missing bundle is reported, not swallowed',
   JSON.stringify(ctxE.logs))

const ctxG = fakeCtx()
mod.apply(ctxG, { verbose: true })
ok(ctxG.logs.some(([level, m]) => level === 'info' && m.includes('project-work-log')),
   'verbose logs the worklog skill')

/* ---- DEGRADED CONTEXTS ------------------------------------------------
   `ctx.logger` is not something this plugin can rely on: only `skills` is
   declared in `inject`, and a missing, partial, or throwing logger used to make
   `apply()` throw — a crash during mount, over a log line. These pin the rule that
   logging never takes the row down, and that the message is not silently dropped
   when the host sink is unusable. */
const NOOP_SKILLS = () => ({ registerProvider: () => () => {} })

for (const [label, makeCtx] of [
  ['no logger at all', () => ({ skills: NOOP_SKILLS() })],
  ['logger is an empty object', () => ({ logger: {}, skills: NOOP_SKILLS() })],
  ['logger.warn is not a function', () => ({
    logger: { warn: 42, error() {}, info() {} }, skills: NOOP_SKILLS(),
  })],
  ['logger methods throw', () => ({
    logger: {
      error() { throw new Error('sink is broken') },
      warn() { throw new Error('sink is broken') },
      info() {},
    },
    skills: NOOP_SKILLS(),
  })],
]) {
  let survived = true
  let detail = ''
  try {
    // A missing bundle exercises the error path, which is where the old code threw.
    mod.apply(makeCtx(), { skillDir: `${PKG}/no/such/dir`, bogusKey: 1 })
  } catch (error) {
    survived = false
    detail = `${error.constructor.name}: ${error.message}`
  }
  ok(survived, `apply() survives a degraded logger (${label})`, detail)
}

// The fallback must actually report, not swallow: with no usable sink the message
// goes to console.error, which is the only place left.
{
  const seen = []
  const original = console.error
  console.error = (...args) => { seen.push(args.join(' ')) }
  try {
    mod.apply({ skills: NOOP_SKILLS }, { skillDir: `${PKG}/no/such/dir` })
  } finally {
    console.error = original
  }
  ok(seen.some((m) => m.includes('skill bundle')),
     'an unusable logger falls back to console.error instead of dropping the message',
     JSON.stringify(seen))
}

/* ---- ACTIONABLE ERROR MESSAGES ---------------------------------------- */
{
  const messages = []
  mod.apply({ logger: { error: (m) => messages.push(String(m)), warn() {}, info() {} }, skills: NOOP_SKILLS() },
    { skillDir: `${PKG}/no/such/dir` })
  const msg = messages[0] ?? ''
  ok(msg.includes('not found'), 'a missing bundle says "not found", not a bare ENOENT', msg)
  ok(msg.includes('SKILL.md'), 'a missing bundle names the file it looked for')
  ok(msg.includes('skillDir'), 'a missing bundle names the config that resolves it')
  ok(!msg.includes('ENOENT'), 'a missing bundle does not leak the raw ENOENT wording', msg)
  ok(!/Error:\s/.test(msg), 'a missing bundle is not prefixed with a redundant "Error:"', msg)
}

/* A malformed bundle must not print the same path twice. */
{
  const dir = `${import.meta.dirname ?? '.'}/.badbundle-probe`
  const fs = await import('node:fs')
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(`${dir}/SKILL.md`, '# no frontmatter here\n\nbody\n')
  const messages = []
  try {
    mod.apply({ logger: { error: (m) => messages.push(String(m)), warn() {}, info() {} }, skills: NOOP_SKILLS() },
      { skillDir: dir })
    const msg = messages[0] ?? ''
    const occurrences = msg.split(dir.replaceAll('\\', '/')).length - 1
    ok(msg.includes('invalid skill bundle'), 'a malformed bundle is reported as invalid', msg)
    ok(occurrences <= 1, 'a malformed bundle prints its path only once', `${occurrences}x in: ${msg}`)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
}

/* ---- A MISSING REGISTRY IS REPORTED, NOT THROWN ---------------------- */
{
  for (const [label, skills] of [
    ['ctx.skills absent', undefined],
    ['registerProvider is not a function', { registerProvider: 42 }],
  ]) {
    const messages = []
    let survived = true
    let detail = ''
    try {
      mod.apply({ logger: { error: (m) => messages.push(String(m)), warn() {}, info() {} }, skills }, {})
    } catch (error) {
      survived = false
      detail = `${error.constructor.name}: ${error.message}`
    }
    ok(survived, `a missing registry does not throw (${label})`, detail)
    ok(messages.some((m) => m.includes('registerProvider')),
       `a missing registry names what is absent (${label})`, JSON.stringify(messages))
  }
}

/* ------------------------------------------------------------------ total */

const failed = results.filter(([good]) => !good)
console.log(`\n${results.length - failed.length}/${results.length} passed`)
process.exit(failed.length === 0 ? 0 : 1)
