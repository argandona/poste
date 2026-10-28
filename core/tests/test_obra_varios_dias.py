"""
Obra de varios días ("Calidad de producto").

Cada capataz manda un parte por día y por punto, y la liquidación es la suma
de todos. Volver a grabar corrige solo el parte de ese día, capataz y punto.
El capataz corrige los suyos mientras la obra siga abierta; el coordinador y
el liquidador, los de cualquiera, también con la obra terminada. La termina
el coordinador.
"""
from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command

from ..models import (
    Actividad, ActividadTipoTrabajo, Camion, CorreccionLiquidacion,
    LiquidacionSuministro, ManoDeObra, Recupero, Rol, SST, SSTEncargado,
    SSTSuministro, StockCamion, Suministro, SuministroRecupero, TipoTrabajo,
    Usuario, UsuarioCamion,
)
from .base import BaseAPITestCase

HOY = date.today()
AYER = HOY - timedelta(days=1)


class EscenarioObra(BaseAPITestCase):
    """Una SST de Calidad de producto con un punto, dos capataces con camión,
    un coordinador y un liquidador."""

    def setUp(self):
        super().setUp()
        call_command('configurar_calidad_producto', stdout=StringIO())
        self.actividad = Actividad.objects.get(nombre='Calidad de producto')
        self.sst = SST.objects.create(
            sst='88888', codigo='SST-88888', empresa=self.empresa,
            distrito='LIMA', actividad=self.actividad)
        self.punto = Suministro.objects.create(
            numero_suministro='Punto 01', distrito='LIMA')
        SSTSuministro.objects.create(sst=self.sst, suministro=self.punto,
                                     asignado_a=self.capataz)
        SSTEncargado.objects.create(sst=self.sst, usuario=self.capataz)

        self.tipo = TipoTrabajo.objects.create(nombre='Calidad X')
        ActividadTipoTrabajo.objects.create(
            actividad=self.actividad, tipo_trabajo=self.tipo)
        self.partida = ManoDeObra.objects.create(
            partida='*777001', descripcion='TRABAJO DE CALIDAD',
            precio='10.00')
        self.stock = StockCamion.objects.create(
            camion=self.camion, material=self.material_a, cantidad=20)

        # Un segundo capataz con su camión, en la misma SST.
        self.capataz2 = Usuario.objects.create(
            nombre='Capataz Dos', rol=self.rol_capataz, empresa=self.empresa,
            email='capataz2@tecsur.pe', clave='x')
        camion2 = Camion.objects.create(empresa=self.empresa, placa='XYZ-999')
        UsuarioCamion.objects.create(camion=camion2, usuario=self.capataz2,
                                     fecha_inicio=HOY - timedelta(days=30))
        StockCamion.objects.create(camion=camion2, material=self.material_a,
                                   cantidad=20)
        self.coordinador = Usuario.objects.create(
            nombre='Coordinador', rol=Rol.objects.create(
                id_rol=Rol.COORDINADOR, descripcion='Coordinador'),
            empresa=self.empresa, email='coord@tecsur.pe', clave='x')
        self.liquidador = Usuario.objects.create(
            nombre='Liquidador', rol=Rol.objects.create(
                id_rol=Rol.LIQUIDADOR, descripcion='Liquidador'),
            empresa=self.empresa, email='liq@tecsur.pe', clave='x')

    def parte(self, quien, cantidad, fecha=HOY, de=None, material=0,
              esperado=201):
        self.auth(quien)
        cuerpo = {
            'suministro': self.punto.pk,
            'sst_externo': self.sst.codigo,
            'usuario': (de or quien).pk,
            'tipo_trabajo': self.tipo.pk,
            'fecha_parte': str(fecha),
            'partidas': [{'mano_de_obra': self.partida.pk,
                          'cantidad': cantidad}],
            'materiales': ([{'material': self.material_a.pk,
                             'cantidad': material}] if material else []),
        }
        r = self.client.post('/api/liquidaciones/', cuerpo, format='json')
        self.assertEqual(r.status_code, esperado, r.data)
        return r

    def total(self):
        return sum(lp.cantidad for liq in LiquidacionSuministro.objects.all()
                   for lp in liq.partidas.all())

    def terminar(self, quien=None, esperado=200):
        self.auth(quien or self.coordinador)
        r = self.client.post('/api/ssts/terminar_obra/',
                             {'sst_codigo': self.sst.codigo}, format='json')
        self.assertEqual(r.status_code, esperado, r.data)
        return r


class ObraVariosDiasTests(EscenarioObra):

    # ── La actividad ─────────────────────────────────────────────────────────

    def test_la_actividad_es_de_varios_dias_y_varios_puntos(self):
        self.assertTrue(self.actividad.varios_dias)
        self.assertTrue(self.actividad.varios_postes)
        self.assertFalse(self.actividad.de_encargado)

    def test_el_comando_corrige_si_alguien_le_quito_varios_dias(self):
        Actividad.objects.filter(pk=self.actividad.pk).update(varios_dias=False)
        call_command('configurar_calidad_producto', stdout=StringIO())
        self.actividad.refresh_from_db()
        self.assertTrue(self.actividad.varios_dias)

    # ── Los partes se suman ──────────────────────────────────────────────────

    def test_los_partes_de_dias_distintos_se_suman(self):
        self.parte(self.capataz, 3, fecha=AYER)
        self.parte(self.capataz, 2, fecha=HOY)
        self.assertEqual(LiquidacionSuministro.objects.count(), 2)
        self.assertEqual(self.total(), 5)

    def test_dos_capataces_el_mismo_dia_se_suman(self):
        self.parte(self.capataz, 3)
        self.parte(self.capataz2, 4)
        self.assertEqual(self.total(), 7)

    def test_grabar_otra_vez_el_mismo_dia_corrige_ese_parte(self):
        self.parte(self.capataz, 3, fecha=AYER)
        self.parte(self.capataz, 2)
        self.parte(self.capataz, 5)  # corrige el de hoy
        self.assertEqual(self.total(), 8)
        self.assertEqual(CorreccionLiquidacion.objects.count(), 1)

    def test_corregir_devuelve_el_material_del_parte_al_camion(self):
        self.parte(self.capataz, 1, fecha=AYER, material=4)
        self.parte(self.capataz, 1, material=3)
        self.parte(self.capataz, 1, material=1)  # corrige el de hoy
        self.stock.refresh_from_db()
        self.assertEqual(str(self.stock.cantidad), '15.00')

    def test_sin_fecha_el_parte_es_de_hoy(self):
        self.auth(self.capataz)
        r = self.client.post('/api/liquidaciones/', {
            'suministro': self.punto.pk, 'sst_externo': self.sst.codigo,
            'usuario': self.capataz.pk, 'tipo_trabajo': self.tipo.pk,
            'partidas': [{'mano_de_obra': self.partida.pk, 'cantidad': 1}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['fecha_parte'], str(HOY))

    def test_no_hay_partes_de_manana(self):
        self.parte(self.capataz, 1, fecha=HOY + timedelta(days=1),
                   esperado=400)

    def test_el_punto_sigue_pendiente_y_la_fecha_es_la_del_primer_parte(self):
        self.parte(self.capataz, 1, fecha=HOY)
        self.parte(self.capataz, 1, fecha=AYER)
        self.punto.refresh_from_db()
        self.sst.refresh_from_db()
        self.assertEqual(self.punto.estado, 'asignado')
        self.assertEqual(self.sst.fecha_ejecucion, AYER)

    def test_el_ipc_de_manana_sigue_ofreciendo_la_obra(self):
        self.parte(self.capataz, 1)
        self.auth(self.capataz)
        r = self.client.get('/api/ssts/mis_sst/',
                            {'usuario': self.capataz.pk, 'pendientes': 1})
        self.assertEqual([s['id_sst'] for s in r.data], [self.sst.pk])

    # ── Quién corrige ────────────────────────────────────────────────────────

    def test_el_capataz_no_graba_el_parte_de_otro(self):
        self.parte(self.capataz2, 1)
        self.parte(self.capataz, 9, de=self.capataz2, esperado=403)
        self.assertEqual(self.total(), 1)

    def test_el_coordinador_y_el_liquidador_corrigen_el_de_cualquiera(self):
        self.parte(self.capataz, 3)
        self.parte(self.coordinador, 2, de=self.capataz)
        self.parte(self.liquidador, 1, de=self.capataz)
        self.assertEqual(self.total(), 1)
        self.assertEqual(LiquidacionSuministro.objects.get().usuario,
                         self.capataz)

    # ── Terminar la obra ─────────────────────────────────────────────────────

    def test_terminada_el_capataz_ya_no_manda_ni_corrige(self):
        self.parte(self.capataz, 3)
        self.terminar()
        self.parte(self.capataz, 5, esperado=400)
        self.parte(self.capataz, 1, fecha=AYER, esperado=400)
        self.assertEqual(self.total(), 3)

    def test_terminada_el_coordinador_y_el_liquidador_aun_corrigen(self):
        self.parte(self.capataz, 3)
        self.terminar()
        self.parte(self.liquidador, 4, de=self.capataz)
        self.assertEqual(self.total(), 4)

    def test_al_terminar_los_puntos_dejan_de_estar_pendientes(self):
        self.parte(self.capataz, 3)
        self.terminar()
        self.punto.refresh_from_db()
        self.assertEqual(self.punto.estado, 'ejecutado')
        self.sst.refresh_from_db()
        self.assertEqual(self.sst.obra_terminada_por, self.coordinador)

    def test_solo_el_coordinador_termina(self):
        self.parte(self.capataz, 3)
        for quien in (self.capataz, self.liquidador):
            self.terminar(quien, esperado=403)
        self.sst.refresh_from_db()
        self.assertIsNone(self.sst.obra_terminada_el)

    def test_sin_partes_no_se_termina(self):
        self.terminar(esperado=400)

    def test_reabrir_devuelve_la_obra_al_capataz(self):
        self.parte(self.capataz, 3)
        self.terminar()
        self.auth(self.coordinador)
        r = self.client.post('/api/ssts/reabrir_obra/',
                             {'sst_codigo': self.sst.codigo}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.punto.refresh_from_db()
        self.assertEqual(self.punto.estado, 'asignado')
        self.parte(self.capataz, 5)
        self.assertEqual(self.total(), 5)

    def test_una_actividad_normal_no_se_termina(self):
        normal = Actividad.objects.create(nombre='Cambio de poste X')
        self.sst.actividad = normal
        self.sst.save()
        self.terminar(esperado=400)

    # ── Lo que se ve ─────────────────────────────────────────────────────────

    def test_la_lista_de_partes_y_el_total(self):
        self.parte(self.capataz, 3, fecha=AYER)
        self.parte(self.capataz2, 4)
        self.auth(self.coordinador)
        r = self.client.get('/api/liquidaciones/partes/',
                            {'sst': self.sst.codigo})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(
            [(p['fecha'], p['usuario_nombre']) for p in r.data['partes']],
            [(str(HOY), 'Capataz Dos'), (str(AYER), 'Capataz Uno')])
        self.assertEqual(r.data['total'][0]['cantidad'], '7.00')
        self.assertEqual(r.data['total'][0]['monto'], '70.0000')
        self.assertTrue(r.data['puede_terminar'])
        self.assertFalse(r.data['terminada'])

    def test_el_parte_de_un_dia_se_pide_por_fecha_y_capataz(self):
        self.parte(self.capataz, 3, fecha=AYER)
        self.parte(self.capataz, 2)
        self.auth(self.capataz)
        r = self.client.get('/api/liquidaciones/', {
            'suministro': self.punto.pk, 'fecha_parte': str(AYER),
            'usuario': self.capataz.pk})
        datos = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual(len(datos), 1)
        self.assertEqual(datos[0]['partidas'][0]['cantidad'], '3.00')

    def test_los_puntos_dicen_que_es_obra_de_varios_dias(self):
        self.auth(self.capataz)
        r = self.client.get('/api/ssts/puntos/',
                            {'sst_codigo': self.sst.codigo})
        self.assertTrue(r.data['varios_dias'])
        self.assertFalse(r.data['obra_terminada'])

    def test_el_consolidado_suma_los_partes(self):
        self.parte(self.capataz, 3, fecha=AYER)
        self.parte(self.capataz2, 4)
        self.auth(self.coordinador)
        r = self.client.get('/api/liquidaciones/consolidado/')
        fila = next(f for f in r.data if f['sst'] == self.sst.codigo)
        self.assertTrue(fila['varios_dias'])
        self.assertEqual(fila['total'], '70.0000')

    # ── Recupero por parte ───────────────────────────────────────────────────

    def test_el_recupero_de_cada_parte_no_pisa_el_de_otro(self):
        rec = Recupero.objects.create(matricula='REC-X', descripcion='FIERRO')

        def registrar(quien, cantidad, fecha):
            self.auth(quien)
            r = self.client.post('/api/recuperos/registrar/', {
                'suministro': self.punto.pk, 'fecha': str(fecha),
                'items': [{'recupero': rec.pk, 'cantidad': cantidad}],
            }, format='json')
            self.assertEqual(r.status_code, 200, r.data)

        registrar(self.capataz, 2, AYER)
        registrar(self.capataz2, 3, HOY)
        registrar(self.capataz, 1, HOY)
        registrar(self.capataz, 5, HOY)  # corrige el suyo de hoy
        self.assertEqual(
            sorted(SuministroRecupero.objects.values_list('cantidad', flat=True)),
            [2, 3, 5])


class PartidaDeSstEnVariosDiasTests(EscenarioObra):
    """Lo que en las demás actividades se cobra una vez por SST, en una obra
    de varios días se suma: el plano crece día a día y cada parte cobra lo
    nuevo (lo resta la app)."""

    def setUp(self):
        super().setUp()
        self.partida.ambito = ManoDeObra.AMBITO_SST
        self.partida.save()

    def test_otro_dia_suma_lo_suyo(self):
        self.parte(self.capataz, 1, fecha=AYER)
        self.parte(self.capataz, 2)
        self.assertEqual(self.total(), 3)

    def test_otro_capataz_el_mismo_dia_tambien(self):
        self.parte(self.capataz, 1)
        self.parte(self.capataz2, 2)
        self.assertEqual(self.total(), 3)

    def test_no_se_muestra_bloqueada(self):
        self.parte(self.capataz, 1, fecha=AYER)
        self.auth(self.capataz)
        r = self.client.get('/api/liquidaciones/partidas_de_sst/',
                            {'sst': self.sst.codigo,
                             'suministro': self.punto.pk})
        self.assertEqual(r.data, {})

    def test_corregir_el_mismo_parte_si_se_puede(self):
        self.parte(self.capataz, 1)
        self.parte(self.capataz, 1)
        self.assertEqual(self.total(), 1)

    def test_cada_parte_dice_lo_que_cobro(self):
        self.parte(self.capataz, 1, fecha=AYER)
        self.parte(self.capataz2, 2)
        self.auth(self.coordinador)
        r = self.client.get('/api/liquidaciones/partes/',
                            {'sst': self.sst.codigo})
        self.assertEqual(
            [(p['usuario_nombre'], p['partidas']) for p in r.data['partes']],
            [('Capataz Dos', {'*777001': '2.00'}),
             ('Capataz Uno', {'*777001': '1.00'})])

    def test_cada_parte_dice_el_material_que_consumio(self):
        self.parte(self.capataz, 1, material=3)
        self.auth(self.coordinador)
        r = self.client.get('/api/liquidaciones/partes/',
                            {'sst': self.sst.codigo})
        self.assertEqual(r.data['partes'][0]['materiales'],
                         {self.material_a.matricula: '3.00'})


class TiposDeCalidadDeProductoTests(EscenarioObra):
    """Las partidas que pasó el usuario el 2026-10-27, en sus dos tipos."""

    def partidas_de(self, nombre):
        tipo = TipoTrabajo.objects.get(nombre=nombre)
        return list(tipo.partidas.order_by('orden')
                    .values_list('mano_de_obra__partida', flat=True))

    def test_los_dos_tipos_cuelgan_de_la_actividad(self):
        nombres = set(ActividadTipoTrabajo.objects
                      .filter(actividad=self.actividad)
                      .values_list('tipo_trabajo__nombre', flat=True))
        self.assertTrue({'Trabajos subterraneos', 'Trabajos civiles'} <= nombres)

    def test_subterraneos_y_civiles_llevan_lo_suyo(self):
        self.assertEqual(self.partidas_de('Trabajos subterraneos'), [
            '*090248', '*091420', '*091440', '*091450', '*091633', '*091642',
            '*091676', '*091775', '*091914', '*091935', '*095210', '*099090'])
        self.assertEqual(self.partidas_de('Trabajos civiles'), [
            '*091800', '*091810', '*091820', '*091830', '*091845', '*095227',
            '*095265', '*095275', '*095280', '*095282'])

    def test_el_material_va_en_subterraneos(self):
        tipo = TipoTrabajo.objects.get(nombre='Trabajos subterraneos')
        matriculas = list(tipo.materiales.values_list(
            'material__matricula', flat=True))
        self.assertEqual(len(matriculas), 33)
        self.assertIn('5031179', matriculas)
        civiles = TipoTrabajo.objects.get(nombre='Trabajos civiles')
        self.assertEqual(civiles.materiales.count(), 0)

    def test_el_material_que_ya_existia_no_se_toca(self):
        from ..models import Material
        Material.objects.filter(matricula='5411070').update(
            precio='12.50', descripcion='CONECTOR CUÑA 70/16')
        call_command('configurar_calidad_producto', stdout=StringIO())
        cuna = Material.objects.get(matricula='5411070')
        self.assertEqual((str(cuna.precio), cuna.descripcion),
                         ('12.50', 'CONECTOR CUÑA 70/16'))

    def test_las_nuevas_nacen_con_el_precio_de_la_lista(self):
        self.assertEqual(
            str(ManoDeObra.objects.get(partida='*095282').precio), '19.23')

    def test_las_que_ya_existian_no_se_tocan(self):
        ManoDeObra.objects.filter(partida='*091810').update(
            precio='80.51', descripcion='REPOSICION DE GRASS M2')
        call_command('configurar_calidad_producto', stdout=StringIO())
        grass = ManoDeObra.objects.get(partida='*091810')
        self.assertEqual(str(grass.precio), '80.51')
        self.assertEqual(grass.descripcion, 'REPOSICION DE GRASS M2')
