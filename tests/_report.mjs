// Harness 的收尾记账：PASS / FAIL / **SKIP 三类分开**，别把"没验"记成"验过了"。
//
// 这个模块存在的理由（审查报告 F13，2026-10-15 复核成立）：
// 各 harness 里一共有 9 处 `ok(true, '… SKIPPED')` —— 恒真断言。它们在输出里是 `PASS`，
// 于是"13 支全绿"这句话分不清"验过"和"跳过"。更糟的是其中几处**只在自己的分支里跳过、
// 没有 else**（`manifest.mjs` 的 patch 不变量、`audit-doc-consistency.mjs` 的文档链接），
// 条件不满足时**一条断言都不跑，却仍然 exit 0**。
//
// 用法（harness 顶部）：
//
//   import { ok, skip, report, problems } from './_report.mjs'
//
// 然后结尾把原来的三行换成一行：
//
//   report('path consistency OK')          // 有 FAIL → 打印 `N FAILED` 并 exit 1
//
// `report()` **总会**打印跳过计数（有跳过时），所以"全绿"这句话从此自带注解。
//
// 判据一条都没放宽：`skip()` 只改记账方式，不改任何断言的真假。

/** 失败的标签。`report()` 用它决定退出码。 */
export const problems = []
/** 跳过的标签，**不计入** problems。 */
export const skipped = []

let passed = 0

/** 一条真断言。`detail` 只在失败时打印（与各 harness 原来的约定一致）。 */
export function ok(condition, label, detail = '') {
  const good = Boolean(condition)
  console.log(`${good ? 'PASS' : 'FAIL'}  ${label}${good || !detail ? '' : `  -- ${detail}`}`)
  if (good) passed += 1
  else problems.push(label)
  return good
}

/**
 * 一条**该验却没验**的断言。
 *
 * 只在"环境里根本没有可比对的东西"时用（例如参考树缺席）。**不要**用它替代一条能写的断言：
 * 能写就必须写 —— 这个函数是给"写不出来"的情况留的出口，不是给"懒得写"留的。
 */
export function skip(label, why = '') {
  console.log(`SKIP  ${label}${why ? `  -- ${why}` : ''}`)
  skipped.push(label)
}

/** 退出码与收尾那行。`message` 是各 harness 原来的成功语。 */
export function report(message, { exit = true } = {}) {
  const tail = skipped.length > 0 ? ` (${skipped.length} skipped)` : ''
  if (problems.length > 0) {
    console.log(`\n${problems.length} FAILED${tail}`)
    if (exit) process.exit(1)
    return 1
  }
  console.log(`\n${message}${tail}`)
  if (exit) process.exit(0)
  return 0
}

/** 读数（`audit-*` 自己还想再断言时用得上）。 */
export function tally() {
  return { passed, failed: problems.length, skipped: skipped.length }
}
