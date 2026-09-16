import logging
import os
import threading
import requests

logger = logging.getLogger(__name__)
MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite')
BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'
TIMEOUT = 30

_keys_lock = threading.Lock()
_key_index = 0


def _load_keys() -> list[str]:
    keys = []
    # Seven independent keys. Keep legacy GEMINI_API_KEY as an 8th/fallback slot for compatibility.
    for i in range(1, 8):
        value = os.getenv(f'GEMINI_API_KEY_{i}')
        if value and value.strip() and value.strip() not in keys:
            keys.append(value.strip())
    legacy = os.getenv('GEMINI_API_KEY')
    if legacy and legacy.strip() and legacy.strip() not in keys:
        keys.append(legacy.strip())
    return keys


def _next_key() -> str | None:
    global _key_index
    keys = _load_keys()
    if not keys:
        return None
    with _keys_lock:
        key = keys[_key_index % len(keys)]
        _key_index += 1
    return key


def is_configured() -> bool:
    return bool(_load_keys())


def list_configured_keys() -> int:
    return len(_load_keys())


def list_models():
    key = _next_key()
    if not key:
        return []
    try:
        r = requests.get(f'{BASE_URL}/models', params={'key': key}, timeout=TIMEOUT)
        r.raise_for_status()
        return [x.get('name', '').replace('models/', '') for x in r.json().get('models', []) if 'generateContent' in x.get('supportedGenerationMethods', [])]
    except Exception as e:
        logger.warning('Не удалось получить модели Gemini: %s', e)
        return []


def generate_reply(user_message: str, persona: str, *, extra_context: str = '') -> str | None:
    keys = _load_keys()
    if not keys:
        return None

    prompt = (
        f'{persona}\n\n'
        'Правила:\n'
        '- Ответь только готовым сообщением.\n'
        '- Не говори, что ты ИИ.\n'
        '- Не копируй сообщение собеседника.\n'
        '- Отвечай именно на смысл сообщения.\n'
        '- Обычно 1–2 коротких предложения.\n'
        f'{extra_context}\n'
        f'Сообщение собеседника:\n{user_message}'
    )

    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {'temperature': 1.0, 'maxOutputTokens': 200},
    }

    # Round-robin through all seven keys, and retry on quota/server failures.
    global _key_index
    with _keys_lock:
        start = _key_index % len(keys)
        _key_index += 1
    ordered = keys[start:] + keys[:start]

    for key in ordered:
        try:
            r = requests.post(f'{BASE_URL}/models/{MODEL}:generateContent', params={'key': key}, json=payload, timeout=TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                candidates = data.get('candidates') or []
                if not candidates:
                    continue
                parts = (candidates[0].get('content') or {}).get('parts') or []
                text = ''.join(p.get('text', '') for p in parts if isinstance(p, dict)).strip()
                if text:
                    return text
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                logger.warning('Gemini HTTP %s — пробуем следующий ключ', r.status_code)
                continue
            logger.error('Gemini HTTP %s: %s', r.status_code, r.text[:500])
        except requests.Timeout:
            logger.warning('Gemini timeout — пробуем следующий ключ')
        except requests.RequestException as e:
            logger.warning('Ошибка Gemini: %s — пробуем следующий ключ', e)
    return None
