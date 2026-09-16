# 16 Accounts — Common / Personal mode

## What changed
- `Группы` now contains a real **Общий режим / Личный режим** switch.
- In **Общий** mode all accounts use the same shared group list and the same shared AI prompt.
- Shared reply interval is configurable; default is `1`, meaning one response per qualifying incoming message for each enabled account.
- Shared groups can be toggled on/off and removed.
- Personal mode keeps each account's own groups, prompt and intervals.
- Each account page still has its own **Автообнаружение групп**.
- Gemini supports **7 rotating keys**: `GEMINI_API_KEY_1` ... `GEMINI_API_KEY_7`. Legacy `GEMINI_API_KEY` is accepted as a fallback/extra key.
- Telegram startup is non-interactive: the service never asks Railway for a phone number. A missing/invalid session marks that account as an error instead of crashing the whole process.

## Important
Do not commit Telegram session strings or Gemini keys to GitHub. Put them only in Railway variables.
