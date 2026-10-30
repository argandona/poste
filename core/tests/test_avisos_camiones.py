"""
Avisos de las salidas del camión (core/avisos_camiones.py): al coordinador,
de lunes a viernes desde las 9:00, los camiones que no salieron y las salidas
sin cerrar; al chofer, desde las 19:00, que cierre o diga que se queda.
"""
import io
from datetime import date, datetime, timedelta
from unittest import mock

from django.core.management import call_command
from django.utils import timezone

from ..avisos_camiones import revisar
from ..models import AvisoSinSalida, Camion, JornadaCamion, Rol, Usuario
from .base import BaseAPITestCase

JUEVES = date(2026, 10, 29)
SABADO = date(2026, 10, 31)


def a_las(dia, hora, minuto=0):
    return timezone.make_aware(datetime(dia.year, dia.month, dia.day, hora, minuto))


class AvisosCamionesTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        call_command('configurar_camiones', stdout=io.StringIO())
        self.chofer = Usuario.objects.create(
            nombre='Carlos Chofer', email='chofer@x.com', clave='x',
            empresa=self.empresa, fcm_token='tok-chofer',
            rol=Rol.objects.get(id_rol=Rol.CHOFER))
        self.coordinador = Usuario.objects.create(
            nombre='Coordinadora', email='coord@x.com', clave='x',
            empresa=self.empresa, fcm_token='tok-coord',
            rol=Rol.objects.create(id_rol=Rol.COORDINADOR, descripcion='Coordinador'))
        self.camion2 = Camion.objects.create(empresa=self.empresa, placa='CXN-208')

    def salida(self, camion=None, fecha=JUEVES, cerrada=False, **datos):
        return JornadaCamion.objects.create(
            camion=camion or self.camion, chofer=self.chofer, fecha=fecha,
            km_salida=1000, foto_salida='f.jpg',
            km_cierre=1050 if cerrada else None, **datos)

    def revisar_a(self, momento):
        with mock.patch('core.fcm.send_notification') as avisar:
            r = revisar(momento)
        return r, avisar

    @staticmethod
    def textos(avisar):
        return [(c.kwargs['title'], c.kwargs['body']) for c in avisar.call_args_list]

    # ── Cierre ────────────────────────────────────────────────────────────

    def test_a_las_7_pm_se_le_pide_cerrar_al_chofer(self):
        self.salida()
        r, avisar = self.revisar_a(a_las(JUEVES, 19, 5))
        self.assertEqual(r['cierre'], 1)
        tokens = avisar.call_args_list[0].args[0]
        self.assertEqual(tokens, ['tok-chofer'])
        titulo, cuerpo = self.textos(avisar)[0]
        self.assertEqual(titulo, 'Cierra tu salida')
        self.assertIn(self.camion.placa, cuerpo)
        self.assertEqual(avisar.call_args_list[0].kwargs['data']['tipo'], 'cerrar_salida')

    def test_antes_de_las_7_no(self):
        self.salida()
        r, avisar = self.revisar_a(a_las(JUEVES, 18, 50))
        self.assertEqual(r['cierre'], 0)

    def test_el_aviso_de_cierre_va_una_sola_vez(self):
        self.salida()
        self.revisar_a(a_las(JUEVES, 19, 5))
        r, _ = self.revisar_a(a_las(JUEVES, 19, 35))
        self.assertEqual(r['cierre'], 0)

    def test_si_dijo_que_se_queda_no_se_le_avisa(self):
        self.salida(se_queda_tarde=a_las(JUEVES, 18, 30))
        r, _ = self.revisar_a(a_las(JUEVES, 19, 5))
        self.assertEqual(r['cierre'], 0)

    def test_la_salida_cerrada_no_se_avisa(self):
        self.salida(cerrada=True)
        r, _ = self.revisar_a(a_las(JUEVES, 20, 0))
        self.assertEqual(r['cierre'], 0)

    def test_el_cierre_se_avisa_tambien_el_sabado(self):
        self.salida(fecha=SABADO)
        r, _ = self.revisar_a(a_las(SABADO, 19, 5))
        self.assertEqual(r['cierre'], 1)

    # ── Me quedo más tarde ────────────────────────────────────────────────

    def test_el_chofer_dice_que_se_queda(self):
        j = self.salida(fecha=timezone.localdate())
        self.auth(self.chofer)
        r = self.client.post(f'/api/jornadas-camion/{j.pk}/me_quedo/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNotNone(r.json()['se_queda_tarde'])
        j.refresh_from_db()
        self.assertIsNotNone(j.se_queda_tarde)

    def test_solo_el_chofer_de_la_salida(self):
        j = self.salida()
        self.auth(self.coordinador)
        r = self.client.post(f'/api/jornadas-camion/{j.pk}/me_quedo/')
        self.assertEqual(r.status_code, 403)

    # ── Sin salida, al coordinador ────────────────────────────────────────

    def test_a_las_9_el_coordinador_ve_los_que_no_salieron(self):
        self.salida()  # el camión de la base salió; CXN-208 no
        r, avisar = self.revisar_a(a_las(JUEVES, 9, 5))
        self.assertEqual(r['sin_salida'], 1)
        titulo, cuerpo = self.textos(avisar)[0]
        self.assertEqual(titulo, 'Camiones sin salida hoy')
        self.assertIn('CXN-208', cuerpo)
        self.assertNotIn(self.camion.placa, cuerpo)
        self.assertIn('tok-coord', avisar.call_args_list[0].args[0])

    def test_antes_de_las_9_no(self):
        r, _ = self.revisar_a(a_las(JUEVES, 8, 35))
        self.assertEqual(r['sin_salida'], 0)

    def test_sabado_y_domingo_no(self):
        r, _ = self.revisar_a(a_las(SABADO, 9, 5))
        self.assertEqual(r['sin_salida'], 0)
        r, _ = self.revisar_a(a_las(SABADO + timedelta(days=1), 9, 5))
        self.assertEqual(r['sin_salida'], 0)

    def test_una_vez_al_dia(self):
        self.revisar_a(a_las(JUEVES, 9, 5))
        r, _ = self.revisar_a(a_las(JUEVES, 9, 35))
        self.assertEqual(r['sin_salida'], 0)
        self.assertEqual(AvisoSinSalida.objects.count(), 1)

    def test_la_salida_sin_cerrar_de_ayer_va_aparte(self):
        self.salida(fecha=JUEVES - timedelta(days=1))
        _, avisar = self.revisar_a(a_las(JUEVES, 9, 5))
        _, cuerpo = self.textos(avisar)[0]
        self.assertIn('Sin cerrar de días anteriores', cuerpo)
        self.assertIn(f'{self.camion.placa} (Carlos Chofer, 28/10)', cuerpo)
        # El camión que sigue en ruta desde ayer no cuenta como "no salió".
        self.assertEqual(cuerpo.count(self.camion.placa), 1)

    def test_si_todos_salieron_no_se_avisa(self):
        self.salida()
        self.salida(camion=self.camion2)
        r, avisar = self.revisar_a(a_las(JUEVES, 9, 5))
        self.assertEqual(r['sin_salida'], 0)
        avisar.assert_not_called()

    def test_el_camion_de_baja_no_cuenta(self):
        self.salida()
        self.camion2.activo = False
        self.camion2.save()
        r, _ = self.revisar_a(a_las(JUEVES, 9, 5))
        self.assertEqual(r['sin_salida'], 0)

    # ── El reloj ──────────────────────────────────────────────────────────

    def test_sin_clave_no_corre(self):
        self.client.credentials()
        with mock.patch.dict('os.environ', {'AVISOS_CAMIONES_TOKEN': 'secreta'}):
            r = self.client.post('/api/avisos-camiones/')
            self.assertEqual(r.status_code, 403)
            r = self.client.post('/api/avisos-camiones/',
                                 HTTP_X_AVISOS_TOKEN='otra')
            self.assertEqual(r.status_code, 403)

    def test_sin_clave_en_el_servidor_tampoco(self):
        with mock.patch.dict('os.environ', {}, clear=False):
            import os
            os.environ.pop('AVISOS_CAMIONES_TOKEN', None)
            r = self.client.post('/api/avisos-camiones/', HTTP_X_AVISOS_TOKEN='')
            self.assertEqual(r.status_code, 403)

    def test_con_la_clave_revisa(self):
        self.client.credentials()
        with mock.patch.dict('os.environ', {'AVISOS_CAMIONES_TOKEN': 'secreta'}), \
                mock.patch('core.fcm.send_notification'):
            r = self.client.post('/api/avisos-camiones/',
                                 HTTP_X_AVISOS_TOKEN='secreta')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(set(r.json()), {'cierre', 'sin_salida'})
