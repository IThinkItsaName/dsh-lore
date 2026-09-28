// Locate the package under test, wherever this file is run from.
//
// The same harnesses run from two places — the copy inside the package
// (`<pkg>/tests/`) and the working copy in this workspace (`logs/tests/`) — so a
// bare `resolve(HERE, '..')` is wrong for one of them: from `logs/tests` the parent
// is `logs`, not the package. Probe instead of assuming.
import { existsSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { createRequire, registerHooks } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

/**
 * Let the harness resolve `@deepseek-ai/*`, the way the host does.
 *
 * The host supplies those packages to plugins through its own loader
 * (`dsh-ref/PLUGIN-AUTHORING.md` §4.3: two anchors — the dsh installation, then the profile —
 * with the resolution set being the installed manifest's `dependencies` + `peerDependencies`
 * closure). A bare `node tests/run.mjs` has no such loader, so the moment `lib/index.js`
 * imports one of them the harness fails with `ERR_MODULE_NOT_FOUND` and **the plugin cannot be
 * loaded at all** — which would make every other assertion unrunnable rather than merely
 * failing.
 *
 * Two ways out, and the choice matters:
 *   - keep the plugin free of `@deepseek-ai` imports, and lose the standard APIs; or
 *   - teach the harness to resolve them, and test against the host's **real** implementations.
 *
 * The second is used when `dsh-ref/source` is present (a local, sha256-verified dump of the
 * shipped packages). It is a **reference tree, not part of this project**, so its absence is
 * normal on a clean checkout: the hook then simply does not install, the import fails loudly,
 * and the message says which specifier could not be placed and where it looked. Failing loudly
 * is right here — a silently-skipped load would report a passing suite for a plugin that never
 * ran.
 */
function installHostSpecifierResolver() {
  const candidates = [
    resolve(HERE, '..', '..', 'dsh-ref', 'source', '@deepseek-ai'), // logs/tests → workspace
    resolve(HERE, '..', '..', '..', 'dsh-ref', 'source', '@deepseek-ai'), // <pkg>/tests
  ]
  const sourceRoot = candidates.find((dir) => existsSync(dir))
  if (sourceRoot === undefined) return null

  const hook = (specifier, context, nextResolve) => {
    const match = /^@deepseek-ai\/([^/]+)(\/.*)?$/.exec(specifier)
    if (match === null) return nextResolve(specifier, context)
    const [, name, subpath = ''] = match
    const pkgDir = join(sourceRoot, name)
    if (!existsSync(pkgDir)) return nextResolve(specifier, context)
    // Ask the package's own manifest to place the specifier, so `exports` conditions are
    // honoured rather than guessed. `createRequire` needs a base *inside* the package.
    try {
      const req = createRequire(join(pkgDir, 'package.json'))
      return { url: pathToFileURL(req.resolve(`@deepseek-ai/${name}${subpath}`)).href, shortCircuit: true }
    } catch {
      return nextResolve(specifier, context)
    }
  }
  try {
    registerHooks({ resolve: hook })
  } catch {
    // An older Node without `registerHooks`. Same reasoning as above: the import then fails
    // loudly on its own rather than this file pretending to have solved it.
    return null
  }
  return sourceRoot
}

/** This file's directory (the tests directory). */
export const HERE = dirname(fileURLToPath(import.meta.url))

/**
 * Where `@deepseek-ai/*` will be resolved from, or `null` when the hook could not install.
 *
 * Runs here, after `HERE` — and it must run at module-evaluation time, before any harness
 * imports the plugin under test.
 */
export const HOST_SOURCE_ROOT = installHostSpecifierResolver()

function isPackageDir(dir) {
  const manifest = join(dir, 'package.json')
  if (!existsSync(manifest) || !existsSync(join(dir, 'cordis.patch.yml'))) return false
  try {
    return JSON.parse(readFileSync(manifest, 'utf8')).name === 'dsh-worklog'
  } catch {
    return false
  }
}

function findPackage() {
  // An explicit override wins, for an unusual layout.
  if (process.env.DSH_WORKLOG_PKG) return resolve(process.env.DSH_WORKLOG_PKG)

  const candidates = [
    resolve(HERE, '..'),                 // tests/ inside the package
    resolve(HERE, '..', 'publish', 'worklog'), // tests/ in the workspace next to publish/
    resolve(HERE, '..', '..', 'publish', 'worklog'), // one level deeper
  ]
  for (const dir of candidates) {
    if (isPackageDir(dir)) return dir
  }
  throw new Error(
    `cannot locate the dsh-worklog package from ${HERE}; ` +
    'set DSH_WORKLOG_PKG to its absolute path',
  )
}

export const PKG = findPackage()

/*
 * Isolate the settings file.
 *
 * Importing this module must be enough to keep the harnesses off the real, user-owned
 * settings file (`$DSH_HOME/worklog/settings.json`), because `apply()` reads that file
 * from disk on every mount. Without this, a developer's own settings leak into the
 * suite and assertions start failing for reasons that have nothing to do with the code:
 * `container` / `lessons` / `mode` present in a real file made `run.mjs` report
 * "ignoring unsupported config keys" and drop 13 assertions. A suite that goes red when
 * you use the product is worse than no suite — it teaches people to ignore red.
 *
 * The path need not exist; `readStoredSettings()` reports "absent" and everything falls
 * back to built-in defaults, which is what a test that does not care about settings
 * wants. A harness that DOES exercise the file sets DSH_WORKLOG_SETTINGS to its own
 * temp path, overriding this.
 */
export const ISOLATED_SETTINGS_FILE = join(PKG, 'tests', 'tmp', 'settings-isolated.json')
if (process.env.DSH_WORKLOG_SETTINGS === undefined) {
  process.env.DSH_WORKLOG_SETTINGS = ISOLATED_SETTINGS_FILE
}

/*
 * Isolate the memory root, for the same reason.
 *
 * `memoryDirectory()` defaults to `$DSH_HOME/memory`, which on a machine that actually uses
 * this plugin is a real directory full of real lessons. A harness that read it would assert
 * against whatever the developer happens to have collected — and, worse, a harness that WROTE
 * there would corrupt it. Pointing at a per-run temp path makes an un-exercised root the
 * default (absent, which every reader already handles) and lets a harness that cares create
 * its own under the system temp directory.
 *
 * Under `tmpdir()`, NOT under the package: a fixture left inside `<pkg>/tests/` is reported by
 * `_package.py --check` as drift, because drift means exactly "the package has files the mirror
 * does not". A harness must not leave anything in the tree it is verifying.
 */
export const ISOLATED_MEMORY_ROOT = join(tmpdir(), 'dsh-worklog-memory-isolated')
if (process.env.DSH_WORKLOG_MEMORY === undefined) {
  process.env.DSH_WORKLOG_MEMORY = ISOLATED_MEMORY_ROOT
}
