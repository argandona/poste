"""
La actividad aérea de viento: varios postes por SST y sus retiros siempre.

Sus demás tipos de trabajo se arman desde Configuración, así que lo que
importa es que un despliegue no se los lleve. "Retiros - otros - viento", en
cambio, va siempre y con el mismo catálogo que los retiros de cabria.
"""
from decimal import Decimal

from django.core.management import call_command

from ..management.commands.configurar_cabria import CATALOGO
from ..models import (
    Actividad, ActividadTipoTrabajo, ManoDeObra, TipoTrabajo,
    TipoTrabajoManoDeObra,
)
from .base import BaseAPITestCase

NOMBRE = "Cambio de poste inaccesible aereo - Viento"
RETIROS = "Retiros - otros - viento"
PARTIDAS_DE_CABRIA = list(CATALOGO["Retiros - otros - cabria"]["mano_de_obra"])


class AereoVientoTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        for partida in PARTIDAS_DE_CABRIA:
            ManoDeObra.objects.get_or_create(
                partida=partida,
                defaults={"descripcion": partida, "precio": Decimal("1.00")})

    def configurar(self):
        call_command("configurar_aereo_viento", verbosity=0)

    def actividad(self):
        return Actividad.objects.get(nombre=NOMBRE)

    def tipos(self):
        return list(self.actividad().tipos_trabajo
                    .values_list("tipo_trabajo__nombre", flat=True))

    def test_se_crea_con_varios_postes_y_solo_sus_retiros(self):
        self.configurar()
        self.assertTrue(self.actividad().varios_postes)
        self.assertEqual(self.tipos(), [RETIROS])

    def test_los_retiros_llevan_las_mismas_partidas_que_los_de_cabria(self):
        self.configurar()
        retiros = TipoTrabajo.objects.get(nombre=RETIROS)
        partidas = list(TipoTrabajoManoDeObra.objects
                        .filter(tipo_trabajo=retiros)
                        .order_by("orden")
                        .values_list("mano_de_obra__partida", flat=True))
        self.assertEqual(partidas, PARTIDAS_DE_CABRIA)

    def test_correrlo_dos_veces_no_duplica_nada(self):
        self.configurar()
        self.configurar()
        self.assertEqual(Actividad.objects.filter(nombre=NOMBRE).count(), 1)
        self.assertEqual(TipoTrabajo.objects.filter(nombre=RETIROS).count(), 1)
        self.assertEqual(self.tipos(), [RETIROS])

    def test_lo_armado_en_configuracion_sobrevive_y_los_retiros_van_al_final(self):
        self.configurar()
        tipo = TipoTrabajo.objects.create(nombre="Poste aereo viento")
        ActividadTipoTrabajo.objects.create(
            actividad=self.actividad(), tipo_trabajo=tipo)
        self.configurar()
        self.assertEqual(self.tipos(), ["Poste aereo viento", RETIROS])

    def test_si_alguien_le_quito_los_retiros_vuelven(self):
        self.configurar()
        ActividadTipoTrabajo.objects.filter(
            actividad=self.actividad(), tipo_trabajo__nombre=RETIROS).delete()
        self.configurar()
        self.assertEqual(self.tipos(), [RETIROS])

    def test_si_alguien_le_quito_los_varios_postes_se_los_devuelve(self):
        Actividad.objects.create(nombre=NOMBRE, varios_postes=False)
        self.configurar()
        self.assertTrue(self.actividad().varios_postes)
