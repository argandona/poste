"""El aviso de actualización: el SuperAdmin publica versiones y la app
pregunta por la última, incluso sin sesión o con el token vencido."""
from ..models import Rol, Usuario, VersionApp
from .base import BaseAPITestCase

URL = '/api/version-app/'
APK = 'https://firebasestorage.googleapis.com/v0/b/x/o/tecsur.apk?alt=media'


class VersionAppTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.super = Usuario.objects.create(
            nombre='Super', email='super@tecsur.pe', clave='x', empresa=self.empresa,
            rol=Rol.objects.create(id_rol=Rol.SUPERADMIN, descripcion='SuperAdmin'))

    def publicar(self, codigo, obligatoria=False, **extra):
        self.auth(self.super)
        return self.client.post(URL, {
            'codigo': codigo, 'nombre': f'1.0.{codigo}', 'url_apk': APK,
            'notas': 'Grass en con vereda', 'obligatoria': obligatoria, **extra,
        }, format='json')

    def test_el_superadmin_publica_y_la_app_ve_la_ultima_sin_sesion(self):
        self.assertEqual(self.publicar(3, obligatoria=True).status_code, 201)
        self.assertEqual(self.publicar(4).status_code, 201)
        self.client.credentials()
        r = self.client.get(URL + 'ultima/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['codigo'], 4)
        self.assertEqual(r.json()['url_apk'], APK)
        self.assertEqual(r.json()['minima'], 3)
        self.assertEqual(VersionApp.objects.get(codigo=4).usuario, self.super)

    def test_con_token_vencido_igual_contesta(self):
        self.publicar(3)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer token-vencido')
        r = self.client.get(URL + 'ultima/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['minima'], 0)

    def test_sin_versiones_no_hay_aviso(self):
        self.assertEqual(self.client.get(URL + 'ultima/').json(), {})

    def test_solo_el_superadmin_publica_lista_y_borra(self):
        v = self.publicar(3).json()
        self.auth(self.encargado)
        self.assertEqual(self.client.post(URL, {
            'codigo': 9, 'nombre': '1.0.9', 'url_apk': APK}, format='json').status_code, 403)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.client.delete(f"{URL}{v['id_version']}/").status_code, 403)
        self.auth(self.super)
        self.assertEqual(self.client.get(URL).json()[0]['codigo'], 3)
        self.assertEqual(self.client.delete(f"{URL}{v['id_version']}/").status_code, 204)

    def test_el_enlace_debe_ser_https_y_el_codigo_unico(self):
        self.assertEqual(self.publicar(3, url_apk='http://x.com/a.apk').status_code, 400)
        self.assertEqual(self.publicar(3).status_code, 201)
        self.assertEqual(self.publicar(3).status_code, 400)
