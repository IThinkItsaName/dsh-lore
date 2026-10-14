// Locate the package under test, wherever this file is run from.
//
// The same harnesses run from two places — the copy inside the package
// (`<pkg>/tests/`) and the working copy in this workspace (`logs/tests/`) — so a
// bare `resolve(HERE, '..')` is wrong for one of them: from `logs/tests` the parent
// is `logs`, not the package. Probe instead of assuming.
import { existsSync, readFileSync, readdirSync } from 'node:fs'
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
    return JSON.parse(readFileSync(manifest, 'utf8')).name === 'dsh-lore'
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
    `cannot locate the dsh-lore package from ${HERE}; ` +
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
 * 默认根是 `<用户主目录>/dsh-lore-memory`（2026-10-14 起不再挂在 `$DSH_HOME` 下），而
 * `<DSH_HOME>/memory` 仍是**一次性迁移的来源**。在一台真用这个插件的机器上，两者都是
 * 满满的真题：harness 读了它就会拿"开发者碰巧攒下的东西"当基准断言；写了它更糟。
 * 指向每次运行的临时路径，让没被显式演练的根保持"不存在"（每个读取方本来就要处理这一档），
 * 而关心它的 harness 自己在系统临时目录下另建一份。
 *
 * Under `tmpdir()`, NOT under the package: a fixture left inside `<pkg>/tests/` is reported by
 * `_package.py --check` as drift, because drift means exactly "the package has files the mirror
 * does not". A harness must not leave anything in the tree it is verifying.
 */
export const ISOLATED_MEMORY_ROOT = join(tmpdir(), 'dsh-lore-memory-isolated')
if (process.env.DSH_WORKLOG_MEMORY === undefined) {
  process.env.DSH_WORKLOG_MEMORY = ISOLATED_MEMORY_ROOT
}

/*
 * Isolate `$DSH_HOME` too, and **unconditionally** — this one has no "a harness that cares
 * sets its own" escape hatch, because two things read it that no other variable can redirect:
 *
 *   - `settingsFilePath()`（`<DSH_HOME>/worklog/settings.json`）—— 只在**没有**
 *     `DSH_WORKLOG_SETTINGS` 时才轮到它，而"没有"恰恰是最容易发生的那种写法；
 *   - `legacyMemoryDirectory()`（`<DSH_HOME>/memory`）—— 那是迁移的**来源**。
 *
 * 第二条在 2026-10-14 变成真事故：`apply()` 每次装载都会试着把旧根整份复制进新根。在一个
 * 真有 `<DSH_HOME>/memory` 的机器上跑一遍 harness，真实记忆就被**复制**进共享的
 * `<tmpdir>/dsh-lore-memory-isolated/` 并留下 `.moved-from-dsh-home` 痕迹（源不会被删，
 * 但私人数据落进了临时目录，测试也随之变成有状态）——`RELEASING.md` 的排障表把这条写成
 * "门禁在开发者机器上变红 = harness 读了真实设置文件或真实记忆根"。python 半边一直钉着它
 * （`_selftest.py` 在 try/finally 里设 `DSH_HOME`），JS 半边直到 `audit-memory-settings.mjs`
 * 出现才补上。钉死在这里，任何 harness 都不会漏。
 *
 * 必须在这里钉（`_pkg.mjs` 的顶层，任何 harness 的 import 之后、被测模块之前）：那两个
 * 函数都在**调用时**读环境变量，所以只要在第一次 `apply()` 之前设好就够，但放在最前面才
 * 不会漏 —— 这个文件本来就是所有 harness 的第一条 import。
 */
export const ISOLATED_DSH_HOME = join(tmpdir(), 'dsh-lore-dsh-home-isolated')
if (process.env.DSH_HOME === undefined) {
  process.env.DSH_HOME = ISOLATED_DSH_HOME
}

/*
 * Extra skill bundles this package ships beside the two it mounts by name.
 *
 * The harnesses assert how many providers `apply()` registers, and the first version of that
 * assertion said "2" outright — so it went red the moment a third bundle was added, which says
 * nothing about whether the third bundle is actually served. Deriving the count from the package
 * directory keeps the assertion about the invariant that matters ("one provider per bundle on
 * disk") instead of about today's arithmetic.
 *
 * `project-work-log` and `reliability-guidelines` are mounted by name (the latter only when
 * `guidelinesEnabled`), so they are not "extra".
 */
export function extraBundledSkills() {
  const skillsRoot = join(PKG, 'skills')
  let names
  try {
    names = readdirSync(skillsRoot, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .filter((name) => existsSync(join(skillsRoot, name, 'SKILL.md')))
  } catch {
    return []
  }
  return names
    .filter((name) => name !== 'project-work-log' && name !== 'reliability-guidelines')
    .sort()
}
