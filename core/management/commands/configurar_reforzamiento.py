"""Crea las dos actividades de reforzamiento de poste, que son de encargado,
el cemento que usan y el tipo de trabajo de cada una.

Un encargado solo ve las actividades de encargado, y estas son las suyas; el
capataz no las ve.

El cemento va por bolsa de 42.5 kg y es un agregado: no se pide, se asigna.
Nace con matrícula y precio provisionales.

"Reforzamiento con vereda" es el tipo de trabajo de la actividad con vereda,
con las partidas en el orden en que se hace la obra. Las que ya estaban en el
catálogo conservan su precio: el usuario pidió no tocarlas, porque las cobran
también cabria y viento. Las nuevas nacen con el precio que dio; la reparación
de vereda de 15 cm y los refuerzos, que no lo tenían, a PRECIO_DE_PASO. Las
reglas que las llenan (preguntas, paños, corte y rotura) están en la app.

Nada de lo que ya existe se pisa: lo corregido desde Configuración sobrevive
al próximo despliegue. Lo único que se deja exacto es el conjunto de partidas
y materiales del tipo de trabajo.

"Reforzamiento sin vereda" es el de la otra actividad: lleva el mismo
material, y en lugar de vereda, pista y asfalto se mide piso especial y grass.

Es idempotente. Lo corre el script de despliegue en cada build.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (Actividad, ActividadTipoTrabajo, ManoDeObra, Material,
                         TipoTrabajo)

from .configurar_cabria import Command as ConfigurarCabria

CON_VEREDA = "Reforzamiento de poste con vereda"

SIN_VEREDA = "Reforzamiento de poste sin vereda / piso especial"

ACTIVIDADES = [CON_VEREDA, SIN_VEREDA]

PRECIO_DE_PASO = Decimal("1.00")

CEMENTO = {
    "matricula":   "CEMENTO-425",
    "descripcion": "CEMENTO (BOLSA 42.5 KG)",
    "precio":      PRECIO_DE_PASO,
}

TIPO_CON_VEREDA = "Reforzamiento con vereda"
TIPO_SIN_VEREDA = "Reforzamiento sin vereda"

# Las partidas que no estaban en el catálogo, con el precio que dio el
# usuario el 2026-09-28.
PARTIDAS_NUEVAS = {
    "*090251": ("REFORZAMIENTO CON VEREDA", Decimal("467.52")),
    "*095275": ("REPARACION DE VEREDA DE 15CM M2", PRECIO_DE_PASO),
    "*094919": ("CIMENTACION COMPLEMENTARIA", Decimal("56.35")),
    "*091830": ("ROTURA DE PISTA CUALQUIER ESPESOR", Decimal("54.04")),
    "*095230": ("REPARACION DE ASFALTO M2", Decimal("122.42")),
    "*098822": ("ROTURA DE CIMENTACION", Decimal("78.09")),
    "*099090": ("ROTULACION DE PAT", Decimal("29.30")),
    "*091673": ("COLOC.TUBO PVC.A POSTE P/PUNTO DE ALIMENTACION "
                "(FLEJADO DE SUBIDA)", Decimal("28.00")),
}

# Las del reforzamiento sin vereda que no estaban en el catálogo, con el
# precio que dio el usuario el 2026-10-02. Las que no lo tenían, a
# PRECIO_DE_PASO.
PARTIDAS_SIN_VEREDA = {
    "*090252": ("REFORZAMIENTO SIN VEREDA", Decimal("405.35")),
    "*091800": ("REPARACION DE PISO ESPECIAL M2", PRECIO_DE_PASO),
    "*091810": ("REPOSICION DE GRASS M2", Decimal("80.51")),
    "*020000": ("REPOSICION DE PISOS ESPECIALES M2", PRECIO_DE_PASO),
}

# Partidas con precio pactado: se crean si faltan y, si alguien las cambió,
# se corrigen en cada despliegue.
PRECIOS_FIJOS = {
    # Nació a 140.00 como "REPARACION DE VEREDA DE 20CM M2"; el usuario la
    # corrigió el 2026-09-29.
    "*095280": ("REPARACION DE VEREDA O PISTA 20CM", Decimal("180.00")),
    # Nació a 33.35 como "ROTURA DE VEREDA CON MAQUINA"; corregida el mismo día.
    "*091845": ("ROTURA DE VEREDA CON MAQUINA CORTADORA EN M2", Decimal("31.82")),
}

# Las chaquetas de refuerzo. Se liquida una sola por SST: la regla de la app
# las agrupa por la palabra "REFUERZO" de la descripción.
REFUERZOS = {
    "6913290": "REFUERZO DE FIBRA 7 / 100",
    "6913291": "REFUERZO DE FIBRA 7 / 200",
    "6913292": "REFUERZO DE FIBRA 8,7 / 200",
    "6913293": "REFUERZO DE FIBRA 8,7 / 300",
    "6913294": "REFUERZO DE FIBRA 11,5 / 300",
    "6913284": "REFUERZO DE FIBRA 13 / 300-400-500",
    "6913286": "REFUERZO DE FIBRA 15 / 400-500",
}

# Lo demás que se liquida a mano. El fleje y la hebilla ya los trae el
# catálogo de cabria; si faltaran, nacen con esta descripción.
MATERIALES_A_MANO = {
    "1014213": 'FLEJE (3/4")',
    "1014308": "GRAPA HEBILLA 3/4",
    "2139148": "PEGAMENTO EN GEL",
}

# El tipo de trabajo, con la cantidad con que arranca cada fila. La
# inspección va siempre y el reforzamiento es uno; lo demás se pregunta o se
# calcula en la app. El orden es el que ve quien liquida.
CATALOGO_CON_VEREDA = {
    "materiales": {matricula: 0 for matricula in [*REFUERZOS, *MATERIALES_A_MANO]},
    "mano_de_obra": {
        "*094395": 1,  # inspección previa: siempre
        "*090248": 0,  # trípode: se pregunta
        "*090251": 1,  # reforzamiento con vereda
        "*095266": 0,  # reparación de vereda 10 cm = m² de sus paños
        "*095275": 0,  # reparación de vereda 15 cm = m² de sus paños
        "*095280": 0,  # reparación de vereda 20 cm = m² de sus paños
        "*091842": 0,  # corte de vereda = m² de vereda, hasta 2
        "*091845": 0,  # rotura con máquina = m² de vereda pasados los 2
        "*094919": 0,  # cimentación complementaria: se pregunta
        "*091830": 0,  # rotura de pista = m² de sus paños
        "*095230": 0,  # reparación de asfalto = m² de sus paños / 0.60
        "*098203": 0,  # tubo corrugado: se pregunta
        "*098822": 0,  # rotura de cimentación: se pregunta
        "*090633": 0,  # acarreo = metros por viajes
        "*099090": 0,  # rotulación de PAT: se pregunta
        "*091673": 0,  # flejado de subida: se pregunta
    },
}

# El de la actividad sin vereda, con el mismo material. El reforzamiento es
# uno; lo demás se pregunta o se calcula en la app.
CATALOGO_SIN_VEREDA = {
    "materiales": CATALOGO_CON_VEREDA["materiales"],
    "mano_de_obra": {
        "*094395": 1,  # inspección previa: siempre
        "*090248": 0,  # trípode: se pregunta
        "*090252": 1,  # reforzamiento sin vereda
        "*094919": 0,  # cimentación complementaria: se pregunta
        "*091800": 0,  # reparación de piso especial = m² de sus paños
        "*091810": 0,  # reposición de grass = m² de sus paños
        "*098203": 0,  # tubo corrugado: se pregunta
        "*098822": 0,  # rotura de cimentación: se pregunta
        "*090633": 0,  # acarreo = metros por viajes
        "*099090": 0,  # rotulación de PAT: se pregunta
        "*091673": 0,  # flejado de subida: se pregunta
        "*020000": 0,  # reposición de piso = 1 si se compró
    },
}


class Command(BaseCommand):
    help = ("Crea las actividades de reforzamiento de poste, el cemento y "
            f"«{TIPO_CON_VEREDA}» y «{TIPO_SIN_VEREDA}».")

    @transaction.atomic
    def handle(self, *args, **options):
        for nombre in ACTIVIDADES:
            actividad, nueva = Actividad.objects.get_or_create(
                nombre=nombre, defaults={"de_encargado": True})
            if nueva:
                self.stdout.write(self.style.SUCCESS(
                    f"Actividad creada: «{nombre}»."))
            elif not actividad.de_encargado:
                actividad.de_encargado = True
                actividad.save(update_fields=["de_encargado"])
                self.stdout.write(f"  «{nombre}» pasa a ser de encargado")

        cemento, nuevo = Material.objects.get_or_create(
            matricula=CEMENTO["matricula"],
            defaults={"descripcion": CEMENTO["descripcion"],
                      "precio": CEMENTO["precio"],
                      "es_agregado": True})
        if nuevo:
            self.stdout.write(self.style.SUCCESS(
                f"Material creado: «{cemento.descripcion}»."))
        elif not cemento.es_agregado:
            cemento.es_agregado = True
            cemento.save(update_fields=["es_agregado"])
            self.stdout.write(f"  «{cemento.descripcion}» pasa a ser agregado")

        for matricula, descripcion in {**REFUERZOS, **MATERIALES_A_MANO}.items():
            _, nuevo = Material.objects.get_or_create(
                matricula=matricula,
                defaults={"descripcion": descripcion, "precio": PRECIO_DE_PASO})
            if nuevo:
                self.stdout.write(
                    f"  Material creado a {PRECIO_DE_PASO}: {matricula}")

        for codigo, (descripcion, precio) in {**PARTIDAS_NUEVAS,
                                              **PARTIDAS_SIN_VEREDA}.items():
            _, nueva = ManoDeObra.objects.get_or_create(
                partida=codigo,
                defaults={"descripcion": descripcion, "precio": precio})
            if nueva:
                self.stdout.write(f"  Partida creada a {precio}: {codigo}")

        for codigo, (descripcion, precio) in PRECIOS_FIJOS.items():
            partida, nueva = ManoDeObra.objects.get_or_create(
                partida=codigo,
                defaults={"descripcion": descripcion, "precio": precio})
            if nueva:
                self.stdout.write(f"  Partida creada a {precio}: {codigo}")
            elif partida.precio != precio or partida.descripcion != descripcion:
                partida.precio, partida.descripcion = precio, descripcion
                partida.save(update_fields=["precio", "descripcion"])
                self.stdout.write(f"  {codigo} corregida: {descripcion} a {precio}")

        self._tipo(TIPO_CON_VEREDA, CATALOGO_CON_VEREDA, CON_VEREDA)
        self._tipo(TIPO_SIN_VEREDA, CATALOGO_SIN_VEREDA, SIN_VEREDA)

    def _tipo(self, nombre, catalogo, actividad):
        tipo, creado = TipoTrabajo.objects.get_or_create(nombre=nombre)
        if creado:
            self.stdout.write(f"  Tipo de trabajo creado: «{nombre}».")
        ConfigurarCabria(stdout=self.stdout, stderr=self.stderr)._catalogo(
            tipo, catalogo)
        _, vinculado = ActividadTipoTrabajo.objects.get_or_create(
            actividad=Actividad.objects.get(nombre=actividad),
            tipo_trabajo=tipo)
        if vinculado:
            self.stdout.write(f"  + {nombre}")
