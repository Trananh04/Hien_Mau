#!/bin/sh
set -e

# Chỉ chạy migrate/seed khi khởi động server, không chạy khi gọi lệnh khác (test, shell...)
if [ "$1" = "gunicorn" ]; then
  python manage.py migrate --noinput
  python manage.py createcachetable
  python manage.py collectstatic --noinput >/dev/null
  if [ "${SEED_DEMO:-0}" = "1" ]; then
    python manage.py seed_demo
  fi
fi

exec "$@"
