"""Matriz del saldo de un camión: de dónde sale cada número.

Pedido del usuario el 2026-10-16: un Excel por camión con una fila por
material y, de izquierda a derecha y en orden de fecha, cada movimiento que
tocó el saldo (lo que entró por pedido o asignación, lo que salió por
liquidación o devolución) y al final el saldo que debería tener.

Lo que mueve el saldo del camión, y de dónde se lee:
- **Pedido aprobado** (+): `DetallePedido.cantidad_aprobada`, a la fecha de
  aprobación.
- **Asignación de agregado** (+): `AsignacionAgregado` no anulada (la anulada
  devolvió las bolsas, así que neta es cero). Las del mismo día van juntas en
  una columna.
- **Liquidación** (−): `ConsumoMaterialSuministro`. No guarda el camión: se
  descontó del camión que tenía asignado quien liquidó ese día, así que se
  toman los consumos de los responsables del camión dentro de su periodo.
- **Consumo por Excel aprobado** (−): `DetalleConsumo` (la carga antigua).
- **Devolución aprobada** (−): `DetalleDevolucion.cantidad_aprobada`.
- **Inventario cerrado** (±): deja el saldo en lo contado; aquí va la
  diferencia (contado − teórico).
- **Traspaso**: no mueve material, cambia el responsable. Va como columna
  vacía para que se vea desde cuándo responde cada uno.

El saldo calculado se compara con el que tiene hoy el sistema; si no cuadran,
la diferencia sale en rojo.
"""
import io
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from .models import (
    AsignacionAgregado, ConsumoMaterialSuministro, DetalleConsumo,
    DetalleDevolucion, DetalleInventario, DetallePedido, Material, StockCamion,
    TraspasoCamion, UsuarioCamion,
)

ENTRA, SALE, AJUSTE, INFO = 'entra', 'sale', 'ajuste', 'info'


@dataclass
class Movimiento:
    fecha: date
    tipo: str            # "Pedido", "Liquidación", ...
    documento: str       # "N° 123", "SST 1234 · poste 567"
    responsable: str
    clase: str           # ENTRA, SALE, AJUSTE o INFO
    cantidades: dict = field(default_factory=dict)  # material_id -> Decimal (con signo)
    orden: int = 0


def _dia(valor):
    if isinstance(valor, datetime):
        return timezone.localdate(valor) if timezone.is_aware(valor) else valor.date()
    return valor


def _periodos(camion):
    """Quién fue responsable del camión y entre qué fechas."""
    return list(UsuarioCamion.objects.filter(camion=camion)
                .select_related('usuario').order_by('fecha_inicio'))


def _sst_de(liq):
    if liq.sst_externo:
        return liq.sst_externo
    if liq.suministro_id:
        for rel in liq.suministro.sst_suministros.all():
            return rel.sst.codigo or rel.sst.sst or ''
    return ''


def movimientos(camion):
    """Todos los movimientos del camión, del más viejo al más nuevo."""
    movs = {}

    def mov(clave, **datos):
        if clave not in movs:
            movs[clave] = Movimiento(**datos)
        return movs[clave]

    def sumar(m, material_id, cantidad):
        m.cantidades[material_id] = m.cantidades.get(material_id, Decimal('0')) + cantidad

    for d in (DetallePedido.objects
              .filter(pedido__camion=camion, pedido__estado='aprobado',
                      cantidad_aprobada__gt=0)
              .select_related('pedido__usuario')):
        p = d.pedido
        m = mov(('pedido', p.pk), fecha=p.fecha_aprobacion or p.fecha, tipo='Pedido',
                documento=f'N° {p.pk}', responsable=p.usuario.nombre, clase=ENTRA,
                orden=1)
        sumar(m, d.material_id, d.cantidad_aprobada)

    # Las asignaciones van una por material; en la matriz se juntan las del
    # mismo día en una sola columna, con todos sus números.
    for a in (AsignacionAgregado.objects
              .filter(camion=camion, anulada=False, cantidad__gt=0)
              .select_related('usuario').order_by('fecha', 'pk')):
        dia = _dia(a.fecha)
        m = mov(('agregado', dia), fecha=dia, tipo='Asignación', documento='',
                responsable='', clase=ENTRA, orden=2)
        m.documento = f'{m.documento}, {a.pk}' if m.documento else f'N° {a.pk}'
        if a.usuario.nombre not in m.responsable.split(', '):
            m.responsable = ', '.join(x for x in (m.responsable, a.usuario.nombre) if x)
        sumar(m, a.material_id, a.cantidad)

    filtro = Q(pk__in=[])
    for p in _periodos(camion):
        rango = Q(usuario_id=p.usuario_id, fecha__gte=p.fecha_inicio)
        if p.fecha_fin:
            rango &= Q(fecha__lte=p.fecha_fin)
        filtro |= rango
    for c in (ConsumoMaterialSuministro.objects.filter(filtro, cantidad__gt=0)
              .select_related('liquidacion__suministro', 'liquidacion__tipo_trabajo',
                              'usuario')
              .prefetch_related('liquidacion__suministro__sst_suministros__sst')):
        liq = c.liquidacion
        poste = (liq.suministro.numero_suministro if liq.suministro_id
                 else liq.suministro_externo)
        sst = _sst_de(liq)
        documento = ' · '.join(x for x in (f'SST {sst}' if sst else '',
                                           f'poste {poste}' if poste else '') if x)
        m = mov(('liquidacion', liq.pk), fecha=c.fecha, tipo='Liquidación',
                documento=documento or f'N° {liq.pk}', responsable=c.usuario.nombre,
                clase=SALE, orden=3)
        sumar(m, c.material_id, -c.cantidad)

    for d in (DetalleConsumo.objects
              .filter(consumo__camion=camion, consumo__upload__estado='aprobado')
              .select_related('consumo__usuario_consume')):
        co = d.consumo
        m = mov(('consumo', co.pk), fecha=co.fecha, tipo='Consumo (Excel)',
                documento=f'poste {co.suministro}' if co.suministro else f'N° {co.pk}',
                responsable=co.usuario_consume.nombre, clase=SALE, orden=4)
        sumar(m, d.material_id, -Decimal(d.cantidad))

    for d in (DetalleDevolucion.objects
              .filter(devolucion__camion=camion, devolucion__estado='aprobado',
                      cantidad_aprobada__gt=0)
              .select_related('devolucion__usuario')):
        dv = d.devolucion
        m = mov(('devolucion', dv.pk), fecha=dv.fecha_aprobacion or dv.fecha,
                tipo='Devolución', documento=f'N° {dv.pk}',
                responsable=dv.usuario.nombre, clase=SALE, orden=5)
        sumar(m, d.material_id, -d.cantidad_aprobada)

    for d in (DetalleInventario.objects
              .filter(inventario__camion=camion, inventario__estado='cerrado')
              .exclude(diferencia=0)
              .select_related('inventario__usuario')):
        inv = d.inventario
        m = mov(('inventario', inv.pk), fecha=inv.fecha, tipo='Inventario',
                documento=f'N° {inv.pk} (contado − teórico)',
                responsable=inv.usuario.nombre, clase=AJUSTE, orden=6)
        sumar(m, d.material_id, d.diferencia)

    for t in (TraspasoCamion.objects.filter(camion=camion)
              .select_related('usuario_entrega', 'usuario_recibe')):
        mov(('traspaso', t.pk), fecha=t.fecha, tipo='Traspaso',
            documento=f'{t.usuario_entrega.nombre} → {t.usuario_recibe.nombre}',
            responsable=t.usuario_recibe.nombre, clase=INFO, orden=7)

    return sorted(movs.values(), key=lambda m: (m.fecha, m.orden, m.documento))


def matriz(camion):
    """Las filas de la matriz: por material, cada movimiento y los totales."""
    movs = movimientos(camion)
    actual = {s.material_id: s.cantidad
              for s in StockCamion.objects.filter(camion=camion)}
    ids = set(actual)
    for m in movs:
        ids |= set(m.cantidades)
    materiales = Material.objects.in_bulk(ids)
    filas = []
    for mid in sorted(ids, key=lambda i: materiales[i].matricula):
        celdas = [m.cantidades.get(mid) for m in movs]
        if not any(celdas) and not actual.get(mid):
            continue
        totales = defaultdict(lambda: Decimal('0'))
        for m, c in zip(movs, celdas):
            if c:
                totales[m.clase] += c
        calculado = totales[ENTRA] + totales[SALE] + totales[AJUSTE]
        en_sistema = actual.get(mid, Decimal('0'))
        filas.append({
            'matricula': materiales[mid].matricula,
            'descripcion': materiales[mid].descripcion,
            'celdas': celdas,
            'entra': totales[ENTRA],
            'sale': -totales[SALE],
            'ajuste': totales[AJUSTE],
            'calculado': calculado,
            'en_sistema': en_sistema,
            'diferencia': en_sistema - calculado,
        })
    return movs, filas


def matriz_excel(camion):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    movs, filas = matriz(camion)
    colores = {ENTRA: 'C6EFCE', SALE: 'F8CBAD', AJUSTE: 'FFEB9C', INFO: 'DDDDDD'}
    gris = PatternFill('solid', fgColor='DDDDDD')
    azul = PatternFill('solid', fgColor='BDD7EE')
    rojo = PatternFill('solid', fgColor='FF9999')
    negrita = Font(bold=True)
    centro = Alignment(horizontal='center', vertical='center', wrap_text=True)
    fina = Side(style='thin', color='999999')
    borde = Border(left=fina, right=fina, top=fina, bottom=fina)

    def n(x):
        return float(x) if isinstance(x, Decimal) else x

    responsable = (UsuarioCamion.objects.filter(camion=camion, activo=True)
                   .filter(Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=date.today()))
                   .select_related('usuario').first())

    wb = Workbook()
    ws = wb.active
    ws.title = 'Matriz'
    ws['A1'] = f'Saldo del camión {camion.placa}'
    ws['A1'].font = Font(bold=True, size=13)
    ws['A2'] = (f'Responsable: {responsable.usuario.nombre if responsable else "sin asignar"}'
                f' · Al {date.today():%d/%m/%Y} · Verde entra, rojo sale, amarillo '
                f'ajuste de inventario, gris traspaso')

    # Tres filas de encabezado: fecha, qué fue y el documento.
    inicio = 3  # la primera columna de movimientos
    totales = ['Total entró', 'Total salió', 'Ajustes', 'Saldo calculado',
               'Saldo en sistema', 'Diferencia']
    for fila, (a, b) in zip((4, 5, 6), (('', ''), ('', ''), ('Matrícula', 'Material'))):
        ws.cell(fila, 1, a)
        ws.cell(fila, 2, b)
    for i, m in enumerate(movs):
        col = inicio + i
        relleno = PatternFill('solid', fgColor=colores[m.clase])
        for fila, valor in ((4, m.fecha.strftime('%d/%m/%Y')), (5, m.tipo),
                            (6, f'{m.documento}\n{m.responsable}')):
            celda = ws.cell(fila, col, valor)
            celda.fill = relleno
            celda.font = negrita
            celda.alignment = centro
            celda.border = borde
        ws.column_dimensions[get_column_letter(col)].width = 14
    fin = inicio + len(movs)
    for j, titulo in enumerate(totales):
        col = fin + j
        ws.merge_cells(start_row=4, start_column=col, end_row=6, end_column=col)
        celda = ws.cell(4, col, titulo)
        celda.fill = azul
        celda.font = negrita
        celda.alignment = centro
        ws.column_dimensions[get_column_letter(col)].width = 12
    for fila in (4, 5, 6):
        for col in (1, 2):
            ws.cell(fila, col).fill = gris
            ws.cell(fila, col).font = negrita
    ws.row_dimensions[6].height = 45
    ws.column_dimensions['A'].width = 12
    ws.column_dimensions['B'].width = 38

    for r, f in enumerate(filas, start=7):
        ws.cell(r, 1, f['matricula'])
        ws.cell(r, 2, f['descripcion'])
        for i, c in enumerate(f['celdas']):
            if c:
                ws.cell(r, inicio + i, n(c)).border = borde
        for j, clave in enumerate(('entra', 'sale', 'ajuste', 'calculado',
                                   'en_sistema', 'diferencia')):
            celda = ws.cell(r, fin + j, n(f[clave]))
            celda.border = borde
            if clave in ('calculado', 'en_sistema'):
                celda.font = negrita
        if f['diferencia']:
            ws.cell(r, fin + 5).fill = rojo
    if not filas:
        ws.cell(7, 1, 'El camión no tiene movimientos de material.')
    ws.freeze_panes = ws.cell(7, inicio)

    # La misma historia en lista, con el saldo que iba quedando: para filtrar
    # por material o por fecha.
    wk = wb.create_sheet('Movimientos')
    wk.append(['Fecha', 'Movimiento', 'Documento', 'Responsable', 'Matrícula',
               'Material', 'Cantidad', 'Saldo después'])
    for celda in wk[1]:
        celda.font = negrita
        celda.fill = gris
    materiales = {f['matricula']: f['descripcion'] for f in filas}
    matricula_de = dict(Material.objects.filter(
        pk__in={mid for m in movs for mid in m.cantidades})
        .values_list('pk', 'matricula'))
    saldo = defaultdict(lambda: Decimal('0'))
    for m in movs:
        if m.clase == INFO:
            wk.append([m.fecha, m.tipo, m.documento, m.responsable])
            continue
        for mid, c in sorted(m.cantidades.items(), key=lambda x: matricula_de[x[0]]):
            saldo[mid] += c
            mat = matricula_de[mid]
            wk.append([m.fecha, m.tipo, m.documento, m.responsable, mat,
                       materiales.get(mat, ''), n(c), n(saldo[mid])])
    for i, ancho in enumerate([11, 16, 30, 24, 12, 38, 10, 13], 1):
        wk.column_dimensions[get_column_letter(i)].width = ancho
    for celda in wk['A'][1:]:
        celda.number_format = 'DD/MM/YYYY'
    wk.freeze_panes = 'A2'
    wk.auto_filter.ref = wk.dimensions

    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()
