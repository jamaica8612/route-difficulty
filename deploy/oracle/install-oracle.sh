#!/bin/sh
set -eu

stack_dir="/opt/stacks/route-difficulty"
available_kb=$(df -Pk /opt | awk 'NR==2 {print $4}')
available_mem_kb=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
if [ "${available_kb:-0}" -lt 10485760 ]; then
  echo "At least 10 GB of free disk is required under /opt." >&2
  exit 1
fi
if [ "${available_mem_kb:-0}" -lt 2097152 ]; then
  echo "At least 2 GB of available memory is required for the on-server builder." >&2
  exit 1
fi

install -d -o root -g root -m 0755 "$stack_dir" "$stack_dir/input" "$stack_dir/work" "$stack_dir/published/data"
install -o root -g root -m 0644 deploy/oracle/compose.yaml "$stack_dir/compose.yaml"
install -o root -g root -m 0755 deploy/oracle/run-data-update.sh "$stack_dir/run-data-update.sh"
install -o root -g root -m 0755 deploy/oracle/update-web.sh "$stack_dir/update-web.sh"

if [ ! -f "$stack_dir/deploy.env" ]; then
  install -o root -g root -m 0600 deploy/oracle/deploy.env.example "$stack_dir/deploy.env"
fi
if [ ! -f "$stack_dir/builder.env" ]; then
  install -o root -g root -m 0600 deploy/oracle/builder.env.example "$stack_dir/builder.env"
fi
if [ ! -f "$stack_dir/published/data/manifest.json" ]; then
  cp -a public/data/. "$stack_dir/published/data/"
fi

install -o root -g root -m 0644 deploy/oracle/route-difficulty-data.service /etc/systemd/system/route-difficulty-data.service
install -o root -g root -m 0644 deploy/oracle/route-difficulty-data.timer /etc/systemd/system/route-difficulty-data.timer
install -o root -g root -m 0644 deploy/oracle/route-difficulty-web.service /etc/systemd/system/route-difficulty-web.service
install -o root -g root -m 0644 deploy/oracle/route-difficulty-web.timer /etc/systemd/system/route-difficulty-web.timer

docker compose -f "$stack_dir/compose.yaml" --env-file "$stack_dir/deploy.env" config >/dev/null
systemd-analyze verify /etc/systemd/system/route-difficulty-data.service /etc/systemd/system/route-difficulty-data.timer
systemd-analyze verify /etc/systemd/system/route-difficulty-web.service /etc/systemd/system/route-difficulty-web.timer
systemctl daemon-reload

echo "Stack files installed. Set builder.env, add the Caddy site, then start the web container and timers."
