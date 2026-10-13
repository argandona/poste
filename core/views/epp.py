"""EPP: catálogo, ingresos y pedidos."""
from .comun import *  # noqa: F401,F403
from .almacen import SoloAlmacen


# ── EPP ──────────────────────────────────────────────────────────────────────
class EPPViewSet(viewsets.ModelViewSet):
    """El catálogo de EPP. Lo ve cualquiera con sesión (para pedir); lo
    edita el almacén. No se borra: se desactiva."""
    serializer_class   = EPPSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class   = CatalogoPagination
    http_method_names  = ['get', 'post', 'put', 'patch', 'head', 'options']

    def get_queryset(self):
        actor = Usuario.objects.filter(pk=self.request.user.id_usuario).first()
        almacenes = Almacen.objects.filter(activo=True)
        if actor and not actor.es_superadmin() and actor.empresa_id:
            almacenes = almacenes.filter(empresa_id=actor.empresa_id)
        qs = EPP.objects.annotate(stock=models.functions.Coalesce(
            models.Sum('stocks__cantidad',
                       filter=models.Q(stocks__almacen__in=almacenes)),
            models.Value(Decimal('0')),
            output_field=models.DecimalField(max_digits=12, decimal_places=2)))
        if self.request.query_params.get('activos'):
            qs = qs.filter(activo=True)
        return qs.order_by('descripcion', 'id_epp')

    def _solo_almacen(self):
        actor = Usuario.objects.filter(pk=self.request.user.id_usuario).first()
        if not (actor and actor.puede_gestionar_almacen()):
            raise PermissionDenied('Solo el almacén edita el catálogo de EPP.')

    def perform_create(self, serializer):
        self._solo_almacen()
        serializer.save()

    def perform_update(self, serializer):
        self._solo_almacen()
        serializer.save()


class IngresoEPPViewSet(viewsets.ModelViewSet):
    """EPP que entra al almacén: suma al stock. Solo el almacén."""
    serializer_class   = IngresoEPPSerializer
    permission_classes = [permissions.IsAuthenticated, SoloAlmacen]
    http_method_names  = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return (IngresoEPP.objects.select_related('almacen', 'usuario')
                .prefetch_related('detalles__epp'))

    def perform_create(self, serializer):
        serializer.save(usuario=Usuario.objects.get(pk=self.request.user.id_usuario))


# ── Pedidos de EPP ───────────────────────────────────────────────────────────


class PedidoEPPViewSet(viewsets.ViewSet):
    """Pedidos de EPP. Pide para sí el que sale a obra (operario, ayudante,
    capataz, encargado); el cambio exige foto. Aprueba o rechaza solo el
    almacén (encargado de almacén o SuperAdmin), y al aprobar se descuenta
    del stock del almacén. Cada lado recibe su aviso."""
    permission_classes = [permissions.IsAuthenticated]

    @staticmethod
    def _actor(request):
        return Usuario.objects.filter(pk=request.user.id_usuario).first()

    @staticmethod
    def _con_todo(qs):
        return (qs.select_related('usuario', 'almacen', 'usuario_aprueba')
                .prefetch_related('detalles__epp')
                .defer('foto'))

    @staticmethod
    def _datos(p):
        return {
            'id_pedido_epp': p.pk,
            'usuario': p.usuario_id,
            'usuario_nombre': p.usuario.nombre,
            'usuario_dni': p.usuario.dni,
            'tipo': p.tipo,
            'estado': p.estado,
            'motivo': p.motivo,
            'observacion': p.observacion,
            'tiene_foto': bool(p.foto_tipo),
            'foto_url': url_foto(p.foto_archivo),
            'origen': p.origen,
            'fecha': p.fecha,
            'almacen': p.almacen_id,
            'almacen_nombre': p.almacen.nombre if p.almacen_id else '',
            'usuario_aprueba_nombre': (p.usuario_aprueba.nombre
                                       if p.usuario_aprueba_id else ''),
            'fecha_aprobacion': p.fecha_aprobacion,
            'observacion_aprobacion': p.observacion_aprobacion,
            'detalles': [{
                'epp': d.epp_id,
                'codigo': d.epp.codigo,
                'descripcion': d.epp.descripcion,
                'talla': d.epp.talla,
                'unidad': d.epp.unidad,
                'cantidad_solicitada': d.cantidad_solicitada,
                'cantidad_aprobada': d.cantidad_aprobada,
            } for d in p.detalles.all()],
        }

    def _visibles(self, actor):
        qs = PedidoEPP.objects.all()
        if actor.puede_gestionar_almacen():
            if not actor.es_superadmin() and actor.empresa_id:
                qs = qs.filter(usuario__empresa_id=actor.empresa_id)
            return qs
        return qs.filter(usuario=actor)

    def list(self, request):
        """GET /api/pedidos-epp/?estado=pendiente

        El almacén ve los de su empresa; los demás, solo los suyos."""
        actor = self._actor(request)
        qs = self._con_todo(self._visibles(actor))
        estado = request.query_params.get('estado')
        if estado:
            qs = qs.filter(estado=estado)
        origen = request.query_params.get('origen')
        if origen:
            qs = qs.filter(origen=origen)
        return Response([self._datos(p) for p in qs[:300]])

    @action(detail=False, methods=['post'])
    def asignar(self, request):
        """POST /api/pedidos-epp/asignar/
        {usuario, tipo: nuevo|cambio, almacen?, observacion?,
         detalles: [{epp, cantidad}]}

        El SuperAdmin entrega EPP a un trabajador sin que lo pida: queda como
        una entrega aprobada (sale en Mis EPP y en el historial), se descuenta
        del almacén en el acto y al trabajador le llega el aviso."""
        actor = self._actor(request)
        if not actor.puede_asignar_epp():
            return Response({'detail': 'Solo el SuperAdmin asigna EPP.'}, status=403)
        usuario = Usuario.objects.filter(pk=request.data.get('usuario'),
                                         activo=True).first()
        if usuario is None:
            raise ErrorNegocio('Elige a quién se le entrega.')
        if not usuario.puede_pedir_epp():
            raise ErrorNegocio('Se entrega EPP a operarios, ayudantes, '
                               'capataces, encargados y choferes.')
        tipo = request.data.get('tipo') or PedidoEPP.TIPO_NUEVO
        if tipo not in (PedidoEPP.TIPO_NUEVO, PedidoEPP.TIPO_CAMBIO):
            raise ErrorNegocio('El tipo debe ser nuevo o cambio.')

        lineas = []
        for d in request.data.get('detalles') or []:
            epp = EPP.objects.filter(pk=d.get('epp'), activo=True).first()
            if epp is None:
                raise ErrorNegocio('Uno de los EPP no existe o está inactivo.')
            try:
                cantidad = Decimal(str(d.get('cantidad')).replace(',', '.'))
            except ArithmeticError:
                cantidad = None
            if cantidad is None or not cantidad.is_finite() or cantidad <= 0:
                raise ErrorNegocio(f'Cantidad inválida para {epp}.')
            lineas.append((epp, cantidad.quantize(Decimal('0.01'))))
        if not lineas:
            raise ErrorNegocio('Elige al menos un EPP.')

        almacenes = Almacen.objects.filter(activo=True)
        if not actor.es_superadmin() and actor.empresa_id:
            almacenes = almacenes.filter(empresa_id=actor.empresa_id)
        if request.data.get('almacen'):
            almacen = almacenes.filter(pk=request.data['almacen']).first()
        else:
            almacen = almacenes.first() if almacenes.count() == 1 else None
        if almacen is None:
            raise ErrorNegocio('Elige de qué almacén sale.')

        observacion = (request.data.get('observacion') or '').strip()
        with transaction.atomic():
            for epp, cantidad in lineas:
                stock = (StockEPP.objects.select_for_update()
                         .filter(almacen=almacen, epp=epp).first())
                hay = stock.cantidad if stock else Decimal('0')
                if hay < cantidad:
                    raise ErrorNegocio(
                        f'En {almacen.nombre} solo hay {hay} de {epp}.')
                stock.cantidad -= cantidad
                stock.save(update_fields=['cantidad'])
            ahora = timezone.now()
            pedido = PedidoEPP.objects.create(
                usuario=usuario, tipo=tipo, estado='aprobado',
                origen=PedidoEPP.ORIGEN_ASIGNACION, almacen=almacen,
                usuario_aprueba=actor, fecha_aprobacion=ahora,
                observacion_aprobacion=observacion)
            for epp, cantidad in lineas:
                DetallePedidoEPP.objects.create(
                    pedido=pedido, epp=epp, cantidad_solicitada=cantidad,
                    cantidad_aprobada=cantidad)

        if usuario.fcm_token:
            from ..fcm import send_notification
            send_notification(
                [usuario.fcm_token],
                title='Te asignaron EPP',
                body=', '.join(f'{c.normalize():f} {e}' for e, c in lineas)
                     + '. Recógelo en el almacén.',
                data={'tipo': 'epp_asignado', 'pedido_id': str(pedido.pk)})
        pedido = self._con_todo(PedidoEPP.objects).get(pk=pedido.pk)
        return Response(self._datos(pedido), status=201)

    def create(self, request):
        """POST /api/pedidos-epp/
        {tipo, motivo?, observacion?, foto? (jpeg en base64),
         detalles: [{epp, cantidad}]}"""
        actor = self._actor(request)
        if not actor.puede_pedir_epp():
            return Response({'detail': 'Tu rol no pide EPP.'}, status=403)
        tipo = request.data.get('tipo')
        if tipo not in (PedidoEPP.TIPO_NUEVO, PedidoEPP.TIPO_CAMBIO):
            raise ErrorNegocio('El tipo debe ser nuevo o cambio.')

        lineas = []
        for d in request.data.get('detalles') or []:
            epp = EPP.objects.filter(pk=d.get('epp'), activo=True).first()
            if epp is None:
                raise ErrorNegocio('Uno de los EPP no existe o está inactivo.')
            try:
                cantidad = Decimal(str(d.get('cantidad')).replace(',', '.'))
            except ArithmeticError:
                cantidad = None
            if cantidad is None or not cantidad.is_finite() or cantidad <= 0:
                raise ErrorNegocio(f'Cantidad inválida para {epp}.')
            lineas.append((epp, cantidad.quantize(Decimal('0.01'))))
        if not lineas:
            raise ErrorNegocio('Elige al menos un EPP.')

        foto = leer_base64(request.data.get('foto'))
        motivo = (request.data.get('motivo') or '').strip()
        if tipo == PedidoEPP.TIPO_CAMBIO:
            if not foto:
                raise ErrorNegocio('Para un cambio hay que tomar la foto del EPP malogrado.')
            if not motivo:
                raise ErrorNegocio('Escribe por qué se cambia.')

        # Se sube antes de abrir la transacción: no se espera a Cloudinary
        # con la base bloqueada.
        archivo = guardar_foto(foto, 'epp') if foto else ''
        with transaction.atomic():
            pedido = PedidoEPP.objects.create(
                usuario=actor, tipo=tipo, motivo=motivo,
                observacion=(request.data.get('observacion') or '').strip(),
                foto_archivo=archivo, foto_tipo='image/jpeg' if foto else '')
            for epp, cantidad in lineas:
                DetallePedidoEPP.objects.create(
                    pedido=pedido, epp=epp, cantidad_solicitada=cantidad)

        from ..fcm import send_notification
        tokens = list(
            Usuario.objects.filter(con_rol(*ROLES_QUE_APRUEBAN),
                                   empresa_id=actor.empresa_id, activo=True)
            .exclude(fcm_token__isnull=True).exclude(fcm_token='')
            .values_list('fcm_token', flat=True))
        send_notification(
            tokens,
            title=('Cambio de EPP por aprobar' if tipo == PedidoEPP.TIPO_CAMBIO
                   else 'Pedido de EPP por aprobar'),
            body=f'{actor.nombre} pidió ' + ', '.join(
                f'{c.normalize():f} {e}' for e, c in lineas) + '.',
            data={'tipo': 'pedido_epp_nuevo', 'pedido_id': str(pedido.pk)},
        )
        pedido = self._con_todo(PedidoEPP.objects).get(pk=pedido.pk)
        return Response(self._datos(pedido), status=201)

    @action(detail=True, methods=['get'])
    def foto(self, request, pk=None):
        """GET /api/pedidos-epp/{id}/foto/ — la evidencia del cambio."""
        from django.http import HttpResponse
        actor = self._actor(request)
        pedido = self._visibles(actor).filter(pk=pk).first()
        if pedido is not None and pedido.foto_archivo:
            return responder_foto(pedido.foto_archivo)
        # Las de antes de mover_fotos siguen en la base.
        if pedido is None or not pedido.foto:
            return Response({'detail': 'Sin foto.'}, status=404)
        return HttpResponse(bytes(pedido.foto),
                            content_type=pedido.foto_tipo or 'image/jpeg')

    @action(detail=True, methods=['post'])
    def aprobar(self, request, pk=None):
        """POST /api/pedidos-epp/{id}/aprobar/
        {accion: aprobar|rechazar, almacen?, observacion?,
         detalles?: [{epp, cantidad_aprobada}]}

        Sin detalles se aprueba lo pedido. Aprobar descuenta del almacén."""
        actor = self._actor(request)
        if not actor.puede_gestionar_almacen():
            return Response({'detail': 'Solo el almacén aprueba EPP.'}, status=403)
        accion = request.data.get('accion')
        if accion not in ('aprobar', 'rechazar'):
            raise ErrorNegocio('La acción debe ser aprobar o rechazar.')
        observacion = (request.data.get('observacion') or '').strip()

        with transaction.atomic():
            pedido = (self._visibles(actor).select_for_update(of=('self',))
                      .filter(pk=pk).first())
            if pedido is None:
                return Response({'detail': 'No existe.'}, status=404)
            if pedido.estado != 'pendiente':
                raise ErrorNegocio(f'El pedido ya está {pedido.estado}.')
            if accion == 'aprobar':
                almacenes = Almacen.objects.filter(activo=True)
                if not actor.es_superadmin() and actor.empresa_id:
                    almacenes = almacenes.filter(empresa_id=actor.empresa_id)
                if request.data.get('almacen'):
                    almacen = almacenes.filter(pk=request.data['almacen']).first()
                else:
                    almacen = almacenes.first() if almacenes.count() == 1 else None
                if almacen is None:
                    raise ErrorNegocio('Elige de qué almacén sale.')
                aprobadas = {}
                for d in request.data.get('detalles') or []:
                    try:
                        aprobadas[int(d.get('epp'))] = Decimal(
                            str(d.get('cantidad_aprobada')).replace(',', '.'))
                    except (ArithmeticError, TypeError, ValueError):
                        raise ErrorNegocio('Cantidad aprobada inválida.')
                for det in pedido.detalles.select_related('epp'):
                    cantidad = aprobadas.get(det.epp_id, det.cantidad_solicitada)
                    if not cantidad.is_finite() or cantidad < 0:
                        raise ErrorNegocio(f'Cantidad aprobada inválida para {det.epp}.')
                    cantidad = cantidad.quantize(Decimal('0.01'))
                    if cantidad > 0:
                        stock = (StockEPP.objects.select_for_update()
                                 .filter(almacen=almacen, epp=det.epp).first())
                        hay = stock.cantidad if stock else Decimal('0')
                        if hay < cantidad:
                            raise ErrorNegocio(
                                f'En {almacen.nombre} solo hay {hay} de {det.epp}.')
                        stock.cantidad -= cantidad
                        stock.save(update_fields=['cantidad'])
                    det.cantidad_aprobada = cantidad
                    det.save(update_fields=['cantidad_aprobada'])
                pedido.almacen = almacen
            pedido.estado = 'aprobado' if accion == 'aprobar' else 'rechazado'
            pedido.usuario_aprueba = actor
            pedido.fecha_aprobacion = timezone.now()
            pedido.observacion_aprobacion = observacion
            pedido.save(update_fields=['estado', 'almacen', 'usuario_aprueba',
                                       'fecha_aprobacion',
                                       'observacion_aprobacion'])

        if pedido.usuario.fcm_token:
            from ..fcm import send_notification
            aprobado = pedido.estado == 'aprobado'
            send_notification(
                [pedido.usuario.fcm_token],
                title='Pedido de EPP aprobado' if aprobado else 'Pedido de EPP rechazado',
                body=('Recoge tu EPP en el almacén.' if aprobado
                      else f'Tu pedido de EPP fue rechazado. {observacion}'.strip()),
                data={'tipo': 'pedido_epp_aprobado' if aprobado
                      else 'pedido_epp_rechazado',
                      'pedido_id': str(pedido.pk)},
            )
        pedido = self._con_todo(PedidoEPP.objects).get(pk=pedido.pk)
        return Response(self._datos(pedido))

    def _historial(self, request):
        actor = self._actor(request)
        if not actor.puede_ver_historial_epp():
            raise PermissionDenied('Solo el almacén, el SuperAdmin y el Coordinador ven el historial.')
        from ..historial_epp import armar_historial
        return armar_historial(
            None if actor.es_superadmin() else actor.empresa_id)

    @action(detail=False, methods=['get'])
    def historial(self, request):
        """GET /api/pedidos-epp/historial/

        Lo entregado a cada trabajador: una fila por trabajador y EPP, con la
        fecha de cada entrega y los días que le duró."""
        filas = self._historial(request)
        return Response({
            'columnas': max((len(f['entregas']) for f in filas), default=0),
            'filas': filas,
        })

    @action(detail=False, methods=['get'])
    def historial_excel(self, request):
        """GET /api/pedidos-epp/historial_excel/ — la misma matriz en Excel."""
        from django.http import HttpResponse
        from ..historial_epp import excel_historial
        contenido = excel_historial(self._historial(request))
        resp = HttpResponse(
            contenido,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = (
            f'attachment; filename="historial_epp_{timezone.localdate():%Y%m%d}.xlsx"')
        return resp

    @action(detail=False, methods=['get'])
    def mis_epp(self, request):
        """GET /api/pedidos-epp/mis_epp/?usuario=<id>

        Lo que se le entregó a un usuario: cada EPP con su última entrega y
        el total recibido. ?usuario solo lo usa el almacén."""
        actor = self._actor(request)
        usuario = actor
        if request.query_params.get('usuario') and actor.puede_gestionar_almacen():
            usuario = Usuario.objects.filter(
                pk=request.query_params['usuario']).first() or actor
        detalles = (DetallePedidoEPP.objects
                    .filter(pedido__usuario=usuario, pedido__estado='aprobado',
                            cantidad_aprobada__gt=0)
                    .select_related('epp', 'pedido')
                    .order_by('-pedido__fecha_aprobacion'))
        por_epp = {}
        for d in detalles:
            fila = por_epp.setdefault(d.epp_id, {
                'epp': d.epp_id, 'codigo': d.epp.codigo,
                'descripcion': d.epp.descripcion, 'talla': d.epp.talla,
                'unidad': d.epp.unidad, 'total': Decimal('0'),
                'ultima_entrega': d.pedido.fecha_aprobacion,
                'cambios': 0,
            })
            fila['total'] += d.cantidad_aprobada
            if d.pedido.tipo == PedidoEPP.TIPO_CAMBIO:
                fila['cambios'] += 1
        return Response({'usuario': usuario.pk, 'usuario_nombre': usuario.nombre,
                         'epp': list(por_epp.values())})
