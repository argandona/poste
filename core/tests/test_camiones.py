"""
Camiones: salida y cierre con km y foto, cargas de combustible, la alerta de
rendimiento y el informe mensual (core/camiones.py).
"""
import base64
import io
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

import openpyxl
from django.core.management import call_command
from django.utils import timezone

from ..models import (
    SST, CargaCombustible, JornadaCamion, Rol, SSTEncargado, Usuario,
)
from .base import BaseAPITestCase

J = '/api/jornadas-camion/'
C = '/api/cargas-combustible/'
FOTO = base64.b64encode(b'\xff\xd8\xff\xe0 tablero').decode()


class CamionesTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        call_command('configurar_camiones', stdout=io.StringIO())
        rol_chofer = Rol.objects.get(id_rol=Rol.CHOFER)
        self.chofer = Usuario.objects.create(
            nombre='Carlos Chofer', email='chofer@x.com', clave='x',
            empresa=self.empresa, rol=rol_chofer)
        self.chofer2 = Usuario.objects.create(
            nombre='Otro Chofer', email='chofer2@x.com', clave='x',
            empresa=self.empresa, rol=rol_chofer)
        self.coordinador = Usuario.objects.create(
            nombre='Coordinadora', email='coord@x.com', clave='x',
            empresa=self.empresa, fcm_token='tok-coord',
            rol=Rol.objects.create(id_rol=Rol.COORDINADOR, descripcion='Coordinador'))
        self.camion.combustible = 'diesel'
        self.camion.save()
        self.sst = SST.objects.create(empresa=self.empresa, codigo='SST-1', distrito='Surco')
        SSTEncargado.objects.create(sst=self.sst, usuario=self.capataz)

    def salir(self, km=1000, usuario=None, **datos):
        self.auth(usuario or self.chofer)
        cuerpo = {'camion': self.camion.pk, 'km': km, 'foto': FOTO,
                  'ssts': [self.sst.pk], **datos}
        return self.client.post(J, cuerpo, format='json')

    def cerrar(self, jornada_id, km, **datos):
        self.auth(self.chofer)
        return self.client.post(f'{J}{jornada_id}/cerrar/',
                                {'km': km, 'foto': FOTO, **datos}, format='json')

    def cargar(self, km, cantidad='10', monto='180', lleno=True, **datos):
        self.auth(self.chofer)
        with mock.patch('core.fcm.send_notification') as avisar:
            r = self.client.post(C, {'km': km, 'cantidad': cantidad, 'monto': monto,
                                     'tanque_lleno': lleno, 'foto': FOTO, **datos},
                                 format='json')
        return r, avisar

    # ── Salida y cierre ──────────────────────────────────────────────────────

    def test_sale_y_cierra_con_km_y_foto(self):
        r = self.salir()
        self.assertEqual(r.status_code, 201, r.content)
        j = r.json()
        self.assertEqual((j['km_salida'], j['responsable_nombre'], j['abierta']),
                         (1000, 'Capataz Uno', True))
        self.assertEqual([s['sst'] for s in j['ssts']], ['SST-1'])
        r = self.cerrar(j['id_jornada'], 1085, observacion='Sin novedad')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()['km_recorridos'], r.json()['abierta']), (85, False))
        jornada = JornadaCamion.objects.get()
        self.assertTrue(jornada.foto_salida and jornada.foto_cierre)

    def test_sin_foto_o_sin_motivo_no_sale(self):
        self.assertIn('foto', self.salir(foto='').json()['detail'])
        self.assertIn('trabajo interno', self.salir(ssts=[]).json()['detail'])
        self.assertEqual(self.salir(ssts=[], trabajo_interno='Llevar postes al almacén')
                         .status_code, 201)

    def test_solo_el_chofer_registra(self):
        self.assertEqual(self.salir(usuario=self.capataz).status_code, 403)

    def test_el_superadmin_tambien_registra_y_ve_solo_lo_suyo_en_mias(self):
        admin = Usuario.objects.create(
            nombre='Admin', email='admin@x.com', clave='x',
            rol=Rol.objects.create(id_rol=Rol.SUPERADMIN, descripcion='SuperAdmin'))
        self.auth(admin)
        actual = self.client.get(f'{J}actual/').json()
        self.assertIn(self.camion.pk, [c['id_camion'] for c in actual['camiones']])
        jid = self.salir(usuario=admin).json()['id_jornada']
        self.assertEqual(self.client.post(C, {'km': 1050, 'cantidad': '10', 'monto': '180',
                                              'tanque_lleno': True, 'foto': FOTO},
                                          format='json').status_code, 201)
        self.assertEqual(self.client.post(f'{J}{jid}/cerrar/', {'km': 1100, 'foto': FOTO},
                                          format='json').status_code, 200)
        self.salir(2000, usuario=self.chofer)
        self.auth(admin)
        self.assertEqual(len(self.client.get(J).json()), 2)
        self.assertEqual([j['id_jornada'] for j in self.client.get(f'{J}?mias=1').json()], [jid])

    def test_el_km_no_retrocede(self):
        jid = self.salir(1000).json()['id_jornada']
        self.assertIn('menor', self.cerrar(jid, 990).json()['detail'])
        self.cerrar(jid, 1100)
        self.assertIn('1100', self.salir(1050).json()['detail'])

    def test_un_camion_en_ruta_no_lo_toma_otro_y_hay_que_cerrar_antes(self):
        self.salir()
        self.assertIn('en ruta con Carlos', self.salir(usuario=self.chofer2).json()['detail'])
        self.assertIn('Primero cierra', self.salir(1200).json()['detail'])

    def test_actual_y_ssts_del_responsable(self):
        self.auth(self.chofer)
        r = self.client.get(f'{J}actual/').json()
        self.assertIsNone(r['jornada'])
        self.assertEqual(r['camiones'][0]['placa'], 'ABC-123')
        r = self.client.get(f'{J}ssts/', {'camion': self.camion.pk}).json()
        self.assertEqual((r['responsable_nombre'], [s['sst'] for s in r['ssts']]),
                         ('Capataz Uno', ['SST-1']))
        self.salir()
        r = self.client.get(f'{J}actual/').json()
        self.assertEqual(r['jornada']['camion_placa'], 'ABC-123')
        self.assertEqual(r['camiones'][0]['ultimo_km'], 1000)

    def test_cambia_a_que_va_en_ruta(self):
        jid = self.salir().json()['id_jornada']
        r = self.client.post(f'{J}{jid}/motivo/',
                             {'ssts': [], 'trabajo_interno': 'Traslado de material'},
                             format='json')
        self.assertEqual((r.json()['ssts'], r.json()['trabajo_interno']),
                         ([], 'Traslado de material'))

    def test_la_foto_la_ven_el_chofer_y_el_coordinador(self):
        jid = self.salir().json()['id_jornada']
        self.assertEqual(self.client.get(f'{J}{jid}/foto/').status_code, 200)
        self.auth(self.coordinador)
        self.assertEqual(self.client.get(f'{J}{jid}/foto/').status_code, 200)
        self.auth(self.chofer2)
        self.assertEqual(self.client.get(f'{J}{jid}/foto/').status_code, 404)

    # ── Combustible ──────────────────────────────────────────────────────────

    def test_la_carga_va_sobre_la_salida_abierta(self):
        r, _ = self.cargar(1010)
        self.assertIn('salida', r.json()['detail'])
        self.salir()
        r, _ = self.cargar(1010, cantidad='12,5', monto='225', grifo='Primax')
        self.assertEqual(r.status_code, 201, r.content)
        c = r.json()
        self.assertEqual((c['unidad'], c['cantidad'], c['precio_unitario']),
                         ('gal', 12.5, 18.0))
        self.assertIsNone(c['alerta'])

    def test_la_carga_exige_km_foto_y_no_retrocede(self):
        self.salir()
        self.assertIn('foto', self.cargar(1010, foto='')[0].json()['detail'])
        self.assertIn('km', self.cargar('')[0].json()['detail'])
        self.assertIn('menor', self.cargar(900)[0].json()['detail'])

    def test_sin_combustible_definido_lo_elige_el_chofer(self):
        self.camion.combustible = ''
        self.camion.save()
        self.salir()
        self.assertIn('combustible', self.cargar(1010)[0].json()['detail'])
        r, _ = self.cargar(1010, combustible='gnv')
        self.assertEqual(r.json()['unidad'], 'm³')
        self.camion.refresh_from_db()
        self.assertEqual(self.camion.combustible, 'gnv')

    def test_alerta_cuando_rinde_menos_del_85_por_ciento(self):
        self.salir(1000)
        # Tres tramos de 25 km/gal y uno de 15.
        self.cargar(1000)
        for km in (1250, 1500, 1750):
            r, avisar = self.cargar(km)
            self.assertIsNone(r.json()['alerta'])
        r, avisar = self.cargar(1900)
        alerta = r.json()['alerta']
        self.assertEqual((alerta['rendimiento'], alerta['promedio']), (15.0, 25.0))
        self.assertEqual(avisar.call_args.args[0], ['tok-coord'])
        self.assertIn('ABC-123', avisar.call_args.kwargs['title'])

    # ── Informe ──────────────────────────────────────────────────────────────

    def test_informe_del_mes(self):
        jid = self.salir(1000).json()['id_jornada']
        self.cargar(1000)
        self.cargar(1200, cantidad='8', monto='144')
        self.cerrar(jid, 1200)
        # Otra salida, de trabajo interno, que arranca más adelante: hay km
        # que nadie registró entre el cierre y la salida.
        jid = self.salir(1230, ssts=[], trabajo_interno='Almacén').json()['id_jornada']
        self.cerrar(jid, 1260)

        hoy = timezone.localdate()
        self.auth(self.coordinador)
        r = self.client.get(f'{J}informe/', {'anio': hoy.year, 'mes': hoy.month})
        self.assertEqual(r.status_code, 200, r.content)
        c = r.json()['camiones'][0]
        self.assertEqual((c['km_jornadas'], c['km_sin_registrar'], c['km_total']),
                         (230, 30, 260))
        self.assertEqual((c['km_sst'], c['km_interno'], c['ssts_atendidas']),
                         (200, 30, ['SST-1']))
        self.assertEqual((c['cantidad'], c['monto']), (18.0, 324.0))
        # Entre los dos llenos: 200 km con 8 gal.
        self.assertEqual((c['rendimiento'], c['metodo']), (25.0, 'tanque lleno'))
        self.assertFalse(c['alerta'])

        r = self.client.get(f'{J}informe/', {'anio': hoy.year, 'mes': hoy.month,
                                             'formato': 'xlsx'})
        libro = openpyxl.load_workbook(io.BytesIO(r.content))
        self.assertEqual(libro.sheetnames, ['Resumen', 'Salidas', 'Combustible'])
        self.assertEqual(libro['Resumen']['A4'].value, 'ABC-123')

    def test_salida_sin_cierre_de_un_dia_anterior(self):
        jid = self.salir(1000).json()['id_jornada']
        JornadaCamion.objects.filter(pk=jid).update(fecha=date.today() - timedelta(days=1))
        hoy = timezone.localdate()
        self.auth(self.coordinador)
        desde = date.today() - timedelta(days=1)
        r = self.client.get(f'{J}informe/', {'anio': desde.year, 'mes': desde.month}).json()
        self.assertEqual(r['camiones'][0]['sin_cierre'], 1)

    def test_el_informe_no_lo_ve_el_chofer(self):
        self.auth(self.chofer)
        self.assertEqual(self.client.get(f'{J}informe/').status_code, 403)

    def test_rendimiento_aproximado_sin_dos_llenos(self):
        jid = self.salir(1000).json()['id_jornada']
        self.cargar(1050, cantidad='10', lleno=False)
        self.cerrar(jid, 1300)
        hoy = timezone.localdate()
        self.auth(self.coordinador)
        c = self.client.get(f'{J}informe/', {'anio': hoy.year, 'mes': hoy.month}
                            ).json()['camiones'][0]
        self.assertEqual((c['rendimiento'], c['metodo']), (30.0, 'aproximado'))
        self.assertEqual(c['costo_km'], 0.6)

    def test_si_falla_la_subida_de_la_foto_lo_dice(self):
        with mock.patch('core.fotos.storages') as st:
            st.__getitem__.return_value.save.side_effect = RuntimeError('Invalid api_key')
            r = self.salir()
        self.assertEqual(r.status_code, 400)
        self.assertIn('Invalid api_key', r.json()['detail'])
        self.assertFalse(JornadaCamion.objects.exists())
