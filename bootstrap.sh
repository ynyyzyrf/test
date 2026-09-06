#!/usr/bin/env bash
# Intel stack bootstrap: gateway + TrendRadar timer + ai-daily timers
set -euo pipefail

PAYLOAD_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- gateway ---
mkdir -p /opt/intel/gateway
cp "$PAYLOAD_DIR/gateway/gateway.py" /opt/intel/gateway/gateway.py
if [ ! -f /opt/intel/gateway/.token ]; then
  python3 -c "import secrets; print(secrets.token_urlsafe(24))" > /opt/intel/gateway/.token
  chmod 600 /opt/intel/gateway/.token
fi

# --- ai-daily config + .env placeholder ---
cp "$PAYLOAD_DIR/aidaily/config.json" /opt/intel/ai-daily/config.json
if [ ! -f /opt/intel/ai-daily/.env ]; then
  printf 'DEEPSEEK_API_KEY=\nGITHUB_TOKEN=\nJINA_API_KEY=\n' > /opt/intel/ai-daily/.env
fi

# --- systemd units ---
cat > /etc/systemd/system/intel-gateway.service <<'UNIT'
[Unit]
Description=Intel gateway for MAG workbench
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/intel/gateway/gateway.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

mkdir -p /opt/intel/bin
cat > /opt/intel/bin/tr-run.sh <<'SH'
#!/usr/bin/env bash
export PATH=/root/.local/bin:$PATH
export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
cd /opt/intel/TrendRadar
exec uv run python -m trendradar
SH
chmod +x /opt/intel/bin/tr-run.sh

cat > /etc/systemd/system/trendradar.service <<'UNIT'
[Unit]
Description=TrendRadar crawl cycle
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/intel/bin/tr-run.sh
TimeoutStartSec=900
UNIT

cat > /etc/systemd/system/trendradar.timer <<'UNIT'
[Unit]
Description=Run TrendRadar hourly

[Timer]
OnCalendar=hourly
RandomizedDelaySec=120
Persistent=true

[Install]
WantedBy=timers.target
UNIT

cat > /opt/intel/bin/aidaily-run.sh <<'SH'
#!/usr/bin/env bash
export PATH=/root/.local/bin:$PATH
export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
cd /opt/intel/ai-daily
exec uv run python -m src.main "$@"
SH
chmod +x /opt/intel/bin/aidaily-run.sh

cat > /etc/systemd/system/aidaily-fetch.service <<'UNIT'
[Unit]
Description=ai-daily fetch cycle
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/intel/bin/aidaily-run.sh fetch
TimeoutStartSec=1800
UNIT

cat > /etc/systemd/system/aidaily-fetch.timer <<'UNIT'
[Unit]
Description=Run ai-daily fetch hourly

[Timer]
OnCalendar=hourly
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
UNIT

cat > /etc/systemd/system/aidaily-push.service <<'UNIT'
[Unit]
Description=ai-daily push cycle (daily report)
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/intel/bin/aidaily-run.sh push
TimeoutStartSec=1800
UNIT

cat > /etc/systemd/system/aidaily-push.timer <<'UNIT'
[Unit]
Description=Run ai-daily push at 08:00 and 17:00 CST

[Timer]
OnCalendar=*-*-* 08,17:00:00 Asia/Shanghai
RandomizedDelaySec=60
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now intel-gateway.service
systemctl enable --now trendradar.timer
systemctl enable --now aidaily-fetch.timer
systemctl enable --now aidaily-push.timer

echo "=== token ==="
cat /opt/intel/gateway/.token
echo "=== units ==="
systemctl is-active intel-gateway.service
systemctl list-timers --no-pager | grep -E 'trendradar|aidaily' || true
