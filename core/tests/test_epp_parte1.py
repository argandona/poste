"""
EPP, parte 1: usuarios (solo el SuperAdmin los gestiona), los roles de la
cuadrilla, el catálogo de EPP y su ingreso al almacén.
"""
import io
from decimal import Decimal

from django.core.management import call_command

from ..models import EPP, Rol, StockEPP, Usuario
from ..security import verificar_clave
from .base import BaseAPITestCase


class EPPBase(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.admin = Usuario.objects.create(
            nombre='Admin', email='admin@tecsur.pe', clave='x', empresa=self.empresa,
            rol=Rol.objects.create(id_rol=Rol.SUPERADMIN, descripcion='SuperAdmin'))
        call_command('configurar_epp', stdout=io.StringIO())


class UsuariosTests(EPPBase):

    def datos(self, **extra):
        return {'nombre': 'Pedro Operario', 'email': 'Pedro@Encossa.com',
                'rol': Rol.OPERARIO, 'empresa': self.empresa.pk,
                'clave': 'pedro2026', 'dni': '45678912',
                'fecha_nacimiento': '1990-05-17', **extra}

    def test_el_superadmin_crea_un_operario(self):
        self.auth(self.admin)
        r = self.client.post('/api/usuarios/', self.datos(), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        u = Usuario.objects.get(email='pedro@encossa.com')
        self.assertEqual((u.rol_id, u.dni, str(u.fecha_nacimiento)),
                         (Rol.OPERARIO, '45678912', '1990-05-17'))
        self.assertTrue(verificar_clave('pedro2026', u.clave))
        self.assertNotIn('clave', r.json())

    def test_nadie_mas_crea_usuarios(self):
        for quien in (self.capataz, self.encargado):
            self.auth(quien)
            r = self.client.post('/api/usuarios/', self.datos(), format='json')
            self.assertEqual(r.status_code, 403, quien.email)
        self.assertFalse(Usuario.objects.filter(dni='45678912').exists())

    def test_nadie_mas_edita_usuarios(self):
        self.auth(self.capataz)
        r = self.client.patch(f'/api/usuarios/{self.capataz.pk}/',
                              {'rol': Rol.ENCARGADO_ALMACEN}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_no_se_borran(self):
        self.auth(self.admin)
        r = self.client.delete(f'/api/usuarios/{self.capataz.pk}/')
        self.assertEqual(r.status_code, 405)

    def test_dni_repetido(self):
        self.capataz.dni = '45678912'
        self.capataz.save()
        self.auth(self.admin)
        r = self.client.post('/api/usuarios/', self.datos(), format='json')
        self.assertEqual(r.status_code, 400)

    def test_clave_obligatoria_al_crear_y_opcional_al_editar(self):
        self.auth(self.admin)
        r = self.client.post('/api/usuarios/', self.datos(clave=''), format='json')
        self.assertEqual(r.status_code, 400)
        clave_antes = self.capataz.clave
        r = self.client.patch(f'/api/usuarios/{self.capataz.pk}/',
                              {'dni': '11112222'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.capataz.refresh_from_db()
        self.assertEqual((self.capataz.dni, self.capataz.clave),
                         ('11112222', clave_antes))

    def test_resetear_clave(self):
        self.auth(self.admin)
        r = self.client.post(f'/api/usuarios/{self.capataz.pk}/resetear_clave/',
                             {'clave': 'nueva123'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.capataz.refresh_from_db()
        self.assertTrue(verificar_clave('nueva123', self.capataz.clave))
        self.auth(self.capataz)
        r = self.client.post(f'/api/usuarios/{self.encargado.pk}/resetear_clave/',
                             {'clave': 'nueva123'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_la_lista_trae_dni_y_no_se_corta_en_20(self):
        for i in range(25):
            Usuario.objects.create(nombre=f'Op {i:02d}', email=f'op{i}@x.com',
                                   clave='x', empresa=self.empresa,
                                   rol_id=Rol.OPERARIO)
        self.auth(self.capataz)
        r = self.client.get('/api/usuarios/').json()
        self.assertGreaterEqual(len(r['results']), 28)
        self.assertIn('dni', r['results'][0])


class CatalogoEPPTests(EPPBase):

    def test_el_catalogo_inicial(self):
        self.assertEqual(EPP.objects.count(), 31)
        bota = EPP.objects.get(codigo='BOTA-DIEL-42')
        self.assertEqual((bota.descripcion, bota.unidad, bota.talla),
                         ('BOTAS DIELECTRICAS', 'PAR', '42'))
        self.assertEqual(EPP.objects.get(codigo='CASCO-AZUL').talla, '')
        self.assertTrue(Rol.objects.filter(id_rol=Rol.OPERARIO).exists())
        self.assertTrue(Rol.objects.filter(id_rol=Rol.AYUDANTE).exists())

    def test_no_pisa_lo_corregido(self):
        EPP.objects.filter(codigo='CASCO-AZUL').update(precio='25.50')
        call_command('configurar_epp', stdout=io.StringIO())
        self.assertEqual(EPP.objects.get(codigo='CASCO-AZUL').precio,
                         Decimal('25.50'))

    def test_el_almacen_edita_y_los_demas_solo_ven(self):
        casco = EPP.objects.get(codigo='CASCO-AZUL')
        self.auth(self.capataz)
        self.assertEqual(self.client.get('/api/epp/').status_code, 200)
        r = self.client.patch(f'/api/epp/{casco.pk}/', {'precio': '30'},
                              format='json')
        self.assertEqual(r.status_code, 403)
        self.auth(self.encargado)
        r = self.client.patch(f'/api/epp/{casco.pk}/', {'precio': '30'},
                              format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.post('/api/epp/', {
            'codigo': 'arnes-1', 'descripcion': 'ARNES', 'unidad': 'UND',
            'talla': '', 'precio': '80'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(EPP.objects.filter(codigo='ARNES-1').exists())


class IngresoEPPTests(EPPBase):

    def ingresar(self, usuario, cantidad=10):
        self.auth(usuario)
        bota = EPP.objects.get(codigo='BOTA-DIEL-42')
        return bota, self.client.post('/api/ingresos-epp/', {
            'almacen': self.almacen.pk, 'fecha': '2026-10-05',
            'observacion': 'Compra octubre',
            'detalles': [{'epp': bota.pk, 'cantidad': cantidad}]}, format='json')

    def test_el_ingreso_suma_al_stock(self):
        bota, r = self.ingresar(self.encargado)
        self.assertEqual(r.status_code, 201, r.content)
        self.ingresar(self.encargado, 5)
        self.assertEqual(StockEPP.objects.get(epp=bota).cantidad, Decimal('15'))
        self.auth(self.capataz)
        catalogo = self.client.get('/api/epp/').json()['results']
        fila = next(e for e in catalogo if e['codigo'] == 'BOTA-DIEL-42')
        self.assertEqual(Decimal(str(fila['stock'])), Decimal('15'))

    def test_solo_el_almacen_ingresa(self):
        bota, r = self.ingresar(self.capataz)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(StockEPP.objects.exists())

    def test_cantidad_positiva(self):
        _, r = self.ingresar(self.encargado, 0)
        self.assertEqual(r.status_code, 400)
