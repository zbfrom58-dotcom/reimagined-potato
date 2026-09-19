import json
from pathlib import Path
from threading import RLock
from datetime import datetime, timezone

BASE_DIR = Path('data')
BASE_DIR.mkdir(exist_ok=True)
PATH = BASE_DIR / 'actions.json'
LOCK = RLock()


def _load() -> list[dict]:
    with LOCK:
        if not PATH.exists():
            return []
        try:
            data = json.loads(PATH.read_text(encoding='utf-8'))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []


def _save(items: list[dict]) -> None:
    with LOCK:
        PATH.write_text(json.dumps(items[-200:], ensure_ascii=False, indent=2), encoding='utf-8')


def add(item: dict) -> dict:
    items = _load()
    item = dict(item)
    item.setdefault('created_at', datetime.now(timezone.utc).isoformat())
    items.append(item)
    _save(items)
    return item


def list_items(limit: int = 50) -> list[dict]:
    return list(reversed(_load()[-limit:]))
