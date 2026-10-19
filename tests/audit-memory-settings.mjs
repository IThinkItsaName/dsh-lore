// 记忆根的设置链：卡片 → 插件 → CLI，以及"两个进程读同一个根"这条不变量。
//
// 这个 harness 存在的理由（`0083` 之后的第一次审查，2026-10-15）：
//
//   0.8.0 的招牌功能「记忆存放位置」在桌面 profile 上**是死的** —— 卡片把值写进 profile
//      patch，而 `memoryDirectory()` 调的是**不带 row** 的 `liveMemorySettings()`，只看得见
//      `<DSH_HOME>/worklog/settings.json`（桌面**故意**不读它）。于是用户把路径填进卡片、
//      看不出任何效果，还会收到一条"ignoring unsupported config keys: memoryDir"的警告
//      （因为 `memoryDir` 不在三组"本插件拥有的键"里）。
//
//   而 586 + 13 道门禁**全绿**：`_pkg.mjs` 无条件把 `DSH_WORKLOG_MEMORY` 设成隔离路径，
//   于是 `memoryDirectory()` 每次都从环境变量那一档返回 —— 桌面真正走的那条路，
//   没有任何一条断言碰过它。这个 harness 就是为了那条路。
//
// 断言分四组：
//   A. 解析优先级（卡片 > 文件 > 环境变量 > 默认根），含相对路径按用户主目录解析；
//   B. 绝不出现"不认识的键"警告 —— 这个键是插件自己文档化、卡片提供控件的；
//   C. 跨进程同步：有 `configEditor` 的宿主上，卡片的值必须落进那个 CLI 也读的文件；
//   D. 状态行、条目读取、索引计数用同一个根（同一个工具里不许劈叉）；
//   E. 保存之后、下一次装载之前：Loader 的 volatile 提交也要让那个文件跟上。
//
//   node tests/audit-memory-settings.mjs
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { PKG } from './_pkg.mjs'

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}

/* 夹具放系统临时目录，别放包里：`<pkg>/tests/` 里多一个文件就是 `_package.py --check` 的
 * 漂移（"包里有的、镜像里没有的"），这个坑 `audit-memory-injection.mjs` 已经踩过一次。 */
const SANDBOX = mkdtempSync(join(tmpdir(), 'dsh-lore-memdir-'))
const SETTINGS = join(SANDBOX, 'settings.json')
const CARD_ROOT = join(SANDBOX, 'root-from-card')
const FILE_ROOT = join(SANDBOX, 'root-from-file')
const ENV_ROOT = join(SANDBOX, 'root-from-env')

const mod = await import(pathToFileURL(join(PKG, 'lib', 'index.js')).href)

/* 这个 harness 要**逐档**验解析，所以先把 `_pkg.mjs` 设的隔离环境变量摘掉 ——
 * 它那一档是"环境变量赢默认根"，留着就永远测不到设置那一档（这正是缺陷能出厂的原因）。 */
delete process.env.DSH_WORKLOG_MEMORY
process.env.DSH_WORKLOG_SETTINGS = SETTINGS

function writeSettings(document) {
  mkdirSync(SANDBOX, { recursive: true })
  writeFileSync(SETTINGS, JSON.stringify(document), 'utf8')
}

function readSettings() {
  return existsSync(SETTINGS) ? JSON.parse(readFileSync(SETTINGS, 'utf8')) : {}
}

/* 记忆工具：照 `run.mjs` 的 fakeCtx 取最小面，但把注册下来的工具**留下**，
   不然"工具报的根"这条没法验。`logs` 也要留 —— B 组断言看的就是它。 */
function ctxWith(extra = {}) {
  const providers = []
  const logs = []
  // 注册面用**真数组**：`registered(ctx)` 要能直接 `find`。别把它换成"一个带 register 的
  // 对象里塞个数组"——那样 `ctx.tools`（注册面）与 `ctx.registeredTools`（记录）是两份东西，
  // 测试里最容易拿错（本条也踩过：`ctx.tools.find is not a function`）。
  const tools = []
  const logger = {
    info: (m) => logs.push(['info', String(m)]),
    warn: (m) => logs.push(['warn', String(m)]),
    error: (m) => logs.push(['error', String(m)]),
  }
  const skills = { registerProvider: (create) => { providers.push(create); return () => {} } }
  tools.register = (definition) => { tools.push(definition); return () => {} }
  /* `apply()` 会订阅 `loader/volatile-update`（Loader 对 volatile-only 的改动**不重挂载**，
   * 只把新值提交进运行中的 `.volatile()` 引用）。收下来才验得了"保存到重启之间"那段窗口 ——
   * E 组就是冲它来的：少了那一跳，插件已经用新根而 `journal.py` 还在读旧根。 */
  const events = []
  return {
    ...extra,
    providers,
    logs,
    skills,
    tools,
    logger,
    on: (name, handler) => { events.push([name, handler]); return () => {} },
    events,
  }
}

const registered = (ctx) => ctx.tools
const warningsIn = (ctx) => ctx.logs.filter(([level]) => level === 'warn').map(([, text]) => text)
const unknownKeyWarnings = (ctx) => warningsIn(ctx).filter((text) => text.includes('unsupported config keys'))

/* ------------------------------------------------------------------ A. 解析优先级 */

writeSettings({ memoryDir: FILE_ROOT })
ok(mod.memoryDirectory() === FILE_ROOT, 'A1 设置文件里的 memoryDir 说了算', mod.memoryDirectory())

process.env.DSH_WORKLOG_MEMORY = ENV_ROOT
ok(mod.memoryDirectory() === FILE_ROOT,
   'A2 文件与环境变量同时存在时文件赢（与 journal.py 同一口径）', mod.memoryDirectory())

writeSettings({})
ok(mod.memoryDirectory() === ENV_ROOT, 'A3 文件里没有这个键时环境变量生效', mod.memoryDirectory())

delete process.env.DSH_WORKLOG_MEMORY
ok(mod.memoryDirectory() === join(homedir(), 'dsh-lore-memory'),
   'A4 都没有时回默认根 ~/dsh-lore-memory', mod.memoryDirectory())

process.env.DSH_WORKLOG_MEMORY = ENV_ROOT
ok(mod.memoryDirectory({ memoryDir: CARD_ROOT }) === CARD_ROOT,
   'A5 显式传进来的设置（合并后的那一份）压过环境变量', mod.memoryDirectory({ memoryDir: CARD_ROOT }))

ok(mod.memoryDirectory({ memoryDir: 'relative-root' }) === join(homedir(), 'relative-root'),
   'A6 相对路径按用户主目录解析（不是按 cwd）', mod.memoryDirectory({ memoryDir: 'relative-root' }))

ok(mod.memoryDirectory({ memoryDir: '   ' }) === ENV_ROOT,
   'A7 只有空白算"没设置"，退回下一档', mod.memoryDirectory({ memoryDir: '   ' }))
delete process.env.DSH_WORKLOG_MEMORY

/* -------------------------------------------------------------- B. 键清单（别再误报） */

writeSettings({})
const ctxPlain = ctxWith()
mod.apply(ctxPlain, {})
ok(unknownKeyWarnings(ctxPlain).length === 0,
   'B1 patch 里不写 memoryDir 时不报"不认识的键"', JSON.stringify(unknownKeyWarnings(ctxPlain)))

const ctxWithKey = ctxWith()
mod.apply(ctxWithKey, { memoryDir: CARD_ROOT })
ok(unknownKeyWarnings(ctxWithKey).length === 0,
   'B2 patch 里写了 memoryDir 也不许报"不认识的键" —— 它是插件自己文档化的键',
   JSON.stringify(unknownKeyWarnings(ctxWithKey)))

const ctxBogus = ctxWith()
mod.apply(ctxBogus, { bogusKey: 1 })
ok(unknownKeyWarnings(ctxBogus).some((text) => text.includes('bogusKey')),
   'B3 但真的不认识的键照样要报（判据没被放宽）', JSON.stringify(unknownKeyWarnings(ctxBogus)))

// B4：宿主交给 `apply()` 的是 Config 解析后的**完整**配置（默认值都在），不是稀疏的
// 手写 patch。M2 的误报只在完整配置下才出现，所以这里必须按宿主的形状验一次。
const resolved = mod.Config['~standard'].validate({})
const ctxDefaults = ctxWith()
mod.apply(ctxDefaults, resolved.value ?? {})
ok(unknownKeyWarnings(ctxDefaults).length === 0,
   'B4 Config 解析出的完整配置没有"不认识的键"（含 skillEnabled）',
   JSON.stringify({ warnings: unknownKeyWarnings(ctxDefaults), resolved: resolved.value }))
ok(Object.hasOwn(resolved.value ?? {}, 'skillEnabled'),
   'B4b Config 解析出的键里确实有 skillEnabled（键清单必须覆盖它）',
   JSON.stringify(resolved))

/* ------------------------------------------------------- C. 卡片 → 文件（跨进程那一步） */

/* 桌面 profile 的形状：宿主有 `configEditor`，真源是 profile patch，插件**不读**那个文件。
 * 而 `journal.py` 是另一个进程，只认这个文件 —— 所以卡片的值必须落进去。
 * 桩子给最小面：迁移那条路会调 `entries()`，给它空数组等于"没什么可搬"。 */
const editorStub = {
  entries: () => [],
  configuration: () => [],
  inherited: () => ({}),
  documentPath: join(SANDBOX, 'profile-patch.yml'),
  edit: async () => {},
}
const ctxDesktop = (over = {}) => ctxWith({
  configEditor: editorStub,
  get: (key) => (key === 'configEditor' ? editorStub : undefined),
  ...over,
})

writeSettings({ memoryDir: FILE_ROOT })
const ctxCard = ctxDesktop()
mod.apply(ctxCard, { memoryDir: CARD_ROOT })
ok(readSettings().memoryDir === CARD_ROOT,
   'C1 有 configEditor 时，卡片的值被写进 CLI 也读的那份文件（两个进程同一个根）',
   JSON.stringify(readSettings()))
ok(mod.memoryDirectory() === CARD_ROOT,
   'C2 落盘之后解析出来的根就是卡片那个值', mod.memoryDirectory())

mod.apply(ctxDesktop(), { memoryDir: '' })
ok(!Object.hasOwn(readSettings(), 'memoryDir'),
   'C3 卡片清空 → 文件里的键**消失**，不是留个空串', JSON.stringify(readSettings()))

const ctxHeadless = ctxWith()
writeSettings({ memoryDir: FILE_ROOT })
mod.apply(ctxHeadless, { memoryDir: CARD_ROOT })
ok(readSettings().memoryDir === FILE_ROOT,
   'C4 没有 configEditor 的宿主（headless）不回写文件 —— 那份文件本来就是真源',
   JSON.stringify(readSettings()))

/* 手写的其它键不能被吃掉：那是用户的文件，不是插件的。 */
writeSettings({ memoryDir: FILE_ROOT, container: 'my_log', lessons: 'handbook' })
mod.apply(ctxDesktop(), { memoryDir: CARD_ROOT })
const after = readSettings()
ok(after.container === 'my_log' && after.lessons === 'handbook',
   'C5 回写只碰 memoryDir，用户手写的 container/lessons 原样留着', JSON.stringify(after))

/* ----------------------------------------------------- D. 同一个工具里不许劈叉 */

const ROOT_D = join(SANDBOX, 'root-with-content')
mkdirSync(ROOT_D, { recursive: true })
writeFileSync(join(ROOT_D, 'INDEX.md'), '# memory index\n\n- one line\n', 'utf8')
mkdirSync(join(ROOT_D, 'inbox'), { recursive: true })
writeFileSync(join(ROOT_D, 'inbox', '20261015-0000-msg.md'), '---\nfrom: ws-b\n---\n\nhi\n', 'utf8')
/* 条目的形状是**列表项**：`- id:` 开顶格，其余字段缩进两格（见 `readMemoryEntries()` 的
 * 解析规则）。写成 `id:` 开头的裸键值对会被静默跳过 —— 第一版就是那么写的，
 * 于是 D3 数到 0 条、D5 说"没有这条"，看起来像插件读错了根，其实是夹具不对。 */
writeFileSync(join(ROOT_D, 'someone.md'), [
  '- id: probe-entry',
  '  applies-to: testing',
  '  state: active',
  '  source: audit-memory-settings',
  '  body line',
  '',
].join('\n'), 'utf8')

writeSettings({})
const ctxTool = ctxDesktop()
mod.apply(ctxTool, { memoryDir: ROOT_D })
const memoryTool = registered(ctxTool).find((tool) => tool?.name === 'worklog_memory')

if (typeof memoryTool?.execute !== 'function') {
  ok(false, 'D0 记忆工具注册上了',
     `registered=${JSON.stringify(registered(ctxTool).map((t) => t?.name))} `
     + `warns=${JSON.stringify(warningsIn(ctxTool))}`)
} else {
  const status = await memoryTool.execute({ operation: 'status', workspace: SANDBOX })
  const reported = /^memory root: (.+)$/m.exec(status?.text ?? '')?.[1] ?? '(没有这一行)'
  ok(reported === ROOT_D.replace(/\\/g, '/'),
     'D1 工具 status 报的根 = 解析出的根', `${reported}`)
  ok(/^index: \d+ characters$/m.test(status?.text ?? ''),
     'D2 索引字符数也来自同一个根（不是 0）', status?.text)
  ok(/entries: 1\b/.test(status?.text ?? ''),
     'D3 条目也来自同一个根（放一篇进去就该数到 1）', status?.text)
  ok(/inbox: 1\b/.test(status?.text ?? ''),
     'D4 信箱计数同样来自那个根', status?.text)

  const got = await memoryTool.execute({ operation: 'get', id: 'probe-entry', workspace: SANDBOX })
  ok(got?.ok === true && String(got.text).includes('body line'),
     'D5 get 能从那个根里取到正文', String(got?.text ?? '').slice(0, 80))
}

/* ---------------------- E. 保存之后、下一次装载之前（volatile 提交那一刻） */

/* `Config` 的 13 个字段全是 `.volatile()`：卡片保存不会重挂载，只会把新值提交进那个引用。
 * 插件读引用的那些调用点因此**即时**看到新值，而 `journal.py` 是另一个进程、只认设置文件 ——
 * 所以提交的那一刻也得补一次镜像，否则"保存后到重启前"这段窗口里两个进程各用一个根。 */
const cellFor = (initial) => {
  let value = initial
  return { get: () => value, set: (next) => { value = next } }
}

const LIVE_A = join(SANDBOX, 'root-live-a')
const LIVE_B = join(SANDBOX, 'root-live-b')
const cardDir = cellFor(LIVE_A)

writeSettings({})
const ctxLive = ctxDesktop()
mod.apply(ctxLive, { memoryDir: cardDir })
ok(readSettings().memoryDir === LIVE_A,
   'E1 装载时先把卡片的值镜像进文件（这一步 0.8.1 原来就有）', JSON.stringify(readSettings()))

const updates = ctxLive.events.filter(([name]) => name === 'loader/volatile-update')
ok(updates.length === 1,
   'E2 订阅了 loader/volatile-update —— 配置变更走引用提交，不走重挂载',
   `events=${JSON.stringify(ctxLive.events.map(([name]) => name))}`)

cardDir.set(LIVE_B)                                   // ← Loader 的提交：改引用里的值
for (const [, handler] of updates) handler(['memoryDir'])
ok(readSettings().memoryDir === LIVE_B,
   'E3 提交之后设置文件**立刻**跟上（不是等下一次装载）', JSON.stringify(readSettings()))
ok(mod.memoryDirectory() === LIVE_B,
   'E4 解析出来的根也换成新的（CLI 那边读的就是这个文件）', mod.memoryDirectory())

cardDir.set('')
for (const [, handler] of updates) handler(['memoryDir'])
ok(!Object.hasOwn(readSettings(), 'memoryDir'),
   'E5 清空之后文件里的键同样消失（与装载期的 C3 同一口径）', JSON.stringify(readSettings()))

/* 测试自己收拾干净：包里、临时目录里都不留东西。 */
rmSync(SANDBOX, { recursive: true, force: true })

console.log('')
if (problems.length > 0) {
  console.log(`${problems.length} problem(s):`)
  for (const p of problems) console.log(`  - ${p}`)
  process.exit(1)
}
console.log('memory-root settings OK — card beats file beats environment beats the default, '
  + 'the CLI reads the same root, and a volatile commit reaches that file at once')
