"""
Base común para los tests de la API: arma un escenario mínimo pero realista
(empresa, roles, camión con capataz asignado, almacén con stock) y expone
helpers para autenticar peticiones con el JWT propio del proyecto.
"""
from datetime import date, timedelta

from rest_framework.test import APITestCase

from ..authentication import CustomRefreshToken
from ..models import (
    Almacen, Camion, Empresa, Material, Rol, StockAlmacen, StockCamion,
    Usuario, UsuarioCamion,
)


class BaseAPITestCase(APITestCase):
    """Escenario: un camión con capataz asignado y un almacén con stock."""

    def setUp(self):
        super().setUp()

        # Los ids de Rol son constantes del dominio (Rol.CAPATAZ == 4, etc.),
        # así que se crean explícitamente y no con un autoincremental.
        self.rol_capataz = Rol.objects.create(
            id_rol=Rol.CAPATAZ, descripcion="Capataz")
        self.rol_almacen = Rol.objects.create(
            id_rol=Rol.ENCARGADO_ALMACEN, descripcion="Encargado de Almacén")

        self.empresa = Empresa.objects.create(nombre="TECSUR", ruc="20100000001")

        self.capataz = Usuario.objects.create(
            nombre="Capataz Uno", rol=self.rol_capataz, empresa=self.empresa,
            email="capataz@tecsur.pe", clave="x")
        self.encargado = Usuario.objects.create(
            nombre="Encargado Almacén", rol=self.rol_almacen, empresa=self.empresa,
            email="encargado@tecsur.pe", clave="x")

        self.camion = Camion.objects.create(empresa=self.empresa, placa="ABC-123")
        # La asignación nace abierta: no vence sola, se cierra al liberar o
        # traspasar el camión.
        self.asignacion = UsuarioCamion.objects.create(
            camion=self.camion, usuario=self.capataz,
            fecha_inicio=date.today() - timedelta(days=30))

        self.almacen = Almacen.objects.create(empresa=self.empresa, nombre="Central")

        # Dos materiales: uno con stock en el almacén y otro sin fila de stock,
        # para poder ejercitar el camino de "material sin stock registrado".
        self.material_a = Material.objects.create(
            matricula="MAT-A", descripcion="Cable A", precio="10.00")
        self.material_b = Material.objects.create(
            matricula="MAT-B", descripcion="Cable B", precio="20.00")

        self.stock_almacen_a = StockAlmacen.objects.create(
            almacen=self.almacen, material=self.material_a, cantidad=10)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def auth(self, usuario):
        """Autentica el cliente de test como `usuario` (JWT propio)."""
        token = CustomRefreshToken.for_usuario(usuario)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def stock_almacen(self, material):
        """Cantidad en el almacén, o None si no hay fila de stock."""
        fila = StockAlmacen.objects.filter(
            almacen=self.almacen, material=material).first()
        return fila.cantidad if fila else None

    def stock_camion(self, material):
        """Cantidad en el camión, o None si no hay fila de stock."""
        fila = StockCamion.objects.filter(
            camion=self.camion, material=material).first()
        return fila.cantidad if fila else None
