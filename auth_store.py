"""
Учётные записи для входа в веб-панель.

Изначальный (главный) админ задаётся переменными окружения
ADMIN_USERNAME и ADMIN_PASSWORD — он всегда может войти, даже если
файл с пользователями пуст или удалён.

Дополнительных пользователей (логин+пароль) можно выдавать прямо
из веб-панели — они сохраняются в users.json (пароли хранятся
только в виде хэша, не в открытом виде).
"""

import json
import os

from werkzeug.security import generate_password_hash, check_password_hash

USERS_FILE = "panel_users.json"


def _load() -> dict:
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save(data: dict) -> None:
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _main_admin():
    username = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD")
    if username and password:
        return username, password
    return None, None


def verify(username: str, password: str) -> bool:
    main_user, main_pass = _main_admin()
    if main_user and username == main_user and password == main_pass:
        return True

    data = _load()
    entry = data.get(username)
    if not entry:
        return False
    return check_password_hash(entry["password_hash"], password)


def add_user(username: str, password: str) -> tuple[bool, str]:
    username = username.strip()
    if not username or not password:
        return False, "Логин и пароль не могут быть пустыми."

    main_user, _ = _main_admin()
    if main_user and username == main_user:
        return False, "Этот логин зарезервирован под главного администратора."

    data = _load()
    if username in data:
        return False, "Пользователь с таким логином уже существует."

    data[username] = {"password_hash": generate_password_hash(password)}
    _save(data)
    return True, ""


def remove_user(username: str) -> bool:
    data = _load()
    if username not in data:
        return False
    del data[username]
    _save(data)
    return True


def list_users() -> list:
    """Возвращает список логинов дополнительных пользователей (без главного админа)."""
    return list(_load().keys())
