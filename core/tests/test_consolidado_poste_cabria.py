"""
Lo que el cambio de poste con cabria ya trae incluido.

Hay dos formas de descuento. Una por partida, como el acarreo o la rotura de
vereda. Y otra por grupo: el paquete trae dos empalmes sin importar de cuál de
los dos tipos, y una luminaria y un pastoral, se hayan instalado, retirado o
trasladado. Esa bolsa compartida es lo que se prueba aquí.
"""
from datetime import date

from ..models import (
    Actividad, ActividadTipoTrabajo, LiquidacionPartida, LiquidacionSuministro,
    ManoDeObra, SST, SSTSuministro, Suministro, TipoTrabajo,
)
from .base import BaseAPITestCase

ACTIVIDAD = "Cambio de poste inacc. cabria aereo"


class ConsolidadoPosteCabriaTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.actividad = Actividad.objects.create(nombre=ACTIVIDAD)
        self.sst = SST.objects.create(
            sst="77777", codigo="SST-77777", empresa=self.empresa,
            distrito="LIMA", fecha_ejecucion=date.today())
        self.poste_sum = Suministro.objects.create(numero_suministro="800000001")
        SSTSuministro.objects.create(sst=self.sst, suministro=self.poste_sum)

        self.tipo_poste = self._tipo("Poste cabria")
        self.tipo_alumbrado = self._tipo("Alumbrado cabria")

        self.partidas = {}
        for codigo, precio in [
            ("*090470", "1535.09"), ("*090471", "1312.57"),
            ("*090633", "0.67"), ("*091840", "119.73"), ("*091240", "251.40"),
            ("*091608", "13.44"), ("*090810", "5.31"),
            ("*091320", "86.97"), ("*091316", "60.88"), ("*091322", "113.06"),
            ("*091346", "113.35"), ("*091357", "79.34"), ("*091356", "147.35"),
        ]:
            self.partidas[codigo] = ManoDeObra.objects.create(
                partida=codigo, descripcion=codigo, precio=precio)

    def _tipo(self, nombre):
        tipo = TipoTrabajo.objects.create(nombre=nombre)
        ActividadTipoTrabajo.objects.create(
            actividad=self.actividad, tipo_trabajo=tipo)
        return tipo

    def liquidar(self, tipo, cantidades):
        liq = LiquidacionSuministro.objects.create(
            suministro=self.poste_sum, usuario=self.capataz, tipo_trabajo=tipo)
        for codigo, cantidad in cantidades.items():
            LiquidacionPartida.objects.create(
                liquidacion=liq, mano_de_obra=self.partidas[codigo],
                cantidad=cantidad)

    def consolidado(self):
        self.auth(self.capataz)
        r = self.client.get("/api/liquidaciones/consolidado/")
        self.assertEqual(r.status_code, 200)
        fila = [x for x in r.data if x["sst"] == self.sst.codigo][0]
        return {p["partida"]: p for p in fila["partidas"]}

    def cobrado(self, codigo):
        return self.consolidado()[codigo]["cantidad_cobrada"]

    def test_el_cambio_incluye_cien_de_acarreo(self):
        self.liquidar(self.tipo_poste, {"*090470": 1, "*090633": 120})
        self.assertEqual(self.cobrado("*090633"), "20.00")

    def test_el_cambio_incluye_dos_roturas_de_vereda(self):
        self.liquidar(self.tipo_poste, {"*090470": 1, "*091840": 3})
        self.assertEqual(self.cobrado("*091840"), "1.00")

    def test_dos_empalmes_incluidos_repartidos_entre_los_dos_tipos(self):
        # Uno de cada tipo: los dos entran en la bolsa de dos.
        self.liquidar(self.tipo_poste, {"*090470": 1})
        self.liquidar(self.tipo_alumbrado, {"*091608": 1, "*090810": 1})
        partidas = self.consolidado()
        self.assertEqual(partidas["*091608"]["cantidad_cobrada"], "0.00")
        self.assertEqual(partidas["*090810"]["cantidad_cobrada"], "0.00")

    def test_la_bolsa_de_empalmes_no_descuenta_de_mas(self):
        # Tres de un tipo y dos del otro: solo se descuentan dos en total.
        self.liquidar(self.tipo_poste, {"*090470": 1})
        self.liquidar(self.tipo_alumbrado, {"*091608": 3, "*090810": 2})
        partidas = self.consolidado()
        cobrado = (float(partidas["*091608"]["cantidad_cobrada"])
                   + float(partidas["*090810"]["cantidad_cobrada"]))
        self.assertEqual(cobrado, 3.0)

    def test_una_sola_luminaria_incluida_aunque_se_instale_y_se_retire(self):
        self.liquidar(self.tipo_poste, {"*090470": 1})
        self.liquidar(self.tipo_alumbrado, {"*091320": 1, "*091316": 1})
        partidas = self.consolidado()
        cobrado = (float(partidas["*091320"]["cantidad_cobrada"])
                   + float(partidas["*091316"]["cantidad_cobrada"]))
        self.assertEqual(cobrado, 1.0)

    def test_un_solo_pastoral_incluido(self):
        self.liquidar(self.tipo_poste, {"*090470": 1})
        self.liquidar(self.tipo_alumbrado, {"*091346": 2, "*091356": 1})
        partidas = self.consolidado()
        cobrado = (float(partidas["*091346"]["cantidad_cobrada"])
                   + float(partidas["*091356"]["cantidad_cobrada"]))
        self.assertEqual(cobrado, 2.0)

    def test_dos_cambios_de_poste_duplican_lo_incluido(self):
        self.liquidar(self.tipo_poste, {"*090470": 2})
        self.liquidar(self.tipo_alumbrado, {"*091320": 2})
        self.assertEqual(self.cobrado("*091320"), "0.00")

    def test_sin_cambio_de_poste_no_se_descuenta_nada(self):
        self.liquidar(self.tipo_alumbrado, {"*091608": 2, "*091320": 1})
        partidas = self.consolidado()
        self.assertEqual(partidas["*091608"]["cantidad_cobrada"], "2.00")
        self.assertEqual(partidas["*091320"]["cantidad_cobrada"], "1.00")

    def test_el_cambio_sin_vereda_incluye_lo_mismo(self):
        self.liquidar(self.tipo_poste, {"*090471": 1, "*091240": 1})
        self.assertEqual(self.cobrado("*091240"), "0.00")
