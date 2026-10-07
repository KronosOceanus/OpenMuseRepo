// merge-versions.mjs —— 把两个版本的乐谱摞成一份，用来并排看差异
//
// 产物长这样：
//
//   ┌─ 版本 A（原版）────────────┐
//   │  ♪  ♪  ♪  ♪               │   staff 1, 2
//   ├─ 版本 B（改后）────────────┤
//   │  ♪  ♪  ♪  ♪               │   staff 3, 4
//   └───────────────────────────┘
//
// 两个版本的同一小节上下对齐，差异自己就跳出来了 —— 不用加任何标记。
//
// ── .mscx 的结构 ──────────────────────────────────────────────────
//
//   <museScore version="4.50">
//     <programVersion>…</programVersion>
//     <Score>
//       <eid/>
//       … 乐谱级设置（Division / metaTag / pageFormat …）…
//       <Part id="1">              ← 乐器声明
//         <Staff id="1">…</Staff>  ← 仅供声明的谱表，缩进 6
//         <Staff id="2">…</Staff>
//         <Instrument id="piano">…</Instrument>
//       </Part>
//       <Staff id="1">             ← 真正的音乐，缩进 4
//         <Measure>…</Measure>
//       </Staff>
//     </Score>
//   </museScore>
//
// 合并 = ① 给 B 复制一份 Part 声明  ② 把 B 的音乐谱表接在后面（id 重编号）
//
// ── 踩过的三个坑（都靠实测才发现）────────────────────────────────
//
// ① **不能靠缩进区分两类 <Staff>。** 缩进是「最好别依赖」的信息 ——
//    合并过程中一旦拼接错一格，整个解析就崩（表现为"0 个谱表"，
//    但 MuseScore 其实还能读）。改用「是否落在某个 <Part>…</Part> 区间内」判断。
//
// ② **段尾要取下一个开标签的「起始」位置**，不能取结束位置，
//    否则下一个 <Staff …> 会被算进上一段，合并后出现重复开标签，MuseScore 拒收。
//
// ③ **开闭标签缩进本来就不一致**（<Staff> 缩进 4，</Staff> 缩进 6），
//    所以一切定位都靠开标签。

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname } from 'node:path'

// ── 解析 ──────────────────────────────────────────────────────────

/** 把一份 .mscx 拆成可以重组的几块。 */
export function dissect(xml) {
  const scoreOpenIdx = xml.indexOf('<Score>')
  if (scoreOpenIdx < 0) throw new Error('找不到 <Score>')
  const scoreCloseIdx = xml.lastIndexOf('</Score>')
  if (scoreCloseIdx < 0) throw new Error('找不到 </Score>')

  const before = xml.slice(0, scoreOpenIdx)
  const inner = xml.slice(scoreOpenIdx + '<Score>'.length, scoreCloseIdx)
  const after = xml.slice(scoreCloseIdx)

  // ── Part 块 ──
  const parts = []
  const partRe = /<Part id="(\d+)">[\s\S]*?<\/Part>/g
  let m
  while ((m = partRe.exec(inner))) {
    parts.push({ id: m[1], text: m[0], start: m.index, end: m.index + m[0].length })
  }
  const insidePart = (pos) => parts.some((p) => pos >= p.start && pos < p.end)

  // ── 音乐谱表：所有 <Staff id=…> 里，不在任何 Part 区间内的那些 ──
  const openRe = /<Staff id="(\d+)">/g
  const marks = []
  while ((m = openRe.exec(inner))) {
    if (insidePart(m.index)) continue // 这是乐器声明里的，不是音乐
    marks.push({ id: m[1], tagStart: m.index, tag: m[0], contentStart: m.index + m[0].length })
  }
  marks.forEach((mark, i) => {
    mark.end = i + 1 < marks.length ? marks[i + 1].tagStart : inner.length
  })

  const staves = marks.map((mark) => ({
    id: mark.id,
    text: mark.tag + inner.slice(mark.contentStart, mark.end),
  }))

  // 乐谱级设置 = 第一个 Part 之前的内容
  const scoreHead = inner.slice(0, parts.length ? parts[0].start : marks.length ? marks[0].tagStart : inner.length)

  const measureCount = staves.length ? (staves[0].text.match(/<Measure[^>]*>/g) ?? []).length : 0

  return {
    before,
    scoreHead,
    parts,
    staves,
    after,
    staffIds: staves.map((s) => Number(s.id)),
    measureCount,
  }
}

/** 把一段 XML 里所有 <Staff id="N"> 改成映射后的值。 */
function renumberStaffIds(text, map) {
  return text.replace(/<Staff id="(\d+)">/g, (_, n) => `<Staff id="${map[n] ?? n}">`)
}

/**
 * 改掉 Part / Instrument 里的显示名。
 *
 * 名字出现在三个地方（实测）：
 *   <Part><trackName>钢琴</trackName>
 *   <Part><Instrument><longName>钢琴</longName>     ← 谱表左边显示的是这个
 *   <Part><Instrument><trackName>钢琴</trackName>
 * 三个都改，免得不同渲染路径取到不同的。
 */
function relabelPart(text, label, shortLabel) {
  return text
    .replace(/<trackName>[^<]*<\/trackName>/g, `<trackName>${label}</trackName>`)
    .replace(/<longName>[^<]*<\/longName>/g, `<longName>${label}</longName>`)
    .replace(/<shortName>[^<]*<\/shortName>/g, `<shortName>${shortLabel}</shortName>`)
}

/** 复制一份 Part 声明，改掉它的 id 和内部 Staff 引用。 */
function clonePart(part, newPartId, staffMap) {
  return renumberStaffIds(part.text.replace(/<Part id="\d+">/, `<Part id="${newPartId}">`), staffMap)
}

/**
 * 合并两个版本。
 * @param {string} xmlA 版本 A（基座，保留它的乐谱级设置）
 * @param {string} xmlB 版本 B（谱表接在后面）
 * @param {{labelA?:string, labelB?:string, shortA?:string, shortB?:string}} opts
 *        显示名。longName 只出现在第一个系统，后续系统用 shortName ——
 *        所以 short 也要给有意义的字，否则第二页起就只剩「A」「B」看不懂。
 */
export function mergeVersions(xmlA, xmlB, opts = {}) {
  const labelA = opts.labelA ?? '原版'
  const labelB = opts.labelB ?? '改后'
  const shortA = opts.shortA ?? '原'
  const shortB = opts.shortB ?? '改'

  const A = dissect(xmlA)
  const B = dissect(xmlB)

  if (A.staves.length === 0 || B.staves.length === 0) {
    throw new Error(`解析异常：A 有 ${A.staves.length} 个谱表，B 有 ${B.staves.length} 个`)
  }
  if (A.measureCount !== B.measureCount) {
    throw new Error(
      `两个版本的小节数不同（A=${A.measureCount}，B=${B.measureCount}）—— 摞在一起会对不齐。\n` +
        `这种差异（加了一段/删了一段）更适合用文件 diff 看，不适合并排对照。`,
    )
  }

  const maxA = Math.max(...A.staffIds)
  const staffMap = {}
  B.staffIds.forEach((id, i) => {
    staffMap[id] = String(maxA + i + 1)
  })

  const allPartIds = [...A.parts, ...B.parts].map((p) => Number(p.id))
  const newPartId = String((allPartIds.length ? Math.max(...allPartIds) : 0) + 1)

  // B 的 Part 用 A 的第一个 Part 当模板（保留乐器设置），再改名
  const bPart = relabelPart(clonePart(A.parts[0], newPartId, staffMap), labelB, shortB)

  const IND = '\n    '
  const partsXml =
    A.parts.map((p) => IND + relabelPart(p.text, labelA, shortA)).join('') + IND + bPart
  const musicXml =
    A.staves.map((s) => IND + s.text).join('') + B.staves.map((s) => IND + renumberStaffIds(s.text, staffMap)).join('')

  return A.before + '<Score>' + A.scoreHead + partsXml + musicXml + '\n  ' + A.after
}

// ── CLI ───────────────────────────────────────────────────────────
if (process.argv[1] && import.meta.url === `file://${process.argv[1]}`) {
  const [a, b, out] = process.argv.slice(2)
  if (!a || !b || !out) {
    console.error('用法: node merge-versions.mjs <版本A.mscx> <版本B.mscx> <输出.mscx>')
    process.exit(1)
  }
  const merged = mergeVersions(readFileSync(a, 'utf8'), readFileSync(b, 'utf8'))
  mkdirSync(dirname(out), { recursive: true })
  writeFileSync(out, merged, 'utf8')

  const d = dissect(merged)
  console.log(`  合并完成 → ${out}`)
  console.log(`    A 的谱表 ${dissect(readFileSync(a, 'utf8')).staffIds.join(',')}`)
  console.log(`    B 的谱表 ${dissect(readFileSync(b, 'utf8')).staffIds.join(',')}（重编号后）`)
  console.log(`    合并后 ${d.staffIds.length} 个谱表，每谱表 ${d.measureCount} 小节`)
  console.log(`    字节 ${Buffer.byteLength(merged)}`)
}
