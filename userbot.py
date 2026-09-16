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
    persona = store.get_persona(account_key, cfg.persona)
    reply = await asyncio.to_thread(ai_reply.generate_reply, text, persona)
    if reply:
        await message.reply(reply)
    return reply

def build_client(cfg):
    """Create a Telegram client only from a pre-authorized StringSession.

    Railway cannot answer Telethon's interactive phone/code prompts, so
    authentication is deliberately never started from a blank session here.
    """
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
        if not store.is_allowed(account_key, event.chat_id):
            return
        message = event.message
        if not (message.text or message.raw_text):
            return

        if is_automatic_channel_forward(message):
            if not store.is_autocomment_enabled(account_key):
                return
            if not store.bump_and_should_comment(account_key, event.chat_id):
                return
        else:
            if not store.is_reply_enabled(account_key, event.chat_id):
                return
            if not store.bump_and_should_reply_chat(account_key, event.chat_id):
                return

        try:
            await generate_and_send(account_key, message)
        except Exception:
            logger.exception("[%s] Ошибка обработки сообщения", account_key)

async def start_account(account_key):
    runtime = RUNTIME[account_key]
    if runtime["client"] is not None:
        return True, "Уже запущен."

    cfg = runtime["config"]
    if not cfg.api_id or not cfg.api_hash:
        runtime["status"] = "auth_required"
        runtime["error"] = "Не заданы API_ID/API_HASH."
        return False, "Не заданы API_ID/API_HASH."
    if not cfg.session:
        runtime["status"] = "auth_required"
        runtime["error"] = "Не задан SESSION. Сначала добавь готовую StringSession в Railway Variables."
        return False, "Не задан SESSION. Добавь готовую StringSession в Railway Variables."

    try:
        client = build_client(cfg)
    except Exception as e:
        runtime["status"] = "auth_required"
        runtime["error"] = f"Некорректный SESSION: {e}"
        logger.exception("[%s] Некорректный SESSION", account_key)
        return False, f"Некорректный SESSION: {e}"

    runtime["client"] = client
    try:
        # IMPORTANT: do not use client.start() here. With an empty/invalid
        # session Telethon calls input() for a phone number, which crashes on
        # Railway. connect() + is_user_authorized() never asks for input.
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            runtime["client"] = None
            runtime["status"] = "auth_required"
            runtime["error"] = "SESSION не авторизована. Сгенерируй новую StringSession локально и добавь её в Railway."
            return False, "SESSION не авторизована. Нужна готовая авторизованная StringSession."

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
