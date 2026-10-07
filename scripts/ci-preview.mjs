// ci-preview.mjs —— CI 的入口：找出改动了的乐谱，生成对照，产出 PR 报告
//
// 流程：
//   ① 扫 pieces/*/score.mscx，跟基准版本比，找出真有改动的
//   ② 每个改动 → 按**连续段**切分 → 每段一份对照乐谱（两个版本摞成一份，红绿标注）
//   ③ 渲染成图；再给每段做一段声音，图+声音合成 MP4
//   ④ 写出 out/report.md（CI 把它当 PR 评论贴出去）
//
// 报告的头条是**图**不是文字 —— 审一份扒谱要判断的是「这一处对不对」，
// 用乐谱表达最直接。文字 diff 退到折叠块里，需要精确行号时才展开。
//
// 【为什么做 MP4】
//
// GitHub 的 Markdown 不能嵌音频播放器，但**能嵌视频播放器** ——
// 只要文件是通过评论的附件上传的（`gh pr comment --attach`）。
// 所以「谱面图 + 声音」做成静止画面的 MP4，PR 里点开就能听。
//
// 【链接前缀】
//
// 报告里的图/视频链接有两种用法：
//   --link-prefix out      → 正文里写 `out/神话2/compare-1-1.png`。
//                            这样 `gh --attach out/神话2/compare-1-1.png`
//                            能把正文里的路径原地改写成上传后的 URL。
//   --image-base <url>     → 正文里写绝对 URL（配合把产出推到某条分支）。
//
// 不传就是本地模式，用相对路径（本地看图直接用文件系统）。
//
// 基准版本从哪来：调用方先把它 checkout 到一个目录，用 --base-dir 指过来。
//
// 用法：
//   node scripts/ci-preview.mjs --base-dir <基准目录> [--out out]
//        [--link-prefix out | --image-base <url>]
//        [--max-per-run 4] [--max-runs 6]

import { readFileSync, writeFileSync, mkdirSync, readdirSync, existsSync } from 'node:fs'
import { join, relative } from 'node:path'
import { scoreDiff, renderText } from './score-diff.mjs'
import { findMuseScore, exportPng, exportScore, makeMp4, hasFfmpeg } from './render-changed.mjs'
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
const linkPrefix = (opt('--link-prefix', '') || '').replace(/\/$/, '')
const imageBase = (opt('--image-base', '') || '').replace(/\/$/, '')

if (!baseDir) {
  console.error(
    '用法: node scripts/ci-preview.mjs --base-dir <基准目录> [--out out] [--link-prefix out | --image-base <url>]',
  )
  process.exit(1)
}

/**
 * 产出的相对路径 → 报告里该用的链接。
 *
 * ⚠️ 本地路径（--link-prefix）不能做 URL 编码 —— gh --attach 是按字面量
 *    匹配正文里的路径来原地改写的，编码过就匹配不上了。
 *    绝对 URL（--image-base）必须编码，否则中文路径会让 Markdown 链接断掉。
 */
function linkFor(relPath) {
  if (imageBase) return `${imageBase}/${encodeURI(relPath)}`
  if (linkPrefix) return `${linkPrefix}/${relPath}`
  return relPath
}

/**
 * 记一个要 --attach 的文件。
 *
 * ⚠️ 路径必须和报告正文里写的**逐字相同** —— gh --attach 是按字面量匹配
 *    正文里的路径来原地改写的。所以这里用 linkFor() 生成，和正文同源。
 *    用 relative('.', 绝对路径) 会得到 ../../.. 那种东西，匹配不上。
 */
function noteAttachment(relPath) {
  if (!linkPrefix) return // 用 URL 或纯相对路径时不走 gh --attach
  attachments.push(linkFor(relPath))
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
const ffmpeg = hasFfmpeg()
mkdirSync(outDir, { recursive: true })

// 把工具可用性打出来 —— CI 日志里一眼能看到是不是环境缺东西
console.error(`[环境] MuseScore: ${bin ?? '❌ 没找到'}`)
console.error(`[环境] ffmpeg:    ${ffmpeg ? '✅' : '❌ 没找到（不会生成 MP4）'}`)

const report = []
const attachments = [] // 要 --attach 的文件（相对当前目录的路径）
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
    report.push(`### ${name}`, '')
    report.push(`> ⚠️ 无法生成对照谱：${String(e.message).split('\n')[0]}`)
    report.push('')
    report.push(
      '<details><summary>文字 diff</summary>',
      '',
      '```',
      renderText(result, '基准', '提交'),
      '```',
      '',
      '</details>',
      '',
    )
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
    const n = i + 1
    const cmpPath = join(pieceOut, `compare-${n}.mscx`)
    writeFileSync(cmpPath, it.xml, 'utf8')

    report.push(`**${it.label}**（上＝原版，下＝改后，红＝改掉／绿＝改成）`)
    report.push('')

    if (!bin) continue

    // 图
    let png = null
    try {
      png = exportPng(bin, cmpPath, join(pieceOut, `compare-${n}.png`))
    } catch (e) {
      report.push(`_渲染失败：${String(e.message).slice(0, 300)}_`, '')
      continue
    }
    if (!png) {
      report.push('_没有产出图片_', '')
      continue
    }

    report.push(`![${it.label}](${linkFor(relative(outDir, png))})`)
    report.push('')
    noteAttachment(relative(outDir, png))

    // 声音 → MP4
    //
    // 音频用「改后」那一侧的乐谱，不是上面那张对照谱 ——
    // 对照谱有 4 个谱表（原版 + 改后同时在），播出来像两台钢琴一起弹。
    if (!ffmpeg) {
      console.error(`[跳过声音] 找不到 ffmpeg`)
    } else {
      try {
        const headScorePath = join(pieceOut, `_audio-${n}.mscx`)
        writeFileSync(headScorePath, it.headScore, 'utf8')
        const mp3Path = join(pieceOut, `changed-${n}.mp3`)

        const mp3ok = exportScore(bin, headScorePath, mp3Path, ['-b', '192'])
        if (!mp3ok) {
          console.error(`[跳过声音] 第 ${n} 段：MuseScore 没导出 mp3`)
        } else {
          const mp4 = makeMp4(png, mp3Path, join(pieceOut, `play-${n}.mp4`), { width: 1400 })
          if (mp4) {
            report.push('▶️ **点开听**（这是「改后」那一版的声音）：')
            report.push('')
            // ⚠️ 视频引用必须独占一个段落，gh --attach 才会把它换成播放器。
            //    夹在句子里会退化成普通链接。
            report.push(`![](${linkFor(relative(outDir, mp4))})`)
            report.push('')
            noteAttachment(relative(outDir, mp4))
          } else {
            console.error(`[跳过声音] 第 ${n} 段：ffmpeg 合成 mp4 失败`)
          }
        }
      } catch (e) {
        console.error(`[跳过声音] 第 ${n} 段：\n${String(e.message)}`)
      }
    }

    report.push('')
  }

  if (truncated) {
    report.push(`> 还有改动未渲染（超过 \`--max-runs ${maxRuns}\`）。完整清单见 artifact。`)
    report.push('')
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

// 附件清单单独写一份 —— 工作流的 gh --attach 直接读它，免得在 YAML 里拼数组。
//
// ⚠️ 末尾必须有换行符。`while read` 遇到「最后一行没有 \n」时返回非零、
//    循环体不执行 —— 那一行会被悄悄吃掉。实测过：6 个附件只读到 5 个，
//    最后一段的 MP4 根本没被 --attach 上去。
writeFileSync(join(outDir, 'attachments.txt'), attachments.length ? attachments.join('\n') + '\n' : '', 'utf8')

console.log(`\n报告已写出：${reportPath}`)
console.log(`附件 ${attachments.length} 个：`)
for (const a of attachments) console.log(`  ${a}`)
console.log()
console.log(report.join('\n'))
