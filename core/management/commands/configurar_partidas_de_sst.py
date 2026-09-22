"""Marca qué partidas se cobran una vez por SST y no por cada poste.

El plano es uno solo de la SST. Las partidas que salen de él —la vereda, el
arrastre, el acarreo que se calcula desde el arrastre, los metros de cable y el
traslado de comunicaciones— no se pueden cargar en cada poste, porque las
cobraría dos veces.

En las actividades donde una SST es un poste esto no cambia nada. Importa en la
reforma, donde la SST lleva varios y el capataz los va agregando.

La lista la dio el usuario el 2026-09-22. Es idempotente y lo corre el script
de despliegue en cada build.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import ManoDeObra

PARTIDAS_DE_SST = [
    '*095266',   # reparación de vereda      = área de los paños del plano
    '*091840',   # rotura de vereda          = va con la reparación
    '*090630',   # arrastre en plano         = tramos del plano
    '*090632',   # arrastre en pendiente     = tramos del plano
    '*090634',   # traslado manual           = lo que el arrastre pasa de 100
    '*090633',   # acarreo                   = se calcula desde el arrastre
    '*090163',   # traslado de Caais 3x70    = metros del plano
    '*010101',   # horas de operario         = metros de cable trasladado
    '*010213',   # traslado de comunicaciones = líneas verdes del plano
]


class Command(BaseCommand):
    help = 'Marca las partidas que se cobran una vez por SST.'

    @transaction.atomic
    def handle(self, *args, **options):
        marcadas = ManoDeObra.objects.filter(partida__in=PARTIDAS_DE_SST)
        encontradas = set(marcadas.values_list('partida', flat=True))
        cambiadas = marcadas.exclude(ambito=ManoDeObra.AMBITO_SST).update(
            ambito=ManoDeObra.AMBITO_SST)

        # Lo que salga de la lista vuelve a ser de poste: así se puede sacar
        # una partida de aquí sin tener que tocar la base a mano.
        devueltas = (ManoDeObra.objects
                     .filter(ambito=ManoDeObra.AMBITO_SST)
                     .exclude(partida__in=PARTIDAS_DE_SST)
                     .update(ambito=ManoDeObra.AMBITO_POSTE))

        faltan = [p for p in PARTIDAS_DE_SST if p not in encontradas]
        if faltan:
            self.stdout.write(self.style.WARNING(
                f"No están en el catálogo y se omiten: {', '.join(faltan)}"))
        self.stdout.write(self.style.SUCCESS(
            f"Partidas por SST: {len(encontradas)} "
            f"({cambiadas} marcadas ahora, {devueltas} devueltas a poste)."))
