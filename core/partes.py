"""Las obras de varios días: el parte diario y el cierre de la obra.

En las demás actividades volver a liquidar un poste reemplaza lo anterior. En
una obra de varios días (`Actividad.varios_dias`) cada capataz manda un parte
por día y por punto, y la liquidación es la suma de todos: grabar de nuevo
solo corrige el parte de ese mismo día, capataz y punto.

El capataz corrige sus propios partes mientras la obra siga abierta. El
coordinador y el liquidador corrigen el de cualquiera, también con la obra
terminada. La da por terminada el coordinador.
"""
import datetime

from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from .errores import ErrorNegocio


def sst_del_punto(suministro=None, sst_codigo=''):
    """La SST a la que pertenece lo que se liquida, o None."""
    from .models import SST, SSTSuministro

    if suministro is not None:
        rel = (SSTSuministro.objects.filter(suministro=suministro)
               .select_related('sst__actividad').first())
        if rel:
            return rel.sst
    if sst_codigo:
        return (SST.objects.filter(Q(codigo=sst_codigo) | Q(sst=sst_codigo))
                .select_related('actividad').first())
    return None


def es_de_varios_dias(sst):
    return bool(sst is not None and sst.actividad_id
                and sst.actividad.varios_dias)


def fecha_del_parte(valor):
    """El día que reporta el parte: hoy si no viene. No puede ser mañana."""
    hoy = datetime.date.today()
    if not valor:
        return hoy
    if isinstance(valor, str):
        try:
            valor = datetime.date.fromisoformat(valor)
        except ValueError:
            raise ErrorNegocio('La fecha del parte no es válida.')
    if valor > hoy:
        raise ErrorNegocio('El parte no puede ser de un día que no llega.')
    return valor


def revisar_parte(actor, sst, usuario):
    """Corta si [actor] no puede grabar el parte de [usuario] en [sst].

    Sin actor (scripts, tests viejos) no se revisa nada."""
    if actor is None:
        return
    if actor.puede_corregir_partes():
        return
    if usuario is not None and usuario.pk != actor.pk:
        raise PermissionDenied('Solo corriges tus propios partes.')
    if sst.obra_terminada_el is not None:
        raise ErrorNegocio(
            f'La obra de la SST {sst.codigo or sst.sst} ya está terminada: '
            'solo el coordinador o el liquidador corrigen sus partes.')
