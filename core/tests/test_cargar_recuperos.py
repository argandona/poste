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
