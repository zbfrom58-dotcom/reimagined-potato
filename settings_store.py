import json
import os

SETTINGS_FILE = "settings.json"

DEFAULT_PERSONA = (
    "Ты — обычный живой человек, который комментирует посты в Telegram-канале. "
    "Пиши по-русски, коротко (1 предложение, максимум два), живо и по делу — "
    "конкретная реакция на суть поста, а не общие слова. Не упоминай, что ты ИИ, "
    "не используй длинные вступления и канцелярит."
)


def _defaults() -> dict:
    return {
        "enabled": True,
        "chat_interval": 5,
        "chat_counters": {},
        "autocomment_enabled": True,
        "autocomment_interval": 1,
        "autocomment_counters": {},
        "persona": DEFAULT_PERSONA,
    }


def _load() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return _defaults()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except (json.JSONDecodeError, FileNotFoundError):
        data = {}

    defaults = _defaults()
    for key, value in defaults.items():
        data.setdefault(key, value)

    return data


def _save(data: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_enabled() -> bool:
    return bool(_load().get("enabled", True))


def set_enabled(value: bool) -> None:
    data = _load()
    data["enabled"] = value
    _save(data)


def get_persona() -> str:
    return _load().get("persona", DEFAULT_PERSONA)


def set_persona(text: str) -> None:
    data = _load()
    data["persona"] = text.strip() or DEFAULT_PERSONA
    _save(data)


# ---------- ответы на сообщения людей в группе ----------

def get_chat_interval() -> int:
    return int(_load().get("chat_interval", 5))


def set_chat_interval(n: int) -> bool:
    if n < 1:
        return False
    data = _load()
    data["chat_interval"] = n
    _save(data)
    return True


def bump_and_should_reply_chat(chat_id: int) -> bool:
    data = _load()
    counters = data.setdefault("chat_counters", {})
    key = str(chat_id)
    counters[key] = counters.get(key, 0) + 1
    interval = max(1, int(data.get("chat_interval", 5)))
    if counters[key] >= interval:
        counters[key] = 0
        _save(data)
        return True
    _save(data)
    return False


# ---------- автокомментинг постов канала ----------

def is_autocomment_enabled() -> bool:
    return bool(_load().get("autocomment_enabled", True))


def set_autocomment_enabled(value: bool) -> None:
    data = _load()
    data["autocomment_enabled"] = value
    _save(data)


def get_autocomment_interval() -> int:
    return int(_load().get("autocomment_interval", 1))


def set_autocomment_interval(n: int) -> bool:
    if n < 1:
        return False
    data = _load()
    data["autocomment_interval"] = n
    _save(data)
    return True


def bump_and_should_comment(chat_id: int) -> bool:
    data = _load()
    counters = data.setdefault("autocomment_counters", {})
    key = str(chat_id)
    counters[key] = counters.get(key, 0) + 1
    interval = max(1, int(data.get("autocomment_interval", 1)))
    if counters[key] >= interval:
        counters[key] = 0
        _save(data)
        return True
    _save(data)
    return False
