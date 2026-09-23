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

    def test_el_arrastre_va_antes_que_el_acarreo(self):
        """El acarreo se calcula desde el arrastre, así que leerlo después
        es el orden de la obra. Lo pidió el usuario el 2026-09-22."""
        self._catalogo_completo()
        call_command("configurar_cabria", verbosity=0)
        tipo = TipoTrabajo.objects.get(nombre="Poste cabria")
        orden = [p.mano_de_obra.partida for p in tipo.partidas.all()]
        self.assertLess(orden.index("*090632"), orden.index("*090633"))
        self.assertLess(orden.index("*090632"), orden.index("*090634"))
        self.assertLess(orden.index("*090630"), orden.index("*090633"))
        self.assertLess(orden.index("*090630"), orden.index("*090634"))

    def test_el_orden_del_catalogo_es_el_que_ve_el_capataz(self):
        """No basta con escribirlas en orden: sin el campo, la lista salía en
        el orden en que se crearon las filas."""
        self._catalogo_completo()
        call_command("configurar_cabria", verbosity=0)
        tipo = TipoTrabajo.objects.get(nombre="Poste cabria")
        ordenes = [p.orden for p in tipo.partidas.all()]
        self.assertEqual(ordenes, sorted(ordenes))
        self.assertEqual(len(set(ordenes)), len(ordenes))

    def test_reordenar_el_catalogo_reordena_lo_que_se_ve(self):
        self._catalogo_completo()
        call_command("configurar_cabria", verbosity=0)
        tipo = TipoTrabajo.objects.get(nombre="Poste cabria")
        primera = tipo.partidas.first()
        # Se la manda al final a mano y el comando la devuelve a su sitio.
        primera.orden = 999
        primera.save(update_fields=["orden"])
        call_command("configurar_cabria", verbosity=0)
        self.assertEqual(tipo.partidas.first().pk, primera.pk)

    def test_retiros_otros_cabria_es_solo_mano_de_obra(self):
        self._catalogo_completo()
        call_command("configurar_cabria", verbosity=0)
        tipo = TipoTrabajo.objects.get(nombre="Retiros - otros - cabria")
        self.assertEqual(tipo.materiales.count(), 0)
        # La hora de operario, el traslado de cables de comunicación y los
        # retiros que la app llena con lo recuperado.
        self.assertEqual(
            sorted(p.mano_de_obra.partida for p in tipo.partidas.all()),
            sorted(["*010101", "*010213",
                    "*090137", "*090139", "*090138", "*091411", "*091448",
                    "*090491",
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
        self.assertEqual(str(partida.precio), "10.32")
        self.assertIn("CORONA", partida.descripcion)

    def test_la_hora_de_operario_queda_al_precio_pactado(self):
        # El catálogo la traía a otro precio y de ahí sale el traslado de
        # cable delgado, así que el comando la corrige.
        ManoDeObra.objects.create(
            partida="*010101", descripcion="HORA DE OPERARIO", precio="18.79")
        call_command("configurar_cabria", verbosity=0)
        partida = ManoDeObra.objects.get(partida="*010101")
        self.assertEqual(str(partida.precio), "19.73")

    def test_el_traslado_de_cables_de_comunicacion_queda_a_210_04(self):
        # En el catálogo venía como hora de cuadrilla con grúa a 201.04.
        ManoDeObra.objects.create(
            partida="*010213", precio="201.04",
            descripcion="HORA DE CUADRILLA DE MANTENIMIENTO CON GRUA DE 9 TN")
        call_command("configurar_cabria", verbosity=0)
        self.assertEqual(
            str(ManoDeObra.objects.get(partida="*010213").precio), "210.04")

    def test_el_traslado_de_corona_se_corrige_con_el_del_excel(self):
        # Se había creado a 58.45, copiando el traslado de caja.
        ManoDeObra.objects.create(
            partida="*093043", precio="58.45",
            descripcion="TRASLADO DE CORONA 4 GANCHOS PARA ACOMETIDA "
                        "DOMICILIARIA")
        call_command("configurar_cabria", verbosity=0)
        partida = ManoDeObra.objects.get(partida="*093043")
        self.assertEqual(str(partida.precio), "10.32")
        self.assertEqual(partida.descripcion,
                         "TRASLADO DE ABRAZADERA TIPO CORONA CON GANCHOS")

    def test_los_materiales_que_faltan_nacen_a_uno(self):
        call_command("configurar_cabria", verbosity=0)
        self.assertEqual(
            str(Material.objects.get(matricula="5347095").precio), "1.00")

    def test_un_material_que_quedo_en_cero_pasa_a_uno(self):
        Material.objects.create(
            matricula="5347095", descripcion="PASTORAL JP", precio=0)
        call_command("configurar_cabria", verbosity=0)
        self.assertEqual(
            str(Material.objects.get(matricula="5347095").precio), "1.00")

    def test_no_pisa_el_precio_real_de_un_material_ya_cargado(self):
        Material.objects.create(
            matricula="5347095", descripcion="PASTORAL JP", precio="87.50")
        call_command("configurar_cabria", verbosity=0)
        self.assertEqual(
            str(Material.objects.get(matricula="5347095").precio), "87.50")

    def test_la_rotura_de_vereda_queda_al_precio_del_excel(self):
        # El catálogo la traía a 119.73, casi lo mismo que repararla.
        ManoDeObra.objects.create(
            partida="*091840", precio="119.73",
            descripcion="ROTURA DE VEREDA CUALQUIER ESPESOR S/MAQ.CORTADORA")
        call_command("configurar_cabria", verbosity=0)
        self.assertEqual(
            str(ManoDeObra.objects.get(partida="*091840").precio), "24.55")

    def test_la_descripcion_del_traslado_de_comunicacion_se_corrige(self):
        ManoDeObra.objects.create(
            partida="*010213", precio="201.04",
            descripcion="HORA DE CUADRILLA DE MANTENIMIENTO CON GRUA DE 9 TN")
        call_command("configurar_tipos_viento", verbosity=0)
        self.assertEqual(
            ManoDeObra.objects.get(partida="*010213").descripcion,
            "TRASLADO DE CABLES DE COMUNICACION")

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
