"""
Asignación de SST y suministros: solo un Coordinador (o SuperAdmin) puede
asignar o desasignar suministros a un capataz.

Estos tests existen porque la capacidad `puede_asignar_sst` se perdió una vez en
un reemplazo de models.py y nada lo detectó: los endpoints seguían llamándola y
fallaban con AttributeError en runtime.
"""
from ..models import (
    SST, Rol, SSTEncargado, SSTSuministro, Suministro, Usuario,
)
from .base import BaseAPITestCase


class AsignarSSTTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.rol_coordinador = Rol.objects.create(
            id_rol=Rol.COORDINADOR, descripcion="Coordinador")
        self.coordinador = Usuario.objects.create(
            nombre="Coordinador Uno", rol=self.rol_coordinador,
            empresa=self.empresa, email="coordinador@tecsur.pe", clave="x")

        self.sst = SST.objects.create(
            empresa=self.empresa, sst="0001", codigo="SST-0001",
            distrito="Miraflores")
        self.suministro_1 = Suministro.objects.create(numero_suministro="S-001")
        self.suministro_2 = Suministro.objects.create(numero_suministro="S-002")
        for suministro in (self.suministro_1, self.suministro_2):
            SSTSuministro.objects.create(sst=self.sst, suministro=suministro)

        self.url_asignar = f"/api/ssts/{self.sst.pk}/asignar/"
        self.url_desasignar = f"/api/ssts/{self.sst.pk}/desasignar/"

    def asignados_a_capataz(self):
        return SSTSuministro.objects.filter(
            sst=self.sst, asignado_a=self.capataz).count()

    # ── Permisos ─────────────────────────────────────────────────────────────

    def test_el_coordinador_puede_asignar(self):
        self.auth(self.coordinador)

        resp = self.client.post(
            self.url_asignar, {"usuario": self.capataz.pk}, format="json")

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(self.asignados_a_capataz(), 2)
        self.assertTrue(SSTEncargado.objects.filter(
            sst=self.sst, usuario=self.capataz).exists())

    def test_el_capataz_no_puede_asignar(self):
        self.auth(self.capataz)

        resp = self.client.post(
            self.url_asignar, {"usuario": self.capataz.pk}, format="json")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.asignados_a_capataz(), 0)

    def test_el_encargado_de_almacen_no_puede_asignar(self):
        self.auth(self.encargado)

        resp = self.client.post(
            self.url_asignar, {"usuario": self.capataz.pk}, format="json")

        self.assertEqual(resp.status_code, 403)

    def test_el_capataz_no_puede_desasignar(self):
        SSTSuministro.objects.filter(sst=self.sst).update(asignado_a=self.capataz)
        self.auth(self.capataz)

        resp = self.client.post(self.url_desasignar, {}, format="json")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.asignados_a_capataz(), 2)

    # ── Comportamiento ───────────────────────────────────────────────────────

    def test_asignar_una_lista_parcial_solo_toca_esos_suministros(self):
        self.auth(self.coordinador)

        resp = self.client.post(
            self.url_asignar,
            {"usuario": self.capataz.pk, "suministros": [self.suministro_1.pk]},
            format="json")

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["suministros_asignados"], 1)
        self.assertEqual(self.asignados_a_capataz(), 1)

    def test_sin_usuario_devuelve_400(self):
        self.auth(self.coordinador)

        resp = self.client.post(self.url_asignar, {}, format="json")

        self.assertEqual(resp.status_code, 400)

    def test_usuario_inexistente_devuelve_404(self):
        self.auth(self.coordinador)

        resp = self.client.post(
            self.url_asignar, {"usuario": 999999}, format="json")

        self.assertEqual(resp.status_code, 404)

    def test_el_coordinador_puede_desasignar(self):
        SSTSuministro.objects.filter(sst=self.sst).update(asignado_a=self.capataz)
        self.auth(self.coordinador)

        resp = self.client.post(self.url_desasignar, {}, format="json")

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["suministros_desasignados"], 2)
        self.assertEqual(self.asignados_a_capataz(), 0)


class CapacidadesPorRolTests(BaseAPITestCase):
    """Matriz de capacidades por rol, para que un borrado accidental falle acá."""

    def test_quien_puede_asignar_sst(self):
        self.assertTrue(Usuario(rol_id=Rol.COORDINADOR).puede_asignar_sst())
        self.assertTrue(Usuario(rol_id=Rol.SUPERADMIN).puede_asignar_sst())
        self.assertFalse(Usuario(rol_id=Rol.CAPATAZ).puede_asignar_sst())
        self.assertFalse(Usuario(rol_id=Rol.ENCARGADO_ALMACEN).puede_asignar_sst())
        self.assertFalse(Usuario(rol_id=Rol.LIQUIDADOR).puede_asignar_sst())

    def test_quien_puede_pedir_y_devolver(self):
        for rol in (Rol.CAPATAZ, Rol.ENCARGADO):
            self.assertTrue(Usuario(rol_id=rol).puede_hacer_pedido())
            self.assertTrue(Usuario(rol_id=rol).puede_hacer_devolucion())
        self.assertFalse(Usuario(rol_id=Rol.COORDINADOR).puede_hacer_pedido())

    def test_quien_puede_aprobar(self):
        self.assertTrue(Usuario(rol_id=Rol.ENCARGADO_ALMACEN).puede_aprobar_pedido())
        self.assertTrue(Usuario(rol_id=Rol.SUPERADMIN).puede_aprobar_pedido())
        self.assertFalse(Usuario(rol_id=Rol.CAPATAZ).puede_aprobar_pedido())
        self.assertFalse(Usuario(rol_id=Rol.COORDINADOR).puede_aprobar_pedido())
