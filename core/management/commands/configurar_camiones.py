"""El rol Chofer: maneja el camión y registra su kilometraje y combustible
(core/camiones.py). Es idempotente; lo corre el script de despliegue."""
from django.core.management.base import BaseCommand

from core.models import Rol


class Command(BaseCommand):
    help = "Crea el rol Chofer."

    def handle(self, *args, **options):
        _, nuevo = Rol.objects.get_or_create(
            id_rol=Rol.CHOFER, defaults={"descripcion": "Chofer"})
        if nuevo:
            self.stdout.write("  Rol creado: Chofer")
