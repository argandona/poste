"""Genera el formato TS-REC-FR-001, Registro de Materiales de Recupero.

Es el formato oficial de Tecsur, así que se respeta tal cual: mismo encabezado,
mismas columnas y los 28 renglones de la plantilla, aunque sobren. Lo que la
app aporta es el llenado: los recuperos que el capataz cargó en cada poste de
la SST, sumados por material.
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

# La plantilla tiene 28 renglones y se imprime aunque queden vacíos: así el
# capataz puede agregar a mano lo que aparezca después.
RENGLONES = 28

_NEGRO = colors.HexColor('#212121')
_GRIS  = colors.HexColor('#EEEEEE')


def _estilos():
    base = ParagraphStyle('base', fontName='Helvetica', fontSize=8,
                          leading=10, textColor=_NEGRO)
    return {
        'base': base,
        'celda': ParagraphStyle('celda', parent=base, fontSize=7.5, leading=9),
        'titulo': ParagraphStyle('titulo', parent=base, fontName='Helvetica-Bold',
                                 fontSize=12, leading=14, alignment=1),
        'cabecera': ParagraphStyle('cabecera', parent=base,
                                   fontName='Helvetica-Bold', fontSize=8),
        'pie': ParagraphStyle('pie', parent=base, fontSize=7, leading=9),
        'firma': ParagraphStyle('firma', parent=base,
                                fontName='Helvetica-Oblique', fontSize=14,
                                leading=16, alignment=1),
        'firmaPie': ParagraphStyle('firmaPie', parent=base, fontSize=6.5,
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
    # Con dos nombres y dos apellidos, el apellido es la penúltima palabra.
    apellido = partes[2] if len(partes) >= 4 else partes[-1]
    return f'{partes[0]} {apellido}'


def _encabezado(datos, es):
    """La franja del formato: código, versión y aprobación, tal cual."""
    marca = Paragraph('<b>Tecsur</b>', es['titulo'])
    formato = Paragraph('FORMATO', es['cabecera'])
    codigo = Paragraph(
        'Código&nbsp;&nbsp;&nbsp;: TS-REC-FR-001<br/>'
        'Versión&nbsp;&nbsp;: 01<br/>'
        'Aprobado : GO<br/>'
        'Fecha&nbsp;&nbsp;&nbsp;&nbsp;: 26/01/2024<br/>'
        'Página&nbsp;&nbsp;&nbsp;: 1 de 1',
        es['pie'])
    tabla = Table([[marca, formato, codigo]],
                  colWidths=[3.5 * cm, 9.5 * cm, 5 * cm])
    tabla.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.6, _NEGRO),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (1, 0), 'CENTER'),
        ('LEFTPADDING', (2, 0), (2, 0), 6),
    ]))
    return tabla


def _datos(datos, es):
    def campo(etiqueta, valor):
        return Paragraph(f'<b>{etiqueta}:</b> {valor or ""}', es['base'])

    filas = [
        [campo('N° SST', datos['sst']), campo('FECHA', datos['fecha']),
         campo('DEPARTAMENTO', datos['departamento'])],
        [campo('CONTRATISTA', datos['contratista']),
         campo('REPORTADO POR', datos['reportado_por']), ''],
        [campo('CAPATAZ', datos['capataz']), campo('CARGO', datos['cargo']), ''],
    ]
    tabla = Table(filas, colWidths=[6 * cm, 6 * cm, 6 * cm])
    tabla.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.6, _NEGRO),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    return tabla


def _listado(items, es):
    filas = [[
        Paragraph('<b>N°</b>', es['celda']),
        Paragraph('<b>DESCRIPCIÓN</b>', es['celda']),
        Paragraph('<b>UND.</b>', es['celda']),
        Paragraph('<b>CANTIDAD</b>', es['celda']),
        Paragraph('<b>OBSERVACIÓN</b>', es['celda']),
    ]]
    for i in range(RENGLONES):
        item = items[i] if i < len(items) else None
        filas.append([
            Paragraph(str(i + 1), es['celda']),
            Paragraph(item['descripcion'] if item else '', es['celda']),
            Paragraph(item['unidad'] if item else '', es['celda']),
            Paragraph(item['cantidad'] if item else '', es['celda']),
            '',  # la observación se llena a mano si hace falta
        ])
    tabla = Table(filas, repeatRows=1,
                  colWidths=[1.1 * cm, 8.4 * cm, 1.6 * cm, 2.2 * cm, 4.7 * cm])
    tabla.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, _NEGRO),
        ('BACKGROUND', (0, 0), (-1, 0), _GRIS),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (2, 0), (3, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 1), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 2),
    ]))
    return tabla


def _pie(datos, es):
    nota = Paragraph(
        '<b>Materiales de Recupero:</b> Se consideran a todos los materiales '
        'que son retirados durante la ejecución y finalización de la obra, '
        'debiendo ser entregados al Almacén de Reciclaje de Tecsur por las '
        'Contratistas.<br/>Ejemplo: Cables, Fierro, Luminarias, Seccionadores, '
        'Interruptores, Aisladores, etc.', es['pie'])

    firma = [
        Paragraph(datos['firma'], es['firma']),
        Paragraph('_' * 34, es['firmaPie']),
        Paragraph('<b>FIRMA CAPATAZ</b>', es['firmaPie']),
        Paragraph(datos['firma_pie'], es['firmaPie']),
    ]

    tabla = Table(
        [[Paragraph('<b>VERIFICACIÓN Y CONFORMIDAD DE LAS ACCIONES</b>',
                    es['cabecera'])],
         [nota],
         [firma]],
        colWidths=[18 * cm])
    tabla.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.6, _NEGRO),
        ('BACKGROUND', (0, 0), (0, 0), _GRIS),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('TOPPADDING', (0, 2), (0, 2), 14),
        ('BOTTOMPADDING', (0, 2), (0, 2), 8),
    ]))
    return tabla


def generar_pdf_recupero(datos, items):
    """Arma el formato. `datos` trae el encabezado y la firma; `items`, la lista
    de recuperos ya sumada, cada uno con descripcion, unidad y cantidad."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=1.4 * cm, rightMargin=1.4 * cm,
        topMargin=1.2 * cm, bottomMargin=1.2 * cm,
        title=f'Registro de materiales de recupero {datos["sst"]}',
    )
    es = _estilos()
    doc.build([
        _encabezado(datos, es),
        Spacer(1, 6),
        Paragraph('REGISTRO DE MATERIALES DE RECUPERO', es['titulo']),
        Spacer(1, 6),
        _datos(datos, es),
        Spacer(1, 6),
        Table([[Paragraph('<b>LISTADO</b>', es['cabecera'])]],
              colWidths=[18 * cm],
              style=TableStyle([
                  ('GRID', (0, 0), (-1, -1), 0.6, _NEGRO),
                  ('BACKGROUND', (0, 0), (0, 0), _GRIS),
                  ('ALIGN', (0, 0), (0, 0), 'CENTER'),
              ])),
        _listado(items, es),
        Spacer(1, 6),
        _pie(datos, es),
    ])
    return buffer.getvalue()


def fecha_larga(f=None):
    f = f or date.today()
    return f.strftime('%d/%m/%Y')
