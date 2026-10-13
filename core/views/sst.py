"""SST: carga, asignación de postes, puntos de trabajo y pendientes de liquidar."""
from .comun import *  # noqa: F401,F403


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

    @action(detail=False, methods=['get'])
    def puntos(self, request):
        """GET /api/ssts/puntos/?sst_codigo=<codigo> — los postes de una SST.

        Es lo que la pantalla de liquidar usa para pintar el selector de
        puntos de trabajo. Devuelve todos los de la SST, no solo los del
        usuario: en una reforma varios capataces pueden estar en la misma."""
        codigo = (request.query_params.get('sst_codigo') or '').strip()
        if not codigo:
            return Response({'detail': 'sst_codigo es obligatorio.'}, status=400)
        sst = (qs_empresa(SST.objects.select_related('actividad'), request)
               .filter(models.Q(codigo=codigo) | models.Q(sst=codigo))
               .first())
        if sst is None:
            return Response({'detail': f'No existe la SST {codigo}.'}, status=404)
        relaciones = (SSTSuministro.objects
                      .filter(sst=sst)
                      .select_related('suministro'))
        return Response({
            'sst_codigo':    sst.codigo or sst.sst or '',
            'actividad':     sst.actividad.nombre if sst.actividad_id else '',
            'varios_postes': bool(sst.actividad_id and sst.actividad.varios_postes),
            'puntos': [
                {
                    'id_suministro':     rel.suministro.id_suministro,
                    'numero_suministro': rel.suministro.numero_suministro,
                    'distrito':          rel.suministro.distrito,
                    'estado':            rel.suministro.estado,
                    'asignado_a':        rel.asignado_a_id,
                }
                for rel in relaciones
            ],
        })

    @action(detail=False, methods=['post'])
    def agregar_punto(self, request):
        """POST /api/ssts/agregar_punto/  { sst_codigo, numero_suministro }

        Suma un poste a una SST y se lo asigna a quien lo pide. Lo usa el
        capataz en obra: en una reforma los puntos de trabajo aparecen
        mientras se trabaja, no vienen en la asignación.

        Solo en actividades que admiten varios postes. En cambio de poste una
        SST es un poste, y ahí este botón no existe."""
        codigo = (request.data.get('sst_codigo') or '').strip()
        numero = (request.data.get('numero_suministro') or '').strip()
        if not codigo or not numero:
            return Response(
                {'detail': 'sst_codigo y numero_suministro son obligatorios.'},
                status=400)

        sst = (qs_empresa(SST.objects.select_related('actividad'), request)
               .filter(models.Q(codigo=codigo) | models.Q(sst=codigo))
               .first())
        if sst is None:
            return Response({'detail': f'No existe la SST {codigo}.'}, status=404)
        if not (sst.actividad_id and sst.actividad.varios_postes):
            nombre = sst.actividad.nombre if sst.actividad_id else 'sin actividad'
            return Response(
                {'detail': f'La actividad «{nombre}» liquida un solo poste por '
                           'SST: no se pueden agregar más.'}, status=400)

        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        if actor is None:
            return Response({'detail': 'Usuario no encontrado.'}, status=400)

        # El número solo tiene que ser único DENTRO de su SST: "Poste 01" es una
        # etiqueta que el capataz repite en cada reforma, y un poste real puede
        # trabajarse en dos SST distintas.
        if SSTSuministro.objects.filter(
                sst=sst, suministro__numero_suministro=numero).exists():
            return Response(
                {'detail': f'El poste {numero} ya está en esta SST.'}, status=400)
        # Cada SST tiene su propio registro del poste, aunque el número se
        # repita: si compartieran uno, las liquidaciones de una SST saldrían en
        # el cuaderno y el Excel de la otra.
        suministro = Suministro.objects.create(
            numero_suministro=numero,
            distrito=sst.distrito or '',
            estado='asignado')

        ultimo = (SSTSuministro.objects.filter(sst=sst)
                  .order_by('-orden').values_list('orden', flat=True).first())
        SSTSuministro.objects.create(
            sst=sst, suministro=suministro, asignado_a=actor,
            orden=(ultimo or 0) + 1)
        return Response({
            'id_suministro':     suministro.id_suministro,
            'numero_suministro': suministro.numero_suministro,
            'sst_codigo':        sst.codigo or sst.sst or '',
            'distrito':          suministro.distrito,
            'actividad':         sst.actividad.nombre,
        }, status=201)

    def _punto_de(self, request, solo_por_id=False):
        """La SST y el punto de trabajo que pide el cuerpo, o un error.

        Devuelve (sst, relacion, error): si hay error, los otros dos son None.
        """
        codigo = (request.data.get('sst_codigo') or '').strip()
        id_suministro = request.data.get('id_suministro')
        # Al renombrar, `numero_suministro` es el nombre NUEVO: ahí el punto
        # solo se puede buscar por su id.
        numero = ('' if solo_por_id
                  else (request.data.get('numero_suministro') or '').strip())
        if not codigo or not (id_suministro or numero):
            return None, None, Response(
                {'detail': 'sst_codigo y el punto son obligatorios.'}, status=400)
        sst = (qs_empresa(SST.objects.select_related('actividad'), request)
               .filter(models.Q(codigo=codigo) | models.Q(sst=codigo)).first())
        if sst is None:
            return None, None, Response(
                {'detail': f'No existe la SST {codigo}.'}, status=404)
        if not self._trabaja_en(request, sst):
            return None, None, Response(
                {'detail': 'Esta SST no es suya.'}, status=403)
        relaciones = SSTSuministro.objects.filter(sst=sst).select_related(
            'suministro')
        rel = (relaciones.filter(suministro_id=id_suministro).first()
               if id_suministro
               else relaciones.filter(
                   suministro__numero_suministro=numero).first())
        if rel is None:
            return None, None, Response(
                {'detail': 'Ese punto no está en esta SST.'}, status=404)
        return sst, rel, None

    def _trabaja_en(self, request, sst):
        """Si quien pide tiene algo que ver con esa SST.

        El capataz corrige los puntos de las SST en las que trabaja; el
        coordinador, los de cualquiera."""
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        if actor is None:
            return False
        if actor.puede_asignar_sst():
            return True
        return (SSTSuministro.objects.filter(sst=sst, asignado_a=actor).exists()
                or SSTEncargado.objects.filter(sst=sst, usuario=actor).exists())

    @action(detail=False, methods=['post'])
    def renombrar_punto(self, request):
        """POST /api/ssts/renombrar_punto/  { sst_codigo, id_suministro, numero_suministro }

        Corrige el número de un poste. Lo liquidado sigue colgado de él, así
        que el consolidado, el Excel y el cuaderno pasan a decir el número
        bueno: es lo que se quiere cuando el número se tecleó mal."""
        nuevo = (request.data.get('numero_suministro') or '').strip()
        id_suministro = request.data.get('id_suministro')
        if not id_suministro or not nuevo:
            return Response(
                {'detail': 'id_suministro y numero_suministro son obligatorios.'},
                status=400)
        sst, rel, error = self._punto_de(request, solo_por_id=True)
        if error:
            return error
        choca = (SSTSuministro.objects
                 .filter(sst=sst, suministro__numero_suministro=nuevo)
                 .exclude(suministro_id=rel.suministro_id).exists())
        if choca:
            return Response(
                {'detail': f'El poste {nuevo} ya está en esta SST.'}, status=400)
        anterior = rel.suministro.numero_suministro
        rel.suministro.numero_suministro = nuevo
        rel.suministro.save(update_fields=['numero_suministro'])
        return Response({
            'id_suministro': rel.suministro_id,
            'numero_suministro': nuevo,
            'anterior': anterior,
        })

    @action(detail=False, methods=['post'])
    def ordenar_puntos(self, request):
        """POST /api/ssts/ordenar_puntos/  { sst_codigo, ids: [...] }

        Acomoda los puntos en el orden que manda la lista. Ese orden decide
        en qué columna del Excel cae cada poste y el orden del cuaderno, así
        que lo maneja quien trabaja la SST."""
        codigo = (request.data.get('sst_codigo') or '').strip()
        ids = request.data.get('ids') or []
        if not codigo or not isinstance(ids, list) or not ids:
            return Response(
                {'detail': 'sst_codigo e ids son obligatorios.'}, status=400)
        sst = (qs_empresa(SST.objects.all(), request)
               .filter(models.Q(codigo=codigo) | models.Q(sst=codigo)).first())
        if sst is None:
            return Response({'detail': f'No existe la SST {codigo}.'}, status=404)
        if not self._trabaja_en(request, sst):
            return Response({'detail': 'Esta SST no es suya.'}, status=403)

        relaciones = {r.suministro_id: r
                      for r in SSTSuministro.objects.filter(sst=sst)}
        faltan = [i for i in ids if i not in relaciones]
        if faltan:
            return Response(
                {'detail': 'Hay puntos en la lista que no son de esta SST.'},
                status=400)
        for orden, id_suministro in enumerate(ids):
            rel = relaciones.pop(id_suministro)
            rel.orden = orden
            rel.save(update_fields=['orden'])
        # Lo que no vino en la lista queda al final, en el orden que tenía.
        for extra, rel in enumerate(relaciones.values()):
            rel.orden = len(ids) + extra
            rel.save(update_fields=['orden'])
        return Response({'ids': ids})

    @action(detail=False, methods=['post'])
    def quitar_punto(self, request):
        """POST /api/ssts/quitar_punto/  { sst_codigo, id_suministro }

        Saca un poste de la SST con todo lo suyo: sus liquidaciones, el
        material que consumió —que vuelve al camión— y su recupero.

        Antes de borrar se levanta el acta de cada liquidación, en la misma
        tabla del historial de correcciones: el usuario pidió que el punto se
        fuera entero, pero lo que decía queda registrado."""
        from ..serializers import (
            LiquidacionSuministroCreateSerializer, _retrato_liquidacion,
        )

        sst, rel, error = self._punto_de(request)
        if error:
            return error

        suministro = rel.suministro
        numero = suministro.numero_suministro
        with transaction.atomic():
            liquidaciones = list(
                LiquidacionSuministro.objects
                .filter(models.Q(suministro=suministro) |
                        models.Q(suministro_externo=numero,
                                 sst_externo=sst.codigo or sst.sst))
                .select_related('usuario', 'tipo_trabajo')
                .prefetch_related('partidas__mano_de_obra',
                                  'materiales_consumidos__material'))
            actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
            for liq in liquidaciones:
                CorreccionLiquidacion.objects.create(
                    suministro=None,
                    suministro_externo=numero,
                    sst_externo=sst.codigo or sst.sst or '',
                    tipo_trabajo=liq.tipo_trabajo,
                    usuario_anterior=liq.usuario,
                    usuario=actor or liq.usuario,
                    fecha_anterior=liq.fecha,
                    anterior=_retrato_liquidacion(liq),
                    cambios=f'Se eliminó el punto de trabajo {numero} con '
                            'toda su liquidación.',
                )
            # El material vuelve al camión de quien lo cargó, igual que al
            # corregir una liquidación.
            LiquidacionSuministroCreateSerializer._devolver_al_camion(
                liquidaciones)
            borradas = len(liquidaciones)
            for liq in liquidaciones:
                liq.delete()
            ConsumoMaterialSuministro.objects.filter(
                suministro=suministro).delete()
            recuperados = SuministroRecupero.objects.filter(
                suministro=suministro).count()
            SuministroRecupero.objects.filter(suministro=suministro).delete()
            SuministroTipoTrabajo.objects.filter(suministro=suministro).delete()
            SuministroManoDeObra.objects.filter(suministro=suministro).delete()
            rel.delete()
            # El poste solo se borra si no quedó colgado de otra SST.
            if not SSTSuministro.objects.filter(suministro=suministro).exists():
                suministro.delete()
        return Response({
            'numero_suministro': numero,
            'liquidaciones_borradas': borradas,
            'recuperos_borrados': recuperados,
        })

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

    @staticmethod
    def _tiene_liquidaciones(sst):
        """Si la SST ya tiene mano de obra liquidada, su actividad no se toca.

        Las reglas del consolidado dependen de la actividad, así que cambiarla
        después dejaría lo ya liquidado con tipos de trabajo de otra actividad
        y los descuentos saldrían mal."""
        if sst.codigo and LiquidacionSuministro.objects.filter(
                sst_externo=sst.codigo).exists():
            return True
        ids = (SSTSuministro.objects.filter(sst=sst)
               .values_list('suministro_id', flat=True))
        return LiquidacionSuministro.objects.filter(
            suministro_id__in=list(ids)).exists()

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
        if sst.actividad_id and not actividades_para(capataz).filter(
                pk=sst.actividad_id).exists():
            return Response({'detail': f'La actividad de la SST no es para '
                                       f'{capataz.nombre}.'}, status=400)
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

        Deshace la asignación de los postes indicados (o de todos los de la
        SST). Un poste que ya se liquidó no se deshace: su liquidación lo
        nombra. Quien se queda sin postes en la SST deja de ser su encargado,
        así la SST ya no le aparece."""
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        if not actor or not actor.puede_asignar_sst():
            return Response(
                {'detail': 'Solo un Coordinador puede desasignar.'}, status=403)
        sst = self.get_object()
        suministros_ids = request.data.get('suministros', [])
        qs = SSTSuministro.objects.filter(sst=sst, asignado_a__isnull=False)
        if suministros_ids:
            qs = qs.filter(suministro_id__in=suministros_ids)
        liquidados = [r.suministro.numero_suministro for r in qs.select_related('suministro')
                      if r.suministro.estado != 'asignado'
                      or r.suministro.liquidaciones.exists()]
        if liquidados:
            raise ErrorNegocio(
                'Ya se liquidó y no se puede deshacer: ' + ', '.join(liquidados) + '.')
        with transaction.atomic():
            quienes = set(qs.values_list('asignado_a_id', flat=True))
            actualizados = qs.update(asignado_a=None)
            for usuario_id in quienes:
                if not SSTSuministro.objects.filter(
                        sst=sst, asignado_a_id=usuario_id).exists():
                    SSTEncargado.objects.filter(
                        sst=sst, usuario_id=usuario_id).delete()
        return Response({'status': 'ok', 'suministros_desasignados': actualizados})

    @action(detail=False, methods=['get'])
    def pendientes_de_liquidar(self, request):
        """GET /api/ssts/pendientes_de_liquidar/

        Los postes asignados a capataces y encargados que todavía no se
        liquidan, agrupados por persona y por SST. Solo el SuperAdmin; desde
        aquí también los puede deshacer (desasignar)."""
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        if not actor or not actor.puede_ver_pendientes_de_liquidar():
            return Response({'detail': 'Solo el SuperAdmin.'}, status=403)
        relaciones = (SSTSuministro.objects
                      .filter(asignado_a__isnull=False,
                              suministro__estado='asignado',
                              suministro__liquidaciones__isnull=True)
                      .select_related('sst', 'sst__actividad', 'suministro',
                                      'asignado_a', 'asignado_a__rol')
                      .order_by('asignado_a__nombre', 'sst__fecha_inicio',
                                'sst__codigo', 'orden', 'id_sst_suministro'))
        if not actor.es_superadmin() and actor.empresa_id:
            relaciones = relaciones.filter(sst__empresa_id=actor.empresa_id)
        personas = {}
        for r in relaciones:
            u = r.asignado_a
            persona = personas.setdefault(u.pk, {
                'usuario': u.pk, 'nombre': u.nombre,
                'rol': u.rol.descripcion, 'ssts': {}})
            sst = r.sst
            fila = persona['ssts'].setdefault(sst.pk, {
                'id_sst': sst.pk,
                'sst': sst.codigo or sst.sst,
                'actividad': sst.actividad.nombre if sst.actividad_id else '',
                'distrito': sst.distrito or '',
                'fecha': sst.fecha_inicio,
                'postes': []})
            fila['postes'].append({
                'id_suministro': r.suministro_id,
                'numero': r.suministro.numero_suministro})
        return Response([
            {**p, 'ssts': list(p['ssts'].values()),
             'postes': sum(len(s['postes']) for s in p['ssts'].values())}
            for p in personas.values()])

    @action(detail=False, methods=['post'])
    def set_actividad(self, request):
        """POST /api/ssts/set_actividad/  { sst_codigo, actividad }
        Asigna (o cambia) la actividad de una SST identificada por su código,
        dentro de la empresa del usuario. Lo usa el capataz al liquidar."""
        sst_codigo = (request.data.get('sst_codigo') or '').strip()
        actividad_id = request.data.get('actividad')
        if not sst_codigo or not actividad_id:
            return Response({'detail': 'sst_codigo y actividad son obligatorios.'}, status=400)
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        if not actividades_para(actor).filter(pk=actividad_id).exists():
            return Response({'detail': 'Esa actividad no está habilitada '
                                       'para tu rol.'}, status=400)
        empresa_id = getattr(request.user, 'empresa_id', None)
        qs = SST.objects.filter(codigo=sst_codigo)
        if empresa_id:
            qs = qs.filter(empresa_id=empresa_id)
        ssts = list(qs)
        if not ssts:
            return Response({'detail': 'No se encontró la SST.'}, status=404)
        actualizadas = 0
        for sst in ssts:
            if sst.actividad_id == int(actividad_id):
                continue  # ya la tiene: no hay nada que cambiar
            if self._tiene_liquidaciones(sst):
                return Response(
                    {'detail': 'La SST ya tiene liquidaciones: su actividad '
                               'no se puede cambiar.'}, status=400)
            sst.actividad_id = actividad_id
            sst.save(update_fields=['actividad'])
            actualizadas += 1
        return Response({'status': 'ok', 'sst_codigo': sst_codigo,
                         'actividad': actividad_id, 'ssts_actualizadas': actualizadas})

    @action(detail=False, methods=['post'])
    def set_fecha_ejecucion(self, request):
        """POST /api/ssts/set_fecha_ejecucion/  { sst_codigo, fecha, hora? }
        Fija la fecha de ejecución de la SST (por código, en la empresa del
        usuario) y, si viene, la hora ('HH:MM'), que sale en el cuaderno de obra."""
        sst_codigo = (request.data.get('sst_codigo') or '').strip()
        fecha = request.data.get('fecha')  # 'YYYY-MM-DD' o null
        cambios = {'fecha_ejecucion': fecha or None}
        if 'hora' in request.data:
            cambios['hora_ejecucion'] = request.data.get('hora') or None
        if not sst_codigo:
            return Response({'detail': 'sst_codigo es obligatorio.'}, status=400)
        empresa_id = getattr(request.user, 'empresa_id', None)
        qs = SST.objects.filter(codigo=sst_codigo)
        if empresa_id:
            qs = qs.filter(empresa_id=empresa_id)
        n = qs.update(**cambios)
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
        actividad_id = request.data.get('actividad')  # opcional

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
        # Se le asigna obra a quien la ejecuta: un capataz o un encargado.
        if not (capataz.roles & {Rol.CAPATAZ, Rol.ENCARGADO}):
            return Response({'detail': 'Solo se asigna a un capataz o a un '
                                       'encargado.'}, status=400)
        if actividad_id and not actividades_para(capataz).filter(
                pk=actividad_id).exists():
            return Response({'detail': f'Esa actividad no es para '
                                       f'{capataz.nombre}: el encargado lleva '
                                       'las de encargado y el capataz las '
                                       'demás.'}, status=400)

        with transaction.atomic():
            sst, sst_nuevo = SST.objects.get_or_create(
                empresa_id=actor.empresa_id, codigo=sst_codigo,
                defaults={'distrito': distrito},
            )
            # Dentro de esta SST, no en toda la base: el mismo número puede
            # estar en otra SST y ahí es otro registro.
            sum_obj = Suministro.objects.filter(
                numero_suministro=numero, sst_suministros__sst=sst).first()
            sum_nuevo = sum_obj is None
            if sum_nuevo:
                sum_obj = Suministro.objects.create(
                    numero_suministro=numero,
                    distrito=distrito or sst.distrito, estado='asignado')
            SSTSuministro.objects.update_or_create(
                sst=sst, suministro=sum_obj,
                defaults={'asignado_a': capataz},
            )
            SSTEncargado.objects.get_or_create(sst=sst, usuario=capataz)
            # La actividad decide qué tipos de trabajo verá el capataz. Es
            # dato del coordinador, pero si ya se liquidó algo no se toca.
            if actividad_id and sst.actividad_id != int(actividad_id):
                if self._tiene_liquidaciones(sst):
                    raise ErrorNegocio(
                        'La SST ya tiene liquidaciones: su actividad no se '
                        'puede cambiar.')
                sst.actividad_id = actividad_id
                sst.save(update_fields=['actividad'])

        return Response({
            'status': 'ok',
            'sst': sst.codigo,
            'sst_creada': sst_nuevo,
            'actividad': sst.actividad_id,
            'poste': sum_obj.numero_suministro,
            'poste_creado': sum_nuevo,
            'capataz': capataz.nombre,
        }, status=200)
