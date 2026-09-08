"""
Генерация текста ответа через Google Gemini API.

Требуется переменная окружения GEMINI_API_KEY (получить ключ можно в
Google AI Studio: https://aistudio.google.com/apikey).

Ключ НИКОГДА не хранится в файлах проекта — только в переменной окружения.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


def is_configured() -> bool:
    return bool(GEMINI_API_KEY)


def generate_reply(user_message: str, persona: str) -> str | None:
    """
    Запрашивает у Gemini короткий ответ в заданном "характере" (persona)
    на сообщение собеседника. Возвращает текст ответа или None, если
    ключ не задан, произошла ошибка, либо модель ничего не вернула.
    Это синхронная (блокирующая) функция — вызывающий код должен
    запускать её в отдельном потоке (asyncio.to_thread).
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY не задан — ИИ-ответ невозможен.")
        return None

    prompt = (
        f"{persona}\n\n"
        f"Сообщение собеседника в чате: {user_message}\n\n"
        "Напиши только сам ответ, без кавычек и пояснений."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 1.0,
            "maxOutputTokens": 200,
        },
    }

    try:
        resp = requests.post(
            API_URL,
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"Ошибка запроса к Gemini: {e}")
        return None

    candidates = data.get("candidates") or []
    if not candidates:
        logger.warning(f"Gemini не вернул вариантов ответа: {data}")
        return None

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    return text or None
