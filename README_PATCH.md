# Patch: universal Telegram message reaction links

Replace `telegram_actions.py` in the repository with the included file.

Supported reaction links include:
- `https://t.me/interffacts/322`
- `https://t.me/penzainform/18431?comment=377417`
- `https://t.me/c/2559865477/8450229`
- private/public thread-form message links documented by Telegram

For `?comment=...`, the patch resolves the linked discussion group from the channel post and sends the reaction to the comment message there.

No dependency changes are required.
