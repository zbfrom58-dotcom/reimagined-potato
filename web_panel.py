import asyncio, os
from functools import wraps
from flask import Flask, request, redirect, url_for, session, render_template_string, flash
import auth_store as auth
import multi_store as store
from accounts import load_accounts

app=Flask(__name__); app.secret_key=os.getenv("FLASK_SECRET_KEY",os.urandom(24).hex())
RUNTIME={}; LOOP=None; START_ACCOUNT=None; STOP_ACCOUNT=None; CONFIGS=load_accounts()

def set_runtime(runtime,loop,start_account,stop_account):
    global RUNTIME,LOOP,START_ACCOUNT,STOP_ACCOUNT
    RUNTIME,LOOP,START_ACCOUNT,STOP_ACCOUNT=runtime,loop,start_account,stop_account
def run_async(coro,timeout=30):
    if LOOP is None: raise RuntimeError("Основной цикл ещё не запущен.")
    return asyncio.run_coroutine_threadsafe(coro,LOOP).result(timeout)
def panel_configured(): return bool(auth.bootstrap())
def login_required(fn):
    @wraps(fn)
    def w(*a,**kw):
        if not panel_configured(): return "Панель отключена: задайте ADMIN_USERNAME и ADMIN_PASSWORD.",503
        if not session.get("username"): return redirect(url_for("login"))
        return fn(*a,**kw)
    return w

STYLE='''<style>
:root{--bg:#090b10;--card:#141821;--card2:#1b202b;--border:#293041;--text:#f2f4f8;--muted:#929bad;--accent:#637ff1;--green:#38d996;--red:#ef6262}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}a{color:inherit;text-decoration:none}
.top{position:sticky;top:0;background:#090b10ee;border-bottom:1px solid var(--border);padding:14px 18px;z-index:5}.top h1{font-size:19px;margin:0 0 11px}.nav{display:flex;gap:7px;overflow:auto}.nav a{color:var(--muted);background:var(--card);padding:8px 12px;border-radius:18px;white-space:nowrap}.nav a.active{background:var(--accent);color:white}
main{max-width:1120px;margin:auto;padding:18px}.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:15px;margin-bottom:12px}.row{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}.muted{color:var(--muted);font-size:13px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
button{border:0;border-radius:9px;padding:9px 13px;background:var(--accent);color:#fff;font-weight:650;cursor:pointer}.danger{background:transparent!important;color:var(--red)!important;border:1px solid var(--red)!important}.ghost{background:transparent;border:1px solid var(--border);color:var(--text)}input,textarea{background:var(--card2);border:1px solid var(--border);border-radius:9px;color:var(--text);padding:9px;font:inherit;width:100%}textarea{min-height:180px}.actions{display:flex;gap:7px;flex-wrap:wrap}.tabs{display:flex;gap:8px;margin-bottom:14px}.flash{padding:10px;border-radius:9px;background:#173329;color:var(--green);margin-bottom:12px}.flash.err{background:#3a1d20;color:var(--red)}
</style>'''

def page(title,body,active="home"):
    links=[("home","Режимы","/"),("accounts","Аккаунты","/accounts"),("admins","Доступ","/admins"),("logout","Выйти","/logout")]
    nav="".join("<a class='%s' href='%s'>%s</a>"%("active" if active==k else "",u,t) for k,t,u in links)
    flashes='{% with messages=get_flashed_messages(with_categories=true) %}{% for cat,msg in messages %}<div class="flash {% if cat=="err" %}err{% endif %}">{{msg}}</div>{% endfor %}{% endwith %}' 
    html="<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>%s</title>%s</head><body><div class='top'><h1>🤖 16 Accounts Admin</h1><div class='nav'>%s</div></div><main>%s%s</main></body></html>"
    return render_template_string(html%(title,STYLE,nav,flashes,body))

def group_rows(groups,prefix):
    out=""
    for gid,info in groups.items():
        out+="<div class='card'><div class='row'><div><b>%s</b><div class='muted'>ID: %s</div></div><form method='post' action='%s/groups/remove'><input type='hidden' name='chat_id' value='%s'><button class='danger'>Удалить</button></form></div></div>"%(store.display_label(info),gid,prefix,gid)
    return out or "<div class='card'><span class='muted'>Групп пока нет.</span></div>"

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST" and auth.verify(request.form.get("username"),request.form.get("password")):
        session["username"]=request.form.get("username").strip(); return redirect("/")
    return render_template_string(STYLE+"<main style='max-width:380px;margin:60px auto'><div class='card'><h2>Вход в админку</h2><form method='post'><input name='username' placeholder='Логин'><br><br><input name='password' type='password' placeholder='Пароль'><br><br><button>Войти</button></form></div></main>")
@app.route("/logout")
def logout(): session.clear(); return redirect("/login")

@app.route("/",methods=["GET","POST"])
@login_required
def dashboard():
    if request.method=="POST":
        mode=request.form.get("mode")
        if mode in ("shared","personal"): store.set_mode(mode); flash("Режим сохранён.")
        if request.form.get("save_shared"):
            p=request.form.get("persona","").strip()
            if p: store.set_shared_persona(p)
            try:
                store.set_shared_chat_interval(int(request.form["chat_interval"]))
                store.set_shared_autocomment_interval(int(request.form["autocomment_interval"]))
                store.set_shared_autocomment_enabled(request.form.get("autocomment_enabled")=="1")
                flash("Общие настройки сохранены.")
            except: flash("Интервалы должны быть числами.","err")
    mode=store.get_mode()
    body="<h2>Основной режим</h2><div class='card'><div class='tabs'><form method='post'><input type='hidden' name='mode' value='shared'><button class='%s'>🌐 Общий</button></form><form method='post'><input type='hidden' name='mode' value='personal'><button class='%s'>👤 Личный</button></form></div><b>%s</b><p class='muted'>%s</p></div>"%("ghost" if mode!="shared" else "","ghost" if mode!="personal" else "", "🌐 Сейчас работает общий режим" if mode=="shared" else "👤 Сейчас работает личный режим", "Все аккаунты используют одни и те же группы, интервалы и ИИ-промт." if mode=="shared" else "Каждый аккаунт использует свои группы, интервалы и свой ИИ-промт.")
    if mode=="shared":
        body+="<div class='card'><form method='post'><input type='hidden' name='save_shared' value='1'><h2 style='margin-top:0'>Общие настройки</h2><label>Общий ИИ-промт</label><textarea name='persona'>%s</textarea><br><br><label>Ответы на сообщения: <input type='number' min='1' name='chat_interval' value='%s'></label><br><br><label>Автокомментарии: <input type='number' min='1' name='autocomment_interval' value='%s'></label><br><br><label><input type='checkbox' name='autocomment_enabled' value='1' %s style='width:auto'> Автокомментинг включён</label><br><br><button>💾 Сохранить</button></form></div><h2>Общие группы</h2>%s<div class='card'><form method='post' action='/shared/groups/add'><input name='chat_id' placeholder='ID группы' required><br><br><input name='username' placeholder='username (необязательно)'><br><br><input name='title' placeholder='Название'><br><br><button>Добавить группу</button></form></div>"%(store.get_shared_persona(""),store.get_shared_chat_interval(),store.get_shared_autocomment_interval(),"checked" if store.shared_autocomment_enabled() else "",group_rows(store.list_shared_groups(),"/shared"))
    else: body+="<div class='card'><b>Личные настройки находятся во вкладке «Аккаунты».</b><p class='muted'>Для каждого аккаунта там можно отдельно задать группы, интервалы и промт.</p></div>"
    return page("Режимы",body,"home")

@app.route("/shared/groups/add",methods=["POST"])
@login_required
def shared_add():
    store.add_shared_group(int(request.form["chat_id"]),request.form.get("username") or None,request.form.get("title") or None); return redirect("/")
@app.route("/shared/groups/remove",methods=["POST"])
@login_required
def shared_remove():
    store.remove_shared_group(int(request.form["chat_id"])); return redirect("/")

@app.route("/accounts")
@login_required
def accounts_page():
    cards=""
    for i,cfg in enumerate(CONFIGS,1):
        rt=RUNTIME.get(cfg.key,{}); status=rt.get("status","stopped"); configured=bool(cfg.api_id and cfg.api_hash and cfg.session)
        cards+="<div class='card'><div class='row'><div><b>%s. %s</b><div class='muted'>%s · Telegram: %s</div></div><form method='post' action='/account/%s/%s'><button class='%s'>%s</button></form></div><div class='actions' style='margin-top:10px'><a href='/account/%s'><button class='ghost'>⚙ Личные настройки</button></a><a href='/account/%s/groups'><button class='ghost'>📋 Группы</button></a></div>%s</div>"%(i,cfg.name,"🟢 работает" if status=="running" else "⚪ остановлен","настроен" if configured else "не настроен",cfg.key,"stop" if status=="running" else "start","danger" if status=="running" else "","⏹ Остановить" if status=="running" else "▶ Запустить",cfg.key,cfg.key,("<div class='muted' style='margin-top:8px'>Ошибка: %s</div>"%rt.get("error") if status=="error" else ""))
    return page("Аккаунты","<h2>Все аккаунты</h2>"+cards,"accounts")

@app.route("/account/<key>",methods=["GET","POST"])
@login_required
def account_page(key):
    cfg=next((x for x in CONFIGS if x.key==key),None)
    if not cfg:return "Not found",404
    if request.method=="POST":
        p=request.form.get("persona","").strip()
        if p: store.set_persona(key,p)
        try: store.set_chat_interval(key,int(request.form["chat_interval"])); store.set_autocomment_interval(key,int(request.form["autocomment_interval"]))
        except: flash("Интервалы должны быть числами.","err")
        store.set_autocomment_enabled(key,request.form.get("autocomment_enabled")=="1"); flash("Личные настройки сохранены.")
        return redirect("/account/"+key)
    running=RUNTIME.get(key,{}).get("status")=="running"
    body="<h2>%s — личная настройка</h2><div class='card'><form method='post'><label>Личный ИИ-промт</label><textarea name='persona'>%s</textarea><p class='muted'>Используется только в режиме «Личный».</p><br><label>Ответы на сообщения: <input name='chat_interval' type='number' min='1' value='%s'></label><br><br><label>Автокомментарии: <input name='autocomment_interval' type='number' min='1' value='%s'></label><br><br><label><input name='autocomment_enabled' type='checkbox' value='1' %s style='width:auto'> Автокомментинг включён</label><br><br><button>💾 Сохранить</button></form></div><div class='card'><div class='row'><b>Состояние аккаунта</b><form method='post' action='/account/%s/%s'><button>%s</button></form></div></div>"%(cfg.name,store.get_persona(key,cfg.persona),store.get_chat_interval(key),store.get_autocomment_interval(key),"checked" if store.is_autocomment_enabled(key) else "",key,"stop" if running else "start","⏹ Остановить" if running else "▶ Запустить")
    return page(cfg.name,body,"accounts")

@app.route("/account/<key>/<action>",methods=["POST"])
@login_required
def account_action(key,action):
    if key not in RUNTIME:return "Not found",404
    if action not in ("start","stop"):return "Bad action",400
    ok,msg=run_async(START_ACCOUNT(key) if action=="start" else STOP_ACCOUNT(key))
    if ok: store.set_enabled(key,action=="start")
    else: flash(msg,"err")
    return redirect("/accounts")

@app.route("/account/<key>/groups")
@login_required
def account_groups(key):
    cfg=next((x for x in CONFIGS if x.key==key),None)
    if not cfg:return "Not found",404
    body="<h2>%s — личные группы</h2>%s<div class='card'><form method='post' action='/account/%s/groups/add'><input name='chat_id' placeholder='ID группы' required><br><br><input name='username' placeholder='username (необязательно)'><br><br><input name='title' placeholder='Название'><br><br><button>Добавить группу</button></form></div>"%(cfg.name,group_rows(store.list_groups(key),"/account/"+key),key)
    return page("Группы",body,"accounts")
@app.route("/account/<key>/groups/add",methods=["POST"])
@login_required
def group_add(key):
    store.add_group(key,int(request.form["chat_id"]),request.form.get("username") or None,request.form.get("title") or None); return redirect("/account/"+key+"/groups")
@app.route("/account/<key>/groups/remove",methods=["POST"])
@login_required
def group_remove(key):
    store.remove_group(key,int(request.form["chat_id"])); return redirect("/account/"+key+"/groups")

@app.route("/admins",methods=["GET","POST"])
@login_required
def admins():
    if request.method=="POST":
        u=request.form.get("username","").strip(); p=request.form.get("password","")
        if auth.create_user(u,p): flash("Администратор %s создан."%u)
        else: flash("Не удалось создать: логин уже существует или пароль короче 6 символов.","err")
    cards=""
    for u in auth.list_users():
        if u==session.get("username"): cards+="<div class='card'><div class='row'><b>👤 %s</b><span class='muted'>текущий</span></div></div>"%u
        else: cards+="<div class='card'><div class='row'><b>👤 %s</b><form method='post' action='/admins/delete'><input type='hidden' name='username' value='%s'><button class='danger'>Удалить</button></form></div></div>"%(u,u)
    body="<h2>Доступ в админку</h2><div class='card'><form method='post'><input name='username' placeholder='Новый логин' required><br><br><input name='password' type='password' placeholder='Пароль, минимум 6 символов' required><br><br><button>➕ Создать администратора</button></form></div>"+cards
    return page("Доступ",body,"admins")
@app.route("/admins/delete",methods=["POST"])
@login_required
def admin_delete():
    u=request.form.get("username","")
    if u==session.get("username"): flash("Нельзя удалить текущего администратора.","err")
    elif auth.delete_user(u): flash("Администратор удалён.")
    else: flash("Нельзя удалить последнего администратора.","err")
    return redirect("/admins")

def run_panel(): app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")),threaded=True)
