#!/usr/bin/env bash
# Script de build para Render.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
# Tabla de caché (bloqueo de login). Es idempotente: no falla si ya existe.
python manage.py createcachetable

# Catálogos de referencia. Son idempotentes y no dependen de datos de prueba:
# es la única forma de mantenerlos al día en Render, que en el plan gratuito
# no da consola para correr comandos a mano.
python manage.py cargar_recuperos
python manage.py configurar_tipos_viento
python manage.py configurar_cabria
# Cabria subterráneo comparte dos tipos de trabajo con la aérea, así que va
# después: los tipos los crea el comando de arriba.
python manage.py configurar_cabria_subterraneo
# La reforma hereda los tipos de trabajo de la aérea, así que va después.
python manage.py configurar_reforma_cabria
# Qué se cobra una vez por SST: lo que sale del plano.
python manage.py configurar_partidas_de_sst
