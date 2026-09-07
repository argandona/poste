from rest_framework_simplejwt.authentication import JWTAuthentication


class TokenUsuario:
    """Objeto inyectado en request.user con los datos del token."""
    is_authenticated = True

    def __init__(self, payload):
        self.id_usuario = payload.get('id_usuario')
        self.email      = payload.get('email')
        self.nombre     = payload.get('nombre')
        self.rol_id     = payload.get('rol_id')
        self.empresa_id = payload.get('empresa_id')


class CustomJWTAuthentication(JWTAuthentication):
    """Lee id_usuario del payload en lugar del user_id estándar de Django."""

    def get_user(self, validated_token):
        return TokenUsuario(validated_token)
