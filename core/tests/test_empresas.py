"""
Empresas: cada uno ve la suya, solo el SuperAdmin las crea y edita, y no se
borran (se desactivan).
"""
from ..models import Empresa, Rol, Usuario
from .base import BaseAPITestCase


class EmpresasTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.admin = Usuario.objects.create(
            nombre='Admin', email='admin@tecsur.pe', clave='x', empresa=self.empresa,
            rol=Rol.objects.create(id_rol=Rol.SUPERADMIN, descripcion='SuperAdmin'))
        self.otra = Empresa.objects.create(nombre='ENCOSSA', ruc='20500000002')

    def datos(self, **extra):
        return {'nombre': 'Contratista Sur', 'ruc': '20600000003',
                'direccion': 'Av. Lima 123', 'telefono': '999888777',
                'email': 'sur@contratista.pe', 'activo': True, **extra}

    def test_el_superadmin_crea_una_empresa(self):
        self.auth(self.admin)
        r = self.client.post('/api/empresas/', self.datos(), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(Empresa.objects.filter(ruc='20600000003').exists())

    def test_el_superadmin_la_edita_y_la_desactiva(self):
        self.auth(self.admin)
        r = self.client.patch(f'/api/empresas/{self.otra.pk}/',
                              {'telefono': '014445566', 'activo': False},
                              format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.otra.refresh_from_db()
        self.assertEqual((self.otra.telefono, self.otra.activo),
                         ('014445566', False))

    def test_nadie_mas_crea_empresas(self):
        for quien in (self.capataz, self.encargado):
            self.auth(quien)
            r = self.client.post('/api/empresas/', self.datos(), format='json')
            self.assertEqual(r.status_code, 403, quien.email)
        self.assertFalse(Empresa.objects.filter(ruc='20600000003').exists())

    def test_nadie_mas_edita_ni_su_propia_empresa(self):
        self.auth(self.capataz)
        r = self.client.patch(f'/api/empresas/{self.empresa.pk}/',
                              {'nombre': 'Otra cosa'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.nombre, 'TECSUR')

    def test_no_se_borran(self):
        self.auth(self.admin)
        r = self.client.delete(f'/api/empresas/{self.otra.pk}/')
        self.assertEqual(r.status_code, 405)
        self.assertTrue(Empresa.objects.filter(pk=self.otra.pk).exists())

    def test_ruc_repetido(self):
        self.auth(self.admin)
        r = self.client.post('/api/empresas/', self.datos(ruc='20500000002'),
                             format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['ruc'], ['Ya hay una empresa con ese RUC.'])

    def test_cada_uno_ve_la_suya_y_el_superadmin_todas(self):
        self.auth(self.capataz)
        r = self.client.get('/api/empresas/')
        filas = r.json().get('results', r.json())
        self.assertEqual([e['nombre'] for e in filas], ['TECSUR'])
        self.auth(self.admin)
        r = self.client.get('/api/empresas/')
        filas = r.json().get('results', r.json())
        self.assertEqual([e['nombre'] for e in filas], ['ENCOSSA', 'TECSUR'])
