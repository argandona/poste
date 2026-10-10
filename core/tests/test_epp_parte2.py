"""
EPP, parte 2: el pedido (nuevo o cambio con foto), su aprobación con
descuento de stock, los avisos y lo que cada uno tiene entregado.
"""
import base64
import io
from decimal import Decimal
from unittest import mock

from django.core.management import call_command

from ..models import EPP, PedidoEPP, Rol, StockEPP, Usuario
from .base import BaseAPITestCase

URL = '/api/pedidos-epp/'
FOTO = base64.b64encode(b'\xff\xd8\xff\xe0 jpeg de prueba').decode()


class PedidosEPPTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        call_command('configurar_epp', stdout=io.StringIO())
        self.operario = Usuario.objects.create(
            nombre='Pedro Operario', email='pedro@x.com', clave='x',
            empresa=self.empresa, fcm_token='tok-pedro',
            rol=Rol.objects.get(id_rol=Rol.OPERARIO))
        self.encargado.fcm_token = 'tok-almacen'
        self.encargado.save()
        self.bota = EPP.objects.get(codigo='BOTA-DIEL-42')
        self.casco = EPP.objects.get(codigo='CASCO-AZUL')
        StockEPP.objects.create(almacen=self.almacen, epp=self.bota, cantidad=5)
        StockEPP.objects.create(almacen=self.almacen, epp=self.casco, cantidad=2)

    def pedir(self, usuario=None, **datos):
        self.auth(usuario or self.operario)
        cuerpo = {'tipo': 'nuevo',
                  'detalles': [{'epp': self.bota.pk, 'cantidad': 1},
                               {'epp': self.casco.pk, 'cantidad': 1}],
                  **datos}
        with mock.patch('core.fcm.send_notification') as avisar:
            resp = self.client.post(URL, cuerpo, format='json')
        return resp, avisar

    def aprobar(self, pedido_id, **datos):
        self.auth(self.encargado)
        with mock.patch('core.fcm.send_notification') as avisar:
            resp = self.client.post(f'{URL}{pedido_id}/aprobar/',
                                    {'accion': 'aprobar', **datos}, format='json')
        return resp, avisar

    # ── Pedir ────────────────────────────────────────────────────────────────

    def test_el_operario_pide_y_el_almacen_recibe_el_aviso(self):
        resp, avisar = self.pedir()
        self.assertEqual(resp.status_code, 201, resp.content)
        p = resp.json()
        self.assertEqual((p['tipo'], p['estado'], len(p['detalles'])),
                         ('nuevo', 'pendiente', 2))
        self.assertEqual(avisar.call_args.args[0], ['tok-almacen'])
        self.assertEqual(avisar.call_args.kwargs['title'],
                         'Pedido de EPP por aprobar')

    def test_el_cambio_exige_foto_y_motivo(self):
        resp, _ = self.pedir(tipo='cambio', motivo='Se rompió la suela')
        self.assertEqual(resp.status_code, 400)
        resp, _ = self.pedir(tipo='cambio', foto=FOTO)
        self.assertEqual(resp.status_code, 400)
        resp, avisar = self.pedir(tipo='cambio', foto=FOTO,
                                  motivo='Se rompió la suela')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(resp.json()['tiene_foto'])
        self.assertEqual(avisar.call_args.kwargs['title'],
                         'Cambio de EPP por aprobar')

    def test_la_foto_la_ve_el_que_pidio_y_el_almacen(self):
        pid = self.pedir(tipo='cambio', foto=FOTO, motivo='Rota')[0].json()['id_pedido_epp']
        self.auth(self.operario)
        r = self.client.get(f'{URL}{pid}/foto/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, base64.b64decode(FOTO))
        self.auth(self.encargado)
        self.assertEqual(self.client.get(f'{URL}{pid}/foto/').status_code, 200)
        self.auth(self.capataz)
        self.assertEqual(self.client.get(f'{URL}{pid}/foto/').status_code, 404)

    def test_la_foto_no_queda_en_la_base(self):
        pid = self.pedir(tipo='cambio', foto=FOTO, motivo='Rota')[0].json()['id_pedido_epp']
        pedido = PedidoEPP.objects.get(pk=pid)
        self.assertIsNone(pedido.foto)
        self.assertTrue(pedido.foto_archivo.startswith('tecsur/epp/'))

    def test_en_cloudinary_la_foto_redirige(self):
        pid = self.pedir(tipo='cambio', foto=FOTO, motivo='Rota')[0].json()['id_pedido_epp']
        self.auth(self.operario)
        with mock.patch('core.fotos.url_foto',
                        return_value='https://res.cloudinary.com/x/foto.jpg'):
            r = self.client.get(f'{URL}{pid}/foto/')
        self.assertEqual((r.status_code, r['Location']),
                         (302, 'https://res.cloudinary.com/x/foto.jpg'))

    def test_mover_fotos_saca_las_viejas_de_la_base(self):
        viejo = base64.b64decode(FOTO)
        pid = self.pedir(tipo='nuevo')[0].json()['id_pedido_epp']
        PedidoEPP.objects.filter(pk=pid).update(foto=viejo, foto_tipo='image/jpeg')
        self.auth(self.operario)
        self.assertEqual(self.client.get(f'{URL}{pid}/foto/').content, viejo)

        call_command('mover_fotos', stdout=io.StringIO())  # sin Cloudinary: nada
        self.assertIsNotNone(PedidoEPP.objects.get(pk=pid).foto)
        call_command('mover_fotos', '--local', stdout=io.StringIO())
        pedido = PedidoEPP.objects.get(pk=pid)
        self.assertIsNone(pedido.foto)
        self.assertTrue(pedido.foto_archivo)
        self.assertEqual(self.client.get(f'{URL}{pid}/foto/').content, viejo)

    def test_quien_no_sale_a_obra_no_pide(self):
        resp, _ = self.pedir(self.encargado)
        self.assertEqual(resp.status_code, 403)

    def test_el_capataz_tambien_pide(self):
        resp, _ = self.pedir(self.capataz)
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_epp_inactivo_o_sin_cantidad(self):
        EPP.objects.filter(pk=self.casco.pk).update(activo=False)
        self.assertEqual(self.pedir()[0].status_code, 400)
        resp, _ = self.pedir(detalles=[{'epp': self.bota.pk, 'cantidad': 0}])
        self.assertEqual(resp.status_code, 400)

    # ── Aprobar ──────────────────────────────────────────────────────────────

    def test_aprobar_descuenta_del_almacen_y_avisa(self):
        pid = self.pedir()[0].json()['id_pedido_epp']
        resp, avisar = self.aprobar(pid)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['estado'], 'aprobado')
        self.assertEqual(StockEPP.objects.get(epp=self.bota).cantidad, Decimal('4'))
        self.assertEqual(StockEPP.objects.get(epp=self.casco).cantidad, Decimal('1'))
        self.assertEqual(avisar.call_args.args[0], ['tok-pedro'])
        self.assertEqual(avisar.call_args.kwargs['title'], 'Pedido de EPP aprobado')

    def test_aprobar_menos_de_lo_pedido(self):
        pid = self.pedir()[0].json()['id_pedido_epp']
        resp, _ = self.aprobar(pid, detalles=[
            {'epp': self.casco.pk, 'cantidad_aprobada': 0}])
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(StockEPP.objects.get(epp=self.casco).cantidad, Decimal('2'))
        self.assertEqual(StockEPP.objects.get(epp=self.bota).cantidad, Decimal('4'))

    def test_sin_stock_no_se_aprueba_nada(self):
        self.auth(self.operario)
        pid = self.pedir(detalles=[{'epp': self.bota.pk, 'cantidad': 1},
                                   {'epp': self.casco.pk, 'cantidad': 3}])[0].json()['id_pedido_epp']
        resp, _ = self.aprobar(pid)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('solo hay 2', resp.json()['detail'])
        self.assertEqual(StockEPP.objects.get(epp=self.bota).cantidad, Decimal('5'))
        self.assertEqual(PedidoEPP.objects.get().estado, 'pendiente')

    def test_rechazar_no_toca_stock_y_avisa(self):
        pid = self.pedir()[0].json()['id_pedido_epp']
        self.auth(self.encargado)
        with mock.patch('core.fcm.send_notification') as avisar:
            resp = self.client.post(f'{URL}{pid}/aprobar/', {
                'accion': 'rechazar', 'observacion': 'Ya tiene botas'},
                format='json')
        self.assertEqual(resp.json()['estado'], 'rechazado')
        self.assertEqual(StockEPP.objects.get(epp=self.bota).cantidad, Decimal('5'))
        self.assertIn('Ya tiene botas', avisar.call_args.kwargs['body'])

    def test_solo_el_almacen_aprueba(self):
        pid = self.pedir()[0].json()['id_pedido_epp']
        self.auth(self.capataz)
        r = self.client.post(f'{URL}{pid}/aprobar/', {'accion': 'aprobar'},
                             format='json')
        self.assertEqual(r.status_code, 403)

    def test_no_se_aprueba_dos_veces(self):
        pid = self.pedir()[0].json()['id_pedido_epp']
        self.aprobar(pid)
        resp, _ = self.aprobar(pid)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(StockEPP.objects.get(epp=self.bota).cantidad, Decimal('4'))

    # ── Listas ───────────────────────────────────────────────────────────────

    def test_cada_uno_ve_los_suyos_y_el_almacen_todos(self):
        self.pedir()
        self.pedir(self.capataz)
        self.auth(self.operario)
        self.assertEqual(len(self.client.get(URL).json()), 1)
        self.auth(self.encargado)
        self.assertEqual(len(self.client.get(URL).json()), 2)
        self.assertEqual(len(self.client.get(URL, {'estado': 'pendiente'}).json()), 2)

    def test_mis_epp(self):
        pid = self.pedir()[0].json()['id_pedido_epp']
        self.aprobar(pid)
        pid = self.pedir(tipo='cambio', foto=FOTO, motivo='Rota',
                         detalles=[{'epp': self.bota.pk, 'cantidad': 1}])[0].json()['id_pedido_epp']
        self.aprobar(pid)
        self.auth(self.operario)
        d = self.client.get(f'{URL}mis_epp/').json()
        bota = next(e for e in d['epp'] if e['codigo'] == 'BOTA-DIEL-42')
        self.assertEqual((Decimal(str(bota['total'])), bota['cambios']),
                         (Decimal('2'), 1))
        self.auth(self.encargado)
        d = self.client.get(f'{URL}mis_epp/', {'usuario': self.operario.pk}).json()
        self.assertEqual(d['usuario_nombre'], 'Pedro Operario')
