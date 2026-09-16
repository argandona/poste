"""
Un usuario con dos sombreros.

En obra hay gente que es capataz y coordinador a la vez. Con un solo rol
tendría que entrar con dos cuentas distintas, así que el usuario lleva un rol
secundario y las capacidades miran los dos.
"""
from django.core.exceptions import ValidationError

from ..models import Rol, SST, SSTEncargado, Usuario
from .base import BaseAPITestCase


class RolSecundarioTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.rol_coordinador = Rol.objects.create(
            id_rol=Rol.COORDINADOR, descripcion="Coordinador")
        self.doble = Usuario.objects.create(
            nombre="Hugo Salas", rol=self.rol_capataz,
            rol_secundario=self.rol_coordinador, empresa=self.empresa,
            email="salas@encossa.com", clave="x")

    def test_conserva_lo_que_puede_su_rol_principal(self):
        self.assertTrue(self.doble.puede_hacer_pedido())
        self.assertTrue(self.doble.puede_hacer_inventario())

    def test_gana_lo_que_puede_el_secundario(self):
        self.assertTrue(self.doble.puede_asignar_sst())

    def test_el_capataz_solo_sigue_sin_poder_asignar(self):
        self.assertFalse(self.capataz.puede_asignar_sst())

    def test_no_gana_lo_que_no_le_toca_a_ninguno_de_los_dos(self):
        self.assertFalse(self.doble.puede_gestionar_almacen())
        self.assertFalse(self.doble.es_superadmin())

    def test_los_dos_roles_tienen_que_ser_distintos(self):
        self.doble.rol_secundario = self.rol_capataz
        with self.assertRaises(ValidationError):
            self.doble.full_clean()

    def test_sin_rol_secundario_todo_sigue_igual(self):
        self.assertEqual(self.capataz.roles, {Rol.CAPATAZ})
        self.assertTrue(self.capataz.puede_hacer_pedido())

    def test_asigna_sst_de_verdad_por_el_api(self):
        sst = SST.objects.create(
            empresa=self.empresa, codigo="SST-DOBLE", distrito="Lima")
        self.auth(self.doble)
        r = self.client.post("/api/ssts/asignar_manual/", {
            "sst_codigo": sst.codigo,
            "numero_suministro": "P-DOBLE",
            "usuario": self.capataz.pk,
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_sale_en_la_lista_de_capataces_de_una_sst(self):
        # El formato de recupero busca al capataz de la SST; quien lo es por
        # su rol principal tiene que aparecer igual.
        sst = SST.objects.create(
            empresa=self.empresa, codigo="SST-CAP", distrito="Lima")
        SSTEncargado.objects.create(sst=sst, usuario=self.doble)
        from ..views import con_rol
        encontrado = (Usuario.objects
                      .filter(con_rol(Rol.CAPATAZ), sst_encargados__sst=sst)
                      .first())
        self.assertEqual(encontrado, self.doble)

    def test_el_token_lleva_los_dos_roles(self):
        from ..authentication import CustomRefreshToken
        token = CustomRefreshToken.for_usuario(self.doble)
        self.assertEqual(token["rol_id"], Rol.CAPATAZ)
        self.assertEqual(token["rol_secundario_id"], Rol.COORDINADOR)

    def test_el_login_devuelve_los_dos_roles(self):
        # La app arma sus módulos con lo que viene en el login.
        import hashlib
        self.doble.clave = hashlib.sha256(b"secreto").hexdigest()
        self.doble.save(update_fields=["clave"])

        r = self.client.post("/api/auth/login/",
                             {"email": self.doble.email, "clave": "secreto"},
                             format="json")

        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["usuario"]["rol_id"], Rol.CAPATAZ)
        self.assertEqual(r.data["usuario"]["rol_secundario_id"], Rol.COORDINADOR)
        self.assertEqual(r.data["usuario"]["rol_secundario"], "Coordinador")

    def test_sin_rol_secundario_el_login_lo_manda_vacio(self):
        import hashlib
        self.capataz.clave = hashlib.sha256(b"secreto").hexdigest()
        self.capataz.save(update_fields=["clave"])

        r = self.client.post("/api/auth/login/",
                             {"email": self.capataz.email, "clave": "secreto"},
                             format="json")

        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNone(r.data["usuario"]["rol_secundario_id"])
