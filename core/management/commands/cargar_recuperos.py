"""Carga el catálogo de recuperos desde un TSV: matrícula, descripción y,
opcional, la unidad de medida (por defecto UND).

Uso:  python manage.py cargar_recuperos
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Recupero


class Command(BaseCommand):
    help = "Carga el catálogo de recuperos desde core/data/recuperos.txt."

    def add_arguments(self, parser):
        parser.add_argument("--archivo", default="core/data/recuperos.txt")

    @transaction.atomic
    def handle(self, *args, **opts):
        ruta = Path(settings.BASE_DIR) / opts["archivo"]
        if not ruta.exists():
            raise CommandError(f"No existe el archivo: {ruta}")

        creados = actualizados = 0
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.rstrip()
            if not linea:
                continue
            partes = linea.split("\t") if "\t" in linea else linea.split(None, 1)
            partes = [p.strip() for p in partes if p.strip() != ""]
            if len(partes) < 2:
                continue
            if partes[0].lower() == "matricula":
                continue
            matricula, descripcion = partes[0], partes[1]
            # Tercera columna opcional: la unidad del formato TS-REC-FR-001.
            unidad = partes[2] if len(partes) > 2 else "UND"
            _, nuevo = Recupero.objects.update_or_create(
                matricula=matricula,
                defaults={"descripcion": descripcion, "unidad": unidad})
            creados += 1 if nuevo else 0
            actualizados += 0 if nuevo else 1

        self.stdout.write(self.style.SUCCESS(
            f"Recuperos: {creados} nuevos, {actualizados} actualizados. "
            f"Total: {Recupero.objects.count()}."))
