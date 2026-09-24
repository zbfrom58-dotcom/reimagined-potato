import logging
import os
import requests

logger = logging.getLogger(__name__)

MODEL = "deepseek-flash"
BASE_URL = "https://api.deepseek.com"
TIMEOUT = 20


def _load_key() -> str | None:
    value = os.getenv("DEEPSEEK_API_KEY")
    return value.strip() if value and value.strip() else None


def is_configured() -> bool:
    return bool(_load_key())


def list_configured_keys() -> int:
    return 1 if _load_key() else 0


def list_models():
    return [MODEL] if _load_key() else []


def generate_reply(user_message: str, persona: str, *, extra_context: str = "") -> str | None:
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
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            logger.error("DeepSeek HTTP %s: %s", response.status_code, response.text[:500])
            return None

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            logger.warning("DeepSeek вернул ответ без choices")
            return None

        text = ((choices[0].get("message") or {}).get("content") or "").strip()
        return text or None

    except requests.Timeout:
        logger.warning("DeepSeek timeout")
    except requests.RequestException as e:
        logger.warning("Ошибка DeepSeek: %s", e)
    except (ValueError, TypeError, KeyError) as e:
        logger.warning("Не удалось разобрать ответ DeepSeek: %s", e)
    return None
