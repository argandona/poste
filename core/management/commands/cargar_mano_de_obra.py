"""Carga partidas de mano de obra en la tabla ManoDeObra desde un archivo.

Archivo (TSV o separado por espacios): Partida  Descripcion  Precio
Primera línea = encabezado (se ignora).

Uso:
    python manage.py cargar_mano_de_obra
    python manage.py cargar_mano_de_obra --archivo core/data/mano_de_obra.txt
"""
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import ManoDeObra


class Command(BaseCommand):
    help = "Carga partidas de mano de obra desde un archivo TSV."

    def add_arguments(self, parser):
        parser.add_argument("--archivo", default="core/data/mano_de_obra.txt",
                            help="Ruta al archivo (relativa a la carpeta del proyecto).")

    @transaction.atomic
    def handle(self, *args, **opts):
        ruta = Path(settings.BASE_DIR) / opts["archivo"]
        if not ruta.exists():
            raise CommandError(f"No existe el archivo: {ruta}")

        creados = actualizados = filas = 0
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.rstrip()
            if not linea:
                continue
            partes = linea.split("\t") if "\t" in linea else linea.split()
            partes = [p.strip() for p in partes if p.strip() != ""]
            if len(partes) < 3:
                continue
            if partes[0].lower() == "matricula":
                continue  # encabezado

            partida = partes[0]
            precio = Decimal(partes[-1].replace(",", "."))
            descripcion = " ".join(partes[1:-1]).strip()[:200]
            filas += 1

            _, nuevo = ManoDeObra.objects.update_or_create(
                partida=partida,
                defaults={"descripcion": descripcion, "precio": precio},
            )
            creados += 1 if nuevo else 0
            actualizados += 0 if nuevo else 1

        total = ManoDeObra.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"{filas} filas procesadas ({creados} nuevas, {actualizados} actualizadas). "
            f"Total de partidas en la tabla: {total}."
        ))
