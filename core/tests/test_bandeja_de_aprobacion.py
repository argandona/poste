"""
Quien aprueba ve los pedidos y devoluciones de todos, aunque además sea
capataz.

Pasó con una cuenta de Capataz + SuperAdmin: el filtro de "cada capataz ve lo
suyo" le ganaba al rol que aprueba, y la bandeja de pendientes le salía vacía
aunque otro había pedido cemento.
"""
from ..models import Devolucion, Pedido, Rol, Usuario
from .base import BaseAPITestCase


class BandejaDeAprobacionTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.rol_superadmin = Rol.objects.create(
            id_rol=Rol.SUPERADMIN, descripcion="SuperAdmin")
        # Capataz de rol principal y SuperAdmin de secundario.
        self.jefe = Usuario.objects.create(
            nombre="Jefe", rol=self.rol_capataz,
            rol_secundario=self.rol_superadmin, empresa=self.empresa,
            email="jefe@encossa.com", clave="x")
        self.ajeno = Pedido.objects.create(
            camion=self.camion, usuario=self.capataz, estado="pendiente")
        self.propio = Pedido.objects.create(
            camion=self.camion, usuario=self.jefe, estado="pendiente")
        self.devolucion_ajena = Devolucion.objects.create(
            camion=self.camion, usuario=self.capataz, estado="pendiente")

    def ids(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, resp.content)
        datos = resp.json()
        filas = datos.get("results", datos) if isinstance(datos, dict) else datos
        return {f.get("id_pedido") or f.get("id_devolucion") for f in filas}

    def test_capataz_que_aprueba_ve_los_pedidos_de_otros(self):
        self.auth(self.jefe)
        self.assertEqual(self.ids("/api/pedidos/?estado=pendiente"),
                         {self.ajeno.pk, self.propio.pk})

    def test_capataz_que_aprueba_ve_las_devoluciones_de_otros(self):
        self.auth(self.jefe)
        self.assertEqual(self.ids("/api/devoluciones/?estado=pendiente"),
                         {self.devolucion_ajena.pk})

    def test_con_propios_ve_solo_lo_suyo(self):
        self.auth(self.jefe)
        self.assertEqual(self.ids("/api/pedidos/?propios=1"), {self.propio.pk})
        self.assertEqual(self.ids("/api/devoluciones/?propios=1"), set())

    def test_capataz_comun_sigue_viendo_solo_lo_suyo(self):
        self.auth(self.capataz)
        self.assertEqual(self.ids("/api/pedidos/"), {self.ajeno.pk})
        self.assertEqual(self.ids("/api/devoluciones/"),
                         {self.devolucion_ajena.pk})

    def test_encargado_de_almacen_ve_todo(self):
        self.auth(self.encargado)
        self.assertEqual(self.ids("/api/pedidos/"),
                         {self.ajeno.pk, self.propio.pk})

    def test_capataz_que_aprueba_puede_aprobar_el_pedido_ajeno(self):
        self.auth(self.jefe)
        resp = self.client.post(
            f"/api/pedidos/{self.ajeno.pk}/aprobar/",
            {"accion": "rechazar", "usuario_aprueba": self.jefe.pk,
             "almacen": self.almacen.pk, "observacion": "prueba",
             "detalles": []},
            format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.ajeno.refresh_from_db()
        self.assertEqual(self.ajeno.estado, "rechazado")
