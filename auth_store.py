import json, os
from pathlib import Path
from threading import RLock
from werkzeug.security import generate_password_hash, check_password_hash

PATH=Path("data/admins.json")
LOCK=RLock()

def _load():
    with LOCK:
        if not PATH.exists(): return {}
        try: return json.loads(PATH.read_text(encoding="utf-8")) or {}
        except (OSError,json.JSONDecodeError): return {}

def _save(d):
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")

def bootstrap():
    d=_load()
    if not d and os.getenv("ADMIN_USERNAME") and os.getenv("ADMIN_PASSWORD"):
        d[os.getenv("ADMIN_USERNAME").strip()] = generate_password_hash(os.getenv("ADMIN_PASSWORD"))
        _save(d)
    return d

def list_users():
    return sorted(_load().keys())

def verify(username,password):
    d=bootstrap()
    username=(username or "").strip()
    return username in d and check_password_hash(d[username],password or "")

def create_user(username,password):
    username=(username or "").strip()
    if len(username)<3 or len(password or "")<6 or username in _load(): return False
    d=_load(); d[username]=generate_password_hash(password); _save(d); return True

def delete_user(username):
    d=_load()
    if username not in d or len(d)<=1: return False
    d.pop(username); _save(d); return True
