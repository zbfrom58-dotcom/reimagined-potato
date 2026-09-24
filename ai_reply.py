import logging
import os
import requests

logger = logging.getLogger(__name__)

MODEL = "deepseek-flash"
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.xspase.ru/v1").rstrip("/")
TIMEOUT = 20

def _load_key():
    value = os.getenv("DEEPSEEK_API_KEY")
    return value.strip() if value and value.strip() else None

def is_configured():
    return bool(_load_key())

def list_configured_keys():
    return 1 if _load_key() else 0

def list_models():
    return [MODEL] if _load_key() else []

def generate_reply(user_message, persona, *, extra_context=""):
    key = _load_key()
    if not key:
        logger.warning("DeepSeek API key is not configured")
        return None
    system_prompt = (
        f"{persona}\n\n"
        "Правила:\n"
        "- Ответь только готовым сообщением.\n"
        "- Не говори, что ты ИИ.\n"
        "- Не копируй сообщение собеседника.\n"
        "- Отвечай именно на смысл сообщения.\n"
        "- Обычно 1–2 коротких предложения.\n"
        f"{extra_context}"
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 1.0,
        "max_tokens": 200,
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    try:
        r = requests.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            logger.error("DeepSeek HTTP %s: %s", r.status_code, r.text[:500])
            return None
        choices = (r.json().get("choices") or [])
        if not choices:
            return None
        return ((choices[0].get("message") or {}).get("content") or "").strip() or None
    except requests.Timeout:
        logger.warning("DeepSeek timeout")
    except requests.RequestException as e:
        logger.warning("Ошибка DeepSeek: %s", e)
    return None
