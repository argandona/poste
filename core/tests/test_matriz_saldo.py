"""La matriz del saldo del camión: cada movimiento por material, en orden de
fecha, y al final el saldo que debería tener comparado con el del sistema."""
import io
from datetime import date, timedelta
from decimal import Decimal

from openpyxl import load_workbook

from ..matriz_saldo import ENTRA, SALE, matriz
from ..models import (
    AsignacionAgregado,
    ConsumoMaterialSuministro, DetalleDevolucion, DetallePedido, Devolucion,
    LiquidacionSuministro, Pedido, StockCamion, TipoTrabajo, Usuario,
)
from .base import BaseAPITestCase

URL = '/api/stock-camion/matriz/'


class MatrizSaldoTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        hoy = date.today()
        # Entran 10 del A por pedido, se liquidan 3 y se devuelven 2: quedan 5.
        pedido = Pedido.objects.create(
            camion=self.camion, usuario=self.capataz, estado='aprobado',
            fecha_aprobacion=hoy - timedelta(days=5))
        DetallePedido.objects.create(pedido=pedido, material=self.material_a,
                                     cantidad_solicitada=10, cantidad_aprobada=10)
        liq = LiquidacionSuministro.objects.create(
            usuario=self.capataz, tipo_trabajo=TipoTrabajo.objects.create(nombre='Cambio'),
            suministro_externo='1014213', sst_externo='5551234')
        ConsumoMaterialSuministro.objects.create(
            liquidacion=liq, suministro_externo='1014213', material=self.material_a,
            usuario=self.capataz, cantidad=3)
        devolucion = Devolucion.objects.create(
            camion=self.camion, usuario=self.capataz, estado='aprobado',
            fecha_aprobacion=hoy)
        DetalleDevolucion.objects.create(devolucion=devolucion, material=self.material_a,
                                         cantidad_solicitada=2, cantidad_aprobada=2)
        self.stock = StockCamion.objects.create(camion=self.camion,
                                                material=self.material_a, cantidad=5)

    def test_cada_movimiento_en_su_columna_y_el_saldo_al_final(self):
        movs, [fila] = matriz(self.camion)
        self.assertEqual([m.tipo for m in movs], ['Pedido', 'Liquidación', 'Devolución'])
        self.assertEqual(movs[1].documento, 'SST 5551234 · poste 1014213')
        self.assertEqual([m.clase for m in movs], [ENTRA, SALE, SALE])
        self.assertEqual(fila['celdas'], [Decimal(10), Decimal(-3), Decimal(-2)])
        self.assertEqual(fila['entra'], 10)
        self.assertEqual(fila['sale'], 5)
        self.assertEqual(fila['calculado'], 5)
        self.assertEqual(fila['diferencia'], 0)

    def test_si_no_cuadra_sale_la_diferencia(self):
        self.stock.cantidad = 4
        self.stock.save()
        [fila] = matriz(self.camion)[1]
        self.assertEqual(fila['diferencia'], -1)

    def test_no_cuenta_lo_que_otro_liquidó_con_otro_camion(self):
        otro = Usuario.objects.create(nombre='Otro', rol=self.rol_capataz,
                                      empresa=self.empresa, email='o@t.pe', clave='x')
        liq = LiquidacionSuministro.objects.create(
            usuario=otro, tipo_trabajo=TipoTrabajo.objects.create(nombre='Otro'))
        ConsumoMaterialSuministro.objects.create(
            liquidacion=liq, material=self.material_a, usuario=otro, cantidad=7)
        [fila] = matriz(self.camion)[1]
        self.assertEqual(fila['calculado'], 5)

    def test_las_asignaciones_del_mismo_dia_van_en_una_columna(self):
        for material, cantidad in ((self.material_a, 4), (self.material_b, 6),
                                   (self.material_b, 1)):
            AsignacionAgregado.objects.create(
                almacen=self.almacen, camion=self.camion, material=material,
                cantidad=cantidad, usuario=self.capataz, registrado_por=self.encargado,
                origen=AsignacionAgregado.ORIGEN_ALMACEN)
        movs, filas = matriz(self.camion)
        asignaciones = [m for m in movs if m.tipo == 'Asignación']
        self.assertEqual(len(asignaciones), 1)
        [a] = asignaciones
        self.assertEqual(a.documento.count(','), 2)
        self.assertEqual(a.responsable, 'Capataz Uno')
        self.assertEqual(a.cantidades, {self.material_a.pk: 4, self.material_b.pk: 7})
        self.assertEqual({f['matricula']: f['calculado'] for f in filas},
                         {'MAT-A': 9, 'MAT-B': 7})

    def test_el_almacen_baja_el_excel(self):
        self.auth(self.encargado)
        r = self.client.get(URL, {'camion': self.camion.pk})
        self.assertEqual(r.status_code, 200)
        wb = load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.sheetnames, ['Matriz', 'Movimientos'])
        ws = wb['Matriz']
        self.assertEqual(ws['A7'].value, 'MAT-A')
        self.assertEqual([ws.cell(5, c).value for c in (3, 4, 5)],
                         ['Pedido', 'Liquidación', 'Devolución'])
        self.assertEqual([ws.cell(7, c).value for c in (3, 4, 5)], [10, -3, -2])
        self.assertEqual(ws.cell(4, 9).value, 'Saldo calculado')
        self.assertEqual(ws.cell(7, 9).value, 5)
        self.assertEqual(ws.cell(7, 11).value, 0)
        self.assertEqual([c.value for c in wb['Movimientos']['H'][1:]], [10, 7, 5])

    def test_el_responsable_baja_el_de_su_camion_y_nadie_mas(self):
        self.auth(self.capataz)
        self.assertEqual(self.client.get(URL, {'camion': self.camion.pk}).status_code, 200)
        otro = Usuario.objects.create(nombre='Otro', rol=self.rol_capataz,
                                      empresa=self.empresa, email='o@t.pe', clave='x')
        self.auth(otro)
        self.assertEqual(self.client.get(URL, {'camion': self.camion.pk}).status_code, 403)
        self.assertEqual(self.client.get(URL).status_code, 400)
