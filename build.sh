#!/usr/bin/env bash
# Script de build para Render.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
# Tabla de caché (bloqueo de login). Es idempotente: no falla si ya existe.
python manage.py createcachetable
