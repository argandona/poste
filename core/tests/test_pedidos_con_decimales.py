"""
Pedidos y devoluciones con decimales: el fleje y el cable se piden por metro.

Las cantidades salen como número, y enteras cuando son exactas, para que los
APK anteriores, que las leen como `int`, sigan abriendo los pedidos enteros.
"""
from decimal import Decimal

from ..models import DetalleDevolucion, DetallePedido, Devolucion, Pedido, StockCamion
from .base import BaseAPITestCase


class PedidosConDecimalesTests(BaseAPITestCase):

    def test_se_pide_con_decimales(self):
        self.auth(self.capataz)
        resp = self.client.post("/api/pedidos/", {
            "camion": self.camion.pk, "usuario": self.capataz.pk,
            "observacion": "",
            "detalles": [{"material": self.material_a.pk,
                          "cantidad_solicitada": "2.5"}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(DetallePedido.objects.get().cantidad_solicitada,
                         Decimal("2.50"))

    def test_se_aprueba_con_decimales_y_mueve_el_stock(self):
        pedido = Pedido.objects.create(
            camion=self.camion, usuario=self.capataz, estado="pendiente")
        DetallePedido.objects.create(pedido=pedido, material=self.material_a,
                                     cantidad_solicitada=Decimal("2.5"))
        self.auth(self.encargado)
        resp = self.client.post(f"/api/pedidos/{pedido.pk}/aprobar/", {
            "accion": "aprobar", "usuario_aprueba": self.encargado.pk,
            "almacen": self.almacen.pk,
            "detalles": [{"material": self.material_a.pk,
                          "cantidad_solicitada": 2.5,
                          "cantidad_aprobada": 2.5}],
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("7.50"))
        self.assertEqual(self.stock_camion(self.material_a), Decimal("2.50"))

    def test_las_cantidades_exactas_salen_enteras(self):
        pedido = Pedido.objects.create(
            camion=self.camion, usuario=self.capataz, estado="pendiente")
        DetallePedido.objects.create(pedido=pedido, material=self.material_a,
                                     cantidad_solicitada=4)
        DetallePedido.objects.create(pedido=pedido, material=self.material_b,
                                     cantidad_solicitada=Decimal("1.25"))
        self.auth(self.capataz)
        detalles = self.client.get(f"/api/pedidos/{pedido.pk}/").json()["detalles"]
        por_material = {d["material"]: d for d in detalles}
        exacta = por_material[self.material_a.pk]["cantidad_solicitada"]
        self.assertIs(type(exacta), int)
        self.assertEqual(exacta, 4)
        self.assertEqual(por_material[self.material_a.pk]["cantidad_aprobada"], 0)
        self.assertEqual(
            por_material[self.material_b.pk]["cantidad_solicitada"], 1.25)

    def test_se_devuelve_un_sobrante_con_decimales(self):
        StockCamion.objects.create(camion=self.camion, material=self.material_a,
                                   cantidad=Decimal("3.75"))
        self.auth(self.capataz)
        resp = self.client.post("/api/devoluciones/", {
            "camion": self.camion.pk, "usuario": self.capataz.pk,
            "observacion": "",
            "detalles": [{"material": self.material_a.pk,
                          "cantidad_solicitada": "1.75"}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        devolucion = Devolucion.objects.get()
        self.auth(self.encargado)
        resp = self.client.post(f"/api/devoluciones/{devolucion.pk}/aprobar/", {
            "accion": "aprobar", "usuario_aprueba": self.encargado.pk,
            "almacen_destino": self.almacen.pk,
            "detalles": [{"material": self.material_a.pk,
                          "cantidad_solicitada": 1.75,
                          "cantidad_aprobada": 1.75}],
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.stock_camion(self.material_a), Decimal("2.00"))
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("11.75"))
        self.assertEqual(DetalleDevolucion.objects.get().cantidad_aprobada,
                         Decimal("1.75"))

    def test_no_se_pide_en_negativo(self):
        self.auth(self.capataz)
        resp = self.client.post("/api/pedidos/", {
            "camion": self.camion.pk, "usuario": self.capataz.pk,
            "observacion": "",
            "detalles": [{"material": self.material_a.pk,
                          "cantidad_solicitada": "-1"}],
        }, format="json")
        self.assertEqual(resp.status_code, 400)
