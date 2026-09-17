"""El rename de "Otros cabria" conserva el tipo: no nace uno nuevo vacío."""
from django.core.management import call_command

from ..models import TipoTrabajo
from .base import BaseAPITestCase


class RenombrarOtrosCabriaTests(BaseAPITestCase):

    def test_el_comando_no_vuelve_a_crear_el_nombre_viejo(self):
        call_command("configurar_cabria", verbosity=0)
        self.assertTrue(TipoTrabajo.objects.filter(nombre="Retiros - otros - cabria").exists())
        self.assertFalse(TipoTrabajo.objects.filter(nombre="Otros cabria").exists())

    def test_la_migracion_renombra_la_misma_fila(self):
        import importlib
        from django.apps import apps
        mig = importlib.import_module("core.migrations.0015_renombrar_otros_cabria")
        viejo = TipoTrabajo.objects.create(nombre="Otros cabria")
        mig.renombrar(apps, None)
        viejo.refresh_from_db()
        self.assertEqual(viejo.nombre, "Retiros - otros - cabria")
