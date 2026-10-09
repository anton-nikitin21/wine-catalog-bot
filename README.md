# Wine Catalog — Scraper & Telegram Bot

Я разработал парсер каталога с экспортом в CSV, построением графиков и Telegram-интерфейсом.

## Запуск

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python main.py
# Затем задайте TG_BOT_TOKEN и запустите:
python tg_bot.py
```

## Устройство проекта

Версии парсера: `main.py` и `main1.py`. Бот: `tg_bot.py`. Ключ Telegram хранится только в окружении. CSV и журналы исключены. Парсер зависит от текущей HTML-разметки каталога; работоспособность внешнего сервиса при публикации не проверялась.

Я публикую исходный код без локальных паролей, окружений, баз и журналов. Для воспроизведения анализа я указываю необходимые данные и зависимости.

## Автор

Антон Никитин — [anton-nikitin21](https://github.com/anton-nikitin21).
