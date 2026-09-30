"""
La actividad aérea de viento: varios postes por SST y sus tipos de trabajo.

"Poste viento" va primero, con su catálogo. Alumbrado, ferretería y conexiones son
copias de las de cabria con nombre propio; las retenidas y las ménsulas son
las mismas de cabria. "Retiros - otros - viento" va al final, con el catálogo
de los retiros de cabria. Lo que se agregue desde Configuración sobrevive.
"""
from decimal import Decimal

from django.core.management import call_command

from ..inclusiones import INCLUSIONES_CONSOLIDADO, consolidar_partidas
from ..management.commands.configurar_aereo_viento import (
    CATALOGO_DEL_POSTE, COMPARTIDOS, COPIAS,
)
from ..management.commands.configurar_cabria import CATALOGO
from ..models import (
    Actividad, ActividadTipoTrabajo, ManoDeObra, Material, TipoTrabajo,
    TipoTrabajoManoDeObra, TipoTrabajoMaterial,
)
from .base import BaseAPITestCase

NOMBRE = "Cambio de poste inaccesible aereo - Viento"
RETIROS = "Retiros - otros - viento"
PARTIDAS_DE_CABRIA = list(CATALOGO["Retiros - otros - cabria"]["mano_de_obra"])
# El retiro del poste de fibra: viento lo retira y cabria no.
PARTIDAS_DE_VIENTO = PARTIDAS_DE_CABRIA + ["*090468"]
POSTE = "Poste viento"
# Todos, en el orden de la obra.
TIPOS = [POSTE, *COPIAS, *COMPARTIDOS, RETIROS]


class AereoVientoTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        for partida in PARTIDAS_DE_VIENTO:
            ManoDeObra.objects.get_or_create(
                partida=partida,
                defaults={"descripcion": partida, "precio": Decimal("1.00")})
        # El catálogo de las copias y del poste, para que haya algo que poner.
        catalogos = [CATALOGO[o] for o in COPIAS.values()] + [CATALOGO_DEL_POSTE]
        for catalogo in catalogos:
            for partida in catalogo["mano_de_obra"]:
                ManoDeObra.objects.get_or_create(
                    partida=partida,
                    defaults={"descripcion": partida, "precio": Decimal("1.00")})
            for matricula in catalogo["materiales"]:
                Material.objects.get_or_create(
                    matricula=matricula,
                    defaults={"descripcion": matricula, "precio": Decimal("1.00")})
        for original in COPIAS.values():
            for partida in CATALOGO[original]["mano_de_obra"]:
                ManoDeObra.objects.get_or_create(
                    partida=partida,
                    defaults={"descripcion": partida, "precio": Decimal("1.00")})
            for matricula in CATALOGO[original]["materiales"]:
                Material.objects.get_or_create(
                    matricula=matricula,
                    defaults={"descripcion": matricula, "precio": Decimal("1.00")})

    def configurar(self):
        call_command("configurar_aereo_viento", verbosity=0)

    def actividad(self):
        return Actividad.objects.get(nombre=NOMBRE)

    def tipos(self):
        return list(self.actividad().tipos_trabajo
                    .values_list("tipo_trabajo__nombre", flat=True))

    def test_se_crea_con_varios_postes_y_sus_tipos_en_orden(self):
        self.configurar()
        self.assertTrue(self.actividad().varios_postes)
        self.assertEqual(self.tipos(), TIPOS)

    def test_el_poste_lleva_sus_materiales_y_partidas_en_orden(self):
        self.configurar()
        poste = TipoTrabajo.objects.get(nombre=POSTE)
        partidas = list(TipoTrabajoManoDeObra.objects
                        .filter(tipo_trabajo=poste).order_by("orden")
                        .values_list("mano_de_obra__partida", flat=True))
        self.assertEqual(partidas, list(CATALOGO_DEL_POSTE["mano_de_obra"]))
        materiales = set(TipoTrabajoMaterial.objects.filter(tipo_trabajo=poste)
                         .values_list("material__matricula", flat=True))
        self.assertEqual(materiales, {"5331596", "5331616", "1014213", "1014308"})
        inicial = TipoTrabajoManoDeObra.objects.get(
            tipo_trabajo=poste, mano_de_obra__partida="*094395").cantidad_inicial
        self.assertEqual(inicial, 1)

    def test_las_copias_llevan_el_catalogo_de_su_original(self):
        self.configurar()
        for copia, original in COPIAS.items():
            tipo = TipoTrabajo.objects.get(nombre=copia)
            partidas = list(TipoTrabajoManoDeObra.objects
                            .filter(tipo_trabajo=tipo).order_by("orden")
                            .values_list("mano_de_obra__partida", flat=True))
            self.assertEqual(partidas, list(CATALOGO[original]["mano_de_obra"]),
                             copia)
            materiales = set(TipoTrabajoMaterial.objects
                             .filter(tipo_trabajo=tipo)
                             .values_list("material__matricula", flat=True))
            self.assertEqual(materiales, set(CATALOGO[original]["materiales"]),
                             copia)

    def test_las_copias_son_tipos_aparte_y_los_compartidos_no(self):
        self.configurar()
        for original in COPIAS.values():
            self.assertFalse(ActividadTipoTrabajo.objects.filter(
                actividad=self.actividad(), tipo_trabajo__nombre=original
            ).exists(), original)
        for nombre in COMPARTIDOS:
            self.assertEqual(TipoTrabajo.objects.filter(nombre=nombre).count(), 1)

    def test_los_retiros_llevan_las_de_cabria_y_el_poste_de_fibra(self):
        self.configurar()
        retiros = TipoTrabajo.objects.get(nombre=RETIROS)
        partidas = list(TipoTrabajoManoDeObra.objects
                        .filter(tipo_trabajo=retiros)
                        .order_by("orden")
                        .values_list("mano_de_obra__partida", flat=True))
        self.assertEqual(partidas, PARTIDAS_DE_VIENTO)

    def test_el_poste_de_fibra_no_se_cuela_en_los_retiros_de_cabria(self):
        self.assertNotIn("*090468", PARTIDAS_DE_CABRIA)

    def test_correrlo_dos_veces_no_duplica_nada(self):
        self.configurar()
        self.configurar()
        self.assertEqual(Actividad.objects.filter(nombre=NOMBRE).count(), 1)
        self.assertEqual(TipoTrabajo.objects.filter(nombre=RETIROS).count(), 1)
        self.assertEqual(self.tipos(), TIPOS)

    def test_lo_armado_en_configuracion_sobrevive_y_los_retiros_van_al_final(self):
        self.configurar()
        tipo = TipoTrabajo.objects.create(nombre="Poste aereo viento")
        ActividadTipoTrabajo.objects.create(
            actividad=self.actividad(), tipo_trabajo=tipo)
        self.configurar()
        # Nace con orden 0, como el poste: queda con él, delante del resto.
        self.assertEqual(self.tipos(), ["Poste aereo viento", *TIPOS])

    def test_si_alguien_le_quito_los_retiros_vuelven(self):
        self.configurar()
        ActividadTipoTrabajo.objects.filter(
            actividad=self.actividad(), tipo_trabajo__nombre=RETIROS).delete()
        self.configurar()
        self.assertEqual(self.tipos(), TIPOS)

    def test_si_alguien_le_quito_los_varios_postes_se_los_devuelve(self):
        Actividad.objects.create(nombre=NOMBRE, varios_postes=False)
        self.configurar()
        self.assertTrue(self.actividad().varios_postes)


class AlumbradoVientoTests(BaseAPITestCase):
    """El alumbrado de subterráneo-viento se comporta igual que el de cabria."""

    def test_queda_con_el_catalogo_de_alumbrado_cabria(self):
        catalogo = CATALOGO["Alumbrado cabria"]
        for partida in catalogo["mano_de_obra"]:
            ManoDeObra.objects.create(partida=partida, descripcion=partida,
                                      precio=Decimal("1.00"))
        for matricula in catalogo["materiales"]:
            Material.objects.create(matricula=matricula, descripcion=matricula,
                                    precio=Decimal("1.00"))
        tipo = TipoTrabajo.objects.create(nombre="Alumbrado viento")
        # Lo viejo que no está en cabria se va.
        viejo = Material.objects.create(matricula="VIEJO", descripcion="viejo",
                                        precio=Decimal("1.00"))
        TipoTrabajoMaterial.objects.create(tipo_trabajo=tipo, material=viejo)
        call_command("configurar_tipos_viento", verbosity=0)
        partidas = list(TipoTrabajoManoDeObra.objects.filter(tipo_trabajo=tipo)
                        .order_by("orden")
                        .values_list("mano_de_obra__partida", flat=True))
        self.assertEqual(partidas, list(catalogo["mano_de_obra"]))
        materiales = set(TipoTrabajoMaterial.objects.filter(tipo_trabajo=tipo)
                         .values_list("material__matricula", flat=True))
        self.assertEqual(materiales, set(catalogo["materiales"]))


class IncluidoEnPosteVientoTests(BaseAPITestCase):
    """Cada poste PRFV instalado trae 100 de acarreo, 100 de arrastre y una
    cimentación. El 0.67 del provisional no es un poste instalado."""

    REGLAS = INCLUSIONES_CONSOLIDADO

    def consolidar(self, cantidades):
        partidas = {
            codigo: {"mo": ManoDeObra(partida=codigo, descripcion=codigo,
                                      precio=Decimal("1")),
                     "cantidad": Decimal(str(cantidad))}
            for codigo, cantidad in cantidades.items()}
        return consolidar_partidas(
            [("cambio de poste inaccesible aereo - viento", partidas)],
            self.REGLAS, lambda codigo: None)

    def test_un_poste_instalado_descuenta_lo_incluido(self):
        partidas, cambios = self.consolidar({
            "*090482": 1, "*090633": 150, "*090634": 80, "*094918": 1})
        self.assertEqual(cambios, 1)
        self.assertEqual(partidas["*090633"]["cobra"], 50)
        self.assertEqual(partidas["*090634"]["cobra"], 0)
        self.assertEqual(partidas["*094918"]["cobra"], 0)

    def test_el_provisional_no_cuenta_como_poste_instalado(self):
        partidas, cambios = self.consolidar({"*090482": "1.67", "*090633": 250})
        self.assertEqual(cambios, 1)
        self.assertEqual(partidas["*090633"]["cobra"], 150)
        # La instalación se cobra entera: 1 + 0.67.
        self.assertEqual(partidas["*090482"]["cobra"], Decimal("1.67"))

    def test_solo_provisional_no_descuenta_nada(self):
        partidas, cambios = self.consolidar({"*090482": "0.67", "*090633": 40})
        self.assertEqual(cambios, 0)
        self.assertEqual(partidas["*090633"]["cobra"], 40)
