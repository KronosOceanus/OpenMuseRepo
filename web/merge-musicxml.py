#!/usr/bin/env python3
"""
把两份 MusicXML 合成一份（两个版本各占一组 part）。

【为什么在 MusicXML 层合并，而不是 .mscx】

原来的做法是先把两份 .mscx 合并（merge-versions.mjs），再用 MuseScore
转成 MusicXML。声部一多就崩 —— 实测 11 个声部的曲子合并后 22 个 part，
MuseScore **直接段错误**（退出码 139），转不出文件。

而在 MusicXML 层合并只是拼接 <part> 元素，压根不经过 MuseScore，
也就没有那个问题。而且 AlphaTab 读的就是 MusicXML，少一次转换。

【合并后长什么样】

    A 的 11 个 part  +  B 的 11 个 part  =  22 个 part

    part 0..N-1   基准版
    part N..2N-1  对比版

AlphaTab 会把每个系统里所有 track 的谱表**上下排列**，所以结果是
「原版一组谱表在上、改后一组在下」的摞叠视图。

⚠️ part 的 id 必须改名，否则两边的 P1/P2… 会撞。
   同时给 part-name 加前缀（原 / 改），谱面上才分得清。

用法：
    python3 merge-musicxml.py A.musicxml B.musicxml 输出.musicxml [标签A] [标签B]
"""

import os
import sys
import xml.etree.ElementTree as ET

# 标签前缀。取得短一点 —— 它会印在谱面上每一行的开头。
PRE_A = '原'
PRE_B = '改'


def strip_ns(tag):
    """去掉可能的命名空间前缀。"""
    return tag.split('}')[-1] if '}' in tag else tag


def rename_part_ids(root_b, suffix):
    """把 B 文件里所有 part 的 id 加上后缀，避免和 A 撞。

    MusicXML 里 part 的 id 只被两处引用：
        <score-part id="P1">     声明
        <part id="P1">           正文
    其他 id（score-instrument / midi-instrument）只在自己那个
    score-part 内部引用，不用全局改名。
    """
    pl = root_b.find('part-list')
    mapping = {}
    if pl is not None:
        for sp in pl.findall('score-part'):
            old = sp.get('id')
            if old is None:
                continue
            new = old + suffix
            mapping[old] = new
            sp.set('id', new)
    for p in root_b.findall('part'):
        old = p.get('id')
        if old in mapping:
            p.set('id', mapping[old])
    return mapping


def prefix_names(root, prefix):
    """给每个 part 的显示名加前缀，谱面上能分清是哪个版本。"""
    pl = root.find('part-list')
    if pl is None:
        return
    for sp in pl.findall('score-part'):
        for tag in ('part-name', 'part-abbreviation'):
            el = sp.find(tag)
            if el is not None and el.text:
                el.text = prefix + el.text
            elif el is not None:
                el.text = prefix


def merge(path_a, path_b, out_path, label_a=None, label_b=None):
    pa, pb = PRE_A, PRE_B
    if label_a:
        pa = label_a
    if label_b:
        pb = label_b

    root_a = ET.parse(path_a).getroot()
    root_b = ET.parse(path_b).getroot()

    if strip_ns(root_a.tag) != 'score-partwise' or strip_ns(root_b.tag) != 'score-partwise':
        raise SystemExit('  ❌ 只支持 <score-partwise> 格式的 MusicXML')

    na = len(root_a.findall('part'))
    nb = len(root_b.findall('part'))
    if na != nb:
        print(f'  ⚠️ 两个文件声部数不同：{na} vs {nb}（仍会合并，但 diff 对不齐）')

    # ⚠️ id 要改名，否则两边都有 P1 会撞
    rename_part_ids(root_b, '_B')
    prefix_names(root_a, pa)
    prefix_names(root_b, pb)

    # 把 B 的 <score-part> 追加到 A 的 <part-list>
    pl_a = root_a.find('part-list')
    pl_b = root_b.find('part-list')
    if pl_a is None or pl_b is None:
        raise SystemExit('  ❌ 找不到 <part-list>')
    for sp in list(pl_b.findall('score-part')):
        pl_a.append(sp)

    # 把 B 的 <part> 追加到 A 的根
    for p in list(root_b.findall('part')):
        root_a.append(p)

    ET.ElementTree(root_a).write(out_path, encoding='utf-8', xml_declaration=True)
    return na, nb


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    a, b, out = sys.argv[1], sys.argv[2], sys.argv[3]
    la = sys.argv[4] if len(sys.argv) > 4 else None
    lb = sys.argv[5] if len(sys.argv) > 5 else None

    for f in (a, b):
        if not os.path.isfile(f):
            raise SystemExit(f'  ❌ 找不到 {f}')

    na, nb = merge(a, b, out, la, lb)

    size = os.path.getsize(out)
    print(f'  ✅ 合并 {na} + {nb} = {na + nb} 个 part')
    print(f'     {os.path.basename(out)}  {size // 1024} KB')
    print()
    print(f'  谱面上的声部名：{la or PRE_A}xxx / {lb or PRE_B}xxx')
    print(f'  part 0..{na - 1} = 基准版    part {na}..{na + nb - 1} = 对比版')


if __name__ == '__main__':
    main()
