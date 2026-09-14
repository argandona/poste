#!/usr/bin/env bash
# Pasa los datos de una base de Render a otra, por ejemplo de la gratuita a una
# de pago. Va por el ORM de Django, así que no importa que la versión de
# pg_dump de esta máquina no coincida con la del servidor.
#
# Uso:
#   1. Copia env.migracion.ejemplo a .env.migracion y pon ahí las dos URLs
#      externas, la de la base vieja y la de la nueva. Ese archivo no se sube.
#   2. bash migrar_base.sh
#
# No borra nada del origen: solo lee. Si algo sale mal, la base vieja sigue
# intacta y basta con no cambiar la variable del servicio web.
set -o errexit
set -o pipefail

cd "$(dirname "$0")"

if [ ! -f .env.migracion ]; then
  echo "Falta .env.migracion. Copia env.migracion.ejemplo y complétalo." >&2
  exit 1
fi

# shellcheck disable=SC1091
source .env.migracion

if [ -z "${ORIGEN:-}" ] || [ -z "${DESTINO:-}" ]; then
  echo "Faltan ORIGEN o DESTINO en .env.migracion." >&2
  exit 1
fi

PY=venv/Scripts/python.exe
[ -x "$PY" ] || PY=python

RESPALDO="respaldo_$(date +%Y%m%d_%H%M%S).json"

echo "── 1. Contando lo que hay en la base vieja"
DATABASE_URL="$ORIGEN" "$PY" manage.py shell -c "
from django.apps import apps
for m in apps.get_app_config('core').get_models():
    n = m.objects.count()
    if n: print(f'   {m.__name__:28} {n}')
"

echo "── 2. Sacando el respaldo en $RESPALDO"
# Se excluyen las tablas internas de Django: la base nueva las crea al migrar,
# y copiarlas choca con las que ya vienen.
DATABASE_URL="$ORIGEN" "$PY" manage.py dumpdata \
  --exclude contenttypes --exclude auth.permission \
  --exclude admin.logentry --exclude sessions.session \
  --natural-foreign --indent 2 > "$RESPALDO"
echo "   $(wc -c < "$RESPALDO") bytes"

echo "── 3. Creando las tablas en la base nueva"
DATABASE_URL="$DESTINO" "$PY" manage.py migrate --no-input

echo "── 4. Cargando los datos en la base nueva"
DATABASE_URL="$DESTINO" "$PY" manage.py loaddata "$RESPALDO"

echo "── 5. Contando lo que quedó en la base nueva"
DATABASE_URL="$DESTINO" "$PY" manage.py shell -c "
from django.apps import apps
for m in apps.get_app_config('core').get_models():
    n = m.objects.count()
    if n: print(f'   {m.__name__:28} {n}')
"

echo
echo "Listo. Compara las dos listas: tienen que dar igual."
echo "Recién entonces cambia DATABASE_URL del servicio web en Render por la"
echo "URL INTERNA de la base nueva, y vuelve a desplegar."
echo "Guarda $RESPALDO: es tu copia de seguridad."
