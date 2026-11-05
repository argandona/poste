"""Análisis del informe mensual de camiones, en hojas del Excel con su gráfico.

Pedido del usuario el 2026-11-05: que el Excel muestre qué camión rinde más y
cuál menos, quién maneja más económico, en qué grifo sale más barato, las
cargas raras, cuánto cuesta llegar a cada SST y distrito, cuánto se usa cada
camión y cómo viene el rendimiento en el año.

Todo sale de lo que el chofer ya registra (km, cargas, grifo, SST, distrito y
horas de salida y cierre): no pide datos nuevos.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from django.utils import timezone

from .camiones import (
    MESES, MESES_PROMEDIO, TRAMOS_PROMEDIO, UMBRAL_ALERTA, _fin_de_mes,
    _mes_anterior, km_de_jornada, resumen_periodo, tramos_detalle,
)
from .models import Camion, JornadaCamion

# Una carga cuyo precio por unidad se aparta más que esto de la mediana del mes
# (mismo combustible) se marca para revisar.
DESVIO_PRECIO = Decimal('0.15')
# Hacen falta al menos estas cargas de un combustible para tener mediana.
CARGAS_PARA_MEDIANA = 3
# Una carga a menos de estos km de la anterior del mismo camión.
KM_CARGA_SEGUIDA = 30
# Km sin registrar entre un cierre y la salida siguiente que vale la pena mirar.
KM_HUECO = 20
# Meses de la hoja Tendencia (el del informe y los anteriores).
MESES_TENDENCIA = 12
# Color de las barras.
COLOR = '2F5597'


def _fecha(dt):
    return timezone.localtime(dt).date()


def _horas(j):
    if j['hora_cierre'] and j['hora_salida']:
        return (j['hora_cierre'] - j['hora_salida']).total_seconds() / 3600
    return None


def _r(x, d=2):
    return round(x, d) if x is not None else None


def _grifo(texto):
    """Los grifos se escriben a mano: se juntan sin mayúsculas ni espacios de más."""
    return ' '.join((texto or '').split()).upper() or '(sin grifo)'


# ── Cálculos ─────────────────────────────────────────────────────────────────

def ranking(informe):
    """Camiones del mejor al peor rendimiento, comparando solo los del mismo
    combustible (km/gal no se compara con km/m³). El S/ por km sí se compara
    entre todos."""
    camiones = informe['camiones']
    con_costo = sorted((c for c in camiones if c['costo_km'] is not None),
                       key=lambda c: c['costo_km'])
    puesto_costo = {c['camion']: i for i, c in enumerate(con_costo, 1)}
    grupos = defaultdict(list)
    for c in camiones:
        grupos[c['combustible'] or ''].append(c)
    filas = []
    for comb in sorted(grupos):
        medidos = sorted((c for c in grupos[comb] if c['rendimiento'] is not None),
                         key=lambda c: -c['rendimiento'])
        sin_dato = [c for c in grupos[comb] if c['rendimiento'] is None]
        mejor = medidos[0]['rendimiento'] if medidos else None
        for i, c in enumerate(medidos + sin_dato, 1):
            medido = c['rendimiento'] is not None
            comentario = ''
            if medido and len(medidos) > 1:
                if i == 1:
                    comentario = 'Rinde más'
                elif i == len(medidos):
                    comentario = 'Rinde menos'
            if not medido:
                comentario = 'Sin cargas para medir'
            filas.append({
                'combustible': (comb or 'sin definir').upper(),
                'puesto': i if medido else None,
                'placa': c['placa'],
                'rendimiento': c['rendimiento'],
                'unidad': c['unidad'],
                'vs_mejor': (_r((c['rendimiento'] / mejor - 1) * 100, 1)
                             if medido and mejor else None),
                'metodo': c['metodo'],
                'km': c['km_total'],
                'monto': c['monto'],
                'costo_km': c['costo_km'],
                'puesto_costo': puesto_costo.get(c['camion']),
                'comentario': comentario,
            })
    return filas


def por_chofer(informe, hoy=None):
    """Lo que hizo cada chofer en el mes y su índice de rendimiento.

    El chofer no es fijo, así que el índice compara cada tramo de tanque lleno
    contra el promedio de ese mismo camión (tramos de este mes y los 3
    anteriores): 100 = rinde igual que siempre, más es mejor. Si en un tramo
    manejaron varios, a cada uno le toca según los km que hizo dentro del tramo.
    """
    hoy = hoy or timezone.localdate()
    desde, hasta = informe['desde'], informe['hasta']
    a0, m0 = _mes_anterior(desde.year, desde.month, MESES_PROMEDIO)
    ref_desde = date(a0, m0, 1)

    filas = defaultdict(lambda: {'salidas': 0, 'km': 0, 'camiones': set(), 'horas': 0.0,
                                 'cerradas': 0, 'sin_cierre': 0, 'cargas': 0,
                                 'monto': Decimal(0), 'peso': 0, 'suma': Decimal(0)})
    for c in informe['camiones']:
        for j in c['jornadas']:
            f = filas[j['chofer_nombre']]
            f['salidas'] += 1
            f['km'] += j['km_recorridos']
            f['camiones'].add(c['placa'])
            h = _horas(j)
            if h is not None:
                f['horas'] += h
                f['cerradas'] += 1
            if j['abierta'] and j['fecha'] < hoy:
                f['sin_cierre'] += 1
        for k in c['cargas']:
            f = filas[k['chofer_nombre']]
            f['cargas'] += 1
            f['monto'] += k['monto']

    for c in informe['camiones']:
        if not c['combustible']:
            continue
        tramos = tramos_detalle(c['camion'], c['combustible'])
        ref = [t['rendimiento'] for t in tramos
               if ref_desde <= _fecha(t['carga'].fecha_hora) <= hasta]
        del_mes = [t for t in tramos if desde <= _fecha(t['carga'].fecha_hora) <= hasta]
        if len(ref) < 2 or not del_mes:
            continue
        promedio = sum(ref) / len(ref)
        jornadas = list(JornadaCamion.objects
                        .filter(camion_id=c['camion'],
                                km_salida__lt=max(t['hasta_km'] for t in del_mes))
                        .select_related('chofer'))
        for j in jornadas:
            j.km_fin = j.km_cierre if j.km_cierre is not None else j.km_salida + km_de_jornada(j)
        for t in del_mes:
            indice = t['rendimiento'] / promedio * 100
            for j in jornadas:
                km = min(j.km_fin, t['hasta_km']) - max(j.km_salida, t['desde_km'])
                if km > 0:
                    f = filas[j.chofer.nombre]
                    f['peso'] += km
                    f['suma'] += indice * km

    salida = []
    for nombre, f in filas.items():
        salida.append({
            'chofer': nombre,
            'salidas': f['salidas'],
            'km': f['km'],
            'camiones': ', '.join(sorted(f['camiones'])),
            'horas': round(f['horas'], 1),
            'km_por_salida': round(f['km'] / f['salidas'], 1) if f['salidas'] else None,
            'horas_por_salida': round(f['horas'] / f['cerradas'], 1) if f['cerradas'] else None,
            'cargas': f['cargas'],
            'monto': f['monto'],
            'sin_cierre': f['sin_cierre'],
            'km_medidos': f['peso'],
            'indice': round(f['suma'] / f['peso'], 1) if f['peso'] else None,
        })
    salida.sort(key=lambda f: (f['indice'] is None, -(f['indice'] or 0), f['chofer']))
    return salida


def por_grifo(informe):
    """Precio promedio por grifo y combustible, y cuánto se pagó de más contra
    el grifo más barato del mes para ese combustible."""
    g = defaultdict(lambda: {'cargas': 0, 'cantidad': Decimal(0), 'monto': Decimal(0),
                             'precios': [], 'camiones': set(), 'unidad': ''})
    for c in informe['camiones']:
        for k in c['cargas']:
            f = g[(k['combustible'], _grifo(k['grifo']))]
            f['cargas'] += 1
            f['cantidad'] += k['cantidad']
            f['monto'] += k['monto']
            f['precios'].append(k['precio_unitario'])
            f['camiones'].add(c['placa'])
            f['unidad'] = k['unidad']
    precio = {key: f['monto'] / f['cantidad'] for key, f in g.items() if f['cantidad']}
    mas_barato = {}
    for (comb, _), p in precio.items():
        mas_barato[comb] = min(p, mas_barato.get(comb, p))
    filas = []
    for (comb, grifo), f in sorted(g.items(), key=lambda kv: (kv[0][0], precio.get(kv[0], 0))):
        p = precio.get((comb, grifo))
        minimo = mas_barato.get(comb)
        filas.append({
            'combustible': comb.upper(),
            'grifo': grifo,
            'cargas': f['cargas'],
            'camiones': ', '.join(sorted(f['camiones'])),
            'cantidad': f['cantidad'],
            'unidad': f['unidad'],
            'monto': f['monto'],
            'precio': _r(p),
            'precio_min': min(f['precios']),
            'precio_max': max(f['precios']),
            'vs_barato': _r((p / minimo - 1) * 100, 1) if p and minimo else None,
            'de_mas': _r((p - minimo) * f['cantidad']) if p and minimo else None,
        })
    return filas


def a_revisar(informe, hoy=None):
    """Lo raro del mes, para que alguien lo mire: no acusa a nadie.

    - Carga con un precio por unidad muy distinto al de las demás del mes.
    - Carga a pocos km de la anterior, o segunda carga del día.
    - Tramo de tanque lleno que rindió menos del 85 % de los 5 anteriores.
    - Km que el camión hizo sin salida registrada (entre un cierre y la salida
      siguiente).
    - Salida de un día anterior que nadie cerró.
    """
    hoy = hoy or timezone.localdate()
    desde, hasta = informe['desde'], informe['hasta']
    precios = defaultdict(list)
    for c in informe['camiones']:
        for k in c['cargas']:
            precios[k['combustible']].append(k['precio_unitario'])
    medianas = {comb: median(v) for comb, v in precios.items()
                if len(v) >= CARGAS_PARA_MEDIANA}

    filas = []
    for c in informe['camiones']:
        previa, por_dia = None, defaultdict(int)
        for k in c['cargas']:
            dia = _fecha(k['fecha_hora'])
            por_dia[dia] += 1
            motivos = []
            m = medianas.get(k['combustible'])
            if m and abs(k['precio_unitario'] - m) > m * DESVIO_PRECIO:
                motivos.append(f"Pagó S/ {k['precio_unitario']:.2f} por {k['unidad']}; "
                               f"la mediana del mes es S/ {m:.2f}")
            if previa is not None and k['km'] - previa['km'] < KM_CARGA_SEGUIDA:
                motivos.append(f"Solo {k['km'] - previa['km']} km desde la carga anterior")
            if por_dia[dia] > 1:
                motivos.append(f'Carga número {por_dia[dia]} del día')
            previa = k
            if motivos:
                filas.append([c['placa'], dia, timezone.localtime(k['fecha_hora']).strftime('%H:%M'),
                              k['chofer_nombre'], k['km'], 'Carga', '; '.join(motivos),
                              _grifo(k['grifo']) if k['grifo'] else ''])

        if c['combustible']:
            tramos = tramos_detalle(c['camion'], c['combustible'])
            for i, t in enumerate(tramos):
                dia = _fecha(t['carga'].fecha_hora)
                if not desde <= dia <= hasta:
                    continue
                previos = [x['rendimiento'] for x in tramos[max(0, i - TRAMOS_PROMEDIO):i]]
                if len(previos) < 2:
                    continue
                promedio = sum(previos) / len(previos)
                if t['rendimiento'] >= promedio * UMBRAL_ALERTA:
                    continue
                caida = (1 - t['rendimiento'] / promedio) * 100
                filas.append([c['placa'], dia,
                              timezone.localtime(t['carga'].fecha_hora).strftime('%H:%M'),
                              t['carga'].chofer.nombre, t['hasta_km'], 'Rendimiento bajo',
                              f"{t['rendimiento']:.1f} km/{c['unidad']} entre el km "
                              f"{t['desde_km']} y el {t['hasta_km']}; su promedio es "
                              f"{promedio:.1f} ({caida:.0f} % menos)",
                              _grifo(t['carga'].grifo) if t['carga'].grifo else ''])

        for j in c['jornadas']:
            hora = timezone.localtime(j['hora_salida']).strftime('%H:%M') if j['hora_salida'] else ''
            if j['km_sin_registrar'] > KM_HUECO:
                filas.append([c['placa'], j['fecha'], hora, j['chofer_nombre'], j['km_salida'],
                              'Km sin registrar',
                              f"El camión hizo {j['km_sin_registrar']} km entre el cierre "
                              f"anterior y esta salida sin que nadie los registre", ''])
            if j['abierta'] and j['fecha'] < hoy:
                filas.append([c['placa'], j['fecha'], hora, j['chofer_nombre'], j['km_salida'],
                              'Salida sin cierre', 'Nadie marcó el km de cierre', ''])
    filas.sort(key=lambda f: (f[1], f[2], f[0]))
    return filas


def costos(informe):
    """Lo que costó en combustible llegar a cada SST y a cada distrito.

    S/ estimado = km de la salida × S/ por km del camión en el mes. Con varias
    SST en una salida, los km y los soles se reparten en partes iguales. Sin
    SST, va como trabajo interno con lo que escribió el chofer."""
    por_sst, por_distrito = {}, {}
    for c in informe['camiones']:
        # Sin redondear, para que la suma de las SST dé los S/ del camión.
        costo_km = c['monto'] / c['km_total'] if c['km_total'] and c['monto'] else None
        for j in c['jornadas']:
            partes = j['ssts'] or [None]
            km = Decimal(j['km_recorridos']) / len(partes)
            soles = km * costo_km if costo_km is not None else None
            for s in partes:
                if s:
                    clave, actividad = s['sst'], s['actividad']
                    distrito = s['distrito'] or j['distrito_interno']
                else:
                    clave = 'Trabajo interno: ' + (' '.join(j['trabajo_interno'].split()) or 'sin detalle')
                    actividad, distrito = '', j['distrito_interno']
                distrito = ' '.join((distrito or '').split()) or '(sin distrito)'
                f = por_sst.setdefault(clave, {
                    'sst': clave, 'interno': s is None, 'actividad': actividad,
                    'distritos': set(), 'camiones': set(), 'salidas': set(),
                    'km': Decimal(0), 'soles': Decimal(0), 'sin_costo': 0})
                d = por_distrito.setdefault(distrito.upper(), {
                    'distrito': distrito.upper(), 'ssts': set(), 'salidas': set(),
                    'km': Decimal(0), 'soles': Decimal(0), 'sin_costo': 0})
                for x in (f, d):
                    x['salidas'].add(j['id_jornada'])
                    x['km'] += km
                    if soles is None:
                        x['sin_costo'] += 1
                    else:
                        x['soles'] += soles
                f['distritos'].add(distrito)
                f['camiones'].add(c['placa'])
                if s:
                    d['ssts'].add(clave)

    def fin(lista):
        return sorted(lista, key=lambda x: (-x['soles'], -x['km']))

    ssts = [{**f, 'distritos': ', '.join(sorted(f['distritos'])),
             'camiones': ', '.join(sorted(f['camiones'])), 'salidas': len(f['salidas']),
             'km': round(f['km'], 1), 'soles': round(f['soles'], 2)}
            for f in por_sst.values()]
    distritos = [{**d, 'ssts': len(d['ssts']), 'salidas': len(d['salidas']),
                  'km': round(d['km'], 1), 'soles': round(d['soles'], 2),
                  'soles_por_salida': (round(d['soles'] / len(d['salidas']), 2)
                                       if d['salidas'] else None)}
                 for d in por_distrito.values()]
    return fin(ssts), fin(distritos)


def uso_flota(informe, hoy=None):
    """Cuánto se usó cada camión: días hábiles (lunes a viernes, como el aviso
    de las 9:00) con y sin salida, fines de semana y horas en ruta."""
    hoy = hoy or timezone.localdate()
    desde, hasta = informe['desde'], informe['hasta']
    fin = min(hasta, hoy)
    habiles = [desde + timedelta(days=i) for i in range((fin - desde).days + 1)]
    habiles = [d for d in habiles if d.weekday() < 5]
    filas = []
    for c in informe['camiones']:
        dias = {j['fecha'] for j in c['jornadas']}
        con = sum(1 for d in habiles if d in dias)
        horas = [h for h in (_horas(j) for j in c['jornadas']) if h is not None]
        filas.append({
            'placa': c['placa'],
            'habiles': len(habiles),
            'habiles_con': con,
            'habiles_sin': len(habiles) - con,
            'uso': round(con / len(habiles) * 100, 1) if habiles else None,
            'fin_de_semana': sum(1 for d in dias if d.weekday() >= 5),
            'salidas': c['salidas'],
            'horas': round(sum(horas), 1),
            'horas_por_salida': round(sum(horas) / len(horas), 1) if horas else None,
            'km_por_dia': round(c['km_total'] / len(dias), 1) if dias else None,
        })
    filas.sort(key=lambda f: (f['uso'] is None, -(f['uso'] or 0), f['placa']))
    return filas


def tendencia(informe, hoy=None):
    """Rendimiento, S/ y km de cada camión en los últimos 12 meses."""
    anio, mes = informe['anio'], informe['mes']
    meses = [_mes_anterior(anio, mes, atras) for atras in range(MESES_TENDENCIA - 1, -1, -1)]
    camiones = {c.pk: c for c in Camion.objects.filter(
        pk__in=[c['camion'] for c in informe['camiones']])}
    filas = []
    for c in informe['camiones']:
        camion = camiones[c['camion']]
        rend, soles, km = [], [], []
        for a, m in meses:
            if (a, m) == (anio, mes):
                r = c
            else:
                r = resumen_periodo(camion, date(a, m, 1), _fin_de_mes(a, m), hoy=hoy)
            vacio = not r['salidas'] and not r['cargas']
            rend.append(None if vacio else r['rendimiento'])
            soles.append(None if vacio else r['monto'])
            km.append(None if vacio else r['km_total'])
        filas.append({'placa': c['placa'], 'unidad': c['unidad'],
                      'rendimiento': rend, 'soles': soles, 'km': km})
    etiquetas = [f'{MESES[m - 1][:3]} {a % 100:02d}' for a, m in meses]
    return etiquetas, filas


# ── Excel ────────────────────────────────────────────────────────────────────

def _grafico_barras(ws, titulo, col_cat, col_val, f0, f1, ancla, eje='', horizontal=True):
    from openpyxl.chart import BarChart, Reference
    from openpyxl.chart.label import DataLabelList
    if f1 < f0:
        return
    ch = BarChart()
    ch.type = 'bar' if horizontal else 'col'
    ch.title = titulo
    ch.legend = None
    ch.add_data(Reference(ws, min_col=col_val, min_row=f0, max_row=f1), titles_from_data=False)
    ch.set_categories(Reference(ws, min_col=col_cat, min_row=f0, max_row=f1))
    ch.series[0].graphicalProperties.solidFill = COLOR
    ch.series[0].graphicalProperties.line.solidFill = COLOR
    ch.dataLabels = DataLabelList()
    ch.dataLabels.showVal = True
    for campo in ('showSerName', 'showCatName', 'showLegendKey', 'showPercent'):
        setattr(ch.dataLabels, campo, False)
    ch.x_axis.delete = False
    ch.y_axis.delete = False
    ch.y_axis.title = eje
    ch.y_axis.majorGridlines = None
    ch.y_axis.scaling.min = 0
    if horizontal:
        # El primero de la tabla arriba, y el eje de valores abajo.
        ch.x_axis.scaling.orientation = 'maxMin'
        ch.y_axis.crosses = 'max'
    ch.width = 18
    ch.height = max(7.5, 1.5 + 0.7 * (f1 - f0 + 1)) if horizontal else 9
    ws.add_chart(ch, ancla)
    return ch.height


def _nota(ws, texto):
    from openpyxl.styles import Font
    ws['A2'] = texto
    ws['A2'].font = Font(italic=True, color='555555')


def hojas_de_analisis(wb, informe, hoja, n, hoy=None):
    """Agrega al libro las hojas de análisis, después del Resumen. `hoja` y `n`
    son las ayudas de informe_excel (título, encabezados y anchos; Decimal a
    número)."""
    from openpyxl.chart import LineChart, Reference
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    verde = PatternFill('solid', fgColor='C6EFCE')
    rojo = PatternFill('solid', fgColor='F8CBAD')

    def pintar(ws, fila, relleno):
        for celda in ws[fila]:
            celda.fill = relleno

    # Ranking
    ws = wb.create_sheet('Ranking')
    filas = ranking(informe)
    hoja(ws, ['Combustible', 'Puesto', 'Placa', 'Rendimiento', 'Unidad', 'vs. el mejor %',
              'Método', 'Km del mes', 'S/ combustible', 'S/ por km', 'Puesto S/ por km',
              'Comentario'],
         [[f['combustible'], f['puesto'], f['placa'], n(f['rendimiento']), f'km/{f["unidad"]}',
           n(f['vs_mejor']), f['metodo'], f['km'], n(f['monto']), n(f['costo_km']),
           f['puesto_costo'], f['comentario']] for f in filas],
         [12, 8, 11, 12, 9, 13, 12, 11, 14, 10, 15, 22])
    _nota(ws, 'Rendimiento: solo se compara entre camiones del mismo combustible. '
              'S/ por km: se compara entre todos (1 = el más barato).')
    for i, f in enumerate(filas, 4):
        if f['comentario'] == 'Rinde más':
            pintar(ws, i, verde)
        elif f['comentario'] == 'Rinde menos':
            pintar(ws, i, rojo)
    fila_graf = 3
    inicio = 4
    for comb in dict.fromkeys(f['combustible'] for f in filas):
        grupo = [i for i, f in enumerate(filas, 4)
                 if f['combustible'] == comb and f['rendimiento'] is not None]
        if grupo:
            unidad = filas[grupo[0] - 4]['unidad']
            alto = _grafico_barras(ws, f'Rendimiento {comb} (km/{unidad})', 3, 4,
                                   grupo[0], grupo[-1], f'N{fila_graf}')
            fila_graf += int(alto * 2) + 2
    con_costo = len(filas)
    if any(f['costo_km'] is not None for f in filas):
        _grafico_barras(ws, 'S/ por km (menos es mejor)', 3, 10, inicio, inicio + con_costo - 1,
                        f'N{fila_graf}')

    # Choferes
    ws = wb.create_sheet('Choferes')
    filas = por_chofer(informe, hoy=hoy)
    hoja(ws, ['Chofer', 'Salidas', 'Km manejados', 'Camiones', 'Horas en ruta',
              'Km por salida', 'Horas por salida', 'Cargas', 'S/ cargado',
              'Salidas sin cierre', 'Km en tramos medidos', 'Índice de rendimiento'],
         [[f['chofer'], f['salidas'], f['km'], f['camiones'], f['horas'],
           n(f['km_por_salida']), f['horas_por_salida'], f['cargas'], n(f['monto']),
           f['sin_cierre'], f['km_medidos'], n(f['indice'])] for f in filas],
         [24, 8, 13, 22, 13, 12, 14, 8, 11, 16, 18, 20])
    _nota(ws, 'Índice: 100 = el camión rindió igual que su promedio (este mes y los 3 '
              'anteriores); más es mejor. En un tramo de tanque lleno con varios choferes, '
              'a cada uno le toca según sus km.')
    for i, f in enumerate(filas, 4):
        if f['indice'] is not None and f['indice'] < UMBRAL_ALERTA * 100:
            pintar(ws, i, rojo)
    medidos = [i for i, f in enumerate(filas, 4) if f['indice'] is not None]
    if medidos:
        _grafico_barras(ws, 'Índice de rendimiento por chofer (100 = normal)', 1, 12,
                        medidos[0], medidos[-1], 'N3')

    # Grifos
    ws = wb.create_sheet('Grifos')
    filas = por_grifo(informe)
    hoja(ws, ['Combustible', 'Grifo', 'Cargas', 'Camiones', 'Cantidad', 'Unidad', 'S/',
              'S/ por unidad (promedio)', 'Más barato', 'Más caro', 'vs. el más barato %',
              'S/ pagado de más'],
         [[f['combustible'], f['grifo'], f['cargas'], f['camiones'], n(f['cantidad']),
           f['unidad'], n(f['monto']), n(f['precio']), n(f['precio_min']),
           n(f['precio_max']), n(f['vs_barato']), n(f['de_mas'])] for f in filas],
         [12, 26, 8, 22, 10, 8, 11, 22, 11, 10, 18, 16])
    _nota(ws, 'S/ pagado de más = lo cargado en ese grifo × la diferencia contra el grifo '
              'más barato del mes para el mismo combustible.')
    fila_graf = 3
    for comb in dict.fromkeys(f['combustible'] for f in filas):
        grupo = [i for i, f in enumerate(filas, 4) if f['combustible'] == comb]
        unidad = filas[grupo[0] - 4]['unidad']
        alto = _grafico_barras(ws, f'S/ por {unidad} de {comb} por grifo', 2, 8,
                               grupo[0], grupo[-1], f'N{fila_graf}')
        fila_graf += int(alto * 2) + 2

    # Revisar
    ws = wb.create_sheet('Revisar')
    filas = a_revisar(informe, hoy=hoy)
    hoja(ws, ['Placa', 'Fecha', 'Hora', 'Chofer', 'Km', 'Qué', 'Detalle', 'Grifo'],
         filas, [11, 11, 7, 22, 10, 18, 80, 22])
    _nota(ws, 'Cosas raras del mes para mirar con la foto del tablero: no siempre son un '
              'error.' if filas else 'Nada raro este mes.')
    for i in range(4, 4 + len(filas)):
        ws.cell(row=i, column=2).number_format = 'DD/MM/YYYY'

    # Costo por SST y por distrito
    ssts, distritos = costos(informe)
    ws = wb.create_sheet('Costo por SST')
    hoja(ws, ['SST o trabajo', 'Actividad', 'Distrito', 'Camiones', 'Salidas', 'Km',
              'S/ estimado'],
         [[f['sst'], f['actividad'], f['distritos'], f['camiones'], f['salidas'],
           n(f['km']), n(f['soles'])] for f in ssts],
         [40, 34, 20, 22, 8, 10, 12])
    _nota(ws, 'S/ estimado = km de la salida × S/ por km del camión en el mes. Con varias '
              'SST en una salida se reparte en partes iguales.')
    for i, f in enumerate(ssts, 4):
        if f['interno']:
            ws.cell(row=i, column=1).font = Font(italic=True)
    top = min(len(ssts), 15)
    if top:
        _grafico_barras(ws, f'Las {top} que más costaron (S/)', 1, 7, 4, 3 + top, 'I3')

    ws = wb.create_sheet('Costo por distrito')
    hoja(ws, ['Distrito', 'SST', 'Salidas', 'Km', 'S/ estimado', 'S/ por salida'],
         [[d['distrito'], d['ssts'], d['salidas'], n(d['km']), n(d['soles']),
           n(d['soles_por_salida'])] for d in distritos],
         [24, 8, 8, 10, 12, 13])
    _nota(ws, 'Mismo cálculo que Costo por SST, sumado por distrito.')
    if distritos:
        _grafico_barras(ws, 'S/ estimado por distrito', 1, 5, 4, 3 + min(len(distritos), 20), 'H3')

    # Uso de la flota
    ws = wb.create_sheet('Uso de flota')
    filas = uso_flota(informe, hoy=hoy)
    hoja(ws, ['Placa', 'Días hábiles', 'Con salida', 'Sin salida', '% de uso',
              'Días de fin de semana', 'Salidas', 'Horas en ruta', 'Horas por salida',
              'Km por día con salida'],
         [[f['placa'], f['habiles'], f['habiles_con'], f['habiles_sin'], n(f['uso']),
           f['fin_de_semana'], f['salidas'], f['horas'], f['horas_por_salida'],
           n(f['km_por_dia'])] for f in filas],
         [11, 12, 11, 11, 10, 20, 8, 13, 15, 20])
    _nota(ws, 'Días hábiles: lunes a viernes del mes, hasta hoy si es el mes en curso.')
    if filas and any(f['uso'] is not None for f in filas):
        _grafico_barras(ws, '% de días hábiles con salida', 1, 5, 4, 3 + len(filas), 'L3')

    # Tendencia
    ws = wb.create_sheet('Tendencia')
    etiquetas, filas = tendencia(informe, hoy=hoy)
    ws['A1'] = f"Camiones - últimos {MESES_TENDENCIA} meses hasta {MESES[informe['mes'] - 1]} {informe['anio']}"
    ws['A1'].font = Font(bold=True, size=13)
    _nota(ws, 'Un mes vacío es un mes sin salidas ni cargas de ese camión.')
    gris = PatternFill('solid', fgColor='DDDDDD')
    fila = 4
    graficos = []
    for clave, nombre in (('rendimiento', 'Rendimiento (km por unidad de su combustible)'),
                          ('soles', 'S/ de combustible'),
                          ('km', 'Km recorridos')):
        ws.cell(row=fila, column=1, value=nombre).font = Font(bold=True)
        fila += 1
        for col, texto in enumerate(['Placa'] + etiquetas, 1):
            celda = ws.cell(row=fila, column=col, value=texto)
            celda.font = Font(bold=True)
            celda.fill = gris
        cabecera = fila
        for f in filas:
            fila += 1
            ws.cell(row=fila, column=1, value=f['placa'])
            for col, v in enumerate(f[clave], 2):
                ws.cell(row=fila, column=col, value=n(v))
        if filas:
            graficos.append((nombre, cabecera, fila))
        fila += 2
    ws.column_dimensions['A'].width = 12
    for col in range(2, len(etiquetas) + 2):
        ws.column_dimensions[get_column_letter(col)].width = 9
    ancla = 3
    for nombre, cabecera, ultima in graficos:
        ch = LineChart()
        ch.title = nombre
        ch.legend.position = 'b'
        ch.x_axis.delete = False
        ch.y_axis.delete = False
        ch.add_data(Reference(ws, min_col=1, max_col=len(etiquetas) + 1,
                              min_row=cabecera + 1, max_row=ultima),
                    from_rows=True, titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=2, max_col=len(etiquetas) + 1,
                                    min_row=cabecera, max_row=cabecera))
        for serie in ch.series:
            # Con punto: un mes suelto también se ve.
            serie.marker.symbol = 'circle'
            serie.marker.size = 7
            serie.smooth = False
        ch.width, ch.height = 22, 9
        ws.add_chart(ch, f'{get_column_letter(len(etiquetas) + 3)}{ancla}')
        ancla += 20
