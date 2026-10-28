"""Crea la actividad "Calidad de producto", que es una obra de varios días,
y sus dos tipos de trabajo.

La hacen los capataces: cada uno manda un parte por día y por punto, y la
liquidación es la suma de todos los partes (ver core/partes.py). Admite
varios puntos, que el capataz agrega en obra a medida que los ataca. La da
por terminada el coordinador.

Las partidas las pasó el usuario el 2026-10-27, repartidas en "Trabajos
subterraneos" y "Trabajos civiles". Las que ya estaban en el catálogo
conservan su precio y su descripción: el usuario pidió no tocarlas, porque
las cobran también reforzamiento, cabria y viento. Las nuevas nacen con el
precio que dio. Las reglas que las llenan desde el plano están en la app.

Los materiales los pasó el mismo día, sin precio: van en "Trabajos
subterraneos" y se cargan a mano. Los que ya estaban en el catálogo se
dejan como están; los que faltan nacen a PRECIO_DE_PASO.

Es idempotente. Lo corre el script de despliegue en cada build.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (Actividad, ActividadTipoTrabajo, ManoDeObra, Material,
                         TipoTrabajo)

from .configurar_cabria import Command as ConfigurarCabria

CALIDAD_DE_PRODUCTO = "Calidad de producto"

TIPO_SUBTERRANEOS = "Trabajos subterraneos"
TIPO_CIVILES = "Trabajos civiles"

# Con el precio de la lista del 2026-10-27. Solo se usan para crear las que
# falten: las que ya existen se dejan como están.
PARTIDAS = {
    "*090248": ("COLOCACIÓN DE TRÍPODES PARA TRABAJOS EN POSTES DE FE Y DE "
                "CAC DE 8,7 M", Decimal("35.51")),
    "*091420": ("CABLE NYY BT MAYOR A 3-1x16 HASTA 3-1x70 mm2",
                Decimal("3.80")),
    "*091440": ("CABLE NYY BT MAYOR A 3-1x70mm2 HASTA 3-1x185mm2",
                Decimal("5.06")),
    "*091450": ("CABLE NYY BT MAYOR A 3-1x185mm2", Decimal("9.03")),
    "*091633": ("EMPALME UNIPOLAR CABLE NYY RECT. O DERIV. MAYOR DE 35 HASTA "
                "300MM2", Decimal("45.77")),
    "*091642": ("EMPALME ASIMETRICO DE 120 A 300MM2 PARA CABLE NKY/NYY RECTO "
                "O DERIVADO EN B.T.", Decimal("174.04")),
    "*091676": ("PUNTA MUERTA PARA TERNA MONOFÁSICA O TRIFÁSICA CON MANGA "
                "TERMOREST. CABLE NKY / NYY HASTA 300 MM²", Decimal("49.26")),
    "*091775": ("APERTURA Y CIERRE ZANJAS BT(0,60 x 0,70 PROF.) C/ "
                "APISONADORA MOTORIZ.", Decimal("29.11")),
    "*091800": ("RETIRO Y RECOLOCACION DE LOCETAS O PISOS ESPECIALES",
                Decimal("77.71")),
    "*091810": ("REPOSICION DE GRASS", Decimal("6.81")),
    "*091820": ("ROTURA DE ASFALTO", Decimal("21.50")),
    "*091830": ("ROTURA DE PISTA CUALQUIER ESPESOR", Decimal("53.33")),
    "*091845": ("ROTURA DE VEREDA CON MAQUINA CORTADORA EN M2",
                Decimal("30.87")),
    "*091914": ("CRUZADA 8 VIAS HDPE / TIPO 7 (NO INCLUYE ROTURA NI "
                "REPARACION DE PAVIMENTOS)", Decimal("118.70")),
    "*091935": ("INSTALACION DE TUBO HDPE DE HASTA 4 PULGADAS EN ZANJA (POR "
                "METRO LINEAL DE UNA TERNA)", Decimal("3.43")),
    "*095210": ("SONDEOS VARIOS (RECONOCIMIENTO)", Decimal("145.56")),
    "*095227": ("AFIRMADO >6M EN VEREDA (10CM AFIRMADO+10CM TIERRA DEL "
                "LUGAR) INC. COMPACTADO", Decimal("25.58")),
    "*095265": ("REPARACION DE HORMIGON 10 CM ESPESOR 175 KG/CM2 >3M2",
                Decimal("83.28")),
    "*095275": ("REPARACION DE HORMIGON 15 CM ESPESOR 175 KG/CM2",
                Decimal("118.30")),
    "*095280": ("REPARACION DE HORMIGON 20 CM ESPESOR 140KG/CM2",
                Decimal("176.74")),
    "*095282": ("JUNTA DE DILATACION PARA VEREDA DE CUALQUIER ESPESOR OBRA "
                "VENDIDA", Decimal("19.23")),
    "*099090": ("ROTULACIÓN CON LETRERO EN CELDAS,SAB O POSTES MT",
                Decimal("28.38")),
}

PRECIO_DE_PASO = Decimal("1.00")

# La lista del 2026-10-27, en su orden. Solo se usan para crear los que
# falten.
MATERIALES = {
    "0823207": "TOCUYO DE ALGODON 100% 0.60/0.80 X 1 M.",
    "1035468": "UNION RECTA P.TUBO CORRUGADO DE POLIETILENO 110MM DIAM. "
               "P.INSTALAR CABLES DE 60KV EN DUCTOS",
    "1035526": "TUBO CORRUGADO DE POLIETILENO ALTA DENSIDAD COLOR ROJO DE "
               "110 MM X 450 N, P. INSTALAR CABLES BT Y MT",
    "1035527": "TUBO CORRUGADO DE POLIETILENO ALTA DENSIDAD COLOR ROJO/VERDE "
               "110MMX750N P.CRUZADAS DE CABLES BT Y MT",
    "1611112": "VARILLA PLOMO 60% ESTAÑO 40%",
    "2144121": "PASTA CONDUCTORA SINTETICA P.CONEXIONES ELECTRICAS EN ENVASE "
               "8 OZ, RESISTENTE A ALTAS TEMPERATURAS",
    "5031178": "CABLE DE ENERGIA TRIPOLAR TIPO N2XY 3 - 1 X 70MM2 0,6 / 1KV",
    "5031179": "CABLE TRIPOLAR N2XY 3 - 1 X 120MM2 0,6 / 1KV",
    "5031182": "CABLE DE ENERGIA TRIPOLAR TIPO N2XY 3 - 1 X 185MM2 0,6 / 1KV",
    "5031452": "CABLE DE ENERGIA TRIPOLAR TIPO NA2XY 3 - 1 X 240MM",
    "5111138": "EMPALME DERECHO - DERIVACION SIMETRICO UNIPOLAR AUTOFUNDENTE "
               "P.CABLE SECO DE COBRE 70 / 6-70MM2 B.T.",
    "5111146": "EMPALME DERECHO DERIVACION SIMETRICO UNIPOLAR AUTOFUNDENTE "
               "P.CABLE SECO COBRE 120-185/10-185MM2 BT",
    "5111154": "EMPALME DERECHO - DERIVACION SIMETRICO UNIPOLAR AUTOFUNDENTE "
               "P.CABLE SECO DE COBRE 300/10-300MM2 BT",
    "5111253": "EMPALME DERECHO DERIVACION SIMETRICO UNIPOLAR TERMOCONTRAIBLE "
               "P.CABLE ALUMINIO 240-300/70-300MM2 B.T",
    "5111267": "EMPALME DERECHO DERIVACION SIMETRICO UNIPOLAR AUTOFUNDENTE "
               "P.CABLE DE ALUMINIO 240-300/70-300MM2 B.T",
    "5111579": "EMPALME DERECHO DERIVACION ASIMETRICO AUTOFUNDENTE P.CABLE "
               "NKY / SECO COBRE 120-185/10-185MM2 BT",
    "5112242": "CONECTOR TERMINAL A COMPRESION DE COBRE P.CABLE 185MM2, "
               "SIMPLE FIJACION",
    "5112452": "UNION CU.DERECHA ABIERTA PARA CONDUCTOR 185MM2.",
    "5112462": "UNION CU.DERECHA ABIERTA PARA CONDUCTOR 240MM2.",
    "5112472": "UNION CU.DERECHA ABIERTA PARA CONDUCTOR 300MM2.",
    "5112876": "CONECTOR MECANICO EN DERIVACION DE ALEACION DE ALUMINIO "
               "P.CABLES DE ALUMINIO 240-300/70-300MM2, B.T",
    "5114190": "CINTA AISLANTE TERMOPLASTICA DE PVC DE 19MM X 18,3M X 0,18MM "
               "600V COLOR BLANCO USO EN INTERIORES",
    "5114192": "CINTA AISLANTE TERMOPLASTICA DE PVC DE 19MM X 18,3M X 0,18MM "
               "600V COLOR ROJO USO EN INTERIORES",
    "5114193": "CINTA AISLANTE TERMOPLASTICA DE PVC DE 19MM X 18,3M X 0,18MM "
               "600V COLOR VERDE USO EN INTERIORES",
    "5114702": "CINTA SEÑALIZADORA AMARILLA P.CABLES SUBTERRANEOS 220V "
               "P.LUZ DEL SUR",
    "5119222": "PUNTAS MUERTAS AUTOFUNDENTES P.CABLES ENERGIA UNIPOLARES "
               "6 - 35MM2 KIT DE 3 FASES EN B.T.",
    "5119223": "PUNTAS MUERTAS AUTOFUNDENTES P.CABLES ENERGIA UNIPOLARES "
               "70 - 120MM2 KIT DE 3 FASES EN B.T.",
    "5119224": "PUNTAS MUERTAS AUTOFUNDENTES P.CABLES ENERGIA UNIPOLARES "
               "185 - 300MM2 KIT DE 3 FASES EN B.T.",
    "5131920": "ETIQUETAS MARCACION EMPALMES SUBTERRANEOS 85X50MM.",
    "5132746": "CONECTOR DERECHO MECANICO TABICADO DE ALEACION DE ALUMINIO "
               "P.CABLE 95 - 240 / 95 - 240MM2 P.RED M.T.",
    "5132750": "CONECTOR DERECHO MECANICO TABICADO DE ALEACION DE ALUMINIO "
               "P.CABLE 25 - 95 / 95 - 240MM2 P.RED M.T.",
    "5411068": "CONECTOR DE DERIVACION DE COBRE ESTAÑADO TP.CUÑA "
               "P.CONDUCTOR DE COBRE 70 / 10MM2",
    "5411070": "CONECTOR DE DERIVACION DE COBRE ESTAÑADO TP.CUÑA "
               "P.CONDUCTOR DE COBRE 70 / 16MM2",
}

# Todo arranca en cero: lo llena el plano o una pregunta, en la app, y el
# material se carga a mano. El orden es el de la lista del usuario.
CATALOGO_SUBTERRANEOS = {
    "materiales": {matricula: 0 for matricula in MATERIALES},
    "mano_de_obra": {codigo: 0 for codigo in [
        "*090248",  # trípode: se pregunta
        "*091420",  # cable NYY hasta 3-1x70 = metros del plano
        "*091440",  # cable NYY hasta 3-1x185 = metros del plano
        "*091450",  # cable NYY de más de 3-1x185 = metros del plano
        "*091633",  # empalme derecho (E.D) = 3 unipolares por empalme
        "*091642",  # empalme asimétrico (E.A) = los del plano
        "*091676",  # punta muerta = flechas del plano
        "*091775",  # zanja = metros del plano
        "*091914",  # cruzada = metros del plano
        "*091935",  # tubo HDPE en zanja: se pregunta, en metros
        "*095210",  # sondeo = m³ de los S1, S2... del plano
        "*099090",  # rotulación: se pregunta
    ]},
}

CATALOGO_CIVILES = {
    "materiales": {},
    "mano_de_obra": {codigo: 0 for codigo in [
        "*091800",  # locetas = m² de sus paños
        "*091810",  # grass = m² de sus paños
        "*091820",  # rotura de asfalto = m² de sus paños
        "*091830",  # rotura de pista = m² de sus paños
        "*091845",  # rotura de vereda = m² de vereda
        "*095227",  # afirmado = m² de vereda y de solo afirmado
        "*095265",  # reparación 10 cm = m² de sus paños
        "*095275",  # reparación 15 cm = m² de sus paños
        "*095280",  # reparación 20 cm = m² de sus paños
        "*095282",  # junta de dilatación = ancho por juntas de cada paño
    ]},
}


class Command(BaseCommand):
    help = ("Crea la actividad Calidad de producto (obra de varios días) y "
            f"«{TIPO_SUBTERRANEOS}» y «{TIPO_CIVILES}».")

    @transaction.atomic
    def handle(self, *args, **options):
        actividad, creada = Actividad.objects.get_or_create(
            nombre=CALIDAD_DE_PRODUCTO,
            defaults={'varios_dias': True, 'varios_postes': True,
                      'de_encargado': False})
        # Lo que la hace obra de varios días se deja exacto: sin esto se
        # liquidaría como un cambio de poste, reemplazando el parte anterior.
        cambios = []
        for campo, valor in (('varios_dias', True), ('varios_postes', True),
                             ('de_encargado', False)):
            if getattr(actividad, campo) != valor:
                setattr(actividad, campo, valor)
                cambios.append(campo)
        if cambios:
            actividad.save(update_fields=cambios)
        self.stdout.write(
            f"{CALIDAD_DE_PRODUCTO}: {'creada' if creada else 'ya existía'}"
            f"{' (corregido: ' + ', '.join(cambios) + ')' if cambios else ''}.")

        for codigo, (descripcion, precio) in PARTIDAS.items():
            _, nueva = ManoDeObra.objects.get_or_create(
                partida=codigo,
                defaults={"descripcion": descripcion, "precio": precio})
            if nueva:
                self.stdout.write(f"  Partida creada a {precio}: {codigo}")

        for matricula, descripcion in MATERIALES.items():
            _, nuevo = Material.objects.get_or_create(
                matricula=matricula,
                defaults={"descripcion": descripcion,
                          "precio": PRECIO_DE_PASO})
            if nuevo:
                self.stdout.write(
                    f"  Material creado a {PRECIO_DE_PASO}: {matricula}")

        self._tipo(TIPO_SUBTERRANEOS, CATALOGO_SUBTERRANEOS, actividad)
        self._tipo(TIPO_CIVILES, CATALOGO_CIVILES, actividad)

    def _tipo(self, nombre, catalogo, actividad):
        tipo, creado = TipoTrabajo.objects.get_or_create(nombre=nombre)
        if creado:
            self.stdout.write(f"  Tipo de trabajo creado: «{nombre}».")
        ConfigurarCabria(stdout=self.stdout, stderr=self.stderr)._catalogo(
            tipo, catalogo)
        _, vinculado = ActividadTipoTrabajo.objects.get_or_create(
            actividad=actividad, tipo_trabajo=tipo)
        if vinculado:
            self.stdout.write(f"  + {nombre}")
