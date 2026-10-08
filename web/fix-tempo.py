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
# 按 <direction> 整块处理 —— 这样能拿到同一块里的 <sound tempo>
DIRECTION_RE = re.compile(r'<direction\b[^>]*>[\s\S]*?</direction>')


def fix_metronome_inner(inner, sound_tempo=None):
    """把一个 <metronome> 的内容改成四分音符版本。返回 (新内容, 说明) 或 (None, None)。

    ⚠️ 优先用同一 <direction> 里的 <sound tempo>，而不是自己按 beat-unit 算。

        <sound tempo> 是 **MuseScore 自己播放时用的值**（它内部一律存四分音符 BPM，
        .mscx 里的 <tempo> × 60 就是它）。自己算只在没有 sound 时兜底。

        实测贝多芬第五：谱面标 half· = 108、<sound tempo=194>。
        自己算 → 108 × 3 = 324，和 MuseScore 的 194 **差得很多**
        （那份谱的显示标记和内部速度本身就矛盾，我不确定哪个对；
         但页面要和 MuseScore 播放一致，就该用 194）。
    """
    m_unit = re.search(r'<beat-unit>([^<]+)</beat-unit>', inner)
    m_per = re.search(r'<per-minute>([^<]+)</per-minute>', inner)
    if not m_unit or not m_per:
        return None, None

    unit = m_unit.group(1).strip()
    try:
        per = float(m_per.group(1))
    except ValueError:
        return None, None

    dotted = '<beat-unit-dot' in inner

    if unit == 'quarter' and not dotted and sound_tempo is None:
        return None, None  # 本来就是四分音符，不用动

    factor = FACTOR.get(unit)

    # 认不出的 beat-unit：别乱改，报出来
    if factor is None:
        return None, f'认不出的 beat-unit「{unit}」—— 跳过'

    if dotted:
        factor *= 1.5

    if sound_tempo is not None:
        new_per = float(sound_tempo)          # ← MuseScore 的权威值
        src_note = f'MuseScore 的 sound tempo={sound_tempo}'
    else:
        new_per = per * factor                # ← 没有 sound 时自己算
        src_note = f'自己算（{unit}{"·" if dotted else ""} × {factor:g}）'

    # 整数就别显示小数点
    txt = str(int(round(new_per))) if abs(new_per - round(new_per)) < 1e-9 else f'{new_per:g}'

    out = inner
    out = out.replace(m_unit.group(0), '<beat-unit>quarter</beat-unit>')
    out = out.replace(m_per.group(0), f'<per-minute>{txt}</per-minute>')
    # 附点去掉 —— 换成四分音符之后不能还带附点
    out = re.sub(r'<beat-unit-dot\s*/>', '', out)

    sign = f'{unit}{"·" if dotted else ""} = {m_per.group(1)}'
    return out, f'{sign}  →  四分音符 = {txt}　（{src_note}）'


def ensure_metronomes(src):
    """给每一处 <sound tempo> 补一个 <metronome> 记号。

    【为什么必须要这一步】

    AlphaTab 只读 <metronome>（谱面记号），**忽略 <sound tempo>**。
    谱子里如果只有个别地方有记号，整曲就会按那个速度播到底。

    实测贝多芬第五：MusicXML 里有 **36 处** <sound tempo>，
    但只有第 1 小节有 <metronome>。于是页面把整曲都当成 194 BPM ——
    而那段慢板实际是 25~50 BPM，**被播快了 4~8 倍**。
    （MuseScore 自己渲染 7 分 54 秒，页面按 194 播只要 5 分 10 秒。）

    ⚠️ <sound tempo> 有两种放法，都要管：

        ① 包在 <direction> 里（5 处 —— 这种通常带谱面记号）
        ② **直接挂在 <measure> 下**（31 处 —— 没有可视记号，最容易漏）
          <measure number="20">
            <sound tempo="140"/>
            <note .../>

    返回 (新内容, 补了几处)。
    """
    added = [0]

    # 先算出所有 <direction> 的范围，后面判断某个 <sound> 在不在里面
    dir_spans = [(m.start(), m.end(), '<metronome' in m.group(0))
                 for m in re.finditer(r'<direction\b[^>]*>[\s\S]*?</direction>', src)]

    def in_dir_with_metronome(pos):
        for a, b, has_met in dir_spans:
            if a <= pos < b:
                return has_met
        return False

    out = []
    last = 0
    for m in re.finditer(r'<sound\b[^>]*\btempo="([^"]+)"', src):
        pos = m.start()
        if in_dir_with_metronome(pos):
            continue
        try:
            bpm = float(m.group(1))
        except ValueError:
            continue
        txt = str(int(round(bpm))) if abs(bpm - round(bpm)) < 1e-9 else f'{bpm:g}'
        ins = ('<direction placement="above"><direction-type><metronome>'
               f'<beat-unit>quarter</beat-unit><per-minute>{txt}</per-minute>'
               '</metronome></direction-type></direction>')
        out.append(src[last:pos])
        out.append(ins)
        last = pos
        added[0] += 1
    out.append(src[last:])

    return ''.join(out), added[0]


def process(path, dry=False):
    with open(path, encoding='utf-8') as f:
        src = f.read()

    changes = []

    def do_direction(dm):
        seg = dm.group(0)
        met = re.search(r'<metronome\b[^>]*>([\s\S]*?)</metronome>', seg)
        if not met:
            return seg
        # 同一个 <direction> 里的 <sound tempo> —— MuseScore 的权威值
        snd = re.search(r'<sound\b[^>]*\btempo="([^"]+)"', seg)
        st = None
        if snd:
            try:
                st = float(snd.group(1))
            except ValueError:
                st = None
        new_inner, note = fix_metronome_inner(met.group(1), st)
        if new_inner is None:
            if note:
                changes.append(('skip', note))
            return seg
        changes.append(('fix', note))
        head = met.group(0)[:met.group(0).index('>') + 1]
        return seg.replace(met.group(0), head + new_inner + '</metronome>', 1)

    out = DIRECTION_RE.sub(do_direction, src)

    # ② 给缺失的 <sound tempo> 补 <metronome>
    #    （AlphaTab 只读 metronome，不补的话整曲会按第一个速度播到底）
    out2, n_added = ensure_metronomes(out)
    if n_added:
        changes.append(('add', f'补了 {n_added} 处缺失的谱面速度记号'
                              f'（AlphaTab 只读谱面记号，不补会按第一个速度播到底）'))
        out = out2

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

    return sum(1 for k, _ in changes if k in ('fix', 'add'))


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
