#!/usr/bin/env python3
"""
把 MusicXML 里的速度记号统一成「四分音符 = N」。

【为什么需要这一步】

MuseScore 导出的速度记号是这样的（谱面上是「二分音符 = 80」）：

    <metronome>
      <beat-unit>half</beat-unit>      ← 二分音符
      <per-minute>80</per-minute>      ← 每分钟 80
    </metronome>
    ...
    <sound tempo="160"/>               ← 实际速度：四分音符 160

**这两处都是对的**：<metronome> 管谱面上印什么，<sound tempo> 管播放多快。
二分音符 80 == 四分音符 160，数学也对。

但 AlphaTab（1.8.4）有个 bug —— 见
https://github.com/CoderLine/alphaTab/issues/988

它读 <metronome> 时**忽略 <beat-unit>**，直接把 <per-minute> 当成四分音符 BPM。
于是「二分音符 = 80」被播成「四分音符 = 80」—— **慢了一倍**。

【这个脚本做什么】

把所有非四分音符的 metronome 记号换算成等价的四分音符版本：

    二分音符 80   →  四分音符 160
    全音符 20     →  四分音符 80
    八分音符 120  →  四分音符 60
    附点二分音符 60 → 四分音符 180      （附点 = ×1.5）

语义完全等价，但绕开了那个 bug。<sound tempo> 不动 —— 它本来就是四分音符 BPM。

用法：
    python3 fix-tempo.py <文件.musicxml> [...]      # 原地修改
    python3 fix-tempo.py --dry pieces/*.musicxml    # 只看会改什么
"""

import os
import re
import sys

# 每种 beat-unit 等于几个四分音符
FACTOR = {
    'long': 16, 'breve': 8, 'whole': 4, 'half': 2,
    'quarter': 1,
    'eighth': 0.5, '16th': 0.25, '32nd': 0.125, '64th': 0.0625,
    '128th': 0.03125, '256th': 0.015625,
}

METRONOME_RE = re.compile(r'<metronome\b[^>]*>([\s\S]*?)</metronome>')


def fix_metronome_inner(inner):
    """把一个 <metronome> 的内容改成四分音符版本。返回 (新内容, 说明) 或 (None, None)。"""
    m_unit = re.search(r'<beat-unit>([^<]+)</beat-unit>', inner)
    m_per = re.search(r'<per-minute>([^<]+)</per-minute>', inner)
    if not m_unit or not m_per:
        return None, None

    unit = m_unit.group(1).strip()
    try:
        per = float(m_per.group(1))
    except ValueError:
        return None, None

    if unit == 'quarter' and '<beat-unit-dot' not in inner:
        return None, None  # 本来就是四分音符，不用动

    factor = FACTOR.get(unit)

    # 认不出的 beat-unit：别乱改，报出来
    if factor is None:
        return None, f'认不出的 beat-unit「{unit}」—— 跳过'

    dotted = '<beat-unit-dot' in inner
    if dotted:
        factor *= 1.5

    new_per = per * factor

    # 整数就别显示小数点
    txt = str(int(round(new_per))) if abs(new_per - round(new_per)) < 1e-9 else f'{new_per:g}'

    out = inner
    out = out.replace(m_unit.group(0), '<beat-unit>quarter</beat-unit>')
    out = out.replace(m_per.group(0), f'<per-minute>{txt}</per-minute>')
    # 附点去掉 —— 换成四分音符之后不能还带附点
    out = re.sub(r'<beat-unit-dot\s*/>', '', out)

    sign = f'{unit}{"·" if dotted else ""} = {m_per.group(1)}'
    return out, f'{sign}  →  四分音符 = {txt}'


def process(path, dry=False):
    with open(path, encoding='utf-8') as f:
        src = f.read()

    changes = []

    def repl(m):
        new_inner, note = fix_metronome_inner(m.group(1))
        if new_inner is None:
            if note:
                changes.append(('skip', note))
            return m.group(0)
        changes.append(('fix', note))
        return '<metronome' + m.group(0)[len('<metronome'):m.group(0).index('>') + 1] + new_inner + '</metronome>'

    out = METRONOME_RE.sub(repl, src)

    name = os.path.basename(path)
    if not changes:
        print(f'  {name}：没有需要改的速度记号')
        return 0

    print(f'  {name}：')
    for kind, note in changes:
        print(('    ⚠️ ' if kind == 'skip' else '    ✅ ') + note)

    if not dry and out != src:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(out)
        print(f'    → 已写入')
    elif dry:
        print(f'    → （dry run，未写入）')

    return sum(1 for k, _ in changes if k == 'fix')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dry = '--dry' in sys.argv

    if not args:
        print(__doc__)
        sys.exit(1)

    total = 0
    for p in args:
        if not os.path.isfile(p):
            print(f'  ❌ 找不到：{p}')
            continue
        total += process(p, dry)

    print()
    print(f'  改了 {total} 处速度记号' + ('（dry run）' if dry else ''))
    sys.exit(0 if total >= 0 else 1)


if __name__ == '__main__':
    main()
