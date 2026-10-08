#!/usr/bin/env python3
"""
比较一份「合并谱」里的两个版本，产出差异清单。

【两种输入都支持】

① 两份独立的 MusicXML（推荐，页面做左右分栏时用这个）
       diff-musicxml.py A.musicxml B.musicxml

② 一份「合并谱」—— 里面有 2 个 part，就地比这两组
       diff-musicxml.py merged.musicxml

为什么现在推荐 ①：
    合并谱要先把两个版本摞成一份（merge-versions.mjs）。
    声部一多，那份文件的结构就容易出问题 —— 实测 11 个声部的曲子
    合并后 22 个 part，MuseScore 直接段错误，转不出 MusicXML。
    左右分栏只需要各自的 MusicXML，压根不用合并。

【产出给谁用】

页面上的 AlphaTab 渲染合并谱，然后用 api.boundsLookup 取每个音符头的
坐标，在对应的音符上叠一层红/绿。所以这里要告诉它**哪些音符**要染色。

**用「音高 + 小节内位置」两个键一起匹配，不能只用音高。**
一个改动小节里经常有重复的音高（比如和弦里已经有一个 D5，改动后
又多一个 D5），只按音高匹配会把那个没变的也染上色。

位置的单位要换算：MusicXML 用 <divisions>（每四分音符多少 division），
AlphaTab 的 Beat.displayStart 用 midi ticks，而 960 ticks = 一个四分音符。
    tick = 小节内 onset / divisions * 960

【红绿的含义】（沿用 highlight.mjs 的约定）

    红 = 基准里有、改后没有  → 「这一版这里被改掉了」
    绿 = 改后有、基准里没有  → 「改成了这个」

音高从 B4 变成 D5，就会同时出现一条红（B4）和一条绿（D5）。

用法：
    python3 diff-musicxml.py merged.musicxml [-o diff.json]
    python3 diff-musicxml.py merged.musicxml --text     # 人类可读地打印
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

# 音名 → 半音数
STEP_SEMITONE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
SHARP_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

TICKS_PER_QUARTER = 960   # 和 AlphaTab 的 MidiUtils.QuarterTime 一致


def midi_to_name(m):
    """MIDI → 音名（科学音高记号法，C4 = 中央 C = 60）。"""
    return SHARP_NAMES[m % 12] + str(m // 12 - 1)


def note_pitch(note_el):
    """从一个 <note> 里取 MIDI 音高。休止符返回 None。"""
    if note_el.find('rest') is not None:
        return None
    p = note_el.find('pitch')
    if p is None:
        return None
    step = p.findtext('step')
    if not step or step not in STEP_SEMITONE:
        return None
    alter = int(float(p.findtext('alter') or 0))
    octave = int(p.findtext('octave') or 4)
    return (octave + 1) * 12 + STEP_SEMITONE[step] + alter


def measure_notes(measure_el, divisions, keep_el=False):
    """把一个小节里的发声音符取出来，带小节内的 tick 位置。

    keep_el=True 时每个条目里多带一个 `el`（原始 <note> 元素）——
    diff-marks.py 需要它来读这个音符挂的记号（跳音/重音/连音线…）。
    位置口径必须只有这一处实现：tick 的取整方式差一点就会全盘失配
    （见 README ⑲）。

    MusicXML 的时间轴是靠 <note>/<backup>/<forward> 的 <duration> 累加出来的：
        <note>     往前推进 duration
        <backup>   往回退 duration（多声部时用）
        <forward>  往前跳 duration（空拍）
        <chord/>   和上一个音同一时刻，不推进

    divisions = 每四分音符多少 division，用来换算成 AlphaTab 的 tick。
    """
    out = []
    pos = 0          # 当前小节内的位置（单位 division）
    last_onset = 0   # 上一个非和弦音的起点

    for el in measure_el:
        tag = el.tag
        if tag == 'note':
            dur = int(float(el.findtext('duration') or 0))
            if el.find('chord') is not None:
                onset = last_onset
            else:
                onset = pos
                last_onset = pos
                pos += dur
            m = note_pitch(el)
            if m is not None:
                e2 = {'pitch': m, 'onset': onset}
                if keep_el:
                    e2['el'] = el
                out.append(e2)
        elif tag == 'backup':
            pos -= int(float(el.findtext('duration') or 0))
        elif tag == 'forward':
            pos += int(float(el.findtext('duration') or 0))

    d = divisions or 1
    for n in out:
        # ⚠️ 必须和 AlphaTab 的算法一致：**整除**，不是四舍五入。
        #     实测 onset=144、divisions=56 → 144/56*960 = 2468.57
        #         round → 2469 （清单里写的）
        #         整除 → 2468 （AlphaTab 的 displayStart 给的）
        #     差 1 个 tick 的后果：页面上「音高 + 位置精确匹配」全部失手，
        #     只能落到兜底匹配 —— 实测因此漏掉了一处绿框。
        n['tick'] = (n['onset'] * TICKS_PER_QUARTER) // d
        n['name'] = midi_to_name(n['pitch'])
    return out


# AlphaTab 的 tick：960 = 一个四分音符。
# 容差取 1/32 音符 —— 只吸收换算的舍入误差，**不吸收真正的位移**。
TICK_TOL = 30


def diff_notes(a, b):
    """a 里有、b 里没有的音（按「音高 + 位置」配对，按重数算）。

    两轮匹配：
      第一轮  音高 + 位置都要对得上
      第二轮  音高相同，且**位置差在容差内**才配对

    ⚠️ 第二轮原来写的是「只按音高」—— 那会把**移动了位置的音**当成
    「没变」，于是：

        原版 第5小节   C5@1拍  C#5@2拍  D5@3拍
        改后 第5小节   D5@1拍  C#5@2拍  B4@3拍
                                              （真实改动是 2 处：C5→D5、D5→B4）

    旧逻辑：原版的 D5@3拍 和改后的 D5@1拍 音高相同 → 配对成"没变"，
            于是只报「删 C5、加 B4」—— 少报一处，而且红框和绿框
            落在了**不同的拍**上（一个第1拍、一个第3拍），
            看着像"标记乱标"，其实是清单就报错了。

    加上位置容差之后：真正的位移会被报成「删原音 + 加新音」，
    两边标在**同一拍**上。
    """
    remaining = list(b)
    out = []

    # 第一轮：音高 + 位置都要对得上
    for n in a:
        for i, r in enumerate(remaining):
            if r['pitch'] == n['pitch'] and r['tick'] == n['tick']:
                remaining.pop(i)
                break
        else:
            out.append(n)

    # 第二轮：音高相同，位置差在容差内（取最接近的那个）
    still = []
    for n in out:
        best, best_d = -1, TICK_TOL + 1
        for i, r in enumerate(remaining):
            if r['pitch'] != n['pitch']:
                continue
            d = abs(r['tick'] - n['tick'])
            if d < best_d:
                best_d, best = d, i
        if best >= 0:
            remaining.pop(best)
        else:
            still.append(n)

    return still


def count_pitched(part_el):
    """这个声部整曲有多少个**实际发声**的音（休止符和后缀和弦音不算）。"""
    n = 0
    for m in part_el.findall('measure'):
        for x in m.findall('note'):
            if x.find('rest') is not None:
                continue
            if x.find('chord') is not None:
                continue          # 和弦里除第一个音之外的
            n += 1
    return n


def part_display_names(root):
    """从 <part-list> 读每个 part 的显示名。"""
    names = {}
    pl = root.find('part-list')
    if pl is not None:
        for sp in pl.findall('score-part'):
            names[sp.get('id')] = sp.findtext('part-name') or sp.get('id')
    return names


def build_diff(path_a, path_b=None, label_a=None, label_b=None):
    """比两个版本。path_b 省略时，path_a 必须是含 2 个 part 的合并谱。"""
    root_a = ET.parse(path_a).getroot()

    if path_b is None:
        # 合并谱模式
        parts = root_a.findall('part')
        if len(parts) != 2:
            raise SystemExit(
                f'  ❌ {os.path.basename(path_a)} 里有 {len(parts)} 个 part。\n'
                f'     要么给两个文件（A.musicxml B.musicxml），\n'
                f'     要么给一份含 2 个 part 的合并谱。'
            )
        names = part_display_names(root_a)
        base_name = names.get(parts[0].get('id'), '基准')
        head_name = names.get(parts[1].get('id'), '对比')
        ma = parts[0].findall('measure')
        mb = parts[1].findall('measure')
        src = os.path.basename(path_a)
    else:
        # ── 两个独立文件模式：**逐 part 比**
        #
        # ⚠️ 不能只比 parts[0]。一份多乐器谱有十几个 part，
        #    改动可能落在任何一件乐器上 —— 只比第一个 part 会漏掉绝大部分。
        #    （实测：11 个 part 的谱子改了 6 个谱表，只比 part0 时只报出 1 处）
        #
        # 每个 <part> 在 AlphaTab 里就是一个 track，索引一一对应，
        # 所以结果里带上 track 编号，页面按它上色。
        root_b = ET.parse(path_b).getroot()
        pa = root_a.findall('part')
        pb = root_b.findall('part')
        if not pa or not pb:
            raise SystemExit('  ❌ 有文件里找不到 <part>')
        na = part_display_names(root_a)
        nb = part_display_names(root_b)
        # ⚠️ 这里**不能**用 pa[0] 的名字当整份文件的标签。
        #    多乐器谱里那只是第一件乐器（比如「小号（Bb）」），
        #    结果左右两栏的标题都变成「小号（Bb）」，看着像少了一栏。
        base_name = label_a or '原版'
        head_name = label_b or '改后'
        src = os.path.basename(path_a) + ' ↔ ' + os.path.basename(path_b)

        # ── 声部按【名字】配对，不按下标 ──────────────────────────
        #
        # 下标配对要求两个文件声部数一致、顺序也一致。实测同一首曲子的
        # 不同编配版本根本不满足 —— 例：moonlight melody 的三个版本是
        # 14 / 4 / 1 个 part，而它们共有的双簧管 / 单簧管 / 大管在文件的
        # 第 7、8、9 位 vs 第 0、1、2 位。按下标比会拿双簧管去比长笛。
        #
        # 所以按 <part-name> 配对。名字对不上的声部就跳过，并记下来。
        #
        # ⚠️⚠️ **重名必须按顺序一一配对，不能只取第一个。**
        #
        #    合奏谱里「乐队小提琴」出现两次、「圆号 1/2」之类非常常见。
        #    原来用 setdefault(nm, i) 只记第一个 —— 第二个**静默消失**，
        #    既不比较、也不出现在 unmatched 里，报告只说「配上 7 个」。
        #    实测 世界献礼：两个「乐队小提琴」共 81 个音，其中 47 个
        #    从来没被比过，而用户收不到任何提示。
        from collections import defaultdict
        ga, gb = defaultdict(list), defaultdict(list)
        for i, pp in enumerate(pa):
            nm = na.get(pp.get('id'), '').strip()
            if nm:
                ga[nm].append(i)
        for i, pp in enumerate(pb):
            nm = nb.get(pp.get('id'), '').strip()
            if nm:
                gb[nm].append(i)

        matched = []
        dup_warn = []          # 同名数量不一致
        for nm in ga:
            if nm not in gb:
                continue
            la, lb = ga[nm], gb[nm]
            if len(la) != len(lb):
                dup_warn.append({'name': nm, 'countA': len(la), 'countB': len(lb)})
            for k in range(min(len(la), len(lb))):
                # 重名时加序号后缀，免得差异清单里分不清是哪一个
                label = nm if len(la) == 1 and len(lb) == 1 else f'{nm} #{k + 1}'
                matched.append((label, la[k], lb[k]))
        matched.sort(key=lambda x: x[1])
        unmatched_a = sorted(n for n in ga if n not in gb)
        unmatched_b = sorted(n for n in gb if n not in ga)

        if not matched:
            raise SystemExit(
                '  ❌ 两个文件里没有一个声部的名字对得上，无法配对。\n'
                f'     文件A：{", ".join(sorted(idx_a_by_name)[:6])}…\n'
                f'     文件B：{", ".join(sorted(idx_b_by_name)[:6])}…'
            )

        items = []
        total_common = 0
        truncated = False
        missing = []          # 整声部空缺
        for nm, ia, ib in matched:
            # ── 整声部空缺检测 ────────────────────────────────────
            #
            # 扒谱场景里很常见：**某个声部压根没扒**（谱表留着、内容全休止）。
            # 这时逐音符比会报出成百条「新增」，用户会读成
            # 「改了这么多地方」，实际是"这一侧根本没扒"。
            #
            # 实测 moonlight：双簧管 A 侧 0 个音、B 侧 63 个 —— 逐音符比
            # 就是 63 条噪音，把真正的差异埋掉了。
            #
            # 判据只取**确凿的零**：一侧 0、另一侧有内容。
            # 「接近 0」不做硬判 —— 那是我替用户下结论；数量会照常
            # 出现在报告里，由人判断。
            nA, nB = count_pitched(pa[ia]), count_pitched(pb[ib])
            if nA == 0 and nB == 0:
                continue                    # 两边都没内容，没什么可比的
            if nA == 0 or nB == 0:
                missing.append({
                    'name': nm,
                    'trackA': ia, 'trackB': ib,
                    'notesA': nA, 'notesB': nB,
                    'emptySide': 'A' if nA == 0 else 'B',
                })
                continue                    # 不比了 —— 比出来全是噪音

            ma_i = pa[ia].findall('measure')
            mb_i = pb[ib].findall('measure')
            common_i = min(len(ma_i), len(mb_i))
            total_common = max(total_common, common_i)
            if len(ma_i) != len(mb_i):
                truncated = True
            div_a = div_b = 1
            for i in range(common_i):
                da = ma_i[i].findtext('attributes/divisions')
                if da:
                    div_a = int(da)
                db = mb_i[i].findtext('attributes/divisions')
                if db:
                    div_b = int(db)
                na_notes = measure_notes(ma_i[i], div_a)
                nb_notes = measure_notes(mb_i[i], div_b)
                if [x['pitch'] for x in na_notes] == [x['pitch'] for x in nb_notes]:
                    continue
                removed = diff_notes(na_notes, nb_notes)
                added = diff_notes(nb_notes, na_notes)
                if not removed and not added:
                    continue

                def pack2(lst):
                    return [
                        {'pitch': x['pitch'], 'name': x['name'], 'tick': x['tick']}
                        for x in sorted(lst, key=lambda y: (y['tick'], y['pitch']))
                    ]

                items.append({
                    'index': i,
                    'number': ma_i[i].get('number', str(i + 1)),
                    'trackA': ia,          # 左边（基准）里的声部下标
                    'trackB': ib,          # 右边（对比）里的声部下标
                    'trackName': nm,
                    'removed': pack2(removed),
                    'added': pack2(added),
                })

        items.sort(key=lambda x: (x['index'], x['trackA']))
        return {
            'base': base_name,
            'head': head_name,
            'source': src,
            'partsA': len(pa),
            'partsB': len(pb),
            'parts': len(pa),              # 兼容旧字段
            'matched': [{'name': n, 'trackA': a, 'trackB': b} for n, a, b in matched],
            'unmatchedA': unmatched_a,
            'unmatchedB': unmatched_b,
            # 同名数量不一致（比如一边两个「乐队小提琴」、一边一个）
            'dupWarn': dup_warn,
            'measureCount': total_common,
            'truncated': truncated,
            'diffCount': len(items),
            'measures': items,
            # 整声部空缺（一侧整曲无内容）—— 单独列出来，不混进逐音符差异
            'missingParts': missing,
            'missingCount': len(missing),
        }
    common = min(len(ma), len(mb))

    # ⚠️ divisions 要**跨小节沿用**，不能每小节取一次默认 1。
    #
    # MusicXML 里 <divisions> 是"从此往后有效"的属性，通常只在第 1 小节
    # 声明一次。后面小节没有这个元素 —— 直接 findtext 会拿到 None，
    # 退化成 1，tick 就全错（实测算出 17280 而不是 1440）。
    div_a = 1
    div_b = 1

    items = []
    for i in range(common):
        da = ma[i].findtext('attributes/divisions')
        if da:
            div_a = int(da)
        db = mb[i].findtext('attributes/divisions')
        if db:
            div_b = int(db)

        na = measure_notes(ma[i], div_a)
        nb = measure_notes(mb[i], div_b)
        if [n['pitch'] for n in na] == [n['pitch'] for n in nb]:
            continue

        removed = diff_notes(na, nb)
        added = diff_notes(nb, na)
        if not removed and not added:
            continue

        def pack(lst):
            return [
                {'pitch': n['pitch'], 'name': n['name'], 'tick': n['tick']}
                for n in sorted(lst, key=lambda x: (x['tick'], x['pitch']))
            ]

        items.append({
            'index': i,                                        # 0 基，给 AlphaTab 找小节
            'number': ma[i].get('number', str(i + 1)),          # 谱上印的号码，给人看
            'removed': pack(removed),                          # 在基准谱表上标红
            'added': pack(added),                              # 在对比谱表上标绿
        })

    return {
        'base': base_name,
        'head': head_name,
        'source': src,
        'measureCount': common,
        'truncated': len(ma) != len(mb),
        'diffCount': len(items),
        'measures': items,
    }


def render_text(d):
    L = []
    L.append(f'  合并谱差异　{d["base"]} → {d["head"]}')
    L.append('')
    if d['truncated']:
        L.append(f'  ⚠️ 两个版本小节数不同，只比了公共的 {d["measureCount"]} 小节')
        L.append('')

    # ⚠️ 判断"完全一致"要看**三样**：音符差异、记号差异、整声部空缺。
    #    漏掉任何一个都会误报「完全一致」—— 这个错在本项目犯过两次
    #    （先漏 marks，这次又漏 missingParts）。
    if not d['measures'] and not d.get('missingParts'):
        L.append('  两个版本完全一致。')
        return '\n'.join(L)

    if d.get('missingParts'):
        L.append('  ── 整声部空缺（一侧整曲无内容，可能没扒）──')
        L.append('')
        for m in d['missingParts']:
            have = m['notesB'] if m['emptySide'] == 'A' else m['notesA']
            L.append(f'  {m["name"]}：{m["emptySide"]} 侧整曲无内容，'
                     f'另一侧 {have} 个音')
            L.append(f'      ⟹ 不逐音符比较（否则会报 {have} 处假差异）')
        L.append('')

    if d.get('dupWarn'):
        L.append('  ⚠️ 同名声部数量不一致（只配了较少的那一侧）：')
        for w in d['dupWarn']:
            L.append(f'     {w["name"]}：左 {w["countA"]} 个，右 {w["countB"]} 个')
        L.append('')

    for it in d['measures']:
        tag = f'（{it["trackName"]}）' if it.get('trackName') else ''
        L.append(f'  第 {it["number"]} 小节{tag}')
        if it['removed']:
            L.append('    − 红　' + '、'.join(x['name'] for x in it['removed']))
        if it['added']:
            L.append('    + 绿　' + '、'.join(x['name'] for x in it['added']))
        L.append('')

    L.append(f'  共 {d["diffCount"]} 个小节有音符差异（全谱 {d["measureCount"]} 小节）'
             + (f'，另 {d["missingCount"]} 个声部整曲空缺' if d.get('missingCount') else ''))
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('musicxml', help='A 的 MusicXML；若给第二个参数则比两份文件')
    ap.add_argument('musicxml_b', nargs='?', default=None, help='B 的 MusicXML（可选）')
    ap.add_argument('-o', '--out', default=None)
    ap.add_argument('--label-a', default=None, help='左侧标签（默认「原版」）')
    ap.add_argument('--label-b', default=None, help='右侧标签（默认「改后」）')
    ap.add_argument('--text', action='store_true', help='只打印，不写文件')
    args = ap.parse_args()

    if not os.path.isfile(args.musicxml):
        raise SystemExit(f'  ❌ 找不到 {args.musicxml}')
    if args.musicxml_b and not os.path.isfile(args.musicxml_b):
        raise SystemExit(f'  ❌ 找不到 {args.musicxml_b}')

    d = build_diff(args.musicxml, args.musicxml_b, args.label_a, args.label_b)

    if args.text:
        print(render_text(d))
        return

    out = args.out or os.path.splitext(args.musicxml)[0] + '.diff.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write('\n')

    print(render_text(d))
    print()
    print(f'  ✅ 写出 {out}')


if __name__ == '__main__':
    main()
