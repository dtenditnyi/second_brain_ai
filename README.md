Second Brain AI

Second Brain AI is a personal workspace combining an Obsidian-style knowledge base, a Kanban task tracker, and a local AI assistant based on RAG (Retrieval-Augmented Generation).

The project is focused on complete privacy: the artificial intelligence runs locally on your hardware, analyzes your synchronized Markdown notes, and answers questions strictly based on your personal knowledge base without sending any data to external servers.

Key Features:
- Local AI Assistant: Built on LlamaIndex and ChromaDB. Connects to Ollama (supporting Llama 3 and Phi 3 models) for autonomous offline operation.
- Obsidian Synchronization: Secure connection to private GitHub repositories using Personal Access Tokens (PAT). Tokens are encrypted in the database using the AES-128 algorithm (via the cryptography/Fernet library).
- Note Viewer: Fast navigation through Markdown files without page reloads (SPA). Fully supports Obsidian WikiLinks ([[Note Title]]) and automatic Backlinks generation.
- Task Manager: Kanban task board with To Do, In Progress, and Done statuses, featuring priority and tag filtering.
- Themes: Responsive interface supporting both dark and light themes, along with customizable accent colors.
- Multi-Tenant Architecture: Each account is isolated at the database level, has its own settings, and gets a personal directory for storing notes.

Tech Stack:
- Backend: Python, Django, PostgreSQL (Docker) / SQLite copy for local runs
- AI Components: LlamaIndex, ChromaDB, Ollama (local LLMs and embeddings)
- Frontend: HTML5, Vanilla JavaScript, Tailwind CSS v4 CLI
- Security: python-dotenv for environment variables, cryptography for DB token encryption

Prerequisites:
To run the project, you need:
1. Python 3.10 or higher
2. Node.js (for compiling Tailwind CSS v4 styles)
3. Ollama with downloaded models

Before starting the application, run the following commands in your terminal:
ollama run llama3
or
ollama run phi3

Note: the BAAI/bge-small-en-v1.5 embedding model (HuggingFace) downloads automatically on the first chat request.

Installation and Setup:

1. Clone the repository and navigate to the working directory:
git clone https://github.com/yourusername/second_brain_ai.git
cd second_brain_ai/ai_manager

2. Create and activate a virtual environment:
python -m venv venv
For Windows:
venv\Scripts\activate
For Mac/Linux:
source venv/bin/activate

3. Install backend dependencies:
pip install django llama-index llama-index-vector-stores-chroma llama-index-embeddings-ollama llama-index-llms-ollama chromadb gitpython markdown cryptography python-dotenv

4. Optional: copy .env.example to .env in the repository root and fill in your values
(SECRET_KEY, GEMINI_API_KEY, OLLAMA_HOST, ...). Never commit .env.

5. Install frontend dependencies:
npm install

6. Apply database migrations and create a superuser:
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser

Production on a home server (Proxmox VM, Ubuntu 24.04, Docker, Cloudflare Tunnel): see docs/DEPLOY.md
(step-by-step guide in Russian: deploy/install.sh, update.sh, backup.sh, restore.sh, status.sh).
Tasks live in one Obsidian note of your vault: format and rules in docs/TASKS_FORMAT.md.

Running the Application:

The main way to start everything on Windows is start.bat (double-click it, or run it from a terminal
in the repository root). It calls start.ps1, which runs these steps with an OK / FAIL status for each:
1. Environment checks: venv\Scripts\python.exe, Python 3.10+, node/npx. It warns (does not stop) when
   .env is missing or GEMINI_API_KEY / OLLAMA_HOST are not set. The contents of .env are never read or shown.
2. Local database: creates ai_manager\audit_copy_db.sqlite3 from db.sqlite3 if the copy is missing
   (it never overwrites the copy and never touches the original or the production PostgreSQL DB).
3. Optional dependency install (-Install).
4. manage.py check and migrate with ai_manager.settings_local.
5. CSS build (npm run build).
6. Tests on every start: the fast suite by default. If tests fail, the server is not started and the
   path to the log is shown.
7. Django runserver on http://127.0.0.1:8000; the browser opens once the server answers.

Switches (combine freely, e.g. start.bat -FullTests -Watch -Port 8080):
  -Install     pip install -r requirements.txt -r requirements-dev.txt and npm install
  -FullTests   run all tests, including the Playwright browser tests (needs MS Edge)
  -SkipTests   do not run tests
  -Force       start the server even if tests failed (also skips the -Docker confirmation)
  -Port N      port for the server (default 8000)
  -Watch       Tailwind watch (npm run dev) in a separate window
  -Tunnel      cloudflared tunnel to the local server in a separate window
  -Docker      docker compose up --build instead of the local mode (production configuration!)
  -NoBrowser   do not open the browser
  -NoServer    only run the checks and tests

Every run is logged to logs\runs\run_YYYY-MM-DD_HH-mm-ss.log (the last 30 logs are kept) with the
git branch/commit, parameters, step durations, test results and the final OK/FAIL. One line per run
is appended to logs\runs\history.csv. The old run_matrix.bat still works but start.bat is the
recommended way.

Manual start (two terminals, from ai_manager\ with ..\venv):
  ..\venv\Scripts\python.exe manage.py migrate --settings=ai_manager.settings_local
  ..\venv\Scripts\python.exe manage.py runserver --settings=ai_manager.settings_local
  npm run dev

Environment variables (see .env.example; all optional for a local start):
  SECRET_KEY, DEBUG (False unless set to True; local settings always use True)
  OLLAMA_HOST (default http://localhost:11434), OLLAMA_MODEL (default llama3:latest)
  GEMINI_API_KEY
  GEMINI_MODEL_DEFAULT (default gemini-3.5-flash-lite) - everyday chat
  GEMINI_MODEL_SMART (default gemini-3.8-flash) - status report and the "Smart answer" toggle
  GEMINI_FALLBACK_MODELS (default gemini-3.1-flash-lite,gemma-4-31b-it) - tried in order when a model
    hits its quota (HTTP 429 / RESOURCE_EXHAUSTED); in Auto-Hybrid mode Ollama is the last fallback
  CHAT_HISTORY_MESSAGES (default 6) - previous messages sent to the model as conversation memory
  PROMPT_TOKEN_BUDGET_GEMMA / _GEMINI / _LOCAL (default 8000 / 30000 / 6000)
To check which Gemini model IDs your key can use: venv\Scripts\python.exe scripts\list_gemini_models.py

Tests: from ai_manager\ run ..\venv\Scripts\python.exe -m pytest (all) or add -m "not e2e and not responsive"
for the fast part. External services (Gemini, Ollama, GitHub, HuggingFace) are always mocked.

First Run and Indexing:
1. Register an account or log in with the superuser credentials.
2. Navigate to the Settings section.
3. Provide the URL of your private GitHub repository containing your Obsidian notes and your Personal Access Token (PAT).
4. Choose the AI strategy (Auto-Hybrid, Strictly Local or Cloud Only) and save the settings. The token is never shown again; leave the field empty to keep it.
5. Go to the Notes or AI Chat section. The system will automatically clone the repository, start indexing, and create a local vector database in ChromaDB.


Как пользоваться системой (Rounds 3–5)
=====================================

Сайт — это веб-версия вашего хранилища Obsidian: всё, что вы меняете на сайте, сразу становится
коммитом в GitHub-репозиторий хранилища (как obsidian-git на телефоне), и наоборот.

Каждый день
- Главная — «пульт»: поле быстрой записи (Enter → строка во «Входящих»), задачи на сегодня и неделю,
  текущая недельная заметка с открытыми задачами, недавние заметки, вход в ИИ-чат.
- Ctrl+K (⌘K) или «Поиск» в меню — быстрый переход к заметке по названию или alias (нечёткий поиск).
- «Эта неделя» — открыть или создать заметку недели по Template_Weekly в папке текущего семестра
  (имя продолжает ваш ряд: «Fifth week of 2nd year» → «Sixth week …»). Там же календарь недель и
  «Перенести незакрытые задачи» из прошлой недели: сначала показывается дифф, после подтверждения
  в старой заметке задачи становятся [>], в новой — добавляются; один коммит.

Заметки (Notes)
- Слева: дерево папок PARA (сворачивание запоминается), избранное ★, недавние, полнотекстовый поиск
  с подсветкой и фильтрами (папка, тег, «изменена после»), ссылки на страницы «Теги» и «Граф».
- Заметка показывается как в Obsidian: callouts (сворачиваемые), панель свойств frontmatter, таблицы,
  формулы (KaTeX), Mermaid, [[Заметка#Раздел|текст]], встраивания ![[заметка]], ![[заметка#Раздел]],
  ![[картинка.png]] (из «99 - Cache»), Dataview-запросы LIST / TABLE / TASK (упрощённые; сложное —
  с пометкой «Откройте в Obsidian»). Чекбоксы кликабельны: щелчок = коммит в хранилище.
- Справа: обратные ссылки, «упоминания без ссылки», локальный граф (весь граф — отдельная страница).
- ✏️ Edit — редактор с предпросмотром, автосохранением черновика и защитой от конфликтов (если заметку
  тем временем изменили в Obsidian, сайт покажет разницу и спросит, какую версию оставить).

ИИ
- AI Chat: вопросы по заметкам (RAG). Режим «Агент»: ИИ предлагает изменения (дописать, создать,
  переименовать) — сайт показывает дифф, ничего не пишется без «Применить»; любое применение можно
  «Откатить».

Телефон и офлайн
- Сайт устанавливается как приложение (в браузере телефона «Добавить на главный экран»).
- Без сети: открываются недавно просмотренные заметки (только чтение) и появляется плашка «Нет сети»;
  быстрые записи с главной копятся в очереди и отправляются сами, когда сеть вернётся.
- При выходе из аккаунта офлайн-копии заметок удаляются с устройства.

Безопасность
- Settings → «Двухфакторный вход (2FA)»: QR-код для приложения-аутентификатора и 10 резервных кодов.
- На сервере сайт и Obsidian в браузере закрыты Cloudflare Access (код на почту); бот Link2Note и скрипты
  ходят в /api/v1/ по токенам из Settings → API tokens (права по папкам). Пошагово: docs/DEPLOY.md, разделы 12–14.

Когда нужен «настоящий» Obsidian
- Плагины, Canvas, Templater, полный Dataview — Obsidian в браузере (поддомен obsidian.…, docs/DEPLOY.md §14)
  или Obsidian на ПК/телефоне. Все копии синхронизируются через тот же GitHub-репозиторий.
