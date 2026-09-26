// Locate the package under test, wherever this file is run from.
//
// The same harnesses run from two places — the copy inside the package
// (`<pkg>/tests/`) and the working copy in this workspace (`logs/tests/`) — so a
// bare `resolve(HERE, '..')` is wrong for one of them: from `logs/tests` the parent
// is `logs`, not the package. Probe instead of assuming.
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

/** This file's directory (the tests directory). */
export const HERE = dirname(fileURLToPath(import.meta.url))

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
