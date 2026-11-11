# REST API Second Brain v1

API для Telegram-бота Link2Note и любых своих скриптов. Сайт — единственный, кто пишет в хранилище Obsidian:
каждая запись проходит `git pull → запись → commit → push` с той же проверкой путей, что и редактор сайта.

- Контракт с ботом (главный документ, он важнее этого файла при расхождениях): [`docs/link2note/API_CONTRACT.md`](link2note/API_CONTRACT.md),
  общие файлы — `docs/link2note/contract/url_normalize_cases.json`, `allowed_tags.json` (их проверяют тесты `ai_manager/tests/test_api_contract.py`).
- OpenAPI-схема: `GET /api/v1/schema/` (без токена).
- База: `https://secondbrain-core.com/api/v1` (через Cloudflare) или `http://secondbrain-web:8000/api/v1` (из docker-сети `secondbrain`, так ходит бот).
  Слэш в конце необязателен: `/api/v1/tasks` и `/api/v1/tasks/` — одно и то же.

## 1. Токены и права

Токен создаётся в **Настройки → API tokens**: название, права, срок (необязательно), папки записи/удаления.
Токен показывается **один раз** (в базе хранится только SHA-256), отзывается там же кнопкой **Revoke**.

```http
Authorization: Bearer sb_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

| Право | Что даёт |
|---|---|
| `read` | чтение заметок, папок, задач, `lookup`, `sync` |
| `write` | создание/изменение заметок и задач, захват, применение пакетов агента — только в `write_paths` |
| `delete` | `DELETE /notes/{path}` — только в `delete_paths` |
| `ai` | `POST /ask`, `POST /agent` |

`write_paths` / `delete_paths` — папки или отдельные заметки, по одной на строку. Сравнение по **целым сегментам**:
`03 - Resources/📥 Из ссылок2` не входит в `03 - Resources/📥 Из ссылок`. Пустой список = всё хранилище.
Сессия браузера (cookie) в API не работает — только токен; поэтому CSRF для API не нужен и сессионные
эндпоинты сайта не затронуты.

**Токен для бота Link2Note** (права `read`, `write`, `delete`, `ai`):
- write: `03 - Resources/📥 Из ссылок`, `05 - Fleeting/📥 Входящие.md` (заметка «Входящие», `CAPTURE_INBOX_NOTE`),
  `01 - Projects/🎯 Цели и планы/Задачи.md` (заметка задач из Настроек);
- delete: `03 - Resources/📥 Из ссылок`.

## 2. Общие правила

- **Ошибки** всегда JSON: `{"error": {"code": "forbidden", "message": "…", "retryable": false}}`.
  Коды: `400/422 validation_error`, `401 unauthorized`, `403 forbidden`, `404 not_found`,
  `409 conflict` (+ `current_sha`), `409 in_progress`, `409 idempotency_mismatch`,
  `429 rate_limited` (+ заголовок `Retry-After`), `503 vault_unavailable` / `ai_unavailable` (+ `Retry-After`), `500 internal_error`.
- **Лимит**: `API_RATE_LIMIT_PER_MINUTE` запросов в минуту на токен (по умолчанию 60) → `429` с `Retry-After`.
- **Idempotency-Key** (UUID) принимают все `POST/PUT/PATCH/DELETE`: повтор с тем же ключом и тем же запросом
  (сравнение по смыслу: метод, путь, query, разобранный JSON) возвращает тот же ответ без второй записи
  (заголовок `Idempotent-Replayed: true`); другой запрос с тем же ключом → `409 idempotency_mismatch`;
  пока первый ещё выполняется → `409 in_progress`. Хранятся только окончательные ответы (2xx/4xx) 8 дней;
  `5xx` и `429` не запоминаются — повтор выполнится заново.
- **Версия заметки** `sha` = SHA-256 текста; передаётся в `if_sha` для `PUT`/`PATCH`/`DELETE`.
- **Пути** — от корня хранилища, с `.md`; в URL каждый сегмент percent-encoded. `..`, `\`, `:`, абсолютные пути,
  `.git`, `.obsidian` → `400`.
- **Журнал вызовов** (таблица `ApiCallLog` в базе): метод, путь, код, время — без тел запросов и текста заметок.

## 3. Эндпоинты

| Метод и путь | Право | Назначение |
|---|---|---|
| `GET /health` | — | `{"status": "ok"\|"degraded", "vault_synced_at", "version"}` |
| `GET /sync/` | read | `{"last_sync", "pending", "error", "status"}` |
| `POST /notes` | write | создать из готового Markdown `{folder, name, content}` → `201 {path, name, sha, commit, pushed}`; имя ≤ 120, занято → « (2)» |
| `POST /notes` (без `name`) | write | создать по полям `{folder, title, tags?, template?, moc?, content?}` (frontmatter и `🔗 [[MOC]]` добавит сайт) |
| `GET /notes?folder=&fm.<ключ>=&sort=&limit=` | read | список с фильтром по frontmatter `{"items": [{path, name, title, frontmatter}]}` |
| `GET /notes/?path=…` или `GET /notes/{path}` | read | `{path, name, content, frontmatter, sha}` |
| `GET /notes/lookup?url=` | read | заметки, у которых нормализованный `url:` совпал → `{"items": […]}` (пусто — тоже 200) |
| `GET /notes/search/?q=` | read | поиск по названию, алиасам и тексту `{"results": [{path, name, match}]}` |
| `POST /notes/append/` | write | `{path, text}` — дописать в конец заметки |
| `PATCH /notes/{path}/frontmatter` | write | `{"set": {"status": "read"}, "if_sha"?}` — меняются только эти строки |
| `PUT /notes/{path}` | write | `{content, if_sha}` (if_sha обязателен) |
| `DELETE /notes/{path}?if_sha=` | delete | `204`; файл остаётся в истории git |
| `GET /folders/?path=` | read | `{"folders": […], "notes": […]}` |
| `POST /api/v1/capture/` | write | `{text, target: "inbox"\|"weekly"}` → `201 {path, name, commit, pushed}` |
| `GET /tasks?status=open\|done&due_before=&tag=` | read | `{"items": [{id, text, status, due, priority, tags}]}` |
| `POST /tasks` | write | `{text, due?, priority?: high\|normal\|low, tags?}` → `201` |
| `PATCH /tasks/{id}` | write | `{status?, due?, priority?, text?, tags?}` |
| `DELETE /tasks/{id}` | write | `204` |
| `POST /ask` | ai | `{question, provider?: gemini\|claude\|ollama}` → `{answer_markdown, sources, model}` |
| `POST /agent/` | ai | `{request}` → `{batch_id, changes: [{index, path, kind, diff}], text}` — ничего не пишет |
| `POST /agent/{id}/apply/` | write | применить всё или `{"indices": [0, 2]}` одним коммитом `ai: …` (пути — в `write_paths`) |
| `POST /agent/{id}/reject/`, `/revert/` | write | отклонить / откатить (revert-коммит) |

«Входящие» — одна заметка `CAPTURE_INBOX_NOTE` (по умолчанию `05 - Fleeting/📥 Входящие.md`, создаётся сама),
запись `- ГГГГ-ММ-ДД ЧЧ:ММ — текст` вставляется перед строкой `🔗 [[…]]`. `weekly` — текущая недельная заметка:
в `06 - Daily` заметка с `type: weekly` и самой поздней `date:` не позже сегодняшнего дня.

## 4. Примеры curl

```bash
API=https://secondbrain-core.com/api/v1
TOKEN=sb_...                                   # из Настроек, показывается один раз

curl -s $API/health
curl -s -H "Authorization: Bearer $TOKEN" "$API/tasks?status=open"
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -H "Idempotency-Key: $(uuidgen)" -d '{"text":"сдать лабу","due":"2026-11-13","priority":"high","tags":["university"]}' $API/tasks
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"text":"идея: бот для Anki","target":"inbox"}' $API/capture/
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"question":"что я знаю про Docker?"}' $API/ask
curl -s -H "Authorization: Bearer $TOKEN" "$API/notes/lookup?url=https%3A%2F%2Fyoutu.be%2FdQw4w9WgXcQ"
```

Если пришёл `429` — подождать `Retry-After` секунд; `503` — хранилище занято/офлайн, повторить позже с тем же
`Idempotency-Key`.

## 5. Пример минимального бота (aiogram 3)

Полноценный бот — отдельный проект Link2Note; здесь — минимальный пример для своих экспериментов:
`/task текст` → задача, `/note текст` → во «Входящие», `/ask вопрос` → ответ ИИ, обычный текст → во «Входящие».

```python
import os, uuid
import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

API = os.environ["SECOND_BRAIN_API_URL"]          # например http://secondbrain-web:8000/api/v1
HEADERS = {"Authorization": f"Bearer {os.environ['SECOND_BRAIN_API_TOKEN']}"}
OWNER_ID = int(os.environ["OWNER_TELEGRAM_ID"])    # бот отвечает только владельцу
dp = Dispatcher()


async def call(method, path, payload=None):
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.request(method, API + path, json=payload,
                                 headers={**HEADERS, "Idempotency-Key": str(uuid.uuid4())})
    if r.status_code == 429:
        return f"Подождите {r.headers.get('Retry-After', '60')} с."
    if r.status_code >= 400:
        return "Ошибка: " + r.json()["error"]["message"]
    return r.json() if r.content else {}


@dp.message(Command("task"), F.from_user.id == OWNER_ID)
async def task(message: Message):
    data = await call("POST", "/tasks", {"text": message.text.partition(" ")[2]})
    await message.answer(data if isinstance(data, str) else f"✅ Задача {data['id']} добавлена")


@dp.message(Command("note"), F.from_user.id == OWNER_ID)
async def note(message: Message):
    data = await call("POST", "/capture/", {"text": message.text.partition(" ")[2], "target": "inbox"})
    await message.answer(data if isinstance(data, str) else "📥 Во «Входящих»")


@dp.message(Command("ask"), F.from_user.id == OWNER_ID)
async def ask(message: Message):
    data = await call("POST", "/ask", {"question": message.text.partition(" ")[2]})
    await message.answer(data if isinstance(data, str) else data["answer_markdown"][:4000])


@dp.message(F.text, F.from_user.id == OWNER_ID)
async def inbox(message: Message):
    data = await call("POST", "/capture/", {"text": message.text, "target": "inbox"})
    await message.answer(data if isinstance(data, str) else "📥 Сохранено")


if __name__ == "__main__":
    import asyncio
    asyncio.run(dp.start_polling(Bot(os.environ["TELEGRAM_BOT_TOKEN"])))
```

## 6. Проверка сайта скриптом бота

В репозитории Link2Note есть живая проверка контракта (создаёт и удаляет тестовую заметку в папке бота):

```bash
export SECOND_BRAIN_API_URL=https://secondbrain-core.com/api/v1     # или http://secondbrain-web:8000/api/v1 из docker-сети
export SECOND_BRAIN_API_TOKEN=sb_...                                # токен бота из Настроек
python scripts/check_second_brain_api.py          # заметки, идемпотентность, lookup, PATCH/PUT/DELETE, 403/422/409
python scripts/check_second_brain_api.py --all    # + задачи, захват, /ask
```
