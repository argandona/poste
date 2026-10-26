"""Crea la actividad "Calidad de producto", que es una obra de varios días.

La hacen los capataces: cada uno manda un parte por día y por punto, y la
liquidación es la suma de todos los partes (ver core/partes.py). Admite
varios puntos, que el capataz agrega en obra a medida que los ataca. La da
por terminada el coordinador.

Sus tipos de trabajo y partidas se agregan cuando el usuario las pase.

Es idempotente. Lo corre el script de despliegue en cada build.
"""
from django.core.management.base import BaseCommand

from core.models import Actividad

CALIDAD_DE_PRODUCTO = "Calidad de producto"


class Command(BaseCommand):
    help = "Crea la actividad Calidad de producto (obra de varios días)."

    def handle(self, *args, **options):
        actividad, creada = Actividad.objects.get_or_create(
            nombre=CALIDAD_DE_PRODUCTO,
            defaults={'varios_dias': True, 'varios_postes': True,
                      'de_encargado': False})
        # Lo que la hace obra de varios días se deja exacto: sin esto se
        # liquidaría como un cambio de poste, reemplazando el parte anterior.
        cambios = []
        for campo, valor in (('varios_dias', True), ('varios_postes', True),
                             ('de_encargado', False)):
            if getattr(actividad, campo) != valor:
                setattr(actividad, campo, valor)
                cambios.append(campo)
        if cambios:
            actividad.save(update_fields=cambios)
        self.stdout.write(
            f"{CALIDAD_DE_PRODUCTO}: {'creada' if creada else 'ya existía'}"
            f"{' (corregido: ' + ', '.join(cambios) + ')' if cambios else ''}.")
