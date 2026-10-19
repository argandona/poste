"""Los comandos que siembran o pisan datos no corren en producción por
descuido: se niegan salvo que se pida con --forzar-produccion."""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from ..models import ManoDeObra, StockCamion, Usuario
from .base import BaseAPITestCase

PELIGROSOS = ('seed_demo', 'seed_prueba', 'cargar_mano_de_obra', 'cargar_saldo_camion')


def correr(nombre, **opciones):
    call_command(nombre, stdout=StringIO(), stderr=StringIO(), **opciones)


class CandadoSeedsTests(BaseAPITestCase):

    @override_settings(DEBUG=False)
    def test_en_produccion_se_niegan_y_no_tocan_nada(self):
        mo = ManoDeObra.objects.create(partida='*091810', descripcion='Grass',
                                       precio=Decimal('80.51'))
        StockCamion.objects.create(camion=self.camion, material=self.material_a,
                                   cantidad=7)
        usuarios = Usuario.objects.count()
        for nombre in PELIGROSOS:
            with self.subTest(nombre), self.assertRaises(CommandError) as e:
                correr(nombre)
            self.assertIn('Esto es producción', str(e.exception))
            self.assertIn('--forzar-produccion', str(e.exception))
        mo.refresh_from_db()
        self.assertEqual(mo.precio, Decimal('80.51'))
        self.assertEqual(StockCamion.objects.get(camion=self.camion).cantidad, 7)
        self.assertEqual(Usuario.objects.count(), usuarios)
        self.assertFalse(Usuario.objects.filter(email='admin@tecsur.pe').exists())

    @override_settings(DEBUG=False)
    def test_en_produccion_corre_solo_si_se_fuerza(self):
        correr('seed_demo', forzar_produccion=True)
        self.assertTrue(Usuario.objects.filter(email='admin@tecsur.pe').exists())

    @override_settings(DEBUG=True)
    def test_en_local_corre_como_siempre(self):
        correr('seed_demo')
        self.assertTrue(Usuario.objects.filter(email='capataz@tecsur.pe').exists())
