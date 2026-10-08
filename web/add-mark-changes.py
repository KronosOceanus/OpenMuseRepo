#!/usr/bin/env python3
"""
给一份 MusicXML 注入**记号类**改动（不动任何音符），用来测试记号检测。

记号改动比音符改动难测 —— 音符改动会改变音高序列，一眼能看出来；
记号改动**完全不碰音符**，所以：
  · 只看音高/时值的对比工具会认为"两个文件一样"
  · 必须显式扫 <direction> / <notations> / <barline> 才看得见

用法：
    python3 add-mark-changes.py 输入.musicxml 输出.musicxml
"""

import sys
import xml.etree.ElementTree as ET


def insert_before_first_note(measure, el):
    """把元素插到第一个 <note> 之前（MusicXML 要求 direction 在 note 前）。"""
    notes = measure.findall('note')
    if notes:
        idx = list(measure).index(notes[0])
        measure.insert(idx, el)
    else:
        measure.append(el)


def add_dynamic(measure, val):
    d = ET.Element('direction', {'placement': 'below'})
    dt = ET.SubElement(d, 'direction-type')
    dyn = ET.SubElement(dt, 'dynamics')
    ET.SubElement(dyn, val)
    insert_before_first_note(measure, d)


def add_words(measure, text):
    d = ET.Element('direction', {'placement': 'above'})
    dt = ET.SubElement(d, 'direction-type')
    w = ET.SubElement(dt, 'words')
    w.text = text
    insert_before_first_note(measure, d)


def add_tempo(measure, unit, bpm):
    d = ET.Element('direction', {'placement': 'above'})
    dt = ET.SubElement(d, 'direction-type')
    m = ET.SubElement(dt, 'metronome')
    ET.SubElement(m, 'beat-unit').text = unit
    ET.SubElement(m, 'per-minute').text = str(bpm)
    ET.SubElement(d, 'sound', {'tempo': str(bpm * (2 if unit == 'half' else 1))})
    insert_before_first_note(measure, d)


def add_wedge(measure, kind):
    d = ET.Element('direction', {'placement': 'below'})
    dt = ET.SubElement(d, 'direction-type')
    ET.SubElement(dt, 'wedge', {'type': kind})
    insert_before_first_note(measure, d)


def add_notation(measure, tag, nth=0):
    """给第 nth 个音加一个记号（slur / staccato / accent…）。"""
    notes = [n for n in measure.findall('note') if n.find('rest') is None]
    if not notes:
        return False
    n = notes[min(nth, len(notes) - 1)]
    nt = n.find('notations')
    if nt is None:
        nt = ET.SubElement(n, 'notations')
    if tag == 'slur':
        ET.SubElement(nt, 'slur', {'type': 'start', 'number': '1'})
    else:
        artic = nt.find('articulations')
        if artic is None:
            artic = ET.SubElement(nt, 'articulations')
        ET.SubElement(artic, tag)
    return True


def main():
    src, dst = sys.argv[1], sys.argv[2]
    tree = ET.parse(src)
    root = tree.getroot()
    measures = root.findall('part')[0].findall('measure')

    plan = []
    if len(measures) > 4:
        add_dynamic(measures[4], 'mf'); plan.append('第 5 小节　加力度 mf')
    if len(measures) > 11:
        add_words(measures[11], 'dolce'); plan.append('第 12 小节　加文字 dolce')
    if len(measures) > 17:
        add_tempo(measures[17], 'quarter', 96); plan.append('第 18 小节　改速度 quarter=96')
    if len(measures) > 22:
        add_wedge(measures[22], 'crescendo'); plan.append('第 23 小节　加渐强')
    if len(measures) > 26 and add_notation(measures[26], 'slur'):
        plan.append('第 27 小节　加连音线')
    if len(measures) > 30:
        add_notation(measures[30], 'staccato', 0)
        add_notation(measures[30], 'staccato', 1)
        plan.append('第 31 小节　加 2 个跳音')
    if len(measures) > 35 and add_notation(measures[35], 'accent'):
        plan.append('第 36 小节　加重音')

    tree.write(dst, encoding='utf-8', xml_declaration=True)

    print(f'  在 {src.split("/")[-1]} 上注入了 {len(plan)} 处**记号**改动：')
    print()
    for p in plan:
        print('    ' + p)
    print()
    print('  ⚠️ 这些改动**一个音符都没动** —— 只看音高的对比工具会认为两版一样。')
    print(f'  ✅ 写出 {dst}')


if __name__ == '__main__':
    main()
