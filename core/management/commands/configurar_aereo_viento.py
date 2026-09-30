"""Crea la actividad "Cambio de poste inaccesible aereo - Viento".

Sus tipos de trabajo se asignan desde la pantalla de Configuración del
Coordinador, y el comando no toca esos vínculos: un despliegue no puede
llevarse por delante lo que se armó ahí.

La excepción es "Retiros - otros - viento", que va siempre. Es el mismo
trabajo que "Retiros - otros - cabria": las mismas partidas, con el catálogo
que define `configurar_cabria`, así que si se corrige allá se corrige aquí en
el siguiente despliegue. Encima lleva las de `PARTIDAS_PROPIAS`, que en cabria
no se retiran. Las reglas que lo llenan están en la app.

El resto de sus tipos, en el orden de la obra (decidido el 2026-09-29):

- "Poste viento", primero y vacío: su composición se definirá después, así
  que el comando lo crea y lo cuelga pero no le toca el catálogo.
- Copias de cabria con nombre propio: "Alumbrado aereo viento", "Ferreteria
  viento" y "Conexiones viento". Nacen y se mantienen con el catálogo de su
  original en `configurar_cabria`; las reglas de la app son las mismas.
- Los mismos tipos de cabria, compartidos: las retenidas y las ménsulas. Su
  catálogo lo deja `configurar_cabria`; aquí solo se cuelgan.

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

POSTE = "Poste viento"

# Copia en viento -> el tipo de cabria del que sale.
COPIAS = {
    "Alumbrado aereo viento": "Alumbrado cabria",
    "Ferreteria viento": "Ferreteria",
    "Conexiones viento": "Conexiones cabria",
}

# Los mismos objetos que en cabria: un cambio vale para las dos actividades.
COMPARTIDOS = [
    "Retenida simple",
    "Retenida Violin",
    "Mensula simple",
    "Mensula doble",
    'Retenida Tipo "Y"',
]

RETIROS = "Retiros - otros - viento"
RETIROS_DE_CABRIA = "Retiros - otros - cabria"

# Los retiros van al final, como en cabria: se empieza por el poste y se
# termina por lo suelto. Los tipos que se agregan desde Configuración nacen con
# orden 0, así que este número los deja siempre antes.
ORDEN_DE_LOS_RETIROS = 100

# Lo que viento retira y cabria no, con su cantidad inicial. Van después de
# las de cabria.
PARTIDAS_PROPIAS = {
    "*090468": 0,  # retiro de poste PRFV hasta 8.7 m <- poste de fibra (REC-051)
}


def catalogo_de_los_retiros():
    de_cabria = CATALOGO[RETIROS_DE_CABRIA]
    return {
        "materiales": dict(de_cabria["materiales"]),
        "mano_de_obra": {**de_cabria["mano_de_obra"], **PARTIDAS_PROPIAS},
    }


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

        cabria = ConfigurarCabria(stdout=self.stdout, stderr=self.stderr)
        # El poste va primero, con el orden 0 que también traen los que se
        # agregan desde Configuración; los demás, detrás en el orden de la obra.
        self._colgar(actividad, POSTE, 0)
        orden = 1
        for copia, original in COPIAS.items():
            tipo = self._colgar(actividad, copia, orden)
            cabria._catalogo(tipo, CATALOGO[original])
            orden += 1
        for nombre in COMPARTIDOS:
            self._colgar(actividad, nombre, orden)
            orden += 1

        retiros = self._colgar(actividad, RETIROS, ORDEN_DE_LOS_RETIROS)
        cabria._catalogo(retiros, catalogo_de_los_retiros())

    def _colgar(self, actividad, nombre, orden):
        """El tipo, creado si falta, colgado de la actividad en su lugar."""
        tipo, creado = TipoTrabajo.objects.get_or_create(nombre=nombre)
        if creado:
            self.stdout.write(f"  Tipo de trabajo creado: «{nombre}».")
        _, vinculado = ActividadTipoTrabajo.objects.update_or_create(
            actividad=actividad, tipo_trabajo=tipo, defaults={'orden': orden})
        if vinculado:
            self.stdout.write(f"  + {nombre}")
        return tipo
