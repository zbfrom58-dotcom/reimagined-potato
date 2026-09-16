import asyncio
import os
from functools import wraps
from flask import Flask, request, redirect, url_for, session, render_template_string

import ai_reply
import auth_store as auth
import multi_store as store
from accounts import load_accounts

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24).hex())

RUNTIME = {}
LOOP = None
START_ACCOUNT = None
STOP_ACCOUNT = None
CONFIGS = load_accounts()

def set_runtime(runtime, loop, start_account, stop_account):
    global RUNTIME, LOOP, START_ACCOUNT, STOP_ACCOUNT
    RUNTIME, LOOP, START_ACCOUNT, STOP_ACCOUNT = runtime, loop, start_account, stop_account

def run_async(coro, timeout=30):
    if LOOP is None:
        raise RuntimeError("Основной цикл ещё не запущен.")
    return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout=timeout)

def panel_configured():
    return bool(os.getenv("ADMIN_USERNAME") and os.getenv("ADMIN_PASSWORD")) or bool(auth.list_users())

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not panel_configured():
            return "Панель отключена: задайте ADMIN_USERNAME и ADMIN_PASSWORD.", 503
        if not session.get("username"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

STYLE = """
<style>
:root{--bg:#0b0d12;--card:#151822;--card2:#1b1f2b;--border:#282d3c;--text:#eef0f5;--muted:#8b93a7;--accent:#617df0;--green:#3ecf8e;--red:#ef5b5b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.top{position:sticky;top:0;background:#0b0d12f2;border-bottom:1px solid var(--border);padding:15px 18px;z-index:5}
.top h1{font-size:19px;margin:0 0 12px}.nav{display:flex;gap:7px;overflow:auto}.nav a{color:var(--muted);text-decoration:none;background:var(--card);padding:8px 12px;border-radius:18px;white-space:nowrap}.nav a.active{background:var(--accent);color:white}
main{max-width:1100px;margin:auto;padding:18px}.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:15px;margin-bottom:11px}
.row{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}.muted{color:var(--muted);font-size:13px}.pill{display:inline-block;background:var(--card2);border-radius:20px;padding:4px 10px;font-size:12px}.on{color:var(--green)}.off{color:var(--red)}
button{border:0;border-radius:8px;padding:9px 13px;background:var(--accent);color:white;font-weight:600;cursor:pointer}button.danger{background:transparent;color:var(--red);border:1px solid var(--red)}button.ghost{background:transparent;border:1px solid var(--border)}
input,textarea{background:var(--card2);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:9px;font:inherit;width:100%}textarea{min-height:150px}
form.inline{display:inline-flex;gap:7px;align-items:center}form.inline input{width:80px}.actions{display:flex;gap:7px;flex-wrap:wrap}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:11px}
h2{font-size:15px;color:var(--muted);margin:24px 0 10px}.flash{padding:10px 13px;border-radius:9px;background:#173328;color:var(--green);margin-bottom:12px}.flash.err{background:#3a1d1f;color:var(--red)}
</style>
"""

def page(title, body):
    nav = f"""
    <div class="top"><h1>🤖 16 Accounts Admin</h1>
    <div class="nav">
      <a class="active" href="/">Аккаунты</a>
      <a href="/groups">Группы</a>
      <a href="/logout">Выйти</a>
    </div></div>
    <main>{body}</main>
    """
    return render_template_string("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>"+title+"</title>"+STYLE+"</head><body>"+nav+"</body></html>")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if auth.verify(request.form.get("username",""), request.form.get("password","")):
            session["username"] = request.form.get("username")
            return redirect("/")
        return render_template_string(STYLE+"<main><div class='card'><h2>Ошибка</h2>Неверный логин или пароль.</div></main>")
    return render_template_string(STYLE+"<main style='max-width:360px'><div class='card'><h2>Вход</h2><form method='post'><input name='username' placeholder='Логин'><br><br><input name='password' type='password' placeholder='Пароль'><br><br><button>Войти</button></form></div></main>")

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
        status = rt.get("status", "stopped")
        configured = bool(cfg.api_id and cfg.api_hash and cfg.session)
        pill = "🟢 работает" if status == "running" else ("🔴 ошибка" if status == "error" else "⚪ остановлен")
        config_pill = "настроен" if configured else "не настроен"
        action = f"""
        <form method='post' action='/account/{cfg.key}/{"stop" if status=="running" else "start"}'>
          <button class='{"danger" if status=="running" else ""}'>{'⏹ Остановить' if status=="running" else '▶ Запустить'}</button>
        </form>"""
        cards += f"""
        <div class='card'>
          <div class='row'><div><b>{i}. {cfg.name}</b><div class='muted'>{pill} · Telegram: {config_pill}</div></div>{action}</div>
          <div class='actions' style='margin-top:10px'>
            <a href='/account/{cfg.key}'><button class='ghost'>⚙ Настройки и стиль</button></a>
            <a href='/account/{cfg.key}/groups'><button class='ghost'>📋 Группы</button></a>
          </div>
          {("<div class='muted' style='margin-top:8px'>Ошибка: "+rt.get("error","")+"</div>") if status=="error" else ""}
        </div>"""
    body = "<h2>16 независимых аккаунтов</h2>"+cards
    return page("Аккаунты", body)

@app.route("/groups", methods=["GET", "POST"])
@login_required
def groups_page():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "save_common":
            mode = request.form.get("mode", "common")
            try:
                store.set_mode(mode)
                store.set_common_reply_interval(int(request.form.get("reply_interval", "1")))
            except Exception:
                pass
            store.set_common_persona(request.form.get("common_persona", ""))
            store.set_common_message_once(request.form.get("message_once") == "1")
            return redirect("/groups")

    groups = store.list_common_groups()
    rows = ""
    for gid, info in groups.items():
        enabled = info.get("reply_enabled", True)
        rows += f"""
        <div class='card'>
          <div class='row'>
            <div><b>{store.display_label(info)}</b><div class='muted'>ID: {gid} · {'ответы включены' if enabled else 'ответы выключены'}</div></div>
            <div class='actions'>
              <form method='post' action='/groups/toggle'><input type='hidden' name='chat_id' value='{gid}'><input type='hidden' name='value' value='{'0' if enabled else '1'}'><button class='ghost'>{'🔕 Выключить' if enabled else '🔔 Включить'}</button></form>
              <form method='post' action='/groups/remove'><input type='hidden' name='chat_id' value='{gid}'><button class='danger'>Удалить</button></form>
            </div>
          </div>
        </div>"""

    mode = store.get_mode()
    persona = store.get_common_persona("Ты — обычный участник чата. Отвечай естественно и по смыслу сообщения.")
    interval = store.get_common_reply_interval()
    once = store.common_message_once()
    body = f"""
    <div class='row'><h2>🌐 Общий режим</h2><span class='pill'>{'АКТИВЕН' if mode == 'common' else 'не активен'}</span></div>
    <div class='card'>
      <form method='post'>
        <input type='hidden' name='action' value='save_common'>
        <h2 style='margin-top:0'>Режим работы</h2>
        <label><input type='radio' name='mode' value='common' {'checked' if mode == 'common' else ''} style='width:auto'> 🌐 Общий — все аккаунты используют общий список групп и один общий ИИ-промпт</label><br><br>
        <label><input type='radio' name='mode' value='personal' {'checked' if mode == 'personal' else ''} style='width:auto'> 👤 Личный — каждый аккаунт использует свои группы и свой промпт</label>

        <h2>Общий ИИ-промпт</h2>
        <textarea name='common_persona' placeholder='Общий промпт для всех аккаунтов...'>{persona}</textarea>
        <p class='muted'>В «Общем» режиме этот промпт применяется ко всем 16 аккаунтам.</p>

        <h2>Разовый ответ</h2>
        <label><input name='message_once' type='checkbox' value='1' {'checked' if once else ''} style='width:auto'> Один раз отвечать на каждое входящее сообщение</label><br><br>
        <label>Интервал сообщений: <input name='reply_interval' type='number' min='1' value='{interval}'></label>
        <p class='muted'>При значении 1 каждый аккаунт отвечает на каждое подходящее сообщение один раз.</p><br>
        <button>💾 Сохранить настройки общего режима</button>
      </form>
    </div>

    <h2>Группы общего режима</h2>
    <div class='card'>
      <div class='row'><div><b>Общий список групп</b><div class='muted'>Эти группы используются всеми аккаунтами, когда активен «Общий» режим.</div></div><span class='pill'>{len(groups)} групп</span></div>
    </div>
    {rows or '<div class="card"><div class="muted">Общих групп пока нет.</div></div>'}
    <div class='card'>
      <h2 style='margin-top:0'>Добавить группу вручную</h2>
      <form method='post' action='/groups/add'>
        <input name='chat_id' placeholder='ID группы / канала' required><br><br>
        <input name='username' placeholder='username, например my_group'><br><br>
        <input name='title' placeholder='Название'><br><br>
        <button>➕ Добавить в общий список</button>
      </form>
    </div>
    """
    return page("Общий режим и группы", body)

@app.route("/groups/add", methods=["POST"])
@login_required
def common_group_add():
    try:
        chat_id = int(request.form["chat_id"])
    except Exception:
        return "Некорректный chat_id", 400
    store.add_common_group(chat_id, request.form.get("username") or None, request.form.get("title") or None)
    return redirect("/groups")

@app.route("/groups/toggle", methods=["POST"])
@login_required
def common_group_toggle():
    try:
        chat_id = int(request.form["chat_id"])
        value = request.form.get("value") == "1"
    except Exception:
        return "Bad request", 400
    store.set_common_reply_enabled(chat_id, value)
    return redirect("/groups")

@app.route("/groups/remove", methods=["POST"])
@login_required
def common_group_remove():
    try:
        chat_id = int(request.form["chat_id"])
    except Exception:
        return "Некорректный chat_id", 400
    store.remove_common_group(chat_id)
    return redirect("/groups")

@app.route("/account/<key>", methods=["GET","POST"])
@login_required
def account_page(key):
    cfg = next((x for x in CONFIGS if x.key == key), None)
    if not cfg: return "Not found", 404
    if request.method == "POST":
        persona = request.form.get("persona","").strip()
        if persona:
            store.set_persona(key, persona)
        for field, setter in [
            ("chat_interval", store.set_chat_interval),
            ("autocomment_interval", store.set_autocomment_interval),
        ]:
            try:
                setter(key, int(request.form.get(field)))
            except Exception:
                pass
        store.set_autocomment_enabled(key, request.form.get("autocomment_enabled") == "1")
        return redirect(url_for("account_page", key=key))
    persona = store.get_persona(key, cfg.persona)
    enabled = store.is_enabled(key)
    comment = store.is_autocomment_enabled(key)
    body = f"""
    <h2>{cfg.name}</h2>
    <div class='card'>
      <div class='row'><span>Состояние: {'🟢 включён' if enabled else '🔴 выключен'}</span>
      <form method='post' action='/account/{key}/{"stop" if RUNTIME.get(key,{}).get("status")=="running" else "start"}'><button>{'⏹ Остановить' if RUNTIME.get(key,{}).get("status")=="running" else '▶ Запустить'}</button></form></div>
    </div>
    <div class='card'>
      <form method='post'>
        <h2 style='margin-top:0'>Стиль общения</h2>
        <textarea name='persona'>{persona}</textarea>
        <p class='muted'>Эта персона используется только этим аккаунтом.</p>
        <h2>Интервалы</h2>
        <label>Ответы на сообщения: <input name='chat_interval' type='number' min='1' value='{store.get_chat_interval(key)}'></label><br><br>
        <label>Комментарии: <input name='autocomment_interval' type='number' min='1' value='{store.get_autocomment_interval(key)}'></label><br><br>
        <label><input name='autocomment_enabled' type='checkbox' value='1' {'checked' if comment else ''} style='width:auto'> Автокомментинг включён</label><br><br>
        <button>💾 Сохранить</button>
      </form>
    </div>
    """
    return page(cfg.name, body)

@app.route("/account/<key>/<action>", methods=["POST"])
@login_required
def account_action(key, action):
    if key not in RUNTIME: return "Not found", 404
    if action == "start":
        ok, msg = run_async(START_ACCOUNT(key))
    elif action == "stop":
        ok, msg = run_async(STOP_ACCOUNT(key))
    else:
        return "Bad action", 400
    if ok and action == "start":
        store.set_enabled(key, True)
    if ok and action == "stop":
        store.set_enabled(key, False)
    return redirect("/")

@app.route("/account/<key>/groups", methods=["GET","POST"])
@login_required
def account_groups(key):
    cfg = next((x for x in CONFIGS if x.key == key), None)
    if not cfg: return "Not found", 404

    discovered = []
    discovery_error = ""
    if request.method == "POST" and request.form.get("action") == "discover":
        try:
            discovered = run_async(discover_account_groups(key))
        except Exception as e:
            discovery_error = str(e)

    rows = ""
    for gid, info in store.list_groups(key).items():
        enabled = info.get("reply_enabled", True)
        rows += f"""
        <div class='card'>
          <div class='row'>
            <div><b>{store.display_label(info)}</b><div class='muted'>ID: {gid} · {'ответы включены' if enabled else 'ответы выключены'}</div></div>
            <div class='actions'>
              <form method='post' action='/account/{key}/groups/toggle'><input type='hidden' name='chat_id' value='{gid}'><input type='hidden' name='value' value='{'0' if enabled else '1'}'><button class='ghost'>{'🔕 Выключить' if enabled else '🔔 Включить'}</button></form>
              <form method='post' action='/account/{key}/groups/remove'><input type='hidden' name='chat_id' value='{gid}'><button class='danger'>Удалить</button></form>
            </div>
          </div>
        </div>"""

    discovery_html = ""
    if discovery_error:
        discovery_html = f"<div class='flash err'>Ошибка автообнаружения: {discovery_error}</div>"
    elif discovered:
        items = ""
        for item in discovered:
            gid = item['id']; username = item.get('username') or ''; title = item.get('title') or 'Без названия'
            label = ('@'+username) if username else title
            items += f"""<label class='card' style='display:block;cursor:pointer'><input type='checkbox' name='chat_ids' value='{gid}' style='width:auto'> <b>{label}</b><div class='muted'>ID: {gid}</div></label>"""
        discovery_html = f"""
        <div class='card'>
          <h2 style='margin-top:0'>🔎 Найденные Telegram-чаты</h2>
          <div class='muted' style='margin-bottom:10px'>Выбери чаты, которые добавить в личный список этого аккаунта.</div>
          <form method='post' action='/account/{key}/groups/add-discovered'>
            {items}
            <button>➕ Добавить выбранные</button>
          </form>
        </div>"""

    body = f"""
    <div class='row'><h2>{cfg.name} — личные группы</h2><a href='/'><button class='ghost'>← К аккаунтам</button></a></div>
    <div class='card'>
      <div class='row'><div><b>👤 Личный список</b><div class='muted' style='margin-top:6px'>Эти группы принадлежат только аккаунту {cfg.name}. Они не меняют общий список.</div></div><span class='pill'>{len(store.list_groups(key))} групп</span></div>
    </div>
    <div class='card'>
      <form method='post'>
        <input type='hidden' name='action' value='discover'>
        <button>🔎 Автообнаружение групп</button>
      </form>
      <div class='muted' style='margin-top:8px'>Поиск выполняется от имени этого Telegram-аккаунта и показывает чаты, к которым у него есть доступ.</div>
    </div>
    {discovery_html}
    {rows or '<div class="card"><div class="muted">Личных групп пока нет.</div></div>'}
    <div class='card'>
      <h2 style='margin-top:0'>Добавить вручную</h2>
      <form method='post' action='/account/{key}/groups/add'>
        <input name='chat_id' placeholder='ID группы / канала' required><br><br>
        <input name='username' placeholder='username (необязательно)'><br><br>
        <input name='title' placeholder='Название'><br><br>
        <button>➕ Добавить</button>
      </form>
    </div>
    """
    return page("Личные группы", body)

async def discover_account_groups(key):
    runtime = RUNTIME.get(key)
    if not runtime or not runtime.get("client"):
        raise RuntimeError("Сначала авторизуй и запусти этот аккаунт.")
    client = runtime["client"]
    found = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        # Only real groups/channels; ignore private 1:1 dialogs.
        is_group_or_channel = getattr(entity, "megagroup", False) or isinstance(entity, Channel)
        if not is_group_or_channel:
            continue
        found.append({
            "id": int(dialog.id),
            "title": dialog.title or "Без названия",
            "username": getattr(entity, "username", None),
        })
    return found

@app.route("/account/<key>/groups/add-discovered", methods=["POST"])
@login_required
def account_groups_add_discovered(key):
    cfg = next((x for x in CONFIGS if x.key == key), None)
    if not cfg: return "Not found", 404
    ids = request.form.getlist("chat_ids")
    runtime = RUNTIME.get(key)
    if not runtime or not runtime.get("client"):
        return redirect(f"/account/{key}/groups")
    client = runtime["client"]
    async def add_selected():
        for raw in ids:
            try:
                entity = await client.get_entity(int(raw))
                store.add_group(key, int(raw), getattr(entity, "username", None), getattr(entity, "title", None))
            except Exception:
                continue
    try:
        run_async(add_selected())
    except Exception:
        pass
    return redirect(f"/account/{key}/groups")

@app.route("/account/<key>/groups/toggle", methods=["POST"])
@login_required
def group_toggle(key):
    try:
        chat_id = int(request.form["chat_id"])
        value = request.form.get("value") == "1"
    except Exception:
        return "Bad request", 400
    store.set_reply_enabled(key, chat_id, value)
    return redirect(f"/account/{key}/groups")

@app.route("/account/<key>/groups/add", methods=["POST"])
@login_required
def group_add(key):
    try:
        chat_id = int(request.form["chat_id"])
    except Exception:
        return "Некорректный chat_id", 400
    store.add_group(key, chat_id, request.form.get("username") or None, request.form.get("title") or None)
    return redirect(f"/account/{key}/groups")

@app.route("/account/<key>/groups/remove", methods=["POST"])
@login_required
def group_remove(key):
    try:
        chat_id = int(request.form["chat_id"])
    except Exception:
        return "Некорректный chat_id", 400
    store.remove_group(key, chat_id)
    return redirect(f"/account/{key}/groups")

def run_panel():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","8080")), threaded=True)
