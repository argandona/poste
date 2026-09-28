"""
A quién le llega el aviso de un pedido o una devolución nueva: a quienes
pueden aprobarlos en esa empresa, aunque además sean capataces.
"""
from unittest import mock

from ..models import Rol, StockCamion, Usuario
from .base import BaseAPITestCase


class AvisoDePedidoTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        rol_superadmin = Rol.objects.create(
            id_rol=Rol.SUPERADMIN, descripcion="SuperAdmin")
        self.encargado.fcm_token = "token-almacen"
        self.encargado.save()
        self.jefe = Usuario.objects.create(
            nombre="Jefe", rol=self.rol_capataz, rol_secundario=rol_superadmin,
            empresa=self.empresa, email="jefe@encossa.com", clave="x",
            fcm_token="token-jefe")
        # Un capataz común no aprueba: no recibe el aviso.
        self.capataz.fcm_token = "token-capataz"
        self.capataz.save()

    def destinatarios(self, aviso):
        self.assertEqual(aviso.call_count, 1)
        return set(aviso.call_args.args[0])

    @mock.patch("core.fcm.send_notification")
    def test_el_pedido_nuevo_avisa_a_quienes_aprueban(self, aviso):
        self.auth(self.capataz)
        resp = self.client.post("/api/pedidos/", {
            "camion": self.camion.pk, "usuario": self.capataz.pk,
            "observacion": "",
            "detalles": [{"material": self.material_a.pk,
                          "cantidad_solicitada": 2}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.destinatarios(aviso),
                         {"token-almacen", "token-jefe"})

    @mock.patch("core.fcm.send_notification")
    def test_la_devolucion_nueva_avisa_a_quienes_aprueban(self, aviso):
        StockCamion.objects.create(camion=self.camion, material=self.material_a,
                                   cantidad=3)
        self.auth(self.capataz)
        resp = self.client.post("/api/devoluciones/", {
            "camion": self.camion.pk, "usuario": self.capataz.pk,
            "observacion": "",
            "detalles": [{"material": self.material_a.pk,
                          "cantidad_solicitada": 1}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.destinatarios(aviso),
                         {"token-almacen", "token-jefe"})
