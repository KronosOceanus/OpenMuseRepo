#!/usr/bin/env python3
"""
把两个版本的乐谱做成一份对照，一条命令。

【为什么要有这个脚本】

对比素材原来是我手工拼的：转 MusicXML → 修速度记号 → 出差异清单 →
改 pieces.json。**手工做就会漏步骤** —— 实测漏掉「修速度记号」那一步，
结果左边那一版播出来慢一倍（MuseScore 导出的「二分音符 = 44」
被 AlphaTab 当成四分音符 BPM）。谱面上印的记号还是对的，所以很难查。

这个脚本把那套流程固化下来，顺带把「哪些声部配上了」讲清楚。

【它做的事】

    ① 两边都转 MusicXML（.mscz/.mscx 用 MuseScore 转；已是 MusicXML 就直接用）
    ② 跑 fix-tempo.py      ← 以前手工做时漏的就是这步
    ③ 声部按【名字】配对，出差异清单
    ④ 更新 pieces.json（加 file / compareFile / compare）
    ⑤ 报告：配上了哪些声部、哪些没配上、小节数是否一致

【用法】

    python3 build-compare.py 版本A.mscz 版本B.mscz 对比id ["标题"]

例：
    python3 build-compare.py \\
        ~/Documents/MuseScore4/扒谱new/"moonlight melody（live）.mscz" \\
        ~/Documents/MuseScore4/扒谱new/"moonlight melody.mscz" \\
        moonlight-compare "moonlight melody · 两版对照"

选项：
    --label-a 文字    左边标签（默认用文件名）
    --label-b 文字    右边标签（默认用文件名）
    --no-install      只生成素材，不改 pieces.json
"""

import argparse
import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIECES = os.path.join(HERE, 'pieces')
MANIFEST = os.path.join(HERE, 'pieces.json')


def load_module(fname, modname):
    """按文件路径加载模块（文件名带连字符，不能直接 import）。"""
    path = os.path.join(HERE, fname)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def die(msg, hint=None):
    print()
    print('  ❌ ' + msg)
    if hint:
        print()
        for line in hint.strip().splitlines():
            print('     ' + line)
    print()
    sys.exit(1)


def find_mscore():
    cands = [
        os.environ.get('MUSESCORE_BIN'),
        '/Applications/MuseScore 4.app/Contents/MacOS/mscore',
        '/Applications/MuseScore 3.app/Contents/MacOS/mscore',
        'mscore', 'musescore', 'musescore3',
    ]
    for c in cands:
        if not c:
            continue
        try:
            subprocess.run([c, '--version'], capture_output=True, timeout=30, check=True)
            return c
        except Exception:
            continue
    return None


def locate(arg):
    """把用户给的参数变成一个真实存在的文件路径。

    允许只给文件名 —— 会在 ~/Documents/MuseScore4 下递归找。
    """
    p = os.path.abspath(os.path.expanduser(arg))
    if os.path.isfile(p):
        return p
    print(f'  给定路径不存在，去 ~/Documents/MuseScore4/ 下搜「{arg}」…')
    for pat in (arg, arg + '.mscz', arg + '.mscx', arg + '.musicxml'):
        hits = glob.glob(os.path.expanduser('~/Documents/MuseScore4/**/' + pat), recursive=True)
        if hits:
            print(f'  ✅ 找到：{hits[0]}')
            return hits[0]
    die(f'找不到乐谱文件：{arg}',
        '给完整路径最保险（路径里有空格加引号）。')


def to_musicxml(src, dst, mscore):
    """转成 MusicXML。已经是 MusicXML 就直接复制。"""
    if src.lower().endswith(('.musicxml', '.xml')):
        shutil.copyfile(src, dst)
        return '直接复用', os.path.getsize(dst)

    if not mscore:
        die('需要 MuseScore 才能把 .mscz/.mscx 转成 MusicXML',
            '设 MUSESCORE_BIN 环境变量，或先把文件导成 MusicXML 再喂进来。')

    r = subprocess.run([mscore, '-o', dst, src], capture_output=True, timeout=900)
    if not os.path.isfile(dst):
        err = (r.stderr or b'').decode('utf-8', 'replace')
        noise = ('qml', 'typeregistration', 'log file', 'dumps', 'findlib',
                 'network error', 'crashpad', 'mach_vm', 'in_range', 'mach_o', 'corefoundation')
        lines = [l for l in err.splitlines()
                 if l.strip() and not any(k in l.lower() for k in noise)]
        die('MuseScore 转换失败（没有产出文件）',
            '\n'.join(lines[-10:]) if lines else '（MuseScore 没输出什么）')
    return 'MuseScore 转换', os.path.getsize(dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file_a', help='左边（基准）的乐谱文件')
    ap.add_argument('file_b', help='右边（对比）的乐谱文件')
    ap.add_argument('pid', help='对比条目的 id（ASCII，会进 URL）')
    ap.add_argument('title', nargs='?', default=None, help='显示标题')
    ap.add_argument('--label-a', default=None)
    ap.add_argument('--label-b', default=None)
    ap.add_argument('--no-install', action='store_true')
    args = ap.parse_args()

    if not args.pid.isascii() or not all(c.isalnum() or c in '-_' for c in args.pid):
        die(f'id 只能用小写字母/数字/连字符（会进 URL）：{args.pid}',
            '例：moonlight-compare / kyoutsuu-2')

    print()
    print('  ── build-compare ──────────────────────────────')
    src_a = locate(args.file_a)
    src_b = locate(args.file_b)
    la = args.label_a or os.path.splitext(os.path.basename(src_a))[0]
    lb = args.label_b or os.path.splitext(os.path.basename(src_b))[0]

    mscore = find_mscore()
    print(f'  MuseScore：{mscore or "（没有，只能处理 MusicXML 输入）"}')
    print()

    os.makedirs(PIECES, exist_ok=True)
    out_a = os.path.join(PIECES, f'{args.pid}-a.musicxml')
    out_b = os.path.join(PIECES, f'{args.pid}-b.musicxml')

    # ① 转 MusicXML
    print('  ① 转 MusicXML')
    how_a, sz_a = to_musicxml(src_a, out_a, mscore)
    how_b, sz_b = to_musicxml(src_b, out_b, mscore)
    print(f'     左  {os.path.basename(out_a):<34s} {sz_a // 1024:>5d} KB  （{how_a}）')
    print(f'     右  {os.path.basename(out_b):<34s} {sz_b // 1024:>5d} KB  （{how_b}）')

    # ② 修速度记号 —— ⚠️ 这一步漏过，导致一边慢一倍
    print()
    print('  ② 修速度记号（非四分音符的 metronome 会被 AlphaTab 读错）')
    fixtempo = load_module('fix-tempo.py', 'fixtempo')
    for f in (out_a, out_b):
        fixtempo.process(f)

    # ③ 出差异清单
    print()
    print('  ③ 声部按名字配对 + 出差异清单')
    diffmod = load_module('diff-musicxml.py', 'diffmod')
    d = diffmod.build_diff(out_a, out_b, la, lb)
    out_diff = os.path.join(PIECES, f'{args.pid}.diff.json')
    with open(out_diff, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write('\n')

    print(f'     左 {d["partsA"]} 声部  右 {d["partsB"]} 声部  →  配上 {len(d["matched"])} 个')
    for m in d['matched']:
        print(f'       {m["name"]:<18s} 左 #{m["trackA"]:<3d} ↔  右 #{m["trackB"]}')
    if d['unmatchedA']:
        print(f'     左边独有：{"、".join(d["unmatchedA"][:6])}'
              + ('…' if len(d['unmatchedA']) > 6 else ''))
    if d['unmatchedB']:
        print(f'     右边独有：{len(d["unmatchedB"])} 个'
              + (f'（{"、".join(d["unmatchedB"][:4])}…）' if d['unmatchedB'] else ''))
    print(f'     只比了公共的 {d["measureCount"]} 小节，{d["diffCount"]} 处差异'
          + ('  ⚠️ 两边小节数不同' if d['truncated'] else ''))

    # ③b 记号差异（力度/速度/文字/连音线…）
    # 单独一个脚本、单独一个 JSON —— 这样记号那块出问题不会影响音符对比。
    # ⚠️ 记号改动**完全不碰音符**：实测注入 7 处记号改动后，音符序列
    #    一个字节都没变，音符对比的结论是「完全一致」—— 那是误导。
    print()
    print('  ③b 记号差异（力度/速度/文字/连音线/跳音…）')
    marksmod = load_module('diff-marks.py', 'marksmod')
    md = marksmod.build(out_a, out_b, la, lb)
    out_marks = os.path.join(PIECES, f'{args.pid}.marks.json')
    with open(out_marks, 'w', encoding='utf-8') as f:
        json.dump(md, f, ensure_ascii=False, indent=2)
        f.write('\n')
    if md['markCount']:
        for m in md['marks']:
            for k in m['items']:
                print(f'       第 {m["number"]} 小节　{k["kind"]}：{k["from"]} → {k["to"]}')
        for m in md['partMarks']:
            for k in m['items']:
                print(f'       第 {m["number"]} 小节（{m["trackName"]}）　'
                      f'{k["kind"]}：{k["from"]} → {k["to"]}')
        print(f'     共 {md["markCount"]} 处')
    else:
        print('     没有记号差异')

    # ④ 更新清单
    print()
    print('  ④ 更新 pieces.json')
    data = {'pieces': []}
    if os.path.isfile(MANIFEST):
        try:
            with open(MANIFEST, encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            die(f'pieces.json 解析失败：{e}')
    if not isinstance(data.get('pieces'), list):
        data['pieces'] = []

    existed = any(x.get('id') == args.pid for x in data['pieces'])
    kept = [x for x in data['pieces'] if x.get('id') != args.pid]
    entry = {
        'id': args.pid,
        'title': args.title or f'{la} ↔ {lb}',
        'file': f'pieces/{os.path.basename(out_a)}',
        'compareFile': f'pieces/{os.path.basename(out_b)}',
        'compare': f'pieces/{os.path.basename(out_diff)}',
        'marks': f'pieces/{os.path.basename(out_marks)}',
        # 声部数可能差很多，scale 取小一点更保险
        'display': {'scale': 0.7, 'systemPaddingTop': 26, 'systemPaddingBottom': 26,
                    'trackStaffPaddingBetween': 10},
    }
    kept.append(entry)
    kept.sort(key=lambda x: x.get('id', ''))
    data['pieces'] = kept

    if args.no_install:
        print('     （--no-install，没有写）')
    else:
        with open(MANIFEST, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        print(f'     {"更新" if existed else "新增"}条目 {args.pid}（现在 {len(kept)} 首）')

    print()
    print(f'  打开：http://127.0.0.1:8080/?piece={args.pid}')
    print()


if __name__ == '__main__':
    main()
