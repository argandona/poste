"""Crea la actividad de reforma y le cuelga los tipos de trabajo de cabria aérea.

Una reforma es el mismo trabajo que "Cambio de poste inacc. cabria aereo" — los
mismos tipos, los mismos materiales, las mismas reglas y los mismos descuentos —
con una diferencia: su SST lleva **varios postes**, y el capataz los va
agregando en obra.

Por eso no se copia nada: se cuelgan de esta actividad los MISMOS registros de
tipo de trabajo que usa la aérea. Si mañana se corrige el catálogo de uno, la
reforma lo hereda sola.

Es idempotente. Lo corre el script de despliegue en cada build, después de
`configurar_cabria`, que es quien crea esos tipos.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Actividad, ActividadTipoTrabajo, TipoTrabajo

from .configurar_cabria import ACTIVIDAD as ACTIVIDAD_AEREA

NOMBRE = "Reforma - cambio de poste inacc. aereo - cabria"


class Command(BaseCommand):
    help = ('Crea la actividad de reforma con los tipos de trabajo de cabria '
            'aérea.')

    @transaction.atomic
    def handle(self, *args, **options):
        actividad, nueva = Actividad.objects.get_or_create(
            nombre=NOMBRE, defaults={'varios_postes': True})
        if nueva:
            self.stdout.write(f"Actividad creada: «{NOMBRE}».")
        # Es lo que la distingue de la aérea: su SST lleva varios postes.
        if not actividad.varios_postes:
            actividad.varios_postes = True
            actividad.save(update_fields=['varios_postes'])
            self.stdout.write("  admite varios postes por SST")

        # El orden es el de la obra y lo define la aérea: se copia tal cual
        # para que el capataz vea los tipos en la misma secuencia.
        de_la_aerea = (ActividadTipoTrabajo.objects
                       .filter(actividad__nombre=ACTIVIDAD_AEREA)
                       .select_related('tipo_trabajo')
                       .order_by('orden', 'tipo_trabajo__nombre'))
        if not de_la_aerea:
            self.stdout.write(self.style.WARNING(
                f"«{ACTIVIDAD_AEREA}» no tiene tipos de trabajo: se omite. "
                "¿Corrió configurar_cabria antes que este comando?"))
            return

        for orden, vinculo in enumerate(de_la_aerea):
            _, creado = ActividadTipoTrabajo.objects.update_or_create(
                actividad=actividad, tipo_trabajo=vinculo.tipo_trabajo,
                defaults={'orden': orden})
            if creado:
                self.stdout.write(f"  + {vinculo.tipo_trabajo.nombre}")

        # Lo que sobre: un tipo que la aérea ya no tiene tampoco va aquí.
        suyos = {v.tipo_trabajo_id for v in de_la_aerea}
        sobran = (ActividadTipoTrabajo.objects
                  .filter(actividad=actividad)
                  .exclude(tipo_trabajo_id__in=suyos)
                  .select_related('tipo_trabajo'))
        for vinculo in sobran:
            self.stdout.write(f"  - {vinculo.tipo_trabajo.nombre}")
            vinculo.delete()

        nombres = list(ActividadTipoTrabajo.objects
                       .filter(actividad=actividad)
                       .order_by('orden')
                       .values_list('tipo_trabajo__nombre', flat=True))
        self.stdout.write(self.style.SUCCESS(
            f"{NOMBRE}: {', '.join(nombres)}"))


def tipos_de_trabajo():
    """Los nombres de los tipos que hoy tiene la reforma. Para los tests."""
    return list(TipoTrabajo.objects
                .filter(actividades__actividad__nombre=NOMBRE)
                .order_by('actividades__orden')
                .values_list('nombre', flat=True))
