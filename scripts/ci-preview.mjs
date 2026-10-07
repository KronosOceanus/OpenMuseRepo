// ci-preview.mjs —— CI 的入口：找出改动了的乐谱，生成对照，产出 PR 报告
//
// 流程：
//   ① 扫 pieces/*/score.mscx，跟基准版本比，找出真有改动的
//   ② 每个改动 → 按**连续段**切分 → 每段一份对照乐谱（两个版本摞成一份）
//   ③ 渲染成图（+ 改动小节的音频）
//   ④ 写出 out/report.md（CI 把它当 PR 评论贴出去）
//
// 报告的头条是**图**不是文字 —— 审一份扒谱要判断的是「这一处对不对」，
// 用乐谱表达最直接。文字 diff 退到折叠块里，需要精确行号时才展开。
//
// 基准版本从哪来：调用方先把它 checkout 到某个目录，用 --base-dir 指过来。
//
// 用法：
//   node scripts/ci-preview.mjs --base-dir <基准目录> [--out out]
//        [--max-per-run 8] [--max-runs 6]

import { readFileSync, writeFileSync, mkdirSync, readdirSync, existsSync } from 'node:fs'
import { join, relative } from 'node:path'
import { scoreDiff, renderText, filterMeasures } from './score-diff.mjs'
import { findMuseScore, exportPng, exportScore } from './render-changed.mjs'
import { buildComparisons, DEFAULT_MAX_PER_RUN, DEFAULT_MAX_RUNS } from './compare.mjs'

// 纯 CLI，不导出任何东西。被 import 时直接报错 —— 否则下面的 process.exit
// 会把调用方一起杀掉，而且报的还是"缺 --base-dir"这种莫名其妙的错。
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
const maxPerRun = Number(opt('--max-per-run', DEFAULT_MAX_PER_RUN))
const maxRuns = Number(opt('--max-runs', DEFAULT_MAX_RUNS))

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
report.push('## 🎼 乐谱改动预览')
report.push('')

if (!bin) {
  report.push('> ⚠️ 本次没有 MuseScore，只有文字 diff。')
  report.push('> 本地渲染：`node scripts/compare.mjs 原版.mscx 改后.mscx out/`')
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

  let built
  try {
    built = buildComparisons(baseXml, headXml, { maxPerRun, maxRuns })
  } catch (e) {
    // 小节数不同（加了一段/删了一段）→ 摞不起来
    report.push(`### ${name}`, '')
    report.push(`> ⚠️ 无法生成对照谱：${String(e.message).split('\n')[0]}`)
    report.push('')
    report.push('<details><summary>文字 diff</summary>', '', '```', renderText(result, '基准', '提交'), '```', '', '</details>', '')
    continue
  }

  const { items, changed, runCount, truncated } = built

  report.push(`### ${name}`)
  report.push('')
  report.push(
    `改动 **${changed.length}** 个小节，切出 **${runCount}** 个连续段：` +
      changed.map((n) => `第 ${n} 小节`).join('、'),
  )
  report.push('')

  const pieceOut = join(outDir, name)
  mkdirSync(pieceOut, { recursive: true })

  for (let i = 0; i < items.length; i++) {
    const it = items[i]
    const cmpPath = join(pieceOut, `compare-${i + 1}.mscx`)
    writeFileSync(cmpPath, it.xml, 'utf8')

    report.push(`**${it.label}**（上＝原版，下＝改后）`)
    report.push('')

    if (bin) {
      try {
        const png = exportPng(bin, cmpPath, join(pieceOut, `compare-${i + 1}.png`))
        if (png) report.push(`![${it.label}](${relative(outDir, png)})`, '')
      } catch (e) {
        report.push(`_渲染失败：${String(e.message).slice(0, 80)}_`, '')
      }
    }
    report.push('')
  }

  if (truncated) {
    report.push(`> 还有改动未渲染（超过 \`--max-runs ${maxRuns}\`）。完整清单见 artifact。`)
    report.push('')
  }

  // 改动小节的音频（用提交版本筛出来的那份）
  if (bin && changed.length > 0) {
    try {
      const audioSrc = join(pieceOut, '_audio.mscx')
      writeFileSync(audioSrc, filterMeasures(headXml, changed), 'utf8')
      if (exportScore(bin, audioSrc, join(pieceOut, 'changed.mp3'), ['-b', '192'])) {
        report.push(`音频（改动的小节，连起来听）：\`${name}/changed.mp3\``)
        report.push('')
      }
    } catch {
      /* 音频失败不影响报告 */
    }
  }

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
console.log(report.join('\n'))
