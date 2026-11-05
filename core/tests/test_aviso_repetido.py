"""
Un aviso llega una sola vez a cada celular, aunque el celular figure en dos
cuentas (pasó el 2026-11-02 con el aviso de camiones sin salida).
"""
import sys
import types
from unittest import mock

from .. import fcm
from ..models import Usuario
from .base import BaseAPITestCase


class AvisoRepetidoTests(BaseAPITestCase):

    def test_el_celular_queda_solo_en_la_cuenta_que_entro_ultima(self):
        self.capataz.fcm_token = 'tok-celular'
        self.capataz.save()
        self.auth(self.encargado)
        resp = self.client.post('/api/usuarios/fcm_token/',
                                {'token': 'tok-celular'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(Usuario.objects.get(pk=self.encargado.pk).fcm_token,
                         'tok-celular')
        self.assertIsNone(Usuario.objects.get(pk=self.capataz.pk).fcm_token)

    def test_un_token_repetido_se_manda_una_vez(self):
        messaging = types.SimpleNamespace(
            MulticastMessage=mock.MagicMock(), Notification=mock.MagicMock(),
            AndroidConfig=mock.MagicMock(),
            AndroidNotification=mock.MagicMock(),
            send_each_for_multicast=mock.MagicMock(
                return_value=types.SimpleNamespace(failure_count=0)))
        firebase = types.ModuleType('firebase_admin')
        firebase.messaging = messaging
        with mock.patch.object(fcm, '_init', return_value=True), \
                mock.patch.dict(sys.modules, {
                    'firebase_admin': firebase,
                    'firebase_admin.messaging': messaging}):
            fcm.send_notification(['tok-a', 'tok-b', 'tok-a', ''], 'T', 'C')
        self.assertEqual(messaging.MulticastMessage.call_args.kwargs['tokens'],
                         ['tok-a', 'tok-b'])
