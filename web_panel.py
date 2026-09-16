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
    <div class="top"><h1>🤖 15 Accounts Admin</h1>
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
        if status == "running":
            pill = "🟢 работает"
        elif status == "auth_required":
            pill = "🟠 нужна авторизация"
        elif status == "error":
            pill = "🔴 ошибка"
        else:
            pill = "⚪ остановлен"
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
          {(("<div class='muted' style='margin-top:8px'>" + ("Авторизация: " if status=="auth_required" else "Ошибка: ") + rt.get("error","") + "</div>")) if status in ("error", "auth_required") else ""}
        </div>"""
    body = "<h2>16 независимых аккаунтов</h2>"+cards
    return page("Аккаунты", body)

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
      <div class='row'><span>Состояние: {'🟢 работает' if RUNTIME.get(key,{}).get('status') == 'running' else ('🟠 нужна авторизация' if RUNTIME.get(key,{}).get('status') == 'auth_required' else ('🔴 ошибка' if RUNTIME.get(key,{}).get('status') == 'error' else '⚪ остановлен'))}</span>
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

@app.route("/account/<key>/groups")
@login_required
def account_groups(key):
    cfg = next((x for x in CONFIGS if x.key == key), None)
    if not cfg: return "Not found", 404
    rows = ""
    for gid, info in store.list_groups(key).items():
        rows += f"<div class='card'><div class='row'><b>{store.display_label(info)}</b><form method='post' action='/account/{key}/groups/remove'><input type='hidden' name='chat_id' value='{gid}'><button class='danger'>Удалить</button></form></div></div>"
    body = f"<h2>{cfg.name} — группы</h2>{rows or '<div class=\"card\">Групп пока нет.</div>'}<div class='card'><form method='post' action='/account/{key}/groups/add'><input name='chat_id' placeholder='ID группы'><br><br><input name='username' placeholder='username (необязательно)'><br><br><input name='title' placeholder='Название'><br><br><button>Добавить</button></form></div>"
    return page("Группы", body)

@app.route("/account/<key>/groups/add", methods=["POST"])
@login_required
def group_add(key):
    store.add_group(key, int(request.form["chat_id"]), request.form.get("username") or None, request.form.get("title") or None)
    return redirect(f"/account/{key}/groups")

@app.route("/account/<key>/groups/remove", methods=["POST"])
@login_required
def group_remove(key):
    store.remove_group(key, int(request.form["chat_id"]))
    return redirect(f"/account/{key}/groups")

def run_panel():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","8080")), threaded=True)
