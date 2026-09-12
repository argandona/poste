"""
La responsabilidad sobre el saldo de un camión no se evapora.

Mientras el camión cargue material, su asignación no se puede cerrar, acortar,
desactivar ni borrar: el capataz devuelve el material al almacén o se lo entrega
a otro responsable con acta. Sin esto, bastaba con pedir material y dejar que la
asignación venciera para quedarse sin saldos que devolver.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError

from ..models import (
    Camion, StockCamion, TraspasoCamion, Usuario, UsuarioCamion,
)
from .base import BaseAPITestCase


class BaseAsignacion(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.otro_capataz = Usuario.objects.create(
            nombre="Capataz Dos", rol=self.rol_capataz, empresa=self.empresa,
            email="capataz2@tecsur.pe", clave="x")

    def cargar_camion(self, cantidad=5):
        StockCamion.objects.create(
            camion=self.camion, material=self.material_a, cantidad=cantidad)

    def vaciar_camion(self):
        StockCamion.objects.filter(camion=self.camion).update(cantidad=0)


class CierreConSaldoTests(BaseAsignacion):

    def test_no_se_libera_un_camion_con_saldo(self):
        self.cargar_camion()
        with self.assertRaises(ValidationError) as cm:
            self.asignacion.liberar()
        self.assertIn("tiene saldo a nombre de", str(cm.exception))
        self.asignacion.refresh_from_db()
        self.assertTrue(self.asignacion.activo)
        self.assertIsNone(self.asignacion.fecha_fin)

    def test_se_libera_el_camion_vacio(self):
        self.cargar_camion()
        self.vaciar_camion()
        self.asignacion.liberar()
        self.asignacion.refresh_from_db()
        self.assertFalse(self.asignacion.activo)
        self.assertEqual(self.asignacion.fecha_fin, date.today())

    def test_no_se_adelanta_la_fecha_de_fin_con_saldo(self):
        """Acortar la vigencia es otra forma de soltar el camión."""
        self.cargar_camion()
        self.asignacion.fecha_fin = date.today() + timedelta(days=1)
        with self.assertRaises(ValidationError):
            self.asignacion.full_clean()

    def test_no_se_desactiva_la_asignacion_con_saldo(self):
        self.cargar_camion()
        self.asignacion.activo = False
        with self.assertRaises(ValidationError):
            self.asignacion.full_clean()

    def test_no_se_borra_la_asignacion_con_saldo(self):
        self.cargar_camion()
        with self.assertRaises(ValidationError):
            self.asignacion.delete()
        self.assertTrue(UsuarioCamion.objects.filter(pk=self.asignacion.pk).exists())

    def test_una_asignacion_nueva_no_lleva_fecha_de_fin(self):
        otro = Camion.objects.create(empresa=self.empresa, placa="NUE-111")
        nueva = UsuarioCamion(camion=otro, usuario=self.otro_capataz,
                              fecha_inicio=date.today(),
                              fecha_fin=date.today() + timedelta(days=30))
        with self.assertRaises(ValidationError) as cm:
            nueva.full_clean()
        self.assertIn("no lleva fecha de fin", str(cm.exception))

    def test_mudar_al_capataz_a_otro_camion_no_cierra_el_anterior_en_silencio(self):
        """El cierre implícito de la asignación previa era la puerta de atrás."""
        self.cargar_camion()
        otro = Camion.objects.create(empresa=self.empresa, placa="OTR-222")
        with self.assertRaises(ValidationError):
            UsuarioCamion(camion=otro, usuario=self.capataz,
                          fecha_inicio=date.today()).save()
        self.asignacion.refresh_from_db()
        self.assertTrue(self.asignacion.activo)

    def test_mudar_al_capataz_con_el_camion_vacio_si_cierra_el_anterior(self):
        otro = Camion.objects.create(empresa=self.empresa, placa="OTR-333")
        UsuarioCamion(camion=otro, usuario=self.capataz,
                      fecha_inicio=date.today()).save()
        self.asignacion.refresh_from_db()
        self.assertFalse(self.asignacion.activo)
        self.assertEqual(
            UsuarioCamion.camion_activo_de_usuario(self.capataz).placa, "OTR-333")


class TraspasoTests(BaseAsignacion):

    def test_el_traspaso_pasa_el_saldo_al_nuevo_responsable(self):
        self.cargar_camion(7)
        self.asignacion.traspasar_a(self.otro_capataz, observacion="Cambio de cuadrilla")

        self.asignacion.refresh_from_db()
        self.assertFalse(self.asignacion.activo)
        self.assertEqual(self.asignacion.fecha_fin, date.today())

        vigente = UsuarioCamion.camion_activo_de_usuario(self.otro_capataz)
        self.assertEqual(vigente.pk, self.camion.pk)
        self.assertIsNone(UsuarioCamion.camion_activo_de_usuario(self.capataz))

    def test_el_acta_guarda_el_saldo_que_cambio_de_manos(self):
        self.cargar_camion(7)
        acta = self.asignacion.traspasar_a(self.otro_capataz)
        self.assertEqual(acta.usuario_entrega, self.capataz)
        self.assertEqual(acta.usuario_recibe, self.otro_capataz)
        detalle = acta.detalles.get()
        self.assertEqual(detalle.material, self.material_a)
        self.assertEqual(detalle.cantidad, Decimal("7.00"))

    def test_no_se_traspasa_a_uno_mismo(self):
        self.cargar_camion()
        with self.assertRaises(ValidationError):
            self.asignacion.traspasar_a(self.capataz)

    def test_el_traspaso_no_deja_el_camion_sin_responsable(self):
        """Si algo falla a mitad, no se cierra la asignación de nadie."""
        self.cargar_camion()
        # El que recibe ya tiene otro camión con saldo, así que su asignación
        # previa no se puede cerrar y el traspaso completo debe revertirse.
        otro = Camion.objects.create(empresa=self.empresa, placa="LLE-444")
        UsuarioCamion.objects.create(
            camion=otro, usuario=self.otro_capataz, fecha_inicio=date.today())
        StockCamion.objects.create(
            camion=otro, material=self.material_b, cantidad=3)

        with self.assertRaises(ValidationError):
            self.asignacion.traspasar_a(self.otro_capataz)

        self.asignacion.refresh_from_db()
        self.assertTrue(self.asignacion.activo)
        self.assertFalse(TraspasoCamion.objects.exists())


class EndpointsAsignacionTests(BaseAsignacion):

    def test_el_capataz_no_libera_su_propio_camion(self):
        self.auth(self.capataz)
        r = self.client.post(f"/api/usuario-camion/{self.asignacion.pk}/liberar/")
        self.assertEqual(r.status_code, 403)

    def test_liberar_con_saldo_responde_400_con_detail_string(self):
        self.cargar_camion()
        self.auth(self.encargado)
        r = self.client.post(f"/api/usuario-camion/{self.asignacion.pk}/liberar/")
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.data["detail"], str)
        self.assertIn("saldo", r.data["detail"])

    def test_liberar_el_camion_vacio(self):
        self.auth(self.encargado)
        r = self.client.post(f"/api/usuario-camion/{self.asignacion.pk}/liberar/")
        self.assertEqual(r.status_code, 200)
        self.asignacion.refresh_from_db()
        self.assertFalse(self.asignacion.activo)

    def test_traspasar_por_api_levanta_el_acta(self):
        self.cargar_camion(4)
        self.auth(self.encargado)
        r = self.client.post("/api/usuario-camion/traspasar/", {
            "camion": self.camion.pk,
            "usuario_recibe": self.otro_capataz.pk,
            "observacion": "Vacaciones del titular",
        }, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["recibe_nombre"], "Capataz Dos")
        self.assertEqual(len(r.data["detalles"]), 1)
        self.assertEqual(
            UsuarioCamion.camion_activo_de_usuario(self.otro_capataz).pk,
            self.camion.pk)

    def test_un_patch_no_puede_cerrar_la_asignacion(self):
        self.cargar_camion()
        self.auth(self.encargado)
        r = self.client.patch(f"/api/usuario-camion/{self.asignacion.pk}/",
                              {"activo": False, "fecha_fin": str(date.today())},
                              format="json")
        self.assertEqual(r.status_code, 200)
        self.asignacion.refresh_from_db()
        self.assertTrue(self.asignacion.activo)
        self.assertIsNone(self.asignacion.fecha_fin)

    def test_un_delete_no_puede_borrar_una_asignacion_con_saldo(self):
        self.cargar_camion()
        self.auth(self.encargado)
        r = self.client.delete(f"/api/usuario-camion/{self.asignacion.pk}/")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(UsuarioCamion.objects.filter(pk=self.asignacion.pk).exists())

    def test_reporte_de_saldos_por_responsable(self):
        self.cargar_camion(9)
        self.auth(self.encargado)
        r = self.client.get("/api/usuario-camion/saldos_por_responsable/")
        self.assertEqual(r.status_code, 200)
        fila = next(f for f in r.data if f["id_usuario"] == self.capataz.pk)
        self.assertEqual(fila["camion"], "ABC-123")
        self.assertEqual(Decimal(str(fila["saldo_total"])), Decimal("9.00"))
        self.assertFalse(fila["puede_liberar"])
