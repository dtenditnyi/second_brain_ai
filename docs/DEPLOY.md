# Развёртывание Second Brain на домашнем сервере

Пошаговая инструкция для новичка: от виртуальной машины в Proxmox до работающего сайта
`https://secondbrain-core.com`, который сам поднимается после перезагрузки, обновляется одной
командой и каждый день делает бэкап.

Итоговая схема:

```
Интернет ──► Cloudflare (HTTPS) ──► cloudflared (контейнер) ──► web: Django + gunicorn ──► PostgreSQL
                                                                  │
                                                                  ├─► scheduler: sync_tasks раз в минуту
                                                                  ├─► GitHub: хранилище Obsidian (push/pull)
                                                                  └─► Ollama на ПК в домашней сети (если включён) / Gemini
```

Наружу ничего не открыто: Postgres вообще не публикуется, сайт доступен только через туннель
Cloudflare. Порт web по умолчанию слушает только `127.0.0.1`.

---

## 1. Виртуальная машина в Proxmox

| Параметр | Значение | Почему |
|---|---|---|
| ОС | Ubuntu Server 24.04 LTS (ISO с ubuntu.com) | LTS-версия с поддержкой до 2029 года |
| vCPU | 4 (тип CPU — `host`) | Эмбеддинги (torch + HuggingFace) считаются на CPU |
| RAM | 6 ГБ (минимум 4 ГБ) | Модель эмбеддингов, Chroma и Postgres вместе занимают 2–3 ГБ, плюс запас на сборку образа |
| Диск | 40 ГБ (SCSI, VirtIO SCSI single, discard включён) | Образ ~3 ГБ, кэш моделей ~0,5 ГБ, бэкапы, логи |
| Сеть | VirtIO, мост `vmbr0` | |
| QEMU guest agent | **Включить** (Options → QEMU Guest Agent → Enabled) | Корректное выключение и IP в интерфейсе Proxmox |
| Start at boot | **Включить** (Options → Start at boot → Yes) | VM сама запускается после перезагрузки хоста |

В установщике Ubuntu отметьте «Install OpenSSH server». Docker из установщика (snap) **не**
ставьте: скрипт установит его из официального репозитория Docker.

После установки, в консоли VM:

```bash
sudo apt update && sudo apt install -y qemu-guest-agent
sudo systemctl enable --now qemu-guest-agent
```

## 2. Базовая настройка Ubuntu

```bash
# Обновления
sudo apt update && sudo apt full-upgrade -y
# Автоматические обновления безопасности
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades     # выберите «Yes»
# Часовой пояс
sudo timedatectl set-timezone Europe/Bucharest
```

### Статический IP

Удобнее всего сделать **резервирование адреса в роутере** (DHCP reservation по MAC-адресу VM,
MAC видно в Proxmox: Hardware → Network Device). Либо статический IP в
`/etc/netplan/50-cloud-init.yaml`:

```yaml
network:
  version: 2
  ethernets:
    ens18:
      dhcp4: false
      addresses: [192.168.1.50/24]
      routes: [{to: default, via: 192.168.1.1}]
      nameservers: {addresses: [1.1.1.1, 8.8.8.8]}
```

```bash
sudo netplan apply
```

### SSH только по ключу

На своём ПК (PowerShell или терминал):

```bash
ssh-keygen -t ed25519            # если ключа ещё нет
ssh-copy-id user@192.168.1.50    # Windows: type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh user@192.168.1.50 "cat >> ~/.ssh/authorized_keys"
```

Проверьте, что вход по ключу работает, затем на сервере отключите вход по паролю:

```bash
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```

### Брандмауэр ufw: только SSH из домашней сети

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp
sudo ufw enable
sudo ufw status
```

Туннелю Cloudflare входящие порты не нужны: он сам подключается к Cloudflare изнутри.

## 3. Код и `.env`

```bash
sudo apt install -y git
git clone https://github.com/<ваш-аккаунт>/second_brain_ai.git
cd second_brain_ai
cp .env.example .env
nano .env
```

Обязательные переменные:

| Переменная | Что указать |
|---|---|
| `SECRET_KEY` | Длинная случайная строка: `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`. Пустой или стандартный ключ сайт не примет. |
| `POSTGRES_PASSWORD` | Надёжный пароль базы данных (`POSTGRES_DB`, `POSTGRES_USER` можно оставить) |
| `CLOUDFLARE_TUNNEL_TOKEN` | Токен туннеля (раздел 5) |
| `GEMINI_API_KEY` | Ключ Gemini (облачный ИИ) |
| `OLLAMA_HOST` | Ollama на ПК в домашней сети, например `http://192.168.1.20:11434`. Если ПК выключен, режим Auto-Hybrid сам переключится на Gemini |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | Значения по умолчанию подходят для `secondbrain-core.com` |

Остальные переменные описаны в `.env.example` (модели Gemini, `TASKS_NOTE_PATH`,
`TASKS_SYNC_INTERVAL`, `GUNICORN_WORKERS`, `WEB_BIND`…). Сам `.env` никому не показывайте и не
коммитьте.

### Токен GitHub для хранилища (PAT)

Сайт записывает задачи и правки обратно в хранилище, поэтому токену нужно право записи:

1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** →
   Generate new token.
2. Repository access: **Only select repositories** → репозиторий хранилища (`myObsidian`).
3. Permissions → Repository permissions → **Contents: Read and write** (остальное не нужно).
4. Срок действия — на ваше усмотрение (например, 1 год; напоминание в календарь).
5. Токен вводится не в `.env`, а на сайте: **Настройки** → «GitHub personal access token»,
   вместе с URL репозитория. Сайт хранит его зашифрованным и никогда не показывает обратно.

Если у токена нет права записи, на странице задач и в Настройках появится ошибка с текстом
«Contents: Read and write».

## 4. Установка одной командой

```bash
bash deploy/install.sh
```

Скрипт (можно запускать повторно):

1. ставит Docker Engine и compose plugin из официального репозитория Docker;
2. добавляет пользователя в группу `docker`;
3. проверяет `.env` (значения не выводятся);
4. собирает образ (первый раз 10–20 минут: CSS, Python-зависимости, torch для CPU);
5. запускает контейнеры `db`, `web`, `scheduler`, `tunnel`;
6. ждёт, пока `/healthz/` ответит «ok»;
7. ставит systemd-юниты: `secondbrain.service` (поднимает стек при загрузке) и
   `secondbrain-backup.timer` (бэкап каждый день в 03:30).

Затем создайте администратора:

```bash
docker compose exec web python manage.py createsuperuser
```

Перелогиньтесь по SSH, чтобы группа `docker` заработала без `sudo`.

## 5. Cloudflare Tunnel для `secondbrain-core.com`

1. Cloudflare Dashboard → **Zero Trust** → Networks → **Tunnels** → Create a tunnel →
   Cloudflared → имя `secondbrain`.
2. Скопируйте **токен** из команды установки (длинная строка после `--token`) в `.env` →
   `CLOUDFLARE_TUNNEL_TOKEN=...`, затем `docker compose up -d tunnel`.
3. В туннеле → **Public Hostname** → Add:
   - Subdomain: пусто (или `www`), Domain: `secondbrain-core.com`;
   - Service: **HTTP** → `web:8000` (контейнер `tunnel` видит `web` по имени).
4. Проверка: `https://secondbrain-core.com/healthz/` → `{"status": "ok", "db": "ok"}`.

HTTPS обеспечивает Cloudflare. Django перенаправляет на https, ставит secure-cookies и HSTS.
Защита доступа (Cloudflare Access, одноразовый код на почту) описана в Round 5.

## 6. Обновление

```bash
cd ~/second_brain_ai
deploy/update.sh
```

Что делает скрипт: `git pull` → бэкап → сборка нового образа (старый сохраняется как
`secondbrain-web:rollback`) → перезапуск (миграции применяются автоматически при старте) →
проверка `/healthz/`. Если новая версия не стала «healthy», скрипт сам откатывается на предыдущий
коммит и образ. Миграции базы автоматически **не** откатываются: если сломалась миграция,
восстановите бэкап, сделанный в начале обновления (`deploy/restore.sh`).

## 7. Бэкапы и восстановление

- Автоматически: каждый день в 03:30 `deploy/backup.sh` → `backups/db-ДАТА.sql.gz`, хранятся
  последние 14. Проверка таймера: `systemctl list-timers secondbrain-backup.timer`.
- Вручную: `deploy/backup.sh`. С файлами (векторный индекс и клон хранилища):
  `deploy/backup.sh --with-files`. Хранилище Obsidian и так лежит в GitHub, а индекс Chroma
  сайт пересобирает сам, так что `--with-files` нужен только для быстрого переезда.
- Копируйте папку `backups/` на другой диск или в облако (например, `rclone`), иначе бэкап
  погибнет вместе с диском VM.
- Восстановление: `deploy/restore.sh backups/db-2026-11-11_03-30-00.sql.gz`. Скрипт попросит
  ввести `RESTORE`, сначала сделает страховочный бэкап, остановит web/scheduler, пересоздаст схему
  и загрузит дамп **в одной транзакции** (при ошибке ничего не меняется), затем запустит всё
  обратно — при старте web миграции доведут базу до текущей версии.
- Версию туннеля лучше закрепить: в `.env` `CLOUDFLARED_IMAGE=cloudflare/cloudflared:<проверенная версия>`.

## 8. Перенос со старого ПК (Postgres в Docker на Windows)

Старую базу скрипт **не изменяет**: делается только чтение (`pg_dump`).

1. На старом ПК (Git Bash в папке проекта, Docker Desktop запущен, контейнер БД работает):
   ```bash
   deploy/migrate-from-old-pc.sh --dump
   # имя контейнера, если отличается:  OLD_DB_CONTAINER=имя deploy/migrate-from-old-pc.sh --dump
   ```
   Появится файл `secondbrain-old-ДАТА.sql.gz`.
2. Скопируйте его на сервер:
   ```bash
   scp secondbrain-old-*.sql.gz user@192.168.1.50:~/second_brain_ai/backups/
   ```
3. На сервере:
   ```bash
   deploy/migrate-from-old-pc.sh --restore backups/secondbrain-old-ДАТА.sql.gz
   ```
4. Перенесите старые задачи в заметку Obsidian (`docs/TASKS_FORMAT.md`). Сначала предпросмотр,
   потом запись:
   ```bash
   docker compose exec web python manage.py export_tasks_to_note --user ВАШ_ЛОГИН --dry-run
   docker compose exec web python manage.py export_tasks_to_note --user ВАШ_ЛОГИН
   ```
   Повторный запуск дублей не создаёт. Теги не из разрешённого списка будут отброшены, и команда
   об этом напишет.
5. Скопируйте `SECRET_KEY` со старого ПК в новый `.env`: от него зависит расшифровка сохранённых
   токенов GitHub. Если ключ новый, просто введите токен заново в Настройках.
6. Когда всё работает, остановите старый стек на Windows-ПК (`docker compose stop`) и выключите
   туннель там, чтобы оба сервера не отвечали на один домен.

## 9. Логи и состояние

```bash
deploy/status.sh                       # контейнеры, healthcheck, диск, ошибки, бэкапы, синхронизация задач
docker compose logs -f web             # логи сайта (gunicorn)
docker compose logs -f scheduler       # синхронизация задач (sync_tasks)
docker compose exec web ls logs/       # rag_engine.log, system.log (ротация по 5 МБ × 5)
ls logs/deploy/                        # журналы install/update/backup/restore
```

Логи Docker ротируются автоматически (10 МБ × 5 на контейнер).

## 10. Чек-лист «Сайт не открывается»

1. **VM работает?** В Proxmox VM в статусе running; `ping 192.168.1.50`.
2. **Контейнеры запущены?** `docker compose ps` — у `db` и `web` статус `healthy`. Если нет —
   `sudo systemctl start secondbrain` или `docker compose up -d`.
3. **Сайт отвечает внутри сервера?** `curl -s http://127.0.0.1:8000/healthz/` → `{"status": "ok", "db": "ok"}`.
   - `db: error` → `docker compose logs db`, место на диске (`df -h`).
   - нет ответа → `docker compose logs --tail 100 web` (ошибки миграций, `SECRET_KEY`, нехватка памяти).
4. **Ошибка `SECRET_KEY is empty or the insecure default`** → задайте длинный `SECRET_KEY` в `.env`,
   затем `docker compose up -d`.
5. **Туннель работает?** `docker compose logs --tail 50 tunnel` — должно быть «Registered tunnel
   connection». В Cloudflare Zero Trust туннель в статусе HEALTHY. Проверьте токен в `.env` и
   Public Hostname → `http://web:8000`.
6. **400 Bad Request** → домена нет в `ALLOWED_HOSTS`. **403 CSRF** → нет `https://домен` в
   `CSRF_TRUSTED_ORIGINS`.
7. **Бесконечный редирект** → в Cloudflare SSL/TLS режим должен быть **Full** (не Flexible), либо
   временно поставьте `SECURE_SSL_REDIRECT=False`.
8. **Задачи не синхронизируются** → страница «Задачи» показывает ошибку; `deploy/status.sh` →
   раздел «tasks sync». Частые причины: у PAT нет «Contents: Read and write» или истёк срок
   токена, неверный URL репозитория.
9. **ИИ не отвечает** → `GEMINI_API_KEY` в `.env`; для Ollama — ПК включён и
   `curl http://IP-ПК:11434/api/tags` с сервера отвечает (на ПК: `OLLAMA_HOST=0.0.0.0` и
   разрешённый порт 11434 в брандмауэре Windows).
10. **После перезагрузки ничего не поднялось** → `systemctl status secondbrain docker`;
    `sudo systemctl enable --now docker secondbrain`.

## 11. Проверено / не проверено

Конфигурация проверена без живого Docker. На машине разработки Docker-демон не запускался
намеренно, чтобы не поднять старые прод-контейнеры. Проверено: `docker compose config`,
`bash -n` и shellcheck всех скриптов, тесты для `/healthz/`, проверки `SECRET_KEY`, настроек из env
и `manage.py check --deploy`.

Что `.dockerignore` действительно исключает (базы `*.sqlite3`, `.env`, логи, тесты, кэш) проверено тестом по правилам Docker (`tests/test_round3_regressions.py`), но не настоящей сборкой. Восстановление `restore.sh` пересоздаёт схему и загружает дамп в одной транзакции (подходит и для дампа старой версии со старого ПК; миграции применяются при старте web), но вживую на Postgres не запускалось.

Первая настоящая сборка и запуск выполняются на сервере через `deploy/install.sh`. Если что-то
пойдёт не так, смотрите раздел 10 и журнал в `logs/deploy/`.
