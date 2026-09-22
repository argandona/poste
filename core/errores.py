"""Errores de negocio que la app entiende.

Vive aparte de las vistas para que los serializers también puedan lanzarlo sin
importar `views` y armar un ciclo.
"""
from rest_framework import status
from rest_framework.exceptions import APIException


class ErrorNegocio(APIException):
    """Error de regla de negocio dentro de un bloque transaccional.

    Devolver un `Response` desde dentro de un `transaction.atomic()` sale del
    bloque sin excepción, así que la transacción COMMITEA lo hecho hasta ahí:
    un pedido de varios materiales podía descontar los primeros y responder 400
    por el último. Lanzar esta excepción aborta la transacción y responde 400
    con la forma `{"detail": "<texto>"}` — string plano, que es lo que espera
    la app Flutter en api_service.dart.
    """
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Operación inválida.'
