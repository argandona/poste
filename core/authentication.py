"""
Autenticación JWT personalizada usando la tabla Usuario (no django.auth.User).
El token guarda: id_usuario, email, rol_id, empresa_id.
"""
from django.conf import settings
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from .models import Usuario
from .security import verificar_clave, migrar_clave_si_legacy, esta_bloqueado, registrar_intento_fallido, limpiar_intentos, intentos_restantes


class CustomRefreshToken(RefreshToken):
    """Agrega claims extra al token."""
    @classmethod
    def for_usuario(cls, usuario: Usuario):
        token = cls()
        token['id_usuario']  = usuario.id_usuario
        token['email']       = usuario.email
        token['nombre']      = usuario.nombre
        token['rol_id']      = usuario.rol_id
        token['empresa_id']  = usuario.empresa_id
        return token


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    clave = serializers.CharField(write_only=True)


class LoginView(APIView):
    """POST /api/auth/login/  →  { access, refresh, usuario }"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        clave = serializer.validated_data['clave']

        if esta_bloqueado(email):
            return Response(
                {'detail': 'Demasiados intentos fallidos. Intenta en 15 minutos.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            usuario = Usuario.objects.select_related('rol', 'empresa').get(
                email=email, activo=True
            )
        except Usuario.DoesNotExist:
            registrar_intento_fallido(email)
            return Response({'detail': 'Credenciales inválidas.'}, status=status.HTTP_401_UNAUTHORIZED)

        if not verificar_clave(clave, usuario.clave):
            restantes = intentos_restantes(email) - 1
            registrar_intento_fallido(email)
            msg = 'Credenciales inválidas.'
            if restantes <= 2 and restantes >= 0:
                msg += f' Te quedan {restantes} intento(s) antes del bloqueo.'
            return Response({'detail': msg}, status=status.HTTP_401_UNAUTHORIZED)

        limpiar_intentos(email)
        migrar_clave_si_legacy(usuario, clave)

        # Actualizar último acceso
        from django.utils import timezone
        usuario.ultimo_acceso = timezone.now()
        usuario.save(update_fields=['ultimo_acceso'])

        refresh = CustomRefreshToken.for_usuario(usuario)
        return Response({
            'access':  str(refresh.access_token),
            'refresh': str(refresh),
            'usuario': {
                'id_usuario':  usuario.id_usuario,
                'nombre':      usuario.nombre,
                'email':       usuario.email,
                'rol_id':      usuario.rol_id,
                'rol':         usuario.rol.descripcion,
                'empresa_id':  usuario.empresa_id,
                'empresa':     usuario.empresa.nombre if usuario.empresa else None,
            }
        })


class RefreshView(APIView):
    """POST /api/auth/refresh/  →  { access }"""
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'detail': 'refresh requerido.'}, status=400)
        try:
            token  = CustomRefreshToken(refresh_token)
            access = str(token.access_token)
            return Response({'access': access})
        except Exception:
            return Response({'detail': 'Token inválido o expirado.'}, status=401)



