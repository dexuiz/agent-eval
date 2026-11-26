#!/usr/bin/env bash
set -euo pipefail
umask 077

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
install_dir="$HOME/.local/share/evalharness-live"
service_dir="$HOME/.config/systemd/user"
systemctl --user show-environment >/dev/null
mkdir -p -- "$install_dir/evalharness" "$service_dir"

if [[ ! -f "$install_dir/keys.env" ]]; then
    read -rs -p 'OpenRouter API key: ' openrouter_key
    printf '\n'
    read -rs -p 'Anthropic API key: ' anthropic_key
    printf '\n'
    if [[ ! $openrouter_key =~ ^[A-Za-z0-9_-]+$ || ! $anthropic_key =~ ^[A-Za-z0-9_-]+$ ]]; then
        echo 'Enter both API keys without spaces or quotes.' >&2
        exit 2
    fi
    printf 'OPENROUTER_API_KEY=%s\nANTHROPIC_API_KEY=%s\n' \
        "$openrouter_key" "$anthropic_key" > "$install_dir/keys.env"
    unset openrouter_key anthropic_key
fi

cp -- "$root"/evalharness/*.py "$install_dir/evalharness/"
cp -- "$root/models.json" "$root/scripts/live_worker.py" "$install_dir/"
printf '%s\n' "$root" > "$install_dir/workspace.txt"
cat > "$service_dir/evalharness-live.service" <<'UNIT'
[Unit]
Description=Eval harness live test worker

[Service]
ExecStart=/usr/bin/python3 -I %h/.local/share/evalharness-live/live_worker.py
EnvironmentFile=%h/.local/share/evalharness-live/keys.env
UMask=0077
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable evalharness-live.service
systemctl --user restart evalharness-live.service
systemctl --user is-active evalharness-live.service
