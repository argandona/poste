"""
El cuaderno de obra del reforzamiento de poste y su formato de recupero.

El reforzamiento tiene su propio formato de casillas, y el recupero sale con
la tabla vacía y cruzado con "SIN RECUPERO". Las demás actividades siguen
con lo de siempre.
"""
from datetime import date
from unittest import mock

from ..cuaderno_reforzamiento import (VACIO, _casilla, _subrayado,
                                      en_renglones, generar_pdf_reforzamiento,
                                      reunir_reforzamiento)
from ..models import (SST, Actividad, ConsumoMaterialSuministro,
                      LiquidacionPartida, LiquidacionSuministro, ManoDeObra,
                      Material, Recupero, SSTSuministro, Suministro,
                      SuministroRecupero, TipoTrabajo)
from .base import BaseAPITestCase

CON = 'Reforzamiento de poste con vereda'
SIN = 'Reforzamiento de poste sin vereda / piso especial'
CABRIA = 'Cambio de poste inacc. cabria aereo'


class CuadernoReforzamientoTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.sst = self.sst_de(CON, '7001')
        self.poste = Suministro.objects.create(numero_suministro='P-4455',
                                               distrito='SURCO')
        SSTSuministro.objects.create(sst=self.sst, suministro=self.poste)
        self.cimentacion = ManoDeObra.objects.create(
            partida='*094919', descripcion='CIMENTACION', precio='56.35')
        self.rotura = ManoDeObra.objects.create(
            partida='*098822', descripcion='ROTURA', precio='78.09')
        self.refuerzo = Material.objects.create(
            matricula='6913292', descripcion='REFUERZO DE FIBRA 8,7 / 200',
            precio='1')
        self.fleje = Material.objects.create(
            matricula='1014213', descripcion='FLEJE', precio='1')
        self.gel = Material.objects.create(
            matricula='2139148', descripcion='PEGAMENTO EN GEL', precio='1')

    def sst_de(self, actividad, numero):
        return SST.objects.create(
            sst=numero, codigo=f'SST-{numero}', empresa=self.empresa,
            distrito='LIMA', fecha_ejecucion=date(2026, 10, 2),
            actividad=Actividad.objects.get_or_create(nombre=actividad)[0])

    def liquidar(self, tipo='Reforzamiento con vereda', medidas=None,
                 partidas=(), materiales=(), sst=None, suministro=None):
        suministro = suministro or self.poste
        liq = LiquidacionSuministro.objects.create(
            suministro=suministro, sst_externo=(sst or self.sst).codigo,
            usuario=self.encargado, medidas=medidas or {},
            tipo_trabajo=TipoTrabajo.objects.get_or_create(nombre=tipo)[0])
        for partida in partidas:
            LiquidacionPartida.objects.create(
                liquidacion=liq, mano_de_obra=partida, cantidad=1)
        for material, cantidad in materiales:
            ConsumoMaterialSuministro.objects.create(
                liquidacion=liq, suministro=suministro, material=material,
                usuario=self.encargado, cantidad=cantidad)
        return liq

    # ── Lo que va en la hoja ────────────────────────────────────────────────

    def test_llena_la_hoja_con_vereda(self):
        self.liquidar(
            medidas={'panos': {'vereda_10': [[1.5, 1.0]],
                               'vereda_20': [[0.8, 0.5]],
                               'pista': [[2, 1]]},
                     'viajes': {'acarreo': [30, 6]},
                     'textos': {'poste_existente': '8.7/200'}},
            partidas=[self.cimentacion],
            materiales=[(self.refuerzo, 1), (self.fleje, 2.5), (self.gel, 1)])
        [h] = reunir_reforzamiento(self.sst)
        self.assertTrue(h.con_vereda)
        self.assertEqual((h.sst, h.fecha, h.distrito, h.poste),
                         ('SST-7001', '02/10/2026', 'SURCO', 'P-4455'))
        self.assertEqual(h.encargado, self.encargado.nombre)
        self.assertEqual((h.cimentacion, h.rotura), ('1', ''))
        self.assertEqual(h.poste_existente, '8.7/200')
        self.assertEqual(h.refuerzo, '8,7 / 200')
        self.assertEqual(h.panos, ['1.5 x 1 (10 cm)', '0.8 x 0.5 (20 cm)', ''])
        self.assertEqual((h.pista, h.asfalto), ('2 x 1', ''))
        self.assertEqual((h.acarreo_metros, h.acarreo_viajes), ('30 m', '6'))
        self.assertEqual((h.fleje, h.hebilla, h.gel), ('2.5', '', '1'))

    def test_llena_la_hoja_sin_vereda(self):
        sst = self.sst_de(SIN, '7002')
        self.liquidar(tipo='Reforzamiento sin vereda', sst=sst,
                      medidas={'panos': {'piso_especial': [[1, 1], [2, 0.5]],
                                         'grass': [[3, 1]]}},
                      partidas=[self.rotura])
        [h] = reunir_reforzamiento(sst)
        self.assertFalse(h.con_vereda)
        self.assertEqual(h.pisos, ['1 x 1', '2 x 0.5'])
        self.assertEqual(h.grass, '3 x 1')
        self.assertEqual((h.cimentacion, h.rotura), ('', '1'))

    def test_lo_que_no_entra_se_junta_en_el_ultimo_renglon(self):
        self.assertEqual(en_renglones(['a', 'b', 'c', 'd'], 3),
                         ['a', 'b', 'c; d'])
        self.assertEqual(en_renglones(['a'], 3), ['a', '', ''])

    def test_lo_vacio_se_escribe_con_una_rayita(self):
        c = mock.MagicMock()
        _casilla(c, 0, 0, '')
        c.drawCentredString.assert_called_once_with(mock.ANY, 0, VACIO)
        c = mock.MagicMock()
        _subrayado(c, 0, 0, '', 100)
        c.drawString.assert_called_once_with(mock.ANY, 0, VACIO)
        c = mock.MagicMock()
        _casilla(c, 0, 0, '8,7 / 200')
        c.drawCentredString.assert_called_once_with(mock.ANY, 0, '8,7 / 200')
        self.assertEqual(VACIO, '-')

    def test_sin_respuesta_la_casilla_queda_vacia(self):
        self.liquidar()
        [h] = reunir_reforzamiento(self.sst)
        self.assertEqual(h.poste_existente, '')
        self.assertEqual(h.panos, ['', '', ''])

    def test_un_poste_por_hoja(self):
        otro = Suministro.objects.create(numero_suministro='P-4456')
        SSTSuministro.objects.create(sst=self.sst, suministro=otro)
        self.liquidar()
        self.liquidar(suministro=otro)
        hojas = reunir_reforzamiento(self.sst)
        self.assertEqual([h.poste for h in hojas], ['P-4455', 'P-4456'])
        self.assertTrue(generar_pdf_reforzamiento(hojas).startswith(b'%PDF'))

    # ── Las descargas ───────────────────────────────────────────────────────

    def get(self, ruta, sst=None):
        self.auth(self.encargado)
        return self.client.get(ruta, {'sst': (sst or self.sst).codigo})

    def test_el_cuaderno_del_reforzamiento_usa_su_formato(self):
        self.liquidar(partidas=[self.cimentacion])
        with mock.patch(
                'core.cuaderno_reforzamiento.generar_pdf_reforzamiento',
                return_value=b'%PDF') as generar, \
                mock.patch('core.cuaderno_obra.generar_pdf_cuaderno') as otro:
            r = self.get('/api/liquidaciones/cuaderno_obra/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(generar.call_args.args[0][0].poste, 'P-4455')
        otro.assert_not_called()

    def test_las_demas_actividades_siguen_con_su_cuaderno(self):
        sst = self.sst_de(CABRIA, '7003')
        self.liquidar(tipo='Poste cabria', sst=sst, partidas=[self.cimentacion])
        with mock.patch(
                'core.cuaderno_reforzamiento.generar_pdf_reforzamiento') as nuevo:
            r = self.get('/api/liquidaciones/cuaderno_obra/', sst)
        self.assertEqual(r.status_code, 200, r.content[:300])
        nuevo.assert_not_called()

    def test_el_cuaderno_real_es_un_pdf(self):
        self.liquidar(partidas=[self.cimentacion])
        r = self.get('/api/liquidaciones/cuaderno_obra/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertIn('cuaderno_obra_SST-7001.pdf', r['Content-Disposition'])

    def test_el_recupero_sale_vacio_y_cruzado(self):
        self.liquidar(partidas=[self.cimentacion])
        recupero = Recupero.objects.create(
            matricula='R1', descripcion='CABLE', unidad='M')
        SuministroRecupero.objects.create(suministro=self.poste,
                                          recupero=recupero, cantidad=3,
                                          fecha=date(2026, 10, 2))
        with mock.patch('core.pdf_recupero.generar_pdf_recupero',
                        return_value=b'%PDF') as generar:
            r = self.get('/api/recuperos/formato_pdf/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        datos, items = generar.call_args.args
        self.assertEqual(items, [])
        self.assertTrue(generar.call_args.kwargs['sin_recupero'])
        self.assertEqual(datos['sst'], 'SST-7001')

    def test_el_recupero_de_otras_actividades_no_se_cruza(self):
        sst = self.sst_de(CABRIA, '7004')
        with mock.patch('core.pdf_recupero.generar_pdf_recupero',
                        return_value=b'%PDF') as generar:
            r = self.get('/api/recuperos/formato_pdf/', sst)
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertFalse(generar.call_args.kwargs['sin_recupero'])

    def test_el_recupero_cruzado_real_es_un_pdf(self):
        self.liquidar()
        r = self.get('/api/recuperos/formato_pdf/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))
