// Client-half contract: does the host have everything it needs to load
// `lib/client.js`, and can that file actually run under the browser loader?
//
// Everything here exists because the failure is SILENT or fatal-late:
//
//   1. `dsh.client` declared without `exports["./client"]` throws at load time
//      (`packages/client/modules/src/index.ts` — "declares dsh.client but
//      exports no ./client bundle"), and the client path is taken VERBATIM from
//      `exports["./client"]`. Declaring one without the other is a hard failure,
//      not a warning.
//   2. The bundle reaches the browser as BYTES. A syntax error in hand-written
//      JavaScript therefore surfaces as a broken settings page with nothing in
//      the node-side log — so it is parsed here instead.
//   3. `require` inside the factory is the browser loader's lookup, not Node's.
//      Only NINE specifiers exist in its frozen table
//      (`packages/client/web/src/seed.ts`: "the ONLY entities the shell shares
//      into the frozen module table"). A tenth specifier can never resolve, and
//      nothing says so until the page loads — this is the check that earns its
//      keep.
//
//   node tests/audit-client.mjs
import { readFileSync, existsSync } from 'node:fs'
import { PKG } from './_pkg.mjs'

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}

/**
 * The frozen module table, verbatim from packages/client/web/src/seed.ts.
 *
 * Kept as a literal list rather than imported: this package must not depend on
 * the DSH tree, and the point of the check is that the two lists are compared
 * by a human reading them side by side when DSH changes.
 */
const BASELINE = [
  'react',
  'react/jsx-runtime',
  'react-dom',
  'react-dom/client',
  '@deepseek-ai/cordis',
  '@deepseek-ai/dsh-client-store',
  '@deepseek-ai/dsh-client-ui-slots',
  '@deepseek-ai/dsh-client-ui-primitives',
  '@deepseek-ai/dsh-client-ui-dockkit',
]

const pkg = JSON.parse(readFileSync(`${PKG}/package.json`, 'utf8'))

/* ---- 1. the manifest declaration the host reads ---- */
const clientExport = pkg.exports?.['./client']
ok(clientExport !== undefined,
  'package.json exports a ./client subpath',
  `without it the host throws "declares dsh.client but exports no \\"./client\\" bundle"; exports: ${Object.keys(pkg.exports ?? {}).join(', ')}`)
ok(typeof clientExport === 'string',
  'exports["./client"] is a plain path string (the host joins it directly)', String(clientExport))

const clientRel = typeof clientExport === 'string' ? clientExport.replace(/^\.\//, '') : ''
const clientPath = `${PKG}/${clientRel}`
ok(clientRel !== '' && existsSync(clientPath),
  'the file exports["./client"] names exists', clientPath)

const shipping = pkg.files ?? []
ok(shipping.includes('lib') || shipping.includes(clientRel),
  'package.json files ships the client bundle', JSON.stringify(shipping))

/* ---- 2. the dsh.client declaration ---- */
const client = pkg.dsh?.client
ok(client !== undefined && typeof client === 'object',
  'package.json declares dsh.client', JSON.stringify(pkg.dsh))
ok(client?.platform === 'web',
  'dsh.client.platform is "web"', String(client?.platform))
ok(Array.isArray(client?.inject) && client.inject.length === 0,
  'dsh.client.inject is an empty array', JSON.stringify(client?.inject))
ok(client?.immediately === true,
  'dsh.client.immediately is true (the settings seat must exist before first render)',
  String(client?.immediately))

/* ---- 3. the bundle parses as JavaScript and carries the loader wrapper ---- */
if (!existsSync(clientPath)) {
  console.log('\nclient bundle missing; parse and require checks skipped')
  console.log(`\n${problems.length} FAILED`)
  process.exit(1)
}
const source = readFileSync(clientPath, 'utf8')
ok(source.length > 0, 'the client bundle is non-empty')

let parseError = null
try {
  // Not `import`: this is a browser bundle that touches `window` at top level.
  // Parsing is exactly the check that a syntax error cannot reach the browser.
  new Function(source)
} catch (error) {
  parseError = error
}
ok(parseError === null, 'the client bundle parses as JavaScript',
  parseError === null ? '' : String(parseError))

const wrapper = /window\.__ModuleLoader__\.load\(\{/.exec(source)
ok(wrapper !== null, 'the bundle opens the window.__ModuleLoader__.load({...}) wrapper',
  'the loader never runs a file without it, and nothing else reports that')

const idMatch = /id:\s*['"]([^'"]+)['"]/.exec(source)
ok(idMatch !== null, 'the wrapper declares an id', String(idMatch?.[1]))
ok(idMatch?.[1] === pkg.name,
  'the wrapper id equals the package name (host and bundle agree on the module id)',
  `${String(idMatch?.[1])} vs ${pkg.name}`)

const factoryMatch = /factory:\s*(?:function\s*\(\s*(\w+)\s*\)|\(\s*(\w+)\s*\)\s*=>)/.exec(source)
ok(factoryMatch !== null, 'the wrapper declares a factory taking the loader require',
  'factory: (require) => { ... }')
const factoryParam = factoryMatch?.[1] ?? factoryMatch?.[2] ?? ''
ok(factoryParam !== '',
  'the factory parameter is a plain identifier (the host passes it positionally)',
  String(factoryParam))

const returnMatch = /return\s+module\.exports/.test(source)
ok(returnMatch, 'the factory returns module.exports')
ok(/var\s+module\s*=\s*\{\s*exports:\s*\{\}\s*\}/.test(source),
  'the factory body builds the CJS shell (var module = { exports: {} })')

/* ---- 4. every require(...) specifier resolves in the frozen table ---- */
const specifiers = [...source.matchAll(new RegExp(`${factoryParam}\\s*\\(\\s*['"]([^'"]+)['"]\\s*\\)`, 'g'))]
  .map((match) => match[1])
ok(specifiers.length > 0, 'the bundle requires at least one module', `${specifiers.length} site(s)`)

const outside = [...new Set(specifiers)].filter((name) => !BASELINE.includes(name))
ok(outside.length === 0,
  'every require() specifier is in the nine-item baseline',
  outside.length === 0
    ? ''
    : `${outside.join(', ')} cannot resolve in the browser; the baseline is ${BASELINE.join(', ')}`)

console.log(`      requires: ${[...new Set(specifiers)].join(', ') || '(none)'}`)

/* ---- 5. the wrapper must not be an ES module (the loader expects plain JS) ---- */
ok(!/^\s*export\s/m.test(source),
  'the bundle has no top-level ESM export (the loader evaluates it as a script)',
  'use exports.<name> = ... inside the factory instead')
ok(!/^\s*import\s/m.test(source),
  'the bundle has no top-level ESM import', 'the factory parameter require is the only lookup')

/* ---- 6. no JSX: the whole point is that there is no build step ---- */
// The parse above already rejects JSX (it is not JavaScript), so this only
// records WHICH mechanism the file uses for elements — the choice that keeps
// the build step away.
const createElementSites = (source.match(/\.createElement\(|(?<![\w.$])h\(/g) ?? []).length
ok(createElementSites > 0,
  'elements are built with React.createElement (no JSX, so no transpile step)',
  `${createElementSites} createElement site(s)`)
ok(!/<[A-Z][A-Za-z0-9.]*\s*\/?>/.test(source),
  'no JSX-looking component tags are present', 'e.g. <Switch ...> would not parse anyway')

/* ---- 7. the two locale dictionaries must carry the same keys ---- */
// `locale.register(ns, { zh, en })` looks a key up in the active language and
// then in English, so a key missing from a dictionary renders as the raw key —
// invisible here, visible to a user as `advanced.title` on the page.
const dictKeys = (name) => {
  const start = source.indexOf(`const ${name} = {`)
  if (start === -1) return null
  const end = source.indexOf('\n    }', start)
  if (end === -1) return null
  const block = source.slice(start, end)
  return new Set([...block.matchAll(/^\s*'([^']+)':/gm)].map((match) => match[1]))
}
const zhKeys = dictKeys('DICT_ZH')
const enKeys = dictKeys('DICT_EN')
ok(zhKeys !== null && enKeys !== null, 'both dictionaries are present and readable',
  `zh=${zhKeys?.size ?? 'missing'} en=${enKeys?.size ?? 'missing'}`)
if (zhKeys !== null && enKeys !== null) {
  const missingInEn = [...zhKeys].filter((key) => !enKeys.has(key))
  const missingInZh = [...enKeys].filter((key) => !zhKeys.has(key))
  ok(missingInEn.length === 0, 'every zh key exists in en', missingInEn.join(', '))
  ok(missingInZh.length === 0, 'every en key exists in zh', missingInZh.join(', '))
  console.log(`      dictionaries: ${zhKeys.size} keys, ${missingInEn.length + missingInZh.length} mismatched`)
}

/* ---- 8. every t('...') call site names a key the dictionary holds ---- */
if (zhKeys !== null) {
  const used = new Set([...source.matchAll(/\bt\(\s*'([^']+)'\s*\)/g)].map((match) => match[1]))
  const unknown = [...used].filter((key) => !zhKeys.has(key))
  ok(unknown.length === 0, 'every t() key resolves in the dictionary',
    unknown.length === 0 ? '' : `unresolved: ${unknown.join(', ')}`)
  console.log(`      t() keys used: ${used.size}`)
}

console.log(problems.length === 0
  ? `\nclient half OK — ${clientRel} loads under id ${pkg.name} with ${[...new Set(specifiers)].length} resolvable require(s)`
  : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
