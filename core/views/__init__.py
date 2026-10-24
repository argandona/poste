"""Vistas de la API, partidas por área. Este archivo reexporta todo para
que `from core.views import X` siga funcionando igual que cuando eran un
solo views.py."""
from .comun import *  # noqa: F401,F403
from .usuarios import *  # noqa: F401,F403
from .unidades import *  # noqa: F401,F403
from .sst import *  # noqa: F401,F403
from .almacen import *  # noqa: F401,F403
from .liquidaciones import *  # noqa: F401,F403
from .configuracion import *  # noqa: F401,F403
from .epp import *  # noqa: F401,F403
from .ipc import *  # noqa: F401,F403
from .configuracion import _solo_superadmin  # noqa: F401
