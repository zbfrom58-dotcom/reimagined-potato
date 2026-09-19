#!/usr/bin/env python3
"""
Патч интерфейса «Жалобы»: несколько аккаунтов + очередь.
Запускать из корня reimagined-potato:
    python apply_report_queue_patch.py
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web_panel.py"
ACTIONS = ROOT / "telegram_actions.py"

if not WEB.exists() or not ACTIONS.exists():
    raise SystemExit("Запусти скрипт из корня reimagined-potato.")

web = WEB.read_text(encoding="utf-8")
actions = ACTIONS.read_text(encoding="utf-8")

old_imports = "\n".join([
    "    InputReportReasonSpam,",
    "    InputReportReasonFake,",
    "    InputReportReasonViolence,",
    "    InputReportReasonIllegalDrugs,",
    "    InputReportReasonOther,",
]) + "\n"

new_imports = "\n".join([
    "    InputReportReasonSpam,",
    "    InputReportReasonFake,",
    "    InputReportReasonViolence,",
    "    InputReportReasonIllegalDrugs,",
    "    InputReportReasonOther,",
    "    InputReportReasonChildAbuse,",
    "    InputReportReasonPornography,",
    "    InputReportReasonCopyright,",
    "    InputReportReasonPersonalDetails,",
]) + "\n"

if "InputReportReasonChildAbuse" not in actions:
    if old_imports not in actions:
        raise SystemExit("Не найден блок импортов ReportReason.")
    actions = actions.replace(old_imports, new_imports, 1)

old_mapping = "\n".join([
    "REPORT_REASON_TYPES = {",
    '    "Спам": InputReportReasonSpam,',
    '    "Мошенничество": InputReportReasonFake,',
    '    "Насилие": InputReportReasonViolence,',
    '    "Незаконный контент": InputReportReasonIllegalDrugs,',
    '    "Другое": InputReportReasonOther,',
    "}",
])

new_mapping = "\n".join([
    "REPORT_REASON_TYPES = {",
    '    "Не нравится": InputReportReasonOther,',
    '    "Жестокое обращение с детьми": InputReportReasonChildAbuse,',
    '    "Насилие": InputReportReasonViolence,',
    '    "Незаконные товары и услуги": InputReportReasonOther,',
    '    "Порнографические материалы": InputReportReasonPornography,',
    '    "Персональные данные": InputReportReasonPersonalDetails,',
    '    "Мошенничество": InputReportReasonFake,',
    '    "Нарушение авторских прав": InputReportReasonCopyright,',
    '    "Спам": InputReportReasonSpam,',
    '    "Другое": InputReportReasonOther,',
    '    "Не нарушает закон, но надо удалить": InputReportReasonOther,',
    '    "Другое: добавить ID обращения": InputReportReasonOther,',
    "}",
])

if old_mapping in actions:
    actions = actions.replace(old_mapping, new_mapping, 1)
elif new_mapping not in actions:
    raise SystemExit("Не найден REPORT_REASON_TYPES.")

start = web.index("REPORT_REASONS = {")
end = web.index("@app.route('/reactions'", start)

new_block = r"""REPORT_REASONS = [
    "Не нравится",
    "Жестокое обращение с детьми",
    "Насилие",
    "Незаконные товары и услуги",
    "Порнографические материалы",
    "Персональные данные",
    "Мошенничество",
    "Нарушение авторских прав",
    "Спам",
    "Другое",
    "Не нарушает закон, но надо удалить",
    "Другое: добавить ID обращения",
]

@app.route('/reports', methods=['GET', 'POST'])
@login_required
def reports_page():
    from flask import session

    flash = ''
    action = request.form.get('queue_action', '').strip() if request.method == 'POST' else ''

    if request.method == 'POST' and action == 'start_queue':
        username = request.form.get('username', '').strip()
        reason = request.form.get('reason', '').strip()
        comment = request.form.get('comment', '').strip()
        selected_accounts = request.form.getlist('accounts')

        if username and not username.startswith('@'):
            username = '@' + username

        valid_accounts = {cfg.key for cfg in CONFIGS}
        selected_accounts = [a for a in selected_accounts if a in valid_accounts]

        if not username or reason not in REPORT_REASONS or not selected_accounts:
            flash = "<div class='flash err'>Укажи @username, причину и выбери хотя бы один аккаунт.</div>"
        else:
            session['report_queue'] = selected_accounts
            session['report_queue_index'] = 0
            session['report_form'] = {
                'username': username,
                'reason': reason,
                'comment': comment,
            }
            flash = (
                f"<div class='flash'>✅ Очередь создана: {len(selected_accounts)} "
                f"аккаунт(а/ов). Ниже доступна ручная отправка для текущего аккаунта.</div>"
            )

    elif request.method == 'POST' and action == 'send_current':
        queue = session.get('report_queue', [])
        idx = int(session.get('report_queue_index', 0))
        form_data = session.get('report_form', {})

        if not queue or idx >= len(queue) or not form_data:
            flash = "<div class='flash err'>Очередь пуста. Создай её заново.</div>"
        else:
            account_key = queue[idx]
            username = form_data.get('username', '')
            reason = form_data.get('reason', '')
            comment = form_data.get('comment', '')

            try:
                from telegram_actions import run_single_report
                result = run_async(
                    run_single_report(
                        username, reason, comment,
                        account_key, RUNTIME, START_ACCOUNT
                    ),
                    timeout=60,
                )

                actions_store.add({
                    'type': 'report',
                    'username': username,
                    'reason': reason,
                    'subreason': comment,
                    'count': 1,
                    'results': [result],
                })

                if result.get('ok'):
                    flash = (
                        f"<div class='flash'>✅ {account_key}: жалоба отправлена. "
                        f"Можно перейти к следующему аккаунту.</div>"
                    )
                else:
                    flash = (
                        f"<div class='flash err'>❌ {account_key}: "
                        f"{result.get('message', 'неизвестная ошибка')}</div>"
                    )

                session['report_queue_index'] = idx + 1

            except Exception as e:
                actions_store.add({
                    'type': 'report',
                    'username': username,
                    'reason': reason,
                    'subreason': comment,
                    'count': 1,
                    'results': [{
                        'account': account_key,
                        'ok': False,
                        'message': f'{type(e).__name__}: {e}',
                    }],
                })
                flash = (
                    f"<div class='flash err'>❌ {account_key}: "
                    f"{type(e).__name__}: {e}</div>"
                )

    elif request.method == 'POST' and action == 'reset_queue':
        session.pop('report_queue', None)
        session.pop('report_queue_index', None)
        flash = "<div class='flash'>Очередь сброшена. Данные формы сохранены.</div>"

    form_data = session.get('report_form', {})
    username_value = form_data.get('username', '')
    reason_value = form_data.get('reason', '')
    comment_value = form_data.get('comment', '')

    queue = session.get('report_queue', [])
    idx = int(session.get('report_queue_index', 0))
    queue_active = bool(queue) and idx < len(queue)
    current_account = queue[idx] if queue_active else ''

    if queue and idx >= len(queue):
        queue_status = (
            "<div class='flash'>🏁 Очередь закончена. Все выбранные аккаунты обработаны. "
            "Форма сохранена — можно создать новую очередь.</div>"
        )
    elif queue_active:
        queue_status = (
            f"<div class='card' style='margin-bottom:12px'>"
            f"<b>Очередь: {idx + 1} / {len(queue)}</b>"
            f"<div class='muted' style='margin-top:6px'>"
            f"Текущий аккаунт: <b>{current_account}</b></div>"
            f"</div>"
        )
    else:
        queue_status = ""

    items = [x for x in actions_store.list_items(40) if x.get('type') == 'report']
    if not items:
        history = "<div class='card'><div class='muted'>История жалоб пока пустая.</div></div>"
    else:
        blocks = []
        for item in items:
            accounts_html = ''.join(
                f"<div>{r.get('account')}: {'🟢' if r.get('ok') else '🔴'} "
                f"{r.get('message','')}</div>"
                for r in item.get('results', [])
            )
            detail = item.get('subreason', '')
            detail_html = (
                f"<div class='muted' style='margin-top:6px'>Комментарий: {detail}</div>"
                if detail else ''
            )
            blocks.append(
                f"<div class='card'><div class='row'>"
                f"<b>{item.get('username','')}</b>"
                f"<span class='pill'>{item.get('reason','')}</span></div>"
                f"{detail_html}"
                f"<div class='muted' style='margin-top:6px'>"
                f"{item.get('created_at','')}</div>"
                f"<details style='margin-top:10px'><summary>Результат</summary>"
                f"<div style='margin-top:8px'>{accounts_html}</div></details></div>"
            )
        history = ''.join(blocks)

    reason_options = ''.join(
        f"<option value='{r}' {'selected' if r == reason_value else ''}>{r}</option>"
        for r in REPORT_REASONS
    )

    account_options = []
    for i, cfg in enumerate(CONFIGS, 1):
        checked = " checked" if cfg.key in queue else ""
        status = (
            '🟢 запущен'
            if RUNTIME.get(cfg.key, {}).get('status') == 'running'
            else '⚪ не запущен'
        )
        account_options.append(
            f"<label class='card' style='display:flex;gap:10px;align-items:center;"
            f"padding:10px 12px;margin-bottom:7px;cursor:pointer'>"
            f"<input type='checkbox' name='accounts' value='{cfg.key}'{checked} "
            f"style='width:auto'>"
            f"<span><b>{i}. {cfg.name}</b>"
            f"<span class='muted' style='display:block'>{status}</span></span></label>"
        )

    send_button = ""
    if queue_active:
        send_button = (
            f"<form method='post' style='margin-top:10px'>"
            f"<input type='hidden' name='queue_action' value='send_current'>"
            f"<button style='width:100%;padding:13px'>"
            f"🚩 Отправить от {current_account}</button></form>"
        )

    reset_button = (
        f"<form method='post' style='margin-top:8px'>"
        f"<input type='hidden' name='queue_action' value='reset_queue'>"
        f"<button type='submit' style='width:100%;padding:10px'>"
        f"🔄 Сбросить очередь</button></form>"
        if queue else ""
    )

    body = (
        f"<h2>🚩 Жалоба</h2>"
        f"{flash}{queue_status}"
        f"<div class='card'><form method='post'>"
        f"<input type='hidden' name='queue_action' value='start_queue'>"
        f"<h2 style='margin-top:0'>1. Кому</h2>"
        f"<input name='username' value='{username_value}' placeholder='@username' "
        f"autocomplete='off' required>"
        f"<h2>2. Причина</h2>"
        f"<select name='reason' required style='background:var(--card2);"
        f"border:1px solid var(--border);border-radius:8px;color:var(--text);"
        f"padding:9px;width:100%'>"
        f"<option value=''>Выбери причину</option>{reason_options}</select>"
        f"<h2>3. Аккаунты</h2>"
        f"<div>{''.join(account_options)}</div>"
        f"<h2>Комментарий <span class='muted'>(необязательно)</span></h2>"
        f"<input name='comment' value='{comment_value}' "
        f"placeholder='Можно оставить пустым' autocomplete='off'>"
        f"<br><br><button style='width:100%;padding:12px'>"
        f"▶ Создать очередь</button>"
        f"</form>"
        f"{send_button}{reset_button}"
        f"<p class='muted' style='margin-bottom:0;margin-top:12px'>"
        f"Ссылка/причина/комментарий сохраняются. Выбранные аккаунты обрабатываются "
        f"по очереди, и отправка для каждого аккаунта требует отдельного нажатия."
        f"</p></div>"
        f"<h2>История жалоб</h2>{history}"
    )
    return page('Жалобы', body, active='reports')

"""

web = web[:start] + new_block + web[end:]

WEB.write_text(web, encoding="utf-8")
ACTIONS.write_text(actions, encoding="utf-8")
print("Готово: интерфейс жалоб обновлён.")
