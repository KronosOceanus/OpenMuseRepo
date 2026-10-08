#!/usr/bin/env python3
"""
把一首曲子加进播放页。

做三件事：
    ① 用 MuseScore CLI 把 .mscx/.mscz 转成 MusicXML，放进 pieces/
    ② 在 pieces.json 里加/更新一条
    ③ 打印结果

用法：
    python3 add-piece.py <乐谱文件> <id> [标题]
    python3 add-piece.py --relayout          # 按声部数重套排版规则

例：
    python3 add-piece.py ~/Documents/MuseScore4/作曲/优纪.mscz youji "优纪"
    python3 add-piece.py pieces/xxx.mscx youji          # 标题省略则用 id

id 要 ASCII —— 它会进 URL（?piece=<id>）。
"""

import json
import os
import subprocess
import sys
import glob
import re
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
PIECES_DIR = os.path.join(HERE, 'pieces')
MANIFEST = os.path.join(HERE, 'pieces.json')


# ══════════════════════════════════════════════════════════════════
#  排版规则：按声部数自动配一套观感合适的参数
#
#  为什么不统一用一套：声部数差一个量级，需求完全相反。
#    1 声部钢琴   想要音符大、看得清
#    11 声部总谱  想要一屏看到更多、行距拉开
#  用同一个 scale，不是钢琴太小就是总谱太挤。
#
#  默认那套（scale 0.5 / 行距 60 / 声部距 24）是在 11 声部总谱上
#  实调出来的，所以 10 声部以上不写 display，直接用默认。
#
#  这些值都可以在页面上用 URL 参数覆盖（见 README「排版」一节），
#  调好了改这里，或者直接改 pieces.json 里那一首的 display。
# ══════════════════════════════════════════════════════════════════

LAYOUT_TIERS = [
    # (最大声部数, display 设置；None = 用页面默认值)
    (2,    {'scale': 1.0,  'systemPaddingTop': 24, 'systemPaddingBottom': 24}),
    (4,    {'scale': 0.9,  'systemPaddingTop': 28, 'systemPaddingBottom': 28,
            'trackStaffPaddingBetween': 16}),
    (6,    {'scale': 0.8,  'systemPaddingTop': 34, 'systemPaddingBottom': 34,
            'trackStaffPaddingBetween': 18}),
    (9,    {'scale': 0.65, 'systemPaddingTop': 44, 'systemPaddingBottom': 44,
            'trackStaffPaddingBetween': 20}),
    (9999, None),   # 10 声部以上：用页面默认值
]


def layout_for(n_parts):
    """给 n 个声部挑一套排版设置。返回 dict 或 None（None = 用默认值）。"""
    for limit, cfg in LAYOUT_TIERS:
        if n_parts <= limit:
            return dict(cfg) if cfg else None
    return None


def count_parts(xml_path):
    """数一数 MusicXML 里有几个声部。"""
    try:
        with open(xml_path, encoding='utf-8') as f:
            return len(re.findall(r'<score-part\s', f.read()))
    except Exception:
        return 0


def die(msg, hint=None):
    """统一失败出口 —— 报错时一定带上「怎么修」。

    hint 用三引号写，dedent 之后每行统一加 5 个空格 ——
    否则手写缩进和这里的缩进会叠起来，输出歪得没法看。
    """
    print()
    print('  ❌ ' + msg)
    if hint:
        print()
        # ⚠️ 前面加个换行再 dedent。
        # textwrap.dedent 算的是「所有行的公共缩进」——
        # 如果提示语的第一行顶格写（无缩进），公共缩进就是 0，等于没去。
        # 补一个空行当第一行，后续行就共享缩进了。
        for line in textwrap.dedent('\n' + hint).strip().splitlines():
            print(('     ' + line).rstrip() if line.strip() else '')
    print()
    sys.exit(1)


def find_mscore():
    """找 MuseScore CLI。macOS 的路径带空格，用列表传给 subprocess。"""
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


def relayout_all():
    """把排版规则重新套到 pieces.json 里所有曲子上。

    曲子的声部数可能变（改了谱、重新导出），规则也可能调 —— 用这个同步。
    只动 display 字段，其他不动。
    """
    if not os.path.isfile(MANIFEST):
        die('没有 pieces.json')
    with open(MANIFEST, encoding='utf-8') as f:
        data = json.load(f)

    print()
    print('  ── 重新套用排版规则 ─────────────────────')
    print()
    for it in data.get('pieces', []):
        path = os.path.join(HERE, it.get('file', ''))
        if not os.path.isfile(path):
            print(f'  ⚠️ {it.get("title", it["id"])}：文件不在，跳过')
            continue
        n = count_parts(path)
        layout = layout_for(n)
        if layout:
            it['display'] = layout
            desc = f'scale={layout["scale"]} 行距={layout["systemPaddingTop"]} 声部距={layout.get("trackStaffPaddingBetween", "默认")}'
        else:
            it.pop('display', None)
            desc = '用页面默认值（scale 0.5 / 行距 60）'
        print(f'  {it.get("title", it["id"]):<14s} {n:2d} 声部 → {desc}')

    with open(MANIFEST, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print()
    print('  ✅ 已写入 pieces.json')
    print()


def main():
    if '--relayout' in sys.argv:
        relayout_all()
        return

    if len(sys.argv) < 3:
        print(__doc__)
        print('  ⚠️ 参数不够。最少要两个：乐谱文件 和 id')
        print()
        print('  例：python3 add-piece.py ~/Documents/MuseScore4/作曲/优纪.mscz youji "优纪"')
        sys.exit(1)

    raw_arg = sys.argv[1]
    pid = sys.argv[2]
    title = sys.argv[3] if len(sys.argv) > 3 else pid

    print()
    print('  ── add-piece ──────────────────────────────')
    print(f'  文件参数：{raw_arg}')
    print(f'  id      ：{pid}')
    print(f'  标题    ：{title}')
    print(f'  工作目录：{HERE}')
    print()

    # ── 找文件 ────────────────────────────────────────────────────
    src = os.path.abspath(os.path.expanduser(raw_arg))
    if not os.path.isfile(src):
        print(f'  给定路径不存在，去 ~/Documents/MuseScore4/ 下搜「{raw_arg}」…')
        hits = glob.glob(os.path.expanduser('~/Documents/MuseScore4/**/' + raw_arg), recursive=True)
        if not hits:
            # 补一个常见情况：忘了带扩展名
            for ext in ('.mscz', '.mscx'):
                hits = glob.glob(os.path.expanduser('~/Documents/MuseScore4/**/' + raw_arg + ext), recursive=True)
                if hits:
                    break
        if not hits:
            die(f'找不到乐谱文件：{raw_arg}',
                '''给完整路径最保险，比如：
                     python3 add-piece.py ~/Documents/MuseScore4/作曲/优纪.mscz youji

                   路径里有空格要加引号：
                     python3 add-piece.py "~/Documents/my scores/a.mscz" myscore''')
        src = hits[0]
        print(f'  ✅ 自动找到：{src}')
    else:
        print(f'  ✅ 文件存在：{src}')

    # ── 校验 id ───────────────────────────────────────────────────
    if not pid.isascii():
        die(f'id 里有非 ASCII 字符：{pid}',
            '''id 会进 URL（?piece=<id>），必须用 ASCII。

              ❌ 优纪 / 神话2 / 终末之蓝
              ✅ youji / shenhua2 / shumatsu

             中文标题没问题，放在第三个参数：
               python3 add-piece.py 优纪.mscz youji "优纪"''')

    if not re.fullmatch(r'[A-Za-z0-9_-]+', pid):
        die(f'id 含有不允许的字符：{pid}',
            '只允许字母、数字、下划线、连字符。例：youji / shenhua-2 / op_01')

    # ── 找 MuseScore ──────────────────────────────────────────────
    mscore = find_mscore()
    if not mscore:
        die('找不到 MuseScore 命令行',
            '''试过这些位置：
                 环境变量 MUSESCORE_BIN
                 /Applications/MuseScore 4.app/Contents/MacOS/mscore
                 /Applications/MuseScore 3.app/Contents/MacOS/mscore
                 PATH 里的 mscore / musescore / musescore3

             装了 MuseScore 的话，用环境变量直接指：
                 MUSESCORE_BIN="/Applications/MuseScore 4.app/Contents/MacOS/mscore" \\
                   python3 add-piece.py 曲子.mscz myid''')
    print(f'  ✅ MuseScore：{mscore}')

    # ── 转换 ──────────────────────────────────────────────────────
    os.makedirs(PIECES_DIR, exist_ok=True)
    out_name = f'{pid}.musicxml'
    out_path = os.path.join(PIECES_DIR, out_name)

    print()
    print(f'  转换中…（大谱子要几十秒）')
    cmd = [mscore, '-o', out_path, src]
    r = subprocess.run(cmd, capture_output=True, timeout=900)

    if not os.path.isfile(out_path):
        err = (r.stderr or b'').decode('utf-8', 'replace')
        noise = ('qml', 'typeregistration', 'log file', 'dumps', 'findlib', 'network error')
        lines = [l for l in err.splitlines() if l.strip() and not any(k in l.lower() for k in noise)]
        die('MuseScore 转换失败（没有产出文件）',
            '命令：\n       ' + ' '.join(cmd) +
            '\n\n     MuseScore 说：\n       ' + ('\n       '.join(lines[-12:]) if lines else '（无输出）') +
            '\n\n     常见原因：\n' +
            '       · .mscz 是 MuseScore 3 或更老的版本存的，当前版本读不了\n' +
            '       · 文件损坏\n' +
            '       · 磁盘满 / 没有写权限\n\n' +
            '     可以先用 MuseScore 打开那个文件另存一次再试。')

    size = os.path.getsize(out_path)
    print(f'  ✅ 转换完成：{os.path.relpath(out_path, HERE)}  {size} 字节')

    # ── 修正速度记号 ──────────────────────────────────────────────
    # MuseScore 会把「二分音符 = 80」导出成 <beat-unit>half</beat-unit>
    # <per-minute>80</per-minute>，而 AlphaTab 1.8.4 读这个时**忽略 beat-unit**，
    # 直接当成四分音符 BPM —— 结果慢一倍。见 fix-tempo.py 的注释。
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('fixtempo', os.path.join(HERE, 'fix-tempo.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.process(out_path)
    except Exception as e:
        print(f'  ⚠️ 速度记号修正跳过：{e}')

    # ── 更新清单 ──────────────────────────────────────────────────
    data = {'pieces': []}
    if os.path.isfile(MANIFEST):
        try:
            with open(MANIFEST, encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            die(f'pieces.json 解析失败：{e}',
                f'文件：{MANIFEST}\n     修好它，或者删掉让它重建（会丢掉已有条目）。')
    if not isinstance(data.get('pieces'), list):
        data['pieces'] = []

    n_parts = count_parts(out_path)
    layout = layout_for(n_parts)

    existed = any(p.get('id') == pid for p in data['pieces'])
    kept = [p for p in data['pieces'] if p.get('id') != pid]

    entry = {'id': pid, 'title': title, 'file': f'pieces/{out_name}'}
    if layout:
        entry['display'] = layout
    kept.append(entry)
    kept.sort(key=lambda p: p.get('id', ''))
    data['pieces'] = kept

    if layout:
        print(f'  ✅ 排版：{n_parts} 声部 → scale={layout["scale"]} '
              f'行距={layout["systemPaddingTop"]} 声部距={layout.get("trackStaffPaddingBetween", "默认")}')
    else:
        print(f'  ✅ 排版：{n_parts} 声部 → 用页面默认值（scale 0.5 / 行距 60）')

    with open(MANIFEST, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

    print(f'  ✅ {"更新" if existed else "新增"} pieces.json（现在 {len(kept)} 首）')
    print()
    print(f'  打开：http://127.0.0.1:8080/?piece={pid}')
    print()


if __name__ == '__main__':
    main()
