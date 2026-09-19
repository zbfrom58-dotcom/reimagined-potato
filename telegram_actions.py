import asyncio
import re
from urllib.parse import urlparse

from telethon.errors import RPCError, UserAlreadyParticipantError, FloodWaitError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, SendReactionRequest
from telethon.tl.types import ReactionEmoji

PUBLIC_RE = re.compile(r"^/?([A-Za-z0-9_]{4,64})(?:/|$)")
MESSAGE_RE = re.compile(r"^/?([A-Za-z0-9_]{4,64})/(\d+)(?:/|$)")
PRIVATE_MESSAGE_RE = re.compile(r"^/?c/(\d+)/(\d+)(?:/|$)")
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


def parse_message_link(link: str) -> tuple[str, int | str]:
    url = _clean_url(link)
    path = urlparse(url).path
    m = PRIVATE_MESSAGE_RE.match(path)
    if m:
        # Telegram t.me/c/<internal_id>/<message_id> corresponds to peer -100<internal_id>.
        return f"-100{m.group(1)}", int(m.group(2))
    m = MESSAGE_RE.match(path)
    if m:
        return m.group(1), int(m.group(2))
    raise ValueError('Нужна ссылка вида https://t.me/user/123 или https://t.me/c/1234567890/123.')


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


async def react_to_message(client, link: str, emoji: str) -> str:
    peer, msg_id = parse_message_link(link)
    entity = await client.get_entity(peer)
    await client(SendReactionRequest(
        peer=entity,
        msg_id=int(msg_id),
        reaction=[ReactionEmoji(emoticon=emoji)],
    ))
    return 'реакция поставлена'


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
