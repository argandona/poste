"""Lo que comparten las vistas: importaciones, permisos por rol y helpers."""
import datetime
import io
import unicodedata
import openpyxl
from decimal import Decimal
from django.db.models import Q
from django.utils import timezone


from ..inclusiones import (
    INCLUSIONES_CONSOLIDADO, consolidar_partidas, partidas_cobradas,
    partidas_cobradas_por_poste, norm_actividad as _norm_txt,
)


from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from ..errores import ErrorNegocio
from ..fotos import guardar_foto, leer_base64, responder_foto, url_foto

from ..models import (
    ActividadTipoTrabajo, Actividad, actividades_para,
    Empresa, Rol, Usuario, Camion, UsuarioCamion, TraspasoCamion, SST,
    Material, StockCamion, Almacen, StockAlmacen, Proveedor,
    IngresoTecsur, DevolucionTecsur, MaterialMalogrado, TransferenciaAlmacen,
    Pedido, DetallePedido, Devolucion, DetalleDevolucion,
    UploadConsumo, Consumo, DetalleConsumo,
    Inventario, DetalleInventario,
    SSTEncargado, SSTSuministro, Suministro, TipoTrabajo, SuministroTipoTrabajo,
    SuministroManoDeObra, TipoTrabajoManoDeObra, TipoTrabajoMaterial, ManoDeObra, Recupero, SuministroRecupero,
    LiquidacionSuministro, LiquidacionPartida, ConsumoMaterialSuministro,
    CorreccionLiquidacion,
    PlanoSST, AsignacionAgregado,
    EPP, StockEPP, IngresoEPP, PedidoEPP, DetallePedidoEPP,
    ContactoEmergencia, IPC, IPCSST, IPCParticipante, Conduccion,
)
from ..serializers import (
    EmpresaSerializer, RolSerializer,
    UsuarioSerializer, UsuarioCreateSerializer,
    CamionSerializer, UsuarioCamionSerializer, TraspasoCamionSerializer,
    SSTSerializer,
    MaterialSerializer, StockCamionSerializer, AlmacenSerializer, StockAlmacenSerializer,
    ProveedorSerializer,
    IngresoTecsurSerializer, IngresoTecsurCreateSerializer,
    DevolucionTecsurSerializer, DevolucionTecsurCreateSerializer,
    MaterialMalogradoSerializer, MaterialMalogradoCreateSerializer,
    TransferenciaAlmacenSerializer, TransferenciaAlmacenCreateSerializer,
    PedidoSerializer, PedidoCreateSerializer, PedidoAprobarSerializer,
    DevolucionSerializer, DevolucionCreateSerializer, DevolucionAprobarSerializer,
    UploadConsumoSerializer,
    InventarioSerializer, InventarioCreateSerializer,
    SuministroSerializer, TipoTrabajoSerializer, ActividadSerializer, ManoDeObraSerializer,
    SuministroManoDeObraSerializer, RecuperoSerializer, SuministroRecuperoSerializer,
    LiquidacionSuministroSerializer, LiquidacionSuministroCreateSerializer,
    CorreccionLiquidacionSerializer,
    ConsumoMaterialSuministroSerializer,
    PlanoSSTSerializer,
    EPPSerializer, IngresoEPPSerializer,
)


def con_rol(*roles):
    """Filtro de usuarios por rol, mirando el principal y el secundario.

    Quien es capataz y coordinador a la vez tiene que salir en las dos listas."""
    return Q(rol_id__in=roles) | Q(rol_secundario_id__in=roles)

class CatalogoPagination(PageNumberPagination):
    """Paginación amplia para catálogos usados en búsquedas (mano de obra,
    materiales): una búsqueda devuelve todas sus coincidencias, no solo 20."""
    page_size = 500
    page_size_query_param = 'page_size'
    max_page_size = 2000

# ── Helper: suministros asignados (100% LOCAL, sin fuentes externas) ──────────
def _suministros_asignados_usuario(usuario, fecha_desde=None, fecha_hasta=None):
    """
    Suministros ASIGNADOS pendientes de liquidar del usuario, tomados de la
    base local de TECSUR (SSTSuministro.asignado_a = usuario y
    Suministro.estado = 'asignado'). Devuelve dicts con la misma forma que
    consume la app (semana_trabajo / semana_sst), pero sin depender de nada
    externo.
    """
    qs = (SSTSuministro.objects
          .select_related('sst', 'sst__actividad', 'suministro')
          .filter(asignado_a=usuario, suministro__estado='asignado'))

    con_rango = bool(fecha_desde and fecha_hasta)
    if con_rango:
        qs = qs.filter(sst__fecha_inicio__gte=fecha_desde,
                       sst__fecha_inicio__lte=fecha_hasta)

    out = []
    for rel in qs:
        sst = rel.sst
        s   = rel.suministro
        fecha_prog = str(sst.fecha_inicio) if sst.fecha_inicio else ''
        out.append({
            'id':                     s.id_suministro,
            'suministro':             s.numero_suministro,
            'numero_suministro':      s.numero_suministro,
            'sst_codigo':             sst.codigo or sst.sst or '',
            'fecha_programada':       fecha_prog,
            'direccion':              s.medidor or '',
            'distrito':   {'nombre_distrito':  s.distrito or sst.distrito or ''},
            'actividad':  {'nombre_actividad': sst.actividad.nombre if sst.actividad else ''},
            'estado_suministro': {'estado_suministro': 'ASIGNADO'},
            'hora_inicio_programada': None,
            'hora_fin_programada':    None,
            'ejecutado_por':          usuario.nombre,
        })
    return out

# Alias para no tocar el resto de las vistas que ya llamaban a este nombre.
def ssts_ya_liquidadas(usuario, sst_ids=None):
    """Las SST en que el usuario ya liquidó todos sus postes: ya se ejecutaron,
    así que ya tuvieron su IPC y no se ofrecen para uno nuevo. Una SST sin
    postes suyos todavía (los agrega en campo) no cuenta como liquidada."""
    qs = SSTSuministro.objects.filter(asignado_a=usuario)
    if sst_ids is not None:
        qs = qs.filter(sst_id__in=sst_ids)
    con_postes = set(qs.values_list('sst_id', flat=True))
    pendientes = set(qs.filter(suministro__estado='asignado',
                               suministro__liquidaciones__isnull=True)
                     .values_list('sst_id', flat=True))
    # Una obra de varios días sigue hasta que el coordinador la termina: cada
    # día lleva su IPC aunque ya tenga partes.
    abiertas = set(qs.filter(sst__actividad__varios_dias=True,
                             sst__obra_terminada_el__isnull=True)
                   .values_list('sst_id', flat=True))
    return con_postes - pendientes - abiertas


def usuario_consultado(request, puede_ver_otros):
    """El usuario de `?usuario=<id>`, si quien pregunta puede verlo.

    Cada uno ve lo suyo; ver lo de otro solo si `puede_ver_otros(actor)` y
    es de su empresa (el SuperAdmin, de cualquiera). Así nadie consulta los
    datos de otro cambiando el número en la dirección."""
    actor = (Usuario.objects.select_related('rol')
             .filter(pk=request.user.id_usuario).first())
    if actor is None:
        raise PermissionDenied('Sesión no válida.')
    usuario_id = str(request.query_params.get('usuario') or '').strip()
    if not usuario_id or usuario_id == str(actor.pk):
        return actor
    if not puede_ver_otros(actor):
        raise PermissionDenied('Solo puedes ver tus propios datos.')
    usuario = (Usuario.objects.select_related('rol')
               .filter(pk=usuario_id).first() if usuario_id.isdigit() else None)
    if usuario is None:
        raise ErrorNegocio('Usuario no encontrado.')
    if (not actor.es_superadmin() and actor.empresa_id
            and usuario.empresa_id != actor.empresa_id):
        raise PermissionDenied('Ese usuario es de otra empresa.')
    return usuario


def _render_suministros(nombre_usuario, fecha_desde=None, fecha_hasta=None):
    usuario = Usuario.objects.filter(nombre=nombre_usuario).first()
    if usuario is None:
        return []
    return _suministros_asignados_usuario(usuario, fecha_desde, fecha_hasta)

# ── Helper: retorna queryset filtrado por empresa del usuario autenticado ──
def solo_superadmin(request, mensaje):
    """Corta con 403 si quien pide no es SuperAdmin."""
    actor = Usuario.objects.filter(
        pk=getattr(request.user, 'id_usuario', None)).first()
    if not (actor and actor.es_superadmin()):
        raise PermissionDenied(mensaje)


def qs_empresa(qs, request, campo='empresa'):
    """
    Si el usuario autenticado es SuperAdmin ve todo.
    Cualquier otro rol solo ve registros de su empresa.
    """
    user = request.user
    # Usamos el usuario de nuestra tabla (no el auth de Django).
    # La autenticación JWT guarda el id_usuario en el token.
    try:
        usuario_obj = Usuario.objects.get(pk=user.id_usuario)
        if not usuario_obj.es_superadmin() and usuario_obj.empresa_id:
            return qs.filter(**{campo: usuario_obj.empresa_id})
    except (AttributeError, Usuario.DoesNotExist):
        pass
    return qs

# Quienes aprueban pedidos y devoluciones, y por eso reciben el aviso cuando
# llega uno nuevo. Tienen que ser los mismos que puede_aprobar_pedido().
ROLES_QUE_APRUEBAN = (Rol.ENCARGADO_ALMACEN, Rol.SUPERADMIN)

def _texto_de_celda(valor):
    """Una celda como texto, sin el ".0" que Excel le pone a los números."""
    if valor is None:
        return ''
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()

def _sin_tildes(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto.lower())
                   if unicodedata.category(c) != 'Mn')

def lineas_de_ingreso(filas):
    """Las líneas de un Excel de ingreso, listas para revisar.

    Las columnas se buscan por su título en las primeras filas: la que diga
    "matrícula" (o "código") y la que diga "cantidad". Sin títulos se toma la
    A como matrícula y la B como cantidad."""
    col_mat, col_cant, inicio = 0, 1, 0
    for i, fila in enumerate(filas[:10]):
        titulos = [_sin_tildes(_texto_de_celda(c)) for c in fila]
        mat = next((j for j, t in enumerate(titulos)
                    if 'matricula' in t or 'codigo' in t), None)
        cant = next((j for j, t in enumerate(titulos) if 'cantidad' in t), None)
        if mat is not None and cant is not None:
            col_mat, col_cant, inicio = mat, cant, i + 1
            break

    sumadas, orden, sin_cantidad = {}, [], []
    for numero, fila in enumerate(filas[inicio:], start=inicio + 1):
        celdas = list(fila) + [None] * 2
        matricula = _texto_de_celda(celdas[col_mat])
        if not matricula:
            continue
        try:
            cantidad = Decimal(_texto_de_celda(celdas[col_cant]).replace(',', '.'))
        except ArithmeticError:
            cantidad = None
        if cantidad is None or not cantidad.is_finite() or cantidad <= 0:
            sin_cantidad.append({'fila': numero, 'matricula': matricula})
            continue
        if matricula not in sumadas:
            orden.append(matricula)
            sumadas[matricula] = {'fila': numero, 'cantidad': Decimal('0')}
        sumadas[matricula]['cantidad'] += cantidad

    materiales = {m.matricula: m for m in
                  Material.objects.filter(matricula__in=orden)}
    lineas, no_encontrados = [], []
    for matricula in orden:
        dato = sumadas[matricula]
        material = materiales.get(matricula)
        if material is None:
            no_encontrados.append({'fila': dato['fila'], 'matricula': matricula})
            continue
        lineas.append({
            'material': material.id_material,
            'matricula': matricula,
            'descripcion': material.descripcion,
            'cantidad': float(dato['cantidad'].quantize(Decimal('0.01'))),
        })
    return {'lineas': lineas, 'no_encontrados': no_encontrados,
            'sin_cantidad': sin_cantidad}

def fmt_cantidad(valor, signo=False):
    """Una cantidad como se lee en obra: 4, 2.5, 1.25; con signo, +2.5 o -1."""
    valor = Decimal(valor).quantize(Decimal('0.01')).normalize()
    texto = f'{valor:f}'
    return f'+{texto}' if signo and valor > 0 else texto

# El "departamento" del formato de recupero TS-REC-FR-001.
DEPARTAMENTO_DEL_RECUPERO = 'Mantenimiento'

def solo_propios(qs, request, puede_aprobar):
    """Pedidos o devoluciones que le tocan a quien consulta.

    Quien los hace ve solo los suyos. Quien los aprueba los ve todos, aunque
    además tenga rol de capataz: si no, su bandeja de pendientes le mostraría
    solo lo que él mismo pidió. Con ?propios=1 cualquiera ve solo los suyos,
    que es lo que pide la pantalla de "mis pedidos".
    """
    try:
        usr = Usuario.objects.get(pk=request.user.id_usuario)
    except (AttributeError, Usuario.DoesNotExist):
        return qs
    propios = request.query_params.get('propios') in ('1', 'true')
    if propios or (usr.puede_hacer_pedido() and not getattr(usr, puede_aprobar)()):
        return qs.filter(usuario_id=usr.pk)
    return qs


# Todo lo de aquí (importaciones incluidas) lo usan las áreas.
__all__ = [n for n in dir() if not n.startswith("__")]
