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

TIPOS = [
    "Alumbrado cabria",
    "Poste cabria",
    "Mensula doble",
    "Mensula simple",
    "Retenida simple",
    "Retenida Violin",
    "Ferreteria",
    "Otros cabria",
]

# Conectores de cuña que la ferretería usa y que no estaban en el catálogo.
# Se crean sin precio: hay que cargárselo antes de liquidar con ellos.
MATERIALES_NUEVOS = {
    "5567145": "LUMINARIA LED TP.III,220V,60HZ,CL.II,SIN TELEG. 165W",
    "5347095": "PASTORAL JP (5347095)",
    "5411060": "CONECTOR CUÑA TP UDC. REF. CU.70/35MM2",
    "5411063": "CONECTOR DE DERIVACION DE COBRE ESTAÑADO TP.CUÑA "
               "P.CONDUCTOR DE COBRE 70 / 70MM2",
    "5411076": "CONECTOR DE DERIVACION DE COBRE ESTAÑADO TP.CUÑA "
               "P.CONDUCTOR DE COBRE 70 / 2,5-4-6MM2",
    "5411078": "CONECTOR DE DERIVACION DE COBRE ESTAÑADO TP.CUÑA "
               "P.CONDUCTOR DE COBRE 70 / 1,5 MM2",
    "5411072": "CONECTOR DE DERIVACION DE COBRE ESTAÑADO TP.CUÑA "
               "P.CONDUCTOR DE COBRE 35 / 1,5 - 2,5MM2",
}

# Partida y precio. Sin precio la liquidación de esa partida sale en cero.
PARTIDAS_NUEVAS = {
    "*090430": ("PORTALINEA DE PASO O REMATE DE 1 A 5 VIAS", "26.91"),
    "*090310": ("RETENIDA SIMPLE O VIOLIN MT O BT", "343.83"),
}

# Tipo de trabajo → materiales y partidas con su cantidad inicial.
CATALOGO = {
    "Otros cabria": {
        "materiales": {},
        "mano_de_obra": {
            "*010101": 0,  # hora de operario: se carga según lo trabajado
            "*010213": 0,  # traslado de cables de comunicación
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

        for nombre in TIPOS:
            tipo, _ = TipoTrabajo.objects.get_or_create(nombre=nombre)
            ActividadTipoTrabajo.objects.get_or_create(
                actividad=actividad, tipo_trabajo=tipo)
            if nombre in CATALOGO:
                self._catalogo(tipo, CATALOGO[nombre])

        self.stdout.write(self.style.SUCCESS(
            f"{ACTIVIDAD}: {actividad.tipos_trabajo.count()} tipos de trabajo, "
            f"{len(CATALOGO)} con catálogo definido."))

    def _crear_lo_que_falta(self):
        """Da de alta lo que la actividad usa y el catálogo no tenía.

        Nacen sin precio, así que se avisa: sin precio, la liquidación de esa
        partida sale en cero.
        """
        for matricula, descripcion in MATERIALES_NUEVOS.items():
            _, nuevo = Material.objects.get_or_create(
                matricula=matricula,
                defaults={"descripcion": descripcion, "precio": 0})
            if nuevo:
                self.stdout.write(self.style.WARNING(
                    f"  Material creado SIN PRECIO: {matricula}"))
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
        for codigo, cantidad in config["mano_de_obra"].items():
            partida = partidas.get(codigo)
            if partida is None:
                continue
            TipoTrabajoManoDeObra.objects.update_or_create(
                tipo_trabajo=tipo, mano_de_obra=partida,
                defaults={"cantidad_inicial": cantidad})

        self.stdout.write(
            f"  {tipo.nombre}: {tipo.materiales.count()} materiales, "
            f"{tipo.partidas.count()} partidas.")

    def _faltantes(self, tipo, que, pedidos, encontrados):
        faltan = [p for p in pedidos if p not in encontrados]
        if faltan:
            self.stdout.write(self.style.WARNING(
                f"  {tipo.nombre}: no están en el catálogo y se omiten "
                f"{que}: {', '.join(faltan)}"))
