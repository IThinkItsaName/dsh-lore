// Load `lib/client.js` the way the BROWSER module system does, and drive the
// settings panel without a browser.
//
// `tests/audit-client.mjs` proves the bundle is shaped right and only requires
// specifiers that exist. This goes further, because shaped-right is not the same
// as works:
//
//   1. it evaluates the bundle with a stub `window.__ModuleLoader__`, exactly as
//      `packages/client/ui-trajectory/tests/client-bundle.client.spec.ts` does in
//      the DSH tree, and takes the handoff;
//   2. it calls `factory(require)` with a module table built from the nine-item
//      baseline — so a require the loader would refuse fails here instead;
//   3. it runs `apply()` against fake `locale`/`slots` services and checks the
//      registration shape the settings shell reads (`settings.section`,
//      id, label thunk, locale namespace);
//   4. it MOUNTS the panel component with a minimal React hook runtime and a
//      stubbed `fetch`, then clicks the Switch and types into an Input to prove
//      the load → change → POST → re-read loop actually closes.
//
// That is not "the page renders correctly" — layout, styling and the shell's own
// behaviour still need a browser. It IS everything up to the point where only a
// browser can decide.
//
//   node tests/audit-client-runtime.mjs
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { PKG } from './_pkg.mjs'

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}
const settle = async (rounds = 6) => {
  for (let i = 0; i < rounds; i += 1) await Promise.resolve()
}

const CLIENT_PATH = `${PKG}/lib/client.js`
const code = readFileSync(CLIENT_PATH, 'utf8')

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
    pendingEffect: null,
    renders: 0,
  }

  const render = () => {
    runtime.index = 0
    runtime.pendingEffect = null
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
    useRef(initial) {
      const slot = runtime.index
      runtime.index += 1
      if (!(slot in runtime.hooks)) runtime.hooks[slot] = { current: initial }
      return runtime.hooks[slot]
    },
    useCallback(fn) {
      // The component's callbacks are pure closures over stable refs; returning
      // the fresh function is behaviourally the same for this test.
      runtime.index += 1
      return fn
    },
    useEffect(fn) {
      runtime.index += 1
      runtime.pendingEffect = fn
    },
    /** Run the effect the last render scheduled; its cleanup is dropped. */
    flushEffects() {
      const effect = runtime.pendingEffect
      runtime.pendingEffect = null
      if (effect) effect()
    },
    /** Mount a function component and return its element tree. */
    mount(Component, props) {
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
 * Yields text children too (a `{ type, props, children }` node's children are a
 * mix of elements and strings), so a text assertion can read the rendered copy
 * without re-implementing the traversal.
 */
function* walk(node) {
  if (node === null || node === undefined || node === false) return
  if (typeof node !== 'object') { yield node; return }
  yield node
  for (const child of node.children ?? []) yield* walk(child)
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
 * The four primitives are marker components: the test reads the element tree, so
 * a component only has to exist and be identifiable by its function identity —
 * the same identity the bundle receives, because both sides share these. */
function SwitchMarker(props) { return { type: 'Switch', props, children: [] } }
function InputMarker(props) { return { type: 'Input', props, children: [] } }
function SegmentedControlMarker(props) { return { type: 'SegmentedControl', props, children: [] } }
function DisclosureRowMarker(props) {
  return { type: 'DisclosureRow', props, children: props.children ? [props.children] : [] }
}

function createRequire(hooks) {
  const primitives = {
    Switch: SwitchMarker,
    Input: InputMarker,
    SegmentedControl: SegmentedControlMarker,
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

/* ============================ 1. wrapper + factory ========================= */
// One module table for every section below. The bundle must be evaluated once:
// the primitives it requires and the component it registers have to come from
// the SAME evaluation, or the tree's node types are not the ones this file
// compares against.
const { api, runtime } = createHookRuntime()
const handoff = loadBundle(api)
const { require: loadRequire, seen } = createRequire(api)
let SettingsPanel = null
{
  ok(handoff !== null, 'the bundle calls window.__ModuleLoader__.load')
  ok(handoff?.id === 'dsh-worklog', 'the handoff id is the package name', String(handoff?.id))
  ok(typeof handoff?.factory === 'function', 'the handoff carries a factory')

  const exports = handoff.factory(loadRequire)
  ok(exports !== null && typeof exports === 'object', 'the factory returns an exports object')
  ok(typeof exports.apply === 'function', 'exports.apply is a function')
  ok(Array.isArray(exports.inject), 'exports.inject is an array', JSON.stringify(exports.inject))
  ok(exports.inject.join(',') === 'locale,slots',
    'exports.inject names locale and slots (both are needed by the panel)', exports.inject.join(','))
  ok(exports.name === 'dsh-worklog', 'exports.name matches the package', String(exports.name))
  ok(seen.join(',') === 'react,@deepseek-ai/dsh-client-ui-primitives',
    'the factory resolves through the injected require, and only those two words',
    seen.join(','))

  /* =================== 2. apply() registers into the slots ================= */
  const registered = []
  const boundNamespaces = []
  const dictionaries = []
  const effects = []
  const injections = []
  const dictionariesByNs = new Map()
  const boundByNs = new Map()

  // A locale runtime shaped like the real one: bind(ns) returns the
  // namespace-bound translate function, register stores dictionaries.
  const locale = {
    bind: (ns) => {
      if (!boundByNs.has(ns)) {
        boundByNs.set(ns, (key) => (dictionariesByNs.get(ns)?.zh?.[key] ?? key))
        boundNamespaces.push(ns)
      }
      return boundByNs.get(ns)
    },
    register: (ns, dicts) => {
      dictionaries.push({ ns, dicts })
      dictionariesByNs.set(ns, dicts)
      return () => {}
    },
  }
  const slots = {
    inject: (name, factory) => { injections.push(name); factory() },
    register: (options, component) => {
      registered.push({ options, component })
      return () => {}
    },
  }
  const ctx = {
    locale,
    slots,
    effect: (callback) => { effects.push(callback()) },
  }

  exports.apply(ctx)

  ok(boundNamespaces.length === 1, 'apply() binds exactly one locale namespace', `${boundNamespaces.length}`)
  ok(dictionaries.length === 1, 'apply() registers exactly one dictionary set')
  const ns = dictionaries[0]?.ns
  ok(ns === boundNamespaces[0], 'the dictionary namespace and the bound namespace agree', String(ns))
  ok(dictionaries[0]?.dicts?.zh !== undefined && dictionaries[0]?.dicts?.en !== undefined,
    'the dictionary set carries both zh and en (the register({zh,en}) form)',
    Object.keys(dictionaries[0]?.dicts ?? {}).join(','))
  ok(effects.length === 1 && typeof effects[0] === 'function',
    'the dictionary disposer is handed to ctx.effect (cleanup on unload)')

  ok(injections.join(',') === 'settings.section',
    'apply() injects the settings.section slot before registering', injections.join(','))
  ok(registered.length === 1, 'apply() registers exactly one component', `${registered.length}`)
  const options = registered[0]?.options
  ok(options?.name === 'settings.section', 'the registration names settings.section', String(options?.name))
  ok(options?.id === 'dsh-worklog', 'the section id is dsh-worklog (the nav key)', String(options?.id))
  ok(options?.order === 50, 'the section order is 50', String(options?.order))
  ok(options?.locale === ns, 'the registration declares the locale namespace (this is what injects t)',
    String(options?.locale))
  ok(typeof options?.label === 'function', 'label is a thunk (the shell re-evaluates it on locale change)')
  const navLabel = options?.label()
  ok(typeof navLabel === 'string' && navLabel !== '' && navLabel !== 'nav.label',
    'the nav label resolves through the dictionary', String(navLabel))
  ok(typeof registered[0]?.component === 'function',
    'the registration carries a function component', typeof registered[0]?.component)
  SettingsPanel = registered[0].component
}


/* ================== 3. mount the panel against a stub fetch =============== */
{
  const panel = SettingsPanel

  /** A server with the same shape as the node half's route, in memory. */
  function createServer(initial, { failPost = false } = {}) {
    const state = { document: { ...initial }, posts: [] }
    const json = (body, status = 200) => ({
      ok: status >= 200 && status < 300,
      status,
      text: async () => JSON.stringify(body),
      json: async () => body,
    })
    /**
     * The two groups the route reports, kept in the same shape as the node half:
     * `effective` carries ONLY what apply() reads, and the project-side keys are
     * reported apart from it under the not-applied marker.
     */
    const report = () => ({
      effective: {
        skillDir: state.document.skillDir || 'skills/project-work-log',
        skillFile: 'SKILL.md',
        guidelinesDir: state.document.guidelinesDir || 'skills/reliability-guidelines',
        guidelinesEnabled: state.document.guidelinesEnabled !== false,
        guidelinesLanguage: state.document.guidelinesLanguage === 'en' ? 'en' : 'zh',
      },
      projectDefaults: {
        appliedByPlugin: false,
        values: {
          container: state.document.container || 'work_log',
          lessons: state.document.lessons || 'lessons',
          mode: state.document.mode || 'full',
        },
      },
    })
    const fetchStub = async (url, init) => {
      if (url !== '/plugins/dsh-worklog/settings.json') {
        throw new Error(`unexpected fetch: ${url}`)
      }
      if ((init?.method ?? 'GET') === 'GET') {
        return json({
          path: '/home/.dsh/worklog/settings.json',
          settings: state.document,
          ...report(),
          error: null,
        })
      }
      const body = JSON.parse(init.body)
      state.posts.push(body)
      if (failPost) return json({ error: 'could not write the settings file: EACCES' }, 500)
      state.document = { ...state.document, ...body }
      return json({
        path: '/home/.dsh/worklog/settings.json',
        settings: state.document,
        ...report(),
      })
    }
    return { state, fetchStub }
  }

  const getSwitch = (tree) => find(tree, (node) => node.type === SwitchMarker)
  const getSegment = (tree, id) => find(tree, (node) =>
    node.type === SegmentedControlMarker && node.props.id === id)
  const getInputs = (tree) => [...walk(tree)].filter((node) => node.type === InputMarker)
  const textOf = (node) => [...walk(node)]
    .filter((child) => typeof child === 'string')
    .join('')

  /* ---- 3a. the initial load populates the form from the server ---- */
  {
    const server = createServer({ guidelinesEnabled: false, guidelinesLanguage: 'en', mode: 'digest' })
    globalThis.fetch = server.fetchStub

    const tree = api.mount(SettingsPanel, {})
    // The panel's first paint is the loading state; the effect starts the fetch.
    ok(JSON.stringify(tree).includes('正在读取'), 'the first paint is the loading state')
    api.flushEffects()
    await settle()

    const loaded = runtime.tree
    const toggle = getSwitch(loaded)
    ok(toggle !== null, 'the panel renders a Switch',
      `${runtime.renders} render(s); top-level types: ${(loaded?.children ?? []).map((child) => typeName(child.type)).join(',')}`)
    ok(toggle.props.checked === false, 'the Switch reflects the loaded value (false)', String(toggle.props.checked))
    ok(typeof toggle.props.label === 'string' && toggle.props.label !== '',
      'the Switch carries an accessible label (the primitive requires one)')
    ok(typeof toggle.props.onChange === 'function', 'the Switch is controlled (onChange present)')

    const language = getSegment(loaded, 'dsh-worklog-guidelines-language')
    ok(language !== null, 'the panel renders the language SegmentedControl')
    ok(language.props.value === 'en', 'the language control reflects the loaded value', String(language.props.value))
    ok(Array.isArray(language.props.options) && language.props.options.length === 2,
      'the language control has exactly two options', String(language.props.options?.length))
    ok(language.props.options.map((option) => option.value).join(',') === 'zh,en',
      'the options are zh and en in that order')
    ok(language.props.options.map((option) => option.label).join(',') === '中文,English',
      'the option labels are the two language names, each in its own language',
      language.props.options.map((option) => option.label).join(','))
    ok(typeof language.props.label === 'string' && language.props.label !== '',
      'the language control carries an accessible name (the primitive requires one)')

    const mode = getSegment(loaded, 'dsh-worklog-mode')
    ok(mode !== null, 'the advanced area contributes the mode SegmentedControl')
    ok(mode.props.value === 'digest', 'the mode control reflects the loaded value', String(mode.props.value))
    ok(mode.props.options.length === 4, 'the mode control has four options')
    ok(mode.props.options.map((option) => option.value).join(',') === 'full,session,digest,milestone',
      'the mode options are the four documented modes',
      mode.props.options.map((option) => option.value).join(','))

    ok(textOf(loaded).includes('重启'), 'the panel says a restart is required')
    ok(textOf(loaded).includes('/home/.dsh/worklog/settings.json'),
      'the panel shows the settings file path it read')

    const advanced = find(loaded, (node) => node.type === DisclosureRowMarker)
    ok(advanced !== null, 'the advanced area is a DisclosureRow')
    ok(advanced.props.open === false, 'the advanced area starts collapsed')
    ok(advanced.props.expandable === true, 'the advanced area is expandable')

    const inputs = getInputs(loaded)
    ok(inputs.length === 4, 'the advanced area holds four text inputs', String(inputs.length))
    ok(inputs[0].props.placeholder === 'skills/project-work-log',
      'a blank field shows the effective value as its placeholder',
      String(inputs[0].props.placeholder))

    /* ---- the project-side group must not read as plugin effect ---- */
    const panelText = textOf(loaded)
    ok(panelText.includes('插件不读'),
      'the project-defaults group says the plugin does not read them', panelText.slice(-320))
    ok(panelText.includes('journal.py'),
      'the group hint names what does read them: `journal.py`')
    ok(inputs[2].props.placeholder === 'work_log' && inputs[3].props.placeholder === 'lessons',
      'the project-default fields take their placeholders from projectDefaults.values',
      `${String(inputs[2].props.placeholder)} / ${String(inputs[3].props.placeholder)}`)
    // The right-hand "in effect" mark belongs to load-time options only; leaving it
    // on a stored-but-unread field is the same false claim in a smaller font.
    const defaultMarks = (panelText.match(/（默认）/g) ?? []).length
    ok(defaultMarks === 2,
      'only the two load-time path fields carry an "in effect (default)" mark',
      `${defaultMarks} mark(s) in: ${panelText.slice(-320)}`)
  }

  /* ---- 3b. clicking the Switch posts the whole form, serially ---- */
  {
    const server = createServer({ guidelinesEnabled: true, guidelinesLanguage: 'zh' })
    globalThis.fetch = server.fetchStub

    api.mount(SettingsPanel, {})
    api.flushEffects()
    await settle()
    ok(getSwitch(runtime.tree) !== null, 'the panel re-rendered after loading')

    const toggle = getSwitch(runtime.tree)
    toggle.props.onChange(false)

    // Two changes fired back to back: the queue must serialize them, and each
    // must carry the value the user just set rather than a stale render's copy.
    toggle.props.onChange(true)
    await settle(12)

    ok(server.state.posts.length === 2, 'two changes produced two POSTs', String(server.state.posts.length))
    ok(server.state.posts[0]?.guidelinesEnabled === false,
      'the first POST carries the first value', JSON.stringify(server.state.posts[0]))
    ok(server.state.posts[1]?.guidelinesEnabled === true,
      'the second POST carries the second value, not a stale one',
      JSON.stringify(server.state.posts[1]))
    ok(server.state.posts[1]?.guidelinesLanguage === 'zh',
      'each POST carries the whole form (the route treats it as a document)',
      JSON.stringify(server.state.posts[1]))
    ok(server.state.document.guidelinesEnabled === true, 'the server state ended at the last value')
    ok(getSwitch(runtime.tree).props.checked === true,
      'the Switch shows the value the server confirmed')

    const texts = textOf(runtime.tree)
    ok(texts.includes('已保存'), 'the panel reports the save as done')
  }

  /* ---- 3c. the segmented control and a text input ---- */
  {
    const server = createServer({ guidelinesEnabled: true, guidelinesLanguage: 'zh' })
    globalThis.fetch = server.fetchStub

    api.mount(SettingsPanel, {})
    api.flushEffects()
    await settle()

    const language = getSegment(runtime.tree, 'dsh-worklog-guidelines-language')
    language.props.onChange('en')
    await settle(12)
    ok(server.state.document.guidelinesLanguage === 'en',
      'choosing English persists guidelinesLanguage=en',
      JSON.stringify(server.state.document))

    const skillDirInput = getInputs(runtime.tree)[0]
    skillDirInput.props.onChange({ target: { value: '/opt/bundles/worklog' } })
    await settle(12)
    ok(server.state.document.skillDir === '/opt/bundles/worklog',
      'typing a path persists it',
      JSON.stringify(server.state.document.skillDir))

    const advanced = find(runtime.tree, (node) => node.type === DisclosureRowMarker)
    advanced.props.onToggle()
    await settle()
    ok(find(runtime.tree, (node) => node.type === DisclosureRowMarker).props.open === true,
      'toggling the DisclosureRow opens the advanced area')
  }

  /* ---- 3d. a failed save is reported, not swallowed ---- */
  {
    const server = createServer({ guidelinesEnabled: true }, { failPost: true })
    globalThis.fetch = server.fetchStub

    api.mount(SettingsPanel, {})
    api.flushEffects()
    await settle()
    getSwitch(runtime.tree).props.onChange(false)
    await settle(12)

    const texts = textOf(runtime.tree)
    ok(texts.includes('保存失败'), 'a failed save shows an error state')
    ok(texts.includes('EACCES'), 'the error carries the server\'s own reason', texts.slice(-200))
  }

  /* ---- 3e. a load failure is reported, and does not render a half form ---- */
  {
    globalThis.fetch = async () => ({ ok: false, status: 503, text: async () => '', json: async () => ({}) })

    api.mount(SettingsPanel, {})
    api.flushEffects()
    await settle()

    ok(getSwitch(runtime.tree) === null, 'a load failure does not render an editable form')
    ok(textOf(runtime.tree).includes('读取设置失败'), 'a load failure says so')
    ok(textOf(runtime.tree).includes('503'), 'a load failure names the HTTP status')
  }
}

console.log(problems.length === 0
  ? '\nclient runtime OK — the bundle mounts, loads, saves and reports'
  : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
