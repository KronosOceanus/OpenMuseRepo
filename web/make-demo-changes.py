#!/usr/bin/env python3
"""
给一份 MusicXML 造演示用的改动，产出「改后」版本。

【为什么直接改 MusicXML，不改 .mscx】

① .mscx 存的是**记谱音高**，MusicXML 导出的是**实际音高**。
   移调乐器（Bb 小号等）两者差若干个半音 —— 实测 .mscx 里的 G4/D#5
   导出后是 A4/F5（+2）。在 .mscx 上下手，改出来的和预期不是一回事。

② 而 AlphaTab 读的就是 MusicXML。直接改它，所见即所得，
   也省掉一次 MuseScore 转换（那一步在多声部时还会段错误）。

【三种改动，轮流施加】

真实的扒谱差异不只是「音高听错」，更常见的是**漏音和多音**。
所以这里三种轮着来：

    改音高   把一个音换成别的音高（改错音）
    删音     把一个音变成等时值休止符（漏扒）
    加音     把一个休止符变成音（多扒）

三种都**不改变小节总时值** —— 两边小节保持对齐，
差异只体现在音符本身。

【位置怎么挑】

· 只挑「有 ≥3 个音」的小节（多乐器编配里很多小节是整小节休止）
· **轮转各个声部** —— 不然可能整首都在改钢琴，别的声部一次都没测到
· 三种改动轮流施加（这一处做不了就顺延到下一种）
· 移调量在音域内（越界就反向）

用法：
    python3 make-demo-changes.py 输入.musicxml 输出.musicxml [位置数]
"""

import sys
import xml.etree.ElementTree as ET

STEP = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
SPELL = {
    0: ('C', 0), 1: ('C', 1), 2: ('D', 0), 3: ('D', 1), 4: ('E', 0), 5: ('F', 0),
    6: ('F', 1), 7: ('G', 0), 8: ('G', 1), 9: ('A', 0), 10: ('A', 1), 11: ('B', 0),
}
SHIFTS = [2, -3, 12, -5, 7, -12, 3, -2, 5, -7, 10, -10]
KINDS = ['pitch', 'delete', 'add']


def nm(p):
    return STEP[p % 12] + str(p // 12 - 1)


def midi_of(note):
    p = note.find('pitch')
    if p is None:
        return None
    return (int(p.findtext('octave')) + 1) * 12 + STEP.index(p.findtext('step')) + \
        int(float(p.findtext('alter') or 0))


def set_pitch(note, midi):
    """给一个 note 设音高（把休止符变成音，或改已有音）。"""
    p = note.find('pitch')
    if p is None:
        r = note.find('rest')
        if r is not None:
            note.remove(r)
        p = ET.Element('pitch')
        idx = 0
        for i, ch in enumerate(list(note)):
            if ch.tag in ('duration', 'tie', 'instrument', 'voice', 'type'):
                idx = i
                break
        note.insert(idx, p)
        ET.SubElement(p, 'step')
        ET.SubElement(p, 'octave')
    step, alter = SPELL[midi % 12]
    p.find('step').text = step
    a = p.find('alter')
    if alter:
        if a is None:
            a = ET.Element('alter')
            oc = p.find('octave')
            p.insert(list(p).index(oc) if oc is not None else len(p), a)
        a.text = str(alter)
    elif a is not None:
        p.remove(a)
    oc = p.find('octave')
    if oc is None:
        oc = ET.SubElement(p, 'octave')
    oc.text = str(midi // 12 - 1)
    return True


def to_rest(note):
    """把一个音变成等时值休止符（漏扒）。保留 duration/voice/type。"""
    p = note.find('pitch')
    if p is None:
        return False
    note.remove(p)
    u = note.find('unpitched')
    if u is not None:
        note.remove(u)
    idx = 0
    for i, ch in enumerate(list(note)):
        if ch.tag in ('duration', 'tie', 'instrument', 'voice', 'type'):
            idx = i
            break
    note.insert(idx, ET.Element('rest'))
    for t in note.findall('tie'):
        note.remove(t)
    return True


def pitched(measure):
    return [n for n in measure.findall('note')
            if n.find('rest') is None and n.find('pitch') is not None
            and n.find('chord') is None]


def rests_can_add(measure):
    """可以变音符的休止符（排除整小节休止）。"""
    out = []
    for n in measure.findall('note'):
        if n.find('rest') is None:
            continue
        if n.get('print-object') == 'no':
            continue
        if not n.findtext('duration'):
            continue
        out.append(n)
    return out


def main():
    src, dst = sys.argv[1], sys.argv[2]
    wanted = int(sys.argv[3]) if len(sys.argv) > 3 else 9

    tree = ET.parse(src)
    root = tree.getroot()
    parts = root.findall('part')
    pl = root.find('part-list')
    pname = ({sp.get('id'): (sp.findtext('part-name') or '').strip()
              for sp in pl.findall('score-part')} if pl is not None else {})

    cand = []
    for pi, p in enumerate(parts):
        for mi, m in enumerate(p.findall('measure')):
            if len(pitched(m)) >= 3:
                cand.append((pi, mi))
    if not cand:
        raise SystemExit('  ❌ 没找到任何有 ≥3 个音的小节')

    # 轮转声部：按声部归组，依次各取一个
    by_part = {}
    for pi, mi in cand:
        by_part.setdefault(pi, []).append(mi)

    picks = []
    idxs = {k: 0 for k in by_part}
    order = sorted(by_part)
    while len(picks) < wanted:
        progressed = False
        for k in order:
            if len(picks) >= wanted:
                break
            lst = by_part[k]
            if idxs[k] >= len(lst):
                continue
            step = max(1, len(lst) // max(1, (wanted // max(1, len(order))) + 1))
            j = min(len(lst) - 1, idxs[k] * step)
            picks.append((k, lst[j]))
            idxs[k] += 1
            progressed = True
        if not progressed:
            break

    print(f'  {src.split("/")[-1]}：{len(parts)} 个 part，'
          f'{sum(len(p.findall("measure")) for p in parts)} 个小节（合计）')
    print(f'  挑中 {len(picks)} 处（改音高 / 删音 / 加音 轮流，轮转声部）：')
    print()

    changes = []
    k = 0
    for pi, mi in picks:
        part = parts[pi]
        label = pname.get(part.get('id'), f'part{pi}')
        m = part.findall('measure')[mi]
        notes = pitched(m)
        kind = KINDS[k % len(KINDS)]
        desc = None

        if kind == 'pitch' and notes:
            i = min(2, len(notes) - 1)
            old = midi_of(notes[i]); sh = SHIFTS[k % len(SHIFTS)]; new = old + sh
            if not (36 <= new <= 96):
                new = old - sh
            if new != old:
                set_pitch(notes[i], new)
                desc = f'改音高　{nm(old)} → {nm(new)}'

        elif kind == 'delete' and len(notes) >= 2:
            old = midi_of(notes[1])
            if to_rest(notes[1]):
                desc = f'删音　{nm(old)} → 休止符'

        elif kind == 'add':
            rs = rests_can_add(m)
            if rs and notes:
                base = midi_of(notes[0])
                new = max(36, min(96, base - 5))
                set_pitch(rs[0], new)
                desc = f'加音　休止符 → {nm(new)}'

        # 轮到的种类做不了 → 顺延到别的种类
        if desc is None:
            for alt in KINDS:
                if alt == kind:
                    continue
                if alt == 'pitch' and notes:
                    i = min(1, len(notes) - 1)
                    old = midi_of(notes[i]); sh = SHIFTS[k % len(SHIFTS)]; new = old + sh
                    if not (36 <= new <= 96):
                        new = old - sh
                    if new != old:
                        set_pitch(notes[i], new)
                        desc = f'改音高(顺延)　{nm(old)} → {nm(new)}'
                        break
                if alt == 'delete' and len(notes) >= 2:
                    old = midi_of(notes[1])
                    if to_rest(notes[1]):
                        desc = f'删音(顺延)　{nm(old)} → 休止符'
                        break
                if alt == 'add':
                    rs = rests_can_add(m)
                    if rs and notes:
                        base = midi_of(notes[0])
                        new = max(36, min(96, base - 5))
                        set_pitch(rs[0], new)
                        desc = f'加音(顺延)　休止符 → {nm(new)}'
                        break

        if desc:
            # ⚠️ 记**实际**做的种类，不是原本轮到的那个。
            #    轮到的种类做不了会顺延（比如「加音」但那小节没有休止符），
            #    记 kind 会让汇总数字和实际不符（实测差过）。
            if desc.startswith('改音高'):
                real = 'pitch'
            elif desc.startswith('删音'):
                real = 'delete'
            else:
                real = 'add'
            changes.append({'part': pi, 'measure': mi, 'kind': real, 'want': kind})
            print(f'    part{pi:<2d} {label:<12s} 第 {mi + 1:>3d} 小节　{desc}')
        k += 1

    tree.write(dst, encoding='utf-8', xml_declaration=True)
    n_pitch = sum(1 for c in changes if c['kind'] == 'pitch')
    n_del = sum(1 for c in changes if c['kind'] == 'delete')
    n_add = sum(1 for c in changes if c['kind'] == 'add')
    print()
    print(f'  共改了 {len(changes)} 处：改音高 {n_pitch}　删音 {n_del}　加音 {n_add}')
    print(f'  ✅ 写出 {dst}')


if __name__ == '__main__':
    main()
