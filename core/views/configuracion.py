"""Configuración del Coordinador: actividades, mano de obra y tipos de trabajo."""
from .comun import *  # noqa: F401,F403


# ── Configuración (Coordinador): Actividad / TipoTrabajo / relaciones ─────────
def _solo_coordinador(request):
    """True si el usuario autenticado puede asignar/configurar (Coordinador o SuperAdmin)."""
    actor = Usuario.objects.filter(pk=getattr(request.user, 'id_usuario', None)).first()
    return bool(actor and actor.puede_asignar_sst())


class ActividadViewSet(viewsets.ModelViewSet):
    serializer_class   = ActividadSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Las actividades que ve quien pregunta: el encargado las suyas y el
        capataz las demás. Con ?para_usuario=<id>, quien asigna pide las que
        puede recibir ese usuario."""
        actor = Usuario.objects.filter(
            pk=getattr(self.request.user, 'id_usuario', None)).first()
        para = self.request.query_params.get('para_usuario')
        if para and actor and actor.puede_asignar_sst():
            destino = Usuario.objects.filter(pk=para).first()
            if destino is not None:
                return actividades_para(destino).order_by('nombre')
        return actividades_para(actor).order_by('nombre')

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
            # Dentro de una actividad manda el orden de obra, no el alfabético.
            from django.db.models import F
            qs = (qs.filter(actividades__actividad_id=actividad)
                    .annotate(_orden=F('actividades__orden'))
                    .order_by('_orden', 'nombre'))
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
