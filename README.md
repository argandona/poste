# TECSUR — Backend (poste)

API REST del sistema de gestión de almacén y liquidación de TECSUR.
Django + Django REST Framework + PostgreSQL. Preparado para desplegar en Render.

## Stack
- Django 6 · DRF · SimpleJWT (login contra la tabla `usuario`)
- PostgreSQL · gunicorn · whitenoise
- Autenticación por rol: SuperAdmin, Coordinador, Encargado, Capataz, Liquidador, Encargado de Almacén

## Correr local
```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
# crear .env con DB_* (ver .env.example)
python manage.py migrate
python manage.py seed_prueba
python manage.py runserver
```

## Deploy en Render
El repo incluye `render.yaml` (Blueprint): crea el web service + PostgreSQL.
Después del deploy, correr en la Shell del servicio:
```bash
python manage.py seed_prueba
```

Usuarios de prueba (clave `tecsur123`): `coordinador@`, `capataz@`, `almacen@`,
`liquidador@`, `encargado@`, `admin@` `tecsur.pe`.
