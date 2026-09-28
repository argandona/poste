"""
Los movimientos de almacén se crean por la API con sus detalles.

El detalle exigía el campo de su padre (ingreso, transferencia...), que
todavía no existe cuando se manda el cuerpo, así que ninguno se podía crear:
la respuesta era 400 con "ingreso: Este campo es requerido".
"""
from datetime import date
from decimal import Decimal

from ..models import Almacen, Proveedor
from .base import BaseAPITestCase


class MovimientosDeAlmacenTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.proveedor = Proveedor.objects.create(nombre="TECSUR", ruc="TECSUR-SIN-RUC")
        self.auth(self.encargado)

    def cabecera(self, **extra):
        return {"almacen": self.almacen.pk, "proveedor": self.proveedor.pk,
                "usuario": self.encargado.pk, "fecha": date.today().isoformat(),
                "observacion": "", **extra}

    def test_ingreso_suma_al_almacen(self):
        resp = self.client.post("/api/ingresos-tecsur/", self.cabecera(
            folio="ING-1",
            detalles=[{"material": self.material_a.pk, "cantidad": 500},
                      {"material": self.material_b.pk, "cantidad": 1000}]),
            format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("510"))
        self.assertEqual(self.stock_almacen(self.material_b), Decimal("1000"))

    def test_el_folio_repetido_no_carga_dos_veces(self):
        cuerpo = self.cabecera(
            folio="ING-1",
            detalles=[{"material": self.material_a.pk, "cantidad": 5}])
        self.client.post("/api/ingresos-tecsur/", cuerpo, format="json")
        resp = self.client.post("/api/ingresos-tecsur/", cuerpo, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("15"))

    def test_devolucion_a_tecsur_resta_del_almacen(self):
        resp = self.client.post("/api/devoluciones-tecsur/", self.cabecera(
            folio="DEV-1",
            detalles=[{"material": self.material_a.pk, "cantidad": 3}]),
            format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("7"))

    def test_material_malogrado_resta_del_almacen(self):
        resp = self.client.post("/api/materiales-malogrados/", self.cabecera(
            folio_factura="F-1",
            detalles=[{"material": self.material_a.pk, "cantidad": 2,
                       "costo_unitario": "10.00"}]),
            format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("8"))

    def test_transferencia_mueve_entre_almacenes(self):
        otro = Almacen.objects.create(empresa=self.empresa, nombre="Obra")
        resp = self.client.post("/api/transferencias/", {
            "almacen_origen": self.almacen.pk, "almacen_destino": otro.pk,
            "usuario": self.encargado.pk, "fecha": date.today().isoformat(),
            "observacion": "",
            "detalles": [{"material": self.material_a.pk, "cantidad": 4}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("6"))
