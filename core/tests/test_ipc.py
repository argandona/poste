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

    def _poste(self, sst, numero, estado):
        from ..models import SSTEncargado, SSTSuministro, Suministro
        SSTEncargado.objects.get_or_create(sst=sst, usuario=self.capataz)
        p = Suministro.objects.create(numero_suministro=numero, estado=estado)
        SSTSuministro.objects.create(sst=sst, suministro=p, asignado_a=self.capataz)

    def test_solo_se_ofrecen_las_sst_por_liquidar(self):
        sst3 = SST.objects.create(sst='3', codigo='SST-3', empresa=self.empresa)
        self._poste(self.sst1, 'P-1', 'ejecutado')   # ya liquidada
        self._poste(self.sst2, 'P-2', 'ejecutado')   # le falta un poste
        self._poste(self.sst2, 'P-3', 'asignado')
        from ..models import SSTEncargado
        SSTEncargado.objects.create(sst=sst3, usuario=self.capataz)  # sin postes aún
        self.auth(self.capataz)
        codigos = lambda **q: sorted(s['codigo'] for s in self.client.get(
            '/api/ssts/mis_sst/', {'usuario': self.capataz.pk, **q}).json())
        self.assertEqual(codigos(pendientes=1), ['SST-2', 'SST-3'])
        # Sin el filtro, como antes: todas.
        self.assertEqual(codigos(), ['SST-1', 'SST-2', 'SST-3'])

    def test_una_sst_liquidada_no_entra_a_un_ipc(self):
        self._poste(self.sst1, 'P-1', 'ejecutado')
        r, _ = self.crear()
        self.assertEqual(r.status_code, 400)
        self.assertIn('ya está liquidada', r.json()['detail'])
        r, _ = self.crear(ssts=[{'sst': self.sst2.pk}])
        self.assertEqual(r.status_code, 201, r.content)
        r = self.client.post(f"{URL}{r.json()['id_ipc']}/agregar_sst/",
                             {'sst': self.sst1.pk}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_etapas_de_plantilla_en_su_orden_y_mas_de_10(self):
        self.auth(self.capataz)
        [plantilla] = self.client.get(f'{URL}formato/').json()['plantillas_etapas']
        self.assertIn('reforzamiento de poste', plantilla['claves'])
        self.assertEqual(len(plantilla['etapas']), 9)
        # Las 9 marcadas más tres propias, una metida en medio: se guardan en
        # ese orden y el PDF les hace sitio.
        etapas = plantilla['etapas'][:4] + ['Retiro de poste viejo'] + \
            plantilla['etapas'][4:] + ['Extra 1', 'Extra 2']
        r, _ = self.crear(datos={'etapas': etapas})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['datos']['etapas'], etapas)
        pdf = self.client.get(f"{URL}{r.json()['id_ipc']}/pdf/")
        self.assertTrue(pdf.content.startswith(b'%PDF'))

    def test_una_sst_escrita_a_mano(self):
        r, _ = self.crear(ssts=[{'sst': self.sst1.pk},
                                {'codigo': ' sst-9000 ', 'direccion': 'Jr. Luna 5'}])
        self.assertEqual(r.status_code, 201, r.content)
        ssts = r.json()['ssts']
        self.assertEqual([(s['sst'], s['manual'], s['id_sst']) for s in ssts],
                         [('SST-1', False, self.sst1.pk), ('SST-9000', True, None)])
        ipc_id = r.json()['id_ipc']
        # No crea una SST en el sistema.
        self.assertFalse(SST.objects.filter(codigo__iexact='SST-9000').exists())
        # Repetida, aunque se escriba distinto, no entra.
        r = self.client.post(f'{URL}{ipc_id}/agregar_sst/', {'codigo': 'Sst-9000'},
                             format='json')
        self.assertEqual(r.status_code, 400)
        # Escribir el código de una SST que existe la enlaza (y ya estaba).
        r = self.client.post(f'{URL}{ipc_id}/agregar_sst/', {'codigo': 'sst-1'},
                             format='json')
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f'{URL}{ipc_id}/agregar_sst/', {'codigo': 'SST-2'},
                             format='json')
        self.assertEqual(r.json()['ssts'][-1]['id_sst'], self.sst2.pk)
        # Al liquidar la manual, el aviso sabe que tiene IPC.
        cubre = self.client.get(f'{URL}cubre/', {'sst': 'SST-9000'}).json()
        self.assertTrue(cubre['cubierta'])
        self.assertTrue(self.client.get(f'{URL}{ipc_id}/pdf/').content.startswith(b'%PDF'))

    def test_escribir_una_sst_ya_liquidada_tampoco_entra(self):
        self._poste(self.sst2, 'P-2', 'ejecutado')
        r, _ = self.crear(ssts=[{'codigo': 'SST-2'}])
        self.assertEqual(r.status_code, 400)
        r, _ = self.crear(ssts=[{'codigo': ''}])
        self.assertEqual(r.status_code, 400)

    def test_el_centro_medico_lo_escribe_el_responsable(self):
        r, _ = self.crear(centro_medico='  Hospital de Surco ')
        e = r.json()['datos']['emergencia']
        # Los teléfonos y el superior siguen siendo los del SuperAdmin.
        self.assertEqual((e['centro_medico'], e['superior_telefono']),
                         ('Hospital de Surco', '999111222'))
        ipc_id = r.json()['id_ipc']
        r = self.client.patch(f'{URL}{ipc_id}/', {'centro_medico': 'Clínica Norte'},
                              format='json')
        e = r.json()['datos']['emergencia']
        self.assertEqual((e['centro_medico'], e['superior_nombre']),
                         ('Clínica Norte', 'Jefe Uno'))
        # Cambiar el formato no borra lo de emergencia.
        r = self.client.patch(f'{URL}{ipc_id}/', {'datos': {'epp': ['casco']}},
                              format='json')
        self.assertEqual(r.json()['datos']['emergencia']['centro_medico'], 'Clínica Norte')

    def test_sin_centro_medico_queda_el_del_superadmin(self):
        # La app anterior no lo manda.
        r, _ = self.crear()
        self.assertEqual(r.json()['datos']['emergencia']['centro_medico'], 'Clínica Sur')

    def test_el_superadmin_pone_los_telefonos_de_una_empresa(self):
        admin = Usuario.objects.create(
            nombre='Admin', email='admin@x.com', clave='x',
            rol=Rol.objects.get_or_create(id_rol=Rol.SUPERADMIN,
                                          defaults={'descripcion': 'SuperAdmin'})[0])
        self.auth(admin)
        url = f'{URL}contacto_emergencia/'
        # Sin empresa no sabe de cuál son.
        self.assertEqual(self.client.put(url, {'medico_telefono': '1'},
                                         format='json').status_code, 400)
        r = self.client.put(url, {'empresa': self.empresa.pk,
                                  'superior_telefono': '111', 'medico_telefono': '222',
                                  'centro_medico_telefono': '333'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.get(url, {'empresa': self.empresa.pk}).json()
        self.assertEqual((r['superior_telefono'], r['medico_telefono'],
                          r['centro_medico_telefono'], r['superior_nombre']),
                         ('111', '222', '333', 'Jefe Uno'))
        # El capataz los ve en su IPC nuevo.
        r, _ = self.crear(centro_medico='Hospital')
        self.assertEqual(r.json()['datos']['emergencia']['centro_medico_telefono'], '333')

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
