"""Crea la actividad de cabria aérea con sus tipos de trabajo.

A diferencia de `configurar_tipos_viento`, este comando NO toca los materiales
ni las partidas de cada tipo: solo se asegura de que la actividad y sus tipos
existan y estén ligados. La composición de cada tipo se arma desde la pantalla
de Configuración, y si el comando la reescribiera en cada despliegue borraría
lo que el Coordinador acabara de cargar.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Actividad, ActividadTipoTrabajo, TipoTrabajo

ACTIVIDAD = "Cambio de poste inacc. cabria aereo"

TIPOS = [
    "Alumbrado cabria",
    "Poste cabria",
    "Mensula doble",
    "Mensula simple",
    "Retenida simple",
    "Retenida Violin",
    "Ferreteria",
]


class Command(BaseCommand):
    help = f'Crea la actividad "{ACTIVIDAD}" y sus tipos de trabajo.'

    @transaction.atomic
    def handle(self, *args, **options):
        actividad, nueva = Actividad.objects.get_or_create(nombre=ACTIVIDAD)
        if nueva:
            self.stdout.write(f"Actividad creada: {ACTIVIDAD}")

        creados = ligados = 0
        for nombre in TIPOS:
            tipo, es_nuevo = TipoTrabajo.objects.get_or_create(nombre=nombre)
            creados += 1 if es_nuevo else 0
            _, se_ligo = ActividadTipoTrabajo.objects.get_or_create(
                actividad=actividad, tipo_trabajo=tipo)
            ligados += 1 if se_ligo else 0

        self.stdout.write(self.style.SUCCESS(
            f"{ACTIVIDAD}: {actividad.tipos_trabajo.count()} tipos de trabajo "
            f"({creados} nuevos, {ligados} ligados en esta corrida)."))
