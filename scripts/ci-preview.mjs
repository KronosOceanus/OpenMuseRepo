// ci-preview.mjs —— CI 的入口：找出改动了的乐谱，生成对照，产出 PR 报告
//
// 流程：
//   ① 扫 pieces/*/score.mscx
//   ② 跟「基准版本」比，找出真的有改动的
//   ③ 每个改动 → 语义 diff + 只渲染改动的小节（PNG + MP3）
//   ④ 产出 out/report.md（CI 直接把它当 PR 评论贴出去）
//
// 基准版本从哪来：调用方先把它 checkout 到某个目录，用 --base-dir 指过来。
// 在 GitHub Actions 里就是 `git worktree add` 或 `git checkout <base> -- <path>`。
//
// 用法：
//   node scripts/ci-preview.mjs --base-dir <基准目录> [--out out]

import { readFileSync, writeFileSync, mkdirSync, readdirSync, existsSync } from 'node:fs'
import { join, dirname, relative } from 'node:path'
import { scoreDiff, renderText } from './score-diff.mjs'
import { filterMeasures, findMuseScore, exportPng, exportScore } from './render-changed.mjs'

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

// ── ① 找所有乐谱 ──────────────────────────────────────────────────
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
report.push(`MuseScore：${bin ? `\`${bin}\`` : '❌ 没找到（只有 diff，没有图和音频）'}`)
report.push('')

let anyChange = false

for (const { name, path: headPath } of headScores) {
  const basePath = join(baseDir, 'pieces', name, 'score.mscx')
  if (!existsSync(basePath)) {
    report.push(`### ${name}`)
    report.push('')
    report.push('🆕 新加的曲子。')
    report.push('')
    anyChange = true
    continue
  }

  const baseXml = readFileSync(basePath, 'utf8')
  const headXml = readFileSync(headPath, 'utf8')
  if (baseXml === headXml) continue

  anyChange = true
  const result = scoreDiff(baseXml, headXml)
  const changed = result.changes.map((c) => ({ staff: c.staff, index: c.measure }))

  report.push(`### ${name}`)
  report.push('')
  report.push('```')
  report.push(renderText(result, '基准', '提交'))
  report.push('```')
  report.push('')

  if (changed.length === 0) continue

  // 渲染改动的小节
  const pieceOut = join(outDir, name)
  mkdirSync(pieceOut, { recursive: true })
  const work = join(pieceOut, '_filtered')
  mkdirSync(work, { recursive: true })

  const pair = {}
  for (const [label, xml] of [
    ['before', baseXml],
    ['after', headXml],
  ]) {
    const filtered = filterMeasures(xml, changed)
    const p = join(work, `${label}.mscx`)
    writeFileSync(p, filtered, 'utf8')
    pair[label] = p
  }

  if (bin) {
    for (const [label, p] of Object.entries(pair)) {
      try {
        const png = exportPng(bin, p, join(pieceOut, `${label}.png`))
        if (png) report.push(`**${label === 'before' ? '改动前' : '改动后'}**（第 ${changed.map((c) => c.index).join(', ')} 小节）`)
        if (png) report.push('')
        if (png) report.push(`![${label}](${relative(outDir, png)})`)
        if (png) report.push('')
      } catch (e) {
        report.push(`_${label} PNG 渲染失败：${String(e.message).slice(0, 80)}_`)
        report.push('')
      }
      try {
        exportScore(bin, p, join(pieceOut, `${label}.mp3`), ['-b', '192'])
      } catch {
        /* 音频失败不影响报告 */
      }
    }
  }
}

if (!anyChange) {
  report.push('_没有乐谱改动。_')
}

const reportPath = join(outDir, 'report.md')
writeFileSync(reportPath, report.join('\n'), 'utf8')
console.log(`\n报告已写出：${reportPath}`)
console.log(report.join('\n'))
