"""
Lo que sale del plano se cobra una vez por SST, no por cada poste.

El plano es uno solo de la SST. Si una reforma lleva tres postes y cada uno
liquidara la vereda o el arrastre dibujados ahí, se cobrarían tres veces. Estas
partidas quedan marcadas como de SST: el primer poste las liquida y en los
demás se bloquean.

En las actividades donde una SST es un poste esto no cambia nada.
"""
from datetime import date

from django.core.management import call_command

from ..models import (
    Actividad, ActividadTipoTrabajo, LiquidacionPartida, LiquidacionSuministro,
    ManoDeObra, SST, SSTSuministro, Suministro, TipoTrabajo,
)
from .base import BaseAPITestCase

REFORMA = "Reforma - cambio de poste inacc. aereo - cabria"


class PartidasDeSstTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.actividad = Actividad.objects.create(
            nombre=REFORMA, varios_postes=True)
        self.tipo = TipoTrabajo.objects.create(nombre="Poste cabria")
        ActividadTipoTrabajo.objects.create(
            actividad=self.actividad, tipo_trabajo=self.tipo)
        self.sst = SST.objects.create(
            sst="3920624", codigo="SST-3920624", empresa=self.empresa,
            distrito="SURCO", actividad=self.actividad,
            fecha_ejecucion=date.today())
        self.poste1 = self._poste("771000100")
        self.poste2 = self._poste("771000101")

        # Del plano: se cobra una vez por SST.
        self.arrastre = ManoDeObra.objects.create(
            partida="*090630", descripcion="ARRASTRE EN PLANO", precio="10")
        # Del poste: cada uno el suyo.
        self.inspeccion = ManoDeObra.objects.create(
            partida="*094395", descripcion="INSPECCION PREVIA", precio="53.30")
        call_command("configurar_partidas_de_sst", verbosity=0)

    def _poste(self, numero):
        poste = Suministro.objects.create(numero_suministro=numero)
        SSTSuministro.objects.create(sst=self.sst, suministro=poste)
        return poste

    def liquidar(self, poste, partidas):
        self.auth(self.capataz)
        return self.client.post("/api/liquidaciones/", {
            "suministro": poste.pk,
            "sst_externo": self.sst.codigo,
            "usuario": self.capataz.pk,
            "tipo_trabajo": self.tipo.pk,
            "partidas": [{"mano_de_obra": mo.pk, "cantidad": c}
                         for mo, c in partidas.items()],
        }, format="json")

    def ocupadas(self, poste=None):
        self.auth(self.capataz)
        params = {"sst": self.sst.codigo}
        if poste is not None:
            params["suministro"] = poste.pk
        r = self.client.get("/api/liquidaciones/partidas_de_sst/", params)
        self.assertEqual(r.status_code, 200)
        return r.data

    # ── El catálogo ─────────────────────────────────────────────────────────

    def test_el_comando_marca_las_del_plano(self):
        self.arrastre.refresh_from_db()
        self.assertEqual(self.arrastre.ambito, ManoDeObra.AMBITO_SST)

    def test_las_demas_siguen_siendo_por_poste(self):
        self.inspeccion.refresh_from_db()
        self.assertEqual(self.inspeccion.ambito, ManoDeObra.AMBITO_POSTE)

    def test_el_comando_es_idempotente(self):
        call_command("configurar_partidas_de_sst", verbosity=0)
        self.arrastre.refresh_from_db()
        self.assertEqual(self.arrastre.ambito, ManoDeObra.AMBITO_SST)

    def test_una_partida_que_sale_de_la_lista_vuelve_a_ser_de_poste(self):
        suelta = ManoDeObra.objects.create(
            partida="*099999", descripcion="OTRA", precio="1",
            ambito=ManoDeObra.AMBITO_SST)
        call_command("configurar_partidas_de_sst", verbosity=0)
        suelta.refresh_from_db()
        self.assertEqual(suelta.ambito, ManoDeObra.AMBITO_POSTE)

    # ── El bloqueo ──────────────────────────────────────────────────────────

    def test_el_primer_poste_la_liquida(self):
        r = self.liquidar(self.poste1, {self.arrastre: 40})
        self.assertEqual(r.status_code, 201, r.data)

    def test_el_segundo_poste_ya_no_puede(self):
        self.liquidar(self.poste1, {self.arrastre: 40})
        r = self.liquidar(self.poste2, {self.arrastre: 40})
        self.assertEqual(r.status_code, 400)
        self.assertIn("una vez por SST", r.data["detail"])
        self.assertIn("771000100", r.data["detail"])

    def test_el_aviso_es_texto_plano(self):
        """La app lee `detail` como String: una lista la haría reventar."""
        self.liquidar(self.poste1, {self.arrastre: 40})
        r = self.liquidar(self.poste2, {self.arrastre: 40})
        self.assertIsInstance(r.data["detail"], str)

    def test_el_segundo_poste_si_puede_liquidar_lo_suyo(self):
        self.liquidar(self.poste1, {self.arrastre: 40})
        r = self.liquidar(self.poste2, {self.inspeccion: 1})
        self.assertEqual(r.status_code, 201, r.data)

    def test_en_cero_no_molesta(self):
        """Una partida automática que salió en cero no bloquea nada."""
        self.liquidar(self.poste1, {self.arrastre: 40})
        r = self.liquidar(self.poste2, {self.arrastre: 0, self.inspeccion: 1})
        self.assertEqual(r.status_code, 201, r.data)

    def test_corregir_el_mismo_poste_no_se_bloquea_a_si_mismo(self):
        """Volver a grabar es corregir: su propia liquidación no cuenta."""
        self.liquidar(self.poste1, {self.arrastre: 40})
        r = self.liquidar(self.poste1, {self.arrastre: 55})
        self.assertEqual(r.status_code, 201, r.data)
        liq = LiquidacionSuministro.objects.get(suministro=self.poste1)
        self.assertEqual(
            str(LiquidacionPartida.objects.get(liquidacion=liq).cantidad),
            "55.00")

    def test_otra_sst_no_se_estorba(self):
        otra = SST.objects.create(
            sst="9999", codigo="SST-9999", empresa=self.empresa,
            distrito="LIMA", actividad=self.actividad)
        poste = Suministro.objects.create(numero_suministro="880000100")
        SSTSuministro.objects.create(sst=otra, suministro=poste)
        self.liquidar(self.poste1, {self.arrastre: 40})
        self.auth(self.capataz)
        r = self.client.post("/api/liquidaciones/", {
            "suministro": poste.pk, "sst_externo": otra.codigo,
            "usuario": self.capataz.pk, "tipo_trabajo": self.tipo.pk,
            "partidas": [{"mano_de_obra": self.arrastre.pk, "cantidad": 40}],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    # ── Lo que la app consulta para bloquear ────────────────────────────────

    def test_dice_que_partida_esta_tomada_y_por_quien(self):
        self.liquidar(self.poste1, {self.arrastre: 40})
        self.assertEqual(self.ocupadas(), {"*090630": "771000100"})

    def test_para_el_poste_que_la_tiene_no_esta_tomada(self):
        self.liquidar(self.poste1, {self.arrastre: 40})
        self.assertEqual(self.ocupadas(poste=self.poste1), {})

    def test_para_los_demas_si(self):
        self.liquidar(self.poste1, {self.arrastre: 40})
        self.assertEqual(self.ocupadas(poste=self.poste2),
                         {"*090630": "771000100"})

    def test_lo_de_poste_nunca_aparece(self):
        self.liquidar(self.poste1, {self.inspeccion: 1})
        self.assertEqual(self.ocupadas(), {})

    def test_sin_sst_no_responde(self):
        self.auth(self.capataz)
        r = self.client.get("/api/liquidaciones/partidas_de_sst/")
        self.assertEqual(r.status_code, 400)
