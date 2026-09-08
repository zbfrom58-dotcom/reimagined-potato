"""
Генерация текста ответа через Google Gemini API.
"""

import logging
import os

import requests


logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Можно переопределить через Railway Variables.
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

TIMEOUT = 30


def is_configured() -> bool:
    return bool(GEMINI_API_KEY)


def list_models() -> list[str]:
    """
    Возвращает список моделей, которые реально доступны
    текущему GEMINI_API_KEY.
    """

    if not GEMINI_API_KEY:
        return []

    try:
        response = requests.get(
            f"{BASE_URL}/models",
            params={"key": GEMINI_API_KEY},
            timeout=TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        return [
            model.get("name", "").replace("models/", "")
            for model in data.get("models", [])
            if "generateContent"
            in model.get("supportedGenerationMethods", [])
        ]

    except Exception as e:
        logger.warning("Не удалось получить список моделей Gemini: %s", e)
        return []


def generate_reply(user_message: str, persona: str) -> str | None:
    if not GEMINI_API_KEY:
        logger.warning(
            "GEMINI_API_KEY не задан — ИИ-ответ невозможен."
        )
        return None

    prompt = (
        f"{persona}\n\n"
        f"Сообщение собеседника в чате: {user_message}\n\n"
        "Напиши только сам ответ, без кавычек и пояснений."
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 1.0,
            "maxOutputTokens": 200,
        },
    }

    api_url = (
        f"{BASE_URL}/models/{MODEL}:generateContent"
    )

    try:
        response = requests.post(
            api_url,
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=TIMEOUT,
        )

        if response.status_code != 200:
            logger.error(
                "Gemini HTTP %s. Model=%s. Response=%s",
                response.status_code,
                MODEL,
                response.text[:1000],
            )
            return None

        data = response.json()

    except requests.Timeout:
        logger.warning(
            "Gemini не ответил за %s секунд.",
            TIMEOUT,
        )
        return None

    except requests.RequestException as e:
        logger.warning(
            "Ошибка сети при запросе к Gemini: %s",
            e,
        )
        return None

    except Exception as e:
        logger.exception(
            "Неожиданная ошибка Gemini: %s",
            e,
        )
        return None

    candidates = data.get("candidates") or []

    if not candidates:
        logger.warning(
            "Gemini не вернул вариантов ответа: %s",
            data,
        )
        return None

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []

    text = "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict)
    ).strip()

    if not text:
        logger.warning(
            "Gemini вернул кандидата без текста: %s",
            data,
        )
        return None

    return text
