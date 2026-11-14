#!/usr/bin/env bash
# Second Brain — first installation on a clean Ubuntu Server 24.04 LTS (docs/DEPLOY.md).
# Installs Docker Engine + compose plugin from Docker's official repository, adds the
# user to the docker group, checks .env (values are never printed), builds and starts
# the stack, waits for the healthcheck and installs the systemd units
# (secondbrain.service + secondbrain-backup.timer). Safe to run again (idempotent).
set -euo pipefail

# shellcheck source=deploy/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
log_setup install

step "1/7 Docker Engine + compose plugin"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    ok "already installed: $(docker --version)"
else
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    codename="$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")"
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    ok "installed: $(docker --version)"
fi
sudo systemctl enable --now docker >/dev/null
ok "docker service enabled at boot"

step "2/7 docker group"
if id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
    ok "$USER is in the docker group"
else
    sudo usermod -aG docker "$USER"
    warn "$USER added to the docker group — log out and back in later (this run uses sudo)"
fi

step "3/7 .env"
check_env

step "4/7 build the image (first time: 10–20 minutes)"
compose build
ok "image built"

step "5/7 start the stack"
compose up -d --remove-orphans
ok "containers started"

step "6/7 wait for /healthz/"
if wait_healthy 900; then
    healthz
else
    compose ps
    compose logs --tail 80 web
    fail "web did not become healthy — see the log above and docs/DEPLOY.md («Сайт не открывается»)"
fi

git -C "$REPO_DIR" rev-parse HEAD > "$REPO_DIR/.deployed_commit"

step "7/7 systemd: start at boot + daily backup 03:30"
for unit in secondbrain.service secondbrain-backup.service secondbrain-backup.timer; do
    sed "s#__REPO_DIR__#${REPO_DIR}#g; s#__USER__#${USER}#g" "$DEPLOY_DIR/systemd/$unit" \
        | sudo tee "/etc/systemd/system/$unit" >/dev/null
done
sudo chmod +x "$DEPLOY_DIR"/*.sh
sudo systemctl daemon-reload
sudo systemctl enable secondbrain.service >/dev/null
sudo systemctl enable --now secondbrain-backup.timer >/dev/null
ok "secondbrain.service enabled, secondbrain-backup.timer active"

step "Done"
ok "Second Brain is running. Status: deploy/status.sh · Update: deploy/update.sh · Backup: deploy/backup.sh"
ok "Next: create the admin user — docker compose exec web python manage.py createsuperuser"
