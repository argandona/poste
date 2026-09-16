"""
Quién pone la actividad de una SST y hasta cuándo se puede cambiar.

La actividad decide qué tipos de trabajo ve el capataz y qué descuenta el
consolidado. La pone el coordinador al asignar; si no la puso, la pone el
capataz al liquidar. Una vez que hay mano de obra liquidada ya no se cambia:
lo liquidado quedaría colgando de tipos de trabajo de otra actividad.
"""
from ..models import (
    Actividad, LiquidacionSuministro, Rol, SST, SSTSuministro, Suministro,
    TipoTrabajo, Usuario,
)
from .base import BaseAPITestCase


class ActividadDeLaSSTTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.rol_coordinador = Rol.objects.create(
            id_rol=Rol.COORDINADOR, descripcion="Coordinador")
        self.coordinador = Usuario.objects.create(
            nombre="Coordinador Uno", rol=self.rol_coordinador,
            empresa=self.empresa, email="coordinador@tecsur.pe", clave="x")

        self.cabria = Actividad.objects.create(
            nombre="Cambio de poste inacc. cabria aereo")
        self.viento = Actividad.objects.create(
            nombre="Cambio de poste inaccesible subterráneo-viento")
        self.tipo = TipoTrabajo.objects.create(nombre="Poste cabria")

    def sst_con_poste(self, codigo="SST-0001"):
        sst = SST.objects.create(
            empresa=self.empresa, codigo=codigo, distrito="Miraflores")
        poste = Suministro.objects.create(numero_suministro=f"P-{codigo}")
        SSTSuministro.objects.create(sst=sst, suministro=poste)
        return sst, poste

    def poner(self, codigo, actividad, como=None):
        self.auth(como or self.capataz)
        return self.client.post(
            "/api/ssts/set_actividad/",
            {"sst_codigo": codigo, "actividad": actividad.pk}, format="json")

    # ── Quién la pone ────────────────────────────────────────────────────────

    def test_el_coordinador_la_deja_puesta_al_asignar(self):
        self.auth(self.coordinador)
        resp = self.client.post("/api/ssts/asignar_manual/", {
            "sst_codigo": "SST-0002",
            "numero_suministro": "P-0002",
            "usuario": self.capataz.pk,
            "actividad": self.cabria.pk,
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        sst = SST.objects.get(codigo="SST-0002")
        self.assertEqual(sst.actividad_id, self.cabria.pk)

    def test_asignar_sin_actividad_sigue_funcionando(self):
        self.auth(self.coordinador)
        resp = self.client.post("/api/ssts/asignar_manual/", {
            "sst_codigo": "SST-0003",
            "numero_suministro": "P-0003",
            "usuario": self.capataz.pk,
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIsNone(SST.objects.get(codigo="SST-0003").actividad_id)

    def test_si_el_coordinador_no_la_puso_la_pone_el_capataz(self):
        sst, _ = self.sst_con_poste()
        resp = self.poner(sst.codigo, self.cabria)
        self.assertEqual(resp.status_code, 200, resp.data)
        sst.refresh_from_db()
        self.assertEqual(sst.actividad_id, self.cabria.pk)

    # ── Hasta cuándo se puede cambiar ────────────────────────────────────────

    def test_sin_liquidaciones_todavia_se_puede_corregir(self):
        sst, _ = self.sst_con_poste()
        self.poner(sst.codigo, self.cabria)
        resp = self.poner(sst.codigo, self.viento)
        self.assertEqual(resp.status_code, 200, resp.data)
        sst.refresh_from_db()
        self.assertEqual(sst.actividad_id, self.viento.pk)

    def test_con_liquidaciones_ya_no_se_cambia(self):
        sst, poste = self.sst_con_poste()
        self.poner(sst.codigo, self.cabria)
        LiquidacionSuministro.objects.create(
            suministro=poste, usuario=self.capataz, tipo_trabajo=self.tipo)

        resp = self.poner(sst.codigo, self.viento)

        self.assertEqual(resp.status_code, 400)
        self.assertIn("liquidaciones", resp.data["detail"])
        sst.refresh_from_db()
        self.assertEqual(sst.actividad_id, self.cabria.pk)

    def test_la_liquidacion_por_codigo_de_sst_tambien_cuenta(self):
        # Las liquidaciones del proyecto externo se guardan por código, sin
        # apuntar al suministro local.
        sst, _ = self.sst_con_poste()
        self.poner(sst.codigo, self.cabria)
        LiquidacionSuministro.objects.create(
            sst_externo=sst.codigo, suministro_externo="P-9",
            usuario=self.capataz, tipo_trabajo=self.tipo)

        self.assertEqual(self.poner(sst.codigo, self.viento).status_code, 400)

    def test_repetir_la_misma_actividad_no_molesta(self):
        # La app la reenvía cada vez que se abre la pantalla.
        sst, poste = self.sst_con_poste()
        self.poner(sst.codigo, self.cabria)
        LiquidacionSuministro.objects.create(
            suministro=poste, usuario=self.capataz, tipo_trabajo=self.tipo)

        resp = self.poner(sst.codigo, self.cabria)

        self.assertEqual(resp.status_code, 200, resp.data)

    def test_el_coordinador_tampoco_la_cambia_si_ya_se_liquido(self):
        sst, poste = self.sst_con_poste()
        self.poner(sst.codigo, self.cabria)
        LiquidacionSuministro.objects.create(
            suministro=poste, usuario=self.capataz, tipo_trabajo=self.tipo)

        self.auth(self.coordinador)
        resp = self.client.post("/api/ssts/asignar_manual/", {
            "sst_codigo": sst.codigo,
            "numero_suministro": "P-SST-0001",
            "usuario": self.capataz.pk,
            "actividad": self.viento.pk,
        }, format="json")

        self.assertEqual(resp.status_code, 400)
        sst.refresh_from_db()
        self.assertEqual(sst.actividad_id, self.cabria.pk)

    def test_una_sst_que_no_existe_avisa(self):
        self.assertEqual(self.poner("SST-NO-EXISTE", self.cabria).status_code, 404)
