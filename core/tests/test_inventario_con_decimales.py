"""
El inventario del camión con decimales.

El fleje se cuenta por metro. Con enteros, el inventario abría con el saldo de
2.5 m como teórico 2, y al cerrarlo escribía ese 2 en el camión: el medio metro
se perdía sin que nadie lo tocara.
"""
from decimal import Decimal
from unittest import mock

from ..models import DetalleInventario, Inventario, StockCamion
from .base import BaseAPITestCase


class InventarioConDecimalesTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        StockCamion.objects.create(camion=self.camion, material=self.material_a,
                                   cantidad=Decimal("2.50"))
        StockCamion.objects.create(camion=self.camion, material=self.material_b,
                                   cantidad=Decimal("4"))
        self.auth(self.capataz)

    def iniciar(self):
        resp = self.client.post("/api/inventarios/iniciar_o_continuar/", {
            "camion": self.camion.pk, "usuario": self.capataz.pk}, format="json")
        self.assertIn(resp.status_code, (200, 201), resp.content)
        return resp.json()

    def detalle(self, datos, material):
        return next(d for d in datos["detalles"] if d["material"] == material.pk)

    def test_abre_con_el_saldo_exacto_del_camion(self):
        datos = self.iniciar()
        self.assertEqual(self.detalle(datos, self.material_a)["cantidad_teorica"], 2.5)
        # Lo exacto sale entero: el APK anterior lo lee como int.
        exacta = self.detalle(datos, self.material_b)["cantidad_teorica"]
        self.assertIs(type(exacta), int)

    def test_cerrar_no_le_borra_los_decimales_al_camion(self):
        self.iniciar()
        inventario = Inventario.objects.get()
        with mock.patch("core.pdf_inventario.enviar_pdf_inventario"):
            resp = self.client.post(f"/api/inventarios/{inventario.pk}/cerrar/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.stock_camion(self.material_a), Decimal("2.50"))

    def test_el_conteo_con_decimales_llega_al_camion_con_su_diferencia(self):
        datos = self.iniciar()
        fila = self.detalle(datos, self.material_a)
        resp = self.client.patch(
            f"/api/inventarios/{datos['id_inventario']}/guardar_conteo/",
            {"detalles": [{"id_detalle_inventario": fila["id_detalle_inventario"],
                           "cantidad_fisica": 1.75}]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        fila = self.detalle(resp.json(), self.material_a)
        self.assertEqual(fila["cantidad_fisica"], 1.75)
        self.assertEqual(fila["diferencia"], -0.75)
        with mock.patch("core.pdf_inventario.enviar_pdf_inventario"):
            self.client.post(f"/api/inventarios/{datos['id_inventario']}/cerrar/")
        self.assertEqual(self.stock_camion(self.material_a), Decimal("1.75"))

    def test_un_conteo_invalido_no_se_guarda(self):
        datos = self.iniciar()
        fila = self.detalle(datos, self.material_a)
        for malo in ("-1", "mucho"):
            resp = self.client.patch(
                f"/api/inventarios/{datos['id_inventario']}/guardar_conteo/",
                {"detalles": [{"id_detalle_inventario": fila["id_detalle_inventario"],
                               "cantidad_fisica": malo}]}, format="json")
            self.assertEqual(resp.status_code, 400, malo)
        self.assertEqual(DetalleInventario.objects.get(
            material=self.material_a).cantidad_fisica, Decimal("2.50"))

    def test_al_continuar_la_diferencia_sigue_al_nuevo_teorico(self):
        datos = self.iniciar()
        fila = self.detalle(datos, self.material_a)
        self.client.patch(
            f"/api/inventarios/{datos['id_inventario']}/guardar_conteo/",
            {"detalles": [{"id_detalle_inventario": fila["id_detalle_inventario"],
                           "cantidad_fisica": "2.5"}]}, format="json")
        # Mientras el borrador está abierto, el camión recibe más fleje.
        StockCamion.objects.filter(material=self.material_a).update(
            cantidad=Decimal("3.25"))
        fila = self.detalle(self.iniciar(), self.material_a)
        self.assertEqual(fila["cantidad_teorica"], 3.25)
        self.assertEqual(fila["diferencia"], -0.75)

    def test_el_pdf_sale_con_decimales(self):
        datos = self.iniciar()
        resp = self.client.get(
            f"/api/inventarios/{datos['id_inventario']}/descargar_pdf/")
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.assertTrue(resp.content.startswith(b"%PDF"))
