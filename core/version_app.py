"""Versiones de la app y el aviso de actualización.

Pedido del usuario el 2026-10-14: que la app avise sola cuando hay una versión
nueva y se actualice desde ahí, sin pasar el APK a mano. El APK vive en
Firebase Storage; aquí solo se guarda su enlace.

- El SuperAdmin registra cada versión: código (el +N del pubspec), nombre,
  enlace del APK, notas y si es obligatoria.
- `GET version-app/ultima/` lo consulta la app al abrir, incluso antes de
  iniciar sesión: devuelve la última versión y `minima`, el código de la
  obligatoria más nueva. Si el celular tiene menos que `minima`, no sigue.
"""
from django.db.models import Max
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .models import Usuario, VersionApp


class VersionAppSerializer(serializers.ModelSerializer):
    usuario_nombre = serializers.CharField(source='usuario.nombre', read_only=True)

    class Meta:
        model = VersionApp
        fields = ['id_version', 'codigo', 'nombre', 'url_apk', 'notas',
                  'obligatoria', 'usuario_nombre', 'fecha_hora']
        read_only_fields = ['id_version', 'usuario_nombre', 'fecha_hora']

    def validate_url_apk(self, valor):
        if not valor.lower().startswith('https://'):
            raise serializers.ValidationError('El enlace debe empezar con https://')
        return valor


def ultima_version():
    """Lo que la app necesita para decidir si avisa: la última y la mínima."""
    ultima = VersionApp.objects.order_by('-codigo').first()
    if ultima is None:
        return {}
    minima = (VersionApp.objects.filter(obligatoria=True)
              .aggregate(m=Max('codigo'))['m']) or 0
    return {**VersionAppSerializer(ultima).data, 'minima': minima}


class VersionAppViewSet(viewsets.ModelViewSet):
    """El SuperAdmin lista, registra y borra versiones; cualquiera, incluso sin
    sesión, pregunta por la última."""
    serializer_class = VersionAppSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ['get', 'post', 'delete']
    pagination_class = None
    queryset = VersionApp.objects.select_related('usuario')

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.action != 'ultima':
            actor = Usuario.objects.filter(pk=request.user.id_usuario).first()
            if not (actor and actor.es_superadmin()):
                raise PermissionDenied('Solo el SuperAdmin publica versiones de la app.')

    def perform_create(self, serializer):
        serializer.save(usuario_id=self.request.user.id_usuario)

    # Sin autenticación: con un token vencido igual tiene que contestar, para
    # que la app vieja se entere de que debe actualizar.
    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny],
            authentication_classes=[])
    def ultima(self, request):
        return Response(ultima_version())
