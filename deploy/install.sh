#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(dirname "$script_dir")
server_host=
https_port=9443
cert_file=
key_file=
input_env=
check_only=false
cert_mode=

usage() {
    cat <<'EOF'
Usage: sudo ./deploy/install.sh --host HOST --env-file ENV [--port PORT]
       sudo ./deploy/install.sh --host HOST --env-file ENV --cert-mode existing --cert-file FULLCHAIN --key-file PRIVATE_KEY
       sudo ./deploy/install.sh --host HOST --env-file ENV --cert-mode issue
       ./deploy/install.sh --check --host HOST --cert-file FULLCHAIN --key-file PRIVATE_KEY --env-file ENV

HOST must be an IPv4 address or DNS name covered by the certificate.
ENV must contain API_KEY, SUPABASE_URL and SUPABASE_ANON_KEY.
Without --cert-mode, installation asks whether a certificate already exists.
Issue mode obtains a Let's Encrypt certificate using public port 80 and configures renewal.
Check mode validates an existing certificate without changing the system.
EOF
}

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

while (($#)); do
    case $1 in
        --host) (($# >= 2)) || die 'Missing --host value'; server_host=$2; shift 2 ;;
        --port) (($# >= 2)) || die 'Missing --port value'; https_port=$2; shift 2 ;;
        --cert-file) (($# >= 2)) || die 'Missing --cert-file value'; cert_file=$2; shift 2 ;;
        --key-file) (($# >= 2)) || die 'Missing --key-file value'; key_file=$2; shift 2 ;;
        --env-file) (($# >= 2)) || die 'Missing --env-file value'; input_env=$2; shift 2 ;;
        --cert-mode) (($# >= 2)) || die 'Missing --cert-mode value'; cert_mode=$2; shift 2 ;;
        --check) check_only=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

[[ $server_host =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || die 'Use an IPv4 address or DNS name for --host'
[[ $https_port =~ ^[0-9]+$ ]] && ((10#$https_port >= 1 && 10#$https_port <= 65535)) || die 'Invalid HTTPS port'
if [[ -z $cert_mode ]]; then
    if $check_only || [[ -n $cert_file || -n $key_file ]]; then
        cert_mode=existing
    else
        [[ -t 0 ]] || die 'Noninteractive installation requires --cert-mode existing or --cert-mode issue'
        read -r -p 'Сертификат уже существует? [д/Н] ' answer
        case $answer in
            [дДyY]*) cert_mode=existing ;;
            [нНnN]*|'') cert_mode=issue ;;
            *) die 'Ответьте да или нет' ;;
        esac
    fi
fi
[[ $cert_mode == existing || $cert_mode == issue ]] || die 'Use --cert-mode existing or --cert-mode issue'
if [[ $cert_mode == existing ]]; then
    if [[ -z $cert_file && -t 0 ]] && ! $check_only; then
        read -r -p 'Абсолютный путь к fullchain.pem: ' cert_file
    fi
    if [[ -z $key_file && -t 0 ]] && ! $check_only; then
        read -r -p 'Абсолютный путь к privkey.pem: ' key_file
    fi
    [[ $cert_file =~ ^/[A-Za-z0-9_./+-]+$ && -f $cert_file ]] || die 'Certificate must be an existing absolute path without spaces'
    [[ $key_file =~ ^/[A-Za-z0-9_./+-]+$ && -f $key_file ]] || die 'Private key must be an existing absolute path without spaces'
else
    $check_only && die '--check only validates an existing certificate'
    [[ -z $cert_file && -z $key_file ]] || die 'Issue mode uses /etc/gemini-cli/tls; omit --cert-file and --key-file'
    cert_file=/etc/gemini-cli/tls/fullchain.pem
    key_file=/etc/gemini-cli/tls/privkey.pem
fi
[[ -f $input_env && -r $input_env ]] || die 'Cannot read --env-file'
[[ -f $project_dir/server.py && -f $script_dir/requirements-server.txt &&
   -f $script_dir/nginx-gemini-cli.conf.in && -f $script_dir/gemini-tls-reload.service.in ]] || die 'Run from a complete Gemini_CLI checkout'
for key in API_KEY SUPABASE_URL SUPABASE_ANON_KEY; do
    line=$(grep -m1 "^${key}=" "$input_env") || die "Missing $key in --env-file"
    [[ -n ${line#*=} ]] || die "Empty $key in --env-file"
done

if ! $check_only; then
    ((EUID == 0)) || die 'Run the installer as root (sudo)'
fi
if ! command -v openssl >/dev/null; then
    $check_only && die 'OpenSSL is required for --check'
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openssl
fi

validate_certificate() {
    if [[ $server_host =~ ^[0-9.]+$ ]]; then
        openssl x509 -in "$cert_file" -noout -checkip "$server_host" >/dev/null || die 'Certificate does not cover the IP address'
    else
        openssl x509 -in "$cert_file" -noout -checkhost "$server_host" >/dev/null || die 'Certificate does not cover the DNS name'
    fi
    openssl x509 -in "$cert_file" -noout -checkend 86400 >/dev/null || die 'Certificate expires within 24 hours'
    local cert_pub key_pub
    cert_pub=$(openssl x509 -in "$cert_file" -pubkey -noout | openssl pkey -pubin -outform DER 2>/dev/null | sha256sum) || die 'Cannot read certificate public key'
    key_pub=$(openssl pkey -in "$key_file" -passin pass: -pubout -outform DER 2>/dev/null | sha256sum) || die 'Cannot read private key'
    [[ $cert_pub == "$key_pub" ]] || die 'Certificate and private key do not match'
}
if [[ $cert_mode == existing ]]; then
    validate_certificate
fi
if $check_only; then
    printf 'Checks passed for https://%s:%s\n' "$server_host" "$https_port"
    exit 0
fi

[[ -f /etc/os-release ]] || die 'Supported systems: Ubuntu/Debian with systemd'
# shellcheck source=/dev/null
. /etc/os-release
[[ $ID == ubuntu || $ID == debian ]] || die 'Supported systems: Ubuntu/Debian with systemd'
command -v systemctl >/dev/null || die 'systemd is required'
command -v apt-get >/dev/null || die 'apt-get is required'
command -v dpkg-query >/dev/null || die 'dpkg-query is required'

if ! command -v python3 >/dev/null; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 python3-venv
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die 'Python 3.10 or newer is required'
if ! dpkg-query -W -f='${Status}' python3-venv 2>/dev/null | grep -qx 'install ok installed'; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3-venv
fi
install -d -m 755 /opt/gemini-cli
if [[ $(readlink -f "$script_dir/requirements-server.txt") != /opt/gemini-cli/requirements-server.txt ]]; then
    install -m 644 "$script_dir/requirements-server.txt" /opt/gemini-cli/requirements-server.txt
fi
[[ -x /opt/gemini-cli/.venv/bin/python ]] || python3 -m venv /opt/gemini-cli/.venv
/opt/gemini-cli/.venv/bin/python -m pip install --disable-pip-version-check --no-input -q -r /opt/gemini-cli/requirements-server.txt
/opt/gemini-cli/.venv/bin/python -m pip check

if [[ $cert_mode == issue ]]; then
    [[ $https_port != 80 ]] || die 'HTTPS port 80 conflicts with ACME validation'
    for package in git curl socat cron iproute2 ca-certificates; do
        dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -qx 'install ok installed' ||
            DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$package"
    done
    if ss -H -ltn 'sport = :80' | grep -q .; then
        die 'Port 80 is occupied; standalone ACME validation needs it free'
    fi
    acme_home=/etc/gemini-cli/acme
    if [[ ! -x $acme_home/acme.sh ]]; then
        acme_source=$(mktemp -d)
        trap 'rm -rf -- "$acme_source"' EXIT
        git clone --depth 1 https://github.com/acmesh-official/acme.sh.git "$acme_source"
        install -d -m 700 /etc/gemini-cli
        "$acme_source/acme.sh" --install --home "$acme_home"
        rm -rf -- "$acme_source"
        trap - EXIT
    fi
    systemctl enable --now cron.service
    issue_args=(--issue -d "$server_host" --standalone --server letsencrypt --httpport 80 --keylength ec-256)
    if [[ $server_host =~ ^[0-9.]+$ ]]; then
        issue_args+=(--certificate-profile shortlived --days 6)
    fi
    "$acme_home/acme.sh" "${issue_args[@]}"
    install -d -m 700 /etc/gemini-cli/tls
    "$acme_home/acme.sh" --install-cert --ecc -d "$server_host" \
        --key-file "$key_file" --fullchain-file "$cert_file" \
        --reloadcmd 'systemctl is-active --quiet nginx && systemctl reload nginx || true'
    chmod 600 "$key_file"
    validate_certificate
fi

nginx_preinstalled=true
command -v nginx >/dev/null || nginx_preinstalled=false
missing_packages=()
for package in nginx curl ca-certificates iproute2 openssl; do
    dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -qx 'install ok installed' || missing_packages+=("$package")
done
if ((${#missing_packages[@]})); then
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing_packages[@]}"
fi

if ss -H -ltn "sport = :$https_port" | grep -q .; then
    [[ -f /etc/nginx/conf.d/gemini-cli.conf ]] || die "Port $https_port is already in use"
    ss -H -ltnp "sport = :$https_port" | grep -q nginx || die "Port $https_port belongs to another service"
fi
if [[ -f /etc/nginx/conf.d/gemini-cli.conf ]] &&
   ! grep -Fq 'Managed by Gemini_CLI deploy/install.sh' /etc/nginx/conf.d/gemini-cli.conf &&
   ! grep -Fq 'proxy_pass http://127.0.0.1:8000;' /etc/nginx/conf.d/gemini-cli.conf; then
    die 'Refusing to replace an unrelated Nginx site'
fi
if ss -H -ltn 'sport = :8000' | grep -q .; then
    systemctl is-active --quiet gemini-cli.service || die 'Port 8000 is already in use'
fi

if ! $nginx_preinstalled && [[ -L /etc/nginx/sites-enabled/default ]]; then
    [[ $(readlink /etc/nginx/sites-enabled/default) == /etc/nginx/sites-available/default ]] || die 'Unexpected default Nginx site'
    unlink /etc/nginx/sites-enabled/default
fi

getent passwd gemini-cli >/dev/null || useradd --system --home /nonexistent --shell /usr/sbin/nologin gemini-cli
install -d -m 700 /etc/gemini-cli
if [[ $(readlink -f "$project_dir/server.py") != /opt/gemini-cli/server.py ]]; then
    install -m 644 "$project_dir/server.py" /opt/gemini-cli/server.py
fi

work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT
for key in API_KEY SUPABASE_URL SUPABASE_ANON_KEY; do
    grep -m1 "^${key}=" "$input_env" >> "$work_dir/server.env"
done
install -m 600 "$work_dir/server.env" /etc/gemini-cli/server.env

render() {
    local content
    content=$(<"$1")
    content=${content//@HTTPS_PORT@/$https_port}
    content=${content//@CERT_FILE@/$cert_file}
    content=${content//@KEY_FILE@/$key_file}
    printf '%s\n' "$content" > "$2"
}
render "$script_dir/nginx-gemini-cli.conf.in" "$work_dir/nginx.conf"
render "$script_dir/gemini-tls-reload.service.in" "$work_dir/tls-reload.service"

if [[ -f /etc/nginx/conf.d/gemini-cli.conf ]]; then
    cp -p /etc/nginx/conf.d/gemini-cli.conf "$work_dir/previous-nginx.conf"
fi
install -m 644 "$work_dir/nginx.conf" /etc/nginx/conf.d/gemini-cli.conf
if ! nginx -t; then
    if [[ -f $work_dir/previous-nginx.conf ]]; then
        install -m 644 "$work_dir/previous-nginx.conf" /etc/nginx/conf.d/gemini-cli.conf
    else
        rm -f /etc/nginx/conf.d/gemini-cli.conf
    fi
    die 'Nginx configuration failed; previous site restored'
fi

install -m 644 "$script_dir/gemini-cli.service" /etc/systemd/system/gemini-cli.service
install -m 644 "$work_dir/tls-reload.service" /etc/systemd/system/gemini-tls-reload.service
install -m 644 "$script_dir/gemini-tls-reload.timer" /etc/systemd/system/gemini-tls-reload.timer
systemctl daemon-reload
systemctl enable --now gemini-cli.service nginx.service gemini-tls-reload.timer
systemctl restart gemini-cli.service
systemctl reload nginx.service
systemctl start gemini-tls-reload.service

result=$(curl --noproxy '*' --silent --show-error --max-time 15 \
    --resolve "$server_host:$https_port:127.0.0.1" --output /dev/null \
    --write-out '%{http_code} %{ssl_verify_result}' "https://$server_host:$https_port/chats")
[[ $result == '401 0' ]] || die "HTTPS check failed (status and TLS result: $result)"
printf 'Ready: https://%s:%s (unauthenticated /chats returned 401)\n' "$server_host" "$https_port"
printf 'Verify external reachability from another device and allow the HTTPS port in your firewall.\n'
if [[ $cert_mode == existing ]]; then
    printf 'Keep the existing certificate renewal configured; the hourly timer reloads Nginx.\n'
fi
