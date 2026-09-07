"""Carga materiales y fija el saldo (StockCamion) de un camión desde un archivo.

Archivo (TSV): Matricula<TAB>Descripcion<TAB>Precio<TAB>Cantidad
Primera línea = encabezado (se ignora).

Uso:
    python manage.py cargar_saldo_camion
    python manage.py cargar_saldo_camion --placa ABC-123
    python manage.py cargar_saldo_camion --archivo core/data/materiales_camion.txt
"""
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Camion, Material, StockCamion


class Command(BaseCommand):
    help = "Carga materiales y fija el saldo de un camión desde un archivo TSV."

    def add_arguments(self, parser):
        parser.add_argument("--placa", default="ABC-123",
                            help="Placa del camión (por defecto ABC-123).")
        parser.add_argument("--archivo", default="core/data/materiales_camion.txt",
                            help="Ruta al archivo TSV (relativa a la carpeta del proyecto).")

    @transaction.atomic
    def handle(self, *args, **opts):
        placa = opts["placa"]
        ruta = Path(settings.BASE_DIR) / opts["archivo"]
        if not ruta.exists():
            raise CommandError(f"No existe el archivo: {ruta}")

        try:
            camion = Camion.objects.get(placa=placa)
        except Camion.DoesNotExist:
            raise CommandError(f"No existe el camión con placa {placa}.")

        creados = actualizados = filas = 0
        for i, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines()):
            linea = linea.rstrip()
            if not linea:
                continue
            # Separa por TAB si lo hay; si no, por espacios múltiples.
            partes = linea.split("\t") if "\t" in linea else linea.split()
            partes = [p.strip() for p in partes if p.strip() != ""]
            if len(partes) < 4:
                continue
            if partes[0].lower() == "matricula":
                continue  # encabezado

            matricula = partes[0]
            cantidad = Decimal(partes[-1].replace(",", "."))
            precio = Decimal(partes[-2].replace(",", "."))
            descripcion = " ".join(partes[1:-2]).strip()
            filas += 1

            material, nuevo = Material.objects.update_or_create(
                matricula=matricula,
                defaults={"descripcion": descripcion, "precio": precio},
            )
            creados += 1 if nuevo else 0
            actualizados += 0 if nuevo else 1

            StockCamion.objects.update_or_create(
                camion=camion, material=material,
                defaults={"cantidad": cantidad},
            )

        total_stock = StockCamion.objects.filter(camion=camion).count()
        self.stdout.write(self.style.SUCCESS(
            f"Camión {placa}: {filas} filas procesadas "
            f"({creados} materiales nuevos, {actualizados} actualizados). "
            f"El camión tiene ahora {total_stock} materiales con saldo."
        ))
