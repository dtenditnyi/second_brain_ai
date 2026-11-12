# Итог раундов 3–5 (для владельца)

Подробности — `docs/audit/REPORT.md` (Round 3, 4, 5), баги — `docs/BUGS.md`, решения — `docs/audit/DECISIONS.md`.

## Что сделано
- **Round 3** (`feature/round3`): Markdown в ответах ИИ, Core Matrix, логи; **задачи живут в одной заметке Obsidian**
  (`Задачи.md`, формат `docs/TASKS_FORMAT.md`), единый путь записи в хранилище (lock → pull → операция → commit → push, повтор),
  офлайн-очередь; **прод**: Dockerfile, compose (db, web, scheduler, tunnel), скрипты `deploy/`, инструкция `docs/DEPLOY.md`.
- **Round 4** (`feature/round4`): редактор заметок (CodeMirror, конфликты, офлайн, переименование со ссылками),
  ИИ-агент (Gemini / Ollama / Claude, изменения только после «Применить», откат), **REST API `/api/v1/` по контракту Link2Note**.
- **Round 5** (`feature/round5`): веб-версия хранилища (дерево, Ctrl+K, поиск, теги, обратные ссылки, граф, рендер как в Obsidian,
  Dataview-lite), «Эта неделя» + перенос задач + календарь, главная-пульт, PWA (офлайн-чтение, офлайн-захват), 2FA (TOTP),
  Obsidian в браузере (compose-профиль `obsidian`), инструкции по Cloudflare Access. Сквозной e2e-тест всего пути владельца.
- Безопасность/данные в последнем сеансе: ссылки-симлинки больше не выводят за пределы хранилища; цепочка офлайн-сохранений,
  конфликт-копии в одну минуту, повтор после таймаута push (без « (2)»), удаление/переименование с проверкой версии.

## Проверено вживую
- Бот Link2Note (`scripts/check_second_brain_api.py --all`) против локального сайта на копии БД и тестовом хранилище:
  **18 из 18 ✅**, история git чистая, повтор с тем же `Idempotency-Key` дублей не создал (`round5/LINK2NOTE_CHECK.md`).
- Все тесты (unit, контракт, e2e в Edge, адаптивность) — итог в `docs/audit/round5/test-run.txt`.

## Не проверено вживую
- Docker на этом ПК не был запущен: прод-образ, `/healthz/` в контейнере, контейнер бота (`api-health`), контейнер `obsidian`.
- Настоящий GitHub-репозиторий хранилища, настоящие ответы Gemini/Claude, политики Cloudflare Access, установка PWA на телефон.

## Шаги владельца (по порядку)
1. **Слияние.** Ветки идут цепочкой `feature/round3` → `feature/round4` → `feature/round5`, поэтому достаточно слить
   `feature/round5` в `main` (PR на GitHub или `git checkout main && git merge feature/round5 && git push`).
   Репозиторий переехал: обновите адрес — `git remote set-url origin https://github.com/dtenditnyi/second_brain_ai.git`.
2. **Деплой** на сервер — `docs/DEPLOY.md` §1–5: VM Ubuntu, `.env` (`SECRET_KEY`, `POSTGRES_PASSWORD`, `CLOUDFLARE_TUNNEL_TOKEN`,
   `GEMINI_API_KEY`, по желанию `ANTHROPIC_API_KEY`, `OLLAMA_HOST`), `bash deploy/install.sh`, туннель → `http://web:8000`.
   Перенос данных со старого ПК — §8. Затем в Настройках: URL хранилища + fine-grained PAT (Contents: Read and write).
3. **Защита** — §13: Cloudflare Access (одноразовый код на почту) для сайта и поддомена Obsidian, правило **Bypass** для `/api/v1/`;
   на сайте Настройки → 2FA (QR, сохранить резервные коды). Obsidian в браузере — §14 (`docker compose --profile obsidian up -d obsidian`,
   только за Access: внутри контейнера sudo без пароля).
4. **Токен для бота** — §12: Настройки → API-токены → права read, write, delete, ai; write: `03 - Resources/📥 Из ссылок`,
   `05 - Fleeting/📥 Входящие.md`, `01 - Projects/🎯 Цели и планы/Задачи.md`; delete: только `03 - Resources/📥 Из ссылок`.
   Токен показывается один раз → в `.env` бота: `SECOND_BRAIN_API_TOKEN=sb_…`, `SECOND_BRAIN_API_URL=http://secondbrain-web:8000/api/v1`.
5. **Переключение бота**: в `.env` бота `VAULT_BACKEND=api`, перезапуск; проверка —
   `uv run python scripts/check_second_brain_api.py --all` (должно быть 18 ✅) и `python -m digest.admin api-health` → `api: ok`.
   После проверки удалите вручную тестовую задачу «Link2Note contract test» и строку во «Входящих».
6. На этом ПК порт 8765 занят Anki — сайт локально запускайте на 8000 (по умолчанию).
