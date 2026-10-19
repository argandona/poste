"""IPC: Instrucción Previa en Campo y Check List."""
from .comun import *  # noqa: F401,F403


# ── IPC: Instrucción Previa en Campo ─────────────────────────────────────────
class IPCViewSet(viewsets.ViewSet):
    """IPC y Check List: la Instrucción Previa en Campo.

    La hace un capataz o encargado antes de empezar; durante el día le suma
    las SST que va ejecutando (nunca un IPC de otro día). Cada participante
    confirma desde su app; si no puede, firma en el equipo del responsable.
    Al terminar se cierra con las observaciones y sale el PDF del formato."""
    permission_classes = [permissions.IsAuthenticated]

    # Firma dibujada (PNG) más pesada que esto es un error.
    FIRMA_MAXIMA = 600 * 1024

    @staticmethod
    def _actor(request):
        return (Usuario.objects.select_related('rol', 'empresa')
                .filter(pk=request.user.id_usuario).first())

    @staticmethod
    def _con_todo(qs):
        return (qs.select_related('responsable', 'coordinador', 'empresa')
                .prefetch_related('ssts__sst', 'participantes__usuario'))

    def _visibles(self, actor):
        qs = IPC.objects.all()
        if actor.puede_ver_todos_los_ipc():
            if not actor.es_superadmin() and actor.empresa_id:
                qs = qs.filter(empresa_id=actor.empresa_id)
            return qs
        return qs.filter(models.Q(responsable=actor) |
                         models.Q(participantes__usuario=actor)).distinct()

    def _datos(self, ipc, actor):
        from ..ipc_formato import factores_en_riesgo
        hoy = timezone.localdate()
        mio = next((p for p in ipc.participantes.all()
                    if p.usuario_id == actor.pk), None)
        return {
            'id_ipc': ipc.pk,
            'fecha': ipc.fecha,
            'es_de_hoy': ipc.fecha == hoy,
            'estado': ipc.estado,
            'tarea': ipc.tarea,
            'responsable': ipc.responsable_id,
            'responsable_nombre': ipc.responsable.nombre,
            'coordinador': ipc.coordinador_id,
            'coordinador_nombre': ipc.coordinador.nombre if ipc.coordinador_id else '',
            'formato': f'{ipc.formato_codigo} v{ipc.formato_version}',
            'datos': ipc.datos,
            'factores_en_riesgo': [f['texto'] for f in factores_en_riesgo(ipc.datos)],
            'observaciones': ipc.observaciones,
            'hora_cierre': ipc.hora_cierre,
            'puedo_editar': (ipc.responsable_id == actor.pk and ipc.fecha == hoy
                             and ipc.estado == 'abierto'),
            'mi_estado': mio.estado if mio else None,
            'ssts': [{'id_sst': s.sst_id, 'sst': s.codigo,
                      'manual': s.sst_id is None,
                      'direccion': s.direccion, 'agregada': s.agregada}
                     for s in ipc.ssts.all()],
            'participantes': [{
                'usuario': p.usuario_id, 'nombre': p.usuario.nombre,
                'dni': p.dni, 'cargo': p.cargo, 'estado': p.estado,
                'metodo': p.metodo, 'confirmado': p.confirmado,
                'tiene_firma': bool(p.firma),
            } for p in ipc.participantes.all()],
        }

    def _responder(self, ipc, actor, status=200):
        ipc = self._con_todo(IPC.objects).get(pk=ipc.pk)
        return Response(self._datos(ipc, actor), status=status)

    def _mio_editable(self, request, pk):
        """El IPC del actor, abierto y de hoy: lo único que se modifica."""
        actor = self._actor(request)
        ipc = IPC.objects.filter(pk=pk, responsable=actor).first()
        if ipc is None:
            raise PermissionDenied('Solo el responsable modifica su IPC.')
        if ipc.fecha != timezone.localdate():
            raise ErrorNegocio('Un IPC solo sirve el día en que se hizo: '
                               'para hoy genera uno nuevo.')
        if ipc.estado != 'abierto':
            raise ErrorNegocio('El IPC ya está cerrado.')
        return actor, ipc

    # ── Participantes ───────────────────────────────────────────────────────
    @staticmethod
    def _candidato(actor, usuario_id):
        u = (Usuario.objects.select_related('rol')
             .filter(pk=usuario_id, activo=True).first())
        if u is None or not u.participa_en_ipc():
            raise ErrorNegocio('Los participantes son operarios, ayudantes, '
                               'capataces y encargados.')
        if (not actor.es_superadmin() and actor.empresa_id
                and u.empresa_id != actor.empresa_id):
            raise ErrorNegocio(f'{u.nombre} es de otra empresa.')
        return u

    @staticmethod
    def _sumar_participante(ipc, usuario, conforme=False):
        p, nuevo = IPCParticipante.objects.get_or_create(
            ipc=ipc, usuario=usuario,
            defaults={'dni': usuario.dni, 'cargo': usuario.rol.descripcion})
        if conforme and p.estado != 'conforme':
            p.estado = 'conforme'
            p.metodo = IPCParticipante.METODO_APP
            p.confirmado = timezone.now()
            p.save(update_fields=['estado', 'metodo', 'confirmado'])
        return p, nuevo

    @staticmethod
    def _avisar_participantes(ipc, usuarios):
        from ..fcm import send_notification
        tokens = [u.fcm_token for u in usuarios if u.fcm_token]
        send_notification(
            tokens,
            title='Confirma tu IPC de hoy',
            body=(f'{ipc.responsable.nombre} te agregó al IPC: {ipc.tarea[:80]}. '
                  'Revisa los riesgos y confirma.'),
            data={'tipo': 'ipc_por_confirmar', 'ipc_id': str(ipc.pk)})

    # ── SST ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _sst(actor, sst_id):
        sst = SST.objects.filter(pk=sst_id).first()
        if sst is None:
            raise ErrorNegocio('Elige una SST.')
        if (not actor.es_superadmin() and actor.empresa_id
                and sst.empresa_id != actor.empresa_id):
            raise ErrorNegocio('Esa SST es de otra empresa.')
        # Una SST no se ejecuta sin IPC: si ya la liquidó, ya tuvo el suyo.
        if ssts_ya_liquidadas(actor, [sst.pk]):
            raise ErrorNegocio(f'La SST {sst.codigo or sst.sst} ya está liquidada: '
                               'ya se ejecutó con su IPC.')
        return sst

    @classmethod
    def _sst_de(cls, actor, item):
        """De {sst: id} (una asignada) o {codigo: '...'} (escrita a mano):
        (SST o None, código). Si el código escrito ya es una SST de la empresa,
        se enlaza a esa, con las mismas reglas."""
        item = item if isinstance(item, dict) else {}
        if item.get('sst'):
            sst = cls._sst(actor, item['sst'])
            return sst, sst.codigo or sst.sst
        codigo = str(item.get('codigo') or '').strip().upper()
        if not codigo:
            raise ErrorNegocio('Elige una SST o escribe su código.')
        if len(codigo) > 20:
            raise ErrorNegocio('El código de la SST es muy largo.')
        existente = SST.objects.filter(
            models.Q(codigo__iexact=codigo) | models.Q(sst__iexact=codigo),
            empresa_id=actor.empresa_id).first() if actor.empresa_id else None
        if existente:
            return cls._sst(actor, existente.pk), codigo
        return None, codigo

    @staticmethod
    def _sumar_sst(ipc, sst, codigo, direccion=''):
        repetida = models.Q(codigo__iexact=codigo)
        if sst is not None:
            repetida |= models.Q(sst=sst)
        fila = ipc.ssts.filter(repetida).first()
        if fila:
            return fila, False
        fila = IPCSST.objects.create(
            ipc=ipc, sst=sst, codigo=codigo, orden=ipc.ssts.count(),
            direccion=(direccion or (sst.distrito if sst else '') or '').strip()[:250])
        return fila, True

    # ── Endpoints ───────────────────────────────────────────────────────────
    @action(detail=False, methods=['get'])
    def formato(self, request):
        """GET /api/ipcs/formato/ — las preguntas y opciones del formato."""
        from ..ipc_formato import formato
        return Response(formato())

    @action(detail=False, methods=['get', 'put'])
    def contacto_emergencia(self, request):
        """GET|PUT /api/ipcs/contacto_emergencia/?empresa=<id>

        Los contactos que el IPC trae precargados. Editarlos: SuperAdmin, que
        no es de ninguna empresa y por eso dice cuál (`empresa` en la consulta
        o en el cuerpo); los demás ven los de la suya."""
        actor = self._actor(request)
        empresa_id = actor.empresa_id
        if actor.es_superadmin():
            empresa_id = (request.data.get('empresa')
                          or request.query_params.get('empresa') or empresa_id)
        if request.method == 'PUT':
            if not actor.es_superadmin():
                raise PermissionDenied('Solo el SuperAdmin edita los contactos.')
            if not empresa_id:
                raise ErrorNegocio('Elige la empresa.')
            contacto, _ = ContactoEmergencia.objects.get_or_create(
                empresa_id=empresa_id)
            for campo in ('superior_nombre', 'superior_telefono',
                          'medico_nombre', 'medico_telefono',
                          'centro_medico', 'centro_medico_telefono'):
                if campo in request.data:
                    setattr(contacto, campo,
                            str(request.data.get(campo) or '').strip()[:200])
            contacto.save()
        contacto = ContactoEmergencia.objects.filter(empresa_id=empresa_id).first()
        return Response(self._contacto(contacto))

    @staticmethod
    def _centro_medico(request):
        return str(request.data.get('centro_medico') or '').strip()[:200]

    @staticmethod
    def _contacto(contacto):
        campos = ('superior_nombre', 'superior_telefono', 'medico_nombre',
                  'medico_telefono', 'centro_medico', 'centro_medico_telefono')
        return {c: (getattr(contacto, c) if contacto else '') for c in campos}

    def list(self, request):
        """GET /api/ipcs/?por_confirmar=1&fecha=AAAA-MM-DD

        Los del actor (los que hizo y en los que participa); el SuperAdmin y
        el Coordinador ven todos los de la empresa. Los últimos 200."""
        actor = self._actor(request)
        qs = self._visibles(actor)
        if request.query_params.get('por_confirmar'):
            qs = IPC.objects.filter(participantes__usuario=actor,
                                    participantes__estado='pendiente',
                                    estado='abierto')
        if request.query_params.get('fecha'):
            qs = qs.filter(fecha=request.query_params['fecha'])
        qs = self._con_todo(qs)[:200]
        return Response([self._datos(i, actor) for i in qs])

    def retrieve(self, request, pk=None):
        actor = self._actor(request)
        ipc = self._con_todo(self._visibles(actor)).filter(pk=pk).first()
        if ipc is None:
            return Response({'detail': 'No existe.'}, status=404)
        return Response(self._datos(ipc, actor))

    @action(detail=False, methods=['get'])
    def hoy(self, request):
        """GET /api/ipcs/hoy/ — los IPC abiertos que el actor hizo hoy: los
        que puede reutilizar sumando la siguiente SST."""
        actor = self._actor(request)
        qs = self._con_todo(IPC.objects.filter(
            responsable=actor, fecha=timezone.localdate(), estado='abierto'))
        return Response([self._datos(i, actor) for i in qs])

    def create(self, request):
        """POST /api/ipcs/
        {tarea, coordinador?, centro_medico?, datos,
         ssts: [{sst | codigo, direccion?}],
         participantes: [usuario, ...]}

        El responsable entra solo como participante, ya conforme. Los contactos
        de emergencia se copian de los del SuperAdmin, salvo el centro médico
        más cercano, que depende de dónde se trabaja: lo escribe el responsable
        (la app lo pide; sin él, queda el del SuperAdmin)."""
        from ..ipc_formato import CODIGO, VERSION, limpiar_datos
        actor = self._actor(request)
        if not actor.puede_hacer_ipc():
            return Response({'detail': 'El IPC lo hacen capataces y encargados.'},
                            status=403)
        tarea = (request.data.get('tarea') or '').strip()
        if not tarea:
            raise ErrorNegocio('Describe la tarea.')
        ssts = request.data.get('ssts') or []
        if not ssts:
            raise ErrorNegocio('Agrega al menos una SST.')
        coordinador = None
        if request.data.get('coordinador'):
            coordinador = Usuario.objects.filter(
                pk=request.data['coordinador'], activo=True).first()
            if coordinador is None or Rol.COORDINADOR not in coordinador.roles:
                raise ErrorNegocio('Elige un coordinador.')
        participantes = [self._candidato(actor, u)
                         for u in request.data.get('participantes') or []
                         if str(u) != str(actor.pk)]
        lista_ssts = [(*self._sst_de(actor, s), s.get('direccion', ''))
                      for s in ssts if isinstance(s, dict)]
        datos = limpiar_datos(request.data.get('datos'))
        contacto = ContactoEmergencia.objects.filter(
            empresa_id=actor.empresa_id).first()
        datos['emergencia'] = self._contacto(contacto)
        centro = self._centro_medico(request)
        if centro:
            datos['emergencia']['centro_medico'] = centro
        with transaction.atomic():
            ipc = IPC.objects.create(
                empresa_id=actor.empresa_id, responsable=actor,
                coordinador=coordinador, fecha=timezone.localdate(),
                tarea=tarea[:2000], formato_codigo=CODIGO,
                formato_version=VERSION, datos=datos)
            for sst, codigo, direccion in lista_ssts:
                self._sumar_sst(ipc, sst, codigo, direccion)
            self._sumar_participante(ipc, actor, conforme=True)
            for u in participantes:
                self._sumar_participante(ipc, u)
            # El chofer que llenó antes su Conducción de hoy: queda ligada.
            Conduccion.objects.filter(chofer=actor, fecha=ipc.fecha,
                                      ipc__isnull=True).update(ipc=ipc)
        self._avisar_participantes(ipc, participantes)
        return self._responder(ipc, actor, status=201)

    def partial_update(self, request, pk=None):
        """PATCH /api/ipcs/{id}/ {tarea?, coordinador?, centro_medico?, datos?}
        — hoy y abierto."""
        from ..ipc_formato import limpiar_datos
        actor, ipc = self._mio_editable(request, pk)
        if 'tarea' in request.data:
            tarea = (request.data.get('tarea') or '').strip()
            if not tarea:
                raise ErrorNegocio('Describe la tarea.')
            ipc.tarea = tarea[:2000]
        if 'coordinador' in request.data:
            c = request.data.get('coordinador')
            coordinador = Usuario.objects.filter(pk=c, activo=True).first() if c else None
            if c and (coordinador is None or Rol.COORDINADOR not in coordinador.roles):
                raise ErrorNegocio('Elige un coordinador.')
            ipc.coordinador = coordinador
        emergencia = (ipc.datos or {}).get('emergencia') or {}
        if 'centro_medico' in request.data:
            emergencia = {**emergencia, 'centro_medico': self._centro_medico(request)}
        if 'datos' in request.data:
            ipc.datos = limpiar_datos(request.data.get('datos'))
        ipc.datos = {**(ipc.datos or {}), 'emergencia': emergencia}
        ipc.save()
        return self._responder(ipc, actor)

    @action(detail=True, methods=['post'])
    def agregar_sst(self, request, pk=None):
        """POST /api/ipcs/{id}/agregar_sst/ {sst | codigo, direccion?}

        Usar el IPC de hoy en la siguiente SST: se conservan las anteriores.
        Una asignada (`sst`) o una escrita a mano (`codigo`)."""
        actor, ipc = self._mio_editable(request, pk)
        sst, codigo = self._sst_de(actor, request.data)
        _, nueva = self._sumar_sst(ipc, sst, codigo, request.data.get('direccion', ''))
        if not nueva:
            raise ErrorNegocio(f'La SST {codigo} ya está en este IPC.')
        return self._responder(ipc, actor)

    @action(detail=True, methods=['post'])
    def agregar_participante(self, request, pk=None):
        """POST /api/ipcs/{id}/agregar_participante/ {usuario}"""
        actor, ipc = self._mio_editable(request, pk)
        usuario = self._candidato(actor, request.data.get('usuario'))
        _, nuevo = self._sumar_participante(ipc, usuario)
        if nuevo:
            self._avisar_participantes(ipc, [usuario])
        return self._responder(ipc, actor)

    @action(detail=True, methods=['post'])
    def quitar_participante(self, request, pk=None):
        """POST /api/ipcs/{id}/quitar_participante/ {usuario}

        Solo si todavía no confirmó, y nunca el responsable."""
        actor, ipc = self._mio_editable(request, pk)
        p = ipc.participantes.filter(usuario_id=request.data.get('usuario')).first()
        if p is None:
            raise ErrorNegocio('No está en el IPC.')
        if p.usuario_id == actor.pk or p.estado == 'conforme':
            raise ErrorNegocio('No se puede quitar a quien ya confirmó.')
        p.delete()
        return self._responder(ipc, actor)

    @action(detail=True, methods=['post'])
    def confirmar(self, request, pk=None):
        """POST /api/ipcs/{id}/confirmar/ — el participante, desde su app."""
        actor = self._actor(request)
        p = (IPCParticipante.objects.select_related('ipc')
             .filter(ipc_id=pk, usuario=actor).first())
        if p is None:
            raise PermissionDenied('No estás en este IPC.')
        if p.ipc.estado != 'abierto':
            raise ErrorNegocio('El IPC ya está cerrado.')
        if p.estado != 'conforme':
            p.estado = 'conforme'
            p.metodo = IPCParticipante.METODO_APP
            p.confirmado = timezone.now()
            p.save(update_fields=['estado', 'metodo', 'confirmado'])
        return self._responder(p.ipc, actor)

    @action(detail=True, methods=['post'])
    def firmar_en_equipo(self, request, pk=None):
        """POST /api/ipcs/{id}/firmar_en_equipo/ {usuario, firma (PNG base64)}

        Plan B: el participante sin celular firma con el dedo en el equipo del
        responsable. En el PDF queda indicado."""
        import base64
        import binascii
        actor, ipc = self._mio_editable(request, pk)
        p = ipc.participantes.filter(usuario_id=request.data.get('usuario')).first()
        if p is None:
            raise ErrorNegocio('No está en el IPC.')
        if p.estado == 'conforme':
            raise ErrorNegocio('Ya confirmó.')
        try:
            firma = base64.b64decode(request.data.get('firma') or '', validate=True)
        except (binascii.Error, ValueError):
            firma = b''
        try:
            from PIL import Image as _Imagen
            _Imagen.open(io.BytesIO(firma)).verify()
            valida = firma.startswith(b'\x89PNG')
        except Exception:
            valida = False
        if not valida:
            raise ErrorNegocio('La firma no se pudo leer.')
        if len(firma) > self.FIRMA_MAXIMA:
            raise ErrorNegocio('La firma es muy pesada.')
        p.firma = firma
        p.estado = 'conforme'
        p.metodo = IPCParticipante.METODO_EQUIPO
        p.confirmado = timezone.now()
        p.save(update_fields=['firma', 'estado', 'metodo', 'confirmado'])
        return self._responder(ipc, actor)

    @action(detail=True, methods=['post'])
    def cerrar(self, request, pk=None):
        """POST /api/ipcs/{id}/cerrar/ {observaciones?}

        (17) Observaciones y hora de cierre del frente de trabajo. Se puede
        cerrar el día siguiente si quedó abierto, pero ya no se le suma nada."""
        from ..ipc_formato import OBSERVACION_POR_DEFECTO
        actor = self._actor(request)
        ipc = IPC.objects.filter(pk=pk, responsable=actor).first()
        if ipc is None:
            raise PermissionDenied('Solo el responsable cierra su IPC.')
        if ipc.estado != 'abierto':
            raise ErrorNegocio('El IPC ya está cerrado.')
        ipc.observaciones = ((request.data.get('observaciones') or '').strip()
                             or OBSERVACION_POR_DEFECTO)[:3000]
        ipc.hora_cierre = timezone.localtime().time().replace(microsecond=0)
        ipc.estado = 'cerrado'
        ipc.save(update_fields=['observaciones', 'hora_cierre', 'estado'])
        return self._responder(ipc, actor)

    @action(detail=False, methods=['get'])
    def cubre(self, request):
        """GET /api/ipcs/cubre/?sst=<código>

        Si la SST está en un IPC de hoy del actor (como responsable o
        participante). La liquidación lo usa para avisar, no para bloquear."""
        actor = self._actor(request)
        codigo = (request.query_params.get('sst') or '').strip()
        cubre = IPCSST.objects.filter(
            models.Q(codigo__iexact=codigo) | models.Q(sst__codigo=codigo) |
            models.Q(sst__sst=codigo),
            ipc__fecha=timezone.localdate()).filter(
            models.Q(ipc__responsable=actor) |
            models.Q(ipc__participantes__usuario=actor)).exists() if codigo else False
        return Response({'sst': codigo, 'cubierta': cubre})

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        """GET /api/ipcs/{id}/pdf/ — el formato F01-IA-SMAC-003 lleno."""
        from django.http import HttpResponse
        from ..ipc_pdf import generar_pdf_ipc
        actor = self._actor(request)
        ipc = self._con_todo(self._visibles(actor)).filter(pk=pk).first()
        if ipc is None:
            return Response({'detail': 'No existe.'}, status=404)
        resp = HttpResponse(generar_pdf_ipc(ipc), content_type='application/pdf')
        resp['Content-Disposition'] = (
            f'attachment; filename="IPC_{ipc.fecha:%Y%m%d}_{ipc.pk}.pdf"')
        return resp
