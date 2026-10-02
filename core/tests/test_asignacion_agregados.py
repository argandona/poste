"""
Asignación de agregados: el cemento sale del almacén al camión sin pedido.

Se registra por los dos lados y sin aprobación. Desde el almacén se elige el
camión; desde el camión, va al propio. Las dos impactan en el acto en los dos
stocks, y el almacén puede anular para devolver las bolsas.
"""
from decimal import Decimal
from unittest import mock

from ..models import (Almacen, AsignacionAgregado, Material, StockAlmacen,
                      StockCamion)
from .base import BaseAPITestCase

URL = "/api/asignaciones-agregado/"


class AsignacionAgregadosTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.cemento = Material.objects.create(
            matricula="CEMENTO-425", descripcion="CEMENTO (BOLSA 42.5 KG)",
            precio="1", es_agregado=True)
        StockAlmacen.objects.create(almacen=self.almacen, material=self.cemento,
                                    cantidad=20)

    def registrar(self, usuario, **datos):
        self.auth(usuario)
        cuerpo = {"material": self.cemento.pk, "cantidad": "5", **datos}
        with mock.patch("core.fcm.send_notification") as avisar:
            resp = self.client.post(URL, cuerpo, format="json")
        return resp, avisar

    # ── Desde el camión ──────────────────────────────────────────────────────

    def test_el_capataz_se_lo_lleva_a_su_camion_en_el_acto(self):
        resp, _ = self.registrar(self.capataz, cantidad="5.5")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.stock_almacen(self.cemento), Decimal("14.50"))
        self.assertEqual(self.stock_camion(self.cemento), Decimal("5.50"))
        a = AsignacionAgregado.objects.get()
        self.assertEqual((a.origen, a.usuario, a.registrado_por, a.camion),
                         ("camion", self.capataz, self.capataz, self.camion))

    def test_lo_del_camion_le_avisa_al_almacen(self):
        self.encargado.fcm_token = "tok-almacen"
        self.encargado.save()
        _, avisar = self.registrar(self.capataz)
        self.assertEqual(avisar.call_args.args[0], ["tok-almacen"])
        self.assertIn("ABC-123", avisar.call_args.kwargs["body"])

    def test_sin_camion_activo_no_se_puede(self):
        self.asignacion.activo = False
        self.asignacion.save()
        resp, _ = self.registrar(self.capataz)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.stock_almacen(self.cemento), Decimal("20"))

    # ── Desde el almacén ─────────────────────────────────────────────────────

    def test_el_almacen_se_lo_entrega_al_responsable_del_camion(self):
        resp, avisar = self.registrar(self.encargado, camion=self.camion.pk)
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["usuario_nombre"], self.capataz.nombre)
        self.assertEqual(self.stock_camion(self.cemento), Decimal("5"))
        a = AsignacionAgregado.objects.get()
        self.assertEqual((a.origen, a.usuario, a.registrado_por),
                         ("almacen", self.capataz, self.encargado))
        avisar.assert_not_called()

    def test_el_almacen_tiene_que_elegir_camion(self):
        resp, _ = self.registrar(self.encargado)
        self.assertEqual(resp.status_code, 400)
        self.assertIsInstance(resp.json()["detail"], str)

    # ── Lo que no se permite ────────────────────────────────────────────────

    def test_no_alcanza_el_stock_del_almacen(self):
        resp, _ = self.registrar(self.capataz, cantidad="21")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("solo hay 20", resp.json()["detail"])
        self.assertIsNone(self.stock_camion(self.cemento))

    def test_solo_agregados(self):
        resp, _ = self.registrar(self.capataz, material=self.material_a.pk)
        self.assertEqual(resp.status_code, 400)

    def test_cantidad_positiva(self):
        for cantidad in ("0", "-2", "abc"):
            resp, _ = self.registrar(self.capataz, cantidad=cantidad)
            self.assertEqual(resp.status_code, 400, cantidad)

    def test_con_dos_almacenes_hay_que_elegir(self):
        otro = Almacen.objects.create(empresa=self.empresa, nombre="Norte")
        resp, _ = self.registrar(self.capataz)
        self.assertEqual(resp.status_code, 400)
        StockAlmacen.objects.create(almacen=otro, material=self.cemento,
                                    cantidad=8)
        resp, _ = self.registrar(self.capataz, almacen=otro.pk)
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(StockAlmacen.objects.get(almacen=otro).cantidad,
                         Decimal("3"))

    # ── Anular ───────────────────────────────────────────────────────────────

    def test_anular_devuelve_las_bolsas(self):
        resp, _ = self.registrar(self.capataz)
        self.auth(self.encargado)
        r = self.client.post(f"{URL}{resp.json()['id_asignacion']}/anular/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["anulada"])
        self.assertEqual(self.stock_almacen(self.cemento), Decimal("20"))
        self.assertEqual(self.stock_camion(self.cemento), Decimal("0"))
        r = self.client.post(f"{URL}{resp.json()['id_asignacion']}/anular/")
        self.assertEqual(r.status_code, 400)

    def test_el_capataz_no_anula(self):
        resp, _ = self.registrar(self.capataz)
        r = self.client.post(f"{URL}{resp.json()['id_asignacion']}/anular/")
        self.assertEqual(r.status_code, 403)

    def test_no_se_anula_lo_que_ya_se_gasto(self):
        resp, _ = self.registrar(self.capataz)
        StockCamion.objects.filter(material=self.cemento).update(cantidad=2)
        self.auth(self.encargado)
        r = self.client.post(f"{URL}{resp.json()['id_asignacion']}/anular/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.stock_almacen(self.cemento), Decimal("15"))

    # ── Listas ───────────────────────────────────────────────────────────────

    def test_cada_uno_ve_lo_suyo_y_el_almacen_todo(self):
        self.registrar(self.capataz)
        self.registrar(self.encargado, camion=self.camion.pk)
        self.auth(self.encargado)
        self.assertEqual(len(self.client.get(URL).json()), 2)
        self.auth(self.capataz)
        self.assertEqual(len(self.client.get(URL).json()), 2)
        self.assertEqual(len(self.client.get(URL, {"dia": "2020-01-01"}).json()), 0)

    def test_opciones_segun_quien_pregunta(self):
        self.auth(self.encargado)
        d = self.client.get(f"{URL}opciones/").json()
        self.assertTrue(d["es_almacen"])
        self.assertEqual([c["placa"] for c in d["camiones"]], ["ABC-123"])
        [cemento] = d["agregados"]
        self.assertEqual(Decimal(cemento["saldos"][str(self.almacen.pk)]),
                         Decimal("20"))
        self.auth(self.capataz)
        d = self.client.get(f"{URL}opciones/").json()
        self.assertFalse(d["es_almacen"])
        self.assertEqual(d["mi_camion"]["placa"], "ABC-123")
