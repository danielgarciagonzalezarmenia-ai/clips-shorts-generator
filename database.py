import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = 'users.db'

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = _get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    conn.commit()
    conn.close()

def create_user(username, password):
    conn = _get_db()
    try:
        conn.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)',
                     (username, generate_password_hash(password)))
        conn.commit()
        user = conn.execute('SELECT id, username FROM users WHERE username = ?', (username,)).fetchone()
        return dict(user)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def verify_user(username, password):
    conn = _get_db()
    try:
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            return {'id': user['id'], 'username': user['username']}
        return None
    finally:
        conn.close()

def get_user(user_id):
    conn = _get_db()
    try:
        user = conn.execute('SELECT id, username, created_at FROM users WHERE id = ?', (user_id,)).fetchone()
        return dict(user) if user else None
    finally:
        conn.close()

init_db()
