// Load `lib/client.js` the way the BROWSER module system does, and drive the
// plugin's configuration card without a browser.
//
// `tests/audit-client.mjs` proves the bundle is shaped right (wrapper, module
// table, dictionary parity) and `tests/audit-client-tokens.mjs` proves it only
// uses design tokens that exist. This file goes further, because shaped-right is
// not the same as works:
//
//   1. it evaluates the bundle with a stub `window.__ModuleLoader__`, exactly as
//      `packages/client/ui-trajectory/tests/client-bundle.client.spec.ts` does in
//      the DSH tree, and takes the handoff;
//   2. it drives `claimNamespace` — the pure predicate that decides WHICH settings
//      namespace is ours — with adversarial inputs, because a wrong claim writes
//      into somebody else's configuration;
//   3. it runs `apply()` against fake `locale`/`slots`/`configForms` services and
//      proves the card is mounted ONLY once our namespace is served, and taken
//      down when it stops being served;
//   4. it MOUNTS the card with a minimal React hook runtime and a stubbed
//      `fetch`, then drives it: switches, the language control, the path fields'
//      three-step commit (type → blur → write), the reject path, and the
//      read-only status block;
//   5. it asserts STRUCTURALLY that the card offers no control for the
//      project-side keys (`container` / `lessons` / `mode`), which belong to a
//      project's own `.config.json` and are changed with `journal.py config`;
//   6. it re-derives the volatile field names from `lib/index.js` and compares
//      them with the client's claim predicate, so the two can never drift apart
//      silently (a drift means the card stops appearing at all).
//
// What this still cannot decide: layout, styling, and the shell's own behaviour.
// It IS everything up to the point where only a browser can decide.
//
//   node tests/audit-client-runtime.mjs
import { readFileSync } from 'node:fs'
import { PKG } from './_pkg.mjs'

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}
const settle = async (rounds = 8) => {
  for (let i = 0; i < rounds; i += 1) await Promise.resolve()
}

const CLIENT_PATH = `${PKG}/lib/client.js`
const INDEX_PATH = `${PKG}/lib/index.js`
const code = readFileSync(CLIENT_PATH, 'utf8')

/** The namespace this machine really serves the entry under — deliberately NOT
 * the entry id: the claim must work from the schema, so a test that fed back the
 * "expected" id would pass even if the code hard-coded one. */
const SERVED_NS = 'include:dsh-worklog'

/* ------------------------------------------------------------------ React --
 * A hook runtime, not React. It keeps the two properties this file needs: a
 * state write re-renders synchronously with the new value visible to the next
 * line, and effects run against the latest committed tree. Anything React does
 * beyond that (batching, scheduling, reconciliation) is invisible to the logic
 * under test. */
function createHookRuntime() {
  const runtime = {
    hooks: [],
    index: 0,
    Component: null,
    props: null,
    tree: null,
    pendingEffects: [],
    renders: 0,
  }

  const render = () => {
    runtime.index = 0
    runtime.renders += 1
    runtime.tree = runtime.Component(runtime.props)
  }

  runtime.render = render

  const api = {
    createElement(type, props, ...children) {
      // React accepts a children array as one argument; flatten like React does.
      const flat = children.length === 1 && Array.isArray(children[0]) ? children[0] : children
      return {
        type,
        props: props ?? {},
        children: flat.filter((child) => child !== null && child !== undefined && child !== false),
      }
    },
    useState(initial) {
      const slot = runtime.index
      runtime.index += 1
      if (!(slot in runtime.hooks)) runtime.hooks[slot] = typeof initial === 'function' ? initial() : initial
      const set = (value) => {
        const current = runtime.hooks[slot]
        const next = typeof value === 'function' ? value(current) : value
        if (next === current) return
        runtime.hooks[slot] = next
        render()
      }
      return [runtime.hooks[slot], set]
    },
    useCallback(fn) {
      // The component's callbacks are pure closures over stable values; returning
      // the fresh function is behaviourally the same for this test.
      runtime.index += 1
      return fn
    },
    /**
     * Collect EVERY effect this render scheduled.
     *
     * React runs all of them; an earlier version of this file kept only the last
     * one, which silently dropped the form subscription and would have made
     * "the card re-renders when the host value changes" untestable.
     */
    useEffect(fn) {
      runtime.index += 1
      runtime.pendingEffects.push(fn)
    },
    /** Run the effects the last render scheduled; their cleanups are dropped. */
    flushEffects() {
      const effects = runtime.pendingEffects
      runtime.pendingEffects = []
      for (const effect of effects) effect()
    },
    /** Mount a function component fresh: hook slots from a previous mount must
     * not leak into this one, or state would carry over between scenarios. */
    mount(Component, props) {
      runtime.hooks = []
      runtime.index = 0
      runtime.pendingEffects = []
      runtime.Component = Component
      runtime.props = props
      render()
      return runtime.tree
    },
  }
  return { api, runtime }
}

/**
 * Depth-first walk of a `createElement` element tree.
 *
 * Yields text children too, so a text assertion can read the rendered copy
 * without re-implementing the traversal. Arrays are flattened because a
 * component that forwards `props.children` verbatim hands one through.
 */
function* walk(node) {
  if (node === null || node === undefined || node === false) return
  if (Array.isArray(node)) {
    for (const child of node) yield* walk(child)
    return
  }
  if (typeof node !== 'object') { yield node; return }
  yield node
  for (const child of childrenOf(node)) yield* walk(child)
}

/**
 * The children a node really renders.
 *
 * **This runtime expands only the top-level component**, so the marker functions
 * below are never CALLED — they exist so the tree can be identified by type, and
 * nothing more. A nested component's own render logic therefore has to be
 * modelled here when an assertion depends on it, and `DisclosureRow` is the one
 * that does: the host component renders `open && children`, so a card that put
 * its rows beside the disclosure would show a "collapsed" section with every row
 * still on screen.
 */
function childrenOf(node) {
  if (node.type === DisclosureRowMarker && node.props.open !== true) return []
  return node.children ?? []
}

/** First element in the tree for which `predicate` holds. */
function find(tree, predicate) {
  for (const node of walk(tree)) {
    if (predicate(node)) return node
  }
  return null
}

/* ------------------------------------------------------- the module table --
 * Exactly the nine-item baseline from packages/client/web/src/seed.ts, with the
 * two entries the bundle uses supplied by this file. Anything the bundle asks
 * for beyond that throws, the way the real loader's table miss does.
 *
 * The primitives are marker components: the test reads the element tree, so a
 * component only has to exist and be identifiable by its function identity — the
 * same identity the bundle receives, because both sides share these. */
function SwitchMarker(props) { return { type: 'Switch', props, children: [] } }
function InputMarker(props) { return { type: 'Input', props, children: [] } }
function SegmentedControlMarker(props) { return { type: 'SegmentedControl', props, children: [] } }
/**
 * `SegmentedTabs` renders the tab list ONLY and owns no panels, so its items are
 * data rather than children — the marker keeps them in props, where an assertion
 * can read the values, the labels and the tab/panel id pair.
 */
function SegmentedTabsMarker(props) { return { type: 'SegmentedTabs', props, children: [] } }
/** The disclosure header; its `open && children` behaviour is in `childrenOf`. */
function DisclosureRowMarker(props) { return { type: 'DisclosureRow', props, children: props.children ?? [] } }

function createRequire(hooks) {
  const primitives = {
    Switch: SwitchMarker,
    Input: InputMarker,
    SegmentedControl: SegmentedControlMarker,
    SegmentedTabs: SegmentedTabsMarker,
    DisclosureRow: DisclosureRowMarker,
  }
  const table = new Map([
    ['react', hooks],
    ['@deepseek-ai/dsh-client-ui-primitives', primitives],
  ])
  const seen = []
  const require = (specifier) => {
    seen.push(specifier)
    if (!table.has(specifier)) throw new Error(`loader table miss: ${specifier}`)
    return table.get(specifier)
  }
  return { require, seen }
}

/** Evaluate the bundle with a stub loader and return its handoff. */
function loadBundle(hooks) {
  let handoff = null
  globalThis.window = { __ModuleLoader__: { load: (value) => { handoff = value } } }
  // Deliberate: this is the loader's own evaluation model, not string eval of
  // untrusted input — the file is this package's own bundle.
  new Function(code)()
  return handoff
}

/** Element type of a node, as a printable name. */
const typeName = (type) => (typeof type === 'function' ? (type.name || 'anonymous') : String(type))

/**
 * The `.volatile()` field names `lib/index.js` actually declares.
 *
 * Re-derived from the SOURCE, not from the client's own export: the rows this file
 * serves below have to look like the ones a real host projects, or the claim would be
 * checked against the client's own belief about itself. (`export const Config = z.object({`
 * … the first `})` closes it.)
 */
const CONFIG_VOLATILE_FIELDS = (() => {
  const indexSource = readFileSync(INDEX_PATH, 'utf8')
  const start = indexSource.indexOf('export const Config = z.object({')
  const end = indexSource.indexOf('})', start)
  return start === -1 || end <= start
    ? []
    : [...indexSource.slice(start, end).matchAll(/^\s*([A-Za-z_$][\w$]*)\s*:\s*z\.[^\n]*\.volatile\(\)/gm)]
      .map((match) => match[1])
})()

/**
 * The schema the host REALLY projects, copied from a live measurement.
 *
 * Measured 2026-09-29 by running the host's own `volatileForm(Config).toJSON()`
 * (`dsh-settings/lib/types/schema.js`) over this plugin's `Config`:
 *
 *     toJSON() top-level keys : ["uid","refs"]
 *     json.properties         : UNDEFINED
 *
 * It is schemastery's **rehydration envelope**: the field names live in `refs[<uid>].dict`, and the
 * browser hands the envelope back to `schema.rehydrate(...)` to recover a real schema. There is no
 * `properties` key at the top level.
 *
 * This constant exists so the fake rows are shaped like the host's, and NOT like whatever the claim
 * happens to read. The shipped first version of the claim read `schema.properties` — a key this
 * envelope does not have — so it returned undefined on every real host and the card never appeared,
 * while 151 assertions passed against fake rows that had been built to match the code.
 */
const REAL_SCHEMA_ENVELOPE = {
  uid: 85,
  refs: {
    74: { type: 'string', meta: { default: '' } },
    85: { type: 'object', meta: { default: {} }, dict: { skillDir: { $ref: 74 } } },
  },
}

/** The values a projected row carries — the config's own defaults, keyed by field name. */
const PROJECTED_DEFAULTS = {
  skillDir: '', skillFile: 'SKILL.md', modelInvocable: true, userInvocable: true, verbose: false,
  guidelinesEnabled: true, guidelinesDir: '', guidelinesLanguage: 'zh',
  memoryEnabled: true, memoryInjectIndex: true, memoryPersonalSearchable: false,
}

/* ============================ 1. wrapper + factory ========================= */
// One module table for every section below. The bundle must be evaluated once:
// the primitives it requires and the component it registers have to come from
// the SAME evaluation, or the tree's node types are not the ones this file
// compares against.
const { api, runtime } = createHookRuntime()
const handoff = loadBundle(api)
const { require: loadRequire, seen } = createRequire(api)

let clientExports = null
{
  ok(handoff !== null, 'the bundle calls window.__ModuleLoader__.load')
  ok(handoff?.id === 'dsh-worklog', 'the handoff id is the package name', String(handoff?.id))
  ok(typeof handoff?.factory === 'function', 'the handoff carries a factory')

  clientExports = handoff.factory(loadRequire)
  ok(clientExports !== null && typeof clientExports === 'object', 'the factory returns an exports object')
  ok(typeof clientExports.apply === 'function', 'exports.apply is a function')
  ok(Array.isArray(clientExports.inject), 'exports.inject is an array', JSON.stringify(clientExports.inject))
  ok(clientExports.inject.join(',') === 'locale,slots,configForms',
    'exports.inject names locale, slots and configForms (the settings channel is a required service)',
    clientExports.inject.join(','))
  ok(clientExports.name === 'dsh-worklog', 'exports.name matches the package', String(clientExports.name))
  ok(seen.join(',') === 'react,@deepseek-ai/dsh-client-ui-primitives',
    'the factory resolves through the injected require, and only those two words',
    seen.join(','))
  ok(typeof clientExports.claimNamespace === 'function',
    'the namespace claim is exported (the test drives it directly)')
  ok(Array.isArray(clientExports.FORM_FIELDS) && clientExports.FORM_FIELDS.length === 11,
    'the claim fingerprint is exported and names eleven fields',
    JSON.stringify(clientExports.FORM_FIELDS))
  ok(clientExports.STATUS_URL === '/plugins/dsh-worklog/status.json',
    'the read-only status endpoint is the only HTTP surface the client has',
    String(clientExports.STATUS_URL))
  // The written channel moved to the official one; the old route must be gone
  // from this file's CODE. (The header comment still names the file it belongs
  // to, which is why this looks for the literal route, not the bare filename.)
  ok(!code.includes("'/plugins/dsh-worklog/settings.json'")
    && !code.includes('"/plugins/dsh-worklog/settings.json"'),
    'the client carries no string literal for the removed settings route')
  ok(clientExports.SETTINGS_URL === undefined,
    'and exports no SETTINGS_URL any more (the export was the write path)')
  ok(!/\bmethod:\s*['"]POST['"]/.test(code),
    'the client issues no POST (every write goes through ctx.configForms)')
}

/* ================== 2. the claim predicate, adversarially ================== */
{
  const claim = clientExports.claimNamespace
  const FIELDS = clientExports.FORM_FIELDS
  const valuesFor = (keys) => Object.fromEntries(keys.map((key) => [key, PROJECTED_DEFAULTS[key] ?? null]))
  const mirrorOf = (rows) => ({ getSnapshot: () => ({ status: 'ready', view: { namespaces: rows } }) })
  /** A row shaped like the host's: the real envelope for `schema`, plain JSON for `value`. */
  const rowOf = (ns, keys, extra = {}) => ({
    ns, schema: structuredClone(REAL_SCHEMA_ENVELOPE), value: valuesFor(keys), ...extra,
  })

  ok(claim(undefined) === undefined, 'no mirror at all claims nothing')
  ok(claim({}) === undefined, 'a mirror without getSnapshot claims nothing')
  ok(claim(mirrorOf([])) === undefined, 'an empty namespace list claims nothing')
  ok(claim({ getSnapshot: () => ({}) }) === undefined, 'a view with no namespaces claims nothing')
  ok(claim({ getSnapshot: () => ({ view: { namespaces: 'nope' } }) }) === undefined,
    'a non-array namespaces field claims nothing')
  ok(claim(mirrorOf([{ ns: SERVED_NS }])) === undefined,
    'a row with no value claims nothing')
  ok(claim(mirrorOf([{ ns: SERVED_NS, value: null }])) === undefined,
    'a row whose value is null claims nothing')
  ok(claim(mirrorOf([{ ns: SERVED_NS, value: [] }])) === undefined,
    'a row whose value is an array claims nothing')

  const short = FIELDS.slice(0, FIELDS.length - 1)
  ok(claim(mirrorOf([rowOf(SERVED_NS, short)])) === undefined,
    'a namespace missing even ONE of our fields claims nothing',
    `${short.length} of ${FIELDS.length}`)
  ok(claim(mirrorOf([rowOf(SERVED_NS, FIELDS.slice(1))])) === undefined,
    'a namespace missing the FIRST field claims nothing too')

  ok(claim(mirrorOf([rowOf(SERVED_NS, FIELDS)])) === SERVED_NS,
    'the full field set claims that namespace, verbatim (the id is never assumed)',
    String(claim(mirrorOf([rowOf(SERVED_NS, FIELDS)]))))
  ok(claim(mirrorOf([rowOf('dsh-worklog', FIELDS)])) === 'dsh-worklog',
    'a differently-mounted deployment (entry id == package name) is claimed too')

  ok(claim(mirrorOf([rowOf('somebody-else', ['endpoint', 'retries']), rowOf(SERVED_NS, FIELDS)])) === SERVED_NS,
    'an unrelated namespace ahead of ours does not shadow it')
  ok(claim(mirrorOf([rowOf(SERVED_NS, FIELDS), rowOf('somebody-else', FIELDS)])) === SERVED_NS,
    'our namespace later in the list is found as well')
  ok(claim(mirrorOf([rowOf(SERVED_NS, [...FIELDS, 'extraField'])])) === SERVED_NS,
    'an extra projected field does not stop the claim (a superset is still ours)')
  ok(claim(mirrorOf([rowOf('', FIELDS)])) === undefined,
    'a row with an empty ns is never claimed (it could not be addressed)')

  /* ---- the two cases that pin the MEASURED shape (the shipped bug lived here) ---- */
  ok(claim(mirrorOf([{ ns: SERVED_NS, value: valuesFor(FIELDS) }])) === SERVED_NS,
    'a row with nothing but ns + value is enough (the claim reads plain JSON, not the envelope)')
  ok(claim(mirrorOf([{
    ns: SERVED_NS,
    // The OLD signal, exactly as the fake rows used to fake it: a JSON-Schema `properties` map.
    // The real envelope has no such key, so a claim that still reads it must fail right here.
    schema: { type: 'object', properties: valuesFor(FIELDS) },
    value: {},
  }])) === undefined,
    'a legacy-shaped schema with an EMPTY value claims nothing (reading `schema.properties` is the bug)')
}

/* ================== the fake host services the card needs ================= */

/** A `configForms.describe()` mirror: snapshot store + the `ensure` nudge. */
function createMirror() {
  const listeners = new Set()
  let snapshot = { status: 'idle', view: undefined, error: null }
  let ensures = 0
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener) => { listeners.add(listener); return () => listeners.delete(listener) },
    ensure: () => { ensures += 1 },
    ensures: () => ensures,
    publish: (view) => {
      snapshot = { status: 'ready', view, error: null }
      for (const listener of [...listeners]) listener()
    },
  }
}

/**
 * A `ctx.configForms.get(ns)` form, shaped like the real
 * `ConfigFormController`: `getSnapshot` / `subscribe` / `set` / `unset` /
 * `mutate`, with `set`/`unset` expressed AS `mutate` operations — so what the
 * test records is exactly what the Host would receive on the wire.
 */
function createFormStub({ value = {}, base = {}, user = {}, writable = true, status = 'ready' } = {}) {
  const listeners = new Set()
  const mutations = []
  const state = {
    status,
    value: { ...value },
    base: { ...base },
    user: { ...user },
    revision: 1,
    writable,
    mode: 'host',
  }
  const behaviour = { reject: false, throwError: false }
  const notify = () => { for (const listener of [...listeners]) listener() }

  const form = {
    getSnapshot: () => state,
    subscribe: (listener) => { listeners.add(listener); return () => listeners.delete(listener) },
    mutate(operations) {
      mutations.push(JSON.parse(JSON.stringify(operations)))
      if (behaviour.reject) return Promise.resolve(false)
      if (behaviour.throwError) return Promise.reject(new Error('transport down'))
      for (const operation of operations) {
        const field = operation.path[0]
        if (operation.op === 'set') {
          state.user[field] = operation.value
          state.value[field] = operation.value
        } else {
          delete state.user[field]
          state.value[field] = state.base[field]
        }
      }
      state.revision += 1
      notify()
      return Promise.resolve(true)
    },
    set(field, value) { return form.mutate([{ op: 'set', path: [field], value }]) },
    unset(field) { return form.mutate([{ op: 'unset', path: [field] }]) },
  }
  form.mutations = mutations
  form.behaviour = behaviour
  form.state = state
  return form
}

/** The rows a real deployment would expose for this plugin. */
function namespaceRow(ns, keys) {
  return {
    ns,
    autoGenerate: true,
    schema: structuredClone(REAL_SCHEMA_ENVELOPE),
    revision: 1,
    applies: 'live',
    // The projected live configuration: plain JSON, one key per `.volatile()` field.
    value: Object.fromEntries(keys.map((key) => [key, PROJECTED_DEFAULTS[key] ?? null])),
    base: {},
    user: {},
  }
}

/**
 * One `apply()` world: fake locale / slots / configForms, plus the recorders the
 * assertions read.
 */
function createWorld(seed = {}) {
  const dictionaries = new Map()
  const bound = []
  const registered = []
  const injections = []
  const forms = new Map()
  const seeds = { ...seed }
  const mirror = createMirror()

  const locale = {
    bind: (ns) => {
      if (!bound.includes(ns)) bound.push(ns)
      return (key) => {
        const dict = dictionaries.get(ns)
        return dict?.zh?.[key] === undefined ? key : dict.zh[key]
      }
    },
    register: (ns, dicts) => { dictionaries.set(ns, dicts); return () => {} },
  }
  const slots = {
    inject: (name, factory) => {
      const inner = factory()
      const record = { name, live: true }
      injections.push(record)
      return () => {
        record.live = false
        if (typeof inner === 'function') inner()
      }
    },
    register: (options, component) => {
      registered.push({ options, component })
      return () => {}
    },
  }
  const configForms = {
    describe: () => mirror,
    get: (ns) => {
      if (!forms.has(ns)) forms.set(ns, createFormStub(seeds[ns]))
      return forms.get(ns)
    },
  }
  const ctx = {
    locale,
    slots,
    configForms,
    // The real `ctx.effect` runs the callback at once and keeps its disposer.
    effect: (callback) => { callback() },
  }
  return { ctx, dictionaries, bound, registered, injections, forms, mirror, seeds }
}

/** The face a slot registration injects: `hooks.<name>` becomes `use<Name>`. */
function cardProps(world, registration, extra = {}) {
  const face = typeof registration.options.inject === 'function' ? registration.options.inject() : {}
  const props = { ...extra }
  for (const [key, value] of Object.entries(face)) {
    if (key !== 'hooks') { props[key] = value; continue }
    for (const [name, store] of Object.entries(value)) {
      props['use' + name[0].toUpperCase() + name.slice(1)] = makeUseHook(store)
    }
  }
  const dict = world.dictionaries.get(registration.options.locale)?.zh ?? {}
  props.t = (key) => (dict[key] === undefined ? key : dict[key])
  return props
}

/**
 * The framework's `hooks.<name>` → `use<Name>` binding.
 *
 * It reads the store AND subscribes, so a snapshot replacement re-renders — the
 * property that makes "the card shows what the host confirmed" a real assertion
 * rather than an accident of mount order.
 */
function makeUseHook(store) {
  return (selector) => {
    api.useEffect(() => store.subscribe(() => runtime.render()), [store])
    const snapshot = store.getSnapshot()
    return typeof selector === 'function' ? selector(snapshot) : snapshot
  }
}

/* ================== 3. apply(): mount and unmount by claim ================== */
{
  const world = createWorld({ [SERVED_NS]: { value: { guidelinesEnabled: true }, base: {} } })
  clientExports.apply(world.ctx)

  ok(world.bound.join(',') === 'dsh-worklog.settings',
    'apply() binds exactly one locale namespace', world.bound.join(','))
  ok(world.dictionaries.size === 1, 'apply() registers exactly one dictionary set')
  const dicts = world.dictionaries.get('dsh-worklog.settings')
  ok(dicts?.zh !== undefined && dicts?.en !== undefined,
    'the dictionary set carries both zh and en (the register({zh,en}) form)',
    Object.keys(dicts ?? {}).join(','))
  ok(world.mirror.ensures() === 1, 'apply() nudges the lazy describe mirror once',
    String(world.mirror.ensures()))

  ok(world.registered.length === 0 && world.injections.length === 0,
    'nothing is registered before the host serves our namespace',
    `${world.registered.length} registration(s), ${world.injections.length} injection(s)`)

  world.mirror.publish({ namespaces: [namespaceRow('somebody-else', ['endpoint', 'retries'])] })
  ok(world.registered.length === 0 && world.injections.length === 0,
    'another plugin\u2019s namespace does not make us claim a page')

  world.mirror.publish({ namespaces: [namespaceRow('somebody-else', ['endpoint']), namespaceRow(SERVED_NS, CONFIG_VOLATILE_FIELDS)] })
  ok(world.registered.length === 1, 'once our namespace is served, exactly one card is registered',
    String(world.registered.length))
  ok(world.injections.length === 1 && world.injections[0].name === 'plugins.item',
    'the card is injected into the Plugins page slot (plugins.item)', world.injections.map((i) => i.name).join(','))

  const options = world.registered[0].options
  ok(options?.name === 'plugins.item', 'the registration names plugins.item', String(options?.name))
  ok(options?.id === 'dsh-worklog', 'the card id is the package name', String(options?.id))
  ok(options?.order === 50, 'the card order is 50', String(options?.order))
  ok(options?.locale === 'dsh-worklog.settings',
    'the registration declares its locale namespace (this is what injects t)', String(options?.locale))
  ok(typeof options?.label === 'function', 'label is a thunk (the shell re-evaluates it on locale change)')
  ok(options?.label() === '工作记录', 'the item label resolves through the dictionary', String(options?.label()))
  ok(typeof world.registered[0].component === 'function',
    'the registration carries a function component', typeof world.registered[0].component)

  const face = options.inject()
  ok(face?.hooks?.form === world.forms.get(SERVED_NS),
    'the injected face hands the card the form for the namespace we claimed')
  ok(typeof face?.save === 'function' && typeof face?.reset === 'function',
    'the face carries the two write actions')
  const saveResult = face.save('verbose', true)
  ok(saveResult !== null && typeof saveResult?.then === 'function',
    'saving goes through the form controller and returns its promise')
  await settle(4)
  ok(world.forms.get(SERVED_NS).mutations.length === 1,
    'the face\u2019s save reached the form as one mutation',
    JSON.stringify(world.forms.get(SERVED_NS).mutations))

  // The namespace goes away again (the plugin was disabled / the entry removed).
  world.mirror.publish({ namespaces: [namespaceRow('somebody-else', ['endpoint'])] })
  ok(world.injections[0].live === false,
    'when the namespace stops being served, the card is taken down again')

  world.mirror.publish({ namespaces: [namespaceRow(SERVED_NS, CONFIG_VOLATILE_FIELDS)] })
  ok(world.registered.length === 2 && world.injections.length === 2,
    'and it comes back when the namespace returns',
    `${world.registered.length} registration(s)`)

  // The surface itself: it must NOT also claim a Settings navigation entry.
  ok(world.registered.every((row) => row.options.name !== 'settings.section'),
    'the client registers no settings.section entry (the surface moved to the Plugins page)')
}

/* ===================== 4. the card, mounted and driven ===================== */

/** The values a real profile would project, with one field overridden. */
const SEED = {
  value: {
    skillDir: 'skills/project-work-log', skillFile: 'SKILL.md',
    modelInvocable: true, userInvocable: true, verbose: false,
    guidelinesEnabled: false, guidelinesDir: 'skills/reliability-guidelines', guidelinesLanguage: 'en',
    memoryEnabled: true, memoryInjectIndex: true, memoryPersonalSearchable: false,
  },
  base: {
    skillDir: 'skills/project-work-log', skillFile: 'SKILL.md',
    modelInvocable: true, userInvocable: true, verbose: false,
    guidelinesEnabled: true, guidelinesDir: 'skills/reliability-guidelines', guidelinesLanguage: 'zh',
    memoryEnabled: true, memoryInjectIndex: true, memoryPersonalSearchable: false,
  },
  user: { guidelinesEnabled: false },
}

/** A world with our namespace served and the card mounted. */
function mountCard({ seed = SEED, statusFetch = null, extra = {} } = {}) {
  const world = createWorld({ [SERVED_NS]: seed })
  clientExports.apply(world.ctx)
  world.mirror.publish({ namespaces: [namespaceRow(SERVED_NS, CONFIG_VOLATILE_FIELDS)] })
  const registration = world.registered[world.registered.length - 1]
  globalThis.fetch = statusFetch ?? (async (url) => {
    if (url !== clientExports.STATUS_URL) throw new Error(`unexpected fetch: ${url}`)
    return {
      ok: true,
      status: 200,
      json: async () => ({
        source: 'config',
        path: '/home/.dsh/profiles/desktop/cordis.patch.yml',
        memory: { workspaces: 8, inbox: 0, indexChars: 426 },
        error: null,
      }),
    }
  })
  const props = cardProps(world, registration, extra)
  api.mount(registration.component, props)
  api.flushEffects()
  return { world, registration, props, form: world.forms.get(SERVED_NS) }
}

/* ---- tree readers ---- */
const controlsOf = (tree, type) => [...walk(tree)].filter((node) => node.type === type)
const getSwitches = (tree) => controlsOf(tree, SwitchMarker)
const getInputs = (tree) => controlsOf(tree, InputMarker)
const getSegments = (tree) => controlsOf(tree, SegmentedControlMarker)
const getTabs = (tree) => find(tree, (node) => node.type === SegmentedTabsMarker)
const getDisclosures = (tree) => controlsOf(tree, DisclosureRowMarker)
const tabPanels = (tree) => [...walk(tree)].filter((node) => node.props?.role === 'tabpanel')
const markedRows = (tree) => [...walk(tree)].filter((node) => node.props?.['data-mark'] !== undefined)
const textOf = (node) => [...walk(node)].filter((child) => typeof child === 'string').join('')
/** Every control's accessible name — how a removed field is checked structurally. */
const controlNames = (tree) => [...walk(tree)]
  .filter((node) => node.type === InputMarker
    || node.type === SegmentedControlMarker
    || node.type === SwitchMarker)
  .map((node) => String(node.props['aria-label'] ?? node.props.label ?? ''))

/** Words that name the removed project-side settings; a control named for one of
 * them means the group came back. */
const REMOVED_CONTROLS = ['容器', '经验目录', '精细度']
const projectKeyControls = (tree) => controlNames(tree)
  .filter((name) => REMOVED_CONTROLS.some((word) => name.includes(word)))

/** Select a tab the way the tab list does; returns the settled tree. */
const selectTab = async (value) => {
  const tabs = getTabs(runtime.tree)
  if (tabs !== null && tabs.props.value !== value) {
    tabs.props.onChange(value)
    await settle()
  }
  return runtime.tree
}
/** Expand the first collapsed disclosure; returns the settled tree. */
const openDisclosure = async (index = 0) => {
  const rows = getDisclosures(runtime.tree)
  if (rows[index] !== undefined && rows[index].props.open !== true) {
    rows[index].props.onToggle()
    await settle()
  }
  return runtime.tree
}

/* ---- 4a. the Plugins page summary ---- */
{
  const { registration, world } = mountCard({ extra: { view: 'summary' } })
  const summary = registration.component(cardProps(world, registration, { view: 'summary' }))
  ok(typeof summary === 'string' && summary !== '' && summary !== 'summary',
    'the summary view returns a plain string (the Plugins page renders it as the item description)',
    String(summary))
  ok(summary.includes('工作记录'),
    'the summary copy is the localized one-liner', String(summary))
}

/* ---- 4b. the full page: structure, values, tabs ---- */
{
  const { form } = mountCard()
  api.flushEffects()
  await settle()
  const loaded = runtime.tree

  const tabs = getTabs(loaded)
  ok(tabs !== null, 'the card renders the host SegmentedTabs')
  ok(tabs.props.value === 'skills', 'the selected tab defaults to 技能', String(tabs.props.value))
  ok(typeof tabs.props.label === 'string' && tabs.props.label !== 'tabs.label',
    'the tab list carries a localized accessible name', String(tabs.props.label))
  const items = tabs.props.items
  ok(Array.isArray(items) && items.length === 3, 'there are exactly three tabs',
    JSON.stringify(items?.map((item) => item.value)))
  ok(items.map((item) => item.value).join(',') === 'skills,memory,advanced',
    'the tab values are skills, memory and advanced', items.map((item) => item.value).join(','))
  ok(items.map((item) => item.label).join(',') === '技能,记忆,高级',
    'the tab labels are 技能 / 记忆 / 高级', items.map((item) => item.label).join(','))
  ok(items.every((item) => typeof item.id === 'string' && item.id !== ''
    && typeof item.panelId === 'string' && item.panelId !== '' && item.id !== item.panelId),
    'each tab declares its own id and panelId',
    JSON.stringify(items.map((item) => [item.id, item.panelId])))
  ok(new Set(items.map((item) => item.id)).size === 3
    && new Set(items.map((item) => item.panelId)).size === 3,
    'the tab ids and the panel ids are each unique (the primitive validates this)')

  const panels = tabPanels(loaded)
  ok(panels.length === 1, 'exactly one tabpanel is rendered', String(panels.length))
  ok(panels[0].props.id === 'dsh-worklog-panel-skills',
    'the rendered panel is the one the selected tab controls', String(panels[0].props.id))
  ok(panels[0].props['aria-labelledby'] === 'dsh-worklog-tab-skills',
    'the panel points back at its tab with aria-labelledby',
    String(panels[0].props['aria-labelledby']))

  /* ---- the 技能 panel: one switch, the language control, the paths ---- */
  const skillsSwitches = getSwitches(loaded)
  ok(skillsSwitches.length === 1, 'the 技能 panel holds exactly one switch', String(skillsSwitches.length))
  ok(skillsSwitches[0].props.label === '启用可靠性准则技能',
    'the switch is guidelinesEnabled, with localized copy (not the raw key)',
    String(skillsSwitches[0].props.label))
  ok(skillsSwitches[0].props.checked === false,
    'the switch reflects the LIVE value the host projected', String(skillsSwitches[0].props.checked))
  ok(skillsSwitches[0].props.disabled === false, 'a writable form leaves the switch enabled')
  ok(typeof skillsSwitches[0].props.onChange === 'function', 'the switch is controlled')

  const language = getSegments(loaded)[0]
  ok(getSegments(loaded).length === 1, 'the 技能 panel carries exactly one SegmentedControl',
    getSegments(loaded).map((node) => node.props.id).join(','))
  ok(language?.props.id === 'dsh-worklog-guidelines-language',
    'it is the language control', String(language?.props.id))
  ok(language.props.value === 'en', 'it reflects the projected language', String(language.props.value))
  ok(language.props.options.map((option) => option.value).join(',') === 'zh,en',
    'the options are zh and en in that order')
  ok(language.props.options.map((option) => option.label).join(',') === '中文,English',
    'the option labels are the two language names, each in its own language')
  ok(typeof language.props.label === 'string' && language.props.label !== 'guidelinesLanguage.label',
    'the language control carries a localized accessible name', String(language.props.label))

  const pathsDisclosure = getDisclosures(loaded)[0]
  ok(pathsDisclosure !== null && pathsDisclosure !== undefined,
    'the 技能 panel renders the 路径 DisclosureRow')
  ok(pathsDisclosure.props.title === '路径', 'the disclosure is titled 路径', String(pathsDisclosure.props.title))
  ok(pathsDisclosure.props.open === false, 'the 路径 area starts collapsed')
  ok(getInputs(loaded).length === 0,
    'a collapsed 路径 area renders no input at all (its rows are children, not siblings)',
    String(getInputs(loaded).length))

  await openDisclosure(0)
  const opened = runtime.tree
  const inputs = getInputs(opened)
  ok(inputs.length === 2, 'opening 路径 shows exactly two text inputs', String(inputs.length))
  ok(inputs.map((node) => node.props.id).join(',') === 'dsh-worklog-skillDir,dsh-worklog-guidelinesDir',
    'the two inputs are the two path fields', inputs.map((node) => node.props.id).join(','))
  ok(inputs.map((node) => node.props['aria-label']).join('|') === '工作记录技能目录|准则技能目录',
    'each input carries a localized accessible name',
    inputs.map((node) => node.props['aria-label']).join('|'))
  ok(inputs[0].props.value === '',
    'an un-overridden field shows EMPTY (blank means "use the layer below")',
    JSON.stringify(inputs[0].props.value))
  ok(inputs[0].props.placeholder === 'skills/project-work-log',
    'and shows the value it would fall back to as its placeholder',
    String(inputs[0].props.placeholder))
  ok(inputs[1].props.placeholder === 'skills/reliability-guidelines',
    'the guidelines directory does too', String(inputs[1].props.placeholder))
  ok(markedRows(opened).length === 0,
    'neither path field shows an override badge while neither is overridden',
    String(markedRows(opened).length))

  /* ---- no control for the project-side keys, in any tab ---- */
  ok(projectKeyControls(loaded).length === 0,
    'no control in the 技能 panel is named for container / lessons / mode',
    projectKeyControls(loaded).join(' | '))
  ok(getSegments(loaded).every((node) => node.props.id !== 'dsh-worklog-mode'),
    'the removed mode control did not come back')

  /* ---- the 记忆 panel ---- */
  await selectTab('memory')
  const memory = runtime.tree
  const memoryPanels = tabPanels(memory)
  ok(memoryPanels.length === 1 && memoryPanels[0].props.id === 'dsh-worklog-panel-memory',
    'selecting 记忆 renders its panel and only its panel',
    memoryPanels.map((node) => node.props.id).join(','))
  ok(memoryPanels[0].props['aria-labelledby'] === 'dsh-worklog-tab-memory',
    'the 记忆 panel points back at its own tab')
  const memorySwitches = getSwitches(memory)
  ok(memorySwitches.length === 3, 'the 记忆 panel holds three switches', String(memorySwitches.length))
  ok(memorySwitches.map((node) => node.props.label).join(',') === '启用全局记忆,默认注入记忆索引,个人目录可被检索',
    'the three switches are memoryEnabled / memoryInjectIndex / memoryPersonalSearchable, in order',
    memorySwitches.map((node) => node.props.label).join(','))
  ok(memorySwitches.map((node) => node.props.checked).join(',') === 'true,true,false',
    'they reflect the projected values', memorySwitches.map((node) => node.props.checked).join(','))
  ok(projectKeyControls(memory).length === 0,
    'the 记忆 panel offers no control for container / lessons / mode',
    projectKeyControls(memory).join(' | '))
  // The restart distinction and the upload-permission pointer are CARRIED BY THE
  // DICTIONARY, so that is what gets asserted. `textOf` cannot reach copy inside
  // nested components; asserting rendered text there would be a test that can
  // never fail — a mistake this project already made once.
  ok(clientExports.DICT_ZH['restart.memory'].includes('需重启')
    && clientExports.DICT_ZH['restart.memory'].includes('即时生效'),
    'the 记忆 copy distinguishes the load-time switch from the live ones',
    clientExports.DICT_ZH['restart.memory'])
  ok(clientExports.DICT_EN['restart.memory'].includes('restart')
    && clientExports.DICT_EN['restart.memory'].includes('immediately'),
    'the English copy draws the same distinction')
  ok(clientExports.DICT_ZH['memory.note'].includes('发布.md'),
    'the 记忆 copy says upload permission lives in each workspace\'s 发布.md',
    clientExports.DICT_ZH['memory.note'])

  /* ---- the read-only status block ---- */
  const stateDisclosure = getDisclosures(memory)[0]
  ok(stateDisclosure !== null && stateDisclosure !== undefined,
    'the 记忆 panel has the 当前状态 disclosure',
    getDisclosures(memory).map((node) => node.props.title).join(','))
  ok(stateDisclosure.props.open === false, 'the status block starts collapsed')
  ok(!textOf(memory).includes('已登记工作区'),
    'a collapsed status block does not render its numbers')
  await openDisclosure(0)
  const stateText = textOf(runtime.tree)
  ok(stateText.includes('已登记工作区 8 · 待收 0 · 索引字数 426'),
    'the status block reports what the host answered',
    stateText.slice(0, 200))
  ok(stateText.includes('发布.md'), 'and says where upload permission lives')

  /* ---- the 高级 panel ---- */
  await selectTab('advanced')
  const advanced = runtime.tree
  const advancedPanels = tabPanels(advanced)
  ok(advancedPanels.length === 1 && advancedPanels[0].props.id === 'dsh-worklog-panel-advanced',
    'selecting 高级 renders its panel and only its panel')
  const advancedSwitches = getSwitches(advanced)
  ok(advancedSwitches.length === 3, 'the 高级 panel holds three switches', String(advancedSwitches.length))
  ok(advancedSwitches.map((node) => node.props.label).join(',') === '装载时打日志,允许模型自动调用,允许手动调用',
    'the three switches are verbose / modelInvocable / userInvocable, in order',
    advancedSwitches.map((node) => node.props.label).join(','))
  ok(advancedSwitches.map((node) => node.props.checked).join(',') === 'false,true,true',
    'they reflect the projected values',
    advancedSwitches.map((node) => node.props.checked).join(','))
  ok(getInputs(advanced).length === 0, 'the 高级 panel holds no text input')
  ok(getSegments(advanced).length === 0, 'the 高级 panel holds no segmented control')
  ok(projectKeyControls(advanced).length === 0,
    'the 高级 panel offers no control for container / lessons / mode')

  /* ---- the footers ---- */
  const footers = textOf(advanced)
  ok(footers.includes('这一页是装载参数：改完需重启 DSH 才生效。'),
    'the panel says a restart is required, in the panel-specific wording')
  ok(footers.includes('设置位置'),
    'the card says WHERE the settings live (the official channel is not a guess)')
  ok(!footers.includes('where.config'),
    'and resolves that copy through the dictionary rather than printing the key',
    footers.slice(-200))
}

/* ---- 4c. switches write through the form, one operation each ---- */
{
  const { form } = mountCard()
  await settle()
  const first = getSwitches(runtime.tree)[0]
  first.props.onChange(true)
  await settle()

  const calls = form.mutations
  ok(calls.length === 1, 'toggling a switch issues exactly one mutation', String(calls.length))
  ok(JSON.stringify(calls[0]) === JSON.stringify([{ op: 'set', path: ['guidelinesEnabled'], value: true }]),
    'the mutation is a set of that one field to the chosen value', JSON.stringify(calls[0]))
  ok(getSwitches(runtime.tree)[0].props.checked === true,
    'and the card re-renders from the host answer (not from an optimistic local copy)',
    String(getSwitches(runtime.tree)[0].props.checked))
  ok(textOf(runtime.tree).includes('已保存'), 'the card reports the save as done')

  const language = getSegments(runtime.tree)[0]
  language.props.onChange('zh')
  await settle()
  ok(JSON.stringify(form.mutations[1]) === JSON.stringify([{ op: 'set', path: ['guidelinesLanguage'], value: 'zh' }]),
    'choosing a language issues a set of that field', JSON.stringify(form.mutations[1]))
}

/* ---- 4d. the path fields commit on blur, not per keystroke ---- */
{
  const mounted = mountCard()
  await settle()
  await openDisclosure(0)

  const input = getInputs(runtime.tree)[0]
  input.props.onChange({ target: { value: '/opt/bundles/worklog' } })
  await settle()
  ok(mounted.form.mutations.length === 0,
    'typing does NOT write: no patch rewrite per keystroke',
    `${mounted.form.mutations.length} mutation(s)`)
  const midTyping = getInputs(runtime.tree)[0]
  ok(midTyping.props.value === '/opt/bundles/worklog',
    'the draft is what the user sees while typing (a controlled input reading the mirror would reset it)',
    String(midTyping.props.value))

  midTyping.props.onBlur()
  await settle()
  ok(mounted.form.mutations.length === 1,
    'blurring writes exactly once', String(mounted.form.mutations.length))
  ok(JSON.stringify(mounted.form.mutations[0])
    === JSON.stringify([{ op: 'set', path: ['skillDir'], value: '/opt/bundles/worklog' }]),
    'the write carries the settled text', JSON.stringify(mounted.form.mutations[0]))
  ok(mounted.form.state.user.skillDir === '/opt/bundles/worklog',
    'and the host now has the override')
  const afterCommit = getInputs(runtime.tree)[0]
  ok(afterCommit.props.value === '/opt/bundles/worklog',
    'the field still shows the committed text')
  ok(markedRows(runtime.tree).length === 1,
    'the override badge appears now that the value is overridden')
  ok(markedRows(runtime.tree)[0].props['data-mark'] === '已覆盖',
    'the badge is the localized copy', String(markedRows(runtime.tree)[0].props['data-mark']))

  /* blurring with no change writes nothing */
  getInputs(runtime.tree)[0].props.onBlur()
  await settle()
  ok(mounted.form.mutations.length === 1,
    'blurring without changing anything writes nothing', String(mounted.form.mutations.length))

  /* clearing the field resets the override rather than storing an empty string */
  const field = getInputs(runtime.tree)[0]
  field.props.onChange({ target: { value: '' } })
  await settle()
  getInputs(runtime.tree)[0].props.onBlur()
  await settle()
  ok(mounted.form.mutations.length === 2, 'clearing writes once', String(mounted.form.mutations.length))
  ok(JSON.stringify(mounted.form.mutations[1]) === JSON.stringify([{ op: 'unset', path: ['skillDir'] }]),
    'clearing sends an UNSET (back to the layer below), not a stored empty string',
    JSON.stringify(mounted.form.mutations[1]))
  ok(mounted.form.state.user.skillDir === undefined,
    'the host no longer carries the override')
  ok(getInputs(runtime.tree)[0].props.value === '',
    'the field shows empty again')
  ok(getInputs(runtime.tree)[0].props.placeholder === 'skills/project-work-log',
    'and falls back to showing the inherited value as its placeholder')
  ok(markedRows(runtime.tree).length === 0, 'the override badge is gone')

  /* the explicit reset button */
  const field2 = getInputs(runtime.tree)[1]
  field2.props.onChange({ target: { value: '/tmp/guides' } })
  getInputs(runtime.tree)[1].props.onBlur()
  await settle()
  const resetButton = find(runtime.tree, (node) => node.type === 'button' && textOf(node).includes('恢复默认'))
  ok(resetButton !== null, 'an overridden field offers a 恢复默认 control')
  resetButton.props.onClick()
  await settle()
  ok(JSON.stringify(mounted.form.mutations[mounted.form.mutations.length - 1])
    === JSON.stringify([{ op: 'unset', path: ['guidelinesDir'] }]),
    'the reset control unsets that field',
    JSON.stringify(mounted.form.mutations[mounted.form.mutations.length - 1]))
}

/* ---- 4e. a refused or failed write is reported, and reverts the display ---- */
{
  const mounted = mountCard()
  await settle()
  await openDisclosure(0)
  getInputs(runtime.tree)[0].props.onChange({ target: { value: '/nope' } })
  mounted.form.behaviour.reject = true
  getInputs(runtime.tree)[0].props.onBlur()
  await settle()
  ok(textOf(runtime.tree).includes('宿主拒绝了这次修改'),
    'a refused write says the host refused it', textOf(runtime.tree).slice(-160))
  ok(getInputs(runtime.tree)[0].props.value === '',
    'and the field falls back to the value that is actually stored (no "looks saved" illusion)',
    String(getInputs(runtime.tree)[0].props.value))

  mounted.form.behaviour.reject = false
  mounted.form.behaviour.throwError = true
  getInputs(runtime.tree)[0].props.onChange({ target: { value: '/also-nope' } })
  getInputs(runtime.tree)[0].props.onBlur()
  await settle()
  ok(textOf(runtime.tree).includes('保存失败'),
    'a throwing write reports a failure too', textOf(runtime.tree).slice(-160))
}

/* ---- 4f. a write that is refused is NOT reported as saved ---- */
{
  const { form } = mountCard()
  form.behaviour.reject = true
  await settle()
  getSwitches(runtime.tree)[0].props.onChange(true)
  await settle()
  ok(textOf(runtime.tree).includes('宿主拒绝了这次修改'),
    'a refused switch change is reported, not swallowed')
  ok(!textOf(runtime.tree).includes('已保存'), 'and it is not reported as saved')
}

/* ---- 4g. a status read failure degrades, it does not break the form ---- */
{
  mountCard({
    statusFetch: async () => ({ ok: false, status: 503, json: async () => ({}) }),
  })
  await settle()
  await selectTab('memory')
  await openDisclosure(0)
  const texts = textOf(runtime.tree)
  ok(texts.includes('状态读取失败'), 'a failed status read says so', texts.slice(0, 200))
  ok(texts.includes('503'), 'and names the HTTP status')
  ok(getSwitches(runtime.tree).length === 3,
    'while the configuration form still works (the status endpoint is optional)')
  ok(!texts.includes('已登记工作区'), 'and no invented numbers are shown')
}

/* ---- 4h. an unprojected form disables the controls instead of lying ---- */
{
  mountCard({ seed: { ...SEED, status: 'loading' } })
  await settle()
  ok(textOf(runtime.tree).includes('配置暂时不可用'),
    'a form the host has not projected says so', textOf(runtime.tree).slice(0, 200))
  ok(getSwitches(runtime.tree).every((node) => node.props.disabled === true),
    'and every control is disabled rather than writable-but-dead')
  ok(getInputs(runtime.tree).length === 0, 'with the path fields still collapsed')
}

/* ============ 5. the claim fingerprint answers to lib/index.js ============= */
// The client claims its namespace by the set of `.volatile()` field names. If a
// field is added to Config and not to FORM_FIELDS, the card silently stops
// appearing; if one is REMOVED from FORM_FIELDS the card keeps working here and
// silently stops on a deployment whose projection differs. Either way the two lists
// have to agree, so they are re-derived from the source and compared rather than
// trusted to a comment.
//
// Note the direction that the sections above CANNOT catch on their own: they serve
// rows built from `CONFIG_VOLATILE_FIELDS`, so an under-claiming client still
// claims them (a subset of the required fields is enough). That asymmetry is
// exactly why this对账 exists.
{
  const declared = [...CONFIG_VOLATILE_FIELDS].sort()
  const claimed = [...clientExports.FORM_FIELDS].sort()
  ok(declared.length > 0, 'lib/index.js declares a Config object literal with volatile fields',
    String(declared.length))
  ok(new Set(clientExports.FORM_FIELDS).size === clientExports.FORM_FIELDS.length,
    'the client fingerprint has no duplicate field')
  ok(declared.join(',') === claimed.join(','),
    'the client claims exactly the volatile fields the Config declares',
    `Config: ${declared.join(',')} | client: ${claimed.join(',')}`)
}

console.log(problems.length === 0
  ? '\nclient runtime OK — the card claims its namespace, mounts, edits and reports'
  : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
