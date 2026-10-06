"""
Asignación de EPP: el SuperAdmin entrega EPP a un trabajador sin pedido. Se
descuenta del almacén en el acto, queda como entrega aprobada (sale en Mis
EPP y en el historial) y al trabajador le llega el aviso.
"""
import io
from decimal import Decimal
from unittest import mock

from django.core.management import call_command

from ..historial_epp import armar_historial
from ..models import EPP, PedidoEPP, Rol, StockEPP, Usuario
from .base import BaseAPITestCase

URL = '/api/pedidos-epp/asignar/'


class AsignacionEPPTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        call_command('configurar_epp', stdout=io.StringIO())
        self.admin = Usuario.objects.create(
            nombre='Admin', email='admin@tecsur.pe', clave='x', empresa=self.empresa,
            rol=Rol.objects.create(id_rol=Rol.SUPERADMIN, descripcion='SuperAdmin'))
        self.pedro = Usuario.objects.create(
            nombre='Pedro Operario', email='pedro@x.com', clave='x',
            empresa=self.empresa, fcm_token='tok-pedro',
            rol=Rol.objects.get(id_rol=Rol.OPERARIO))
        self.bota = EPP.objects.get(codigo='BOTA-DIEL-42')
        StockEPP.objects.create(almacen=self.almacen, epp=self.bota, cantidad=3)

    def asignar(self, quien=None, **datos):
        self.auth(quien or self.admin)
        cuerpo = {'usuario': self.pedro.pk, 'tipo': 'nuevo',
                  'detalles': [{'epp': self.bota.pk, 'cantidad': 1}], **datos}
        with mock.patch('core.fcm.send_notification') as avisar:
            r = self.client.post(URL, cuerpo, format='json')
        return r, avisar

    def test_se_entrega_se_descuenta_y_avisa(self):
        r, avisar = self.asignar(observacion='Ingreso a cuadrilla')
        self.assertEqual(r.status_code, 201, r.content)
        p = r.json()
        self.assertEqual((p['estado'], p['origen'], p['usuario_nombre']),
                         ('aprobado', 'asignacion', 'Pedro Operario'))
        self.assertEqual(StockEPP.objects.get(epp=self.bota).cantidad, Decimal('2'))
        self.assertEqual(avisar.call_args.args[0], ['tok-pedro'])
        self.assertEqual(avisar.call_args.kwargs['title'], 'Te asignaron EPP')

    def test_sale_en_mis_epp_y_en_el_historial(self):
        self.asignar()
        self.auth(self.pedro)
        d = self.client.get('/api/pedidos-epp/mis_epp/').json()
        self.assertEqual([e['codigo'] for e in d['epp']], ['BOTA-DIEL-42'])
        [fila] = armar_historial()
        self.assertEqual((fila['trabajador'], len(fila['entregas'])),
                         ('Pedro Operario', 1))

    def test_solo_el_superadmin(self):
        for quien in (self.encargado, self.capataz, self.pedro):
            r, _ = self.asignar(quien)
            self.assertEqual(r.status_code, 403, quien.email)
        self.assertFalse(PedidoEPP.objects.exists())

    def test_sin_stock_no_se_entrega(self):
        r, _ = self.asignar(detalles=[{'epp': self.bota.pk, 'cantidad': 4}])
        self.assertEqual(r.status_code, 400)
        self.assertIn('solo hay 3', r.json()['detail'])
        self.assertFalse(PedidoEPP.objects.exists())

    def test_solo_a_quien_usa_epp(self):
        r, _ = self.asignar(usuario=self.encargado.pk)  # encargado de almacén
        self.assertEqual(r.status_code, 400)

    def test_se_listan_aparte(self):
        self.asignar()
        self.auth(self.pedro)
        self.client.post('/api/pedidos-epp/', {
            'tipo': 'nuevo', 'detalles': [{'epp': self.bota.pk, 'cantidad': 1}]},
            format='json')
        self.auth(self.admin)
        r = self.client.get('/api/pedidos-epp/', {'origen': 'asignacion'})
        self.assertEqual([p['origen'] for p in r.json()], ['asignacion'])
