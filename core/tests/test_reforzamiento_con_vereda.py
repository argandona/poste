"""
El reforzamiento de poste con vereda: su catálogo y las medidas que se
guardan con la liquidación.

Las partidas que ya estaban en el catálogo las cobran también cabria y
viento, así que el comando no les toca el precio. Las nuevas nacen con el
precio que dio el usuario, y los paños con que se calcularon las cantidades
viajan con la liquidación para poder reabrirla.
"""
import io
from decimal import Decimal

from django.core.management import call_command

from ..models import (ActividadTipoTrabajo, LiquidacionSuministro, ManoDeObra,
                      Material, StockCamion, TipoTrabajo)
from .base import BaseAPITestCase

TIPO = "Reforzamiento con vereda"

# Las que ya existían, con el precio viejo que no debe cambiar.
EXISTENTES = {
    "*094395": "53.30",
    "*090248": "36.82",
    "*095266": "119.56",
    "*091842": "68.37",
    "*098203": "4.04",
    "*090633": "0.67",
}


class ReforzamientoConVeredaTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        for codigo, precio in EXISTENTES.items():
            ManoDeObra.objects.create(
                partida=codigo, descripcion=codigo, precio=precio)

    def configurar(self):
        call_command("configurar_reforzamiento", stdout=io.StringIO())
        return TipoTrabajo.objects.get(nombre=TIPO)

    # ── El catálogo ──────────────────────────────────────────────────────────

    def test_el_tipo_cuelga_de_la_actividad_con_vereda(self):
        tipo = self.configurar()
        self.assertEqual(
            list(ActividadTipoTrabajo.objects.filter(tipo_trabajo=tipo)
                 .values_list("actividad__nombre", flat=True)),
            ["Reforzamiento de poste con vereda"])

    def test_lleva_las_dieciseis_partidas_en_el_orden_de_la_obra(self):
        tipo = self.configurar()
        codigos = [p.mano_de_obra.partida for p in tipo.partidas.all()]
        self.assertEqual(codigos, [
            "*094395", "*090248", "*090251", "*095266", "*095275", "*095280",
            "*091842", "*091845", "*094919", "*091830", "*095230", "*098203",
            "*098822", "*090633", "*099090", "*091673"])

    def test_la_inspeccion_y_el_reforzamiento_arrancan_en_uno(self):
        tipo = self.configurar()
        iniciales = {p.mano_de_obra.partida: p.cantidad_inicial
                     for p in tipo.partidas.all()}
        self.assertEqual(iniciales["*094395"], 1)
        self.assertEqual(iniciales["*090251"], 1)
        self.assertEqual(iniciales["*090248"], 0)

    def test_no_toca_el_precio_de_las_que_ya_existian(self):
        self.configurar()
        for codigo, precio in EXISTENTES.items():
            self.assertEqual(ManoDeObra.objects.get(partida=codigo).precio,
                             Decimal(precio), codigo)

    def test_las_nuevas_nacen_con_el_precio_dado(self):
        self.configurar()
        precio = lambda c: ManoDeObra.objects.get(partida=c).precio
        self.assertEqual(precio("*090251"), Decimal("467.52"))
        self.assertEqual(precio("*095280"), Decimal("180.00"))
        self.assertEqual(precio("*091845"), Decimal("31.82"))
        self.assertEqual(precio("*095230"), Decimal("122.42"))
        # Sin precio dado: provisional, para cargarlo desde Configuración.
        self.assertEqual(precio("*095275"), Decimal("1.00"))

    def test_la_reparacion_de_20cm_se_corrige_a_180(self):
        ManoDeObra.objects.create(partida="*095280", precio="140.00",
                                  descripcion="REPARACION DE VEREDA DE 20CM M2")
        self.configurar()
        partida = ManoDeObra.objects.get(partida="*095280")
        self.assertEqual(partida.precio, Decimal("180.00"))
        self.assertEqual(partida.descripcion, "REPARACION DE VEREDA O PISTA 20CM")

    def test_la_rotura_con_maquina_se_corrige_a_31_82(self):
        ManoDeObra.objects.create(partida="*091845", precio="33.35",
                                  descripcion="ROTURA DE VEREDA CON MAQUINA")
        self.configurar()
        partida = ManoDeObra.objects.get(partida="*091845")
        self.assertEqual(partida.precio, Decimal("31.82"))
        self.assertEqual(partida.descripcion,
                         "ROTURA DE VEREDA CON MAQUINA CORTADORA EN M2")

    def test_lleva_los_siete_refuerzos(self):
        tipo = self.configurar()
        descripciones = [m.material.descripcion for m in tipo.materiales.all()]
        self.assertEqual(sum("REFUERZO" in d for d in descripciones), 7)
        self.assertFalse(Material.objects.get(matricula="6913290").es_agregado)

    def test_lleva_fleje_hebilla_y_pegamento(self):
        # El fleje ya existe por cabria: se usa el suyo, sin tocarlo.
        Material.objects.create(
            matricula="1014213", precio="12.50",
            descripcion="FLEJE DE ACERO INOXIDABLE 19MM (3/4\")")
        tipo = self.configurar()
        matriculas = {m.material.matricula for m in tipo.materiales.all()}
        self.assertTrue({"1014213", "1014308", "2139148"} <= matriculas)
        fleje = Material.objects.get(matricula="1014213")
        self.assertEqual(fleje.precio, Decimal("12.50"))
        self.assertIn("ACERO", fleje.descripcion)
        pegamento = Material.objects.get(matricula="2139148")
        self.assertEqual(pegamento.descripcion, "PEGAMENTO EN GEL")
        self.assertEqual(pegamento.precio, Decimal("1.00"))

    def test_no_pisa_lo_corregido_desde_configuracion(self):
        self.configurar()
        ManoDeObra.objects.filter(partida="*095275").update(precio="131.00")
        Material.objects.filter(matricula="6913290").update(precio="250.00")
        self.configurar()
        self.assertEqual(ManoDeObra.objects.get(partida="*095275").precio,
                         Decimal("131.00"))
        self.assertEqual(Material.objects.get(matricula="6913290").precio,
                         Decimal("250.00"))

    def test_se_puede_repetir(self):
        self.configurar()
        tipo = self.configurar()
        self.assertEqual(tipo.partidas.count(), 16)
        self.assertEqual(tipo.materiales.count(), 10)

    # ── Las medidas viajan con la liquidación ────────────────────────────────

    def test_la_liquidacion_guarda_y_devuelve_los_panos(self):
        tipo = self.configurar()
        refuerzo = Material.objects.get(matricula="6913292")
        StockCamion.objects.create(camion=self.camion, material=refuerzo,
                                   cantidad=2)
        medidas = {"panos": {"vereda_10": [[1.5, 1.0], [0.8, 0.5]]},
                   "viajes": {"acarreo": [30, 2]}}
        self.auth(self.capataz)
        resp = self.client.post("/api/liquidaciones/", {
            "usuario": self.capataz.pk,
            "tipo_trabajo": tipo.pk,
            "suministro_externo": "1234567",
            "sst_externo": "SST-0001",
            "partidas": [{"mano_de_obra": ManoDeObra.objects.get(
                partida="*095266").pk, "cantidad": "1.90"}],
            "materiales": [{"material": refuerzo.pk, "cantidad": "1"}],
            "medidas": medidas,
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["medidas"], medidas)
        self.assertEqual(LiquidacionSuministro.objects.get().medidas, medidas)
        # El refuerzo sale del camión, como cualquier material.
        self.assertEqual(self.stock_camion(refuerzo), 1)

    def test_sin_medidas_queda_vacio(self):
        tipo = self.configurar()
        self.auth(self.capataz)
        resp = self.client.post("/api/liquidaciones/", {
            "usuario": self.capataz.pk,
            "tipo_trabajo": tipo.pk,
            "suministro_externo": "1234567",
            "sst_externo": "SST-0001",
            "partidas": [{"mano_de_obra": ManoDeObra.objects.get(
                partida="*094395").pk, "cantidad": "1"}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["medidas"], {})
