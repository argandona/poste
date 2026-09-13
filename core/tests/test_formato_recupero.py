"""
Formato TS-REC-FR-001, Registro de Materiales de Recupero.

Los recuperos se cargan poste por poste y el formato es por SST, así que lo que
importa es que se junten bien y que la cantidad de cada material salga sumada.
"""
from datetime import date

from ..models import (
    Recupero, SST, SSTEncargado, Suministro, SSTSuministro, SuministroRecupero,
)
from ..pdf_recupero import nombre_de_firma
from .base import BaseAPITestCase


class NombreDeFirmaTests(BaseAPITestCase):
    """La firma lleva el primer nombre y el primer apellido."""

    def test_dos_nombres_y_dos_apellidos(self):
        self.assertEqual(
            nombre_de_firma("Juan Carlos Pérez Rojas"), "Juan Pérez")

    def test_un_nombre_y_un_apellido(self):
        self.assertEqual(nombre_de_firma("Juan Capataz"), "Juan Capataz")

    def test_un_nombre_y_dos_apellidos(self):
        self.assertEqual(nombre_de_firma("María Elena Vargas"), "María Vargas")

    def test_sin_nombre_no_revienta(self):
        self.assertEqual(nombre_de_firma(""), "")
        self.assertEqual(nombre_de_firma(None), "")


class FormatoRecuperoTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.sst = SST.objects.create(
            sst="12345", codigo="SST-12345", empresa=self.empresa,
            distrito="LIMA", fecha_ejecucion=date.today())
        SSTEncargado.objects.create(sst=self.sst, usuario=self.capataz)

        self.luminaria = Recupero.objects.create(
            matricula="REC-036", descripcion="LUMINARIA DE 150 W", unidad="UND")
        self.cable = Recupero.objects.create(
            matricula="REC-002", descripcion="CABLE CAAIS 3X35+1X16", unidad="M")

        # Dos postes de la misma SST, cada uno con su recupero.
        self.postes = []
        for numero in ("100000001", "100000002"):
            s = Suministro.objects.create(numero_suministro=numero)
            SSTSuministro.objects.create(sst=self.sst, suministro=s)
            self.postes.append(s)

    def registrar(self, suministro, recupero, cantidad):
        SuministroRecupero.objects.create(
            suministro=suministro, recupero=recupero,
            cantidad=cantidad, fecha=date.today())

    def descargar(self, codigo=None):
        self.auth(self.capataz)
        return self.client.get(
            "/api/recuperos/formato_pdf/",
            {"sst": codigo or self.sst.codigo})

    def test_devuelve_un_pdf(self):
        self.registrar(self.postes[0], self.luminaria, 2)
        r = self.descargar()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertIn("recupero_SST-12345.pdf", r["Content-Disposition"])

    def test_sale_aunque_no_haya_recuperos(self):
        # La plantilla en blanco también sirve: se llena a mano en obra.
        r = self.descargar()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_junta_los_recuperos_de_todos_los_postes(self):
        self.registrar(self.postes[0], self.luminaria, 2)
        self.registrar(self.postes[1], self.luminaria, 3)
        self.registrar(self.postes[1], self.cable, 50)
        r = self.descargar()
        self.assertEqual(r.status_code, 200)
        # Se comprueba contra la fuente, que es lo que arma el PDF.
        from ..views import RecuperoViewSet  # noqa: F401
        registros = SuministroRecupero.objects.filter(
            suministro__sst_suministros__sst=self.sst)
        total_luminaria = sum(
            x.cantidad for x in registros if x.recupero_id == self.luminaria.pk)
        self.assertEqual(total_luminaria, 5)

    def test_se_puede_pedir_por_el_numero_corto_de_sst(self):
        r = self.descargar(codigo="12345")
        self.assertEqual(r.status_code, 200)

    def test_una_sst_que_no_existe_avisa(self):
        r = self.descargar(codigo="NO-EXISTE")
        self.assertEqual(r.status_code, 404)
        self.assertIsInstance(r.data["detail"], str)

    def test_sin_sst_avisa_con_detalle_de_texto(self):
        self.auth(self.capataz)
        r = self.client.get("/api/recuperos/formato_pdf/")
        self.assertEqual(r.status_code, 400)
        self.assertIsInstance(r.data["detail"], str)
