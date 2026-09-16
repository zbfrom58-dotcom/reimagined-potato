
import asyncio
import os
import secrets
from functools import wraps

from flask import Flask, request, redirect, url_for, session, render_template_string
from markupsafe import escape
from telethon.tl.types import Channel

import auth_store as auth
import multi_store as store
from accounts import load_accounts


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "1") == "1",
)

auth.bootstrap()

RUNTIME = {}
LOOP = None
START_ACCOUNT = None
STOP_ACCOUNT = None
CONFIGS = load_accounts()


def set_runtime(runtime, loop, start_account, stop_account, configs=None):
    global RUNTIME, LOOP, START_ACCOUNT, STOP_ACCOUNT, CONFIGS
    RUNTIME = runtime
    LOOP = loop
    START_ACCOUNT = start_account
    STOP_ACCOUNT = stop_account
    if configs is not None:
        CONFIGS = list(configs)


def run_async(coro, timeout=90):
    if LOOP is None:
        raise RuntimeError("Основной Telegram loop ещё не запущен.")
    return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth.bootstrap()
        if not auth.list_users():
            return "Панель отключена: задайте ADMIN_USERNAME и ADMIN_PASSWORD.", 503
        if not session.get("username"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def csrf():
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return f"<input type='hidden' name='_csrf' value='{escape(token)}'>"


def csrf_ok():
    a = request.form.get("_csrf", "")
    b = session.get("_csrf", "")
    return bool(a and b and secrets.compare_digest(a, b))


STYLE = """
<style>
*{box-sizing:border-box}
html{background:#0b0d12}
body{margin:0;background:#0b0d12;color:#eef0f5;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;line-height:1.4;overflow-x:hidden}
main{width:100%;max-width:1050px;margin:0 auto;padding:18px 16px 32px}
.top{position:sticky;top:0;background:rgba(11,13,18,.96);backdrop-filter:blur(10px);border-bottom:1px solid #282d3c;padding:14px max(16px,calc((100vw - 1050px)/2));z-index:20}
.top h1{margin:0 0 12px;font-size:19px;line-height:1.2}
.nav{display:flex;gap:8px;overflow-x:auto;overscroll-behavior-x:contain;scrollbar-width:none;padding-bottom:2px}
.nav::-webkit-scrollbar{display:none}
.nav a{color:#9aa3b8;text-decoration:none;background:#151822;padding:9px 13px;border-radius:20px;white-space:nowrap;flex:0 0 auto}
.nav a.active{background:#617df0;color:white}
.card{display:block;width:100%;background:#151822;border:1px solid #282d3c;border-radius:16px;padding:15px;margin:0 0 11px;overflow:hidden}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;min-width:0}
.row>div{min-width:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(310px,100%),1fr));gap:11px}
.muted{color:#8b93a7;font-size:13px;overflow-wrap:anywhere}
.green{color:#3ecf8e}.red{color:#ef5b5b}.yellow{color:#e8bd62}
.pill{background:#1b1f2b;border-radius:20px;padding:5px 10px;font-size:12px;white-space:nowrap}
.actions{display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.actions form{margin:0;max-width:100%}
a{text-decoration:none;color:inherit}
button{border:0;border-radius:9px;padding:10px 13px;background:#617df0;color:white;font-weight:600;cursor:pointer;min-height:40px;max-width:100%}
button.ghost{background:transparent;border:1px solid #394052}button.danger{background:transparent;color:#ef5b5b;border:1px solid #ef5b5b}
input,textarea{background:#1b1f2b;border:1px solid #282d3c;border-radius:9px;color:#eef0f5;padding:10px;font:inherit;width:100%;max-width:100%}
textarea{min-height:140px;resize:vertical}
h2{font-size:15px;color:#8b93a7;margin:24px 0 10px}
.err{padding:10px;border-radius:9px;background:#3a1d1f;color:#ef5b5b;margin-bottom:10px;overflow-wrap:anywhere}
form{max-width:100%}
label{display:block}
input[type="checkbox"],input[type="radio"]{width:auto;max-width:none;flex:0 0 auto}
.discover-list{display:grid;grid-template-columns:1fr;gap:8px;margin-bottom:12px}
.discover-item{display:flex;align-items:center;gap:11px;width:100%;margin:0;padding:12px 13px;border:1px solid #282d3c;border-radius:12px;background:#11141c;cursor:pointer;min-width:0}
.discover-item:hover{border-color:#617df0}
.discover-item .discover-text{min-width:0;flex:1;overflow:hidden}
.discover-item .discover-title{display:block;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.discover-item .discover-id{display:block;margin-top:2px;overflow-wrap:anywhere}
.discover-actions{position:sticky;bottom:8px;z-index:3;background:#151822;padding-top:8px}
.mobile-full{width:100%}
@media (max-width:700px){
  main{padding:14px 10px 28px}
  .top{padding:12px 10px}
  .top h1{font-size:18px}
  .card{border-radius:14px;padding:13px;margin-bottom:9px}
  .grid{grid-template-columns:1fr;gap:9px}
  .row{align-items:stretch}
  .row>.actions,.row>form,.row>a{width:100%}
  .row>.actions button,.row>form button,.row>a button{width:100%}
  .actions{width:100%}
  .actions form{flex:1 1 150px}
  .actions form button{width:100%}
  button{width:100%;min-height:42px}
  .nav a{padding:9px 12px}
  .discover-item{padding:12px 10px}
  .discover-item .discover-title{white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere}
  .discover-actions{bottom:4px}
}
</style>
"""


def page(title, body, active="accounts"):
    nav = f"""
    <div class="top">
      <h1>🤖 16 Accounts Admin</h1>
      <div class="nav">
        <a class="{'active' if active == 'accounts' else ''}" href="/">Аккаунты</a>
        <a class="{'active' if active == 'common' else ''}" href="/groups">🌐 Общий режим</a>
        <a href="/logout">Выйти</a>
      </div>
    </div>
    <main>{body}</main>
    """
    return render_template_string(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)}</title>{STYLE}</head><body>{nav}</body></html>"
    )


def cfg_for(key):
    return next((x for x in CONFIGS if x.key == key), None)


def status_label(status):
    return {
        "running": ("🟢 работает", "green"),
        "starting": ("🟡 запускается", "yellow"),
        "error": ("🔴 ошибка", "red"),
        "stopped": ("⚪ остановлен", ""),
    }.get(status, ("⚪ остановлен", ""))


@app.route("/login", methods=["GET", "POST"])
def login():
    auth.bootstrap()
    if not auth.list_users():
        return "Панель отключена: задайте ADMIN_USERNAME и ADMIN_PASSWORD.", 503

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if auth.verify(username, request.form.get("password", "")):
            session.clear()
            session["username"] = username
            session["_csrf"] = secrets.token_urlsafe(32)
            return redirect("/")
        return render_template_string(
            STYLE + "<main><div class='card'><h2>Ошибка</h2>"
            "<div class='red'>Неверный логин или пароль.</div></div></main>"
        )

    return render_template_string(
        STYLE + """
        <main style="max-width:380px">
          <div class="card"><h2>🔐 Вход</h2>
          <form method="post">
            <input name="username" placeholder="Логин" required><br><br>
            <input name="password" type="password" placeholder="Пароль" required><br><br>
            <button>Войти</button>
          </form></div>
        </main>
        """
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
@login_required
def dashboard():
    cards = ""

    for i, cfg in enumerate(CONFIGS, 1):
        rt = RUNTIME.get(cfg.key, {})
        status, cls = status_label(rt.get("status", "stopped"))
        configured = bool(cfg.api_id and cfg.api_hash and cfg.session)
        groups = len(store.list_groups(cfg.key))

        if rt.get("status") == "running":
            action = f"""
            <form method="post" action="/account/{cfg.key}/stop">
              {csrf()}<button class="danger">⏹ Остановить</button>
            </form>
            """
        else:
            action = f"""
            <form method="post" action="/account/{cfg.key}/start">
              {csrf()}<button>▶ Запустить</button>
            </form>
            """

        error = ""
        if rt.get("error"):
            error = f"<div class='err'>Ошибка: {escape(rt['error'])}</div>"

        cards += f"""
        <div class="card">
          <div class="row">
            <div>
              <b>{i}. {escape(cfg.name)}</b>
              <div class="muted">{escape(cfg.key)} · <span class="{cls}">{status}</span></div>
            </div>
            {action}
          </div>
          <div class="muted" style="margin-top:10px">
            Telegram: {'🟢 session задан' if configured else '🔴 session отсутствует'}<br>
            Пользователь: {escape(rt.get('me') or 'не авторизован')}<br>
            Личный автоответ: {'🟢 ON' if store.is_enabled(cfg.key) else '🔴 OFF'}<br>
            Личных групп: {groups}
          </div>
          <div class="actions" style="margin-top:10px">
            <a href="/account/{cfg.key}"><button class="ghost" type="button">⚙ Настройки</button></a>
            <a href="/account/{cfg.key}/groups"><button class="ghost" type="button">📋 Группы</button></a>
          </div>
          {error}
        </div>
        """

    common = store.is_common_mode() and store.is_common_enabled()
    body = f"""
    <div class="row">
      <div><h2 style="margin-top:0">16 независимых аккаунтов</h2>
      <div class="muted">У каждого свой client, свои группы и свои настройки.</div></div>
      <span class="pill">{len(CONFIGS)} аккаунтов</span>
    </div>
    <div class="card">
      <div class="row">
        <div><b>🌐 Общий режим</b><div class="muted">
        {'🟢 ВКЛЮЧЕН' if common else '⚪ ВЫКЛЮЧЕН'} ·
        все аккаунты остаются отдельными, общий режим только задаёт общие действия.</div></div>
        <a href="/groups"><button>Открыть</button></a>
      </div>
    </div>
    <div class="grid">{cards}</div>
    """
    return page("16 Accounts Admin", body)


@app.route("/common/toggle", methods=["POST"])
@login_required
def common_toggle():
    if not csrf_ok():
        return "Bad CSRF token", 403

    enabled = request.form.get("value") == "1"
    store.set_common_enabled(enabled)

    if enabled:
        async def start_all():
            for cfg in CONFIGS:
                ok, msg = await START_ACCOUNT(cfg.key)
                if ok:
                    RUNTIME[cfg.key]["common_started"] = True
                else:
                    RUNTIME[cfg.key]["error"] = msg
        try:
            run_async(start_all(), 180)
        except Exception:
            pass

    else:
        async def stop_common_started():
            for cfg in CONFIGS:
                rt = RUNTIME.get(cfg.key, {})
                if rt.get("common_started"):
                    await STOP_ACCOUNT(cfg.key)
                    rt["common_started"] = False
        try:
            run_async(stop_common_started(), 180)
        except Exception:
            pass

    return redirect("/groups")


@app.route("/groups", methods=["GET", "POST"])
@login_required
def common_groups():
    if request.method == "POST":
        if not csrf_ok():
            return "Bad CSRF token", 403

        if request.form.get("action") == "save":
            mode = request.form.get("mode", "common")
            if mode not in {"common", "personal"}:
                mode = "common"
            store.set_mode(mode)
            store.set_common_persona(request.form.get("persona", ""))
            try:
                store.set_common_reply_interval(
                    int(request.form.get("interval", "1"))
                )
            except Exception:
                pass
            store.set_common_message_once(
                request.form.get("once") == "1"
            )
            return redirect("/groups")

    groups = store.list_common_groups()
    rows = ""

    for gid, info in groups.items():
        enabled = info.get("reply_enabled", True)
        rows += f"""
        <div class="card"><div class="row">
          <div><b>{escape(store.display_label(info))}</b>
          <div class="muted">ID {gid} · {'🟢 ответы' if enabled else '🔴 без ответов'}</div></div>
          <div class="actions">
            <form method="post" action="/groups/toggle">
              {csrf()}<input type="hidden" name="chat_id" value="{gid}">
              <input type="hidden" name="value" value="{'0' if enabled else '1'}">
              <button class="ghost">{'🔕 Выключить' if enabled else '🔔 Включить'}</button>
            </form>
            <form method="post" action="/groups/remove">
              {csrf()}<input type="hidden" name="chat_id" value="{gid}">
              <button class="danger">Удалить</button>
            </form>
          </div>
        </div></div>
        """

    mode = store.get_mode()
    persona = store.get_common_persona(
        "Ты — обычный участник чата. Отвечай естественно и по смыслу."
    )

    body = f"""
    <div class="row"><div><h2 style="margin-top:0">🌐 Общий режим</h2>
    <div class="muted">Общие группы и persona применяются к каждому из 16 аккаунтов,
    но аккаунты не объединяются в один client.</div></div>
    <span class="pill">{'🟢 ВКЛЮЧЕН' if store.is_common_enabled() and mode == 'common' else '⚪ ВЫКЛЮЧЕН'}</span></div>

    <div class="card"><div class="row">
      <div><b>Главный выключатель</b><div class="muted">
      Включает общий режим и запускает все настроенные аккаунты.</div></div>
      <form method="post" action="/common/toggle">
        {csrf()}<input type="hidden" name="value" value="{'0' if store.is_common_enabled() else '1'}">
        <button class="{'danger' if store.is_common_enabled() else ''}">
        {'⏹ Выключить' if store.is_common_enabled() else '▶ Включить'}</button>
      </form>
    </div></div>

    <div class="card"><form method="post">
      {csrf()}<input type="hidden" name="action" value="save">
      <h2 style="margin-top:0">Режим</h2>
      <label><input type="radio" name="mode" value="common" {'checked' if mode == 'common' else ''} style="width:auto">
      🌐 Общий</label><br><br>
      <label><input type="radio" name="mode" value="personal" {'checked' if mode == 'personal' else ''} style="width:auto">
      👤 Личный</label>
      <h2>Общая persona</h2>
      <textarea name="persona">{escape(persona)}</textarea>
      <h2>Интервал</h2>
      <input name="interval" type="number" min="1" value="{store.get_common_reply_interval()}">
      <br><br>
      <label><input name="once" type="checkbox" value="1" {'checked' if store.common_message_once() else ''} style="width:auto">
      Обрабатывать каждое подходящее сообщение</label>
      <br><br><button>💾 Сохранить</button>
    </form></div>

    <h2>Общие группы</h2>
    {rows or '<div class="card"><div class="muted">Общих групп пока нет.</div></div>'}

    <div class="card"><h2 style="margin-top:0">Добавить общую группу</h2>
      <form method="post" action="/groups/add">
        {csrf()}<input name="chat_id" placeholder="ID группы" required><br><br>
        <input name="username" placeholder="username"><br><br>
        <input name="title" placeholder="Название"><br><br>
        <button>➕ Добавить</button>
      </form>
    </div>
    """
    return page("Общий режим", body, "common")


@app.route("/groups/add", methods=["POST"])
@login_required
def common_add():
    if not csrf_ok():
        return "Bad CSRF token", 403
    try:
        gid = int(request.form["chat_id"])
    except Exception:
        return "Некорректный chat_id", 400
    store.add_common_group(gid, request.form.get("username") or None, request.form.get("title") or None)
    return redirect("/groups")


@app.route("/groups/toggle", methods=["POST"])
@login_required
def common_toggle_group():
    if not csrf_ok():
        return "Bad CSRF token", 403
    store.set_common_reply_enabled(
        int(request.form["chat_id"]),
        request.form.get("value") == "1",
    )
    return redirect("/groups")


@app.route("/groups/remove", methods=["POST"])
@login_required
def common_remove():
    if not csrf_ok():
        return "Bad CSRF token", 403
    store.remove_common_group(int(request.form["chat_id"]))
    return redirect("/groups")


@app.route("/account/<key>", methods=["GET", "POST"])
@login_required
def account_page(key):
    cfg = cfg_for(key)
    if not cfg:
        return "Not found", 404

    if request.method == "POST":
        if not csrf_ok():
            return "Bad CSRF token", 403
        persona = request.form.get("persona", "").strip()
        if persona:
            store.set_persona(key, persona)
        try:
            store.set_chat_interval(key, int(request.form.get("chat_interval", "5")))
        except Exception:
            pass
        try:
            store.set_autocomment_interval(key, int(request.form.get("comment_interval", "1")))
        except Exception:
            pass
        store.set_autocomment_enabled(
            key, request.form.get("autocomment") == "1"
        )
        # Personal auto-reply is a separate switch from Runtime.
        store.set_enabled(key, request.form.get("auto_reply") == "1")
        return redirect(f"/account/{key}")

    rt = RUNTIME.get(key, {})
    status, cls = status_label(rt.get("status", "stopped"))
    running_action = "stop" if rt.get("status") == "running" else "start"
    button = "⏹ Остановить" if running_action == "stop" else "▶ Запустить"

    body = f"""
    <div class="row"><div><h2 style="margin-top:0">{escape(cfg.name)}</h2>
    <div class="muted">{escape(cfg.key)}</div></div>
    <a href="/"><button class="ghost">← Аккаунты</button></a></div>

    <div class="card"><div class="row"><div>
      <b>Runtime: <span class="{cls}">{status}</span></b>
      <div class="muted">Telegram: {escape(rt.get('me') or 'не авторизован')}</div>
    </div>
    <form method="post" action="/account/{key}/{running_action}">
      {csrf()}<button>{button}</button>
    </form></div>
    {("<div class='err'>"+str(escape(rt.get('error')))+"</div>") if rt.get('error') else ""}
    </div>

    <div class="card"><form method="post">{csrf()}
      <h2 style="margin-top:0">Persona</h2>
      <textarea name="persona">{escape(store.get_persona(key, cfg.persona))}</textarea>
      <h2>Интервалы</h2>
      <label>Ответы: <input name="chat_interval" type="number" min="1" value="{store.get_chat_interval(key)}"></label>
      <br><br>
      <label>Комментарии: <input name="comment_interval" type="number" min="1" value="{store.get_autocomment_interval(key)}"></label>
      <br><br>
      <label><input name="auto_reply" type="checkbox" value="1"
      {'checked' if store.is_enabled(key) else ''} style="width:auto">
      Личный автоответ</label>
      <br><br>
      <label><input name="autocomment" type="checkbox" value="1"
      {'checked' if store.is_autocomment_enabled(key) else ''} style="width:auto">
      Автокомментинг</label>
      <br><br><button>💾 Сохранить</button>
    </form></div>
    """
    return page(cfg.name, body)


@app.route("/account/<key>/<action>", methods=["POST"])
@login_required
def account_action(key, action):
    if not csrf_ok():
        return "Bad CSRF token", 403
    if not cfg_for(key):
        return "Not found", 404
    if action == "start":
        run_async(START_ACCOUNT(key))
    elif action == "stop":
        run_async(STOP_ACCOUNT(key))
    else:
        return "Bad action", 400
    return redirect(f"/account/{key}")


async def discover_account_groups(key):
    rt = RUNTIME.get(key)
    if not rt or not rt.get("client"):
        raise RuntimeError("Сначала запусти этот аккаунт.")

    client = rt["client"]
    found = []

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if not (getattr(entity, "megagroup", False) or isinstance(entity, Channel)):
            continue
        found.append({
            "id": int(dialog.id),
            "title": dialog.title or "Без названия",
            "username": getattr(entity, "username", None),
        })
    return found


@app.route("/account/<key>/groups", methods=["GET", "POST"])
@login_required
def account_groups(key):
    cfg = cfg_for(key)
    if not cfg:
        return "Not found", 404

    found = []
    error = ""

    if request.method == "POST":
        if not csrf_ok():
            return "Bad CSRF token", 403
        try:
            found = run_async(discover_account_groups(key))
        except Exception as exc:
            error = str(exc)

    rows = ""
    for gid, info in store.list_groups(key).items():
        on = info.get("reply_enabled", True)
        rows += f"""
        <div class="card"><div class="row">
          <div><b>{escape(store.display_label(info))}</b>
          <div class="muted">ID {gid} · {'🟢 ответы' if on else '🔴 без ответов'}</div></div>
          <div class="actions">
            <form method="post" action="/account/{key}/groups/toggle">
              {csrf()}<input type="hidden" name="chat_id" value="{gid}">
              <input type="hidden" name="value" value="{'0' if on else '1'}">
              <button class="ghost">{'🔕 Выключить' if on else '🔔 Включить'}</button>
            </form>
            <form method="post" action="/account/{key}/groups/remove">
              {csrf()}<input type="hidden" name="chat_id" value="{gid}">
              <button class="danger">Удалить</button>
            </form>
          </div>
        </div></div>
        """

    discovered = ""
    if error:
        discovered = f"<div class='err'>Ошибка: {escape(error)}</div>"
    elif found:
        items = "".join(
            f"<label class='discover-item'>"
            f"<input type='checkbox' name='ids' value='{x['id']}'>"
            f"<span class='discover-text'>"
            f"<span class='discover-title'>{escape('@'+x['username'] if x.get('username') else x['title'])}</span>"
            f"<span class='muted discover-id'>ID {x['id']}</span>"
            f"</span></label>"
            for x in found
        )
        discovered = f"""
        <div class="card"><h2 style="margin-top:0">Найденные чаты</h2>
        <form method="post" action="/account/{key}/groups/add-found">
        {csrf()}<div class="discover-list">{items}</div>
        <div class="discover-actions"><button class="mobile-full">➕ Добавить выбранные</button></div>
        </form></div>
        """

    body = f"""
    <div class="row"><div><h2 style="margin-top:0">{escape(cfg.name)} — группы</h2>
    <div class="muted">Этот список принадлежит только этому аккаунту.</div></div>
    <a href="/account/{key}"><button class="ghost">← Настройки</button></a></div>

    <div class="card"><form method="post">
      {csrf()}<button>🔎 Автообнаружение групп</button>
    </form></div>
    {discovered}
    {rows or '<div class="card"><div class="muted">Личных групп пока нет.</div></div>'}

    <div class="card"><h2 style="margin-top:0">Добавить вручную</h2>
      <form method="post" action="/account/{key}/groups/add">
        {csrf()}<input name="chat_id" placeholder="ID группы" required><br><br>
        <input name="username" placeholder="username"><br><br>
        <input name="title" placeholder="Название"><br><br>
        <button>➕ Добавить</button>
      </form>
    </div>
    """
    return page(f"{cfg.name} — группы", body)


@app.route("/account/<key>/groups/add-found", methods=["POST"])
@login_required
def add_found(key):
    if not csrf_ok() or not cfg_for(key):
        return "Bad request", 400

    rt = RUNTIME.get(key)
    if not rt or not rt.get("client"):
        return redirect(f"/account/{key}/groups")

    ids = request.form.getlist("ids")
    client = rt["client"]

    async def add():
        for raw in ids:
            try:
                entity = await client.get_entity(int(raw))
                store.add_group(
                    key,
                    int(raw),
                    getattr(entity, "username", None),
                    getattr(entity, "title", None),
                )
            except Exception:
                continue

    run_async(add())
    return redirect(f"/account/{key}/groups")


@app.route("/account/<key>/groups/toggle", methods=["POST"])
@login_required
def personal_toggle(key):
    if not csrf_ok() or not cfg_for(key):
        return "Bad request", 400
    store.set_reply_enabled(
        key,
        int(request.form["chat_id"]),
        request.form.get("value") == "1",
    )
    return redirect(f"/account/{key}/groups")


@app.route("/account/<key>/groups/add", methods=["POST"])
@login_required
def personal_add(key):
    if not csrf_ok() or not cfg_for(key):
        return "Bad request", 400
    store.add_group(
        key,
        int(request.form["chat_id"]),
        request.form.get("username") or None,
        request.form.get("title") or None,
    )
    return redirect(f"/account/{key}/groups")


@app.route("/account/<key>/groups/remove", methods=["POST"])
@login_required
def personal_remove(key):
    if not csrf_ok() or not cfg_for(key):
        return "Bad request", 400
    store.remove_group(key, int(request.form["chat_id"]))
    return redirect(f"/account/{key}/groups")


def run_panel():
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        threaded=True,
    )
