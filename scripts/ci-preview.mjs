// ci-preview.mjs —— CI 的入口：找出改动了的乐谱，生成对照，产出 PR 报告
//
// 流程：
//   ① 扫 pieces/*/score.mscx，跟基准版本比，找出真有改动的
//   ② 每个改动 → 生成**对照乐谱**（两个版本摞成一份，改动的小节）
//   ③ 渲染成图 + 改动小节的音频
//   ④ 写出 out/report.md（CI 把它当 PR 评论贴出去）
//
// 报告的头条是**图**不是文字 —— 审一份扒谱要判断的是「这一处对不对」，
// 用乐谱表达最直接：两个版本上下对齐，同一拍在同一水平位置，差异自己就跳出来。
// 文字 diff 退到折叠块里，需要精确行号时才展开。
//
// 基准版本从哪来：调用方先把它 checkout 到某个目录，用 --base-dir 指过来。
//
// 用法：
//   node scripts/ci-preview.mjs --base-dir <基准目录> [--out out]

import { readFileSync, writeFileSync, mkdirSync, readdirSync, existsSync } from 'node:fs'
import { join, relative } from 'node:path'
import { scoreDiff, renderText, filterMeasures } from './score-diff.mjs'
import { findMuseScore, exportPng, exportScore } from './render-changed.mjs'
import { buildComparison } from './compare.mjs'

// 这个文件是纯 CLI，不导出任何东西。被 import 时直接报错 —— 否则下面的
// process.exit 会把调用方一起杀掉（而且报的还是"缺 --base-dir"这种莫名其妙的错）。
if (!(process.argv[1] && import.meta.url === `file://${process.argv[1]}`)) {
  throw new Error('ci-preview.mjs 是 CLI 脚本，不支持被 import')
}

// ── 参数 ──────────────────────────────────────────────────────────
const argv = process.argv.slice(2)
const opt = (name, dflt) => {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt
}
const baseDir = opt('--base-dir')
const outDir = opt('--out', 'out')

if (!baseDir) {
  console.error('用法: node scripts/ci-preview.mjs --base-dir <基准目录> [--out out]')
  process.exit(1)
}

/** 扫出所有乐谱 piece。 */
function findScores(root) {
  const out = []
  const pieces = join(root, 'pieces')
  if (!existsSync(pieces)) return out
  for (const name of readdirSync(pieces)) {
    const p = join(pieces, name, 'score.mscx')
    if (existsSync(p)) out.push({ name, path: p })
  }
  return out
}

const headScores = findScores('.')
const bin = findMuseScore()
mkdirSync(outDir, { recursive: true })

const report = []
const artifacts = [] // { piece, label, rel } 供调用方决定怎么发布
report.push('## 🎼 乐谱改动预览')
report.push('')

if (!bin) {
  report.push('> ⚠️ 没找到 MuseScore —— 这次只有文字 diff，没有对照谱图。')
  report.push('> macOS 上它需要写 `~/Library/Application Support/MuseScore/`，被沙箱挡住会静默无产出。')
  report.push('')
}

let anyChange = false

for (const { name, path: headPath } of headScores) {
  const basePath = join(baseDir, 'pieces', name, 'score.mscx')
  if (!existsSync(basePath)) {
    report.push(`### ${name}`, '', '🆕 新加的曲子。', '')
    anyChange = true
    continue
  }

  const baseXml = readFileSync(basePath, 'utf8')
  const headXml = readFileSync(headPath, 'utf8')
  if (baseXml === headXml) continue

  anyChange = true
  const result = scoreDiff(baseXml, headXml)
  const changedMeasures = [...new Set(result.changes.map((c) => Number(c.measure)))].sort((a, b) => a - b)

  report.push(`### ${name}`)
  report.push('')
  report.push(`改动 **${changedMeasures.length}** 个小节：${changedMeasures.map((n) => `第 ${n} 小节`).join('、')}`)
  report.push('')

  if (changedMeasures.length === 0) {
    report.push('_（只有结构层面变化，没有可对比的小节）_', '')
    continue
  }

  const pieceOut = join(outDir, name)
  mkdirSync(pieceOut, { recursive: true })

  // ── ① 对照乐谱：两个版本摞成一份 ──
  let comparisonRendered = false
  try {
    const { xml } = buildComparison(baseXml, headXml, { labelA: '原版', labelB: '改后' })
    if (xml) {
      const cmpPath = join(pieceOut, 'compare.mscx')
      writeFileSync(cmpPath, xml, 'utf8')

      if (bin) {
        const png = exportPng(bin, cmpPath, join(pieceOut, 'compare.png'))
        if (png) {
          report.push(`**对照谱**（上＝原版，下＝改后）`)
          report.push('')
          report.push(`![对照谱](${relative(outDir, png)})`)
          report.push('')
          artifacts.push({ piece: name, label: '对照谱', rel: relative(outDir, png) })
          comparisonRendered = true
        }
      }
    }
  } catch (e) {
    // 小节数不同（加了一段/删了一段）→ 摞不起来，退回并排两图
    report.push(`> ⚠️ 无法生成对照谱：${String(e.message).split('\n')[0]}`)
    report.push('')
  }

  // ── ② 兜底：摞不起来就分别渲染改动的小节 ──
  if (!comparisonRendered && bin) {
    for (const [label, xml, cn] of [
      ['before', baseXml, '原版'],
      ['after', headXml, '改后'],
    ]) {
      try {
        // 用 compare 里同一套筛法（按小节序号）
        const p = join(pieceOut, `_${label}.mscx`)
        writeFileSync(p, filterMeasures(xml, changedMeasures), 'utf8')
        const png = exportPng(bin, p, join(pieceOut, `${label}.png`))
        if (png) {
          report.push(`**${cn}**`, '', `![${cn}](${relative(outDir, png)})`, '')
          artifacts.push({ piece: name, label: cn, rel: relative(outDir, png) })
        }
      } catch (e) {
        report.push(`_${cn} 渲染失败：${String(e.message).slice(0, 80)}_`, '')
      }
    }
  }

  // ── ③ 文字 diff 收进折叠块 ──
  report.push('<details><summary>文字 diff（精确到行）</summary>')
  report.push('')
  report.push('```')
  report.push(renderText(result, '基准', '提交'))
  report.push('```')
  report.push('')
  report.push('</details>')
  report.push('')
}

if (!anyChange) {
  report.push('_没有乐谱改动。_')
}

const reportPath = join(outDir, 'report.md')
writeFileSync(reportPath, report.join('\n'), 'utf8')
console.log(`\n报告已写出：${reportPath}`)
console.log(`产出 ${artifacts.length} 张图`)
for (const a of artifacts) console.log(`  ${a.piece} / ${a.label}  →  ${a.rel}`)
console.log()
console.log(report.join('\n'))
