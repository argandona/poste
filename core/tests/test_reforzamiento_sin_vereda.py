"""
El reforzamiento de poste sin vereda / piso especial: su catálogo.

Lleva el mismo material que el de vereda. Las partidas que no estaban en el
catálogo nacen provisionales, y las que ya existían no se tocan.
"""
import io
from decimal import Decimal

from django.core.management import call_command

from ..models import ActividadTipoTrabajo, ManoDeObra, TipoTrabajo
from .base import BaseAPITestCase

TIPO = "Reforzamiento sin vereda"

# Las que ya existían en el catálogo, con el precio que no debe cambiar.
EXISTENTES = {
    "*094395": "53.30",
    "*090248": "36.82",
    "*098203": "4.04",
    "*090633": "0.67",
}


class ReforzamientoSinVeredaTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        for codigo, precio in EXISTENTES.items():
            ManoDeObra.objects.create(
                partida=codigo, descripcion=codigo, precio=precio)

    def configurar(self):
        call_command("configurar_reforzamiento", stdout=io.StringIO())
        return TipoTrabajo.objects.get(nombre=TIPO)

    def test_el_tipo_cuelga_de_la_actividad_sin_vereda(self):
        tipo = self.configurar()
        self.assertEqual(
            list(ActividadTipoTrabajo.objects.filter(tipo_trabajo=tipo)
                 .values_list("actividad__nombre", flat=True)),
            ["Reforzamiento de poste sin vereda / piso especial"])

    def test_lleva_las_doce_partidas_en_el_orden_dado(self):
        tipo = self.configurar()
        codigos = [p.mano_de_obra.partida for p in tipo.partidas.all()]
        self.assertEqual(codigos, [
            "*094395", "*090248", "*090252", "*094919", "*091800", "*091810",
            "*098203", "*098822", "*090633", "*099090", "*091673", "*020000"])

    def test_la_inspeccion_y_el_reforzamiento_arrancan_en_uno(self):
        tipo = self.configurar()
        iniciales = {p.mano_de_obra.partida: p.cantidad_inicial
                     for p in tipo.partidas.all()}
        self.assertEqual(iniciales["*094395"], 1)
        self.assertEqual(iniciales["*090252"], 1)
        self.assertEqual(iniciales["*091800"], 0)

    def test_las_nuevas_nacen_con_el_precio_dado(self):
        self.configurar()
        precio = lambda c: ManoDeObra.objects.get(partida=c).precio
        self.assertEqual(precio("*090252"), Decimal("405.35"))
        self.assertEqual(precio("*091810"), Decimal("80.51"))
        # Sin precio dado: provisional, para cargarlo desde Configuración.
        self.assertEqual(precio("*091800"), Decimal("1.00"))
        self.assertEqual(precio("*020000"), Decimal("1.00"))
        # Las que ya existían conservan su precio.
        for codigo, precio in EXISTENTES.items():
            self.assertEqual(ManoDeObra.objects.get(partida=codigo).precio,
                             Decimal(precio), codigo)
        self.assertEqual(ManoDeObra.objects.get(partida="*094919").precio,
                         Decimal("56.35"))

    def test_lleva_el_mismo_material_que_el_de_vereda(self):
        tipo = self.configurar()
        con_vereda = TipoTrabajo.objects.get(nombre="Reforzamiento con vereda")
        matriculas = lambda t: {m.material.matricula for m in t.materiales.all()}
        self.assertEqual(matriculas(tipo), matriculas(con_vereda))
        self.assertEqual(tipo.materiales.count(), 10)

    def test_no_pisa_el_precio_corregido(self):
        self.configurar()
        ManoDeObra.objects.filter(partida="*090252").update(precio="410.00")
        tipo = self.configurar()
        self.assertEqual(ManoDeObra.objects.get(partida="*090252").precio,
                         Decimal("410.00"))
        self.assertEqual(tipo.partidas.count(), 12)
