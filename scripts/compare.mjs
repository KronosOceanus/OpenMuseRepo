// compare.mjs —— 一步到位：算出差异 → 只留改动的小节 → 把两个版本摞起来
//
// 产物是一份 .mscx，渲染出来就是并排对照：
//
//   ┌─ 原版 ───────────┐
//   │  ♪ ♪ ♪ ♪         │   ← 只含改动过的那些小节
//   ├─ 改后 ───────────┤
//   │  ♪ ♪ ♪ ♪         │
//   └──────────────────┘
//
// 【为什么不用文字 diff】
//
// 文字 diff 是给程序员看的。审一份扒谱要判断的是「这一处对不对」，
// 而乐谱的差异用乐谱表达最直接 —— 两个版本上下对齐，同一拍在同一水平位置，
// 差异自己就跳出来了，不用加任何标记、也不用读数字。
//
// 用法：
//   node scripts/compare.mjs <原版.mscx> <改后.mscx> <输出.mscx> [--labels 原版,改后]

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname } from 'node:path'
import { scoreDiff, filterMeasures } from './score-diff.mjs'
import { mergeVersions, dissect } from './merge-versions.mjs'

/**
 * 生成对照乐谱。
 * @returns {{ xml: string|null, changed: number[], kept: number, diff: object }}
 */
export function buildComparison(baseXml, headXml, opts = {}) {
  const result = scoreDiff(baseXml, headXml)

  // 哪些小节变了（按序号去重 —— 差异可能只落在某个谱表上）
  const changed = [...new Set(result.changes.map((c) => Number(c.measure)))].sort((a, b) => a - b)

  if (changed.length === 0) {
    return { xml: null, changed: [], kept: 0, diff: result }
  }

  // 两个版本都筛同样的小节序号，所以筛后小节数必然相同 —— mergeVersions 会校验这点
  const xml = mergeVersions(filterMeasures(baseXml, changed), filterMeasures(headXml, changed), opts)

  return { xml, changed, kept: changed.length, diff: result }
}

// ── CLI ───────────────────────────────────────────────────────────
if (process.argv[1] && import.meta.url === `file://${process.argv[1]}`) {
  const argv = process.argv.slice(2)
  const li = argv.indexOf('--labels')
  const labels = li >= 0 && argv[li + 1] ? argv[li + 1].split(',') : []
  // ⚠️ 只有 --labels 真的出现时，才跳过它后面那个值。
  //    否则 li = -1 → li + 1 = 0，会把第一个参数当成标签值排掉。
  const positional = argv.filter((a, i) => !a.startsWith('--') && !(li >= 0 && i === li + 1))
  const [basePath, headPath, outPath] = positional

  if (!basePath || !headPath || !outPath) {
    console.error('用法: node scripts/compare.mjs <原版.mscx> <改后.mscx> <输出.mscx> [--labels 原版,改后]')
    process.exit(1)
  }

  const { xml, changed, kept, diff } = buildComparison(
    readFileSync(basePath, 'utf8'),
    readFileSync(headPath, 'utf8'),
    labels.length === 2 ? { labelA: labels[0], labelB: labels[1] } : {},
  )

  if (!xml) {
    console.log('  两个版本没有差异，不生成对照。')
    process.exit(0)
  }

  mkdirSync(dirname(outPath), { recursive: true })
  writeFileSync(outPath, xml, 'utf8')

  const d = dissect(xml)
  console.log(`  改动的小节：${changed.join(', ')}`)
  console.log(`  对照乐谱 → ${outPath}`)
  console.log(`    ${d.staffIds.length} 个谱表（上半 = 原版，下半 = 改后）`)
  console.log(`    共 ${d.measureCount} 小节 = 改动过的 ${kept} 个`)
  console.log(`    字节 ${Buffer.byteLength(xml)}`)
  console.log()
  for (const c of diff.changes) console.log(`    小节 ${c.measure}（谱表 ${c.staff}）`)
}
