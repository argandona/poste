"""
Flujo de pedidos: un capataz solicita material y el encargado de almacén
aprueba o rechaza. Al aprobar, el stock sale del almacén y entra al camión.
"""
from decimal import Decimal

from ..models import DetallePedido, Pedido
from .base import BaseAPITestCase


class AprobarPedidoTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.pedido = Pedido.objects.create(
            camion=self.camion, usuario=self.capataz, estado="pendiente")
        self.detalle_a = DetallePedido.objects.create(
            pedido=self.pedido, material=self.material_a, cantidad_solicitada=4)
        self.auth(self.encargado)

    def url(self, pedido=None):
        return f"/api/pedidos/{(pedido or self.pedido).pk}/aprobar/"

    def payload(self, accion="aprobar", **extra):
        cuerpo = {
            "accion": accion,
            "usuario_aprueba": self.encargado.pk,
            "almacen": self.almacen.pk,
            "detalles": [{
                "material": self.material_a.pk,
                "cantidad_solicitada": 4,
                "cantidad_aprobada": 4,
            }],
        }
        cuerpo.update(extra)
        return cuerpo

    # ── Camino feliz ─────────────────────────────────────────────────────────

    def test_aprobar_descuenta_del_almacen_y_suma_al_camion(self):
        resp = self.client.post(self.url(), self.payload(), format="json")

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self.stock_almacen(self.material_a), 6)   # 10 - 4
        self.assertEqual(self.stock_camion(self.material_a), Decimal("4"))

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, "aprobado")
        self.assertEqual(self.pedido.almacen_id, self.almacen.pk)
        self.assertEqual(self.pedido.usuario_aprueba_id, self.encargado.pk)
        self.assertIsNotNone(self.pedido.fecha_aprobacion)

    def test_aprobacion_parcial_mueve_solo_la_cantidad_aprobada(self):
        cuerpo = self.payload()
        cuerpo["detalles"][0]["cantidad_aprobada"] = 1

        resp = self.client.post(self.url(), cuerpo, format="json")

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self.stock_almacen(self.material_a), 9)
        self.assertEqual(self.stock_camion(self.material_a), Decimal("1"))

        self.detalle_a.refresh_from_db()
        self.assertEqual(self.detalle_a.cantidad_aprobada, 1)
        self.assertEqual(self.detalle_a.cantidad_solicitada, 4)

    def test_rechazar_no_mueve_stock(self):
        resp = self.client.post(
            self.url(), self.payload(accion="rechazar"), format="json")

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self.stock_almacen(self.material_a), 10)
        self.assertIsNone(self.stock_camion(self.material_a))

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, "rechazado")

    # ── Estados no reprocesables ─────────────────────────────────────────────

    def test_pedido_ya_aprobado_no_se_reprocesa(self):
        self.client.post(self.url(), self.payload(), format="json")

        resp = self.client.post(self.url(), self.payload(), format="json")

        self.assertEqual(resp.status_code, 400)
        # El stock quedó como después de la primera aprobación, sin doble descuento.
        self.assertEqual(self.stock_almacen(self.material_a), 6)
        self.assertEqual(self.stock_camion(self.material_a), Decimal("4"))

    def test_pedido_rechazado_no_se_aprueba_despues(self):
        self.client.post(self.url(), self.payload(accion="rechazar"), format="json")

        resp = self.client.post(self.url(), self.payload(), format="json")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.stock_almacen(self.material_a), 10)


class AprobarPedidoSinStockTests(BaseAPITestCase):
    """
    Un pedido que no se puede satisfacer entero no debe aplicarse a medias:
    o entra completo o no entra nada.
    """

    def setUp(self):
        super().setUp()
        self.pedido = Pedido.objects.create(
            camion=self.camion, usuario=self.capataz, estado="pendiente")
        DetallePedido.objects.create(
            pedido=self.pedido, material=self.material_a, cantidad_solicitada=4)
        DetallePedido.objects.create(
            pedido=self.pedido, material=self.material_b, cantidad_solicitada=2)
        self.auth(self.encargado)
        self.url = f"/api/pedidos/{self.pedido.pk}/aprobar/"

    def test_material_sin_stock_registrado_no_deja_movimientos_parciales(self):
        # material_b no tiene fila de StockAlmacen; material_a va primero y sí
        # se podría descontar. El pedido debe rechazarse entero.
        cuerpo = {
            "accion": "aprobar",
            "usuario_aprueba": self.encargado.pk,
            "almacen": self.almacen.pk,
            "detalles": [
                {"material": self.material_a.pk,
                 "cantidad_solicitada": 4, "cantidad_aprobada": 4},
                {"material": self.material_b.pk,
                 "cantidad_solicitada": 2, "cantidad_aprobada": 2},
            ],
        }

        resp = self.client.post(self.url, cuerpo, format="json")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.stock_almacen(self.material_a), 10)
        self.assertIsNone(self.stock_camion(self.material_a))

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, "pendiente")

    def test_stock_insuficiente_responde_400_y_no_mueve_nada(self):
        # El almacén tiene 10 de material_a; se piden 99.
        cuerpo = {
            "accion": "aprobar",
            "usuario_aprueba": self.encargado.pk,
            "almacen": self.almacen.pk,
            "detalles": [{"material": self.material_a.pk,
                          "cantidad_solicitada": 99, "cantidad_aprobada": 99}],
        }

        resp = self.client.post(self.url, cuerpo, format="json")

        self.assertEqual(resp.status_code, 400, f"devolvió {resp.status_code}")
        self.assertEqual(self.stock_almacen(self.material_a), 10)
        self.assertIsNone(self.stock_camion(self.material_a))

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, "pendiente")

    def test_el_mensaje_de_error_es_una_cadena_en_detail(self):
        # La app Flutter hace `json['detail']` esperando un String
        # (api_service.dart:136); una lista rompería el cliente.
        cuerpo = {
            "accion": "aprobar",
            "usuario_aprueba": self.encargado.pk,
            "almacen": self.almacen.pk,
            "detalles": [{"material": self.material_b.pk,
                          "cantidad_solicitada": 2, "cantidad_aprobada": 2}],
        }

        resp = self.client.post(self.url, cuerpo, format="json")

        self.assertEqual(resp.status_code, 400)
        self.assertIsInstance(resp.data.get("detail"), str)
