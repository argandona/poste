"""
La actividad aérea de viento: nace vacía y con varios postes por SST.

Sus tipos de trabajo se arman desde Configuración, así que lo que importa es
que un despliegue no se los lleve.
"""
from django.core.management import call_command

from ..models import Actividad, ActividadTipoTrabajo, TipoTrabajo
from .base import BaseAPITestCase

NOMBRE = "Cambio de poste inaccesible aereo - Viento"


class AereoVientoTests(BaseAPITestCase):

    def configurar(self):
        call_command("configurar_aereo_viento", verbosity=0)

    def test_se_crea_vacia_y_con_varios_postes(self):
        self.configurar()
        actividad = Actividad.objects.get(nombre=NOMBRE)
        self.assertTrue(actividad.varios_postes)
        self.assertFalse(actividad.tipos_trabajo.exists())

    def test_correrlo_dos_veces_no_la_duplica(self):
        self.configurar()
        self.configurar()
        self.assertEqual(Actividad.objects.filter(nombre=NOMBRE).count(), 1)

    def test_lo_armado_en_configuracion_sobrevive_al_despliegue(self):
        self.configurar()
        actividad = Actividad.objects.get(nombre=NOMBRE)
        tipo = TipoTrabajo.objects.create(nombre="Poste aereo viento")
        ActividadTipoTrabajo.objects.create(actividad=actividad, tipo_trabajo=tipo)
        self.configurar()
        self.assertEqual(
            list(actividad.tipos_trabajo.values_list("tipo_trabajo__nombre", flat=True)),
            ["Poste aereo viento"])

    def test_si_alguien_le_quito_los_varios_postes_se_los_devuelve(self):
        Actividad.objects.create(nombre=NOMBRE, varios_postes=False)
        self.configurar()
        self.assertTrue(Actividad.objects.get(nombre=NOMBRE).varios_postes)
