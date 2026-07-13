#!/usr/bin/env python3
"""HTTPS server: static files + proxy /api/ to backend"""
import ssl, os, json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.error import URLError

API_BASE = 'http://localhost:8081'

class ProxyHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/'):
            self._proxy('GET')
        else:
            super().do_GET()

    def do_POST(self):
        print(f'POST path={self.path!r}')
        if self.path.startswith('/api/'):
            self._proxy('POST')
        else:
            super().do_POST()

    def _proxy(self, method):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length > 0 else None
            url = API_BASE + self.path
            req = Request(url, data=body, method=method)
            req.add_header('Content-Type', self.headers.get('Content-Type', 'application/json'))
            if self.headers.get('Authorization'):
                req.add_header('Authorization', self.headers['Authorization'])
            resp = urlopen(req, timeout=10)
            self.send_response(resp.status)
            self.send_header('Content-Type', resp.headers.get('Content-Type', 'application/json'))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(resp.read())
        except URLError as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        self.end_headers()

os.chdir(os.path.dirname(__file__))
CERT = 'cert.pem'; KEY = 'key.pem'
use_tls = os.path.isfile(CERT) and os.path.isfile(KEY)
if use_tls:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    server = HTTPServer(('0.0.0.0', 8443), ProxyHandler)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print('HTTPS server on https://localhost:8443 (proxy /api/ -> 8081)')
else:
    # ponytail: cert 不存在则回退纯 HTTP，避免开发机一启动就崩。安全性在真实部署时由反代负责
    server = HTTPServer(('0.0.0.0', 8443), ProxyHandler)
    print('HTTP server on http://localhost:8443 (no TLS: cert.pem/key.pem missing; proxy /api/ -> 8081)')
server.serve_forever()
