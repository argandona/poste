"""PDF de la Conducción: el formato F03-IA-QHSE-001 de Encossa, lleno.

Sigue el papel: página 1 con fecha y hora, los 8 controles con su guía y la
respuesta marcada, y la primera fila de firmas; página 2 con el dibujo de los
controles y las demás filas (una por SST, con la hora en que el chofer firmó
desde su app).
"""
import io
from pathlib import Path

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (Image, PageBreak, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from . import conduccion_formato as F
from .ipc_pdf import ANCHO, LOGO, _base, _caja, _cen, _cen_neg, _grilla, _p, _titulo

ILUSTRACION = Path(__file__).resolve().parent / 'data' / 'conduccion' / 'ilustracion.jpg'

CELESTE = colors.HexColor('#D9E2F3')
ROJO = colors.HexColor('#FF0000')
AZUL = colors.HexColor('#2E3192')
NARANJA = colors.HexColor('#F28C28')

_blanco = ParagraphStyle('blanco', parent=_cen_neg, textColor=colors.white,
                         fontSize=9, leading=11)
_numero = ParagraphStyle('numero', parent=_cen_neg, textColor=NARANJA, fontSize=10)
_texto = ParagraphStyle('texto', parent=_base, fontSize=8, leading=9.5)


def _cabecera(c, pagina):
    logo = Image(str(LOGO), width=3.4 * cm, height=1 * cm) if LOGO.exists() else ''
    control = _p(f'Código: {c.formato_codigo}<br/>Versión: {c.formato_version}'
                 f'<br/>Aprobado: SGQHSE<br/>Fecha: 02/03/2026<br/>Página: {pagina} de 2')
    return _grilla(Table([[logo, _p('FORMATO<br/>CONDUCCIÓN', _titulo), control]],
                         colWidths=[4 * cm, ANCHO - 8 * cm, 4 * cm]))


def _encabezado(c):
    creada = timezone.localtime(c.creada)
    camion = f'Camión: {c.camion.placa}' if c.camion_id else ''
    return _grilla(Table(
        [[_p('<b>CONDUCCIÓN</b>', _titulo), _p('<b>Fecha y hora:</b>', _cen),
          _p(f'{creada:%d/%m/%Y %H:%M}', _cen), _p(camion, _cen)]],
        colWidths=[ANCHO * .45, ANCHO * .15, ANCHO * .2, ANCHO * .2]))


def _barra(texto, fondo, estilo):
    return _grilla(Table([[_p(texto, estilo)]], colWidths=[ANCHO]), fondo)


def _controles(c):
    respuestas = c.controles or {}
    filas = [[_p('Asegura los siguientes controles/ barreras', _blanco), '',
              _p('Guía para confirmar cada control/barrera', _blanco),
              _p('¿Cumple?', _blanco)]]
    for i, ctrl in enumerate(F.CONTROLES, 1):
        r = respuestas.get(ctrl['clave'])
        filas.append([
            _p(str(i), _numero), _p(ctrl['control'], _texto),
            _p('<br/>'.join(f'• {g}' for g in ctrl['guia']), _texto),
            _p(f'{_caja(r == "si")} Sí<br/>{_caja(r == "no")} No', _texto),
        ])
    t = Table(filas, colWidths=[ANCHO * .06, ANCHO * .34, ANCHO * .46, ANCHO * .14])
    estilo = [('SPAN', (0, 0), (1, 0)), ('BACKGROUND', (0, 0), (-1, 0), AZUL)]
    t.setStyle(TableStyle(estilo))
    return _grilla(t)


def _firmas(c, filas_ssts, minimo):
    encabezado = [_p('<b>Nombres y Apellidos</b>', _cen), _p('<b>SST</b>', _cen),
                  _p('<b>Cargo</b>', _cen), _p('<b>Firma</b>', _cen)]
    filas = [encabezado]
    for s in filas_ssts:
        firma = timezone.localtime(s.firmada)
        filas.append([_p(c.chofer.nombre), _p(s.codigo, _cen), _p(c.cargo, _cen),
                      _p(f'Conforme digital<br/>{firma:%d/%m %H:%M}', _cen)])
    while len(filas) < minimo + 1:
        filas.append(['', '', '', ''])
    return _grilla(Table(filas, colWidths=[ANCHO * .45, ANCHO * .17,
                                           ANCHO * .2, ANCHO * .18]))


def generar_pdf_conduccion(c):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=(21 * cm, 29.7 * cm),
                            leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=1 * cm, bottomMargin=1 * cm,
                            title=f'Conducción {c.fecha:%d/%m/%Y} {c.chofer.nombre}')
    ssts = list(c.ssts.all())
    primera, resto = ssts[:F.RENGLONES_PAGINA_1], ssts[F.RENGLONES_PAGINA_1:]
    partes = [
        _cabecera(c, 1), Spacer(1, 10), _encabezado(c),
        _barra('<b>Completar antes del inicio de cualquier actividad de CONDUCCIÓN</b>',
               CELESTE, _cen),
        _barra(F.AVISO, ROJO, _blanco),
        _controles(c), Spacer(1, 6),
        _firmas(c, primera, F.RENGLONES_PAGINA_1),
        PageBreak(),
        _cabecera(c, 2), Spacer(1, 10),
    ]
    if ILUSTRACION.exists():
        ancho = ANCHO * .9
        partes.append(Image(str(ILUSTRACION), width=ancho, height=ancho * 1249 / 1376))
    partes += [Spacer(1, 8), _firmas(c, resto, F.RENGLONES_PAGINA_2)]
    doc.build(partes)
    return buffer.getvalue()
