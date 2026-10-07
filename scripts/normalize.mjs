// normalize.mjs —— 把 MuseScore 文件变成「可以 git diff」的形态
//
// 【为什么需要这一步】
//
// MuseScore 的 XML 里有几百个 <eid>（元素 ID），每个都是随机字符串。
// 同一首曲子两次导出，先差上千行噪音 —— 跟音乐内容毫无关系。
//
// 实测（神话2.mscz，4074 行的 mscx，798 个 eid）：
//   只改 eid 的值        → diff 1596 行
//   剥掉 eid 之后        → diff    0 行   ← 噪声清零
//   剥掉 eid 再改一个音  → diff    2 行   ← 而且精确定位到 <pitch>
//
// 所以：**剥掉 eid 是让乐谱可 diff 的唯一前提。**
//
// 用法：
//   node scripts/normalize.mjs <输入.mscz|输入.mscx> <输出.mscx>

import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync, mkdtempSync, rmSync, readdirSync, statSync } from 'node:fs'
import { join, basename, extname } from 'node:path'
import { tmpdir } from 'node:os'

/** 把 <eid>xxxx</eid> 统一成 <eid/>，不留任何随机内容。 */
export function stripEids(xml) {
  return xml.replace(/<eid>[^<]*<\/eid>/g, '<eid/>')
}

/** 从 .mscz（zip）里取出主 .mscx 的文本。.mscx 直接读。 */
export function readScoreText(inputPath) {
  const ext = extname(inputPath).toLowerCase()
  if (ext === '.mscx') return readFileSync(inputPath, 'utf8')
  if (ext !== '.mscz') throw new Error(`不支持的格式 ${ext}（只认 .mscz / .mscx）`)

  // .mscz 是 zip。用系统 unzip（macOS / Linux / CI 都有）。
  const dir = mkdtempSync(join(tmpdir(), 'om-'))
  try {
    execFileSync('unzip', ['-q', '-o', inputPath, '-d', dir], { stdio: 'pipe' })
    const found = readdirSync(dir).filter((f) => f.toLowerCase().endsWith('.mscx'))
    if (found.length === 0) throw new Error('.mscz 里没有 .mscx')
    // 正常只有一个；多个时选最大的（主谱）
    found.sort((a, b) => statSync(join(dir, b)).size - statSync(join(dir, a)).size)
    return readFileSync(join(dir, found[0]), 'utf8')
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

/** 统计基本信息，用来在 CI 里报告。 */
export function summarize(xml) {
  const count = (re) => (xml.match(re) ?? []).length
  return {
    eids: count(/<eid>/g),
    measures: count(/<Measure>/g),
    staves: count(/<Staff /g),
    chords: count(/<Chord>/g),
    rests: count(/<Rest>/g),
    bytes: Buffer.byteLength(xml),
    lines: xml.split('\n').length,
  }
}

// ── 直接运行时当作 CLI ────────────────────────────────────────────
if (process.argv[1] && import.meta.url === `file://${process.argv[1]}`) {
  const [input, output] = process.argv.slice(2)
  if (!input || !output) {
    console.error('用法: node scripts/normalize.mjs <输入.mscz|.mscx> <输出.mscx>')
    process.exit(1)
  }
  const raw = readScoreText(input)
  const before = summarize(raw)
  const xml = stripEids(raw)
  writeFileSync(output, xml, 'utf8')
  const after = summarize(xml)

  console.log(`  ${basename(input)} → ${basename(output)}`)
  console.log(`    剥掉 eid   ${before.eids} 个`)
  console.log(`    字节       ${before.bytes} → ${after.bytes}`)
  console.log(`    行数       ${before.lines} → ${after.lines}`)
  console.log(
    `    结构       小节 ${after.measures} / 谱表 ${after.staves} / 和弦 ${after.chords} / 休止 ${after.rests}`,
  )
}
