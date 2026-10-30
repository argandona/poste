"""Manda los avisos de las salidas del camión que toquen a esta hora (ver
core/avisos_camiones.py). Normalmente lo hace el reloj de GitHub; esto sirve
para correrlo a mano. Lo ya avisado no se repite."""
from django.core.management.base import BaseCommand

from core.avisos_camiones import revisar


class Command(BaseCommand):
    help = 'Manda los avisos de salida y cierre de los camiones que toquen.'

    def handle(self, *args, **options):
        r = revisar()
        self.stdout.write(f"Avisos de cierre: {r['cierre']} · "
                          f"sin salida: {r['sin_salida']}.")
