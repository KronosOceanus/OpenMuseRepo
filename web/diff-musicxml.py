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


def measure_notes(measure_el, divisions):
    """把一个小节里的发声音符取出来，带小节内的 tick 位置。

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
                out.append({'pitch': m, 'onset': onset})
        elif tag == 'backup':
            pos -= int(float(el.findtext('duration') or 0))
        elif tag == 'forward':
            pos += int(float(el.findtext('duration') or 0))

    d = divisions or 1
    for n in out:
        n['tick'] = int(round(n['onset'] / d * TICKS_PER_QUARTER))
        n['name'] = midi_to_name(n['pitch'])
    return out


def diff_notes(a, b):
    """a 里有、b 里没有的音（按「音高 + 位置」配对，按重数算）。

    先按 (pitch, tick) 精确配对，配不上的再按 pitch 配一遍 ——
    这样即使两边的 division 换算有一点点出入，也不会漏掉整处改动。
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

    # 第二轮：只看音高（位置换算可能有偏差时兜底）
    still = []
    for n in out:
        for i, r in enumerate(remaining):
            if r['pitch'] == n['pitch']:
                remaining.pop(i)
                break
        else:
            still.append(n)

    return still


def part_display_names(root):
    """从 <part-list> 读每个 part 的显示名。"""
    names = {}
    pl = root.find('part-list')
    if pl is not None:
        for sp in pl.findall('score-part'):
            names[sp.get('id')] = sp.findtext('part-name') or sp.get('id')
    return names


def build_diff(path_a, path_b=None):
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
        if len(pa) != len(pb):
            raise SystemExit(
                f'  ❌ 两个文件声部数不同：{len(pa)} vs {len(pb)}\n'
                f'     逐 part 对齐要求声部数一致。'
            )

        na = part_display_names(root_a)
        nb = part_display_names(root_b)
        # ⚠️ 这里**不能**用 pa[0] 的名字当整份文件的标签。
        #    多乐器谱里那只是第一件乐器（比如「小号（Bb）」），
        #    结果左右两栏的标题都变成「小号（Bb）」，看着像少了一栏。
        base_name = '原版'
        head_name = '改后'
        src = os.path.basename(path_a) + ' ↔ ' + os.path.basename(path_b)

        items = []
        total_common = 0
        truncated = False
        for ti in range(len(pa)):
            ma_i = pa[ti].findall('measure')
            mb_i = pb[ti].findall('measure')
            common_i = min(len(ma_i), len(mb_i))
            total_common = max(total_common, common_i)
            if len(ma_i) != len(mb_i):
                truncated = True
            didx = 1
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
                    'track': ti,
                    'trackName': na.get(pa[ti].get('id'), 'P' + str(ti + 1)),
                    'removed': pack2(removed),
                    'added': pack2(added),
                })

        items.sort(key=lambda x: (x['index'], x['track']))
        return {
            'base': base_name,
            'head': head_name,
            'source': src,
            'parts': len(pa),
            'measureCount': total_common,
            'truncated': truncated,
            'diffCount': len(items),
            'measures': items,
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
    if not d['measures']:
        L.append('  两个版本完全一致。')
        return '\n'.join(L)

    for it in d['measures']:
        tag = f'（{it["trackName"]}）' if it.get('trackName') else ''
        L.append(f'  第 {it["number"]} 小节{tag}')
        if it['removed']:
            L.append('    − 红　' + '、'.join(x['name'] for x in it['removed']))
        if it['added']:
            L.append('    + 绿　' + '、'.join(x['name'] for x in it['added']))
        L.append('')
    L.append(f'  共 {d["diffCount"]} 个小节有差异（全谱 {d["measureCount"]} 小节）')
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('musicxml', help='A 的 MusicXML；若给第二个参数则比两份文件')
    ap.add_argument('musicxml_b', nargs='?', default=None, help='B 的 MusicXML（可选）')
    ap.add_argument('-o', '--out', default=None)
    ap.add_argument('--text', action='store_true', help='只打印，不写文件')
    args = ap.parse_args()

    if not os.path.isfile(args.musicxml):
        raise SystemExit(f'  ❌ 找不到 {args.musicxml}')
    if args.musicxml_b and not os.path.isfile(args.musicxml_b):
        raise SystemExit(f'  ❌ 找不到 {args.musicxml_b}')

    d = build_diff(args.musicxml, args.musicxml_b)

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
