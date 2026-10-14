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
 *     也是 CI 上唯一够得着的那份（CI 只 checkout 这个包，看不到工作区里的 `logs/`）。
 *     以前只写工作区那份，于是这条断言在 CI 上静默 SKIP —— 门禁看着接上了，其实从没验过。
 *   - `<工作区>/logs/dsh-src/dsw-tokens.txt` —— 工作区的镜像，继续写，供翻查与旧路径兼容。
 *
 * 两份一起写，就不会再出现"本机绿、CI 跳过"这种不一致。
 */
import { readdirSync, readFileSync, writeFileSync, existsSync, mkdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const PKG = join(here, '..', '..')
const OUT = join(here, 'host-tokens.txt')
const MIRROR = join(PKG, '..', '..', 'logs', 'dsh-src', 'dsw-tokens.txt')
const DEFAULT_CHECKOUT = 'D:\\Program Files (x86)\\dsh_from_github\\deepseek-harness'

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
try {
  mkdirSync(dirname(MIRROR), { recursive: true })
  writeFileSync(MIRROR, sorted.join('\n') + '\n', 'utf8')
  console.log(`written   ${OUT}`)
  console.log(`mirrored  ${MIRROR}`)
} catch (err) {
  console.log(`written   ${OUT}`)
  console.log(`mirror    skipped (${err.code ?? err.message}); the packaged copy is the one the gate reads`)
}
