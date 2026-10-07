// highlight.mjs —— 把「改动过的音符」染色，让差异在谱面上直接看见
//
// 【为什么需要它】
//
// 对照谱让两个版本上下对齐，差异"能看出来"——但那要靠人逐音比对。
// 染色把这一步也省掉：改掉的音在**原版**里标红，在**改后**里标绿，
// 眼睛直接跳到该看的地方。
//
// 【写法是怎么确定的（实测）】
//
// MuseScore 的 XML 里，音符颜色写成元素内的一个 <color> 子元素：
//
//   <Note>
//     <eid/>
//     <color r="255" g="0" b="0" a="255"/>     ← 放在这里
//     <pitch>71</pitch>
//     <tpc>19</tpc>
//   </Note>
//
// 四种候选位置的渲染结果：
//   跟在 <eid/> 后     ✅ 变红
//   跟在 <pitch> 后    ✅ 变红（与上者逐字节相同）
//   放 <Note> 开头     ✅ 变红
//   大写 <Color>       ❌ 无效（样式文件里用大写，但元素属性用的小写）
//
// 【对齐方式】
//
// 按「事件序号」对齐：一个 <Measure> 里的事件序列是 Chord / Rest。
// 比较第 i 个事件的音高集合，不同就标记为改动。
// 这对「改错了一个音」这种主要场景是准的；如果插入/删除了整拍，
// 从插入点往后都会标成改动 —— 偏保守，但不会漏。

// 对齐靠 measureSpans（小节字符区间），和 diff / 渲染共用同一套定位逻辑。
import { measureSpans } from './score-diff.mjs'

/** 颜色。a=255 是不透明。 */
export const COLORS = {
  removed: { r: 255, g: 0, b: 0 }, // 原版里被改掉的
  added: { r: 0, g: 150, b: 0 }, // 改后里新出现的
}

/** 生成一个 <color> 元素。 */
export function colorTag({ r, g, b }, a = 255) {
  return `<color r="${r}" g="${g}" b="${b}" a="${a}"/>`
}

/**
 * 把一节里的「事件」切出来。
 * 事件 = <Chord>…</Chord> 或 <Rest>…</Rest>，按出现顺序。
 */
export function splitEvents(measureXml) {
  const events = []
  const re = /<(Chord|Rest)(?:\s[^>]*)?>[\s\S]*?<\/\1>/g
  let m
  while ((m = re.exec(measureXml))) {
    events.push({
      kind: m[1],
      text: m[0],
      start: m.index,
      end: m.index + m[0].length,
      pitches: [...m[0].matchAll(/<pitch>(\d+)<\/pitch>/g)].map((x) => Number(x[1])),
    })
  }
  return events
}

/**
 * 把一个事件里的音符染色。
 *
 * 逐个 <Note> 处理：只给「音高确实不同」的那些染色 ——
 * 整个和弦一起变色会掩盖"只有其中一个音错了"这件事。
 *
 * @param eventXml  事件原文
 * @param colorTag  <color …/> 字符串
 * @param onlyPitches 只染这些音高（undefined = 全染）
 */
export function colorNotes(eventXml, tag, onlyPitches) {
  const want = onlyPitches ? new Set(onlyPitches.map(Number)) : null
  return eventXml.replace(/<Note(?:\s[^>]*)?>[\s\S]*?<\/Note>/g, (note) => {
    const p = /<pitch>(\d+)<\/pitch>/.exec(note)
    if (want && !(p && want.has(Number(p[1])))) return note
    return insertColor(note, tag)
  })
}

/** 把 <color> 插进一个元素里 —— 紧跟在 <eid…> 之后，没有 <eid> 就放开头。 */
export function insertColor(elementXml, tag) {
  const eid = /<eid(?:\s[^>]*)?\/?>/.exec(elementXml)
  if (eid) {
    const at = eid.index + eid[0].length
    return elementXml.slice(0, at) + tag + elementXml.slice(at)
  }
  return elementXml.replace(/^(\s*<[A-Za-z]+(?:\s[^>]*)?>)/, `$1${tag}`)
}

/**
 * 比较两节，把改动过的音符分别染色。
 *
 * @returns {{ a: string, b: string, changed: number }} 染色后的两节 + 改动事件数
 */
export function highlightMeasurePair(measureA, measureB, colors = COLORS) {
  const ea = splitEvents(measureA)
  const eb = splitEvents(measureB)
  const tagRemoved = colorTag(colors.removed)
  const tagAdded = colorTag(colors.added)

  const n = Math.min(ea.length, eb.length)
  let changed = 0

  // 从后往前替换，避免偏移量失效
  const patchesA = []
  const patchesB = []

  for (let i = 0; i < n; i++) {
    const A = ea[i]
    const B = eb[i]
    if (A.kind !== B.kind) {
      // 和弦变休止（或反过来）—— 整块染
      patchesA.push({ ...A, text: A.kind === 'Rest' ? insertColor(A.text, tagRemoved) : colorNotes(A.text, tagRemoved) })
      patchesB.push({ ...B, text: B.kind === 'Rest' ? insertColor(B.text, tagAdded) : colorNotes(B.text, tagAdded) })
      changed++
      continue
    }
    if (A.pitches.join(',') === B.pitches.join(',')) continue

    // 只染音高不同的那些音符
    const onlyA = diffPitches(A.pitches, B.pitches)
    const onlyB = diffPitches(B.pitches, A.pitches)
    patchesA.push({
      ...A,
      text: A.kind === 'Rest' ? insertColor(A.text, tagRemoved) : colorNotes(A.text, tagRemoved, onlyA.length ? onlyA : undefined),
    })
    patchesB.push({
      ...B,
      text: B.kind === 'Rest' ? insertColor(B.text, tagAdded) : colorNotes(B.text, tagAdded, onlyB.length ? onlyB : undefined),
    })
    changed++
  }

  // 一方比另一方长：多的那些事件也算改动
  for (let i = n; i < ea.length; i++) {
    const A = ea[i]
    patchesA.push({ ...A, text: A.kind === 'Rest' ? insertColor(A.text, tagRemoved) : colorNotes(A.text, tagRemoved) })
    changed++
  }
  for (let i = n; i < eb.length; i++) {
    const B = eb[i]
    patchesB.push({ ...B, text: B.kind === 'Rest' ? insertColor(B.text, tagAdded) : colorNotes(B.text, tagAdded) })
    changed++
  }

  const apply = (xml, patches) => {
    let out = xml
    for (const p of [...patches].sort((x, y) => y.start - x.start)) {
      out = out.slice(0, p.start) + p.text + out.slice(p.end)
    }
    return out
  }

  return { a: apply(measureA, patchesA), b: apply(measureB, patchesB), changed }
}

/** A 里有、B 里没有的音高（按重数算）。 */
function diffPitches(a, b) {
  const count = new Map()
  for (const p of b) count.set(p, (count.get(p) ?? 0) + 1)
  const out = []
  for (const p of a) {
    const c = count.get(p) ?? 0
    if (c > 0) count.set(p, c - 1)
    else out.push(p)
  }
  return out
}

/**
 * 对整份乐谱做染色：逐小节比较两个版本，改动处分别标红/标绿。
 *
 * 两个版本的小节数必须相同（同一首曲子的两个版本基本都满足）。
 *
 * @returns {{ a: string, b: string, changedMeasures: number[] }}
 */
export function highlightScorePair(xmlA, xmlB, colors = COLORS) {
  const spansA = measureSpans(xmlA)
  const spansB = measureSpans(xmlB)

  const byKey = (spans) => {
    const m = new Map()
    for (const s of spans) m.set(`${s.staff}:${s.index}`, s)
    return m
  }
  const mapB = byKey(spansB)

  const patchesA = []
  const patchesB = []
  const changedMeasures = []

  for (const sA of spansA) {
    const sB = mapB.get(`${sA.staff}:${sA.index}`)
    if (!sB) continue
    if (sA.text === sB.text) continue // 原文就一样，不用染色

    const { a, b, changed } = highlightMeasurePair(sA.text, sB.text, colors)
    if (changed === 0) continue
    patchesA.push({ start: sA.start, end: sA.end, text: a })
    patchesB.push({ start: sB.start, end: sB.end, text: b })
    if (!changedMeasures.includes(sA.index)) changedMeasures.push(sA.index)
  }

  const apply = (xml, patches) => {
    let out = xml
    for (const p of [...patches].sort((x, y) => y.start - x.start)) {
      out = out.slice(0, p.start) + p.text + out.slice(p.end)
    }
    return out
  }

  return { a: apply(xmlA, patchesA), b: apply(xmlB, patchesB), changedMeasures: changedMeasures.sort((x, y) => x - y) }
}
