#!/usr/bin/env python3
"""
扫 index.html 里「调用了但没定义」的函数。

【为什么需要】

删代码时容易连带删掉别的函数，而这类问题：
    · node --check **查不出来**（语法完全合法）
    · 页面照样加载
    · 只有真的点到那个功能才报 "xxx is not defined"

实测踩过：删「上下摞叠」模式时用「从这个注释块删到下一个注释块」，
而 measureStartTick 正好夹在中间 —— 结果「点差异列表跳转」整个失效，
报错还是被 try/catch 吞在日志里，不展开诊断面板根本看不见。

用法：
    python3 check-page.py [index.html]
"""

import os
import re
import sys

# 内建 / 浏览器全局，不算「缺失」
BUILTIN = {
    'if', 'for', 'while', 'switch', 'catch', 'typeof', 'new', 'function', 'return',
    'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'String', 'Number', 'Boolean',
    'Array', 'Object', 'Math', 'JSON', 'Date', 'Map', 'Set', 'Promise', 'Error', 'Symbol',
    'fetch', 'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval',
    'requestAnimationFrame', 'getComputedStyle', 'alert',
    'decodeURIComponent', 'encodeURIComponent', 'URLSearchParams',
    # CSS 函数（会出现在 <style> 里）
    'rgba', 'rgb', 'hsl', 'calc', 'var', 'url', 'linear-gradient', 'translateY', 'translateX',
}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
    with open(path, encoding='utf-8') as f:
        html = f.read()

    # 去掉 HTML 注释再抽内联 script（注释里也可能出现函数名）
    h = re.sub(r'<!--.*?-->', '', html, flags=re.S)
    code = '\n'.join(re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', h, re.S))

    defined = set(re.findall(r'function\s+(\w+)\s*\(', code))
    defined |= set(re.findall(r'(?:var|let|const)\s+(\w+)\s*=\s*function', code))

    called = set(re.findall(r'(?<![\w.$])([a-z][A-Za-z0-9_]*)\s*\(', code))
    # 排除 xxx.method() 形式（那些是对象方法，不是本文件的函数）
    methods = set(re.findall(r'\.([a-z][A-Za-z0-9_]*)\s*\(', code))

    missing = sorted(called - defined - BUILTIN - methods)

    print(f'  文件：{os.path.basename(path)}')
    print(f'  定义了 {len(defined)} 个函数，调用了 {len(called)} 个名字')
    print()
    if missing:
        print(f'  ❌ 有 {len(missing)} 个「调用了但没定义」：')
        for m in missing:
            n = len(re.findall(r'(?<![\w.$])' + re.escape(m) + r'\s*\(', code))
            print(f'     {m:26s} 被调用 {n} 次')
        print()
        print('  ⚠️ 这些不会让页面加载失败，只有点到那个功能才报错。')
        sys.exit(1)
    else:
        print('  ✅ 没有「调用但未定义」的函数')


if __name__ == '__main__':
    main()
