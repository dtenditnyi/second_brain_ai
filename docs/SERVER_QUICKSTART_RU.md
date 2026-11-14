# Перенос на домашний сервер — по шагам (Second Brain + Link2Note)

Подробности и объяснения — `docs/DEPLOY.md`. Здесь — только команды по порядку под мою сеть:
- Proxmox (мини-ПК): **192.168.1.200**, веб-панель `https://192.168.1.200:8006`
- ПК с Ollama: IP узнать `ipconfig` (лучше закрепить в роутере, например `192.168.1.150`)
- VM Ubuntu Server: IP — в Proxmox (шаг 2)

---

## 1. На ПК (PowerShell)

### 1.1 Закоммитить и слить всё в `main`
```powershell
cd C:\Users\dania\Desktop\Projects\second_brain_ai
git add -A ai_manager docs deploy
git update-index --chmod=+x deploy/update-all.sh
git commit -m "fix: normalize OLLAMA_HOST bind address (B-73); server quickstart, update-all.sh"
git push
git checkout main
git pull
git merge --no-ff feature/round5 -m "Merge rounds 3-5"
git push origin main
git checkout feature/round5
```
(Link2Note уже в `main`.)

### 1.2 Открыть Ollama для сервера
Проверь, что Ollama слушает всю сеть: `netstat -ano | findstr :11434` должно показать `0.0.0.0:11434`. Если там `127.0.0.1:11434` — Параметры Windows → «Переменные среды» → пользовательская переменная `OLLAMA_HOST` = `0.0.0.0`, затем перезапусти Ollama (значок в трее → Quit → открыть снова). Потом разреши порт в брандмауэре — **PowerShell от имени администратора**:
```powershell
New-NetFirewallRule -DisplayName "Ollama 11434 (LAN)" -Direction Inbound -Protocol TCP -LocalPort 11434 -RemoteAddress 192.168.1.0/24 -Action Allow
ipconfig | findstr IPv4
```
Запомни IPv4 ПК (`192.168.1.x`) — это `<IP-ПК>`. Проверка с телефона в той же Wi-Fi: `http://<IP-ПК>:11434/api/tags` → список моделей.

### 1.3 Что взять с собой из `.env` ПК
Открой `second_brain_ai\.env` в блокноте и скопируй **только** `GEMINI_API_KEY` (и `ANTHROPIC_API_KEY`, если есть). Остальное на сервере будет новым.

---

## 2. Proxmox и вход на сервер
1. Браузер → `https://192.168.1.200:8006` → предупреждение о сертификате «Дополнительно → Перейти». Логин `root`, Realm **Linux PAM**, пароль root от Proxmox.
2. Слева VM с Ubuntu → **Summary** → строка **IPs** (её показывает QEMU guest agent). Это `<IP-VM>`. Если пусто — **Console** → войти → `ip -4 a`.
3. Проверь ресурсы VM (**Hardware**): RAM **≥ 8 ГБ** (сайт + torch ≈ 3 ГБ, бот + Whisper ≈ 2 ГБ, Obsidian в браузере ещё ~1 ГБ), диск ≥ 40 ГБ. **Options → Start at boot = Yes**.
4. В роутере (`192.168.1.1`, DHCP Binding) закрепи `<IP-VM>` за VM, как сделано для Proxmox.
5. С ПК: `ssh <пользователь>@<IP-VM>`

---

## 3. Second Brain на сервере
```bash
sudo apt update && sudo apt install -y git
cd ~
git clone https://github.com/dtenditnyi/second_brain_ai.git
cd second_brain_ai
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"     # → SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(24))"     # → POSTGRES_PASSWORD
nano .env
```
В `.env` заменить:
```ini
SECRET_KEY=<первая строка выше>
POSTGRES_PASSWORD=<вторая строка>
GEMINI_API_KEY=<из .env ПК>
OLLAMA_HOST=http://<IP-ПК>:11434
OLLAMA_MODEL=llama3:latest
CLOUDFLARE_TUNNEL_TOKEN=<шаг 3.1; можно сначала оставить как есть>
```
Сохранить: Ctrl+O, Enter, Ctrl+X. Проверка Ollama с сервера: `curl -s http://<IP-ПК>:11434/api/tags | head -c 200`.

Установка (10–20 минут при первом запуске):
```bash
bash deploy/install.sh
```
Если скрипт сказал перелогиниться (группа docker) — `exit`, снова `ssh …`, и ещё раз `bash deploy/install.sh`. Потом:
```bash
docker compose exec web python manage.py createsuperuser
curl -s http://127.0.0.1:8000/healthz/        # {"status": "ok", "db": "ok"}
bash deploy/status.sh
```

### 3.1 Cloudflare Tunnel (доступ к сайту откуда угодно)
Cloudflare → **Zero Trust → Networks → Tunnels → Create a tunnel** → Cloudflared → имя `secondbrain` → скопировать токен (строка после `--token`) → в `.env` `CLOUDFLARE_TUNNEL_TOKEN=…` →
```bash
docker compose up -d tunnel
```
В туннеле **Public Hostname → Add**: Domain `secondbrain-core.com`, Service **HTTP** `web:8000`. Проверка: `https://secondbrain-core.com/healthz/`.
Если старый туннель домена ещё запущен на ПК (`run_matrix.bat`, `cloudflared`) — останови его.

### 3.2 Первый вход на сайт
`https://secondbrain-core.com` → войти созданным пользователем → **Настройки**:
- GitHub repository URL: `https://github.com/dtenditnyi/myObsidian`, PAT с правом **Contents: Read and write**;
- AI strategy: **Auto-Hybrid** (Ollama на ПК, если он включён, иначе Gemini);
- Сохранить → страница **Tasks** → Refresh (хранилище склонируется).
- Потом: **2FA** (раздел 13.2 DEPLOY.md) и **Cloudflare Access** (13.1).

---

## 4. Link2Note рядом
```bash
cd ~
git clone https://github.com/dtenditnyi/Link2Note.git link2note
cd link2note
```
Дальше — `docs/OWNER_TODO.md` в репозитории бота, шаги 3–5 (deploy key для режима git, `.env`, `./deploy/install.sh`, перенос базы с ПК). Сеть `secondbrain` уже создана сайтом.

Сразу переключиться на API сайта (без deploy key):
1. На сайте: **Настройки → API tokens** → имя `link2note`, права `read write delete ai`; Write folders:
   ```
   03 - Resources/📥 Из ссылок
   05 - Fleeting/📥 Входящие.md
   01 - Projects/🎯 Цели и планы/Задачи.md
   ```
   Delete folders: `03 - Resources/📥 Из ссылок` → **Create token** → скопировать `sb_…` (показывается один раз).
2. В `~/link2note/.env`: `VAULT_BACKEND=api` и `SECOND_BRAIN_API_TOKEN=sb_…` (строки `VAULT_REPO` и `GIT_SSH_COMMAND` не нужны) → `docker compose up -d`.
3. Проверка контракта:
   ```bash
   read -rs SECOND_BRAIN_API_TOKEN && export SECOND_BRAIN_API_TOKEN
   docker compose exec -e SECOND_BRAIN_API_TOKEN bot /app/.venv/bin/python scripts/check_second_brain_api.py --all
   ```
   Все строки ✅ → в Telegram: ссылка на видео, `/task`, `/note`, `/ask`.
4. Бот на ПК/ноутбуке с тем же токеном Telegram **не запускать**.

---

## 5. Обновления (каждый раз после изменений)
На ПК: правки → `git commit` → `git push` в `main` (для обоих репозиториев — как обычно).
На сервере — одна команда:
```bash
~/second_brain_ai/deploy/update-all.sh
```
Она обновляет сайт (`git pull` → бэкап → сборка → перезапуск → проверка `/healthz/`, при ошибке — откат) и затем бота (`~/link2note/deploy/update.sh`). Чтобы запускать просто словом `update-all`:
```bash
sudo ln -sf ~/second_brain_ai/deploy/update-all.sh /usr/local/bin/update-all
```
Пересобрать без новых коммитов: `update-all --force`. Состояние: `bash ~/second_brain_ai/deploy/status.sh`, `cd ~/link2note && ./deploy/status.sh`.
