"""Crea las dos actividades de reforzamiento de poste, que son de encargado.

Un encargado solo ve las actividades de encargado, y estas son las suyas; el
capataz no las ve. Sus tipos de trabajo todavía no están definidos: se cuelgan
desde la pantalla de Configuración, y el comando no toca esos vínculos.

Es idempotente. Lo corre el script de despliegue en cada build.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Actividad

ACTIVIDADES = [
    "Reforzamiento de poste con vereda",
    "Reforzamiento de poste sin vereda / piso especial",
]


class Command(BaseCommand):
    help = "Crea las actividades de reforzamiento de poste, de encargado."

    @transaction.atomic
    def handle(self, *args, **options):
        for nombre in ACTIVIDADES:
            actividad, nueva = Actividad.objects.get_or_create(
                nombre=nombre, defaults={"de_encargado": True})
            if nueva:
                self.stdout.write(self.style.SUCCESS(
                    f"Actividad creada: «{nombre}»."))
            elif not actividad.de_encargado:
                actividad.de_encargado = True
                actividad.save(update_fields=["de_encargado"])
                self.stdout.write(f"  «{nombre}» pasa a ser de encargado")
