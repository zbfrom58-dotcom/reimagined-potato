
import asyncio
import html
import os
from functools import wraps

from flask import Flask, request, redirect, url_for, session, render_template_string
from telethon.tl.types import Channel

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
CONFIG_BY_KEY = {cfg.key: cfg for cfg in CONFIGS}


def set_runtime(runtime, loop, start_account, stop_account):
    """
    Called by userbot.py BEFORE the Flask server starts.

    Important: do not replace this dict with a copy. Flask and userbot must
    see the same RUNTIME object so /account/<key>/groups can see clients.
    """
    global RUNTIME, LOOP, START_ACCOUNT, STOP_ACCOUNT, CONFIGS, CONFIG_BY_KEY
    RUNTIME = runtime
    LOOP = loop
    START_ACCOUNT = start_account
    STOP_ACCOUNT = stop_account
    CONFIGS = load_accounts()
    CONFIG_BY_KEY = {cfg.key: cfg for cfg in CONFIGS}

    # Guarantee a slot for every configured account.
    for cfg in CONFIGS:
        RUNTIME.setdefault(
            cfg.key,
            {
                "client": None,
                "status": "stopped",
                "error": "",
                "me": None,
                "common_started": False,
            },
        )


def run_async(coro, timeout=30):
    if LOOP is None:
        raise RuntimeError("Основной цикл ещё не запущен.")
    return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout=timeout)


def panel_configured():
    return bool(
        os.getenv("ADMIN_USERNAME") and os.getenv("ADMIN_PASSWORD")
    ) or bool(auth.list_users())


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not panel_configured():
            return (
                "Панель отключена: задайте ADMIN_USERNAME и ADMIN_PASSWORD.",
                503,
            )
        if not session.get("username"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


STYLE = """
<style>
:root{--bg:#0b0d12;--card:#151822;--card2:#1b1f2b;--border:#282d3c;
--text:#eef0f5;--muted:#8b93a7;--accent:#617df0;--green:#3ecf8e;
--red:#ef5b5b;--yellow:#e0b04f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.top{position:sticky;top:0;background:#0b0d12f2;border-bottom:1px solid var(--border);
padding:15px 18px;z-index:5}
.top h1{font-size:19px;margin:0 0 12px}
.nav{display:flex;gap:7px;overflow:auto}
.nav a{color:var(--muted);text-decoration:none;background:var(--card);
padding:8px 12px;border-radius:18px;white-space:nowrap}
.nav a.active{background:var(--accent);color:white}
main{max-width:1100px;margin:auto;padding:18px}
.card{background:var(--card);border:1px solid var(--border);
border-radius:14px;padding:15px;margin-bottom:11px}
.row{display:flex;align-items:center;justify-content:space-between;
gap:10px;flex-wrap:wrap}
.muted{color:var(--muted);font-size:13px}
.pill{display:inline-block;background:var(--card2);border-radius:20px;
padding:4px 10px;font-size:12px}
.on{color:var(--green)}.off{color:var(--red)}
button{border:0;border-radius:8px;padding:9px 13px;background:var(--accent);
color:white;font-weight:600;cursor:pointer}
button.danger{background:transparent;color:var(--red);border:1px solid var(--red)}
button.ghost{background:transparent;border:1px solid var(--border)}
input,textarea{background:var(--card2);border:1px solid var(--border);
border-radius:8px;color:var(--text);padding:9px;font:inherit;width:100%}
textarea{min-height:150px}
form.inline{display:inline-flex;gap:7px;align-items:center}
.actions{display:flex;gap:7px;flex-wrap:wrap}
.flash{padding:10px 13px;border-radius:9px;background:#173328;
color:var(--green);margin-bottom:12px}
.flash.err{background:#3a1d1f;color:var(--red)}
h2{font-size:15px;color:var(--muted);margin:20px 0 10px}
</style>
"""


def page(title, body, active="accounts"):
    nav = f"""
    <div class="top">
      <h1>🤖 16 Accounts Admin</h1>
      <div class="nav">
        <a class="{'active' if active=='accounts' else ''}" href="/">Аккаунты</a>
        <a class="{'active' if active=='groups' else ''}" href="/groups">Группы</a>
        <a href="/logout">Выйти</a>
      </div>
    </div>
    <main>{body}</main>
    """
    return render_template_string(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title>{STYLE}</head><body>{nav}</body></html>"
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ok = False

        admin_user = os.getenv("ADMIN_USERNAME")
        admin_pass = os.getenv("ADMIN_PASSWORD")
        if admin_user and admin_pass and username == admin_user and password == admin_pass:
            ok = True
        else:
            try:
                ok = bool(auth.verify(username, password))
            except Exception:
                ok = False

        if ok:
            session["username"] = username
            return redirect("/")
        return page(
            "Вход",
            "<div class='card'><div class='flash err'>Неверный логин или пароль.</div>"
            "<form method='post'><input name='username' placeholder='Логин' required><br><br>"
            "<input name='password' type='password' placeholder='Пароль' required><br><br>"
            "<button>Войти</button></form></div>",
        )

    return page(
        "Вход",
        "<div class='card'><form method='post'>"
        "<input name='username' placeholder='Логин' required><br><br>"
        "<input name='password' type='password' placeholder='Пароль' required><br><br>"
        "<button>Войти</button></form></div>",
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    cards = []

    for i, cfg in enumerate(CONFIGS, 1):
        rt = RUNTIME.get(cfg.key, {})
        status = rt.get("status", "stopped")
        configured = bool(cfg.api_id and cfg.api_hash and cfg.session)

        if status == "running":
            pill = "🟢 работает"
        elif status == "starting":
            pill = "🟡 запускается"
        elif status == "error":
            pill = "🔴 ошибка"
        else:
            pill = "⚪ остановлен"

        config_pill = "настроен" if configured else "не настроен"
        action = (
            f"<form method='post' action='/account/{cfg.key}/stop'>"
            "<button class='danger'>⏹ Остановить</button></form>"
            if status == "running"
            else
            f"<form method='post' action='/account/{cfg.key}/start'>"
            "<button>▶ Запустить</button></form>"
        )

        error = ""
        if status == "error" and rt.get("error"):
            error = (
                "<div class='flash err' style='margin-top:8px'>"
                + html.escape(str(rt["error"]))
                + "</div>"
            )

        cards.append(
            f"""
            <div class='card'>
              <div class='row'>
                <div>
                  <b>{i}. {html.escape(cfg.name)}</b>
                  <div class='muted'>{pill} · Telegram: {config_pill}</div>
                </div>
                {action}
              </div>
              <div class='actions' style='margin-top:10px'>
                <a href='/account/{cfg.key}'><button class='ghost'>⚙ Настройки</button></a>
                <a href='/account/{cfg.key}/groups'><button class='ghost'>📋 Группы</button></a>
              </div>
              {error}
            </div>
            """
        )

    return page("Аккаунты", "<h2>16 независимых аккаунтов</h2>" + "".join(cards))


@app.route("/account/<key>/<action>", methods=["POST"])
@login_required
def account_action(key, action):
    if key not in CONFIG_BY_KEY:
        return "Not found", 404
    if action not in {"start", "stop"}:
        return "Bad action", 400
    if LOOP is None or START_ACCOUNT is None or STOP_ACCOUNT is None:
        return "Юзербот ещё не инициализировал runtime.", 503

    try:
        if action == "start":
            ok, msg = run_async(START_ACCOUNT(key))
            if ok:
                store.set_enabled(key, True)
        else:
            ok, msg = run_async(STOP_ACCOUNT(key))
            if ok:
                store.set_enabled(key, False)

        if ok:
            return redirect("/")
        return page(
            "Ошибка",
            f"<div class='flash err'>{html.escape(str(msg))}</div>"
            "<a href='/'><button class='ghost'>← Назад</button></a>",
        )
    except Exception as exc:
        return page(
            "Ошибка",
            f"<div class='flash err'>{html.escape(str(exc))}</div>"
            "<a href='/'><button class='ghost'>← Назад</button></a>",
        )


@app.route("/account/<key>", methods=["GET", "POST"])
@login_required
def account_page(key):
    cfg = CONFIG_BY_KEY.get(key)
    if not cfg:
        return "Not found", 404

    if request.method == "POST":
        persona = request.form.get("persona", "").strip()
        if persona:
            store.set_persona(key, persona)

        try:
            store.set_chat_interval(key, int(request.form.get("chat_interval", "5")))
        except Exception:
            pass

        try:
            store.set_autocomment_interval(
                key, int(request.form.get("autocomment_interval", "1"))
            )
        except Exception:
            pass

        store.set_autocomment_enabled(
            key, request.form.get("autocomment_enabled") == "1"
        )
        return redirect(url_for("account_page", key=key))

    rt = RUNTIME.get(key, {})
    status = rt.get("status", "stopped")
    persona = store.get_persona(key, cfg.persona)

    action = (
        f"<form method='post' action='/account/{key}/stop'>"
        "<button class='danger'>⏹ Остановить</button></form>"
        if status == "running"
        else
        f"<form method='post' action='/account/{key}/start'>"
        "<button>▶ Запустить</button></form>"
    )

    body = f"""
    <div class='row'>
      <h2>{html.escape(cfg.name)}</h2>
      <a href='/'><button class='ghost'>← К аккаунтам</button></a>
    </div>

    <div class='card'>
      <div class='row'>
        <span>Состояние: <b>{html.escape(status)}</b></span>
        {action}
      </div>
      {("<div class='flash err' style='margin-top:10px'>"+html.escape(str(rt.get("error")))+"</div>") if rt.get("error") else ""}
    </div>

    <div class='card'>
      <form method='post'>
        <h2 style='margin-top:0'>Стиль общения</h2>
        <textarea name='persona'>{html.escape(persona)}</textarea>

        <h2>Интервалы</h2>
        <label>Ответы:
          <input name='chat_interval' type='number' min='1'
                 value='{store.get_chat_interval(key)}'>
        </label><br><br>

        <label>Комментарии:
          <input name='autocomment_interval' type='number' min='1'
                 value='{store.get_autocomment_interval(key)}'>
        </label><br><br>

        <label>
          <input name='autocomment_enabled' type='checkbox' value='1'
                 {'checked' if store.is_autocomment_enabled(key) else ''}
                 style='width:auto'>
          Автокомментинг включён
        </label><br><br>

        <button>💾 Сохранить</button>
      </form>
    </div>
    """
    return page(cfg.name, body)


async def discover_account_groups(key):
    rt = RUNTIME.get(key)
    if not rt or rt.get("status") != "running" or not rt.get("client"):
        raise RuntimeError(
            "Аккаунт не запущен. Сначала нажми «▶ Запустить», "
            "дождись статуса «🟢 работает», затем повтори автообнаружение."
        )

    client = rt["client"]
    if not client.is_connected():
        raise RuntimeError("Telegram-клиент не подключён.")

    found = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity

        # Supergroups and channels; ignore private 1:1 chats.
        is_group_or_channel = (
            getattr(entity, "megagroup", False) or isinstance(entity, Channel)
        )
        if not is_group_or_channel:
            continue

        found.append(
            {
                "id": int(dialog.id),
                "title": dialog.title or "Без названия",
                "username": getattr(entity, "username", None),
            }
        )

    return found


@app.route("/account/<key>/groups", methods=["GET", "POST"])
@login_required
def account_groups(key):
    cfg = CONFIG_BY_KEY.get(key)
    if not cfg:
        return "Not found", 404

    discovered = []
    discovery_error = ""

    if request.method == "POST" and request.form.get("action") == "discover":
        try:
            discovered = run_async(discover_account_groups(key), timeout=60)
        except Exception as exc:
            discovery_error = str(exc)

    rows = []
    for gid, info in store.list_groups(key).items():
        enabled = info.get("reply_enabled", True)
        label = store.display_label(info)
        rows.append(
            f"""
            <div class='card'>
              <div class='row'>
                <div>
                  <b>{html.escape(label)}</b>
                  <div class='muted'>ID: {html.escape(str(gid))} ·
                    {'ответы включены' if enabled else 'ответы выключены'}</div>
                </div>
                <div class='actions'>
                  <form method='post' action='/account/{key}/groups/toggle'>
                    <input type='hidden' name='chat_id' value='{html.escape(str(gid))}'>
                    <input type='hidden' name='value' value='{'0' if enabled else '1'}'>
                    <button class='ghost'>{'🔕 Выключить' if enabled else '🔔 Включить'}</button>
                  </form>
                  <form method='post' action='/account/{key}/groups/remove'>
                    <input type='hidden' name='chat_id' value='{html.escape(str(gid))}'>
                    <button class='danger'>Удалить</button>
                  </form>
                </div>
              </div>
            </div>
            """
        )

    discovery_html = ""
    if discovery_error:
        discovery_html = (
            "<div class='flash err'>Ошибка автообнаружения: "
            + html.escape(discovery_error)
            + "</div>"
        )
    elif discovered:
        items = []
        for item in discovered:
            gid = item["id"]
            username = item.get("username") or ""
            title = item.get("title") or "Без названия"
            label = "@" + username if username else title
            items.append(
                f"""
                <label class='card' style='display:block;cursor:pointer'>
                  <input type='checkbox' name='chat_ids' value='{gid}' style='width:auto'>
                  <b>{html.escape(label)}</b>
                  <div class='muted'>ID: {gid}</div>
                </label>
                """
            )

        discovery_html = f"""
        <div class='card'>
          <h2 style='margin-top:0'>🔎 Найденные Telegram-чаты</h2>
          <form method='post' action='/account/{key}/groups/add-discovered'>
            {''.join(items)}
            <button>➕ Добавить выбранные</button>
          </form>
        </div>
        """

    body = f"""
    <div class='row'>
      <h2>{html.escape(cfg.name)} — личные группы</h2>
      <a href='/'><button class='ghost'>← К аккаунтам</button></a>
    </div>

    <div class='card'>
      <div class='row'>
        <div>
          <b>👤 Личный список</b>
          <div class='muted'>Эти группы принадлежат только аккаунту {html.escape(cfg.name)}.</div>
        </div>
        <span class='pill'>{len(store.list_groups(key))} групп</span>
      </div>
    </div>

    <div class='card'>
      <form method='post'>
        <input type='hidden' name='action' value='discover'>
        <button>🔎 Автообнаружение групп</button>
      </form>
      <div class='muted' style='margin-top:8px'>
        Поиск выполняется от имени этого Telegram-аккаунта.
      </div>
    </div>

    {discovery_html}
    {''.join(rows) or "<div class='card'><div class='muted'>Личных групп пока нет.</div></div>"}

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


@app.route("/account/<key>/groups/add-discovered", methods=["POST"])
@login_required
def account_groups_add_discovered(key):
    if key not in CONFIG_BY_KEY:
        return "Not found", 404

    ids = request.form.getlist("chat_ids")
    rt = RUNTIME.get(key)
    if not rt or rt.get("status") != "running" or not rt.get("client"):
        return redirect(url_for("account_groups", key=key))

    client = rt["client"]

    async def add_selected():
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

    try:
        run_async(add_selected(), timeout=60)
    except Exception:
        pass

    return redirect(url_for("account_groups", key=key))


@app.route("/account/<key>/groups/toggle", methods=["POST"])
@login_required
def group_toggle(key):
    if key not in CONFIG_BY_KEY:
        return "Not found", 404
    try:
        chat_id = int(request.form["chat_id"])
    except Exception:
        return "Bad request", 400

    store.set_reply_enabled(key, chat_id, request.form.get("value") == "1")
    return redirect(url_for("account_groups", key=key))


@app.route("/account/<key>/groups/remove", methods=["POST"])
@login_required
def group_remove(key):
    if key not in CONFIG_BY_KEY:
        return "Not found", 404
    try:
        chat_id = int(request.form["chat_id"])
    except Exception:
        return "Bad request", 400

    store.remove_group(key, chat_id)
    return redirect(url_for("account_groups", key=key))


@app.route("/groups", methods=["GET", "POST"])
@login_required
def groups_page():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "save_common":
            try:
                store.set_mode(request.form.get("mode", "common"))
                store.set_common_reply_interval(
                    int(request.form.get("reply_interval", "1"))
                )
            except Exception:
                pass

            store.set_common_persona(request.form.get("common_persona", ""))
            store.set_common_message_once(
                request.form.get("message_once") == "1"
            )
            return redirect("/groups")

    groups = store.list_common_groups()
    rows = []

    for gid, info in groups.items():
        enabled = info.get("reply_enabled", True)
        label = store.display_label(info)
        rows.append(
            f"""
            <div class='card'>
              <div class='row'>
                <div>
                  <b>{html.escape(label)}</b>
                  <div class='muted'>ID: {html.escape(str(gid))}</div>
                </div>
                <div class='actions'>
                  <form method='post' action='/groups/toggle'>
                    <input type='hidden' name='chat_id' value='{html.escape(str(gid))}'>
                    <input type='hidden' name='value' value='{'0' if enabled else '1'}'>
                    <button class='ghost'>{'🔕 Выключить' if enabled else '🔔 Включить'}</button>
                  </form>
                  <form method='post' action='/groups/remove'>
                    <input type='hidden' name='chat_id' value='{html.escape(str(gid))}'>
                    <button class='danger'>Удалить</button>
                  </form>
                </div>
              </div>
            </div>
            """
        )

    mode = store.get_mode()
    common_enabled = store.is_common_enabled()
    persona = store.get_common_persona(
        "Ты — обычный участник чата. Отвечай естественно и по смыслу сообщения."
    )

    body = f"""
    <div class='row'>
      <h2>🌐 Общий режим</h2>
      <span class='pill'>{'🟢 ВКЛЮЧЕН' if common_enabled and mode == 'common' else '⚪ ВЫКЛЮЧЕН'}</span>
    </div>

    <div class='card'>
      <div class='row'>
        <div>
          <b>Главный выключатель общего режима</b>
          <div class='muted'>При включении запускаются все 16 настроенных аккаунтов.</div>
        </div>
        <form method='post' action='/common/toggle'>
          <input type='hidden' name='value' value='{'0' if common_enabled else '1'}'>
          <button class='{'danger' if common_enabled else ''}'>
            {'⏹ Выключить' if common_enabled else '▶ Включить'}
          </button>
        </form>
      </div>
    </div>

    <div class='card'>
      <form method='post'>
        <input type='hidden' name='action' value='save_common'>
        <h2 style='margin-top:0'>Режим работы</h2>
        <label><input type='radio' name='mode' value='common'
          {'checked' if mode == 'common' else ''} style='width:auto'>
          🌐 Общий</label><br><br>
        <label><input type='radio' name='mode' value='personal'
          {'checked' if mode == 'personal' else ''} style='width:auto'>
          👤 Личный</label>

        <h2>Общий ИИ-промпт</h2>
        <textarea name='common_persona'>{html.escape(persona)}</textarea>

        <h2>Интервал ответов</h2>
        <input name='reply_interval' type='number' min='1'
               value='{store.get_common_reply_interval()}'>

        <br><br>
        <button>💾 Сохранить</button>
      </form>
    </div>

    <h2>Общие группы</h2>
    {''.join(rows) or "<div class='card'><div class='muted'>Общих групп пока нет.</div></div>"}

    <div class='card'>
      <h2 style='margin-top:0'>Добавить группу вручную</h2>
      <form method='post' action='/groups/add'>
        <input name='chat_id' placeholder='ID группы / канала' required><br><br>
        <input name='username' placeholder='username'><br><br>
        <input name='title' placeholder='Название'><br><br>
        <button>➕ Добавить</button>
      </form>
    </div>
    """
    return page("Общий режим и группы", body, active="groups")


@app.route("/common/toggle", methods=["POST"])
@login_required
def common_toggle():
    enabled = request.form.get("value") == "1"
    store.set_common_enabled(enabled)

    if LOOP is not None and START_ACCOUNT is not None and STOP_ACCOUNT is not None:
        if enabled:
            async def start_all():
                for cfg in CONFIGS:
                    ok, _ = await START_ACCOUNT(cfg.key)
                    if ok:
                        RUNTIME[cfg.key]["common_started"] = True

            try:
                run_async(start_all(), timeout=180)
            except Exception:
                pass
        else:
            async def stop_started():
                for cfg in CONFIGS:
                    rt = RUNTIME.get(cfg.key, {})
                    if rt.get("common_started"):
                        try:
                            await STOP_ACCOUNT(cfg.key)
                        finally:
                            rt["common_started"] = False

            try:
                run_async(stop_started(), timeout=180)
            except Exception:
                pass

    return redirect("/groups")


@app.route("/groups/add", methods=["POST"])
@login_required
def common_group_add():
    try:
        chat_id = int(request.form["chat_id"])
    except Exception:
        return "Некорректный chat_id", 400

    store.add_common_group(
        chat_id,
        request.form.get("username") or None,
        request.form.get("title") or None,
    )
    return redirect("/groups")


@app.route("/groups/toggle", methods=["POST"])
@login_required
def common_group_toggle():
    try:
        chat_id = int(request.form["chat_id"])
    except Exception:
        return "Bad request", 400

    store.set_common_reply_enabled(
        chat_id, request.form.get("value") == "1"
    )
    return redirect("/groups")


@app.route("/groups/remove", methods=["POST"])
@login_required
def common_group_remove():
    try:
        chat_id = int(request.form["chat_id"])
    except Exception:
        return "Bad request", 400

    store.remove_common_group(chat_id)
    return redirect("/groups")


def run_panel():
    port = int(os.getenv("PORT", "8080"))
    host = "0.0.0.0"
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    run_panel()
