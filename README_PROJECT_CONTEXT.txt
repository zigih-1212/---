================================================================================
AUTOPOST BOT — ПОЛНЫЙ КОНТЕКСТ ПРОЕКТА (для передачи в организацию)
================================================================================

ВЕРСИЯ: 2026-09-06
СТАТУС: Production-ready, 13 критических багов исправлено, готово к деплою
РЕПОЗИТОРИЙ: https://github.com/zigih-1212/---.git (ветка main)
РАБОЧАЯ ПАПКА: C:\Users\Hewlett Packard\Desktop\router\myproject

---

1. ОБЩЕЕ ОПИСАНИЕ ПРОЕКТА
--------------------------------------------------------------------------------

AutoPost Bot — SaaS-бот для автоматической публикации товарных постов (CPA/CPC)
в Telegram-каналы. Основной use-case: блогеры/вебмастера подключают магазины из
Admitad, бот подбирает товары с ERID, публикует в каналы с партнёрскими ссылками,
собирает статистику кликов/лидов, управляет выплатами.

Ключевые роли:
- SaaS — автопостинг по таймерам/интервалам
- Blogger — принудительный постинг (Force Post) + те же авто-возможности
- Admin — управление пользователями, выплатами, модерация

Технологический стек:
- Python 3.12, aiogram 3.x (Telegram Bot API)
- FastAPI + Jinja2 (веб-панель /my-stats)
- SQLite3 (файловая БД, ~87% диска на Railway)
- Docker (libcairo2-dev для cairosvg: SVG→PNG)
- Railway (хостинг, автодеплой по git push)
- APScheduler (фоновые джобы: публикация каждые 10/15 мин)

---

2. АРХИТЕКТУРА И СТРУКТУРА ФАЙЛОВ
--------------------------------------------------------------------------------

myproject/
├── main.py                    # Точка входа, инициализация БД, планировщик, админ-хендлеры
├── config.py                  # Настройки из env, PAYOUT_FIXED_FEE, MIN_PAYOUT
├── helpers.py                 # Утилиты: генерация текстов, subid2, delivery info
├── keyboards/                 # Клавиатуры бота (saas.py, social.py, admin.py)
├── handlers/
│   ├── saas.py                # Основная логика: CPA/CPC, Force Post, таймеры, магазины
│   ├── social.py              # Подключение каналов, видео-каналы
│   └── admin.py               # Админ-панель
├── services/
│   ├── saas_core.py           # publish_from_catalog(), publish_cpc_campaigns()
│   ├── admitad.py             # STORE_ID_MAP, ADULT_STORES, каталог товаров
│   └── db.py                  # get_db() — SQLite connection pool (один файл)
├── webapp/
│   ├── routes_user.py         # Веб-панель пользователя (/my-stats/*)
│   ├── routes_admin.py        # Админ веб-панель
│   ├── routes_postback.py     # Postback от Admitad (клики/лиды)
│   └── auth.py                # JWT токены для веб-панели
├── utils/feature_flags.py     # Флаги фич
├── stats.py                   # Статистика, графики
├── Dockerfile                 # Python 3.12-slim + libcairo2-dev
├── requirements.txt
└── railway.json (нет, деплой через Dockerfile)

---

3. БАЗА ДАННЫХ (SQLite) — КЛЮЧЕВЫЕ ТАБЛИЦЫ
--------------------------------------------------------------------------------

users
  user_id (PK), telegram_id, role (saas/blogger/admin), tariff_id,
  is_active, cpa_enabled, post_interval_minutes (default 60),
  post_days (bitmask: 1=Пн..64=Вс, default 127=все дни),
  default_auto_delete_hours, auto_pin, notify_posts,
  force_preview_confirmed, min_discount, tax_status,
  commission_rate, cpc_banned, sub_id, product_template, cpc_template,
  cpa_city, cpa_city_id, created_at

channels
  id, user_id, channel_id, channel_title, sub_id, is_active, platform

user_category_preferences
  user_id, category_id, city (для Galaxy Store)

gdeslon_catalog
  id, user_id, source (название магазина), title, price, currency,
  partner_url, image_url, erid, advertiser, discount_percent, old_price,
  used (0/1), source_id, category_id

cpc_campaigns
  id, user_id, campaign_id, name, cpc_link, text, image_url,
  description, rules, more_rules, traffics,
  is_active, interval_hours, interval_minutes, post_days,
  last_posted_at, times_posted

post_schedules          <-- НОВАЯ ТАБЛИЦА (таймеры)
  id, user_id, target_type (store/campaign), target_id,
  post_date, post_time, is_posted

payout_requests
  id, user_id, amount, status (processing/awaiting_receipt/receipt_uploaded/paid/rejected),
  receipt_photo (TEXT — ссылка на lknpd.nalog.ru), created_at

payout_chat
  request_id, sender_role (user/admin), message, created_at

transactions / subid_stats / pinned_posts / referrals / promo_activations /
user_consents / saas_queue / night_queue / admitad_tokens / cyclic_schedules (МЁРТВАЯ)

---

4. БИЗНЕС-ЛОГИКА: CPA vs CPC
--------------------------------------------------------------------------------

CPA (Cost Per Action) — товарные посты из Admitad каталога:
- Пользователь выбирает магазины (категории) в боте/вебке
- Бот синхронизирует каталог (ERID, партнёрские ссылки)
- Публикация: по таймеру (post_schedules) ИЛИ по интервалу (post_interval_minutes)
- Fallback: если нет таймеров — постит из всех выбранных магазинов
- Проверки: минимальная скидка, ERID обязателен, 18+ магазины (Розовый кролик)
- Автоудаление постов, автозакрепление, уведомления пользователю

CPC (Cost Per Click) — рекламные кампании:
- Пользователь создаёт кампанию: название, CPC-ссылка, текст, картинка, правила
- Публикация ТОЛЬКО по таймеру (post_schedules, target_type='campaign')
- Правила модерации: проверка ключевых слов, стоп-слов
- Force Post CPC: публикация без правил (через подтверждение)

Force Post (ручное):
- CPA: выбор типа → предпросмотр товара → публикация во все каналы ИЛИ в конкретный
- CPC: выбор кампании + канала → подтверждение → публикация

---

5. РАСПИСАНИЕ ПУБЛИКАЦИЙ (ЗАМЕНИЛО ЦИКЛИЧЕСКИЙ ПОСТИНГ)
--------------------------------------------------------------------------------

БЫЛО: циклический постинг — interval_days, cyclic_schedules таблица, вкладка "Расписание".
СТАЛО: post_schedules — календарь + время для КАЖДОГО магазина/кампании отдельно.

UI:
- /cpa-stores — страница магазинов, кнопка "⏰ Таймер" → модалка календарь+циферблат
- /cpc-campaigns — страница кампаний, кнопка таймера на каждой
- Сохранение: /save-timer → post_schedules (is_posted=0)
- При публикации: is_posted=1, удаление таймера

Логика в publish_from_catalog():
1. Загружает post_schedules на сегодня (is_posted=0, target_type='store')
2. Есть сработавшие таймеры? → allowed_sources = [best], игнорирует post_interval
3. Нет таймеров? → проверка post_interval от последнего поста
4. post_days bitmask проверяется ДО всего (фикс #12)

publish_cpc_campaigns() — аналогично, но только по таймерам (нет интервального fallback).

---

6. ВЕБ-ПАНЕЛЬ (/my-stats)
--------------------------------------------------------------------------------

Страницы (все с сайдбаром, 7 страниц):
1. /my-stats — дашборд: баланс, графики кликов/лидов, последние транзакции
2. /my-stats/settings — настройки (вкладки: Общие, Видео-каналы, Рефералка)
3. /my-stats/cpa-stores — CPA магазины (галочки, таймеры)
4. /my-stats/cpc-campaigns — CPC кампании (создание, редактирование, таймеры)
5. /my-stats/templates — шаблоны постов (товар, видео, CPC)
6. /my-stats/payouts — заявки на вывод, чат с админом, загрузка чеков
7. /my-stats/guide — "📖 Выплаты" (инструкция по чекам, ОРД, срокам)

Ключевые endpoints:
- GET /settings-data?token= — загрузка настроек (post_interval, post_days, auto_pin, ...)
- POST /save-settings — сохранение (теперь с post_days)
- POST /save-timer — создание таймера
- GET /get-schedules — список таймеров
- POST /delete-schedule — удаление таймера
- POST /toggle-cpa-store — вкл/выкл магазина
- POST /upload-receipt — загрузка чека (текстовая ссылка lknpd.nalog.ru)
- GET /receipt-file — отдача загруженных файлов (с проверкой владельца)

---

7. ВЫПЛАТЫ И НАЛОГИ (СРОЧНО ДЛЯ ADMITAD)
--------------------------------------------------------------------------------

Модель:
- Пользователь накапливает баланс от лидов (Admitad postback)
- Заявка на вывод: кнопка "💸 Вывести" → статус processing
- Админ подтверждает → статус awaiting_receipt
- Пользователь создаёт чек в «Мой Налог» (тип: Продажа физ.лицу, услуга: Рекламные услуги)
- Загружает ССЫЛКУ на чек (lknpd.nalog.ru) через веб-панель
- Статус receipt_uploaded → админ платит → paid

Критические правила:
- Чек ОБЯЗАТЕЛЬНЕН в течение 24 часов после получения перевода
- Без чека — аккаунт БЛОКИРУЕТСЯ НАВСЕГДА, средства аннулируются
- Налоговый статус: Самозанятый/ИП (бизнес) или Физлицо
- Минимальная сумма вывода: MIN_PAYOUT = 3000₽ (config.py:33)
- Комиссия банка: PAYOUT_BANK_PCT = 4.3%

---

8. ИСТОРИЯ ИЗМЕНЕНИЙ (ПОСЛЕДНЯЯ СЕССИЯ — 13 КРИТИЧЕСКИХ ФИКСОВ)
--------------------------------------------------------------------------------

Все фиксы ВНЕСЕНЫ В КОД, компиляция проходит (py_compile OK), НЕ ЗАПУШЕНЫ В GIT.

FIX 1: store_confirm_adult handler (handlers/saas.py:245)
  Кнопка 18+ для Розового кролика не имела обработчика. Добавлен cb_store_confirm_adult.

FIX 2: Receipt upload — файл → текстовая ссылка (webapp/routes_user.py)
  HTML: <input type="url" id="receipt-link"> вместо file input
  JS: отправляет receipt_link, не file
  Endpoint: принимает receipt_link: str = Form(...)

FIX 3: Receipt redirect — пустой token (webapp/routes_user.py:1372)
  token теперь принимается как Form параметр, возвращается JSONResponse.

FIX 4: scheduled_store_id undefined на fallback (services/saas_core.py:321)
  Инициализация None ДО блока таймеров.

FIX 5: best ≠ scheduled_store_id (дубли постов) (services/saas_core.py:361-379)
  Оба вычисляются в одном цикле — указывают на один магазин.

FIX 6: fromisoformat ValueError убивал цикл (services/saas_core.py:350-357)
  try/except ValueError → continue (пропускает пользователя, не падает цикл).

FIX 7: DB connection leak (services/saas_core.py:558-568)
  conn_sched.close() перенесено в finally блок.

FIX 8: Удаление аккаунта — пропущены таблицы (main.py:1208-1221)
  Добавлены cpc_campaigns, post_schedules в _delete_user_data.

FIX 9: Двойной callback.answer в CPC (handlers/saas.py:557, 767)
  Убран первый answer, второй show_alert=True.

FIX 10: /receipt-file security (webapp/routes_user.py:1416)
  Проверка user_id: файл должен быть в user_{user_id}/.

FIX 11: _force_post_immediate игнорировал channel_id (handlers/saas.py:968, 991)
  _publish_product(target_channel_id) фильтрует канал.

FIX 12: post_days не проверялся при публикации (services/saas_core.py:289-296)
  SELECT u.post_days + проверка bitmask перед обработкой пользователя.

FIX 13: post_days UI + save/load (webapp/routes_user.py)
  HTML: чекбоксы дней недели (.day-btn, .post-day)
  CSS: :has(input:checked) стилизация
  JS: loadSettings загружает, saveGeneralSettings отправляет bitmask
  Backend: settings-data возвращает post_days

---

9. ОСТАВШИЕСЯ ПРОБЛЕМЫ (НЕ ИСПРАВЛЕНЫ, ТРЕБУЮТ РЕШЕНИЯ)
--------------------------------------------------------------------------------

[ ] Railway storage 87% — нужен VACUUM (sqlite3 vacuum; или пересоздание БД)
[ ] post_interval_minutes "не сохраняется" (пользователь ставит 40, после релоада 10)
    - Код save/load выглядит корректно
    - Подозрение: браузерный кеш / CDN / старый HTML
    - План: добавить cache: 'no-store' в fetch, или версионирование
[ ] Мёртвая таблица cyclic_schedules — CREATE TABLE + 2 ALTER в main.py (строки 590, 689, 704)
    - Удалить из миграций
[ ] Config naming: PAYOUT_FIXED_FEE vs min_payout (config.py:14,34)
    - Ключ "min_payout" загружается из env PAYOUT_FIXED_FEE
    - Переименовать ключ в "payout_fixed_fee" для ясности
[ ] payout_chat не удаляется при удалении аккаунта (col=None в списке)
    - Нужен DELETE по request_id из payout_requests

---

10. ПРЕЗЕНТАЦИЯ И ПИТЧ ДЛЯ ADMITAD
--------------------------------------------------------------------------------

Gamma.app: https://telegram-k4fgkxw.gamma.site (публичная, финальная)
Письмо готово для:
- welcome@admitad.com
- Nastassia Shkampletava (LinkedIn, BD Admitad)

Продукт должен быть ИДЕАЛЬНЫЙ к моменту ответа Admitad — это Technology Partnership.

---

11. ДЕПЛОЙ И ОПЕРАЦИИ
--------------------------------------------------------------------------------

Локальный запуск:
  python main.py

Docker build:
  docker build -t autopost-bot .
  docker run -d --name autopost -v autopost_data:/app/data autopost-bot

Railway деплой:
  git add -A
  git commit -m "сообщение"
  git push origin main
  # Railway автоматически собирает Dockerfile и деплоит

Переменные окружения (Railway Variables):
  BOT_TOKEN=...
  ADMIN_IDS=...
  ADMITAD_CLIENT_ID=...
  ADMITAD_CLIENT_SECRET=...
  WEBAPP_URL=https://...railway.app
  PAYOUT_FIXED_FEE=35
  PAYOUT_BANK_PCT=0.043
  # ... остальные в config.py

База данных: /app/data/bot.db (volume на Railway)
Бэкап: cp /app/data/bot.db /app/data/bot.db.backup.$(date +%s)

---

12. ТЕКУЩИЕ ЗАДАЧИ (ПРИОРИТЕТНОСТЬ)
--------------------------------------------------------------------------------

P0 (Срочно, до ответа Admitad):
  1. Пуш 13 фиксов на Railway (git push)
  2. Проверить: сохраняется ли post_interval_minutes (40 мин)
  3. VACUUM БД на Railway (storage 87%)

P1 (Важно, после деплоя):
  4. Удалить мёртвую cyclic_schedules из main.py
  5. Исправить config naming (PAYOUT_FIXED_FEE)
  6. Добавить удаление payout_chat при удалении аккаунта

P2 (Техдолг):
  7. Добавить post_days в CPC кампании (сейчас только у пользователя)
  8. Рефакторинг saas_core.py (слишком длинные функции)
  9. Тесты (пока нет ни одного)

---

13. КОНТАКТЫ И ДОСТУПЫ
--------------------------------------------------------------------------------

GitHub: zigih-1212 / ---
Railway: (аккаунт пользователя)
Admitad: partnership pitch sent
Gamma: https://telegram-k4fgkxw.gamma.site

---

14. ИЗВЕСТНЫЕ БАГИ В КОДЕ (НЕ КРИТИЧНЫЕ, НО ЕСТЬ)
--------------------------------------------------------------------------------

- adj() в JS: при клике ▼ на часах 1:00 → post-interval=0 → timeDisplay показывает 1:00 снова (fallback ||60)
- syncFromInput не валидирует ввод пользователя (можно ввести 99 часов)
- CPC post_days в таблице есть, но не используется в publish_cpc_campaigns
- payout_chat DELETE требует JOIN с payout_requests (сложнее простого WHERE user_id)
- Нет линтера/форматтера в CI (black, ruff, mypy не настроены)
- Нет юнит-тестов

---

15. НАВИГАЦИЯ ПО КОДУ (БЫСТРЫЕ ССЫЛКИ)
--------------------------------------------------------------------------------

main.py:266     — publish_from_catalog() планировщик
main.py:640     — publish_cpc_campaigns() планировщик
main.py:1202    — _delete_user_data()
handlers/saas.py:142  — cb_toggle_store (магазины)
handlers/saas.py:245  — cb_store_confirm_adult (FIX 1)
handlers/saas.py:486  — cb_force_type_cpa (Force Post CPA)
handlers/saas.py:492  — cb_force_type_cpc (Force Post CPC)
handlers/saas.py:772  — _force_post_immediate (FIX 11)
handlers/saas.py:968  — _publish_product (FIX 11)
handlers/saas.py:557  — CPC flow (FIX 9)
services/saas_core.py:266 — publish_from_catalog (FIX 5,6,7,12)
services/saas_core.py:640 — publish_cpc_campaigns
services/saas_core.py:558 — schedule update (FIX 4,7)
webapp/routes_user.py:494 — receipt upload HTML (FIX 2)
webapp/routes_user.py:546 — uploadReceipt JS (FIX 2,3)
webapp/routes_user.py:1372 — upload_receipt endpoint (FIX 2,3)
webapp/routes_user.py:1416 — receipt-file endpoint (FIX 10)
webapp/routes_user.py:978 — post_days UI (FIX 13)
webapp/routes_user.py:1126 — loadSettings post_days (FIX 13)
webapp/routes_user.py:1176 — saveGeneralSettings post_days (FIX 13)
webapp/routes_user.py:1468 — settings-data endpoint (FIX 13)
config.py:14,33-35 — PAYOUT_FIXED_FEE / MIN_PAYOUT naming issue

---

ПРИМЕЧАНИЕ: Этот файл создан для передачи контекста в организацию. Он содержит
всё, что известно о проекте на 2026-09-06. При передаче — убедись, что новый
разработчик запустил проект локально, пробил все эндпоинты, и понял схему БД.