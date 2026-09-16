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

# More detailed logs are intentional: they show exactly why a message is
# accepted, skipped, sent to Gemini, or fails to send.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

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
        logger.info("[%s] skip: empty text", key)
        return None

    cfg = RUNTIME[key]["config"]
    common = store.is_common_mode()

    if common:
        persona = store.get_common_persona(cfg.persona)
    else:
        persona = store.get_persona(key, cfg.persona)

    logger.info(
        "[%s] generating Gemini reply | chat_id=%s | text=%r | common=%s",
        key,
        getattr(message, "chat_id", None),
        text[:300],
        common,
    )

    try:
        reply = await asyncio.to_thread(ai_reply.generate_reply, text, persona)
    except Exception:
        logger.exception("[%s] Gemini ERROR", key)
        return None

    if not reply:
        logger.warning("[%s] Gemini returned empty reply", key)
        return None

    logger.info("[%s] Gemini reply received: %r", key, reply[:500])

    try:
        logger.info("[%s] sending reply to chat_id=%s", key, message.chat_id)
        await message.reply(reply)
        logger.info("[%s] reply SENT to chat_id=%s", key, message.chat_id)
    except Exception:
        logger.exception("[%s] SEND ERROR to chat_id=%s", key, message.chat_id)
        return None

    return reply


def register_handlers(key, client):
    @client.on(events.NewMessage(outgoing=True, pattern=r"^/autoon$"))
    async def autoon(event):
        store.set_enabled(key, True)
        logger.info("[%s] /autoon -> account auto-reply ENABLED", key)
        await event.edit("✅ Этот аккаунт включён.")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/autooff$"))
    async def autooff(event):
        store.set_enabled(key, False)
        logger.info("[%s] /autooff -> account auto-reply DISABLED", key)
        await event.edit("⛔ Этот аккаунт выключен.")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/persona(?:\s+([\s\S]+))?$"))
    async def persona(event):
        arg = event.pattern_match.group(1)
        if arg:
            store.set_persona(key, arg.strip())
            logger.info("[%s] persona updated", key)
            await event.edit("✅ Persona сохранена.")
        else:
            cfg = RUNTIME[key]["config"]
            await event.edit(store.get_persona(key, cfg.persona))

    @client.on(events.NewMessage(outgoing=True, pattern=r"^/status$"))
    async def status(event):
        rt = RUNTIME[key]
        enabled = store.is_enabled(key)
        logger.info(
            "[%s] /status | runtime=%s | auto_reply=%s | groups=%s | gemini=%s",
            key,
            rt["status"],
            enabled,
            len(store.list_groups(key)),
            ai_reply.is_configured(),
        )
        await event.edit(
            f"{rt['config'].name}\n"
            f"Runtime: {rt['status']}\n"
            f"Telegram: {rt.get('me') or 'не авторизован'}\n"
            f"Автоответ: {'🟢' if enabled else '🔴'}\n"
            f"Групп: {len(store.list_groups(key))}\n"
            f"Gemini: {'🟢' if ai_reply.is_configured() else '🔴'}"
        )

    @client.on(events.NewMessage(incoming=True))
    async def incoming(event):
        message = event.message
        chat_id = event.chat_id
        text = (message.text or message.raw_text or "").strip()

        # This line is the most important diagnostic signal. If it appears,
        # Telethon delivered the incoming message to our handler.
        logger.info(
            "[%s] NEW MESSAGE | chat_id=%s | is_group=%s | is_channel=%s | text=%r",
            key,
            chat_id,
            getattr(event, "is_group", False),
            getattr(event, "is_channel", False),
            text[:300],
        )

        if not text:
            logger.info("[%s] SKIP | empty/non-text message | chat_id=%s", key, chat_id)
            return

        common = store.is_common_mode()
        logger.info(
            "[%s] STATE | common_mode=%s | account_enabled=%s | common_enabled=%s",
            key,
            common,
            store.is_enabled(key),
            store.is_common_enabled(),
        )

        if common:
            if not store.is_common_enabled():
                logger.info("[%s] SKIP | common mode is disabled", key)
                return

            allowed = store.is_common_allowed(chat_id)
            logger.info("[%s] COMMON | allowed=%s | chat_id=%s", key, allowed, chat_id)
            if not allowed:
                logger.info("[%s] SKIP | chat is not in common groups", key)
                return
        else:
            enabled = store.is_enabled(key)
            logger.info("[%s] PERSONAL | enabled=%s | chat_id=%s", key, enabled, chat_id)
            if not enabled:
                logger.info(
                    "[%s] SKIP | account auto-reply is OFF (runtime can still be running)",
                    key,
                )
                return

            allowed = store.is_allowed(key, chat_id)
            logger.info("[%s] PERSONAL | allowed=%s | chat_id=%s", key, allowed, chat_id)
            if not allowed:
                logger.info("[%s] SKIP | chat is not allowed for this account", key)
                return

        try:
            forwarded = is_automatic_channel_forward(message)
        except Exception:
            forwarded = False
            logger.exception("[%s] error while detecting channel forward", key)

        logger.info("[%s] MESSAGE TYPE | automatic_channel_forward=%s", key, forwarded)

        if forwarded:
            auto_comment = store.is_autocomment_enabled(key)
            logger.info("[%s] AUTOCOMMENT | enabled=%s", key, auto_comment)
            if not auto_comment:
                logger.info("[%s] SKIP | autocomment is OFF", key)
                return

            should_comment = store.bump_and_should_comment(key, chat_id)
            logger.info(
                "[%s] AUTOCOMMENT | should_comment=%s | chat_id=%s",
                key,
                should_comment,
                chat_id,
            )
            if not should_comment:
                logger.info("[%s] SKIP | comment interval has not elapsed", key)
                return
        else:
            if common:
                reply_enabled = store.is_common_reply_enabled(chat_id)
                logger.info(
                    "[%s] COMMON REPLY | enabled=%s | chat_id=%s",
                    key,
                    reply_enabled,
                    chat_id,
                )
            else:
                reply_enabled = store.is_reply_enabled(key, chat_id)
                logger.info(
                    "[%s] PERSONAL REPLY | enabled=%s | chat_id=%s",
                    key,
                    reply_enabled,
                    chat_id,
                )

            if not reply_enabled:
                logger.info("[%s] SKIP | replies are OFF for this chat", key)
                return

            should_reply = store.bump_and_should_reply_chat(key, chat_id)
            logger.info(
                "[%s] REPLY INTERVAL | should_reply=%s | chat_id=%s",
                key,
                should_reply,
                chat_id,
            )
            if not should_reply:
                logger.info("[%s] SKIP | reply interval has not elapsed", key)
                return

        await generate_and_send(key, message)


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
        logger.error("[%s] cannot start: missing API_ID/API_HASH/SESSION", key)
        return False, rt["error"]

    client = build_client(cfg)
    if client is None:
        rt["status"] = "error"
        rt["error"] = "Не удалось создать Telegram client."
        logger.error("[%s] cannot create Telegram client", key)
        return False, rt["error"]

    rt["client"] = client
    rt["status"] = "starting"
    rt["error"] = ""

    try:
        logger.info("[%s] connecting to Telegram...", key)
        await client.connect()

        authorized = await client.is_user_authorized()
        logger.info("[%s] Telegram authorized=%s", key, authorized)
        if not authorized:
            raise RuntimeError("Telegram-сессия не авторизована.")

        me = await client.get_me()
        name = " ".join(x for x in [me.first_name, me.last_name] if x).strip()
        rt["me"] = name or getattr(me, "username", None) or str(me.id)
        rt["status"] = "running"

        register_handlers(key, client)

        logger.info(
            "[%s] STARTED | telegram=%s | auto_reply=%s | gemini=%s | groups=%s",
            key,
            rt["me"],
            store.is_enabled(key),
            ai_reply.is_configured(),
            len(store.list_groups(key)),
        )
        return True, f"Запущен: {rt['me']}"
    except Exception as exc:
        rt["client"] = None
        rt["status"] = "error"
        rt["error"] = str(exc)
        try:
            await client.disconnect()
        except Exception:
            pass
        logger.exception("[%s] START ERROR", key)
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
    logger.info("[%s] STOPPED", key)
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

    logger.info("RUNTIME accounts: %s", ", ".join(RUNTIME.keys()))


async def start_enabled_accounts():
    for cfg in CONFIGS:
        if store.is_enabled(cfg.key):
            logger.info("[%s] auto-start because account auto-reply is enabled", cfg.key)
            await start_account(cfg.key)
        else:
            logger.info("[%s] not auto-started: account auto-reply is OFF", cfg.key)


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

    web_panel.set_runtime(
        RUNTIME, loop, start_account, stop_account, configs=CONFIGS
    )

    threading.Thread(
        target=web_panel.run_panel,
        daemon=True,
        name="web-panel",
    ).start()

    logger.info(
        "GLOBAL STATE | common_mode=%s | common_enabled=%s | gemini=%s",
        store.is_common_mode(),
        store.is_common_enabled(),
        ai_reply.is_configured(),
    )

    if store.is_common_mode() and store.is_common_enabled():
        await start_common_accounts()
    else:
        await start_enabled_accounts()

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
