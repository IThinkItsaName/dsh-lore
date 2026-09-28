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
//      stubbed `fetch`, then clicks the Switch, switches tabs, expands the
//      disclosure and types into an Input to prove the load → change → POST →
//      re-read loop actually closes;
//   5. it asserts STRUCTURALLY that the page offers no control for the
//      project-side keys (`container` / `lessons` / `mode`). Those are stored by
//      the node half and reported as `projectDefaults`, but they belong to a
//      project's own `.config.json` and are changed with `journal.py config` —
//      so the page must not manage them, in either tab. Text is the wrong test
//      for that (the page's own compatibility note names them), hence: no marked
//      row, no input, no segment.
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
 *
 * Arrays are flattened because a component that forwards `props.children`
 * verbatim hands one through; without this everything inside such a node would be
 * invisible — the same class of silent zero this file has already been bitten by.
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
 * above are never CALLED — they exist so the tree can be identified by type
 * (`node.type === SwitchMarker`), and nothing more. A nested component's own
 * render logic therefore has to be modelled here when an assertion depends on it.
 *
 * `DisclosureRow` is the one that does: the host component renders `open &&
 * children`, and a panel that put its rows beside the disclosure instead of
 * inside it would show a "collapsed" section with every row still on screen.
 * Ignoring `open` here would hide exactly that defect.
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
 * The five primitives are marker components: the test reads the element tree, so
 * a component only has to exist and be identifiable by its function identity —
 * the same identity the bundle receives, because both sides share these. */
function SwitchMarker(props) { return { type: 'Switch', props, children: [] } }
function InputMarker(props) { return { type: 'Input', props, children: [] } }
function SegmentedControlMarker(props) { return { type: 'SegmentedControl', props, children: [] } }
/**
 * `SegmentedTabs` renders the tab list ONLY and owns no panels, so its items are
 * data rather than children — the marker keeps them in props, where an assertion
 * can read the values, the labels and the tab/panel id pair.
 */
function SegmentedTabsMarker(props) { return { type: 'SegmentedTabs', props, children: [] } }
/**
 * The disclosure header. Its `open && children` behaviour is modelled in
 * `childrenOf`, because this runtime never calls a nested component — see there.
 */
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
     *
     * The page must IGNORE `projectDefaults` now — it neither renders a control
     * for it nor sends it back — so the stub keeps reporting it. A stub that
     * dropped the field would make "the page ignores it" untestable.
     */
    const report = () => ({
      effective: {
        skillDir: state.document.skillDir || 'skills/project-work-log',
        skillFile: 'SKILL.md',
        guidelinesDir: state.document.guidelinesDir || 'skills/reliability-guidelines',
        guidelinesEnabled: state.document.guidelinesEnabled !== false,
        guidelinesLanguage: state.document.guidelinesLanguage === 'en' ? 'en' : 'zh',
        verbose: state.document.verbose === true,
        modelInvocable: state.document.modelInvocable !== false,
        userInvocable: state.document.userInvocable !== false,
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
      // The route treats the body as a PATCH (`sanitizeSettings` merges it into
      // the stored document), so a key the page no longer sends keeps its value.
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
  const getSwitches = (tree) => [...walk(tree)].filter((node) => node.type === SwitchMarker)
  const getSegment = (tree, id) => find(tree, (node) =>
    node.type === SegmentedControlMarker && node.props.id === id)
  const getSegments = (tree) => [...walk(tree)].filter((node) => node.type === SegmentedControlMarker)
  const getInputs = (tree) => [...walk(tree)].filter((node) => node.type === InputMarker)
  const getTabs = (tree) => find(tree, (node) => node.type === SegmentedTabsMarker)
  const getDisclosure = (tree) => find(tree, (node) => node.type === DisclosureRowMarker)
  const tabPanels = (tree) => [...walk(tree)].filter((node) => node.props?.role === 'tabpanel')
  const markedRows = (tree) => [...walk(tree)].filter((node) => node.props?.['data-mark'] !== undefined)
  /** Every control's accessible name — how a removed field is checked structurally. */
  const controlNames = (tree) => [...walk(tree)]
    .filter((node) => node.type === InputMarker
      || node.type === SegmentedControlMarker
      || node.type === SwitchMarker)
    .map((node) => String(node.props['aria-label'] ?? node.props.label ?? ''))
  const idsOf = (tree) => [...walk(tree)]
    .map((node) => node.props?.id)
    .filter((id) => id !== undefined)
  const textOf = (node) => [...walk(node)]
    .filter((child) => typeof child === 'string')
    .join('')

  /**
   * Words that name the removed project-side settings. A control named for one of
   * them means the group came back, in some tab.
   */
  const REMOVED_CONTROLS = ['容器', '经验目录', '精细度']
  const projectKeyControls = (tree) => controlNames(tree)
    .filter((name) => REMOVED_CONTROLS.some((word) => name.includes(word)))
  const PROJECT_KEYS = ['container', 'lessons', 'mode']

  /** Select a tab the way the tab list does; returns the settled tree. */
  const selectTab = async (value) => {
    const tabs = getTabs(runtime.tree)
    if (tabs !== null && tabs.props.value !== value) {
      tabs.props.onChange(value)
      await settle()
    }
    return runtime.tree
  }

  /** Expand the 路径 disclosure if it is collapsed; returns the settled tree. */
  const openPaths = async () => {
    const disclosure = getDisclosure(runtime.tree)
    if (disclosure !== null && disclosure.props.open !== true) {
      disclosure.props.onToggle()
      await settle()
    }
    return runtime.tree
  }

  /* ---- 3a. the initial load populates the form from the server ---- */
  {
    // The document deliberately STATES the three project-side keys as well: they
    // are on disk, the route still reports them, and the page must neither render
    // a control for them nor send them back. A document that omitted them could
    // not tell "the page ignores them" from "there was nothing to ignore".
    const server = createServer({
      guidelinesEnabled: false, guidelinesLanguage: 'en',
      skillDir: '', guidelinesDir: '',
      container: 'notes', lessons: 'kb', mode: 'digest',
    })
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

    ok(textOf(loaded).includes('重启'), 'the panel says a restart is required')
    ok(textOf(loaded).includes('/home/.dsh/worklog/settings.json'),
      'the panel shows the settings file path it read')

    /* ---- the three-tab structure ---------------------------------------- */
    const tabs = getTabs(loaded)
    ok(tabs !== null, 'the panel renders the host SegmentedTabs')
    ok(tabs.props.value === 'skills', 'the selected tab defaults to 技能', String(tabs.props.value))
    ok(typeof tabs.props.label === 'string' && tabs.props.label !== '',
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

    /* ---- the panel wiring: the selected panel, and only it -------------- */
    const panels = tabPanels(loaded)
    ok(panels.length === 1, 'exactly one tabpanel is rendered', String(panels.length))
    ok(panels[0].props.id === 'dsh-worklog-panel-skills',
      'the rendered panel is the one the selected tab controls', String(panels[0].props.id))
    ok(panels[0].props['aria-labelledby'] === 'dsh-worklog-tab-skills',
      'the panel points back at its tab with aria-labelledby',
      String(panels[0].props['aria-labelledby']))
    ok(items[0].panelId === panels[0].props.id && items[0].id === panels[0].props['aria-labelledby'],
      'the tab\'s id/panelId and the panel\'s id/aria-labelledby are the same pair',
      `${items[0].id}/${items[0].panelId} vs ${panels[0].props['aria-labelledby']}/${panels[0].props.id}`)

    /* ---- the 路径 disclosure, and that it really HOLDS the two rows ----- */
    const disclosure = getDisclosure(loaded)
    ok(disclosure !== null, 'the 技能 panel renders the 路径 DisclosureRow')
    ok(disclosure.props.open === false, 'the 路径 area starts collapsed')
    ok(disclosure.props.expandable === true, 'the 路径 area is expandable')
    ok(getInputs(loaded).length === 0,
      'a collapsed 路径 area renders no input at all (its rows are children, not siblings)',
      String(getInputs(loaded).length))
    ok(markedRows(loaded).length === 0,
      'a collapsed 路径 area exposes no mark slot either', String(markedRows(loaded).length))

    await openPaths()
    const opened = runtime.tree
    const inputs = getInputs(opened)
    ok(inputs.length === 2, 'opening 路径 shows exactly two text inputs', String(inputs.length))
    ok(inputs[0].props.placeholder === 'skills/project-work-log',
      'a blank field shows the effective value as its placeholder',
      String(inputs[0].props.placeholder))
    ok(inputs[1].props.placeholder === 'skills/reliability-guidelines',
      'the guidelines directory does too', String(inputs[1].props.placeholder))

    // The right-hand "in effect" mark belongs to load-time options only. Read from
    // the row's own attribute rather than from the rendered text: this runtime
    // expands only the top-level component, so anything inside a nested component
    // is invisible to `textOf` — an earlier version of this assertion read a count
    // of 0 and passed anyway.
    const rows = markedRows(opened)
    ok(rows.length === 2, 'the two 路径 rows expose a mark slot', String(rows.length))
    ok(rows.every((node) => node.props['data-mark'] !== 'none'),
      'both carry an "in effect (default)" mark',
      rows.map((node) => node.props['data-mark']).join(' | '))
    ok(rows.every((node) => node.props['data-mark'].includes('（默认）')),
      'a carried mark says it is the default',
      rows.map((node) => node.props['data-mark']).join(' | '))

    /* ---- change 1: no control for the project-side keys, in EITHER tab -- */
    // Structural, not textual: the page's own compatibility note names these keys,
    // so text is exactly the wrong test. What must not come back is a CONTROL.
    ok(getSegment(loaded, 'dsh-worklog-mode') === null,
      'the 技能 tab has no mode SegmentedControl (it was removed)')
    ok(getSegments(loaded).length === 1,
      'the 技能 tab carries exactly one SegmentedControl — the language one',
      getSegments(loaded).map((node) => node.props.id).join(','))
    ok(projectKeyControls(loaded).length === 0,
      'no control in the 技能 tab is named for container / lessons / mode',
      projectKeyControls(loaded).join(' | '))
    ok(!idsOf(loaded).includes('dsh-worklog-mode'),
      'no node carries the removed mode control id',
      idsOf(loaded).join(','))
    ok(inputs.map((node) => node.props['aria-label']).join('|') === '工作记录技能目录|准则技能目录',
      'the only two inputs are the two load-time path fields',
      inputs.map((node) => node.props['aria-label']).join('|'))

    /* ---- the 高级 tab: the three load-time switches --------------------- */
    await selectTab('advanced')
    const advanced = runtime.tree
    ok(getTabs(advanced).props.value === 'advanced', 'the 高级 tab can be selected')
    const advancedPanels = tabPanels(advanced)
    ok(advancedPanels.length === 1 && advancedPanels[0].props.id === 'dsh-worklog-panel-advanced',
      'selecting 高级 renders its panel and only its panel',
      advancedPanels.map((node) => node.props.id).join(','))
    ok(advancedPanels[0].props['aria-labelledby'] === 'dsh-worklog-tab-advanced',
      'the 高级 panel points back at its own tab',
      String(advancedPanels[0].props['aria-labelledby']))
    const advancedSwitches = getSwitches(advanced)
    ok(advancedSwitches.length === 3, 'the 高级 tab holds three switches', String(advancedSwitches.length))
    ok(advancedSwitches.map((node) => node.props.label).join(',') === '装载时打日志,允许模型自动调用,允许手动调用',
      'the three switches are verbose / modelInvocable / userInvocable, in order',
      advancedSwitches.map((node) => node.props.label).join(','))
    ok(advancedSwitches.map((node) => node.props.checked).join(',') === 'false,true,true',
      'they reflect the loaded values (documented defaults when the file is silent)',
      advancedSwitches.map((node) => node.props.checked).join(','))
    ok(advancedSwitches.every((node) => typeof node.props.onChange === 'function'),
      'each of the three switches is controlled')
    ok(getInputs(advanced).length === 0, 'the 高级 tab holds no text input')
    ok(getSegments(advanced).length === 0, 'the 高级 tab holds no segmented control')
    ok(markedRows(advanced).length === 0, 'the 高级 tab exposes no mark slot')
    ok(projectKeyControls(advanced).length === 0,
      'no control in the 高级 tab is named for container / lessons / mode',
      projectKeyControls(advanced).join(' | '))
    ok(!idsOf(advanced).includes('dsh-worklog-mode'),
      'the 高级 tab carries no removed mode control id')
    ok(getDisclosure(advanced) === null, 'the 路径 disclosure belongs to the 技能 tab only')

    /* ---- the 记忆 tab: three defaults, all live-read ------------------- */
    await selectTab('memory')
    const memory = runtime.tree
    ok(getTabs(memory).props.value === 'memory', 'the 记忆 tab can be selected')
    const memoryPanels = tabPanels(memory)
    ok(memoryPanels.length === 1 && memoryPanels[0].props.id === 'dsh-worklog-panel-memory',
      'selecting 记忆 renders its panel and only its panel',
      memoryPanels.map((node) => node.props.id).join(','))
    const memorySwitches = getSwitches(memory)
    ok(memorySwitches.length === 3, 'the 记忆 tab holds three switches', String(memorySwitches.length))
    ok(memorySwitches.map((node) => node.props.label).join(',') === '启用全局记忆,默认注入记忆索引,个人目录可被检索',
      'the three switches are memoryEnabled / memoryInjectIndex / memoryPersonalSearchable, in order',
      memorySwitches.map((node) => node.props.label).join(','))
    ok(memorySwitches.map((node) => node.props.checked).join(',') === 'true,true,false',
      'their defaults are on / on / off',
      memorySwitches.map((node) => node.props.checked).join(','))
    // The master switch genuinely needs a restart (it decides whether the prompt section and
    // the tool are registered at all); the other two are read at use time. The panel must say
    // both things rather than one blanket sentence for the whole page.
    // The restart wording and the upload-permission pointer are CARRIED BY THE DICTIONARY,
    // and that is what these assert. `textOf` cannot see them: it only reaches strings on
    // top-level elements, and both live inside panel elements or nested components. Asserting
    // the rendered text would therefore be a test that can never fail — the mistake this
    // project already made once.
    const clientExports = handoff.factory(loadRequire)
    ok(clientExports.DICT_ZH['restart.memory'].includes('需重启')
      && clientExports.DICT_ZH['restart.memory'].includes('即时生效'),
      'the 记忆 panel copy distinguishes the load-time switch from the live ones',
      clientExports.DICT_ZH['restart.memory'])
    ok(clientExports.DICT_EN['restart.memory'].includes('restart')
      && clientExports.DICT_EN['restart.memory'].includes('immediately'),
      'the English copy draws the same distinction',
      clientExports.DICT_EN['restart.memory'])
    // Upload permission is a per-workspace fact and must not appear as a control here; the
    // panel has to SAY where it lives, or a reader hunts for a switch that never existed.
    ok(clientExports.DICT_ZH['memory.note'].includes('发布.md'),
      'the 记忆 copy says upload permission lives in each workspace\'s 发布.md',
      clientExports.DICT_ZH['memory.note'])
    ok(memoryPanels[0].props['aria-labelledby'] === 'dsh-worklog-tab-memory',
      'the 记忆 panel points back at its own tab',
      String(memoryPanels[0].props['aria-labelledby']))
    ok(projectKeyControls(memory).length === 0,
      'the 记忆 tab offers no control for container / lessons / mode',
      projectKeyControls(memory).join(' | '))

    await selectTab('skills')
    ok(getTabs(runtime.tree).props.value === 'skills', 'the 技能 tab can be selected again')
  }

  /* ---- 3b. clicking the Switch posts the whole form, serially ---- */
  {
    const server = createServer({
      guidelinesEnabled: true, guidelinesLanguage: 'zh', container: 'notes',
    })
    globalThis.fetch = server.fetchStub

    api.mount(SettingsPanel, {})
    api.flushEffects()
    await settle()
    await selectTab('skills')
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
    const postedKeys = Object.keys(server.state.posts[1] ?? {}).sort()
    // Ten keys now: the seven load-time ones plus the three memory defaults. What this
    // assertion is really guarding is the ABSENCE of the project-side trio, which the next
    // check pins directly — so the two overlap on purpose.
    ok(postedKeys.join(',') === 'guidelinesDir,guidelinesEnabled,guidelinesLanguage,'
      + 'memoryEnabled,memoryInjectIndex,memoryPersonalSearchable,'
      + 'modelInvocable,skillDir,userInvocable,verbose',
      'the body is exactly the ten keys the page owns — no project-side key is sent',
      postedKeys.join(','))
    ok(PROJECT_KEYS.every((key) => !(key in (server.state.posts[1] ?? {}))),
      'the page never posts container / lessons / mode back',
      JSON.stringify(server.state.posts[1]))
    ok(server.state.document.container === 'notes',
      'a project-side value already on disk survives the page\'s save (the route patches)',
      JSON.stringify(server.state.document))
    ok(server.state.document.guidelinesEnabled === true, 'the server state ended at the last value')
    ok(getSwitch(runtime.tree).props.checked === true,
      'the Switch shows the value the server confirmed')

    const texts = textOf(runtime.tree)
    ok(texts.includes('已保存'), 'the panel reports the save as done')
  }

  /* ---- 3c. the segmented control, a text input, and the disclosure ---- */
  {
    const server = createServer({ guidelinesEnabled: true, guidelinesLanguage: 'zh' })
    globalThis.fetch = server.fetchStub

    api.mount(SettingsPanel, {})
    api.flushEffects()
    await settle()
    await selectTab('skills')

    const language = getSegment(runtime.tree, 'dsh-worklog-guidelines-language')
    language.props.onChange('en')
    await settle(12)
    ok(server.state.document.guidelinesLanguage === 'en',
      'choosing English persists guidelinesLanguage=en',
      JSON.stringify(server.state.document))

    // The paths are collapsed by default now, so they have to be revealed before
    // they can be typed into — that is the point of the disclosure.
    await openPaths()
    const skillDirInput = getInputs(runtime.tree)[0]
    skillDirInput.props.onChange({ target: { value: '/opt/bundles/worklog' } })
    await settle(12)
    ok(server.state.document.skillDir === '/opt/bundles/worklog',
      'typing a path persists it',
      JSON.stringify(server.state.document.skillDir))

    const advanced = getDisclosure(runtime.tree)
    advanced.props.onToggle()
    await settle()
    ok(getDisclosure(runtime.tree).props.open === false,
      'toggling the DisclosureRow collapses the 路径 area again')
    ok(getInputs(runtime.tree).length === 0,
      'a collapsed 路径 area takes its rows out of the tree')
  }

  /* ---- 3d. a failed save is reported, not swallowed ---- */
  {
    const server = createServer({ guidelinesEnabled: true }, { failPost: true })
    globalThis.fetch = server.fetchStub

    api.mount(SettingsPanel, {})
    api.flushEffects()
    await settle()
    await selectTab('skills')
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

  /* ---- 3f. the 高级 tab: the three switches that had no control before ---- */
  {
    const server = createServer({ guidelinesEnabled: true, guidelinesLanguage: 'zh' })
    globalThis.fetch = server.fetchStub

    api.mount(SettingsPanel, {})
    api.flushEffects()
    await settle()
    await selectTab('advanced')

    const switches = getSwitches(runtime.tree)
    ok(switches.length === 3, 'the 高级 tab holds the three load-time switches', String(switches.length))
    ok(switches.map((node) => node.props.checked).join(',') === 'false,true,true',
      'absent keys fall back to the documented defaults (off, on, on)',
      switches.map((node) => node.props.checked).join(','))

    switches[0].props.onChange(true)
    await settle(20)
    ok(server.state.document.verbose === true,
      'toggling verbose persists it (this key had no control before)',
      JSON.stringify(server.state.document))

    getSwitches(runtime.tree)[1].props.onChange(false)
    await settle(20)
    ok(server.state.document.modelInvocable === false,
      'toggling modelInvocable persists it', JSON.stringify(server.state.document))

    getSwitches(runtime.tree)[2].props.onChange(false)
    await settle(20)
    ok(server.state.document.userInvocable === false,
      'toggling userInvocable persists it', JSON.stringify(server.state.document))

    ok(server.state.posts.length === 3, 'three changes produced three POSTs',
      String(server.state.posts.length))
    ok(PROJECT_KEYS.every((key) => server.state.posts.every((post) => !(key in post))),
      'no POST from this tab mentions a project-side key either')
    ok(getSwitches(runtime.tree).map((node) => node.props.checked).join(',') === 'true,false,false',
      'the three switches show what the server confirmed',
      getSwitches(runtime.tree).map((node) => node.props.checked).join(','))

    await selectTab('skills')
    ok(getTabs(runtime.tree).props.value === 'skills', 'the 技能 tab is still reachable afterwards')
  }
}

console.log(problems.length === 0
  ? '\nclient runtime OK — the bundle mounts, loads, saves and reports'
  : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
