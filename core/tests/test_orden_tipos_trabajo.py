"""
En qué orden ve el capataz los tipos de trabajo de una actividad.

El orden es el de la obra, no el del abecedario: se empieza por el poste y se
termina por lo suelto. Lo define el comando que configura la actividad.
"""
from django.core.management import call_command

from ..models import Actividad, ActividadTipoTrabajo, TipoTrabajo
from .base import BaseAPITestCase

ACTIVIDAD = "Cambio de poste inacc. cabria aereo"

ESPERADO = [
    "Poste cabria",
    "Alumbrado cabria",
    "Ferreteria",
    "Conexiones cabria",
    "Retenida simple",
    "Retenida Violin",
    "Mensula simple",
    "Mensula doble",
    'Retenida Tipo "Y"',
    "Otros cabria",
]


class OrdenTiposTrabajoTests(BaseAPITestCase):

    def nombres_del_api(self, actividad):
        self.auth(self.capataz)
        r = self.client.get("/api/tipos-trabajo/?actividad=%s" % actividad.pk)
        self.assertEqual(r.status_code, 200)
        datos = r.data.get("results", r.data)
        return [t["nombre"] for t in datos]

    def test_salen_en_el_orden_de_obra(self):
        call_command("configurar_cabria", verbosity=0)
        actividad = Actividad.objects.get(nombre=ACTIVIDAD)
        self.assertEqual(self.nombres_del_api(actividad), ESPERADO)

    def test_el_orden_no_es_el_alfabetico(self):
        # Si alguien quita el orden, la lista vuelve al abecedario y esto lo
        # delata: "Alumbrado cabria" quedaría antes que "Poste cabria".
        call_command("configurar_cabria", verbosity=0)
        actividad = Actividad.objects.get(nombre=ACTIVIDAD)
        nombres = self.nombres_del_api(actividad)
        self.assertNotEqual(nombres, sorted(nombres))

    def test_correr_el_comando_dos_veces_no_altera_el_orden(self):
        call_command("configurar_cabria", verbosity=0)
        call_command("configurar_cabria", verbosity=0)
        actividad = Actividad.objects.get(nombre=ACTIVIDAD)
        self.assertEqual(self.nombres_del_api(actividad), ESPERADO)

    def test_la_retenida_en_y_se_crea_vacia(self):
        # Se crea para que el coordinador la arme desde Configuración; el
        # comando no le inventa materiales ni partidas.
        call_command("configurar_cabria", verbosity=0)
        tipo = TipoTrabajo.objects.get(nombre='Retenida Tipo "Y"')
        self.assertEqual(tipo.materiales.count(), 0)
        self.assertEqual(tipo.partidas.count(), 0)

    def test_un_tipo_agregado_a_mano_no_se_pierde(self):
        call_command("configurar_cabria", verbosity=0)
        actividad = Actividad.objects.get(nombre=ACTIVIDAD)
        suelto = TipoTrabajo.objects.create(nombre="Tipo hecho en la app")
        ActividadTipoTrabajo.objects.create(
            actividad=actividad, tipo_trabajo=suelto)

        call_command("configurar_cabria", verbosity=0)

        nombres = self.nombres_del_api(actividad)
        self.assertIn("Tipo hecho en la app", nombres)
        # Sin orden asignado va primero; lo importante es que siga estando.
        self.assertEqual(len(nombres), len(ESPERADO) + 1)
