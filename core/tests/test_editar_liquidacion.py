"""
Corregir una liquidación ya guardada.

Se entra por el consolidado, que ahora dice qué postes tiene cada SST y qué
se le liquidó a cada uno. La pantalla vuelve a cargar lo guardado y al grabar
reemplaza la liquidación anterior. Lo que importa aquí es que el material de
la que se reemplaza vuelva al camión: sin eso, cada corrección le come stock.
"""
from datetime import date

from ..models import (
    Actividad, ActividadTipoTrabajo, ManoDeObra, SST, SSTSuministro,
    StockCamion, Suministro, TipoTrabajo,
)
from .base import BaseAPITestCase

ACTIVIDAD = "Cambio de poste inacc. cabria aereo"


class EditarLiquidacionTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.actividad = Actividad.objects.create(nombre=ACTIVIDAD)
        self.sst = SST.objects.create(
            sst="77777", codigo="SST-77777", empresa=self.empresa,
            distrito="LIMA", fecha_ejecucion=date.today())
        self.poste = Suministro.objects.create(
            numero_suministro="900000777", distrito="LIMA")
        SSTSuministro.objects.create(sst=self.sst, suministro=self.poste)

        self.tipo = TipoTrabajo.objects.create(nombre="Mensula simple")
        ActividadTipoTrabajo.objects.create(
            actividad=self.actividad, tipo_trabajo=self.tipo)
        self.partida = ManoDeObra.objects.create(
            partida="*090191", descripcion="COLOCACION DE MENSULA",
            precio="53.70")
        self.stock = StockCamion.objects.create(
            camion=self.camion, material=self.material_a, cantidad=10)

    def liquidar(self, cantidad_material, cantidad_partida=1):
        self.auth(self.capataz)
        r = self.client.post("/api/liquidaciones/", {
            "suministro": self.poste.pk,
            "sst_externo": self.sst.codigo,
            "usuario": self.capataz.pk,
            "tipo_trabajo": self.tipo.pk,
            "partidas": [{"mano_de_obra": self.partida.pk,
                          "cantidad": cantidad_partida}],
            "materiales": [{"material": self.material_a.pk,
                            "cantidad": cantidad_material}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def lista(self, url):
        """El cuerpo de un listado, venga paginado o no."""
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        return r.data["results"] if isinstance(r.data, dict) else r.data

    def stock_actual(self):
        self.stock.refresh_from_db()
        return self.stock.cantidad

    # ── Stock al corregir ────────────────────────────────────────────────────

    def test_liquidar_descuenta_del_camion(self):
        self.liquidar(3)
        self.assertEqual(str(self.stock_actual()), "7.00")

    def test_corregir_con_la_misma_cantidad_deja_el_stock_igual(self):
        self.liquidar(3)
        self.liquidar(3)
        self.assertEqual(str(self.stock_actual()), "7.00")

    def test_corregir_hacia_abajo_devuelve_la_diferencia(self):
        self.liquidar(3)
        self.liquidar(1)
        self.assertEqual(str(self.stock_actual()), "9.00")

    def test_corregir_hacia_arriba_descuenta_solo_lo_que_falta(self):
        self.liquidar(3)
        self.liquidar(4)
        self.assertEqual(str(self.stock_actual()), "6.00")

    def test_corregir_no_acumula_liquidaciones(self):
        self.liquidar(3)
        self.liquidar(2)
        self.auth(self.capataz)
        self.assertEqual(
            len(self.lista(f"/api/liquidaciones/?suministro={self.poste.pk}")), 1)

    # ── Leer lo liquidado para volver a cargarlo ─────────────────────────────

    def test_lo_liquidado_se_puede_volver_a_leer(self):
        self.liquidar(3, cantidad_partida=2)
        self.auth(self.capataz)
        liq = self.lista(f"/api/liquidaciones/?suministro={self.poste.pk}")[0]
        self.assertEqual(liq["tipo_trabajo"], self.tipo.pk)
        self.assertEqual(liq["partidas"][0]["mano_de_obra"], self.partida.pk)
        self.assertEqual(liq["partidas"][0]["cantidad"], "2.00")
        self.assertEqual(liq["materiales"][0]["material"], self.material_a.pk)
        self.assertEqual(liq["materiales"][0]["cantidad"], "3.00")

    def test_el_poste_externo_se_busca_por_su_numero_y_su_sst(self):
        self.auth(self.capataz)
        r = self.client.post("/api/liquidaciones/", {
            "suministro_externo": "800000111",
            "sst_externo": self.sst.codigo,
            "usuario": self.capataz.pk,
            "tipo_trabajo": self.tipo.pk,
            "partidas": [{"mano_de_obra": self.partida.pk, "cantidad": 1}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(self.lista(
            "/api/liquidaciones/"
            f"?suministro_externo=800000111&sst={self.sst.codigo}")), 1)
        self.assertEqual(len(self.lista(
            "/api/liquidaciones/?suministro_externo=800000111&sst=OTRA-SST")), 0)

    # ── El consolidado dice por dónde entrar ─────────────────────────────────

    def test_el_consolidado_trae_los_postes_de_la_sst(self):
        self.liquidar(1)
        self.auth(self.capataz)
        r = self.client.get("/api/liquidaciones/consolidado/")
        fila = [x for x in r.data if x["sst"] == self.sst.codigo][0]
        self.assertEqual(len(fila["postes"]), 1)
        poste = fila["postes"][0]
        self.assertEqual(poste["suministro"], self.poste.numero_suministro)
        self.assertEqual(poste["suministro_id"], self.poste.pk)
        self.assertEqual(poste["actividad"], ACTIVIDAD)
        self.assertEqual(poste["distrito"], "LIMA")
        self.assertEqual(len(poste["liquidaciones"]), 1)
        self.assertEqual(poste["liquidaciones"][0]["tipo_trabajo"],
                         self.tipo.pk)
        self.assertEqual(poste["liquidaciones"][0]["tipo_trabajo_nombre"],
                         "Mensula simple")

    def test_dos_postes_en_la_misma_sst_salen_los_dos(self):
        self.liquidar(1)
        otro = Suministro.objects.create(numero_suministro="900000778")
        SSTSuministro.objects.create(sst=self.sst, suministro=otro)
        self.auth(self.capataz)
        self.client.post("/api/liquidaciones/", {
            "suministro": otro.pk,
            "sst_externo": self.sst.codigo,
            "usuario": self.capataz.pk,
            "tipo_trabajo": self.tipo.pk,
            "partidas": [{"mano_de_obra": self.partida.pk, "cantidad": 1}],
        }, format="json")
        r = self.client.get("/api/liquidaciones/consolidado/")
        fila = [x for x in r.data if x["sst"] == self.sst.codigo][0]
        self.assertEqual([p["suministro"] for p in fila["postes"]],
                         ["900000777", "900000778"])

    def test_otro_usuario_corrige_y_no_quedan_dos(self):
        # Desde el consolidado corrige el liquidador o el coordinador, no el
        # capataz que cargó. Si quedaran las dos, el consolidado las sumaría.
        self.liquidar(2)
        self.auth(self.encargado)
        r = self.client.post("/api/liquidaciones/", {
            "suministro": self.poste.pk,
            "sst_externo": self.sst.codigo,
            "usuario": self.encargado.pk,
            "tipo_trabajo": self.tipo.pk,
            "partidas": [{"mano_de_obra": self.partida.pk, "cantidad": 5}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        liquidaciones = self.lista(
            f"/api/liquidaciones/?suministro={self.poste.pk}")
        self.assertEqual(len(liquidaciones), 1)
        self.assertEqual(liquidaciones[0]["partidas"][0]["cantidad"], "5.00")

    def test_el_material_vuelve_al_camion_de_quien_lo_cargo(self):
        # Corrige otro usuario, pero el material sale (y vuelve) del camión
        # del capataz que lo consumió.
        self.liquidar(3)
        self.assertEqual(str(self.stock_actual()), "7.00")
        self.auth(self.encargado)
        self.client.post("/api/liquidaciones/", {
            "suministro": self.poste.pk,
            "sst_externo": self.sst.codigo,
            "usuario": self.encargado.pk,
            "tipo_trabajo": self.tipo.pk,
            "partidas": [{"mano_de_obra": self.partida.pk, "cantidad": 1}],
        }, format="json")
        self.assertEqual(str(self.stock_actual()), "10.00")

    def test_la_hora_de_ejecucion_sale_en_el_consolidado(self):
        from datetime import time
        SST.objects.filter(pk=self.sst.pk).update(hora_ejecucion=time(14, 30))
        self.liquidar(1)
        self.auth(self.capataz)
        r = self.client.get("/api/liquidaciones/consolidado/")
        fila = [x for x in r.data if x["sst"] == self.sst.codigo][0]
        self.assertEqual(fila["hora"], "14:30")
