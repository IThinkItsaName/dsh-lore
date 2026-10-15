// 门禁自己的卫生规则 —— 写成断言，因为每一条都已经被违反过一次，而且违反时**看不出来**：
//
//   1. 每个 harness 都必须 import `_pkg.mjs`。2026-10-14：一个都没 import，`run.mjs` 于是读了
//      开发者的真实设置文件，13 条断言被静默丢掉（"用着产品反而变红"的那种套件）；2026-10-15：
//      那条 `$DSH_HOME` 钉写成了条件式，桌面会话导出的真实 `$DSH_HOME` 直接胜出，一次性迁移把
//      整份真实记忆库复制进了 `<tmpdir>/…-isolated`（45 个文件含 `.git`）。
//   2. `_pkg.mjs` 的三处钉必须**无条件**。条件式钉恰好钉不住"真正要钉的那台机器"：真实会话本来
//      就会导出这些变量，而"开发者机器上跑门禁"正是唯一需要隔离的场景。
//   3. 隔离用的设置文件不能在包内。`_package.py --check` 会把包内多出来的夹具判成漂移，而
//      harness 不该往它正在验证的那棵树里写东西。
//   4. 磁盘上的每道门禁都接在某个 npm 脚本上，脚本点名的每个文件也都存在。没人跑的新审计
//      等于一盏什么都不表示的绿灯；脚本里写错文件名则是"跑了一半就断"。
//   5. CI 仍然跑两道 node 门禁与 python 自测（F3：`lib/**` 与 15 支 harness 曾经无人守）。
//   6. 文档里写的 harness 支数（CI 注释、`RELEASING.md` 的发版清单）必须等于链上真跑的数。
//      "15 支"在 16 支时留着过一次：发版清单也是断言漏掉的地方。
//   7. `RELEASING.md` 判读行里那句"N 条变异"必须等于变异表里真有的条数 —— 同一个理由，
//      只是这条守的是第 6 步（变异驱动）而不是第 5 步。
//   8. 变异驱动自己不许有"看着在跑、其实没跑"：表里用到的每一相都得在 `PHASES` 里登记，
//      而且它得保留**起飞前检查**（先跑一遍未变异的自测，期望字样不在标签里就当场退出）。
//      2026-10-15：三条变异的期望断言内联在 `main()` 里，驱动跑不到它们，白跑一整轮。
//
//   运行：node tests/audit-harness-hygiene.mjs
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { ok, report } from './_report.mjs'
import { PKG } from './_pkg.mjs'

const read = (path) => readFileSync(path, 'utf8')
const TESTS = join(PKG, 'tests')

/* 不是门禁的 .mjs：豁免要有理由，而且理由写在这里，不写在"没人记得"里。 */
const NOT_A_GATE = new Map([
  ['_pkg.mjs', '隔离垫片本身（被所有门禁 import）'],
  ['_report.mjs', '记账器本身'],
  ['preaudit.mjs', '由 `npm run audit` 接走，不在 test:plugin 链里'],
  ['measure-real-corpus.mjs', '手动测量工具：它测的就是真实语料，本来就不该隔离'],
])

/* ---- 1. `test:plugin` 链上的每个文件都在磁盘上，磁盘上的每道门禁都在这条链上 ---- */
const scripts = JSON.parse(read(join(PKG, 'package.json'))).scripts
const wired = String(scripts['test:plugin'] || '')
  .split('&&')
  .map((step) => step.trim().replace(/^node\s+/, ''))
  .filter(Boolean)
const missing = wired.filter((rel) => !existsSync(join(PKG, rel)))
ok(missing.length === 0, '`test:plugin` 点名的每个文件都存在', missing.join(', ') || 'all present')

const gates = readdirSync(TESTS)
  .filter((name) => name.endsWith('.mjs') && !NOT_A_GATE.has(name))
  .sort()
const wiredGates = wired.filter((rel) => rel.startsWith('tests/')).map((rel) => rel.slice(6)).sort()
ok(JSON.stringify(gates) === JSON.stringify(wiredGates),
  '`test:plugin` 跑的就是磁盘上那几道门禁（不重、不漏、不写错名）',
  `磁盘 ${gates.length} 支，脚本 ${wiredGates.length} 支`
  + (JSON.stringify(gates) === JSON.stringify(wiredGates)
    ? '' : `；只有磁盘有：${gates.filter((g) => !wiredGates.includes(g)).join(',') || '无'}`
      + `；只有脚本有：${wiredGates.filter((g) => !gates.includes(g)).join(',') || '无'}`))
ok(/preaudit\.mjs/.test(String(scripts.audit || '')), '`npm run audit` 接的是 preaudit.mjs',
  String(scripts.audit || '(missing)'))

/* ---- 2. 每道门禁都 import 隔离垫片 ---- */
const withoutShim = gates.filter((name) => !/_pkg\.mjs/.test(read(join(TESTS, name))))
ok(withoutShim.length === 0,
  '每道门禁都 import `_pkg.mjs`（否则它读的是开发者机器上的真实设置/记忆）',
  withoutShim.join(', ') || `all ${gates.length} import it`)

/* ---- 3. 垫片里的三处钉是无条件的，且隔离路径不在包内 ---- */
const shim = read(join(TESTS, '_pkg.mjs'))
const PINNED = ['DSH_WORKLOG_SETTINGS', 'DSH_WORKLOG_MEMORY', 'DSH_HOME']
for (const variable of PINNED) {
  ok(new RegExp(`^process\\.env\\.${variable} = `, 'm').test(shim),
    `_pkg.mjs 在顶层钉住 ${variable}`,
    shim.split('\n').filter((line) => line.includes(variable) && line.startsWith('process.env')).join(' | '))
  ok(!new RegExp(`^if \\(process\\.env\\.${variable} === undefined\\)`, 'm').test(shim),
    `${variable} 的钉是无条件的（条件式等于没钉 —— 2026-10-14/15 两次都是这么漏的）`)
}
ok(!/join\(PKG, 'tests', 'tmp'/.test(shim),
  '隔离设置文件不在包内（包内多出来的夹具就是 `_package.py --check` 的漂移）')
ok(/ISOLATED_SETTINGS_FILE = join\(tmpdir\(\)/.test(shim),
  '隔离设置文件在系统临时目录下')
/* 收尾：隔离根不能跨运行残留（残留会让下一次的结果取决于上一次留下什么）。 */
ok(/process\.on\('exit'/.test(shim) && /rmSync\(path, \{ recursive: true, force: true \}\)/.test(shim),
  '`_pkg.mjs` 在退出时收走自己那三个隔离路径（不在共享临时目录里留东西）')

/* ---- 4. CI 还守着两道 node 门禁与 python 自测 ---- */
const ci = read(join(PKG, '.github', 'workflows', 'ci.yml'))
ok(/npm run test:plugin/.test(ci), 'CI 跑 `npm run test:plugin`')
ok(/npm run audit/.test(ci), 'CI 跑 `npm run audit`')
ok(/_selftest\.py/.test(ci), 'CI 跑技能自测')

/* ---- 5. CI 里那句话不许再说反（第二轮审查 N4）----
   `dist/skill-only/` 有 3 个文件是**跟踪的**，而 `npm run test:skill-only` 是 `--check`：
   产物缺失/过期时它**报错**，不会"建出来"。注释与步骤名都写反过一次。 */
ok(!/dist\/skill-only\/[^\n]*不在 git 里/.test(ci),
  'CI 不再说 `dist/skill-only/` 不在 git 里（它有 3 个跟踪文件）')
ok(!/name:\s*Build the skill-only copy/.test(ci),
  'CI 那一步不再叫 "Build …"（它跑的是 `--check`，报错而不是构建）')
ok(/name:\s*Check the skill-only copy/.test(ci), 'CI 那一步叫 "Check the skill-only copy"')
/* 步骤里写的 harness 支数必须等于这条链真正跑的支数（"15 支"曾经在 16 支时留着）。 */
const claimed = /(\d+)\s*支 harness/.exec(ci)
ok(claimed !== null && Number(claimed[1]) === wiredGates.length,
  'CI 注释里的 harness 支数与链上真跑的一致',
  claimed ? `注释说 ${claimed[1]} 支，链上 ${wiredGates.length} 支` : '注释里没写支数')

/* ---- 6. 发版清单里写的支数也得是真的（`RELEASING.md` 同时是"最后一道文档门禁"）---- */
const releasing = read(join(PKG, 'RELEASING.md'))
const releasingClaim = /(\d+)\s*个 harness/.exec(releasing)
ok(releasingClaim !== null && Number(releasingClaim[1]) === wiredGates.length,
  '`RELEASING.md` 发版清单里的 harness 支数与链上真跑的一致',
  releasingClaim ? `清单说 ${releasingClaim[1]} 个，链上 ${wiredGates.length} 支` : '清单里没写支数')

/* 判读行里那句"N 条变异"同样是发版时才看的数字：表长了而清单没跟，就是 F17 那类
   "文档里抄了一个会过期的字面值"。数的是表里以 `("` 开头的行。 */
const driver = read(join(PKG, 'tests', 'reverse-verify.py'))
const table = /MUTATIONS[^=]*=\s*\[([\s\S]*?)\n\]/.exec(driver)
const rows = table ? (table[1].match(/^\s*\("/gm) || []).length : 0
const mutationClaim = /(\d+)\s*条变异：/.exec(releasing)
ok(rows > 0 && mutationClaim !== null && Number(mutationClaim[1]) === rows,
  '`RELEASING.md` 判读行里的变异条数与 `tests/reverse-verify.py` 的变异表一致',
  `清单说 ${mutationClaim ? mutationClaim[1] : '（没写）'} 条，表里有 ${rows} 条`)

/* ---- 7. 变异驱动自己也有"看着在跑、其实没跑"（第三轮复查踩到的）----
   2026-10-15：三条新变异的期望断言内联在 `_selftest.py` 的 `main()` 里，而驱动只跑
   `PHASES` 登记过的函数 —— 跑完一整轮才报"期望的标签没变红；红了 0 条"，真实原因却是
   那条断言从头到尾没被执行过（跑完九十条才发现，一轮白跑）。修法两半：断言搬进相
   （`numbering_phase`），驱动加**起飞前检查**（先跑一遍未变异的自测，期望字样不在标签
   里就当场退出）。下面几条守的就是这两半别被改回去。

   起飞前检查自己也有过一次假警报：`gates` 那一相的标签是拼出来的
   （`f"gates: the central list names \`{name}\`"` —— 未变异时拼的是别的规则名），拿
   "未变异时的标签里有没有这个字样"硬比，会把一条一直好好的变异判成不可达。所以那关按
   `reachability()` 分情形判：标签里有 → 通过；字样写在相源码里 → 通过；只出现在相之外
   （`main()` 里）→ 当场报"不可达"；相里的模板也拼不出来 → 报"期望字样写错了"。 */
const phaseBlock = /PHASES[^=]*=\s*\{([\s\S]*?)\n\}/.exec(driver)
const registered = new Set([...(phaseBlock ? phaseBlock[1].matchAll(/"(\w+)":/g) : [])].map((m) => m[1]))
const usedPhases = new Set((table ? (table[1].match(/^\s*\("(\w+)"/gm) || []) : [])
  .map((line) => /"(\w+)"/.exec(line)[1]))
const unregistered = [...usedPhases].filter((phase) => !registered.has(phase))
ok(registered.size > 0 && usedPhases.size > 0 && unregistered.length === 0,
  '变异表里用到的每一相都在 `PHASES` 里登记过（没登记的那一相，驱动当场 KeyError）',
  `登记 ${registered.size} 相；表里用到 ${usedPhases.size} 相`
  + (unregistered.length ? `；没登记的：${unregistered.join(', ')}` : ''))
ok(/^def unmutated_labels\(/m.test(driver) && /unmutated_labels\(st_path, /.test(driver),
  '驱动有起飞前检查：先跑一遍未变异的自测，把断言标签收进来')
ok(/^def reachability\(/m.test(driver) && /if any\(expect in label for label in labels\)/.test(driver),
  '起飞前检查与判定用同一种匹配（`expect in label`）——两处不一样就等于没查')
ok(/^def phase_templates\(/m.test(driver) && /phase_templates\(selftest_src, ranges\)/.test(driver),
  '起飞前检查认"动态标签"（相里拼出来的 `f"…{name}…"`），不把好好的变异判成不可达')
ok(/^def top_level_ranges\(/m.test(driver) && /字样只出现在相之外/.test(driver),
  '起飞前检查能指出"字样落在哪个函数里"（内联在 `main()` 里的那种，当场点名）')
ok(/--no-preflight/.test(driver),
  '起飞前检查能显式跳过（`--no-preflight`），而不是悄悄失效')

report(`harness hygiene OK — ${wiredGates.length} gates wired, all importing the shim, the CI + RELEASING prose matches reality (${rows} mutations), and the driver keeps its preflight (${registered.size} phases registered)`)
