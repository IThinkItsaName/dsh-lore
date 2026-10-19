// Gate: the vendored skill copy still matches the independent skill repo.
//
// Why this exists: since 2026-10-19 the portable skill has its own repository
// (`publish/project-work-log/`). The DSH plugin still has to ship the skill — the provider
// serves it and `preaudit` hashes the served body — so the plugin keeps a vendored copy.
// Two copies without a gate drift silently, and the symptom is the model reading a different
// SKILL.md than the one pi installs.
//
// The gate is a local two-repo check: on a bare plugin checkout the sibling is absent and
// this reports SKIP (not a failure). When the sibling is present, any missing/extra/differing
// file is a failure, with `node tools/sync-skill.mjs` as the one-line fix.
//
// The tool itself is exercised on a throwaway pair below: copy, remove-stale, content drift,
// temp-file cleanup, inode-swap atomicity, the Windows read-only failure path, and the
// "source absent" SKIP path. Testing only the live pair would leave the tool's own branches
// unverified (and the live pair is always clean here).
//
//   node tests/audit-skill-sync.mjs
import { chmodSync, linkSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { ok, skip, report } from './_report.mjs'
import { PKG } from './_pkg.mjs'
import { checkSkillSync, syncSkill } from '../tools/sync-skill.mjs'

/* ── 1. the live pair ─────────────────────────────────────────────────────── */
const result = checkSkillSync()

if (result.status === 'skip') {
  skip('the independent skill repo is not checked out beside this one', result.source)
} else {
  ok(result.status === 'ok',
    `the vendored skill matches ${result.source} (${result.count} files)`,
    result.problems.slice(0, 8).join('\n'))
}

/* ── 2. the sync tool's own branches, on a throwaway pair ─────────────────── */
const sandbox = mkdtempSync(join(tmpdir(), 'skill-sync-'))
try {
  const source = join(sandbox, 'source')
  const target = join(sandbox, 'target')
  mkdirSync(join(source, 'scripts'), { recursive: true })
  writeFileSync(join(source, 'SKILL.md'), '# skill\n', 'utf8')
  writeFileSync(join(source, 'scripts', 'a.py'), 'print(1)\n', 'utf8')

  const empty = checkSkillSync({ source, dest: target })
  ok(empty.status === 'drift' && empty.problems.some((p) => p.startsWith('missing in the vendored copy')),
    'an empty target reports every source file as missing',
    empty.problems.join('; '))

  const first = syncSkill({ source, dest: target })
  ok(first.copied === 2 && checkSkillSync({ source, dest: target }).status === 'ok',
    'sync copies the whole tree, and the pair is clean afterwards',
    JSON.stringify(first))

  writeFileSync(join(target, 'extra.md'), 'stale\n', 'utf8')
  const extra = checkSkillSync({ source, dest: target })
  ok(extra.status === 'drift' && extra.problems.some((p) => p.includes('extra file in the vendored copy')),
    'an extra file in the vendored copy is drift, not ignored',
    extra.problems.join('; '))

  const second = syncSkill({ source, dest: target })
  ok(second.removed === 1 && checkSkillSync({ source, dest: target }).status === 'ok',
    'sync removes files that no longer exist upstream',
    JSON.stringify(second))

  const leftoverTemps = () => {
    const found = []
    const visit = (dir) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        if (entry.isDirectory()) visit(join(dir, entry.name))
        else if (entry.name.includes('.tmp-')) found.push(join(dir, entry.name))
      }
    }
    visit(target)
    return found
  }
  ok(leftoverTemps().length === 0, 'sync leaves no *.tmp-* behind', leftoverTemps().join(', '))

  // A leftover from an interrupted write must be visible as drift, and the next sync must
  // remove it — otherwise the atomic-write temp name becomes a permanent blind spot.
  writeFileSync(join(target, 'SKILL.md.tmp-999-0'), 'partial\n', 'utf8')
  const withTemp = checkSkillSync({ source, dest: target })
  ok(withTemp.status === 'drift'
    && withTemp.problems.some((p) => p.includes('.tmp-') && p.includes('extra file')),
    'a leftover temp file is reported as an extra file', withTemp.problems.join('; '))
  const cleaned = syncSkill({ source, dest: target })
  ok(cleaned.removed === 1 && leftoverTemps().length === 0
    && checkSkillSync({ source, dest: target }).status === 'ok',
    'sync removes a leftover temp file', JSON.stringify(cleaned))

  // The scan must be recursive: a temp under a subdirectory is just as much a leftover.
  mkdirSync(join(target, 'scripts'), { recursive: true })
  writeFileSync(join(target, 'scripts', 'a.py.tmp-999-1'), 'partial\n', 'utf8')
  const nested = leftoverTemps()
  ok(nested.length === 1 && nested[0].includes('scripts'),
    'a nested temp file is visible to the recursive scan', nested.join(', '))
  const nestedCleaned = syncSkill({ source, dest: target })
  ok(nestedCleaned.removed === 1 && leftoverTemps().length === 0,
    'sync removes a nested temp file', JSON.stringify(nestedCleaned))

  writeFileSync(join(source, 'SKILL.md'), '# changed\n', 'utf8')
  const changed = checkSkillSync({ source, dest: target })
  ok(changed.status === 'drift' && changed.problems.some((p) => p.startsWith('content differs')),
    'a changed source file is drift',
    changed.problems.join('; '))

  // The Windows failure path that matters: a read-only target makes rename fail. The old
  // bytes must survive and the temp file must be cleaned up (the 0-byte incident shape).
  if (process.platform === 'win32') {
    const locked = join(target, 'SKILL.md')
    chmodSync(locked, 0o444)
    try {
      let failure = null
      try {
        syncSkill({ source, dest: target })
      } catch (error) {
        failure = error
      }
      ok(failure !== null && readFileSync(locked, 'utf8') === '# skill\n' && leftoverTemps().length === 0,
        'a locked target fails safely: old bytes kept, no temp file left', String(failure))
    } finally {
      chmodSync(locked, 0o666)
    }
    syncSkill({ source, dest: target })
    ok(checkSkillSync({ source, dest: target }).status === 'ok',
      'sync succeeds once the target is writable again')
  } else {
    skip('read-only rename failure only reproduces on win32')
  }

  // Portable proof that the write is a rename, not an in-place overwrite: a hard link made
  // before the sync must keep seeing the old bytes. A direct `writeFileSync(target, …)` writes
  // through the link, so this assertion turns red when the atomic write is reverted.
  writeFileSync(join(source, 'SKILL.md'), '# atomic-old\n', 'utf8')
  syncSkill({ source, dest: target })
  const pinned = join(sandbox, 'pinned.md')
  let canLink = true
  try {
    linkSync(join(target, 'SKILL.md'), pinned)
  } catch (error) {
    // Only "this filesystem cannot do hard links" is a reason to skip. A missing target or a
    // real bug must fail the gate, otherwise the one portable atomicity check silently skips.
    const code = error?.code
    if (!['ENOTSUP', 'ENOSYS', 'EPERM', 'EACCES', 'EXDEV', 'EMLINK'].includes(code)) throw error
    canLink = false
  }
  if (!canLink) {
    skip('hard links are unavailable, so the inode-swap atomicity check cannot run')
  } else {
    writeFileSync(join(source, 'SKILL.md'), '# atomic-new\n', 'utf8')
    syncSkill({ source, dest: target })
    const throughLink = readFileSync(pinned, 'utf8')
    const throughTarget = readFileSync(join(target, 'SKILL.md'), 'utf8')
    ok(throughLink === '# atomic-old\n' && throughTarget === '# atomic-new\n',
      'sync swaps the file (rename), so a pre-sync hard link keeps the old bytes',
      `link=${JSON.stringify(throughLink)} target=${JSON.stringify(throughTarget)}`)
  }

  const absent = checkSkillSync({ source: join(sandbox, 'no-such-repo'), dest: target })
  ok(absent.status === 'skip' && absent.problems.length === 0,
    'a missing source repo is SKIP, not a false failure',
    JSON.stringify(absent))
} finally {
  rmSync(sandbox, { recursive: true, force: true })
}

report(`skill sync OK — ${PKG}/skills/project-work-log is the independent repo's copy, and the sync tool's branches hold`)
