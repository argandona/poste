"""
La actividad de reforma: el mismo trabajo que cabria aérea, con varios postes.

Lo que importa aquí es que no sea una copia. Sus tipos de trabajo son los
MISMOS registros que usa la aérea, así que comparten catálogo, reglas y
descuentos, y corregir uno corrige los dos.
"""
from django.core.management import call_command

from ..inclusiones import INCLUSIONES_CONSOLIDADO, norm_actividad
from ..models import Actividad, ActividadTipoTrabajo, TipoTrabajo
from .base import BaseAPITestCase

AEREA = "Cambio de poste inacc. cabria aereo"
REFORMA = "Reforma - cambio de poste inacc. aereo - cabria"

# En el orden de la obra, igual que en la aérea.
TIPOS = [
    "Poste cabria", "Alumbrado cabria", "Ferreteria", "Conexiones cabria",
    "Retenida simple", "Retenida Violin", "Mensula simple", "Mensula doble",
    'Retenida Tipo "Y"', "Retiros - otros - cabria",
]


class ReformaCabriaTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.aerea = Actividad.objects.create(nombre=AEREA)
        self.tipos = []
        for orden, nombre in enumerate(TIPOS):
            tipo = TipoTrabajo.objects.create(nombre=nombre)
            ActividadTipoTrabajo.objects.create(
                actividad=self.aerea, tipo_trabajo=tipo, orden=orden)
            self.tipos.append(tipo)

    def configurar(self):
        call_command("configurar_reforma_cabria", verbosity=0)

    def tipos_de_la_reforma(self):
        return list(ActividadTipoTrabajo.objects
                    .filter(actividad__nombre=REFORMA)
                    .order_by("orden")
                    .values_list("tipo_trabajo__nombre", flat=True))

    # ── La actividad ────────────────────────────────────────────────────────

    def test_se_crea_la_actividad(self):
        self.configurar()
        self.assertTrue(Actividad.objects.filter(nombre=REFORMA).exists())

    def test_es_idempotente(self):
        self.configurar()
        self.configurar()
        self.assertEqual(Actividad.objects.filter(nombre=REFORMA).count(), 1)
        self.assertEqual(self.tipos_de_la_reforma(), TIPOS)

    def test_sin_la_aerea_configurada_no_hace_nada(self):
        ActividadTipoTrabajo.objects.filter(actividad=self.aerea).delete()
        self.configurar()
        self.assertEqual(self.tipos_de_la_reforma(), [])

    # ── Los tipos de trabajo ────────────────────────────────────────────────

    def test_tiene_los_mismos_tipos_y_en_el_mismo_orden(self):
        self.configurar()
        self.assertEqual(self.tipos_de_la_reforma(), TIPOS)

    def test_son_los_mismos_registros_no_copias(self):
        """Si fueran copias, corregir el catálogo de uno dejaría el otro viejo."""
        self.configurar()
        ids = list(ActividadTipoTrabajo.objects
                   .filter(actividad__nombre=REFORMA)
                   .order_by("orden")
                   .values_list("tipo_trabajo_id", flat=True))
        self.assertEqual(ids, [t.pk for t in self.tipos])

    def test_la_aerea_se_queda_como_estaba(self):
        self.configurar()
        self.assertEqual(
            list(ActividadTipoTrabajo.objects
                 .filter(actividad=self.aerea).order_by("orden")
                 .values_list("tipo_trabajo__nombre", flat=True)),
            TIPOS)

    def test_un_tipo_que_la_aerea_pierde_tambien_sale_de_la_reforma(self):
        self.configurar()
        ActividadTipoTrabajo.objects.filter(
            actividad=self.aerea, tipo_trabajo__nombre="Ferreteria").delete()
        self.configurar()
        self.assertNotIn("Ferreteria", self.tipos_de_la_reforma())

    def test_un_tipo_nuevo_en_la_aerea_llega_a_la_reforma(self):
        self.configurar()
        tipo = TipoTrabajo.objects.create(nombre="Pastoral doble")
        ActividadTipoTrabajo.objects.create(
            actividad=self.aerea, tipo_trabajo=tipo, orden=99)
        self.configurar()
        self.assertIn("Pastoral doble", self.tipos_de_la_reforma())

    # ── Los descuentos ──────────────────────────────────────────────────────

    def test_los_descuentos_son_los_de_la_aerea(self):
        self.assertIs(INCLUSIONES_CONSOLIDADO[norm_actividad(REFORMA)],
                      INCLUSIONES_CONSOLIDADO[norm_actividad(AEREA)])
