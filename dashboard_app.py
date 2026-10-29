# -*- coding: utf-8 -*-
"""
红利低波 · 每日指标看板 —— Web 服务入口（Render.com 免费实例 / 本地均可运行）

零 Web 框架依赖（标准库 http.server），启动后：
    GET /          实时渲染看板（scripts/dashboard/dashboard_live.py，10 分钟缓存）
    GET /healthz   健康检查（配合外部保活 ping）
本地运行：  python dashboard_app.py            （默认 http://127.0.0.1:10000）
Render 运行：自动注入 PORT 环境变量，配置见 render.yaml
"""
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.abspath(os.path.join(ROOT, '..', '..', '红利低波价格走势分析程序'))
sys.path.insert(0, ROOT)                                     # dashboard_live / build_dashboard
sys.path.insert(0, os.path.join(_PROJ, 'scripts', 'data'))   # update_data（主项目）

from dashboard_live import get_dashboard_html  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/healthz':
            self._respond(200, b'ok', 'text/plain; charset=utf-8')
        elif path in ('/', '/index.html'):
            try:
                self._respond(200, get_dashboard_html().encode('utf-8'),
                              'text/html; charset=utf-8')
            except Exception as e:
                self._respond(502, f'渲染失败: {e}'.encode('utf-8'),
                              'text/plain; charset=utf-8')
        elif path == '/favicon.ico':
            self._respond(204, b'')
        else:
            self.send_response(302)
            self.send_header('Location', '/')
            self.end_headers()

    def _respond(self, code, body, ctype=None):
        self.send_response(code)
        if ctype:
            self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f'{self.address_string()} {fmt % args}', flush=True)


if __name__ == '__main__':
    if sys.platform.startswith('win'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
    port = int(os.environ.get('PORT', 10000))
    print(f'看板服务启动: http://0.0.0.0:{port}', flush=True)
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
