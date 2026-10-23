#!/usr/bin/env node
/**
 * journal.mjs — 给 `journal.py` 找 Python 的薄启动器。
 *
 * 为什么需要它：DSH 桌面版自带一个 Python 运行时（`<DSH_HOME>/dsh-runtimes/`），
 * 但 PATH 上不一定有 `python`。这个启动器按下面的顺序找，找到一个就 `spawn`：
 *
 *   1. `DSH_WORKLOG_PYTHON`（显式指定，最高优先级）
 *   2. `DSH_PRIMARY_RUNTIME` / `DSH_BUNDLED_PRIMARY_RUNTIME`（DSH 自己也可能设）
 *   3. `<DSH_HOME>/dsh-runtimes/* /dependencies/python/python[3]`
 *   4. PATH 上的 `python` / `python3` / `py -3`
 *
 * 用法与 `python scripts/journal.py` **完全相同**：
 *     node scripts/journal.mjs brief
 *     node scripts/journal.mjs auto --run orient
 *
 * 只用 Node 标准库；不依赖 DSH 的 npm 包，所以技能层仍然可以独立跑。
 */
import { spawnSync } from 'node:child_process'
import { existsSync, readdirSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const JOURNAL = join(HERE, 'journal.py')

function dshHome() {
  const value = (process.env.DSH_HOME ?? '').trim()
  return value === '' ? join(homedir(), '.dsh') : value
}

function candidates() {
  const result = []
  const seen = new Set()
  const add = (command, prefix = []) => {
    const key = `${command}\0${prefix.join('\0')}`
    if (seen.has(key)) return
    seen.add(key)
    result.push({ command, prefix })
  }

  const addRuntime = (value) => {
    const raw = (value ?? '').trim()
    if (raw === '') return
    const path = resolve(raw)
    if (!existsSync(path)) return
    let info
    try {
      info = statSync(path)
    } catch {
      return
    }
    if (info.isFile()) {
      if (/python(?:3(?:\.\d+)?)?(?:\.exe)?$/i.test(path)) add(path)
      else if (/runtime\.json$/i.test(path)) addRuntime(dirname(path))
      return
    }
    const suffixes = process.platform === 'win32'
      ? ['dependencies/python/python.exe', 'python.exe']
      : ['dependencies/python/bin/python3', 'dependencies/python/bin/python', 'bin/python3', 'bin/python']
    for (const suffix of suffixes) {
      const candidate = join(path, suffix)
      if (existsSync(candidate)) add(candidate)
    }
  }

  const configured = (process.env.DSH_WORKLOG_PYTHON ?? '').trim()
  if (configured !== '') add(configured)
  for (const key of ['DSH_PRIMARY_RUNTIME', 'DSH_BUNDLED_PRIMARY_RUNTIME']) {
    addRuntime(process.env[key])
  }

  const runtimes = join(dshHome(), 'dsh-runtimes')
  try {
    const names = readdirSync(runtimes)
    names.sort((a, b) => (a === 'dsh-primary-runtime' ? -1
      : b === 'dsh-primary-runtime' ? 1
        : a.localeCompare(b)))
    for (const name of names) addRuntime(join(runtimes, name))
  } catch { /* 没有 dsh-runtimes：继续走 PATH */ }

  add('python')
  add('python3')
  if (process.platform === 'win32') add('py', ['-3'])
  return result
}

if (!existsSync(JOURNAL)) {
  console.error(`journal.mjs: 找不到 ${JOURNAL}`)
  process.exit(1)
}

const args = process.argv.slice(2)
let lastError
for (const candidate of candidates()) {
  const result = spawnSync(
    candidate.command,
    [...candidate.prefix, '-B', JOURNAL, ...args],
    { cwd: process.cwd(), env: process.env, stdio: 'inherit', windowsHide: true },
  )
  if (result.error) {
    if (result.error.code === 'ENOENT') {
      lastError = result.error
      continue
    }
    console.error(`journal.mjs: 起不了 ${candidate.command}：${result.error.message}`)
    process.exit(1)
  }
  // Windows Store 的 python 桩存在但退出 9009；它不算“找到了”，继续回退。
  if (result.status === 9009) {
    lastError = new Error(`${candidate.command} 是 Windows Store 桩（exit 9009）`)
    continue
  }
  process.exit(result.status ?? 1)
}

const tried = candidates().map(({ command, prefix }) => [command, ...prefix].join(' '))
console.error('journal.mjs: 找不到 Python。试过：' + tried.join('、'))
if (lastError) console.error(`           最后一个错误：${lastError.message}`)
console.error('           设 `DSH_WORKLOG_PYTHON` 指向 python 可执行文件；')
console.error('           或安装 DSH 桌面版（自带运行时），或把 python 放进 PATH。')
process.exit(127)
