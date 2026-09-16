import json
from pathlib import Path
from threading import RLock

BASE_DIR = Path('data')
BASE_DIR.mkdir(exist_ok=True)
LOCK = RLock()

DEFAULTS = {
    'enabled': False,
    'autocomment_enabled': True,
    'autocomment_interval': 1,
    'chat_interval': 5,
    'chat_counters': {},
    'autocomment_counters': {},
    'persona': '',
    'groups': {},
}

COMMON_KEY = '__common__'
COMMON_DEFAULTS = {
    'mode': 'common',
    'persona': '',
    'reply_interval': 1,
    'groups': {},
    'message_once': True,
    'enabled': False,
}


def _path(account_key: str) -> Path:
    return BASE_DIR / f'{account_key}.json'


def _load(account_key: str) -> dict:
    with LOCK:
        path = _path(account_key)
        if not path.exists():
            return dict(DEFAULTS)
        try:
            data = json.loads(path.read_text(encoding='utf-8')) or {}
        except (OSError, json.JSONDecodeError):
            data = {}
        result = dict(DEFAULTS)
        result.update(data)
        return result


def _save(account_key: str, data: dict) -> None:
    with LOCK:
        _path(account_key).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def get(account_key: str) -> dict:
    return _load(account_key)


def set_enabled(account_key: str, value: bool):
    d = _load(account_key); d['enabled'] = bool(value); _save(account_key, d)


def is_enabled(account_key: str) -> bool:
    return bool(_load(account_key)['enabled'])


def set_autocomment_enabled(account_key: str, value: bool):
    d = _load(account_key); d['autocomment_enabled'] = bool(value); _save(account_key, d)


def is_autocomment_enabled(account_key: str) -> bool:
    return bool(_load(account_key)['autocomment_enabled'])


def set_autocomment_interval(account_key: str, n: int) -> bool:
    if n < 1: return False
    d = _load(account_key); d['autocomment_interval'] = n; _save(account_key, d); return True


def get_autocomment_interval(account_key: str) -> int:
    return max(1, int(_load(account_key)['autocomment_interval']))


def set_chat_interval(account_key: str, n: int) -> bool:
    if n < 1: return False
    d = _load(account_key); d['chat_interval'] = n; _save(account_key, d); return True


def get_chat_interval(account_key: str) -> int:
    return max(1, int(_load(account_key)['chat_interval']))


def set_persona(account_key: str, text: str):
    d = _load(account_key); d['persona'] = text.strip(); _save(account_key, d)


def get_persona(account_key: str, fallback: str) -> str:
    value = _load(account_key).get('persona', '')
    return value or fallback


def add_group(account_key: str, chat_id: int, username=None, title=None):
    d = _load(account_key)
    d['groups'][str(chat_id)] = {'username': username, 'title': title, 'reply_enabled': True}
    _save(account_key, d)


def remove_group(account_key: str, chat_id: int):
    d = _load(account_key); d['groups'].pop(str(chat_id), None); _save(account_key, d)


def list_groups(account_key: str) -> dict:
    return _load(account_key).get('groups', {})


def is_allowed(account_key: str, chat_id: int) -> bool:
    return str(chat_id) in _load(account_key)['groups']


def set_reply_enabled(account_key: str, chat_id: int, value: bool):
    d = _load(account_key)
    item = d['groups'].get(str(chat_id))
    if item is not None:
        item['reply_enabled'] = bool(value)
        _save(account_key, d)


def is_reply_enabled(account_key: str, chat_id: int) -> bool:
    item = _load(account_key)['groups'].get(str(chat_id))
    return bool(item and item.get('reply_enabled', True))


# ---------------- Common (global) mode ----------------

def _common_load() -> dict:
    d = _load(COMMON_KEY)
    result = dict(COMMON_DEFAULTS)
    result.update(d)
    result['groups'] = d.get('groups', {})
    return result


def get_mode() -> str:
    mode = _common_load().get('mode', 'common')
    return mode if mode in {'common', 'personal'} else 'common'


def set_mode(mode: str) -> None:
    if mode not in {'common', 'personal'}:
        raise ValueError('Недопустимый режим')
    d = _common_load(); d['mode'] = mode; _save(COMMON_KEY, d)


def is_common_mode() -> bool:
    return get_mode() == 'common'


def set_common_persona(text: str):
    d = _common_load(); d['persona'] = text.strip(); _save(COMMON_KEY, d)


def get_common_persona(fallback: str = '') -> str:
    value = _common_load().get('persona', '')
    return value or fallback


def set_common_reply_interval(n: int) -> bool:
    if n < 1: return False
    d = _common_load(); d['reply_interval'] = n; _save(COMMON_KEY, d); return True


def get_common_reply_interval() -> int:
    return max(1, int(_common_load().get('reply_interval', 1)))


def common_message_once() -> bool:
    return bool(_common_load().get('message_once', True))


def set_common_message_once(value: bool):
    d = _common_load(); d['message_once'] = bool(value); _save(COMMON_KEY, d)


def set_common_enabled(value: bool):
    d = _common_load(); d['enabled'] = bool(value); _save(COMMON_KEY, d)


def is_common_enabled() -> bool:
    return bool(_common_load().get('enabled', False))


def add_common_group(chat_id: int, username=None, title=None):
    add_group(COMMON_KEY, chat_id, username, title)


def remove_common_group(chat_id: int):
    remove_group(COMMON_KEY, chat_id)


def list_common_groups() -> dict:
    return list_groups(COMMON_KEY)


def is_common_allowed(chat_id: int) -> bool:
    return is_allowed(COMMON_KEY, chat_id)


def set_common_reply_enabled(chat_id: int, value: bool):
    set_reply_enabled(COMMON_KEY, chat_id, value)


def is_common_reply_enabled(chat_id: int) -> bool:
    return is_reply_enabled(COMMON_KEY, chat_id)


def display_label(info: dict) -> str:
    if info.get('username'):
        return '@' + info['username']
    return info.get('title') or 'Без названия'


def _bump(account_key: str, chat_id: int, field: str, interval: int) -> bool:
    d = _load(account_key)
    counters = d.setdefault(field, {})
    key = str(chat_id)
    counters[key] = int(counters.get(key, 0)) + 1
    if counters[key] >= max(1, interval):
        counters[key] = 0
        _save(account_key, d)
        return True
    _save(account_key, d)
    return False


def bump_and_should_comment(account_key: str, chat_id: int) -> bool:
    return _bump(account_key, chat_id, 'autocomment_counters', get_autocomment_interval(account_key))


def bump_and_should_reply_chat(account_key: str, chat_id: int) -> bool:
    if is_common_mode():
        # Counter belongs to the account, so every running account can reply once
        # to the same incoming message/event according to the common interval.
        return _bump(account_key, chat_id, 'chat_counters', get_common_reply_interval())
    return _bump(account_key, chat_id, 'chat_counters', get_chat_interval(account_key))
