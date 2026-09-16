
import asyncio
import logging
import os
import threading
from typing import Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Channel

import ai_reply
import multi_store as store
import web_panel
from accounts import AccountConfig, load_accounts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("userbot")

CONFIGS = load_accounts()
CONFIG_BY_KEY = {cfg.key: cfg for cfg in CONFIGS}

# Always create a runtime slot for every configured account.
# web_panel relies on these slots existing even while an account is stopped.
RUNTIME = {
    cfg.key: {
        "client": None,
        "status": "stopped",
        "error": "",
        "me": None,
        "handler_bound": False,
        "common_started": False,
    }
    for cfg in CONFIGS
}

LOOP: Optional[asyncio.AbstractEventLoop] = None


def _is_common_mode() -> bool:
    return store.is_common_mode()


def _account_enabled(key: str) -> bool:
    if _is_common_mode():
        return store.is_common_enabled()
    return store.is_enabled(key)


def _allowed(key: str, chat_id: int) -> bool:
    if _is_common_mode():
        return store.is_common_allowed(chat_id)
    return store.is_allowed(key, chat_id)


def _reply_enabled(key: str, chat_id: int) -> bool:
    if _is_common_mode():
        return store.is_common_reply_enabled(chat_id)
    return store.is_reply_enabled(key, chat_id)


def _persona(key: str) -> str:
    cfg = CONFIG_BY_KEY[key]
    if _is_common_mode():
        return store.get_common_persona(
            "Ты — обычный участник чата. Отвечай естественно, коротко и по смыслу."
        )
    return store.get_persona(key, cfg.persona)


def _is_automatic_channel_forward(message) -> bool:
    if not message.fwd_from:
        return False
    if not getattr(message.fwd_from, "channel_post", None):
        return False
    return isinstance(message.sender, Channel)


async def _send_ai_reply(key: str, message):
    text = (message.text or message.raw_text or "").strip()
    if not text:
        return None

    reply_text = await asyncio.to_thread(
        ai_reply.generate_reply,
        text,
        _persona(key),
    )
    if not reply_text:
        return None

    await message.reply(reply_text)
    return reply_text


def _bind_handlers(key: str, client: TelegramClient) -> None:
    rt = RUNTIME[key]
    if rt["handler_bound"]:
        return

    @client.on(events.NewMessage(incoming=True))
    async def incoming_handler(event):
        try:
            if not _allowed(key, event.chat_id):
                return
            if not _account_enabled(key):
                return

            message = event.message

            # Channel post forwarded into a discussion group.
            if _is_automatic_channel_forward(message):
                if not store.is_autocomment_enabled(key):
                    return
                if not store.bump_and_should_comment(key, event.chat_id):
                    return
                sent = await _send_ai_reply(key, message)
                if sent:
                    logger.info("[%s] autocomment sent in %s", key, event.chat_id)
                return

            # Normal participant message.
            if not _reply_enabled(key, event.chat_id):
                return
            if not (message.text or message.raw_text):
                return
            if not store.bump_and_should_reply_chat(key, event.chat_id):
                return

            sent = await _send_ai_reply(key, message)
            if sent:
                logger.info("[%s] chat reply sent in %s", key, event.chat_id)

        except Exception:
            logger.exception("[%s] incoming handler failed", key)

    rt["handler_bound"] = True


async def start_account(key: str):
    cfg = CONFIG_BY_KEY.get(key)
    if cfg is None:
        return False, f"Аккаунт {key} не найден."

    rt = RUNTIME[key]

    if rt.get("status") == "running" and rt.get("client"):
        return True, "Уже запущен."

    if not cfg.api_id or not cfg.api_hash or not cfg.session:
        msg = (
            f"{cfg.name}: не настроен Telegram-сеанс. "
            f"Нужна переменная {key.upper()}_SESSION; "
            f"API_ID/API_HASH могут быть общими."
        )
        rt.update(status="error", error=msg)
        logger.error(msg)
        return False, msg

    client = None
    try:
        client = TelegramClient(
            StringSession(cfg.session),
            int(cfg.api_id),
            cfg.api_hash,
        )
        _bind_handlers(key, client)

        rt.update(
            client=client,
            status="starting",
            error="",
            me=None,
        )

        await client.start()
        me = await client.get_me()

        rt.update(
            client=client,
            status="running",
            error="",
            me={
                "id": getattr(me, "id", None),
                "first_name": getattr(me, "first_name", None),
                "username": getattr(me, "username", None),
            },
        )

        logger.info(
            "Telegram account started: %s (%s), id=%s",
            cfg.name,
            cfg.key,
            getattr(me, "id", None),
        )
        return True, f"{cfg.name} запущен."

    except Exception as exc:
        logger.exception("Failed to start account %s", key)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass
        rt.update(
            client=None,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            me=None,
        )
        return False, rt["error"]


async def stop_account(key: str):
    rt = RUNTIME.get(key)
    if rt is None:
        return False, f"Аккаунт {key} не найден."

    client = rt.get("client")
    if client is None:
        rt.update(status="stopped", error="", me=None)
        return True, "Уже остановлен."

    try:
        await client.disconnect()
    except Exception as exc:
        logger.warning("Disconnect %s failed: %s", key, exc)

    rt.update(
        client=None,
        status="stopped",
        error="",
        me=None,
        common_started=False,
    )
    logger.info("Telegram account stopped: %s", key)
    return True, f"{CONFIG_BY_KEY[key].name} остановлен."


async def start_initial_accounts():
    # Personal mode: start accounts explicitly enabled in data/<key>.json.
    # Common mode: the common master switch starts all accounts.
    if _is_common_mode() and store.is_common_enabled():
        for cfg in CONFIGS:
            ok, msg = await start_account(cfg.key)
            RUNTIME[cfg.key]["common_started"] = bool(ok)
            if not ok:
                logger.error("Initial start %s failed: %s", cfg.key, msg)
    else:
        for cfg in CONFIGS:
            if store.is_enabled(cfg.key):
                await start_account(cfg.key)


async def shutdown_all():
    for cfg in CONFIGS:
        if RUNTIME[cfg.key].get("client"):
            await stop_account(cfg.key)


async def main():
    global LOOP
    LOOP = asyncio.get_running_loop()

    # This is the critical bridge:
    # web_panel.RUNTIME[key] must reference the SAME runtime dict used here.
    web_panel.set_runtime(
        RUNTIME,
        LOOP,
        start_account,
        stop_account,
    )

    logger.info("Loaded %d account configurations.", len(CONFIGS))
    for cfg in CONFIGS:
        logger.info(
            "CONFIG %s: api=%s hash=%s session=%s",
            cfg.key,
            bool(cfg.api_id),
            bool(cfg.api_hash),
            bool(cfg.session),
        )

    await start_initial_accounts()

    logger.info("Web panel starting...")
    panel_thread = threading.Thread(
        target=web_panel.run_panel,
        name="web-panel",
        daemon=True,
    )
    panel_thread.start()

    try:
        # Keep the single asyncio loop alive for all Telethon clients.
        await asyncio.Event().wait()
    finally:
        await shutdown_all()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
