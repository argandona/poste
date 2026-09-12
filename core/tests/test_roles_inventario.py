"""
Matriz de roles del almacén: quién cuenta existencias (inventario físico) y
quién mueve el stock del almacén. En TECSUR el Capataz inventaría su propio
camión, pero no toca el almacén ni los camiones ajenos.
"""
from datetime import date, timedelta

from django.core.exceptions import ValidationError

from ..models import (
    Camion, IngresoTecsur, Inventario, Proveedor, Rol, TransferenciaAlmacen,
    Usuario, UsuarioCamion,
)
from .base import BaseAPITestCase


class MatrizRolesTests(BaseAPITestCase):
    """Las dos capacidades son distintas y ya no comparten método."""

    def test_capataz_inventaria_pero_no_gestiona_almacen(self):
        self.assertTrue(self.capataz.puede_hacer_inventario())
        self.assertFalse(self.capataz.puede_gestionar_almacen())

    def test_encargado_almacen_puede_ambas(self):
        self.assertTrue(self.encargado.puede_hacer_inventario())
        self.assertTrue(self.encargado.puede_gestionar_almacen())

    def test_liquidador_no_puede_ninguna(self):
        rol = Rol.objects.create(id_rol=Rol.LIQUIDADOR, descripcion="Liquidador")
        liquidador = Usuario.objects.create(
            nombre="Liquidador Uno", rol=rol, empresa=self.empresa,
            email="liquidador@tecsur.pe", clave="x")
        self.assertFalse(liquidador.puede_hacer_inventario())
        self.assertFalse(liquidador.puede_gestionar_almacen())


class InventarioCapatazTests(BaseAPITestCase):
    """`Inventario.clean()` limita al Capataz a su propio camión."""

    def _inventario(self, usuario, camion=None, almacen=None):
        hoy = date.today()
        return Inventario(usuario=usuario, camion=camion, almacen=almacen,
                          mes=hoy.month, anio=hoy.year)

    def test_capataz_cuenta_su_camion_asignado(self):
        self._inventario(self.capataz, camion=self.camion).full_clean()

    def test_capataz_no_cuenta_el_almacen(self):
        with self.assertRaises(ValidationError) as cm:
            self._inventario(self.capataz, almacen=self.almacen).full_clean()
        self.assertIn("no el almacén", str(cm.exception))

    def test_capataz_no_cuenta_un_camion_ajeno(self):
        ajeno = Camion.objects.create(empresa=self.empresa, placa="XYZ-789")
        with self.assertRaises(ValidationError) as cm:
            self._inventario(self.capataz, camion=ajeno).full_clean()
        self.assertIn("no está asignado", str(cm.exception))

    def test_capataz_sin_camion_vigente_no_cuenta_nada(self):
        UsuarioCamion.objects.filter(usuario=self.capataz).update(
            fecha_fin=date.today() - timedelta(days=1), activo=False)
        with self.assertRaises(ValidationError) as cm:
            self._inventario(self.capataz, camion=self.camion).full_clean()
        self.assertIn("camión asignado", str(cm.exception))

    def test_encargado_cuenta_el_almacen(self):
        self._inventario(self.encargado, almacen=self.almacen).full_clean()

    def test_encargado_cuenta_cualquier_camion(self):
        """El límite del camión propio es del Capataz, no del Encargado."""
        self._inventario(self.encargado, camion=self.camion).full_clean()


class MovimientosAlmacenTests(BaseAPITestCase):
    """Los movimientos de stock siguen siendo solo del Encargado de Almacén."""

    def setUp(self):
        super().setUp()
        self.proveedor = Proveedor.objects.create(
            nombre="Proveedor Uno", ruc="20100000002")

    def _ingreso(self, usuario):
        return IngresoTecsur(almacen=self.almacen, proveedor=self.proveedor,
                             usuario=usuario, folio="ING-001", fecha=date.today())

    def test_capataz_no_registra_ingresos(self):
        with self.assertRaises(ValidationError) as cm:
            self._ingreso(self.capataz).full_clean()
        self.assertIn("Encargado de Almacén", str(cm.exception))

    def test_encargado_registra_ingresos(self):
        self._ingreso(self.encargado).full_clean()

    def test_capataz_no_transfiere_entre_almacenes(self):
        destino = type(self.almacen).objects.create(
            empresa=self.empresa, nombre="Secundario")
        transferencia = TransferenciaAlmacen(
            almacen_origen=self.almacen, almacen_destino=destino,
            usuario=self.capataz, fecha=date.today())
        with self.assertRaises(ValidationError) as cm:
            transferencia.full_clean()
        self.assertIn("Encargado de Almacén", str(cm.exception))
