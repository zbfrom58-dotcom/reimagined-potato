"""
Запускается ОДИН РАЗ локально на вашем компьютере (не на Railway!),
чтобы залогиниться в ваш аккаунт и получить строку сессии.

Как использовать:
1. pip install telethon
2. Получите api_id и api_hash на https://my.telegram.org (Api Development Tools)
3. python generate_session.py
4. Введите api_id, api_hash, номер телефона, код из Telegram (и пароль 2FA, если включён)
5. Скрипт выведет длинную строку — это SESSION_STRING.
   Скопируйте её и вставьте в переменные окружения Railway (SESSION_STRING).

Строку сессии НИКОМУ не показывайте — это равнозначно доступу к вашему аккаунту.
"""

from telethon import TelegramClient
from telethon.sessions import StringSession


def main():
    print("=== Генерация сессии для юзербота ===\n")
    api_id = int(input("Введите api_id (с my.telegram.org): ").strip())
    api_hash = input("Введите api_hash (с my.telegram.org): ").strip()

    with TelegramClient(StringSession(), api_id, api_hash) as client:
        session_string = client.session.save()
        print("\n✅ Готово! Ваша строка сессии:\n")
        print(session_string)
        print("\nСохраните её в переменную окружения SESSION_STRING на Railway.")
        print("Также сохраните api_id и api_hash — они понадобятся в переменных API_ID и API_HASH.")


if __name__ == "__main__":
    main()
