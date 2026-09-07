"""
Genera el PDF de acta de inventario y lo envía por correo.
"""
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

# Verde corporativo Encossa
_VERDE  = colors.HexColor('#1D6A3A')
_VERDE2 = colors.HexColor('#E8F5E9')
_GRIS   = colors.HexColor('#F5F5F5')
_NEGRO  = colors.HexColor('#212121')

MESES = [
    '', 'Enero','Febrero','Marzo','Abril','Mayo','Junio',
    'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre',
]


def _estilos():
    ss = getSampleStyleSheet()
    return {
        'titulo': ParagraphStyle(
            'titulo', parent=ss['Normal'],
            fontSize=18, textColor=_VERDE,
            fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=2,
        ),
        'subtitulo': ParagraphStyle(
            'subtitulo', parent=ss['Normal'],
            fontSize=10, textColor=colors.grey,
            fontName='Helvetica', alignment=TA_CENTER, spaceAfter=4,
        ),
        'etiqueta': ParagraphStyle(
            'etiqueta', parent=ss['Normal'],
            fontSize=8, textColor=colors.grey,
            fontName='Helvetica', alignment=TA_LEFT,
        ),
        'valor': ParagraphStyle(
            'valor', parent=ss['Normal'],
            fontSize=10, textColor=_NEGRO,
            fontName='Helvetica-Bold', alignment=TA_LEFT,
        ),
        'firma_label': ParagraphStyle(
            'firma_label', parent=ss['Normal'],
            fontSize=8, textColor=colors.grey,
            fontName='Helvetica', alignment=TA_CENTER,
        ),
        'firma_nombre': ParagraphStyle(
            'firma_nombre', parent=ss['Normal'],
            fontSize=10, textColor=_NEGRO,
            fontName='Helvetica-Bold', alignment=TA_CENTER,
        ),
        'nota': ParagraphStyle(
            'nota', parent=ss['Normal'],
            fontSize=8, textColor=colors.grey,
            fontName='Helvetica-Oblique', alignment=TA_CENTER,
        ),
    }


def generar_pdf_inventario(inventario, encargado_camion=None) -> bytes:
    """
    Genera el acta de inventario en PDF y retorna los bytes.

    - inventario: instancia de Inventario con detalles y relaciones cargadas
    - encargado_camion: instancia de Usuario (encargado del camión) o None
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm,   bottomMargin=2*cm,
    )

    es = _estilos()
    story = []

    # ── Encabezado ────────────────────────────────────────────────────────────
    story.append(Paragraph('ENCOSSA', es['titulo']))
    story.append(Paragraph('Sistema de Control de Almacén', es['subtitulo']))
    story.append(HRFlowable(width='100%', thickness=2, color=_VERDE, spaceAfter=10))
    story.append(Paragraph('ACTA DE INVENTARIO', ParagraphStyle(
        'acta', fontSize=14, fontName='Helvetica-Bold',
        textColor=_NEGRO, alignment=TA_CENTER, spaceAfter=4,
    )))
    story.append(Spacer(1, 10))

    # ── Bloque informativo ────────────────────────────────────────────────────
    empresa_nombre = (
        inventario.usuario.empresa.nombre
        if inventario.usuario.empresa_id else 'Encossa'
    )
    camion_placa   = inventario.camion.placa if inventario.camion_id else '—'
    mes_anio       = f'{MESES[inventario.mes]} {inventario.anio}'
    fecha_str      = inventario.fecha.strftime('%d/%m/%Y') if inventario.fecha else date.today().strftime('%d/%m/%Y')
    realizado_por  = inventario.usuario.nombre
    encargado_str  = encargado_camion.nombre if encargado_camion else '—'

    info_data = [
        [
            Paragraph('EMPRESA', es['etiqueta']),
            Paragraph(empresa_nombre, es['valor']),
            Paragraph('FECHA', es['etiqueta']),
            Paragraph(fecha_str, es['valor']),
        ],
        [
            Paragraph('CAMIÓN / PLACA', es['etiqueta']),
            Paragraph(camion_placa, es['valor']),
            Paragraph('PERÍODO', es['etiqueta']),
            Paragraph(mes_anio, es['valor']),
        ],
        [
            Paragraph('REALIZADO POR', es['etiqueta']),
            Paragraph(realizado_por, es['valor']),
            Paragraph('ENCARGADO CAMIÓN', es['etiqueta']),
            Paragraph(encargado_str, es['valor']),
        ],
    ]

    info_table = Table(info_data, colWidths=[3.5*cm, 6*cm, 3.5*cm, 4.5*cm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), _GRIS),
        ('GRID',       (0, 0), (-1, -1), 0.5, colors.white),
        ('ROWBACKGROUND', (0, 0), (-1, -1), _GRIS),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ('ROUNDEDCORNERS', [4]),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 16))

    # ── Tabla de materiales ───────────────────────────────────────────────────
    story.append(Paragraph('DETALLE DE MATERIALES INVENTARIADOS', ParagraphStyle(
        'sec', fontSize=10, fontName='Helvetica-Bold',
        textColor=_VERDE, spaceAfter=6,
    )))

    th_style = ParagraphStyle('th', fontSize=8, fontName='Helvetica-Bold',
                               textColor=colors.white, alignment=TA_CENTER)
    td_style = ParagraphStyle('td', fontSize=9, fontName='Helvetica',
                               textColor=_NEGRO, alignment=TA_LEFT)
    td_num   = ParagraphStyle('tdn', fontSize=9, fontName='Helvetica-Bold',
                               textColor=_NEGRO, alignment=TA_RIGHT)

    encabezado = [
        Paragraph('N°',          th_style),
        Paragraph('MATRÍCULA',   th_style),
        Paragraph('DESCRIPCIÓN', th_style),
        Paragraph('TEÓRICO',     th_style),
        Paragraph('FÍSICO',      th_style),
        Paragraph('DIFERENCIA',  th_style),
    ]

    filas = [encabezado]
    detalles = list(inventario.detalles.all())

    con_dif = 0
    for i, d in enumerate(detalles, 1):
        dif = d.cantidad_fisica - d.cantidad_teorica
        if dif != 0:
            con_dif += 1

        if dif > 0:
            dif_color = colors.HexColor('#1565C0')   # azul (sobrante)
            dif_str   = f'+{dif}'
        elif dif < 0:
            dif_color = colors.HexColor('#B71C1C')   # rojo (faltante)
            dif_str   = str(dif)
        else:
            dif_color = colors.HexColor('#388E3C')   # verde (ok)
            dif_str   = '0'

        td_dif = ParagraphStyle('tdd', fontSize=9, fontName='Helvetica-Bold',
                                 textColor=dif_color, alignment=TA_RIGHT)

        filas.append([
            Paragraph(str(i),               td_num),
            Paragraph(d.material.matricula, td_style),
            Paragraph(d.material.descripcion, td_style),
            Paragraph(str(d.cantidad_teorica), td_num),
            Paragraph(str(d.cantidad_fisica),  td_num),
            Paragraph(dif_str,                 td_dif),
        ])

    col_widths = [1*cm, 3*cm, 7.5*cm, 2*cm, 2*cm, 2*cm]
    mat_table = Table(filas, colWidths=col_widths, repeatRows=1)

    row_count = len(filas)
    style_cmds = [
        # Encabezado
        ('BACKGROUND',    (0, 0), (-1, 0),  _VERDE),
        ('TEXTCOLOR',     (0, 0), (-1, 0),  colors.white),
        ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0),  8),
        ('ALIGN',         (0, 0), (-1, 0),  'CENTER'),
        ('TOPPADDING',    (0, 0), (-1, 0),  6),
        ('BOTTOMPADDING', (0, 0), (-1, 0),  6),
        # Filas de datos
        ('FONTSIZE',      (0, 1), (-1, -1), 9),
        ('TOPPADDING',    (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ('GRID',          (0, 0), (-1, -1), 0.4, colors.HexColor('#DDDDDD')),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]
    # Filas alternas
    for row in range(1, row_count):
        bg = _VERDE2 if row % 2 == 0 else colors.white
        style_cmds.append(('BACKGROUND', (0, row), (-1, row), bg))

    mat_table.setStyle(TableStyle(style_cmds))
    story.append(mat_table)
    story.append(Spacer(1, 8))

    # Resumen diferencias
    sin_dif = len(detalles) - con_dif
    resumen_data = [[
        Paragraph(f'Total materiales: <b>{len(detalles)}</b>', ParagraphStyle(
            'res', fontSize=9, fontName='Helvetica')),
        Paragraph(f'Sin diferencia: <b><font color="#388E3C">{sin_dif}</font></b>', ParagraphStyle(
            'res2', fontSize=9, fontName='Helvetica')),
        Paragraph(f'Con diferencia: <b><font color="#B71C1C">{con_dif}</font></b>', ParagraphStyle(
            'res3', fontSize=9, fontName='Helvetica')),
    ]]
    res_table = Table(resumen_data, colWidths=[6*cm, 5*cm, 5*cm])
    res_table.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), _GRIS),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
    ]))
    story.append(res_table)
    story.append(Spacer(1, 30))

    # ── Firmas ────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 20))

    firma_data = [[
        # Firma encargado almacén
        Table([
            [Paragraph('', es['firma_label'])],
            [HRFlowable(width=5*cm, thickness=1, color=_NEGRO)],
            [Paragraph('FIRMA', es['firma_label'])],
            [Paragraph(realizado_por, es['firma_nombre'])],
            [Paragraph('Encargado de Almacén', es['firma_label'])],
        ], colWidths=[6*cm]),
        # Espacio
        Spacer(1, 1),
        # Firma encargado camión
        Table([
            [Paragraph('', es['firma_label'])],
            [HRFlowable(width=5*cm, thickness=1, color=_NEGRO)],
            [Paragraph('FIRMA', es['firma_label'])],
            [Paragraph(encargado_str, es['firma_nombre'])],
            [Paragraph('Encargado de Camión', es['firma_label'])],
        ], colWidths=[6*cm]),
    ]]
    firma_table = Table(firma_data, colWidths=[7*cm, 3.5*cm, 7*cm])
    firma_table.setStyle(TableStyle([
        ('ALIGN',  (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(firma_table)
    story.append(Spacer(1, 20))

    # Nota al pie
    story.append(Paragraph(
        f'Documento generado automáticamente por el Sistema de Control de Almacén Encossa '
        f'el {date.today().strftime("%d/%m/%Y")}.',
        es['nota'],
    ))

    doc.build(story)
    return buffer.getvalue()


def enviar_pdf_inventario(inventario, encargado_camion=None):
    """
    Genera el PDF y lo envía por correo a los destinatarios relevantes.
    Falla silenciosamente si no hay emails configurados.
    """
    from django.core.mail import EmailMessage
    from django.conf import settings

    destinatarios = []
    if encargado_camion and encargado_camion.email:
        destinatarios.append(encargado_camion.email)
    if inventario.usuario.email:
        destinatarios.append(inventario.usuario.email)

    if not destinatarios or not getattr(settings, 'EMAIL_HOST_USER', ''):
        return  # Sin email configurado o sin destinatarios

    try:
        pdf_bytes = generar_pdf_inventario(inventario, encargado_camion)

        placa    = inventario.camion.placa if inventario.camion_id else 'almacén'
        mes_anio = f'{MESES[inventario.mes]} {inventario.anio}'
        asunto   = f'Acta de Inventario — {placa} — {mes_anio}'
        cuerpo   = (
            f'Estimado/a,\n\n'
            f'Se adjunta el acta de inventario correspondiente al camión {placa} '
            f'del período {mes_anio}.\n\n'
            f'Realizado por: {inventario.usuario.nombre}\n'
            f'Encargado de camión: {encargado_camion.nombre if encargado_camion else "—"}\n\n'
            f'Este es un mensaje automático del Sistema de Control de Almacén Encossa.'
        )

        msg = EmailMessage(
            subject=asunto,
            body=cuerpo,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=destinatarios,
        )
        msg.attach(
            filename=f'inventario_{placa}_{inventario.mes}_{inventario.anio}.pdf',
            content=pdf_bytes,
            mimetype='application/pdf',
        )
        msg.send(fail_silently=True)

    except Exception:
        pass  # No interrumpir el cierre de inventario por fallo de email
