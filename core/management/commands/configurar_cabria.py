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
