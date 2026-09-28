// Settings route + settings-file contract, driven directly.
//
// The route handler is exported from `lib/index.js` for exactly this reason: a
// handler registered inside a `ctx.effect` is otherwise only reachable through a
// live HTTP server and a browser, and neither is available here. So the handler
// is called with a fake `req` (an async-iterable body) and a fake `res` (a
// recorder), which is enough to pin the four things that decide whether the
// settings page works at all:
//
//   1. GET reports the document on disk, the values the plugin will use, and —
//      separately, and marked — the project-side defaults it only STORES, so the
//      page cannot render those as plugin effect.
//   2. A POST persists, and a following GET reads back what was written.
//   3. A rejected value answers 400 and does NOT touch the file.
//   4. The route is registered as `(kind: 'exact', path)` and the disposer is
//      RETURNED — a plugin reload that leaves it behind makes the host throw
//      "duplicate exact route" and fails activation outright.
//
// Precedence is checked too, because it is the one rule the whole feature rests
// on: `cordis.patch.yml` declares `guidelinesEnabled` / `guidelinesLanguage` /
// `skillDir` / `guidelinesDir` outright, so if the row config won, the page
// could never change anything.
//
//   node tests/audit-settings.mjs
import { readFileSync, existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { PKG, extraBundledSkills } from './_pkg.mjs'

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}

/* ---- a settings file inside a temp home, so nothing real is touched ---- */
const sandbox = mkdtempSync(join(tmpdir(), 'dsh-worklog-settings-'))
const settingsPath = join(sandbox, 'worklog', 'settings.json')
process.env.DSH_WORKLOG_SETTINGS = settingsPath

const mod = await import(pathToFileURL(`${PKG}/lib/index.js`).href)
const { createSettingsRouteHandler, sanitizeSettings, effectiveSettings, projectDefaults } = mod

/**
 * The project-side keys, spelled out HERE rather than imported from the module.
 *
 * `PROJECT_DEFAULT_KEYS` is the module's own list, and a test that read it would
 * pass however it changed — including the change that folded `container`,
 * `lessons` and `mode` back into `effectiveSettings`, which is the regression the
 * checks below exist to catch.
 */
const PROJECT_KEYS = ['container', 'lessons', 'mode']

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

async function call(method, body) {
  const res = fakeResponse()
  await createSettingsRouteHandler()(fakeRequest(method, body), res)
  let json = null
  try {
    json = JSON.parse(res.body)
  } catch { /* asserted by the caller when it matters */ }
  return { res, json }
}

/* ---- 1. GET with no file: defaults, and no error ---- */
{
  const { res, json } = await call('GET')
  ok(res.status === 200, 'GET answers 200', String(res.status))
  ok(json !== null, 'GET answers JSON')
  ok(json?.path === settingsPath, 'GET reports the settings path it used', String(json?.path))
  ok(json?.error === null, 'a missing file is not an error', String(json?.error))
  ok(JSON.stringify(json?.settings) === '{}',
    'a missing file reports an empty document (defaults live in `effective`)',
    JSON.stringify(json?.settings))
  ok(json?.effective?.guidelinesEnabled === true, 'effective.guidelinesEnabled defaults to true')
  ok(json?.effective?.guidelinesLanguage === 'zh', 'effective.guidelinesLanguage defaults to zh')
  // `effective` is the options apply() reads. A project-side default in it is the
  // route claiming plugin effect, which is exactly what the page then renders.
  for (const key of PROJECT_KEYS) {
    ok(!(key in (json?.effective ?? {})),
      `GET keeps the project key "${key}" out of effective (stored, not resolved)`,
      JSON.stringify(json?.effective))
  }
  ok(json?.projectDefaults?.appliedByPlugin === false,
    'GET marks the project defaults as not applied by the plugin',
    JSON.stringify(json?.projectDefaults))
  ok(json?.projectDefaults?.values?.container === 'work_log'
    && json?.projectDefaults?.values?.lessons === 'lessons'
    && json?.projectDefaults?.values?.mode === 'full',
    'GET reports the project defaults beside the marker',
    JSON.stringify(json?.projectDefaults?.values))
  ok(res.headers?.['cache-control'] === 'no-store',
    'the response forbids caching (a stale document after save is a real bug)')
}

/* ---- 2. POST persists, GET reads it back ---- */
{
  const { res, json } = await call('POST', JSON.stringify({
    guidelinesEnabled: false,
    guidelinesLanguage: 'en',
  }))
  ok(res.status === 200, 'POST answers 200', `${res.status} ${res.body.slice(0, 200)}`)
  ok(json?.settings?.guidelinesEnabled === false, 'the response echoes the stored document')
  ok(existsSync(settingsPath), 'the settings file was created', settingsPath)

  const onDisk = JSON.parse(readFileSync(settingsPath, 'utf8'))
  ok(onDisk.guidelinesEnabled === false, 'the file holds the new boolean')
  ok(onDisk.guidelinesLanguage === 'en', 'the file holds the new language')
  ok(!onDisk.modelInvocable, 'a partial POST does not invent keys for unmentioned fields')

  const back = await call('GET')
  ok(back.json?.settings?.guidelinesEnabled === false, 'a following GET reads it back (false)')
  ok(back.json?.settings?.guidelinesLanguage === 'en', 'a following GET reads it back (en)')
  ok(back.json?.effective?.guidelinesEnabled === false, 'effective follows the file')
  ok(back.json?.effective?.guidelinesLanguage === 'en', 'effective language follows the file')
}

/* ---- 3. a full-field POST, including the advanced fields ---- */
{
  const advanced = {
    guidelinesEnabled: true,
    guidelinesLanguage: 'zh',
    skillDir: 'skills/project-work-log',
    guidelinesDir: 'skills/reliability-guidelines',
    container: 'work_log',
    lessons: 'lessons',
    mode: 'digest',
  }
  const { res, json } = await call('POST', JSON.stringify(advanced))
  ok(res.status === 200, 'a full-document POST is accepted', String(res.status))
  // The page re-reads its whole state from this response, so a field only GET
  // carried would go blank after every save.
  ok(json?.projectDefaults?.values?.mode === 'digest',
    'the POST response carries the project defaults as well as GET',
    JSON.stringify(json?.projectDefaults))
  ok(json?.effective?.mode === undefined,
    'the POST response keeps the project keys out of effective',
    JSON.stringify(json?.effective))
  const onDisk = JSON.parse(readFileSync(settingsPath, 'utf8'))
  ok(Object.keys(advanced).every((key) => onDisk[key] === advanced[key]),
    'every known key round-trips', JSON.stringify(onDisk))

  const empty = await call('POST', JSON.stringify({ skillDir: '' }))
  ok(empty.res.status === 200, 'an empty string is accepted (it means "use the default")')
  ok(JSON.parse(readFileSync(settingsPath, 'utf8')).skillDir === '',
    'the empty string is stored, not silently replaced by a default')
  ok(empty.json?.effective?.skillDir === 'skills/project-work-log',
    'effective falls back to the bundled default for an empty string',
    String(empty.json?.effective?.skillDir))
}

/* ---- 4. rejected input: 400, and the file is untouched ---- */
{
  const before = readFileSync(settingsPath, 'utf8')
  for (const [label, payload] of [
    ['a wrong boolean type', { guidelinesEnabled: 'yes' }],
    ['an unknown language', { guidelinesLanguage: 'fr' }],
    ['an unknown mode', { mode: 'verbose' }],
    ['a non-object body', [1, 2, 3]],
  ]) {
    const { res, json } = await call('POST', JSON.stringify(payload))
    ok(res.status === 400, `POST with ${label} answers 400`, `${res.status} ${res.body.slice(0, 120)}`)
    ok(typeof json?.error === 'string', `the 400 for ${label} carries an error string`)
  }
  const broken = await call('POST', '{ not json')
  ok(broken.res.status === 400, 'POST with a malformed body answers 400', String(broken.res.status))
  ok(readFileSync(settingsPath, 'utf8') === before,
    'no rejected write touched the file')
}

/* ---- 5. the body cap and the method gate ---- */
{
  const huge = JSON.stringify({ container: 'x'.repeat(300 * 1024) })
  const { res } = await call('POST', huge)
  ok(res.status === 413, 'an oversized body answers 413', String(res.status))

  const del = await call('DELETE')
  ok(del.res.status === 405, 'an unsupported method answers 405', String(del.res.status))
  ok(del.res.headers?.allow === 'GET, HEAD, POST', 'the 405 names the allowed methods',
    String(del.res.headers?.allow))
}

/* ---- 6. a corrupt file is reported, not fatal ---- */
{
  const brokenPath = join(sandbox, 'broken', 'settings.json')
  process.env.DSH_WORKLOG_SETTINGS = brokenPath
  const { mkdirSync, writeFileSync } = await import('node:fs')
  mkdirSync(join(sandbox, 'broken'), { recursive: true })
  writeFileSync(brokenPath, '{ oops', 'utf8')
  const { res, json } = await call('GET')
  ok(res.status === 200, 'a corrupt settings file still answers 200', String(res.status))
  ok(typeof json?.error === 'string' && json.error !== '',
    'the corrupt file is reported through `error`', String(json?.error))
  ok(json?.effective?.guidelinesEnabled === true,
    'effective falls back to defaults for a corrupt file')
  process.env.DSH_WORKLOG_SETTINGS = settingsPath
}

/* ---- 7. unknown keys are preserved, not dropped ---- */
{
  const path = join(sandbox, 'unknown', 'settings.json')
  process.env.DSH_WORKLOG_SETTINGS = path
  const { mkdirSync, writeFileSync } = await import('node:fs')
  mkdirSync(join(sandbox, 'unknown'), { recursive: true })
  writeFileSync(path, JSON.stringify({ somethingElse: 42, guidelinesEnabled: false }), 'utf8')
  await call('POST', JSON.stringify({ guidelinesLanguage: 'en' }))
  const onDisk = JSON.parse(readFileSync(path, 'utf8'))
  ok(onDisk.somethingElse === 42,
    'a key this plugin does not read survives a save (the file is hand-editable)',
    JSON.stringify(onDisk))
  ok(onDisk.guidelinesEnabled === false, 'unmentioned known keys survive a save too')
  ok(onDisk.guidelinesLanguage === 'en', 'the posted key is applied')
  process.env.DSH_WORKLOG_SETTINGS = settingsPath
}

/* ---- 8. sanitizeSettings / effectiveSettings / projectDefaults on their own ---- */
{
  ok(sanitizeSettings({ mode: 'nope' }).error !== undefined, 'sanitizeSettings rejects a bad mode')
  ok(sanitizeSettings({ guidelinesLanguage: 'fr' }).error !== undefined,
    'sanitizeSettings rejects a bad language')
  ok(sanitizeSettings({ verbose: true }).document.verbose === true, 'sanitizeSettings accepts a boolean')
  // `knownSettingsKeys()` is what routes a key through `coerceSetting`, and the
  // project-side defaults must stay on that list: off it, the write path would
  // store them verbatim instead of validating them.
  ok(sanitizeSettings({ container: 'notes' }).document.container === 'notes',
    'a project-side default is a known key, so the page may store it')
  ok(sanitizeSettings({ container: 42 }).error !== undefined,
    'a project-side default is validated like any other known key (a number is rejected)')
  const eff = effectiveSettings({})
  ok(eff.skillDir === 'skills/project-work-log', 'effectiveSettings applies the skillDir default',
    eff.skillDir)
  ok(eff.skillFile === 'SKILL.md',
    'effectiveSettings resolves skillFile (apply() reads it, the page just cannot write it)',
    String(eff.skillFile))

  // The point of the split, and the check whose absence let it drift: `effective`
  // is the options apply() reads, so a stored project-side default in it is the
  // route claiming effect the plugin does not have. Checked against a document
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

/* ---- 9. the mount contract: exact kind, one path, disposer returned ---- */
{
  const routes = []
  let disposed = 0
  const ctx = {
    get: (name) => (name === 'webServer'
      ? { register: (route) => { routes.push(route); return () => { disposed += 1 } } }
      : null),
  }
  const dispose = mod.mountSettingsRoute(ctx, () => {})
  ok(routes.length === 1, 'mountSettingsRoute registers exactly one route', String(routes.length))
  ok(routes[0]?.kind === 'exact', 'the route is kind "exact"', String(routes[0]?.kind))
  ok(routes[0]?.path === '/plugins/dsh-worklog/settings.json',
    'the route path matches the client half\'s fetch URL', String(routes[0]?.path))
  ok(typeof routes[0]?.handler === 'function', 'the route carries a handler')
  ok(typeof dispose === 'function', 'mountSettingsRoute RETURNS a disposer')
  dispose()
  ok(disposed === 1, 'the disposer releases the route exactly once', String(disposed))
  dispose()
  ok(disposed === 1, 'the disposer is idempotent (a double cleanup cannot double-release)')

  // No web server at all: the plugin must still activate, and the cleanup must
  // still be safe.
  const withoutServer = mod.mountSettingsRoute({ get: () => null }, () => {})
  ok(typeof withoutServer === 'function',
    'a missing webServer yields a disposer rather than throwing (headless hosts activate)')
  withoutServer()
  ok(true, 'cleaning up before the route was ever registered is safe')
}

/* ---- 10. apply() mounts both skills with the settings layer on top ---- */
{
  const { writeFileSync } = await import('node:fs')

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

  const row = {
    skillDir: 'skills/project-work-log',
    guidelinesEnabled: true,
    guidelinesLanguage: 'zh',
    guidelinesDir: 'skills/reliability-guidelines',
  }

  // The row says ON, the file says OFF: the file must win, or the page would be
  // inert — this bundle's patch declares every one of these keys outright.
  writeFileSync(settingsPath, JSON.stringify({ guidelinesEnabled: false }), 'utf8')
  const fileOff = runApply(row)
  ok(fileOff.creates.length === 1 + extraBundledSkills().length,
    'the settings file beats the row config (file false with row true → one skill)',
    `${fileOff.creates.length} provider(s)`)
  ok(fileOff.errors.length === 0, 'apply() logged no error', JSON.stringify(fileOff.logs))

  // The reverse direction, and the row still wins for keys the file omits.
  writeFileSync(settingsPath, JSON.stringify({ guidelinesEnabled: true }), 'utf8')
  const fileOn = runApply({ ...row, guidelinesEnabled: false })
  ok(fileOn.creates.length === 2 + extraBundledSkills().length,
    'the settings file beats the row config (file true with row false → two skills)',
    `${fileOn.creates.length} provider(s)`)

  writeFileSync(settingsPath, JSON.stringify({ guidelinesLanguage: 'en' }), 'utf8')
  const rowOnly = runApply({ ...row, guidelinesEnabled: false })
  ok(rowOnly.creates.length === 1 + extraBundledSkills().length,
    'a key the file does not state still comes from the row config (row false → one skill)',
    `${rowOnly.creates.length} provider(s)`)

  // And the file's language actually selects the English bundle.
  const fileEn = runApply({ ...row, guidelinesEnabled: false })
  ok(fileEn.creates.length === 1 + extraBundledSkills().length,
    'the file language alone does not enable the skill')
  const both = runApply(row)
  const provider = both.creates[1]({ signal: new AbortController().signal, invalidate: () => {} })
  const catalog = await provider.list()
  const enPath = String(catalog.candidates?.[0]?.path).replaceAll('\\', '/')
  ok(enPath.includes('/en/'),
    'the file\'s guidelinesLanguage=en selects the en/ bundle', enPath)

  writeFileSync(settingsPath, JSON.stringify({ guidelinesLanguage: 'zh' }), 'utf8')
  const bothZh = runApply(row)
  const providerZh = bothZh.creates[1]({ signal: new AbortController().signal, invalidate: () => {} })
  const catalogZh = await providerZh.list()
  const zhPath = String(catalogZh.candidates?.[0]?.path).replaceAll('\\', '/')
  ok(!zhPath.includes('/en/'),
    'the file\'s guidelinesLanguage=zh selects the zh bundle', zhPath)
}

/* ---- 11. the patch row and the page must not disagree about key names ---- */
{
  const patch = readFileSync(`${PKG}/cordis.patch.yml`, 'utf8')
  for (const key of ['guidelinesEnabled', 'guidelinesLanguage', 'skillDir', 'guidelinesDir']) {
    ok(patch.includes(`${key}:`), `the bundle patch still declares ${key}`,
      'the precedence check above is only meaningful while the row states the key')
  }
}

rmSync(sandbox, { recursive: true, force: true })
console.log(problems.length === 0
  ? '\nsettings route and settings file OK'
  : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
