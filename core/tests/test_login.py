"""
Login y bloqueo por intentos fallidos.

El contador de intentos vive en la caché (core/security.py), así que estos tests
también verifican que el backend de caché configurado sirve para eso.
"""
from django.core.cache import cache

from ..models import Empresa, Rol, Usuario
from ..security import MAX_INTENTOS, hashear_clave
from .base import BaseAPITestCase


class LoginTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        cache.clear()
        self.clave = "tecsur123"
        self.capataz.clave = hashear_clave(self.clave)
        self.capataz.save(update_fields=["clave"])

    def login(self, clave):
        return self.client.post(
            "/api/auth/login/",
            {"email": self.capataz.email, "clave": clave},
            format="json",
        )

    def test_login_correcto_devuelve_tokens_y_usuario(self):
        resp = self.login(self.clave)

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)
        self.assertEqual(resp.data["usuario"]["rol_id"], Rol.CAPATAZ)
        self.assertNotIn("clave", resp.data["usuario"])

    def test_clave_incorrecta_devuelve_401(self):
        resp = self.login("incorrecta")

        self.assertEqual(resp.status_code, 401)

    def test_se_bloquea_tras_demasiados_intentos_fallidos(self):
        for _ in range(MAX_INTENTOS):
            self.login("incorrecta")

        resp = self.login("incorrecta")
        self.assertEqual(resp.status_code, 429)

        # Y el bloqueo aplica incluso con la clave correcta.
        resp = self.login(self.clave)
        self.assertEqual(resp.status_code, 429)

    def test_un_login_correcto_limpia_los_intentos(self):
        for _ in range(MAX_INTENTOS - 1):
            self.login("incorrecta")

        self.assertEqual(self.login(self.clave).status_code, 200)

        # Contador reseteado: vuelve a haber margen antes del bloqueo.
        for _ in range(MAX_INTENTOS - 1):
            self.assertEqual(self.login("incorrecta").status_code, 401)

    def test_usuario_inactivo_no_puede_entrar(self):
        self.capataz.activo = False
        self.capataz.save(update_fields=["activo"])

        self.assertEqual(self.login(self.clave).status_code, 401)

    def test_clave_legacy_sha256_se_migra_al_entrar(self):
        import hashlib

        empresa = Empresa.objects.get(pk=self.empresa.pk)
        legacy = Usuario.objects.create(
            nombre="Viejo", rol=self.rol_capataz, empresa=empresa,
            email="legacy@tecsur.pe",
            clave=hashlib.sha256(self.clave.encode()).hexdigest())

        resp = self.client.post(
            "/api/auth/login/",
            {"email": legacy.email, "clave": self.clave}, format="json")

        self.assertEqual(resp.status_code, 200, resp.data)
        legacy.refresh_from_db()
        self.assertTrue(legacy.clave.startswith("pbkdf2_"))


class EndpointsProtegidosTests(BaseAPITestCase):

    def test_sin_token_no_se_accede_a_la_api(self):
        self.assertEqual(self.client.get("/api/pedidos/").status_code, 401)

    def test_token_invalido_no_se_acepta(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer no-es-un-token")

        self.assertEqual(self.client.get("/api/pedidos/").status_code, 401)
