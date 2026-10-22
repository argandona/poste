"""Empresas, roles y usuarios."""
from .comun import *  # noqa: F401,F403


# ── Empresa ─────────────────────────────────────────────────────────────────
class EmpresaViewSet(viewsets.ModelViewSet):
    """Las empresas. Cada uno ve la suya (el SuperAdmin, todas); crearlas y
    editarlas, solo el SuperAdmin. No se borran: se desactivan, porque sus
    usuarios, camiones y almacenes las nombran."""
    serializer_class   = EmpresaSerializer
    queryset           = Empresa.objects.order_by('nombre')
    permission_classes = [permissions.IsAuthenticated]
    http_method_names  = ['get', 'post', 'put', 'patch', 'head', 'options']

    def _solo_superadmin(self, request):
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        if not (actor and actor.es_superadmin()):
            raise PermissionDenied('Solo el SuperAdmin gestiona empresas.')

    def create(self, request, *args, **kwargs):
        self._solo_superadmin(request)
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        self._solo_superadmin(request)
        return super().update(request, *args, **kwargs)

    def get_queryset(self):
        return qs_empresa(super().get_queryset(), self.request, 'id_empresa')


# ── Rol ─────────────────────────────────────────────────────────────────────
class RolViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class   = RolSerializer
    queryset           = Rol.objects.all()
    permission_classes = [permissions.IsAuthenticated]


# ── Usuario ─────────────────────────────────────────────────────────────────
class UsuarioViewSet(viewsets.ModelViewSet):
    """Los usuarios. Verlos puede cualquiera con sesión (se eligen en varias
    pantallas); crearlos, editarlos y restablecer claves, solo el SuperAdmin.
    No se borran: se desactivan, porque sus pedidos y liquidaciones los
    nombran."""
    permission_classes = [permissions.IsAuthenticated]
    # Con operarios y ayudantes pasan de 20: una sola página.
    pagination_class   = CatalogoPagination
    http_method_names  = ['get', 'post', 'put', 'patch', 'head', 'options']

    def _solo_superadmin(self, request):
        actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
        if not (actor and actor.puede_gestionar_usuarios()):
            raise PermissionDenied('Solo el SuperAdmin gestiona usuarios.')

    def create(self, request, *args, **kwargs):
        self._solo_superadmin(request)
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        self._solo_superadmin(request)
        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def resetear_clave(self, request, pk=None):
        """POST /api/usuarios/{id}/resetear_clave/  {clave}"""
        self._solo_superadmin(request)
        from ..security import hashear_clave
        usuario = self.get_object()
        clave = request.data.get('clave') or ''
        if len(clave) < 6:
            raise ErrorNegocio('La clave debe tener al menos 6 caracteres.')
        usuario.clave = hashear_clave(clave)
        usuario.save(update_fields=['clave'])
        return Response({'detail': f'Clave de {usuario.nombre} restablecida.'})

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return UsuarioCreateSerializer
        return UsuarioSerializer

    def get_queryset(self):
        return qs_empresa(Usuario.objects.select_related('rol','empresa')
                          .order_by('nombre'), self.request)

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
