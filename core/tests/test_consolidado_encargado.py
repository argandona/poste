"""
El encargado ve su consolidado como el capataz: sus SST de reforzamiento con
lo liquidado, y desde ahí descarga los documentos.
"""
from datetime import date

from ..models import (SST, Actividad, ActividadTipoTrabajo, LiquidacionPartida,
                      LiquidacionSuministro, ManoDeObra, Rol, SSTSuministro,
                      Suministro, TipoTrabajo, Usuario)
from .base import BaseAPITestCase


class ConsolidadoEncargadoTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.obra = Usuario.objects.create(
            nombre='Encargado de Obra', empresa=self.empresa,
            email='obra@encossa.com', clave='x',
            rol=Rol.objects.create(id_rol=Rol.ENCARGADO, descripcion='Encargado'))
        actividad = Actividad.objects.create(
            nombre='Reforzamiento de poste con vereda', de_encargado=True)
        tipo = TipoTrabajo.objects.create(nombre='Reforzamiento con vereda')
        ActividadTipoTrabajo.objects.create(actividad=actividad, tipo_trabajo=tipo)
        self.sst = SST.objects.create(
            sst='8001', codigo='SST-8001', empresa=self.empresa, distrito='LIMA',
            actividad=actividad, fecha_ejecucion=date(2026, 10, 2))
        poste = Suministro.objects.create(numero_suministro='P-8001')
        SSTSuministro.objects.create(sst=self.sst, suministro=poste,
                                     asignado_a=self.obra)
        liq = LiquidacionSuministro.objects.create(
            suministro=poste, sst_externo='SST-8001', usuario=self.obra,
            tipo_trabajo=tipo)
        for codigo, precio in (('*094395', '53.30'), ('*090251', '467.52')):
            LiquidacionPartida.objects.create(
                liquidacion=liq, cantidad=1,
                mano_de_obra=ManoDeObra.objects.create(
                    partida=codigo, descripcion=codigo, precio=precio))
        # Otro que liquida aparte: no debe aparecerle al encargado.
        otro = Suministro.objects.create(numero_suministro='P-9999')
        LiquidacionSuministro.objects.create(
            suministro=otro, sst_externo='SST-9999', usuario=self.capataz,
            tipo_trabajo=tipo)

    def test_ve_solo_lo_suyo(self):
        self.auth(self.obra)
        r = self.client.get('/api/liquidaciones/consolidado/',
                            {'usuario': self.obra.pk})
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual([f['sst'] for f in r.json()], ['SST-8001'])

    def test_descarga_los_documentos(self):
        self.auth(self.obra)
        for ruta in ('/api/liquidaciones/excel/',
                     '/api/liquidaciones/cuaderno_obra/',
                     '/api/recuperos/formato_pdf/'):
            r = self.client.get(ruta, {'sst': 'SST-8001'})
            self.assertEqual(r.status_code, 200, (ruta, r.content[:300]))
