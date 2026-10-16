"""Unidades de transporte: alta y baja, responsable (asignar, liberar, traspasar) y saldo del camión.
El kilometraje y el combustible están en core/camiones.py."""
from .comun import *  # noqa: F401,F403


# ── Camion ──────────────────────────────────────────────────────────────────
class CamionViewSet(viewsets.ModelViewSet):
    """Gestión de unidades de transporte. Las ve cualquiera con sesión (se
    eligen en pedidos y saldos); crearlas, modificarlas, eliminarlas y
    asignarlas es solo del SuperAdmin. Antes cualquiera con sesión podía."""
    serializer_class   = CamionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class   = CatalogoPagination

    def get_queryset(self):
        return qs_empresa(Camion.objects.select_related('empresa')
                          .order_by('-activo', 'placa'), self.request)

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        hoy = datetime.date.today()
        contexto['responsables'] = {
            r.camion_id: r for r in UsuarioCamion.objects
            .filter(activo=True, fecha_inicio__lte=hoy)
            .filter(models.Q(fecha_fin__isnull=True) | models.Q(fecha_fin__gte=hoy))
            .select_related('usuario')}
        return contexto

    def _solo_superadmin(self):
        actor = Usuario.objects.filter(pk=self.request.user.id_usuario).first()
        if not (actor and actor.puede_gestionar_unidades()):
            raise PermissionDenied('Solo el SuperAdmin gestiona las unidades de transporte.')
        return actor

    def perform_create(self, serializer):
        actor = self._solo_superadmin()
        datos = {}
        if not serializer.validated_data.get('empresa'):
            if not actor.empresa_id:
                raise ErrorNegocio('Elige la empresa de la unidad.')
            datos['empresa_id'] = actor.empresa_id
        serializer.save(**datos)

    def perform_update(self, serializer):
        self._solo_superadmin()
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        """DELETE /api/camiones/{id}/

        Si la unidad nunca se usó, se borra. Si ya tiene historia (pedidos,
        stock, liquidaciones...), se da de baja: queda inactiva y no se puede
        asignar. Con responsable vigente no se toca: primero se libera o se
        traspasa."""
        from django.db.models.deletion import ProtectedError
        self._solo_superadmin()
        camion = self.get_object()
        if self.get_serializer_context()['responsables'].get(camion.pk):
            raise ErrorNegocio(
                f'{camion.placa} tiene responsable: primero libéralo o '
                'traspásalo en Responsables de Camión.')
        try:
            with transaction.atomic():
                camion.delete()
            return Response({'detail': f'Unidad {camion.placa} eliminada.',
                             'eliminada': True})
        except ProtectedError:
            camion.activo = False
            camion.save(update_fields=['activo'])
            return Response({
                'detail': f'{camion.placa} ya tiene movimientos: se dio de baja '
                          'y queda en el historial.',
                'eliminada': False})

    @action(detail=True, methods=['post'])
    def reactivar(self, request, pk=None):
        """POST /api/camiones/{id}/reactivar/ — deshace la baja."""
        self._solo_superadmin()
        camion = self.get_object()
        camion.activo = True
        camion.save(update_fields=['activo'])
        return Response(self.get_serializer(camion).data)

    @action(detail=True, methods=['post'])
    def asignar(self, request, pk=None):
        """POST /api/camiones/{id}/asignar/  {usuario}

        Asigna una unidad libre a un capataz o encargado. La asignación no
        vence: se cierra al liberar o traspasar, como siempre."""
        self._solo_superadmin()
        camion = self.get_object()
        if not camion.activo:
            raise ErrorNegocio(f'{camion.placa} está dada de baja.')
        usuario = Usuario.objects.filter(pk=request.data.get('usuario'),
                                         activo=True).first()
        if usuario is None:
            raise ErrorNegocio('Elige a quién se asigna.')
        if not (usuario.roles & {Rol.CAPATAZ, Rol.ENCARGADO}):
            raise ErrorNegocio('Solo se asigna a capataces y encargados.')
        asignacion = UsuarioCamion(camion=camion, usuario=usuario,
                                   fecha_inicio=datetime.date.today())
        try:
            asignacion.full_clean()
            asignacion.save()
        except DjangoValidationError as e:
            raise ErrorNegocio(' '.join(e.messages))
        if usuario.fcm_token:
            from ..fcm import send_notification
            send_notification(
                [usuario.fcm_token],
                title='Te asignaron una unidad',
                body=f'La unidad {camion.placa} está a tu nombre.',
                data={'tipo': 'unidad_asignada', 'camion_id': str(camion.pk)})
        return Response(self.get_serializer(camion).data, status=201)


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


# ── StockCamion ──────────────────────────────────────────────────────────────
class StockCamionViewSet(viewsets.ReadOnlyModelViewSet):
    # Solo lectura: el saldo del camión cambia únicamente con pedidos,
    # devoluciones, inventarios y liquidaciones, que dejan registro.
    serializer_class   = StockCamionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = StockCamion.objects.select_related('camion','material')
        camion_id = self.request.query_params.get('camion')
        if camion_id:
            qs = qs.filter(camion_id=camion_id)
        return qs

    @action(detail=False, methods=['get'])
    def matriz(self, request):
        """GET /api/stock-camion/matriz/?camion=<id> — Excel con cada
        movimiento del camión por material y el saldo que debería tener. Lo
        baja el almacén, el SuperAdmin o quien haya sido responsable del camión."""
        from django.http import HttpResponse
        from ..matriz_saldo import matriz_excel

        camion = Camion.objects.filter(pk=request.query_params.get('camion')).first()
        if camion is None:
            return Response({'detail': 'Elige el camión.'}, status=400)
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        fue_suyo = UsuarioCamion.objects.filter(camion=camion, usuario=actor).exists()
        if not (actor and (actor.puede_gestionar_almacen() or fue_suyo)):
            return Response({'detail': 'Solo el almacén o el responsable del camión.'},
                            status=403)
        r = HttpResponse(
            matriz_excel(camion),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        r['Content-Disposition'] = (
            f'attachment; filename="saldo_{camion.placa}_{datetime.date.today():%Y%m%d}.xlsx"')
        return r

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
