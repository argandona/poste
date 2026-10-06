"""
Liquidaciones pendientes: el SuperAdmin ve los postes asignados a capataces y
encargados que todavía no se liquidan, y puede deshacer la asignación. Lo ya
liquidado no se deshace.
"""
from datetime import date

from ..models import (SST, LiquidacionSuministro, Rol, SSTEncargado,
                      SSTSuministro, Suministro, TipoTrabajo, Usuario)
from .base import BaseAPITestCase

URL = '/api/ssts/pendientes_de_liquidar/'


class PendientesTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.admin = Usuario.objects.create(
            nombre='Admin', email='admin@tecsur.pe', clave='x', empresa=self.empresa,
            rol=Rol.objects.create(id_rol=Rol.SUPERADMIN, descripcion='SuperAdmin'))
        self.obra = Usuario.objects.create(
            nombre='Encargado de Obra', email='obra@x.com', clave='x',
            empresa=self.empresa,
            rol=Rol.objects.create(id_rol=Rol.ENCARGADO, descripcion='Encargado'))
        self.sst = SST.objects.create(sst='1', codigo='SST-1', empresa=self.empresa,
                                      fecha_inicio=date(2026, 10, 1))
        self.p1 = self.poste('P-1', self.obra)
        self.p2 = self.poste('P-2', self.obra)
        self.p3 = self.poste('P-3', self.capataz)
        SSTEncargado.objects.create(sst=self.sst, usuario=self.obra)
        SSTEncargado.objects.create(sst=self.sst, usuario=self.capataz)
        # Sin asignar: no es pendiente de nadie.
        self.poste('P-4', None)

    def poste(self, numero, usuario):
        s = Suministro.objects.create(numero_suministro=numero)
        SSTSuministro.objects.create(sst=self.sst, suministro=s, asignado_a=usuario)
        return s

    def liquidar(self, suministro):
        suministro.estado = 'ejecutado'
        suministro.save()
        LiquidacionSuministro.objects.create(
            suministro=suministro, usuario=self.obra,
            tipo_trabajo=TipoTrabajo.objects.get_or_create(nombre='T')[0])

    def test_ve_lo_asignado_y_sin_liquidar_de_capataces_y_encargados(self):
        self.liquidar(self.p2)
        self.auth(self.admin)
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200, r.content)
        por_persona = {p['nombre']: [x['numero'] for s in p['ssts']
                                     for x in s['postes']] for p in r.json()}
        self.assertEqual(por_persona, {'Encargado de Obra': ['P-1'],
                                       'Capataz Uno': ['P-3']})

    def test_solo_el_superadmin(self):
        for quien in (self.capataz, self.encargado, self.obra):
            self.auth(quien)
            self.assertEqual(self.client.get(URL).status_code, 403, quien.email)

    def test_deshacer_un_poste(self):
        self.auth(self.admin)
        r = self.client.post(f'/api/ssts/{self.sst.pk}/desasignar/',
                             {'suministros': [self.p1.pk]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNone(SSTSuministro.objects.get(suministro=self.p1).asignado_a)
        # Le queda P-2: sigue siendo encargado de la SST.
        self.assertTrue(SSTEncargado.objects.filter(
            sst=self.sst, usuario=self.obra).exists())

    def test_sin_postes_deja_de_ser_encargado_de_la_sst(self):
        self.auth(self.admin)
        self.client.post(f'/api/ssts/{self.sst.pk}/desasignar/',
                         {'suministros': [self.p1.pk, self.p2.pk]}, format='json')
        self.assertFalse(SSTEncargado.objects.filter(
            sst=self.sst, usuario=self.obra).exists())
        self.assertTrue(SSTEncargado.objects.filter(
            sst=self.sst, usuario=self.capataz).exists())

    def test_lo_liquidado_no_se_deshace(self):
        self.liquidar(self.p2)
        self.auth(self.admin)
        r = self.client.post(f'/api/ssts/{self.sst.pk}/desasignar/',
                             {'suministros': [self.p1.pk, self.p2.pk]},
                             format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('P-2', r.json()['detail'])
        # No se tocó nada, tampoco P-1.
        self.assertEqual(SSTSuministro.objects.get(suministro=self.p1).asignado_a,
                         self.obra)

    def test_deshacer_toda_la_sst_pendiente(self):
        self.auth(self.admin)
        r = self.client.post(f'/api/ssts/{self.sst.pk}/desasignar/', {},
                             format='json')
        self.assertEqual(r.json()['suministros_desasignados'], 3)
        self.assertFalse(SSTEncargado.objects.filter(sst=self.sst).exists())
