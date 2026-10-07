// compare.mjs —— 把两个版本的差异做成「乐谱对照」
//
// 【为什么不用文字 diff】
//
// 文字 diff 是给程序员看的。审一份扒谱要判断的是「这一处对不对」，
// 而乐谱的差异用乐谱表达最直接：两个版本上下对齐，同一拍落在同一水平位置，
// 差异自己就跳出来了，不用加任何标记、也不用读数字。
//
// 【为什么要按「连续段」分组】
//
// 最初的实现是把**所有**改动的小节筛出来拼成一份对照谱。实测发现三个问题：
//
//   ① 非连续的小节被首尾拼在一起 —— 改的是 5,6,7,8, 20,21,22, 40,41，
//      拼出来读起来像一段连贯的音乐，**这是误导**。
//   ② 分页会把"上原版 / 下改后"的对应关系劈开，跨页之后就断了。
//   ③ 显示名只在第一个系统用全名，后续系统退化成简称（原来给的简称是
//      "A"/"B"，第二页起就看不懂哪个是哪个）。
//
// 改成按连续段切，四件事一起解决：
//   每段内部连续（符合音乐阅读习惯）、每张图都很短（一页装得下）、
//   标签带上小节范围（不会有歧义）、改动多的时候是一列小图而不是一张长图。
//
// 用法：
//   node scripts/compare.mjs <原版.mscx> <改后.mscx> <输出目录>
//        [--labels 原版,改后] [--max-per-run 8] [--max-runs 6]

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { scoreDiff, filterMeasures } from './score-diff.mjs'
import { mergeVersions, dissect } from './merge-versions.mjs'
import { highlightScorePair, COLORS } from './highlight.mjs'

/**
 * 默认：一个连续段最多渲染多少小节。
 *
 * 实测：一首中等密度的钢琴曲，**一个系统只能放约 3 个小节**。
 * 段太长会让「上原版 / 下改后」跨系统被切开（配对仍然正确，只是要跨行看）。
 * 所以取 4 —— 稍微宽松一点，大多数情况仍是单系统；要更严可以传 --max-per-run 3。
 */
export const DEFAULT_MAX_PER_RUN = 4
/** 默认：最多渲染多少个段（再多就只给前几个 + 一句说明）。 */
export const DEFAULT_MAX_RUNS = 6

/**
 * 把改动的小节按「连续段」切分，过长的段再切开。
 *
 * [5,6,7,8,20,21,22,40,41] → [[5,6,7,8],[20,21,22],[40,41]]
 * [1..20]（连续 20 小节）   → [[1..8],[9..16],[17..20]]
 *
 * @param {number[]} measures 已排序的小节序号
 * @param {number} maxPerRun 单段上限
 */
export function groupRuns(measures, maxPerRun = DEFAULT_MAX_PER_RUN) {
  const sorted = [...new Set(measures.map(Number))].sort((a, b) => a - b)
  if (sorted.length === 0) return []

  // 先按连续性切
  const runs = []
  let cur = [sorted[0]]
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] === sorted[i - 1] + 1) cur.push(sorted[i])
    else {
      runs.push(cur)
      cur = [sorted[i]]
    }
  }
  runs.push(cur)

  // 再把过长的段切开
  const limit = Math.max(1, Number(maxPerRun) || DEFAULT_MAX_PER_RUN)
  const out = []
  for (const run of runs) {
    for (let i = 0; i < run.length; i += limit) out.push(run.slice(i, i + limit))
  }
  return out
}

/**
 * 生成对照。
 *
 * @returns {{
 *   items: Array<{from:number,to:number,measures:number[],xml:string,label:string}>,
 *   changed: number[], runCount: number, truncated: boolean, diff: object
 * }}
 */
export function buildComparisons(baseXml, headXml, opts = {}) {
  const maxPerRun = opts.maxPerRun ?? DEFAULT_MAX_PER_RUN
  const maxRuns = opts.maxRuns ?? DEFAULT_MAX_RUNS
  const labelA = opts.labelA ?? '原版'
  const labelB = opts.labelB ?? '改后'
  const shortA = opts.shortA ?? '原'
  const shortB = opts.shortB ?? '改'

  const result = scoreDiff(baseXml, headXml)

  // 哪些小节变了（按序号去重 —— 差异可能只落在某个谱表上）
  const changed = [...new Set(result.changes.map((c) => Number(c.measure)))].sort((a, b) => a - b)
  const runs = groupRuns(changed, maxPerRun)

  const shown = runs.slice(0, Math.max(1, maxRuns))
  const items = []
  for (const run of shown) {
    const from = run[0]
    const to = run[run.length - 1]
    const range = from === to ? `${from}` : `${from}–${to}`

    // 先筛出这一段，再染色，最后摞起来。
    // 顺序不能反：染色会改变 XML 长度，先染后筛会让小节偏移量失效。
    const a0 = filterMeasures(baseXml, run)
    const b0 = filterMeasures(headXml, run)

    let a = a0
    let b = b0
    let marked = 0
    if (opts.color !== false) {
      const hl = highlightScorePair(a0, b0, opts.colors ?? COLORS)
      a = hl.a
      b = hl.b
      marked = hl.changedMeasures.length
    }

    // 标签带上小节范围 —— 每张图自己说清楚它是哪一段，
    // 不用回去翻 PR 描述。
    const xml = mergeVersions(a, b, {
      labelA: `${labelA} ${range}`,
      labelB: `${labelB} ${range}`,
      shortA,
      shortB,
    })
    items.push({ from, to, measures: run, xml, label: `第 ${range} 小节`, marked })
  }

  return {
    items,
    changed,
    runCount: runs.length,
    truncated: runs.length > shown.length,
    diff: result,
  }
}

// ── CLI ───────────────────────────────────────────────────────────
if (process.argv[1] && import.meta.url === `file://${process.argv[1]}`) {
  const argv = process.argv.slice(2)
  const opt = (name) => {
    const i = argv.indexOf(name)
    return i >= 0 && argv[i + 1] ? argv[i + 1] : undefined
  }
  const labels = (opt('--labels') ?? '').split(',').filter(Boolean)
  const maxPerRun = Number(opt('--max-per-run') ?? DEFAULT_MAX_PER_RUN)
  const maxRuns = Number(opt('--max-runs') ?? DEFAULT_MAX_RUNS)

  // ⚠️ 定位参数要排除掉选项后面那个值，否则 --labels a,b 的 "a,b" 会被当成输入文件
  const consumed = new Set()
  for (const name of ['--labels', '--max-per-run', '--max-runs']) {
    const i = argv.indexOf(name)
    if (i >= 0) consumed.add(i).add(i + 1)
  }
  const positional = argv.filter((a, i) => !a.startsWith('--') && !consumed.has(i))
  const [basePath, headPath, outDir] = positional

  if (!basePath || !headPath || !outDir) {
    console.error(
      '用法: node scripts/compare.mjs <原版.mscx> <改后.mscx> <输出目录> [--labels 原版,改后] [--max-per-run 8] [--max-runs 6]',
    )
    process.exit(1)
  }

  const { items, changed, runCount, truncated } = buildComparisons(
    readFileSync(basePath, 'utf8'),
    readFileSync(headPath, 'utf8'),
    {
      maxPerRun,
      maxRuns,
      ...(labels.length === 2 ? { labelA: labels[0], labelB: labels[1] } : {}),
    },
  )

  if (changed.length === 0) {
    console.log('  两个版本没有差异，不生成对照。')
    process.exit(0)
  }

  mkdirSync(outDir, { recursive: true })
  console.log(`  改动 ${changed.length} 个小节：${changed.join(', ')}`)
  console.log(`  切出 ${runCount} 个连续段：`)
  items.forEach((it, i) => {
    const file = join(outDir, `compare-${i + 1}.mscx`)
    writeFileSync(file, it.xml, 'utf8')
    const d = dissect(it.xml)
    console.log(
      `    ${i + 1}. ${it.label.padEnd(18)} ${d.measureCount} 小节 / ${d.staffIds.length} 谱表 / ${Buffer.byteLength(it.xml)} B → ${file}`,
    )
  })
  if (truncated) {
    console.log(`  ⚠️ 共 ${runCount} 段，只渲染了前 ${items.length} 段（--max-runs ${maxRuns}）`)
  }
}
