#!/bin/sh
# Prepare the demo database, create the demo staff user once, then run the server.
set -e

python demo/manage.py migrate --noinput

# DJANGO_SUPERUSER_USERNAME / _PASSWORD / _EMAIL come from docker-compose.yml.
# createsuperuser fails if the user already exists (on a restart): that is fine.
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
  python demo/manage.py createsuperuser --noinput || true
fi

exec "$@"
