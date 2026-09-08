"""
Веб-панель администратора для юзербота.
Запускается автоматически вместе с userbot.py (в отдельном потоке),
слушает порт, который выдаёт Railway (переменная окружения PORT).

Вход: логин + пароль (можно несколько пользователей — см. auth_store.py).
Главный админ задаётся переменными окружения ADMIN_USERNAME / ADMIN_PASSWORD.

Комментарии под постами и ответы на сообщения людей генерируются через
Google Gemini (см. ai_reply.py) на основе текста, который вы задаёте на
вкладке "ИИ-персона" — это системный промпт, описывающий характер и стиль.
"""

import asyncio
import os
from functools import wraps

from flask import Flask, request, redirect, url_for, session, render_template_string
from telethon.tl.types import Channel
from telethon import utils

import ai_reply
import groups_store as groups
import settings_store as settings
import auth_store as auth

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
SECRET_KEY = os.getenv("FLASK_SECRET_KEY", os.urandom(24).hex())

app = Flask(__name__)
app.secret_key = SECRET_KEY

_client = None
_loop = None


def set_client(client, loop):
    global _client, _loop
    _client = client
    _loop = loop


def run_async(coro, timeout=20):
    if _loop is None:
        raise RuntimeError("Юзербот ещё не запущен.")
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=timeout)


def normalize_username(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("@"):
        raw = raw[1:]
    return raw


def panel_configured() -> bool:
    return bool(ADMIN_USERNAME and ADMIN_PASSWORD) or bool(auth.list_users())


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not panel_configured():
            return (
                "Панель отключена: не заданы переменные окружения "
                "ADMIN_USERNAME / ADMIN_PASSWORD.",
                503,
            )
        if not session.get("username"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def _flash_redirect(endpoint, message, is_error=False):
    session["_flash"] = message
    session["_flash_err"] = is_error
    return redirect(url_for(endpoint))


def _pop_flash():
    return session.pop("_flash", None), session.pop("_flash_err", False)


# =========================================================
#                     ОБЩИЙ ДИЗАЙН
# =========================================================

BASE_STYLE = """
<style>
:root{
  --bg:#0b0d12; --card:#151822; --card2:#1b1f2b; --border:#262b3a;
  --text:#eef0f5; --muted:#8b93a7; --accent:#6c8cff; --accent2:#4f6fe0;
  --green:#3ecf8e; --red:#ef5b5b; --yellow:#e0b04f;
}
*{box-sizing:border-box}
body{font-family:-apple-system,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);margin:0;padding-bottom:60px}
a{color:var(--accent);text-decoration:none}
.topbar{position:sticky;top:0;background:rgba(11,13,18,0.95);backdrop-filter:blur(6px);padding:14px 16px 0;z-index:10;border-bottom:1px solid var(--border)}
.topbar h1{font-size:18px;margin:0 0 12px;display:flex;justify-content:space-between;align-items:center}
.topbar h1 span.logout{font-size:12px;color:var(--muted);font-weight:400}
.nav{display:flex;gap:4px;overflow-x:auto;padding-bottom:10px;-webkit-overflow-scrolling:touch}
.nav a{white-space:nowrap;padding:8px 14px;border-radius:20px;font-size:13px;color:var(--muted);background:var(--card)}
.nav a.active{color:#fff;background:var(--accent2);font-weight:600}
.content{padding:16px}
h2.section{font-size:15px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin:22px 0 10px;font-weight:600}
h2.section:first-child{margin-top:0}
.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:14px 16px;margin-bottom:10px}
.card.dim{opacity:.7}
input[type=text],input[type=password],input[type=number],select,textarea{
  padding:9px 10px;border-radius:8px;border:1px solid var(--border);
  background:var(--card2);color:var(--text);box-sizing:border-box;font-size:14px;font-family:inherit}
input[type=text]:focus,input[type=number]:focus,textarea:focus{outline:none;border-color:var(--accent)}
button{padding:9px 16px;border-radius:8px;border:none;background:var(--accent2);
  color:#fff;font-weight:600;cursor:pointer;font-size:13px}
button.danger{background:transparent;color:var(--red);border:1px solid var(--red)}
button.ghost{background:transparent;color:var(--accent);border:1px solid var(--border)}
button.small{padding:6px 10px;font-size:12px}
.row{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.stack{display:flex;flex-direction:column;gap:8px}
.pill{background:var(--card2);padding:3px 10px;border-radius:20px;font-size:12px;color:var(--muted)}
.pill.on{color:var(--green)}
.pill.off{color:var(--red)}
.muted{color:var(--muted);font-size:13px}
form.inline{display:inline-flex;align-items:center;gap:6px}
.msg{padding:10px 14px;border-radius:10px;margin-bottom:14px;font-size:14px;background:#173328;color:var(--green);border:1px solid #235b41}
.msg.err{background:#3a1d1f;color:var(--red);border-color:#6b2a2a}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
label.toggle{display:flex;align-items:center;gap:8px;cursor:pointer;font-size:14px}
.empty{color:var(--muted);font-size:13px;padding:6px 0}
</style>
"""


def render_page(active, content_html, message=None, is_error=False):
    tabs = [
        ("dashboard", "⚙️ Обзор"),
        ("groups_page", "📋 Группы"),
        ("persona_page", "🤖 ИИ-персона"),
        ("users_page", "🔑 Доступ"),
    ]
    nav_html = "".join(
        f'<a href="{url_for(ep)}" class="{"active" if ep == active else ""}">{label}</a>'
        for ep, label in tabs
    )
    msg_html = ""
    if message:
        msg_html = f'<div class="msg {"err" if is_error else ""}">{message}</div>'

    page = """
<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Панель юзербота</title>
""" + BASE_STYLE + """
</head><body>
<div class="topbar">
  <h1>🤖 Панель юзербота <span class="logout"><a href="/logout">Выйти ({{ user }})</a></span></h1>
  <div class="nav">""" + nav_html + """</div>
</div>
<div class="content">
""" + msg_html + content_html + """
</div>
</body></html>
"""
    return render_template_string(page, user=session.get("username", ""))


# =========================================================
#                        ВХОД
# =========================================================

LOGIN_PAGE = """
<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Вход — панель юзербота</title>
""" + BASE_STYLE + """
</head><body style="display:flex;height:100vh;align-items:center;justify-content:center">
<div class="card" style="width:300px">
<h2 style="margin-top:0">🔐 Вход в панель</h2>
{% if error %}<div class="msg err">{{ error }}</div>{% endif %}
<form method="post" class="stack">
<input type="text" name="username" placeholder="Логин" autofocus>
<input type="password" name="password" placeholder="Пароль">
<button type="submit">Войти</button>
</form>
</div></body></html>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    if not panel_configured():
        return (
            "Панель отключена: не заданы переменные окружения "
            "ADMIN_USERNAME / ADMIN_PASSWORD.",
            503,
        )
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if auth.verify(username, password):
            session["username"] = username
            return redirect(url_for("dashboard"))
        error = "Неверный логин или пароль."
    return render_template_string(LOGIN_PAGE, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================================================
#                  ВКЛАДКА: ОБЗОР
# =========================================================

@app.route("/", methods=["GET"])
@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    message, is_error = _pop_flash()

    enabled = settings.is_enabled()
    ai_ok = ai_reply.is_configured()
    comment_enabled = settings.is_autocomment_enabled()

    ai_pill = (
        '<span class="pill on">✅ Gemini подключён</span>' if ai_ok
        else '<span class="pill off">⛔ Нет GEMINI_API_KEY</span>'
    )

    content = f"""
<h2 class="section">Статус</h2>
<div class="card">
  <div class="row" style="margin-bottom:10px">
    <span class="pill {'on' if enabled else 'off'}">{'● Бот включён' if enabled else '● Бот выключен'}</span>
    <form method="post" action="{url_for('settings_toggle')}">
      <button type="submit" class="{'danger' if enabled else ''}">{'Выключить' if enabled else 'Включить'}</button>
    </form>
  </div>
  <div class="row">
    {ai_pill}
  </div>
  {'<p class="muted" style="margin-bottom:0">Добавьте переменную окружения GEMINI_API_KEY на Railway, иначе бот не сможет ничего генерировать.</p>' if not ai_ok else ''}
</div>

<h2 class="section">Автокомментинг постов канала</h2>
<div class="card">
  <div class="row" style="margin-bottom:10px">
    <span class="pill {'on' if comment_enabled else 'off'}">{'● Включён' if comment_enabled else '● Выключен'}</span>
    <form method="post" action="{url_for('autocomment_toggle')}">
      <button type="submit" class="{'danger' if comment_enabled else ''}">{'Выключить' if comment_enabled else 'Включить'}</button>
    </form>
  </div>
  <div class="row">
    <span class="muted">Комментировать раз в N постов (1 = каждый пост)</span>
    <form method="post" action="{url_for('autocomment_interval')}" class="inline">
      <input type="number" name="value" value="{settings.get_autocomment_interval()}" min="1" style="width:70px">
      <button type="submit" class="small">Сохранить</button>
    </form>
  </div>
  <p class="muted" style="margin-bottom:0;margin-top:10px">
    Работает в подключённых группах (вкладка «Группы») — группа должна быть привязана
    к каналу как "группа обсуждений", тогда посты пересылаются туда автоматически, и
    бот старается прокомментировать их первым.
  </p>
</div>

<h2 class="section">Ответы на сообщения людей в группах</h2>
<div class="card">
  <div class="row">
    <span class="muted">Отвечать раз в N сообщений людей</span>
    <form method="post" action="{url_for('settings_chatinterval')}" class="inline">
      <input type="number" name="value" value="{settings.get_chat_interval()}" min="1" style="width:70px">
      <button type="submit" class="small">Сохранить</button>
    </form>
  </div>
  <p class="muted" style="margin-bottom:0;margin-top:10px">Включается/выключается отдельно по каждой группе на вкладке «Группы».</p>
</div>

<h2 class="section">Краткая сводка</h2>
<div class="card grid2">
  <div><span class="muted">Групп подключено</span><br><b>{len(groups.list_groups())}</b></div>
</div>
"""
    return render_page("dashboard", content, message, is_error)


@app.route("/settings/toggle", methods=["POST"])
@login_required
def settings_toggle():
    settings.set_enabled(not settings.is_enabled())
    return redirect(url_for("dashboard"))


@app.route("/settings/chatinterval", methods=["POST"])
@login_required
def settings_chatinterval():
    try:
        settings.set_chat_interval(int(request.form.get("value", 5)))
    except ValueError:
        pass
    return redirect(url_for("dashboard"))


@app.route("/autocomment/toggle", methods=["POST"])
@login_required
def autocomment_toggle():
    settings.set_autocomment_enabled(not settings.is_autocomment_enabled())
    return redirect(url_for("dashboard"))


@app.route("/autocomment/interval", methods=["POST"])
@login_required
def autocomment_interval():
    try:
        settings.set_autocomment_interval(int(request.form.get("value", 1)))
    except ValueError:
        pass
    return redirect(url_for("dashboard"))


# =========================================================
#                  ВКЛАДКА: ГРУППЫ
# =========================================================

async def _add_group_coro(raw):
    raw = raw.strip()
    if raw.lstrip('-').isdigit():
        entity = await _client.get_entity(int(raw))
    else:
        entity = await _client.get_entity(normalize_username(raw))
    if not isinstance(entity, Channel) or not entity.megagroup:
        raise ValueError("Это не группа обсуждений (супергруппа).")
    groups.add_group(utils.get_peer_id(entity), username=entity.username, title=entity.title)
    return entity.username or entity.title or str(utils.get_peer_id(entity))


async def _discover_groups_coro():
    """Возвращает список групп (супергрупп), в которых состоит аккаунт."""
    results = []
    async for dialog in _client.iter_dialogs(limit=300):
        entity = dialog.entity
        if isinstance(entity, Channel) and entity.megagroup:
            results.append({
                "id": utils.get_peer_id(entity),
                "username": entity.username,
                "title": dialog.name,
            })
    return results


@app.route("/groups", methods=["GET"])
@login_required
def groups_page():
    message, is_error = _pop_flash()
    data = groups.list_groups()

    cards = ""
    for gid, g in data.items():
        label = groups.display_label(g)
        is_private = not g.get("username")
        kind_pill = '<span class="pill">🔒 приватная</span>' if is_private else '<span class="pill">🌐 публичная</span>'
        reply_on = g.get("reply_enabled", True)
        cards += f"""
<div class="card">
  <div class="row">
    <span><b>{label}</b> {kind_pill}</span>
    <div class="row" style="gap:6px">
      <form method="post" action="{url_for('groups_toggle_reply')}">
        <input type="hidden" name="chat_id" value="{gid}">
        <input type="hidden" name="enabled" value="{'false' if reply_on else 'true'}">
        <button type="submit" class="small {'ghost' if reply_on else ''}">{'✅ Ответы на сообщения вкл' if reply_on else '⛔ Ответы на сообщения выкл'}</button>
      </form>
      <form method="post" action="{url_for('groups_remove')}" onsubmit="return confirm('Отключить {label}?')">
        <input type="hidden" name="chat_id" value="{gid}">
        <button class="danger small" type="submit">Отключить</button>
      </form>
    </div>
  </div>
</div>
"""
    if not data:
        cards = '<div class="empty">Групп пока не подключено.</div>'

    discover_html = ""
    if request.args.get("discover") == "1":
        try:
            found = run_async(_discover_groups_coro())
        except Exception as e:
            found = []
            discover_html += f'<div class="msg err">Не удалось получить список: {e}</div>'

        connected_ids = set(data.keys())
        rows = ""
        for g in found:
            already = str(g["id"]) in connected_ids
            if g["username"]:
                label2 = f"@{g['username']}"
                kind2 = '<span class="pill">🌐 публичная</span>'
            else:
                label2 = f"{g['title'] or 'Без названия'}"
                kind2 = '<span class="pill">🔒 приватная</span>'
            btn = (
                '<span class="pill on">Уже подключена</span>' if already else f"""
                <form method="post" action="{url_for('groups_quickadd')}">
                  <input type="hidden" name="chat_id" value="{g['id']}">
                  <input type="hidden" name="username" value="{g['username'] or ''}">
                  <input type="hidden" name="title" value="{g['title'] or ''}">
                  <button type="submit" class="small">Подключить</button>
                </form>
                """
            )
            rows += f"""
<div class="card">
  <div class="row">
    <span>{label2} {kind2}</span>
    {btn}
  </div>
</div>
"""
        if not rows:
            rows = '<div class="empty">Групп (супергрупп с обсуждениями) не найдено среди ваших чатов.</div>'

        discover_html += f"""
<h2 class="section">Найдено в Telegram ({len(found)})</h2>
{rows}
"""
    else:
        discover_html = f"""
<div class="card">
  <button type="button" onclick="window.location='{url_for('groups_page')}?discover=1'">🔍 Показать мои группы из Telegram</button>
</div>
"""

    content = f"""
<h2 class="section">Подключённые группы ({len(data)})</h2>
<p class="muted">Бот комментирует посты канала, пересылаемые в эти группы, и (если включено по группе) отвечает на сообщения людей. Общие переключатели автокомментинга и интервал ответов — на вкладке «Обзор».</p>
{cards}

<h2 class="section">Автообнаружение</h2>
{discover_html}

<h2 class="section">Подключить вручную</h2>
<div class="card">
  <form method="post" action="{url_for('groups_add')}" class="stack">
    <input type="text" name="username" placeholder="@username_группы или ID (для приватной)" required>
    <button type="submit">➕ Подключить группу</button>
  </form>
  <p class="muted" style="margin-bottom:0">Публичную группу — по @юзернейму. Приватную группу без юзернейма — по числовому ID (найдите его через автообнаружение выше). Бот должен уже состоять в группе.</p>
</div>
"""
    return render_page("groups_page", content, message, is_error)


@app.route("/groups/quickadd", methods=["POST"])
@login_required
def groups_quickadd():
    chat_id = request.form.get("chat_id")
    username = request.form.get("username", "").strip() or None
    title = request.form.get("title", "").strip() or None
    label = f"@{username}" if username else (title or str(chat_id))
    try:
        groups.add_group(int(chat_id), username=username, title=title)
        return _flash_redirect("groups_page", f"Группа «{label}» подключена.")
    except Exception as e:
        return _flash_redirect("groups_page", f"Не удалось подключить: {e}", True)


@app.route("/groups/add", methods=["POST"])
@login_required
def groups_add():
    raw = request.form.get("username", "").strip()
    if not raw:
        return _flash_redirect("groups_page", "Укажите юзернейм или ID группы.", True)
    try:
        label = run_async(_add_group_coro(raw))
        return _flash_redirect("groups_page", f"Группа «{label}» подключена.")
    except Exception as e:
        return _flash_redirect("groups_page", f"Не удалось подключить «{raw}»: {e}", True)


@app.route("/groups/remove", methods=["POST"])
@login_required
def groups_remove():
    chat_id = request.form.get("chat_id")
    groups.remove_group_by_chat_id(chat_id)
    return redirect(url_for("groups_page"))


@app.route("/groups/togglereply", methods=["POST"])
@login_required
def groups_toggle_reply():
    chat_id = request.form.get("chat_id")
    enabled = request.form.get("enabled") == "true"
    groups.set_reply_enabled(int(chat_id), enabled)
    return redirect(url_for("groups_page"))


# =========================================================
#               ВКЛАДКА: ИИ-ПЕРСОНА
# =========================================================

@app.route("/persona", methods=["GET"])
@login_required
def persona_page():
    message, is_error = _pop_flash()
    current = settings.get_persona()
    ai_ok = ai_reply.is_configured()

    ai_pill = (
        '<span class="pill on">✅ GEMINI_API_KEY найден</span>' if ai_ok
        else '<span class="pill off">⛔ GEMINI_API_KEY не задан на Railway</span>'
    )

    content = f"""
<h2 class="section">Статус Gemini</h2>
<div class="card">{ai_pill}</div>

<h2 class="section">Характер комментариев/ответов (системный промпт)</h2>
<p class="muted">Этот текст отправляется модели перед каждым постом или сообщением — он определяет стиль, тон и длину комментария. Пишите как инструкцию для актёра, играющего роль.</p>
<div class="card">
  <form method="post" action="{url_for('persona_save')}" class="stack">
    <textarea name="persona" rows="8" style="width:100%">{current}</textarea>
    <button type="submit">💾 Сохранить</button>
  </form>
</div>

<div class="card">
  <form method="post" action="{url_for('persona_reset')}" onsubmit="return confirm('Сбросить персону на стандартную?')">
    <button type="submit" class="ghost small">↺ Сбросить на стандартную</button>
  </form>
</div>
"""
    return render_page("persona_page", content, message, is_error)


@app.route("/persona/save", methods=["POST"])
@login_required
def persona_save():
    text = request.form.get("persona", "").strip()
    if not text:
        return _flash_redirect("persona_page", "Текст персоны не может быть пустым.", True)
    settings.set_persona(text)
    return _flash_redirect("persona_page", "Персона сохранена.")


@app.route("/persona/reset", methods=["POST"])
@login_required
def persona_reset():
    settings.set_persona(settings.DEFAULT_PERSONA)
    return _flash_redirect("persona_page", "Персона сброшена на стандартную.")


# =========================================================
#              ВКЛАДКА: ДОСТУП (логины/пароли)
# =========================================================

@app.route("/users", methods=["GET"])
@login_required
def users_page():
    message, is_error = _pop_flash()
    extra_users = auth.list_users()

    cards = ""
    for u in extra_users:
        cards += f"""
<div class="card">
  <div class="row">
    <span>{u}</span>
    <form method="post" action="{url_for('users_remove')}" onsubmit="return confirm('Удалить доступ у {u}?')">
      <input type="hidden" name="username" value="{u}">
      <button class="danger small" type="submit">Удалить</button>
    </form>
  </div>
</div>
"""
    if not extra_users:
        cards = '<div class="empty">Дополнительных пользователей пока нет.</div>'

    content = f"""
<h2 class="section">Кто имеет доступ</h2>
<p class="muted">Главный администратор задан в переменных окружения Railway и здесь не отображается — его нельзя удалить из панели.</p>
{cards}

<h2 class="section">Выдать новый доступ</h2>
<div class="card">
  <form method="post" action="{url_for('users_add')}" class="stack">
    <input type="text" name="username" placeholder="Логин" required>
    <input type="text" name="password" placeholder="Пароль" required>
    <button type="submit">➕ Выдать доступ</button>
  </form>
</div>
"""
    return render_page("users_page", content, message, is_error)


@app.route("/users/add", methods=["POST"])
@login_required
def users_add():
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    ok, error = auth.add_user(username, password)
    if ok:
        return _flash_redirect("users_page", f"Логин «{username}» создан.")
    return _flash_redirect("users_page", error, True)


@app.route("/users/remove", methods=["POST"])
@login_required
def users_remove():
    username = request.form.get("username", "")
    auth.remove_user(username)
    return redirect(url_for("users_page"))


@app.errorhandler(500)
def handle_500(e):
    app.logger.exception("Необработанная ошибка на странице панели")
    return (
        "<h2>⚠️ Что-то пошло не так</h2>"
        "<p>Произошла внутренняя ошибка. Подробности записаны в логи Railway "
        "(Deployments → последний деплой → прокрутить вниз).</p>"
        f'<p><a href="{url_for("dashboard")}">← Вернуться на главную</a></p>',
        500,
    )


def run_panel():
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
