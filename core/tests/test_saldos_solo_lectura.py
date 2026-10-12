"""
Los saldos del camión y del almacén no se tocan a mano por la API: solo cambian
con los movimientos que dejan registro (pedidos, devoluciones, ingresos...).
"""
from decimal import Decimal

from ..models import StockCamion
from .base import BaseAPITestCase


class SaldosSoloLecturaTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.stock = StockCamion.objects.create(
            camion=self.camion, material=self.material_a, cantidad=8)
        self.auth(self.encargado)

    def test_el_saldo_del_camion_no_se_cambia_a_mano(self):
        url = f'/api/stock-camion/{self.stock.pk}/'
        self.assertEqual(self.client.patch(url, {'cantidad': 0}, format='json').status_code, 405)
        self.assertEqual(self.client.put(url, {'cantidad': 0}, format='json').status_code, 405)
        self.assertEqual(self.client.delete(url).status_code, 405)
        self.assertEqual(self.client.post('/api/stock-camion/', {
            'camion': self.camion.pk, 'material': self.material_b.pk, 'cantidad': 5,
        }, format='json').status_code, 405)
        self.assertEqual(self.stock_camion(self.material_a), Decimal('8'))
        self.assertIsNone(self.stock_camion(self.material_b))

    def test_el_stock_del_almacen_no_se_cambia_a_mano(self):
        url = f'/api/stock-almacen/{self.stock_almacen_a.pk}/'
        self.assertEqual(self.client.patch(url, {'cantidad': 999}, format='json').status_code, 405)
        self.assertEqual(self.client.delete(url).status_code, 405)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal('10'))

    def test_los_saldos_se_siguen_leyendo(self):
        r = self.client.get('/api/stock-camion/por_camion/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()[0]['placa'], 'ABC-123')
        self.assertEqual(self.client.get(f'/api/stock-camion/?camion={self.camion.pk}').status_code, 200)
        self.assertEqual(self.client.get('/api/stock-almacen/').status_code, 200)
