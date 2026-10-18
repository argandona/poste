"""Al asignar postes de una SST, al capataz o encargado le llega un aviso; si se
los quitan (desasignar o pasarlos a otro), también."""
from unittest import mock

from ..models import Actividad, Rol, SST, SSTSuministro, Suministro, Usuario
from .base import BaseAPITestCase


class AvisoSSTAsignadaTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        rol = Rol.objects.create(id_rol=Rol.COORDINADOR, descripcion="Coordinador")
        self.coordinador = Usuario.objects.create(
            nombre="Coordinador Uno", rol=rol, empresa=self.empresa,
            email="coordinador@tecsur.pe", clave="x")
        self.capataz.fcm_token = "token-uno"
        self.capataz.save()
        self.otro = Usuario.objects.create(
            nombre="Capataz Dos", rol=self.rol_capataz, empresa=self.empresa,
            email="dos@tecsur.pe", clave="x", fcm_token="token-dos")
        self.sst = SST.objects.create(
            empresa=self.empresa, codigo="SST-0001", distrito="Miraflores",
            actividad=Actividad.objects.create(nombre="Cambio de poste"))
        self.postes = []
        for numero in ("P-1", "P-2", "P-3", "P-4", "P-5"):
            p = Suministro.objects.create(numero_suministro=numero)
            SSTSuministro.objects.create(sst=self.sst, suministro=p)
            self.postes.append(p)
        self.auth(self.coordinador)

    def asignar(self, usuario, postes=()):
        with mock.patch("core.fcm.send_notification") as avisar:
            r = self.client.post(f"/api/ssts/{self.sst.pk}/asignar/", {
                "usuario": usuario.pk,
                "suministros": [p.pk for p in postes]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        return avisar

    def desasignar(self, postes=()):
        with mock.patch("core.fcm.send_notification") as avisar:
            r = self.client.post(f"/api/ssts/{self.sst.pk}/desasignar/", {
                "suministros": [p.pk for p in postes]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        return avisar

    @staticmethod
    def avisos(mock_avisar):
        return [(c.args[0], c.kwargs["title"], c.kwargs["body"], c.kwargs["data"])
                for c in mock_avisar.call_args_list]

    def test_al_asignar_le_llega_la_sst_con_sus_postes(self):
        [(tokens, titulo, cuerpo, data)] = self.avisos(
            self.asignar(self.capataz, self.postes[:2]))
        self.assertEqual(tokens, ["token-uno"])
        self.assertEqual(titulo, "Nueva SST asignada")
        self.assertEqual(cuerpo, "SST SST-0001 · Cambio de poste · 2 postes: P-1, P-2")
        self.assertEqual(data, {"tipo": "sst_asignada", "sst_id": str(self.sst.pk)})

    def test_muchos_postes_se_resumen(self):
        [(_, _, cuerpo, _)] = self.avisos(self.asignar(self.capataz))
        self.assertTrue(cuerpo.endswith("5 postes: P-1, P-2, P-3 y 2 más"), cuerpo)

    def test_mas_postes_en_una_sst_que_ya_tenia(self):
        self.asignar(self.capataz, self.postes[:1])
        [(_, titulo, cuerpo, _)] = self.avisos(
            self.asignar(self.capataz, self.postes[:2]))
        self.assertEqual(titulo, "Más postes en tu SST")
        self.assertTrue(cuerpo.endswith("1 poste: P-2"), cuerpo)

    def test_reasignar_lo_mismo_no_avisa(self):
        self.asignar(self.capataz, self.postes[:2])
        self.assertEqual(self.avisos(self.asignar(self.capataz, self.postes[:2])), [])

    def test_pasar_postes_a_otro_avisa_a_los_dos(self):
        self.asignar(self.capataz, self.postes[:2])
        avisos = self.avisos(self.asignar(self.otro, self.postes[:1]))
        self.assertEqual([(a[0], a[1]) for a in avisos], [
            (["token-dos"], "Nueva SST asignada"),
            (["token-uno"], "Te quitaron postes de una SST")])
        self.assertIn("1 poste: P-1. Los demás postes siguen contigo.", avisos[1][2])

    def test_quien_se_queda_sin_postes_deja_de_ver_la_sst(self):
        self.asignar(self.capataz, self.postes[:2])
        self.asignar(self.otro, self.postes[:2])
        mis = lambda u: self.client.get("/api/ssts/mis_sst/", {"usuario": u.pk}).data
        self.assertEqual(mis(self.capataz), [])
        self.assertEqual(len(mis(self.otro)), 1)

    def test_desasignar_avisa_que_ya_no_le_toca(self):
        self.asignar(self.capataz, self.postes[:2])
        [(tokens, titulo, cuerpo, data)] = self.avisos(self.desasignar())
        self.assertEqual(tokens, ["token-uno"])
        self.assertEqual(titulo, "Te quitaron una SST")
        self.assertEqual(cuerpo, "SST SST-0001 · 2 postes: P-1, P-2. Ya no te toca.")
        self.assertEqual(data["tipo"], "sst_retirada")

    def test_desasignar_parte_avisa_que_sigue_con_los_demas(self):
        self.asignar(self.capataz, self.postes[:2])
        [(_, titulo, _, _)] = self.avisos(self.desasignar(self.postes[:1]))
        self.assertEqual(titulo, "Te quitaron postes de una SST")

    def test_asignar_manual_avisa_y_al_que_lo_tenia_tambien(self):
        with mock.patch("core.fcm.send_notification") as avisar:
            r = self.client.post("/api/ssts/asignar_manual/", {
                "sst_codigo": "SST-0001", "numero_suministro": "P-1",
                "usuario": self.capataz.pk}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        [(_, titulo, cuerpo, _)] = self.avisos(avisar)
        self.assertEqual(titulo, "Nueva SST asignada")
        self.assertTrue(cuerpo.endswith("1 poste: P-1"), cuerpo)
        with mock.patch("core.fcm.send_notification") as avisar:
            self.client.post("/api/ssts/asignar_manual/", {
                "sst_codigo": "SST-0001", "numero_suministro": "P-1",
                "usuario": self.otro.pk}, format="json")
        self.assertEqual([a[1] for a in self.avisos(avisar)],
                         ["Nueva SST asignada", "Te quitaron una SST"])

    def test_sin_token_no_se_envia_nada(self):
        self.capataz.fcm_token = ""
        self.capataz.save()
        self.assertEqual(self.avisos(self.asignar(self.capataz)), [])
