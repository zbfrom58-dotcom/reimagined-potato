import json
import os

DM_FILE = "allowed_dms.json"


def _load() -> dict:
    if not os.path.exists(DM_FILE):
        return {}
    try:
        with open(DM_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save(data: dict) -> None:
    with open(DM_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_dm(chat_id: int, label: str) -> None:
    """Подключает личный чат: сохраняет его chat_id и метку (username/имя)."""
    data = _load()
    data[str(chat_id)] = {"label": label}
    _save(data)


def remove_dm_by_label(label: str) -> bool:
    """Отключает личный чат по метке (username или имя/ID, как вводили при добавлении)."""
    data = _load()
    label_lower = label.lower()
    for key, info in list(data.items()):
        if info.get("label", "").lower() == label_lower or key == label:
            del data[key]
            _save(data)
            return True
    return False


def remove_dm_by_chat_id(chat_id) -> bool:
    """Отключает личный чат по chat_id (используется веб-панелью)."""
    data = _load()
    key = str(chat_id)
    if key not in data:
        return False
    del data[key]
    _save(data)
    return True


def is_allowed(chat_id: int) -> bool:
    """Проверяет, подключён ли личный чат с данным chat_id."""
    return str(chat_id) in _load()


def list_dms() -> dict:
    """Возвращает все подключённые личные чаты: {chat_id: {"label": ...}}"""
    return _load()
