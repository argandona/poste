"""PDF del IPC: el formato F01-IA-SMAC-003 de Encossa, lleno.

Sigue el orden del papel: Sección A (tarea, EPP, peligros críticos, etapas,
emergencia, brigadas y factores de comportamiento), Sección B (las energías
con sus peligros, tareas y medidas) y Sección C (participantes con su
confirmación, las SST y las observaciones de cierre). Lo marcado sale con un
cuadrado relleno; lo no marcado, vacío.
"""
import io
from pathlib import Path

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from . import ipc_formato as F

ICONOS = Path(__file__).resolve().parent / 'data' / 'ipc'
LOGO = Path(__file__).resolve().parent / 'data' / 'logo_encossa.png'
ANCHO = A4[0] - 2.4 * cm

AMARILLO = colors.HexColor('#FFF200')
VERDE = colors.HexColor('#00A651')
GRIS = colors.HexColor('#DDDDDD')

_base = ParagraphStyle('base', fontName='Helvetica', fontSize=7, leading=8.5)
_neg = ParagraphStyle('neg', parent=_base, fontName='Helvetica-Bold')
_cen = ParagraphStyle('cen', parent=_base, alignment=1)
_cen_neg = ParagraphStyle('cenneg', parent=_neg, alignment=1)
_titulo = ParagraphStyle('tit', parent=_neg, fontSize=11, leading=13, alignment=1)


def _p(texto, estilo=_base):
    return Paragraph(texto, estilo)


def _caja(marcada):
    """La casilla del papel: con una X si está marcada, vacía si no. Va como
    imagen dentro del texto (y no con un carácter de ZapfDingbats), porque esa
    fuente no se incrusta y cada visor la dibuja a su modo."""
    ruta = ICONOS / ('casilla_si.png' if marcada else 'casilla_no.png')
    return f'<img src="{ruta.as_posix()}" width="7" height="7" valign="-1"/>'


def _icono(nombre, lado=1.25 * cm):
    ruta = ICONOS / nombre
    return Image(str(ruta), width=lado, height=lado) if ruta.exists() else ''


def _grilla(t, fondo_primera=None):
    estilo = [('GRID', (0, 0), (-1, -1), 0.5, colors.black),
              ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
              ('TOPPADDING', (0, 0), (-1, -1), 2),
              ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]
    if fondo_primera:
        estilo.append(('BACKGROUND', (0, 0), (-1, 0), fondo_primera))
    t.setStyle(TableStyle(estilo))
    return t


def _barra(texto, fondo=AMARILLO):
    return _grilla(Table([[_p(texto, _cen_neg)]], colWidths=[ANCHO]), fondo)


def _cabecera(ipc):
    logo = Image(str(LOGO), width=3.4 * cm, height=1 * cm) if LOGO.exists() else ''
    control = _p(f'Código: {ipc.formato_codigo}<br/>Versión: {ipc.formato_version}'
                 '<br/>Aprobado: SMAC<br/>Fecha: 20/05/2024')
    return _grilla(Table(
        [[logo, _p('FORMATO<br/>INSTRUCCIÓN PREVIA EN CAMPO (IPC)', _titulo), control]],
        colWidths=[4 * cm, ANCHO - 8 * cm, 4 * cm]))


def _seccion_a(ipc, d):
    responsable = ipc.participantes.filter(usuario=ipc.responsable).first()
    firma_resp = ('Conforme digital ' +
                  timezone.localtime(responsable.confirmado).strftime('%H:%M')
                  if responsable and responsable.confirmado else '')
    filas = [
        [_p(f'<b>(1) TAREA:</b> {ipc.tarea}'), '',
         _p(f'<b>(2) COORDINADOR:</b> {ipc.coordinador.nombre if ipc.coordinador_id else ""}'), ''],
        [_p(f'<b>(3) CAPATAZ / ENCARGADO:</b> {ipc.responsable.nombre}'), '',
         _p(f'<b>FIRMA:</b> {firma_resp}'),
         _p(f'<b>(4) FECHA:</b> {ipc.fecha:%d/%m/%Y}')],
    ]
    t = Table(filas, colWidths=[ANCHO * .3, ANCHO * .2, ANCHO * .3, ANCHO * .2])
    t.setStyle(TableStyle([('SPAN', (0, 0), (1, 0)), ('SPAN', (2, 0), (3, 0)),
                           ('SPAN', (0, 1), (1, 1))]))
    return _grilla(t)


def _iconos_marcados(lista, marcados, otros):
    lado = (ANCHO * .55) / 9 - 2
    iconos = [_icono(x['icono'], lado) for x in lista]
    cajas = [_p(_caja(x['clave'] in marcados), _cen) for x in lista]
    t = Table([iconos, cajas], colWidths=[lado + 2] * len(lista))
    t.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                           ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    return [t, _p(f'Otros/Detallar: {otros or ""}')]


def _epp_peligros_etapas(d):
    izquierda = Table(
        [[_p('<b>(5) EPP a utilizar</b>', _cen)],
         *[[x] for x in _iconos_marcados(F.EPP, d.get('epp', []), d.get('epp_otros'))],
         [_p('<b>(6) Peligros críticos</b>', _cen)],
         *[[x] for x in _iconos_marcados(F.PELIGROS_CRITICOS,
                                          d.get('peligros_criticos', []),
                                          d.get('peligros_otros'))]],
        colWidths=[ANCHO * .58])
    etapas = d.get('etapas', [])
    derecha = Table(
        [[_p('<b>(7) Etapas de la Tarea</b>', _cen)]] +
        [[_p(f'<b>{i}</b>  {etapas[i - 1] if i <= len(etapas) else ""}')]
         for i in range(1, F.MAX_ETAPAS + 1)],
        colWidths=[ANCHO * .42 - 12])
    derecha.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.grey)]))
    return _grilla(Table([[izquierda, derecha]], colWidths=[ANCHO * .58, ANCHO * .42]))


def _emergencia(d):
    e = d.get('emergencia') or {}
    filas = [
        [_p(f'<b>Nombre del Superior Inmediato:</b> {e.get("superior_nombre", "")}'),
         _p(f'<b>N° de Teléfono de Emergencia:</b> {e.get("superior_telefono", "")}')],
        [_p(f'<b>Médico Ocupacional:</b> {e.get("medico_nombre", "")}'),
         _p(f'<b>N° de Teléfono de Emergencia:</b> {e.get("medico_telefono", "")}')],
        [_p(f'<b>Centro médico más Cercano:</b> {e.get("centro_medico", "")}'),
         _p(f'<b>N° de Teléfono:</b> {e.get("centro_medico_telefono", "")}')],
    ]
    return _grilla(Table(filas, colWidths=[ANCHO * .6, ANCHO * .4]))


def _brigadas(d):
    brig = '   '.join(f'{_caja(b["clave"] in d.get("brigadas", []))} {b["texto"]}'
                      for b in F.BRIGADAS)
    eq = '   '.join(f'{_caja(b["clave"] in d.get("equipamiento", []))} {b["texto"]}'
                    for b in F.EQUIPAMIENTO)
    if d.get('equipamiento_otros'):
        eq += f'   Otros: {d["equipamiento_otros"]}'
    return _grilla(Table(
        [[_p('<b>(9) Brigada de Respuesta Inicial Disponibles</b>', _cen),
          _p('<b>(10) Equipamiento disponible de las Brigadas</b>', _cen)],
         [_p(brig), _p(eq)]],
        colWidths=[ANCHO * .5, ANCHO * .5]), AMARILLO)


def _factores(d):
    respuestas = d.get('factores', {})
    filas = [[_p('<b>** FACTORES Y ASPECTOS QUE AFECTAN EL COMPORTAMIENTO E '
                 'INFLUYEN EL DESEMPEÑO</b>', _cen), '', '', '']]
    estilos = [('SPAN', (0, 0), (-1, 0)), ('BACKGROUND', (0, 0), (-1, 0), AMARILLO)]
    grupo_anterior, inicio = None, 1
    for i, f in enumerate(F.FACTORES, start=1):
        r = respuestas.get(f['clave'])
        riesgo = r == f['riesgo']
        filas.append([_p(f'<b>{f["grupo"]}</b>', _cen) if f['grupo'] != grupo_anterior else '',
                      _p(f['texto']),
                      _p(f'{_caja(r == "no")} NO', _cen),
                      _p(f'{_caja(r == "si")} SI', _cen)])
        if riesgo:
            estilos.append(('BACKGROUND', (1, i), (3, i), colors.HexColor('#FFD6D6')))
        if f['grupo'] != grupo_anterior and grupo_anterior is not None:
            estilos.append(('SPAN', (0, inicio), (0, i - 1)))
            inicio = i
        grupo_anterior = f['grupo']
    estilos.append(('SPAN', (0, inicio), (0, len(filas) - 1)))
    t = Table(filas, colWidths=[ANCHO * .15, ANCHO * .61, ANCHO * .12, ANCHO * .12])
    t.setStyle(TableStyle(estilos))
    return _grilla(t)


def _seccion_b(d):
    energias = d.get('energias', {})
    filas = [[_p('<b>(11) ENERGÍA</b>', _cen), _p('<b>(12) PELIGROS POTENCIALES</b>', _cen),
              _p('<b>(13) IDENTIFICAR LAS TAREAS</b>', _cen),
              _p('<b>(14) MEDIDAS DE CONTROL REQUERIDAS</b>', _cen)]]
    estilos = [('VALIGN', (0, 0), (-1, -1), 'TOP')]
    for e in F.ENERGIAS:
        inicio = len(filas)
        for pregunta in e['preguntas']:
            r = energias.get(pregunta['clave']) or {}
            marcados = r.get('peligros', [])
            opciones = '<br/>'.join(f'{_caja(o["clave"] in marcados)} {o["texto"]}'
                                    for o in pregunta['opciones'])
            if r.get('otros'):
                opciones += f'<br/>{_caja(True)} Otros: {r["otros"]}'
            filas.append([
                '',
                _p(f'<b>{pregunta["texto"]}</b><br/>{opciones}'),
                _p((r.get('tareas') or '').replace('\n', '<br/>')),
                _p((r.get('medidas') or '').replace('\n', '<br/>')),
            ])
        filas[inicio][0] = Table([[_p(f'<b>{e["energia"].replace("/", "/<br/>")}</b>', _cen)],
                                  [_icono(e['icono'], 1.1 * cm)]])
        if len(filas) - 1 > inicio:
            estilos.append(('SPAN', (0, inicio), (0, len(filas) - 1)))
    t = Table(filas, colWidths=[ANCHO * .14, ANCHO * .36, ANCHO * .23, ANCHO * .27],
              repeatRows=1)
    t.setStyle(TableStyle(estilos))
    return _grilla(t, GRIS)


def _firma(p):
    if p.estado != 'conforme':
        return _p('<i>Pendiente</i>', _cen)
    hora = timezone.localtime(p.confirmado).strftime('%d/%m %H:%M') if p.confirmado else ''
    if p.metodo == p.METODO_EQUIPO and p.firma:
        try:
            from reportlab.lib.utils import ImageReader
            ImageReader(io.BytesIO(bytes(p.firma))).getRGBData()
            imagen = Image(io.BytesIO(bytes(p.firma)), width=2.6 * cm, height=0.9 * cm)
        except Exception:
            # Una firma dañada no tumba el documento.
            imagen = _p('<i>(firma ilegible)</i>', _cen)
        return Table([[imagen], [_p(f'En equipo del responsable · {hora}', _cen)]])
    return _p(f'Conforme digital · {hora}', _cen)


def _seccion_c(ipc):
    filas = [[_p('<b>Nombre</b>', _cen), _p('<b>DNI</b>', _cen),
              _p('<b>CARGO</b>', _cen), _p('<b>FIRMA</b>', _cen)]]
    participantes = list(ipc.participantes.all())
    for i in range(max(10, len(participantes))):
        if i < len(participantes):
            p = participantes[i]
            filas.append([_p(f'{i + 1}  {p.usuario.nombre}'), _p(p.dni, _cen),
                          _p(p.cargo, _cen), _firma(p)])
        else:
            filas.append([_p(f'{i + 1}'), '', '', ''])
    participantes_t = _grilla(Table(
        filas, colWidths=[ANCHO * .4, ANCHO * .15, ANCHO * .2, ANCHO * .25]), GRIS)

    # (16) Ubicación: 8 renglones; lo que pasa va en la misma fila con guion.
    ssts = [f'{s.sst.codigo or s.sst.sst}' + (f' · {s.direccion}' if s.direccion else '')
            for s in ipc.ssts.all()]
    renglones = ['' for _ in range(F.RENGLONES_UBICACION)]
    for i, texto in enumerate(ssts):
        r = i % F.RENGLONES_UBICACION
        renglones[r] = f'{renglones[r]} - {texto}' if renglones[r] else texto
    mitad = F.RENGLONES_UBICACION // 2
    ubicacion = [[_p(f'{i + 1}  {renglones[i]}'), _p(f'{i + 1 + mitad}  {renglones[i + mitad]}')]
                 for i in range(mitad)]
    ubicacion_t = _grilla(Table(ubicacion, colWidths=[ANCHO * .5, ANCHO * .5]))

    cierre = (f'{ipc.responsable.nombre}<br/>Hora de cierre: '
              f'{ipc.hora_cierre:%H:%M}' if ipc.hora_cierre else
              f'{ipc.responsable.nombre}<br/><i>Sin cerrar</i>')
    observaciones_t = _grilla(Table(
        [[_p((ipc.observaciones or '').replace('\n', '<br/>')), _p(cierre, _cen)],
         ['', _p('<b>NOMBRE / FIRMA / HORA DE CIERRE DEL FRENTE DE TRABAJO</b>', _cen)]],
        colWidths=[ANCHO * .7, ANCHO * .3], rowHeights=[2.2 * cm, None]))
    return [_barra('SECCIÓN C · (15) Participantes / Equipo de Trabajo', VERDE),
            participantes_t, Spacer(1, 4),
            _barra('(16) Ubicación (dirección y SST de los puntos de trabajo)', VERDE),
            ubicacion_t, Spacer(1, 4),
            _barra('(17) Observaciones', VERDE), observaciones_t]


def generar_pdf_ipc(ipc):
    d = ipc.datos or {}
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.2 * cm,
                            rightMargin=1.2 * cm, topMargin=1 * cm,
                            bottomMargin=1 * cm,
                            title=f'IPC {ipc.fecha:%d/%m/%Y} {ipc.responsable.nombre}')
    partes = [_cabecera(ipc), Spacer(1, 4), _barra('SECCIÓN A'),
              _seccion_a(ipc, d), _epp_peligros_etapas(d),
              _barra('(8) EN CASO DE EMERGENCIA'), _emergencia(d),
              _brigadas(d), _factores(d), Spacer(1, 4),
              _barra('SECCIÓN B'), _seccion_b(d), Spacer(1, 4),
              *_seccion_c(ipc)]
    doc.build(partes)
    return buffer.getvalue()
