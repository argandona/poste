"""Deja los tipos de trabajo de la actividad "-viento" con su catálogo definitivo.

La composición de un tipo de trabajo (qué materiales y qué partidas de mano de
obra lo forman) se edita normalmente desde la pantalla de Configuración del
Coordinador, así que vive solo en la base. Este comando la deja escrita en el
repo para poder repetirla en cualquier entorno: local, Render o una base nueva.
Lo corre el script de despliegue en cada build.

Es idempotente y deja el conjunto EXACTO de cada tipo: agrega lo que falta y
quita lo que sobre. Las reglas que autocompletan la mano de obra a partir del
material y del recupero están en la app, en `reglas_liquidacion.dart`.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    ManoDeObra, Material, TipoTrabajo, TipoTrabajoManoDeObra,
    TipoTrabajoMaterial,
)

from .configurar_cabria import CATALOGO
from .configurar_cabria import Command as ConfigurarCabria

ALUMBRADO = "Alumbrado viento"

TIPOS = {
    # Sin materiales: son horas y traslados, no cosas que se instalen.
    "Otros viento": {
        "materiales": [],
        "mano_de_obra": [
            "*010101",  # hora de operario, traslado de cables inaccesible
            "*010213",  # traslado de cables de comunicación
        ],
    },
}

# La hora de operario es genérica en el catálogo; en estos trabajos se usa para
# el traslado de cables, y el capataz necesita leerlo para no confundirla.
# *010213 venía como hora de cuadrilla con grúa, y es el traslado de cables de
# comunicación.
DESCRIPCIONES_MANO_DE_OBRA = {
    "*010101": "HORA DE OPERARIO (TRASLADO DE CABLES INACCESIBLE <=35MM)",
    "*010213": "TRASLADO DE CABLES DE COMUNICACION",
}

# Nombres de obra con los que el capataz reconoce el material. Reemplazan a la
# descripción larga del catálogo, que en dos pastorales era idéntica.
DESCRIPCIONES = {
    "1014308": "GRAPA HEBILLA 3/4",  # pedido del usuario el 2026-09-29
    "5021407": "CONDUCTOR SOLIDO TWT 450/750V.BIPOLAR 2X1.5 MM2 (INDOPRENE)",
    "5347015": "PASTORAL BASTON",
    "5347095": "PASTORAL JP",
    "5347174": "PASTORAL CHILENO CORTO",
    "5567146": "LUM.LED TP.IV,220V,60HZ,CL.II,SIN TELEG. 90W",
}


class Command(BaseCommand):
    help = 'Configura los tipos de trabajo de la actividad "-viento".'

    @transaction.atomic
    def handle(self, *args, **options):
        for matricula, descripcion in DESCRIPCIONES.items():
            actualizadas = (Material.objects
                            .filter(matricula=matricula)
                            .exclude(descripcion=descripcion)
                            .update(descripcion=descripcion))
            if actualizadas:
                self.stdout.write(f"  {matricula} → {descripcion}")

        for partida, descripcion in DESCRIPCIONES_MANO_DE_OBRA.items():
            actualizadas = (ManoDeObra.objects
                            .filter(partida=partida)
                            .exclude(descripcion=descripcion)
                            .update(descripcion=descripcion))
            if actualizadas:
                self.stdout.write(f"  {partida} → {descripcion}")

        for nombre, config in TIPOS.items():
            self._configurar(nombre, config)

        # Desde el 2026-09-29 "Alumbrado viento" se comporta igual que
        # "Alumbrado cabria": el mismo catálogo, con sus cantidades y su
        # orden, y en la app la misma regla. Sigue siendo su propio tipo.
        alumbrado = TipoTrabajo.objects.filter(nombre=ALUMBRADO).first()
        if alumbrado is None:
            self.stdout.write(self.style.WARNING(
                f'No existe el tipo de trabajo "{ALUMBRADO}", se omite.'))
        else:
            ConfigurarCabria(stdout=self.stdout, stderr=self.stderr)._catalogo(
                alumbrado, CATALOGO["Alumbrado cabria"])

    def _configurar(self, nombre, config):
        try:
            tipo = TipoTrabajo.objects.get(nombre=nombre)
        except TipoTrabajo.DoesNotExist:
            self.stdout.write(self.style.WARNING(
                f'No existe el tipo de trabajo "{nombre}", se omite.'))
            return

        materiales = list(
            Material.objects.filter(matricula__in=config["materiales"]))
        self._avisar_faltantes("materiales", config["materiales"],
                               [m.matricula for m in materiales])
        (TipoTrabajoMaterial.objects
         .filter(tipo_trabajo=tipo).exclude(material__in=materiales).delete())
        for material in materiales:
            TipoTrabajoMaterial.objects.get_or_create(
                tipo_trabajo=tipo, material=material)

        partidas = list(
            ManoDeObra.objects.filter(partida__in=config["mano_de_obra"]))
        self._avisar_faltantes("partidas", config["mano_de_obra"],
                               [p.partida for p in partidas])
        (TipoTrabajoManoDeObra.objects
         .filter(tipo_trabajo=tipo).exclude(mano_de_obra__in=partidas).delete())
        for partida in partidas:
            TipoTrabajoManoDeObra.objects.get_or_create(
                tipo_trabajo=tipo, mano_de_obra=partida)

        self.stdout.write(self.style.SUCCESS(
            f"{nombre}: {tipo.materiales.count()} materiales, "
            f"{tipo.partidas.count()} partidas."))

    def _avisar_faltantes(self, que, esperados, encontrados):
        faltan = [e for e in esperados if e not in encontrados]
        if faltan:
            self.stdout.write(self.style.WARNING(
                f"  No están en el catálogo, se omiten {que}: {', '.join(faltan)}"))
