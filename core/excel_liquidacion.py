"""Liquidación de material y mano de obra en la plantilla de Tecsur.

La plantilla es la misma que se llenaba a mano (Liquidacion.xls), pasada a
.xlsx para poder escribirla. Solo se escriben los datos: las fórmulas, los
formatos y las demás hojas quedan como vienen.

- Carátula: SST, cliente, actividad, distrito, fechas, contratista y capataz.
- MATERIAL: la cantidad va en la columna del poste, desde AV (P1) hasta donde
  la plantilla siga rotulando P2, P3...
- MANO DE OBRA: igual, desde F (P1), que la plantilla suma en Cant. Con un
  solo poste -lo normal- todo cae en P1, como salía antes; en una reforma
  cada punto de trabajo tiene la suya. El encabezado P1, P2... se reemplaza
  por el número de cada poste, en el orden en que se grabaron.
- Cables: los metros de cable de hasta 35 mm2, un tramo del plano por vano y
  desde la columna I hacia la derecha. Lo instalado va en la fila 52 y lo
  trasladado en la 53, como las rotula la plantilla.
- Vereda: largo y ancho de cada paño del plano, desde C5 y D5 hacia abajo.
- Traslado - Acarreo: los tramos de arrastre del poste, uno por columna, en la
  fila 4 (lo ejecutado) y en la fila 5 (lo que se cobra, con el descuento de
  los 100 metros incluidos). El bloque de acarreo de abajo se llena solo: la
  plantilla trae C19 = C4, C20 = D4, y así.

Lo que la plantilla no trae listado se agrega en las filas libres de cada hoja.
"""
import io
import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

PLANTILLA = Path(__file__).resolve().parent / 'data' / 'plantilla_liquidacion.xlsx'

# Hoja MATERIAL
MAT_PRIMERA, MAT_ULTIMA = 14, 170
# Una columna por poste, desde la primera: cuáles son se leen de la plantilla
# (ver `_columnas_de_postes`). Con más postes que columnas, la última se lleva
# el resto para que el total siga cuadrando.
MAT_POSTES = ('AV', 'AW', 'AX')
# La fila donde la plantilla rotula esas columnas como P1, P2 y P3.
MAT_ENCABEZADO = 13
# Hoja MANO DE OBRA
MO_PRIMERA, MO_ULTIMA = 7, 112
MO_POSTES = ('F', 'G', 'H')
MO_ENCABEZADO = 6
# Hoja Cables: la plantilla rotula la fila 52 como instalación y la 53 como
# traslado, cada una con seis vanos que suma su columna O.
CABLES_INSTALADO = 52
CABLES_FILA = 53
CABLES_VANOS = ['I', 'J', 'K', 'L', 'M', 'N']
# Los calibres de hasta 35 mm2, como aparecen en la descripción del plano:
# "3x16" también encuentra al "3x16+1x16".
CABLES_HASTA_35 = ('2x16', '3x16', '3x35')
# Hoja Traslado - Acarreo. La fila 4 es el traslado del poste retirado y la 5
# el del instalado; de C a K van los adicionales y L suma la fila.
TRASLADO_EJECUTADO = 4
TRASLADO_COBRADO = 5
TRASLADO_COLUMNAS = ('C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K')
# El cambio de poste ya trae 100 metros: el descuento va al final de la fila.
TRASLADO_INCLUIDO = 100
TRASLADO_DESCUENTO = 'K5'

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


def generar_excel_liquidacion(encabezado, materiales, partidas,
                              elementos_plano=(), materiales_por_poste=(),
                              partidas_por_poste=(), postes=()):
    """`encabezado`: sst, actividad, distrito, fecha (date o None), contratista,
    capataz. `materiales` y `partidas`: listas de Item de cuaderno_obra, con el
    total de la SST. `elementos_plano`: lo guardado en el plano de la SST.

    `materiales_por_poste` y `partidas_por_poste` son listas de listas de Item,
    una por punto de trabajo. Con uno solo no hacen falta: el total ya va en su
    columna. `postes` son sus números, en el mismo orden, para rotular las
    columnas que la plantilla trae como P1, P2 y P3."""
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

    _membrete_de_impresion(wb['MATERIAL'])
    mat_columnas = _columnas_de_postes(
        wb['MATERIAL'], MAT_ENCABEZADO, MAT_POSTES[0])
    mo_columnas = _columnas_de_postes(
        wb['MANO DE OBRA'], MO_ENCABEZADO, MO_POSTES[0])
    _llenar_material(wb['MATERIAL'], materiales, materiales_por_poste,
                     mat_columnas)
    _llenar_mano_de_obra(wb['MANO DE OBRA'], partidas, partidas_por_poste,
                         mo_columnas)
    _rotular_postes(wb['MATERIAL'], MAT_ENCABEZADO, mat_columnas, postes)
    _rotular_postes(wb['MANO DE OBRA'], MO_ENCABEZADO, mo_columnas, postes)
    _llenar_cables(wb['Cables'], elementos_plano)
    _llenar_veredas(wb['Vereda'], elementos_plano)
    _llenar_traslado_acarreo(wb['Traslado - Acarreo'], elementos_plano)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _llenar_material(ws, materiales, por_poste=(), columnas=None):
    columnas = columnas or _columnas_de_postes(ws, MAT_ENCABEZADO, MAT_POSTES[0])
    escritas = []
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
        ws[f'{columnas[0]}{fila}'] = float(m.cantidad)
        escritas.append(fila)
    _por_columna(ws, filas, por_poste, columnas, escritas)


def _membrete_de_impresion(ws):
    """Repone el encabezado y el pie de página de la hoja al imprimirla.

    La plantilla los trae, pero openpyxl no sabe leer el pie 'Página &P de &N'
    -no dice en qué sección va- y descarta el bloque entero, membrete
    incluido. La hoja se imprime y se entrega, así que se vuelve a poner."""
    ws.oddHeader.left.text = 'TECSUR  S.A.'
    ws.oddHeader.left.font = 'Arial,Negrita'
    ws.oddHeader.left.size = 9
    ws.oddFooter.left.text = 'Página &[Page] de &[Pages]'


def _columnas_de_postes(ws, fila, primera):
    """Las columnas de postes de la plantilla, contando desde `primera` hacia
    la derecha mientras el encabezado siga diciendo P1, P2, P3...

    Se leen de la hoja y no se fijan aquí a propósito: si a la plantilla se le
    insertan columnas para más postes y se rotulan igual, el Excel las usa
    solas. Insertarlas *dentro* del bloque es lo que hace que Excel estire sus
    propias fórmulas de suma."""
    salida = []
    columna = column_index_from_string(primera)
    while True:
        valor = str(ws.cell(row=fila, column=columna).value or '').strip()
        if not re.fullmatch(r'P\s*\d+', valor, re.I):
            break
        salida.append(get_column_letter(columna))
        columna += 1
    return tuple(salida) or (primera,)


def _columna_con(ws, fila, titulo):
    """La columna cuyo encabezado dice `titulo`, o None.

    Sirve para no tener fijas en el código las columnas que se corren si a la
    plantilla se le insertan las de más postes."""
    objetivo = titulo.strip().lower()
    for celda in ws[fila]:
        if str(celda.value or '').strip().lower() == objetivo:
            return celda.column_letter
    return None


def _rotular_postes(ws, fila, columnas, postes):
    """Cambia los P1, P2 y P3 de la plantilla por el número de cada poste.

    Van en el orden en que se grabaron, que es el orden de las columnas. Si
    hay más postes que columnas, la última los nombra a todos, porque es la
    que se lleva sus cantidades sumadas."""
    if not postes:
        return
    ultima = len(columnas) - 1
    nombres = {}
    for i, numero in enumerate(postes):
        if not numero:
            continue
        columna = columnas[min(i, ultima)]
        nombres.setdefault(columna, []).append(str(numero))
    for columna, quienes in nombres.items():
        ws[f'{columna}{fila}'] = ' + '.join(quienes)


def _por_columna(ws, filas, por_poste, columnas, escritas):
    """Reparte lo de cada poste en su columna.

    Sin postes que repartir no se toca nada: queda el total en la primera
    columna, que es como sale una SST de un solo poste. Con más postes que
    columnas, la última se lleva la suma del resto, para que el total de la
    fila siga cuadrando."""
    if len(por_poste) < 2:
        return
    ultima = len(columnas) - 1
    acumulado = {}
    for i, items in enumerate(por_poste):
        columna = columnas[min(i, ultima)]
        for item in items:
            fila = filas.get(_clave(item.codigo))
            if fila is None:
                continue
            clave = (columna, fila)
            acumulado[clave] = acumulado.get(clave, 0) + float(item.cantidad)
    # El total quedó en la primera columna: se borra antes de repartirlo, y
    # solo en las filas que se escribieron.
    for fila in escritas:
        ws[f'{columnas[0]}{fila}'] = None
    for (columna, fila), cantidad in acumulado.items():
        ws[f'{columna}{fila}'] = cantidad


def _llenar_mano_de_obra(ws, partidas, por_poste=(), columnas=None):
    columnas = columnas or _columnas_de_postes(ws, MO_ENCABEZADO, MO_POSTES[0])
    # Las columnas de la derecha se corren si a la plantilla se le insertan
    # columnas de postes, así que se buscan por su rótulo.
    suma = _columna_con(ws, MO_ENCABEZADO, 'Cant.') or 'I'
    final = _columna_con(ws, MO_ENCABEZADO, 'Cant. Final') or 'L'
    total = _columna_con(ws, MO_ENCABEZADO, 'Total Final') or 'M'
    escritas = []
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
            ws[f'{suma}{fila}'] = (
                f'=SUM({columnas[0]}{fila}:{columnas[-1]}{fila})')
            ws[f'{final}{fila}'] = f'={suma}{fila}'
            ws[f'{total}{fila}'] = (
                f'=IF(A{fila}=0,"",({final}{fila}*$E{fila}))')
            filas[_clave(p.codigo)] = fila
        ws[f'{columnas[0]}{fila}'] = float(p.cantidad)
        escritas.append(fila)
    _por_columna(ws, filas, por_poste, columnas, escritas)


def tramos_hasta_35(elementos_plano, estado='T'):
    """Metros de cada tramo de cable de hasta 35 mm2, en el orden en que se
    dibujaron. Por defecto los trasladados; con estado='I', los instalados."""
    return [float(e.get('metros') or 0) for e in elementos_plano
            if e.get('tipo') == 'cable' and e.get('estado') == estado
            and any(c in (e.get('descripcion') or '').lower() for c in CABLES_HASTA_35)]


def _llenar_cables(ws, elementos_plano):
    _vanos(ws, CABLES_FILA, tramos_hasta_35(elementos_plano))
    _vanos(ws, CABLES_INSTALADO,
           tramos_hasta_35(elementos_plano, estado='I'))


def _vanos(ws, fila, tramos):
    """Un tramo por vano. La plantilla trae seis: si hay más tramos, el último
    vano se lleva el resto, para que el total de la fila siga siendo el del
    plano. Se suma aparte y se escribe al final, porque la plantilla ya trae
    ceros en esas celdas."""
    if not tramos:
        return
    ultimo = len(CABLES_VANOS) - 1
    por_vano = {}
    for i, metros in enumerate(tramos):
        columna = CABLES_VANOS[min(i, ultimo)]
        por_vano[columna] = por_vano.get(columna, 0) + metros
    for columna, metros in por_vano.items():
        ws[f'{columna}{fila}'] = metros


def tramos_de_arrastre(elementos_plano):
    """Los metros de cada tramo de arrastre dibujado en el plano."""
    return [float(e.get('metros') or 0) for e in elementos_plano
            if e.get('tipo') == 'cable' and e.get('estado') == 'A'
            and float(e.get('metros') or 0) > 0]


def _escribir_tramos(ws, fila, columnas, tramos):
    """Un tramo por columna. Si hay más tramos que columnas, la última se lleva
    la suma de lo que sobra, para que el total de la fila siga siendo el del
    plano."""
    ultima = len(columnas) - 1
    for i, metros in enumerate(tramos):
        celda = f'{columnas[min(i, ultima)]}{fila}'
        ws[celda] = (ws[celda].value or 0) + metros if i > ultima else metros


def _llenar_traslado_acarreo(ws, elementos_plano):
    """El arrastre del poste: lo ejecutado arriba y lo cobrable debajo.

    Los primeros 100 metros van incluidos en el cambio de poste, así que la
    fila de cobro solo se escribe cuando el total los pasa, y el descuento va
    en K5. El bloque de acarreo de abajo no se toca: la plantilla lo calcula
    desde la fila 4 y lo multiplica por los seis viajes."""
    tramos = tramos_de_arrastre(elementos_plano)
    if not tramos:
        return
    _escribir_tramos(ws, TRASLADO_EJECUTADO, TRASLADO_COLUMNAS, tramos)
    if sum(tramos) > TRASLADO_INCLUIDO:
        # K5 queda para el descuento, así que la fila de cobro tiene una
        # columna menos que la de arriba.
        _escribir_tramos(ws, TRASLADO_COBRADO, TRASLADO_COLUMNAS[:-1], tramos)
        ws[TRASLADO_DESCUENTO] = -TRASLADO_INCLUIDO


def _llenar_veredas(ws, elementos_plano):
    panos = [e for e in elementos_plano if e.get('tipo') == 'vereda']
    for fila, pano in zip(range(VEREDA_PRIMERA, VEREDA_ULTIMA + 1), panos):
        ws[f'C{fila}'] = float(pano.get('largo') or 0)
        ws[f'D{fila}'] = float(pano.get('ancho') or 0)
