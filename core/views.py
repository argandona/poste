import datetime
import unicodedata
import openpyxl
from decimal import Decimal
from django.utils import timezone


def _norm_txt(s):
    s = (s or '').lower().strip()
    s = ''.join(c for c in unicodedata.normalize('NFD', s)
                if unicodedata.category(c) != 'Mn')
    return ' '.join(s.split())


# Reglas de "lo ya incluido" en el paquete de cambio de poste, por actividad.
# Cobrado = max(0, real - num_cambios * incluido_por_unidad).
INCLUSIONES_CONSOLIDADO = {
    'cambio de poste inaccesible subterraneo': {
        'paquete': ['*090470', '*090471'],
        # Valor entero -> se multiplica por N (total de cambios de poste).
        # Dict {'segun': partida, 'cantidad': v} -> se multiplica por la cantidad
        # de esa partida específica del paquete (ej. solo *090470 con vereda).
        'incluidos': {
            '*091608': 2, '*091320': 1, '*091316': 1, '*091322': 1,
            '*091346': 1, '*091357': 1, '*091356': 1,
            '*090633': 100,   # el cambio de poste ya incluye 100 de acarreo
            '*091840': {'segun': '*090470', 'cantidad': 2},  # 2 incluidos por cambio CON vereda
        },
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
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.parsers import MultiPartParser
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class ErrorNegocio(APIException):
    """Error de regla de negocio dentro de un bloque transaccional.

    Devolver un `Response` desde dentro de un `transaction.atomic()` sale del
    bloque sin excepción, así que la transacción COMMITEA lo hecho hasta ahí:
    un pedido de varios materiales podía descontar los primeros y responder 400
    por el último. Lanzar esta excepción aborta la transacción y responde 400
    con la misma forma que antes (`{"detail": "<texto>"}`), que es lo que espera
    la app Flutter en api_service.dart.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Operación inválida.'


class CatalogoPagination(PageNumberPagination):
    """Paginación amplia para catálogos usados en búsquedas (mano de obra,
    materiales): una búsqueda devuelve todas sus coincidencias, no solo 20."""
    page_size = 500
    page_size_query_param = 'page_size'
    max_page_size = 2000

from .models import (
    ActividadTipoTrabajo, Actividad,
    Empresa, Rol, Usuario, Camion, UsuarioCamion, TraspasoCamion, SST,
    Material, StockCamion, Almacen, StockAlmacen, Proveedor,
    IngresoTecsur, DevolucionTecsur, MaterialMalogrado, TransferenciaAlmacen,
    Pedido, DetallePedido, Devolucion, DetalleDevolucion,
    UploadConsumo, Consumo, DetalleConsumo,
    Inventario, DetalleInventario,
    SSTEncargado, SSTSuministro, Suministro, TipoTrabajo, SuministroTipoTrabajo,
    SuministroManoDeObra, TipoTrabajoManoDeObra, TipoTrabajoMaterial, ManoDeObra, Recupero, SuministroRecupero,
    LiquidacionSuministro, LiquidacionPartida, ConsumoMaterialSuministro,
    PlanoSST,
)
from .serializers import (
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
    ConsumoMaterialSuministroSerializer,
    PlanoSSTSerializer,
)


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
def _render_suministros(nombre_usuario, fecha_desde=None, fecha_hasta=None):
    usuario = Usuario.objects.filter(nombre=nombre_usuario).first()
    if usuario is None:
        return []
    return _suministros_asignados_usuario(usuario, fecha_desde, fecha_hasta)


# ── Helper: retorna queryset filtrado por empresa del usuario autenticado ──
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


# ── Empresa ─────────────────────────────────────────────────────────────────
class EmpresaViewSet(viewsets.ModelViewSet):
    serializer_class   = EmpresaSerializer
    queryset           = Empresa.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return qs_empresa(super().get_queryset(), self.request, 'id_empresa')


# ── Rol ─────────────────────────────────────────────────────────────────────
class RolViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class   = RolSerializer
    queryset           = Rol.objects.all()
    permission_classes = [permissions.IsAuthenticated]


# ── Usuario ─────────────────────────────────────────────────────────────────
class UsuarioViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return UsuarioCreateSerializer
        return UsuarioSerializer

    def get_queryset(self):
        return qs_empresa(Usuario.objects.select_related('rol','empresa'), self.request)

    @action(detail=False, methods=['post'])
    def fcm_token(self, request):
        """POST /api/usuarios/fcm_token/ — guarda el token FCM del usuario autenticado."""
        token = request.data.get('token')
        if not token:
            return Response({'detail': 'token requerido'}, status=400)
        Usuario.objects.filter(pk=request.user.id_usuario).update(fcm_token=token)
        return Response({'status': 'ok'})

    @action(detail=False, methods=['get'])
    def me(self, request):
        """Devuelve los datos del usuario autenticado."""
        try:
            usuario = Usuario.objects.select_related('rol','empresa').get(pk=request.user.id_usuario)
            serializer = UsuarioSerializer(usuario)
            return Response(serializer.data)
        except Usuario.DoesNotExist:
            return Response({'detail': 'No encontrado.'}, status=404)


# ── Camion ──────────────────────────────────────────────────────────────────
class CamionViewSet(viewsets.ModelViewSet):
    serializer_class   = CamionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return qs_empresa(Camion.objects.select_related('empresa'), self.request)


# ── UsuarioCamion ────────────────────────────────────────────────────────────
class UsuarioCamionViewSet(viewsets.ModelViewSet):
    serializer_class   = UsuarioCamionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return UsuarioCamion.objects.select_related('camion','usuario').all()

    # El ModelViewSet guarda sin pasar por clean(), así que las reglas de
    # responsabilidad se validan a mano en cada escritura.
    def _validar(self, instancia):
        try:
            instancia.full_clean()
        except DjangoValidationError as e:
            raise ErrorNegocio(' '.join(e.messages))

    def perform_create(self, serializer):
        self._validar(UsuarioCamion(**serializer.validated_data))
        serializer.save()

    def perform_update(self, serializer):
        instancia = serializer.instance
        for campo, valor in serializer.validated_data.items():
            setattr(instancia, campo, valor)
        self._validar(instancia)
        serializer.save()

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except DjangoValidationError as e:
            raise ErrorNegocio(' '.join(e.messages))

    @action(detail=False, methods=['get'])
    def camion_activo(self, request):
        """GET /api/usuario-camion/camion_activo/?usuario=<id>"""
        usuario_id = request.query_params.get('usuario')
        if not usuario_id:
            return Response({'detail': 'Parámetro usuario requerido.'}, status=400)
        try:
            usuario = Usuario.objects.get(pk=usuario_id)
        except Usuario.DoesNotExist:
            return Response({'detail': 'Usuario no encontrado.'}, status=404)
        camion = UsuarioCamion.camion_activo_de_usuario(usuario)
        if camion:
            return Response(CamionSerializer(camion).data)
        return Response({'detail': 'Sin camión asignado.'}, status=404)

    # ── Soltar un camión es una operación, nunca un vencimiento ─────────────
    # Mientras el camión tenga saldo, el responsable no puede desaparecer: o
    # devuelve el material al almacén, o se lo entrega a otro con acta.

    def _actor_gestiona_almacen(self, request):
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        return actor if (actor and actor.puede_gestionar_almacen()) else None

    @action(detail=True, methods=['post'])
    def liberar(self, request, pk=None):
        """POST /api/usuario-camion/{id}/liberar/ — cierra la asignación.

        Solo si el camión quedó en cero; si tiene saldo hay que traspasarlo."""
        if not self._actor_gestiona_almacen(request):
            return Response(
                {'detail': 'Solo el Encargado de Almacén puede liberar un camión.'},
                status=403)
        asignacion = self.get_object()
        if not asignacion.activo:
            raise ErrorNegocio('Esta asignación ya está cerrada.')
        try:
            asignacion.liberar()
        except DjangoValidationError as e:
            raise ErrorNegocio(' '.join(e.messages))
        return Response(UsuarioCamionSerializer(asignacion).data)

    @action(detail=False, methods=['post'])
    def traspasar(self, request):
        """POST /api/usuario-camion/traspasar/
        Body: {camion: id, usuario_recibe: id, observacion?: str}

        Cierra la asignación vigente y abre la del nuevo responsable en un solo
        movimiento, dejando el acta con el saldo que cambió de manos."""
        if not self._actor_gestiona_almacen(request):
            return Response(
                {'detail': 'Solo el Encargado de Almacén puede traspasar un camión.'},
                status=403)
        camion_id  = request.data.get('camion')
        recibe_id  = request.data.get('usuario_recibe')
        if not camion_id or not recibe_id:
            raise ErrorNegocio('Se requiere camion y usuario_recibe.')
        try:
            camion = Camion.objects.get(pk=camion_id)
            recibe = Usuario.objects.get(pk=recibe_id)
        except (Camion.DoesNotExist, Usuario.DoesNotExist):
            return Response({'detail': 'Camión o usuario no encontrado.'}, status=404)

        asignacion = (UsuarioCamion.objects
                      .filter(camion=camion, activo=True)
                      .filter(models.Q(fecha_fin__isnull=True)|models.Q(fecha_fin__gte=datetime.date.today()))
                      .select_related('usuario').first())
        if asignacion is None:
            raise ErrorNegocio(f'El camión {camion.placa} no tiene un responsable vigente.')
        try:
            acta = asignacion.traspasar_a(
                recibe, observacion=request.data.get('observacion', ''))
        except DjangoValidationError as e:
            raise ErrorNegocio(' '.join(e.messages))
        return Response(TraspasoCamionSerializer(acta).data, status=201)

    @action(detail=False, methods=['get'])
    def saldos_por_responsable(self, request):
        """GET /api/usuario-camion/saldos_por_responsable/ — quién tiene qué encima."""
        hoy = datetime.date.today()
        vigentes = (UsuarioCamion.objects
                    .filter(activo=True)
                    .filter(models.Q(fecha_fin__isnull=True)|models.Q(fecha_fin__gte=hoy))
                    .select_related('usuario', 'camion')
                    .order_by('usuario__nombre'))
        datos = []
        for a in vigentes:
            saldo = (StockCamion.objects.filter(camion=a.camion)
                     .aggregate(t=models.Sum('cantidad'))['t'] or Decimal('0'))
            materiales = (StockCamion.objects
                          .filter(camion=a.camion, cantidad__gt=0).count())
            datos.append({
                'id_usuario_camion': a.pk,
                'usuario':      a.usuario.nombre,
                'id_usuario':   a.usuario_id,
                'camion':       a.camion.placa,
                'id_camion':    a.camion_id,
                'fecha_inicio': a.fecha_inicio,
                'materiales':   materiales,
                'saldo_total':  saldo,
                'puede_liberar': saldo == 0,
            })
        return Response(datos)


class TraspasoCamionViewSet(viewsets.ReadOnlyModelViewSet):
    """Actas de entrega de camión. Se crean con /usuario-camion/traspasar/."""
    serializer_class   = TraspasoCamionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = (TraspasoCamion.objects
              .select_related('camion', 'usuario_entrega', 'usuario_recibe')
              .prefetch_related('detalles__material'))
        camion = self.request.query_params.get('camion')
        if camion:
            qs = qs.filter(camion_id=camion)
        return qs


# ── SST ─────────────────────────────────────────────────────────────────────
class SSTViewSet(viewsets.ModelViewSet):
    serializer_class   = SSTSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return qs_empresa(SST.objects.select_related('empresa', 'actividad'), self.request)

    @action(detail=False, methods=['get'])
    def mis_sst(self, request):
        """GET /api/ssts/mis_sst/?usuario=<id> — SSTs donde el usuario es encargado."""
        usuario_id = request.query_params.get('usuario')
        if not usuario_id:
            return Response({'detail': 'Parámetro usuario requerido.'}, status=400)
        sst_ids = SSTEncargado.objects.filter(usuario_id=usuario_id).values_list('sst_id', flat=True)
        ssts = SST.objects.filter(id_sst__in=sst_ids).select_related('empresa', 'actividad')
        return Response(SSTSerializer(ssts, many=True).data)

    @action(detail=True, methods=['get'])
    def suministros(self, request, pk=None):
        """GET /api/ssts/<id>/suministros/ — suministros (postes) de este SST."""
        sst = self.get_object()
        items = (SSTSuministro.objects
                 .filter(sst=sst)
                 .select_related('suministro', 'asignado_a'))
        data = [
            {
                'id_sst_suministro': ss.id_sst_suministro,
                'id_suministro':     ss.suministro.id_suministro,
                'numero_suministro': ss.suministro.numero_suministro,
                'medidor':           ss.suministro.medidor,
                'distrito':          ss.suministro.distrito,
                'monto_sum':         str(ss.suministro.monto_sum),
                'estado':            ss.suministro.estado,
                'asignado_a':        ss.asignado_a_id,
                'asignado_nombre':   ss.asignado_a.nombre if ss.asignado_a else None,
            }
            for ss in items
        ]
        return Response(data)

    @action(detail=True, methods=['post'])
    def asignar(self, request, pk=None):
        """POST /api/ssts/<id>/asignar/  { usuario, suministros: [id_suministro,...] }

        Asigna los suministros (postes) indicados a un usuario (capataz) y lo
        marca como encargado del SST. Si no se envían suministros, asigna todos
        los del SST. Solo un Coordinador (o SuperAdmin) puede hacerlo."""
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        if not actor or not actor.puede_asignar_sst():
            return Response(
                {'detail': 'Solo un Coordinador puede asignar SST/suministros.'},
                status=403)
        sst = self.get_object()
        usuario_id = request.data.get('usuario')
        suministros_ids = request.data.get('suministros', [])
        if not usuario_id:
            return Response({'detail': 'usuario requerido.'}, status=400)
        try:
            capataz = Usuario.objects.get(pk=usuario_id)
        except Usuario.DoesNotExist:
            return Response({'detail': 'Usuario no encontrado.'}, status=404)
        with transaction.atomic():
            SSTEncargado.objects.get_or_create(sst=sst, usuario=capataz)
            qs = SSTSuministro.objects.filter(sst=sst)
            if suministros_ids:
                qs = qs.filter(suministro_id__in=suministros_ids)
            actualizados = qs.update(asignado_a=capataz)
        return Response({
            'status': 'ok',
            'suministros_asignados': actualizados,
            'sst': sst.codigo or sst.sst,
            'usuario': capataz.nombre,
        })

    @action(detail=True, methods=['post'])
    def desasignar(self, request, pk=None):
        """POST /api/ssts/<id>/desasignar/  { suministros: [id_suministro,...] }
        Quita la asignación de los suministros indicados (o de todos)."""
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        if not actor or not actor.puede_asignar_sst():
            return Response(
                {'detail': 'Solo un Coordinador puede desasignar.'}, status=403)
        sst = self.get_object()
        suministros_ids = request.data.get('suministros', [])
        qs = SSTSuministro.objects.filter(sst=sst)
        if suministros_ids:
            qs = qs.filter(suministro_id__in=suministros_ids)
        actualizados = qs.update(asignado_a=None)
        return Response({'status': 'ok', 'suministros_desasignados': actualizados})

    @action(detail=False, methods=['post'])
    def set_actividad(self, request):
        """POST /api/ssts/set_actividad/  { sst_codigo, actividad }
        Asigna (o cambia) la actividad de una SST identificada por su código,
        dentro de la empresa del usuario. Lo usa el capataz al liquidar."""
        sst_codigo = (request.data.get('sst_codigo') or '').strip()
        actividad_id = request.data.get('actividad')
        if not sst_codigo or not actividad_id:
            return Response({'detail': 'sst_codigo y actividad son obligatorios.'}, status=400)
        empresa_id = getattr(request.user, 'empresa_id', None)
        qs = SST.objects.filter(codigo=sst_codigo)
        if empresa_id:
            qs = qs.filter(empresa_id=empresa_id)
        actualizadas = qs.update(actividad_id=actividad_id)
        if not actualizadas:
            return Response({'detail': 'No se encontró la SST.'}, status=404)
        return Response({'status': 'ok', 'sst_codigo': sst_codigo,
                         'actividad': actividad_id, 'ssts_actualizadas': actualizadas})

    @action(detail=False, methods=['post'])
    def set_fecha_ejecucion(self, request):
        """POST /api/ssts/set_fecha_ejecucion/  { sst_codigo, fecha }
        Fija la fecha de ejecución de la SST (por código, en la empresa del usuario)."""
        sst_codigo = (request.data.get('sst_codigo') or '').strip()
        fecha = request.data.get('fecha')  # 'YYYY-MM-DD' o null
        if not sst_codigo:
            return Response({'detail': 'sst_codigo es obligatorio.'}, status=400)
        empresa_id = getattr(request.user, 'empresa_id', None)
        qs = SST.objects.filter(codigo=sst_codigo)
        if empresa_id:
            qs = qs.filter(empresa_id=empresa_id)
        n = qs.update(fecha_ejecucion=fecha or None)
        if not n:
            return Response({'detail': 'No se encontró la SST.'}, status=404)
        return Response({'status': 'ok', 'sst_codigo': sst_codigo,
                         'fecha_ejecucion': fecha, 'ssts_actualizadas': n})

    @action(detail=False, methods=['post'])
    def asignar_manual(self, request):
        """POST /api/ssts/asignar_manual/
        Body: { sst_codigo, numero_suministro, usuario, distrito? }

        Asignación escribiendo los códigos: crea la SST y/o el poste (suministro)
        si no existen, los enlaza y asigna el poste al capataz indicado, dejándolo
        como encargado de la SST. Solo Coordinador (o SuperAdmin)."""
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        if not actor or not actor.puede_asignar_sst():
            return Response(
                {'detail': 'Solo un Coordinador puede asignar.'}, status=403)

        sst_codigo = (request.data.get('sst_codigo') or '').strip()
        numero = (request.data.get('numero_suministro') or '').strip()
        usuario_id = request.data.get('usuario')
        distrito = (request.data.get('distrito') or '').strip()

        if not sst_codigo or not numero or not usuario_id:
            return Response(
                {'detail': 'sst_codigo, numero_suministro y usuario son obligatorios.'},
                status=400)

        if not actor.empresa_id:
            return Response(
                {'detail': 'El coordinador no tiene empresa asignada.'}, status=400)

        try:
            capataz = Usuario.objects.get(pk=usuario_id)
        except Usuario.DoesNotExist:
            return Response({'detail': 'Capataz no encontrado.'}, status=404)

        with transaction.atomic():
            sst, sst_nuevo = SST.objects.get_or_create(
                empresa_id=actor.empresa_id, codigo=sst_codigo,
                defaults={'distrito': distrito},
            )
            sum_obj, sum_nuevo = Suministro.objects.get_or_create(
                numero_suministro=numero,
                defaults={'distrito': distrito or sst.distrito, 'estado': 'asignado'},
            )
            SSTSuministro.objects.update_or_create(
                sst=sst, suministro=sum_obj,
                defaults={'asignado_a': capataz},
            )
            SSTEncargado.objects.get_or_create(sst=sst, usuario=capataz)

        return Response({
            'status': 'ok',
            'sst': sst.codigo,
            'sst_creada': sst_nuevo,
            'poste': sum_obj.numero_suministro,
            'poste_creado': sum_nuevo,
            'capataz': capataz.nombre,
        }, status=200)


# ── Material ─────────────────────────────────────────────────────────────────
class MaterialViewSet(viewsets.ModelViewSet):
    serializer_class   = MaterialSerializer
    queryset           = Material.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    pagination_class   = CatalogoPagination

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params.get('q')
        if q:
            qs = qs.filter(descripcion__icontains=q) | qs.filter(matricula__icontains=q)
        return qs

    @action(detail=False, methods=['get'])
    def resumen_stock(self, request):
        """
        GET /api/materiales/resumen_stock/
        Saldo real desde StockCamion (fuente de verdad, se actualiza al cerrar inventario).
        Los conteos de pedidos/consumos/devoluciones son informativos históricos.
        """
        from django.db.models import Sum, Q, IntegerField
        from django.db.models.functions import Coalesce
        from django.db.models import Value

        try:
            usr = Usuario.objects.get(pk=request.user.id_usuario)
            empresa_id = usr.empresa_id
        except (AttributeError, Usuario.DoesNotExist):
            empresa_id = None

        # Saldo real = suma de StockCamion por material (actualizado con inventarios físicos)
        stock_filter = Q(camion__empresa_id=empresa_id) if empresa_id else Q()
        stock_map = {
            row['material_id']: row['total']
            for row in (StockCamion.objects
                        .filter(stock_filter)
                        .values('material_id')
                        .annotate(total=Sum('cantidad')))
        }

        if not stock_map:
            return Response([])

        # Conteos históricos informativos para el modal de detalle
        eq_p = Q(detalles_pedido__pedido__camion__empresa_id=empresa_id) if empresa_id else Q()
        eq_d = Q(detalles_devolucion__devolucion__camion__empresa_id=empresa_id) if empresa_id else Q()
        eq_c = Q(detalles_consumo__consumo__camion__empresa_id=empresa_id) if empresa_id else Q()

        out = IntegerField()
        materiales = Material.objects.filter(id_material__in=stock_map.keys()).annotate(
            total_pedidos=Coalesce(
                Sum('detalles_pedido__cantidad_aprobada',
                    filter=Q(detalles_pedido__pedido__estado='aprobado') & eq_p),
                Value(0), output_field=out,
            ),
            total_devoluciones=Coalesce(
                Sum('detalles_devolucion__cantidad_aprobada',
                    filter=Q(detalles_devolucion__devolucion__estado='aprobado') & eq_d),
                Value(0), output_field=out,
            ),
            total_consumos=Coalesce(
                Sum('detalles_consumo__cantidad',
                    filter=Q(detalles_consumo__consumo__upload__estado='aprobado') & eq_c),
                Value(0), output_field=out,
            ),
        ).order_by('matricula')

        data = []
        for m in materiales:
            saldo = stock_map.get(m.id_material, 0)
            if saldo > 0:
                data.append({
                    'id_material':        m.id_material,
                    'matricula':          m.matricula,
                    'descripcion':        m.descripcion,
                    'total_pedidos':      m.total_pedidos,
                    'total_devoluciones': m.total_devoluciones,
                    'total_consumos':     m.total_consumos,
                    'saldo_actual':       saldo,
                })
        return Response(data)


# ── StockCamion ──────────────────────────────────────────────────────────────
class StockCamionViewSet(viewsets.ModelViewSet):
    serializer_class   = StockCamionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = StockCamion.objects.select_related('camion','material')
        camion_id = self.request.query_params.get('camion')
        if camion_id:
            qs = qs.filter(camion_id=camion_id)
        return qs

    @action(detail=False, methods=['get'])
    def por_camion(self, request):
        """
        GET /api/stock-camion/por_camion/
        Devuelve camiones agrupados con sus materiales en stock (cantidad > 0).
        ?usuario=<id>  → solo camiones asignados a ese usuario
        """
        from datetime import date
        from django.db.models import Q

        usuario_id = request.query_params.get('usuario')

        # Encargado ve solo materiales con stock > 0 (su vista no muestra negativos).
        # Enc. almacén (sin usuario_id) ve todo, incluyendo negativos.
        if usuario_id:
            ids = UsuarioCamion.objects.filter(
                usuario_id=usuario_id
            ).values_list('camion_id', flat=True).distinct()
            qs = StockCamion.objects.filter(
                cantidad__gt=0, camion_id__in=ids
            ).select_related('camion', 'material').order_by('material__matricula')
        else:
            qs = (StockCamion.objects.exclude(cantidad=0)
                  .select_related('camion', 'material')
                  .order_by('material__matricula'))

        hoy = date.today()
        asignaciones = {
            a.camion_id: a.usuario.nombre
            for a in UsuarioCamion.objects.filter(
                activo=True, fecha_inicio__lte=hoy
            ).filter(
                Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=hoy)
            ).select_related('usuario')
        }

        camiones = {}
        for stock in qs:
            cid = stock.camion_id
            if cid not in camiones:
                camiones[cid] = {
                    'camion_id':      cid,
                    'placa':          stock.camion.placa,
                    'usuario_nombre': asignaciones.get(cid, 'Sin asignar'),
                    'items':          [],
                }
            camiones[cid]['items'].append({
                'material_id': stock.material_id,
                'matricula':   stock.material.matricula,
                'descripcion': stock.material.descripcion,
                'cantidad':    stock.cantidad,
            })

        # Agregar cuánto hay en devoluciones pendientes por (camion, material)
        from django.db.models import Sum as _Sum
        camion_ids = list(camiones.keys())
        pending_map = {}
        for row in (DetalleDevolucion.objects
                    .filter(devolucion__estado='pendiente',
                            devolucion__camion_id__in=camion_ids)
                    .values('devolucion__camion_id', 'material_id')
                    .annotate(total=_Sum('cantidad_solicitada'))):
            pending_map[(row['devolucion__camion_id'], row['material_id'])] = row['total']

        for cid, camion_data in camiones.items():
            for item in camion_data['items']:
                item['pendiente_devolucion'] = pending_map.get((cid, item['material_id']), 0)

        return Response(list(camiones.values()))


# ── Almacen ──────────────────────────────────────────────────────────────────
class AlmacenViewSet(viewsets.ModelViewSet):
    serializer_class   = AlmacenSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return qs_empresa(Almacen.objects.select_related('empresa'), self.request)


# ── StockAlmacen ─────────────────────────────────────────────────────────────
class StockAlmacenViewSet(viewsets.ModelViewSet):
    serializer_class   = StockAlmacenSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = StockAlmacen.objects.select_related('almacen','material')
        almacen_id = self.request.query_params.get('almacen')
        if almacen_id:
            qs = qs.filter(almacen_id=almacen_id)
        return qs


# ── Proveedor ─────────────────────────────────────────────────────────────────
class ProveedorViewSet(viewsets.ModelViewSet):
    serializer_class   = ProveedorSerializer
    queryset           = Proveedor.objects.all()
    permission_classes = [permissions.IsAuthenticated]


# ── IngresoTecsur ─────────────────────────────────────────────────────────────
class IngresoTecsurViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return IngresoTecsurCreateSerializer
        return IngresoTecsurSerializer

    def get_queryset(self):
        return IngresoTecsur.objects.prefetch_related('detalles__material').select_related('almacen','proveedor','usuario')


# ── DevolucionTecsur ──────────────────────────────────────────────────────────
class DevolucionTecsurViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return DevolucionTecsurCreateSerializer
        return DevolucionTecsurSerializer

    def get_queryset(self):
        return DevolucionTecsur.objects.prefetch_related('detalles__material').select_related('almacen','proveedor','usuario')


# ── MaterialMalogrado ─────────────────────────────────────────────────────────
class MaterialMalogradoViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return MaterialMalogradoCreateSerializer
        return MaterialMalogradoSerializer

    def get_queryset(self):
        return MaterialMalogrado.objects.prefetch_related('detalles__material').select_related('almacen','proveedor','usuario')


# ── TransferenciaAlmacen ──────────────────────────────────────────────────────
class TransferenciaAlmacenViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return TransferenciaAlmacenCreateSerializer
        return TransferenciaAlmacenSerializer

    def get_queryset(self):
        return TransferenciaAlmacen.objects.prefetch_related('detalles__material').select_related('almacen_origen','almacen_destino','usuario')


# ── Pedido ────────────────────────────────────────────────────────────────────
class PedidoViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return PedidoCreateSerializer
        if self.action == 'aprobar':
            return PedidoAprobarSerializer
        return PedidoSerializer

    def perform_create(self, serializer):
        from .fcm import send_notification
        pedido = serializer.save()
        empresa_id = pedido.usuario.empresa_id
        tokens = list(
            Usuario.objects.filter(rol_id=Rol.ENCARGADO_ALMACEN, empresa_id=empresa_id, activo=True)
            .exclude(fcm_token__isnull=True).exclude(fcm_token='')
            .values_list('fcm_token', flat=True)
        )
        send_notification(
            tokens,
            title='Nuevo pedido por despachar',
            body=f'{pedido.usuario.nombre} solicitó materiales para el camión {pedido.camion.placa}.',
            data={'tipo': 'pedido_nuevo', 'pedido_id': str(pedido.pk)},
        )

    def get_queryset(self):
        qs = Pedido.objects.prefetch_related('detalles__material').select_related('camion','usuario','almacen','usuario_aprueba').order_by('-fecha')
        estado = self.request.query_params.get('estado')
        if estado:
            qs = qs.filter(estado=estado)
        camion = self.request.query_params.get('camion')
        if camion:
            qs = qs.filter(camion_id=camion)
        try:
            usr = Usuario.objects.get(pk=self.request.user.id_usuario)
            if usr.rol_id in (Rol.ENCARGADO, Rol.CAPATAZ):
                qs = qs.filter(usuario_id=usr.pk)
        except (AttributeError, Usuario.DoesNotExist):
            pass
        return qs

    @action(detail=True, methods=['post'])
    def aprobar(self, request, pk=None):
        """
        POST /api/pedidos/<id>/aprobar/
        Body: { accion, usuario_aprueba, almacen, observacion, detalles:[{material,cantidad_aprobada}] }
        """
        pedido = self.get_object()
        serializer = PedidoAprobarSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if pedido.estado != 'pendiente':
            return Response({'detail': 'Solo se puede procesar pedidos pendientes.'}, status=400)

        with transaction.atomic():
            if data['accion'] == 'rechazar':
                pedido.estado          = 'rechazado'
                pedido.usuario_aprueba = data['usuario_aprueba']
                pedido.observacion     = data.get('observacion', pedido.observacion)
                pedido.fecha_aprobacion = timezone.now().date()
                pedido.save()
                from .fcm import send_notification
                token = pedido.usuario.fcm_token
                if token:
                    send_notification([token], title='Pedido rechazado',
                        body=f'Tu pedido para el camión {pedido.camion.placa} fue rechazado.',
                        data={'tipo': 'pedido_rechazado', 'pedido_id': str(pedido.pk)})
                return Response({'detail': 'Pedido rechazado.'})

            # Aprobar
            almacen = data.get('almacen')
            if not almacen:
                raise ErrorNegocio('Se requiere almacen para aprobar.')

            for det_data in data.get('detalles', []):
                det = DetallePedido.objects.get(pedido=pedido, material=det_data['material'])
                cant_aprobada = det_data.get('cantidad_aprobada', 0)
                # Validar stock
                try:
                    stock = StockAlmacen.objects.get(almacen=almacen, material=det.material)
                    stock.descontar(cant_aprobada)
                except StockAlmacen.DoesNotExist:
                    raise ErrorNegocio(f'Sin stock de {det.material} en el almacén.')
                except DjangoValidationError as exc:
                    raise ErrorNegocio(exc.messages[0])
                # Subir stock camion
                stock_camion, _ = StockCamion.objects.get_or_create(
                    camion=pedido.camion, material=det.material, defaults={'cantidad': 0}
                )
                stock_camion.agregar(cant_aprobada)
                det.cantidad_aprobada = cant_aprobada
                det.save()

            pedido.estado           = 'aprobado'
            pedido.almacen          = almacen
            pedido.usuario_aprueba  = data['usuario_aprueba']
            pedido.fecha_aprobacion = timezone.now().date()
            pedido.observacion      = data.get('observacion', pedido.observacion)
            pedido.save()

        from .fcm import send_notification
        token = pedido.usuario.fcm_token
        if token:
            send_notification([token], title='Pedido despachado',
                body=f'Tu pedido para el camión {pedido.camion.placa} fue aprobado.',
                data={'tipo': 'pedido_aprobado', 'pedido_id': str(pedido.pk)})
        return Response(PedidoSerializer(pedido).data)


# ── Devolucion ────────────────────────────────────────────────────────────────
class DevolucionViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return DevolucionCreateSerializer
        if self.action == 'aprobar':
            return DevolucionAprobarSerializer
        return DevolucionSerializer

    def perform_create(self, serializer):
        from .fcm import send_notification
        devolucion = serializer.save()
        empresa_id = devolucion.usuario.empresa_id
        tokens = list(
            Usuario.objects.filter(rol_id=Rol.ENCARGADO_ALMACEN, empresa_id=empresa_id, activo=True)
            .exclude(fcm_token__isnull=True).exclude(fcm_token='')
            .values_list('fcm_token', flat=True)
        )
        send_notification(
            tokens,
            title='Nueva devolución por aprobar',
            body=f'{devolucion.usuario.nombre} devuelve materiales del camión {devolucion.camion.placa}.',
            data={'tipo': 'devolucion_nueva', 'devolucion_id': str(devolucion.pk)},
        )

    def get_queryset(self):
        qs = Devolucion.objects.prefetch_related('detalles__material').select_related('camion','usuario','almacen_destino','usuario_aprueba').order_by('-fecha')
        estado = self.request.query_params.get('estado')
        if estado:
            qs = qs.filter(estado=estado)
        try:
            usr = Usuario.objects.get(pk=self.request.user.id_usuario)
            if usr.rol_id in (Rol.ENCARGADO, Rol.CAPATAZ):
                qs = qs.filter(usuario_id=usr.pk)
        except (AttributeError, Usuario.DoesNotExist):
            pass
        return qs

    @action(detail=True, methods=['post'])
    def aprobar(self, request, pk=None):
        """
        POST /api/devoluciones/<id>/aprobar/
        Body: { accion, usuario_aprueba, almacen_destino, observacion, detalles }
        """
        devolucion = self.get_object()
        serializer = DevolucionAprobarSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if devolucion.estado != 'pendiente':
            return Response({'detail': 'Solo se puede procesar devoluciones pendientes.'}, status=400)

        with transaction.atomic():
            if data['accion'] == 'rechazar':
                devolucion.estado           = 'rechazado'
                devolucion.usuario_aprueba  = data['usuario_aprueba']
                devolucion.observacion      = data.get('observacion', devolucion.observacion)
                devolucion.fecha_aprobacion = timezone.now().date()
                devolucion.save()
                from .fcm import send_notification
                token = devolucion.usuario.fcm_token
                if token:
                    send_notification([token], title='Devolución rechazada',
                        body=f'Tu devolución del camión {devolucion.camion.placa} fue rechazada.',
                        data={'tipo': 'devolucion_rechazada', 'devolucion_id': str(devolucion.pk)})
                return Response({'detail': 'Devolución rechazada.'})

            almacen_destino = data.get('almacen_destino')
            if not almacen_destino:
                raise ErrorNegocio('Se requiere almacen_destino para aprobar.')

            for det_data in data.get('detalles', []):
                det = DetalleDevolucion.objects.get(devolucion=devolucion, material=det_data['material'])
                cant_aprobada = det_data.get('cantidad_aprobada', 0)
                # Descontar del camion
                try:
                    stock_camion = StockCamion.objects.get(camion=devolucion.camion, material=det.material)
                    stock_camion.descontar(cant_aprobada)
                except StockCamion.DoesNotExist:
                    raise ErrorNegocio(f'Sin stock de {det.material} en el camión.')
                except DjangoValidationError as exc:
                    raise ErrorNegocio(exc.messages[0])
                # Subir al almacén
                stock_alm, _ = StockAlmacen.objects.get_or_create(
                    almacen=almacen_destino, material=det.material, defaults={'cantidad': 0}
                )
                stock_alm.agregar(cant_aprobada)
                det.cantidad_aprobada = cant_aprobada
                det.save()

            devolucion.estado           = 'aprobado'
            devolucion.almacen_destino  = almacen_destino
            devolucion.usuario_aprueba  = data['usuario_aprueba']
            devolucion.fecha_aprobacion = timezone.now().date()
            devolucion.observacion      = data.get('observacion', devolucion.observacion)
            devolucion.save()
        from .fcm import send_notification
        token = devolucion.usuario.fcm_token
        if token:
            send_notification([token], title='Devolución aprobada',
                body=f'Tu devolución del camión {devolucion.camion.placa} fue aprobada.',
                data={'tipo': 'devolucion_aprobada', 'devolucion_id': str(devolucion.pk)})
        return Response(DevolucionSerializer(devolucion).data)


# ── UploadConsumo ─────────────────────────────────────────────────────────────
class UploadConsumoViewSet(viewsets.ModelViewSet):
    serializer_class   = UploadConsumoSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return UploadConsumo.objects.prefetch_related('consumos__detalles__material').select_related('sst','usuario')

    @action(detail=True, methods=['post'])
    def aprobar(self, request, pk=None):
        """POST /api/uploads-consumo/<id>/aprobar/ — descuenta StockCamion por cada DetalleConsumo."""
        upload = self.get_object()
        if upload.estado != 'pendiente':
            return Response({'detail': 'Solo se puede aprobar uploads pendientes.'}, status=400)
        with transaction.atomic():
            for consumo in upload.consumos.prefetch_related('detalles__material'):
                for det in consumo.detalles.all():
                    try:
                        stock = StockCamion.objects.get(camion=consumo.camion, material=det.material)
                        stock.descontar(det.cantidad)
                    except StockCamion.DoesNotExist:
                        raise ErrorNegocio(f'Sin stock de {det.material} en camión {consumo.camion}.')
                    except DjangoValidationError as exc:
                        raise ErrorNegocio(exc.messages[0])
            upload.estado = 'aprobado'
            upload.save()
        return Response({'detail': 'Consumo aprobado y stock descontado.'})

    @action(detail=True, methods=['post'])
    def rechazar(self, request, pk=None):
        upload = self.get_object()
        if upload.estado != 'pendiente':
            return Response({'detail': 'Solo se puede rechazar uploads pendientes.'}, status=400)
        upload.estado = 'rechazado'
        upload.save()
        return Response({'detail': 'Consumo rechazado.'})

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser])
    def procesar_excel(self, request):
        """
        POST /api/uploads-consumo/procesar_excel/
        Multipart: archivo (xlsx), usuario (id)

        Columnas esperadas:
          SST | SUMINISTRO | FECHA EJECUCION | TECNICO_EMPLEADO | MAT1 | MAT2 | ...
        """
        archivo    = request.FILES.get('archivo')
        usuario_id = request.data.get('usuario')

        if not archivo:
            return Response({'detail': 'Se requiere el archivo Excel.'}, status=400)
        if not usuario_id:
            return Response({'detail': 'Se requiere el parámetro usuario.'}, status=400)

        try:
            usuario_upload = Usuario.objects.get(pk=usuario_id)
        except Usuario.DoesNotExist:
            return Response({'detail': 'Usuario no encontrado.'}, status=404)

        # ── Leer Excel ────────────────────────────────────────────────────────
        try:
            wb   = openpyxl.load_workbook(archivo, data_only=True)
            ws   = wb.active
            rows = list(ws.iter_rows(values_only=True))
        except Exception as exc:
            return Response({'detail': f'Error al leer el archivo: {exc}'}, status=400)

        if len(rows) < 2:
            return Response({'detail': 'El archivo no contiene datos.'}, status=400)

        header             = rows[0]
        matriculas_excel   = [str(h).strip() for h in header[4:] if h is not None]

        # Precargar materiales por matrícula
        materiales = {
            m.matricula: m
            for m in Material.objects.filter(matricula__in=matriculas_excel)
        }

        # ── Obtener SST desde la primera fila de datos ────────────────────────
        codigo_sst = str(rows[1][0]).strip() if rows[1][0] is not None else ''
        try:
            sst = SST.objects.get(codigo=codigo_sst)
        except SST.DoesNotExist:
            return Response({'detail': f'SST con código "{codigo_sst}" no existe en el sistema.'}, status=404)

        errores  = []
        creados  = 0

        with transaction.atomic():
            upload, _ = UploadConsumo.objects.get_or_create(
                sst=sst,
                defaults={
                    'usuario':        usuario_upload,
                    'nombre_archivo': archivo.name,
                    'estado':         'pendiente',
                }
            )

            if upload.estado == 'aprobado':
                raise ErrorNegocio('Este SST ya tiene un consumo aprobado.')

            for num_fila, row in enumerate(rows[1:], start=2):
                if not any(row):
                    continue

                suministro   = str(row[1]).strip() if row[1] is not None else ''
                fecha_raw    = row[2]
                tecnico_str  = str(row[3]).strip().upper() if row[3] is not None else ''
                cantidades   = row[4:]

                # Parsear fecha
                if isinstance(fecha_raw, (datetime.date, datetime.datetime)):
                    fecha = fecha_raw if isinstance(fecha_raw, datetime.date) else fecha_raw.date()
                else:
                    try:
                        fecha = datetime.datetime.strptime(str(fecha_raw).strip(), '%d/%m/%Y').date()
                    except ValueError:
                        errores.append(f'Fila {num_fila}: fecha inválida "{fecha_raw}".')
                        continue

                # Buscar técnico por nombre (contiene apellido)
                qs_tecnico = Usuario.objects.filter(nombre__icontains=tecnico_str)
                if not qs_tecnico.exists():
                    errores.append(f'Fila {num_fila}: técnico "{tecnico_str}" no encontrado.')
                    continue
                if qs_tecnico.count() > 1:
                    errores.append(f'Fila {num_fila}: técnico "{tecnico_str}" es ambiguo ({qs_tecnico.count()} coincidencias).')
                    continue
                tecnico = qs_tecnico.first()

                # Buscar camión activo del técnico en esa fecha
                camion = UsuarioCamion.camion_activo_de_usuario(tecnico, fecha)
                if not camion:
                    errores.append(f'Fila {num_fila}: "{tecnico_str}" no tiene camión asignado el {fecha}.')
                    continue

                consumo, nuevo = Consumo.objects.get_or_create(
                    upload=upload,
                    usuario_consume=tecnico,
                    camion=camion,
                    suministro=suministro,
                    fecha=fecha,
                )

                # Registrar materiales con cantidad > 0
                for i, cantidad in enumerate(cantidades):
                    if i >= len(matriculas_excel):
                        break
                    if not cantidad or int(cantidad) == 0:
                        continue
                    material = materiales.get(matriculas_excel[i])
                    if not material:
                        errores.append(f'Fila {num_fila}: material "{matriculas_excel[i]}" no existe.')
                        continue
                    DetalleConsumo.objects.get_or_create(
                        consumo=consumo,
                        material=material,
                        defaults={'cantidad': int(cantidad)},
                    )

                if nuevo:
                    creados += 1

        return Response({
            'upload_id':       upload.id_upload,
            'sst':             codigo_sst,
            'archivo':         archivo.name,
            'consumos_creados': creados,
            'errores':         errores,
        }, status=201 if not errores else 207)


# ── Inventario ────────────────────────────────────────────────────────────────
class InventarioViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return InventarioCreateSerializer
        return InventarioSerializer

    def get_queryset(self):
        qs = Inventario.objects.prefetch_related('detalles__material').select_related('camion','almacen','usuario')
        camion  = self.request.query_params.get('camion')
        almacen = self.request.query_params.get('almacen')
        mes     = self.request.query_params.get('mes')
        anio    = self.request.query_params.get('anio')
        if camion:  qs = qs.filter(camion_id=camion)
        if almacen: qs = qs.filter(almacen_id=almacen)
        if mes:     qs = qs.filter(mes=mes)
        if anio:    qs = qs.filter(anio=anio)
        return qs

    @action(detail=False, methods=['post'])
    def iniciar_o_continuar(self, request):
        """
        POST /api/inventarios/iniciar_o_continuar/
        Body: {camion: id, usuario: id}
        Devuelve borrador del mes actual si existe, o crea uno nuevo
        con el stock teórico pre-cargado desde StockCamion.
        """
        from datetime import date as _date
        camion_id  = request.data.get('camion')
        usuario_id = request.data.get('usuario')
        if not camion_id or not usuario_id:
            return Response({'detail': 'Se requiere camion y usuario.'}, status=400)
        try:
            camion  = Camion.objects.get(pk=camion_id)
            usuario = Usuario.objects.get(pk=usuario_id)
        except (Camion.DoesNotExist, Usuario.DoesNotExist):
            return Response({'detail': 'Camión o usuario no encontrado.'}, status=404)

        hoy  = _date.today()
        mes  = hoy.month
        anio = hoy.year

        existente = (Inventario.objects
                     .prefetch_related('detalles__material')
                     .filter(camion=camion, mes=mes, anio=anio, estado='borrador')
                     .first())
        if existente:
            # Sincronizar con StockCamion actual: agregar materiales nuevos y
            # actualizar cantidad_teorica de los existentes
            with transaction.atomic():
                materiales_actuales = set(
                    existente.detalles.values_list('material_id', flat=True))
                for sc in StockCamion.objects.filter(camion=camion, cantidad__gt=0).select_related('material'):
                    if sc.material_id not in materiales_actuales:
                        DetalleInventario.objects.create(
                            inventario=existente,
                            material=sc.material,
                            cantidad_teorica=sc.cantidad,
                            cantidad_fisica=sc.cantidad,
                            diferencia=0,
                        )
                    else:
                        existente.detalles.filter(material_id=sc.material_id).update(
                            cantidad_teorica=sc.cantidad)
            existente.refresh_from_db()
            existente = (Inventario.objects
                         .prefetch_related('detalles__material')
                         .get(pk=existente.pk))
            return Response(InventarioSerializer(existente).data)

        with transaction.atomic():
            inventario = Inventario.objects.create(
                camion=camion, usuario=usuario, mes=mes, anio=anio, estado='borrador')
            for sc in StockCamion.objects.filter(camion=camion, cantidad__gt=0).select_related('material').order_by('material__matricula'):
                DetalleInventario.objects.create(
                    inventario=inventario,
                    material=sc.material,
                    cantidad_teorica=sc.cantidad,
                    cantidad_fisica=sc.cantidad,
                    diferencia=0,
                )
        inventario = (Inventario.objects
                      .prefetch_related('detalles__material')
                      .get(pk=inventario.pk))
        return Response(InventarioSerializer(inventario).data, status=201)

    @action(detail=True, methods=['patch'])
    def guardar_conteo(self, request, pk=None):
        """
        PATCH /api/inventarios/{id}/guardar_conteo/
        Body: {detalles: [{id_detalle_inventario: x, cantidad_fisica: y}, ...]}
        """
        inventario = self.get_object()
        if inventario.estado == 'cerrado':
            return Response({'detail': 'No se puede editar un inventario cerrado.'}, status=400)
        with transaction.atomic():
            for d in request.data.get('detalles', []):
                try:
                    det = DetalleInventario.objects.get(
                        pk=d['id_detalle_inventario'], inventario=inventario)
                    det.cantidad_fisica = d.get('cantidad_fisica', det.cantidad_fisica)
                    det.save()
                except DetalleInventario.DoesNotExist:
                    pass
        inventario = (Inventario.objects
                      .prefetch_related('detalles__material')
                      .get(pk=inventario.pk))
        return Response(InventarioSerializer(inventario).data)

    @action(detail=True, methods=['post'])
    def cerrar(self, request, pk=None):
        inventario = self.get_object()
        if inventario.estado == 'cerrado':
            return Response({'detail': 'Ya está cerrado.'}, status=400)

        with transaction.atomic():
            inventario = (Inventario.objects
                          .prefetch_related('detalles__material')
                          .select_related('camion','usuario')
                          .get(pk=inventario.pk))

            # Sincronizar StockCamion con el conteo físico
            if inventario.camion_id:
                for det in inventario.detalles.all():
                    StockCamion.objects.filter(
                        camion=inventario.camion, material=det.material
                    ).update(cantidad=det.cantidad_fisica)

            inventario.estado = 'cerrado'
            inventario.save()

        # Notificar al encargado del camión con las diferencias
        if inventario.camion_id:
            from datetime import date as _date
            from django.db.models import Q as _Q
            from .fcm import send_notification

            hoy = _date.today()
            asignacion = UsuarioCamion.objects.filter(
                camion=inventario.camion,
                activo=True,
                fecha_inicio__lte=hoy,
            ).filter(
                _Q(fecha_fin__isnull=True) | _Q(fecha_fin__gte=hoy)
            ).select_related('usuario').first()

            if asignacion and asignacion.usuario.fcm_token:
                diffs = [d for d in inventario.detalles.all() if d.diferencia != 0]
                if diffs:
                    lineas = ', '.join(
                        f'{d.material.matricula}: {d.diferencia:+d}' for d in diffs[:5]
                    )
                    if len(diffs) > 5:
                        lineas += f' y {len(diffs)-5} más'
                    body = f'Inventario cerrado. Diferencias: {lineas}'
                else:
                    body = 'Inventario cerrado. Sin diferencias.'
                send_notification(
                    [asignacion.usuario.fcm_token],
                    title=f'Inventario camión {inventario.camion.placa} cerrado',
                    body=body,
                    data={'tipo': 'inventario_cerrado', 'inventario_id': str(inventario.pk)},
                )

        # Enviar PDF por correo al encargado del camión y al enc. almacén
        from .pdf_inventario import enviar_pdf_inventario
        encargado = asignacion.usuario if (inventario.camion_id and asignacion) else None
        enviar_pdf_inventario(inventario, encargado_camion=encargado)

        return Response({'detail': 'Inventario cerrado.'})

    @action(detail=True, methods=['get'])
    def descargar_pdf(self, request, pk=None):
        """GET /api/inventarios/{id}/descargar_pdf/ — retorna el PDF del acta."""
        from django.http import HttpResponse
        from .pdf_inventario import generar_pdf_inventario
        from datetime import date as _date
        from django.db.models import Q as _Q

        inventario = (Inventario.objects
                      .prefetch_related('detalles__material')
                      .select_related('camion', 'usuario__empresa')
                      .get(pk=pk))

        encargado = None
        if inventario.camion_id:
            hoy = _date.today()
            asig = UsuarioCamion.objects.filter(
                camion=inventario.camion, activo=True, fecha_inicio__lte=hoy,
            ).filter(
                _Q(fecha_fin__isnull=True) | _Q(fecha_fin__gte=hoy)
            ).select_related('usuario').first()
            if asig:
                encargado = asig.usuario

        pdf_bytes = generar_pdf_inventario(inventario, encargado_camion=encargado)
        placa = inventario.camion.placa if inventario.camion_id else 'almacen'
        filename = f'inventario_{placa}_{inventario.mes}_{inventario.anio}.pdf'

        resp = HttpResponse(pdf_bytes, content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="{filename}"'
        return resp


# ── Suministro ────────────────────────────────────────────────────────────────
class SuministroViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class   = SuministroSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset           = Suministro.objects.all()

    @action(detail=True, methods=['get'])
    def mano_de_obra(self, request, pk=None):
        """GET /api/suministros/<id>/mano_de_obra/ — partidas de MO del suministro."""
        suministro = self.get_object()
        qs = SuministroManoDeObra.objects.filter(suministro=suministro).select_related('mano_de_obra')
        return Response(SuministroManoDeObraSerializer(qs, many=True).data)

    @action(detail=True, methods=['get'])
    def tipos_trabajo(self, request, pk=None):
        """GET /api/suministros/<id>/tipos_trabajo/ — todos los tipos con sus partidas."""
        tipos = TipoTrabajo.objects.prefetch_related('partidas__mano_de_obra', 'materiales__material').order_by('nombre')
        return Response(TipoTrabajoSerializer(tipos, many=True).data)

    @action(detail=True, methods=['get'])
    def recuperos(self, request, pk=None):
        """GET /api/suministros/<id>/recuperos/ — recuperos registrados del suministro."""
        suministro = self.get_object()
        qs = SuministroRecupero.objects.filter(suministro=suministro).select_related('recupero')
        return Response(SuministroRecuperoSerializer(qs, many=True).data)

    @action(detail=True, methods=['get'])
    def stock_camion_usuario(self, request, pk=None):
        """GET /api/suministros/<id>/stock_camion_usuario/ — materiales disponibles en el camión activo del usuario."""
        self.get_object()
        camion = UsuarioCamion.camion_activo_de_usuario(request.user)
        if camion is None:
            return Response({'detail': 'No tenés un camión activo asignado.'}, status=400)
        qs = StockCamion.objects.filter(camion=camion, cantidad__gt=0).select_related('material')
        return Response(StockCamionSerializer(qs, many=True).data)

    @action(detail=True, methods=['get'])
    def materiales_consumidos(self, request, pk=None):
        """GET /api/suministros/<id>/materiales_consumidos/ — historial de consumos de material del suministro."""
        suministro = self.get_object()
        qs = ConsumoMaterialSuministro.objects.filter(suministro=suministro).select_related('material', 'usuario', 'liquidacion')
        return Response(ConsumoMaterialSuministroSerializer(qs, many=True).data)


# ── Recupero ──────────────────────────────────────────────────────────────────
class RecuperoViewSet(viewsets.ModelViewSet):
    """Catálogo de recuperos + registro por suministro."""
    serializer_class   = RecuperoSerializer
    queryset           = Recupero.objects.all().order_by('matricula')
    permission_classes = [permissions.IsAuthenticated]
    pagination_class   = CatalogoPagination  # devuelve el catálogo completo

    @action(detail=False, methods=['get'])
    def por_suministro(self, request):
        """GET /api/recuperos/por_suministro/?suministro=<id> — recuperos ya
        registrados de ese suministro (para precargar la pestaña)."""
        suministro_id = request.query_params.get('suministro')
        qs = SuministroRecupero.objects.select_related('recupero')
        if suministro_id:
            qs = qs.filter(suministro_id=suministro_id)
        else:
            qs = qs.none()
        return Response(SuministroRecuperoSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'])
    def formato_pdf(self, request):
        """GET /api/recuperos/formato_pdf/?sst=<codigo>

        El formato TS-REC-FR-001 de Tecsur, lleno con los recuperos de todos
        los postes de esa SST, sumados por material."""
        from django.http import HttpResponse

        from .pdf_recupero import (
            fecha_larga, generar_pdf_recupero, nombre_de_firma,
        )

        codigo = (request.query_params.get('sst') or '').strip()
        if not codigo:
            raise ErrorNegocio('Se requiere el código de la SST.')

        sst = (SST.objects
               .filter(models.Q(codigo=codigo) | models.Q(sst=codigo))
               .select_related('empresa')
               .first())
        if sst is None:
            return Response({'detail': f'No existe la SST {codigo}.'}, status=404)

        # Los recuperos se cargan por poste; el formato es por SST, así que se
        # juntan todos y se suma la cantidad de cada material.
        suministros = Suministro.objects.filter(sst_suministros__sst=sst)
        registros = (SuministroRecupero.objects
                     .filter(suministro__in=suministros)
                     .select_related('recupero')
                     .order_by('recupero__descripcion'))
        sumados = {}
        for r in registros:
            clave = r.recupero_id
            if clave in sumados:
                sumados[clave]['total'] += r.cantidad
            else:
                sumados[clave] = {
                    'descripcion': r.recupero.descripcion,
                    'unidad': r.recupero.unidad,
                    'total': r.cantidad,
                }
        items = [{
            'descripcion': v['descripcion'],
            'unidad': v['unidad'],
            'cantidad': (f"{v['total']:.2f}".rstrip('0').rstrip('.')),
        } for v in sumados.values()]

        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        capataz = (Usuario.objects
                   .filter(sst_encargados__sst=sst, rol_id=Rol.CAPATAZ)
                   .select_related('rol').first())
        if capataz is None:
            capataz = (Usuario.objects
                       .filter(suministros_asignados__sst=sst)
                       .select_related('rol').distinct().first())

        firma = nombre_de_firma(capataz.nombre if capataz else '')
        pdf = generar_pdf_recupero({
            'sst': sst.codigo or sst.sst,
            'fecha': fecha_larga(sst.fecha_ejecucion),
            'departamento': sst.distrito or '',
            'contratista': sst.empresa.nombre if sst.empresa_id else '',
            'reportado_por': actor.nombre if actor else '',
            'capataz': capataz.nombre if capataz else '',
            'cargo': capataz.rol.descripcion if capataz else '',
            'firma': firma,
            'firma_pie': (
                f'Firmado electrónicamente desde la app · '
                f'{fecha_larga()} · usuario #{capataz.id_usuario}'
                if capataz else 'Sin capataz asignado'),
        }, items)

        resp = HttpResponse(pdf, content_type='application/pdf')
        nombre = f'recupero_{sst.codigo or sst.sst}.pdf'
        resp['Content-Disposition'] = f'attachment; filename="{nombre}"'
        return resp

    @action(detail=False, methods=['post'])
    def registrar(self, request):
        """POST /api/recuperos/registrar/ { suministro, fecha?, items:[{recupero,cantidad}] }
        Reemplaza los recuperos del suministro por los enviados."""
        import datetime as _dt
        suministro_id = request.data.get('suministro')
        items = request.data.get('items', [])
        fecha = request.data.get('fecha') or str(_dt.date.today())
        if not suministro_id:
            return Response({'detail': 'suministro requerido.'}, status=400)
        sum_obj = Suministro.objects.filter(pk=suministro_id).first()
        if sum_obj is None:
            return Response({'detail': 'Suministro no encontrado.'}, status=404)
        with transaction.atomic():
            SuministroRecupero.objects.filter(suministro=sum_obj).delete()
            for it in items:
                cant = it.get('cantidad')
                rec = it.get('recupero')
                if rec and cant and float(cant) > 0:
                    SuministroRecupero.objects.create(
                        suministro=sum_obj, recupero_id=rec, cantidad=cant, fecha=fecha)
        n = SuministroRecupero.objects.filter(suministro=sum_obj).count()
        return Response({'status': 'ok', 'recuperos': n})


# ── Liquidacion Suministro ────────────────────────────────────────────────────
class LiquidacionViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return LiquidacionSuministroCreateSerializer
        return LiquidacionSuministroSerializer

    def get_queryset(self):
        qs = (LiquidacionSuministro.objects
              .select_related('suministro', 'usuario', 'tipo_trabajo')
              .prefetch_related('partidas__mano_de_obra', 'materiales_consumidos__material')
              .order_by('-fecha'))
        suministro = self.request.query_params.get('suministro')
        if suministro:
            qs = qs.filter(suministro_id=suministro)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = LiquidacionSuministroCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        liq = serializer.save()
        return Response(LiquidacionSuministroSerializer(liq).data, status=201)

    @action(detail=False, methods=['get'])
    def consolidado(self, request):
        """GET /api/liquidaciones/consolidado/?usuario=<id>

        Consolida las liquidaciones. El descuento del 'cambio de poste' se
        calcula POR POSTE (suministro): cobrado = max(0, real - N*incluido),
        con N = cambios de poste de ese poste. Luego se AGREGA por SST para
        mostrar. La actividad se detecta por el tipo de trabajo liquidado.
        Para que descuente, el poste y su alumbrado deben liquidarse en el
        MISMO suministro."""
        usuario_id = request.query_params.get('usuario')
        qs = (LiquidacionSuministro.objects
              .select_related('tipo_trabajo')
              .prefetch_related('partidas__mano_de_obra'))
        if usuario_id:
            qs = qs.filter(usuario_id=usuario_id)

        # Actividad por tipo de trabajo (más confiable que el registro SST).
        act_por_tipo = {}
        for att in ActividadTipoTrabajo.objects.select_related('actividad'):
            act_por_tipo.setdefault(att.tipo_trabajo_id, att.actividad.nombre)

        fecha_por_sst = {}
        for sst in SST.objects.all():
            clave = sst.codigo or sst.sst
            if clave:
                fecha_por_sst[clave] = str(sst.fecha_ejecucion) if sst.fecha_ejecucion else ''

        def sst_de(liq):
            if liq.sst_externo:
                return liq.sst_externo
            if liq.suministro_id:
                rel = (SSTSuministro.objects.filter(suministro_id=liq.suministro_id)
                       .select_related('sst').first())
                if rel:
                    return rel.sst.codigo or rel.sst.sst
            return ''

        def sum_de(liq):
            return liq.suministro_externo or (f'id{liq.suministro_id}' if liq.suministro_id else '(s/n)')

        # 1) Agrupar por poste (sst, suministro): partidas + actividad.
        postes = {}
        for liq in qs:
            g = postes.setdefault((sst_de(liq), sum_de(liq)), {'act': '', 'partidas': {}})
            act = act_por_tipo.get(liq.tipo_trabajo_id, '')
            if act and (_norm_txt(act) in INCLUSIONES_CONSOLIDADO or not g['act']):
                g['act'] = act
            for lp in liq.partidas.all():
                mo = lp.mano_de_obra
                e = g['partidas'].setdefault(mo.partida, {'mo': mo, 'cantidad': Decimal('0')})
                e['cantidad'] += lp.cantidad

        # 2) Descuento POR POSTE, agregado por SST.
        ssts = {}
        _mo_cache = {}
        for (sst_cod, _sum), g in postes.items():
            regla = INCLUSIONES_CONSOLIDADO.get(_norm_txt(g['act']))
            num = Decimal('0')
            if regla:
                for pc in regla['paquete']:
                    if pc in g['partidas']:
                        num += g['partidas'][pc]['cantidad']
            agg = ssts.setdefault(sst_cod, {'act': g['act'], 'cambios': Decimal('0'), 'partidas': {}})
            if regla:
                agg['act'] = g['act']
            agg['cambios'] += num
            for pc, info in g['partidas'].items():
                real = info['cantidad']
                incl = Decimal('0')
                cfg = regla['incluidos'].get(pc) if regla else None
                if cfg is not None:
                    if isinstance(cfg, dict):
                        # 'segun' puede ser una partida o varias que suman.
                        segun = cfg['segun']
                        claves = segun if isinstance(segun, (list, tuple)) else [segun]
                        base = sum(
                            (g['partidas'].get(k, {}).get('cantidad', Decimal('0'))
                             for k in claves),
                            Decimal('0'))
                        incl = base * Decimal(cfg['cantidad'])
                    else:
                        incl = num * Decimal(cfg)
                cobra = real - incl
                if cobra < 0:
                    cobra = Decimal('0')
                pe = agg['partidas'].setdefault(pc, {'mo': info['mo'], 'real': Decimal('0'),
                                                     'incl': Decimal('0'), 'cobra': Decimal('0')})
                pe['real'] += real
                pe['incl'] += incl
                pe['cobra'] += cobra

            # Grupos con cantidad compartida: el paquete incluye N unidades
            # repartidas entre varias partidas, no N de cada una.
            for grupo in (regla.get('incluidos_grupo') if regla else None) or []:
                bolsa = num * Decimal(grupo['cantidad'])
                for pc in grupo['partidas']:
                    if bolsa <= 0:
                        break
                    info = g['partidas'].get(pc)
                    if info is None:
                        continue
                    pe = agg['partidas'][pc]
                    incl = min(info['cantidad'], bolsa)
                    bolsa -= incl
                    pe['incl'] += incl
                    pe['cobra'] -= incl
                    if pe['cobra'] < 0:
                        pe['cobra'] = Decimal('0')

            # Derivación: excedente de acarreo (*090633 ÷ 6) → traslado manual (*090634).
            deriv = regla.get('derivar') if regla else None
            if deriv and deriv['origen'] in g['partidas']:
                metrado = g['partidas'][deriv['origen']]['cantidad']
                q = metrado / deriv['divisor']
                umbral = num * Decimal(deriv['umbral']) if num > 0 else Decimal('0')
                cobra_d = q - umbral
                if cobra_d < 0:
                    cobra_d = Decimal('0')
                if deriv['destino'] not in _mo_cache:
                    _mo_cache[deriv['destino']] = ManoDeObra.objects.filter(
                        partida=deriv['destino']).first()
                mo_d = _mo_cache[deriv['destino']]
                if mo_d is not None:
                    pe = agg['partidas'].setdefault(deriv['destino'],
                        {'mo': mo_d, 'real': Decimal('0'), 'incl': Decimal('0'),
                         'cobra': Decimal('0')})
                    pe['real'] += q
                    pe['incl'] += umbral
                    pe['cobra'] += cobra_d

        # 3) Salida por SST.
        resultado = []
        for sst_cod, agg in ssts.items():
            items = []
            total = Decimal('0')
            for pc, pe in sorted(agg['partidas'].items()):
                mo = pe['mo']
                monto = pe['cobra'] * mo.precio
                total += monto
                items.append({
                    'partida': pc, 'descripcion': mo.descripcion, 'precio': str(mo.precio),
                    'cantidad_real': str(pe['real']), 'cantidad_incluida': str(pe['incl']),
                    'cantidad_cobrada': str(pe['cobra']), 'monto': str(monto),
                })
            resultado.append({
                'sst': sst_cod, 'actividad': agg['act'],
                'fecha': fecha_por_sst.get(sst_cod, ''),
                'cambios_poste': str(agg['cambios']),
                'total': str(total), 'partidas': items,
            })
        resultado.sort(key=lambda r: (r['fecha'] == '', r['fecha'], r['sst']))
        return Response(resultado)

    @action(detail=False, methods=['get'])
    def semana_trabajo(self, request):
        """
        GET /api/liquidaciones/semana_trabajo/?usuario=<id>

        Retorna TODOS los suministros ASIGNADOS pendientes de liquidar del
        proyecto Render (sin filtro de semana) que tengan ejecutado_por =
        nombre del usuario local. Agrupa por día de programación e incluye los
        TipoTrabajo disponibles según la Actividad de cada suministro.
        """
        usuario_id = request.query_params.get('usuario')
        if not usuario_id:
            return Response({'detail': 'Parámetro usuario requerido.'}, status=400)

        try:
            usuario = Usuario.objects.get(pk=usuario_id)
        except Usuario.DoesNotExist:
            return Response({'detail': 'Usuario no encontrado.'}, status=404)

        # Mapa actividad_nombre → lista de TipoTrabajo (local)
        atts = (ActividadTipoTrabajo.objects
                .select_related('actividad', 'tipo_trabajo')
                .prefetch_related('tipo_trabajo__partidas__mano_de_obra',
                                  'tipo_trabajo__materiales__material'))
        actividad_map = {}
        for att in atts:
            nombre = att.actividad.nombre
            if nombre not in actividad_map:
                actividad_map[nombre] = []
            actividad_map[nombre].append(att.tipo_trabajo)

        # Todos los suministros ASIGNADOS pendientes de liquidar (sin filtro de semana)
        suministros = _suministros_asignados_usuario(usuario)

        # Agrupar por día
        dias = {}
        for s in suministros:
            fecha_str = s.get('fecha_programada') or ''
            if fecha_str not in dias:
                dias[fecha_str] = []

            # Enriquecer con tipos de trabajo según actividad
            actividad_data  = s.get('actividad') or {}
            actividad_nombre = actividad_data.get('nombre_actividad', '')
            tipos_trabajo = []
            for tt in actividad_map.get(actividad_nombre, []):
                tipos_trabajo.append({
                    'id_tipo_trabajo': tt.id_tipo_trabajo,
                    'nombre':          tt.nombre,
                    'partidas': [
                        {
                            'id_mano_de_obra': p.mano_de_obra.id_mano_de_obra,
                            'partida':         p.mano_de_obra.partida,
                            'descripcion':     p.mano_de_obra.descripcion,
                            'precio':          str(p.mano_de_obra.precio),
                        }
                        for p in tt.partidas.all()
                    ],
                    'materiales': [
                        {
                            'id_material': m.material.id_material,
                            'matricula':   m.material.matricula,
                            'descripcion': m.material.descripcion,
                        }
                        for m in tt.materiales.all()
                    ],
                })

            dias[fecha_str].append({**s, 'tipos_trabajo_disponibles': tipos_trabajo})

        # Convertir a lista ordenada por fecha
        resultado = [
            {'fecha': fecha, 'suministros': items}
            for fecha, items in sorted(dias.items())
        ]
        # Rango real que abarcan los pendientes (para el encabezado de la app)
        fechas = [s.get('fecha_programada') for s in suministros if s.get('fecha_programada')]
        hoy    = str(datetime.date.today())
        return Response({
            'semana':    {'desde': min(fechas) if fechas else hoy,
                          'hasta': max(fechas) if fechas else hoy},
            'usuario':   {'id': usuario.id_usuario, 'nombre': usuario.nombre},
            'dias':      resultado,
        })


# ── PlanoSST ─────────────────────────────────────────────────────────────────
class PlanoSSTViewSet(viewsets.ModelViewSet):
    """Plano/croquis editable por SST.

    - POST   /api/planos/                  → upsert por (empresa, sst_codigo)
    - GET    /api/planos/?sst_codigo=XXX   → plano de ese SST (o elementos vacíos)
    - GET    /api/planos/semana_sst/?usuario=<id>
                                           → SSTs de la semana agrupados por fecha
    """
    serializer_class   = PlanoSSTSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = qs_empresa(PlanoSST.objects.select_related('empresa', 'usuario'), self.request)
        sst_codigo = self.request.query_params.get('sst_codigo')
        if sst_codigo:
            qs = qs.filter(sst_codigo=sst_codigo)
        return qs

    def _empresa_del_request(self):
        usuario = Usuario.objects.get(pk=self.request.user.id_usuario)
        return usuario.empresa_id

    def create(self, request, *args, **kwargs):
        """Upsert: si ya existe el plano de ese SST en la empresa, lo actualiza."""
        empresa_id = self._empresa_del_request()
        sst_codigo = request.data.get('sst_codigo')
        if not sst_codigo:
            return Response({'detail': 'sst_codigo requerido.'}, status=400)
        if not empresa_id:
            return Response({'detail': 'El usuario no tiene empresa asignada.'}, status=400)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plano, _ = PlanoSST.objects.update_or_create(
            empresa_id=empresa_id,
            sst_codigo=sst_codigo,
            defaults={
                'usuario':   serializer.validated_data['usuario'],
                'elementos': serializer.validated_data.get('elementos', []),
            },
        )
        return Response(self.get_serializer(plano).data, status=200)

    @action(detail=False, methods=['get'])
    def semana_sst(self, request):
        """
        GET /api/planos/semana_sst/?usuario=<id>

        Lista los SSTs programados para el usuario en la semana actual
        (lunes–domingo), agrupados por fecha de programación y deduplicados por
        código de SST, marcando cuáles ya tienen plano.
        """
        usuario_id = request.query_params.get('usuario')
        if not usuario_id:
            return Response({'detail': 'Parámetro usuario requerido.'}, status=400)

        try:
            usuario = Usuario.objects.get(pk=usuario_id)
        except Usuario.DoesNotExist:
            return Response({'detail': 'Usuario no encontrado.'}, status=404)

        # Todas las SST asignadas pendientes (sin filtro de semana)
        suministros = _suministros_asignados_usuario(usuario)

        # Códigos de SST que ya tienen plano en la empresa del usuario
        con_plano = set(
            PlanoSST.objects
            .filter(empresa_id=usuario.empresa_id)
            .values_list('sst_codigo', flat=True)
        )

        # Agrupar por fecha y deduplicar SSTs dentro de cada día
        dias = {}
        vistos = {}  # fecha -> set(sst_codigo)
        for s in suministros:
            fecha_str  = s.get('fecha_programada') or ''
            sst_codigo = s.get('sst_codigo') or ''
            if not sst_codigo:
                continue
            vistos.setdefault(fecha_str, set())
            if sst_codigo in vistos[fecha_str]:
                continue
            vistos[fecha_str].add(sst_codigo)
            distrito  = (s.get('distrito')  or {}).get('nombre_distrito', '')
            actividad = (s.get('actividad') or {}).get('nombre_actividad', '')
            dias.setdefault(fecha_str, []).append({
                'sst_codigo': sst_codigo,
                'distrito':   distrito,
                'actividad':  actividad,
                'tiene_plano': sst_codigo in con_plano,
            })

        resultado = [
            {'fecha': fecha, 'ssts': items}
            for fecha, items in sorted(dias.items())
        ]
        fechas = [s.get('fecha_programada') for s in suministros if s.get('fecha_programada')]
        hoy    = str(datetime.date.today())
        return Response({
            'semana':  {'desde': min(fechas) if fechas else hoy,
                        'hasta': max(fechas) if fechas else hoy},
            'usuario': {'id': usuario.id_usuario, 'nombre': usuario.nombre},
            'dias':    resultado,
        })


# ── Configuración (Coordinador): Actividad / TipoTrabajo / relaciones ─────────
def _solo_coordinador(request):
    """True si el usuario autenticado puede asignar/configurar (Coordinador o SuperAdmin)."""
    actor = Usuario.objects.filter(pk=getattr(request.user, 'id_usuario', None)).first()
    return bool(actor and actor.puede_asignar_sst())


class ActividadViewSet(viewsets.ModelViewSet):
    serializer_class   = ActividadSerializer
    queryset           = Actividad.objects.all().order_by('nombre')
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        if not _solo_coordinador(request):
            return Response({'detail': 'Solo un Coordinador puede crear actividades.'}, status=403)
        return super().create(request, *args, **kwargs)


class ManoDeObraViewSet(viewsets.ModelViewSet):
    serializer_class   = ManoDeObraSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class   = CatalogoPagination

    def get_queryset(self):
        qs = ManoDeObra.objects.all().order_by('partida')
        q = self.request.query_params.get('q')
        if q:
            qs = qs.filter(descripcion__icontains=q) | qs.filter(partida__icontains=q)
        return qs


class TipoTrabajoViewSet(viewsets.ModelViewSet):
    serializer_class   = TipoTrabajoSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = (TipoTrabajo.objects
              .prefetch_related('partidas__mano_de_obra', 'materiales__material',
                                'actividades__actividad')
              .order_by('nombre'))
        actividad = self.request.query_params.get('actividad')
        if actividad:
            qs = qs.filter(actividades__actividad_id=actividad)
        return qs

    def create(self, request, *args, **kwargs):
        if not _solo_coordinador(request):
            return Response({'detail': 'Solo un Coordinador puede crear tipos de trabajo.'}, status=403)
        actividad_id = request.data.get('actividad')
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            tt = serializer.save()
            if actividad_id:
                ActividadTipoTrabajo.objects.get_or_create(
                    tipo_trabajo=tt, actividad_id=actividad_id)
        return Response(TipoTrabajoSerializer(tt).data, status=201)

    @action(detail=True, methods=['post'])
    def set_actividades(self, request, pk=None):
        """POST /api/tipos-trabajo/<id>/set_actividades/  { ids: [id_actividad,...] }
        Reemplaza el conjunto de actividades asociadas a este tipo de trabajo."""
        if not _solo_coordinador(request):
            return Response({'detail': 'No autorizado.'}, status=403)
        tt = self.get_object()
        ids = request.data.get('ids', [])
        with transaction.atomic():
            ActividadTipoTrabajo.objects.filter(tipo_trabajo=tt).delete()
            for aid in ids:
                ActividadTipoTrabajo.objects.get_or_create(tipo_trabajo=tt, actividad_id=aid)
        return Response(TipoTrabajoSerializer(tt).data)

    @action(detail=True, methods=['post'])
    def set_mano_de_obra(self, request, pk=None):
        """POST /api/tipos-trabajo/<id>/set_mano_de_obra/  { ids: [id_mano_de_obra,...] }"""
        if not _solo_coordinador(request):
            return Response({'detail': 'No autorizado.'}, status=403)
        tt = self.get_object()
        ids = request.data.get('ids', [])
        with transaction.atomic():
            TipoTrabajoManoDeObra.objects.filter(tipo_trabajo=tt).delete()
            for mid in ids:
                TipoTrabajoManoDeObra.objects.get_or_create(tipo_trabajo=tt, mano_de_obra_id=mid)
        return Response(TipoTrabajoSerializer(tt).data)

    @action(detail=True, methods=['post'])
    def set_materiales(self, request, pk=None):
        """POST /api/tipos-trabajo/<id>/set_materiales/  { ids: [id_material,...] }"""
        if not _solo_coordinador(request):
            return Response({'detail': 'No autorizado.'}, status=403)
        tt = self.get_object()
        ids = request.data.get('ids', [])
        with transaction.atomic():
            TipoTrabajoMaterial.objects.filter(tipo_trabajo=tt).delete()
            for mid in ids:
                TipoTrabajoMaterial.objects.get_or_create(tipo_trabajo=tt, material_id=mid)
        return Response(TipoTrabajoSerializer(tt).data)
