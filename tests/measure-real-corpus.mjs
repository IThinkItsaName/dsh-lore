// Measure the real record corpus under embeding try, to decide what a synthesis
// with the skill's format should keep.
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = 'D:/Program Files (x86)/project_of_agent/embeding try'
const lines = readdirSync(ROOT).filter((n) => {
  const p = join(ROOT, n)
  return statSync(p).isDirectory() && !n.startsWith('.') && n !== '_shared'
})

const totals = { files: 0, bytes: 0, dated: 0, titled: 0, numTitle: 0, dateLine: 0, verify: 0, withHead: 0 }
const perLine = []

for (const line of lines) {
  const wl = join(ROOT, line, 'work_log')
  if (!existsSync(wl)) continue
  const files = readdirSync(wl).filter((f) => f.endsWith('.md') && f !== 'README.md')
  const rows = []
  let bytes = 0

  for (const f of files) {
    const text = readFileSync(join(wl, f), 'utf8')
    const size = Buffer.byteLength(text, 'utf8')
    bytes += size
    const stem = f.replace(/\.md$/, '')
    const dated = /^\d{4}-\d{2}-\d{2}/.test(stem)
    const h1 = /^#\s+(.+)$/m.exec(text)?.[1] ?? ''
    const numTitle = /^#\s+\d+\s*·/.test(text)
    // A date line anywhere in the header area (first 15 lines), flexible separator.
    const head = text.split('\n').slice(0, 15).join('\n')
    const dateLine = /^\s*日期\s*[:：]/m.test(head)
    // A verification-ish heading, same synonym set the skill accepts.
    const verify = /^#{2,4}\s*.*(验证|复核|检查|评审|结果|证据|评估|确认|实测|审查)/m.test(text)

    if (dated) totals.dated += 1
    if (h1) totals.titled += 1
    if (numTitle) totals.numTitle += 1
    if (dateLine) totals.dateLine += 1
    if (verify) totals.verify += 1
    totals.files += 1
    totals.bytes += size
    rows.push({ f, size, dated, h1, numTitle, dateLine, verify })
  }

  const h2 = [...new Set(files.flatMap((f) => {
    const text = readFileSync(join(wl, f), 'utf8')
    return [...text.matchAll(/^##\s+(.+)$/gm)].map((m) => m[1].trim())
  }))]
  const idx = join(wl, 'README.md')
  const idxText = existsSync(idx) ? readFileSync(idx, 'utf8') : ''
  perLine.push({ line, n: files.length, bytes, avg: files.length ? Math.round(bytes / files.length) : 0, h2, idxBytes: Buffer.byteLength(idxText, 'utf8'), idxHasStatus: /##\s*当前状态/.test(idxText) })
}

console.log('=== per line ===')
for (const r of perLine) {
  console.log(`${r.line.padEnd(20)} ${String(r.n).padStart(3)} md  ${String(Math.round(r.bytes / 1024)).padStart(4)} KB  avg ${String(r.avg).padStart(5)} B  index ${String(Math.round(r.idxBytes / 1024)).padStart(3)} KB  status-block=${r.idxHasStatus}`)
}
console.log('\n=== corpus totals ===')
const kb = (b) => Math.round(b / 1024)
console.log(`files          : ${totals.files}`)
console.log(`total size     : ${kb(totals.bytes)} KB   avg ${Math.round(totals.bytes / totals.files)} B/file`)
console.log(`date-named     : ${totals.dated}/${totals.files}`)
console.log(`has H1         : ${totals.titled}/${totals.files}`)
console.log(`H1 is "# NNNN ·" : ${totals.numTitle}/${totals.files}   <-- the skill REQUIRES this`)
console.log(`has 日期: line  : ${totals.dateLine}/${totals.files}   <-- the skill REQUIRES this`)
console.log(`verification § : ${totals.verify}/${totals.files}   <-- the skill REQUIRES this`)

console.log('\n=== section headings actually used (top 24 across the corpus) ===')
const freq = new Map()
for (const r of perLine) for (const h of r.h2) freq.set(h, (freq.get(h) ?? 0) + 1)
for (const [h, c] of [...freq.entries()].sort((a, b) => b[1] - a[1]).slice(0, 24)) {
  console.log(`  ${String(c).padStart(3)}x  ${h}`)
}
console.log(`\ndistinct H2 headings: ${freq.size}`)
