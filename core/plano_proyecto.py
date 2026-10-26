"""El plano proyectado de una obra de varios días, en DXF.

El coordinador lo sube a la SST. De aquí salen tres cosas:

- el dibujo, simplificado a líneas y textos, para que la app lo muestre;
- los trabajos del proyecto: cada texto que dice lo que falta hacer
  ("PROY.", "INSTALAR", "EMPALMAR"). El capataz los marca en su parte;
- el replanteo: el mismo DXF con esos textos pasados a lo instalado
  ("INST.", "SE INSTALÓ", "SE EMPALMÓ"), los metros reales y el avance.

Los planos son sin escala: los metros salen de lo que dice el texto, no del
largo de la línea dibujada.
"""
import io
import re
import unicodedata
import zlib
from decimal import Decimal

from .errores import ErrorNegocio

# Un DXF de una lámina pesa unos 8 MB. Más que esto no es un plano de obra.
DXF_MAXIMO = 40 * 1024 * 1024

# El cajetín y el marco no son obra.
CAPAS_SIN_OBRA = ('CAJETIN', 'TEXTO CAJETIN', 'MARCO', 'LOGO')

# Lo que no se dibuja en la app: rellenos y la cuadrícula.
TIPOS_DIBUJABLES = {'LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC',
                    'ELLIPSE', 'SPLINE', 'TEXT', 'MTEXT', 'INSERT',
                    'DIMENSION', 'MULTILEADER', 'SOLID'}

TUBO, EMPALME, CABLE = 'tubo', 'empalme', 'cable'


def sin_tildes(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto)
                   if unicodedata.category(c) != 'Mn')


def texto_plano(entidad):
    """Lo que dice un TEXT, MTEXT o MULTILEADER, sin códigos de formato."""
    from ezdxf.tools.text import plain_mtext

    tipo = entidad.dxftype()
    if tipo == 'TEXT':
        return entidad.plain_text()
    if tipo == 'MTEXT':
        return entidad.plain_text(split=False)
    if tipo == 'MULTILEADER':
        mtext = entidad.context.mtext
        return plain_mtext(mtext.default_content, split=False) if mtext else ''
    return ''


def _capa_sin_obra(capa):
    c = sin_tildes(capa).upper()
    return any(c.startswith(p) for p in CAPAS_SIN_OBRA)


_METROS = re.compile(r'\(\s*([\d]+(?:[.,]\d+)?)\s*M\s*\)')
_CANTIDAD = re.compile(r'\b0*(\d+)\s+TUBOS?\b')


def trabajo_de(texto):
    """El trabajo que describe [texto], o None si no es un trabajo pendiente.

    Devuelve {tipo, unidad, proyectado, cantidad}: cuántos metros dice el
    proyecto (los tubos lo traen entre paréntesis, "(82.00m)") y cuántos
    tubos van en paralelo. Un empalme es una unidad."""
    t = ' '.join(sin_tildes(texto).upper().split())
    if not re.search(r'\bPROY\b|\bPROY\.|\bINSTALAR\b|\bEMPALMAR\b', t):
        return None
    if 'EMPALMAR' in t:
        return {'tipo': EMPALME, 'unidad': 'UND', 'proyectado': Decimal('1'),
                'cantidad': 1}
    m = _METROS.search(t)
    metros = Decimal(m.group(1).replace(',', '.')) if m else None
    if 'TUBO' in t:
        c = _CANTIDAD.search(t)
        return {'tipo': TUBO, 'unidad': 'M', 'proyectado': metros,
                'cantidad': int(c.group(1)) if c else 1}
    return {'tipo': CABLE, 'unidad': 'M', 'proyectado': metros, 'cantidad': 1}


def revisar_archivo(contenido):
    """Corta antes de leerlo si el archivo no es un DXF de un tamaño
    razonable. Es barato: lo pesado se lee en un proceso aparte."""
    if not contenido:
        raise ErrorNegocio('El archivo está vacío.')
    if len(contenido) > DXF_MAXIMO:
        raise ErrorNegocio('El plano pesa demasiado.')
    if contenido[:4] == b'AC10':
        raise ErrorNegocio('Ese archivo es DWG. En AutoCAD guárdalo como '
                           '"AutoCAD DXF" y súbelo de nuevo.')
    cabeza = contenido[:2048].lstrip()
    if not (cabeza.startswith(b'0') or cabeza.startswith(b'999')
            or cabeza.startswith(b'AutoCAD Binary DXF')):
        raise ErrorNegocio('Ese archivo no es un plano DXF.')


def leer_archivo(ruta):
    """El documento ezdxf del DXF en [ruta]. Un DXF guardado desde AutoCAD
    se lee directo; si viene con algún defecto, se intenta recuperarlo."""
    import ezdxf
    from ezdxf import recover

    try:
        doc = ezdxf.readfile(ruta)
        # Repara lo que falte (materiales, capas) para poder volver a
        # escribirlo como replanteo.
        doc.audit()
        return doc
    except ezdxf.DXFStructureError:
        pass
    try:
        doc, _auditor = recover.readfile(ruta)
    except (ezdxf.DXFStructureError, IOError, ValueError):
        raise ErrorNegocio('No se pudo leer el plano: ¿es un DXF?')
    return doc


def _rgb(doc, entidad):
    """El color con que se ve la entidad, como '#rrggbb'. El blanco y el
    negro de AutoCAD (7) se dejan en gris claro: la app es oscura."""
    from ezdxf import colors

    aci = entidad.dxf.get('color', 256)
    if aci == 256:  # por capa
        capa = doc.layers.get(entidad.dxf.layer) if doc.layers.has_entry(
            entidad.dxf.layer) else None
        aci = abs(capa.color) if capa else 7
    if aci in (0, 7, 255) or not 1 <= aci <= 255:
        return '#d0d0d0'
    r, g, b = colors.aci2rgb(aci)
    return f'#{r:02x}{g:02x}{b:02x}'


def _explotar(entidad, profundidad=0):
    """Las entidades simples que forman [entidad]: los bloques, cotas y
    multileaders se descomponen en líneas y textos."""
    tipo = entidad.dxftype()
    if tipo in ('INSERT', 'DIMENSION', 'MULTILEADER') and profundidad < 4:
        try:
            for hija in entidad.virtual_entities():
                yield from _explotar(hija, profundidad + 1)
        except Exception:
            return
        return
    yield entidad


def _trazo(entidad):
    """Los puntos de una línea o curva, o None si no es una."""
    from ezdxf import path

    if entidad.dxftype() not in ('LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE',
                                 'ARC', 'ELLIPSE', 'SPLINE', 'SOLID'):
        return None
    try:
        p = path.make_path(entidad)
        return [(v.x, v.y) for v in p.flattening(0.25, segments=8)]
    except Exception:
        return None


def analizar(doc):
    """El dibujo y los trabajos del plano.

    Devuelve {'dibujo': {...}, 'trabajos': [...]}. Las coordenadas van
    corridas al origen y redondeadas a centímetros: el plano está en
    coordenadas UTM y los números enormes no sirven para dibujar."""
    msp = doc.modelspace()
    trazos, textos, trabajos = [], [], []
    for entidad in msp:
        if entidad.dxftype() not in TIPOS_DIBUJABLES:
            continue
        capa = entidad.dxf.layer
        # Los trabajos se buscan en los textos tal como están en el plano,
        # antes de descomponer el multileader: su handle es el que se
        # reemplaza al armar el replanteo.
        if entidad.dxftype() in ('TEXT', 'MTEXT', 'MULTILEADER') \
                and not _capa_sin_obra(capa):
            dice = texto_plano(entidad).strip()
            trabajo = trabajo_de(dice) if dice else None
            if trabajo:
                x, y = _posicion(entidad)
                trabajos.append({'handle': entidad.dxf.handle,
                                 'texto': ' '.join(dice.split()),
                                 'capa': capa, 'x': x, 'y': y, **trabajo})
        for parte in _explotar(entidad):
            color = _rgb(doc, parte if parte.dxf.get('color', 256) != 0
                         else entidad)
            puntos = _trazo(parte)
            if puntos and len(puntos) > 1:
                trazos.append({'c': color, 'p': puntos})
                continue
            if parte.dxftype() in ('TEXT', 'MTEXT'):
                dice = texto_plano(parte).strip()
                if not dice:
                    continue
                x, y = _posicion(parte)
                textos.append({'c': color, 't': dice, 'x': x, 'y': y,
                               'h': _altura(parte),
                               'r': parte.dxf.get('rotation', 0) or 0})

    xs = [x for t in trazos for x, _ in t['p']] + [t['x'] for t in textos]
    ys = [y for t in trazos for _, y in t['p']] + [t['y'] for t in textos]
    if not xs:
        raise ErrorNegocio('El plano no tiene nada dibujado.')
    x0, y0 = min(xs), min(ys)

    def corto(v):
        return round(v, 2)

    dibujo = {
        'ancho': corto(max(xs) - x0), 'alto': corto(max(ys) - y0),
        'trazos': [{'c': t['c'],
                    'p': [v for x, y in t['p']
                          for v in (corto(x - x0), corto(y - y0))]}
                   for t in trazos],
        'textos': [{**t, 'x': corto(t['x'] - x0), 'y': corto(t['y'] - y0),
                    'h': corto(t['h'])} for t in textos],
    }
    for t in trabajos:
        t['x'], t['y'] = corto(t['x'] - x0), corto(t['y'] - y0)
    return {'dibujo': dibujo, 'trabajos': trabajos}


def _posicion(entidad):
    if entidad.dxftype() == 'MULTILEADER':
        ctx = entidad.context
        if ctx.mtext is not None:
            p = ctx.mtext.insert
            return p.x, p.y
        return ctx.base_point.x, ctx.base_point.y
    p = entidad.dxf.insert
    return p.x, p.y


def _altura(entidad):
    if entidad.dxftype() == 'MTEXT':
        return entidad.dxf.get('char_height', 1.0) or 1.0
    return entidad.dxf.get('height', 1.0) or 1.0


def comprimir(contenido):
    return zlib.compress(contenido, 6)


def descomprimir(guardado):
    return zlib.decompress(bytes(guardado))


# ── El replanteo ────────────────────────────────────────────────────────────

_A_INSTALADO = [
    (re.compile(r'\bINSTALAR\b'), 'SE INSTALÓ'),
    (re.compile(r'\bInstalar\b'), 'Se instaló'),
    (re.compile(r'\bEMPALMAR\b'), 'SE EMPALMÓ'),
    (re.compile(r'\bEmpalmar\b'), 'Se empalmó'),
    (re.compile(r'\bPROY\b\.?'), 'INST.'),
    (re.compile(r'\bProy\b\.?'), 'Inst.'),
]


def _fmt(metros):
    return f'{Decimal(metros):.2f}'


def a_instalado(texto, metros=None, cantidad=1):
    """El texto de un trabajo ya hecho: con los verbos pasados a lo
    instalado y, si hay [metros] reales, esos metros en lugar de los del
    proyecto. Con varios tubos en paralelo se agrega el total."""
    for patron, nuevo in _A_INSTALADO:
        texto = patron.sub(nuevo, texto)
    if metros is not None:
        def real(m):
            total = (f'\\PTotal ({_fmt(Decimal(metros) * cantidad)}m)'
                     if cantidad > 1 else '')
            return f'({_fmt(metros)}m){total}'
        texto, n = re.subn(r'\(\s*[\d]+(?:[.,]\d+)?\s*[mM]\s*\)', real, texto,
                           count=1)
    return texto


def replanteo(doc, hechos, avance=None):
    """Pasa a lo instalado, en [doc], los trabajos de [hechos]
    ({handle: (metros reales o None, tubos en paralelo)}) y pone el avance
    en el cajetín si viene. Lo que no se hizo queda como proyectado.

    Devuelve los bytes del DXF nuevo."""
    msp = doc.modelspace()
    for entidad in msp:
        tipo = entidad.dxftype()
        if tipo not in ('TEXT', 'MTEXT', 'MULTILEADER'):
            continue
        handle = entidad.dxf.handle
        if handle in hechos:
            metros, cantidad = hechos[handle]
            _reescribir(entidad, lambda t: a_instalado(t, metros, cantidad))
        elif avance is not None and tipo == 'TEXT' \
                and re.fullmatch(r'0*%+', (entidad.dxf.text or '').strip()):
            # El "AVANCE 000%" del cajetín.
            entidad.dxf.text = f'{avance}%%%'
    salida = io.StringIO()
    doc.write(salida)
    return salida.getvalue().encode(doc.output_encoding or 'utf-8',
                                    errors='replace')


def _reescribir(entidad, cambio):
    tipo = entidad.dxftype()
    if tipo == 'TEXT':
        entidad.dxf.text = cambio(entidad.dxf.text)
    elif tipo == 'MTEXT':
        entidad.text = cambio(entidad.text)
    elif tipo == 'MULTILEADER' and entidad.context.mtext is not None:
        mtext = entidad.context.mtext
        mtext.default_content = cambio(mtext.default_content)
