/**
 * 宿主浏览器模块表的白名单，以及"哪些 require 是表外的"这个纯函数。
 *
 * 为什么是纯函数而不是直接跑子进程：判断逻辑要能被自测直接调用。
 * 抽成函数后，自测不需要 spawn 任何东西，也就不会踩沙箱里 Node 管道（piped stdio）的限制。
 */
import { readFileSync } from 'node:fs'

/** 浏览器里唯一能 `require` 到的 9 个名字（宿主模块表；写别的在浏览器里解析不到，且不报错）。 */
export const WHITELIST = new Set([
  'react',
  'react/jsx-runtime',
  'react-dom',
  'react-dom/client',
  '@deepseek-ai/cordis',
  'dsh-client-store',
  'dsh-client-ui-slots',
  'dsh-client-ui-primitives',
  'dsh-client-ui-dockkit',
])

const REQUIRE_RE = /\brequire\(\s*['"]([^'"]+)['"]\s*\)/g

/**
 * 去掉注释再匹配。
 *
 * 为什么必须去：注释掉的 `// require('x')` 是**已经删掉**的代码，把它报成表外是误报；
 * 而误报会让这条检查被无视 —— 那比没有检查更糟。
 *
 * 边界（刻意保留，不值得为最简示例写词法分析）：字符串里出现 `//` 时会被误当注释，
 * 例如 `require('http://x')`。specifier 里出现 `//` 不是合法模块名，所以这个边界实际碰不到。
 */
export function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
}

/** 从源码里抽出所有 `require('x')` 的 specifier。 */
export function specifiers(src) {
  return [...stripComments(src).matchAll(REQUIRE_RE)].map((m) => m[1])
}

/** 表外的 specifier（去重、保持出现顺序）。返回空数组就是干净。 */
export function offenders(src) {
  const bad = []
  for (const s of specifiers(src)) {
    if (!WHITELIST.has(s) && !bad.includes(s)) bad.push(s)
  }
  return bad
}

/** 读文件并按上面同一套判据给出结论。 */
export function offendersInFile(path) {
  return offenders(readFileSync(path, 'utf8'))
}

/* ------------------------------------------------------------------ *
 * 彩蛋：诊断签（ABB 叠词）
 *
 * 给几种结局各起一个名字，`--彩蛋` 才打印；正常输出保持素净，
 * 免得这份检查在 CI 里显得像个玩具。想加签就往 `FORTUNES` 里加一行。
 *
 * **顺序即优先级**：诊断（空荡荡 / 硬邦邦）排在口味签（慢吞吞 / 亮晶晶）前面 ——
 * 一个表外名字都没扫出来的时候，才有闲心说"扫得挺多"。
 * ------------------------------------------------------------------ */
export const FORTUNES = [
  ['空荡荡', (_n, files) => files === 0, '一个文件都没给，清单空荡荡'],
  ['硬邦邦', (n) => n > 0, '有表外名字杵在那儿 —— 浏览器里 require 不到，还不吭声'],
  ['慢吞吞', (_n, files) => files >= 5, '扫了这么多文件还一个都不差，慢吞吞也稳当'],
  ['亮晶晶', (n, files) => n === 0 && files > 0, '一个表外名字都没有，亮晶晶地干净'],
]

/** 按结局挑一支签；挑不到就让「硬邦邦」兜底（它本来就是最常见的结局）。 */
export function fortune(offendersCount, fileCount) {
  return FORTUNES.find(([, match]) => match(offendersCount, fileCount)) ?? FORTUNES[0]
}

/** 一支签的打印样式：`【诊断签】硬邦邦 —— …` */
export function renderFortune(offendersCount, fileCount) {
  const [word, , note] = fortune(offendersCount, fileCount)
  return `【诊断签】${word} —— ${note}`
}

