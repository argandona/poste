"""
Actividad de cabria aérea con sus siete tipos de trabajo.

Lo que importa aquí, además de que se creen, es que el comando NO toque el
catálogo de cada tipo: eso se arma desde la pantalla de Configuración y un
despliegue no puede borrarlo.
"""
from django.core.management import call_command

from ..models import (
    Actividad, ActividadTipoTrabajo, ManoDeObra, Material, Rol, TipoTrabajo,
    TipoTrabajoManoDeObra, TipoTrabajoMaterial,
)
from ..management.commands.configurar_cabria import (
    ACTIVIDAD, CATALOGO, TIPOS,
)
from .base import BaseAPITestCase


class ConfigurarCabriaTests(BaseAPITestCase):

    def test_crea_la_actividad_con_todos_sus_tipos(self):
        call_command("configurar_cabria", verbosity=0)
        actividad = Actividad.objects.get(nombre=ACTIVIDAD)
        ligados = ActividadTipoTrabajo.objects.filter(actividad=actividad)
        self.assertEqual(ligados.count(), len(TIPOS))
        self.assertEqual(
            sorted(l.tipo_trabajo.nombre for l in ligados), sorted(TIPOS))

    def test_correrlo_dos_veces_no_duplica_nada(self):
        call_command("configurar_cabria", verbosity=0)
        call_command("configurar_cabria", verbosity=0)
        self.assertEqual(Actividad.objects.filter(nombre=ACTIVIDAD).count(), 1)
        for nombre in TIPOS:
            self.assertEqual(TipoTrabajo.objects.filter(nombre=nombre).count(), 1)

    def test_mensula_simple_trae_sus_cantidades_iniciales(self):
        # Lo que se propone al elegir el tipo de trabajo, para no escribir
        # siempre lo mismo.
        self._catalogo_completo()
        call_command("configurar_cabria", verbosity=0)
        tipo = TipoTrabajo.objects.get(nombre="Mensula simple")
        por_matricula = {
            m.material.matricula: m.cantidad_inicial
            for m in tipo.materiales.select_related("material")}
        self.assertEqual(por_matricula["5461238"], 8)
        self.assertEqual(por_matricula["5335110"], 1)
        self.assertEqual(por_matricula["5463118"], 3)
        por_partida = {
            p.mano_de_obra.partida: p.cantidad_inicial
            for p in tipo.partidas.select_related("mano_de_obra")}
        self.assertEqual(por_partida["*090191"], 1)

    def test_mensula_doble_lleva_el_doble_de_mensulas(self):
        self._catalogo_completo()
        call_command("configurar_cabria", verbosity=0)
        tipo = TipoTrabajo.objects.get(nombre="Mensula doble")
        por_matricula = {
            m.material.matricula: m.cantidad_inicial
            for m in tipo.materiales.select_related("material")}
        self.assertEqual(por_matricula["5335110"], 2)
        self.assertEqual(por_matricula["5461238"], 14)

    def test_otros_cabria_es_solo_mano_de_obra(self):
        self._catalogo_completo()
        call_command("configurar_cabria", verbosity=0)
        tipo = TipoTrabajo.objects.get(nombre="Otros cabria")
        self.assertEqual(tipo.materiales.count(), 0)
        # La hora de operario, el traslado de cables de comunicación y los
        # retiros que la app llena con lo recuperado.
        self.assertEqual(
            sorted(p.mano_de_obra.partida for p in tipo.partidas.all()),
            sorted(["*010101", "*010213",
                    "*090139", "*090138", "*091411", "*091448", "*090491",
                    "*090497", "*093241", "*093044", "*090189", "*098669",
                    "*090061", "*090064", "*090391", "*090395", "*090319"]))

    def test_conexiones_cabria_queda_con_su_catalogo(self):
        self._catalogo_completo()
        call_command("configurar_cabria", verbosity=0)
        tipo = TipoTrabajo.objects.get(nombre="Conexiones cabria")
        self.assertEqual(tipo.materiales.count(), 14)
        self.assertEqual(
            sorted(p.mano_de_obra.partida for p in tipo.partidas.all()),
            ["*093043", "*093045", "*093081", "*093242", "*093247"])

    def test_el_traslado_de_corona_se_crea_con_su_precio(self):
        call_command("configurar_cabria", verbosity=0)
        partida = ManoDeObra.objects.get(partida="*093043")
        self.assertEqual(str(partida.precio), "58.45")
        self.assertIn("CORONA", partida.descripcion)

    def test_la_hora_de_operario_queda_al_precio_pactado(self):
        # El catálogo la traía a otro precio y de ahí sale el traslado de
        # cable delgado, así que el comando la corrige.
        ManoDeObra.objects.create(
            partida="*010101", descripcion="HORA DE OPERARIO", precio="18.79")
        call_command("configurar_cabria", verbosity=0)
        partida = ManoDeObra.objects.get(partida="*010101")
        self.assertEqual(str(partida.precio), "19.73")

    def test_correr_dos_veces_deja_el_mismo_precio(self):
        call_command("configurar_cabria", verbosity=0)
        call_command("configurar_cabria", verbosity=0)
        self.assertEqual(
            str(ManoDeObra.objects.get(partida="*010101").precio), "19.73")

    def test_avisa_de_lo_que_falta_en_el_catalogo(self):
        # Sin materiales en la base, el comando no revienta: los omite.
        call_command("configurar_cabria", verbosity=0)
        tipo = TipoTrabajo.objects.get(nombre="Mensula simple")
        self.assertEqual(tipo.materiales.count(), 0)

    def _catalogo_completo(self):
        """Deja en la base los materiales y partidas que el comando espera."""
        for config in CATALOGO.values():
            for matricula in config["materiales"]:
                Material.objects.get_or_create(
                    matricula=matricula,
                    defaults={"descripcion": matricula, "precio": "1.00"})
            for partida in config["mano_de_obra"]:
                ManoDeObra.objects.get_or_create(
                    partida=partida,
                    defaults={"descripcion": partida, "precio": "1.00"})

    def test_no_borra_lo_que_se_configuro_en_la_app(self):
        # Un despliegue no puede llevarse por delante el catálogo que el
        # Coordinador acaba de cargar.
        call_command("configurar_cabria", verbosity=0)
        # Un tipo que el comando no define: lo agregó el Coordinador a mano.
        actividad = Actividad.objects.get(nombre=ACTIVIDAD)
        tipo = TipoTrabajo.objects.create(nombre="Tipo hecho en la app")
        ActividadTipoTrabajo.objects.create(
            actividad=actividad, tipo_trabajo=tipo)
        # La hora de operario ya la dejó la corrida anterior.
        partida = ManoDeObra.objects.get(partida="*010101")
        TipoTrabajoManoDeObra.objects.create(
            tipo_trabajo=tipo, mano_de_obra=partida)
        TipoTrabajoMaterial.objects.create(
            tipo_trabajo=tipo, material=self.material_a)

        call_command("configurar_cabria", verbosity=0)

        self.assertEqual(tipo.partidas.count(), 1)
        self.assertEqual(tipo.materiales.count(), 1)

    # Los que nacerían vacíos a propósito, para que el coordinador los arme
    # desde la pantalla de Configuración. Hoy todos tienen catálogo.
    SIN_CATALOGO = set()

    def test_todos_los_tipos_tienen_su_catalogo_definido(self):
        # Si alguno se queda fuera sin querer, nace vacío y nadie se entera.
        self.assertEqual(sorted(CATALOGO),
                         sorted(set(TIPOS) - self.SIN_CATALOGO))

    def test_la_app_los_ve_por_actividad(self):
        call_command("configurar_cabria", verbosity=0)
        actividad = Actividad.objects.get(nombre=ACTIVIDAD)
        Rol.objects.get_or_create(
            id_rol=Rol.COORDINADOR, defaults={"descripcion": "Coordinador"})
        self.auth(self.capataz)
        r = self.client.get("/api/tipos-trabajo/", {"actividad": actividad.pk})
        self.assertEqual(r.status_code, 200)
        datos = r.data["results"] if isinstance(r.data, dict) else r.data
        self.assertEqual(len(datos), len(TIPOS))

    def test_no_se_mezcla_con_las_otras_actividades(self):
        call_command("configurar_cabria", verbosity=0)
        otra = Actividad.objects.create(nombre="Otra actividad")
        self.assertEqual(
            ActividadTipoTrabajo.objects.filter(actividad=otra).count(), 0)
        # Y los materiales del escenario siguen intactos.
        self.assertTrue(Material.objects.filter(pk=self.material_a.pk).exists())
