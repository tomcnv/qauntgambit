#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
WEB_ROOT="/var/www/quantgambit"
NGINX_CONF="/etc/nginx/conf.d/quantgambit.conf"

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

require docker
require npm
require rsync
require nginx
require python3

compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
    return
  fi
  echo "missing docker compose or docker-compose" >&2
  exit 1
}

ensure_quant_python311() {
  local quant_root python311_bin
  quant_root="${REPO_ROOT}/quantgambit-python"
  python311_bin="$(command -v python3.11 || true)"
  if [[ -z "${python311_bin}" ]]; then
    echo "missing required command: python3.11" >&2
    echo "Install python3.11 on the host before deploying bot runtimes." >&2
    exit 1
  fi

  if [[ ! -x "${quant_root}/venv311/bin/python" ]]; then
    echo "Creating quantgambit-python/venv311"
    rm -rf "${quant_root}/venv311"
    "${python311_bin}" -m venv "${quant_root}/venv311"
  fi

  echo "Refreshing quantgambit-python/venv311 dependencies"
  (
    cd "${quant_root}"
    ./venv311/bin/python -m pip install --upgrade pip setuptools wheel
    ./venv311/bin/python -m pip install -r requirements.txt
  )
}

HOST_ENV_FILE="/opt/quantgambit/config/host.env.example"

load_host_env() {
  if [[ -f "${HOST_ENV_FILE}" ]]; then
    set -a
    source "${HOST_ENV_FILE}"
    set +a
  fi
}

install_cloudflare_origin_cert() {
  load_host_env
  if [[ -z "${CF_ORIGIN_SECRET_ID:-}" ]]; then
    return 0
  fi

  require aws
  require jq

  local secret_json cert key
  secret_json="$(
    aws secretsmanager get-secret-value \
      --secret-id "${CF_ORIGIN_SECRET_ID}" \
      --region "${AWS_REGION:-ap-southeast-1}" \
      --query SecretString \
      --output text
  )"
  cert="$(printf '%s' "${secret_json}" | jq -r '.certificate_pem // empty')"
  key="$(printf '%s' "${secret_json}" | jq -r '.private_key_pem // empty')"

  if [[ -z "${cert}" || -z "${key}" ]]; then
    echo "Cloudflare origin secret is missing certificate_pem or private_key_pem" >&2
    exit 1
  fi

  sudo mkdir -p /etc/ssl/cloudflare
  printf '%s\n' "${cert}" | sudo tee /etc/ssl/cloudflare/quantgambit-origin.crt >/dev/null
  printf '%s\n' "${key}" | sudo tee /etc/ssl/cloudflare/quantgambit-origin.key >/dev/null
  sudo chmod 644 /etc/ssl/cloudflare/quantgambit-origin.crt
  sudo chmod 600 /etc/ssl/cloudflare/quantgambit-origin.key
}

render_env_from_secret() {
  load_host_env
  if [[ -z "${APP_ENV_SECRET_ID:-}" ]]; then
    return 1
  fi
  require aws
  aws secretsmanager get-secret-value \
    --secret-id "${APP_ENV_SECRET_ID}" \
    --region "${AWS_REGION:-ap-southeast-1}" \
    --query SecretString \
    --output text > "${SCRIPT_DIR}/.env"
}

if [[ ! -f "${SCRIPT_DIR}/.env" ]]; then
  if ! render_env_from_secret; then
    echo "missing ${SCRIPT_DIR}/.env and could not render it from Secrets Manager." >&2
    echo "Set APP_ENV_SECRET_ID on the host or copy .env.example and fill in secrets first." >&2
    exit 1
  fi
fi

install_cloudflare_origin_cert

build_frontends() {
  if [[ "${SKIP_FRONTEND_BUILD:-0}" == "1" ]]; then
    [[ -d "${REPO_ROOT}/deeptrader-landing/dist" ]] || {
      echo "missing prebuilt landing dist directory" >&2
      exit 1
    }
    [[ -d "${REPO_ROOT}/deeptrader-dashhboard/dist" ]] || {
      echo "missing prebuilt dashboard dist directory" >&2
      exit 1
    }
    return
  fi

  echo "Building landing site"
  (
    cd "${REPO_ROOT}/deeptrader-landing"
    set -a
    source <(grep -E '^(VITE_API_URL|VITE_DASHBOARD_URL)=' "${SCRIPT_DIR}/.env")
    set +a
    npm ci
    npm run build
  )

  echo "Building dashboard"
  (
    cd "${REPO_ROOT}/deeptrader-dashhboard"
    set -a
    source <(grep -E '^(VITE_LANDING_URL|VITE_DASHBOARD_URL|VITE_CORE_API_BASE_URL|VITE_BOT_API_BASE_URL|VITE_WS_URL)=' "${SCRIPT_DIR}/.env")
    set +a
    npm ci
    npm run build
  )
}

mkdir -p "${WEB_ROOT}/landing" "${WEB_ROOT}/dashboard" /var/www/certbot

build_frontends
rsync -a --delete "${REPO_ROOT}/deeptrader-landing/dist/" "${WEB_ROOT}/landing/"
rsync -a --delete "${REPO_ROOT}/deeptrader-dashhboard/dist/" "${WEB_ROOT}/dashboard/"

ensure_quant_python311

echo "Installing nginx config"
sudo rsync -a "${SCRIPT_DIR}/nginx.quantgambit.conf" "${NGINX_CONF}"
sudo nginx -t
sudo systemctl reload nginx

echo "Launching backend services"
(
  cd "${SCRIPT_DIR}"
  $(compose_cmd) up -d --build
)

cat <<'EOF'
Deployment completed.
EOF
