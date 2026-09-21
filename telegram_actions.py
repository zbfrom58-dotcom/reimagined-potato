import asyncio
import re
from urllib.parse import urlparse, parse_qs
from telethon.errors import RPCError, UserAlreadyParticipantError, FloodWaitError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, SendReactionRequest, GetDiscussionMessageRequest
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.types import (
    ReactionEmoji,
    InputReportReasonSpam,
    InputReportReasonFake,
    InputReportReasonViolence,
    InputReportReasonIllegalDrugs,
    InputReportReasonOther,
)
PUBLIC_RE = re.compile(r"^/?([A-Za-z0-9_]{4,64})(?:/|$)")
MESSAGE_RE = re.compile(r"^/?([A-Za-z0-9_]{4,64})/(\d+)(?:/|$)")
PUBLIC_THREAD_MESSAGE_RE = re.compile(r"^/?([A-Za-z0-9_]{4,64})/(\d+)/(\d+)(?:/|$)")
PRIVATE_MESSAGE_RE = re.compile(r"^/?c/(\d+)/(\d+)(?:/|$)")
PRIVATE_THREAD_MESSAGE_RE = re.compile(r"^/?c/(\d+)/(\d+)/(\d+)(?:/|$)")
PRIVATE_INVITE_RE = re.compile(r"^/?(?:\+|joinchat/)([A-Za-z0-9_-]+)$")


def _clean_url(value: str) -> str:
    value = value.strip()
    if '://' not in value:
        value = 'https://' + value
    return value

def parse_join_link(link: str) -> tuple[str, str]:
    url = _clean_url(link)
    path = urlparse(url).path
    m = PRIVATE_INVITE_RE.match(path)
    if m:
        return 'private', m.group(1)
    m = PUBLIC_RE.match(path)
    if m:
        return 'public', m.group(1)
    raise ValueError('Не удалось распознать ссылку на Telegram-группу/канал.')

def parse_message_link(link: str) -> dict:
    """Parse Telegram message links, including channel comment links.

    Supported examples:
      https://t.me/channel/123
      https://t.me/channel/123?comment=456
      https://t.me/c/123456789/123
      https://t.me/c/123456789/123?comment=456
      https://t.me/channel/111/123?comment=456
      https://t.me/c/123456789/111/123?comment=456

    For a channel comment link, ``comment`` is the message ID in the linked
    discussion group. Telegram documents this meaning for t.me message links.
    """
    url = _clean_url(link)
    parsed = urlparse(url)
    path = parsed.path
    query = parse_qs(parsed.query, keep_blank_values=True)

    # Private links: t.me/c/<internal_channel_id>/<message_id>
    # and the newer thread form: t.me/c/<internal_channel_id>/<thread_id>/<message_id>.
    m = PRIVATE_THREAD_MESSAGE_RE.match(path)
    if m:
        peer = f"-100{m.group(1)}"
        msg_id = int(m.group(3))
        thread_id = int(m.group(2))
    else:
        m = PRIVATE_MESSAGE_RE.match(path)
        if not m:
            m = None
        if m:
            peer = f"-100{m.group(1)}"
            msg_id = int(m.group(2))
            thread_id = None
        else:
            peer = None
            msg_id = None
            thread_id = None

    if peer is None:
        # Public links: t.me/<username>/<message_id> and the newer
        # t.me/<username>/<thread_id>/<message_id> form.
        m = PUBLIC_THREAD_MESSAGE_RE.match(path)
        if m:
            peer = m.group(1)
            msg_id = int(m.group(3))
            thread_id = int(m.group(2))
        else:
            m = MESSAGE_RE.match(path)
            if m:
                peer = m.group(1)
                msg_id = int(m.group(2))
                thread_id = None

    if peer is None or msg_id is None:
        raise ValueError(
            'Нужна ссылка на Telegram-сообщение, например: '
            'https://t.me/user/123, '
            'https://t.me/user/123?comment=456 или '
            'https://t.me/c/1234567890/123.'
        )

    comment_values = query.get('comment')
    comment_id = None
    if comment_values and comment_values[0].strip():
        try:
            comment_id = int(comment_values[0])
        except ValueError as exc:
            raise ValueError('Параметр comment в ссылке должен быть числом.') from exc
        if comment_id <= 0:
            raise ValueError('Параметр comment в ссылке должен быть положительным числом.')

    return {
        'peer': peer,
        'msg_id': msg_id,
        'thread_id': thread_id,
        'comment_id': comment_id,
    }


async def _resolve_reaction_peer(client, peer):
    """Resolve a reaction target, including private /c/<id>/<msg> links.

    Some Telethon sessions can know a private megagroup only through the
    dialog/entity cache. Try the normal resolver first, then fall back to
    the account's dialogs.
    """
    try:
        return await client.get_input_entity(peer)
    except Exception as first_error:
        try:
            target_id = int(peer)
        except (TypeError, ValueError):
            raise first_error

        async for dialog in client.iter_dialogs():
            if int(dialog.id) == target_id:
                return await client.get_input_entity(dialog.entity)

        raise first_error


async def _react(client, entity, msg_id: int, emoji: str) -> None:
    await client(SendReactionRequest(
        peer=entity,
        msg_id=int(msg_id),
        reaction=[ReactionEmoji(emoticon=emoji)],
    ))


async def _react_to_channel_comment(client, channel_entity, post_id: int, comment_id: int, emoji: str) -> None:
    """React to a comment in the linked discussion group of a channel post."""
    discussion = await client(
        GetDiscussionMessageRequest(
            peer=channel_entity,
            msg_id=int(post_id),
        )
    )

    # messages.getDiscussionMessage returns the linked discussion chat in
    # ``chats``. Prefer a megagroup because channel comments live there.
    discussion_entity = next(
        (chat for chat in discussion.chats if getattr(chat, 'megagroup', False)),
        None,
    )
    if discussion_entity is None:
        # Fallback: use the first returned chat if Telegram did not expose
        # the megagroup flag on this result.
        discussion_entity = next(iter(discussion.chats), None)

    if discussion_entity is None:
        raise ValueError(
            'Не удалось найти связанную discussion-группу для комментариев.'
        )

    await _react(client, discussion_entity, comment_id, emoji)


async def react_to_message(client, link: str, emoji: str) -> str:
    parsed = parse_message_link(link)
    peer = parsed['peer']
    msg_id = parsed['msg_id']
    comment_id = parsed['comment_id']

    # For private /c/... links use an InputPeer resolved from the account's
    # own access/cache. This is more reliable for private megagroups.
    if str(peer).startswith("-100"):
        entity = await _resolve_reaction_peer(client, peer)
    else:
        entity = await client.get_input_entity(peer)

    if comment_id is not None:
        # Telegram's t.me link format defines ?comment=<id> as the ID of the
        # comment in the linked discussion group. Resolve that group from the
        # channel post and react to the comment there.
        await _react_to_channel_comment(client, entity, msg_id, comment_id, emoji)
        return 'реакция поставлена на комментарий'

    await _react(client, entity, msg_id, emoji)
    return 'реакция поставлена'

REPORT_REASON_TYPES = {
    "Спам": InputReportReasonSpam,
    "Мошенничество": InputReportReasonFake,
    "Насилие": InputReportReasonViolence,
    "Незаконный контент": InputReportReasonIllegalDrugs,
    "Другое": InputReportReasonOther,
}
async def join_target(client, link: str) -> str:
    kind, target = parse_join_link(link)
    if kind == 'private':
        try:
            await client(ImportChatInviteRequest(target))
            return 'вступил'
        except UserAlreadyParticipantError:
            return 'уже состоит'
    entity = await client.get_entity(target)
    try:
        await client(JoinChannelRequest(entity))
        return 'вступил'
    except UserAlreadyParticipantError:
        return 'уже состоит'

async def report_peer(client, username: str, reason: str, subreason: str) -> str:
    """Send one legitimate Telegram peer report from one connected user account."""
    entity = await client.get_input_entity(username)
    reason_cls = REPORT_REASON_TYPES.get(reason, InputReportReasonOther)
    detail = subreason.strip() if subreason else ""
    result = await client(ReportPeerRequest(
        peer=entity,
        reason=reason_cls(),
        message=detail,
    ))
    if result is False:
        raise RuntimeError("Telegram отклонил отправку жалобы.")
    return "жалоба отправлена"
async def run_single_report(username: str, reason: str, subreason: str, account_key: str, runtime: dict, start_account):
    rt = runtime.get(account_key)
    if rt is None:
        return {"account": account_key, "ok": False, "message": "Аккаунт не найден"}
    started_here = False
    try:
        client = rt.get("client")
        if client is None:
            ok, msg = await start_account(account_key)
            if not ok:
                return {"account": account_key, "ok": False, "message": msg}
            client = runtime[account_key].get("client")
            started_here = True
        message = await report_peer(client, username, reason, subreason)
        return {"account": account_key, "ok": True, "message": message}
    except FloodWaitError as e:
        return {"account": account_key, "ok": False, "message": f"FloodWait: повторить через {e.seconds} сек."}
    except (RPCError, ValueError, TypeError) as e:
        return {"account": account_key, "ok": False, "message": str(e)}
    except Exception as e:
        return {"account": account_key, "ok": False, "message": f"{type(e).__name__}: {e}"}
    finally:
        if started_here:
            try:
                await runtime[account_key]['client'].disconnect()
            except Exception:
                pass
            runtime[account_key]['client'] = None
            runtime[account_key]['status'] = 'stopped'
async def run_for_accounts(action: str, link: str, account_keys: list[str], emoji: str | None, runtime: dict, start_account):
    results = []
    for key in account_keys:
        rt = runtime.get(key)
        if rt is None:
            results.append({'account': key, 'ok': False, 'message': 'Аккаунт не найден'})
            continue
        started_here = False
        try:
            client = rt.get('client')
            if client is None:
                ok, msg = await start_account(key)
                if not ok:
                    results.append({'account': key, 'ok': False, 'message': msg})
                    continue
                client = runtime[key].get('client')
                started_here = True
            if action == 'subscribe':
                message = await join_target(client, link)
            elif action == 'reaction':
                message = await react_to_message(client, link, emoji or '👍')
            else:
                raise ValueError('Неизвестное действие')
            results.append({'account': key, 'ok': True, 'message': message})
        except FloodWaitError as e:
            results.append({'account': key, 'ok': False, 'message': f'FloodWait: повторить через {e.seconds} сек.'})
        except (RPCError, ValueError, TypeError) as e:
            results.append({'account': key, 'ok': False, 'message': str(e)})
        except Exception as e:
            results.append({'account': key, 'ok': False, 'message': f'{type(e).__name__}: {e}'})
        finally:
            # Keep already-running clients alive. Stop only clients that this one-off action started.
            if started_here:
                try:
                    await runtime[key]['client'].disconnect()
                except Exception:
                    pass
                runtime[key]['client'] = None
                runtime[key]['status'] = 'stopped'
        await asyncio.sleep(1.0)
    return results
