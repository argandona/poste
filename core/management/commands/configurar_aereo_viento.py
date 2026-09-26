"""Crea la actividad "Cambio de poste inaccesible aereo - Viento".

Sus tipos de trabajo se asignan desde la pantalla de Configuración del
Coordinador, y el comando no toca esos vínculos: un despliegue no puede
llevarse por delante lo que se armó ahí.

La excepción es "Retiros - otros - viento", que va siempre. Es el mismo
trabajo que "Retiros - otros - cabria": las mismas partidas, con el catálogo
que define `configurar_cabria`, así que si se corrige allá se corrige aquí en
el siguiente despliegue. Las reglas que lo llenan están en la app.

Lo otro que fija es que su SST lleve **varios postes**, que el capataz va
agregando en obra.

Es idempotente. Lo corre el script de despliegue en cada build, después de
`configurar_cabria`, que es quien crea las partidas del catálogo.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Actividad, ActividadTipoTrabajo, TipoTrabajo

from .configurar_cabria import CATALOGO
from .configurar_cabria import Command as ConfigurarCabria

NOMBRE = "Cambio de poste inaccesible aereo - Viento"

RETIROS = "Retiros - otros - viento"
RETIROS_DE_CABRIA = "Retiros - otros - cabria"

# Los retiros van al final, como en cabria: se empieza por el poste y se
# termina por lo suelto. Los tipos que se agregan desde Configuración nacen con
# orden 0, así que este número los deja siempre antes.
ORDEN_DE_LOS_RETIROS = 100


class Command(BaseCommand):
    help = (f'Crea la actividad «{NOMBRE}», con varios postes por SST y '
            f'«{RETIROS}».')

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

        retiros, creado = TipoTrabajo.objects.get_or_create(nombre=RETIROS)
        if creado:
            self.stdout.write(f"  Tipo de trabajo creado: «{RETIROS}».")
        ConfigurarCabria(stdout=self.stdout, stderr=self.stderr)._catalogo(
            retiros, CATALOGO[RETIROS_DE_CABRIA])
        _, vinculado = ActividadTipoTrabajo.objects.update_or_create(
            actividad=actividad, tipo_trabajo=retiros,
            defaults={'orden': ORDEN_DE_LOS_RETIROS})
        if vinculado:
            self.stdout.write(f"  + {RETIROS}")
