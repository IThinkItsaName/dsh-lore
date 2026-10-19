// 把独立技能仓库的 `skills/project-work-log/` 同步进本插件仓库（vendored 副本）。
//
// 为什么需要这道门禁：2026-10-19 起技能层有了独立仓库
// `publish/project-work-log/`（自己的 git 史、自己的发布节奏），而 DSH 插件运行时
// **必须**带着这份技能（`skillDir` 默认值、`preaudit` 哈希 served body）。两份副本
// 之间没有门禁就会悄悄漂移，而漂移的症状是"模型看到的技能正文和 pi 里的不是一份"。
//
// 方向永远只有一条：**独立仓库 → 本仓库**。不要反过来改 vendored 副本（下一次同步
// 会静默覆盖）；要改技能就改独立仓库，再跑本脚本。
//
//   node tools/sync-skill.mjs            # 同步
//   node tools/sync-skill.mjs --check    # 只检查（漂移 → 退出码 1；源仓库缺席 → SKIP/0）
//   node tools/sync-skill.mjs --source DIR   # 指定另一份技能源（测试/特殊布局）
//
// `checkSkillSync()` 同时被 `tests/audit-skill-sync.mjs` import，供 `test:plugin` 链使用。
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, '..')
const DEFAULT_SOURCE = resolve(REPO, '..', 'project-work-log', 'skills', 'project-work-log')
const DEST = join(REPO, 'skills', 'project-work-log')

/** Directory names / extensions that are never part of a skill. */
const SKIP_NAMES = new Set(['__pycache__', '.DS_Store', 'Thumbs.db'])
const SKIP_EXT = new Set(['.pyc'])

/** POSIX-shaped relative path, so output and comparison do not depend on the platform. */
const rel = (base, file) => relative(base, file).split(sep).join('/')

/** Every regular file under root → Map(relative path → absolute path). */
function walk(root) {
  const out = new Map()
  const visit = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (SKIP_NAMES.has(entry.name) || SKIP_EXT.has(entry.name.slice(entry.name.lastIndexOf('.')))) continue
      const full = join(dir, entry.name)
      if (entry.isDirectory()) visit(full)
      else if (entry.isFile()) out.set(rel(root, full), full)
    }
  }
  visit(root)
  return out
}

/**
 * Compare the vendored copy against the independent skill repo.
 *
 * @returns {{ status: 'skip'|'ok'|'drift', source: string, dest: string, count: number, problems: string[] }}
 *   `skip` means the sibling repo is not checked out — a local two-repo gate cannot run,
 *   and a bare plugin checkout should not be reported as broken.
 */
export function checkSkillSync({ source = DEFAULT_SOURCE, dest = DEST } = {}) {
  if (!existsSync(source) || !statSync(source).isDirectory()) {
    return { status: 'skip', source, dest, count: 0, problems: [] }
  }
  const sourceFiles = walk(source)
  const destFiles = existsSync(dest) ? walk(dest) : new Map()
  const problems = []
  for (const [path, file] of sourceFiles) {
    if (!destFiles.has(path)) {
      problems.push(`missing in the vendored copy: ${path}`)
      continue
    }
    if (!readFileSync(file).equals(readFileSync(destFiles.get(path)))) {
      problems.push(`content differs: ${path}`)
    }
  }
  for (const path of destFiles.keys()) {
    if (!sourceFiles.has(path)) problems.push(`extra file in the vendored copy: ${path}`)
  }
  return { status: problems.length === 0 ? 'ok' : 'drift', source, dest, count: sourceFiles.size, problems }
}

/** Copy source → dest, dropping files that no longer exist upstream. */
export function syncSkill({ source = DEFAULT_SOURCE, dest = DEST } = {}) {
  if (!existsSync(source) || !statSync(source).isDirectory()) {
    throw new Error(`sync-skill: source skill tree not found: ${source}`)
  }
  const sourceFiles = walk(source)
  const destFiles = existsSync(dest) ? walk(dest) : new Map()
  mkdirSync(dest, { recursive: true })
  let copied = 0
  for (const [path, file] of sourceFiles) {
    const target = join(dest, path.split('/').join(sep))
    mkdirSync(dirname(target), { recursive: true })
    const bytes = readFileSync(file)
    const current = existsSync(target) ? readFileSync(target) : undefined
    if (current === undefined || !current.equals(bytes)) {
      // Same-directory copy + rename: the active profile reads these files through the
      // publish/worklog link while a sync runs, and a straight overwrite can leave a
      // half-written file if it is interrupted (the 2026-10-16 `SKILL.md` → 0 bytes incident).
      const tmp = `${target}.tmp-${process.pid}-${copied}`
      try {
        writeFileSync(tmp, bytes)
        renameSync(tmp, target)
      } catch (error) {
        try { rmSync(tmp, { force: true }) } catch { /* the failed write is not worth masking the real error */ }
        throw error
      }
      copied += 1
    }
  }
  let removed = 0
  for (const path of destFiles.keys()) {
    if (!sourceFiles.has(path)) {
      rmSync(join(dest, path.split('/').join(sep)), { force: true })
      removed += 1
    }
  }
  const prune = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) prune(join(dir, entry.name))
    }
    if (dir !== dest && readdirSync(dir).length === 0) rmSync(dir, { recursive: true, force: true })
  }
  prune(dest)
  return { source, dest, count: sourceFiles.size, copied, removed }
}

/* ------------------------------- CLI ------------------------------- */

const invokedDirectly = process.argv[1] !== undefined
  && resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (invokedDirectly) {
  const check = process.argv.includes('--check')
  const sourceArg = process.argv.indexOf('--source')
  const source = sourceArg >= 0 && process.argv[sourceArg + 1] !== undefined
    ? resolve(process.argv[sourceArg + 1])
    : DEFAULT_SOURCE

  if (check) {
    const result = checkSkillSync({ source })
    if (result.status === 'skip') {
      console.log(`SKIP  skill source repo not found: ${result.source}`)
      console.log('      (sync-skill is a local two-repo gate; a bare plugin checkout cannot run it)')
      process.exit(0)
    }
    if (result.status === 'ok') {
      console.log(`skill in sync (${result.count} files) — ${rel(REPO, DEST)} matches ${result.source}`)
      process.exit(0)
    }
    console.log(`skill DRIFT (${result.problems.length}):`)
    for (const problem of result.problems) console.log(`  ${problem}`)
    console.log('\nfix: node tools/sync-skill.mjs   (never edit the vendored copy by hand)')
    process.exit(1)
  }

  try {
    const result = syncSkill({ source })
    console.log(`skill synced (${result.count} files; ${result.copied} written, ${result.removed} removed) — ${rel(REPO, DEST)}`)
    console.log(`source: ${result.source}`)
  } catch (error) {
    console.error(String(error?.message ?? error))
    process.exit(1)
  }
}
