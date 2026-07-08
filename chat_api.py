#!/usr/bin/env python3
"""eShop Chat API - Python + SQLite 零依赖"""

import json, sqlite3, os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = os.path.join(os.path.dirname(__file__), 'eshop.db')

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("""CREATE TABLE IF NOT EXISTS chat_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_name TEXT NOT NULL DEFAULT '匿名用户',
        last_message TEXT,
        unread INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        sender_type TEXT NOT NULL,
        content TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
    )""")
    db.commit()
    db.close()

class ChatHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        action = params.get('action', [''])[0]

        try:
            if action == 'sessions':
                self._json(self._get_sessions())
            elif action == 'messages':
                sid = int(params.get('session_id', [0])[0])
                self._json(self._get_messages(sid))
            elif action == 'unread':
                db = sqlite3.connect(DB_PATH)
                row = db.execute("SELECT COUNT(*) FROM chat_sessions WHERE unread > 0 AND status='open'").fetchone()
                db.close()
                self._json({'code': 0, 'data': {'count': row[0]}})
            else:
                self._json({'code': 1, 'msg': 'unknown action'}, 400)
        except Exception as e:
            self._json({'code': 1, 'msg': str(e)}, 500)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}
        params = parse_qs(urlparse(self.path).query)
        action = params.get('action', [''])[0]

        try:
            if action == 'messages':
                sid = body.get('session_id') or int(params.get('session_id', [0])[0])
                result = self._send_message(sid, body.get('content', ''),
                    body.get('sender_type', 'user'), body.get('user_name', '匿名用户'))
                self._json(result)
            elif action == 'close':
                sid = body.get('session_id', 0)
                db = sqlite3.connect(DB_PATH)
                db.execute("UPDATE chat_sessions SET status='closed' WHERE id=?", (sid,))
                db.commit()
                db.close()
                self._json({'code': 0, 'msg': 'closed'})
            else:
                self._json({'code': 1, 'msg': 'unknown action'}, 400)
        except Exception as e:
            self._json({'code': 1, 'msg': str(e)}, 500)

    def _get_sessions(self):
        db = sqlite3.connect(DB_PATH)
        rows = db.execute(
            """SELECT s.*, (SELECT COUNT(*) FROM chat_messages WHERE session_id=s.id AND sender_type='user' AND is_read=0) as unread
               FROM chat_sessions s WHERE s.status='open' ORDER BY s.updated_at DESC"""
        ).fetchall()
        db.close()
        return {'code': 0, 'data': [{
            'id': r[0], 'user_name': r[1], 'last_message': r[2],
            'unread': r[-1], 'status': r[4], 'created_at': r[5], 'updated_at': r[6]
        } for r in rows]}

    def _get_messages(self, sid):
        db = sqlite3.connect(DB_PATH)
        rows = db.execute("SELECT * FROM chat_messages WHERE session_id=? ORDER BY created_at ASC", (sid,)).fetchall()
        db.execute("UPDATE chat_messages SET is_read=1 WHERE session_id=? AND sender_type='user'", (sid,))
        db.execute("UPDATE chat_sessions SET unread=0 WHERE id=?", (sid,))
        db.commit()
        db.close()
        return {'code': 0, 'data': [{
            'id': r[0], 'session_id': r[1], 'sender_type': r[2], 'content': r[3], 'is_read': r[4], 'created_at': r[5]
        } for r in rows]}

    def _send_message(self, sid, content, sender_type, user_name):
        if not content:
            return {'code': 1, 'msg': 'empty'}
        db = sqlite3.connect(DB_PATH)
        if not sid:
            db.execute("INSERT INTO chat_sessions (user_name, last_message) VALUES (?, ?)", (user_name, content[:100]))
            sid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            db.execute("UPDATE chat_sessions SET last_message=?, updated_at=datetime('now','localtime') WHERE id=?", (content[:100], sid))
        if sender_type == 'user':
            db.execute("UPDATE chat_sessions SET unread=unread+1 WHERE id=?", (sid,))
        db.execute("INSERT INTO chat_messages (session_id, sender_type, content) VALUES (?, ?, ?)", (sid, sender_type, content))
        db.commit()
        mid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.close()
        return {'code': 0, 'data': {'session_id': sid, 'id': mid}}

    def _json(self, data, code=200):
        self.send_response(code)
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Type', 'application/json')

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    init_db()
    port = 8081
    server = HTTPServer(('0.0.0.0', port), ChatHandler)
    print(f'Chat API running on http://0.0.0.0:{port}')
    server.serve_forever()
