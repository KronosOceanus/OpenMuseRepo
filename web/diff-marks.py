#!/usr/bin/env python3
"""
比两个 MusicXML 的**记号**差异（力度、速度、文字、连音线、跳音…）。

【为什么单独一个脚本】

`diff-musicxml.py` 只比音符。记号改动**完全不碰音符** ——
实测给一份谱注入 7 处记号改动（加力度、改速度、加连音线…），
音符序列一个字节都没变，于是 `diff-musicxml.py` 的结论是
「两个版本完全一致」。**这是误导** —— 用户会以为没问题。

所以记号单独一个脚本，先跑通、验证稳了再合进主管线。
好处是主管线（已经能用的那部分）完全不受影响。

【两类记号，两种比法】

① 方向类：速度、力度、文字、渐强渐弱、踏板、排练号
   ⚠️ 这类**常常只写在某一个声部上** —— 实测 moonlight 的速度记号
      A 版写在双簧管、B 版写在长笛。**分声部比会大量误报**
      「A 有速度、B 没有」。
   ⟹ 跨声部合并后**按小节比**。

② 音符挂载类：连音线、延音线、跳音、重音、延长号、装饰音、歌词、反复
   ⟹ 这些是声部自己的东西，**分声部比**是对的。

【不比什么】

排版类（页边距、行距、字体）—— 那是"怎么印"不是"音乐是什么"，
报了只是噪音。所以只看 <direction> / <notations> / <barline> / <lyric>。

用法：
    python3 diff-marks.py A.musicxml B.musicxml [--label-a X] [--label-b Y]
    python3 diff-marks.py A.musicxml B.musicxml --json out.json
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

LABEL = {
    'dynamics': '力度', 'words': '文字', 'tempo': '速度', 'wedge': '渐强渐弱',
    'pedal': '踏板', 'rehearsal': '排练号', 'lyrics': '歌词',
    'slur': '连音线', 'tied': '延音线', 'staccato': '跳音', 'accent': '重音',
    'strong-accent': '强重音', 'tenuto': '保持音', 'fermata': '延长号',
    'trill-mark': '颤音', 'mordent': '波音', 'turn': '回音',
    'arpeggiate': '琶音', 'glissando': '滑音', 'ornaments': '装饰音',
}


def part_names(root):
    pl = root.find('part-list')
    if pl is None:
        return {}
    return {sp.get('id'): (sp.findtext('part-name') or '').strip()
            for sp in pl.findall('score-part')}


def norm_name(n):
    return n


def direction_signature(measure):
    """方向类记号。不含位置。"""
    sig = {}
    dyn, words, tempo, wedge, pedal, rehearsal = [], [], [], [], [], []
    for d in measure.findall('direction'):
        for dt in d.findall('direction-type'):
            for child in dt:
                t = child.tag
                if t == 'dynamics':
                    dyn.extend(x.tag for x in child)
                elif t == 'words':
                    words.append((child.text or '').strip())
                elif t == 'metronome':
                    bu = child.findtext('beat-unit') or '?'
                    dot = '.' if child.find('beat-unit-dot') is not None else ''
                    pm = child.findtext('per-minute') or '?'
                    tempo.append(f'{bu}{dot}={pm}')
                elif t == 'wedge':
                    wedge.append(child.get('type') or '?')
                elif t == 'pedal':
                    pedal.append(child.get('type') or '?')
                elif t == 'rehearsal':
                    rehearsal.append((child.text or '').strip())
    if dyn: sig['dynamics'] = dyn
    if words: sig['words'] = words
    if tempo: sig['tempo'] = tempo
    if wedge: sig['wedge'] = wedge
    if pedal: sig['pedal'] = pedal
    if rehearsal: sig['rehearsal'] = rehearsal
    return sig


def notation_signature(measure):
    """音符挂载类记号 + 歌词 + 小节线。"""
    sig = {}
    cnt = {}
    for n in measure.findall('note'):
        for nt in n.findall('notations'):
            for child in nt:
                if child.tag in ('articulations', 'ornaments'):
                    # ⚠️ 这两个是**容器** —— 真正有意义的是里面的子元素
                    #    （<articulations><staccato/></articulations>）。
                    #    不展开的话报出来是 "articulations: 无 → 2"，
                    #    用户根本不知道改了什么。
                    for sub in child:
                        cnt[sub.tag] = cnt.get(sub.tag, 0) + 1
                elif child.tag in ('slur', 'tied'):
                    if child.get('type') in (None, 'start'):
                        cnt[child.tag] = cnt.get(child.tag, 0) + 1
                else:
                    cnt[child.tag] = cnt.get(child.tag, 0) + 1
        if n.find('grace') is not None:
            cnt['ornaments'] = cnt.get('ornaments', 0) + 1
        for ly in n.findall('lyric'):
            tx = ly.findtext('text')
            if tx:
                sig.setdefault('lyrics', []).append(tx.strip())
    if cnt:
        sig['notations'] = cnt
    for bl in measure.findall('barline'):
        for r in bl.findall('repeat'):
            sig.setdefault('barline', []).append(r.get('direction') or '?')
        for w in bl.findall('ending'):
            sig.setdefault('barline', []).append('ending:' + (w.get('number') or '?'))
    return sig


def merge_directions(parts_measures, mi):
    """第 mi 小节里**所有声部**的方向类记号，合并成一个签名。"""
    merged = {}
    for measures in parts_measures:
        if mi >= len(measures):
            continue
        for k, v in direction_signature(measures[mi]).items():
            b = merged.setdefault(k, [])
            for x in v:
                if x not in b:
                    b.append(x)
    return merged


def compare(sa, sb):
    out = []
    for k in sorted(set(sa) | set(sb)):
        va, vb = sa.get(k), sb.get(k)
        if va == vb:
            continue
        if k == 'notations':
            for kk in sorted(set(va or {}) | set(vb or {})):
                a = (va or {}).get(kk, 0)
                b = (vb or {}).get(kk, 0)
                if a != b:
                    out.append({'kind': LABEL.get(kk, kk), 'from': a or '无', 'to': b or '无'})
        else:
            out.append({'kind': LABEL.get(k, k),
                        'from': '、'.join(map(str, va)) if va else '无',
                        'to': '、'.join(map(str, vb)) if vb else '无'})
    return out


def build(path_a, path_b, la=None, lb=None):
    ra, rb = ET.parse(path_a).getroot(), ET.parse(path_b).getroot()
    na, nb = part_names(ra), part_names(rb)
    A, B = ra.findall('part'), rb.findall('part')

    ia, ib = {}, {}
    for i, p in enumerate(A):
        n = na.get(p.get('id'), '')
        if n:
            ia.setdefault(n, i)
    for i, p in enumerate(B):
        n = nb.get(p.get('id'), '')
        if n:
            ib.setdefault(n, i)

    matched = sorted((n, ia[n], ib[n]) for n in ia if n in ib)
    pa_ms = [p.findall('measure') for p in A]
    pb_ms = [p.findall('measure') for p in B]
    n = min(max((len(x) for x in pa_ms), default=0),
            max((len(x) for x in pb_ms), default=0))

    def number_of(i):
        for pms in (pa_ms, pb_ms):
            for ms in pms:
                if i < len(ms):
                    return ms[i].get('number', str(i + 1))
        return str(i + 1)

    # ① 方向类：跨声部合并，按小节
    global_items = []
    for i in range(n):
        d = compare(merge_directions(pa_ms, i), merge_directions(pb_ms, i))
        if d:
            global_items.append({'index': i, 'number': number_of(i), 'items': d})

    # ② 音符挂载类：分声部
    part_items = []
    for nm, i, j in matched:
        mas, mbs = pa_ms[i], pb_ms[j]
        for k in range(min(len(mas), len(mbs))):
            d = compare(notation_signature(mas[k]), notation_signature(mbs[k]))
            if d:
                part_items.append({'index': k, 'number': number_of(k), 'trackName': nm,
                                   'trackA': i, 'trackB': j, 'items': d})

    return {
        'base': la or '原版', 'head': lb or '改后',
        'source': os.path.basename(path_a) + ' ↔ ' + os.path.basename(path_b),
        'measureCount': n,
        'marks': global_items,          # 方向类（不分声部）
        'partMarks': part_items,        # 音符挂载类（分声部）
        'markCount': len(global_items) + len(part_items),
    }


def render_text(d):
    L = []
    L.append(f'  记号差异　{d["base"]} → {d["head"]}')
    L.append('')
    if not d['marks'] and not d['partMarks']:
        L.append('  没有记号差异。')
        return '\n'.join(L)

    if d['marks']:
        L.append('  ── 方向类（力度/速度/文字/渐强/踏板/排练号，不分声部）──')
        L.append('')
        for m in d['marks']:
            L.append(f'  第 {m["number"]} 小节')
            for k in m['items']:
                L.append(f'    · {k["kind"]}：{k["from"]} → {k["to"]}')
            L.append('')

    if d['partMarks']:
        L.append('  ── 音符挂载类（连音线/跳音/重音/歌词/反复，分声部）──')
        L.append('')
        for m in d['partMarks']:
            L.append(f'  第 {m["number"]} 小节（{m["trackName"]}）')
            for k in m['items']:
                L.append(f'    · {k["kind"]}：{k["from"]} → {k["to"]}')
            L.append('')

    L.append(f'  共 {len(d["marks"])} 个小节有方向类差异，'
             f'{len(d["partMarks"])} 个声部小节有挂载类差异')
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('musicxml')
    ap.add_argument('musicxml_b')
    ap.add_argument('--label-a', default=None)
    ap.add_argument('--label-b', default=None)
    ap.add_argument('--json', default=None, help='同时写出 JSON')
    args = ap.parse_args()

    for p in (args.musicxml, args.musicxml_b):
        if not os.path.isfile(p):
            raise SystemExit(f'  ❌ 找不到 {p}')

    d = build(args.musicxml, args.musicxml_b, args.label_a, args.label_b)
    print()
    print(render_text(d))
    print()
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
            f.write('\n')
        print(f'  ✅ 写出 {args.json}')
        print()


if __name__ == '__main__':
    main()
