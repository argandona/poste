"""Lo pesado del plano proyectado, en un proceso aparte.

Leer un DXF de obra con ezdxf toma unos segundos y unos 70 MB. Python no
devuelve esa memoria al sistema, así que hecho dentro del servidor cada
proceso de gunicorn quedaría así de gordo para siempre, y en Render los dos
procesos comparten 512 MB. Aquí se lee en un proceso que termina al
acabar y se lleva su memoria.

    python -m core.plano_aparte analizar|replanteo <carpeta>

La carpeta trae plano.dxf (y extra.json para el replanteo); el resultado se
deja en salida, o el motivo en error.txt.
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

from .errores import ErrorNegocio

log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent

# Por debajo del timeout de gunicorn (60 s).
TIEMPO_MAXIMO = 50


def _correr(accion, contenido, extra=None):
    with tempfile.TemporaryDirectory() as carpeta:
        d = Path(carpeta)
        (d / 'plano.dxf').write_bytes(contenido)
        if extra is not None:
            (d / 'extra.json').write_text(json.dumps(extra), encoding='utf-8')
        try:
            r = subprocess.run(
                [sys.executable, '-m', 'core.plano_aparte', accion, carpeta],
                cwd=RAIZ, capture_output=True, timeout=TIEMPO_MAXIMO)
        except subprocess.TimeoutExpired:
            raise ErrorNegocio('El plano tardó demasiado en leerse.')
        error = d / 'error.txt'
        if error.exists():
            raise ErrorNegocio(error.read_text(encoding='utf-8'))
        salida = d / 'salida'
        if r.returncode != 0 or not salida.exists():
            log.error('plano_aparte %s falló: %s', accion,
                      r.stderr.decode('utf-8', 'replace')[-2000:])
            raise ErrorNegocio('No se pudo leer el plano.')
        return salida.read_bytes()


def analizar(contenido):
    """El dibujo y los trabajos del plano (ver plano_proyecto.analizar)."""
    datos = json.loads(_correr('analizar', contenido))
    for t in datos['trabajos']:
        if t['proyectado'] is not None:
            t['proyectado'] = Decimal(t['proyectado'])
    return datos


def replanteo(contenido, hechos, avance=None):
    """Los bytes del DXF replanteado (ver plano_proyecto.replanteo)."""
    return _correr('replanteo', contenido, {
        'hechos': {h: [None if m is None else str(m), c]
                   for h, (m, c) in hechos.items()},
        'avance': avance,
    })


def _main(accion, carpeta):
    from . import plano_proyecto as pp

    d = Path(carpeta)
    try:
        doc = pp.leer_archivo(str(d / 'plano.dxf'))
        if accion == 'analizar':
            datos = pp.analizar(doc)
            (d / 'salida').write_text(json.dumps(datos, default=str),
                                      encoding='utf-8')
        elif accion == 'replanteo':
            extra = json.loads((d / 'extra.json').read_text(encoding='utf-8'))
            hechos = {h: (None if m is None else Decimal(m), c)
                      for h, (m, c) in extra['hechos'].items()}
            (d / 'salida').write_bytes(
                pp.replanteo(doc, hechos, extra.get('avance')))
        else:
            raise ValueError(accion)
    except ErrorNegocio as e:
        (d / 'error.txt').write_text(str(e.detail), encoding='utf-8')


if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    _main(*sys.argv[1:3])
