"""Almacén: materiales, stock, ingresos, pedidos, devoluciones, inventarios y asignación de agregados."""
from .comun import *  # noqa: F401,F403


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


# ── Almacen ──────────────────────────────────────────────────────────────────
class AlmacenViewSet(viewsets.ModelViewSet):
    serializer_class   = AlmacenSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return qs_empresa(Almacen.objects.select_related('empresa'), self.request)


# ── StockAlmacen ─────────────────────────────────────────────────────────────
class StockAlmacenViewSet(viewsets.ReadOnlyModelViewSet):
    # Solo lectura: el stock del almacén cambia con ingresos, despachos y
    # devoluciones aprobadas, que dejan registro.
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
        qs = (IngresoTecsur.objects.prefetch_related('detalles__material')
              .select_related('almacen', 'proveedor', 'usuario')
              .order_by('-fecha', '-id_ingreso'))
        return qs_empresa(qs, self.request, campo='almacen__empresa')

    def create(self, request, *args, **kwargs):
        """Solo quien gestiona el almacén registra lo que entra. El ingreso va
        a nombre de quien tiene la sesión, no de quien diga el cuerpo."""
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        if not actor or not actor.puede_gestionar_almacen():
            return Response(
                {'detail': 'Solo el encargado de almacén puede registrar ingresos.'},
                status=403)
        datos = request.data.copy()
        datos['usuario'] = actor.pk
        serializer = IngresoTecsurCreateSerializer(data=datos)
        serializer.is_valid(raise_exception=True)
        ingreso = serializer.save()
        return Response(IngresoTecsurSerializer(ingreso).data, status=201)

    @action(detail=False, methods=['post'])
    def leer_excel(self, request):
        """POST /api/ingresos-tecsur/leer_excel/  { archivo: <xlsx en base64> }

        Lee un Excel de ingreso y devuelve sus líneas para revisarlas en la
        app antes de registrar: no toca el stock. Busca las columnas por su
        título (matrícula y cantidad); sin títulos, toma la A y la B. Una
        matrícula repetida se suma. Avisa de las que no están en el catálogo y
        de las filas sin una cantidad válida."""
        import base64
        import io

        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        if not actor or not actor.puede_gestionar_almacen():
            return Response(
                {'detail': 'Solo el encargado de almacén puede registrar ingresos.'},
                status=403)
        try:
            contenido = base64.b64decode(request.data.get('archivo') or '',
                                         validate=True)
            libro = openpyxl.load_workbook(io.BytesIO(contenido),
                                           read_only=True, data_only=True)
        except Exception as exc:  # base64 roto, .xls viejo, zip o xml inválido
            raise ErrorNegocio(
                'No se pudo leer el archivo: tiene que ser un Excel .xlsx.') from exc
        filas = list(libro.worksheets[0].iter_rows(values_only=True))
        return Response(lineas_de_ingreso(filas))

    @action(detail=False, methods=['get'])
    def plantilla_excel(self, request):
        """GET /api/ingresos-tecsur/plantilla_excel/ — el Excel en blanco con
        las columnas que lee leer_excel."""
        import io
        from django.http import HttpResponse

        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.title = 'Ingreso'
        hoja.append(['Matrícula', 'Descripción', 'Cantidad'])
        hoja.append(['1014213', 'FLEJE (3/4") (ejemplo, bórrala)', 2.5])
        for columna, ancho in (('A', 14), ('B', 50), ('C', 12)):
            hoja.column_dimensions[columna].width = ancho
        salida = io.BytesIO()
        libro.save(salida)
        resp = HttpResponse(
            salida.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = 'attachment; filename="plantilla_ingreso.xlsx"'
        return resp

    @action(detail=False, methods=['get'])
    def faltantes(self, request):
        """GET /api/ingresos-tecsur/faltantes/?almacen=<id>

        Lo que le falta al almacén para despachar los pedidos pendientes de los
        camiones de su empresa: por material, lo pedido, lo que hay y la
        diferencia. Solo los materiales que no alcanzan."""
        from django.db.models import Sum

        almacen = qs_empresa(Almacen.objects.all(), request).filter(
            pk=request.query_params.get('almacen')).first()
        if almacen is None:
            raise ErrorNegocio('Indica un almacén de tu empresa.')
        pedido = (DetallePedido.objects
                  .filter(pedido__estado='pendiente',
                          pedido__camion__empresa_id=almacen.empresa_id)
                  .values('material_id', 'material__matricula',
                          'material__descripcion')
                  .annotate(total=Sum('cantidad_solicitada'))
                  .order_by('material__matricula'))
        hay = dict(StockAlmacen.objects.filter(almacen=almacen)
                   .values_list('material_id', 'cantidad'))
        salida = []
        for fila in pedido:
            stock = hay.get(fila['material_id'], Decimal('0'))
            falta = fila['total'] - stock
            if falta > 0:
                salida.append({
                    'material': fila['material_id'],
                    'matricula': fila['material__matricula'],
                    'descripcion': fila['material__descripcion'],
                    'pedido': float(fila['total']),
                    'stock': float(stock),
                    'falta': float(falta),
                })
        return Response(salida)


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
        from ..fcm import send_notification
        pedido = serializer.save()
        empresa_id = pedido.usuario.empresa_id
        tokens = list(
            Usuario.objects.filter(con_rol(*ROLES_QUE_APRUEBAN), empresa_id=empresa_id, activo=True)
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
        return solo_propios(qs, self.request, 'puede_aprobar_pedido')

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
                from ..fcm import send_notification
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

        from ..fcm import send_notification
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
        from ..fcm import send_notification
        devolucion = serializer.save()
        empresa_id = devolucion.usuario.empresa_id
        tokens = list(
            Usuario.objects.filter(con_rol(*ROLES_QUE_APRUEBAN), empresa_id=empresa_id, activo=True)
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
        return solo_propios(qs, self.request, 'puede_aprobar_devolucion')

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
                from ..fcm import send_notification
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
        from ..fcm import send_notification
        token = devolucion.usuario.fcm_token
        if token:
            send_notification([token], title='Devolución aprobada',
                body=f'Tu devolución del camión {devolucion.camion.placa} fue aprobada.',
                data={'tipo': 'devolucion_aprobada', 'devolucion_id': str(devolucion.pk)})
        return Response(DevolucionSerializer(devolucion).data)


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
                        # update() no pasa por save(): la diferencia se
                        # recalcula aquí o queda la del teórico viejo.
                        existente.detalles.filter(material_id=sc.material_id).update(
                            cantidad_teorica=sc.cantidad,
                            diferencia=models.F('cantidad_fisica') - sc.cantidad)
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
                except DetalleInventario.DoesNotExist:
                    continue
                if d.get('cantidad_fisica') is None:
                    continue
                # Como texto: un 2.5 que llega como float no se resta con el
                # teórico, que es Decimal.
                try:
                    fisica = Decimal(str(d['cantidad_fisica']).replace(',', '.'))
                except ArithmeticError:
                    fisica = None
                if fisica is None or not fisica.is_finite() or fisica < 0:
                    raise ErrorNegocio(
                        f'Cantidad inválida para {det.material.matricula}: '
                        f'{d["cantidad_fisica"]}.')
                det.cantidad_fisica = fisica.quantize(Decimal('0.01'))
                det.save()
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
            from ..fcm import send_notification

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
                        f'{d.material.matricula}: {fmt_cantidad(d.diferencia, signo=True)}'
                        for d in diffs[:5]
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
        from ..pdf_inventario import enviar_pdf_inventario
        encargado = asignacion.usuario if (inventario.camion_id and asignacion) else None
        enviar_pdf_inventario(inventario, encargado_camion=encargado)

        return Response({'detail': 'Inventario cerrado.'})

    @action(detail=True, methods=['get'])
    def descargar_pdf(self, request, pk=None):
        """GET /api/inventarios/{id}/descargar_pdf/ — retorna el PDF del acta."""
        from django.http import HttpResponse
        from ..pdf_inventario import generar_pdf_inventario
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


# ── Asignación de agregados ──────────────────────────────────────────────────
class SoloAlmacen(permissions.BasePermission):
    """El encargado de almacén y el SuperAdmin. Pedido del usuario el
    2026-10-02: el capataz y el encargado no registran agregados."""
    message = 'Solo el almacén asigna agregados.'

    def has_permission(self, request, view):
        id_usuario = getattr(request.user, 'id_usuario', None)
        actor = Usuario.objects.filter(pk=id_usuario).first() if id_usuario else None
        return bool(actor and actor.puede_gestionar_almacen())


class AsignacionAgregadoViewSet(viewsets.ViewSet):
    """Asignación de agregados y materiales: el cemento, o cualquier material
    con saldo, sale del almacén al camión sin pedido.

    Solo los registra el almacén, y sin aprobación: elige el camión y las
    bolsas se descuentan del almacén y se suman al camión en el acto. Si se
    equivocó, anula y las bolsas vuelven."""
    permission_classes = [permissions.IsAuthenticated, SoloAlmacen]

    @staticmethod
    def _actor(request):
        return (Usuario.objects.select_related('empresa')
                .filter(pk=request.user.id_usuario).first())

    @staticmethod
    def _datos(a):
        return {
            'id_asignacion': a.pk,
            'fecha': a.fecha,
            'material': a.material_id,
            'matricula': a.material.matricula,
            'descripcion': a.material.descripcion,
            'cantidad': a.cantidad,
            'camion': a.camion_id,
            'placa': a.camion.placa,
            'almacen': a.almacen_id,
            'almacen_nombre': a.almacen.nombre,
            'usuario': a.usuario_id,
            'usuario_nombre': a.usuario.nombre,
            'registrado_por_nombre': a.registrado_por.nombre,
            'origen': a.origen,
            'observacion': a.observacion,
            'anulada': a.anulada,
            'anulada_por_nombre': a.anulada_por.nombre if a.anulada_por_id else '',
        }

    @staticmethod
    def _almacenes(actor):
        qs = Almacen.objects.filter(activo=True).order_by('nombre')
        if not actor.es_superadmin() and actor.empresa_id:
            qs = qs.filter(empresa_id=actor.empresa_id)
        return qs

    @staticmethod
    def _responsables_vigentes():
        hoy = datetime.date.today()
        return (UsuarioCamion.objects
                .filter(activo=True, fecha_inicio__lte=hoy)
                .filter(models.Q(fecha_fin__isnull=True) | models.Q(fecha_fin__gte=hoy))
                .select_related('usuario', 'camion'))

    @staticmethod
    def _con_todo(qs):
        return qs.select_related('material', 'camion', 'almacen', 'usuario',
                                 'registrado_por', 'anulada_por')

    # Un rango más largo que esto se pide por partes: la lista no se pagina.
    DIAS_MAXIMOS = 370

    def list(self, request):
        """GET /api/asignaciones-agregado/?desde=AAAA-MM-DD&hasta=AAAA-MM-DD

        Las del rango, de los almacenes del actor (las dos fechas incluidas).
        Sin fechas, las de hoy; con ?dia=, las de ese día (lo que usaba la
        app antes)."""
        actor = self._actor(request)
        if actor is None:
            raise ErrorNegocio('Usuario no encontrado.')
        p = request.query_params
        hoy = str(timezone.localdate())
        try:
            desde = datetime.date.fromisoformat(p.get('desde') or p.get('dia') or hoy)
            hasta = datetime.date.fromisoformat(p.get('hasta') or p.get('dia') or str(desde))
        except ValueError:
            raise ErrorNegocio('Las fechas deben ser AAAA-MM-DD.')
        if hasta < desde:
            raise ErrorNegocio('La fecha final es anterior a la inicial.')
        if (hasta - desde).days > self.DIAS_MAXIMOS:
            raise ErrorNegocio('Elige un rango de un año como máximo.')
        qs = self._con_todo(AsignacionAgregado.objects.filter(
            fecha__date__gte=desde, fecha__date__lte=hasta,
            almacen__in=self._almacenes(actor)))
        return Response([self._datos(a) for a in qs])

    @action(detail=False, methods=['get'])
    def opciones(self, request):
        """GET /api/asignaciones-agregado/opciones/

        Lo que hace falta para el formulario: lo que se puede entregar, con su
        saldo en cada almacén, y los camiones con responsable. Se entregan los
        agregados (aunque estén en cero, para que se vea que falta) y cualquier
        material que tenga saldo en algún almacén."""
        actor = self._actor(request)
        if actor is None:
            raise ErrorNegocio('Usuario no encontrado.')
        almacenes = list(self._almacenes(actor))
        saldos = {
            (s.almacen_id, s.material_id): s.cantidad
            for s in StockAlmacen.objects.filter(
                almacen__in=almacenes, cantidad__gt=0)
        }
        con_saldo = {material_id for _a, material_id in saldos}
        # Los agregados primero, que son el uso diario; después lo demás.
        materiales = sorted(
            Material.objects.filter(Q(es_agregado=True) | Q(pk__in=con_saldo)),
            key=lambda m: (not m.es_agregado, m.descripcion))
        lista = [{
            'id_material': m.pk,
            'matricula': m.matricula,
            'descripcion': m.descripcion,
            'es_agregado': m.es_agregado,
            'saldos': {str(a.pk): saldos.get((a.pk, m.pk), Decimal('0'))
                       for a in almacenes},
        } for m in materiales]
        datos = {
            'almacenes': [{'id_almacen': a.pk, 'nombre': a.nombre}
                          for a in almacenes],
            'materiales': lista,
            # El nombre de antes, para las apps que todavía lo leen así.
            'agregados': lista,
        }
        vistos = set()
        camiones = []
        for r in self._responsables_vigentes().order_by('camion__placa'):
            if r.camion_id in vistos:
                continue
            if (not actor.es_superadmin()
                    and r.camion.empresa_id != actor.empresa_id):
                continue
            vistos.add(r.camion_id)
            camiones.append({'id_camion': r.camion_id,
                             'placa': r.camion.placa,
                             'usuario': r.usuario_id,
                             'usuario_nombre': r.usuario.nombre})
        datos['camiones'] = camiones
        return Response(datos)

    def create(self, request):
        """POST /api/asignaciones-agregado/
        Body: {material, cantidad, camion, almacen?, observacion?}"""
        actor = self._actor(request)

        material = Material.objects.filter(pk=request.data.get('material')).first()
        if material is None:
            raise ErrorNegocio('Elige el material.')
        try:
            cantidad = Decimal(str(request.data.get('cantidad')).replace(',', '.'))
        except ArithmeticError:
            cantidad = None
        if cantidad is None or not cantidad.is_finite() or cantidad <= 0:
            raise ErrorNegocio('La cantidad debe ser mayor que cero.')
        cantidad = cantidad.quantize(Decimal('0.01'))

        almacenes = self._almacenes(actor)
        if request.data.get('almacen'):
            almacen = almacenes.filter(pk=request.data.get('almacen')).first()
        else:
            almacen = almacenes.first() if almacenes.count() == 1 else None
        if almacen is None:
            raise ErrorNegocio('Elige de qué almacén salen.')

        camion = Camion.objects.filter(pk=request.data.get('camion')).first()
        if camion is None:
            raise ErrorNegocio('Elige el camión que las recibe.')
        responsable = (self._responsables_vigentes()
                       .filter(camion=camion).first())
        if responsable is None:
            raise ErrorNegocio(
                f'El camión {camion.placa} no tiene responsable.')
        usuario = responsable.usuario

        with transaction.atomic():
            stock = (StockAlmacen.objects.select_for_update()
                     .filter(almacen=almacen, material=material).first())
            if stock is None or stock.cantidad < cantidad:
                hay = stock.cantidad if stock else Decimal('0')
                raise ErrorNegocio(
                    f'En {almacen.nombre} solo hay {hay} de '
                    f'{material.descripcion}.')
            stock.descontar(cantidad)
            en_camion, _ = (StockCamion.objects.select_for_update()
                            .get_or_create(camion=camion, material=material,
                                           defaults={'cantidad': 0}))
            en_camion.agregar(cantidad)
            asignacion = AsignacionAgregado.objects.create(
                almacen=almacen, camion=camion, material=material,
                cantidad=cantidad, usuario=usuario, registrado_por=actor,
                origen=AsignacionAgregado.ORIGEN_ALMACEN,
                observacion=(request.data.get('observacion') or '').strip())

        # Al responsable del camión le llega el aviso de lo que se le cargó.
        if usuario.fcm_token:
            from ..fcm import send_notification
            send_notification(
                [usuario.fcm_token],
                title='Te asignaron material',
                body=(f'{cantidad.normalize():f} de {material.descripcion} '
                      f'a tu camión {camion.placa}.'),
                data={'tipo': 'material_asignado',
                      'asignacion_id': str(asignacion.pk)},
            )
        asignacion = self._con_todo(AsignacionAgregado.objects).get(pk=asignacion.pk)
        return Response(self._datos(asignacion), status=201)

    @action(detail=True, methods=['post'])
    def anular(self, request, pk=None):
        """POST /api/asignaciones-agregado/{id}/anular/

        Solo el almacén. Las bolsas vuelven del camión al almacén; si el camión
        ya las gastó, no se puede."""
        actor = self._actor(request)
        with transaction.atomic():
            asignacion = (AsignacionAgregado.objects.select_for_update()
                          .filter(pk=pk, almacen__in=self._almacenes(actor))
                          .first())
            if asignacion is None:
                return Response({'detail': 'No existe.'}, status=404)
            if asignacion.anulada:
                raise ErrorNegocio('Ya estaba anulada.')
            en_camion = (StockCamion.objects.select_for_update()
                         .filter(camion=asignacion.camion,
                                 material=asignacion.material).first())
            saldo = en_camion.cantidad if en_camion else Decimal('0')
            if saldo < asignacion.cantidad:
                raise ErrorNegocio(
                    f'El camión {asignacion.camion.placa} ya gastó parte: le '
                    f'quedan {saldo} y la asignación fue de '
                    f'{asignacion.cantidad}.')
            en_camion.descontar(asignacion.cantidad)
            en_almacen, _ = (StockAlmacen.objects.select_for_update()
                             .get_or_create(almacen=asignacion.almacen,
                                            material=asignacion.material,
                                            defaults={'cantidad': 0}))
            en_almacen.agregar(asignacion.cantidad)
            asignacion.anulada = True
            asignacion.anulada_por = actor
            asignacion.fecha_anulacion = timezone.now()
            asignacion.save(update_fields=['anulada', 'anulada_por',
                                           'fecha_anulacion'])
        asignacion = self._con_todo(AsignacionAgregado.objects).get(pk=asignacion.pk)
        return Response(self._datos(asignacion))
