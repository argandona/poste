"""Crea la actividad "Cambio de poste inaccesible aereo - Viento".

Nace vacía: sus tipos de trabajo se asignan desde la pantalla de Configuración
del Coordinador. Por eso el comando no toca sus vínculos con tipos de trabajo,
y un despliegue no puede llevarse por delante lo que se armó ahí.

Lo único que fija es que su SST lleve **varios postes**, que el capataz va
agregando en obra.

Es idempotente. Lo corre el script de despliegue en cada build.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Actividad

NOMBRE = "Cambio de poste inaccesible aereo - Viento"


class Command(BaseCommand):
    help = f'Crea la actividad «{NOMBRE}», con varios postes por SST.'

    @transaction.atomic
    def handle(self, *args, **options):
        actividad, nueva = Actividad.objects.get_or_create(
            nombre=NOMBRE, defaults={'varios_postes': True})
        if nueva:
            self.stdout.write(self.style.SUCCESS(f"Actividad creada: «{NOMBRE}»."))
        if not actividad.varios_postes:
            actividad.varios_postes = True
            actividad.save(update_fields=['varios_postes'])
            self.stdout.write("  admite varios postes por SST")
