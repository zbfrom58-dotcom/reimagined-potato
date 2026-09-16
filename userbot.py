import asyncio
import logging
import os
import threading
from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession
from telethon.tl.types import Channel

import ai_reply
import multi_store as store
import web_panel
from accounts import load_accounts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIGS = load_accounts()
RUNTIME = {}
RUNTIME_LOCK = threading.RLock()

def is_automatic_channel_forward(message) -> bool:
    if not message.fwd_from:
        return False
    if not getattr(message.fwd_from, "channel_post", None):
        return False
    return isinstance(message.sender, Channel)

async def generate_and_send(account_key, message):
    text = (message.text or message.raw_text or "").strip()
    if not text:
        return None
    cfg = RUNTIME[account_key]["config"]
    if store.is_common_mode():
        persona = store.get_common_persona(cfg.persona)
    else:
        persona = store.get_persona(account_key, cfg.persona)
    reply = await asyncio.to_thread(ai_reply.generate_reply, text, persona)
    if reply:
        await message.reply(reply)
    return reply

def build_client(cfg):
    if not cfg.api_id or not cfg.api_hash or not cfg.session:
        return None
    return TelegramClient(StringSession(cfg.session), cfg.api_id, cfg.api_hash)

def register_handlers(account_key, client):
    @client.on(events.NewMessage(outgoing=True, pattern=r'^/autoon$'))
    async def autoon(event):
        store.set_enabled(account_key, True)
        await event.edit("✅ Этот аккаунт включён.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'^/autooff$'))
    async def autooff(event):
        store.set_enabled(account_key, False)
        await event.edit("⛔ Этот аккаунт выключен.")

    @client.on(events.NewMessage(outgoing=True, pattern=r'^/persona(?:\s+([\s\S]+))?$'))
    async def persona(event):
        arg = event.pattern_match.group(1)
        if arg:
            store.set_persona(account_key, arg.strip())
            await event.edit("✅ Персона сохранена для этого аккаунта.")
        else:
            cfg = RUNTIME[account_key]["config"]
            await event.edit(store.get_persona(account_key, cfg.persona))

    @client.on(events.NewMessage(outgoing=True, pattern=r'^/status$'))
    async def status(event):
        await event.edit(
            f"{RUNTIME[account_key]['config'].name}\n"
            f"Статус: {'🟢 включён' if store.is_enabled(account_key) else '🔴 выключен'}\n"
            f"Gemini: {'🟢' if ai_reply.is_configured() else '🔴'}\n"
            f"Групп: {len(store.list_groups(account_key))}"
        )

    @client.on(events.NewMessage(incoming=True))
    async def incoming(event):
        if not store.is_enabled(account_key):
            return

        chat_id = event.chat_id
        # In common mode every account uses the shared group list.
        allowed = store.is_common_allowed(chat_id) if store.is_common_mode() else store.is_allowed(account_key, chat_id)
        if not allowed:
            return

        message = event.message
        if not (message.text or message.raw_text):
            return

        if is_automatic_channel_forward(message):
            if not store.is_autocomment_enabled(account_key):
                return
            if not store.bump_and_should_comment(account_key, chat_id):
                return
        else:
            if store.is_common_mode():
                if not store.is_common_reply_enabled(chat_id):
                    return
            else:
                if not store.is_reply_enabled(account_key, chat_id):
                    return
            # Common mode defaults to one response per incoming message.
            if not store.bump_and_should_reply_chat(account_key, chat_id):
                return

        try:
            await generate_and_send(account_key, message)
        except Exception:
            logger.exception("[%s] Ошибка обработки сообщения", account_key)

async def start_account(account_key):
    runtime = RUNTIME[account_key]
    if runtime["client"] is not None:
        return True, "Уже запущен."

    client = build_client(runtime["config"])
    if client is None:
        return False, "Не заданы API_ID/API_HASH/SESSION."

    runtime["client"] = client
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram-сессия не авторизована. Добавьте корректный SESSION для этого аккаунта.")
        me = await client.get_me()
        runtime["me"] = f"{me.first_name or ''} {me.last_name or ''}".strip()
        runtime["status"] = "running"
        register_handlers(account_key, client)
        logger.info("[%s] запущен: %s", account_key, runtime["me"])
        return True, f"Запущен: {runtime['me']}"
    except Exception as e:
        runtime["client"] = None
        runtime["status"] = "error"
        runtime["error"] = str(e)
        logger.exception("[%s] Не удалось запустить", account_key)
        return False, str(e)

async def stop_account(account_key):
    runtime = RUNTIME[account_key]
    client = runtime.get("client")
    if client:
        await client.disconnect()
    runtime["client"] = None
    runtime["status"] = "stopped"
    return True, "Остановлен."

async def start_enabled_accounts():
    for cfg in CONFIGS:
        if store.is_enabled(cfg.key):
            await start_account(cfg.key)

def init_runtime():
    for cfg in CONFIGS:
        RUNTIME[cfg.key] = {
            "config": cfg,
            "client": None,
            "status": "stopped",
            "me": "",
            "error": "",
        }

async def main():
    init_runtime()
    loop = asyncio.get_running_loop()
    web_panel.set_runtime(RUNTIME, loop, start_account, stop_account)
    threading.Thread(target=web_panel.run_panel, daemon=True).start()

    await start_enabled_accounts()

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
