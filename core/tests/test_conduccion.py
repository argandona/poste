"""Formato de Conducción: el chofer lo llena cada día después de su IPC,
empieza con una SST y le suma las demás; si un control sale No, avisa al
responsable del camión y al coordinador y deja seguir."""
from unittest import mock

from django.utils import timezone

from ..models import (
    Conduccion, IPC, JornadaCamion, Rol, SST, SSTEncargado, Usuario,
)
from .base import BaseAPITestCase

URL = '/api/conducciones/'
TODO_SI = {c: 'si' for c in ('plan', 'en_forma', 'normas', 'documentos',
                             'inspeccion', 'objetos', 'cinturon', 'distracciones')}


class ConduccionTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.chofer = Usuario.objects.create(
            nombre='Chofer Uno', email='chofer@tecsur.pe', clave='x', empresa=self.empresa,
            fcm_token='tok-chofer',
            rol=Rol.objects.create(id_rol=Rol.CHOFER, descripcion='Chofer'))
        self.coordinador = Usuario.objects.create(
            nombre='Coordinador', email='coord@tecsur.pe', clave='x', empresa=self.empresa,
            fcm_token='tok-coord',
            rol=Rol.objects.create(id_rol=Rol.COORDINADOR, descripcion='Coordinador'))
        self.capataz.fcm_token = 'tok-capataz'
        self.capataz.save()
        # El camión ABC-123 es del capataz (base); el chofer salió con él.
        JornadaCamion.objects.create(camion=self.camion, chofer=self.chofer,
                                     responsable=self.capataz,
                                     fecha=timezone.localdate(), km_salida=1000,
                                     foto_salida='x.jpg')
        self.sst = SST.objects.create(empresa=self.empresa, codigo='SST-1')
        SSTEncargado.objects.create(sst=self.sst, usuario=self.capataz)

    def ipc_del_chofer(self):
        self.auth(self.chofer)
        with mock.patch('core.fcm.send_notification'):
            r = self.client.post('/api/ipcs/', {
                'tarea': 'Traslado de personal y materiales',
                'ssts': [{'sst': self.sst.pk}], 'centro_medico': 'Clínica'},
                format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def crear(self, controles=None, **datos):
        self.auth(self.chofer)
        cuerpo = {'controles': controles or TODO_SI, 'sst': self.sst.pk, **datos}
        with mock.patch('core.fcm.send_notification') as avisar:
            r = self.client.post(URL, cuerpo, format='json')
        return r, avisar

    @staticmethod
    def tokens(avisar):
        return sorted(t for c in avisar.call_args_list for t in c.args[0])

    def test_el_chofer_hace_su_ipc(self):
        d = self.ipc_del_chofer()
        self.assertEqual(d['responsable_nombre'], 'Chofer Uno')
        self.assertEqual([s['sst'] for s in d['ssts']], ['SST-1'])

    def test_sin_ipc_de_hoy_no_se_llena(self):
        r, _ = self.crear()
        self.assertEqual(r.status_code, 400)
        self.assertIn('Primero haz tu IPC', r.json()['detail'])
        self.auth(self.chofer)
        self.assertIsNone(self.client.get(f'{URL}hoy/').json()['ipc_de_hoy'])

    def test_le_ofrece_el_camion_y_las_sst_de_su_responsable(self):
        self.auth(self.chofer)
        d = self.client.get(f'{URL}ssts/').json()
        self.assertEqual((d['camion_placa'], d['responsable_nombre']),
                         ('ABC-123', 'Capataz Uno'))
        self.assertEqual([s['codigo'] for s in d['ssts']], ['SST-1'])

    def test_todo_si_crea_la_de_hoy_sin_avisar(self):
        ipc = self.ipc_del_chofer()
        r, avisar = self.crear()
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual((d['camion_placa'], d['cargo'], d['ipc']),
                         ('ABC-123', 'Chofer', ipc['id_ipc']))
        self.assertEqual([s['sst'] for s in d['ssts']], ['SST-1'])
        self.assertEqual(d['controles_en_no'], [])
        avisar.assert_not_called()
        self.auth(self.chofer)
        self.assertEqual(self.client.get(f'{URL}hoy/').json()['conduccion']['id_conduccion'],
                         d['id_conduccion'])

    def test_un_no_avisa_al_responsable_y_al_coordinador_y_deja_seguir(self):
        self.ipc_del_chofer()
        r, avisar = self.crear({**TODO_SI, 'cinturon': 'no'})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['controles_en_no'],
                         ['7. TODOS los ocupantes usan cinturón de seguridad.'])
        self.assertEqual(self.tokens(avisar), ['tok-capataz', 'tok-coord'])
        self.assertIn('Chofer Uno (ABC-123) marcó No en: 7.',
                      avisar.call_args.kwargs['body'])

    def test_faltan_controles(self):
        self.ipc_del_chofer()
        r, _ = self.crear({'plan': 'si'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('falta: 2, 3', r.json()['detail'])

    def test_una_por_dia_y_se_suman_las_sst(self):
        self.ipc_del_chofer()
        r, _ = self.crear()
        cid = r.json()['id_conduccion']
        r, _ = self.crear()
        self.assertEqual(r.status_code, 400)
        self.assertIn('Ya tienes tu Conducción de hoy', r.json()['detail'])
        r = self.client.post(f'{URL}{cid}/agregar_sst/', {'codigo': 'sst-777'}, format='json')
        self.assertEqual([(s['sst'], s['manual']) for s in r.json()['ssts']],
                         [('SST-1', False), ('SST-777', True)])
        r = self.client.post(f'{URL}{cid}/agregar_sst/', {'sst': self.sst.pk}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_corregir_controles_solo_avisa_los_no_nuevos(self):
        self.ipc_del_chofer()
        r, _ = self.crear({**TODO_SI, 'objetos': 'no'})
        cid = r.json()['id_conduccion']
        url = f'{URL}{cid}/controles/'
        with mock.patch('core.fcm.send_notification') as avisar:
            r = self.client.post(url, {'controles': TODO_SI}, format='json')
        self.assertEqual(r.json()['controles_en_no'], [])
        avisar.assert_not_called()
        with mock.patch('core.fcm.send_notification') as avisar:
            self.client.post(url, {'controles': {**TODO_SI, 'plan': 'no'}}, format='json')
        self.assertIn('1. Se cuenta con plan', avisar.call_args.kwargs['body'])

    def test_quien_la_ve_y_quien_la_llena(self):
        self.ipc_del_chofer()
        r, _ = self.crear()
        cid = r.json()['id_conduccion']
        self.auth(self.capataz)
        self.assertEqual(self.client.post(URL, {'controles': TODO_SI}, format='json')
                         .status_code, 403)
        self.assertEqual(self.client.get(f'{URL}{cid}/').status_code, 404)
        self.auth(self.coordinador)
        self.assertEqual([c['id_conduccion'] for c in self.client.get(URL).json()], [cid])

    def test_pdf_con_varias_sst(self):
        self.ipc_del_chofer()
        r, _ = self.crear({**TODO_SI, 'normas': 'no'})
        cid = r.json()['id_conduccion']
        for i in range(13):
            self.client.post(f'{URL}{cid}/agregar_sst/', {'codigo': f'X-{i}'}, format='json')
        r = self.client.get(f'{URL}{cid}/pdf/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertEqual(Conduccion.objects.get(pk=cid).ssts.count(), 14)
        self.assertEqual(IPC.objects.filter(responsable=self.chofer).count(), 1)
