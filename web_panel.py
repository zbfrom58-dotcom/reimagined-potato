import asyncio
import os
from functools import wraps
from flask import Flask, request, redirect, url_for, session, render_template_string

import ai_reply
import auth_store as auth
import multi_store as store
import actions_store
from telegram_actions import run_for_accounts
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

def page(title, body, active='accounts'):
    nav = f"""
    <div class="top"><h1>🤖 42 Accounts Admin</h1>
    <div class="nav">
      <a class="{'active' if active=='accounts' else ''}" href="/">Аккаунты</a>
      <a class="{'active' if active=='groups' else ''}" href="/groups">Группы</a>
      <a class="{'active' if active=='subscriptions' else ''}" href="/subscriptions">Подписки</a>
      <a class="{'active' if active=='reactions' else ''}" href="/reactions">Реакции</a>
      <a class="{'active' if active=='reports' else ''}" href="/reports">Жалобы</a>
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
    body = "<h2>42 независимых аккаунтов</h2>"+cards
    return page("Аккаунты", body)

@app.route("/common/toggle", methods=["POST"])
@login_required
def common_toggle():
    enabled = request.form.get("value") == "1"
    store.set_common_enabled(enabled)
    if enabled and LOOP is not None and START_ACCOUNT is not None:
        # Common mode is a master switch: start every configured account.
        async def start_all_common():
            results = {}
            for cfg in CONFIGS:
                ok, msg = await START_ACCOUNT(cfg.key)
                results[cfg.key] = ok
                if ok:
                    RUNTIME.setdefault(cfg.key, {})["common_started"] = True
            return results
        try:
            run_async(start_all_common(), timeout=120)
        except Exception:
            pass
    elif not enabled and LOOP is not None and STOP_ACCOUNT is not None:
        # Only stop accounts that were started by the common-mode master switch.
        async def stop_common_started():
            for cfg in CONFIGS:
                rt = RUNTIME.get(cfg.key, {})
                if rt.get("common_started"):
                    try:
                        await STOP_ACCOUNT(cfg.key)
                    finally:
                        rt["common_started"] = False
        try:
            run_async(stop_common_started(), timeout=120)
        except Exception:
            pass
    return redirect("/groups")

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
            store.set_common_enabled(request.form.get("common_enabled") == "1")
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
    common_enabled = store.is_common_enabled()
    persona = store.get_common_persona("Ты — обычный участник чата. Отвечай естественно и по смыслу сообщения.")
    interval = store.get_common_reply_interval()
    once = store.common_message_once()
    body = f"""
    <div class='row'><h2>🌐 Общий режим</h2>
      <span class='pill'>{'🟢 ВКЛЮЧЕН' if common_enabled and mode == 'common' else '⚪ ВЫКЛЮЧЕН'}</span>
    </div>
    <div class='card'>
      <div class='row'>
        <div><b>Главный выключатель общего режима</b><div class='muted'>Когда включён, все запущенные Telegram-аккаунты работают в выбранных общих группах по общему ИИ-промпту.</div></div>
        <form method='post' action='/common/toggle'>
          <input type='hidden' name='value' value='{'0' if common_enabled else '1'}'>
          <button class='{"danger" if common_enabled else ""}'>{'⏹ Выключить общий режим' if common_enabled else '▶ Включить общий режим'}</button>
        </form>
      </div>
    </div>
    <div class='card'>
      <form method='post'>
        <input type='hidden' name='action' value='save_common'>
        <h2 style='margin-top:0'>Режим работы</h2>
        <label><input type='radio' name='mode' value='common' {'checked' if mode == 'common' else ''} style='width:auto'> 🌐 Общий — все аккаунты используют общий список групп и один общий ИИ-промпт</label><br><br>
        <label><input type='radio' name='mode' value='personal' {'checked' if mode == 'personal' else ''} style='width:auto'> 👤 Личный — каждый аккаунт использует свои группы и свой промпт</label><p class='muted'>Главный выключатель выше запускает/останавливает все аккаунты для Общего режима. В Общем режиме их индивидуальные переключатели не требуются.</p>

        <h2>Общий ИИ-промпт</h2>
        <textarea name='common_persona' placeholder='Общий промпт для всех аккаунтов...'>{persona}</textarea>
        <p class='muted'>В «Общем» режиме этот промпт применяется ко всем 42 аккаунтам.</p>

        <h2>Ответы в общем режиме</h2>
        <label><input name='message_once' type='checkbox' value='1' {'checked' if once else ''} style='width:auto'> Разово отвечать на каждое входящее сообщение</label><br><br>
        <p class='muted'>Каждый запущенный аккаунт отвечает один раз на одно входящее сообщение в каждой выбранной общей группе. Сообщения от других твоих аккаунтов тоже считаются входящими.</p>
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
    return page("Общий режим и группы", body, active='groups')

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
    return page("Личные группы", body, active='accounts')

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

# ---------------- One-off Telegram actions ----------------

EMOJI_OPTIONS = ["👍", "❤️", "🔥", "😂", "😢", "😡", "🎉", "👏", "💯", "🤔", "👎"]


def _account_checkboxes(name: str, selected: set[str] | None = None) -> str:
    selected = selected or set()
    html = []
    for i, cfg in enumerate(CONFIGS, 1):
        checked = " checked" if cfg.key in selected else ""
        html.append(
            f"<label class='card' style='display:flex;gap:10px;align-items:center;padding:10px 12px;margin-bottom:7px'>"
            f"<input type='checkbox' name='{name}' value='{cfg.key}'{checked} style='width:auto'>"
            f"<span><b>{i}. {cfg.name}</b><span class='muted' style='display:block'>{'🟢 запущен' if RUNTIME.get(cfg.key,{}).get('status') == 'running' else '⚪ не запущен'}</span></span>"
            f"</label>"
        )
    return "".join(html)


def _render_action_history(kind: str) -> str:
    items = [x for x in actions_store.list_items(40) if x.get('type') == kind]
    if not items:
        return "<div class='card'><div class='muted'>История пока пустая.</div></div>"
    out = []
    for item in items:
        success = sum(1 for r in item.get('results', []) if r.get('ok'))
        total = len(item.get('results', []))
        out.append(
            f"<div class='card'><div class='row'><b>{item.get('link','')}</b><span class='pill'>{success}/{total}</span></div>"
            f"<div class='muted' style='margin-top:6px'>{item.get('emoji','')} {item.get('created_at','')} · аккаунтов: {total}</div>"
            f"<details style='margin-top:10px'><summary>Показать результаты</summary><div style='margin-top:8px'>"
            + "".join(f"<div>{r.get('account')}: {'✅' if r.get('ok') else '❌'} {r.get('message','')}</div>" for r in item.get('results', []))
            + "</div></details></div>"
        )
    return "".join(out)


@app.route('/subscriptions', methods=['GET', 'POST'])
@login_required
def subscriptions_page():
    flash = ''
    if request.method == 'POST':
        link = request.form.get('link', '').strip()
        selected = request.form.getlist('accounts')
        if not link or not selected:
            flash = "<div class='flash err'>Укажи ссылку и хотя бы один аккаунт.</div>"
        else:
            try:
                from telegram_actions import parse_join_link
                parse_join_link(link)
                results = run_async(run_for_accounts('subscribe', link, selected, None, RUNTIME, START_ACCOUNT), timeout=max(60, 15 * len(selected)))
                actions_store.add({'type': 'subscription', 'link': link, 'results': results})
                ok = sum(1 for x in results if x.get('ok'))
                flash = f"<div class='flash'>✅ Готово: {ok}/{len(results)} аккаунтов обработано.</div>"
            except Exception as e:
                flash = f"<div class='flash err'>Ошибка: {e}</div>"

    body = f"""
    <h2>➕ Подписки / вступления</h2>
    {flash}
    <div class='card'>
      <h2 style='margin-top:0'>Ссылка на группу или канал</h2>
      <p class='muted'>Поддерживаются публичные ссылки вида <code>https://t.me/name</code> и приватные invite-ссылки вида <code>https://t.me/+HASH</code> / <code>joinchat/HASH</code>.</p>
      <form method='post'>
        <input name='link' placeholder='Ссылка Telegram' required><br><br>
        <h2>Аккаунты</h2>
        <div>{_account_checkboxes('accounts')}</div>
        <br><button>▶ Выполнить вступление</button>
      </form>
    </div>
    <h2>История вступлений</h2>
    {_render_action_history('subscription')}
    """
    return page('Подписки', body, active='subscriptions')



REPORT_REASONS = {
    "Спам": ["Реклама", "Массовые сообщения", "Подозрительная активность"],
    "Мошенничество": ["Фишинг", "Обман", "Поддельный аккаунт"],
    "Насилие": ["Угрозы", "Призывы к насилию", "Опасный контент"],
    "Незаконный контент": ["Наркотики", "Продажа запрещённых товаров", "Другое"],
    "Другое": ["Нарушение правил", "Оскорбления", "Другое"],
}

@app.route('/reports', methods=['GET', 'POST'])
@login_required
def reports_page():
    flash = ''
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        reason = request.form.get('reason', '').strip()
        subreason = request.form.get('subreason', '').strip()
        selected = request.form.getlist('accounts')
        if username and not username.startswith('@'):
            username = '@' + username
        valid_subreasons = REPORT_REASONS.get(reason, [])
        if not username or not reason or subreason not in valid_subreasons or not selected:
            flash = "<div class='flash err'>Укажи @username, причину, подпричину и выбери хотя бы один аккаунт.</div>"
        else:
            results = [{'account': key, 'ok': True, 'message': 'Выбран для индивидуальной обработки; отправка жалобы выполняется вручную в Telegram.'} for key in selected]
            actions_store.add({
                'type': 'report',
                'username': username,
                'reason': reason,
                'subreason': subreason,
                'count': len(selected),
                'results': results,
            })
            flash = f"<div class='flash'>✅ Заявка подтверждена: выбрано {len(selected)} аккаунтов. Для каждого аккаунта создана отдельная запись на ручную обработку.</div>"

    items = [x for x in actions_store.list_items(40) if x.get('type') == 'report']
    history = ''
    if not items:
        history = "<div class='card'><div class='muted'>История жалоб пока пустая.</div></div>"
    else:
        blocks=[]
        for item in items:
            accounts_html = ''.join(f"<div>{r.get('account')}: {'🟢' if r.get('ok') else '🔴'} {r.get('message','')}</div>" for r in item.get('results', []))
            blocks.append(f"<div class='card'><div class='row'><b>{item.get('username','')}</b><span class='pill'>{item.get('reason','')} · {item.get('subreason','')}</span></div><div class='muted' style='margin-top:6px'>{item.get('created_at','')} · аккаунтов: {item.get('count',0)}</div><details style='margin-top:10px'><summary>Аккаунты</summary><div style='margin-top:8px'>{accounts_html}</div></details></div>")
        history=''.join(blocks)

    reason_options=''.join(f"<option value='{r}'>{r}</option>" for r in REPORT_REASONS)
    body=f"""
    <h2>🚩 Жалобы</h2>
    {flash}
    <div class='card'>
      <h2 style='margin-top:0'>Нарушитель</h2>
      <form method='post'>
        <input name='username' placeholder='@username' required>
        <br><br>
        <label>Причина</label><br><br>
        <select name='reason' required style='background:var(--card2);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:9px;width:100%'>
          <option value=''>Выбери причину</option>{reason_options}
        </select>
        <br><br>
        <label>Подпричина</label><br><br>
        <select name='subreason' required style='background:var(--card2);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:9px;width:100%'>
          <option value=''>Сначала выбери причину</option>
          {''.join(f"<option value='{x}'>{x}</option>" for vals in REPORT_REASONS.values() for x in vals)}
        </select>
        <p class='muted'>Подпричина проверяется сервером и должна соответствовать выбранной причине.</p>
        <h2>Аккаунты</h2>
        <div>{_account_checkboxes('accounts')}</div>
        <p class='muted'>Ты сам выбираешь аккаунты. После подтверждения для каждого выбранного аккаунта создаётся отдельная запись для ручной обработки жалобы.</p>
        <button>✅ Подтвердить</button>
      </form>
    </div>
    <h2>История жалоб</h2>
    {history}
    """
    return page('Жалобы', body, active='reports')

@app.route('/reactions', methods=['GET', 'POST'])
@login_required
def reactions_page():
    flash = ''
    if request.method == 'POST':
        link = request.form.get('link', '').strip()
        emoji = request.form.get('emoji', '👍').strip()
        selected = request.form.getlist('accounts')
        try:
            count = max(1, int(request.form.get('count', str(len(selected) or 1))))
        except Exception:
            count = 1
        if not link or not selected:
            flash = "<div class='flash err'>Укажи ссылку и хотя бы один аккаунт.</div>"
        elif emoji not in EMOJI_OPTIONS:
            flash = "<div class='flash err'>Выбери реакцию из списка.</div>"
        else:
            try:
                from telegram_actions import parse_message_link
                parse_message_link(link)
                targets = selected[:count]
                results = run_async(run_for_accounts('reaction', link, targets, emoji, RUNTIME, START_ACCOUNT), timeout=max(60, 15 * len(targets)))
                actions_store.add({'type': 'reaction', 'link': link, 'emoji': emoji, 'count': len(targets), 'results': results})
                ok = sum(1 for x in results if x.get('ok'))
                flash = f"<div class='flash'>✅ Реакции: {ok}/{len(results)} аккаунтов обработано.</div>"
            except Exception as e:
                flash = f"<div class='flash err'>Ошибка: {e}</div>"

    body = f"""
    <h2>❤️ Реакции</h2>
    {flash}
    <div class='card'>
      <h2 style='margin-top:0'>Сообщение</h2>
      <form method='post'>
        <input name='link' placeholder='https://t.me/channel/123' required><br><br>
        <label>Реакция</label><br><br>
        <select name='emoji' style='background:var(--card2);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:9px;width:100%'>
          {''.join(f"<option value='{e}'>{e}</option>" for e in EMOJI_OPTIONS)}
        </select><br><br>
        <label>Количество реакций (аккаунтов): <input name='count' type='number' min='1' max='{len(CONFIGS)}' value='1'></label><br><br>
        <h2>Аккаунты</h2>
        <div>{_account_checkboxes('accounts')}</div>
        <p class='muted'>Из отмеченных аккаунтов будут взяты первые N согласно указанному количеству. Выполнение идёт последовательно, по одной операции за раз.</p>
        <button>❤️ Поставить реакции</button>
      </form>
    </div>
    <h2>История реакций</h2>
    {_render_action_history('reaction')}
    """
    return page('Реакции', body, active='reactions')


