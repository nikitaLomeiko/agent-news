#!/usr/bin/env bash
set -eu
cd /home/admin/projects/AI/agent-news

expected_version=$(/usr/bin/python3 -c 'import server; print(server.APP_VERSION)')
health_json=$(/usr/bin/curl --silent --fail --max-time 1 http://127.0.0.1:8765/api/health 2>/dev/null || true)
running_version=$(printf '%s' "$health_json" | /usr/bin/python3 -c 'import json, sys; print(json.load(sys.stdin).get("version", ""))' 2>/dev/null || true)

if [ -n "$health_json" ] && [ "$running_version" != "$expected_version" ]; then
  /usr/bin/pkill -u "$(id -u)" -f '^/usr/bin/python3 /home/admin/projects/AI/agent-news/server.py' 2>/dev/null || true
  for _attempt in 1 2 3 4 5 6 7 8 9 10; do
    if ! /usr/bin/curl --silent --fail --max-time 1 http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
      break
    fi
    sleep 0.1
  done
fi

exec /usr/bin/python3 /home/admin/projects/AI/agent-news/server.py --open
