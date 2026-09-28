#!/usr/bin/env node
/**
 * 最简自测：**一条命令**，能变红能变绿。
 *
 *   node selftest.mjs
 *
 * 判据就是升格验收要求的那件事：干净样本必须绿、坏样本必须红。
 * 它自己也会红 —— 把 `scripts/whitelist.mjs` 里的 WHITELIST 改小一项，干净样本就会报表外，这里立刻 FAIL。
 */
import { offenders, WHITELIST, fortune, renderFortune, FORTUNES } from './scripts/whitelist.mjs'

const checks = []
const check = (name, cond, detail = '') => checks.push([name, !!cond, detail])

check('白名单是宿主那 9 项', WHITELIST.size === 9, `实际 ${WHITELIST.size}`)
check('干净样本没有表外 specifier', offenders('const a = require("react")').length === 0)
check('表外名字被抓出来',
      offenders('require("@deepseek-ai/dsh-client-ui-helper")').join() === '@deepseek-ai/dsh-client-ui-helper')
check('同一名字只报一次',
      offenders('require("x-nope"); require("x-nope")').length === 1)
check('不误伤注释里的 require',
      offenders('// require("x-nope")').length === 0 &&
      offenders('/* require("x-nope") */').length === 0)

// 夹具走同一条判据（这里直接读内容，避免 spawn：沙箱下 Node 的 piped stdio 会 EPERM）
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const okOff = offenders(readFileSync(join(here, 'fixtures', 'ok.js'), 'utf8'))
const badOff = offenders(readFileSync(join(here, 'fixtures', 'bad.js'), 'utf8'))
check('fixtures/ok.js 是绿的', okOff.length === 0, JSON.stringify(okOff))
check('fixtures/bad.js 是红的', badOff.length === 1, JSON.stringify(badOff))

// 彩蛋也要**被测到**：签表挑得对、形状是叠词，才不是一段没人读的装饰。
check('签表里都是三字叠词（ABB 形）', FORTUNES.every(([w]) => /^(.)(.)\2$/.test(w)),
      FORTUNES.map(([w]) => w).join('/'))
check('空荡荡：一个文件都没给', fortune(0, 0)[0] === '空荡荡', fortune(0, 0)[0])
check('硬邦邦：有表外名字', fortune(2, 1)[0] === '硬邦邦', fortune(2, 1)[0])
check('慢吞吞：扫了 ≥5 个文件', fortune(0, 5)[0] === '慢吞吞', fortune(0, 5)[0])
check('亮晶晶：干净', fortune(0, 2)[0] === '亮晶晶', fortune(0, 2)[0])
check('签的样式是「【诊断签】词 —— 说明」',
      /^【诊断签】\S{3} —— .+/.test(renderFortune(1, 1)), renderFortune(1, 1))

let failed = 0
for (const [name, ok, detail] of checks) {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail && !ok ? '   [' + detail + ']' : ''}`)
  if (!ok) failed++
}
console.log(`\n${checks.length - failed}/${checks.length} passed`)
process.exit(failed ? 1 : 0)
