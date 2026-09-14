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
from ..management.commands.configurar_cabria import ACTIVIDAD, TIPOS
from .base import BaseAPITestCase


class ConfigurarCabriaTests(BaseAPITestCase):

    def test_crea_la_actividad_con_sus_siete_tipos(self):
        call_command("configurar_cabria", verbosity=0)
        actividad = Actividad.objects.get(nombre=ACTIVIDAD)
        ligados = ActividadTipoTrabajo.objects.filter(actividad=actividad)
        self.assertEqual(ligados.count(), 7)
        self.assertEqual(
            sorted(l.tipo_trabajo.nombre for l in ligados), sorted(TIPOS))

    def test_correrlo_dos_veces_no_duplica_nada(self):
        call_command("configurar_cabria", verbosity=0)
        call_command("configurar_cabria", verbosity=0)
        self.assertEqual(Actividad.objects.filter(nombre=ACTIVIDAD).count(), 1)
        for nombre in TIPOS:
            self.assertEqual(TipoTrabajo.objects.filter(nombre=nombre).count(), 1)

    def test_no_borra_lo_que_se_configuro_en_la_app(self):
        # Un despliegue no puede llevarse por delante el catálogo que el
        # Coordinador acaba de cargar.
        call_command("configurar_cabria", verbosity=0)
        tipo = TipoTrabajo.objects.get(nombre="Poste cabria")
        partida = ManoDeObra.objects.create(
            partida="*010101", descripcion="HORA DE OPERARIO", precio="18.79")
        TipoTrabajoManoDeObra.objects.create(
            tipo_trabajo=tipo, mano_de_obra=partida)
        TipoTrabajoMaterial.objects.create(
            tipo_trabajo=tipo, material=self.material_a)

        call_command("configurar_cabria", verbosity=0)

        self.assertEqual(tipo.partidas.count(), 1)
        self.assertEqual(tipo.materiales.count(), 1)

    def test_los_tipos_nacen_vacios(self):
        call_command("configurar_cabria", verbosity=0)
        for nombre in TIPOS:
            tipo = TipoTrabajo.objects.get(nombre=nombre)
            self.assertEqual(tipo.partidas.count(), 0)
            self.assertEqual(tipo.materiales.count(), 0)

    def test_la_app_los_ve_por_actividad(self):
        call_command("configurar_cabria", verbosity=0)
        actividad = Actividad.objects.get(nombre=ACTIVIDAD)
        Rol.objects.get_or_create(
            id_rol=Rol.COORDINADOR, defaults={"descripcion": "Coordinador"})
        self.auth(self.capataz)
        r = self.client.get("/api/tipos-trabajo/", {"actividad": actividad.pk})
        self.assertEqual(r.status_code, 200)
        datos = r.data["results"] if isinstance(r.data, dict) else r.data
        self.assertEqual(len(datos), 7)

    def test_no_se_mezcla_con_las_otras_actividades(self):
        call_command("configurar_cabria", verbosity=0)
        otra = Actividad.objects.create(nombre="Otra actividad")
        self.assertEqual(
            ActividadTipoTrabajo.objects.filter(actividad=otra).count(), 0)
        # Y los materiales del escenario siguen intactos.
        self.assertTrue(Material.objects.filter(pk=self.material_a.pk).exists())
