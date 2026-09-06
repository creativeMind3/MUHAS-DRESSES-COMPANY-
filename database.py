import sqlite3
from pathlib import Path

from config import Config

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL NOT NULL CHECK(price >= 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
    description TEXT NOT NULL DEFAULT '',
    image TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    customer_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    address TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    total REAL NOT NULL CHECK(total >= 0),
    status TEXT NOT NULL DEFAULT 'Pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    product_name TEXT NOT NULL,
    price REAL NOT NULL CHECK(price >= 0),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
'''

DEFAULT_SETTINGS = {
    'store_name': 'BIB-STORE',
    'store_email': '',
    'phone': '',
    'whatsapp': '',
    'address': '',
    'logo': '',
    'currency': '₦',
    'description': 'A modern online store for accessories, electronics and lifestyle products.',
    'primary_color': '#6d4aff',
    'announcement_text': 'Fast & secure shopping • Easy ordering',
    'show_announcement': '1',
    'show_whatsapp': '1',
    'whatsapp_message': 'Hello {{store_name}}, I need help with my order #{{order_id}}.',
    'footer_text': 'Quality products, great prices and dependable customer service.',
    'nav_home': '1',
    'nav_shop': '1',
    'nav_categories': '1',
    'nav_about': '1',
    'nav_contact': '1',
}


def get_connection():
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 5000')
    return conn


def init_db():
    Path(Config.UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute('INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)', (key, value))
        # Remove the old promotional delivery threshold from existing installations.
        conn.execute(
            "UPDATE settings SET value=? WHERE key='announcement_text' AND value LIKE 'Free delivery on orders over ₦50,000%'",
            (DEFAULT_SETTINGS['announcement_text'],),
        )
        # BIB-STORE uses a single administrator account. On an older installation
        # that already has multiple admins, keep the oldest admin and safely
        # demote the others to normal customer accounts.
        admins = conn.execute("SELECT id FROM users WHERE is_admin=1 ORDER BY id ASC").fetchall()
        if len(admins) > 1:
            keep_id = admins[0]['id']
            conn.execute("UPDATE users SET is_admin=0 WHERE is_admin=1 AND id != ?", (keep_id,))
        conn.commit()


def fetch_one(query, params=()):
    with get_connection() as conn:
        return conn.execute(query, params).fetchone()


def fetch_all(query, params=()):
    with get_connection() as conn:
        return conn.execute(query, params).fetchall()


def get_settings():
    rows = fetch_all('SELECT key, value FROM settings')
    data = DEFAULT_SETTINGS.copy()
    data.update({r['key']: r['value'] for r in rows})
    return data


def update_settings(values):
    with get_connection() as conn:
        for key, value in values.items():
            conn.execute(
                'INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                (key, value),
            )
        conn.commit()
