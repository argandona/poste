"""
Cuaderno de obra y Excel de liquidación de una SST.

El cuaderno se redacta solo con lo liquidado y lo dibujado en el plano, así que
lo que importa es que cada renglón aparezca cuando corresponde y no cuando no.
El Excel es la plantilla de Tecsur: las cantidades tienen que caer en su celda.
"""
import io
from datetime import date, time
from decimal import Decimal

from openpyxl import load_workbook

from ..cuaderno_obra import Item, Liquidado, lineas_del_cuaderno
from ..models import (
    Actividad, ConsumoMaterialSuministro, CuadernoObra, LiquidacionPartida,
    LiquidacionSuministro, ManoDeObra, Material, PlanoSST, Recupero, SST,
    Suministro, SSTSuministro, SuministroRecupero, TipoTrabajo,
)
from .base import BaseAPITestCase


def item(descripcion, cantidad=1, codigo='X'):
    return Item(codigo, descripcion, Decimal(str(cantidad)))


class LineasDelCuadernoTests(BaseAPITestCase):

    def test_empieza_con_la_frase_del_formato(self):
        self.assertEqual(
            lineas_del_cuaderno(Liquidado())[0],
            'Por la presente se informa que la SST se ejecutó según lo detallado:')

    def test_poste_instalado_con_el_codigo_del_plano_y_el_retirado(self):
        d = Liquidado(
            materiales=[item('POSTE DE POLIESTER 9 / 200')],
            elementos_plano=[{'assetId': 'poste_nuevo', 'codigo': '123456789'},
                             {'assetId': 'poste_retirado', 'codigo': '999'}],
            postes=['P-100'])
        lineas = lineas_del_cuaderno(d)
        self.assertIn('Se instaló poste POSTE DE POLIESTER 9 / 200 con código 123456789',
                      lineas)
        self.assertIn('Se retiró poste P-100', lineas)

    def test_la_abrazadera_de_poste_no_es_un_poste(self):
        d = Liquidado(materiales=[item('ABRAZADERA POSTE C.A.150MMD.C/GANCHO')],
                      postes=['P-100'])
        lineas = lineas_del_cuaderno(d)
        self.assertFalse(any(l.startswith('Se instaló poste') for l in lineas))
        self.assertNotIn('Se retiró poste P-100', lineas)

    def test_traslados_de_pastoral_y_luminaria(self):
        d = Liquidado(partidas=[item('x', 1, '*091356'), item('y', 1, '*091322')])
        lineas = lineas_del_cuaderno(d)
        self.assertIn('Se realizó traslado de pastoral existente', lineas)
        self.assertIn('Se realizó traslado de luminaria existente', lineas)

    def test_sin_traslado_no_se_menciona(self):
        lineas = lineas_del_cuaderno(Liquidado())
        self.assertFalse(any('traslado de pastoral' in l for l in lineas))

    def test_retiro_e_instalacion_de_luminaria(self):
        d = Liquidado(recuperos=[item('LUMINARIA DE 150 W')],
                      materiales=[item('LUMINARIA LED 90W')])
        self.assertIn(
            'Se realizó retiro e instalación de luminaria: se retiró '
            'LUMINARIA DE 150 W (1) y se instaló LUMINARIA LED 90W (1)',
            lineas_del_cuaderno(d))

    def test_la_abrazadera_para_pastoral_no_es_un_pastoral(self):
        d = Liquidado(recuperos=[item('ABRAZADERA PARA PASTORAL')])
        self.assertFalse(any('pastoral' in l for l in lineas_del_cuaderno(d)))

    def test_caja_y_corona(self):
        d = Liquidado(
            recuperos=[item('CAJA DE DERIVACION'), item('ABRAZADERA CORONA')],
            materiales=[item('CAJA NO METALICA DE DERIVACION'),
                        item('ABRAZADERA POSTE C.A.150MMD.C/GANCHO ACOMET.DOMIC.', 2)])
        lineas = lineas_del_cuaderno(d)
        self.assertTrue(any(l.startswith('Se realizó retiro e instalación de caja '
                                         'de distribución') for l in lineas))
        self.assertTrue(any(l.startswith('Se realizó retiro e instalación de abrazadera '
                                         'tipo corona con ganchos') for l in lineas))

    def test_cables_tramo_por_tramo_y_sin_los_existentes(self):
        d = Liquidado(elementos_plano=[
            {'tipo': 'cable', 'estado': 'T', 'descripcion': 'Caais 3x35+1x16', 'metros': 26},
            {'tipo': 'cable', 'estado': 'T', 'descripcion': 'Caais 3x70', 'metros': 25},
            {'tipo': 'cable', 'estado': 'T', 'descripcion': 'Caais 3x35+1x16', 'metros': 15},
            {'tipo': 'cable', 'estado': 'E', 'descripcion': 'Caais 3x16', 'metros': 40},
        ])
        lineas = lineas_del_cuaderno(d)
        self.assertEqual(lineas[1:], [
            'Traslado Caais 3x35+1x16 26 metros',
            'Traslado Caais 3x70 25 metros',
            'Traslado Caais 3x35+1x16 15 metros',
        ])

    def test_arrastre_con_su_zona(self):
        d = Liquidado(elementos_plano=[
            {'tipo': 'cable', 'estado': 'A', 'metros': 12, 'pendiente': True},
            {'tipo': 'cable', 'estado': 'A', 'metros': 8.5, 'pendiente': False},
        ])
        lineas = lineas_del_cuaderno(d)
        self.assertIn('Arrastre de poste 12 metros en zona de pendiente mayor a 30° '
                      'o escalera', lineas)
        self.assertIn('Arrastre de poste 8.5 metros', lineas)

    def test_suministros_trasladados(self):
        d = Liquidado(partidas=[item('x', 2, '*093081')],
                      conexiones=['1234567, 7654321'])
        self.assertIn('Se realizó traslado de 2 suministros: 1234567, 7654321',
                      lineas_del_cuaderno(d))


class DescargasTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.actividad = Actividad.objects.create(
            nombre='Cambio de poste inacc. cabria aereo')
        self.sst = SST.objects.create(
            sst='5001', codigo='SST-5001', empresa=self.empresa, distrito='SURCO',
            actividad=self.actividad, fecha_ejecucion=date(2026, 9, 10),
            hora_ejecucion=time(9, 30))
        self.poste = Suministro.objects.create(numero_suministro='P-7788')
        SSTSuministro.objects.create(sst=self.sst, suministro=self.poste)

        self.poste_prfv = Material.objects.create(
            matricula='5331616', descripcion='POSTE POLIESTER 9 / 200', precio='42')
        self.propio = Material.objects.create(
            matricula='9999999', descripcion='MATERIAL QUE NO ESTA', precio='3')
        self.inspeccion = ManoDeObra.objects.create(
            partida='*094395', descripcion='Inspección previa', precio='53.30')
        self.nueva = ManoDeObra.objects.create(
            partida='*777777', descripcion='Partida nueva', precio='5')

    def liquidar(self, sst=None, suministro=None):
        liq = LiquidacionSuministro.objects.create(
            suministro=suministro or self.poste, sst_externo=(sst or self.sst).codigo,
            usuario=self.capataz,
            tipo_trabajo=TipoTrabajo.objects.get_or_create(nombre='Poste cabria')[0])
        LiquidacionPartida.objects.create(
            liquidacion=liq, mano_de_obra=self.inspeccion, cantidad=1)
        LiquidacionPartida.objects.create(
            liquidacion=liq, mano_de_obra=self.nueva, cantidad=3)
        for material, cantidad in ((self.poste_prfv, 1), (self.propio, 4)):
            ConsumoMaterialSuministro.objects.create(
                liquidacion=liq, suministro=suministro or self.poste,
                material=material, usuario=self.capataz, cantidad=cantidad)
        return liq

    def get(self, ruta, codigo=None):
        self.auth(self.capataz)
        return self.client.get(ruta, {'sst': codigo or self.sst.codigo})

    # ── Cuaderno ────────────────────────────────────────────────────────────

    def test_cuaderno_en_pdf(self):
        self.liquidar()
        r = self.get('/api/liquidaciones/cuaderno_obra/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertIn('cuaderno_obra_SST-5001.pdf', r['Content-Disposition'])

    def test_sin_liquidacion_no_hay_cuaderno_ni_numero(self):
        r = self.get('/api/liquidaciones/cuaderno_obra/')
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.data['detail'], str)
        self.assertFalse(CuadernoObra.objects.exists())

    def test_el_numero_se_conserva_y_el_siguiente_es_correlativo(self):
        self.liquidar()
        self.get('/api/liquidaciones/cuaderno_obra/')
        self.get('/api/liquidaciones/cuaderno_obra/')
        otra = SST.objects.create(sst='5002', codigo='SST-5002',
                                  empresa=self.empresa, distrito='LIMA')
        otro_poste = Suministro.objects.create(numero_suministro='P-9900')
        SSTSuministro.objects.create(sst=otra, suministro=otro_poste)
        self.liquidar(sst=otra, suministro=otro_poste)
        self.get('/api/liquidaciones/cuaderno_obra/', 'SST-5002')
        self.assertEqual(
            list(CuadernoObra.objects.order_by('numero')
                 .values_list('sst_codigo', 'numero')),
            [('SST-5001', 1), ('SST-5002', 2)])

    def test_redacta_con_el_plano_y_el_recupero(self):
        from ..cuaderno_obra import reunir
        self.liquidar()
        PlanoSST.objects.create(
            empresa=self.empresa, sst_codigo=self.sst.codigo, usuario=self.capataz,
            elementos=[{'assetId': 'poste_nuevo', 'codigo': '111222333'},
                       {'tipo': 'cable', 'estado': 'A', 'metros': 20}])
        lum = Recupero.objects.create(matricula='REC-036', descripcion='LUMINARIA DE 150 W')
        SuministroRecupero.objects.create(
            suministro=self.poste, recupero=lum, cantidad=1, fecha=date.today())
        lineas = lineas_del_cuaderno(reunir(self.sst))
        self.assertIn('Se instaló poste POSTE POLIESTER 9 / 200 con código 111222333',
                      lineas)
        self.assertIn('Se retiró poste P-7788', lineas)
        self.assertIn('Arrastre de poste 20 metros', lineas)
        self.assertIn('Se retiró luminaria: LUMINARIA DE 150 W (1)', lineas)

    # ── Excel ───────────────────────────────────────────────────────────────

    def test_excel_con_las_cantidades_en_su_celda(self):
        self.liquidar()
        r = self.get('/api/liquidaciones/excel/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('liquidacion_SST-5001.xlsx', r['Content-Disposition'])
        wb = load_workbook(io.BytesIO(r.content))

        car = wb.worksheets[0]
        self.assertEqual(car['C8'].value, 'SST-5001')
        self.assertEqual(car['C10'].value, 'TECSUR')
        self.assertEqual(car['H18'].value, self.capataz.nombre)

        mat = wb['MATERIAL']
        fila_poste = next(f for f in range(14, 171) if mat[f'A{f}'].value == 5331616)
        self.assertEqual(mat[f'AU{fila_poste}'].value, 1)
        fila_propio = next(f for f in range(14, 171) if mat[f'A{f}'].value == 9999999)
        self.assertGreater(fila_propio, 100)
        self.assertEqual(mat[f'C{fila_propio}'].value, 'MATERIAL QUE NO ESTA')
        self.assertEqual(mat[f'AU{fila_propio}'].value, 4)

        mo = wb['MANO DE OBRA']
        fila_insp = next(f for f in range(7, 113) if mo[f'A{f}'].value == '*094395')
        self.assertEqual(mo[f'F{fila_insp}'].value, 1)
        fila_nueva = next(f for f in range(7, 113) if mo[f'A{f}'].value == '*777777')
        self.assertEqual(mo[f'F{fila_nueva}'].value, 3)
        self.assertEqual(mo[f'I{fila_nueva}'].value, f'=SUM(F{fila_nueva}:H{fila_nueva})')

    def test_excel_sin_liquidacion(self):
        r = self.get('/api/liquidaciones/excel/')
        self.assertEqual(r.status_code, 400)

    # ── Hora de ejecución ───────────────────────────────────────────────────

    def test_la_hora_se_guarda_con_la_fecha(self):
        self.auth(self.capataz)
        r = self.client.post('/api/ssts/set_fecha_ejecucion/', {
            'sst_codigo': self.sst.codigo, 'fecha': '2026-09-12', 'hora': '14:45',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.sst.refresh_from_db()
        self.assertEqual(self.sst.fecha_ejecucion, date(2026, 9, 12))
        self.assertEqual(self.sst.hora_ejecucion, time(14, 45))

    def test_sin_hora_la_hora_no_se_borra(self):
        self.auth(self.capataz)
        self.client.post('/api/ssts/set_fecha_ejecucion/', {
            'sst_codigo': self.sst.codigo, 'fecha': '2026-09-12'}, format='json')
        self.sst.refresh_from_db()
        self.assertEqual(self.sst.hora_ejecucion, time(9, 30))

    def test_el_comentario_del_tipo_se_guarda_aparte(self):
        self.auth(self.capataz)
        tipo = TipoTrabajo.objects.create(nombre='Conexiones cabria')
        r = self.client.post('/api/liquidaciones/', {
            'suministro': self.poste.pk, 'sst_externo': self.sst.codigo,
            'usuario': self.capataz.pk, 'tipo_trabajo': tipo.pk,
            'observacion': 'general — 1234567', 'comentario': '1234567',
            'partidas': [{'mano_de_obra': self.inspeccion.pk, 'cantidad': 1}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(LiquidacionSuministro.objects.get(pk=r.data['id_liquidacion'])
                         .comentario, '1234567')
