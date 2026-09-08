"""
Юзербот: работает от имени вашего личного Telegram-аккаунта.

Что делает:
1. Автокомментинг — в подключённых группах обсуждения (куда канал
   пересылает свои посты) бот первым оставляет осмысленный комментарий
   под каждым новым постом, сгенерированный через Gemini в заданном
   "характере" (персоне).
2. Ответы на сообщения людей — в тех же подключённых группах бот может
   (по желанию, настраивается за группу) время от времени отвечать
   на обычные сообщения участников — тоже через ИИ.

Работает только в группах, которые вы явно подключили через /addgroup —
бот должен уже состоять в этой группе, и группа должна быть привязана
к каналу как "группа обсуждений", чтобы посты пересылались туда автоматически.

Все команды пишутся ВАМИ, от своего аккаунта, в любом чате (например,
в "Избранном"), и начинаются со слэша /. Полный список — команда /help.

Одновременно поднимается веб-панель администратора (Flask) — см. web_panel.py.

Запуск: python userbot.py
Требуются переменные окружения: API_ID, API_HASH, SESSION_STRING, GEMINI_API_KEY
Опционально: ADMIN_USERNAME, ADMIN_PASSWORD (для веб-панели)
"""

import asyncio
import logging
import os
import threading

from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telethon.tl.types import Channel

import ai_reply
import groups_store as store
import settings_store as settings
import web_panel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

if not API_ID or not API_HASH or not SESSION_STRING:
    raise RuntimeError(
        "Не заданы переменные окружения API_ID / API_HASH / SESSION_STRING.\n"
        "Сначала запустите generate_session.py локально, чтобы их получить."
    )

if not ai_reply.is_configured():
    logger.warning(
        "GEMINI_API_KEY не задан — бот запустится, но не сможет отвечать/комментировать, "
        "пока вы не добавите эту переменную окружения."
    )

API_ID = int(API_ID)

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

HELP_TEXT = (
    "🤖 Команды юзербота (пишутся вами, от своего аккаунта):\n\n"
    "— Вкл/выкл —\n"
    "/autoon — включить бота полностью\n"
    "/autooff — выключить бота полностью\n\n"
    "— Группы —\n"
    "/addgroup @username или ID — подключить группу обсуждений (в т.ч. приватную)\n"
    "/discovergroups — список всех групп, где я состою\n"
    "/removegroup @username — отключить группу\n"
    "/mygroups — список подключённых групп\n"
    "/groupreplyon @username — включить ответы на сообщения людей в этой группе\n"
    "/groupreplyoff @username — выключить ответы на сообщения людей в этой группе\n\n"
    "— Автокомментинг постов канала —\n"
    "/commenton — включить автокомментинг\n"
    "/commentoff — выключить автокомментинг\n"
    "/commentinterval — интервал автокомментинга (раз в N постов)\n"
    "/commentinterval <N> — задать его (1 = комментировать каждый пост)\n\n"
    "— ИИ-персона —\n"
    "/persona — показать текущий системный промпт (характер/стиль)\n"
    "/persona <текст> — задать новый характер/стиль\n\n"
    "— Интервал ответов на сообщения людей —\n"
    "/chatinterval — текущий интервал (раз в N сообщений людей)\n"
    "/chatinterval <N> — задать его\n\n"
    "— Прочее —\n"
    "/status — текущее состояние\n"
    "/help — показать этот список команд\n\n"
    "🌐 Все эти настройки также доступны в веб-панели в браузере."
)


def normalize_username(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("@"):
        raw = raw[1:]
    return raw


def is_automatic_channel_forward(message) -> bool:
    """
    Определяет, что сообщение — это автоматически пересланный пост канала
    в привязанную группу обсуждений (а не обычное сообщение человека).
    """
    if not message.fwd_from:
        return False
    if not getattr(message.fwd_from, "channel_post", None):
        return False
    sender = message.sender
    return isinstance(sender, Channel)


async def send_ai_reply(message):
    """
    Генерирует ответ через Gemini на основе текста сообщения/поста и
    текущей персоны, и отправляет его ответом на message. Возвращает
    отправленный текст, либо None, если ответить не удалось.
    """
    user_text = (message.text or message.raw_text or "").strip()
    if not user_text:
        return None

    persona = settings.get_persona()
    reply_text = await asyncio.to_thread(ai_reply.generate_reply, user_text, persona)
    if not reply_text:
        return None

    await message.reply(reply_text)
    return reply_text


# =========================================================
#                 ВКЛ/ВЫКЛ
# =========================================================

@client.on(events.NewMessage(outgoing=True, pattern=r'^/autoon$'))
async def cmd_autoon(event):
    settings.set_enabled(True)
    await event.edit("✅ Бот включён.")


@client.on(events.NewMessage(outgoing=True, pattern=r'^/autooff$'))
async def cmd_autooff(event):
    settings.set_enabled(False)
    await event.edit("⛔ Бот выключен.")


# =========================================================
#                       ГРУППЫ
# =========================================================

@client.on(events.NewMessage(outgoing=True, pattern=r'^/addgroup(?:\s+(.+))?$'))
async def cmd_addgroup(event):
    arg = event.pattern_match.group(1)
    if not arg:
        await event.edit(
            "Использование:\n"
            "/addgroup @username_группы — для публичной группы\n"
            "/addgroup -1001234567890 — по ID (для приватной группы без юзернейма)\n\n"
            "Не знаете ID приватной группы? Используйте /discovergroups."
        )
        return

    raw = arg.strip()

    try:
        if raw.lstrip('-').isdigit():
            entity = await client.get_entity(int(raw))
        else:
            entity = await client.get_entity(normalize_username(raw))
    except Exception:
        await event.edit(
            f"❌ Не удалось найти группу «{raw}». Проверьте юзернейм/ID, "
            f"либо используйте /discovergroups, чтобы выбрать группу из списка."
        )
        return

    if not isinstance(entity, Channel) or not entity.megagroup:
        await event.edit(f"❌ «{raw}» — это не группа обсуждений (супергруппа).")
        return

    label = entity.username or entity.title or str(utils.get_peer_id(entity))
    store.add_group(utils.get_peer_id(entity), username=entity.username, title=entity.title)
    await event.edit(
        f"✅ Группа «{label}» подключена.\n"
        f"Если это группа обсуждений канала — привяжите канал к ней в настройках "
        f"канала в Telegram (Управление → Обсуждение), тогда посты будут пересылаться "
        f"сюда и бот начнёт их комментировать."
    )


@client.on(events.NewMessage(outgoing=True, pattern=r'^/discovergroups$'))
async def cmd_discovergroups(event):
    await event.edit("🔍 Ищу группы, где я состою...")
    results = []
    async for dialog in client.iter_dialogs(limit=300):
        entity = dialog.entity
        if isinstance(entity, Channel) and entity.megagroup:
            results.append((utils.get_peer_id(entity), entity.username, dialog.name))

    if not results:
        await event.edit("Групп (супергрупп) не найдено среди ваших чатов.")
        return

    connected = store.list_groups()
    lines = []
    for chat_id, username, title in results:
        mark = "✅" if str(chat_id) in connected else "➕"
        if username:
            lines.append(f"{mark} @{username} — {title}")
        else:
            lines.append(f"{mark} ID {chat_id} — {title} (приватная)")

    text = (
        "📋 Ваши группы (✅ уже подключена, ➕ ещё нет):\n\n" + "\n".join(lines) +
        "\n\nЧтобы подключить приватную группу, скопируйте её ID и используйте:\n"
        "/addgroup <ID>"
    )
    await event.edit(text)


@client.on(events.NewMessage(outgoing=True, pattern=r'^/removegroup(?:\s+(.+))?$'))
async def cmd_removegroup(event):
    arg = event.pattern_match.group(1)
    if not arg:
        await event.edit("Использование: /removegroup @username_группы")
        return

    username = normalize_username(arg)
    removed = store.remove_group_by_username(username)

    if removed:
        await event.edit(f"✅ Группа @{username} отключена.")
    else:
        await event.edit(f"Группа @{username} не найдена среди подключённых.")


@client.on(events.NewMessage(outgoing=True, pattern=r'^/groupreplyon(?:\s+(.+))?$'))
async def cmd_groupreplyon(event):
    arg = event.pattern_match.group(1)
    if not arg:
        await event.edit("Использование: /groupreplyon @username_группы")
        return
    username = normalize_username(arg)
    for chat_id, info in store.list_groups().items():
        if info.get("username") == username:
            store.set_reply_enabled(int(chat_id), True)
            await event.edit(f"✅ Ответы на сообщения людей включены в группе @{username}.")
            return
    await event.edit(f"❌ Группа @{username} не найдена среди подключённых.")


@client.on(events.NewMessage(outgoing=True, pattern=r'^/groupreplyoff(?:\s+(.+))?$'))
async def cmd_groupreplyoff(event):
    arg = event.pattern_match.group(1)
    if not arg:
        await event.edit("Использование: /groupreplyoff @username_группы")
        return
    username = normalize_username(arg)
    for chat_id, info in store.list_groups().items():
        if info.get("username") == username:
            store.set_reply_enabled(int(chat_id), False)
            await event.edit(f"⛔ Ответы на сообщения людей выключены в группе @{username}.")
            return
    await event.edit(f"❌ Группа @{username} не найдена среди подключённых.")


@client.on(events.NewMessage(outgoing=True, pattern=r'^/mygroups$'))
async def cmd_mygroups(event):
    groups = store.list_groups()
    if not groups:
        await event.edit("Подключённых групп пока нет. Используйте /addgroup @username")
        return

    lines = []
    for info in groups.values():
        label = store.display_label(info)
        reply_state = "ответы: вкл" if info.get("reply_enabled", True) else "ответы: выкл"
        lines.append(f"• {label} ({reply_state})")
    await event.edit("📋 Подключённые группы:\n" + "\n".join(lines))


# =========================================================
#                    АВТОКОММЕНТИНГ
# =========================================================

@client.on(events.NewMessage(outgoing=True, pattern=r'^/commenton$'))
async def cmd_commenton(event):
    settings.set_autocomment_enabled(True)
    await event.edit("✅ Автокомментинг включён.")


@client.on(events.NewMessage(outgoing=True, pattern=r'^/commentoff$'))
async def cmd_commentoff(event):
    settings.set_autocomment_enabled(False)
    await event.edit("⛔ Автокомментинг выключен.")


@client.on(events.NewMessage(outgoing=True, pattern=r'^/commentinterval(?:\s+(\d+))?$'))
async def cmd_commentinterval(event):
    arg = event.pattern_match.group(1)
    if not arg:
        current = settings.get_autocomment_interval()
        await event.edit(
            f"Автокомментинг: раз в {current} пост(ов).\n"
            f"Изменить: /commentinterval <N>, например /commentinterval 1 (каждый пост)"
        )
        return

    n = int(arg)
    if settings.set_autocomment_interval(n):
        await event.edit(f"✅ Автокомментинг: раз в {n} пост(ов).")
    else:
        await event.edit("❌ Интервал должен быть числом ≥ 1.")


# =========================================================
#                    ИИ-ПЕРСОНА
# =========================================================

@client.on(events.NewMessage(outgoing=True, pattern=r'^/persona(?:\s+([\s\S]+))?$'))
async def cmd_persona(event):
    arg = event.pattern_match.group(1)
    if not arg:
        current = settings.get_persona()
        await event.edit(
            f"Текущая ИИ-персона (системный промпт):\n\n{current}\n\n"
            f"Изменить: /persona <новый текст>"
        )
        return

    settings.set_persona(arg.strip())
    await event.edit("✅ ИИ-персона обновлена.")


# =========================================================
#                      ИНТЕРВАЛЫ
# =========================================================

@client.on(events.NewMessage(outgoing=True, pattern=r'^/chatinterval(?:\s+(\d+))?$'))
async def cmd_chatinterval(event):
    arg = event.pattern_match.group(1)
    if not arg:
        current = settings.get_chat_interval()
        await event.edit(
            f"Интервал ответов на сообщения людей: раз в {current} сообщений(-ие).\n"
            f"Изменить: /chatinterval <N>, например /chatinterval 4"
        )
        return

    n = int(arg)
    if settings.set_chat_interval(n):
        await event.edit(f"✅ Ответы на сообщения людей: раз в {n} сообщений(-ие).")
    else:
        await event.edit("❌ Интервал должен быть числом ≥ 1.")


# =========================================================
#                      ПРОЧЕЕ
# =========================================================

@client.on(events.NewMessage(outgoing=True, pattern=r'^/status$'))
async def cmd_status(event):
    groups = store.list_groups()
    state = "включён ✅" if settings.is_enabled() else "выключен ⛔"
    ai_state = "настроен ✅" if ai_reply.is_configured() else "нет ключа GEMINI_API_KEY ⛔"
    comment_state = "включён ✅" if settings.is_autocomment_enabled() else "выключен ⛔"

    await event.edit(
        f"Бот: {state}\n"
        f"Gemini: {ai_state}\n"
        f"Подключено групп: {len(groups)}\n\n"
        f"Автокомментинг: {comment_state}\n"
        f"Интервал автокомментинга: раз в {settings.get_autocomment_interval()} пост(ов)\n\n"
        f"Ответы на сообщения людей: раз в {settings.get_chat_interval()} сообщений(-ие)"
    )


@client.on(events.NewMessage(outgoing=True, pattern=r'^/help$'))
async def cmd_help(event):
    await event.edit(HELP_TEXT)


# =========================================================
#          АВТОКОММЕНТИНГ ПОСТОВ КАНАЛА
# =========================================================

@client.on(events.NewMessage(incoming=True))
async def auto_comment(event):
    if not store.is_allowed(event.chat_id):
        return
    if not settings.is_enabled():
        return
    if not settings.is_autocomment_enabled():
        return

    message = event.message
    if not is_automatic_channel_forward(message):
        return
    if not (message.text or message.raw_text):
        return
    if not settings.bump_and_should_comment(event.chat_id):
        return

    try:
        sent_text = await send_ai_reply(message)
        if sent_text is None:
            logger.warning("ИИ не вернул комментарий — пост оставлен без комментария.")
            return
        logger.info(f"[autocomment] Прокомментировал '{sent_text}' в чате {event.chat_id}")
    except Exception as e:
        logger.warning(f"Не удалось прокомментировать пост в чате {event.chat_id}: {e}")


# =========================================================
#          ОТВЕТЫ НА СООБЩЕНИЯ ЛЮДЕЙ В ГРУППЕ
# =========================================================

@client.on(events.NewMessage(incoming=True))
async def chat_reply(event):
    if not store.is_allowed(event.chat_id):
        return
    if not store.is_reply_enabled(event.chat_id):
        return
    if not settings.is_enabled():
        return

    message = event.message

    if is_automatic_channel_forward(message):
        return  # посты канала обрабатывает auto_comment, не этот хендлер
    if not (message.text or message.raw_text):
        return
    if not settings.bump_and_should_reply_chat(event.chat_id):
        return

    try:
        sent_text = await send_ai_reply(message)
        if sent_text is None:
            logger.warning("ИИ не вернул ответ — сообщение в группе оставлено без ответа.")
            return
        logger.info(f"[chat] Ответил '{sent_text}' в чате {event.chat_id}")
    except Exception as e:
        logger.warning(f"Не удалось ответить в чате {event.chat_id}: {e}")


async def main():
    await client.start()
    me = await client.get_me()
    logger.info(f"Юзербот запущен под аккаунтом: {me.first_name} (id {me.id})")
    logger.info(f"Включён: {settings.is_enabled()}, Gemini настроен: {ai_reply.is_configured()}")
    logger.info(
        f"Автокомментинг: {settings.is_autocomment_enabled()}, "
        f"интервал: {settings.get_autocomment_interval()}"
    )
    logger.info(f"Интервал ответов на сообщения людей: {settings.get_chat_interval()}")

    loop = asyncio.get_running_loop()
    web_panel.set_client(client, loop)

    panel_thread = threading.Thread(target=web_panel.run_panel, daemon=True)
    panel_thread.start()
    logger.info("Веб-панель запущена в фоновом потоке.")

    logger.info("Ожидаю новые посты и сообщения в подключённых группах...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
