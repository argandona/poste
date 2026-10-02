"""Cuaderno de obra del reforzamiento de poste, con y sin vereda.

Calca el formato de Encossa "Cuaderno de obra rehabilitacion de poste.xlsx":
un encabezado con la SST y los responsables, y dos columnas de casillas, una
para el reforzamiento con vereda y otra para el sin vereda. Se llena solo la
columna del tipo liquidado; la otra queda en blanco, como en el papel.

Solo vale para las dos actividades de reforzamiento. Las demás siguen con el
cuaderno de `cuaderno_obra`.

Igual que ese, está partido en dos para probarlo sin pintar:
- `reunir_reforzamiento` lee de la base una hoja por poste;
- `generar_pdf_reforzamiento` las pinta.
"""
import io
from dataclasses import dataclass, field
from pathlib import Path

from django.db.models import Q
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .cuaderno_obra import numero

ACTIVIDADES_REFORZAMIENTO = (
    'Reforzamiento de poste con vereda',
    'Reforzamiento de poste sin vereda / piso especial',
)
TIPO_CON_VEREDA = 'Reforzamiento con vereda'
TIPO_SIN_VEREDA = 'Reforzamiento sin vereda'

MOTIVO = 'REHABILITACION DE POSTE'
CLIENTE = 'TECSUR'
SUPERVISOR = 'MAYCOL ALTAMIRANO'

CIMENTACION = '*094919'
ROTURA_CIMENTACION = '*098822'
FLEJE = '1014213'
HEBILLA = '1014308'
GEL = '2139148'

# Las claves con que la app guarda los paños y las respuestas de texto.
VEREDAS = (('vereda_10', 10), ('vereda_15', 15), ('vereda_20', 20))
RENGLONES_VEREDA = 3
RENGLONES_PISO = 2

LOGO = Path(__file__).resolve().parent / 'data' / 'logo_encossa.png'


@dataclass
class Hoja:
    """Lo que va en el cuaderno de un poste."""
    sst: str = ''
    fecha: str = ''
    distrito: str = ''
    contratista: str = ''
    poste: str = ''
    encargado: str = ''
    con_vereda: bool = True
    cimentacion: str = ''
    rotura: str = ''
    poste_existente: str = ''
    refuerzo: str = ''
    panos: list = field(default_factory=list)   # vereda: hasta 3 renglones
    pista: str = ''
    asfalto: str = ''
    pisos: list = field(default_factory=list)   # piso especial: hasta 2
    grass: str = ''
    acarreo_metros: str = ''
    acarreo_viajes: str = ''
    fleje: str = ''
    hebilla: str = ''
    gel: str = ''


def es_reforzamiento(sst):
    """Si la SST es de reforzamiento: por su actividad o, si no la tiene, por
    lo que se liquidó en ella."""
    from .models import LiquidacionSuministro

    if sst.actividad_id:
        return sst.actividad.nombre in ACTIVIDADES_REFORZAMIENTO
    return (LiquidacionSuministro.objects
            .filter(_de_la_sst(sst),
                    tipo_trabajo__nombre__in=(TIPO_CON_VEREDA, TIPO_SIN_VEREDA))
            .exists())


def _de_la_sst(sst):
    codigo = sst.codigo or sst.sst
    filtro = Q(suministro__sst_suministros__sst=sst)
    if codigo:
        filtro |= Q(sst_externo=codigo)
    return filtro


def medida(largo, ancho):
    """Un paño como se escribe en obra: 1.5 x 1."""
    return f'{numero(largo)} x {numero(ancho)}'


def _panos(medidas, clave):
    filas = (medidas.get('panos') or {}).get(clave) or []
    return [medida(f[0], f[1]) for f in filas
            if isinstance(f, (list, tuple)) and len(f) >= 2]


def en_renglones(textos, renglones):
    """Reparte los paños en los renglones del formato. Lo que no entra se
    junta en el último, para no perder ninguno."""
    if len(textos) <= renglones:
        return textos + [''] * (renglones - len(textos))
    return textos[:renglones - 1] + ['; '.join(textos[renglones - 1:])]


def _refuerzo(descripcion):
    """"REFUERZO DE FIBRA 8,7 / 200" -> "8,7 / 200"."""
    texto = descripcion.upper()
    for prefijo in ('REFUERZO DE FIBRA', 'REFUERZO'):
        if texto.startswith(prefijo):
            return descripcion[len(prefijo):].strip()
    return descripcion


def hoja_de(liq, sst):
    """La hoja de una liquidación de reforzamiento."""
    medidas = liq.medidas or {}
    partidas = {p.mano_de_obra.partida: p.cantidad for p in liq.partidas.all()}
    materiales = {}
    refuerzos = []
    for c in liq.materiales_consumidos.all():
        materiales[c.material.matricula] = (
            materiales.get(c.material.matricula, 0) + c.cantidad)
        if 'REFUERZO' in c.material.descripcion.upper() and c.cantidad > 0:
            refuerzos.append(_refuerzo(c.material.descripcion))

    def cantidad(valor):
        return numero(valor) if valor else ''

    def marca(codigo):
        return '1' if partidas.get(codigo, 0) > 0 else ''

    vereda = [f'{t} ({espesor} cm)'
              for clave, espesor in VEREDAS for t in _panos(medidas, clave)]
    metros, viajes = ((medidas.get('viajes') or {}).get('acarreo')
                      or [0, 0])[:2]
    textos = medidas.get('textos') or {}
    suministro = (liq.suministro.numero_suministro if liq.suministro_id
                  else liq.suministro_externo or '')
    distrito = ((liq.suministro.distrito if liq.suministro_id else '')
                or sst.distrito or '')
    return Hoja(
        sst=sst.codigo or sst.sst or '',
        fecha=(sst.fecha_ejecucion.strftime('%d/%m/%Y')
               if sst.fecha_ejecucion else ''),
        distrito=distrito,
        contratista=(sst.empresa.nombre if sst.empresa_id else '').upper(),
        poste=suministro,
        encargado=liq.usuario.nombre,
        con_vereda=liq.tipo_trabajo.nombre == TIPO_CON_VEREDA,
        cimentacion=marca(CIMENTACION),
        rotura=marca(ROTURA_CIMENTACION),
        poste_existente=str(textos.get('poste_existente') or '').strip(),
        refuerzo=', '.join(refuerzos),
        panos=en_renglones(vereda, RENGLONES_VEREDA),
        pista='; '.join(_panos(medidas, 'pista')),
        asfalto='; '.join(_panos(medidas, 'asfalto')),
        pisos=en_renglones(_panos(medidas, 'piso_especial'), RENGLONES_PISO),
        grass='; '.join(_panos(medidas, 'grass')),
        acarreo_metros=f'{numero(metros)} m' if metros else '',
        acarreo_viajes=numero(viajes) if viajes else '',
        fleje=cantidad(materiales.get(FLEJE)),
        hebilla=cantidad(materiales.get(HEBILLA)),
        gel=cantidad(materiales.get(GEL)),
    )


def reunir_reforzamiento(sst):
    """Una hoja por cada poste liquidado como reforzamiento en la SST."""
    from .models import LiquidacionSuministro

    liquidaciones = (
        LiquidacionSuministro.objects
        .filter(_de_la_sst(sst),
                tipo_trabajo__nombre__in=(TIPO_CON_VEREDA, TIPO_SIN_VEREDA))
        .select_related('usuario', 'tipo_trabajo', 'suministro')
        .prefetch_related('partidas__mano_de_obra',
                          'materiales_consumidos__material')
        .distinct()
        .order_by('id_liquidacion'))
    return [hoja_de(liq, sst) for liq in liquidaciones]


# ── El dibujo ────────────────────────────────────────────────────────────────

_ANCHO, _ALTO = A4
_IZQ = 1.6 * cm
_DER = _ANCHO - 1.6 * cm
_COL2 = _ANCHO / 2 + 0.3 * cm
_CASILLA = 2.9 * cm
_ALTO_CASILLA = 0.5 * cm


def _texto_que_entra(c, texto, ancho, fuente='Helvetica', tamano=9, minimo=5.5):
    """Achica la letra hasta que el texto entre en la casilla."""
    while tamano > minimo and stringWidth(texto, fuente, tamano) > ancho:
        tamano -= 0.5
    c.setFont(fuente, tamano)


def _casilla(c, x, y, texto=''):
    """Una casilla con su valor centrado. `y` es la base del renglón."""
    c.setLineWidth(0.8)
    c.rect(x, y - 0.12 * cm, _CASILLA, _ALTO_CASILLA)
    if texto:
        _texto_que_entra(c, texto, _CASILLA - 0.15 * cm)
        c.drawCentredString(x + _CASILLA / 2, y, texto)


def _renglon(c, x_etiqueta, y, etiqueta, valor, ancho_columna):
    _texto_que_entra(c, etiqueta, ancho_columna - _CASILLA - 0.2 * cm)
    c.drawString(x_etiqueta, y, etiqueta)
    _casilla(c, x_etiqueta + ancho_columna - _CASILLA, y, valor)


def _subrayado(c, x, y, texto, ancho):
    c.setLineWidth(0.6)
    c.line(x, y - 0.1 * cm, x + ancho, y - 0.1 * cm)
    if texto:
        _texto_que_entra(c, texto, ancho - 0.1 * cm, tamano=10)
        c.drawString(x + 0.05 * cm, y, texto)


def _acarreo(c, x, y, ancho_columna, metros, viajes):
    previo, raya = 'Acarreo de equipos y herramientas x ', 0.6 * cm
    libre = ancho_columna - _CASILLA - 0.2 * cm
    tamano = 9
    while tamano > 6 and (stringWidth(previo + ' viajes', 'Helvetica', tamano)
                          + raya > libre):
        tamano -= 0.5
    c.setFont('Helvetica', tamano)
    c.drawString(x, y, previo)
    x_viajes = x + stringWidth(previo, 'Helvetica', tamano)
    _subrayado(c, x_viajes, y, viajes, raya)
    c.setFont('Helvetica', tamano)
    c.drawString(x_viajes + raya + 0.05 * cm, y, ' viajes')
    _casilla(c, x + ancho_columna - _CASILLA, y, metros)


def _pagina(c, h):
    c.setLineWidth(1.2)
    c.rect(_IZQ - 0.4 * cm, 1.2 * cm, _DER - _IZQ + 0.8 * cm, _ALTO - 2.4 * cm)
    arriba = _ALTO - 1.6 * cm
    if LOGO.exists():
        c.drawImage(str(LOGO), _IZQ, arriba - 1.3 * cm, width=4 * cm,
                    height=1.2 * cm, preserveAspectRatio=True, mask='auto')
    c.setFont('Helvetica', 15)
    c.drawCentredString(_ANCHO / 2 + 1 * cm, arriba - 0.7 * cm,
                        'CUADERNO DE OBRA')

    # Encabezado.
    y = arriba - 2.2 * cm
    x_valor = _IZQ + 3.6 * cm
    for etiqueta, valor in (
            ('SST:', h.sst), ('FECHA', h.fecha), ('MOTIVO', MOTIVO),
            ('CLIENTE', CLIENTE), ('DISTRITO', h.distrito),
            ('SUPERVISOR TECSUR', SUPERVISOR),
            ('CONTRATISTA', h.contratista)):
        _texto_que_entra(c, etiqueta, x_valor - _IZQ - 0.2 * cm)
        c.drawString(_IZQ, y, etiqueta)
        _subrayado(c, x_valor, y, valor, 5.5 * cm)
        y -= 0.75 * cm

    y -= 0.5 * cm
    c.setFont('Helvetica', 9)
    frase = 'EN LA PRESENTE ORDEN, SE REALIZO EL REFORZAMIENTO DEL POSTE N. '
    c.drawString(_IZQ, y, frase)
    x_poste = _IZQ + stringWidth(frase, 'Helvetica', 9) + 0.3 * cm
    _subrayado(c, x_poste, y, h.poste, _DER - x_poste)
    y -= 0.9 * cm
    c.setFont('Helvetica', 9)
    c.drawString(_IZQ, y, 'ASIMISMO SE REALIZO LOS SIGUIENTES TRABAJOS:')

    # Las dos columnas: se llena solo la del tipo liquidado.
    ancho = _COL2 - _IZQ - 0.6 * cm
    vacia = Hoja()
    con = h if h.con_vereda else vacia
    sin = vacia if h.con_vereda else h
    y -= 1.2 * cm
    for etiqueta_con, etiqueta_sin, valor_con, valor_sin in (
            ('REHABILITACION DE POSTE CON VEREDA',
             'REHABILITACION DE POSTE SIN VEREDA',
             '1' if h.con_vereda else '', '' if h.con_vereda else '1'),
            ('CIMENTACION DE POSTE', 'CIMENTACION DE POSTE',
             con.cimentacion, sin.cimentacion),
            ('ROTURA DE CIMENTACION', 'ROTURA DE CIMENTACION',
             con.rotura, sin.rotura),
            ('POSTE EXISTENTE', 'POSTE EXISTENTE',
             con.poste_existente, sin.poste_existente),
            ('REFUERZO INSTALADO', 'REFUERZO INSTALADO',
             con.refuerzo, sin.refuerzo)):
        _renglon(c, _IZQ, y, etiqueta_con, valor_con, ancho)
        _renglon(c, _COL2, y, etiqueta_sin, valor_sin, ancho)
        y -= 0.85 * cm

    y -= 0.2 * cm
    panos = con.panos or [''] * RENGLONES_VEREDA
    pisos = sin.pisos or [''] * RENGLONES_PISO
    izquierda = [(f'PAÑO 0{i + 1}', p) for i, p in enumerate(panos)] + [
        ('PISTA', con.pista), ('ASFALTO', con.asfalto)]
    derecha = [(f'PISO ESPECIAL 0{i + 1}', p) for i, p in enumerate(pisos)] + [
        ('GRASS', sin.grass)]
    for i, (etiqueta, valor) in enumerate(izquierda):
        _renglon(c, _IZQ, y - i * _ALTO_CASILLA, etiqueta, valor, ancho)
    for i, (etiqueta, valor) in enumerate(derecha):
        _renglon(c, _COL2, y - i * _ALTO_CASILLA, etiqueta, valor, ancho)
    y -= len(izquierda) * _ALTO_CASILLA + 0.6 * cm

    _acarreo(c, _IZQ, y, ancho, con.acarreo_metros, con.acarreo_viajes)
    _acarreo(c, _COL2, y, ancho, sin.acarreo_metros, sin.acarreo_viajes)
    y -= 1.1 * cm

    for i, (etiqueta, campo) in enumerate((('Fleje', 'fleje'),
                                           ('Grapa Hebilla', 'hebilla'),
                                           ('Gel', 'gel'))):
        _renglon(c, _IZQ, y - i * _ALTO_CASILLA, etiqueta,
                 getattr(con, campo), ancho)
        _renglon(c, _COL2, y - i * _ALTO_CASILLA, etiqueta,
                 getattr(sin, campo), ancho)
    y -= 3 * _ALTO_CASILLA + 0.8 * cm

    c.setFont('Helvetica', 9)
    c.drawString(_IZQ, y, 'SE ELABORA EL PRESENTE CUADERNO DE OBRA EN SEÑAL '
                          'DE CONFORMIDAD DE LOS TRABAJOS')
    c.drawString(_IZQ, y - 0.45 * cm, 'EJECUTADOS')

    # La firma: el nombre del encargado sobre la raya.
    y_firma = 2.4 * cm
    c.setLineWidth(0.6)
    c.line(_ANCHO / 2 - 3 * cm, y_firma, _ANCHO / 2 + 3 * cm, y_firma)
    if h.encargado:
        _texto_que_entra(c, h.encargado, 6 * cm, tamano=10)
        c.drawCentredString(_ANCHO / 2, y_firma + 0.15 * cm, h.encargado)
    c.setFont('Helvetica', 9)
    c.drawCentredString(_ANCHO / 2, y_firma - 0.45 * cm, 'ENCARGADO')


def generar_pdf_reforzamiento(hojas):
    """Una página por poste."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f'Cuaderno de obra {hojas[0].sst}' if hojas else 'Cuaderno de obra')
    c.setStrokeColor(colors.black)
    for h in hojas:
        _pagina(c, h)
        c.showPage()
    c.save()
    return buffer.getvalue()
