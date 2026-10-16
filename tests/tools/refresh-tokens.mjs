#!/usr/bin/env node
/**
 * Regenerate the DSH design-token list that `tests/audit-client-tokens.mjs` checks against.
 *
 * Why a generated file rather than a hand-written one: the list *is* the host's own
 * stylesheets. Typing it by hand would make the audit circular — it would only ever
 * confirm that our client uses the names we already believed in. Extracting them means a
 * token we invented fails against the host's real vocabulary.
 *
 *   node tests/tools/refresh-tokens.mjs "D:\path\to\deepseek-harness"
 *
 * Default target is the checkout this project was developed against.
 *
 * 输出**两份**：
 *   - `tests/tools/host-tokens.txt` —— **随包提交**的那份。`audit-client-tokens.mjs` 的权威，
 *     也是 CI 上唯一够得着的那份（CI 只 checkout 这个包，看不到工作区里的 `work_log/logs/`）。
 *     以前只写工作区那份，于是这条断言在 CI 上静默 SKIP —— 门禁看着接上了，其实从没验过。
 *   - `<工作区>/work_log/logs/eng/dsh-src/dsw-tokens.txt` —— 工作区的镜像，继续写，供翻查。
 *     工作区已经整理过（顶层不再有 `logs/dsh-src/`），所以这里是三级向上；
 *     老工作区的 `<工作区>/logs/dsh-src/dsw-tokens.txt` 由 `audit-client-tokens.mjs`
 *     作为兼容落点继续认。
 *
 * 两份一起写，就不会再出现"本机绿、CI 跳过"这种不一致。
 */
import { readdirSync, readFileSync, writeFileSync, existsSync, mkdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const PKG = join(here, '..', '..')
const OUT = join(here, 'host-tokens.txt')
const DEFAULT_CHECKOUT = 'D:\\Program Files (x86)\\dsh_from_github\\deepseek-harness'

// 工作区镜像的落点：`<工作区>/work_log/logs/eng/dsh-src/dsw-tokens.txt`。
//
// 从前这里写死 `join(PKG, '..', '..', '..', 'work_log', …)` —— 多退了一级。它在 `.pi`
// 那份布局里**碰巧**是对的（`.pi/skills/<skill>` 比 `publish/worklog` 浅一层），所以当年
// 那份镜像就是这么写出来的；换到本仓库的布局，它算出来是**包外面**（实测
// `D:\Program Files (x86)\work_log\…`），而下面 `mkdirSync(…, { recursive: true })` 会
// 照建不误 —— 写进一个谁也不看的地方，还打印"mirrored"（2026-10-17 复核发现，
// 与 `tests/audit-ranks.mjs` 多退一级是同一个形状：路径错了，于是静默失效）。
//
// 现在不猜层数：哪一级真有 `work_log/` 就用哪一级，都没有就不写（CI 里正是这个情形）。
const workspaceWithLog = [
  join(PKG, '..', '..', 'work_log'), // publish/worklog → 工作区（本仓库布局）
  join(PKG, '..', 'work_log'),       // <工作区>/skills/<skill> → 工作区（.pi 布局）
].find((p) => existsSync(p)) ?? null
const MIRROR = workspaceWithLog === null
  ? null
  : join(workspaceWithLog, 'logs', 'eng', 'dsh-src', 'dsw-tokens.txt')

const checkout = process.argv[2] ?? DEFAULT_CHECKOUT
const clientDir = join(checkout, 'packages', 'client')
if (!existsSync(clientDir)) {
  console.error(`not a DSH checkout (no packages/client): ${checkout}`)
  process.exit(1)
}

/** Every `*.css` under a package's `src/`, since that is where the tokens are declared. */
function cssFiles(root) {
  const out = []
  const walk = (dir) => {
    let entries
    try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return }
    for (const entry of entries) {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (entry.name.endsWith('.css')) out.push(full)
    }
  }
  walk(root)
  return out
}

const packages = readdirSync(clientDir, { withFileTypes: true })
  .filter((e) => e.isDirectory())
  .map((e) => join(clientDir, e.name, 'src'))
  .filter((p) => existsSync(p) && statSync(p).isDirectory())

const tokens = new Set()
let files = 0
for (const src of packages) {
  for (const file of cssFiles(src)) {
    files++
    for (const m of readFileSync(file, 'utf8').matchAll(/var\((--dsw-[A-Za-z0-9-]+)/g)) tokens.add(m[1])
  }
}

const sorted = [...tokens].sort()
mkdirSync(dirname(OUT), { recursive: true })
writeFileSync(OUT, sorted.join('\n') + '\n', 'utf8')

console.log(`scanned   ${files} css files across ${packages.length} client packages`)
console.log(`tokens    ${sorted.length}`)

// 工作区镜像：尽力而为。在 CI（只有包、没有工作区）里这里会失败，那**正常**——
// 上面那份随包的在就够了，所以镜像写不进去只提示、不影响退出码。
if (MIRROR === null) {
  console.log(`written   ${OUT}`)
  console.log('mirror    skipped (包里那一层没有 work_log/，说明不在工作区里); '
    + 'the packaged copy is the one the gate reads')
} else {
  try {
    mkdirSync(dirname(MIRROR), { recursive: true })
    writeFileSync(MIRROR, sorted.join('\n') + '\n', 'utf8')
    console.log(`written   ${OUT}`)
    console.log(`mirrored  ${MIRROR}`)
  } catch (err) {
    console.log(`written   ${OUT}`)
    console.log(`mirror    skipped (${err.code ?? err.message}); the packaged copy is the one the gate reads`)
  }
}
