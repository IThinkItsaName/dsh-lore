// Design-token check for the client half.
//
// Why this exists: `var(--dsw-…)` does NOT fail when the token is misspelled. It
// silently falls back to whatever the second argument is, or to nothing, so the page
// still renders and still looks plausible — while every colour has quietly stopped
// following the theme. The first version of lib/client.js used four invented names
// (`--dsw-text-secondary`, `--dsw-border`, `--dsw-danger`, `--dsw-font-mono`); none
// exists in DSH, and nothing anywhere said so. It was found by reading the host's CSS,
// which is not a mechanism.
//
// The authority is the host's own stylesheets. `work_log/logs/eng/dsh-src/dsw-tokens.txt` is the
// deduplicated list extracted from deepseek-harness/packages/client/*/src/**/*.css, and
// `tests/tools/refresh-tokens.mjs` regenerates it from a DSH checkout.
//
//   node tests/audit-client-tokens.mjs
import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { ok, skip, report, problems } from './_report.mjs'
import { PKG } from './_pkg.mjs'


/* ---- every --dsw-* name the client half asks for ---- */
const clientPath = join(PKG, 'lib', 'client.js')
const source = readFileSync(clientPath, 'utf8')
const used = [...new Set([...source.matchAll(/var\((--dsw-[A-Za-z0-9-]+)/g)].map((m) => m[1]))].sort()

ok(used.length > 0, 'the client half uses at least one --dsw-* token', String(used.length))
console.log(`      tokens used: ${used.join(', ')}`)

/* ---- the harness must be able to prove it is checking something ---- */
ok(used.every((t) => /^--dsw-[a-z0-9-]+$/.test(t)),
   'every token is named in the documented --dsw-<group>-<role> form',
   used.filter((t) => !/^--dsw-[a-z0-9-]+$/.test(t)).join(', '))

/* ---- compare against the host's own list ---- */
//
// 清单有**两个落点**，先找包内那份：
//
//   - `tests/tools/host-tokens.txt` —— 随包提交的夹具。206 个名字、5.7 KB，一年也变不了几次，
//     而它是这条断言唯一的权威，所以它必须**跟着仓库走**：CI 只 checkout 这个包，
//     工作区里那份够不着。
//   - `<工作区>/work_log/logs/eng/dsh-src/dsw-tokens.txt` —— `refresh-tokens.mjs` 的工作区镜像，
//     继续认（本机重生成时不会因为两份不同步而误报）。
//   - `<工作区>/logs/dsh-src/dsw-tokens.txt` —— 工作区整理前的旧落点，作为兼容继续认。
//
// 这一条曾经只认工作区那份：本机有那棵树，所以一直是绿的；CI 上它会**静默 SKIP**
// （报告 F3 的同族问题：门禁看着接上了，其实从没验过）。
const CANDIDATES = [
  join(PKG, 'tests', 'tools', 'host-tokens.txt'),
  join(PKG, '..', '..', '..', 'work_log/logs', 'eng', 'dsh-src', 'dsw-tokens.txt'),
  join(PKG, '..', '..', '..', 'logs', 'dsh-src', 'dsw-tokens.txt'),
]
const listPath = CANDIDATES.find((p) => existsSync(p)) ?? ''
if (listPath === '') {
  // 两份都没有才跳过 —— 那时确实无从比对，所以这是"该验却没验"，不是"验过了"。
  skip('host token list ABSENT at both locations — comparison SKIPPED '
       + `(${CANDIDATES.join(' , ')}; run tests/tools/refresh-tokens.mjs)`)
} else {
  const known = new Set(
    readFileSync(listPath, 'utf8').split(/\r?\n/).map((l) => l.trim()).filter((l) => l.startsWith('--dsw-')),
  )
  ok(known.size > 100, 'the host token list looks real', `${known.size} tokens from ${listPath}`)
  const bogus = used.filter((t) => !known.has(t))
  ok(bogus.length === 0,
     'every token the client half uses exists in the host',
     `${bogus.join(', ')} — a misspelled token does not throw; it silently falls back, so the theme stops applying and nothing reports it`)
}

/* ---- the copy-paste fallbacks must not come back ---- */
// A `var(--x, hardcoded)` hides a missing token behind a colour that looks fine in one
// theme and wrong in the other. The host's own CSS never does this for these roles.
const withFallback = [...source.matchAll(/var\(--dsw-[A-Za-z0-9-]+\s*,\s*([^)]+)\)/g)].map((m) => m[1].trim())
ok(withFallback.length === 0,
   'no --dsw-* token carries a hard-coded colour fallback',
   withFallback.join(' | '))

report('client design tokens OK') 