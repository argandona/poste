"""
Las actividades de encargado y las de capataz no se cruzan.

El encargado ve solo las actividades marcadas como suyas (el reforzamiento de
poste) y el capataz solo las demás. Quien asigna o revisa las ve todas, y al
asignar pide las que le corresponden a quien recibe la obra.
"""
import io

from django.core.management import call_command

from ..models import Actividad, Rol, SST, SSTSuministro, Suministro, Usuario
from .base import BaseAPITestCase


class ActividadesDeEncargadoTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.rol_coordinador = Rol.objects.create(
            id_rol=Rol.COORDINADOR, descripcion="Coordinador")
        self.rol_encargado = Rol.objects.create(
            id_rol=Rol.ENCARGADO, descripcion="Encargado")
        self.coordinador = Usuario.objects.create(
            nombre="Coordinador Uno", rol=self.rol_coordinador,
            empresa=self.empresa, email="coordinador@tecsur.pe", clave="x")
        self.de_obra = Usuario.objects.create(
            nombre="Encargado de Obra", rol=self.rol_encargado,
            empresa=self.empresa, email="obra@encossa.com", clave="x")

        self.cabria = Actividad.objects.create(
            nombre="Cambio de poste inacc. cabria aereo")
        self.con_vereda = Actividad.objects.create(
            nombre="Reforzamiento de poste con vereda", de_encargado=True)

    def nombres(self, como, **params):
        self.auth(como)
        resp = self.client.get("/api/actividades/", params)
        self.assertEqual(resp.status_code, 200, resp.data)
        datos = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        return {a["nombre"] for a in datos}

    def sst(self, codigo="SST-0001"):
        sst = SST.objects.create(
            empresa=self.empresa, codigo=codigo, distrito="Miraflores")
        poste = Suministro.objects.create(numero_suministro=f"P-{codigo}")
        SSTSuministro.objects.create(sst=sst, suministro=poste)
        return sst

    # ── Quién ve qué ─────────────────────────────────────────────────────────

    def test_el_encargado_solo_ve_las_suyas(self):
        self.assertEqual(self.nombres(self.de_obra), {self.con_vereda.nombre})

    def test_el_capataz_no_ve_las_de_encargado(self):
        self.assertEqual(self.nombres(self.capataz), {self.cabria.nombre})

    def test_el_coordinador_ve_todas(self):
        self.assertEqual(self.nombres(self.coordinador),
                         {self.cabria.nombre, self.con_vereda.nombre})

    def test_quien_es_capataz_y_encargado_ve_las_dos(self):
        self.capataz.rol_secundario = self.rol_encargado
        self.capataz.save()
        self.assertEqual(self.nombres(self.capataz),
                         {self.cabria.nombre, self.con_vereda.nombre})

    def test_el_coordinador_pide_las_de_quien_recibe(self):
        self.assertEqual(
            self.nombres(self.coordinador, para_usuario=self.de_obra.pk),
            {self.con_vereda.nombre})
        self.assertEqual(
            self.nombres(self.coordinador, para_usuario=self.capataz.pk),
            {self.cabria.nombre})

    def test_un_capataz_no_puede_mirar_las_de_otro(self):
        # para_usuario es cosa de quien asigna: el capataz sigue viendo lo suyo.
        self.assertEqual(
            self.nombres(self.capataz, para_usuario=self.de_obra.pk),
            {self.cabria.nombre})

    # ── Elegirla al liquidar ─────────────────────────────────────────────────

    def test_el_encargado_pone_la_suya(self):
        self.sst()
        self.auth(self.de_obra)
        resp = self.client.post("/api/ssts/set_actividad/", {
            "sst_codigo": "SST-0001", "actividad": self.con_vereda.pk},
            format="json")
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_el_encargado_no_puede_poner_una_de_capataz(self):
        sst = self.sst()
        self.auth(self.de_obra)
        resp = self.client.post("/api/ssts/set_actividad/", {
            "sst_codigo": "SST-0001", "actividad": self.cabria.pk},
            format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIsInstance(resp.data["detail"], str)
        sst.refresh_from_db()
        self.assertIsNone(sst.actividad_id)

    def test_el_capataz_no_puede_poner_una_de_encargado(self):
        self.sst()
        self.auth(self.capataz)
        resp = self.client.post("/api/ssts/set_actividad/", {
            "sst_codigo": "SST-0001", "actividad": self.con_vereda.pk},
            format="json")
        self.assertEqual(resp.status_code, 400)

    # ── Asignar ──────────────────────────────────────────────────────────────

    def asignar(self, usuario, actividad, codigo="SST-0002"):
        self.auth(self.coordinador)
        return self.client.post("/api/ssts/asignar_manual/", {
            "sst_codigo": codigo, "numero_suministro": f"P-{codigo}",
            "usuario": usuario.pk, "actividad": actividad.pk}, format="json")

    def test_se_le_asigna_obra_a_un_encargado(self):
        resp = self.asignar(self.de_obra, self.con_vereda)
        self.assertEqual(resp.status_code, 200, resp.data)
        sst = SST.objects.get(codigo="SST-0002")
        self.assertEqual(sst.actividad_id, self.con_vereda.pk)
        self.assertTrue(sst.sst_encargados.filter(usuario=self.de_obra).exists())

    def test_no_se_le_asigna_al_encargado_una_de_capataz(self):
        resp = self.asignar(self.de_obra, self.cabria)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(SST.objects.filter(codigo="SST-0002").exists())

    def test_no_se_le_asigna_al_capataz_una_de_encargado(self):
        resp = self.asignar(self.capataz, self.con_vereda)
        self.assertEqual(resp.status_code, 400)

    def test_no_se_asigna_obra_a_quien_no_la_ejecuta(self):
        resp = self.asignar(self.encargado, self.cabria)  # encargado de almacén
        self.assertEqual(resp.status_code, 400)

    def test_asignar_una_sst_ya_armada_respeta_su_actividad(self):
        sst = self.sst("SST-0003")
        sst.actividad = self.cabria
        sst.save()
        self.auth(self.coordinador)
        resp = self.client.post(f"/api/ssts/{sst.pk}/asignar/",
                                {"usuario": self.de_obra.pk}, format="json")
        self.assertEqual(resp.status_code, 400)

    # ── El comando ───────────────────────────────────────────────────────────

    def test_el_comando_crea_las_dos_de_encargado(self):
        call_command("configurar_reforzamiento", stdout=io.StringIO())
        for nombre in ("Reforzamiento de poste con vereda",
                       "Reforzamiento de poste sin vereda / piso especial"):
            self.assertTrue(
                Actividad.objects.get(nombre=nombre).de_encargado, nombre)

    def test_el_comando_se_puede_repetir(self):
        call_command("configurar_reforzamiento", stdout=io.StringIO())
        call_command("configurar_reforzamiento", stdout=io.StringIO())
        self.assertEqual(Actividad.objects.filter(
            nombre__startswith="Reforzamiento de poste").count(), 2)
