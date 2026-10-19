"""El formato de Conducción de Encossa (F03-IA-QHSE-001, versión 01).

Lo llena el chofer cada día antes de manejar, después de su IPC: los 8
controles con su guía y la respuesta Sí o No. Si alguno no se cumple, el papel
dice detener la actividad y avisar al capataz y al supervisor; la app avisa y
deja seguir (decisión del usuario, 2026-10-18).

La app arma la pantalla con esto (GET /api/conducciones/formato/) y el PDF lo
pinta con lo mismo. Lo respondido se guarda en `Conduccion.controles` como
{clave: "si" | "no"}.
"""
from .errores import ErrorNegocio

CODIGO = 'F03-IA-QHSE-001'
VERSION = '01'

CONTROLES = [
    {'clave': 'plan', 'control': 'Se cuenta con plan para gestionar peligros del viaje.',
     'guia': ['Conductor autorizado según Fotocheck y consciente de: IPC completo, '
              'destino definido, tráfico, condiciones de carretera.']},
    {'clave': 'en_forma', 'control': 'Conductor en forma, descansado, y 100% alerta.',
     'guia': ['Conductor descansado, no bajo influencia de alcohol o medicamentos '
              'que afecten su concentración.']},
    {'clave': 'normas', 'control': 'El conductor está familiarizado con las normas de tránsito.',
     'guia': ['Conoce límites de velocidad y señalización local.']},
    {'clave': 'documentos', 'control': 'Vehículo habilitado y con documentos vigentes.',
     'guia': ['Según corresponda: inspección técnica, seguro contra terceros, SOAT, '
              'conversión GNV/GLP, transporte mercancías peligrosos y/o no peligrosos.']},
    {'clave': 'inspeccion', 'control': 'Se inspeccionó el vehículo y es apto para el viaje.',
     'guia': ['Checklist llenado y firmado.',
              'Caminata 360° y vehículo libre de peligros antes del movimiento.']},
    {'clave': 'objetos', 'control': 'Objetos dentro y fuera del vehículo son asegurados.',
     'guia': ['Objetos sueltos se aseguran tanto dentro como fuera del vehículo '
              '(ejemplo: llanta repuesta, baterías, escaleras, etc.).']},
    {'clave': 'cinturon', 'control': 'TODOS los ocupantes usan cinturón de seguridad.',
     'guia': ['Cinturones de seguridad en buen estado y TODOS lo usan correctamente.']},
    {'clave': 'distracciones', 'control': 'Minimizar/eliminar distracciones mientras se conduce.',
     'guia': ['No usar celular al manejar; de necesitar, detenerse en lugar seguro.',
              'El mapeo digital (Waze, GPS) se programan antes de iniciar el viaje.']},
]

AVISO = ('Si no se cumple al menos uno de los controles, detenga la actividad y '
         'comuníquelo al capataz y al supervisor. No continúe hasta que se '
         'implementen las medidas de control necesarias.')

# Renglones de firma del papel: 1 en la página 1 y 11 en la 2.
RENGLONES_PAGINA_1 = 1
RENGLONES_PAGINA_2 = 11


def formato():
    """Todo el formato, para que la app arme la pantalla."""
    return {'codigo': CODIGO, 'version': VERSION, 'controles': CONTROLES,
            'aviso': AVISO}


def limpiar_controles(datos):
    """Los 8 controles respondidos, o un error que dice cuáles faltan."""
    datos = datos if isinstance(datos, dict) else {}
    faltan = [i for i, c in enumerate(CONTROLES, 1)
              if datos.get(c['clave']) not in ('si', 'no')]
    if faltan:
        raise ErrorNegocio('Responde Sí o No en todos los controles (falta: '
                           + ', '.join(map(str, faltan)) + ').')
    return {c['clave']: datos[c['clave']] for c in CONTROLES}


def controles_en_no(controles):
    """Los controles respondidos No, con su número, en el orden del papel."""
    controles = controles or {}
    return [(i, c) for i, c in enumerate(CONTROLES, 1)
            if controles.get(c['clave']) == 'no']
