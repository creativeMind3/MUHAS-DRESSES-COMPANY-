import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SECRET_FILE = BASE_DIR / '.secret_key'
if os.environ.get('SECRET_KEY'):
    _SECRET_KEY = os.environ['SECRET_KEY']
else:
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32), encoding='utf-8')
    _SECRET_KEY = SECRET_FILE.read_text(encoding='utf-8').strip()

class Config:
    SECRET_KEY = _SECRET_KEY
    DATABASE = str(BASE_DIR / 'bib_store.db')
    UPLOAD_FOLDER = str(BASE_DIR / 'uploads')
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7
    STORE_CURRENCY = '₦'
    CATEGORIES = [
        'Phone Accessories', 'Watches', 'Bags', 'Jewelry',
        'Audio', 'Electronics', 'Lifestyle', 'Other'
    ]
