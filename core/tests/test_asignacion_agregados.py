"""
Asignación de agregados: el cemento sale del almacén al camión sin pedido.

Solo la usa el almacén (encargado de almacén y SuperAdmin), y sin
aprobación: elige el camión y las bolsas pasan del almacén al camión en el
acto. Si se equivocó, anula y vuelven.
"""
from decimal import Decimal

from ..models import (Almacen, AsignacionAgregado, Material, Rol,
                      StockAlmacen, StockCamion, Usuario)
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

    def registrar(self, usuario=None, **datos):
        self.auth(usuario or self.encargado)
        cuerpo = {"material": self.cemento.pk, "cantidad": "5",
                  "camion": self.camion.pk, **datos}
        return self.client.post(URL, cuerpo, format="json")

    # ── Quién entra ─────────────────────────────────────────────────────────

    def test_el_capataz_no_entra(self):
        self.auth(self.capataz)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.client.get(f"{URL}opciones/").status_code, 403)
        self.assertEqual(self.registrar(self.capataz).status_code, 403)
        self.assertEqual(self.stock_almacen(self.cemento), Decimal("20"))

    def test_el_superadmin_entra(self):
        admin = Usuario.objects.create(
            nombre="Admin", empresa=self.empresa, email="admin@tecsur.pe",
            clave="x", rol=Rol.objects.create(id_rol=Rol.SUPERADMIN,
                                              descripcion="SuperAdmin"))
        resp = self.registrar(admin)
        self.assertEqual(resp.status_code, 201, resp.content)

    # ── Entregar ────────────────────────────────────────────────────────────

    def test_se_entrega_al_responsable_del_camion_en_el_acto(self):
        resp = self.registrar(cantidad="5.5")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["usuario_nombre"], self.capataz.nombre)
        self.assertEqual(self.stock_almacen(self.cemento), Decimal("14.50"))
        self.assertEqual(self.stock_camion(self.cemento), Decimal("5.50"))
        a = AsignacionAgregado.objects.get()
        self.assertEqual((a.origen, a.usuario, a.registrado_por),
                         ("almacen", self.capataz, self.encargado))

    def test_hay_que_elegir_camion(self):
        resp = self.registrar(camion=None)
        self.assertEqual(resp.status_code, 400)
        self.assertIsInstance(resp.json()["detail"], str)

    def test_camion_sin_responsable(self):
        self.asignacion.activo = False
        self.asignacion.save()
        self.assertEqual(self.registrar().status_code, 400)
        self.assertEqual(self.stock_almacen(self.cemento), Decimal("20"))

    def test_no_alcanza_el_stock_del_almacen(self):
        resp = self.registrar(cantidad="21")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("solo hay 20", resp.json()["detail"])
        self.assertIsNone(self.stock_camion(self.cemento))

    def test_solo_agregados(self):
        self.assertEqual(
            self.registrar(material=self.material_a.pk).status_code, 400)

    def test_cantidad_positiva(self):
        for cantidad in ("0", "-2", "abc"):
            self.assertEqual(self.registrar(cantidad=cantidad).status_code,
                             400, cantidad)

    def test_con_dos_almacenes_hay_que_elegir(self):
        otro = Almacen.objects.create(empresa=self.empresa, nombre="Norte")
        self.assertEqual(self.registrar().status_code, 400)
        StockAlmacen.objects.create(almacen=otro, material=self.cemento,
                                    cantidad=8)
        resp = self.registrar(almacen=otro.pk)
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(StockAlmacen.objects.get(almacen=otro).cantidad,
                         Decimal("3"))

    # ── Anular ───────────────────────────────────────────────────────────────

    def test_anular_devuelve_las_bolsas(self):
        id_ = self.registrar().json()["id_asignacion"]
        r = self.client.post(f"{URL}{id_}/anular/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["anulada"])
        self.assertEqual(self.stock_almacen(self.cemento), Decimal("20"))
        self.assertEqual(self.stock_camion(self.cemento), Decimal("0"))
        self.assertEqual(self.client.post(f"{URL}{id_}/anular/").status_code,
                         400)

    def test_el_capataz_no_anula(self):
        id_ = self.registrar().json()["id_asignacion"]
        self.auth(self.capataz)
        self.assertEqual(
            self.client.post(f"{URL}{id_}/anular/").status_code, 403)

    def test_no_se_anula_lo_que_ya_se_gasto(self):
        id_ = self.registrar().json()["id_asignacion"]
        StockCamion.objects.filter(material=self.cemento).update(cantidad=2)
        r = self.client.post(f"{URL}{id_}/anular/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.stock_almacen(self.cemento), Decimal("15"))

    # ── Listas ───────────────────────────────────────────────────────────────

    def test_las_del_dia(self):
        self.registrar()
        self.registrar(cantidad="2")
        self.assertEqual(len(self.client.get(URL).json()), 2)
        self.assertEqual(len(self.client.get(URL, {"dia": "2020-01-01"}).json()), 0)

    def test_opciones(self):
        self.auth(self.encargado)
        d = self.client.get(f"{URL}opciones/").json()
        self.assertEqual([c["placa"] for c in d["camiones"]], ["ABC-123"])
        [cemento] = d["agregados"]
        self.assertEqual(Decimal(cemento["saldos"][str(self.almacen.pk)]),
                         Decimal("20"))
