"""Liquidaciones: consumos, suministros, recuperos, liquidación y planos."""
from .comun import *  # noqa: F401,F403


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
        # En una obra de varios días, el recupero de un parte.
        fecha = request.query_params.get('fecha')
        if fecha:
            qs = qs.filter(fecha=fecha)
        usuario = request.query_params.get('usuario')
        if usuario:
            qs = qs.filter(usuario_id=usuario)
        return Response(SuministroRecuperoSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'])
    def formato_pdf(self, request):
        """GET /api/recuperos/formato_pdf/?sst=<codigo>

        El formato TS-REC-FR-001 de Tecsur, lleno con los recuperos de todos
        los postes de esa SST, sumados por material."""
        from django.http import HttpResponse

        from ..pdf_recupero import (
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
        # El reforzamiento no retira nada: el formato sale con la tabla vacía
        # y cruzado con "SIN RECUPERO".
        from ..cuaderno_reforzamiento import es_reforzamiento
        sin_recupero = es_reforzamiento(sst)

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
        if sin_recupero:
            items = []

        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        capataz = (Usuario.objects
                   .filter(con_rol(Rol.CAPATAZ, Rol.ENCARGADO),
                           sst_encargados__sst=sst)
                   .select_related('rol').first())
        if capataz is None:
            capataz = (Usuario.objects
                       .filter(suministros_asignados__sst=sst)
                       .select_related('rol').distinct().first())

        firma = nombre_de_firma(capataz.nombre if capataz else '')
        pdf = generar_pdf_recupero({
            'sst': sst.codigo or sst.sst,
            'fecha': fecha_larga(sst.fecha_ejecucion),
            # El área de Tecsur que recibe el recupero, no un lugar: siempre
            # Mantenimiento (pedido del usuario el 2026-09-29).
            'departamento': DEPARTAMENTO_DEL_RECUPERO,
            'contratista': sst.empresa.nombre if sst.empresa_id else '',
            'reportado_por': actor.nombre if actor else '',
            'capataz': capataz.nombre if capataz else '',
            'cargo': capataz.rol.descripcion if capataz else '',
            'firma': firma,
            'firma_pie': (
                f'Firmado electrónicamente desde la app · '
                f'{fecha_larga()} · usuario #{capataz.id_usuario}'
                if capataz else 'Sin capataz asignado'),
        }, items, sin_recupero=sin_recupero)

        resp = HttpResponse(pdf, content_type='application/pdf')
        nombre = f'recupero_{sst.codigo or sst.sst}.pdf'
        resp['Content-Disposition'] = f'attachment; filename="{nombre}"'
        return resp

    @action(detail=False, methods=['post'])
    def registrar(self, request):
        """POST /api/recuperos/registrar/ { suministro, fecha?, usuario?, items:[{recupero,cantidad}] }
        Reemplaza los recuperos del suministro por los enviados.

        En una obra de varios días reemplaza solo los del parte: los de ese
        día (`fecha`) y ese capataz (`usuario`, por defecto quien graba)."""
        from ..partes import (es_de_varios_dias, fecha_del_parte,
                              revisar_parte, sst_del_punto)

        suministro_id = request.data.get('suministro')
        items = request.data.get('items', [])
        if not suministro_id:
            return Response({'detail': 'suministro requerido.'}, status=400)
        sum_obj = Suministro.objects.filter(pk=suministro_id).first()
        if sum_obj is None:
            return Response({'detail': 'Suministro no encontrado.'}, status=404)
        fecha = fecha_del_parte(request.data.get('fecha'))
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        usuario = actor
        if request.data.get('usuario'):
            usuario = Usuario.objects.filter(pk=request.data['usuario']).first()
            if usuario is None:
                raise ErrorNegocio('Usuario no encontrado.')
        sst = sst_del_punto(sum_obj)
        reemplaza = SuministroRecupero.objects.filter(suministro=sum_obj)
        if es_de_varios_dias(sst):
            revisar_parte(actor, sst, usuario)
            reemplaza = reemplaza.filter(fecha=fecha, usuario=usuario)
        with transaction.atomic():
            reemplaza.delete()
            for it in items:
                cant = it.get('cantidad')
                rec = it.get('recupero')
                if rec and cant and float(cant) > 0:
                    SuministroRecupero.objects.create(
                        suministro=sum_obj, recupero_id=rec, cantidad=cant,
                        fecha=fecha, usuario=usuario)
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
        # El poste del proyecto externo no tiene id local: se pide por su
        # número, y con la SST si se sabe, porque el número puede repetirse.
        externo = self.request.query_params.get('suministro_externo')
        if externo:
            qs = qs.filter(suministro_externo=externo)
        sst = self.request.query_params.get('sst')
        if sst:
            qs = qs.filter(sst_externo=sst)
        # El parte de un día en una obra de varios días: el de ese día y ese
        # capataz es lo que la app vuelve a mostrar para corregirlo.
        fecha_parte = self.request.query_params.get('fecha_parte')
        if fecha_parte:
            qs = qs.filter(fecha_parte=fecha_parte)
        usuario = self.request.query_params.get('usuario')
        if usuario:
            qs = qs.filter(usuario_id=usuario)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = LiquidacionSuministroCreateSerializer(
            data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        liq = serializer.save()
        return Response(LiquidacionSuministroSerializer(liq).data, status=201)

    @action(detail=False, methods=['get'])
    def partidas_de_sst(self, request):
        """GET /api/liquidaciones/partidas_de_sst/?sst=<codigo>

        Las partidas que se cobran una vez por SST y que algún poste de esa
        SST ya liquidó, con el número del poste que las tiene. La app las
        muestra bloqueadas en los demás puntos de trabajo, para que el capataz
        vea que ya están cobradas y por quién."""
        from ..serializers import partidas_de_sst_ocupadas

        codigo = (request.query_params.get('sst') or '').strip()
        if not codigo:
            return Response({'detail': 'Se requiere el código de la SST.'},
                            status=400)
        suministro = None
        id_suministro = request.query_params.get('suministro')
        if id_suministro:
            suministro = Suministro.objects.filter(pk=id_suministro).first()
        externo = (request.query_params.get('suministro_externo') or '').strip()
        # En una obra de varios días se excluye solo el parte que se corrige.
        fecha_parte = request.query_params.get('fecha_parte') or None
        usuario = request.query_params.get('usuario') or None
        return Response(partidas_de_sst_ocupadas(
            codigo, suministro, externo, fecha_parte=fecha_parte,
            usuario=usuario))

    @action(detail=False, methods=['get'])
    def partes(self, request):
        """GET /api/liquidaciones/partes/?sst=<codigo>

        Los partes diarios de una obra de varios días: quién reportó qué día
        y en qué punto, y la suma de todo, que es la liquidación. También dice
        si la obra está terminada y qué puede hacer quien pregunta."""
        from ..partes import es_de_varios_dias

        codigo = (request.query_params.get('sst') or '').strip()
        if not codigo:
            raise ErrorNegocio('Se requiere el código de la SST.')
        sst = (qs_empresa(SST.objects.select_related(
                   'actividad', 'obra_terminada_por'), request)
               .filter(models.Q(codigo=codigo) | models.Q(sst=codigo))
               .first())
        if sst is None:
            raise ErrorNegocio(f'No existe la SST {codigo}.')
        if not es_de_varios_dias(sst):
            raise ErrorNegocio(f'La SST {codigo} no es una obra de varios días.')
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()

        postes = Suministro.objects.filter(sst_suministros__sst=sst)
        liquidaciones = (LiquidacionSuministro.objects
                         .filter(models.Q(suministro__in=postes) |
                                 models.Q(sst_externo=sst.codigo or sst.sst))
                         .select_related('usuario', 'suministro', 'tipo_trabajo')
                         .prefetch_related('partidas__mano_de_obra')
                         .order_by('-fecha_parte', 'usuario__nombre',
                                   'id_liquidacion'))
        partes, total = {}, {}
        for liq in liquidaciones:
            clave = (liq.fecha_parte, liq.usuario_id, liq.suministro_id)
            parte = partes.setdefault(clave, {
                'fecha': str(liq.fecha_parte) if liq.fecha_parte else '',
                'usuario': liq.usuario_id,
                'usuario_nombre': liq.usuario.nombre,
                'suministro': liq.suministro_id,
                'numero_suministro': (liq.suministro.numero_suministro
                                      if liq.suministro_id
                                      else liq.suministro_externo),
                'tipos': [],
            })
            parte['tipos'].append(liq.tipo_trabajo.nombre)
            for lp in liq.partidas.all():
                if lp.cantidad <= 0:
                    continue
                mo = lp.mano_de_obra
                fila = total.setdefault(mo.partida, {
                    'partida': mo.partida, 'descripcion': mo.descripcion,
                    'precio': mo.precio, 'cantidad': Decimal('0')})
                fila['cantidad'] += lp.cantidad
        filas = []
        for f in sorted(total.values(), key=lambda f: f['partida']):
            filas.append({**f, 'precio': str(f['precio']),
                          'cantidad': str(f['cantidad']),
                          'monto': str(f['cantidad'] * f['precio'])})
        terminada = sst.obra_terminada_el is not None
        return Response({
            'sst': sst.codigo or sst.sst,
            'actividad': sst.actividad.nombre,
            'terminada': terminada,
            'terminada_el': sst.obra_terminada_el,
            'terminada_por': (sst.obra_terminada_por.nombre
                              if sst.obra_terminada_por_id else ''),
            'puede_terminar': bool(actor and actor.puede_terminar_obra()),
            'corrige_todos': bool(actor and actor.puede_corregir_partes()),
            'partes': list(partes.values()),
            'total': filas,
        })

    @action(detail=False, methods=['get'])
    def correcciones(self, request):
        """GET /api/liquidaciones/correcciones/ — quién corrigió qué y cuándo.

        Se filtra por el mismo poste con que se piden las liquidaciones
        (suministro local, o número externo con su SST) y, si se quiere, por
        tipo de trabajo. Sin filtros devuelve las últimas correcciones de
        todos.

        Es un acta de auditoría: la ve el Coordinador y nadie más. El capataz
        no tiene por qué mirar quién le corrigió la liquidación."""
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        if not actor or not actor.puede_ver_correcciones():
            return Response(
                {'detail': 'Solo un Coordinador puede ver las correcciones.'},
                status=403)
        qs = (CorreccionLiquidacion.objects
              .select_related('suministro', 'usuario', 'usuario_anterior', 'tipo_trabajo'))
        suministro = request.query_params.get('suministro')
        if suministro:
            qs = qs.filter(suministro_id=suministro)
        externo = request.query_params.get('suministro_externo')
        if externo:
            qs = qs.filter(suministro_externo=externo)
        sst = request.query_params.get('sst')
        if sst:
            qs = qs.filter(sst_externo=sst)
        tipo = request.query_params.get('tipo_trabajo')
        if tipo:
            qs = qs.filter(tipo_trabajo_id=tipo)
        return Response(CorreccionLiquidacionSerializer(qs[:200], many=True).data)

    def _sst_liquidada(self, request):
        """La SST del parámetro ?sst=, con lo que se liquidó en ella. Sin
        liquidaciones no hay nada que documentar."""
        from ..cuaderno_obra import reunir

        codigo = (request.query_params.get('sst') or '').strip()
        if not codigo:
            raise ErrorNegocio('Se requiere el código de la SST.')
        qs = SST.objects.filter(models.Q(codigo=codigo) | models.Q(sst=codigo))
        empresa_id = getattr(request.user, 'empresa_id', None)
        if empresa_id:
            qs = qs.filter(empresa_id=empresa_id)
        sst = qs.select_related('empresa', 'actividad').first()
        if sst is None:
            raise ErrorNegocio(f'No existe la SST {codigo}.')
        datos = reunir(sst)
        if not (datos.materiales or datos.partidas):
            raise ErrorNegocio(f'La SST {codigo} todavía no tiene liquidación.')
        return sst, datos

    @action(detail=False, methods=['get'])
    def cuaderno_obra(self, request):
        """GET /api/liquidaciones/cuaderno_obra/?sst=<codigo>

        El cuaderno de obra de la SST en PDF, redactado con lo liquidado y lo
        dibujado en el plano. El número se le da la primera vez y se conserva."""
        from django.db import IntegrityError
        from django.http import HttpResponse

        from ..cuaderno_obra import generar_pdf_cuaderno, lineas_del_cuaderno
        from ..models import CuadernoObra

        sst, datos = self._sst_liquidada(request)
        codigo = sst.codigo or sst.sst

        # El reforzamiento de poste tiene su propio formato, de casillas.
        from ..cuaderno_reforzamiento import (
            es_reforzamiento, generar_pdf_reforzamiento, reunir_reforzamiento)
        if es_reforzamiento(sst):
            hojas = reunir_reforzamiento(sst)
            if not hojas:
                raise ErrorNegocio(
                    f'La SST {codigo} todavía no tiene reforzamiento liquidado.')
            resp = HttpResponse(generar_pdf_reforzamiento(hojas),
                                content_type='application/pdf')
            resp['Content-Disposition'] = (
                f'attachment; filename="cuaderno_obra_{codigo}.pdf"')
            return resp

        cuaderno = CuadernoObra.objects.filter(
            empresa_id=sst.empresa_id, sst_codigo=codigo).first()
        while cuaderno is None:
            ultimo = (CuadernoObra.objects.filter(empresa_id=sst.empresa_id)
                      .aggregate(n=models.Max('numero'))['n'] or 0)
            try:
                with transaction.atomic():
                    cuaderno = CuadernoObra.objects.create(
                        empresa_id=sst.empresa_id, sst_codigo=codigo,
                        numero=ultimo + 1)
            except IntegrityError:
                # Otro lo generó a la vez: se toma el suyo o el número siguiente.
                cuaderno = CuadernoObra.objects.filter(
                    empresa_id=sst.empresa_id, sst_codigo=codigo).first()

        pdf = generar_pdf_cuaderno({
            'numero': f'{cuaderno.numero:06d}',
            'sst': codigo,
            'direccion': sst.distrito,
            'distrito': sst.distrito,
            'fecha': sst.fecha_ejecucion.strftime('%d/%m/%Y') if sst.fecha_ejecucion else '',
            'hora': sst.hora_ejecucion.strftime('%H:%M') if sst.hora_ejecucion else '',
            'encargado': datos.capataz,
        }, lineas_del_cuaderno(datos))
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="cuaderno_obra_{codigo}.pdf"'
        return resp

    @action(detail=False, methods=['get'])
    def excel(self, request):
        """GET /api/liquidaciones/excel/?sst=<codigo>

        La liquidación de material y mano de obra de la SST en la plantilla
        Excel de Tecsur."""
        from django.http import HttpResponse

        from ..cuaderno_reforzamiento import _de_la_sst
        from ..excel_liquidacion import (generar_excel_liquidacion,
                                        panos_de_liquidaciones)

        sst, datos = self._sst_liquidada(request)
        codigo = sst.codigo or sst.sst
        por_poste = partidas_cobradas_por_poste(sst)
        # Los paños que se midieron al liquidar (reforzamiento) van a la hoja
        # Vereda, cada uno en el bloque de su espesor.
        panos = panos_de_liquidaciones(
            LiquidacionSuministro.objects.filter(_de_la_sst(sst))
            .distinct().order_by('id_liquidacion'))
        # La mano de obra va con lo que se COBRA, no con lo que se liquidó: el
        # paquete de cambio de poste ya incluye parte de ese trabajo y no se
        # cobra dos veces. Es la misma columna que muestra el consolidado.
        contenido = generar_excel_liquidacion({
            'sst': codigo,
            'actividad': datos.actividad,
            'distrito': sst.distrito,
            'fecha': sst.fecha_ejecucion,
            'contratista': sst.empresa.nombre if sst.empresa_id else '',
            'capataz': datos.capataz,
        }, datos.materiales, partidas_cobradas(sst), datos.elementos_plano,
            materiales_por_poste=[p.materiales for p in datos.por_poste],
            partidas_por_poste=[
                partidas for _numero, partidas in por_poste
            ],
            # Los dos van en el orden en que se grabaron los postes, que es el
            # orden de las columnas del Excel.
            postes=[numero for numero, _partidas in por_poste],
            panos_medidos=panos)
        resp = HttpResponse(
            contenido,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="liquidacion_{codigo}.xlsx"'
        return resp

    @action(detail=False, methods=['get'])
    def consolidado(self, request):
        """GET /api/liquidaciones/consolidado/?usuario=<id>

        Consolida las liquidaciones. El descuento del 'cambio de poste' se
        calcula POR POSTE (suministro): cobrado = max(0, real - N*incluido),
        con N = cambios de poste de ese poste. Luego se AGREGA por SST para
        mostrar. La actividad se detecta por el tipo de trabajo liquidado.
        Para que descuente, el poste y su alumbrado deben liquidarse en el
        MISMO suministro.

        Quien liquida (capataz, encargado) ve solo lo suyo aunque pida otro;
        el liquidador, el coordinador y el SuperAdmin, el de todos o el de
        uno, siempre de su empresa (el SuperAdmin, de todas)."""
        actor = (Usuario.objects.select_related('rol')
                 .filter(pk=request.user.id_usuario).first())
        if actor is None or not actor.puede_ver_consolidado():
            raise PermissionDenied('No puedes ver el consolidado.')
        qs = (LiquidacionSuministro.objects
              .select_related('tipo_trabajo', 'suministro')
              .prefetch_related('partidas__mano_de_obra'))
        if not actor.es_superadmin() and actor.empresa_id:
            qs = qs.filter(usuario__empresa_id=actor.empresa_id)
        if actor.puede_ver_consolidado_de_todos():
            usuario_id = request.query_params.get('usuario')
        else:
            usuario_id = actor.pk
        if usuario_id:
            qs = qs.filter(usuario_id=usuario_id)

        # Actividad por tipo de trabajo (más confiable que el registro SST).
        act_por_tipo = {}
        for att in ActividadTipoTrabajo.objects.select_related('actividad'):
            act_por_tipo.setdefault(att.tipo_trabajo_id, att.actividad.nombre)

        # Fecha y hora de ejecución: la pantalla de corregir las vuelve a
        # mostrar tal como se guardaron.
        fecha_por_sst = {}
        hora_por_sst = {}
        # Las obras de varios días: la app entra por sus partes, no por poste.
        obra_por_sst = {}
        for sst in SST.objects.select_related('actividad'):
            clave = sst.codigo or sst.sst
            if clave and sst.actividad_id and sst.actividad.varios_dias:
                obra_por_sst[clave] = sst.obra_terminada_el is not None
            if clave:
                fecha_por_sst[clave] = str(sst.fecha_ejecucion) if sst.fecha_ejecucion else ''
                hora_por_sst[clave] = (sst.hora_ejecucion.strftime('%H:%M')
                                       if sst.hora_ejecucion else '')

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
            g = postes.setdefault((sst_de(liq), sum_de(liq)),
                                  {'act': '', 'partidas': {}, 'liquidaciones': [],
                                   'suministro_id': None, 'externo': '',
                                   'numero': '', 'distrito': ''})
            g['liquidaciones'].append(liq)
            if liq.suministro_id:
                g['suministro_id'] = liq.suministro_id
                g['numero'] = liq.suministro.numero_suministro
                g['distrito'] = liq.suministro.distrito or ''
            if liq.suministro_externo:
                g['externo'] = liq.suministro_externo
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

        def buscar_partida(codigo):
            if codigo not in _mo_cache:
                _mo_cache[codigo] = ManoDeObra.objects.filter(
                    partida=codigo).first()
            return _mo_cache[codigo]

        for (sst_cod, _sum), g in postes.items():
            agg = ssts.setdefault(sst_cod, {'act': g['act'], 'cambios': Decimal('0'),
                                            'partidas': {}, 'postes': [],
                                            'calculo': []})
            # Cada poste con lo que se le liquidó: es por donde se entra a
            # corregir una liquidación desde el consolidado.
            agg['postes'].append({
                'suministro': g['externo'] or g['numero'] or _sum,
                'suministro_id': g['suministro_id'],
                'suministro_externo': g['externo'],
                'distrito': g['distrito'],
                'actividad': g['act'],
                'liquidaciones': [
                    {'id_liquidacion': liq.pk,
                     'tipo_trabajo': liq.tipo_trabajo_id,
                     'tipo_trabajo_nombre': liq.tipo_trabajo.nombre,
                     'usuario': liq.usuario_id,
                     'fecha_parte': (str(liq.fecha_parte)
                                     if liq.fecha_parte else '')}
                    for liq in g['liquidaciones']
                ],
            })
            if _norm_txt(g['act']) in INCLUSIONES_CONSOLIDADO:
                agg['act'] = g['act']
            # El descuento se calcula por poste, con la actividad de ese poste.
            agg['calculo'].append((_norm_txt(g['act']), g['partidas']))

        for agg in ssts.values():
            agg['partidas'], agg['cambios'] = consolidar_partidas(
                agg.pop('calculo'), INCLUSIONES_CONSOLIDADO, buscar_partida)

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
                'hora': hora_por_sst.get(sst_cod, ''),
                'cambios_poste': str(agg['cambios']),
                'varios_dias': sst_cod in obra_por_sst,
                'obra_terminada': obra_por_sst.get(sst_cod, False),
                'total': str(total), 'partidas': items,
                'postes': sorted(agg['postes'], key=lambda p: p['suministro']),
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
        if not request.query_params.get('usuario'):
            return Response({'detail': 'Parámetro usuario requerido.'}, status=400)
        usuario = usuario_consultado(
            request, lambda a: a.puede_ver_datos_de_otros())

        # Mapa actividad_nombre → lista de TipoTrabajo (local)
        atts = (ActividadTipoTrabajo.objects
                .select_related('actividad', 'tipo_trabajo')
                .prefetch_related('tipo_trabajo__partidas__mano_de_obra',
                                  'tipo_trabajo__materiales__material')
                .order_by('orden', 'tipo_trabajo__nombre'))
        actividad_map = {}
        for att in atts:
            nombre = att.actividad.nombre
            if nombre not in actividad_map:
                actividad_map[nombre] = []
            actividad_map[nombre].append(att.tipo_trabajo)

        # Todos los suministros ASIGNADOS pendientes de liquidar (sin filtro de semana)
        suministros = _suministros_asignados_usuario(usuario)

        # La actividad que puso el coordinador manda sobre la que trae el
        # proyecto externo: es la que está escrita con los nombres de este
        # catálogo, así que es la que encuentra los tipos de trabajo.
        codigos = {s.get('sst_codigo') for s in suministros if s.get('sst_codigo')}
        actividad_local = {
            codigo: nombre
            for codigo, nombre in SST.objects
            .filter(codigo__in=codigos, actividad__isnull=False)
            .values_list('codigo', 'actividad__nombre')
        }

        # Agrupar por día
        dias = {}
        for s in suministros:
            fecha_str = s.get('fecha_programada') or ''
            if fecha_str not in dias:
                dias[fecha_str] = []

            # Enriquecer con tipos de trabajo según actividad
            actividad_data  = s.get('actividad') or {}
            actividad_nombre = (actividad_local.get(s.get('sst_codigo'))
                                or actividad_data.get('nombre_actividad', ''))
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

            dias[fecha_str].append({
                **s,
                'actividad_nombre': actividad_nombre,
                'tipos_trabajo_disponibles': tipos_trabajo,
            })

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
        if not request.query_params.get('usuario'):
            return Response({'detail': 'Parámetro usuario requerido.'}, status=400)
        usuario = usuario_consultado(
            request, lambda a: a.puede_ver_datos_de_otros())

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
