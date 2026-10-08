#!/usr/bin/env python3
"""一条命令重造一份「三类差异合看」的对照。

这一套流程（清空一个声部 → 造改音高/删音/加音 → 造记号改动 → build-compare）
已经手敲过好几遍，每次都要重写一遍临时脚本。固化下来。

用法：
    python3 rebuild-compare.py <基础曲目id> <要清空的声部名> <改动处数> <标题> [对照id]

    对照 id 不传就是「基础 id + -all」。产物会是 <对照id>-a/-b/.diff.json/.marks.json。

例：
    python3 rebuild-compare.py m0203 乐队中提琴 13 "M02+03 · 三类差异合看"

它会：
  ① 读 pieces.json 找到这个条目的 file（原版）
  ② 把指定声部整曲改成休止符（模拟"某个声部没扒"）
  ③ 用 make-demo-changes.py 造 n 处改动（改音高/删音/加音 三类轮流、轮转声部）
  ④ 用 add-mark-changes.py 造记号改动（力度/文字/速度/渐强/跳音/重音）
  ⑤ 跑 build-compare.py 生成清单
  ⑥ 打印对账：造出多少处 vs 清单报多少处

⚠️ n 是「改动处数」，不是「清单条数」——
   两处改动落在同一小节同一声部时会合并成一条，所以条数可能少 1~2。
   脚本会把两边都打出来，让人自己核对，而不是含糊地说"完成"。
"""
import json, os, subprocess, sys, tempfile
import xml.etree.ElementTree as ET


def blank_part(src, dst, target):
    """把某个声部的全部发声音符改成休止符。返回改了多少个音。"""
    tree = ET.parse(src)
    root = tree.getroot()
    names = {sp.get('id'): (sp.findtext('part-name') or '').strip()
             for sp in root.find('part-list').findall('score-part')}
    hit = [p for p in root.findall('part') if names.get(p.get('id')) == target]
    if not hit:
        raise SystemExit(f'❌ 找不到声部「{target}」。这个条目的声部有：\n   '
                         + '\n   '.join(sorted(set(names.values()))))
    n = 0
    for p in hit:
        for m in p.findall('measure'):
            for x in list(m.findall('note')):
                if x.find('rest') is not None:
                    continue
                for tag in ('pitch', 'unpitched', 'chord'):
                    e = x.find(tag)
                    if e is not None:
                        x.remove(e)
                if x.find('rest') is None:
                    x.insert(0, ET.Element('rest'))
                n += 1
    tree.write(dst, encoding='utf-8', xml_declaration=True)
    return n


def run_marks(src, dst):
    """调 add-mark-changes.py（它是个带 main() 的脚本，用 exec 调）。"""
    code = ("import sys;sys.argv=['x',%r,%r];\n"
            "exec(open('add-mark-changes.py',encoding='utf-8').read()"
            ".replace(\"if __name__ == '__main__':\\n    main()\",''));main()"
            % (src, dst))
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    return r.stdout


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)
    base, part, n, title = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    # 对照条目的 id 默认是「基础 id + -all」
    cmp_id = sys.argv[5] if len(sys.argv) > 5 else base + '-all'

    # ⚠️⚠️ 这两个 id **必须**分开。
    #
    #    踩过：原来只有一个 id，我传了基础曲目 id（m0203）当 pid，
    #    而 build-compare 是拿 pid 当产物名的 —— 于是
    #      · 产物成了 m0203-a/-b/.diff/.marks（不是 m0203-all-*）
    #      · pieces.json 里**单曲条目 m0203 被覆盖成了对照条目**
    #    后果不是报错：单曲页还在，只是变成了一个"对照"，而真正的对照缺文件。
    if cmp_id == base:
        raise SystemExit('❌ 对照条目 id 不能等于基础曲目 id（会把单曲条目覆盖掉）')

    d = json.load(open('pieces.json', encoding='utf-8'))
    ent = next((x for x in d['pieces'] if x['id'] == base), None)
    if not ent:
        raise SystemExit(f'❌ pieces.json 里没有 id={base}')
    if ent.get('compareFile'):
        raise SystemExit(f'❌ {base} 是个对照条目，不是单曲 —— '
                         f'请传基础曲目的 id')
    src = ent['file']
    if not os.path.isfile(src):
        raise SystemExit(f'❌ 找不到原版文件 {src}')

    tmp = tempfile.mkdtemp(prefix='rebuild-')
    b = os.path.join(tmp, 'b.musicxml')
    c = os.path.join(tmp, 'c.musicxml')
    dd = os.path.join(tmp, 'd.musicxml')

    print(f'── {base} → {cmp_id} ──')
    print(f'  原版：{src}')
    k = blank_part(src, b, part)
    print(f'  ① 清空「{part}」：{k} 个音 → 休止符')

    r1 = subprocess.run([sys.executable, 'make-demo-changes.py', b, c, str(n)],
                        capture_output=True, text=True)
    print('  ② 三类改动：')
    for l in r1.stdout.split('\n'):
        if l.strip() and ('共改了' in l or '小节' in l and '　' in l):
            print('       ' + l.strip())

    r2 = run_marks(c, dd)
    print('  ③ 记号改动：')
    for l in r2.split('\n'):
        if '小节' in l and '　' in l:
            print('       ' + l.strip())

    # ⚠️⚠️ 改后版**必须**写到临时目录，绝不能写进 pieces/。
    #
    #    踩过：这里原来写的是 `pieces/{pid}.musicxml` ——
    #    而 src 本身就是 `pieces/{pid}.musicxml`
    #    （pieces.json 里 file 字段指向的就是它）。
    #    于是先覆盖了原版，finally 里的清理又把它删了。
    #    后果不是报错，而是 build-compare 拿"改后版"和"改后版"比 →
    #    **静默报 0 处差异、0 个空缺** —— 看起来像"跑通了"，其实什么都没比。
    #
    #    ⟹ 任何"算出来的路径 + 写/删"的组合，先确认它不等于输入文件。
    tmp_dst = os.path.join(tmp, 'forcompare.musicxml')
    import shutil
    shutil.copy(dd, tmp_dst)
    if os.path.abspath(tmp_dst) == os.path.abspath(src):
        raise SystemExit(f'❌ 改后版路径和原版相同（{src}），拒绝写入')
    try:
        r3 = subprocess.run([sys.executable, 'build-compare.py', src, tmp_dst, cmp_id, title,
                             '--label-a', '原版', '--label-b', '改后'],
                            capture_output=True, text=True)
        print('  ④ build-compare：')
        for l in r3.stdout.split('\n'):
            if any(k2 in l for k2 in ('处差异', '空缺', '小节　', '共 ', '（一侧')):
                print('       ' + l.strip())
        if r3.returncode != 0:
            print('       ❌ build-compare 失败：')
            print(r3.stderr[-800:])
    finally:
        # ⚠️ 只删临时目录里的东西，且再确认一次它不是原版
        if os.path.isfile(tmp_dst) and os.path.abspath(tmp_dst) != os.path.abspath(src):
            os.remove(tmp_dst)

    # ⑤ 对账
    dif = json.load(open(f'pieces/{cmp_id}.diff.json', encoding='utf-8'))
    mk = None
    if os.path.isfile(f'pieces/{cmp_id}.marks.json'):
        mk = json.load(open(f'pieces/{cmp_id}.marks.json', encoding='utf-8'))
    only_r = sum(1 for m in dif['measures'] if m['removed'] and not m['added'])
    only_a = sum(1 for m in dif['measures'] if m['added'] and not m['removed'])
    both = sum(1 for m in dif['measures'] if m['added'] and m['removed'])
    print()
    print(f"  对账：")
    print(f"    造出 {n} 处改动")
    print(f"    清单 {dif['diffCount']} 条：删+加 {both}　只删 {only_r}　只加 {only_a}")
    print(f"    （两处改动落在同一小节同一声部会合并成一条，所以条数可能略少于 {n}）")
    print(f"    整声部空缺 {dif.get('missingCount',0)} 个"
          f"　记号差异 {mk['markCount'] if mk else '-'} 处"
          f"　重名警告 {dif.get('dupWarn') or '无'}")
    print(f"    打开：http://10.198.30.177:8080/?piece={cmp_id}")


if __name__ == '__main__':
    main()
