// import-score.mjs —— 把一个 .mscz 收进仓库
//
// .mscz 是二进制（zip），不能直接进 git。这个脚本做两件事：
//   ① 剥掉 <eid>，写成 pieces/<曲名>/score.mscx   ← 这份进 git，参与 diff
//   ② 原封保留原始 .mscz 到 pieces/<曲名>/source.mscz（存档，可选 --no-source）
//
// 为什么留原始文件：万一以后发现归一化有损，能重新导一次。
//
// 用法：
//   node scripts/import-score.mjs <输入.mscz> [曲名] [--no-source]

import { readFileSync, writeFileSync, mkdirSync, copyFileSync, existsSync } from 'node:fs'
import { join, basename, extname } from 'node:path'
import { stripEids, readScoreText, summarize } from './normalize.mjs'
import { parseScore } from './score-diff.mjs'

// 纯 CLI，不导出任何东西。被 import 时直接报错，别让 process.exit 杀掉调用方。
if (!(process.argv[1] && import.meta.url === `file://${process.argv[1]}`)) {
  throw new Error('import-score.mjs 是 CLI 脚本，不支持被 import')
}

const args = process.argv.slice(2)
const noSource = args.includes('--no-source')
const positional = args.filter((a) => !a.startsWith('--'))
const [input, nameArg] = positional

if (!input) {
  console.error('用法: node scripts/import-score.mjs <输入.mscz> [曲名] [--no-source]')
  process.exit(1)
}
if (!existsSync(input)) {
  console.error(`找不到文件：${input}`)
  process.exit(1)
}

const name = nameArg ?? basename(input, extname(input))
const dir = join('pieces', name)

if (existsSync(join(dir, 'score.mscx'))) {
  console.error(`已经存在：${dir}/score.mscx`)
  console.error('（要重新导入就先删掉那个目录。脚本拒绝覆盖，免得悄悄弄丢改动。）')
  process.exit(1)
}

mkdirSync(dir, { recursive: true })

const raw = readScoreText(input)
const xml = stripEids(raw)
writeFileSync(join(dir, 'score.mscx'), xml, 'utf8')

if (!noSource) copyFileSync(input, join(dir, 'source.mscz'))

// 注意：剥掉的 eid 个数要从**原始**文本统计 ——
// 剥完之后的文本里它们已经变成 <eid/> 了，统计永远是 0。
const before = summarize(raw)
const after = summarize(xml)
const staves = parseScore(xml)

console.log(`导入「${name}」→ ${dir}/`)
console.log(`  score.mscx    ${after.bytes} B   小节 ${staves.map((x) => `${x.id}:${x.measures.length}`).join(' ')}`)
console.log(`  剥掉 eid      ${before.eids} 个   （${before.bytes} → ${after.bytes} B）`)
console.log(`  格式版本      ${(raw.match(/<programVersion>([^<]+)</) ?? [, '?'])[1]}`)
if (!noSource) console.log(`  source.mscz   原始文件（存档，不参与 diff）`)
