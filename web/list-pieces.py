#!/usr/bin/env python3
"""
列出手上所有曲子的概况 —— 挑曲子时看这个。

每首显示：声部数、用了几种音色、都有什么乐器、时长、小节数。

用法：
    python3 list-pieces.py            # 全部
    python3 list-pieces.py dreamy     # 只看某一首（支持部分匹配）
"""

import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# General MIDI 音色表（1-based，和 MusicXML 的 <midi-program> 一致）
GM = {
    1: 'Acoustic Grand Piano', 2: 'Bright Piano', 3: 'Electric Grand', 4: 'Honky-tonk',
    5: 'Electric Piano 1', 6: 'Electric Piano 2', 7: 'Harpsichord', 8: 'Clavinet',
    9: 'Celesta', 10: 'Glockenspiel', 11: 'Music Box', 12: 'Vibraphone',
    13: 'Marimba', 14: 'Xylophone', 15: 'Tubular Bells', 16: 'Dulcimer',
    17: 'Drawbar Organ', 18: 'Percussive Organ', 19: 'Rock Organ', 20: 'Church Organ',
    21: 'Reed Organ', 22: 'Accordion', 23: 'Harmonica', 24: 'Tango Accordion',
    25: 'Nylon Guitar', 26: 'Steel Guitar', 27: 'Jazz Guitar', 28: 'Clean Guitar',
    29: 'Muted Guitar', 30: 'Overdriven Guitar', 31: 'Distortion Guitar', 32: 'Guitar Harmonics',
    33: 'Acoustic Bass', 34: 'Finger Bass', 35: 'Pick Bass', 36: 'Fretless Bass',
    37: 'Slap Bass 1', 38: 'Slap Bass 2', 39: 'Synth Bass 1', 40: 'Synth Bass 2',
    41: 'Violin', 42: 'Viola', 43: 'Cello', 44: 'Contrabass', 45: 'Tremolo Strings',
    46: 'Pizzicato Strings', 47: 'Orchestral Harp', 48: 'Timpani',
    49: 'String Ensemble 1', 50: 'String Ensemble 2', 51: 'Synth Strings 1', 52: 'Synth Strings 2',
    53: 'Choir Aahs', 54: 'Voice Oohs', 55: 'Synth Voice', 56: 'Orchestra Hit',
    57: 'Trumpet', 58: 'Trombone', 59: 'Tuba', 60: 'Muted Trumpet',
    61: 'French Horn', 62: 'Brass Section', 63: 'Synth Brass 1', 64: 'Synth Brass 2',
    65: 'Soprano Sax', 66: 'Alto Sax', 67: 'Tenor Sax', 68: 'Baritone Sax',
    69: 'Oboe', 70: 'English Horn', 71: 'Bassoon', 72: 'Clarinet',
    73: 'Piccolo', 74: 'Flute', 75: 'Recorder', 76: 'Pan Flute',
    77: 'Blown Bottle', 78: 'Shakuhachi', 79: 'Whistle', 80: 'Ocarina',
    81: 'Square Lead', 82: 'Saw Lead', 83: 'Calliope Lead', 84: 'Chiff Lead',
    85: 'Charang Lead', 86: 'Voice Lead', 87: 'Fifths Lead', 88: 'Bass + Lead',
    89: 'Pad 1 (New Age)', 90: 'Pad 2 (Warm)', 91: 'Pad 3 (Polysynth)', 92: 'Pad 4 (Choir)',
    93: 'Pad 5 (Bowed)', 94: 'Pad 6 (Metallic)', 95: 'Pad 7 (Halo)', 96: 'Pad 8 (Sweep)',
    97: 'FX 1 (Rain)', 98: 'FX 2 (Soundtrack)', 99: 'FX 3 (Crystal)', 100: 'FX 4 (Atmosphere)',
    101: 'FX 5 (Brightness)', 102: 'FX 6 (Goblins)', 103: 'FX 7 (Echoes)', 104: 'FX 8 (Sci-Fi)',
    105: 'Sitar', 106: 'Banjo', 107: 'Shamisen', 108: 'Koto',
    109: 'Kalimba', 110: 'Bagpipe', 111: 'Fiddle', 112: 'Shanai',
    113: 'Tinkle Bell', 114: 'Agogo', 115: 'Steel Drums', 116: 'Woodblock',
    117: 'Taiko Drum', 118: 'Melodic Tom', 119: 'Synth Drum', 120: 'Reverse Cymbal',
    121: 'Guitar Fret Noise', 122: 'Breath Noise', 123: 'Seashore', 124: 'Bird Tweet',
    125: 'Telephone Ring', 126: 'Helicopter', 127: 'Applause', 128: 'Gunshot',
}


def inspect(path):
    with open(path, encoding='utf-8') as f:
        s = f.read()

    parts = []
    for m in re.finditer(r'<score-part id="([^"]+)">([\s\S]*?)</score-part>', s):
        pid, body = m.group(1), m.group(2)
        name = re.search(r'<part-name>([^<]*)</part-name>', body)
        prog = re.search(r'<midi-program>([^<]+)</midi-program>', body)
        p = int(prog.group(1)) if prog and prog.group(1).isdigit() else None
        parts.append({
            'id': pid,
            'name': (name.group(1) if name else '?').strip() or '?',
            'program': p,
            'gm': GM.get(p, f'program {p}') if p else '?',
        })

    # 时长：用 <sound tempo> 和小节长度估个大概
    tempo = None
    tm = re.search(r'<sound[^>]*tempo="([^"]+)"', s)
    if tm:
        try:
            tempo = float(tm.group(1))
        except ValueError:
            pass

    return {
        'parts': parts,
        'measures': len(re.findall(r'<measure ', s)),
        'tempo': tempo,
        'distinct': len({p['program'] for p in parts if p['program']}),
    }


def main():
    filt = sys.argv[1].lower() if len(sys.argv) > 1 else None

    manifest_path = os.path.join(HERE, 'pieces.json')
    if not os.path.isfile(manifest_path):
        print('  ❌ 没有 pieces.json')
        sys.exit(1)

    with open(manifest_path, encoding='utf-8') as f:
        pieces = json.load(f).get('pieces', [])

    if filt:
        pieces = [p for p in pieces if filt in p.get('id', '').lower() or filt in p.get('title', '').lower()]

    if not pieces:
        print('  没有匹配的曲子')
        sys.exit(0)

    print()
    for it in pieces:
        path = os.path.join(HERE, it['file'])
        print(f'  ━━ {it.get("title", it["id"])}  ({it["id"]})')

        if not os.path.isfile(path):
            print(f'     ❌ 文件不在：{it["file"]}')
            print()
            continue

        info = inspect(path)
        size = os.path.getsize(path)
        d = info['distinct']
        tag = '✅ 多音色' if d > 1 else ('⚠️ 只有一种音色' if d == 1 else '?')
        print(f'     {info["measures"]} 小节 · {len(info["parts"])} 声部 · {d} 种音色 {tag}'
              + (f' · 四分音符 {info["tempo"]:g}' if info['tempo'] else '')
              + f' · {size // 1024} KB')
        for p in info['parts']:
            print(f'       {p["name"]:<14s} {p["gm"]}')
        print()

    print(f'  共 {len(pieces)} 首')
    print()


if __name__ == '__main__':
    main()
