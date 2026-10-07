"""El formato del IPC (Instrucción Previa en Campo) de Encossa.

F01-IA-SMAC-003, versión 01. Aquí están las preguntas y opciones tal como las
trae el papel, con una clave estable para cada una. La app arma la pantalla
con esto (GET /api/ipcs/formato/) y el PDF lo pinta con lo mismo, así que una
versión 02 del formato es otra definición, sin tocar los IPC ya llenados: cada
uno guarda con qué versión se hizo.

Lo marcado se guarda en `IPC.datos` con estas claves:

    epp:               [clave, ...]           (5) EPP a utilizar
    epp_otros:         str
    peligros_criticos: [clave, ...]           (6)
    peligros_otros:    str
    etapas:            [str, ...]             (7) hasta 10
    brigadas:          [clave, ...]           (9)
    equipamiento:      [clave, ...]           (10)
    equipamiento_otros: str
    factores:          {clave: "si"|"no"}     factores de comportamiento
    energias:          {clave_pregunta: {"peligros": [clave, ...],
                                         "otros": str, "tareas": str,
                                         "medidas": str}}
    emergencia:        copia de los contactos al momento de crearlo
"""

CODIGO = 'F01-IA-SMAC-003'
VERSION = '01'

# (5) EPP a utilizar, en el orden del papel. `icono` es el archivo en
# core/data/ipc/ (y en assets/ipc/ de la app).
EPP = [
    {'clave': 'ropa', 'texto': 'Ropa de trabajo', 'icono': 'epp_ropa.png'},
    {'clave': 'careta', 'texto': 'Careta facial', 'icono': 'epp_careta.png'},
    {'clave': 'guantes', 'texto': 'Guantes', 'icono': 'epp_guantes.png'},
    {'clave': 'calzado', 'texto': 'Calzado de seguridad', 'icono': 'epp_calzado.png'},
    {'clave': 'auditiva', 'texto': 'Protección auditiva', 'icono': 'epp_auditiva.png'},
    {'clave': 'lentes', 'texto': 'Lentes de seguridad', 'icono': 'epp_lentes.png'},
    {'clave': 'casco', 'texto': 'Casco', 'icono': 'epp_casco.png'},
    {'clave': 'arnes', 'texto': 'Arnés de seguridad', 'icono': 'epp_arnes.png'},
    {'clave': 'respirador', 'texto': 'Respirador', 'icono': 'epp_respirador.png'},
]

# (6) Peligros críticos.
PELIGROS_CRITICOS = [
    {'clave': 'prohibido', 'texto': 'Prohibido el ingreso', 'icono': 'pc_prohibido.png'},
    {'clave': 'inflamables', 'texto': 'Sustancias o materias inflamables', 'icono': 'pc_inflamables.png'},
    {'clave': 'manos', 'texto': 'Atención con sus manos', 'icono': 'pc_manos.png'},
    {'clave': 'gruas', 'texto': 'Grúas trabajando', 'icono': 'pc_gruas.png'},
    {'clave': 'transito', 'texto': 'Tránsito de vehículos', 'icono': 'pc_transito.png'},
    {'clave': 'explosiva', 'texto': 'Atmósfera explosiva', 'icono': 'pc_explosiva.png'},
    {'clave': 'electrico', 'texto': 'Riesgo eléctrico', 'icono': 'pc_electrico.png'},
    {'clave': 'derrumbe', 'texto': 'Riesgo de derrumbe', 'icono': 'pc_derrumbe.png'},
    {'clave': 'caidas', 'texto': 'Peligro de caídas', 'icono': 'pc_caidas.png'},
]

# (9) Brigadas de respuesta inicial disponibles.
BRIGADAS = [
    {'clave': 'primeros_auxilios', 'texto': 'Primeros Auxilios'},
    {'clave': 'evacuacion', 'texto': 'Evacuación y Rescate'},
    {'clave': 'contencion', 'texto': 'Contención de sustancias peligrosas'},
    {'clave': 'incendio', 'texto': 'Contra Incendio'},
]

# (10) Equipamiento disponible de las brigadas.
EQUIPAMIENTO = [
    {'clave': 'extintor', 'texto': 'Extintor'},
    {'clave': 'botiquin', 'texto': 'Botiquín'},
    {'clave': 'kit_derrames', 'texto': 'Kit de contención contra derrames'},
    {'clave': 'lavaojos', 'texto': 'Estación de lavaojos'},
]

# Factores y aspectos que afectan el comportamiento. `riesgo` es la respuesta
# que obliga a tomar medidas (la nota ** del formato): en unas es el "no" y en
# otras el "sí".
FACTORES = [
    {'grupo': 'Personales', 'clave': 'capaz', 'riesgo': 'no',
     'texto': '¿El empleado es físicamente capaz de realizar la tarea (fuerza, destreza, coordinación)?'},
    {'grupo': 'Personales', 'clave': 'conocimiento', 'riesgo': 'no',
     'texto': '¿El empleado tiene el conocimiento, la experiencia y las habilidades necesarias para realizar la tarea de manera segura?'},
    {'grupo': 'Personales', 'clave': 'estresado', 'riesgo': 'si',
     'texto': '¿El empleado está estresado o preocupado por asuntos personales o laborales que podrían distraer su atención de la tarea?'},
    {'grupo': 'Personales', 'clave': 'cansancio', 'riesgo': 'si',
     'texto': '¿El cansancio, la fatiga u otros factores afectarán la capacidad del empleado para realizar el trabajo?'},
    {'grupo': 'Laborales', 'clave': 'herramientas', 'riesgo': 'no',
     'texto': '¿Se tiene las herramientas y equipos adecuados para realizar la tarea?'},
    {'grupo': 'Laborales', 'clave': 'instrucciones', 'riesgo': 'no',
     'texto': '¿Se cuenta con instrucciones, etiquetas, letreros y procedimientos claros y fáciles de entender?'},
    {'grupo': 'Laborales', 'clave': 'horario', 'riesgo': 'no',
     'texto': '¿El horario y volumen de trabajo son apropiados para el tiempo asignado?'},
    {'grupo': 'Laborales', 'clave': 'concentracion', 'riesgo': 'si',
     'texto': '¿La tarea requiere altos niveles de concentración o multitareas?'},
    {'grupo': 'Organizacionales', 'clave': 'empoderado', 'riesgo': 'no',
     'texto': '¿Se siente el empleado empoderado para detener el trabajo?'},
    {'grupo': 'Organizacionales', 'clave': 'roles', 'riesgo': 'no',
     'texto': '¿Se tiene claridad sobre los roles y responsabilidades del empleado?'},
    {'grupo': 'Organizacionales', 'clave': 'comunicacion', 'riesgo': 'no',
     'texto': '¿Existe una comunicación abierta entre los compañeros de trabajo y el responsable en el área de trabajo?'},
    {'grupo': 'Organizacionales', 'clave': 'tiempo', 'riesgo': 'no',
     'texto': '¿Se anima al empleado a tomarse el tiempo para estar seguro en lugar de asumir riesgos para hacer el trabajo rápidamente?'},
]


def _opciones(*textos):
    """Cada opción con una clave estable: el texto en minúsculas, sin tildes
    ni signos ("Conductor aéreo" → "conductor_aereo")."""
    import re
    from .cuaderno_obra import normalizar
    return [{'clave': re.sub(r'[^a-z0-9]+', '_', normalizar(t)).strip('_')[:40],
             'texto': t} for t in textos]


# Sección B: (11) energía, (12) peligros potenciales por pregunta.
ENERGIAS = [
    {'energia': 'Gravedad', 'icono': 'en_gravedad.png', 'preguntas': [
        {'clave': 'caer', 'texto': '¿Puede algo caer, COLAPSAR O PRODUCIR APLASTAMIENTO?',
         'opciones': _opciones(
             'Por maquinarias/equipos.', 'Por material pesado/ gran volumen.',
             'Objeto suspendido', 'Trabajo a desnivel', 'Superficie irregular',
             'Equipos de izaje', 'Excavación inestable',
             'Paredes y estructuras inestables o en mal estado.',
             'Remoción de Suelo/Ornato/Desmonte')},
        {'clave': 'estabilidad', 'texto': '¿Puede algo perder su ESTABILIDAD DURANTE LA OPERACIÓN?',
         'opciones': _opciones(
             'Trabajar en un terreno irregular.', 'Izajes de carga.',
             'Traslado de material con montacargas y tracto.',
             'Traslado de personal.')},
        {'clave': 'resbalones', 'texto': '¿Puede algo ser capaz de producir RESBALONES, TROPIEZOS o CAÍDAS?',
         'opciones': _opciones(
             'Superficie Irregular.', 'Trabajo a distinto nivel.',
             'Trabajo a nivel de piso.')},
    ]},
    {'energia': 'Movimiento', 'icono': 'en_movimiento.png', 'preguntas': [
        {'clave': 'ergonomicos', 'texto': '¿Existen peligros ERGONÓMICOS?',
         'opciones': _opciones(
             'Manipulación manual.', 'Movimientos repetitivos.',
             'Posturas forzadas.', 'Posturas sedentarias.')},
        {'clave': 'entorno', 'texto': '¿Existe algo en el ENTORNO DE TRABAJO MOVIENDOSE y ser capaz de producir impactos o colisiones?',
         'opciones': _opciones('Tránsito vehicular de terceros.')},
    ]},
    {'energia': 'Mecánico', 'icono': 'en_mecanico.png', 'preguntas': [
        {'clave': 'atrapamiento', 'texto': '¿Puede algo producir ATRAPAMIENTO ENTRE SUS PARTES MOVILES?',
         'opciones': _opciones(
             'Partes móviles.', 'Equipo giratorio o partes en desplazamiento',
             'Herramienta de percusión (de golpe)', 'Herramientas manuales',
             'Superficie u objeto cortante')},
        {'clave': 'cortes', 'texto': '¿Puede algo producir CORTES, PUNZADAS, FRICCIÓN Y PERFORACIONES?',
         'opciones': _opciones(
             'Objetos proyectados.', 'Partes móviles.',
             'Puntos de aprisionamiento.', 'Entre dos partes móviles.',
             'Contacto continuo con partes móviles.')},
        {'clave': 'rotacion', 'texto': '¿Puede algo producir ROTACIÓN, COMPRESIÓN, PERCUSIÓN O VIBRACIÓN?',
         'opciones': _opciones(
             'Vibroapisonador.', 'Montacarga.', 'Amoladoras.', 'Roto martillo.',
             'Maquina cortadora de pavimento.')},
    ]},
    {'energia': 'Eléctrico', 'icono': 'en_electrico.png', 'preguntas': [
        {'clave': 'electrico', 'texto': '¿Puede darse contacto con un CONDUCTOR O PARTE DE UN EQUIPO ELÉCTRICO ENERGIZADO?',
         'opciones': _opciones(
             'Conductor aéreo', 'Conductor subterráneo', 'Equipos eléctricos',
             'Herramientas eléctricas')},
    ]},
    {'energia': 'Sonido/Ruido', 'icono': 'en_ruido.png', 'preguntas': [
        {'clave': 'ruido', 'texto': '¿Puede algún equipo producir RUIDO NOCIVO?',
         'opciones': _opciones(
             'Por uso de maquinarias y equipos.',
             'Por uso de camiones y/o brazos grúa.',
             'Por Actividades de terceros.')},
    ]},
    {'energia': 'Presión', 'icono': 'en_presion.png', 'preguntas': [
        {'clave': 'presion', 'texto': '¿Puede algún contenedor DESPRESURIZARSE O FALLAR BAJO PRESIÓN?',
         'opciones': _opciones(
             'Mangueras hidráulicas.',
             'Presión de línea residual (mangueras, tuberías, entre otros).',
             'Tuberías de gas.', 'Balones de gas.', 'Compresoras.')},
    ]},
    {'energia': 'Temperatura', 'icono': 'en_temperatura.png', 'preguntas': [
        {'clave': 'temperatura', 'texto': '¿Puede el entorno, equipo o material PRESENTAR O PRODUCIR ALTA O BAJA TEMPERATURA?',
         'opciones': _opciones(
             'Temperaturas Ambientales (calor o frío)', 'Sopletes, soldadura')},
    ]},
    {'energia': 'Químico', 'icono': 'en_quimico.png', 'preguntas': [
        {'clave': 'quimico', 'texto': '¿Puede un equipo o material LIBERAR UN QUÍMICO PELIGROSO EN ESTADO LÍQUIDO, SÓLIDO O GASEOSO?',
         'opciones': _opciones(
             'Hidrocarburo.', 'Aceite dieléctrico', 'Gases de combustión.',
             "Residuos Peligrosos (envases de productos químicos, Epp's contaminados entre otros)",
             'El uso de gel B2.', 'Uso de pintura en spray.')},
        {'clave': 'polvo', 'texto': '¿Puede un EQUIPO O MATERIALES PRODUCIR O DESPRENDER POLVO PARTICULADO SUSPENDIDO?',
         'opciones': _opciones(
             'Maquina cortadora de vereda.',
             'Por excavación manual o con maquinaria.',
             'Ocasionado por traslado de unidades terceras en vía pública.',
             'Ocasionado por traslado de unidades de la operación.')},
    ]},
    {'energia': 'Radiación', 'icono': 'en_radiacion.png', 'preguntas': [
        {'clave': 'radiacion', 'texto': '¿Puede algún equipo o material emitir RADIACIONES NOCIVAS?',
         'opciones': _opciones('Exposición solar', 'Radiación UV')},
    ]},
    {'energia': 'Biológico', 'icono': 'en_biologico.png', 'preguntas': [
        {'clave': 'biologico', 'texto': '¿Puede alguien AGREDIRTE O ALGO PRODUCIRTE MORDEDURAS O PICADURAS?',
         'opciones': _opciones(
             'Canes.', 'Abejas.', 'Trabajos de terceros.',
             'Agresión de terceros, paralizaciones, huelgas, vandalismo.',
             'Zancudos')},
    ]},
]

OBSERVACION_POR_DEFECTO = ('La actividad se concluyó con normalidad y el '
                           'personal no manifiesta ninguna dolencia o malestar.')

# Renglones del cuadro (16) Ubicación: lo que pasa de aquí va en la misma fila
# separado por guion.
RENGLONES_UBICACION = 8
MAX_ETAPAS = 10


def formato():
    """Todo el formato, para que la app arme la pantalla."""
    return {
        'codigo': CODIGO, 'version': VERSION,
        'epp': EPP, 'peligros_criticos': PELIGROS_CRITICOS,
        'brigadas': BRIGADAS, 'equipamiento': EQUIPAMIENTO,
        'factores': FACTORES, 'energias': ENERGIAS,
        'observacion_por_defecto': OBSERVACION_POR_DEFECTO,
        'max_etapas': MAX_ETAPAS,
    }


def factores_en_riesgo(datos):
    """Las preguntas de comportamiento respondidas del lado del riesgo."""
    respuestas = (datos or {}).get('factores') or {}
    return [f for f in FACTORES if respuestas.get(f['clave']) == f['riesgo']]


def limpiar_datos(datos):
    """Deja solo lo que el formato conoce, para que no se cuele cualquier cosa
    en el JSON."""
    datos = datos if isinstance(datos, dict) else {}
    claves = lambda lista: {x['clave'] for x in lista}

    def lista_de(nombre, validas):
        valor = datos.get(nombre) or []
        return [v for v in valor if v in validas] if isinstance(valor, list) else []

    def texto(nombre, largo=500):
        return str(datos.get(nombre) or '').strip()[:largo]

    energias = {}
    validas = {p['clave']: {o['clave'] for o in p['opciones']}
               for e in ENERGIAS for p in e['preguntas']}
    for clave, valor in (datos.get('energias') or {}).items():
        if clave not in validas or not isinstance(valor, dict):
            continue
        energias[clave] = {
            'peligros': [v for v in (valor.get('peligros') or [])
                         if v in validas[clave]],
            'otros': str(valor.get('otros') or '').strip()[:300],
            'tareas': str(valor.get('tareas') or '').strip()[:1000],
            'medidas': str(valor.get('medidas') or '').strip()[:1000],
        }
    factores = {k: v for k, v in (datos.get('factores') or {}).items()
                if k in claves(FACTORES) and v in ('si', 'no')}
    etapas = [str(e).strip()[:300] for e in (datos.get('etapas') or [])
              if str(e).strip()][:MAX_ETAPAS]
    return {
        'epp': lista_de('epp', claves(EPP)),
        'epp_otros': texto('epp_otros'),
        'peligros_criticos': lista_de('peligros_criticos', claves(PELIGROS_CRITICOS)),
        'peligros_otros': texto('peligros_otros'),
        'etapas': etapas,
        'brigadas': lista_de('brigadas', claves(BRIGADAS)),
        'equipamiento': lista_de('equipamiento', claves(EQUIPAMIENTO)),
        'equipamiento_otros': texto('equipamiento_otros'),
        'factores': factores,
        'energias': energias,
    }
