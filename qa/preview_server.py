"""静态预览服务器：serve frontend/dist，并把 /api、/files 反代到后端 8000。

用途：Firefox headless 对 SPA 截图时无法等待异步数据，因此先用 jsdom 渲染
静态快照放到 dist/qa/，再由本服务器提供（图片与接口也能正常加载）。

用法: python preview_server.py [port=8001]
"""
import sys
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIST = Path(__file__).resolve().parent.parent / 'frontend' / 'dist'
UPSTREAM = 'http://127.0.0.1:8000'


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(DIST), **kw)

    def _proxy(self):
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else None
        url = UPSTREAM + self.path
        req = urllib.request.Request(url, data=body, method=self.command)
        for h in ('Content-Type', 'Authorization'):
            if self.headers.get(h):
                req.add_header(h, self.headers[h])
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = r.read()
                self.send_response(r.status)
                self.send_header('Content-Type', r.headers.get('Content-Type', 'application/json'))
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header('Content-Type', e.headers.get('Content-Type', 'text/plain'))
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:  # noqa: BLE001
            self.send_error(502, str(e))

    def do_GET(self):
        if self.path.startswith(('/api/', '/files/')):
            return self._proxy()
        return super().do_GET()

    def do_POST(self):
        return self._proxy()

    def log_message(self, fmt, *args):  # 安静一点
        pass


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'preview server on http://127.0.0.1:{port}/ (dist={DIST})', flush=True)
    srv.serve_forever()
