"""
Consolidado de la actividad de cabria.

Cada retenida ya trae incluido su perno de anclaje, así que si además se
liquidó ese perno en ferretería no se puede cobrar dos veces.
"""
from datetime import date

from ..models import (
    Actividad, ActividadTipoTrabajo, LiquidacionPartida, LiquidacionSuministro,
    ManoDeObra, SST, SSTSuministro, Suministro, TipoTrabajo,
)
from .base import BaseAPITestCase

ACTIVIDAD = "Cambio de poste inacc. cabria aereo"


class ConsolidadoCabriaTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.actividad = Actividad.objects.create(nombre=ACTIVIDAD)
        self.sst = SST.objects.create(
            sst="55555", codigo="SST-55555", empresa=self.empresa,
            distrito="LIMA", fecha_ejecucion=date.today())
        self.poste = Suministro.objects.create(numero_suministro="900000001")
        SSTSuministro.objects.create(sst=self.sst, suministro=self.poste)

        self.retenida = self._tipo("Retenida Violin")
        self.ferreteria = self._tipo("Ferreteria")

        self.p_violin = ManoDeObra.objects.create(
            partida="*090310", descripcion="RETENIDA SIMPLE O VIOLIN",
            precio="343.83")
        self.p_aereo = ManoDeObra.objects.create(
            partida="*090320", descripcion="RETENIDA-TEMPLADOR AEREO",
            precio="83.38")
        self.p_perno = ManoDeObra.objects.create(
            partida="*090392", descripcion="PERNO PARA ANCLAJE", precio="9.75")

    def _tipo(self, nombre):
        tipo = TipoTrabajo.objects.create(nombre=nombre)
        ActividadTipoTrabajo.objects.create(
            actividad=self.actividad, tipo_trabajo=tipo)
        return tipo

    def liquidar(self, tipo, partidas):
        liq = LiquidacionSuministro.objects.create(
            suministro=self.poste, usuario=self.capataz, tipo_trabajo=tipo)
        for partida, cantidad in partidas.items():
            LiquidacionPartida.objects.create(
                liquidacion=liq, mano_de_obra=partida, cantidad=cantidad)
        return liq

    def consolidado(self):
        self.auth(self.capataz)
        r = self.client.get("/api/liquidaciones/consolidado/")
        self.assertEqual(r.status_code, 200)
        fila = [x for x in r.data if x["sst"] == self.sst.codigo]
        self.assertEqual(len(fila), 1, "Debería salir una fila por SST")
        return {p["partida"]: p for p in fila[0]["partidas"]}

    def test_la_retenida_se_come_el_perno_de_ferreteria(self):
        self.liquidar(self.retenida, {self.p_violin: 1})
        self.liquidar(self.ferreteria, {self.p_perno: 1})
        partidas = self.consolidado()
        perno = partidas["*090392"]
        self.assertEqual(perno["cantidad_real"], "1.00")
        self.assertEqual(perno["cantidad_incluida"], "1.00")
        self.assertEqual(perno["cantidad_cobrada"], "0.00")

    def test_el_perno_de_mas_si_se_cobra(self):
        # Tres pernos con una sola retenida: dos son trabajo aparte.
        self.liquidar(self.retenida, {self.p_violin: 1})
        self.liquidar(self.ferreteria, {self.p_perno: 3})
        self.assertEqual(
            self.consolidado()["*090392"]["cantidad_cobrada"], "2.00")

    def test_el_templador_aereo_tambien_incluye_su_perno(self):
        self.liquidar(self.retenida, {self.p_aereo: 1})
        self.liquidar(self.ferreteria, {self.p_perno: 1})
        self.assertEqual(
            self.consolidado()["*090392"]["cantidad_cobrada"], "0.00")

    def test_dos_retenidas_incluyen_dos_pernos(self):
        self.liquidar(self.retenida, {self.p_violin: 2})
        self.liquidar(self.ferreteria, {self.p_perno: 2})
        self.assertEqual(
            self.consolidado()["*090392"]["cantidad_cobrada"], "0.00")

    def test_sin_retenida_el_perno_se_cobra_entero(self):
        self.liquidar(self.ferreteria, {self.p_perno: 2})
        self.assertEqual(
            self.consolidado()["*090392"]["cantidad_cobrada"], "2.00")

    def test_la_retenida_se_cobra_completa(self):
        # El descuento es del perno, no de la retenida.
        self.liquidar(self.retenida, {self.p_violin: 1})
        self.assertEqual(
            self.consolidado()["*090310"]["cantidad_cobrada"], "1.00")

    def test_en_cabria_no_se_cuentan_cambios_de_poste(self):
        self.liquidar(self.retenida, {self.p_violin: 2})
        self.auth(self.capataz)
        r = self.client.get("/api/liquidaciones/consolidado/")
        fila = [x for x in r.data if x["sst"] == self.sst.codigo][0]
        self.assertEqual(fila["cambios_poste"], "0")
