"""
El catálogo de recuperos que carga cada despliegue.

Los cables Caais van por metro: la app los suma para llenar los retiros de
cable (*090137, *090138, *090139) según el calibre.
"""
from django.core.management import call_command

from ..models import Recupero
from .base import BaseAPITestCase


class CargarRecuperosTests(BaseAPITestCase):

    def test_los_caais_nuevos_entran_por_metro(self):
        call_command("cargar_recuperos", verbosity=0)
        caais = dict(Recupero.objects
                     .filter(matricula__in=["REC-047", "REC-048", "REC-049", "REC-050"])
                     .values_list("matricula", "descripcion"))
        self.assertEqual(caais, {
            "REC-047": "CABLE CAAIS 2X16",
            "REC-048": "CABLE CAAIS 3X35",
            "REC-049": "CABLE CAAIS 3X120",
            "REC-050": "CABLE CAAIS 3X120+1X16",
        })
        self.assertEqual(
            set(Recupero.objects.filter(matricula__in=caais)
                .values_list("unidad", flat=True)),
            {"M"})

    def test_los_postes_de_fibra_van_por_medida_y_por_unidad(self):
        # REC-051 era "POSTE DE FIBRA" a secas; desde el 2026-09-29 es el de
        # 7 m, y se suman el de 8 y el de 9.
        Recupero.objects.create(matricula="REC-051", descripcion="POSTE DE FIBRA")
        call_command("cargar_recuperos", verbosity=0)
        for matricula, descripcion in (("REC-051", "POSTE DE FIBRA DE 7"),
                                       ("REC-052", "POSTE DE FIBRA DE 8"),
                                       ("REC-053", "POSTE DE FIBRA DE 9")):
            poste = Recupero.objects.get(matricula=matricula)
            self.assertEqual(poste.descripcion, descripcion)
            self.assertEqual(poste.unidad, "UND")
