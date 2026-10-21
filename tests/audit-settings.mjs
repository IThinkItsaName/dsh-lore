// Status route + settings-store contract, driven directly.
//
// The route handler is exported from `lib/index.js` for exactly this reason: a
// handler registered inside a `ctx.effect` is otherwise only reachable through a
// live HTTP server and a browser, and neither is available here. So the handler is
// called with a fake `req` and a fake `res` (a recorder), which is enough to pin
// what decides whether the plugin's status block works at all:
//
//   1. GET reports ONLY runtime state — where the settings are read from, and the
//      memory system's size. It carries no configuration: that moved to the host's
//      own settings channel (`ctx.configForms` + `dsh-config-editor`), and a route
//      that still served a document would be a second source of truth for the same
//      values — exactly the class of defect this project treats as a bug.
//   2. It has NO write verb. POST/PUT/DELETE answer 405 with `allow: GET, HEAD`,
//      and the legacy settings file is left byte-identical.
//   3. The memory readout is honest: counts when it can read them, `null` when the
//      root does not exist — never a zero, which would claim "nothing registered".
//   4. The route is registered as `(kind: 'exact', path)` and the disposer is
//      RETURNED — a plugin reload that leaves it behind makes the host throw
//      "duplicate exact route" and fails activation outright.
//
// Two stores are still real, and both are covered below: the profile patch (a host
// with `configEditor`, where the official channel writes) and this plugin's own
// file (a host with no editor — headless — where these values have nowhere else to
// live, and which a user edits by hand).
//
//   node tests/audit-settings.mjs
import { readFileSync, existsSync, mkdtempSync, mkdirSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { ok, skip, report, problems } from './_report.mjs'
import { PKG, extraBundledSkills } from './_pkg.mjs'


/* ---- a settings file and a memory root inside a temp home, so nothing real is
 * touched. The memory root matters as much as the settings path: without the
 * override, `readMemorySummary()` would report the DEVELOPER's own memory
 * directory, and an assertion over it is either vacuous or machine-dependent. ---- */
const sandbox = mkdtempSync(join(tmpdir(), 'dsh-lore-settings-'))
const settingsPath = join(sandbox, 'worklog', 'settings.json')
const memoryRoot = join(sandbox, 'memory')
// The directory, not the file: nothing in the plugin creates it any more (it used to be the write
// path's job), and these tests write the file by hand to simulate a headless profile.
mkdirSync(join(sandbox, 'worklog'), { recursive: true })
process.env.DSH_WORKLOG_SETTINGS = settingsPath
process.env.DSH_WORKLOG_MEMORY = memoryRoot

const mod = await import(pathToFileURL(`${PKG}/lib/index.js`).href)
const { createStatusRouteHandler, effectiveSettings, projectDefaults } = mod

/**
 * The project-side keys, spelled out HERE rather than imported from the module.
 *
 * `PROJECT_DEFAULT_KEYS` is the module's own list, and a test that read it would
 * pass however it changed — including the change that folded `container`,
 * `lessons` and `mode` back into `effectiveSettings`, which is the regression the
 * checks below exist to catch.
 */
const PROJECT_KEYS = ['container', 'lessons', 'mode']

/** The exact response shape. A key beyond these would mean a second source of
 * truth for configuration has come back. */
const STATUS_KEYS = 'error,memory,path,source'

/* ---- fakes ---- */

/** An async-iterable request body, like the one Node hands a handler. */
async function* bodyOf(text) {
  if (text === undefined) return
  yield Buffer.from(text, 'utf8')
}

function fakeRequest(method, body) {
  return {
    method,
    async *[Symbol.asyncIterator]() { yield* bodyOf(body) },
  }
}

/** Records what the handler wrote, so the assertions read like the response. */
function fakeResponse() {
  return {
    status: null,
    headers: null,
    body: '',
    writeHead(status, headers) { this.status = status; this.headers = headers ?? null },
    end(chunk) { if (chunk !== undefined) this.body += String(chunk) },
  }
}

const handler = createStatusRouteHandler()

async function call(method, body) {
  const res = fakeResponse()
  await handler(fakeRequest(method, body), res)
  let json = null
  try {
    json = JSON.parse(res.body)
  } catch { /* asserted by the caller when it matters */ }
  return { res, json }
}

/* ---- 1. GET with no file and no memory root: the honest empty answer ---- */
{
  const { res, json } = await call('GET')
  ok(res.status === 200, 'GET answers 200', String(res.status))
  ok(json !== null, 'GET answers JSON')
  ok(Object.keys(json ?? {}).sort().join(',') === STATUS_KEYS,
    'GET reports exactly source/path/memory/error — no configuration document',
    Object.keys(json ?? {}).join(','))
  ok(json?.path === settingsPath, 'GET reports the settings path it would read', String(json?.path))
  ok(json?.source === 'file',
    'without a profile config editor, the plugin\u2019s own file IS the source', String(json?.source))
  ok(json?.error === null, 'a missing file is not an error', String(json?.error))
  ok(json?.memory === null,
    'a missing memory root reports null, not a zero (0 workspaces would be a different claim)',
    JSON.stringify(json?.memory))
  ok(res.headers?.['cache-control'] === 'no-store',
    'the response forbids caching (a stale readout is a real bug)')
  ok(!existsSync(settingsPath), 'and reading the status created nothing on disk')
}

/* ---- 2. the memory readout, when there is one ---- */
{
  mkdirSync(join(memoryRoot, 'inbox'), { recursive: true })
  writeFileSync(join(memoryRoot, 'INDEX.md'), 'x'.repeat(120), 'utf8')
  writeFileSync(join(memoryRoot, 'workspaces.json'), JSON.stringify({ a: {}, b: {} }), 'utf8')
  writeFileSync(join(memoryRoot, 'inbox', 'one.md'), 'hi', 'utf8')
  // Not a markdown file: the count must be of inbox ENTRIES, not of everything.
  writeFileSync(join(memoryRoot, 'inbox', 'notes.txt'), 'hi', 'utf8')

  const { json } = await call('GET')
  ok(json?.memory?.workspaces === 2, 'the workspace count comes from the registry',
    JSON.stringify(json?.memory))
  ok(json?.memory?.inbox === 1, 'the inbox count is of markdown entries only',
    JSON.stringify(json?.memory))
  ok(json?.memory?.indexChars === 120, 'the index size is the length of INDEX.md',
    JSON.stringify(json?.memory))

  rmSync(memoryRoot, { recursive: true, force: true })
  const { json: gone } = await call('GET')
  ok(gone?.memory === null, 'and it goes back to null when the root disappears',
    JSON.stringify(gone?.memory))
}

/* ---- 3. a corrupt settings file is reported, not fatal ---- */
{
  mkdirSync(join(sandbox, 'broken'), { recursive: true })
  const brokenPath = join(sandbox, 'broken', 'settings.json')
  writeFileSync(brokenPath, '{ oops', 'utf8')
  process.env.DSH_WORKLOG_SETTINGS = brokenPath
  const warnings = []
  const loud = createStatusRouteHandler((level, message) => warnings.push([level, message]))
  const res = fakeResponse()
  await loud(fakeRequest('GET'), res)
  const json = JSON.parse(res.body)
  ok(res.status === 200, 'a corrupt settings file still answers 200', String(res.status))
  ok(typeof json?.error === 'string' && json.error !== '',
    'the corrupt file is reported through `error`', String(json?.error))
  ok(warnings.some(([level, message]) => level === 'warn' && message.includes('unusable')),
    'and the host log says so too (a silent fallback is how settings "stop working")',
    JSON.stringify(warnings))
  process.env.DSH_WORKLOG_SETTINGS = settingsPath
}

/* ---- 4. there is no write verb, and the file is untouchable ---- */
{
  writeFileSync(settingsPath, JSON.stringify({ verbose: false }), 'utf8')
  const before = readFileSync(settingsPath, 'utf8')
  for (const [method, payload] of [
    ['POST', JSON.stringify({ verbose: true })],
    ['PUT', JSON.stringify({ verbose: true })],
    ['PATCH', '{}'],
    ['DELETE', undefined],
  ]) {
    const { res } = await call(method, payload)
    ok(res.status === 405, `${method} answers 405 (configuration is not written over HTTP)`,
      `${res.status} ${String(res.body).slice(0, 80)}`)
    ok(res.headers?.allow === 'GET, HEAD',
      `the 405 for ${method} names exactly the allowed methods`, String(res.headers?.allow))
    ok(res.body === '', `the 405 for ${method} carries no body (nothing was parsed)`)
  }
  ok(readFileSync(settingsPath, 'utf8') === before,
    'no refused write touched the legacy file')

  const head = await call('HEAD')
  ok(head.res.status === 200, 'HEAD is accepted beside GET', String(head.res.status))
}

/* ---- 5. the mount contract: exact kind, one path, disposer returned ---- */
{
  const routes = []
  let disposed = 0
  const ctx = {
    get: (name) => (name === 'webServer'
      ? { register: (route) => { routes.push(route); return () => { disposed += 1 } } }
      : null),
  }
  const dispose = mod.mountStatusRoute(ctx, () => {})
  ok(routes.length === 1, 'mountStatusRoute registers exactly one route', String(routes.length))
  ok(routes[0]?.kind === 'exact', 'the route is kind "exact"', String(routes[0]?.kind))
  ok(routes[0]?.path === '/plugins/dsh-lore/status.json',
    'the route path matches the client half\'s STATUS_URL', String(routes[0]?.path))
  ok(typeof routes[0]?.handler === 'function', 'the route carries a handler')
  ok(typeof dispose === 'function', 'mountStatusRoute RETURNS a disposer')
  dispose()
  ok(disposed === 1, 'the disposer releases the route exactly once', String(disposed))
  dispose()
  ok(disposed === 1, 'the disposer is idempotent (a double cleanup cannot double-release)')

  // 2026-10-21：页面上那块「当前状态」删掉了（工作区数 / 待收 / 索引字数），客户端
  // 不再读这个端点 —— 它现在**没有消费者**。端点本身保留：排障时仍可 curl，而且删掉它
  // 要动 `lib/index.js` 里与它绑在一起的统计逻辑。所以这条断言记录的是"故意留的孤儿"：
  // 客户端**不该**再出现这个路径，除非有人连读取一起加回来。
  const clientSource = readFileSync(`${PKG}/lib/client.js`, 'utf8')
  ok(!clientSource.includes(routes[0].path),
    'the client no longer names the status path (its only consumer was removed on 2026-10-21)',
    clientSource.includes(routes[0].path) ? 'lib/client.js still references it' : '')

  const withoutServer = mod.mountStatusRoute({ get: () => null }, () => {})
  ok(typeof withoutServer === 'function',
    'a missing webServer yields a disposer rather than throwing (headless hosts activate)')
  // 真断言而不是 `ok(true, …)`：以前这里靠"调用它如果抛就把整支 harness 掀掉"来当证据，
  // 于是失败长得像崩溃、也不进 `problems`（审查报告 F13）。
  let cleanupError = ''
  try { withoutServer() } catch (error) { cleanupError = `threw: ${error}` }
  ok(cleanupError === '', 'cleaning up before the route was ever registered is safe', cleanupError)
}

/* ---- 6. effectiveSettings / projectDefaults on their own ---- */
{
  const eff = effectiveSettings({})
  ok(eff.skillDir === 'skills/project-work-log', 'effectiveSettings applies the skillDir default',
    eff.skillDir)
  ok(eff.skillFile === 'SKILL.md',
    'effectiveSettings resolves skillFile (apply() reads it; no surface offers a control for it)',
    String(eff.skillFile))
  ok(eff.skillEnabled === true && eff.userInvocable === true,
    'and the work-log defaults', `${eff.skillEnabled}/${eff.userInvocable}`)

  // The point of the split, and the check whose absence let it drift: `effective`
  // is the options apply() reads, so a stored project-side default in it would be
  // the module claiming plugin effect it does not have. Checked against a document
  // that STATES all three, so a missing key cannot be a side effect of `{}`.
  for (const [label, document] of [
    ['an empty document', {}],
    ['a document stating all three', { container: 'notes', lessons: 'kb', mode: 'digest' }],
  ]) {
    const resolved = effectiveSettings(document)
    for (const key of PROJECT_KEYS) {
      ok(!(key in resolved),
        `effectiveSettings does not carry the project key "${key}" (${label})`,
        Object.keys(resolved).join(', '))
    }
  }

  const stored = projectDefaults({ container: 'notes', lessons: 'kb', mode: 'digest' })
  ok(stored.appliedByPlugin === false,
    'projectDefaults marks the group as not applied by the plugin')
  ok(Object.keys(stored.values).sort().join(',') === PROJECT_KEYS.slice().sort().join(','),
    'projectDefaults.values carries exactly the stored-but-unread keys',
    Object.keys(stored.values).join(', '))
  ok(stored.values.container === 'notes' && stored.values.lessons === 'kb'
    && stored.values.mode === 'digest',
    'projectDefaults reports what the document states', JSON.stringify(stored.values))

  const fallback = projectDefaults({})
  ok(fallback.values.container === 'work_log' && fallback.values.lessons === 'lessons'
    && fallback.values.mode === 'full',
    'projectDefaults applies the documented defaults', JSON.stringify(fallback.values))
  ok(projectDefaults({ mode: 'nope' }).values.mode === 'full',
    'a hand-edited unusable mode falls back to the documented default',
    JSON.stringify(projectDefaults({ mode: 'nope' }).values))
}

/* ---- 7. apply() on a host with no editor: the file is the store ---- */
{
  /** Run apply() once with the given layers and report what it mounted. */
  function runApply(row) {
    const creates = []
    const logs = []
    mod.apply({
      logger: {
        info: (m) => logs.push(['I', String(m)]),
        warn: (m) => logs.push(['W', String(m)]),
        error: (m) => logs.push(['E', String(m)]),
      },
      skills: { registerProvider: (create) => { creates.push(create); return () => {} } },
      // The route has no web server here; the effect still runs its callback
      // and its returned disposer is what matters.
      effect: (callback) => { callback() },
    }, row)
    const errors = logs.filter(([level]) => level === 'E')
    return { creates, errors, logs }
  }

  /**
   * 谁**真的在服务技能**：把每个 provider 叫一次 `list()`。
   *
   * 2026-10-14 起 provider **全部常驻注册**（开关与路径现读，为的是"改完即时生效"），
   * 所以"几个 provider"不再是"服务几个技能"的等价物 —— 断言要问的是后者。
   */
  async function served(run) {
    const names = []
    for (const create of run.creates) {
      const provider = create({ signal: new AbortController().signal, invalidate: () => {} })
      const obs = await provider.list()
      for (const candidate of obs.candidates ?? []) names.push(candidate.name)
    }
    return names
  }

  const row = {
    skillDir: 'skills/project-work-log',
    skillEnabled: true,
  }

  // The row says ON, the file says OFF: the file must win, or a headless user's
  // hand-edited file would be inert — this bundle's patch declares every one of
  // these keys outright.
  writeFileSync(settingsPath, JSON.stringify({ skillEnabled: false }), 'utf8')
  const fileOff = runApply(row)
  ok((await served(fileOff)).join(',') === extraBundledSkills().join(','),
    'the settings file beats the row config (file false with row true → skill not served)',
    `${(await served(fileOff)).join(',')}（providers=${fileOff.creates.length}）`)
  ok(fileOff.errors.length === 0, 'apply() logged no error', JSON.stringify(fileOff.logs))

  writeFileSync(settingsPath, JSON.stringify({ skillEnabled: true }), 'utf8')
  const fileOn = runApply({ ...row, skillEnabled: false })
  ok((await served(fileOn)).length === 1 + extraBundledSkills().length,
    'the settings file beats the row config (file true with row false → the skill is served)',
    `${(await served(fileOn)).join(',')}`)

  writeFileSync(settingsPath, JSON.stringify({ userInvocable: false }), 'utf8')
  const rowOnly = runApply({ ...row, skillEnabled: false })
  ok((await served(rowOnly)).join(',') === extraBundledSkills().join(','),
    'a key the file does not state still comes from the row config (row false → skill not served)',
    `${(await served(rowOnly)).join(',')}（providers=${rowOnly.creates.length}）`)
}

/* ---- 8. the patch row and the documented config surface still agree ---- */
{
  const patch = readFileSync(`${PKG}/cordis.patch.yml`, 'utf8')
  for (const key of ['skillDir', 'modelInvocable', 'userInvocable', 'verbose']) {
    ok(patch.includes(`${key}:`), `the bundle patch still declares ${key}`,
      key)
  }
  for (const key of ['guidelinesEnabled', 'guidelinesLanguage', 'guidelinesDir']) {
    ok(!patch.includes(`${key}:`), `the bundle patch no longer declares ${key}`, key)
  }
  ok(!patch.includes('container:') && !patch.includes('lessons:') && !patch.includes('mode:'),
    'and it declares none of the project-side keys (those are not plugin configuration)')
}


/* ---- 8b. SETTINGS.md 的字段表不能与 Config 漂移（2026-10-18 复核 low） ---- */
{
  // 根目录那份 SETTINGS.md 是给人读的，之前没有任何测试读它：Config 加了
  // `sessionsCrossWorkspace` 之后它仍写 13 个字段，直到复核才发现。只核对
  // 「已知配置键」那一节里的表行，别的表格（环境变量、验证记录）不掺进来。
  const doc = readFileSync(`${PKG}/SETTINGS.md`, 'utf8')
  const section = doc.split('## 已知配置键')[1]?.split('\n## ')[0] ?? ''
  const documented = new Set()
  for (const line of section.split('\n')) {
    const m = /^\|\s*`([A-Za-z][A-Za-z0-9]*)`\s*\|/.exec(line)
    if (m) documented.add(m[1])
  }
  const declared = new Set(Object.keys(mod.Config.dict))
  const missing = [...declared].filter((key) => !documented.has(key))
  const extra = [...documented].filter((key) => !declared.has(key))
  ok(missing.length === 0, 'SETTINGS.md 的配置键表列全了 Config 的每个字段',
    `缺：${missing.join(', ') || '无'}`)
  ok(extra.length === 0, 'SETTINGS.md 的配置键表没有 Config 不认识的字段',
    `多：${extra.join(', ') || '无'}`)
}


/* ==========================================================================================
 * The official path: when the host provides `configEditor`, the profile patch is the store.
 *
 * Everything above exercises the **fallback** — a host without the editor, where this plugin's own
 * file is the only place these values can live (a headless profile; the harness itself). Both paths
 * have to keep working, and they are not the same feature: the fallback is not a shim to delete
 * later, and the official path is where a desktop profile now keeps its settings.
 *
 * What is pinned below: the status route says which store is live, names the patch, and does NOT
 * read the legacy file at all (a corrupt one must not even produce a warning); `apply()` resolves
 * its options from the config; and a pre-existing settings file is migrated into the profile once —
 * then archived, so the user's configuration is neither lost nor silently ignored afterwards.
 * ========================================================================================== */

/** A `configEditor` fake: two layers, because the real one has two and the difference is the bug.
 *
 * `entry.options.config` is the config of whichever patch CREATED the row — for this bundle that
 * is its own `insert:` in `cordis.patch.yml`, which declares four of our keys. `configuration()`
 * reports `override`: the profile patch's own `config:` block, i.e. what the USER has stated.
 *
 * This fake used to keep only the first, and default it to `{}` — which hid the distinction
 * entirely, so the migration looked right while it archived the legacy file and copied nothing.
 * Measured on a real profile on 2026-09-29.
 */
const BUNDLE_LAYER = {
  skillDir: 'skills/project-work-log', modelInvocable: true, userInvocable: true, verbose: false,
}

function fakeEditor(override = {}, entryConfig = BUNDLE_LAYER) {
  const entry = { options: { id: 'include:dsh-lore', name: 'dsh-lore', config: { ...entryConfig } } }
  const layers = { override: structuredClone(override) }
  const calls = []
  return {
    entry,
    calls,
    layers,
    documentPath: join(sandbox, 'cordis.patch.yml'),
    entries: () => [entry],
    configuration: () => [{ entry, inherited: structuredClone(entryConfig), override: structuredClone(layers.override) }],
    async edit(target, change) {
      const next = change(structuredClone(entry.options.config), structuredClone(entryConfig))
      calls.push({ target, next })
      layers.override = { ...next }
      entry.options.config = { ...entryConfig, ...next }
    },
  }
}

{
  // A stale file must lose to the profile: that is the whole point of moving the
  // store. It is CORRUPT on purpose — a status read that still consulted it would
  // report an error and log a warning, both of which are asserted absent below.
  writeFileSync(settingsPath, '{ not json at all', 'utf8')
  const editor = fakeEditor({ userInvocable: false, verbose: true })
  const warnings = []
  const withEditor = createStatusRouteHandler((level, message) => warnings.push([level, message]), { configEditor: editor })

  const getRes = fakeResponse()
  await withEditor(fakeRequest('GET'), getRes)
  const got = JSON.parse(getRes.body)
  ok(got.source === 'config', 'GET says the config is the source', JSON.stringify(got.source))
  ok(String(got.path).includes('cordis.patch.yml'),
    'and names the patch as the file to edit', String(got.path))
  ok(got.error === null && warnings.length === 0,
    'it does not read the legacy file at all (a corrupt one produces no error and no warning)',
    `${String(got.error)} / ${JSON.stringify(warnings)}`)
  ok(Object.keys(got).sort().join(',') === STATUS_KEYS,
    'the response shape is the same on both stores (the card renders one thing)',
    Object.keys(got).join(','))

  // A write verb is refused here too, and nothing reaches the editor.
  const postRes = fakeResponse()
  await withEditor(fakeRequest('POST', JSON.stringify({ userInvocable: true })), postRes)
  ok(postRes.status === 405, 'a save attempt through HTTP is refused on the official path too',
    String(postRes.status))
  ok(editor.calls.length === 0, 'and no write reached configEditor',
    String(editor.calls.length))

  // `apply()` has to resolve its options from the config rather than the file. `verbose` is the
  // observable one: it is what prints the "serving skill" line at mount.
  //
  // The values go in as the **row config** — that is the object the loader hands `apply()`.
  const archived = `${settingsPath}.migrated`
  rmSync(archived, { force: true })
  rmSync(settingsPath, { force: true })
  const logs = []
  const applyEditor = fakeEditor({ verbose: true, skillDir: 'skills/project-work-log' })
  mod.apply({
    logger: {
      info: (m) => logs.push(['I', String(m)]),
      warn: (m) => logs.push(['W', String(m)]),
      error: (m) => logs.push(['E', String(m)]),
    },
    skills: { registerProvider: () => () => {} },
    effect: (callback) => { callback() },
    configEditor: applyEditor,
  }, { verbose: true, skillDir: 'skills/project-work-log' })
  ok(logs.some(([level, message]) => level === 'I' && message.includes('serving skill')),
    'apply() reads verbose from the profile config', JSON.stringify(logs))
  ok(!logs.some(([level]) => level === 'E'), 'and logs no error on the official path',
    JSON.stringify(logs))

  /* ---- migration: a pre-Config settings file is folded into the patch, once ---- */
  // The regression this block exists for: the bundle's own `insert:` states four of our keys, and
  // the migration's guard MUST NOT read that as "the profile already owns them" — that is what made
  // it archive the file without migrating. `fakeEditor({})` is exactly that profile shape: bundle
  // layer populated, user layer empty.
  writeFileSync(settingsPath, JSON.stringify({ mode: 'digest', userInvocable: false }), 'utf8')
  const moving = fakeEditor({})
  const outcome = await mod.migrateLegacySettings(moving, () => {})
  ok(moving.calls.length === 1,
    'a populated BUNDLE layer does not stop the migration (the bug that shipped)',
    `${outcome} / ${moving.calls.length} edit call(s)`)
  ok(moving.calls[0]?.next?.userInvocable === false,
    'the file\u2019s value is what gets written', JSON.stringify(moving.calls[0]?.next))
  ok(!('mode' in (moving.calls[0]?.next ?? {})),
    'a project-side key is NOT migrated (it is not in Config, so the patch must not carry it)',
    JSON.stringify(moving.calls[0]?.next))
  ok(!('skillDir' in (moving.calls[0]?.next ?? {})),
    'and neither is the bundle layer\u2019s own skillDir (only the file\u2019s values are written)',
    JSON.stringify(moving.calls[0]?.next))
  ok(!existsSync(settingsPath) && existsSync(`${settingsPath}.migrated`),
    'and the file is archived rather than deleted', outcome)
  const again = await mod.migrateLegacySettings(moving, () => {})
  ok(moving.calls.length === 1 && again === 'nothing to migrate',
    'running it again is a no-op', again)

  // An empty string means "use the default" in the legacy file but "explicitly empty" in the patch,
  // and `resolveSkillDir('')` resolves to the PACKAGE ROOT — carrying it over would break the mount.
  writeFileSync(settingsPath, JSON.stringify({ skillDir: '', verbose: true }), 'utf8')
  rmSync(`${settingsPath}.migrated`, { force: true })
  const blanks = fakeEditor({})
  const blanksOutcome = await mod.migrateLegacySettings(blanks, () => {})
  ok(!('skillDir' in (blanks.calls[0]?.next ?? {})),
    'empty/blank strings are not migrated (they would become an explicit empty override)',
    `${blanksOutcome} / ${JSON.stringify(blanks.calls[0]?.next)}`)
  ok(blanks.calls[0]?.next?.verbose === true, 'while a usable value beside them still migrates')

  // A profile that already states a key wins: migration must never overwrite an explicit value.
  writeFileSync(settingsPath, JSON.stringify({ userInvocable: false }), 'utf8')
  rmSync(`${settingsPath}.migrated`, { force: true })
  const owner = fakeEditor({ userInvocable: true })
  const owned = await mod.migrateLegacySettings(owner, () => {})
  ok(owner.calls.length === 0, 'an existing profile value is never overwritten by the file', owned)
  ok(existsSync(`${settingsPath}.migrated`),
    'the file is still archived (the user layer is the authority, so there is nothing to carry)',
    owned)

  // `skillEnabled` was missing from `KNOWN_CONFIG_KEYS`, so `migratableSettingsKeys()` did not
  // list it either: a profile override `skillEnabled:false` was not "owned", migration called
  // `edit()` with the legacy value, and the card's setting was silently lost. Pin the ownership.
  writeFileSync(settingsPath, JSON.stringify({ skillEnabled: true }), 'utf8')
  rmSync(archived, { force: true })
  const skillOwner = fakeEditor({ skillEnabled: false })
  const skillOwned = await mod.migrateLegacySettings(skillOwner, () => {})
  ok(skillOwner.calls.length === 0 && existsSync(archived),
    'a profile-owned skillEnabled is never overwritten by the legacy file', skillOwned)

  // "I cannot tell what the user stated" must never be read as "the user stated nothing".
  writeFileSync(settingsPath, JSON.stringify({ userInvocable: false }), 'utf8')
  rmSync(`${settingsPath}.migrated`, { force: true })
  const blind = fakeEditor({})
  delete blind.configuration
  const blindLogs = []
  const blindOutcome = await mod.migrateLegacySettings(blind, (level, message) => blindLogs.push([level, message]))
  ok(blindOutcome === 'cannot read the profile layer' && existsSync(settingsPath),
    'an editor that cannot report the user layer leaves the file alone', blindOutcome)
  ok(blind.calls.length === 0, 'and writes nothing', String(blind.calls.length))
  ok(blindLogs.some(([level, message]) => level === 'warn' && message.includes('cannot read')),
    'and says why', JSON.stringify(blindLogs))

  // And a failed write leaves the file exactly where it was: a half-migrated store is worse than
  // no migration, because the next mount would read neither copy with confidence.
  writeFileSync(settingsPath, JSON.stringify({ userInvocable: false }), 'utf8')
  const broken = fakeEditor({})
  broken.edit = async () => { throw new Error('profile write failed') }
  const failed = []
  const failedOutcome = await mod.migrateLegacySettings(broken, (level, message) => failed.push([level, message]))
  ok(failedOutcome === 'failed' && existsSync(settingsPath),
    'a failed migration keeps the file and reports failure', `${failedOutcome} / ${String(existsSync(settingsPath))}`)
  ok(failed.some(([level, message]) => level === 'warn' && message.includes('could not migrate')),
    'and warns loudly about it', JSON.stringify(failed))
  rmSync(settingsPath, { force: true })
  rmSync(`${settingsPath}.migrated`, { force: true })
}

rmSync(sandbox, { recursive: true, force: true })
report('status route and settings stores OK') 