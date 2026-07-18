#!/usr/bin/env python3
"""eShop Social API - Python + libSQL (Turso) 三层社交商城"""
import json, sqlite3, hashlib, hmac, base64, time, os, uuid, mimetypes
import libsql
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = os.path.join(os.path.dirname(__file__), 'eshop.db')
TURSO_URL = os.environ.get('TURSO_URL', '')
TURSO_TOKEN = os.environ.get('TURSO_TOKEN', '')
if not TURSO_URL:
    _env = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.isfile(_env):
        for _line in open(_env, encoding='utf-8'):
            _line = _line.strip()
            if _line and '=' in _line and not _line.startswith('#'):
                _k, _v = _line.split('=', 1)
                if _k == 'TURSO_URL' and not TURSO_URL: TURSO_URL = _v
                if _k == 'TURSO_TOKEN' and not TURSO_TOKEN: TURSO_TOKEN = _v
SECRET = b'eshop_secret_key_2024'

# In-memory WebRTC signaling state
rtc_rooms = {}  # {room_id: {host_id, title, viewers:set(), chat:[], offers:{}, answers:{}, ices:[]}}

class _DictRow(dict):
    def __getitem__(self, k):
        if isinstance(k, int):
            return list(self.values())[k]
        return dict.__getitem__(self, k)

class _WrapCursor:
    def __init__(self, cur):
        self._cur = cur
        cols = [d[0] for d in (cur.description or [])]
        self._cols = cols
    def _row(self, r):
        if r is None: return None
        if not self._cols: return r
        return _DictRow(zip(self._cols, r))
    def fetchone(self): return self._row(self._cur.fetchone())
    def fetchall(self): return [self._row(r) for r in self._cur.fetchall()]
    def fetchmany(self, n): return [self._row(r) for r in self._cur.fetchmany(n)]
    def __iter__(self): return (self._row(r) for r in self._cur)

class _WrapConn:
    def __init__(self, raw):
        self._raw = raw
    def execute(self, sql, args=()):
        return _WrapCursor(self._raw.execute(sql, args))
    def executemany(self, sql, args):
        return self._raw.executemany(sql, args)
    def executescript(self, sql):
        return self._raw.executescript(sql)
    def commit(self): return self._raw.commit()
    def close(self): return self._raw.close()
    @property
    def row_factory(self): return None
    @row_factory.setter
    def row_factory(self, v): pass

def _connect():
    if TURSO_URL and TURSO_TOKEN:
        return _WrapConn(libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN))
    return _WrapConn(libsql.connect(DB_PATH))

def init_db():
    db = _connect()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL, nickname TEXT DEFAULT '', avatar TEXT DEFAULT '',
            bio TEXT DEFAULT '', token TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            description TEXT DEFAULT '', price REAL NOT NULL,
            original_price REAL DEFAULT 0, image TEXT DEFAULT '',
            category_id INTEGER DEFAULT 1, sales INTEGER DEFAULT 0,
            rating REAL DEFAULT 5.0, specs TEXT DEFAULT '[]',
            stock INTEGER DEFAULT 999, is_hot INTEGER DEFAULT 0,
            status INTEGER DEFAULT 1, seller_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            icon TEXT DEFAULT '📦',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_no TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL, total REAL NOT NULL,
            status TEXT DEFAULT 'pending', address TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL, product_name TEXT NOT NULL,
            product_image TEXT DEFAULT '', spec TEXT DEFAULT '',
            price REAL NOT NULL, quantity INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_name TEXT DEFAULT '匿名用户',
            last_message TEXT, unread INTEGER DEFAULT 0, status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL,
            sender_type TEXT NOT NULL, content TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- L1: Reviews
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL, order_id INTEGER DEFAULT 0,
            rating INTEGER NOT NULL DEFAULT 5, content TEXT DEFAULT '',
            images TEXT DEFAULT '[]', like_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- L1: Favorites
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- L1: User follows
        CREATE TABLE IF NOT EXISTS follows (
            id INTEGER PRIMARY KEY AUTOINCREMENT, follower_id INTEGER NOT NULL,
            following_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- L2: Group buys
        CREATE TABLE IF NOT EXISTS group_buys (
            id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
            initiator_id INTEGER NOT NULL, group_price REAL NOT NULL,
            required_count INTEGER DEFAULT 2, current_count INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active', expire_at TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS group_buy_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT, group_buy_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, order_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- L2: Coupons
        CREATE TABLE IF NOT EXISTS coupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            amount REAL NOT NULL, min_amount REAL DEFAULT 0,
            total_count INTEGER DEFAULT 100, used_count INTEGER DEFAULT 0,
            expire_days INTEGER DEFAULT 7,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS user_coupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            coupon_id INTEGER NOT NULL, status TEXT DEFAULT 'unused',
            used_at TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- L2: Seckill
        CREATE TABLE IF NOT EXISTS seckill_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
            seckill_price REAL NOT NULL, stock INTEGER NOT NULL,
            start_time TEXT NOT NULL, end_time TEXT NOT NULL,
            status TEXT DEFAULT 'upcoming',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- L2: Referral
        CREATE TABLE IF NOT EXISTS referral_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            code TEXT NOT NULL UNIQUE, total_earnings REAL DEFAULT 0,
            invited_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- L3: Posts (种草)
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            title TEXT DEFAULT '', content TEXT NOT NULL,
            images TEXT DEFAULT '[]', product_id INTEGER DEFAULT 0,
            topic_id INTEGER DEFAULT 0, like_count INTEGER DEFAULT 0,
            comment_count INTEGER DEFAULT 0, view_count INTEGER DEFAULT 0,
            media_type TEXT DEFAULT 'image', video_url TEXT DEFAULT '',
            status INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- L3: Post likes
        CREATE TABLE IF NOT EXISTS post_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- L3: Comments
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, content TEXT NOT NULL,
            parent_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- L3: Topics
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            icon TEXT DEFAULT '📌', post_count INTEGER DEFAULT 0,
            description TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- L3: Live rooms
        CREATE TABLE IF NOT EXISTS live_rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            title TEXT NOT NULL, cover TEXT DEFAULT '',
            product_ids TEXT DEFAULT '[]', viewer_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'offline',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- Addresses
        CREATE TABLE IF NOT EXISTS addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            name TEXT NOT NULL, phone TEXT NOT NULL,
            province TEXT DEFAULT '', city TEXT DEFAULT '', district TEXT DEFAULT '',
            detail TEXT NOT NULL, is_default INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- Search history
        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            keyword TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- Notifications
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            type TEXT NOT NULL, title TEXT NOT NULL, content TEXT DEFAULT '',
            related_id INTEGER DEFAULT 0, is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- Followers
        CREATE TABLE IF NOT EXISTS followers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            follow_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, follow_id)
        );
        -- Referral earnings
        CREATE TABLE IF NOT EXISTS referral_earnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL, order_id INTEGER NOT NULL,
            amount REAL NOT NULL, rate REAL DEFAULT 0.05,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        -- Cart (P0: was missing; api_client.dart calls /api/cart/*)
        CREATE TABLE IF NOT EXISTS cart (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL, spec TEXT DEFAULT '',
            quantity INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
    """)
    # Init products
    count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if count == 0:
        products = [
            ('iPhone 15 Pro Max 256GB','A17 Pro芯片，钛金属设计',8999,9999,'📱',1,12340,4.8,'["256GB","512GB","1TB"]',999,1),
            ('MacBook Pro 14 M3 Pro','18GB/512GB',12999,14999,'💻',2,8560,4.9,'["18GB","36GB"]',500,1),
            ('AirPods Pro 第二代','自适应音频 USB-C',1799,1899,'🎧',3,25600,4.7,'[]',2000,1),
            ('Apple Watch Ultra 2','49mm钛金属',6299,6499,'⌚',4,4320,4.9,'["海洋表带","野径回环"]',800,1),
            ('iPad Pro M4 11英寸','超视网膜XDR',7599,8499,'📋',5,6780,4.8,'["256GB","512GB","1TB"]',600,1),
            ('Sony A7M4 全画幅微单','3300万像素 4K60p',15499,16999,'📷',6,3210,4.8,'["单机身","24-70mm套机"]',300,1),
            ('MagSafe 充电器','15W无线快充',299,329,'🔌',7,89000,4.5,'[]',5000,0),
            ('Dyson V15 Detect','激光探测微尘',4990,5690,'🏠',8,12400,4.7,'[]',1000,0),
        ]
        db.executemany("INSERT INTO products (name,description,price,original_price,image,category_id,sales,rating,specs,stock,is_hot) VALUES (?,?,?,?,?,?,?,?,?,?,?)", products)
    # Init categories
    cc = db.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    if cc == 0:
        categories = [('手机','📱'),('电脑','💻'),('耳机','🎧'),('手表','⌚'),('平板','📋'),('相机','📷'),('配件','🔌'),('家电','🏠')]
        db.executemany("INSERT INTO categories (name,icon) VALUES (?,?)", categories)
    # Init topics
    tc = db.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    if tc == 0:
        topics = [('数码','📱','手机电脑数码产品'),('穿搭','👗','时尚穿搭分享'),('美妆','💄','护肤化妆好物'),('家居','🏠','家居生活好物'),('美食','🍔','美食推荐'),('运动','⚽','运动户外装备')]
        db.executemany("INSERT INTO topics (name,icon,description) VALUES (?,?,?)", topics)
    uc = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if uc == 0:
        import hashlib as _h
        pwd = _h.sha256('123456'.encode()).hexdigest()
        db.executemany("INSERT INTO users (phone,password,nickname) VALUES (?,?,?)", [('13800138000', pwd, '小明'), ('13900139000', pwd, '小红')])
    db.commit()
    db.close()

def notify(db, uid, type, title, content='', related_id=0):
    db.execute("INSERT INTO notifications (user_id,type,title,content,related_id) VALUES (?,?,?,?,?)",(uid,type,title,content,related_id))

def _specs_to_list(specs):
    # ponytail: 共享 helper，避免每个路由都写一遍 try/except json。specs 在 init_db 里就是 JSON 字符串
    if specs is None: return []
    if isinstance(specs, list): return specs
    if isinstance(specs, str) and specs.startswith('['):
        try: return json.loads(specs)
        except: return []
    return []

def make_token(uid):
    payload = f'{uid}:{int(time.time())}'
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()[:16]
    return base64.b64encode(f'{payload}:{sig}'.encode()).decode()

def verify_token(token):
    try:
        data = base64.b64decode(token.encode()).decode()
        uid_str, ts_str, sig = data.split(':')
        expected = hmac.new(SECRET, f'{uid_str}:{ts_str}'.encode(), hashlib.sha256).hexdigest()[:16]
        return int(uid_str) if sig == expected else None
    except:
        return None

class APIHandler(BaseHTTPRequestHandler):
    def _json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type','application/json')
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET,POST,PUT,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type,Authorization')
        self.end_headers()
        self.wfile.write(json.dumps(data,ensure_ascii=False).encode())

    def _serve_static(self, path):
        if path == '/': path = '/index.html'
        filepath = os.path.join(os.path.dirname(__file__), 'admin', path.lstrip('/'))
        if not os.path.isfile(filepath):
            self._json({'code':1,'msg':'not found'},404)
            return
        content_type, _ = mimetypes.guess_type(filepath)
        self.send_response(200)
        self.send_header('Content-Type', content_type or 'text/html')
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers()
        with open(filepath, 'rb') as f:
            self.wfile.write(f.read())

    def _auth(self, params):
        auth = self.headers.get('Authorization','')
        if auth.startswith('Bearer '):
            return verify_token(auth[7:])
        return verify_token(params.get('token',[''])[0])

    def _uid(self):
        auth = self.headers.get('Authorization','')
        if auth.startswith('Bearer '):
            return verify_token(auth[7:])
        return None

    def do_OPTIONS(self):
        self._json({})

    def do_GET(self):
        path = urlparse(self.path).path
        params = parse_qs(urlparse(self.path).query)
        # Root path
        if path == '/' or path == '':
            self._json({'code':0,'msg':'eShop Social API v1.0','endpoints':['/api/products','/api/categories','/api/cart','/api/orders','/api/user/login','/api/search','/api/live']})
            return
        # Serve static files from admin/ directory
        if not path.startswith('/api/'):
            self._serve_static(path)
            return
        uid = self._auth(params)
        try:
            db = _connect()
            # Search
            if path == '/api/search':
                q = params.get('q',[''])[0].strip()
                if not q: self._json({'code':0,'data':[]}); db.close(); return
                # Fuzzy search with relevance scoring
                rows = db.execute("""
                    SELECT *, (CASE WHEN name LIKE ? THEN 3 WHEN name LIKE ? THEN 2 WHEN description LIKE ? THEN 1 ELSE 0 END) as relevance
                    FROM products WHERE name LIKE ? OR description LIKE ? OR (SELECT name FROM categories WHERE id=products.category_id) LIKE ?
                    ORDER BY relevance DESC, sales DESC LIMIT 20
                """,(f'%{q}%',f'{q}%',f'%{q}%',f'%{q}%',f'%{q}%',f'%{q}%')).fetchall()
                self._json({'code':0,'data':[dict(r) for r in rows]})
                db.close(); return
            elif path == '/api/search/suggest':
                q = params.get('q',[''])[0].strip()
                if not q: self._json({'code':0,'data':[]}); db.close(); return
                rows = db.execute("SELECT DISTINCT name FROM products WHERE name LIKE ? LIMIT 8",(f'%{q}%',)).fetchall()
                self._json({'code':0,'data':[r['name'] for r in rows]})
                db.close(); return
            elif path == '/api/search/hot':
                rows = db.execute("SELECT name FROM products ORDER BY sales DESC LIMIT 8").fetchall()
                self._json({'code':0,'data':[r['name'] for r in rows]})
                db.close(); return
            elif path == '/api/search/history':
                if not uid: self._json({'code':0,'data':[]}); db.close(); return
                rows = db.execute("SELECT keyword FROM search_history WHERE user_id=? ORDER BY id DESC LIMIT 10",(uid,)).fetchall()
                self._json({'code':0,'data':[r['keyword'] for r in rows]})
                db.close(); return
            # Notifications
            elif path == '/api/notifications':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 30",(uid,)).fetchall()
                self._json({'code':0,'data':[dict(r) for r in rows]})
            elif path == '/api/notification/read':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                nid = params.get('id',[None])[0]
                if nid: db.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?",(nid,uid))
                else: db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(uid,))
                db.commit()
                self._json({'code':0,'msg':'ok'})
            elif path == '/api/notification/unread':
                if not uid: self._json({'code':0,'data':0}); db.close(); return
                cnt = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",(uid,)).fetchone()[0]
                self._json({'code':0,'data':cnt})
            # User profile
            elif path == '/api/user/profile':
                uid2 = params.get('user_id',[None])[0]
                if not uid2: self._json({'code':1,'msg':'缺少用户ID'},400); db.close(); return
                try: uid2 = int(uid2)
                except: self._json({'code':1,'msg':'无效用户ID'},400); db.close(); return
                u = db.execute("SELECT id,nickname,phone,avatar,bio,created_at FROM users WHERE id=?",(uid2,)).fetchone()
                if not u: self._json({'code':1,'msg':'用户不存在'},404); db.close(); return
                posts = db.execute("SELECT * FROM posts WHERE user_id=? AND status=1 ORDER BY id DESC LIMIT 10",(uid2,)).fetchall()
                followers = db.execute("SELECT COUNT(*) FROM followers WHERE follow_id=?",(uid2,)).fetchone()[0]
                following = db.execute("SELECT COUNT(*) FROM followers WHERE user_id=?",(uid2,)).fetchone()[0]
                is_following = 0
                if uid: is_following = db.execute("SELECT COUNT(*) FROM followers WHERE user_id=? AND follow_id=?",(uid,uid2)).fetchone()[0]
                self._json({'code':0,'data':{'user':dict(u),'posts':[dict(p) for p in posts],'followers':followers,'following':following,'is_following':is_following>0}})
                db.close(); return
            elif path == '/api/followers':
                uid2 = params.get('user_id',[uid])[0]
                try: uid2 = int(uid2)
                except: uid2 = uid
                rows = db.execute("SELECT u.id,u.nickname,u.avatar FROM followers f JOIN users u ON f.user_id=u.id WHERE f.follow_id=? ORDER BY f.id DESC LIMIT 50",(uid2,)).fetchall()
                self._json({'code':0,'data':[dict(r) for r in rows]})
                db.close(); return
            elif path == '/api/following':
                uid2 = params.get('user_id',[uid])[0]
                try: uid2 = int(uid2)
                except: uid2 = uid
                rows = db.execute("SELECT u.id,u.nickname,u.avatar FROM followers f JOIN users u ON f.follow_id=u.id WHERE f.user_id=? ORDER BY f.id DESC LIMIT 50",(uid2,)).fetchall()
                self._json({'code':0,'data':[dict(r) for r in rows]})
                db.close(); return
            elif path == '/api/referral/earnings':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                rows = db.execute("SELECT r.*,u.nickname as buyer_name FROM referral_earnings r LEFT JOIN users u ON r.buyer_id=u.id WHERE r.user_id=? ORDER BY r.id DESC LIMIT 50",(uid,)).fetchall()
                total = db.execute("SELECT COALESCE(SUM(amount),0) FROM referral_earnings WHERE user_id=? AND status='settled'",(uid,)).fetchone()[0]
                self._json({'code':0,'data':{'earnings':[dict(r) for r in rows],'total':total}})
                db.close(); return
            # My products (seller)
            elif path == '/api/my/products':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                rows = db.execute("SELECT * FROM products WHERE seller_id=? ORDER BY id DESC",(uid,)).fetchall()
                self._json({'code':0,'data':[dict(r) for r in rows]})
                db.close(); return
            elif path == '/api/videos':
                rows = db.execute("SELECT p.*,u.nickname,u.avatar FROM posts p JOIN users u ON p.user_id=u.id WHERE p.media_type='video' AND p.status=1 ORDER BY p.id DESC LIMIT 30").fetchall()
                self._json({'code':0,'data':[dict(r) for r in rows]})
                db.close(); return
            if path == '/api/products':
                # P1-1: 支持 category_id 过滤 + page/limit 分页，前端 category_page 需要
                cat_id = params.get('category_id',[None])[0]
                page = int(params.get('page',['1'])[0] or 1)
                limit = int(params.get('limit',['50'])[0] or 50)
                if page < 1: page = 1
                if limit < 1 or limit > 200: limit = 50
                offset = (page - 1) * limit
                if cat_id:
                    rows = db.execute("SELECT * FROM products WHERE status=1 AND category_id=? ORDER BY is_hot DESC, sales DESC LIMIT ? OFFSET ?",(cat_id,limit,offset)).fetchall()
                else:
                    rows = db.execute("SELECT * FROM products WHERE status=1 ORDER BY is_hot DESC, sales DESC LIMIT ? OFFSET ?",(limit,offset)).fetchall()
                self._json([dict(r) for r in rows])
            elif path == '/api/products/hot':
                rows = db.execute("SELECT * FROM products WHERE is_hot=1 AND status=1 ORDER BY sales DESC LIMIT 10").fetchall()
                self._json([dict(r) for r in rows])
            elif path == '/api/categories':
                # P0: 前端 api_client.getCategories 调这里，原来根本没实现，必 404
                rows = db.execute("SELECT * FROM categories ORDER BY id ASC").fetchall()
                self._json({'code':0,'data':[dict(r) for r in rows]})
            elif path.startswith('/api/cart'):
                # P0: 购物车整套路由原来不存在，api_client.dart:123 起六个方法全跑空
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                # GET /api/cart/{uid}  -> 该用户的购物车，附带商品快照
                parts = path.split('/')
                if len(parts) == 3:
                    self._json({'code':1,'msg':'缺少用户ID'},400); db.close(); return
                target_uid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else uid
                rows = db.execute("""SELECT c.id,c.product_id,c.spec,c.quantity,p.name,p.price,p.image,p.stock
                    FROM cart c LEFT JOIN products p ON c.product_id=p.id
                    WHERE c.user_id=? ORDER BY c.id DESC""",(target_uid,)).fetchall()
                self._json({'code':0,'data':[dict(r) for r in rows]})
                db.close(); return
            elif path.startswith('/api/products/') and len(path.split('/'))==4:
                pid = path.split('/')[-1]
                row = db.execute("SELECT * FROM products WHERE id=?",(pid,)).fetchone()
                if row:
                    d = dict(row)
                    # specs 存的是 JSON 字符串，前端 Product 直接 cast 会出错，统一成 list
                    d['images'] = [d.get('image','')] if d.get('image') else []
                    d['specs'] = _specs_to_list(d.get('specs'))
                    reviews = db.execute("SELECT r.*,u.nickname,u.avatar FROM reviews r LEFT JOIN users u ON r.user_id=u.id WHERE r.product_id=? ORDER BY r.id DESC LIMIT 20",(pid,)).fetchall()
                    d['reviews'] = [dict(r) for r in reviews]
                    self._json({'code':0,'data':d})
                else:
                    self._json({'code':1,'msg':'not found'},404)
            # Orders
            elif path == '/api/orders':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                rows = db.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall()
                orders = []
                for r in rows:
                    o = dict(r)
                    items = db.execute("SELECT * FROM order_items WHERE order_id=?",(r['id'],)).fetchall()
                    o['items'] = [dict(i) for i in items]
                    orders.append(o)
                self._json(orders)
            # Reviews
            elif path == '/api/reviews':
                pid = params.get('product_id',[''])[0]
                rows = db.execute("SELECT r.*,u.nickname,u.avatar FROM reviews r LEFT JOIN users u ON r.user_id=u.id WHERE r.product_id=? ORDER BY r.id DESC",(pid,)).fetchall()
                # P1-3: 加壳 {code:0,data:[]} 让前端 res.data['data'] as List 不抛
                self._json({'code':0,'data':[dict(r) for r in rows]})
                db.close(); return
            # Favorites
            elif path == '/api/favorites':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                rows = db.execute("SELECT f.*,p.name,p.price,p.image FROM favorites f LEFT JOIN products p ON f.product_id=p.id WHERE f.user_id=? ORDER BY f.id DESC",(uid,)).fetchall()
                self._json({'code':0,'data':[dict(r) for r in rows]})
                db.close(); return
            # User profile
            elif path.startswith('/api/user/') and 'profile' in path:
                target_id = int(path.split('/')[-2]) if path.split('/')[-2].isdigit() else uid
                row = db.execute("SELECT id,nickname,avatar,bio,created_at FROM users WHERE id=?",(target_id,)).fetchone()
                if row:
                    d = dict(row)
                    d['follower_count'] = db.execute("SELECT COUNT(*) FROM follows WHERE following_id=?",(target_id,)).fetchone()[0]
                    d['following_count'] = db.execute("SELECT COUNT(*) FROM follows WHERE follower_id=?",(target_id,)).fetchone()[0]
                    d['post_count'] = db.execute("SELECT COUNT(*) FROM posts WHERE user_id=? AND status=1",(target_id,)).fetchone()[0]
                    self._json(d)
                else:
                    self._json({'code':1,'msg':'用户不存在'},404)
            # User
            elif path == '/api/user':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                row = db.execute("SELECT id,nickname,avatar,bio,phone,created_at FROM users WHERE id=?",(uid,)).fetchone()
                self._json(dict(row) if row else {})
            # Group buys
            elif path == '/api/group_buys':
                rows = db.execute("SELECT g.*,p.name,p.image,p.price as original_price FROM group_buys g LEFT JOIN products p ON g.product_id=p.id WHERE g.status='active' ORDER BY g.id DESC").fetchall()
                self._json([dict(r) for r in rows])
            elif path.startswith('/api/group_buys/') and len(path.split('/'))==4:
                gid = path.split('/')[-1]
                row = db.execute("SELECT g.*,p.name,p.image FROM group_buys g LEFT JOIN products p ON g.product_id=p.id WHERE g.id=?",(gid,)).fetchone()
                if row:
                    d = dict(row)
                    parts = db.execute("SELECT gp.*,u.nickname,u.avatar FROM group_buy_participants gp LEFT JOIN users u ON gp.user_id=u.id WHERE gp.group_buy_id=?",(gid,)).fetchall()
                    d['participants'] = [dict(p) for p in parts]
                    self._json(d)
                else:
                    self._json({'code':1,'msg':'not found'},404)
            # Coupons
            elif path == '/api/coupons':
                rows = db.execute("SELECT * FROM coupons ORDER BY id DESC").fetchall()
                self._json([dict(r) for r in rows])
            elif path == '/api/user_coupons':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                rows = db.execute("SELECT uc.*,c.title,c.amount,c.min_amount FROM user_coupons uc LEFT JOIN coupons c ON uc.coupon_id=c.id WHERE uc.user_id=? AND uc.status='unused'",(uid,)).fetchall()
                self._json([dict(r) for r in rows])
            elif path == '/api/coupons/my':
                # P0: api_client.getMyCoupons 调这里（路径和 user_coupons 不一致）
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                rows = db.execute("SELECT uc.*,c.title,c.amount,c.min_amount FROM user_coupons uc LEFT JOIN coupons c ON uc.coupon_id=c.id WHERE uc.user_id=? AND uc.status='unused'",(uid,)).fetchall()
                self._json({'code':0,'data':[dict(r) for r in rows]})
                db.close(); return
            # Seckill
            elif path == '/api/seckill':
                rows = db.execute("SELECT s.*,p.name,p.image,p.price as original_price, 0 as sold_count FROM seckill_events s LEFT JOIN products p ON s.product_id=p.id WHERE s.status!='ended' ORDER BY s.start_time").fetchall()
                # P1-5: 加壳 + sold_count 字段(0 baseline,真实存量靠 stock 列；schema 未加 sold_count 列故 0 作 placeholder)
                self._json({'code':0,'data':[dict(r) for r in rows]})
                db.close(); return
            # Referral
            elif path == '/api/referral':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                row = db.execute("SELECT * FROM referral_codes WHERE user_id=?",(uid,)).fetchone()
                if not row:
                    code = uuid.uuid4().hex[:8].upper()
                    db.execute("INSERT INTO referral_codes (user_id,code) VALUES (?,?)",(uid,code))
                    db.commit()
                    row = db.execute("SELECT * FROM referral_codes WHERE user_id=?",(uid,)).fetchone()
                self._json(dict(row))
            # Posts (种草)
            elif path == '/api/posts':
                tid = params.get('topic_id',[''])[0]
                # P1-6: 加 is_liked + like_count 子查询，前端 social_page 列表需要知道当前用户是否点赞
                if tid:
                    rows = db.execute("SELECT p.*,u.nickname,u.avatar,(CASE WHEN ? IS NULL THEN 0 WHEN EXISTS(SELECT 1 FROM post_likes WHERE post_id=p.id AND user_id=?) THEN 1 ELSE 0 END) as is_liked FROM posts p LEFT JOIN users u ON p.user_id=u.id WHERE p.topic_id=? AND p.status=1 ORDER BY p.id DESC",(uid,uid,tid)).fetchall()
                else:
                    rows = db.execute("SELECT p.*,u.nickname,u.avatar,(CASE WHEN ? IS NULL THEN 0 WHEN EXISTS(SELECT 1 FROM post_likes WHERE post_id=p.id AND user_id=?) THEN 1 ELSE 0 END) as is_liked FROM posts p LEFT JOIN users u ON p.user_id=u.id WHERE p.status=1 ORDER BY p.id DESC LIMIT 30",(uid,uid)).fetchall()
                self._json({'code':0,'data':[dict(r) for r in rows]})
                db.close(); return
            elif path.startswith('/api/posts/') and len(path.split('/'))==4:
                pid = path.split('/')[-1]
                row = db.execute("SELECT p.*,u.nickname,u.avatar FROM posts p LEFT JOIN users u ON p.user_id=u.id WHERE p.id=?",(pid,)).fetchone()
                if row:
                    d = dict(row)
                    comments = db.execute("SELECT c.*,u.nickname,u.avatar FROM comments c LEFT JOIN users u ON c.user_id=u.id WHERE c.post_id=? ORDER BY c.id ASC",(pid,)).fetchall()
                    d['comments'] = [dict(c) for c in comments]
                    liked = db.execute("SELECT 1 FROM post_likes WHERE post_id=? AND user_id=?",(pid,uid or 0)).fetchone()
                    d['is_liked'] = bool(liked)
                    db.execute("UPDATE posts SET view_count=view_count+1 WHERE id=?",(pid,))
                    db.commit()
                    self._json(d)
                else:
                    self._json({'code':1,'msg':'not found'},404)
            # Topics
            elif path == '/api/topics':
                rows = db.execute("SELECT * FROM topics ORDER BY post_count DESC").fetchall()
                self._json([dict(r) for r in rows])
            # Live
            elif path == '/api/live':
                rows = db.execute("SELECT l.*,u.nickname,u.avatar FROM live_rooms l LEFT JOIN users u ON l.user_id=u.id WHERE l.status='online' ORDER BY l.viewer_count DESC").fetchall()
                self._json([dict(r) for r in rows])
            # RTC Signaling GET
            elif path == '/api/rtc/status':
                rid = params.get('room_id',[None])[0]
                try: rid = int(rid)
                except: pass
                self._json({'live': rid in rtc_rooms})
            elif path == '/api/rtc/offers':
                rid = params.get('room_id',[None])[0]
                try: rid = int(rid)
                except: pass
                r = rtc_rooms.get(rid, {})
                self._json(r.get('offers',{}))
            elif path == '/api/rtc/ices':
                rid = params.get('room_id',[None])[0]
                try: rid = int(rid)
                except: pass
                r = rtc_rooms.get(rid, {})
                ices = r.get('ices',[])
                # Return and clear
                self._json(ices)
                rtc_rooms[rid]['ices'] = []
            elif path == '/api/rtc/viewers':
                rid = params.get('room_id',[None])[0]
                try: rid = int(rid)
                except: pass
                r = rtc_rooms.get(rid, {})
                self._json({'count':len(r.get('viewers',set()))})
            elif path == '/api/rtc/answer':
                rid = params.get('room_id',[None])[0]
                try: rid = int(rid)
                except: pass
                # P0: 原来 pop(str(id(self)))，每次请求 handler 都是不同对象，answer 永远取不出。
                # POST /api/rtc/answer 用 peer 作为 key（前端不发就是 ''），GET 也用 peer 一致
                peer = params.get('peer',[''])[0]
                r = rtc_rooms.get(rid, {})
                self._json({'sdp': r.get('answers',{}).pop(peer, None)})
            elif path == '/api/rtc/chat':
                rid = params.get('room_id',[None])[0]
                try: rid = int(rid)
                except: pass
                self._json(rtc_rooms.get(rid,{}).get('chat',[]))
            # KOL
            elif path == '/api/kol':
                rows = db.execute("SELECT u.id,u.nickname,u.avatar,u.bio,(SELECT COUNT(*) FROM follows WHERE following_id=u.id) as followers FROM users u ORDER BY followers DESC LIMIT 20").fetchall()
                self._json([dict(r) for r in rows])
            # Chat
            elif path == '/api/chat':
                action = params.get('action',[''])[0]
                if action == 'sessions':
                    rows = db.execute("SELECT * FROM chat_sessions ORDER BY updated_at DESC").fetchall()
                    self._json({'code':0,'data':[dict(r) for r in rows]})
                elif action == 'messages':
                    sid = params.get('session_id',[''])[0]
                    if sid:
                        rows = db.execute("SELECT * FROM chat_messages WHERE session_id=? ORDER BY id ASC",(sid,)).fetchall()
                        self._json({'code':0,'data':[dict(r) for r in rows]})
                    else:
                        self._json({'code':0,'data':[]})
                else:
                    self._json({'code':1,'msg':'unknown action'})
            else:
                self._json({'code':1,'msg':'not found'},404)
            db.close()
        except Exception as e:
            self._json({'code':1,'msg':str(e)},500)

    def do_POST(self):
        import sys; print(f'POST path={self.path!r}', file=sys.stderr)
        path = urlparse(self.path).path
        print(f'POST parsed={path!r}', file=sys.stderr)
        params = parse_qs(urlparse(self.path).query)
        length = int(self.headers.get('Content-Length',0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}
        uid = self._uid()
        print(f'POST uid={uid}', file=sys.stderr)
        try:
            db = _connect()
            print(f'POST routing...', file=sys.stderr)
            # User
            if path == '/api/user/register':
                phone = body.get('phone','').strip()
                pwd = body.get('password','').strip()
                nick = body.get('nickname','').strip() or '用户'+phone[-4:]
                if not phone or not pwd: self._json({'code':1,'msg':'手机号和密码不能为空'},400); db.close(); return
                if db.execute("SELECT id FROM users WHERE phone=?",(phone,)).fetchone():
                    self._json({'code':1,'msg':'手机号已注册'},400); db.close(); return
                hpwd = hashlib.sha256(pwd.encode()).hexdigest()
                db.execute("INSERT INTO users (phone,password,nickname) VALUES (?,?,?)",(phone,hpwd,nick))
                db.commit()
                uid2 = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                token = make_token(uid2)
                db.execute("UPDATE users SET token=? WHERE id=?",(token,uid2)); db.commit()
                # Auto create referral code
                code = uuid.uuid4().hex[:8].upper()
                db.execute("INSERT OR IGNORE INTO referral_codes (user_id,code) VALUES (?,?)",(uid2,code)); db.commit()
                self._json({'code':0,'data':{'id':uid2,'token':token,'nickname':nick,'phone':phone}})
            elif path == '/api/user/login':
                phone = body.get('phone','').strip()
                pwd = body.get('password','').strip()
                hpwd = hashlib.sha256(pwd.encode()).hexdigest()
                row = db.execute("SELECT * FROM users WHERE phone=? AND password=?",(phone,hpwd)).fetchone()
                if not row: self._json({'code':1,'msg':'手机号或密码错误'},400); db.close(); return
                token = make_token(row['id'])
                db.execute("UPDATE users SET token=? WHERE id=?",(token,row['id'])); db.commit()
                self._json({'code':0,'data':{'id':row['id'],'token':token,'nickname':row['nickname'],'phone':row['phone'],'avatar':row['avatar'],'bio':row['bio']}})
            # Update user
            elif path == '/api/user/update':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                for field in ['nickname','avatar','bio']:
                    if field in body:
                        db.execute(f"UPDATE users SET {field}=? WHERE id=?",(body[field],uid))
                db.commit()
                row = db.execute("SELECT id,nickname,avatar,bio FROM users WHERE id=?",(uid,)).fetchone()
                self._json({'code':0,'data':dict(row)})
            # Products CRUD (admin)
            elif path == '/api/products':
                action = body.get('action','create')
                if action == 'create':
                    name = body.get('name','').strip()
                    if not name: self._json({'code':1,'msg':'商品名不能为空'},400); db.close(); return
                    db.execute("INSERT INTO products (name,description,price,original_price,image,category_id,sales,rating,specs,stock,is_hot) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (name, body.get('description',''), body.get('price',0), body.get('original_price',0),
                         body.get('image','📦'), body.get('category_id',1), 0, 5.0,
                         body.get('specs','[]'), body.get('stock',999), body.get('is_hot',0)))
                    db.commit()
                    pid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                    self._json({'code':0,'data':{'id':pid}})
                elif action == 'update':
                    pid = body.get('id')
                    if not pid: self._json({'code':1,'msg':'缺少商品ID'},400); db.close(); return
                    db.execute("UPDATE products SET name=?,description=?,price=?,original_price=?,image=?,category_id=?,specs=?,stock=?,is_hot=? WHERE id=?",
                        (body.get('name',''), body.get('description',''), body.get('price',0), body.get('original_price',0),
                         body.get('image',''), body.get('category_id',1), body.get('specs','[]'), body.get('stock',999), body.get('is_hot',0), pid))
                    db.commit()
                    self._json({'code':0,'data':{'id':pid}})
                elif action == 'delete':
                    pid = body.get('id')
                    if not pid: self._json({'code':1,'msg':'缺少商品ID'},400); db.close(); return
                    db.execute("DELETE FROM products WHERE id=?",(pid,))
                    db.commit()
                    self._json({'code':0,'data':{}})
                else:
                    self._json({'code':1,'msg':'unknown action'})
            # Cart  (P0: 前端 api_client.dart:128 起的加购/改数/删除原本全部 404)
            elif path == '/api/cart':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                action = body.get('action','add')
                if action == 'add':
                    pid = body.get('product_id'); spec = body.get('spec','') or ''; qty = body.get('quantity',1)
                    if not pid: self._json({'code':1,'msg':'缺少商品ID'},400); db.close(); return
                    # 同商品同规格合并
                    existing = db.execute("SELECT id,quantity FROM cart WHERE user_id=? AND product_id=? AND spec=?",(uid,pid,spec)).fetchone()
                    if existing:
                        db.execute("UPDATE cart SET quantity=quantity+? WHERE id=?",(qty,existing['id']))
                    else:
                        db.execute("INSERT INTO cart (user_id,product_id,spec,quantity) VALUES (?,?,?,?)",(uid,pid,spec,qty))
                    db.commit()
                    self._json({'code':0,'msg':'已加入购物车'})
                elif action == 'set_qty':
                    cid = body.get('id'); qty = body.get('quantity',1)
                    if not cid: self._json({'code':1,'msg':'缺少ID'},400); db.close(); return
                    if qty <= 0:
                        db.execute("DELETE FROM cart WHERE id=? AND user_id=?",(cid,uid))
                    else:
                        db.execute("UPDATE cart SET quantity=? WHERE id=? AND user_id=?",(qty,cid,uid))
                    db.commit(); self._json({'code':0,'msg':'ok'})
                elif action == 'remove':
                    cid = body.get('id')
                    if not cid: self._json({'code':1,'msg':'缺少ID'},400); db.close(); return
                    db.execute("DELETE FROM cart WHERE id=? AND user_id=?",(cid,uid))
                    db.commit(); self._json({'code':0,'msg':'ok'})
                elif action == 'clear':
                    db.execute("DELETE FROM cart WHERE user_id=?",(uid,))
                    db.commit(); self._json({'code':0,'msg':'已清空'})
                else:
                    self._json({'code':1,'msg':'unknown action'},400)
            elif path == '/api/orders':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                items = body.get('items',[])
                address = body.get('address','{}')
                if not items: self._json({'code':1,'msg':'商品不能为空'},400); db.close(); return
                total = 0; order_items = []
                for it in items:
                    pid = it.get('product_id',0); qty = it.get('quantity',1); spec = it.get('spec','')
                    row = db.execute("SELECT * FROM products WHERE id=?",(pid,)).fetchone()
                    if not row: self._json({'code':1,'msg':f'商品{pid}不存在'},400); db.close(); return
                    price = row['price']
                    order_items.append({'pid':pid,'name':row['name'],'image':row['image'],'spec':spec,'price':price,'qty':qty})
                    total += price * qty
                ono = 'ES'+time.strftime('%Y%m%d%H%M%S')+uuid.uuid4().hex[:4].upper()
                db.execute("INSERT INTO orders (order_no,user_id,total,status,address) VALUES (?,?,?,'pending',?)",(ono,uid,total,address))
                oid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                for oi in order_items:
                    db.execute("INSERT INTO order_items (order_id,product_id,product_name,product_image,spec,price,quantity) VALUES (?,?,?,?,?,?,?)",(oid,oi['pid'],oi['name'],oi['image'],oi['spec'],oi['price'],oi['qty']))
                # Referral commission
                ref = body.get('ref')
                if ref:
                    ref_user = db.execute("SELECT user_id FROM referral_codes WHERE code=?",(ref,)).fetchone()
                    if ref_user and ref_user['user_id'] != uid:
                        commission = round(total * 0.05, 2)
                        db.execute("INSERT INTO referral_earnings (user_id,buyer_id,order_id,amount,rate) VALUES (?,?,?,?,0.05)",(ref_user['user_id'],uid,oid,commission))
                        notify(db, ref_user['user_id'], 'order', '分销佣金', f'用户通过你的链接下单，佣金 ¥{commission}', oid)
                db.commit()
                self._json({'code':0,'data':{'order_id':oid,'order_no':ono,'total':total}})
            # Order actions
            elif path == '/api/order/pay':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                oid = body.get('order_id')
                db.execute("UPDATE orders SET status='paid',pay_time=datetime('now') WHERE id=? AND user_id=?",(oid,uid))
                notify(db, uid, 'order', '支付成功', f'订单 #{oid} 已支付，等待发货', oid)
                db.commit()
                self._json({'code':0,'msg':'支付成功'})
            elif path == '/api/order/cancel':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                oid = body.get('order_id')
                db.execute("UPDATE orders SET status='cancelled' WHERE id=? AND user_id=? AND status IN ('pending','paid')",(oid,uid))
                db.commit()
                self._json({'code':0,'msg':'已取消'})
            elif path == '/api/order/confirm':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                oid = body.get('order_id')
                db.execute("UPDATE orders SET status='completed',confirm_time=datetime('now') WHERE id=? AND user_id=? AND status='shipped'",(oid,uid))
                db.commit()
                self._json({'code':0,'msg':'已确认收货'})
            elif path == '/api/order/detail':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                oid = body.get('order_id')
                order = db.execute("SELECT * FROM orders WHERE id=? AND user_id=?",(oid,uid)).fetchone()
                if not order: self._json({'code':1,'msg':'订单不存在'},404); db.close(); return
                items = db.execute("SELECT * FROM order_items WHERE order_id=?",(oid,)).fetchall()
                self._json({'code':0,'data':{'order':dict(order),'items':[dict(i) for i in items]}})
            # Seckill order — 秒杀价专用下单，前端 seckill_page 调这里
            elif path == '/api/seckill/order':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                sid = body.get('seckill_id')
                if not sid: self._json({'code':1,'msg':'缺少秒杀ID'},400); db.close(); return
                ev = db.execute("SELECT * FROM seckill_events WHERE id=? AND status!='ended'",(sid,)).fetchone()
                if not ev: self._json({'code':1,'msg':'秒杀不存在或已结束'},400); db.close(); return
                # 时间窗校验
                now = time.strftime('%Y-%m-%d %H:%M:%S',time.localtime())
                if ev['start_time'] and now < ev['start_time']: self._json({'code':1,'msg':'秒杀未开始'},400); db.close(); return
                if ev['end_time'] and now > ev['end_time']: self._json({'code':1,'msg':'秒杀已结束'},400); db.close(); return
                # 库存
                if ev['stock'] <= 0: self._json({'code':1,'msg':'已售罄'},400); db.close(); return
                # 创建订单(按秒杀价)
                total = ev['seckill_price']
                p = db.execute("SELECT name,image FROM products WHERE id=?",(ev['product_id'],)).fetchone()
                ono = 'SK'+time.strftime('%Y%m%d%H%M%S')+uuid.uuid4().hex[:4].upper()
                db.execute("INSERT INTO orders (order_no,user_id,total,status,address) VALUES (?,?,?,'pending','{}')",(ono,uid,total))
                oid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                db.execute("INSERT INTO order_items (order_id,product_id,product_name,product_image,spec,price,quantity) VALUES (?,?,?,?,?,?,?)",(oid,ev['product_id'],p['name'] if p else '',p['image'] if p else '','秒杀',total,1))
                db.execute("UPDATE seckill_events SET stock=stock-1 WHERE id=?",(sid,))
                if ev['stock']-1 <= 0:
                    db.execute("UPDATE seckill_events SET status='ended' WHERE id=?",(sid,))
                db.commit()
                self._json({'code':0,'data':{'order_id':oid,'order_no':ono,'total':total}})
            # Address
            elif path == '/api/addresses':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                rows = db.execute("SELECT * FROM addresses WHERE user_id=? ORDER BY is_default DESC,id DESC",(uid,)).fetchall()
                self._json({'code':0,'data':[dict(r) for r in rows]})
            elif path == '/api/address/add':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                name = body.get('name',''); phone=body.get('phone',''); province=body.get('province',''); city=body.get('city',''); district=body.get('district',''); detail=body.get('detail',''); is_default=body.get('is_default',0)
                if is_default: db.execute("UPDATE addresses SET is_default=0 WHERE user_id=?",(uid,))
                db.execute("INSERT INTO addresses (user_id,name,phone,province,city,district,detail,is_default) VALUES (?,?,?,?,?,?,?,?)",(uid,name,phone,province,city,district,detail,is_default))
                db.commit()
                self._json({'code':0,'msg':'添加成功'})
            elif path == '/api/address/update':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                aid = body.get('id'); is_default=body.get('is_default',0)
                if is_default: db.execute("UPDATE addresses SET is_default=0 WHERE user_id=?",(uid,))
                for f in ['name','phone','province','city','district','detail','is_default']:
                    if f in body: db.execute(f"UPDATE addresses SET {f}=? WHERE id=? AND user_id=?",(body[f],aid,uid))
                db.commit()
                self._json({'code':0,'msg':'更新成功'})
            elif path == '/api/address/delete':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                db.execute("DELETE FROM addresses WHERE id=? AND user_id=?",(body.get('id'),uid))
                db.commit()
                self._json({'code':0,'msg':'已删除'})
            # Save search history
            elif path == '/api/search/history':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                kw = body.get('keyword','').strip()
                if kw:
                    db.execute("DELETE FROM search_history WHERE user_id=? AND keyword=?",(uid,kw))
                    db.execute("INSERT INTO search_history (user_id,keyword) VALUES (?,?)",(uid,kw))
                    db.commit()
                self._json({'code':0,'msg':'ok'})
            # Follow / Unfollow  (P0: 此前 elif 分支被下方第二次定义覆盖，bug)
            # 兼容两种前端调用：
            #   1) {user_id: X}                     -> followers 表 (api_client.dart 没用，但旧 admin 用)
            #   2) {action: 'follow'|'unfollow', target_id: X}  -> follows 表 (社交帖子流)
            # 为兼容历史两边都写。
            elif path == '/api/follow':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                action = body.get('action')
                target = body.get('target_id') or body.get('user_id')
                if action is None:
                    action = 'follow' if 'user_id' in body else 'follow'
                if target is None:
                    self._json({'code':1,'msg':'参数错误'},400); db.close(); return
                if action == 'follow':
                    if uid == target: self._json({'code':1,'msg':'不能关注自己'},400); db.close(); return
                    db.execute("INSERT OR IGNORE INTO followers (user_id,follow_id) VALUES (?,?)",(uid,target))
                    db.execute("INSERT OR IGNORE INTO follows (follower_id,following_id) VALUES (?,?)",(uid,target))
                    notify(db, target, 'follow', '新粉丝', '有用户关注了你！')
                    db.commit(); self._json({'code':0,'msg':'已关注'})
                elif action == 'unfollow':
                    db.execute("DELETE FROM followers WHERE user_id=? AND follow_id=?",(uid,target))
                    db.execute("DELETE FROM follows WHERE follower_id=? AND following_id=?",(uid,target))
                    db.commit(); self._json({'code':0,'msg':'已取关'})
                else:
                    self._json({'code':1,'msg':'unknown action'},400)
            # Seller product CRUD
            elif path == '/api/product/add':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                name = body.get('name','').strip()
                if not name: self._json({'code':1,'msg':'请输入商品名称'},400); db.close(); return
                price = body.get('price', 0)
                db.execute("INSERT INTO products (name,description,price,original_price,image,category_id,stock,seller_id) VALUES (?,?,?,?,?,?,?,?)",
                    (name, body.get('description',''), price, body.get('original_price',price*1.5),
                     body.get('image','📦'), body.get('category_id',1), body.get('stock',999), uid))
                pid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                db.commit()
                self._json({'code':0,'data':{'id':pid},'msg':'发布成功'})
            elif path == '/api/product/edit':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                pid = body.get('id')
                if not pid: self._json({'code':1,'msg':'缺少商品ID'},400); db.close(); return
                db.execute("UPDATE products SET name=?,description=?,price=?,original_price=?,image=?,category_id=?,stock=? WHERE id=? AND seller_id=?",
                    (body.get('name'), body.get('description',''), body.get('price'), body.get('original_price'),
                     body.get('image','📦'), body.get('category_id',1), body.get('stock',999), pid, uid))
                db.commit()
                self._json({'code':0,'msg':'更新成功'})
            elif path == '/api/product/delete':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                pid = body.get('id')
                db.execute("UPDATE products SET status=0 WHERE id=? AND seller_id=?",(pid,uid))
                db.commit()
                self._json({'code':0,'msg':'已下架'})
            # Reviews
            elif path == '/api/reviews':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                pid = body.get('product_id'); rating = body.get('rating',5); content = body.get('content',''); images = body.get('images','[]')
                db.execute("INSERT INTO reviews (user_id,product_id,rating,content,images) VALUES (?,?,?,?,?)",(uid,pid,rating,content,str(images)))
                # Update product avg rating
                avg = db.execute("SELECT AVG(rating) FROM reviews WHERE product_id=?",(pid,)).fetchone()[0]
                db.execute("UPDATE products SET rating=? WHERE id=?",(round(avg,1),pid))
                db.commit()
                self._json({'code':0,'msg':'评价成功'})
            # Favorites
            elif path == '/api/favorites':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                action = body.get('action','add'); pid = body.get('product_id')
                if action == 'add':
                    db.execute("INSERT OR IGNORE INTO favorites (user_id,product_id) VALUES (?,?)",(uid,pid))
                elif action == 'remove':
                    db.execute("DELETE FROM favorites WHERE user_id=? AND product_id=?",(uid,pid))
                db.commit()
                self._json({'code':0,'msg':'ok'})
            # Follow 第二处已并入上面的合并分支，删除重复定义。
            # Group buys
            elif path == '/api/group_buys':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                action = body.get('action','create')
                if action == 'create':
                    pid = body.get('product_id'); price = body.get('group_price'); count = body.get('required_count',2)
                    expire = time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(time.time()+86400))
                    db.execute("INSERT INTO group_buys (product_id,initiator_id,group_price,required_count,expire_at) VALUES (?,?,?,?,?)",(pid,uid,price,count,expire))
                    gid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                    db.execute("INSERT INTO group_buy_participants (group_buy_id,user_id) VALUES (?,?)",(gid,uid))
                    db.commit()
                    self._json({'code':0,'data':{'id':gid}})
                elif action == 'join':
                    gid = body.get('group_buy_id')
                    gb = db.execute("SELECT * FROM group_buys WHERE id=? AND status='active'",(gid,)).fetchone()
                    if not gb: self._json({'code':1,'msg':'拼团不存在或已结束'},400); db.close(); return
                    if db.execute("SELECT 1 FROM group_buy_participants WHERE group_buy_id=? AND user_id=?",(gid,uid)).fetchone():
                        self._json({'code':1,'msg':'已参与该拼团'},400); db.close(); return
                    db.execute("INSERT INTO group_buy_participants (group_buy_id,user_id) VALUES (?,?)",(gid,uid))
                    new_count = gb['current_count'] + 1
                    db.execute("UPDATE group_buys SET current_count=? WHERE id=?",(new_count,gid))
                    if new_count >= gb['required_count']:
                        db.execute("UPDATE group_buys SET status='success' WHERE id=?",(gid,))
                        # Notify all participants
                        pids = db.execute("SELECT user_id FROM group_buy_participants WHERE group_buy_id=?",(gid,)).fetchall()
                        for p in pids:
                            notify(db, p['user_id'], 'group', '拼团成功', f'你参与的拼团 #{gid} 已成功！', gid)
                    db.commit()
                    self._json({'code':0,'msg':'参与成功'})
            # Coupons
            elif path == '/api/coupons':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                action = body.get('action','claim'); cid = body.get('coupon_id')
                if action == 'claim':
                    cp = db.execute("SELECT * FROM coupons WHERE id=? AND used_count<total_count",(cid,)).fetchone()
                    if not cp: self._json({'code':1,'msg':'优惠券已抢完'},400); db.close(); return
                    if db.execute("SELECT 1 FROM user_coupons WHERE user_id=? AND coupon_id=?",(uid,cid)).fetchone():
                        self._json({'code':1,'msg':'已领取过'},400); db.close(); return
                    db.execute("INSERT INTO user_coupons (user_id,coupon_id) VALUES (?,?)",(uid,cid))
                    db.execute("UPDATE coupons SET used_count=used_count+1 WHERE id=?",(cid,))
                    db.commit()
                    self._json({'code':0,'msg':'领取成功'})
            # Posts
            elif path == '/api/posts':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                action = body.get('action','create')
                if action == 'create':
                    title = body.get('title',''); content = body.get('content',''); images = body.get('images','[]'); tid = body.get('topic_id',0)
                    media_type = body.get('media_type','image'); video_url = body.get('video_url','')
                    db.execute("INSERT INTO posts (user_id,title,content,images,topic_id,media_type,video_url) VALUES (?,?,?,?,?,?,?)",(uid,title,content,str(images),tid,media_type,video_url))
                    if tid: db.execute("UPDATE topics SET post_count=post_count+1 WHERE id=?",(tid,))
                    db.commit()
                    self._json({'code':0,'msg':'发布成功'})
            # Like
            elif path == '/api/like':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                pid = body.get('post_id'); action = body.get('action','like')
                if action == 'like':
                    db.execute("INSERT OR IGNORE INTO post_likes (post_id,user_id) VALUES (?,?)",(pid,uid))
                    db.execute("UPDATE posts SET like_count=like_count+1 WHERE id=?",(pid,))
                elif action == 'unlike':
                    db.execute("DELETE FROM post_likes WHERE post_id=? AND user_id=?",(pid,uid))
                    db.execute("UPDATE posts SET like_count=MAX(0,like_count-1) WHERE id=?",(pid,))
                db.commit()
                self._json({'code':0,'msg':'ok'})
            # Comments
            elif path == '/api/comments':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                pid = body.get('post_id'); content = body.get('content',''); parent = body.get('parent_id',0)
                db.execute("INSERT INTO comments (post_id,user_id,content,parent_id) VALUES (?,?,?,?)",(pid,uid,content,parent))
                db.execute("UPDATE posts SET comment_count=comment_count+1 WHERE id=?",(pid,))
                db.commit()
                self._json({'code':0,'msg':'评论成功'})
            # Live
            elif path == '/api/live':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                action = body.get('action','start')
                if action == 'start':
                    title = body.get('title','直播中'); cover = body.get('cover',''); pids = body.get('product_ids','[]')
                    db.execute("INSERT INTO live_rooms (user_id,title,cover,product_ids,status) VALUES (?,?,?,?,'online')",(uid,title,cover,str(pids)))
                    db.commit()
                    self._json({'code':0,'msg':'开播成功'})
                elif action == 'stop':
                    db.execute("UPDATE live_rooms SET status='offline' WHERE user_id=? AND status='online'",(uid,))
                    db.commit()
                    self._json({'code':0,'msg':'下播成功'})
            # WebRTC Signaling
            elif path == '/api/rtc/start':
                title = body.get('title','直播')
                db.execute("INSERT INTO live_rooms (user_id,title,status) VALUES (?,?,'online')",(uid or 1,title))
                db.commit()
                rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                rtc_rooms[rid] = {'host':uid or 1,'title':title,'viewers':set(),'chat':[],'offers':{},'answers':{},'ices':[]}
                self._json({'room_id':rid})
            elif path == '/api/rtc/stop':
                rid = body.get('room_id')
                try: rid = int(rid)
                except: pass
                rtc_rooms.pop(rid, None)
                db.execute("UPDATE live_rooms SET status='offline' WHERE user_id=? AND status='online'",(uid or 1,))
                db.commit()
                self._json({'ok':True})
            elif path == '/api/rtc/status':
                rid = params.get('room_id',[None])[0]
                self._json({'live': rid in rtc_rooms})
            elif path == '/api/rtc/join':
                rid = body.get('room_id')
                try: rid = int(rid)
                except: pass
                if rid in rtc_rooms: rtc_rooms[rid]['viewers'].add(str(id(self)))
                self._json({'ok':True})
            elif path == '/api/rtc/viewers':
                rid = params.get('room_id',[None])[0]
                r = rtc_rooms.get(rid, {})
                self._json({'count':len(r.get('viewers',set()))})
            elif path == '/api/rtc/offer':
                rid = body.get('room_id')
                try: rid = int(rid)
                except: pass
                peer = body.get('peer', str(id(self)))
                if rid in rtc_rooms: rtc_rooms[rid]['offers'][peer] = body.get('sdp')
                self._json({'ok':True})
            elif path == '/api/rtc/answer':
                rid = body.get('room_id')
                try: rid = int(rid)
                except: pass
                peer = body.get('peer','')
                if rid in rtc_rooms: rtc_rooms[rid]['answers'][peer] = body.get('sdp')
                self._json({'ok':True})
            elif path == '/api/rtc/ice':
                rid = body.get('room_id')
                try: rid = int(rid)
                except: pass
                peer = body.get('peer', str(id(self)))
                if rid in rtc_rooms: rtc_rooms[rid]['ices'].append({'peer':peer,'candidate':body.get('candidate')})
                self._json({'ok':True})
            elif path == '/api/rtc/chat':
                rid = (params.get('room_id',[None])[0] or body.get('room_id'))
                try: rid = int(rid)
                except: pass
                if rid in rtc_rooms: rtc_rooms[rid]['chat'].append({'user':body.get('user',''),'text':body.get('text','')})
                self._json({'ok':True})
            # Chat
            elif path == '/api/chat':
                action = body.get('action',params.get('action',[''])[0])
                if action == 'messages':
                    sid = body.get('session_id',params.get('session_id',[''])[0])
                    content = body.get('content',''); stype = body.get('sender_type','user')
                    uname = body.get('user_name','用户')
                    if not sid:
                        db.execute("INSERT INTO chat_sessions (user_name,last_message) VALUES (?,?)",(uname,content))
                        sid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                    else:
                        db.execute("UPDATE chat_sessions SET last_message=?,unread=unread+1,updated_at=datetime('now','localtime') WHERE id=?",(content,sid))
                    db.execute("INSERT INTO chat_messages (session_id,sender_type,content) VALUES (?,?,?)",(sid,stype,content))
                    db.commit()
                    mid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                    self._json({'code':0,'data':{'session_id':int(sid),'id':mid}})
                else:
                    self._json({'code':1,'msg':'unknown action'})
            else:
                self._json({'code':1,'msg':'not found'},404)
            db.close()
        except Exception as e:
            self._json({'code':1,'msg':str(e)},500)

    def do_PUT(self):
        # P0: api_client.updateCartItem 用 PUT，原来后端无处理必 405
        path = urlparse(self.path).path
        length = int(self.headers.get('Content-Length',0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}
        uid = self._uid()
        try:
            db = _connect()
            if path == '/api/cart':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                cid = body.get('id'); qty = body.get('quantity',1)
                if not cid: self._json({'code':1,'msg':'缺少ID'},400); db.close(); return
                if qty <= 0:
                    db.execute("DELETE FROM cart WHERE id=? AND user_id=?",(cid,uid))
                else:
                    db.execute("UPDATE cart SET quantity=? WHERE id=? AND user_id=?",(qty,cid,uid))
                db.commit(); self._json({'code':0,'msg':'ok'})
            else:
                self._json({'code':1,'msg':'not found'},404)
            db.close()
        except Exception as e:
            self._json({'code':1,'msg':str(e)},500)

    def do_DELETE(self):
        # P0: api_client.removeCartItem 用 DELETE
        path = urlparse(self.path).path
        length = int(self.headers.get('Content-Length',0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}
        uid = self._uid()
        try:
            db = _connect()
            if path == '/api/cart':
                if not uid: self._json({'code':1,'msg':'请先登录'},401); db.close(); return
                cid = body.get('id')
                if not cid: self._json({'code':1,'msg':'缺少ID'},400); db.close(); return
                db.execute("DELETE FROM cart WHERE id=? AND user_id=?",(cid,uid))
                db.commit(); self._json({'code':0,'msg':'ok'})
            else:
                self._json({'code':1,'msg':'not found'},404)
            db.close()
        except Exception as e:
            self._json({'code':1,'msg':str(e)},500)

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT',8081))
    server = HTTPServer(('0.0.0.0',port), APIHandler)
    print(f'eShop Social API running on http://localhost:{port}')
    server.serve_forever()
