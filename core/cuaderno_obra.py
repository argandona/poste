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

TRABAJOS_CABLE = {'T': 'Traslado', 'I': 'Instalación', 'R': 'Retiro'}


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
    conexiones: list = field(default_factory=list)   # comentarios escritos
    capataz: str = ''
    actividad: str = ''

    def partida(self, codigo):
        return sum((p.cantidad for p in self.partidas if p.codigo == codigo),
                   Decimal('0'))


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
    conexiones = []
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
        conexiones=conexiones,
        capataz=ultima.usuario.nombre if ultima else '',
        actividad=sst.actividad.nombre if sst.actividad_id else '',
    )


def _con(items, palabras, excluyendo=()):
    return [i for i in items
            if any(p in normalizar(i.descripcion) for p in palabras)
            and not any(e in normalizar(i.descripcion) for e in excluyendo)]


def _lista(items):
    return ', '.join(f'{i.descripcion} ({numero(i.cantidad)})' for i in items)


# Lo que se cambia en el poste: qué se buscó en el recupero (lo retirado) y qué
# en el material (lo instalado). El catálogo de recupero se escribe a mano, así
# que se busca por texto y con sus variantes.
CAMBIOS = [
    ('luminaria', ('luminaria', 'farola', 'falora', 'lampara'), (), ('luminaria',), ()),
    ('pastoral', ('pastoral',), ('abrazadera',), ('pastoral',), ('abrazadera',)),
    ('caja de distribución', ('caja',), (), ('caja',), ()),
    ('abrazadera tipo corona con ganchos', ('corona',), (), ('gancho',), ()),
]


def lineas_del_cuaderno(d):
    """El cuerpo del cuaderno, renglón por renglón, en el orden en que se
    ejecuta la obra."""
    lineas = ['Por la presente se informa que la SST se ejecutó según lo detallado:']

    # Por el comienzo: "ABRAZADERA POSTE ..." también dice poste y no lo es.
    postes_nuevos = [m for m in d.materiales
                     if normalizar(m.descripcion).startswith('poste')]
    codigos = [str(e.get('codigo')) for e in d.elementos_plano
               if e.get('assetId') == 'poste_nuevo' and e.get('codigo')]
    for poste in postes_nuevos:
        texto = f'Se instaló poste {poste.descripcion}'
        if codigos:
            texto += f' con código {", ".join(codigos)}'
        lineas.append(texto)
    if postes_nuevos or any(d.partida(p) > 0 for p in PARTIDAS_RETIRO_POSTE):
        for n in d.postes:
            lineas.append(f'Se retiró poste {n}')

    if d.partida(TRASLADO_PASTORAL) > 0:
        lineas.append('Se realizó traslado de pastoral existente')
    if d.partida(TRASLADO_LUMINARIA) > 0:
        lineas.append('Se realizó traslado de luminaria existente')

    for nombre, rec, rec_no, mat, mat_no in CAMBIOS:
        retirado = _con(d.recuperos, rec, rec_no)
        instalado = _con(d.materiales, mat, mat_no)
        if retirado and instalado:
            lineas.append(f'Se realizó retiro e instalación de {nombre}: se retiró '
                          f'{_lista(retirado)} y se instaló {_lista(instalado)}')
        elif retirado:
            lineas.append(f'Se retiró {nombre}: {_lista(retirado)}')
        elif instalado:
            lineas.append(f'Se instaló {nombre}: {_lista(instalado)}')

    # Cables y arrastre, tramo por tramo, tal como están en el plano.
    tramos = [e for e in d.elementos_plano if e.get('tipo') == 'cable']
    for e in tramos:
        trabajo = TRABAJOS_CABLE.get(e.get('estado'))
        if trabajo and e.get('descripcion'):
            lineas.append(f'{trabajo} {e["descripcion"]} {numero(e.get("metros"))} metros')
    for e in tramos:
        if e.get('estado') == 'A':
            texto = f'Arrastre de poste {numero(e.get("metros"))} metros'
            if e.get('pendiente') is True:
                texto += ' en zona de pendiente mayor a 30° o escalera'
            lineas.append(texto)

    trasladadas = d.partida(CONEXIONES_TRASLADADAS)
    if trasladadas > 0 or d.conexiones:
        texto = 'Se realizó traslado de '
        texto += (f'{numero(trasladadas)} suministro'
                  f'{"" if trasladadas == 1 else "s"}' if trasladadas > 0
                  else 'suministros')
        if d.conexiones:
            texto += f': {"; ".join(d.conexiones)}'
        lineas.append(texto)
    return lineas


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
