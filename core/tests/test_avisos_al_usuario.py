"""
Al que pidió le llega el aviso cuando el almacén aprueba o rechaza su pedido
o su devolución.
"""
from decimal import Decimal
from unittest import mock

from ..models import (DetalleDevolucion, DetallePedido, Devolucion, Pedido,
                      StockCamion)
from .base import BaseAPITestCase


class AvisosAlUsuarioTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.capataz.fcm_token = 'tok-capataz'
        self.capataz.save()
        self.auth(self.encargado)

    def aprobar(self, url, cuerpo):
        with mock.patch('core.fcm.send_notification') as avisar:
            resp = self.client.post(url, cuerpo, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(avisar.call_args.args[0], ['tok-capataz'])
        return avisar.call_args.kwargs['title']

    def pedido(self, accion):
        pedido = Pedido.objects.create(camion=self.camion, usuario=self.capataz)
        DetallePedido.objects.create(pedido=pedido, material=self.material_a,
                                     cantidad_solicitada=2)
        return self.aprobar(f'/api/pedidos/{pedido.pk}/aprobar/', {
            'accion': accion, 'usuario_aprueba': self.encargado.pk,
            'almacen': self.almacen.pk,
            'detalles': [{'material': self.material_a.pk,
                          'cantidad_solicitada': 2, 'cantidad_aprobada': 2}],
        })

    def devolucion(self, accion):
        StockCamion.objects.create(camion=self.camion, material=self.material_a,
                                   cantidad=Decimal('5'))
        dev = Devolucion.objects.create(camion=self.camion, usuario=self.capataz)
        DetalleDevolucion.objects.create(devolucion=dev, material=self.material_a,
                                         cantidad_solicitada=1)
        return self.aprobar(f'/api/devoluciones/{dev.pk}/aprobar/', {
            'accion': accion, 'usuario_aprueba': self.encargado.pk,
            'almacen_destino': self.almacen.pk,
            'detalles': [{'material': self.material_a.pk,
                          'cantidad_solicitada': 1, 'cantidad_aprobada': 1}],
        })

    def test_pedido_aprobado(self):
        self.assertEqual(self.pedido('aprobar'), 'Pedido despachado')

    def test_pedido_rechazado(self):
        self.assertEqual(self.pedido('rechazar'), 'Pedido rechazado')

    def test_devolucion_aprobada(self):
        self.assertEqual(self.devolucion('aprobar'), 'Devolución aprobada')

    def test_devolucion_rechazada(self):
        self.assertEqual(self.devolucion('rechazar'), 'Devolución rechazada')
