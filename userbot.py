
import asyncio
import logging
import threading

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Channel

import ai_reply
import multi_store as store
import web_panel
from accounts import load_accounts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 16 independent Telegram accounts.
CONFIGS = load_accounts()
RUNTIME = {}
RUNTIME_LOCK = threading.RLock()


def is_automatic_channel_forward(message):
    return bool(
        message.fwd_from
        and getattr(message.fwd_from, "channel_post", None)
        and isinstance(message.sender, Channel)
    )


def build_client(cfg):
    if not cfg.api_id or not cfg.api_hash or not cfg.session:
        return None
    return TelegramClient(StringSession(cfg.session), cfg.api_id, cfg.api_hash)


async def generate_and_send(key, message):
    text = (message.text or message.raw_text or "").strip()
    if not text:
        return None

    cfg = RUNTIME[key]["config"]
    if store.is_common_mode():
        persona = store.get_common_persona(cfg.persona)
    else:
        persona = store.get_persona(key, cfg.persona)

    reply = await asyncio.to_thread(ai_reply.generate_reply, text, persona)
    if reply:
        await message.reply(reply)
    return reply


def register_handlers(key, client):
    @client.on(events.NewMessage(outgoing=True, pattern=r"^/autoon$"))
    async def autoon(event):
        store.set_enabled(key, True)
        await event.edit("✅ Этот аккаунт включён.")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/autooff$"))
    async def autooff(event):
        store.set_enabled(key, False)
        await event.edit("⛔ Этот аккаунт выключен.")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/persona(?:\s+([\s\S]+))?$"))
    async def persona(event):
        arg = event.pattern_match.group(1)
        if arg:
            store.set_persona(key, arg.strip())
            await event.edit("✅ Persona сохранена.")
        else:
            cfg = RUNTIME[key]["config"]
            await event.edit(store.get_persona(key, cfg.persona))

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/status$"))
    async def status(event):
        rt = RUNTIME[key]
        await event.edit(
            f"{rt['config'].name}\n"
            f"Runtime: {rt['status']}\n"
            f"Telegram: {rt.get('me') or 'не авторизован'}\n"
            f"Автоответ: {'🟢' if store.is_enabled(key) else '🔴'}\n"
            f"Групп: {len(store.list_groups(key))}\n"
            f"Gemini: {'🟢' if ai_reply.is_configured() else '🔴'}"
        )

    @client.on(events.NewMessage(incoming=True))
    async def incoming(event):
        if store.is_common_mode():
            if not store.is_common_enabled():
                return
            if not store.is_common_allowed(event.chat_id):
                return
        else:
            if not store.is_enabled(key):
                return
            if not store.is_allowed(key, event.chat_id):
                return

        message = event.message
        if not (message.text or message.raw_text):
            return

        if is_automatic_channel_forward(message):
            if not store.is_autocomment_enabled(key):
                return
            if not store.bump_and_should_comment(key, event.chat_id):
                return
        else:
            if store.is_common_mode():
                if not store.is_common_reply_enabled(event.chat_id):
                    return
            elif not store.is_reply_enabled(key, event.chat_id):
                return

            if not store.bump_and_should_reply_chat(key, event.chat_id):
                return

        try:
            await generate_and_send(key, message)
        except Exception:
            logger.exception("[%s] message handler error", key)


async def start_account(key):
    rt = RUNTIME.get(key)
    if rt is None:
        return False, "Аккаунт не найден."
    if rt.get("client") is not None:
        return True, "Уже запущен."

    cfg = rt["config"]
    if not cfg.api_id or not cfg.api_hash or not cfg.session:
        rt["status"] = "error"
        rt["error"] = "Не заданы API_ID/API_HASH/SESSION."
        return False, rt["error"]

    client = build_client(cfg)
    if client is None:
        return False, "Не удалось создать Telegram client."

    rt["client"] = client
    rt["status"] = "starting"
    rt["error"] = ""

    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram-сессия не авторизована.")

        me = await client.get_me()
        name = " ".join(x for x in [me.first_name, me.last_name] if x).strip()
        rt["me"] = name or getattr(me, "username", None) or str(me.id)
        rt["status"] = "running"
        register_handlers(key, client)

        logger.info("[%s] started: %s", key, rt["me"])
        return True, f"Запущен: {rt['me']}"
    except Exception as exc:
        rt["client"] = None
        rt["status"] = "error"
        rt["error"] = str(exc)
        try:
            await client.disconnect()
        except Exception:
            pass
        logger.exception("[%s] start error", key)
        return False, str(exc)


async def stop_account(key):
    rt = RUNTIME.get(key)
    if rt is None:
        return False, "Аккаунт не найден."

    if rt.get("client"):
        try:
            await rt["client"].disconnect()
        except Exception:
            logger.exception("[%s] disconnect error", key)

    rt["client"] = None
    rt["status"] = "stopped"
    rt["error"] = ""
    logger.info("[%s] stopped", key)
    return True, "Остановлен."


def init_runtime():
    with RUNTIME_LOCK:
        RUNTIME.clear()
        for cfg in CONFIGS:
            RUNTIME[cfg.key] = {
                "config": cfg,
                "client": None,
                "status": "stopped",
                "me": "",
                "error": "",
                "common_started": False,
            }

    logger.info("RUNTIME: %s", ", ".join(RUNTIME.keys()))


async def start_enabled_accounts():
    for cfg in CONFIGS:
        if store.is_enabled(cfg.key):
            await start_account(cfg.key)


async def start_common_accounts():
    for cfg in CONFIGS:
        ok, msg = await start_account(cfg.key)
        if ok:
            RUNTIME[cfg.key]["common_started"] = True
        else:
            logger.error("[%s] common start failed: %s", cfg.key, msg)


async def main():
    init_runtime()
    loop = asyncio.get_running_loop()

    # The panel receives the same per-account RUNTIME dictionary.
    web_panel.set_runtime(
        RUNTIME, loop, start_account, stop_account, configs=CONFIGS
    )

    threading.Thread(
        target=web_panel.run_panel,
        daemon=True,
        name="web-panel",
    ).start()

    if store.is_common_mode() and store.is_common_enabled():
        await start_common_accounts()
    else:
        await start_enabled_accounts()

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
