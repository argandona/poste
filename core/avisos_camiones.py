"""Avisos de las salidas del camión, a una hora del día (pedido del
2026-10-30).

- Desde las 9:00, de lunes a viernes: al coordinador de cada empresa (y al
  SuperAdmin), los camiones activos que hoy no registraron salida y las
  salidas de días anteriores que siguen sin cerrar. Uno por empresa y día.
- Desde las 19:00, todos los días: al chofer que salió hoy y no cerró, que
  cierre el km o diga que se queda hasta más tarde. Uno por salida. Si dijo
  que se queda, no se le avisa; si al día siguiente sigue abierta, la ve el
  coordinador en el aviso de la mañana.

Lo llama cada media hora un reloj de GitHub (POST avisos-camiones/ con la
clave de AVISOS_CAMIONES_TOKEN) o el comando revisar_avisos_camiones. Se
puede llamar las veces que sea: lo ya avisado no se repite.
"""
import hmac
import os

from django.utils import timezone
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

HORA_SIN_SALIDA = 9
HORA_CIERRE = 19
# Lunes a viernes (weekday 0 a 4). El cierre se avisa todos los días.
DIAS_SIN_SALIDA = range(0, 5)
MAX_EN_TEXTO = 6


def _lista(textos):
    texto = ', '.join(textos[:MAX_EN_TEXTO])
    if len(textos) > MAX_EN_TEXTO:
        texto += f' y {len(textos) - MAX_EN_TEXTO} más'
    return texto


def revisar(ahora=None):
    """Manda lo que toque a esta hora. Devuelve cuántos avisos salieron."""
    ahora = timezone.localtime(ahora or timezone.now())
    hoy = ahora.date()
    salieron = {'cierre': 0, 'sin_salida': 0}
    if ahora.hour >= HORA_CIERRE:
        salieron['cierre'] = avisar_cierres(hoy, ahora)
    if ahora.hour >= HORA_SIN_SALIDA and hoy.weekday() in DIAS_SIN_SALIDA:
        salieron['sin_salida'] = avisar_sin_salida(hoy)
    return salieron


def avisar_cierres(hoy, ahora):
    """Al chofer de cada salida de hoy que sigue abierta, una sola vez."""
    from .fcm import send_notification
    from .models import JornadaCamion

    pendientes = (JornadaCamion.objects
                  .filter(fecha=hoy, km_cierre__isnull=True,
                          aviso_cierre__isnull=True, se_queda_tarde__isnull=True)
                  .select_related('camion', 'chofer'))
    enviados = 0
    for j in pendientes:
        # Se marca antes de mandar y solo si nadie la marcó: dos llamadas a la
        # vez no avisan dos veces.
        if not JornadaCamion.objects.filter(
                pk=j.pk, aviso_cierre__isnull=True).update(aviso_cierre=ahora):
            continue
        if not j.chofer.fcm_token:
            continue
        salida = timezone.localtime(j.hora_salida).strftime('%H:%M')
        send_notification(
            [j.chofer.fcm_token], title='Cierra tu salida',
            body=(f'{j.camion.placa} sigue en ruta desde las {salida}. Registra '
                  'el km de cierre o indica que te quedas hasta más tarde.'),
            data={'tipo': 'cerrar_salida', 'jornada_id': str(j.pk)})
        enviados += 1
    return enviados


def texto_sin_salida(sin_salida, abiertas):
    """El cuerpo del aviso de la mañana. [sin_salida]: placas; [abiertas]:
    salidas de días anteriores sin cerrar."""
    partes = []
    if sin_salida:
        partes.append(f'No registraron salida: {_lista(sin_salida)}.')
    if abiertas:
        partes.append('Sin cerrar de días anteriores: ' + _lista([
            f'{j.camion.placa} ({j.chofer.nombre}, {j.fecha:%d/%m})'
            for j in abiertas]) + '.')
    return ' '.join(partes)


def avisar_sin_salida(hoy):
    """Al coordinador de cada empresa con camiones, una vez al día."""
    from .camiones import _avisar
    from .models import AvisoSinSalida, Camion, JornadaCamion

    enviados = 0
    empresas = (Camion.objects.filter(activo=True)
                .values_list('empresa_id', flat=True).distinct())
    for empresa_id in empresas:
        _, nuevo = AvisoSinSalida.objects.get_or_create(
            empresa_id=empresa_id, fecha=hoy)
        if not nuevo:
            continue
        abiertas = list(JornadaCamion.objects
                        .filter(camion__empresa_id=empresa_id,
                                km_cierre__isnull=True, fecha__lt=hoy)
                        .select_related('camion', 'chofer')
                        .order_by('fecha', 'camion__placa'))
        # Un camión que sigue en una salida de ayer no "dejó de salir" hoy:
        # va en la otra lista.
        en_ruta = {j.camion_id for j in abiertas}
        salieron = set(JornadaCamion.objects.filter(fecha=hoy)
                       .values_list('camion_id', flat=True))
        sin_salida = list(Camion.objects
                          .filter(empresa_id=empresa_id, activo=True)
                          .exclude(pk__in=salieron | en_ruta)
                          .order_by('placa').values_list('placa', flat=True))
        if not sin_salida and not abiertas:
            continue
        titulo = ('Camiones sin salida hoy' if sin_salida
                  else 'Salidas sin cerrar')
        _avisar(empresa_id, titulo, texto_sin_salida(sin_salida, abiertas),
                {'tipo': 'camiones_sin_salida'})
        enviados += 1
    return enviados


class AvisosCamionesView(APIView):
    """POST /api/avisos-camiones/ con la cabecera X-Avisos-Token. Lo llama el
    reloj de GitHub; no es de ningún usuario, así que no lleva sesión. Sin la
    variable AVISOS_CAMIONES_TOKEN en el servidor, no corre."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        clave = os.environ.get('AVISOS_CAMIONES_TOKEN', '')
        dada = request.headers.get('X-Avisos-Token', '')
        if not clave or not hmac.compare_digest(clave, dada):
            raise PermissionDenied('Clave de avisos inválida.')
        return Response(revisar())
