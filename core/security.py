"""
Utilidades de seguridad: hashing de contraseñas y rate limiting de login.
"""
import hashlib
from django.contrib.auth.hashers import make_password, check_password
from django.core.cache import cache

# ── Contraseñas ───────────────────────────────────────────────────────────────

def _es_sha256_legacy(clave_db: str) -> bool:
    return len(clave_db) == 64 and all(c in '0123456789abcdef' for c in clave_db)


def verificar_clave(clave_plana: str, clave_db: str) -> bool:
    if _es_sha256_legacy(clave_db):
        return hashlib.sha256(clave_plana.encode()).hexdigest() == clave_db
    return check_password(clave_plana, clave_db)


def hashear_clave(clave_plana: str) -> str:
    return make_password(clave_plana)


def migrar_clave_si_legacy(usuario, clave_plana: str) -> None:
    if _es_sha256_legacy(usuario.clave):
        usuario.clave = hashear_clave(clave_plana)
        usuario.save(update_fields=['clave'])


# ── Rate limiting ─────────────────────────────────────────────────────────────

MAX_INTENTOS = 5
BLOQUEO_SEG  = 900   # 15 minutos


def _key(email: str) -> str:
    return f"login_intentos:{email.lower()}"


def esta_bloqueado(email: str) -> bool:
    return cache.get(_key(email), 0) >= MAX_INTENTOS


def registrar_intento_fallido(email: str) -> int:
    key      = _key(email)
    intentos = cache.get(key, 0) + 1
    cache.set(key, intentos, timeout=BLOQUEO_SEG)
    return intentos


def limpiar_intentos(email: str) -> None:
    cache.delete(_key(email))


def intentos_restantes(email: str) -> int:
    return max(0, MAX_INTENTOS - cache.get(_key(email), 0))
