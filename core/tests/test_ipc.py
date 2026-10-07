"""
IPC (Instrucción Previa en Campo): lo hace el capataz o encargado antes de
empezar; en el día le suma SST (nunca a uno de otro día); los participantes
confirman desde su app o firman en el equipo del responsable; al cerrar sale
el PDF del formato.
"""
import base64
import io
from datetime import date, timedelta
from unittest import mock

from django.core.management import call_command
from django.utils import timezone

from ..models import (IPC, SST, ContactoEmergencia, IPCParticipante, IPCSST,
                      Rol, Usuario)
from .base import BaseAPITestCase

URL = '/api/ipcs/'


def _png():
    from PIL import Image, ImageDraw
    im = Image.new('RGBA', (300, 100), (255, 255, 255, 0))
    ImageDraw.Draw(im).line([(10, 80), (120, 20), (290, 70)], fill='black', width=4)
    buffer = io.BytesIO()
    im.save(buffer, 'PNG')
    return base64.b64encode(buffer.getvalue()).decode()


# Una firma dibujada, como la manda la app.
PNG = _png()


class IPCTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        call_command('configurar_epp', stdout=io.StringIO())
        self.capataz.dni = '11112222'
        self.capataz.save()
        self.pedro = Usuario.objects.create(
            nombre='Pedro Operario', email='pedro@x.com', clave='x', dni='4567',
            empresa=self.empresa, fcm_token='tok-pedro',
            rol=Rol.objects.get(id_rol=Rol.OPERARIO))
        self.coord = Usuario.objects.create(
            nombre='Coordinadora', email='coord@x.com', clave='x',
            empresa=self.empresa,
            rol=Rol.objects.create(id_rol=Rol.COORDINADOR, descripcion='Coordinador'))
        self.sst1 = SST.objects.create(sst='1', codigo='SST-1', empresa=self.empresa,
                                       distrito='SURCO')
        self.sst2 = SST.objects.create(sst='2', codigo='SST-2', empresa=self.empresa)
        ContactoEmergencia.objects.create(
            empresa=self.empresa, superior_nombre='Jefe Uno',
            superior_telefono='999111222', centro_medico='Clínica Sur')

    def crear(self, **datos):
        self.auth(self.capataz)
        cuerpo = {
            'tarea': 'Reforzamiento de poste',
            'coordinador': self.coord.pk,
            'ssts': [{'sst': self.sst1.pk, 'direccion': 'Av. Sol 123'}],
            'participantes': [self.pedro.pk],
            'datos': {
                'epp': ['casco', 'guantes', 'inventado'],
                'peligros_criticos': ['electrico'],
                'etapas': ['Señalizar', 'Excavar', ''],
                'factores': {'capaz': 'si', 'estresado': 'si'},
                'energias': {'electrico': {'peligros': ['conductor_aereo', 'x'],
                                           'tareas': 'Reforzar', 'medidas': 'Guantes dieléctricos'}},
            },
            **datos}
        with mock.patch('core.fcm.send_notification') as avisar:
            r = self.client.post(URL, cuerpo, format='json')
        return r, avisar

    # ── Crear ────────────────────────────────────────────────────────────────

    def test_el_capataz_lo_crea_y_avisa_a_la_cuadrilla(self):
        r, avisar = self.crear()
        self.assertEqual(r.status_code, 201, r.content)
        d = r.json()
        self.assertEqual((d['fecha'], d['estado'], d['tarea']),
                         (str(timezone.localdate()), 'abierto', 'Reforzamiento de poste'))
        self.assertEqual([s['sst'] for s in d['ssts']], ['SST-1'])
        # Lo que el formato no conoce no se guarda.
        self.assertEqual(d['datos']['epp'], ['casco', 'guantes'])
        self.assertEqual(d['datos']['etapas'], ['Señalizar', 'Excavar'])
        self.assertEqual(d['datos']['energias']['electrico']['peligros'],
                         ['conductor_aereo'])
        # Los contactos de emergencia se copian.
        self.assertEqual(d['datos']['emergencia']['superior_nombre'], 'Jefe Uno')
        # El responsable figura como participante, ya conforme; Pedro, pendiente.
        estados = {p['nombre']: (p['estado'], p['dni']) for p in d['participantes']}
        self.assertEqual(estados, {'Capataz Uno': ('conforme', '11112222'),
                                   'Pedro Operario': ('pendiente', '4567')})
        self.assertEqual(avisar.call_args.args[0], ['tok-pedro'])
        # "¿El empleado está estresado?" = sí es un factor de riesgo.
        self.assertEqual(len(d['factores_en_riesgo']), 1)

    def test_solo_capataces_y_encargados(self):
        for quien in (self.encargado, self.pedro, self.coord):
            self.auth(quien)
            r = self.client.post(URL, {'tarea': 'x', 'ssts': [{'sst': self.sst1.pk}]},
                                 format='json')
            self.assertEqual(r.status_code, 403, quien.email)

    def test_pide_tarea_y_al_menos_una_sst(self):
        self.assertEqual(self.crear(tarea='')[0].status_code, 400)
        self.assertEqual(self.crear(ssts=[])[0].status_code, 400)

    # ── Sumar SST el mismo día ───────────────────────────────────────────────

    def test_usar_el_de_hoy_conserva_las_ssts_y_suma_la_nueva(self):
        ipc_id = self.crear()[0].json()['id_ipc']
        self.assertEqual([i['id_ipc'] for i in self.client.get(f'{URL}hoy/').json()],
                         [ipc_id])
        r = self.client.post(f'{URL}{ipc_id}/agregar_sst/', {'sst': self.sst2.pk},
                             format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([s['sst'] for s in r.json()['ssts']], ['SST-1', 'SST-2'])
        r = self.client.post(f'{URL}{ipc_id}/agregar_sst/', {'sst': self.sst2.pk},
                             format='json')
        self.assertEqual(r.status_code, 400)

    def test_nunca_uno_de_otro_dia(self):
        ipc_id = self.crear()[0].json()['id_ipc']
        IPC.objects.filter(pk=ipc_id).update(fecha=date.today() - timedelta(days=1))
        self.assertEqual(self.client.get(f'{URL}hoy/').json(), [])
        r = self.client.post(f'{URL}{ipc_id}/agregar_sst/', {'sst': self.sst2.pk},
                             format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('genera uno nuevo', r.json()['detail'])

    # ── Confirmar y firmar ───────────────────────────────────────────────────

    def test_el_participante_confirma_desde_su_app(self):
        ipc_id = self.crear()[0].json()['id_ipc']
        self.auth(self.pedro)
        por_confirmar = self.client.get(URL, {'por_confirmar': 1}).json()
        self.assertEqual([i['id_ipc'] for i in por_confirmar], [ipc_id])
        r = self.client.post(f'{URL}{ipc_id}/confirmar/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['mi_estado'], 'conforme')
        p = IPCParticipante.objects.get(ipc_id=ipc_id, usuario=self.pedro)
        self.assertEqual(p.metodo, 'app')
        self.assertEqual(self.client.get(URL, {'por_confirmar': 1}).json(), [])

    def test_quien_no_participa_no_confirma(self):
        ipc_id = self.crear()[0].json()['id_ipc']
        self.auth(self.encargado)
        self.assertEqual(self.client.post(f'{URL}{ipc_id}/confirmar/').status_code, 403)

    def test_plan_b_firma_en_el_equipo_del_responsable(self):
        ipc_id = self.crear()[0].json()['id_ipc']
        r = self.client.post(f'{URL}{ipc_id}/firmar_en_equipo/',
                             {'usuario': self.pedro.pk, 'firma': PNG}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        p = IPCParticipante.objects.get(ipc_id=ipc_id, usuario=self.pedro)
        self.assertEqual((p.estado, p.metodo), ('conforme', 'equipo'))
        r = self.client.post(f'{URL}{ipc_id}/firmar_en_equipo/',
                             {'usuario': self.pedro.pk, 'firma': 'no-es-png'},
                             format='json')
        self.assertEqual(r.status_code, 400)

    def test_agregar_y_quitar_participante(self):
        ipc_id = self.crear(participantes=[])[0].json()['id_ipc']
        with mock.patch('core.fcm.send_notification') as avisar:
            r = self.client.post(f'{URL}{ipc_id}/agregar_participante/',
                                 {'usuario': self.pedro.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(avisar.call_args.args[0], ['tok-pedro'])
        r = self.client.post(f'{URL}{ipc_id}/quitar_participante/',
                             {'usuario': self.pedro.pk}, format='json')
        self.assertEqual(len(r.json()['participantes']), 1)
        r = self.client.post(f'{URL}{ipc_id}/quitar_participante/',
                             {'usuario': self.capataz.pk}, format='json')
        self.assertEqual(r.status_code, 400)

    # ── Cerrar, ver y PDF ────────────────────────────────────────────────────

    def test_cerrar_con_la_observacion_por_defecto(self):
        ipc_id = self.crear()[0].json()['id_ipc']
        r = self.client.post(f'{URL}{ipc_id}/cerrar/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['estado'], 'cerrado')
        self.assertIn('concluyó con normalidad', r.json()['observaciones'])
        self.assertIsNotNone(r.json()['hora_cierre'])
        self.assertEqual(self.client.post(f'{URL}{ipc_id}/agregar_sst/',
                                          {'sst': self.sst2.pk}, format='json').status_code, 400)

    def test_quien_lo_ve(self):
        ipc_id = self.crear()[0].json()['id_ipc']
        for quien, ve in ((self.pedro, True), (self.coord, True), (self.encargado, False)):
            self.auth(quien)
            ids = [i['id_ipc'] for i in self.client.get(URL).json()]
            self.assertEqual(ipc_id in ids, ve, quien.email)

    def test_cubre_la_sst_de_hoy(self):
        self.crear()
        for quien in (self.capataz, self.pedro):
            self.auth(quien)
            self.assertTrue(self.client.get(f'{URL}cubre/', {'sst': 'SST-1'}).json()['cubierta'])
            self.assertFalse(self.client.get(f'{URL}cubre/', {'sst': 'SST-2'}).json()['cubierta'])

    def test_el_pdf(self):
        ipc_id = self.crear()[0].json()['id_ipc']
        self.client.post(f'{URL}{ipc_id}/firmar_en_equipo/',
                         {'usuario': self.pedro.pk, 'firma': PNG}, format='json')
        # Más de 8 SST: la novena va en la primera fila con guion.
        for i in range(3, 11):
            sst = SST.objects.create(sst=str(i), codigo=f'SST-{i}', empresa=self.empresa)
            self.client.post(f'{URL}{ipc_id}/agregar_sst/', {'sst': sst.pk}, format='json')
        self.client.post(f'{URL}{ipc_id}/cerrar/', {}, format='json')
        r = self.client.get(f'{URL}{ipc_id}/pdf/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertEqual(IPCSST.objects.filter(ipc_id=ipc_id).count(), 9)

    def test_formato_y_contactos(self):
        self.auth(self.pedro)
        f = self.client.get(f'{URL}formato/').json()
        self.assertEqual(f['codigo'], 'F01-IA-SMAC-003')
        self.assertEqual(sum(len(e['preguntas']) for e in f['energias']), 16)
        self.assertEqual(self.client.get(f'{URL}contacto_emergencia/').json()['centro_medico'],
                         'Clínica Sur')
        r = self.client.put(f'{URL}contacto_emergencia/', {'medico_nombre': 'X'},
                            format='json')
        self.assertEqual(r.status_code, 403)
