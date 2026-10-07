// 自测：验证 score-diff 报出的小节号，真的是被改的那个小节
//
// 用法：node selftest.mjs [score.mscx] [小节号] [谱表id]
import { readFileSync, writeFileSync } from 'node:fs'
import { parseScore, scoreDiff, renderText, measureSpans } from './scripts/score-diff.mjs'

const SRC = process.argv[2] ?? 'pieces/神话2/score.mscx'
const TARGET_MEASURE = Number(process.argv[3] ?? 21)
const TARGET_STAFF = String(process.argv[4] ?? '1')

const xml = readFileSync(SRC, 'utf8')
let pass = 0
let fail = 0
const check = (ok, msg) => {
  console.log(`   ${ok ? '✅' : '❌'} ${msg}`)
  ok ? pass++ : fail++
}

// ── ① 同一文件自比 → 0 改动 ───────────────────────────────────────
console.log('① 自比（无改动）')
const self = scoreDiff(xml, xml)
check(self.changes.length === 0, `自比得到 ${self.changes.length} 处改动（应为 0）`)

// ── ② 定位目标小节，改一个音 ──────────────────────────────────────
// 指定的那一小节可能只有休止符（没有 <pitch>）。那样就往后找一个有的 ——
// 测试的目的是验证「diff 报的小节号 == 实际改的小节」，不是验证指定的小节。
console.log('\n② 精确修改')
const spans = measureSpans(xml)
const onStaff = spans.filter((s) => s.staff === TARGET_STAFF)
if (onStaff.length === 0) throw new Error(`谱表 ${TARGET_STAFF} 不存在（共 ${new Set(spans.map((s) => s.staff)).size} 个谱表）`)

let target = onStaff.find((s) => s.index === TARGET_MEASURE && /<pitch>/.test(s.text))
let shifted = false
if (!target) {
  target = onStaff.find((s) => /<pitch>/.test(s.text))
  shifted = true
}
if (!target) throw new Error(`谱表 ${TARGET_STAFF} 里没有任何带音高的小节`)

const actualMeasure = target.index
const pitchMatch = target.text.match(/<pitch>(\d+)<\/pitch>/)
const oldPitch = Number(pitchMatch[1])
const newPitch = oldPitch === 74 ? 99 : 74

const mutatedXml =
  xml.slice(0, target.start) +
  target.text.replace(pitchMatch[0], `<pitch>${newPitch}</pitch>`) +
  xml.slice(target.end)
writeFileSync('/tmp/om-mutated.mscx', mutatedXml, 'utf8')
check(
  true,
  `谱表${TARGET_STAFF} 第${actualMeasure}小节：<pitch>${oldPitch}</pitch> → <pitch>${newPitch}</pitch>` +
    (shifted ? `（第 ${TARGET_MEASURE} 小节只有休止符，自动往后找）` : ''),
)

// ── ③ diff 是否精确命中 ──────────────────────────────────────────
console.log('\n③ diff 结果')
const result = scoreDiff(xml, mutatedXml)
console.log()
console.log(renderText(result, '原地', '改后').split('\n').map((l) => '     ' + l).join('\n'))
console.log()

check(result.changes.length === 1, `报出 ${result.changes.length} 处改动（应为 1）`)
check(
  result.changes[0]?.measure === actualMeasure && String(result.changes[0]?.staff) === TARGET_STAFF,
  `报的小节 = 谱表${result.changes[0]?.staff} 第${result.changes[0]?.measure}小节（应为 谱表${TARGET_STAFF} 第${actualMeasure}小节）`,
)
check(
  result.changes[0]?.removed.some((l) => l.includes(`<pitch>${oldPitch}</pitch>`)) &&
    result.changes[0]?.added.some((l) => l.includes(`<pitch>${newPitch}</pitch>`)),
  'diff 文本精确指出是哪个 <pitch> 变了',
)

// ── ④ 结构完整性 ─────────────────────────────────────────────────
console.log('\n④ 结构')
const staves = parseScore(xml)
check(staves.length > 0, `解析出 ${staves.length} 个音乐谱表`)
check(
  staves.every((s) => s.measures.length > 0),
  `各谱表小节数：${staves.map((s) => `${s.id}=${s.measures.length}`).join(', ')}`,
)
check(spans.length === staves.reduce((n, s) => n + s.measures.length, 0), `measureSpans 覆盖全部小节（${spans.length}）`)

console.log(`\n   ${fail === 0 ? '全部通过' : `${fail} 项失败`}（${pass} 通过 / ${fail} 失败）`)
process.exit(fail === 0 ? 0 : 1)
