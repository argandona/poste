"""
Gestión de unidades de transporte: solo el SuperAdmin crea, modifica,
elimina (o da de baja) y asigna las unidades, y solo a capataces y
encargados.
"""
from datetime import date, timedelta
from unittest import mock

from ..models import Camion, Rol, StockCamion, Usuario, UsuarioCamion
from .base import BaseAPITestCase

URL = '/api/camiones/'


class UnidadesTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.admin = Usuario.objects.create(
            nombre='Admin', email='admin@tecsur.pe', clave='x', empresa=self.empresa,
            rol=Rol.objects.create(id_rol=Rol.SUPERADMIN, descripcion='SuperAdmin'))
        self.obra = Usuario.objects.create(
            nombre='Encargado de Obra', email='obra@x.com', clave='x',
            empresa=self.empresa, fcm_token='tok-obra',
            rol=Rol.objects.create(id_rol=Rol.ENCARGADO, descripcion='Encargado'))

    def crear(self, usuario=None, **datos):
        self.auth(usuario or self.admin)
        return self.client.post(URL, {
            'placa': ' cmz-999 ', 'descripcion': 'Camioneta 4x4',
            'vence_soat': '2027-03-01', 'vence_revision_tecnica': '2026-12-15',
            **datos}, format='json')

    # ── Crear y modificar ────────────────────────────────────────────────────

    def test_el_superadmin_crea_la_unidad(self):
        r = self.crear()
        self.assertEqual(r.status_code, 201, r.content)
        c = Camion.objects.get(placa='CMZ-999')
        self.assertEqual((c.empresa, str(c.vence_soat), str(c.vence_revision_tecnica)),
                         (self.empresa, '2027-03-01', '2026-12-15'))
        self.assertIsNone(r.json()['responsable'])

    def test_nadie_mas_crea_ni_modifica(self):
        for quien in (self.capataz, self.encargado, self.obra):
            self.assertEqual(self.crear(quien).status_code, 403, quien.email)
            r = self.client.patch(f'{URL}{self.camion.pk}/',
                                  {'descripcion': 'x'}, format='json')
            self.assertEqual(r.status_code, 403, quien.email)
        self.assertFalse(Camion.objects.filter(placa='CMZ-999').exists())

    def test_todos_la_ven_con_su_responsable(self):
        self.auth(self.capataz)
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        fila = next(c for c in r.json()['results'] if c['placa'] == 'ABC-123')
        self.assertEqual(fila['responsable']['nombre'], self.capataz.nombre)

    def test_placa_repetida(self):
        self.crear()
        self.assertEqual(self.crear(placa='CMZ-999').status_code, 400)

    def test_modificar_vencimientos(self):
        self.auth(self.admin)
        r = self.client.patch(f'{URL}{self.camion.pk}/',
                              {'vence_soat': '2027-01-31'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.camion.refresh_from_db()
        self.assertEqual(str(self.camion.vence_soat), '2027-01-31')

    # ── Eliminar o dar de baja ───────────────────────────────────────────────

    def test_sin_uso_se_elimina(self):
        pk = self.crear().json()['id_camion']
        r = self.client.delete(f'{URL}{pk}/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['eliminada'])
        self.assertFalse(Camion.objects.filter(pk=pk).exists())

    def test_con_historia_se_da_de_baja_y_se_reactiva(self):
        # Tuvo responsable y stock, ya liberado.
        self.asignacion.fecha_fin = date.today() - timedelta(days=1)
        UsuarioCamion.objects.filter(pk=self.asignacion.pk).update(
            fecha_fin=date.today() - timedelta(days=1), activo=False)
        StockCamion.objects.create(camion=self.camion, material=self.material_a,
                                   cantidad=0)
        self.auth(self.admin)
        r = self.client.delete(f'{URL}{self.camion.pk}/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()['eliminada'])
        self.camion.refresh_from_db()
        self.assertFalse(self.camion.activo)
        r = self.client.post(f'{URL}{self.camion.pk}/reactivar/')
        self.assertEqual(r.status_code, 200)
        self.camion.refresh_from_db()
        self.assertTrue(self.camion.activo)

    def test_con_responsable_no_se_toca(self):
        self.auth(self.admin)
        r = self.client.delete(f'{URL}{self.camion.pk}/')
        self.assertEqual(r.status_code, 400)
        self.assertIn('Responsables de Camión', r.json()['detail'])
        self.assertTrue(Camion.objects.get(pk=self.camion.pk).activo)

    def test_nadie_mas_elimina(self):
        pk = self.crear().json()['id_camion']
        self.auth(self.capataz)
        self.assertEqual(self.client.delete(f'{URL}{pk}/').status_code, 403)

    # ── Asignar ──────────────────────────────────────────────────────────────

    def asignar(self, camion_id, usuario):
        self.auth(self.admin)
        with mock.patch('core.fcm.send_notification') as avisar:
            r = self.client.post(f'{URL}{camion_id}/asignar/',
                                 {'usuario': usuario.pk}, format='json')
        return r, avisar

    def test_se_asigna_a_un_encargado_y_le_llega_el_aviso(self):
        pk = self.crear().json()['id_camion']
        r, avisar = self.asignar(pk, self.obra)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['responsable']['nombre'], 'Encargado de Obra')
        a = UsuarioCamion.objects.get(camion_id=pk)
        self.assertEqual((a.usuario, a.fecha_fin), (self.obra, None))
        self.assertEqual(avisar.call_args.args[0], ['tok-obra'])

    def test_solo_capataces_y_encargados(self):
        pk = self.crear().json()['id_camion']
        r, _ = self.asignar(pk, self.encargado)  # encargado de almacén
        self.assertEqual(r.status_code, 400)
        self.assertFalse(UsuarioCamion.objects.filter(camion_id=pk).exists())

    def test_una_unidad_con_responsable_no_se_vuelve_a_asignar(self):
        r, _ = self.asignar(self.camion.pk, self.obra)
        self.assertEqual(r.status_code, 400)

    def test_una_unidad_de_baja_no_se_asigna(self):
        pk = self.crear().json()['id_camion']
        Camion.objects.filter(pk=pk).update(activo=False)
        r, _ = self.asignar(pk, self.obra)
        self.assertEqual(r.status_code, 400)

    def test_nadie_mas_asigna(self):
        pk = self.crear().json()['id_camion']
        self.auth(self.encargado)
        r = self.client.post(f'{URL}{pk}/asignar/', {'usuario': self.obra.pk},
                             format='json')
        self.assertEqual(r.status_code, 403)
