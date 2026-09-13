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

TIPOS = {
    "Alumbrado viento": {
        "materiales": [
            "5411514",  # conector bimetálico piercing      -> *090810
            "5411054",  # conector cuña UDC                 -> *091608
            "5411058",  # conector de derivación tipo cuña  -> *091608
            "5111215",  # empalme derecho autofundente
            "5021407",  # conductor sólido TWT bipolar
            "6941274",  # abrazadera para pastoral
            "5347088",  # pastoral JP                       -> *091346
            "5347206",  # pastoral chileno corto            -> *091346
            "5347174",  # pastoral AC GO simple             -> *091346
            "5347015",  # pastoral de acero galvanizado     -> *091346
            "5567146",  # luminaria LED 90W                 -> *091320
        ],
        "mano_de_obra": [
            "*091320",  # luminaria o farola completa
            "*091316",  # retiro de luminaria      (sale del recupero)
            "*091322",  # traslado de luminaria    (se pregunta)
            "*091346",  # pastoral simple
            "*091357",  # retiro de pastoral       (sale del recupero)
            "*091356",  # traslado de pastoral     (se pregunta)
            "*091608",  # empalme aéreo BT con conector cuña
            "*090810",  # conector cualquier tipo hasta 300 mm2
        ],
    },
    # Igual que el tipo "Otros" de la actividad sin viento: una sola partida y
    # ningún material.
    "Otros viento": {
        "materiales": [],
        "mano_de_obra": [
            "*010213",  # traslado de cables de comunicación
        ],
    },
}

# Nombres de obra con los que el capataz reconoce el material. Reemplazan a la
# descripción larga del catálogo, que en dos pastorales era idéntica.
DESCRIPCIONES = {
    "5347088": "PASTORAL JP",
    "5347206": "PASTORAL CHILENO CORTO",
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

        for nombre, config in TIPOS.items():
            self._configurar(nombre, config)

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
