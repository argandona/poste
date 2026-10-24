"""
Los catálogos son de todas las empresas: materiales, partidas con su precio,
actividades y tipos de trabajo. Verlos puede cualquiera con sesión;
cambiarlos, solo el SuperAdmin (ni el Coordinador). Materiales y partidas no
se borran.
"""
from ..models import (Actividad, Empresa, ManoDeObra, Material, Rol,
                      TipoTrabajo, Usuario)
from .base import BaseAPITestCase


class CatalogosProtegidosTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.admin = Usuario.objects.create(
            nombre='Admin', email='admin@tecsur.pe', clave='x', empresa=self.empresa,
            rol=Rol.objects.create(id_rol=Rol.SUPERADMIN, descripcion='SuperAdmin'))
        self.coordinador = Usuario.objects.create(
            nombre='Coordinador', email='coord@tecsur.pe', clave='x',
            empresa=self.empresa,
            rol=Rol.objects.create(id_rol=Rol.COORDINADOR, descripcion='Coordinador'))
        # Un usuario de otra empresa: el caso del cliente nuevo.
        otra = Empresa.objects.create(nombre='CLIENTE', ruc='20600000009')
        self.de_otra = Usuario.objects.create(
            nombre='Capataz Cliente', email='cap@cliente.pe', clave='x',
            empresa=otra, rol=self.rol_capataz)
        self.partida = ManoDeObra.objects.create(
            partida='*090251', descripcion='REFORZAMIENTO', precio='100.00')
        self.mat = Material.objects.create(
            matricula='9990001', descripcion='CEMENTO', precio='30')
        self.actividad = Actividad.objects.create(nombre='Actividad X')
        self.tipo = TipoTrabajo.objects.create(nombre='Tipo X')

    # ── Partidas y precios ──────────────────────────────────────────────────

    def test_nadie_mas_cambia_el_precio_de_una_partida(self):
        for quien in (self.capataz, self.encargado, self.coordinador, self.de_otra):
            self.auth(quien)
            r = self.client.patch(f'/api/mano-de-obra/{self.partida.pk}/',
                                  {'precio': '1.00'}, format='json')
            self.assertEqual(r.status_code, 403, quien.email)
        self.partida.refresh_from_db()
        self.assertEqual(str(self.partida.precio), '100.00')

    def test_nadie_mas_crea_partidas(self):
        self.auth(self.de_otra)
        r = self.client.post('/api/mano-de-obra/', {
            'partida': '*000001', 'descripcion': 'X', 'precio': '1'},
            format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(ManoDeObra.objects.filter(partida='*000001').exists())

    def test_el_superadmin_cambia_el_precio(self):
        self.auth(self.admin)
        r = self.client.patch(f'/api/mano-de-obra/{self.partida.pk}/',
                              {'precio': '120.00'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.partida.refresh_from_db()
        self.assertEqual(str(self.partida.precio), '120.00')

    def test_las_partidas_no_se_borran(self):
        for quien in (self.admin, self.de_otra):
            self.auth(quien)
            r = self.client.delete(f'/api/mano-de-obra/{self.partida.pk}/')
            self.assertEqual(r.status_code, 405, quien.email)
        self.assertTrue(ManoDeObra.objects.filter(pk=self.partida.pk).exists())

    def test_todos_ven_las_partidas(self):
        self.auth(self.de_otra)
        r = self.client.get('/api/mano-de-obra/')
        self.assertEqual(r.status_code, 200)

    # ── Materiales ──────────────────────────────────────────────────────────

    def test_nadie_mas_cambia_ni_crea_materiales(self):
        for quien in (self.capataz, self.encargado, self.coordinador, self.de_otra):
            self.auth(quien)
            r = self.client.patch(f'/api/materiales/{self.mat.pk}/',
                                  {'descripcion': 'OTRA COSA'}, format='json')
            self.assertEqual(r.status_code, 403, quien.email)
            r = self.client.post('/api/materiales/', {
                'matricula': '9990002', 'descripcion': 'X', 'precio': '1'},
                format='json')
            self.assertEqual(r.status_code, 403, quien.email)
        self.mat.refresh_from_db()
        self.assertEqual(self.mat.descripcion, 'CEMENTO')
        self.assertFalse(Material.objects.filter(matricula='9990002').exists())

    def test_el_superadmin_cambia_un_material(self):
        self.auth(self.admin)
        r = self.client.patch(f'/api/materiales/{self.mat.pk}/',
                              {'descripcion': 'CEMENTO TIPO I'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_los_materiales_no_se_borran(self):
        for quien in (self.admin, self.de_otra):
            self.auth(quien)
            r = self.client.delete(f'/api/materiales/{self.mat.pk}/')
            self.assertEqual(r.status_code, 405, quien.email)
        self.assertTrue(Material.objects.filter(pk=self.mat.pk).exists())

    def test_todos_ven_los_materiales(self):
        self.auth(self.de_otra)
        r = self.client.get('/api/materiales/')
        self.assertEqual(r.status_code, 200)

    # ── Actividades y tipos de trabajo ──────────────────────────────────────

    def test_sin_ser_superadmin_no_se_editan_ni_borran(self):
        for quien in (self.capataz, self.encargado, self.coordinador,
                      self.de_otra):
            self.auth(quien)
            for ruta in (f'/api/actividades/{self.actividad.pk}/',
                         f'/api/tipos-trabajo/{self.tipo.pk}/'):
                r = self.client.patch(ruta, {'nombre': 'Cambiado'}, format='json')
                self.assertIn(r.status_code, (403, 404), (quien.email, ruta))
                r = self.client.delete(ruta)
                self.assertIn(r.status_code, (403, 404), (quien.email, ruta))
        self.assertEqual(Actividad.objects.get(pk=self.actividad.pk).nombre,
                         'Actividad X')
        self.assertEqual(TipoTrabajo.objects.get(pk=self.tipo.pk).nombre,
                         'Tipo X')

    def test_el_coordinador_no_crea_ni_configura(self):
        self.auth(self.coordinador)
        r = self.client.post('/api/actividades/', {'nombre': 'Nueva'},
                             format='json')
        self.assertEqual(r.status_code, 403)
        r = self.client.post('/api/tipos-trabajo/', {'nombre': 'Nuevo'},
                             format='json')
        self.assertEqual(r.status_code, 403)
        for accion in ('set_actividades', 'set_mano_de_obra', 'set_materiales'):
            r = self.client.post(f'/api/tipos-trabajo/{self.tipo.pk}/{accion}/',
                                 {'ids': []}, format='json')
            self.assertEqual(r.status_code, 403, accion)
        self.assertFalse(Actividad.objects.filter(nombre='Nueva').exists())

    def test_el_superadmin_configura(self):
        self.auth(self.admin)
        r = self.client.patch(f'/api/tipos-trabajo/{self.tipo.pk}/',
                              {'nombre': 'Tipo Y'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.post('/api/actividades/', {'nombre': 'Nueva'},
                             format='json')
        self.assertEqual(r.status_code, 201, r.content)
        r = self.client.post(f'/api/tipos-trabajo/{self.tipo.pk}/set_mano_de_obra/',
                             {'ids': [self.partida.pk]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
