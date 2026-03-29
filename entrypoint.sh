#!/bin/bash
set -e

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Daphne (ASGI)..."
exec daphne \
    -b 0.0.0.0 \
    -p 8000 \
    --proxy-headers \
    mediap.asgi:application