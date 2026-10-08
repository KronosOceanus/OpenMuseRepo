#!/usr/bin/env python3
"""
本地预览服务器。

比 `python3 -m http.server` 多的唯一一件事：**对所有响应加 no-store**。

为什么需要：
    浏览器的强缓存会让「改完页面刷新还是旧的」变成常态，
    而表现是「我改了但没生效」—— 排查起来非常费时。
    加了这个头，每次刷新都是磁盘上的最新文件。

用法：
    python3 serve.py [端口]      # 默认 8080
"""

import sys
import http.server
import socketserver


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'  # 默认是 1.0，每个请求都要重开连接，慢

    def end_headers(self):
        # 关掉一切缓存
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, fmt, *args):
        # 保留默认日志格式（排查资源加载很有用）
        super().log_message(fmt, *args)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

    # ⚠️ 必须用多线程版，不能用 TCPServer。
    #
    # TCPServer 一次只处理一个请求 —— 浏览器会并发发好几个（HTML、JS、字体、音源），
    # 串行处理时后面的请求要排队。表现是加载变慢，严重时看起来像"卡住"。
    #
    # 另外 protocol_version 设成 HTTP/1.1，否则每个请求都重开 TCP 连接。
    #
    # 注意：ThreadingHTTPServer 在 http.server 里，不在 socketserver 里
    #      （socketserver 只有 ThreadingTCPServer）。
    class Server(http.server.ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    with Server(('127.0.0.1', port), NoCacheHandler) as httpd:
        print(f'OpenMuse 预览服务：http://127.0.0.1:{port}  （多线程 + 已禁用缓存）', flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\n已停止')


if __name__ == '__main__':
    main()
