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
