// 0.8.0 的一次性记忆迁移 —— `<DSH_HOME>/memory` → 新默认根。
//
// 这个 harness 存在的理由（审查报告 F11，2026-10-15 复核成立）：
//
//   0.8.0 的升级路径本身就是 `migrateMemoryIfNeeded()`（`lib/index.js`）：新根**空**、旧根
//   **有内容**时整份复制过去，逐文件校验体积，失败就原样保留并告警，**绝不自动删旧根**。
//   这条路上有六个分支，而 `tests/` 里 `migrateMemoryIfNeeded` / `moved-from-dsh-home`
//   **一次都没出现过**（grep 0 命中）。兄弟迁移（设置文件 → patch）被 `audit-settings.mjs`
//   钉得很细，这一条却全靠人肉 review —— 而它动的是用户**唯一的**记忆库。
//
//   顺带说明为什么它现在能跑：`_pkg.mjs` 之前只钉 `DSH_WORKLOG_SETTINGS` 与
//   `DSH_WORKLOG_MEMORY`，`DSH_HOME` 只出现在注释里。于是开发者机器上真有 `<DSH_HOME>/memory`
//   时，第一次 `apply()` 就会把**真实记忆**复制进共享的 `<tmpdir>/dsh-lore-memory-isolated/`。
//   `_pkg.mjs` 已补钉 `DSH_HOME`；本 harness 再把来源换成自己的沙箱，两道保险。
//
// 断言分六组，正好覆盖六个分支：
//   1. 新根空 + 旧根有内容 → 整份复制 + 留痕（含子目录、`.git`；跳过 `.tmp`），**旧根一字不动**；
//   2. 已经迁过（留痕在）→ 返回 null，不重复搬；
//   3. 新根已有内容 → 返回 null（显式配置优先，不覆盖别人的库）；
//   4. 旧根没有可迁内容 → 返回 null（也不该把空目录搬过去）；
//   5. 新旧同一个路径 → 返回 null（`resolve` 相等就退出，不做自我复制）；
//   6. 复制中途失败 → 返回 `memory migration failed …`，旧根仍然一字不动。
//
//   第 6 组用"目标路径上是个**文件**"来触发失败：`mkdirSync` 会抛，异常落进同一个 catch，
//   于是走的是"复制失败"那条文案。审查报告建议的"逐文件体积校验失败（incomplete）"那一支
//   **无法可移植地触发** —— 它要求复制与校验之间文件体积发生变化（或大小写/规范化冲撞这类
//   平台特性），在 Linux CI 与 Windows 上造不出同一个夹具。这里不假装验过它：那一支的判据是
//   纯字符串比较，靠的是同一段代码被第 6 组走过的 catch 之外的可读性，而不是断言。
//
//   node tests/audit-memory-migration.mjs
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync }
  from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { ok, report } from './_report.mjs'
import { PKG } from './_pkg.mjs'

/* 夹具放系统临时目录，别放包里：`<pkg>/tests/` 里多一个文件就是 `_package.py --check` 的漂移。 */
const SANDBOX = mkdtempSync(join(tmpdir(), 'dsh-lore-migration-'))
const HOME = join(SANDBOX, 'home')
const LEGACY = join(HOME, 'memory')

/* 迁移的**来源**由 `DSH_HOME` 决定，所以必须在被测模块被调用之前换成自己的沙箱
 * （`_pkg.mjs` 已经把它钉进一个隔离路径，这里再收窄一层：连"隔离路径里有东西"都不可能）。 */
process.env.DSH_HOME = HOME
mkdirSync(LEGACY, { recursive: true })

const mod = await import(pathToFileURL(join(PKG, 'lib', 'index.js')).href)

const read = (path) => (existsSync(path) ? readFileSync(path, 'utf8') : null)
const names = (dir) => (existsSync(dir) ? readdirSync(dir).sort() : [])
const MARKER = '.moved-from-dsh-home'

/* 造一份"旧根有内容"：正文 + 子目录 + `.git`（按设计**要**跟着搬）+ 一个 `.tmp`（按设计不搬）。 */
function seedLegacy({ withIndex = true } = {}) {
  rmSync(LEGACY, { recursive: true, force: true })
  mkdirSync(join(LEGACY, 'lessons'), { recursive: true })
  mkdirSync(join(LEGACY, '.git'), { recursive: true })
  if (withIndex) writeFileSync(join(LEGACY, 'INDEX.md'), '# memory index\n\n- one line\n', 'utf8')
  writeFileSync(join(LEGACY, 'lessons', '01-topic.md'), '- id: probe\n  state: active\n', 'utf8')
  writeFileSync(join(LEGACY, '.git', 'HEAD'), 'ref: refs/heads/main\n', 'utf8')
  writeFileSync(join(LEGACY, 'half.tmp'), '不完整的临时文件\n', 'utf8')
}

function freshRoot(name) {
  const root = join(SANDBOX, name)
  rmSync(root, { recursive: true, force: true })
  return root
}

ok(mod.legacyMemoryDirectory() === LEGACY,
   'G0 旧根的路径就是 <DSH_HOME>/memory（迁移来源的定义）', mod.legacyMemoryDirectory())

/* ------------------------------------------------- 1. 复制 + 留痕 + 旧根不动 */

seedLegacy()
const before = {
  index: read(join(LEGACY, 'INDEX.md')),
  lesson: read(join(LEGACY, 'lessons', '01-topic.md')),
  git: read(join(LEGACY, '.git', 'HEAD')),
  names: names(LEGACY),
}
const target1 = freshRoot('root-1')
const message1 = mod.migrateMemoryIfNeeded(target1)
ok(typeof message1 === 'string' && message1.includes('memory moved to'),
   'G1a 新根空 + 旧根有内容 ⇒ 迁移发生并回一句人话', String(message1))
ok(read(join(target1, 'INDEX.md')) === before.index,
   'G1b INDEX.md 逐字节复制过去', String(read(join(target1, 'INDEX.md'))))
ok(read(join(target1, 'lessons', '01-topic.md')) === before.lesson,
   'G1c 子目录里的文件也复制了（不是只搬根目录那一层）')
ok(read(join(target1, '.git', 'HEAD')) === before.git,
   'G1d `.git` 一起带上 —— 历史也是记忆的一部分（这是刻意的）')
ok(!existsSync(join(target1, 'half.tmp')),
   'G1e `.tmp` 半截文件不搬（复制途中被打断的残片不配进新库）')
ok(read(join(target1, MARKER))?.includes(LEGACY),
   'G1f 留痕文件写下了来源路径（下次装载看它就不再搬）',
   String(read(join(target1, MARKER))))
ok(read(join(LEGACY, 'INDEX.md')) === before.index
   && read(join(LEGACY, 'lessons', '01-topic.md')) === before.lesson
   && names(LEGACY).join(',') === before.names.join(','),
   'G1g **旧根一字不动**（绝不自动删：跨卷 rename 会失败、删了不可回滚）',
   names(LEGACY).join(','))
ok(String(message1).includes('left untouched') && String(message1).includes('delete it yourself'),
   'G1h 文案明确告诉用户"旧的那份还在，满意了自己删"', String(message1))

/* ------------------------------------------------------- 2. 已迁过 ⇒ 不再搬 */

const target2 = freshRoot('root-2')
mod.migrateMemoryIfNeeded(target2)                         // 先正常迁一次，落下留痕
writeFileSync(join(LEGACY, 'NEW-AFTER-MIGRATION.md'), '迁完之后旧根又多了一条\n', 'utf8')
const message2 = mod.migrateMemoryIfNeeded(target2)
ok(message2 === null, 'G2a 留痕在 ⇒ 返回 null，不重复搬（旧根后来新增的东西也不追）', String(message2))
ok(!existsSync(join(target2, 'NEW-AFTER-MIGRATION.md')),
   'G2b 重复调用没有把新内容塞进新根（"一次性"是真的只有一次）')
ok(names(LEGACY).includes('NEW-AFTER-MIGRATION.md'),
   'G2c 而旧根那条还在（没被搬走、也没被删）', names(LEGACY).join(','))

/* ----------------------------------------------------------- 3. 新根已有内容 */

seedLegacy()
const target3 = freshRoot('root-3')
mkdirSync(target3, { recursive: true })
writeFileSync(join(target3, 'INDEX.md'), '# 用户自己攒的库\n', 'utf8')
const message3 = mod.migrateMemoryIfNeeded(target3)
ok(message3 === null, 'G3a 新根非空 ⇒ 返回 null（显式配置优先，不覆盖）', String(message3))
ok(read(join(target3, 'INDEX.md')) === '# 用户自己攒的库\n',
   'G3b 新根里已有的内容一个字都没被覆盖')
ok(!existsSync(join(target3, MARKER)), 'G3c 也没留下痕 —— 没搬就不算搬过')

/* --------------------------------------------------------------- 4. 旧根是空的 */

rmSync(LEGACY, { recursive: true, force: true })
const target4 = freshRoot('root-4')
ok(mod.migrateMemoryIfNeeded(target4) === null,
   'G4a 旧根**不存在** ⇒ 返回 null（"没有可迁的东西"不是失败）')
mkdirSync(LEGACY, { recursive: true })
ok(mod.migrateMemoryIfNeeded(target4) === null,
   'G4b 旧根存在但是空目录 ⇒ 也返回 null')
ok(!existsSync(join(target4, MARKER)),
   'G4c 空目录不算迁过：新根连留痕都不该有（否则以后真有内容时就不搬了）')

/* ----------------------------------------------------------------- 5. 同一个路径 */

seedLegacy()
const message5 = mod.migrateMemoryIfNeeded(LEGACY)
ok(message5 === null, 'G5 新旧同一个路径 ⇒ 返回 null（不做自我复制）', String(message5))
ok(names(LEGACY).join(',') === before.names.join(','),
   'G5b 自我复制没有发生（旧根条目没变多）', names(LEGACY).join(','))

/* ------------------------------------------------------------- 6. 复制失败那一支 */

seedLegacy()
const target6 = freshRoot('root-6')
writeFileSync(target6, '我是一个文件，不是目录\n', 'utf8')   // mkdirSync 会在这里抛
const message6 = mod.migrateMemoryIfNeeded(target6)
ok(typeof message6 === 'string' && message6.startsWith('memory migration failed'),
   'G6a 目标不可用 ⇒ 返回 `memory migration failed …`（不抛异常、不半途而废）', String(message6))
ok(String(message6).includes('nothing was moved')
   && String(message6).includes(LEGACY.replace(/\\/g, '/')),
   // 路径在文案里是**正斜杠**形式（`toSlashes`），别拿 `join()` 拼出来的反斜杠去比 ——
   // 第一版就是这么写红的（Windows 上 `join` 给的是 `\`）。
   'G6b 文案说清"什么都没搬走"，并指出旧根在哪', String(message6))
ok(read(join(LEGACY, 'INDEX.md')) === before.index
   && names(LEGACY).join(',') === before.names.join(','),
   'G6c 失败后旧根仍然一字不动（最坏情况只是白跑一次）', names(LEGACY).join(','))
ok(read(target6) === '我是一个文件，不是目录\n',
   'G6d 失败路径没把那个文件当成目录乱写（目标原样留着）', String(read(target6)))

/* 测试自己收拾干净：临时目录里不留东西（`_package.py --check` 看的是包里，这里看的是别脏了机器）。 */
rmSync(SANDBOX, { recursive: true, force: true })

report('memory migration OK — copy, marker, idempotence, three refusals, and the failure path')
