// Memory injection: the two prompt contributions, and the "nothing means nothing" rule.
//
// This harness exists because the two switches on the settings page's 记忆 tab used to be
// **empty promises**: `memoryInjectIndex` was labelled "inject the memory index by default" and
// `memoryPersonalSearchable` claimed the personal directory would be searchable, while the
// plugin called `ctx.systemPrompt` exactly zero times. A control that can be clicked and does
// nothing is a defect, not a backlog item (docs/plugin-spec.md §五) — the page said the feature
// worked, so a reader would conclude the memory was empty rather than that nothing was wired.
//
// What is asserted here, and why each one is worth an assertion:
//
//   1. nothing → `''`. An absent root, an absent index, and a header-only index must all inject
//      nothing. A line saying "the memory is empty" is noise paid for on EVERY request forever,
//      which is the failure mode that is invisible in a single test run.
//   2. content → the index, with the instruction that the body needs a tool call.
//   3. over budget → dropped, not truncated. A truncated index presents a subset as if it were
//      the whole, which is worse than injecting nothing.
//   4. registration: both contributions are registered when enabled, neither when disabled,
//      the index only when its own switch is on, and the inbox even at zero (its text is
//      resolved per assembly, so the count must be read then — not at mount).
//
//   node tests/audit-memory-injection.mjs
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { PKG } from './_pkg.mjs'

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}

/*
 * Fixtures live OUTSIDE the repo, under the system temp directory.
 *
 * `audit-settings.mjs` set this convention and this harness first ignored it, writing settings
 * files into `<pkg>/tests/tmp/` with a `Date.now()` + `Math.random()` name and never deleting
 * them. The result was 25 untracked files inside the package — which the source
 * `_package.py --check` then reported as drift, because "files in the package that the mirror
 * does not have" is exactly what drift means. A harness must not leave things in the tree it
 * is verifying.
 */
const SANDBOX = mkdtempSync(join(tmpdir(), 'dsh-worklog-memory-'))
const ROOT = join(SANDBOX, 'memory')
const INDEX = join(ROOT, 'INDEX.md')
const INBOX = join(ROOT, 'inbox')

function resetMemory() {
  rmSync(ROOT, { recursive: true, force: true })
}

function writeIndex(text) {
  mkdirSync(ROOT, { recursive: true })
  writeFileSync(INDEX, text, 'utf8')
}

function writeInbox(count) {
  mkdirSync(INBOX, { recursive: true })
  for (let i = 0; i < count; i += 1) {
    writeFileSync(join(INBOX, `20260928-0000${i}-msg.md`), 'body', 'utf8')
  }
}

/* The entry, loaded through `_pkg.mjs` so `@deepseek-ai/*` resolves (see its resolver hook).
 * `pathToFileURL` rather than the bare path: on Windows an absolute path is not a valid ESM
 * specifier (`ERR_UNSUPPORTED_ESM_URL_SCHEME`), which is why the other harnesses do this too. */
const mod = await import(pathToFileURL(join(PKG, 'lib', 'index.js')).href)

// Point the plugin at THIS harness's sandbox. `_pkg.mjs` already isolated the memory root so a
// careless harness cannot read the developer's real one; this overrides that with a directory
// this file owns and deletes, so nothing is written into the package at all.
process.env.DSH_WORKLOG_MEMORY = ROOT

/* ---------------------------------------------------------------- 1. nothing ── */

resetMemory()
ok(mod.memoryIndexSection() === '', 'an absent memory root injects nothing')
ok(mod.countInboxItems() === 0, 'an absent inbox counts 0, not a throw')

// A generated index that carries only its own H1 is, in substance, empty. Injecting its header
// would be the "here is nothing" line this rule exists to prevent.
writeIndex('# 全局记忆索引（生成物：由正文分册推出，勿手写）\n')
ok(mod.memoryIndexSection() === '', 'a header-only index injects nothing', mod.memoryIndexSection())

/* ---------------------------------------------------------------- 2. content ── */

const SAMPLE = [
  '# 全局记忆索引（生成物：由正文分册推出，勿手写）',
  '',
  '## dsh-plugin',
  '- host-style-claiming：症状：样式丢失。根因：宿主认领无主 style。（dsh-plugin）',
  '',
].join('\n')
writeIndex(SAMPLE)
const injected = mod.memoryIndexSection()
ok(injected !== '', 'a populated index IS injected')
ok(injected.includes('host-style-claiming'), 'the injected text carries the entry line')
ok(injected.includes('worklog_memory'), 'the injected text says the body needs the tool')
ok(injected.includes('## 全局记忆'), 'the injected text has its own heading')
ok(!injected.startsWith('# 全局记忆索引'), 'the generated file H1 is not duplicated into the prompt')

/* ---------------------------------------------------------------- 3. budget ── */

// Past the soft budget the whole section is dropped. Asserted by GROWING the file rather than by
// reaching into the constant: a test that reads the same number the code does cannot notice the
// number being changed to something absurd.
writeIndex(`${SAMPLE}\n${'- filler：'.repeat(1) + 'x'.repeat(900)}\n`)
ok(mod.memoryIndexSection() === '',
  'an over-budget index is dropped, not truncated',
  `length=${mod.memoryIndexSection().length}`)

/* ---------------------------------------------- 4. registration, and the gates ── */

/** A stand-in context that records what the plugin registers. */
function fakeCtx() {
  const calls = { section: [], context: [] }
  const ctx = {
    skills: {
      registerProvider: () => {},
      get: () => undefined,
      list: async () => [],
    },
    tools: { register: () => () => {} },
    systemPrompt: {
      section: (s) => { calls.section.push(s); return () => {} },
      context: (c) => { calls.context.push(c); return () => {} },
    },
    effect: () => {},
    logger: { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} },
    get: () => null,
  }
  return { ctx, calls }
}

/** Write a settings file for one run. Returns its path, inside the sandbox. */
let settingsSeq = 0
function settingsWith(document) {
  settingsSeq += 1
  const path = join(SANDBOX, `settings-${settingsSeq}.json`)
  writeFileSync(path, JSON.stringify(document), 'utf8')
  return path
}

function mountWith(document) {
  process.env.DSH_WORKLOG_SETTINGS = settingsWith(document)
  const { ctx, calls } = fakeCtx()
  mod.apply(ctx, {})
  return calls
}

resetMemory()
writeIndex(SAMPLE)

// Defaults: memoryEnabled true, memoryInjectIndex true → both registered.
{
  const calls = mountWith({})
  ok(calls.section.length === 1, 'the index section is registered by default', String(calls.section.length))
  ok(calls.context.length === 1, 'the inbox context is registered by default', String(calls.context.length))
  ok(calls.section[0]?.name === 'dsh-worklog:memory-index', 'the section carries a stable name', calls.section[0]?.name)
  ok(calls.context[0]?.name === 'dsh-worklog:inbox', 'the context carries a stable name', calls.context[0]?.name)
  ok(Number.isFinite(calls.section[0]?.order), 'the section carries a finite order')
  ok(Number.isFinite(calls.context[0]?.order), 'the context carries a finite order')
  // The whole point of the two-interface split: the index is STABLE text, the inbox is resolved
  // per assembly. Registering a string for the inbox would freeze the count at mount time.
  ok(typeof calls.section[0]?.text === 'function', 'the index text is a function (re-read per assembly)')
  ok(typeof calls.context[0]?.text === 'function', 'the inbox text is a function (count read per assembly)')
  // These two used to be empty promises; assert the resolved text so a re-registration that
  // ignores the content cannot pass.
  ok(calls.section[0]?.text().includes('host-style-claiming'), 'the registered section resolves to the index')
}

// `memoryInjectIndex: false` → the index is NOT registered, the inbox still is.
{
  const calls = mountWith({ memoryInjectIndex: false })
  ok(calls.section.length === 0, 'memoryInjectIndex=false registers no section', String(calls.section.length))
  ok(calls.context.length === 1, 'but the inbox context is independent of that switch', String(calls.context.length))
}

// `memoryEnabled: false` → neither. This is the master switch that the page says needs a restart,
// and this is the asymmetry it is describing.
{
  const calls = mountWith({ memoryEnabled: false })
  ok(calls.section.length === 0, 'memoryEnabled=false registers no index section')
  ok(calls.context.length === 0, 'memoryEnabled=false registers no inbox context')
}

/* ------------------------------------------- 5. the inbox count and its words ── */

{
  const calls = mountWith({})
  const text = calls.context[0].text
  resetMemory()
  ok(text() === '', 'an absent inbox produces the empty string, not a notice', JSON.stringify(text()))
  mkdirSync(ROOT, { recursive: true })
  ok(text() === '', 'an empty inbox directory produces the empty string')
  writeInbox(3)
  const three = text()
  ok(three.includes('3'), 'the notice states the count', three)
  ok(three.includes('worklog_memory'), 'the notice says how to read them', three)
  // A stray non-`.md` file is not a message — the CLI's own `count` skips it, so this must too.
  writeFileSync(join(INBOX, 'half-written.tmp'), 'x', 'utf8')
  ok(mod.countInboxItems() === 3, 'a .tmp left by an interrupted put is not counted', String(mod.countInboxItems()))
}

resetMemory()
rmSync(SANDBOX, { recursive: true, force: true })

console.log('')
if (problems.length > 0) {
  console.log(`${problems.length} FAILED`)
  process.exit(1)
}
console.log('memory injection OK — nothing means nothing, and both switches are real')
