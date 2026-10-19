"""Candado para los comandos que siembran o pisan datos.

La app está en producción y la gente la usa: un `seed_demo`, `seed_prueba`,
`cargar_mano_de_obra` o `cargar_saldo_camion` corrido por descuido contra la
base de Render pisaría precios, el stock de un camión, la configuración de
tipos de trabajo o dejaría la clave de prueba en el SuperAdmin.

En producción (DEBUG apagado) se niegan a correr, salvo que se pida a
propósito con --forzar-produccion. En local (DEBUG encendido) corren igual que
siempre."""
from django.conf import settings
from django.core.management.base import CommandError

OPCION = '--forzar-produccion'


def agregar_opcion(parser):
    parser.add_argument(
        OPCION, action='store_true', dest='forzar_produccion',
        help='Correrlo aunque sea producción (pisa datos reales).')


def proteger(nombre, opciones):
    """Detiene el comando en producción si no se pidió forzarlo."""
    if settings.DEBUG or opciones.get('forzar_produccion'):
        return
    raise CommandError(
        f'Esto es producción: "{nombre}" no se corre aquí porque pisa datos '
        f'reales (precios, stock, configuración o claves). Si de verdad hace '
        f'falta, repítelo con {OPCION}.')
