"""Actividad de cabria aérea: sus tipos de trabajo y el catálogo de cada uno.

La actividad y sus siete tipos se crean siempre. El catálogo, en cambio, solo
se escribe para los tipos que están definidos aquí abajo: los demás nacen
vacíos y se arman desde la pantalla de Configuración, y un despliegue no puede
llevárselos por delante.

La "cantidad inicial" es lo que se propone al elegir el tipo de trabajo. El
capataz la corrige si en obra salió distinto.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    Actividad, ActividadTipoTrabajo, ManoDeObra, Material, TipoTrabajo,
    TipoTrabajoManoDeObra, TipoTrabajoMaterial,
)

ACTIVIDAD = "Cambio de poste inacc. cabria aereo"

# El orden es el de la obra y es el que ve el capataz: primero el poste, al
# final lo suelto. Cambiar esta lista cambia el orden en la app.
TIPOS = [
    "Poste cabria",
    "Alumbrado cabria",
    "Ferreteria",
    "Conexiones cabria",
    "Retenida simple",
    "Retenida Violin",
    "Mensula simple",
    "Mensula doble",
    'Retenida Tipo "Y"',
    "Retiros - otros - cabria",
]

# Precio de paso de los materiales que el catálogo no trae. A cero no se
# liquidan; a 1 salen en la liquidación y se ve que les falta el precio real.
PRECIO_DE_PASO = "1.00"

# Conectores de cuña que la ferretería usa y que no estaban en el catálogo.
# Se crean a PRECIO_DE_PASO: hay que cargarles el precio real.
MATERIALES_NUEVOS = {
    "5567145": "LUMINARIA LED TP.III,220V,60HZ,CL.II,SIN TELEG. 165W",
    "5347095": "PASTORAL JP",
    "5411060": "CONECTOR CUÑA TP UDC. REF. CU.70/35MM2",
    "5411063": "CONECTOR DE DERIVACION DE COBRE ESTAÑADO TP.CUÑA "
               "P.CONDUCTOR DE COBRE 70 / 70MM2",
    "5411076": "CONECTOR DE DERIVACION DE COBRE ESTAÑADO TP.CUÑA "
               "P.CONDUCTOR DE COBRE 70 / 2,5-4-6MM2",
    "5411078": "CONECTOR DE DERIVACION DE COBRE ESTAÑADO TP.CUÑA "
               "P.CONDUCTOR DE COBRE 70 / 1,5 MM2",
    "5411072": "CONECTOR DE DERIVACION DE COBRE ESTAÑADO TP.CUÑA "
               "P.CONDUCTOR DE COBRE 35 / 1,5 - 2,5MM2",
    "5411070": "CONECTOR DE DERIVACION DE COBRE ESTAÑADO TP.CUÑA "
               "P.CONDUCTOR DE COBRE 70 / 16MM2",
    "5111221": "EMPALME DERECHO DERIVACION UNIPOLAR AUTOFUNDENTE P.CABLE "
               "SECO 6-120 / 10-120MM2 CONEX. TRIFASICA BT",
}

# Partida y precio. Sin precio la liquidación de esa partida sale en cero.
PARTIDAS_NUEVAS = {
    "*090163": ("TRASLADO CABLE AUTOSOPORTADO DE BT CU O AL MAYOR DE 50 "
                "HASTA 120 mm2", "9.71"),
    "*090430": ("PORTALINEA DE PASO O REMATE DE 1 A 5 VIAS", "26.91"),
    "*090310": ("RETENIDA SIMPLE O VIOLIN MT O BT", "343.83"),
}

# Partidas cuyo precio y nombre se fuerzan. A diferencia de las de arriba,
# estas se pisan aunque ya tengan precio: lo que traía el catálogo no era lo
# pactado, y una corrida vieja pudo dejar otro precio.
# La hora de operario importa porque de ella sale el traslado de cable
# delgado: la app divide el monto por metro entre este precio.
# El traslado de cables de comunicación venía como hora de cuadrilla con grúa.
# Ojo: Liquidacion.xls lo trae a 201.04, pero lo pactado es 210.04 y manda
# esto (confirmado por el usuario el 2026-09-17). La rotura de vereda salía a
# 119.73, casi lo mismo que repararla, y el pactado es el del Excel.
PRECIOS_FIJOS = {
    "*010101": ("HORA DE OPERARIO (TRASLADO DE CABLES INACCESIBLE <=35MM)",
                "19.73"),
    "*010213": ("TRASLADO DE CABLES DE COMUNICACION", "210.04"),
    "*091840": ("ROTURA DE VEREDA CUALQUIER ESPESOR S/MAQ.CORTADORA",
                "24.55"),
    # Se había creado a 58.45, copiando el traslado de caja.
    "*093043": ("TRASLADO DE ABRAZADERA TIPO CORONA CON GANCHOS", "10.32"),
}

# Tipo de trabajo → materiales y partidas con su cantidad inicial.
CATALOGO = {
    "Retiros - otros - cabria": {
        "materiales": {},
        "mano_de_obra": {
            "*010101": 0,  # hora de operario: se carga según lo trabajado
            "*010213": 0,  # traslado de cables de comunicación
            # Retiros: la app los llena con lo cargado en Recupero.
            "*090137": 0,  # retiro cable 50-120 mm2     <- CAAIS 3x70(+1x16)
            "*090139": 0,  # retiro cable 10-25 mm2      <- CAAIS 3x16(+1x16)
            "*090138": 0,  # retiro cable 25-50 mm2      <- CAAIS 3x35+1x16
            "*091411": 0,  # retiro cable NYY            <- NYY 2-1x6
            "*091448": 0,  # retiro cable NYBY - NKY     <- NKY 2x6
            "*090491": 0,  # retiro poste acero < 7      <- poste fierro 6.4
            "*090497": 0,  # retiro poste acero > 7      <- poste fierro 7
            "*093241": 0,  # retiro caja de distribución <- caja de derivación
            "*093044": 0,  # retiro corona 4 ganchos     <- abrazadera corona
            "*090189": 0,  # retiro ménsula simple       <- ménsula suelta
            "*098669": 0,  # retiro ménsula doble        <- ménsulas de a dos
            "*090061": 0,  # retiro diagonal             <- diagonal
            "*090064": 0,  # retiro abrazadera de perfil <- abrazadera 4 pernos
            "*090391": 0,  # retiro perno de anclaje     <- pernos
            "*090395": 0,  # retiro punto de fijación    <- grapas
            "*090319": 0,  # retiro retenida-templador   <- cable acerado
        },
    },
    "Mensula simple": {
        "materiales": {
            "5461238": 8,  # arandela cuadrada plana
            "5335110": 1,  # ménsula de madera 4x5x4 pies   -> *090191
            "5337120": 1,  # diagonal de acero              -> *090060
            "6941170": 1,  # abrazadera de 4 pernos         -> *090065
            "5463118": 3,  # varilla roscada 450 mm
            "5463110": 1,  # varilla roscada 250 mm
            "5334104": 1,  # cruceta simétrica de madera    -> *090191
        },
        "mano_de_obra": {
            "*090191": 1,  # colocación de cruceta o ménsula simple
            "*090060": 1,  # diagonal para cruceta
            "*090065": 1,  # abrazadera para perfil
        },
    },
    # El cambio de poste con cabria. Casi todas las partidas se llenan solas o
    # se cargan a mano; ver las reglas en reglas_liquidacion.dart.
    # Conexiones domiciliarias. Sin cantidades: cada poste lleva las suyas.
    "Conexiones cabria": {
        "materiales": {
            "6933194": 0,  # caja de derivación y acometida  -> *093242
            "6941188": 0,  # abrazadera tipo corona          -> *093045
            "5023720": 0,  # cable CAAI-S 3x16
            "1014213": 0,  # fleje de acero inoxidable
            "1014308": 0,  # grapa o hebilla para el fleje
            "5484220": 0,  # templador de acometida
            "5484222": 0,  # templador de acometida trifásica
            "5411524": 0,  # conector piercing
            "5411050": 0,  # conector cuña 25-35 / 16-25
            "5411052": 0,  # conector cuña 16/16, 25/10
            "5411070": 0,  # conector cuña 70/16
            "5111215": 0,  # empalme para un conector
            "5111218": 0,  # empalme para dos conectores
            "5111221": 0,  # empalme para tres conectores
        },
        "mano_de_obra": {
            "*093242": 0,  # caja de distribución       (= 6933194)
            "*093247": 0,  # traslado de caja           (se pregunta)
            "*093045": 0,  # corona de 4 ganchos        (= 6941188)
            "*093043": 0,  # traslado de corona         (se pregunta)
            "*093081": 0,  # traslado de acometida      (se pregunta cuántas)
        },
    },
    "Poste cabria": {
        "materiales": {
            "5331596": 0,  # poste PRFV 7,5
            "5331616": 0,  # poste PRFV 9
            "1014213": 0,  # fleje de acero inoxidable
            "1014308": 0,  # grapa o hebilla para el fleje
        },
        "mano_de_obra": {
            "*094395": 0,  # inspección previa
            "*095266": 0,  # reparación de vereda
            "*091840": 0,  # rotura de vereda      (= reparación)
            "*091842": 0,  # corte de vereda       (a mano)
            "*090248": 0,  # colocación de trípodes (a mano)
            "*090636": 0,  # traslado de postes a disposición final
            "*090632": 0,  # arrastre en pendiente (excluyente con *090630)
            "*090630": 0,  # arrastre en plano     (excluyente con *090632)
            "*090634": 0,  # traslado manual       (excedente del arrastre)
            "*090633": 0,  # acarreo para cimentación
            "*094913": 0,  # punta de diamante     (a mano)
            "*094918": 0,  # cimentación           (a mano)
            "*094911": 0,  # solera de concreto    (a mano)
            "*090482": 0,  # instalación de poste provisional
            "*090468": 0,  # retiro de poste provisional
            "*090471": 0,  # cambio de poste sin vereda
            "*090470": 0,  # cambio de poste con vereda
            "*090163": 0,  # traslado de cable autosoportado
        },
    },
    # Alumbrado de cabria. Sin cantidades: cada poste lleva lo suyo.
    "Alumbrado cabria": {
        "materiales": {
            "5411514": 0,  # conector piercing        -> *090810
            "5411054": 0,  # conector cuña            -> *091608
            "5411058": 0,  # conector de derivación   -> *091608
            "5411078": 0,  # conector 70/1,5          -> *091608
            "5411072": 0,  # conector 35/1,5-2,5      -> *091608
            "5111215": 0,  # empalme autofundente
            "5021407": 0,  # conductor bipolar (indoprene)
            "6941274": 0,  # abrazadera para pastoral
            "5347174": 0,  # pastoral                 -> *091346
            "5347015": 0,  # pastoral bastón          -> *091346
            "5347095": 0,  # pastoral JP              -> *091346
            "5567146": 0,  # luminaria LED 90W        -> *091320
            "5567145": 0,  # luminaria LED 165W       -> *091320
        },
        "mano_de_obra": {
            "*091320": 0,  # luminaria o farola completa
            "*091316": 0,  # retiro de luminaria   (sale del recupero)
            "*091322": 0,  # traslado de luminaria (se pregunta)
            "*091346": 0,  # pastoral simple
            "*091357": 0,  # retiro de pastoral    (sale del recupero)
            "*091356": 0,  # traslado de pastoral  (se pregunta)
            "*091608": 0,  # empalme aéreo por conector
            "*090810": 0,  # conector cualquier tipo
        },
    },
    # Ferretería no trae cantidades: se carga lo que se usó en cada poste.
    "Ferreteria": {
        "materiales": {
            "5422366": 0,  # grapa de dos vías      -> *090394
            "5422364": 0,  # grapa de una vía       -> *090394
            "5463620": 0,  # ojal roscado
            "1015413": 0,  # guardacabo
            "5461510": 0,  # arandela cuadrada curva
            "5464210": 0,  # perno con ojal         -> *090392
            "5467060": 0,  # perno hexagonal        -> *090392
            "5464501": 0,  # soporte fin de línea   -> *090430
            "5021243": 0,  # conductor TW 16mm2     -> *090080
            "5111215": 0,  # empalme para un conector
            "5111218": 0,  # empalme para dos conectores
            # Conectores de cuña: cada uno paga un empalme aéreo.
            "5411011": 0,
            "5411050": 0,
            "5411052": 0,
            "5411054": 0,
            "5411056": 0,
            "5411058": 0,
            "5411060": 0,
            "5411062": 0,
            "5411063": 0,
            "5411072": 0,
            "5411076": 0,
            "5411078": 0,
        },
        "mano_de_obra": {
            "*090238": 0,  # escalamiento de poste (se carga a mano)
            "*090392": 0,  # perno para anclaje
            "*090394": 0,  # punto de fijación
            "*090080": 0,  # conductor hasta 25 mm2
            "*091608": 0,  # empalme aéreo por conector
            "*090430": 0,  # portalínea de paso o remate
        },
    },
    # Retenida violín. La zapata y la barra de anclaje arrancan en blanco: no
    # se usan siempre, y son las que deciden qué partida se cobra.
    "Retenida Violin": {
        "materiales": {
            "5016361": 9,  # cable de acero para retenida
            "5419120": 4,  # amarre preformado
            "5217631": 1,  # aislador de tensión
            "5467804": 1,  # brazo de apoyo tipo violín
            "5467624": 1,  # canaleta protectora
            "5464101": 1,  # eslabón angular
            "1014213": 2,  # fleje de acero inoxidable
            "1014308": 2,  # grapa o hebilla para el fleje
            "5329301": 0,  # zapata de concreto   -> *090310
            "5467101": 0,  # barra con ojo        -> *090310
        },
        "mano_de_obra": {
            "*090310": 0,  # retenida simple o violín: anclada a tierra
            "*090320": 0,  # retenida-templador aéreo: sin anclaje a tierra
        },
    },
    # Retenida simple: la misma lógica que la violín, pero sin brazo de apoyo
    # ni fleje, y con el anclaje al piso como caso normal.
    "Retenida simple": {
        "materiales": {
            "5016361": 9,  # cable de acero para retenida
            "5419120": 4,  # amarre preformado
            "5217631": 1,  # aislador de tensión
            "5467624": 1,  # canaleta protectora
            "5464101": 1,  # eslabón angular
            "5329301": 1,  # zapata de concreto   -> *090310
            "5467101": 1,  # barra con ojo        -> *090310
        },
        "mano_de_obra": {
            "*090310": 0,  # retenida simple o violín: anclada a tierra
            "*090320": 0,  # retenida-templador aéreo: sin anclaje a tierra
        },
    },
    # Retenida tipo "Y": dos vientos, así que lleva el doble de cable, amarres
    # y aisladores que la violín. El anclaje al piso decide las partidas.
    'Retenida Tipo "Y"': {
        "materiales": {
            "1014213": 2,   # fleje de acero inoxidable
            "1014308": 2,   # grapa o hebilla para el fleje
            "5016361": 18,  # cable de acero para retenida
            "5419120": 8,   # amarre preformado
            "5217631": 2,   # aislador de tensión
            "5467804": 1,   # brazo de apoyo tipo violín
            "5467624": 1,   # canaleta protectora
            "5464101": 2,   # eslabón angular
            "5329301": 1,   # zapata de concreto   -> *090310
            "5467101": 1,   # barra con ojo        -> *090310
        },
        "mano_de_obra": {
            "*090310": 0,  # retenida simple o violín: anclada a tierra
            "*090320": 0,  # retenida-templador aéreo
        },
    },
    "Mensula doble": {
        "materiales": {
            "5461238": 14,
            "5335110": 2,  # dos ménsulas hacen una colocación doble
            "5337120": 2,  # -> *090060
            "6941170": 1,  # -> *090065
            "5463118": 4,
            "5463110": 2,
            "5466606": 3,  # plancha de cobre para línea a tierra
        },
        "mano_de_obra": {
            "*098670": 1,  # colocación de cruceta o ménsula doble
            "*090060": 2,
            "*090065": 1,
        },
    },
}


class Command(BaseCommand):
    help = f'Configura la actividad "{ACTIVIDAD}" y sus tipos de trabajo.'

    @transaction.atomic
    def handle(self, *args, **options):
        self._crear_lo_que_falta()
        actividad, nueva = Actividad.objects.get_or_create(nombre=ACTIVIDAD)
        if nueva:
            self.stdout.write(f"Actividad creada: {ACTIVIDAD}")

        for posicion, nombre in enumerate(TIPOS, start=1):
            tipo, _ = TipoTrabajo.objects.get_or_create(nombre=nombre)
            ActividadTipoTrabajo.objects.update_or_create(
                actividad=actividad, tipo_trabajo=tipo,
                defaults={"orden": posicion})
            if nombre in CATALOGO:
                self._catalogo(tipo, CATALOGO[nombre])

        self.stdout.write(self.style.SUCCESS(
            f"{ACTIVIDAD}: {actividad.tipos_trabajo.count()} tipos de trabajo, "
            f"{len(CATALOGO)} con catálogo definido."))

    def _crear_lo_que_falta(self):
        """Da de alta lo que la actividad usa y el catálogo no tenía.

        Los materiales nacen a 1 y no a cero, porque a cero no se liquidan.
        Es un precio de paso: hay que cargarles el real.
        """
        for matricula, descripcion in MATERIALES_NUEVOS.items():
            obj, nuevo = Material.objects.get_or_create(
                matricula=matricula,
                defaults={"descripcion": descripcion, "precio": PRECIO_DE_PASO})
            if nuevo:
                self.stdout.write(self.style.WARNING(
                    f"  Material creado a {PRECIO_DE_PASO}: {matricula}"))
            elif not obj.precio:
                # Lo dejó a cero una corrida anterior.
                obj.precio = PRECIO_DE_PASO
                obj.save(update_fields=["precio"])
                self.stdout.write(self.style.WARNING(
                    f"  Material a {PRECIO_DE_PASO}: {matricula}"))
        for partida, (descripcion, precio) in PARTIDAS_NUEVAS.items():
            obj, nueva = ManoDeObra.objects.get_or_create(
                partida=partida,
                defaults={"descripcion": descripcion, "precio": precio})
            if nueva and float(precio) == 0:
                self.stdout.write(self.style.WARNING(
                    f"  Partida creada SIN PRECIO: {partida}"))
            elif nueva:
                self.stdout.write(f"  Partida creada: {partida} a {precio}")
            elif not obj.precio and float(precio) > 0:
                # Quedó sin precio de una corrida anterior.
                obj.precio = precio
                obj.save(update_fields=["precio"])
                self.stdout.write(f"  Precio cargado: {partida} a {precio}")

        for partida, (descripcion, precio) in PRECIOS_FIJOS.items():
            obj, nueva = ManoDeObra.objects.get_or_create(
                partida=partida,
                defaults={"descripcion": descripcion, "precio": precio})
            if nueva:
                self.stdout.write(f"  Partida creada: {partida} a {precio}")
                continue
            cambios = []
            if str(obj.precio) != precio:
                cambios.append(f"precio de {obj.precio} a {precio}")
                obj.precio = precio
            if obj.descripcion != descripcion:
                cambios.append(f"nombre a {descripcion}")
                obj.descripcion = descripcion
            if cambios:
                obj.save(update_fields=["precio", "descripcion"])
                self.stdout.write(
                    f"  {partida} corregida: {'; '.join(cambios)}")

    def _catalogo(self, tipo, config):
        """Deja el conjunto exacto, con sus cantidades iniciales."""
        materiales = {
            m.matricula: m for m in
            Material.objects.filter(matricula__in=config["materiales"])}
        self._faltantes(tipo, "materiales", config["materiales"], materiales)
        (TipoTrabajoMaterial.objects
         .filter(tipo_trabajo=tipo)
         .exclude(material__in=materiales.values()).delete())
        for matricula, cantidad in config["materiales"].items():
            material = materiales.get(matricula)
            if material is None:
                continue
            TipoTrabajoMaterial.objects.update_or_create(
                tipo_trabajo=tipo, material=material,
                defaults={"cantidad_inicial": cantidad})

        partidas = {
            p.partida: p for p in
            ManoDeObra.objects.filter(partida__in=config["mano_de_obra"])}
        self._faltantes(tipo, "partidas", config["mano_de_obra"], partidas)
        (TipoTrabajoManoDeObra.objects
         .filter(tipo_trabajo=tipo)
         .exclude(mano_de_obra__in=partidas.values()).delete())
        # El orden en que están escritas aquí es el que ve el capataz: el
        # arrastre antes que el acarreo, que se calcula desde él.
        for orden, (codigo, cantidad) in enumerate(config["mano_de_obra"].items()):
            partida = partidas.get(codigo)
            if partida is None:
                continue
            TipoTrabajoManoDeObra.objects.update_or_create(
                tipo_trabajo=tipo, mano_de_obra=partida,
                defaults={"cantidad_inicial": cantidad, "orden": orden})

        self.stdout.write(
            f"  {tipo.nombre}: {tipo.materiales.count()} materiales, "
            f"{tipo.partidas.count()} partidas.")

    def _faltantes(self, tipo, que, pedidos, encontrados):
        faltan = [p for p in pedidos if p not in encontrados]
        if faltan:
            self.stdout.write(self.style.WARNING(
                f"  {tipo.nombre}: no están en el catálogo y se omiten "
                f"{que}: {', '.join(faltan)}"))
