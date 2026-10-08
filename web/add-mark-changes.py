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


# 力度记号对应的 MIDI 力度（MuseScore 导出时会写 <sound dynamics>）
VELOCITY = {'ppp': 10, 'pp': 25, 'p': 40, 'mp': 60, 'mf': 75, 'f': 90, 'ff': 105, 'fff': 120}


def has_real_note(measure):
    """这一小节里有没有真的发声音符（不是整小节休止）。

    ⚠️ 注入力度/文字/速度这类**挂在音符上**的记号时，必须挑这种小节。
       实测 M0203：原来写死「第 5 小节」，而长笛那一小节是整小节休止 ——
       记号插进去了、差异清单也报得出来，但**页面上什么都不显示**，
       因为 AlphaTab 的力度是挂在音符上的，没有音符就没有落脚点。
       （原版小军鼓第 36 小节那处 pp 能显示，就因为后面跟着真音符。）
    """
    return any(n.find('rest') is None for n in measure.findall('note'))


def pick_measure(measures, prefer):
    """从 prefer 位置向两边找一个「有真音符」的小节下标。"""
    n = len(measures)
    for d in range(n):
        for i in (prefer + d, prefer - d):
            if 0 <= i < n and has_real_note(measures[i]):
                return i
    return prefer


def add_dynamic(measure, val):
    """加一个力度记号。

    ⚠️ **结构照抄 MuseScore 导出的形式**，不要图省事只写
       <direction-type><dynamics>。

       实测（M0203）：只写最简形式的话，差异清单里报得出「力度 无 → mf」，
       但**页面上看不到那个 mf**。MuseScore 导出的形式是这样的：

           <direction-type>
             <dynamics default-x="5.32" default-y="-40" relative-y="-40">
               <mp/>
             </dynamics>
           </direction-type>
           <sound dynamics="71.11"/>

       多出来的两部分 —— 定位属性和 <sound dynamics> —— 很可能就是
       AlphaTab 判断"这个记号要不要画"的依据。照抄它最稳。
    """
    d = ET.Element('direction', {'placement': 'below'})
    dt = ET.SubElement(d, 'direction-type')
    dyn = ET.SubElement(dt, 'dynamics',
                        {'default-x': '5', 'default-y': '-40', 'relative-y': '-40'})
    ET.SubElement(dyn, val)
    ET.SubElement(d, 'sound', {'dynamics': str(VELOCITY.get(val, 75))})
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


def add_wedge(measure, kind, stop_measure=None):
    """加一个渐强/渐弱**记号对**。

    ⚠️ 必须同时给 <wedge type="stop"/>。
       只写起点的话，那个记号会**一直延伸到曲末** ——
       实测右边通篇都在渐强，用户一眼就看出来了。
       （MusicXML 里渐强渐弱是一对：crescendo/diminuendo 开始，stop 结束。）

    stop_measure 给 None 就不加停（调用方要自己保证有终点）。
    """
    d = ET.Element('direction', {'placement': 'below'})
    dt = ET.SubElement(d, 'direction-type')
    ET.SubElement(dt, 'wedge', {'type': kind})
    insert_before_first_note(measure, d)

    if stop_measure is not None:
        d2 = ET.Element('direction', {'placement': 'below'})
        dt2 = ET.SubElement(d2, 'direction-type')
        ET.SubElement(dt2, 'wedge', {'type': 'stop'})
        insert_before_first_note(stop_measure, d2)
        return True
    return False


def add_slur(meas_from, nth_from, meas_to, nth_to):
    """加一条连音线 —— **必须成对写**：起点 <slur type="start"/>，
    终点 <slur type="stop"/>。

    ⚠️⚠️ 只写起点的话，谱面上**什么都看不到**。
       实测用户反馈：「连音线 无→1，但谱面没看到哪变了，
       只有第一个音符有红绿框」—— 差异清单是对的、框也是对的，
       是注入的那个记号本身残了（MusicXML 里连音线是一对）。

       这和「渐强只写 crescendo 不写 stop」是同一类错，
       那次的表现是"右边通篇都在渐强"。**凡是一对的记号都要成对写。**

    返回 True 表示两边都写上了。
    """
    def put(m, nth, kind):
        notes = [n for n in m.findall('note') if n.find('rest') is None]
        if not notes:
            return False
        n = notes[min(nth, len(notes) - 1)]
        nt = n.find('notations')
        if nt is None:
            nt = ET.SubElement(n, 'notations')
        ET.SubElement(nt, 'slur', {'type': kind, 'number': '1'})
        return True

    return put(meas_from, nth_from, 'start') and put(meas_to, nth_to, 'stop')


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
        # ⚠️ 这里**故意不处理** slur —— 连音线必须成对写（start + stop）。
        #    用 add_slur(a, i, b, j)。见它的注释。
        return False
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
    # ⚠️ 必须挑「那个声部真的在演奏」的小节 —— 记号是挂在音符上的。
    #    写死 measures[4] 的话，遇到整小节休止就白插了。
    # ⚠️ 挑点要**依次往后推**，不然遇到"前面一大段都休止"的声部时，
    #    五处记号会全部挤在同一个（第一个有音符的）小节里。
    i_dyn = pick_measure(measures, 4)
    add_dynamic(measures[i_dyn], 'mf'); plan.append(f'第 {i_dyn + 1} 小节　加力度 mf')

    i_wrd = pick_measure(measures, max(11, i_dyn + 4))
    add_words(measures[i_wrd], 'dolce'); plan.append(f'第 {i_wrd + 1} 小节　加文字 dolce')

    i_tmp = pick_measure(measures, max(17, i_wrd + 4))
    add_tempo(measures[i_tmp], 'quarter', 96); plan.append(f'第 {i_tmp + 1} 小节　改速度 quarter=96')
    # 渐强放第 23 小节起、第 27 小节结束。
    # ⚠️ 结束位置要**按曲子长度自适应** —— 写死 measures[26] 的话，
    #    短曲子（24 小节的 Dreamy / 世界献礼）会整个跳过、一处都不加。
    # ⚠️ 渐强需要**两个**有真音符的小节（起点 + 终点）。
    #    只在"挑一个最近的小节"上做文章是不够的 —— 实测 kyoutsuu 的
    #    part0（小号）整曲只有 3 个有音符的小节（5、13、21），
    #    起止都落到 21 上，于是判断不通过、整个渐强被跳过。
    #    ⟹ 直接从「有音符的小节」列表里取相邻两个，隔多远都行。
    n_meas = len(measures)
    sounding = [i for i, mm in enumerate(measures) if has_real_note(mm)]
    if len(sounding) >= 2:
        want = max(i_tmp + 3, 22 if n_meas > 27 else max(2, n_meas // 3))
        k = min(range(len(sounding)), key=lambda j: abs(sounding[j] - want))
        a = sounding[k]
        b = sounding[k + 1] if k + 1 < len(sounding) else sounding[k - 1]
        if a > b:
            a, b = b, a
        add_wedge(measures[a], 'crescendo', measures[b])
        plan.append(f'第 {a + 1}-{b + 1} 小节　加渐强（含结束）')
    # 连音线：挑一个**至少有三个发声音符**的小节，把第 1 个连到第 3 个
    # ⚠️ 必须成对 —— 原来只写起点，谱面上画不出来（见 add_slur 注释）
    i_sl = None
    for i in range(max(i_tmp + 2, 1), len(measures)):
        if len([n for n in measures[i].findall('note') if n.find('rest') is None]) >= 3:
            i_sl = i
            break
    if i_sl is not None and add_slur(measures[i_sl], 0, measures[i_sl], 2):
        plan.append(f'第 {i_sl + 1} 小节　加连音线（第 1→3 个音，含终点）')

    i_st = pick_measure(measures, max(b + 4, 30))
    if add_notation(measures[i_st], 'staccato', 0):
        add_notation(measures[i_st], 'staccato', 1)
        plan.append(f'第 {i_st + 1} 小节　加 2 个跳音')
    i_ac = pick_measure(measures, i_st + 4)
    if add_notation(measures[i_ac], 'accent'):
        plan.append(f'第 {i_ac + 1} 小节　加重音')

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
