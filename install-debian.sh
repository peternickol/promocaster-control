#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root" >&2
  exit 1
fi

CONTROL_REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="/root/promocaster-control"
APP_ROOT="${PROMOCASTER_CONTROL_APP_ROOT:-/opt/promocaster-control}"
APP_DIR="$APP_ROOT/app"
CONFIG_DIR="${PROMOCASTER_CONTROL_CONFIG_DIR:-/etc/promocaster-control}"
CONFIG_PATH="${PROMOCASTER_CONTROL_CONFIG_PATH:-$CONFIG_DIR/config.env}"
BASIC_AUTH_CONFIG="${PROMOCASTER_CONTROL_BASIC_AUTH_CONFIG:-$CONFIG_DIR/basic-auth.caddy}"
SOURCE_ROOT_FILE="${PROMOCASTER_CONTROL_SOURCE_ROOT_FILE:-$CONFIG_DIR/source-root}"
DATA_DIR="${PROMOCASTER_CONTROL_DATA_DIR:-/var/lib/promocaster-control}"
SERVICE_USER="${PROMOCASTER_CONTROL_SERVICE_USER:-promocaster-control}"
SERVICE_NAME="${PROMOCASTER_CONTROL_SERVICE_NAME:-promocaster-control.service}"
PACKAGES_FILE="${PROMOCASTER_CONTROL_PACKAGES_FILE:-$CONTROL_REPO/packaging/debian-packages.txt}"
GLOBAL_BIN="${PROMOCASTER_CONTROL_GLOBAL_BIN:-/usr/local/bin/promocaster-control}"
SITE="${PROMOCASTER_CONTROL_SITE:-control.promocaster.io}"
BIND="${PROMOCASTER_CONTROL_BIND:-127.0.0.1}"
PORT="${PROMOCASTER_CONTROL_PORT:-8080}"
NONINTERACTIVE=0

usage() {
  cat <<EOF
Usage: bash install-debian.sh [options]

Options:
  --non-interactive           Use defaults and environment variables without prompting
  --help                      Show this help text

Environment:
  PROMOCASTER_CONTROL_SITE    Caddy site address, default control.promocaster.io
  PROMOCASTER_CONTROL_PORT    Local app port, default 8080
  PROMOCASTER_CONTROL_BIND    Local app bind host, default 127.0.0.1
  PROMOCASTER_CONTROL_DATA_DIR
                              Data root, default /var/lib/promocaster-control
EOF
}

while (($# > 0)); do
  case "$1" in
    --non-interactive)
      NONINTERACTIVE=1
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

fix_loopback_hosts_entry() {
  local tmp_hosts
  if [[ -d /etc/cloud/cloud.cfg.d ]]; then
    cat > /etc/cloud/cloud.cfg.d/99-promocaster-control-hosts.cfg <<'EOF'
# Promocaster Control needs the public FQDN to resolve through DNS for Caddy/ACME.
# Do not let cloud-init put control.promocaster.io back on 127.0.1.1.
manage_etc_hosts: false
EOF
    echo "Disabled cloud-init manage_etc_hosts for durable FQDN DNS resolution"
  fi

  tmp_hosts="$(mktemp)"
  awk -v site="$SITE" '
    /^[[:space:]]*#/ { print; next }
    NF == 0 { print; next }
    {
      ip = $1
      if (ip ~ /^127\./) {
        line = ip
        removed = 0
        for (i = 2; i <= NF; i++) {
          if ($i == site) {
            removed = 1
            next
          }
          line = line " " $i
        }
        if (removed && line == ip) {
          next
        }
        print line
        next
      }
      print
    }
  ' /etc/hosts > "$tmp_hosts"

  if ! cmp -s "$tmp_hosts" /etc/hosts; then
    cp "$tmp_hosts" /etc/hosts
    echo "Removed $SITE from loopback entries in /etc/hosts"
  fi
  rm -f "$tmp_hosts"
}

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer currently supports Debian/apt-based systems only" >&2
  exit 1
fi

if [[ "$CONTROL_REPO" != "$SOURCE_ROOT" ]]; then
  echo "Expected this repo checkout at $SOURCE_ROOT; current path is $CONTROL_REPO" >&2
  echo "Clone or move the repo to $SOURCE_ROOT before running install-debian.sh" >&2
  exit 1
fi

if [[ ! -f "$PACKAGES_FILE" ]]; then
  echo "Missing package list: $PACKAGES_FILE" >&2
  exit 1
fi

REQUIRED_PACKAGES=()
while IFS= read -r package; do
  package="${package#"${package%%[![:space:]]*}"}"
  package="${package%"${package##*[![:space:]]}"}"
  [[ -n "$package" && "${package:0:1}" != "#" ]] || continue
  REQUIRED_PACKAGES+=("$package")
done < "$PACKAGES_FILE"

missing_packages=()
for package in "${REQUIRED_PACKAGES[@]}"; do
  if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "install ok installed"; then
    missing_packages+=("$package")
  fi
done

if (( ${#missing_packages[@]} > 0 )); then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y "${missing_packages[@]}"
fi

cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

cat > /etc/apt/apt.conf.d/52promocaster-control-unattended-upgrades <<'EOF'
Unattended-Upgrade::Origins-Pattern {
        "origin=Debian,codename=${distro_codename},label=Debian-Security";
        "origin=Debian,codename=${distro_codename},label=Debian";
        "origin=Debian,codename=${distro_codename}-updates,label=Debian";
};
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
EOF

dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true
systemctl enable --now unattended-upgrades.service >/dev/null 2>&1 || true

if [[ "$NONINTERACTIVE" -eq 0 && -t 0 ]]; then
  echo "Installing Promocaster Control."
  echo "The app binds to $BIND:$PORT; Caddy owns $SITE and reverse proxies to it."
fi

fix_loopback_hosts_entry

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --user-group --home "$APP_ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -m 0755 "$APP_ROOT" "$CONFIG_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$DATA_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$DATA_DIR/repos" "$DATA_DIR/uploads" "$DATA_DIR/sync"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0700 "$DATA_DIR/ssh"
install -d -m 0755 "$(dirname "$GLOBAL_BIN")"

GITHUB_KEY_PATH="$DATA_DIR/ssh/github_writer_key"
if [[ ! -f "$GITHUB_KEY_PATH" ]]; then
  ssh-keygen -q -t ed25519 -N '' -C "promocaster-control@$SITE" -f "$GITHUB_KEY_PATH"
  echo "Generated GitHub writer key at $GITHUB_KEY_PATH"
fi
chown "$SERVICE_USER:$SERVICE_USER" "$GITHUB_KEY_PATH" "$GITHUB_KEY_PATH.pub" 2>/dev/null || true
chmod 0600 "$GITHUB_KEY_PATH"
chmod 0644 "$GITHUB_KEY_PATH.pub" 2>/dev/null || true

rm -rf "$APP_DIR"
cp -a "$CONTROL_REPO" "$APP_DIR"
printf '%s\n' "$SOURCE_ROOT" > "$SOURCE_ROOT_FILE"
ln -sfn "$APP_DIR/bin/promocaster-control" "$GLOBAL_BIN"

cat > "$CONFIG_PATH" <<EOF
PROMOCASTER_CONTROL_BIND=$BIND
PROMOCASTER_CONTROL_PORT=$PORT
PROMOCASTER_CONTROL_WEB_ROOT=$APP_DIR/web
PROMOCASTER_CONTROL_DATA_DIR=$DATA_DIR
PROMOCASTER_CONTROL_CLIENTS_FILE=$APP_DIR/clients.yml
PROMOCASTER_CONTROL_SYNC_DIR=$DATA_DIR/sync
PROMOCASTER_CONTROL_BASIC_AUTH_CONFIG=$BASIC_AUTH_CONFIG
EOF
chmod 0640 "$CONFIG_PATH"
chmod 0644 "$SOURCE_ROOT_FILE"

if [[ ! -f "$BASIC_AUTH_CONFIG" ]]; then
  cat > "$BASIC_AUTH_CONFIG" <<'EOF'
respond "Promocaster Control basic auth is not configured. Run: promocaster-control basic-auth set <user>" 503
EOF
fi
chown root:caddy "$BASIC_AUTH_CONFIG" 2>/dev/null || true
chmod 0640 "$BASIC_AUTH_CONFIG"

install -m 0644 "$APP_DIR/packaging/$SERVICE_NAME" "/etc/systemd/system/$SERVICE_NAME"
sed -i \
  -e "s#__APP_DIR__#$APP_DIR#g" \
  -e "s#__CONFIG_PATH__#$CONFIG_PATH#g" \
  -e "s#__SERVICE_USER__#$SERVICE_USER#g" \
  "/etc/systemd/system/$SERVICE_NAME"

install -d -m 0755 /etc/caddy
sed \
  -e "s#__SITE__#$SITE#g" \
  -e "s#__UPSTREAM__#$BIND:$PORT#g" \
  -e "s#__BASIC_AUTH_CONFIG__#$BASIC_AUTH_CONFIG#g" \
  "$APP_DIR/packaging/promocaster-control.Caddyfile" > /etc/caddy/promocaster-control.conf
cat > /etc/caddy/Caddyfile <<'EOF'
{
    admin localhost:2019
}

import /etc/caddy/*.conf
EOF
caddy validate --config /etc/caddy/Caddyfile

chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_ROOT" "$DATA_DIR"
chmod 0755 "$APP_DIR/bin/promocaster-control"

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
systemctl enable --now caddy
systemctl reload caddy

cat <<EOF
Promocaster Control has been installed.

Service:
  systemd: $SERVICE_NAME
  Local app: http://$BIND:$PORT
  Public site: $SITE

Paths:
  App: $APP_DIR
  Config: $CONFIG_PATH
  Basic auth: $BASIC_AUTH_CONFIG
  Source checkout: $SOURCE_ROOT_FILE
  Data: $DATA_DIR
  Client repo checkouts: $DATA_DIR/repos
  Upload staging: $DATA_DIR/uploads
  Sync progress state: $DATA_DIR/sync
  Git SSH keys: $DATA_DIR/ssh
  Operator command: $GLOBAL_BIN

Maintenance:
  promocaster-control doctor
  promocaster-control basic-auth set peter
  promocaster-control basic-auth test
  promocaster-control github-key generate
  promocaster-control github-key edit
  promocaster-control github-key show-public
  promocaster-control github-key test
  promocaster-control tls-check
  promocaster-control update

Let's Encrypt:
  Caddy will request and renew certificates for $SITE automatically.
  Make sure DNS points $SITE at this VPS and public TCP ports 80 and 443 are open.
  Check readiness with: promocaster-control tls-check

Next setup:
  Set phase-1 login with: promocaster-control basic-auth set peter
  Add the generated GitHub writer public key to GitHub with: promocaster-control github-key show-public
  Test GitHub auth with: promocaster-control github-key test
  Wire the real auth and git-publish API into server/.
EOF
