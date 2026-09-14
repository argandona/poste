"""Formato TS-REC-FR-001, Registro de Materiales de Recupero.

Es un formato oficial de Tecsur, así que se calca: mismas tablas, mismos anchos
de columna, mismos tamaños de letra y los 28 renglones de la plantilla, aunque
sobren. Las medidas salen del propio .docx, convertidas de twips a centímetros.
Lo único que la app agrega es el llenado y la firma.
"""
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

RENGLONES = 28

# Anchos del formato original, en twips, pasados a centímetros.
_TWIP = 2.54 / 1440


def _cm(twips):
    return twips * _TWIP * cm


ANCHO_TOTAL = _cm(10333)
COL_ENCABEZADO = [_cm(1700), _cm(6300), _cm(2333)]
COL_LISTADO = [_cm(500), _cm(5900), _cm(900), _cm(1100), _cm(1933)]

_NEGRO = colors.HexColor('#000000')


def _estilos():
    base = ParagraphStyle('base', fontName='Helvetica', fontSize=8, leading=9.6,
                          textColor=_NEGRO)

    def variante(nombre, tamano, negrita=False, centrado=False, cursiva=False):
        fuente = 'Helvetica'
        if negrita:
            fuente = 'Helvetica-Bold'
        elif cursiva:
            fuente = 'Helvetica-Oblique'
        return ParagraphStyle(nombre, parent=base, fontName=fuente,
                              fontSize=tamano, leading=tamano * 1.2,
                              alignment=1 if centrado else 0)

    return {
        'marca':     variante('marca', 13, negrita=True, centrado=True),
        'codigo':    variante('codigo', 7),
        'titulo':    variante('titulo', 11, negrita=True, centrado=True),
        'campo':     variante('campo', 8, negrita=True),
        'listado':   variante('listado', 10, negrita=True, centrado=True),
        'thCentro':  variante('thCentro', 8, negrita=True, centrado=True),
        'tdCentro':  variante('tdCentro', 8, centrado=True),
        'td':        variante('td', 8),
        'nota':      variante('nota', 7.5, negrita=True),
        'verifica':  variante('verifica', 9, negrita=True, centrado=True),
        'firmaPie':  variante('firmaPie', 8, negrita=True, centrado=True),
        'firma':     variante('firma', 15, cursiva=True, centrado=True),
        'trazable':  ParagraphStyle('trazable', parent=base, fontSize=6.5,
                                    leading=8, alignment=1,
                                    textColor=colors.HexColor('#616161')),
    }


def nombre_de_firma(nombre_completo):
    """Primer nombre y primer apellido, que es como se firma.

    De "Juan Carlos Pérez Rojas" sale "Juan Pérez".
    """
    partes = [p for p in (nombre_completo or '').split() if p]
    if not partes:
        return ''
    if len(partes) == 1:
        return partes[0]
    # Con dos nombres y dos apellidos, el apellido es la tercera palabra.
    apellido = partes[2] if len(partes) >= 4 else partes[-1]
    return f'{partes[0]} {apellido}'


def _borde(tabla, extra=()):
    tabla.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.75, _NEGRO),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        *extra,
    ]))
    return tabla


def _cabecera(es):
    """Franja del formato: marca, la palabra FORMATO, y el bloque de control.
    El título va en la segunda fila de esta misma tabla, como en el original."""
    codigo = Paragraph(
        'Código&nbsp;&nbsp;&nbsp;: TS-REC-FR-001<br/>'
        'Versión&nbsp;&nbsp;: 01<br/>'
        'Aprobado : GO<br/>'
        'Fecha&nbsp;&nbsp;&nbsp;&nbsp;: 26/01/2024<br/>'
        'Página&nbsp;&nbsp;&nbsp;: 1 de 1', es['codigo'])
    filas = [
        [Paragraph('Tecsur', es['marca']),
         Paragraph('FORMATO', es['marca']),
         codigo],
        ['',
         Paragraph('REGISTRO DE MATERIALES DE RECUPERO', es['titulo']),
         ''],
    ]
    return _borde(Table(filas, colWidths=COL_ENCABEZADO))


def _datos(d, es):
    """Los siete campos, en tres renglones dentro de una sola celda."""
    def campo(etiqueta, valor, relleno=26):
        texto = valor or '&nbsp;' * relleno
        return f'{etiqueta}: {texto}'

    parrafos = [
        Paragraph('&nbsp;&nbsp;&nbsp;&nbsp;'.join([
            campo('N° SST', d['sst']),
            campo('FECHA', d['fecha']),
            campo('DEPARTAMENTO', d['departamento']),
        ]), es['campo']),
        Paragraph('&nbsp;&nbsp;&nbsp;&nbsp;'.join([
            campo('CONTRATISTA', d['contratista']),
            campo('REPORTADO POR', d['reportado_por']),
        ]), es['campo']),
        Paragraph('&nbsp;&nbsp;&nbsp;&nbsp;'.join([
            campo('CAPATAZ', d['capataz']),
            campo('CARGO', d['cargo']),
        ]), es['campo']),
    ]
    return _borde(Table([[parrafos]], colWidths=[ANCHO_TOTAL]),
                  extra=[('TOPPADDING', (0, 0), (-1, -1), 5),
                         ('BOTTOMPADDING', (0, 0), (-1, -1), 5)])


def _listado(items, es):
    filas = [[Paragraph(t, es['thCentro']) for t in
              ('N°', 'DESCRIPCIÓN', 'UND.', 'CANTIDAD', 'OBSERVACIÓN')]]
    for i in range(RENGLONES):
        item = items[i] if i < len(items) else None
        filas.append([
            Paragraph(str(i + 1), es['tdCentro']),
            Paragraph(item['descripcion'] if item else '', es['td']),
            Paragraph(item['unidad'] if item else '', es['tdCentro']),
            Paragraph(item['cantidad'] if item else '', es['tdCentro']),
            '',  # la observación casi nunca se llena; se deja para la mano
        ])
    return _borde(
        Table(filas, colWidths=COL_LISTADO, repeatRows=1),
        extra=[('TOPPADDING', (0, 1), (-1, -1), 2),
               ('BOTTOMPADDING', (0, 1), (-1, -1), 2)])


def generar_pdf_recupero(datos, items):
    """Arma el formato. `datos` trae el encabezado y la firma; `items`, los
    recuperos ya sumados, cada uno con descripcion, unidad y cantidad."""
    buffer = io.BytesIO()
    margen = (A4[0] - ANCHO_TOTAL) / 2
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=margen, rightMargin=margen,
        topMargin=1.2 * cm, bottomMargin=1.2 * cm,
        title=f'Registro de materiales de recupero {datos["sst"]}',
    )
    es = _estilos()
    doc.build([
        _cabecera(es),
        _datos(datos, es),
        Spacer(1, 8),
        _borde(Table([[Paragraph('LISTADO', es['listado'])]],
                     colWidths=[ANCHO_TOTAL])),
        _listado(items, es),
        Spacer(1, 6),
        Paragraph(
            'Materiales de Recupero: Se consideran a todos los materiales que '
            'son retirados durante la ejecución y finalización de la obra, '
            'debiendo ser entregados al Almacén de Reciclaje de Tecsur por las '
            'Contratistas.', es['nota']),
        Paragraph(
            'Ejemplo: Cables, Fierro, Luminarias, Seccionadores, Interruptores, '
            'Aisladores, etc.', es['nota']),
        Spacer(1, 6),
        _borde(Table([[Paragraph('VERIFICACIÓN Y CONFORMIDAD DE LAS ACCIONES',
                                 es['verifica'])]],
                     colWidths=[ANCHO_TOTAL])),
        Spacer(1, 18),
        Paragraph(datos['firma'], es['firma']),
        Paragraph('FIRMA CAPATAZ', es['firmaPie']),
        Paragraph(datos['firma_pie'], es['trazable']),
    ])
    return buffer.getvalue()


def fecha_larga(f=None):
    f = f or date.today()
    return f.strftime('%d/%m/%Y')
