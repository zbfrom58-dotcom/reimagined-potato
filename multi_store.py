import json
from pathlib import Path
from threading import RLock

BASE_DIR = Path("data")
BASE_DIR.mkdir(exist_ok=True)
LOCK = RLock()

DEFAULT_ACCOUNT = {
    "enabled": False,
    "autocomment_enabled": True,
    "autocomment_interval": 1,
    "chat_interval": 5,
    "chat_counters": {},
    "autocomment_counters": {},
    "persona": "",
    "groups": {},
}

DEFAULT_SHARED = {
    "mode": "shared",  # shared | personal
    "persona": "",
    "autocomment_enabled": True,
    "autocomment_interval": 1,
    "chat_interval": 5,
    "chat_counters": {},
    "autocomment_counters": {},
    "groups": {},
}

def _account_path(key): return BASE_DIR / f"{key}.json"
def _shared_path(): return BASE_DIR / "shared.json"

def _load(path, defaults):
    with LOCK:
        if not path.exists(): return dict(defaults)
        try: data = json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError): data = {}
        result = dict(defaults); result.update(data); return result

def _save(path, data):
    with LOCK:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def get(account_key):
    return _load(_account_path(account_key), DEFAULT_ACCOUNT)

def get_shared():
    return _load(_shared_path(), DEFAULT_SHARED)

def set_mode(mode):
    if mode not in ("shared", "personal"): return False
    d=get_shared(); d["mode"]=mode; _save(_shared_path(),d); return True

def get_mode(): return get_shared().get("mode","shared")

def _set_account(key, field, value):
    d=get(key); d[field]=value; _save(_account_path(key),d)

def _set_shared(field,value):
    d=get_shared(); d[field]=value; _save(_shared_path(),d)

def set_enabled(key,v): _set_account(key,"enabled",bool(v))
def is_enabled(key): return bool(get(key)["enabled"])

def set_autocomment_enabled(key,v): _set_account(key,"autocomment_enabled",bool(v))
def is_autocomment_enabled(key): return bool(get(key)["autocomment_enabled"])

def set_autocomment_interval(key,n):
    if n<1:return False
    _set_account(key,"autocomment_interval",int(n)); return True
def get_autocomment_interval(key): return max(1,int(get(key)["autocomment_interval"]))

def set_chat_interval(key,n):
    if n<1:return False
    _set_account(key,"chat_interval",int(n)); return True
def get_chat_interval(key): return max(1,int(get(key)["chat_interval"]))

def set_persona(key,text): _set_account(key,"persona",text.strip())
def get_persona(key,fallback): return get(key).get("persona","") or fallback

def set_shared_persona(text): _set_shared("persona",text.strip())
def get_shared_persona(fallback=""):
    return get_shared().get("persona","") or fallback

def set_shared_autocomment_enabled(v): _set_shared("autocomment_enabled",bool(v))
def shared_autocomment_enabled(): return bool(get_shared()["autocomment_enabled"])
def set_shared_autocomment_interval(n):
    if n<1:return False
    _set_shared("autocomment_interval",int(n)); return True
def get_shared_autocomment_interval(): return max(1,int(get_shared()["autocomment_interval"]))
def set_shared_chat_interval(n):
    if n<1:return False
    _set_shared("chat_interval",int(n)); return True
def get_shared_chat_interval(): return max(1,int(get_shared()["chat_interval"]))

def add_group(key,chat_id,username=None,title=None):
    d=get(key); d["groups"][str(chat_id)]={"username":username,"title":title,"reply_enabled":True}; _save(_account_path(key),d)
def remove_group(key,chat_id):
    d=get(key); d["groups"].pop(str(chat_id),None); _save(_account_path(key),d)
def list_groups(key): return get(key).get("groups",{})
def set_reply_enabled(key,chat_id,v):
    d=get(key); item=d["groups"].get(str(chat_id))
    if item is not None: item["reply_enabled"]=bool(v); _save(_account_path(key),d)
def is_allowed(key,chat_id): return str(chat_id) in get(key)["groups"]
def is_reply_enabled(key,chat_id):
    item=get(key)["groups"].get(str(chat_id)); return bool(item and item.get("reply_enabled",True))

def add_shared_group(chat_id,username=None,title=None):
    d=get_shared(); d["groups"][str(chat_id)]={"username":username,"title":title,"reply_enabled":True}; _save(_shared_path(),d)
def remove_shared_group(chat_id):
    d=get_shared(); d["groups"].pop(str(chat_id),None); _save(_shared_path(),d)
def list_shared_groups(): return get_shared().get("groups",{})
def set_shared_reply_enabled(chat_id,v):
    d=get_shared(); item=d["groups"].get(str(chat_id))
    if item is not None: item["reply_enabled"]=bool(v); _save(_shared_path(),d)
def is_shared_allowed(chat_id): return str(chat_id) in get_shared()["groups"]
def is_shared_reply_enabled(chat_id):
    item=get_shared()["groups"].get(str(chat_id)); return bool(item and item.get("reply_enabled",True))

def effective_persona(key,fallback):
    return get_shared_persona(fallback) if get_mode()=="shared" else get_persona(key,fallback)
def effective_chat_interval(key):
    return get_shared_chat_interval() if get_mode()=="shared" else get_chat_interval(key)
def effective_autocomment_interval(key):
    return get_shared_autocomment_interval() if get_mode()=="shared" else get_autocomment_interval(key)
def effective_autocomment_enabled(key):
    return shared_autocomment_enabled() if get_mode()=="shared" else is_autocomment_enabled(key)
def effective_is_allowed(key,chat_id):
    return is_shared_allowed(chat_id) if get_mode()=="shared" else is_allowed(key,chat_id)
def effective_reply_enabled(key,chat_id):
    return is_shared_reply_enabled(chat_id) if get_mode()=="shared" else is_reply_enabled(key,chat_id)

def _bump(key,chat_id,field,interval,shared=False):
    d=get_shared() if shared else get(key)
    counters=d.setdefault(field,{})
    k=str(chat_id); counters[k]=int(counters.get(k,0))+1
    hit=counters[k]>=max(1,interval)
    if hit: counters[k]=0
    _save(_shared_path() if shared else _account_path(key),d)
    return hit

def bump_and_should_comment(key,chat_id):
    return _bump(key,chat_id,"autocomment_counters",effective_autocomment_interval(key),get_mode()=="shared")
def bump_and_should_reply_chat(key,chat_id):
    return _bump(key,chat_id,"chat_counters",effective_chat_interval(key),get_mode()=="shared")

def display_label(info):
    return "@"+info["username"] if info.get("username") else info.get("title") or "Без названия"
