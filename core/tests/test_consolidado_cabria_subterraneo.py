"""
Consolidado de cabria subterráneo: lo que el cambio de poste ya incluye.

Desde el 2026-09-20 el alumbrado de esta actividad es el mismo tipo de trabajo
que el de cabria aérea, así que trae también el conector *090810. Los
descuentos se cuentan por grupos, igual que en la aérea: el paquete incluye dos
empalmes sea del tipo que sea, y una luminaria y un pastoral, se hayan
instalado, retirado o trasladado.
"""
from datetime import date

from ..models import (
    Actividad, ActividadTipoTrabajo, LiquidacionPartida, LiquidacionSuministro,
    ManoDeObra, SST, SSTSuministro, Suministro, TipoTrabajo,
)
from .base import BaseAPITestCase

ACTIVIDAD = "Cambio de poste inacc. cabria subterraneo"


class ConsolidadoCabriaSubterraneoTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.actividad = Actividad.objects.create(nombre=ACTIVIDAD)
        self.sst = SST.objects.create(
            sst="66666", codigo="SST-66666", empresa=self.empresa,
            distrito="LIMA", fecha_ejecucion=date.today())
        self.poste_sum = Suministro.objects.create(
            numero_suministro="900000066")
        SSTSuministro.objects.create(sst=self.sst, suministro=self.poste_sum)

        self.t_poste = self._tipo("poste")
        self.t_alumbrado = self._tipo("Alumbrado cabria")

        self.p_cambio = self._partida("*090470", "CAMBIO DE POSTE CON VEREDA")
        self.p_empalme = self._partida("*091608", "EMPALME AEREO BT")
        self.p_conector = self._partida("*090810", "CONECTOR HASTA 300 MM2")
        self.p_luminaria = self._partida("*091320", "LUMINARIA COMPLETA")
        self.p_retiro_lum = self._partida("*091316", "RETIRO DE LUMINARIA")
        self.p_acarreo = self._partida("*090633", "ACARREO PARA CIMENTACION")

    def _tipo(self, nombre):
        tipo = TipoTrabajo.objects.create(nombre=nombre)
        ActividadTipoTrabajo.objects.create(
            actividad=self.actividad, tipo_trabajo=tipo)
        return tipo

    def _partida(self, codigo, descripcion):
        return ManoDeObra.objects.create(
            partida=codigo, descripcion=descripcion, precio="10.00")

    def liquidar(self, tipo, partidas):
        liq = LiquidacionSuministro.objects.create(
            suministro=self.poste_sum, usuario=self.capataz, tipo_trabajo=tipo)
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

    def cobrado(self, partidas, *codigos):
        """Lo que se cobra sumando varias partidas: en un grupo da igual sobre
        cuál de ellas caiga el descuento."""
        return sum(float(partidas[c]["cantidad_cobrada"]) for c in codigos
                   if c in partidas)

    def cambio_de_poste(self, cuantos=1):
        self.liquidar(self.t_poste, {self.p_cambio: cuantos})

    # ── Empalme y conector comparten cupo ───────────────────────────────────

    def test_el_paquete_incluye_dos_empalmes(self):
        self.cambio_de_poste()
        self.liquidar(self.t_alumbrado, {self.p_empalme: 2})
        self.assertEqual(self.consolidado()["*091608"]["cantidad_cobrada"],
                         "0.00")

    def test_el_conector_entra_en_el_mismo_cupo(self):
        """Lo que se ganó al compartir el tipo de trabajo con la aérea: antes
        *090810 no estaba contemplado y se cobraba entero."""
        self.cambio_de_poste()
        self.liquidar(self.t_alumbrado,
                      {self.p_empalme: 1, self.p_conector: 1})
        partidas = self.consolidado()
        self.assertEqual(self.cobrado(partidas, "*091608", "*090810"), 0.0)

    def test_el_tercero_si_se_cobra(self):
        self.cambio_de_poste()
        self.liquidar(self.t_alumbrado,
                      {self.p_empalme: 2, self.p_conector: 1})
        partidas = self.consolidado()
        self.assertEqual(self.cobrado(partidas, "*091608", "*090810"), 1.0)

    def test_dos_cambios_de_poste_incluyen_cuatro(self):
        self.cambio_de_poste(2)
        self.liquidar(self.t_alumbrado,
                      {self.p_empalme: 2, self.p_conector: 2})
        partidas = self.consolidado()
        self.assertEqual(self.cobrado(partidas, "*091608", "*090810"), 0.0)

    def test_sin_cambio_de_poste_se_cobra_todo(self):
        self.liquidar(self.t_alumbrado,
                      {self.p_empalme: 1, self.p_conector: 1})
        partidas = self.consolidado()
        self.assertEqual(self.cobrado(partidas, "*091608", "*090810"), 2.0)

    # ── La luminaria cuenta una sola vez ────────────────────────────────────

    def test_instalar_y_retirar_luminaria_cuenta_como_una(self):
        self.cambio_de_poste()
        self.liquidar(self.t_alumbrado,
                      {self.p_luminaria: 1, self.p_retiro_lum: 1})
        partidas = self.consolidado()
        self.assertEqual(self.cobrado(partidas, "*091320", "*091316"), 1.0)

    # ── Lo que no cambió ────────────────────────────────────────────────────

    def test_el_acarreo_sigue_con_sus_cien_incluidos(self):
        self.cambio_de_poste()
        self.liquidar(self.t_poste, {self.p_acarreo: 120})
        partidas = self.consolidado()
        self.assertEqual(partidas["*090633"]["cantidad_incluida"], "100.00")
