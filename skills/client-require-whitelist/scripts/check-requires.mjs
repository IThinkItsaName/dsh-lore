#!/usr/bin/env node
/**
 * 检查客户端插件里的 `require(...)` 是否都在宿主白名单里。
 *
 *   node check-requires.mjs lib/client.js [更多文件…]
 *   node check-requires.mjs --彩蛋 lib/client.js        # 结论附带一支「诊断签」
 *
 * 表外的名字在浏览器里**解析不到，而且不抛错**（工厂体的异常会被宿主吞掉或表现成"插件没效果"），
 * 所以这件事值得变成一条会红的命令，而不是靠记性。
 */
import { offendersInFile, renderFortune } from './whitelist.mjs'

const argv = process.argv.slice(2)
const egg = argv.includes('--彩蛋') || argv.includes('--egg')
const files = argv.filter((a) => a !== '--彩蛋' && a !== '--egg')

if (!files.length) {
  console.error('用法：node check-requires.mjs [--彩蛋] <file.js> [更多文件…]')
  if (egg) console.log(renderFortune(0, 0))   // 空荡荡也有一支签，不然它就永远是死分支
  process.exit(2)
}

let bad = 0
for (const f of files) {
  for (const s of offendersInFile(f)) {
    console.log(`${f}: 表外 specifier \`${s}\``)
    bad++
  }
}
console.log(`检查 ${files.length} 个文件，表外 ${bad} 处`)
if (egg) console.log(renderFortune(bad, files.length))
process.exit(bad ? 1 : 0)
