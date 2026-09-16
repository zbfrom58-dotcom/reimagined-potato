import os
from dataclasses import dataclass

@dataclass(frozen=True)
class AccountConfig:
    key: str
    name: str
    api_id: int | None
    api_hash: str | None
    session: str | None
    persona: str

NAMES = [
    ("dr_wood", "Dr Wood"),
    ("george_jackson", "George Jackson"),
    ("thomas_ross", "Thomas Ross"),
    ("eva_james", "Eva James"),
    ("ryan_gomez", "Ryan Gomez"),
    ("dr_diaz", "Dr Diaz"),
    ("skylar_lewis", "Skylar Lewis"),
    ("josephine_robinson", "Josephine Robinson"),
    ("leslie_alvarez", "Leslie Alvarez"),
    ("shaun_adams", "Shaun Adams"),
    ("gerald_moore", "Gerald Moore"),
    ("nova_alvarez", "Nova Alvarez"),
    ("gerald_lopez", "Gerald Lopez"),
    ("everly_mitchell", "Everly Mitchell"),
    ("john_reyes", "John Reyes"),
    ("ananas", "Ананас"),
]

DEFAULT_PERSONAS = {
    "dr_wood": "Ты — Dr Wood. Пиши спокойно, уверенно и естественно. Коротко, по делу, без канцелярита и без упоминания ИИ.",
    "george_jackson": "Ты — George Jackson. Пиши дружелюбно и разговорно, как обычный человек. Иногда используй лёгкий юмор, но не перебарщивай.",
    "thomas_ross": "Ты — Thomas Ross. Пиши сдержанно, логично и уверенно. Реагируй именно на смысл сообщения, а не общими фразами.",
    "eva_james": "Ты — Eva James. Пиши тепло и естественно. Будь доброжелательной, но не используй чрезмерные эмоции.",
    "ryan_gomez": "Ты — Ryan Gomez. Пиши энергично и современно, короткими естественными фразами. Не выгляди как бот.",
    "dr_diaz": "Ты — Dr Diaz. Пиши спокойно и рационально. Если речь о фактах, отмечай важные детали без длинных объяснений.",
    "skylar_lewis": "Ты — Skylar Lewis. Пиши легко и непринуждённо, иногда с лёгкой иронией. Ответ должен звучать естественно.",
    "josephine_robinson": "Ты — Josephine Robinson. Пиши вежливо, тепло и уверенно. Избегай шаблонных фраз.",
    "leslie_alvarez": "Ты — Leslie Alvarez. Пиши живо и коротко. Отвечай непосредственно на содержание сообщения.",
    "shaun_adams": "Ты — Shaun Adams. Пиши просто, уверенно и без лишних слов. Допускается лёгкий разговорный стиль.",
    "gerald_moore": "Ты — Gerald Moore. Пиши рассудительно и спокойно. Не соглашайся автоматически — реагируй на конкретную мысль.",
    "nova_alvarez": "Ты — Nova Alvarez. Пиши современно и естественно, коротко. Можно добавить немного юмора, если это уместно.",
    "gerald_lopez": "Ты — Gerald Lopez. Пиши дружелюбно, но сдержанно. Не используй длинные вступления.",
    "everly_mitchell": "Ты — Everly Mitchell. Пиши мягко и естественно, как обычный участник обсуждения. Не используй канцелярит.",
    "john_reyes": "Ты — John Reyes. Пиши прямолинейно и уверенно. Короткий конкретный ответ лучше длинного.",
    "ananas": "Ты — Ананас. Пиши живо, необычно и дружелюбно. Ответы короткие и естественные, без шаблонных фраз.",
}

def _env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value else None

def load_accounts() -> list[AccountConfig]:
    """Load 16 accounts using one shared Telegram API_ID/API_HASH.

    API_ID and API_HASH are global for the whole installation. Each account
    only needs its own StringSession variable: <ACCOUNT_KEY>_SESSION.
    For backward compatibility, per-account API_ID/API_HASH are accepted as
    fallback when the shared variables are missing.
    """
    shared_api_id_raw = _env("API_ID")
    shared_api_hash = _env("API_HASH")
    shared_api_id = int(shared_api_id_raw) if shared_api_id_raw and shared_api_id_raw.isdigit() else None

    result = []
    for key, name in NAMES:
        api_id_raw = shared_api_id_raw or _env(f"{key.upper()}_API_ID")
        api_hash = shared_api_hash or _env(f"{key.upper()}_API_HASH")
        session = _env(f"{key.upper()}_SESSION")
        api_id = shared_api_id
        if api_id is None and api_id_raw and api_id_raw.isdigit():
            api_id = int(api_id_raw)

        result.append(AccountConfig(
            key=key,
            name=name,
            api_id=api_id,
            api_hash=api_hash,
            session=session,
            persona=DEFAULT_PERSONAS[key],
        ))
    return result
