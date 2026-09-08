import json
import os

DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)
GROUPS_FILE = os.path.join(DATA_DIR, "allowed_groups.json")


def _load() -> dict:
    if not os.path.exists(GROUPS_FILE):
        return {}
    try:
        with open(GROUPS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

    # Миграция старых записей (до появления title/reply_enabled) —
    # ничего не ломаем, просто доукомплектовываем недостающие поля.
    changed = False
    for chat_id, info in data.items():
        if "reply_enabled" not in info:
            info["reply_enabled"] = True
            changed = True
        if "title" not in info:
            info["title"] = None
            changed = True
    if changed:
        _save(data)

    return data


def _save(data: dict):
    with open(GROUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_group(chat_id: int, username: str = None, title: str = None, reply_enabled: bool = True):
    """
    Подключает группу (используется и для автокомментинга, и для авто-ответов
    на сообщения — это один и тот же список подключённых групп).

    username — реальный @юзернейм группы без символа @, либо None, если
               группа приватная и юзернейма не имеет.
    title    — отображаемое название группы (нужно в первую очередь для
               приватных групп без юзернейма, чтобы показывать что-то
               осмысленное вместо голого ID).
    reply_enabled — включён ли для этой группы авто-ответ на обычные
               сообщения людей (актуально при режиме chat/both). У
               автокомментинга своя логика и на этот флаг он не смотрит.
    """
    data = _load()
    key = str(chat_id)
    existing = data.get(key, {})
    data[key] = {
        "username": username if username else None,
        "title": title if title else existing.get("title"),
        "reply_enabled": existing.get("reply_enabled", reply_enabled) if key in data else reply_enabled,
    }
    _save(data)


def remove_group_by_username(username: str) -> bool:
    data = _load()
    key_to_remove = None
    for chat_id, info in data.items():
        if info.get("username") == username:
            key_to_remove = chat_id
            break
    if key_to_remove is None:
        return False
    del data[key_to_remove]
    _save(data)
    return True


def remove_group_by_chat_id(chat_id) -> bool:
    """Отключает группу по chat_id (используется веб-панелью)."""
    data = _load()
    key = str(chat_id)
    if key not in data:
        return False
    del data[key]
    _save(data)
    return True


def is_allowed(chat_id: int) -> bool:
    data = _load()
    return str(chat_id) in data


def list_groups() -> dict:
    return _load()


def display_label(info: dict) -> str:
    """
    Единообразное отображаемое имя группы для панели/команд:
    @username, если он есть, иначе title (для приватных групп),
    иначе просто заглушка.
    """
    username = info.get("username")
    if username:
        return f"@{username}"
    title = info.get("title")
    return title or "Без названия (приватная)"


def is_reply_enabled(chat_id) -> bool:
    """Включён ли авто-ответ на сообщения именно в этой группе."""
    data = _load()
    info = data.get(str(chat_id))
    if not info:
        return False
    return bool(info.get("reply_enabled", True))


def set_reply_enabled(chat_id, enabled: bool) -> bool:
    data = _load()
    key = str(chat_id)
    if key not in data:
        return False
    data[key]["reply_enabled"] = enabled
    _save(data)
    return True
