"""Liquidación de material y mano de obra en la plantilla de Tecsur.

La plantilla es la misma que se llenaba a mano (Liquidacion.xls), pasada a
.xlsx para poder escribirla. Solo se escriben los datos: las fórmulas, los
formatos y las demás hojas quedan como vienen.

- Carátula: SST, cliente, actividad, distrito, fechas, contratista y capataz.
- MATERIAL: la cantidad va en BT/AER. (columna AU), que es la que suma el
  total de la fila para una obra aérea de baja tensión.
- MANO DE OBRA: la cantidad va en P1 (columna F), que suma la columna Cant.

Lo que la plantilla no trae listado se agrega en las filas libres de cada hoja.
"""
import io
from pathlib import Path

from openpyxl import load_workbook

PLANTILLA = Path(__file__).resolve().parent / 'data' / 'plantilla_liquidacion.xlsx'

# Hoja MATERIAL
MAT_PRIMERA, MAT_ULTIMA = 14, 170
MAT_CANTIDAD = 'AU'
# Hoja MANO DE OBRA
MO_PRIMERA, MO_ULTIMA = 7, 112
MO_CANTIDAD = 'F'


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


def generar_excel_liquidacion(encabezado, materiales, partidas):
    """`encabezado`: sst, actividad, distrito, fecha (date o None), contratista,
    capataz. `materiales` y `partidas`: listas de Item de cuaderno_obra."""
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
