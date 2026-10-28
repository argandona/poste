"""
El plano proyectado (DXF) de una obra de varios días.

El coordinador lo sube; de sus textos salen los trabajos ("PROY.",
"INSTALAR", "EMPALMAR"); el capataz marca en su parte lo que hizo cada día y
al final sale el replanteo, con lo hecho pasado a instalado y los metros
reales. Los planos de verdad son sin escala: los metros vienen del texto.
"""
import io
from datetime import date, timedelta
from decimal import Decimal

import ezdxf
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from ..models import AvanceTrabajo, PlanoProyecto, TrabajoPlano
from ..plano_proyecto import a_instalado, trabajo_de
from .test_obra_varios_dias import AYER, HOY, EscenarioObra


def plano_dxf():
    """Un plano chico con lo que traen los de verdad: un cable proyectado,
    dos tubos con sus metros, un empalme y un cajetín con su avance."""
    doc = ezdxf.new('R2018')
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 20)], dxfattribs={'layer': 'GMT_CEN'})
    msp.add_line((0, 5), (100, 5), dxfattribs={'layer': 'TUVO PVC'})
    msp.add_text('3-1x240 NA2XY PROY.', dxfattribs={'layer': 'GMT_CEN',
                                                    'insert': (10, 2)})
    msp.add_mtext('INSTALAR 02 TUBOS\\PHDPE DE 4%%C (450N)\\P(82.00m)',
                  dxfattribs={'layer': 'TUVO PVC', 'insert': (40, 8)})
    msp.add_text('EMPALMAR 3-1x120 N2XY PROY. A 3-1x70 NYY EXIST',
                 dxfattribs={'layer': 'TEXTO', 'insert': (90, 15)})
    # El cajetín: su leyenda dice PROY. pero no es obra.
    msp.add_text('PROY.', dxfattribs={'layer': 'CAJETIN', 'insert': (200, 0)})
    msp.add_text('AVANCE', dxfattribs={'layer': 'Texto Cajetín', 'insert': (200, 10)})
    msp.add_text('000%%%', dxfattribs={'layer': 'Texto Cajetín', 'insert': (210, 10)})
    salida = io.StringIO()
    doc.write(salida)
    return salida.getvalue().encode('utf-8')


class TextosDelPlanoTests(SimpleTestCase):

    def test_un_cable_proyectado_es_un_trabajo_sin_metros(self):
        t = trabajo_de('3-1x240 NA2XY PROY.')
        self.assertEqual((t['tipo'], t['proyectado']), ('cable', None))
        self.assertEqual(trabajo_de('3-1X70 N2XY Proy')['tipo'], 'cable')

    def test_los_tubos_traen_sus_metros_y_cuantos_van(self):
        t = trabajo_de('INSTALAR 02 TUBOS HDPE DE 4Ø (450N) (82.00m)')
        self.assertEqual(t['tipo'], 'tubo')
        self.assertEqual(t['proyectado'], Decimal('82.00'))
        self.assertEqual(t['cantidad'], 2)

    def test_un_empalme_es_una_unidad(self):
        t = trabajo_de('EMPALMAR 3-1x120 N2XY PROY. A 3-1x70 NYY EXIST')
        self.assertEqual((t['tipo'], t['unidad']), ('empalme', 'UND'))

    def test_lo_existente_no_es_trabajo(self):
        self.assertIsNone(trabajo_de('3-1x70 NYY EXIST LL-02 SED 00559S'))
        self.assertIsNone(trabajo_de('AV. PASEO DEL BOSQUE'))

    def test_el_replanteo_pasa_a_instalado_con_los_metros_reales(self):
        self.assertEqual(
            a_instalado('INSTALAR 02 TUBOS\\P(82.00m)', Decimal('84'), 2),
            'SE INSTALÓ 02 TUBOS\\P(84.00m)\\PTotal (168.00m)')
        self.assertEqual(
            a_instalado('EMPALMAR 3-1x120 N2XY PROY. A 3-1x240 NA2XY PROY.'),
            'SE EMPALMÓ 3-1x120 N2XY INST. A 3-1x240 NA2XY INST.')
        self.assertEqual(a_instalado('3-1X70 N2XY Proy'), '3-1X70 N2XY Inst.')


class PlanoProyectoTests(EscenarioObra):

    def subir(self, quien=None, contenido=None, esperado=201):
        self.auth(quien or self.coordinador)
        r = self.client.post('/api/planos-proyecto/subir/', {
            'sst_codigo': self.sst.codigo,
            'archivo': SimpleUploadedFile('proyectado.dxf',
                                          contenido or plano_dxf()),
        }, format='multipart')
        self.assertEqual(r.status_code, esperado, getattr(r, 'data', r))
        return r

    def ver(self, quien=None):
        self.auth(quien or self.capataz)
        r = self.client.get('/api/planos-proyecto/de_sst/',
                            {'sst': self.sst.codigo})
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def trabajo(self, tipo):
        return TrabajoPlano.objects.get(tipo=tipo)

    def marcar(self, quien, items, fecha=HOY, de=None, esperado=200):
        self.auth(quien)
        r = self.client.post('/api/planos-proyecto/avance/', {
            'sst_codigo': self.sst.codigo, 'fecha_parte': str(fecha),
            **({'usuario': de.pk} if de else {}),
            'items': [{'trabajo': t.pk, 'cantidad': c} for t, c in items],
        }, format='json')
        self.assertEqual(r.status_code, esperado, r.data)
        return r

    def test_el_coordinador_sube_y_salen_los_trabajos(self):
        self.subir()
        datos = self.ver()
        self.assertTrue(datos['existe'])
        self.assertEqual(sorted(t['tipo'] for t in datos['trabajos']),
                         ['cable', 'empalme', 'tubo'])
        tubo = next(t for t in datos['trabajos'] if t['tipo'] == 'tubo')
        self.assertEqual((tubo['proyectado'], tubo['cantidad']), ('82.00', 2))
        self.assertTrue(datos['dibujo']['trazos'])
        self.assertEqual(datos['avance'], 0)

    def test_solo_el_coordinador_sube(self):
        self.subir(self.capataz, esperado=403)
        self.subir(self.liquidador, esperado=403)
        self.assertFalse(PlanoProyecto.objects.exists())

    def test_un_dwg_se_rechaza_con_su_motivo(self):
        r = self.subir(contenido=b'AC1032' + b'\0' * 100, esperado=400)
        self.assertIn('DWG', r.data['detail'])

    def test_sin_plano_dice_si_puede_subirlo(self):
        self.assertEqual(self.ver(),
                         {'existe': False, 'puede_subir': False})
        self.assertTrue(self.ver(self.coordinador)['puede_subir'])

    def test_el_capataz_marca_lo_de_su_dia_y_se_suma(self):
        self.subir()
        tubo = self.trabajo('tubo')
        self.marcar(self.capataz, [(tubo, 40)], fecha=AYER)
        self.marcar(self.capataz2, [(tubo, 44)])
        self.marcar(self.capataz, [(tubo, 30)], fecha=AYER)  # corrige ayer
        datos = self.ver()
        fila = next(t for t in datos['trabajos'] if t['tipo'] == 'tubo')
        self.assertEqual(fila['hecho'], '74.00')
        self.assertEqual(len(fila['avances']), 2)

    def test_el_avance_promedia_los_trabajos(self):
        self.subir()
        self.marcar(self.capataz, [(self.trabajo('tubo'), 41),
                                   (self.trabajo('empalme'), 1)])
        # tubo 41/82 = 0.5, empalme 1, cable 0  →  50 %
        self.assertEqual(self.ver()['avance'], 50)

    def test_el_capataz_no_marca_por_otro_ni_con_la_obra_terminada(self):
        self.subir()
        tubo = self.trabajo('tubo')
        self.marcar(self.capataz, [(tubo, 1)], de=self.capataz2, esperado=403)
        self.parte(self.capataz, 1)
        self.terminar()
        self.marcar(self.capataz, [(tubo, 1)], esperado=400)
        self.marcar(self.liquidador, [(tubo, 5)], de=self.capataz)
        self.assertEqual(AvanceTrabajo.objects.get().cantidad, 5)

    def test_lo_descartado_no_se_marca_ni_cuenta(self):
        self.subir()
        cable = self.trabajo('cable')
        self.auth(self.coordinador)
        r = self.client.post('/api/planos-proyecto/trabajos/', {
            'sst_codigo': self.sst.codigo,
            'activos': [self.trabajo('tubo').pk, self.trabajo('empalme').pk],
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.marcar(self.capataz, [(cable, 3)], esperado=400)
        self.marcar(self.capataz, [(self.trabajo('empalme'), 1)])
        self.assertEqual(self.ver()['avance'], 50)

    def test_con_avances_no_se_reemplaza_el_plano(self):
        self.subir()
        self.marcar(self.capataz, [(self.trabajo('empalme'), 1)])
        self.subir(esperado=400)

    def test_el_replanteo_lleva_lo_hecho_y_el_avance(self):
        self.subir()
        self.marcar(self.capataz, [(self.trabajo('tubo'), 84),
                                   (self.trabajo('empalme'), 1)])
        self.auth(self.capataz)
        r = self.client.get('/api/planos-proyecto/replanteo/',
                            {'sst': self.sst.codigo})
        self.assertEqual(r.status_code, 403)
        self.auth(self.coordinador)
        r = self.client.get('/api/planos-proyecto/replanteo/',
                            {'sst': self.sst.codigo})
        self.assertEqual(r.status_code, 200)
        doc = ezdxf.read(io.StringIO(r.content.decode('utf-8')))
        textos = [e.plain_text() if e.dxftype() == 'TEXT'
                  else e.plain_text(split=False)
                  for e in doc.modelspace() if e.dxftype() in ('TEXT', 'MTEXT')]
        self.assertIn('SE EMPALMÓ 3-1x120 N2XY INST. A 3-1x70 NYY EXIST', textos)
        self.assertIn('SE INSTALÓ 02 TUBOS\nHDPE DE 4Ø (450N)\n(84.00m)\n'
                      'Total (168.00m)', textos)
        # El cable no se marcó: sigue proyectado.
        self.assertIn('3-1x240 NA2XY PROY.', textos)
        # Tubo 1 (84 de 82), empalme 1 y cable 0: 67 %.
        self.assertIn('67%', textos)
