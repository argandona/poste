"""
Flujo de devoluciones: un capataz devuelve material del camión y el encargado
de almacén aprueba. Al aprobar, el stock sale del camión y entra al almacén.
"""
from decimal import Decimal

from ..models import DetalleDevolucion, Devolucion, StockCamion
from .base import BaseAPITestCase


class DevolucionTestCase(BaseAPITestCase):
    """Añade stock en el camión, que es de donde sale una devolución."""

    def setUp(self):
        super().setUp()
        self.stock_camion_a = StockCamion.objects.create(
            camion=self.camion, material=self.material_a, cantidad=Decimal("8"))


class CrearDevolucionTests(DevolucionTestCase):

    def setUp(self):
        super().setUp()
        self.auth(self.capataz)

    def payload(self, cantidad):
        return {
            "camion": self.camion.pk,
            "usuario": self.capataz.pk,
            "detalles": [{"material": self.material_a.pk,
                          "cantidad_solicitada": cantidad}],
        }

    def test_se_crea_si_hay_stock_suficiente(self):
        resp = self.client.post("/api/devoluciones/", self.payload(5), format="json")

        self.assertEqual(resp.status_code, 201, resp.data)
        devolucion = Devolucion.objects.get()
        self.assertEqual(devolucion.estado, "pendiente")
        # Crear la devolución todavía no mueve stock: eso pasa al aprobar.
        self.assertEqual(self.stock_camion(self.material_a), Decimal("8"))

    def test_no_se_puede_devolver_mas_de_lo_que_hay_en_el_camion(self):
        resp = self.client.post("/api/devoluciones/", self.payload(99), format="json")

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Devolucion.objects.exists())

    def test_material_sin_stock_en_el_camion_se_rechaza(self):
        cuerpo = {
            "camion": self.camion.pk,
            "usuario": self.capataz.pk,
            "detalles": [{"material": self.material_b.pk, "cantidad_solicitada": 1}],
        }

        resp = self.client.post("/api/devoluciones/", cuerpo, format="json")

        self.assertEqual(resp.status_code, 400)

    def test_las_devoluciones_pendientes_reservan_stock(self):
        # Con 8 en el camión, dos devoluciones de 5 no pueden coexistir:
        # la segunda solo tiene 3 disponibles.
        primera = self.client.post("/api/devoluciones/", self.payload(5), format="json")
        self.assertEqual(primera.status_code, 201, primera.data)

        segunda = self.client.post("/api/devoluciones/", self.payload(5), format="json")

        self.assertEqual(segunda.status_code, 400)
        self.assertEqual(Devolucion.objects.count(), 1)


class AprobarDevolucionTests(DevolucionTestCase):

    def setUp(self):
        super().setUp()
        self.devolucion = Devolucion.objects.create(
            camion=self.camion, usuario=self.capataz, estado="pendiente")
        self.detalle = DetalleDevolucion.objects.create(
            devolucion=self.devolucion, material=self.material_a,
            cantidad_solicitada=3)
        self.auth(self.encargado)
        self.url = f"/api/devoluciones/{self.devolucion.pk}/aprobar/"

    def payload(self, accion="aprobar", cantidad_aprobada=3):
        return {
            "accion": accion,
            "usuario_aprueba": self.encargado.pk,
            "almacen_destino": self.almacen.pk,
            "detalles": [{"material": self.material_a.pk,
                          "cantidad_solicitada": 3,
                          "cantidad_aprobada": cantidad_aprobada}],
        }

    def test_aprobar_descuenta_del_camion_y_suma_al_almacen(self):
        resp = self.client.post(self.url, self.payload(), format="json")

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self.stock_camion(self.material_a), Decimal("5"))   # 8 - 3
        self.assertEqual(self.stock_almacen(self.material_a), 13)            # 10 + 3

        self.devolucion.refresh_from_db()
        self.assertEqual(self.devolucion.estado, "aprobado")
        self.assertEqual(self.devolucion.almacen_destino_id, self.almacen.pk)

    def test_rechazar_no_mueve_stock(self):
        resp = self.client.post(
            self.url, self.payload(accion="rechazar"), format="json")

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self.stock_camion(self.material_a), Decimal("8"))
        self.assertEqual(self.stock_almacen(self.material_a), 10)

        self.devolucion.refresh_from_db()
        self.assertEqual(self.devolucion.estado, "rechazado")

    def test_devolucion_ya_aprobada_no_se_reprocesa(self):
        self.client.post(self.url, self.payload(), format="json")

        resp = self.client.post(self.url, self.payload(), format="json")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.stock_camion(self.material_a), Decimal("5"))
        self.assertEqual(self.stock_almacen(self.material_a), 13)

    def test_aprobar_mas_de_lo_que_hay_en_el_camion_no_mueve_nada(self):
        resp = self.client.post(
            self.url, self.payload(cantidad_aprobada=99), format="json")

        self.assertEqual(resp.status_code, 400, f"devolvió {resp.status_code}")
        self.assertEqual(self.stock_camion(self.material_a), Decimal("8"))
        self.assertEqual(self.stock_almacen(self.material_a), 10)

        self.devolucion.refresh_from_db()
        self.assertEqual(self.devolucion.estado, "pendiente")

    def test_material_sin_stock_en_camion_no_deja_movimientos_parciales(self):
        DetalleDevolucion.objects.create(
            devolucion=self.devolucion, material=self.material_b,
            cantidad_solicitada=1)
        cuerpo = self.payload()
        cuerpo["detalles"].append({"material": self.material_b.pk,
                                   "cantidad_solicitada": 1,
                                   "cantidad_aprobada": 1})

        resp = self.client.post(self.url, cuerpo, format="json")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.stock_camion(self.material_a), Decimal("8"))
        self.assertEqual(self.stock_almacen(self.material_a), 10)

        self.devolucion.refresh_from_db()
        self.assertEqual(self.devolucion.estado, "pendiente")
