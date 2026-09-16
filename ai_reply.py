import logging
import os
import requests

logger = logging.getLogger(__name__)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT = 30

def is_configured() -> bool:
    return bool(GEMINI_API_KEY)

def list_models():
    if not GEMINI_API_KEY:
        return []
    try:
        r = requests.get(f"{BASE_URL}/models", params={"key": GEMINI_API_KEY}, timeout=TIMEOUT)
        r.raise_for_status()
        return [
            x.get("name", "").replace("models/", "")
            for x in r.json().get("models", [])
            if "generateContent" in x.get("supportedGenerationMethods", [])
        ]
    except Exception as e:
        logger.warning("Не удалось получить модели Gemini: %s", e)
        return []

def generate_reply(user_message: str, persona: str) -> str | None:
    if not GEMINI_API_KEY:
        return None

    prompt = (
        f"{persona}\n\n"
        "Правила:\n"
        "- Ответь только готовым сообщением.\n"
        "- Не говори, что ты ИИ.\n"
        "- Не копируй сообщение собеседника.\n"
        "- Отвечай именно на смысл сообщения.\n"
        "- Обычно 1–2 коротких предложения.\n\n"
        f"Сообщение собеседника:\n{user_message}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.0, "maxOutputTokens": 200},
    }

    try:
        r = requests.post(
            f"{BASE_URL}/models/{MODEL}:generateContent",
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            logger.error("Gemini HTTP %s: %s", r.status_code, r.text[:1000])
            return None
        data = r.json()
    except requests.Timeout:
        logger.warning("Gemini timeout")
        return None
    except requests.RequestException as e:
        logger.warning("Ошибка Gemini: %s", e)
        return None

    candidates = data.get("candidates") or []
    if not candidates:
        return None
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    return text or None
