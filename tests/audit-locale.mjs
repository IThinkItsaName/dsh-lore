// Plugin display metadata (the Plugin Manager page's title and description).
//
// DSH reads a plugin's display text from `locale/<language>.json` INSIDE the
// package, resolved through the Node module resolver with the specifier
// `<pkg>/locale/<lang>.json`. Two failure modes are completely silent, which is
// why this is checked rather than trusted:
//
//   1. Without an `exports` subpath for `./locale/*`, resolution throws
//      ERR_PACKAGE_PATH_NOT_EXPORTED — and the caller treats that as "no locale
//      files", so the page falls back to `package.json` name/description with no
//      warning anywhere.
//   2. Without `locale` in `files`, npm never ships the directory, so an installed
//      copy is English-only no matter what the repo contains.
//
// Shape, from App Boot's readPluginMeta/dictionariesOf:
//   - `en.json` is the ANCHOR: it locates the directory. Missing it means every
//     other language file is ignored, not just English.
//   - every `.json` sibling of en.json is read; the filename stem is the language
//     id, which must match /^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$/ and be unique
//     case-insensitively.
//   - each file is `{ "meta": { "title": string, "description": string } }`.
//
//   node tests/audit-locale.mjs
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { PKG } from './_pkg.mjs'

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}

const pkg = JSON.parse(readFileSync(`${PKG}/package.json`, 'utf8'))
const localeDir = `${PKG}/locale`

/* ---- 1. the manifest lets the locale subpath resolve at all ---- */
const exportsKeys = Object.keys(pkg.exports ?? {})
const localeExport = exportsKeys.find((k) => k === './locale/*' || k.startsWith('./locale'))
ok(localeExport !== undefined,
   'package.json exports a ./locale/* subpath',
   `without it the resolver throws ERR_PACKAGE_PATH_NOT_EXPORTED and DSH silently shows the manifest text; got ${exportsKeys.join(', ')}`)

/* ---- 2. the locale directory ships ---- */
ok((pkg.files ?? []).includes('locale'),
   'package.json files includes "locale"',
   'otherwise npm never publishes it and an installed copy stays English-only')
ok(existsSync(localeDir), 'the locale directory exists on disk')

/* ---- 3. en.json is the anchor and must exist ---- */
ok(existsSync(`${localeDir}/en.json`),
   'locale/en.json exists (the anchor that locates the directory)',
   'without the anchor every other language file is ignored')

/* ---- 4. the real resolver accepts every locale file ---- */
const require = createRequire(`${PKG}/package.json`)
const pkgName = pkg.name
const files = existsSync(localeDir)
  ? readdirSync(localeDir).filter((f) => f.endsWith('.json'))
  : []
ok(files.length >= 2, 'at least two language files are present', files.join(', '))

const LANGUAGE_ID = /^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$/
const seen = new Set()
for (const file of files) {
  const lang = file.slice(0, -5)
  ok(LANGUAGE_ID.test(lang), `locale/${file} uses a valid language id`, lang)
  const lower = lang.toLowerCase()
  ok(!seen.has(lower), `locale/${file} does not duplicate another id case-insensitively`, lower)
  seen.add(lower)

  // The specifier DSH actually resolves.
  const specifier = `${pkgName}/locale/${file}`
  let resolved
  try {
    resolved = require.resolve(specifier)
  } catch (error) {
    ok(false, `${specifier} resolves through the package exports`, error.code ?? String(error))
    continue
  }
  ok(resolved !== undefined, `${specifier} resolves through the package exports`)

  /* ---- 5. the file shape DSH parses ---- */
  let parsed
  try {
    parsed = JSON.parse(readFileSync(resolved, 'utf8'))
  } catch (error) {
    ok(false, `locale/${file} is valid JSON`, String(error))
    continue
  }
  ok(typeof parsed?.meta === 'object' && parsed.meta !== null && !Array.isArray(parsed.meta),
     `locale/${file} has a "meta" object`, JSON.stringify(Object.keys(parsed ?? {})))
  ok(typeof parsed?.meta?.title === 'string' && parsed.meta.title !== '',
     `locale/${file} meta.title is a non-empty string`, String(parsed?.meta?.title))
  ok(typeof parsed?.meta?.description === 'string' && parsed.meta.description !== '',
     `locale/${file} meta.description is a non-empty string`, String(parsed?.meta?.description))
}

/* ---- 6. the languages must actually differ, or the point is lost ---- */
const texts = new Map()
for (const file of files) {
  try {
    const parsed = JSON.parse(readFileSync(`${localeDir}/${file}`, 'utf8'))
    texts.set(file.slice(0, -5), parsed?.meta?.title ?? '')
  } catch { /* reported above */ }
}
if (texts.size >= 2) {
  const values = [...texts.values()]
  ok(new Set(values).size > 1,
     'the language files carry different titles', JSON.stringify([...texts]))
}

/* ---- 7. reproduce what DSH builds, so the result is visible ---- */
const dictionaries = new Map()
for (const file of files) {
  const parsed = JSON.parse(readFileSync(`${localeDir}/${file}`, 'utf8'))
  dictionaries.set(file.slice(0, -5).toLowerCase(), {
    title: parsed?.meta?.title,
    description: parsed?.meta?.description,
  })
}
const localized = (field, fallback) => {
  const entries = [...dictionaries].flatMap(([lang, fields]) =>
    (fields[field] === undefined ? [] : [[lang, fields[field]]]))
  if (entries.length === 0) return fallback
  return { en: fallback ?? '', ...Object.fromEntries(entries) }
}
const title = localized('title', pkg.name)
const description = localized('description', pkg.description)
ok(typeof title === 'object' && Object.keys(title).length > 1,
   'DSH would receive a multi-language title map, not a bare string', JSON.stringify(title))
ok(typeof description === 'object' && Object.keys(description).length > 1,
   'DSH would receive a multi-language description map', JSON.stringify(Object.keys(description)))
console.log(`      title       -> ${JSON.stringify(title)}`)
console.log(`      description -> ${Object.keys(description).join(', ')}`)

console.log(problems.length === 0 ? '\nplugin locale metadata OK' : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
