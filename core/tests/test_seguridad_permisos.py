"""Nadie ve los datos de otro cambiando el número en la dirección.

El consolidado de liquidaciones solo lo ve quien liquida (lo suyo) o quien
supervisa (el de todos, de su empresa). Las consultas con `?usuario=<id>`
responden lo del propio usuario; las de otro, solo a quien supervisa y de su
misma empresa."""
from ..models import (
    Empresa, LiquidacionSuministro, Rol, SST, SSTEncargado, StockCamion,
    TipoTrabajo, Usuario,
)
from .base import BaseAPITestCase


class SeguridadPermisosTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.chofer = Usuario.objects.create(
            nombre="Chofer", email="chofer@tecsur.pe", clave="x", empresa=self.empresa,
            rol=Rol.objects.create(id_rol=Rol.CHOFER, descripcion="Chofer"))
        self.coordinador = Usuario.objects.create(
            nombre="Coordinador", email="coord@tecsur.pe", clave="x", empresa=self.empresa,
            rol=Rol.objects.create(id_rol=Rol.COORDINADOR, descripcion="Coordinador"))
        self.otro_capataz = Usuario.objects.create(
            nombre="Capataz Dos", email="dos@tecsur.pe", clave="x", empresa=self.empresa,
            rol=self.rol_capataz)
        otra = Empresa.objects.create(nombre="OTRA", ruc="20100000002")
        self.de_otra = Usuario.objects.create(
            nombre="Capataz Otra", email="otra@x.pe", clave="x", empresa=otra,
            rol=self.rol_capataz)
        tipo = TipoTrabajo.objects.create(nombre="Cambio")
        for u, sst in ((self.capataz, '1111111'), (self.otro_capataz, '2222222'),
                       (self.de_otra, '3333333')):
            LiquidacionSuministro.objects.create(
                usuario=u, tipo_trabajo=tipo, suministro_externo='P', sst_externo=sst)
        sst = SST.objects.create(empresa=self.empresa, codigo='SST-1')
        SSTEncargado.objects.create(sst=sst, usuario=self.capataz)
        StockCamion.objects.create(camion=self.camion, material=self.material_a, cantidad=3)

    def get(self, quien, url, **q):
        self.auth(quien)
        return self.client.get(url, q)

    @staticmethod
    def ssts(r):
        return sorted(f['sst'] for f in r.json())

    # ── Consolidado ──────────────────────────────────────────────────────────

    def test_el_chofer_no_ve_el_consolidado(self):
        self.assertEqual(self.get(self.chofer, '/api/liquidaciones/consolidado/')
                         .status_code, 403)

    def test_el_capataz_solo_ve_lo_suyo_aunque_pida_otro(self):
        url = '/api/liquidaciones/consolidado/'
        r = self.get(self.capataz, url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ssts(r), ['1111111'])
        self.assertEqual(self.ssts(self.get(self.capataz, url, usuario=self.otro_capataz.pk)),
                         ['1111111'])

    def test_el_coordinador_ve_todo_de_su_empresa_y_no_de_otra(self):
        url = '/api/liquidaciones/consolidado/'
        self.assertEqual(self.ssts(self.get(self.coordinador, url)),
                         ['1111111', '2222222'])
        self.assertEqual(self.ssts(self.get(self.coordinador, url,
                                            usuario=self.otro_capataz.pk)), ['2222222'])
        self.assertEqual(self.ssts(self.get(self.coordinador, url,
                                            usuario=self.de_otra.pk)), [])

    # ── Consultas con ?usuario= ──────────────────────────────────────────────

    def test_mis_sst_de_otro_no(self):
        url = '/api/ssts/mis_sst/'
        self.assertEqual(self.get(self.capataz, url, usuario=self.capataz.pk).status_code, 200)
        self.assertEqual(self.get(self.otro_capataz, url, usuario=self.capataz.pk)
                         .status_code, 403)
        # Quien asigna sí, de su empresa.
        r = self.get(self.coordinador, url, usuario=self.capataz.pk)
        self.assertEqual([s['codigo'] for s in r.json()], ['SST-1'])
        self.assertEqual(self.get(self.coordinador, url, usuario=self.de_otra.pk)
                         .status_code, 403)

    def test_el_camion_activo_de_otro_no(self):
        url = '/api/usuario-camion/camion_activo/'
        self.assertEqual(self.get(self.capataz, url, usuario=self.capataz.pk).status_code, 200)
        self.assertEqual(self.get(self.chofer, url, usuario=self.capataz.pk).status_code, 403)
        self.assertEqual(self.get(self.encargado, url, usuario=self.capataz.pk).status_code,
                         200)

    def test_la_semana_de_otro_no(self):
        for url in ('/api/liquidaciones/semana_trabajo/', '/api/planos/semana_sst/'):
            self.assertEqual(self.get(self.otro_capataz, url, usuario=self.capataz.pk)
                             .status_code, 403, url)
            self.assertEqual(self.get(self.capataz, url, usuario=self.capataz.pk)
                             .status_code, 200, url)

    def test_los_saldos_de_todos_los_camiones_solo_el_almacen(self):
        url = '/api/stock-camion/por_camion/'
        self.assertEqual(self.get(self.capataz, url).status_code, 403)
        self.assertEqual(self.get(self.otro_capataz, url, usuario=self.capataz.pk)
                         .status_code, 403)
        r = self.get(self.capataz, url, usuario=self.capataz.pk)
        self.assertEqual([c['placa'] for c in r.json()], ['ABC-123'])
        self.assertEqual(len(self.get(self.encargado, url).json()), 1)
