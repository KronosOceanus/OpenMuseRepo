// render-changed.mjs —— 只把「改动的小节」拿去渲染
//
// 【为什么这是关键】
//
// 审一份扒谱，你要判断的是「这一处对不对」，不是「整份好不好」。
// 但 MuseScore 的 CLI 只能整份导出（--page 能筛页，不能筛小节）。
//
// 办法：**先用 measureSpans 把其余小节从 XML 里剔掉，再交给 MuseScore 导出。**
// 筛完之后的乐谱只有那几个小节，导出的 PNG 和音频自然就只有那几个小节 ——
// 连音频剪辑都不用做。
//
// 产出（给 PR 用）：
//   out/before.png  out/before.mp3    改动前
//   out/after.png   out/after.mp3     改动后
//
// 用法：
//   node scripts/render-changed.mjs <基准.mscx> <提交.mscx> <输出目录>

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { scoreDiff, filterMeasures } from './score-diff.mjs'

/** 在几个常见位置找 MuseScore 可执行文件。CI 上一般在 PATH 里。 */
export function findMuseScore() {
  const candidates = [
    process.env.MUSESCORE_BIN,
    '/Applications/MuseScore 4.app/Contents/MacOS/mscore',
    '/Applications/MuseScore 3.app/Contents/MacOS/mscore',
    'mscore',
    'musescore',
    'musescore3',
  ].filter(Boolean)
  for (const c of candidates) {
    try {
      execFileSync(c, ['--version'], { stdio: 'pipe', timeout: 20000 })
      return c
    } catch {
      /* 试下一个 */
    }
  }
  return null
}

// filterMeasures 在 score-diff.mjs 里 —— 渲染和对照谱共用同一套小节定位逻辑，
// 放两处迟早会漂移。

/** 用 MuseScore CLI 把一份乐谱导出成指定格式。 */
export function exportScore(mscoreBin, scorePath, outPath, extraArgs = []) {
  execFileSync(mscoreBin, ['-o', outPath, ...extraArgs, scorePath], {
    stdio: 'pipe',
    timeout: 300000,
  })
  return existsSync(outPath)
}

/**
 * 导出 PNG —— 注意 MuseScore 会给多页输出加页码后缀（`out.png` → `out-1.png`）。
 * 所以要回头去找实际产出的文件。
 */
export function exportPng(mscoreBin, scorePath, outPath) {
  const dir = outPath.replace(/\.png$/i, '')
  // -T 20 = 裁掉页面留白，只留乐谱本体。PR 里看图才不用缩放。
  execFileSync(mscoreBin, ['-o', outPath, '-T', '20', scorePath], {
    stdio: 'pipe',
    timeout: 300000,
  })
  const candidates = [
    outPath,
    `${dir}-1.png`,
    `${dir}-01.png`,
  ]
  return candidates.find((p) => existsSync(p)) ?? null
}

/**
 * 静态谱面图 + 音频 → MP4。
 *
 * 【为什么要做成视频】
 *
 * GitHub 的 Markdown 不能嵌音频播放器，但**可以嵌视频播放器** ——
 * 只要文件是通过评论的附件上传的（`gh pr comment --attach`）。
 * 所以「谱面图 + 音频 = 一个静止画面的 MP4」就能在 PR 里点开就听。
 *
 * 【编码参数不是随便写的】
 *
 *   -pix_fmt yuv420p        浏览器只认这个像素格式，缺了会黑屏
 *   -vf scale=trunc(iw/2)*2 宽高必须是偶数，缺了 h264 直接报错
 *   -c:a aac                mp4 容器里的音频，浏览器普遍支持
 *   -shortest               音轨结束就结束（图是 -loop 1，不会自己停）
 *   -tune stillimage        静止画面用的编码预设，体积小很多
 *
 * @returns {string|null} 实际产出的路径，失败返回 null
 */
export function makeMp4(pngPath, audioPath, outPath, { width, fps = 10 } = {}) {
  if (!existsSync(pngPath) || !existsSync(audioPath)) return null

  // 缩放表达式。
  //
  // ⚠️ 踩过的坑：不要用 `oh` 去算输出高度 ——
  //    scale=1400:trunc(oh*a/2)*2  →  "Height expression cannot be self-referencing"
  //    ffmpeg 里 `-2` 就是「保持比例、自动取偶数」，直接用它。
  //    高度取偶数是因为 h264 要求宽高都是偶数。
  const scale = width ? `scale=${width}:-2` : 'scale=trunc(iw/2)*2:trunc(ih/2)*2'

  try {
    execFileSync(
      'ffmpeg',
      [
        '-y',
        '-loop', '1', '-framerate', String(fps), '-i', pngPath,
        '-i', audioPath,
        '-c:v', 'libx264',
        '-tune', 'stillimage',
        '-pix_fmt', 'yuv420p',
        '-vf', scale,
        '-c:a', 'aac', '-b:a', '192k',
        '-shortest',
        outPath,
      ],
      { stdio: 'pipe', timeout: 300000 },
    )
  } catch {
    return null
  }
  return existsSync(outPath) ? outPath : null
}

/** ffmpeg 在不在。 */
export function hasFfmpeg() {
  try {
    execFileSync('ffmpeg', ['-version'], { stdio: 'pipe', timeout: 20000 })
    return true
  } catch {
    return false
  }
}

/**
 * macOS 注意：MuseScore 启动时要往 `~/Library/Application Support/MuseScore/`
 * 写日志和设置。如果进程被限制在工作目录内（沙箱），它会静默退出、什么都不产出。
 * 表现是：退出码 0，但没有输出文件，stderr 里有
 *   `open .../logs/dumps/settings.dat: Operation not permitted`
 * 在 CI（Linux runner）上没有这个限制。
 */
export const MACOS_SANDBOX_HINT =
  'macOS 上 MuseScore 需要写 ~/Library/Application Support/MuseScore/；被沙箱挡住时会静默无产出。CI 上无此限制。'

// ── CLI ───────────────────────────────────────────────────────────
if (process.argv[1] && import.meta.url === `file://${process.argv[1]}`) {
  const [basePath, headPath, outDir] = process.argv.slice(2)
  if (!basePath || !headPath || !outDir) {
    console.error('用法: node scripts/render-changed.mjs <基准.mscx> <提交.mscx> <输出目录>')
    process.exit(1)
  }

  const bin = findMuseScore()
  console.log(`MuseScore: ${bin ?? '❌ 没找到（PNG/MP3 会跳过，diff 仍然生成）'}`)

  const baseXml = readFileSync(basePath, 'utf8')
  const headXml = readFileSync(headPath, 'utf8')

  const result = scoreDiff(baseXml, headXml)
  const changed = result.changes.map((c) => ({ staff: c.staff, index: c.measure }))

  console.log(`\n改动 ${changed.length} 处：`)
  for (const c of changed) console.log(`  · 谱表 ${c.staff} 第 ${c.index} 小节`)
  if (result.notes.length) for (const n of result.notes) console.log(`  · ${n}`)

  if (changed.length === 0) {
    console.log('\n没有改动，不渲染。')
    process.exit(0)
  }

  mkdirSync(outDir, { recursive: true })
  const work = join(outDir, '_filtered')
  mkdirSync(work, { recursive: true })

  // 注意：改动的可能是「新增小节」，两个版本都要按各自的小节号筛
  const beforeXml = filterMeasures(baseXml, changed)
  const afterXml = filterMeasures(headXml, changed)

  const beforePath = join(work, 'before.mscx')
  const afterPath = join(work, 'after.mscx')
  writeFileSync(beforePath, beforeXml, 'utf8')
  writeFileSync(afterPath, afterXml, 'utf8')

  console.log(
    `\n筛出的小节：${Buffer.byteLength(beforeXml)} → 整份 ${Buffer.byteLength(baseXml)} 字节` +
      `（保留 ${(Buffer.byteLength(beforeXml) / Buffer.byteLength(baseXml) * 100).toFixed(0)}%）`,
  )

  if (bin) {
    for (const [label, path] of [
      ['before', beforePath],
      ['after', afterPath],
    ]) {
      // PNG：裁掉留白，且要找实际产出文件名（MuseScore 会加页码后缀）
      try {
        const png = exportPng(bin, path, resolve(outDir, `${label}.png`))
        console.log(png ? `  ✅ ${label}.png  → ${png.replace(outDir + '/', '')}` : `  ❌ ${label}.png 没产出`)
      } catch (e) {
        console.log(`  ❌ ${label}.png   ${String(e.message).split('\n')[0].slice(0, 70)}`)
      }

      // MP3
      try {
        const out = resolve(outDir, `${label}.mp3`)
        const ok = exportScore(bin, path, out, ['-b', '192'])
        console.log(ok ? `  ✅ ${label}.mp3` : `  ❌ ${label}.mp3 没产出`)
      } catch (e) {
        console.log(`  ❌ ${label}.mp3   ${String(e.message).split('\n')[0].slice(0, 70)}`)
      }
    }
  } else {
    console.log(`\n  ⚠️ 没找到 MuseScore —— 只生成了 diff，没有图和音频。`)
    console.log(`     ${MACOS_SANDBOX_HINT}`)
  }

  writeFileSync(join(outDir, 'diff.json'), JSON.stringify(result, null, 2), 'utf8')
  console.log(`\n产出目录：${resolve(outDir)}`)
}
