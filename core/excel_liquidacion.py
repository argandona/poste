"""Liquidación de material y mano de obra en la plantilla de Tecsur.

La plantilla es la misma que se llenaba a mano (Liquidacion.xls), pasada a
.xlsx para poder escribirla. Solo se escriben los datos: las fórmulas, los
formatos y las demás hojas quedan como vienen.

- Carátula: SST, cliente, actividad, distrito, fechas, contratista y capataz.
- MATERIAL: la cantidad va en la columna AV.
- MANO DE OBRA: la cantidad va en P1 (columna F), que suma la columna Cant.
- Cables: los metros de cable de hasta 35 mm2 trasladado, un tramo del plano
  por vano, desde I53 hacia la derecha.
- Vereda: largo y ancho de cada paño del plano, desde C5 y D5 hacia abajo.

Lo que la plantilla no trae listado se agrega en las filas libres de cada hoja.
"""
import io
from pathlib import Path

from openpyxl import load_workbook

PLANTILLA = Path(__file__).resolve().parent / 'data' / 'plantilla_liquidacion.xlsx'

# Hoja MATERIAL
MAT_PRIMERA, MAT_ULTIMA = 14, 170
MAT_CANTIDAD = 'AV'
# Hoja MANO DE OBRA
MO_PRIMERA, MO_ULTIMA = 7, 112
MO_CANTIDAD = 'F'
# Hoja Cables: fila de traslado y sus seis vanos (O53 los suma).
CABLES_FILA = 53
CABLES_VANOS = ['I', 'J', 'K', 'L', 'M', 'N']
# Los calibres de hasta 35 mm2, como aparecen en la descripción del plano:
# "3x16" también encuentra al "3x16+1x16".
CABLES_HASTA_35 = ('2x16', '3x16', '3x35')
# Hoja Vereda: un paño por fila.
VEREDA_PRIMERA, VEREDA_ULTIMA = 5, 218


def _clave(valor):
    """La matrícula como texto, venga como número (5331596.0) o como texto."""
    if valor is None:
        return ''
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip().upper()


def _como_en_plantilla(codigo):
    """Las matrículas numéricas se guardan como número, igual que en la
    plantilla; así las fórmulas que las buscan las siguen encontrando."""
    return int(codigo) if str(codigo).isdigit() else codigo


def _hoja_carátula(wb):
    for ws in wb.worksheets:
        if ws.title.strip().lower() == 'caratula':
            return ws
    return wb.worksheets[0]


def generar_excel_liquidacion(encabezado, materiales, partidas, elementos_plano=()):
    """`encabezado`: sst, actividad, distrito, fecha (date o None), contratista,
    capataz. `materiales` y `partidas`: listas de Item de cuaderno_obra.
    `elementos_plano`: lo guardado en el plano de la SST."""
    wb = load_workbook(PLANTILLA)

    car = _hoja_carátula(wb)
    car['C8'] = encabezado['sst']
    car['C10'] = 'TECSUR'
    car['C12'] = encabezado.get('actividad', '')
    car['C14'] = encabezado.get('distrito', '')
    car['H14'] = encabezado.get('distrito', '')
    if encabezado.get('fecha'):
        for celda in ('C16', 'C18'):
            car[celda] = encabezado['fecha']
            car[celda].number_format = 'DD/MM/YYYY'
    car['H16'] = encabezado.get('contratista', '')
    car['H18'] = encabezado.get('capataz', '')

    _llenar_material(wb['MATERIAL'], materiales)
    _llenar_mano_de_obra(wb['MANO DE OBRA'], partidas)
    _llenar_cables(wb['Cables'], elementos_plano)
    _llenar_veredas(wb['Vereda'], elementos_plano)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _llenar_material(ws, materiales):
    filas = {}
    libres = []
    for fila in range(MAT_PRIMERA, MAT_ULTIMA + 1):
        clave = _clave(ws[f'A{fila}'].value)
        if clave:
            filas.setdefault(clave, fila)
        elif fila > 100:
            libres.append(fila)
    for m in materiales:
        fila = filas.get(_clave(m.codigo))
        if fila is None:
            if not libres:
                continue
            fila = libres.pop(0)
            ws[f'A{fila}'] = _como_en_plantilla(m.codigo)
            ws[f'C{fila}'] = m.descripcion
            ws[f'D{fila}'] = float(m.precio)
            filas[_clave(m.codigo)] = fila
        ws[f'{MAT_CANTIDAD}{fila}'] = float(m.cantidad)


def _llenar_mano_de_obra(ws, partidas):
    filas = {}
    libres = []
    for fila in range(MO_PRIMERA, MO_ULTIMA + 1):
        clave = _clave(ws[f'A{fila}'].value)
        if clave:
            filas.setdefault(clave, fila)
        else:
            libres.append(fila)
    for p in partidas:
        fila = filas.get(_clave(p.codigo))
        if fila is None:
            if not libres:
                continue
            fila = libres.pop(0)
            ws[f'A{fila}'] = p.codigo
            ws[f'B{fila}'] = 'I'
            ws[f'C{fila}'] = p.descripcion
            ws[f'E{fila}'] = float(p.precio)
            ws[f'I{fila}'] = f'=SUM(F{fila}:H{fila})'
            ws[f'L{fila}'] = f'=I{fila}'
            ws[f'M{fila}'] = f'=IF(A{fila}=0,"",(L{fila}*$E{fila}))'
            filas[_clave(p.codigo)] = fila
        ws[f'{MO_CANTIDAD}{fila}'] = float(p.cantidad)


def tramos_hasta_35(elementos_plano):
    """Metros de cada tramo de cable de hasta 35 mm2 trasladado, en el orden
    en que se dibujaron."""
    return [float(e.get('metros') or 0) for e in elementos_plano
            if e.get('tipo') == 'cable' and e.get('estado') == 'T'
            and any(c in (e.get('descripcion') or '').lower() for c in CABLES_HASTA_35)]


def _llenar_cables(ws, elementos_plano):
    tramos = tramos_hasta_35(elementos_plano)
    # La plantilla trae seis vanos. Si hay más tramos, el último vano se
    # lleva el resto, para que el total de la fila siga siendo el del plano.
    ultimo = len(CABLES_VANOS) - 1
    for i, metros in enumerate(tramos):
        celda = f'{CABLES_VANOS[min(i, ultimo)]}{CABLES_FILA}'
        ws[celda] = (ws[celda].value or 0) + metros if i > ultimo else metros


def _llenar_veredas(ws, elementos_plano):
    panos = [e for e in elementos_plano if e.get('tipo') == 'vereda']
    for fila, pano in zip(range(VEREDA_PRIMERA, VEREDA_ULTIMA + 1), panos):
        ws[f'C{fila}'] = float(pano.get('largo') or 0)
        ws[f'D{fila}'] = float(pano.get('ancho') or 0)
