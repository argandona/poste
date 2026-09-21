"""Cuaderno de obra de una SST y lo que se liquidó en ella.

El cuaderno calca el formato impreso de Encossa (co.pdf): encabezado con la SST,
el cliente y los responsables, y una hoja cuadriculada donde se escribe qué se
hizo. Ese texto no se escribe a mano: sale de lo que el capataz ya cargó al
liquidar (material, mano de obra y recupero) y de lo que dibujó en el plano.

Está partido en tres para poder probar cada cosa sola:
- `reunir` junta de la base todo lo liquidado de la SST;
- `lineas_del_cuaderno` redacta el cuerpo, sin tocar la base;
- `generar_pdf_cuaderno` lo pinta.
"""
import io
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from django.db.models import Q
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas

CLIENTE = 'TECSUR'
TEC_TECSUR = 'Eduardo Rabines'
TEC_LDS = 'Patrick Miranda'

# Partidas que dicen que se quitó el poste aunque no se haya puesto otro.
PARTIDAS_RETIRO_POSTE = ('*090468', '*090497', '*090491')
TRASLADO_PASTORAL = '*091356'
TRASLADO_LUMINARIA = '*091322'
CONEXIONES_TRASLADADAS = '*093081'

# Los dos postes del catálogo, como se nombran en el cuaderno. La descripción
# del catálogo trae la medida completa ("7,5 / 150 / 150 / 270 P.A.P. ..."),
# que en obra nadie escribe así.
POSTES = {
    '5331596': 'PRFV 7/150',
    '5331616': 'PRFV 9/200',
}

# Cimentar el poste se liquida con cualquiera de estas dos.
CIMENTACION = ('*094918', '*090482')

# La subida al poste: la partida, o el cable bipolar cuando el metrado es el de
# una subida y no el de un tendido.
SUBIDA_PARTIDA = '*091240'
SUBIDA_CABLE = '5031165'
SUBIDA_MIN, SUBIDA_MAX = Decimal('1'), Decimal('13')

MENSULA_DOBLE = '*098670'
DIAGONAL = '*090060'
ABRAZADERA_4 = '*090065'
# Lo instalado, por su partida. El alumbrado va primero porque es lo que se
# monta en el poste; la acometida, después. La cantidad solo se escribe cuando
# hay más de uno: "Se instaló luminaria" se lee mejor que "luminaria (1)".
ALUMBRADO_INSTALADO = [
    ('*091320', 'Se instaló luminaria'),
    ('*091346', 'Se instaló pastoral'),
]
INSTALADO_POR_PARTIDA = [
    ('*093242', 'Se instaló caja de distribución'),
    ('*093045', 'Se instaló abrazadera tipo corona con ganchos'),
]

# Lo retirado se sabe por el recupero. El catálogo de recuperos se escribe a
# mano, así que se busca por texto y con sus variantes: (nombre, palabras,
# palabras que lo descartan).
RETIRADOS = [
    ('luminaria', ('luminaria', 'farola', 'falora', 'lampara'), ()),
    ('pastoral', ('pastoral',), ('abrazadera',)),
    ('caja de distribución', ('caja',), ()),
    ('abrazadera tipo corona con ganchos', ('corona',), ()),
]

# Retenidas: se escriben por el tipo de trabajo que el capataz marcó, no por la
# partida, porque la partida es la misma para la simple y la violín.
RETENIDAS = [
    ('retenida tipo "y"', 'Se instaló retenida tipo "Y"'),
    ('violin', 'Se instaló retenida tipo violín'),
    ('retenida simple', 'Se instaló retenida tipo simple'),
]

ACARREO = '*090633'
ARRASTRE_PENDIENTE = '*090632'
ARRASTRE_PLANO = '*090630'
# Cada tramo de acarreo se recorre seis veces: ida y vuelta, tres veces.
VIAJES_DE_ACARREO = 6


def normalizar(texto):
    """Sin tildes y en minúsculas, para buscar por palabras."""
    t = unicodedata.normalize('NFKD', texto or '')
    return ''.join(c for c in t if not unicodedata.combining(c)).lower()


def numero(valor):
    """12 en vez de 12.00, y 12.5 en vez de 12.50."""
    v = Decimal(str(valor or 0))
    if v == v.to_integral_value():
        return str(int(v))
    return f'{v.normalize():f}'


@dataclass
class Item:
    codigo: str
    descripcion: str
    cantidad: Decimal
    precio: Decimal = Decimal('0')


@dataclass
class Liquidado:
    """Todo lo que se liquidó en una SST, ya sumado entre sus postes."""
    materiales: list = field(default_factory=list)   # [Item]
    partidas: list = field(default_factory=list)     # [Item]
    recuperos: list = field(default_factory=list)    # [Item]
    elementos_plano: list = field(default_factory=list)
    postes: list = field(default_factory=list)       # números asignados
    tipos: list = field(default_factory=list)        # tipos de trabajo marcados
    conexiones: list = field(default_factory=list)   # comentarios escritos
    capataz: str = ''
    actividad: str = ''

    def partida(self, codigo):
        return sum((p.cantidad for p in self.partidas if p.codigo == codigo),
                   Decimal('0'))

    def material(self, matricula):
        return sum((m.cantidad for m in self.materiales
                    if m.codigo == matricula), Decimal('0'))

    def hay_tipo(self, palabra):
        """Si se liquidó un tipo de trabajo cuyo nombre trae esa palabra."""
        return any(palabra in normalizar(t) for t in self.tipos)

    def plano(self, tipo):
        return [e for e in self.elementos_plano if e.get('tipo') == tipo]


def reunir(sst):
    """Junta lo liquidado en los postes de la SST."""
    from .models import (
        LiquidacionSuministro, PlanoSST, Suministro, SuministroRecupero,
    )

    codigo = sst.codigo or sst.sst
    suministros = list(Suministro.objects
                       .filter(sst_suministros__sst=sst)
                       .order_by('numero_suministro'))
    filtro = Q(suministro__in=suministros)
    if codigo:
        filtro |= Q(sst_externo=codigo)
    liquidaciones = list(
        LiquidacionSuministro.objects.filter(filtro)
        .select_related('usuario', 'tipo_trabajo')
        .prefetch_related('partidas__mano_de_obra',
                          'materiales_consumidos__material')
        .order_by('id_liquidacion'))

    materiales, partidas = {}, {}
    tipos, conexiones = [], []
    for liq in liquidaciones:
        for c in liq.materiales_consumidos.all():
            m = c.material
            item = materiales.setdefault(
                m.matricula, Item(m.matricula, m.descripcion, Decimal('0'), m.precio))
            item.cantidad += c.cantidad
        for p in liq.partidas.all():
            mo = p.mano_de_obra
            item = partidas.setdefault(
                mo.partida, Item(mo.partida, mo.descripcion, Decimal('0'), mo.precio))
            item.cantidad += p.cantidad
        if liq.tipo_trabajo.nombre not in tipos:
            tipos.append(liq.tipo_trabajo.nombre)
        if liq.comentario.strip() and 'conexion' in normalizar(liq.tipo_trabajo.nombre):
            conexiones.append(liq.comentario.strip())

    recuperos = {}
    for r in (SuministroRecupero.objects
              .filter(suministro__in=suministros)
              .select_related('recupero')):
        item = recuperos.setdefault(
            r.recupero_id,
            Item(r.recupero.matricula, r.recupero.descripcion, Decimal('0')))
        item.cantidad += r.cantidad

    plano = (PlanoSST.objects.filter(empresa_id=sst.empresa_id, sst_codigo=codigo)
             .first() if codigo else None)
    ultima = liquidaciones[-1] if liquidaciones else None
    return Liquidado(
        materiales=[i for i in materiales.values() if i.cantidad > 0],
        partidas=[i for i in partidas.values() if i.cantidad > 0],
        recuperos=[i for i in recuperos.values() if i.cantidad > 0],
        elementos_plano=list(plano.elementos) if plano else [],
        postes=[s.numero_suministro for s in suministros],
        tipos=tipos,
        conexiones=conexiones,
        capataz=ultima.usuario.nombre if ultima else '',
        actividad=sst.actividad.nombre if sst.actividad_id else '',
    )


def lineas_del_cuaderno(d):
    """El cuerpo del cuaderno, renglón por renglón, en el orden en que se
    ejecuta la obra: primero el poste, después lo que se le cuelga, y al final
    los traslados, el acarreo y la vereda.

    Cada renglón sale de algo que el capataz ya cargó: una partida liquidada,
    un material, un tipo de trabajo marcado o un trazo del plano. Aquí no se
    inventa nada ni se pregunta nada."""
    lineas = ['Por la presente se informa que la SST se ejecutó según lo detallado:']

    _poste(d, lineas)
    _postes_retirados(d, lineas)
    _alumbrado_instalado(d, lineas)
    _traslados_de_alumbrado(d, lineas)
    _subida_al_poste(d, lineas)
    _ferreteria(d, lineas)
    _retenidas(d, lineas)
    _retirados(d, lineas)
    _cables(d, lineas)
    _arrastre(d, lineas)
    _acarreo(d, lineas)
    _veredas(d, lineas)
    _suministros_trasladados(d, lineas)

    return lineas


def _poste(d, lineas):
    """El poste instalado, con su cimentación y el código que se le puso."""
    # Por el comienzo: "ABRAZADERA POSTE ..." también dice poste y no lo es.
    puestos = [m for m in d.materiales
               if m.codigo in POSTES or normalizar(m.descripcion).startswith('poste')]
    if not puestos:
        return
    cimentado = any(d.partida(p) > 0 for p in CIMENTACION)
    # Las figuras del plano no llevan `tipo`: se reconocen por su assetId.
    codigos = [str(e.get('codigo')) for e in d.elementos_plano
               if e.get('assetId') == 'poste_nuevo' and e.get('codigo')]
    for poste in puestos:
        texto = f'Se instaló {POSTES.get(poste.codigo, poste.descripcion)}'
        if poste.cantidad > 1:
            texto += f' ({numero(poste.cantidad)})'
        if cimentado:
            texto += ' Cimentado'
        if codigos:
            texto += f' con código {", ".join(codigos)}'
        lineas.append(texto)


def _postes_retirados(d, lineas):
    """Los postes de la SST que salieron. Se sabe porque se puso uno nuevo o
    porque se liquidó un retiro, que no siempre trae poste nuevo detrás."""
    hay_nuevo = any(m.codigo in POSTES or normalizar(m.descripcion).startswith('poste')
                    for m in d.materiales)
    if not hay_nuevo and not any(d.partida(p) > 0 for p in PARTIDAS_RETIRO_POSTE):
        return
    for numero_poste in d.postes:
        lineas.append(f'Se retiró poste {numero_poste}')


def _alumbrado_instalado(d, lineas):
    """La luminaria y el pastoral que se pusieron, por su partida."""
    for codigo, texto in ALUMBRADO_INSTALADO:
        cantidad = d.partida(codigo)
        if cantidad <= 0:
            continue
        lineas.append(texto if cantidad == 1
                      else f'{texto} ({numero(cantidad)})')


def _traslados_de_alumbrado(d, lineas):
    """Trasladar no consume ni recupera nada: se sabe por su partida."""
    pastoral = d.partida(TRASLADO_PASTORAL) > 0
    luminaria = d.partida(TRASLADO_LUMINARIA) > 0
    if pastoral and luminaria:
        lineas.append('Se trasladó pastoral + luminaria existente')
    elif pastoral:
        lineas.append('Se trasladó pastoral')
    elif luminaria:
        lineas.append('Se trasladó luminaria')


def _subida_al_poste(d, lineas):
    """La subida al poste, por su partida o por el metrado del cable bipolar.

    Ese cable se usa para dos cosas: la subida y el tendido. Lo que las separa
    es el metrado — una subida son unos pocos metros, un tendido son muchos."""
    metros = d.material(SUBIDA_CABLE)
    es_subida = SUBIDA_MIN < metros < SUBIDA_MAX
    if d.partida(SUBIDA_PARTIDA) <= 0 and not es_subida:
        return
    texto = 'Se instaló Subida AP N2XY 2-1x6'
    if metros > 0:
        texto += f' ({numero(metros)} metros)'
    lineas.append(texto)


def _ferreteria(d, lineas):
    if d.partida(MENSULA_DOBLE) > 0:
        lineas.append('Se instaló ménsula doble de madera')
    diagonal = d.partida(DIAGONAL)
    if diagonal > 0:
        lineas.append(f'Se instaló diagonal de acero ({numero(diagonal)})')
    abrazadera = d.partida(ABRAZADERA_4)
    if abrazadera > 0:
        lineas.append(f'Se instaló abrazadera de 4 pernos ({numero(abrazadera)})')
    for codigo, texto in INSTALADO_POR_PARTIDA:
        if d.partida(codigo) > 0:
            lineas.append(texto)


def _retenidas(d, lineas):
    """Se escriben por el tipo de trabajo marcado: la partida no distingue la
    retenida simple de la violín."""
    for palabra, texto in RETENIDAS:
        if d.hay_tipo(palabra):
            lineas.append(texto)


def _retirados(d, lineas):
    """Lo que se bajó y volvió al almacén, según la pestaña de Recupero."""
    for nombre, palabras, excluyendo in RETIRADOS:
        bajado = [r for r in d.recuperos
                  if any(p in normalizar(r.descripcion) for p in palabras)
                  and not any(e in normalizar(r.descripcion) for e in excluyendo)]
        if bajado:
            detalle = ', '.join(f'{r.descripcion} ({numero(r.cantidad)})'
                                for r in bajado)
            lineas.append(f'Se retiró {nombre}: {detalle}')


def _suministros_trasladados(d, lineas):
    """Las acometidas que se movieron. El capataz anota los suministros en el
    comentario del tipo de trabajo, y van tal cual."""
    trasladadas = d.partida(CONEXIONES_TRASLADADAS)
    if trasladadas <= 0 and not d.conexiones:
        return
    texto = 'Se realizó traslado de '
    if trasladadas > 0:
        texto += (f'{numero(trasladadas)} suministro'
                  f'{"" if trasladadas == 1 else "s"}')
    else:
        texto += 'suministros'
    if d.conexiones:
        texto += f': {"; ".join(d.conexiones)}'
    lineas.append(texto)


def _cables(d, lineas):
    """Los cables trasladados, uno por uno, tal como están en el plano."""
    tramos = d.plano('cable')
    for e in tramos:
        if e.get('estado') == 'T' and e.get('descripcion'):
            lineas.append(f'Se trasladó {e["descripcion"]} '
                          f'{numero(e.get("metros"))} metros')
    # Los de comunicación no llevan tipo ni metros: con que haya uno se escribe
    # una vez, igual que su partida vale 1.
    if any(e.get('estado') == 'C' for e in tramos):
        lineas.append('Se trasladó cables de comunicación')


def _arrastre(d, lineas):
    for e in d.plano('cable'):
        if e.get('estado') != 'A':
            continue
        zona = ('en zona de pendiente mayor a 30° o escalera'
                if e.get('pendiente') is True else 'en plano')
        lineas.append('Se realizó arrastre de poste '
                      f'{numero(e.get("metros"))} metros {zona}')


def _acarreo(d, lineas):
    """El acarreo se recorre seis veces, así que el total es el tramo por seis.

    El tramo es el mismo que se arrastró el poste: las dos partidas del
    arrastre, sumadas."""
    if d.partida(ACARREO) <= 0:
        return
    tramo = d.partida(ARRASTRE_PENDIENTE) + d.partida(ARRASTRE_PLANO)
    total = tramo * VIAJES_DE_ACARREO
    lineas.append(
        f'Se realizó acarreo de equipos y herramientas por un tramo de '
        f'{numero(tramo)} metros por {VIAJES_DE_ACARREO} viajes dando en total '
        f'{numero(total)} metros para lo cual se utilizó la vía más corta')


def _veredas(d, lineas):
    """Un renglón por paño reparado, con sus medidas y su área."""
    for pano in d.plano('vereda'):
        largo = Decimal(str(pano.get('largo') or 0))
        ancho = Decimal(str(pano.get('ancho') or 0))
        if largo <= 0 or ancho <= 0:
            continue
        lineas.append(f'Se reparó vereda de 10cm {numero(largo)} x '
                      f'{numero(ancho)} = {numero(largo * ancho)}')


# ── PDF ──────────────────────────────────────────────────────────────────────
_LOGO = Path(__file__).resolve().parent / 'data' / 'logo_encossa.png'
_ROJO = colors.HexColor('#C0392B')

# La cuadrícula del formato: 31 columnas, casi cuadradas.
_X0, _X1 = 42, 553
_COLUMNAS = 31
_LADO = (_X1 - _X0) / _COLUMNAS
_TOPE_CUADRICULA = 572
_PIE = 150          # debajo de aquí va la firma
_MARGEN = 5


def _encabezado(c, datos, pagina, paginas):
    ancho, alto = A4
    if _LOGO.exists():
        c.drawImage(ImageReader(str(_LOGO)), 45, alto - 92, width=150,
                    height=48.6, mask='auto')
    c.setFont('Helvetica-Bold', 15)
    c.drawCentredString(ancho / 2 + 10, alto - 70, 'CUADERNO DE OBRA')
    c.setFont('Helvetica', 14)
    c.setFillColor(_ROJO)
    c.drawRightString(_X1, alto - 70, f'N° {datos["numero"]}')
    c.setFillColor(colors.black)
    if paginas > 1:
        c.setFont('Helvetica', 7)
        c.drawRightString(_X1, alto - 82, f'Hoja {pagina} de {paginas}')

    def campo(etiqueta, valor, x, y, fin):
        c.setFont('Helvetica', 9)
        c.drawString(x, y, etiqueta)
        inicio = x + c.stringWidth(etiqueta, 'Helvetica', 9) + 3
        c.setLineWidth(0.5)
        c.line(inicio, y - 2, fin, y - 2)
        c.setFont('Helvetica-Bold', 9)
        texto = str(valor or '')
        while texto and c.stringWidth(texto, 'Helvetica-Bold', 9) > fin - inicio - 4:
            texto = texto[:-1]
        c.drawString(inicio + 3, y, texto)

    y = alto - 125
    campo('N° SST:', datos['sst'], _X0, y, _X1)
    campo('CLIENTE:', CLIENTE, _X0, y - 24, _X1)
    campo('DIRECCIÓN:', datos['direccion'], _X0, y - 48, _X1)
    campo('TEC. TECSUR:', TEC_TECSUR, _X0, y - 72, 390)
    campo('DISTRITO:', datos['distrito'], 400, y - 72, _X1)
    campo('TEC. LDS:', TEC_LDS, _X0, y - 96, 390)
    campo('FECHA:', datos['fecha'], 400, y - 96, _X1)
    campo('ENCARGADO:', datos['encargado'], _X0, y - 120, 390)
    campo('HORA:', datos['hora'], 400, y - 120, _X1)


def _cuadricula(c, abajo):
    filas = int((_TOPE_CUADRICULA - abajo) // _LADO)
    y0 = _TOPE_CUADRICULA - filas * _LADO
    c.setStrokeColor(colors.HexColor('#9E9E9E'))
    c.setLineWidth(0.35)
    for i in range(_COLUMNAS + 1):
        x = _X0 + i * _LADO
        c.line(x, y0, x, _TOPE_CUADRICULA)
    for j in range(filas + 1):
        y = y0 + j * _LADO
        c.line(_X0, y, _X1, y)
    c.setStrokeColor(colors.black)
    return filas


def _renglones(lineas, c):
    """Parte las líneas para que entren en el ancho de la cuadrícula. Cada
    punto de la lista arranca en un renglón nuevo."""
    ancho = _X1 - _X0 - 2 * _MARGEN
    salida = []
    for i, linea in enumerate(lineas):
        fuente = 'Helvetica-Bold' if i == 0 else 'Helvetica'
        vineta = '' if i == 0 else '• '
        partes = simpleSplit(vineta + linea, fuente, 10, ancho)
        for k, parte in enumerate(partes):
            salida.append((parte if k == 0 or not vineta else '   ' + parte, fuente))
        if i == 0:
            salida.append(('', fuente))
    return salida


def generar_pdf_cuaderno(datos, lineas):
    """`datos`: numero, sst, direccion, distrito, fecha, hora, encargado."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f'Cuaderno de obra SST {datos["sst"]}')

    renglones = _renglones(lineas, c)
    por_hoja_final = int((_TOPE_CUADRICULA - _PIE) // _LADO)
    por_hoja = int((_TOPE_CUADRICULA - 60) // _LADO)
    # Las hojas de en medio usan toda la cuadrícula; la última deja lugar a la
    # firma.
    hojas, resto = [], renglones
    while len(resto) > por_hoja_final:
        hojas.append(resto[:por_hoja])
        resto = resto[por_hoja:]
    hojas.append(resto)

    for n, hoja in enumerate(hojas, start=1):
        ultima = n == len(hojas)
        _encabezado(c, datos, n, len(hojas))
        _cuadricula(c, _PIE if ultima else 60)
        for k, (texto, fuente) in enumerate(hoja):
            c.setFont(fuente, 10)
            c.drawString(_X0 + _MARGEN, _TOPE_CUADRICULA - (k + 1) * _LADO + 4, texto)
        if ultima:
            _firma(c, datos['encargado'])
        c.showPage()
    c.save()
    return buffer.getvalue()


def _firma(c, nombre):
    centro = (_X0 + _X1) / 2
    c.setLineWidth(0.8)
    c.line(centro - 110, 95, centro + 110, 95)
    c.setFont('Helvetica-Bold', 10)
    c.drawCentredString(centro, 82, nombre or '')
    c.setFont('Helvetica', 9)
    c.drawCentredString(centro, 70, 'Encargado (Capataz)')
