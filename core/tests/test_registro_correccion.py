"""
El registro de las correcciones de una liquidación.

Corregir un poste borra la liquidación anterior y crea otra: es lo que se
quiere (corregir no es acumular), pero hasta ahora la versión vieja no quedaba
en ningún lado. Aquí se prueba que cada corrección deje su acta: quién la hizo,
cuándo, qué decía antes y qué cambió.
"""
from datetime import date

from django.contrib.auth.models import User
from django.test import override_settings

from ..models import (
    Actividad, ActividadTipoTrabajo, CorreccionLiquidacion, ManoDeObra,
    Rol, SST, SSTSuministro, StockCamion, Suministro, TipoTrabajo, Usuario,
)
from .base import BaseAPITestCase

ACTIVIDAD = "Cambio de poste inacc. cabria aereo"


class RegistroCorreccionTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.actividad = Actividad.objects.create(nombre=ACTIVIDAD)
        self.sst = SST.objects.create(
            sst="55555", codigo="SST-55555", empresa=self.empresa,
            distrito="LIMA", fecha_ejecucion=date.today())
        self.poste = Suministro.objects.create(
            numero_suministro="900000555", distrito="LIMA")
        SSTSuministro.objects.create(sst=self.sst, suministro=self.poste)

        self.tipo = TipoTrabajo.objects.create(nombre="Mensula simple")
        self.otro_tipo = TipoTrabajo.objects.create(nombre="Ferreteria")
        for tipo in (self.tipo, self.otro_tipo):
            ActividadTipoTrabajo.objects.create(
                actividad=self.actividad, tipo_trabajo=tipo)

        self.partida = ManoDeObra.objects.create(
            partida="*090191", descripcion="COLOCACION DE MENSULA",
            precio="53.70")
        self.partida_b = ManoDeObra.objects.create(
            partida="*091316", descripcion="RETIRO DE LUMINARIA",
            precio="21.40")

        StockCamion.objects.create(
            camion=self.camion, material=self.material_a, cantidad=20)
        StockCamion.objects.create(
            camion=self.camion, material=self.material_b, cantidad=20)

        # El acta la lee el Coordinador; los demás ni la piden.
        self.rol_coordinador = Rol.objects.create(
            id_rol=Rol.COORDINADOR, descripcion="Coordinador")
        self.coordinador = Usuario.objects.create(
            nombre="Coordinador Uno", rol=self.rol_coordinador,
            empresa=self.empresa, email="coordinador@tecsur.pe", clave="x")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def liquidar(self, partidas=None, materiales=None, observacion="",
                 tipo=None, como=None):
        """Graba una liquidación del poste. Repetirla es corregirla."""
        self.auth(como or self.capataz)
        cuerpo = {
            "suministro":   self.poste.pk,
            "sst_externo":  self.sst.codigo,
            "usuario":      self.capataz.pk,
            "tipo_trabajo": (tipo or self.tipo).pk,
            "observacion":  observacion,
            "partidas": partidas if partidas is not None else [
                {"mano_de_obra": self.partida.pk, "cantidad": 1}],
        }
        if materiales is not None:
            cuerpo["materiales"] = materiales
        r = self.client.post("/api/liquidaciones/", cuerpo, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def correcciones(self, consulta="", como=None):
        self.auth(como or self.coordinador)
        r = self.client.get(f"/api/liquidaciones/correcciones/{consulta}")
        self.assertEqual(r.status_code, 200)
        return r.data

    # ── Cuándo hay acta y cuándo no ──────────────────────────────────────────

    def test_la_primera_liquidacion_no_deja_acta(self):
        self.liquidar()
        self.assertEqual(self.correcciones(), [])

    def test_corregir_deja_un_acta(self):
        self.liquidar()
        self.liquidar(partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 2}])
        self.assertEqual(len(self.correcciones()), 1)

    def test_cada_correccion_deja_la_suya(self):
        self.liquidar()
        self.liquidar(partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 2}])
        self.liquidar(partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 3}])
        actas = self.correcciones()
        self.assertEqual(len(actas), 2)
        # La más nueva primero: es la que se mira.
        self.assertIn("de 2 a 3", actas[0]["cambios"])
        self.assertIn("de 1 a 2", actas[1]["cambios"])

    # ── Quién y cuándo ───────────────────────────────────────────────────────

    def test_el_acta_dice_quien_liquido_y_quien_corrigio(self):
        self.liquidar()
        self.liquidar(partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 2}],
                      como=self.encargado)
        acta = self.correcciones()[0]
        self.assertEqual(acta["usuario_anterior_nombre"], "Capataz Uno")
        self.assertEqual(acta["usuario_nombre"], "Encargado Almacén")

    def test_firma_quien_tiene_la_sesion_no_lo_que_venga_en_el_cuerpo(self):
        """El cuerpo siempre manda al capataz (es su material); el acta no."""
        self.liquidar()
        self.liquidar(partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 2}],
                      como=self.encargado)
        self.assertEqual(self.correcciones()[0]["usuario"], self.encargado.pk)

    def test_el_acta_dice_cuando(self):
        self.liquidar()
        self.liquidar(partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 2}])
        acta = self.correcciones()[0]
        self.assertTrue(acta["fecha"].startswith(date.today().isoformat()))
        self.assertEqual(acta["fecha_anterior"], date.today().isoformat())

    # ── Qué cambió ───────────────────────────────────────────────────────────

    def test_dice_que_partida_cambio_de_cuanto_a_cuanto(self):
        self.liquidar()
        self.liquidar(partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 2}])
        self.assertIn("Mano de obra: *090191 de 1 a 2.",
                      self.correcciones()[0]["cambios"])

    def test_dice_la_partida_que_se_agrego_y_la_que_se_quito(self):
        self.liquidar()
        self.liquidar(partidas=[{"mano_de_obra": self.partida_b.pk, "cantidad": 4}])
        cambios = self.correcciones()[0]["cambios"]
        self.assertIn("quitó *090191 (1)", cambios)
        self.assertIn("agregó *091316 (4)", cambios)

    def test_dice_que_material_cambio(self):
        self.liquidar(materiales=[{"material": self.material_a.pk, "cantidad": 3}])
        self.liquidar(materiales=[{"material": self.material_a.pk, "cantidad": 1}])
        self.assertIn("Material: MAT-A de 3 a 1.",
                      self.correcciones()[0]["cambios"])

    def test_dice_el_material_que_se_agrego(self):
        self.liquidar(materiales=[{"material": self.material_a.pk, "cantidad": 2}])
        self.liquidar(materiales=[
            {"material": self.material_a.pk, "cantidad": 2},
            {"material": self.material_b.pk, "cantidad": 5}])
        self.assertIn("agregó MAT-B (5)", self.correcciones()[0]["cambios"])

    def test_dice_si_cambio_la_observacion(self):
        self.liquidar(observacion="poste en esquina")
        self.liquidar(observacion="poste en esquina, vereda rota")
        self.assertIn("Cambió la observación.",
                      self.correcciones()[0]["cambios"])

    def test_volver_a_grabar_lo_mismo_lo_dice(self):
        self.liquidar(materiales=[{"material": self.material_a.pk, "cantidad": 2}])
        self.liquidar(materiales=[{"material": self.material_a.pk, "cantidad": 2}])
        self.assertEqual(self.correcciones()[0]["cambios"],
                         "Se volvió a grabar sin cambios.")

    # ── Lo que decía antes ───────────────────────────────────────────────────

    def test_el_acta_guarda_la_version_anterior_entera(self):
        self.liquidar(partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 2}],
                      materiales=[{"material": self.material_a.pk, "cantidad": 3}],
                      observacion="lo que decía antes")
        self.liquidar(partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 1}])
        anterior = self.correcciones()[0]["anterior"]
        self.assertEqual(anterior["usuario"], "Capataz Uno")
        self.assertEqual(anterior["observacion"], "lo que decía antes")
        self.assertEqual(anterior["partidas"], [{
            "partida": "*090191",
            "descripcion": "COLOCACION DE MENSULA",
            "cantidad": "2",
        }])
        self.assertEqual(anterior["materiales"], [{
            "matricula": "MAT-A",
            "descripcion": "Cable A",
            "cantidad": "3",
        }])

    def test_la_version_anterior_sobrevive_aunque_ya_no_exista_la_liquidacion(self):
        self.liquidar(partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 7}])
        self.liquidar()
        acta = CorreccionLiquidacion.objects.get()
        self.assertFalse(
            self.poste.liquidaciones.filter(
                pk=acta.anterior["id_liquidacion"]).exists())
        self.assertEqual(acta.anterior["partidas"][0]["cantidad"], "7")

    # ── Cómo se consulta ─────────────────────────────────────────────────────

    def test_se_filtra_por_poste(self):
        self.liquidar()
        self.liquidar(partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 2}])
        self.assertEqual(
            len(self.correcciones(f"?suministro={self.poste.pk}")), 1)
        otro = Suministro.objects.create(
            numero_suministro="900000556", distrito="LIMA")
        self.assertEqual(len(self.correcciones(f"?suministro={otro.pk}")), 0)

    def test_se_filtra_por_tipo_de_trabajo(self):
        self.liquidar()
        self.liquidar(partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 2}])
        self.liquidar(tipo=self.otro_tipo)
        self.liquidar(tipo=self.otro_tipo,
                      partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 5}])
        self.assertEqual(len(self.correcciones()), 2)
        self.assertEqual(
            len(self.correcciones(f"?tipo_trabajo={self.otro_tipo.pk}")), 1)

    def test_el_poste_externo_guarda_su_numero_y_su_sst(self):
        self.auth(self.capataz)
        for cantidad in (1, 2):
            r = self.client.post("/api/liquidaciones/", {
                "suministro_externo": "800000222",
                "sst_externo":        self.sst.codigo,
                "usuario":            self.capataz.pk,
                "tipo_trabajo":       self.tipo.pk,
                "partidas": [{"mano_de_obra": self.partida.pk,
                              "cantidad": cantidad}],
            }, format="json")
            self.assertEqual(r.status_code, 201, r.data)
        acta = self.correcciones(
            f"?suministro_externo=800000222&sst={self.sst.codigo}")[0]
        self.assertEqual(acta["numero_suministro"], "800000222")
        self.assertEqual(acta["sst_externo"], self.sst.codigo)
        self.assertEqual(acta["tipo_trabajo_nombre"], "Mensula simple")

    def test_hay_que_estar_autenticado(self):
        self.client.credentials()
        r = self.client.get("/api/liquidaciones/correcciones/")
        self.assertIn(r.status_code, (401, 403))

    def test_solo_el_coordinador_las_lee(self):
        """El capataz no tiene por qué ver quién le corrigió la liquidación."""
        self.liquidar()
        self.liquidar(partidas=[{"mano_de_obra": self.partida.pk, "cantidad": 2}])
        for usuario in (self.capataz, self.encargado):
            self.auth(usuario)
            r = self.client.get("/api/liquidaciones/correcciones/")
            self.assertEqual(r.status_code, 403, usuario.nombre)
        self.assertEqual(len(self.correcciones()), 1)


# En producción WhiteNoise sirve los estáticos con manifiesto, que solo existe
# después de collectstatic. Aquí se dibujan páginas del admin, así que se usa
# el almacenamiento simple.
@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class ActaEnElAdminTests(BaseAPITestCase):
    """El acta se mira por la web, y solo la mira el Coordinador.

    Las cuentas del admin de Django son propias, aparte de la tabla Usuario:
    lo que las une es el correo."""

    def setUp(self):
        super().setUp()
        Rol.objects.create(id_rol=Rol.COORDINADOR, descripcion="Coordinador")
        Usuario.objects.create(
            nombre="Coordinador Uno", rol_id=Rol.COORDINADOR,
            empresa=self.empresa, email="coordinador@tecsur.pe", clave="x")

    LISTA = "/admin/core/correccionliquidacion/"

    def entrar(self, correo, superusuario=False):
        User.objects.create_user(
            username=correo.split("@")[0], email=correo,
            password="clave-de-prueba", is_staff=True,
            is_superuser=superusuario)
        self.client.credentials()
        self.assertTrue(self.client.login(
            username=correo.split("@")[0], password="clave-de-prueba"))

    def test_el_coordinador_ve_la_lista(self):
        self.entrar("coordinador@tecsur.pe")
        self.assertEqual(self.client.get(self.LISTA).status_code, 200)

    def test_el_capataz_no_la_ve(self):
        self.entrar("capataz@tecsur.pe")
        self.assertEqual(self.client.get(self.LISTA).status_code, 403)

    def test_una_cuenta_suelta_del_admin_tampoco_la_ve(self):
        """Ser del admin no alcanza: hay que ser Coordinador en el sistema."""
        self.entrar("alguien@otraparte.pe")
        self.assertEqual(self.client.get(self.LISTA).status_code, 403)

    def test_el_superusuario_la_ve(self):
        self.entrar("root@tecsur.pe", superusuario=True)
        self.assertEqual(self.client.get(self.LISTA).status_code, 200)

    def test_nadie_la_crea_desde_la_web(self):
        self.entrar("coordinador@tecsur.pe")
        self.assertEqual(
            self.client.get(f"{self.LISTA}add/").status_code, 403)
