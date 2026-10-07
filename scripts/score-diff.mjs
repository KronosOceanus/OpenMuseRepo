// score-diff.mjs —— 按小节输出「语义 diff」
//
// 【为什么不用 git diff】
//
// git 的行级 diff 对乐谱是错的粒度。MuseScore 的 XML 一个 <Measure> 展开成
// 几十行，「第 21 小节改了」这件事在行级 diff 里看不出来。
//
// 而且复合情况（换小节、加谱表）会让行级 diff 整体错位，
// 输出的东西人没法读。
//
// 这个脚本按 **小节** 对齐比较，输出的是：
//
//   小节 21（谱表 1）
//     - <pitch>74</pitch>
//     + <pitch>99</pitch>
//
// 这才是能拿去裁决的单位 —— 一个改动 = 一个小节里的一处差异。
//
// 用法：
//   node scripts/score-diff.mjs <基准.mscx> <提交.mscx> [--json]

import { readFileSync } from 'node:fs'
import { basename } from 'node:path'

/**
 * 把 .mscx 拆成 { staffId, measures[] }。
 *
 * 层级（已实测）：
 *   <Score>
 *     <Part id="1">            ← 乐器定义（缩进 4）
 *       <Staff id="1">         ← 定义用的 Staff（缩进 6）
 *     </Part>
 *     <Staff id="1">           ← 音乐（缩进 4）★ 只取这些
 *       <Measure>…</Measure>
 *     </Staff>
 *   </Score>
 *
 * ⚠️ 踩过的坑：**开闭标签的缩进不一致。**
 *     实测这台机器上导出的文件：
 *       L101    4 空格  <Staff id="1">    ← 开
 *       L2152   6 空格  </Staff>          ← 闭（多两格！）
 *     所以不能靠 </Staff> 定位。这里改成**按开标签的位置切段** ——
 *     找到每个音乐 Staff 的开标签，段尾就是下一个开标签（或 </Score>）。
 *     不依赖任何闭合标签的格式。
 */
export function parseScore(xml) {
  const partEnd = xml.indexOf('</Part>')
  if (partEnd < 0) throw new Error('解析失败：找不到 </Part>，可能不是 MuseScore 原生格式')

  const scoreEnd = xml.lastIndexOf('</Score>')
  const music = xml.slice(partEnd, scoreEnd > partEnd ? scoreEnd : undefined)

  // 收集所有「缩进 4 的 <Staff id=…>」开标签位置
  const openRe = /\n {4}<Staff id="(\d+)">/g
  const marks = []
  let m
  while ((m = openRe.exec(music))) {
    marks.push({ id: m[1], start: m.index + m[0].length })
  }
  if (marks.length === 0) throw new Error('解析失败：没找到任何音乐谱表')

  // 段尾 = 下一个开标签的位置（最后一段到末尾）
  marks.forEach((mark, i) => {
    mark.end = i + 1 < marks.length ? marks[i + 1].start : music.length
  })

  return marks.map((mark) => ({
    id: mark.id,
    measures: splitMeasures(music.slice(mark.start, mark.end)),
  }))
}

function splitMeasures(body) {
  const out = []
  const re = /<Measure[^>]*>([\s\S]*?)<\/Measure>/g
  let m
  while ((m = re.exec(body))) out.push(m[1])
  return out
}

/**
 * 返回每个小节的**字符区间**（相对整份 XML）。
 *
 * 这是给别的工具用的：要「只把改动的小节拿去渲染」，就得能精确定位它们，
 * 然后把其余小节剔掉。渲染和 diff 共用同一套定位逻辑，两边才不会错位。
 *
 * 返回 [{ staff, index (1-based), start, end }]
 */
export function measureSpans(xml) {
  const partEnd = xml.indexOf('</Part>')
  if (partEnd < 0) throw new Error('解析失败：找不到 </Part>')
  const scoreEnd = xml.lastIndexOf('</Score>')
  const base = partEnd
  const music = xml.slice(partEnd, scoreEnd > partEnd ? scoreEnd : undefined)

  const openRe = /\n {4}<Staff id="(\d+)">/g
  const marks = []
  let m
  while ((m = openRe.exec(music))) marks.push({ id: m[1], start: m.index + m[0].length })
  marks.forEach((mark, i) => {
    mark.end = i + 1 < marks.length ? marks[i + 1].start : music.length
  })

  const spans = []
  for (const mark of marks) {
    const segment = music.slice(mark.start, mark.end)
    const re = /<Measure[^>]*>[\s\S]*?<\/Measure>/g
    let mm
    let idx = 0
    while ((mm = re.exec(segment))) {
      idx++
      spans.push({
        staff: mark.id,
        index: idx,
        start: base + mark.start + mm.index,
        end: base + mark.start + mm.index + mm[0].length,
        text: mm[0],
      })
    }
  }
  return spans
}

/** 逐行比较两个小节，返回差异（只保留有意义的变化）。 */
function diffMeasure(a, b) {
  const la = a.split('\n').map((s) => s.trim()).filter(Boolean)
  const lb = b.split('\n').map((s) => s.trim()).filter(Boolean)

  // 用最长公共子序列太贵；这里用简单的集合差 + 顺序保留。
  // 目标不是完美 diff，是「人能看懂的差异摘要」。
  const setA = new Map()
  for (const line of la) setA.set(line, (setA.get(line) ?? 0) + 1)
  const setB = new Map()
  for (const line of lb) setB.set(line, (setB.get(line) ?? 0) + 1)

  const removed = []
  const added = []
  for (const [line, n] of setA) {
    const diff = n - (setB.get(line) ?? 0)
    for (let i = 0; i < diff; i++) removed.push(line)
  }
  for (const [line, n] of setB) {
    const diff = n - (setA.get(line) ?? 0)
    for (let i = 0; i < diff; i++) added.push(line)
  }
  return { removed, added }
}

/** 比较两份乐谱，返回按小节组织的改动清单。 */
export function scoreDiff(baseXml, headXml) {
  const a = parseScore(baseXml)
  const b = parseScore(headXml)

  const staffIds = [...new Set([...a.map((s) => s.id), ...b.map((s) => s.id)])].sort(
    (x, y) => Number(x) - Number(y),
  )

  const changes = []
  const notes = []

  for (const id of staffIds) {
    const sa = a.find((s) => s.id === id)
    const sb = b.find((s) => s.id === id)

    if (!sa) {
      notes.push(`谱表 ${id}：新增`)
      continue
    }
    if (!sb) {
      notes.push(`谱表 ${id}：删除`)
      continue
    }
    if (sa.measures.length !== sb.measures.length) {
      notes.push(`谱表 ${id}：小节数变化 ${sa.measures.length} → ${sb.measures.length}`)
    }

    const n = Math.min(sa.measures.length, sb.measures.length)
    for (let i = 0; i < n; i++) {
      if (sa.measures[i] === sb.measures[i]) continue
      const d = diffMeasure(sa.measures[i], sb.measures[i])
      if (d.removed.length === 0 && d.added.length === 0) continue
      changes.push({ staff: id, measure: i + 1, removed: d.removed, added: d.added })
    }
  }
  return { changes, notes, staffCount: staffIds.length }
}

/** 渲染成人读的文本（就是 CI 会贴进 PR 的那段）。 */
export function renderText(result, baseName = 'base', headName = 'head') {
  const lines = []
  lines.push(`乐谱 diff　${baseName} → ${headName}`)
  lines.push('')

  if (result.changes.length === 0 && result.notes.length === 0) {
    lines.push('  没有差异。')
    return lines.join('\n')
  }

  for (const n of result.notes) lines.push(`  · ${n}`)
  if (result.notes.length) lines.push('')

  for (const c of result.changes) {
    lines.push(`小节 ${c.measure}（谱表 ${c.staff}）`)
    for (const l of c.removed) lines.push(`  - ${l}`)
    for (const l of c.added) lines.push(`  + ${l}`)
    lines.push('')
  }

  const measures = new Set(result.changes.map((c) => `${c.staff}:${c.measure}`)).size
  lines.push('─'.repeat(40))
  lines.push(`改动：${measures} 个小节，${result.changes.length} 处`)
  return lines.join('\n')
}

// ── CLI ───────────────────────────────────────────────────────────
if (process.argv[1] && import.meta.url === `file://${process.argv[1]}`) {
  const args = process.argv.slice(2)
  const json = args.includes('--json')
  const [basePath, headPath] = args.filter((a) => !a.startsWith('--'))

  if (!basePath || !headPath) {
    console.error('用法: node scripts/score-diff.mjs <基准.mscx> <提交.mscx> [--json]')
    process.exit(1)
  }

  const result = scoreDiff(readFileSync(basePath, 'utf8'), readFileSync(headPath, 'utf8'))

  if (json) {
    console.log(JSON.stringify(result, null, 2))
  } else {
    console.log(renderText(result, basename(basePath), basename(headPath)))
  }
}
