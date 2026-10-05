"""Los roles de la cuadrilla (operario y ayudante) y el catálogo inicial de EPP.

Pedido del usuario el 2026-10-05. Cada talla es un EPP aparte, con su código.
Los precios no se dieron: nacen en 0 para cargarlos desde la app. La lista
traía "casco azul" dos veces; va una sola.

Es idempotente y no pisa lo que se corrija después desde la app. Lo corre el
script de despliegue en cada build.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import EPP, Rol

ROLES = {
    Rol.OPERARIO: "Operario",
    Rol.AYUDANTE: "Ayudante",
}

# (prefijo del código, descripción, unidad, tallas). Sin tallas, uno solo.
CATALOGO = [
    ("GUANTE-LIV", "GUANTES LIVIANOS", "PAR", ["6", "7", "8", "9"]),
    ("GUANTE-PES", "GUANTES PESADOS", "PAR", ["8", "9"]),
    ("BOTA-DIEL", "BOTAS DIELECTRICAS", "PAR",
     ["38", "39", "40", "41", "42", "43", "44", "45"]),
    ("JEAN", "PANTALON JEAN", "UND",
     ["38", "39", "40", "41", "42", "43", "44", "45"]),
    ("POLO", "POLO DE CONTRATISTA", "UND", ["S", "M", "L", "XL"]),
    ("LENTE-CLARO", "LENTES CLAROS", "UND", []),
    ("LENTE-OSCURO", "LENTES OSCUROS", "UND", []),
    ("OREJERA-TAPON", "OREJERAS TIPO TAPON", "PAR", []),
    ("TAPANUCA-DIEL", "TAPA NUCA DIELECTRICA", "UND", []),
    ("CASCO-AZUL", "CASCO AZUL", "UND", []),
]


class Command(BaseCommand):
    help = "Crea los roles Operario y Ayudante y el catálogo inicial de EPP."

    @transaction.atomic
    def handle(self, *args, **options):
        for id_rol, descripcion in ROLES.items():
            _, nuevo = Rol.objects.get_or_create(
                id_rol=id_rol, defaults={"descripcion": descripcion})
            if nuevo:
                self.stdout.write(f"  Rol creado: {descripcion}")

        creados = 0
        for prefijo, descripcion, unidad, tallas in CATALOGO:
            for talla in tallas or [""]:
                codigo = f"{prefijo}-{talla}" if talla else prefijo
                _, nuevo = EPP.objects.get_or_create(
                    codigo=codigo,
                    defaults={"descripcion": descripcion, "unidad": unidad,
                              "talla": talla})
                creados += nuevo
        self.stdout.write(f"  EPP: {creados} creados, "
                          f"{EPP.objects.count()} en el catálogo.")
