"""Lo que el paquete de cambio de poste ya incluye, y lo que queda por cobrar.

Cambiar un poste ya trae dentro parte del trabajo que lo rodea: el acarreo, la
rotura de vereda, la subida al poste, el empalme. Si eso se liquida aparte no
se cobra dos veces: se descuenta lo incluido y se cobra la diferencia.

El descuento se calcula **por poste** y recién después se suma por SST, porque
lo incluido depende de cuántos cambios de poste hubo en ese poste, no en la
SST entera.

Esto vivía dentro de la vista del consolidado, así que el Excel exportaba las
cantidades liquidadas sin descontar nada y cobraba de más. Ahora los dos leen
de aquí.
"""
import unicodedata
from decimal import Decimal


def norm_actividad(nombre):
    """El nombre de una actividad como clave: sin tildes, en minúsculas y con
    los espacios colapsados. La misma SST puede venir escrita de dos maneras."""
    texto = (nombre or '').lower().strip()
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto)
                    if unicodedata.category(c) != 'Mn')
    return ' '.join(texto.split())


# Reglas de "lo ya incluido" en el paquete de cambio de poste, por actividad.
# Cobrado = max(0, real - num_cambios * incluido_por_unidad).
INCLUSIONES_CONSOLIDADO = {
    'cambio de poste inaccesible subterraneo': {
        'paquete': ['*090470', '*090471'],
        # Valor entero -> se multiplica por N (total de cambios de poste).
        # Dict {'segun': partida, 'cantidad': v} -> se multiplica por la cantidad
        # de esa partida específica del paquete (ej. solo *090470 con vereda).
        'incluidos': {
            '*090633': 100,   # el cambio de poste ya incluye 100 de acarreo
            '*091840': {'segun': '*090470', 'cantidad': 2},  # 2 incluidos por cambio CON vereda
            # Cambiar el poste ya incluye subirse a él y escalarlo, igual que
            # en cabria aérea. En esta actividad casi nunca se liquidan; el
            # descuento está por si alguna vez se liquidan.
            '*091240': 1,     # subida a poste
            '*090238': 1,     # escalamiento con escalera
            # El cable que baja del poste: el cambio ya incluye retirar hasta
            # 10 metros, que es lo que mide la subida que después vuelve a
            # ponerse. Va por metro, no por unidad.
            '*091411': 10,    # retiro de cable NYY hasta 3-1x16
        },
        # Desde el 2026-09-20 el alumbrado de esta actividad es el mismo tipo
        # de trabajo que el de cabria aérea, así que trae también el conector
        # *090810. Se cuenta por grupos, igual que allá: el paquete incluye
        # dos empalmes sea del tipo que sea, y una luminaria y un pastoral,
        # se hayan instalado, retirado o trasladado.
        'incluidos_grupo': [
            {'partidas': ['*091608', '*090810'], 'cantidad': 2},
            {'partidas': ['*091320', '*091316', '*091322'], 'cantidad': 1},
            {'partidas': ['*091346', '*091357', '*091356'], 'cantidad': 1},
        ],
        # Derivación: el excedente de acarreo se cobra como traslado manual.
        # origen (*090633) ÷ divisor; si supera umbral*N, el sobrante va a destino.
        'derivar': {
            'origen': '*090633', 'destino': '*090634',
            'divisor': Decimal('6'), 'umbral': 100,
        },
    },
    'cambio de poste inacc. cabria aereo': {
        'paquete': ['*090470', '*090471'],
        'incluidos': {
            '*090633': 100,   # acarreo para cimentación
            '*091840': 2,     # rotura de vereda
            '*091240': 1,     # subida a poste
            '*090238': 1,     # escalamiento: cambiar el poste ya lo incluye
            '*091411': 10,    # retiro de cable NYY: 10 metros por cambio
            # Cada retenida, sea violín anclada o templador aéreo, ya trae
            # incluido su perno de anclaje: no se cobra dos veces si además
            # se liquidó en ferretería.
            '*090392': {'segun': ['*090310', '*090320'], 'cantidad': 1},
        },
        # Grupos que comparten una misma cantidad incluida: el paquete trae
        # dos empalmes, sin importar de cuál de los dos tipos, y una luminaria
        # y un pastoral, se hayan instalado, retirado o trasladado.
        'incluidos_grupo': [
            {'partidas': ['*091608', '*090810'], 'cantidad': 2},
            {'partidas': ['*091320', '*091316', '*091322'], 'cantidad': 1},
            {'partidas': ['*091346', '*091357', '*091356'], 'cantidad': 1},
        ],
    },
}

# La actividad subterránea se renombró el 2026-09-20 a "Cambio de poste inacc.
# cabria subterraneo". Sus descuentos de "lo ya incluido" son los mismos: el
# poste sigue siendo el suyo, solo cambió el nombre. Valen los dos mientras
# queden bases sin renombrar.
INCLUSIONES_CONSOLIDADO['cambio de poste inacc. cabria subterraneo'] = \
    INCLUSIONES_CONSOLIDADO['cambio de poste inaccesible subterraneo']


def consolidar_partidas(postes, reglas, buscar_partida):
    """Las partidas de una SST con lo real, lo incluido y lo que se cobra.

    - `postes`: lista de (actividad, {codigo: {'mo': ManoDeObra, 'cantidad': D}}),
      un elemento por poste de la SST. La actividad viaja por poste porque la
      regla que aplica es la suya.
    - `reglas`: el catálogo de inclusiones, por nombre de actividad normalizado.
    - `buscar_partida`: (codigo) -> ManoDeObra o None, para las partidas que
      nacen de una derivación y que nadie liquidó.

    Devuelve `(partidas, cambios)`: un dict {codigo: {'mo', 'real', 'incl',
    'cobra'}} ya sumado entre los postes, y cuántos cambios de poste hubo.
    """
    agregadas = {}
    cambios = Decimal('0')

    for actividad, partidas in postes:
        regla = reglas.get(actividad or '')
        # Cuántos cambios de poste tuvo ESTE poste: es lo que multiplica todo
        # lo incluido.
        num = Decimal('0')
        if regla:
            for codigo in regla['paquete']:
                if codigo in partidas:
                    num += partidas[codigo]['cantidad']
        cambios += num

        for codigo, info in partidas.items():
            real = info['cantidad']
            incl = _incluido(codigo, regla, partidas, num)
            entrada = agregadas.setdefault(
                codigo, {'mo': info['mo'], 'real': Decimal('0'),
                         'incl': Decimal('0'), 'cobra': Decimal('0')})
            entrada['real'] += real
            entrada['incl'] += incl
            entrada['cobra'] += max(real - incl, Decimal('0'))

        _grupos(agregadas, regla, partidas, num)
        _derivaciones(agregadas, regla, partidas, num, buscar_partida)

    return agregadas, cambios


def _incluido(codigo, regla, partidas, num):
    """Lo que el paquete ya trae de esa partida en este poste."""
    cfg = regla['incluidos'].get(codigo) if regla else None
    if cfg is None:
        return Decimal('0')
    if not isinstance(cfg, dict):
        return num * Decimal(cfg)
    # 'segun': lo incluido no va por cambio de poste sino por la cantidad de
    # otra partida — por ejemplo, dos roturas de vereda por cada cambio CON
    # vereda. Puede mirar varias partidas que suman.
    segun = cfg['segun']
    claves = segun if isinstance(segun, (list, tuple)) else [segun]
    base = sum((partidas.get(k, {}).get('cantidad', Decimal('0')) for k in claves),
               Decimal('0'))
    return base * Decimal(cfg['cantidad'])


def _grupos(agregadas, regla, partidas, num):
    """Grupos con cantidad compartida.

    El paquete trae N unidades repartidas entre varias partidas, no N de cada
    una: dos empalmes, sean del tipo que sean."""
    for grupo in (regla.get('incluidos_grupo') if regla else None) or []:
        bolsa = num * Decimal(grupo['cantidad'])
        for codigo in grupo['partidas']:
            if bolsa <= 0:
                break
            info = partidas.get(codigo)
            if info is None:
                continue
            entrada = agregadas[codigo]
            incl = min(info['cantidad'], bolsa)
            bolsa -= incl
            entrada['incl'] += incl
            entrada['cobra'] = max(entrada['cobra'] - incl, Decimal('0'))


def _derivaciones(agregadas, regla, partidas, num, buscar_partida):
    """Lo que se cobra en otra partida.

    El excedente de acarreo se paga como traslado manual: nace de una partida
    que nadie liquidó, así que hay que traerla del catálogo."""
    deriv = regla.get('derivar') if regla else None
    if not deriv or deriv['origen'] not in partidas:
        return
    metrado = partidas[deriv['origen']]['cantidad']
    cantidad = metrado / deriv['divisor']
    umbral = num * Decimal(deriv['umbral']) if num > 0 else Decimal('0')
    mo = buscar_partida(deriv['destino'])
    if mo is None:
        return
    entrada = agregadas.setdefault(
        deriv['destino'], {'mo': mo, 'real': Decimal('0'),
                           'incl': Decimal('0'), 'cobra': Decimal('0')})
    entrada['real'] += cantidad
    entrada['incl'] += umbral
    entrada['cobra'] += max(cantidad - umbral, Decimal('0'))


def partidas_cobradas(sst):
    """Las partidas de una SST tal como se cobran.

    Ya descontado lo que el paquete de cambio de poste incluye, y con las que
    nacen de una derivación aunque nadie las haya liquidado. Es exactamente la
    columna de cobrado del consolidado: el Excel tiene que decir lo mismo."""
    from django.db.models import Q

    from .cuaderno_obra import Item
    from .models import (ActividadTipoTrabajo, LiquidacionSuministro,
                         ManoDeObra, Suministro)

    codigo = sst.codigo or sst.sst
    suministros = list(Suministro.objects.filter(sst_suministros__sst=sst))
    filtro = Q(suministro__in=suministros)
    if codigo:
        filtro |= Q(sst_externo=codigo)
    liquidaciones = (LiquidacionSuministro.objects.filter(filtro)
                     .select_related('tipo_trabajo')
                     .prefetch_related('partidas__mano_de_obra'))

    # La actividad se detecta por el tipo de trabajo liquidado, igual que en el
    # consolidado: es más confiable que lo que diga el registro de la SST.
    actividad_de = {}
    for att in ActividadTipoTrabajo.objects.select_related('actividad'):
        actividad_de.setdefault(att.tipo_trabajo_id, att.actividad.nombre)

    # Agrupado por poste: lo incluido depende de los cambios de ESE poste.
    postes = {}
    for liq in liquidaciones:
        clave = liq.suministro_id or liq.suministro_externo or ''
        poste = postes.setdefault(clave, {'act': '', 'partidas': {}})
        nombre = actividad_de.get(liq.tipo_trabajo_id, '')
        if nombre and (norm_actividad(nombre) in INCLUSIONES_CONSOLIDADO
                       or not poste['act']):
            poste['act'] = nombre
        for lp in liq.partidas.all():
            mo = lp.mano_de_obra
            entrada = poste['partidas'].setdefault(
                mo.partida, {'mo': mo, 'cantidad': Decimal('0')})
            entrada['cantidad'] += lp.cantidad

    cache = {}

    def buscar_partida(codigo_partida):
        if codigo_partida not in cache:
            cache[codigo_partida] = ManoDeObra.objects.filter(
                partida=codigo_partida).first()
        return cache[codigo_partida]

    agregadas, _ = consolidar_partidas(
        [(norm_actividad(p['act']), p['partidas']) for p in postes.values()],
        INCLUSIONES_CONSOLIDADO, buscar_partida)

    return [Item(codigo_partida, e['mo'].descripcion, e['cobra'], e['mo'].precio)
            for codigo_partida, e in sorted(agregadas.items())]
