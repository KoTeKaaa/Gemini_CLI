#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
temp_dir=$(mktemp -d)
trap 'rm -rf -- "$temp_dir"' EXIT

openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
    -keyout "$temp_dir/key.pem" -out "$temp_dir/fullchain.pem" \
    -subj /CN=127.0.0.1 -addext 'subjectAltName=IP:127.0.0.1' \
    >/dev/null 2>&1
cat > "$temp_dir/server.env" <<'EOF'
API_KEY=test-key
SUPABASE_URL=https://example.supabase.co
SUPABASE_ANON_KEY=test-anon-key
TEST_USER_PASSWORD=must-not-be-copied
EOF

args=(--check --host 127.0.0.1 --cert-file "$temp_dir/fullchain.pem"
      --key-file "$temp_dir/key.pem" --env-file "$temp_dir/server.env")
"$project_dir/deploy/install.sh" "${args[@]}" | grep -q 'Checks passed'
"$project_dir/deploy/install.sh" "${args[@]}" --cert-mode existing | grep -q 'Checks passed'

if "$project_dir/deploy/install.sh" --check --cert-mode issue --host 127.0.0.1 \
    --env-file "$temp_dir/server.env" >/dev/null 2>&1; then
    echo 'Issue mode was accepted in read-only checks' >&2
    exit 1
fi
if "$project_dir/deploy/install.sh" --host 127.0.0.1 \
    --env-file "$temp_dir/server.env" </dev/null >/dev/null 2>&1; then
    echo 'Noninteractive install without certificate mode was accepted' >&2
    exit 1
fi

if "$project_dir/deploy/install.sh" "${args[@]}" --port 70000 >/dev/null 2>&1; then
    echo 'Invalid port was accepted' >&2
    exit 1
fi
if "$project_dir/deploy/install.sh" --check --host 127.0.0.2 \
    --cert-file "$temp_dir/fullchain.pem" --key-file "$temp_dir/key.pem" \
    --env-file "$temp_dir/server.env" >/dev/null 2>&1; then
    echo 'Certificate for another IP was accepted' >&2
    exit 1
fi
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
    -out "$temp_dir/other-key.pem" >/dev/null 2>&1
if "$project_dir/deploy/install.sh" --check --host 127.0.0.1 \
    --cert-file "$temp_dir/fullchain.pem" --key-file "$temp_dir/other-key.pem" \
    --env-file "$temp_dir/server.env" >/dev/null 2>&1; then
    echo 'Mismatched private key was accepted' >&2
    exit 1
fi
sed -i '/^SUPABASE_ANON_KEY=/d' "$temp_dir/server.env"
if "$project_dir/deploy/install.sh" "${args[@]}" >/dev/null 2>&1; then
    echo 'Missing environment variable was accepted' >&2
    exit 1
fi
echo 'Deployment preflight: PASS'
