"""
Agregar un punto de trabajo a una SST.

En una reforma los postes aparecen en obra: no vienen en la asignación, los
suma el capataz mientras trabaja. Solo en las actividades que admiten varios;
en cambio de poste una SST es un poste y ahí esto no se puede.
"""
from datetime import date

from ..models import (
    Actividad, SST, SSTSuministro, Suministro,
)
from .base import BaseAPITestCase

REFORMA = "Reforma - cambio de poste inacc. aereo - cabria"
AEREA = "Cambio de poste inacc. cabria aereo"


class PuntoDeTrabajoTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.reforma = Actividad.objects.create(
            nombre=REFORMA, varios_postes=True)
        self.aerea = Actividad.objects.create(nombre=AEREA)
        self.sst = SST.objects.create(
            sst="3920624", codigo="SST-3920624", empresa=self.empresa,
            distrito="SURCO", actividad=self.reforma,
            fecha_ejecucion=date.today())

    def agregar(self, numero, codigo=None, como=None):
        self.auth(como or self.capataz)
        return self.client.post("/api/ssts/agregar_punto/", {
            "sst_codigo": codigo or self.sst.codigo,
            "numero_suministro": numero,
        }, format="json")

    def postes_de_la_sst(self):
        return list(SSTSuministro.objects
                    .filter(sst=self.sst)
                    .order_by("id_sst_suministro")
                    .values_list("suministro__numero_suministro", flat=True))

    # ── Agregar ─────────────────────────────────────────────────────────────

    def test_se_agrega_el_poste_a_la_sst(self):
        r = self.agregar("771000100")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.postes_de_la_sst(), ["771000100"])

    def test_queda_asignado_a_quien_lo_agrego(self):
        """Si no, no le aparece al capataz en su semana de trabajo."""
        self.agregar("771000100")
        rel = SSTSuministro.objects.get(sst=self.sst)
        self.assertEqual(rel.asignado_a_id, self.capataz.pk)

    def test_nace_asignado_para_que_se_pueda_liquidar(self):
        self.agregar("771000100")
        poste = Suministro.objects.get(numero_suministro="771000100")
        self.assertEqual(poste.estado, "asignado")
        self.assertEqual(poste.distrito, "SURCO")

    def test_se_pueden_agregar_varios(self):
        for numero in ("771000100", "771000101", "771000102"):
            self.assertEqual(self.agregar(numero).status_code, 201)
        self.assertEqual(self.postes_de_la_sst(),
                         ["771000100", "771000101", "771000102"])

    def test_devuelve_el_poste_para_que_la_app_lo_muestre(self):
        r = self.agregar("771000100")
        self.assertEqual(r.data["numero_suministro"], "771000100")
        self.assertEqual(r.data["sst_codigo"], self.sst.codigo)
        self.assertEqual(r.data["actividad"], REFORMA)

    # ── Lo que no se permite ────────────────────────────────────────────────

    def test_en_cambio_de_poste_no_se_puede(self):
        """Ahí una SST es un poste: el botón no existe y el backend lo cierra."""
        self.sst.actividad = self.aerea
        self.sst.save(update_fields=["actividad"])
        r = self.agregar("771000100")
        self.assertEqual(r.status_code, 400)
        self.assertIn("un solo poste", r.data["detail"])

    def test_sin_actividad_tampoco(self):
        self.sst.actividad = None
        self.sst.save(update_fields=["actividad"])
        self.assertEqual(self.agregar("771000100").status_code, 400)

    def test_el_mismo_poste_dos_veces_avisa(self):
        self.agregar("771000100")
        r = self.agregar("771000100")
        self.assertEqual(r.status_code, 400)
        self.assertIn("ya está en esta SST", r.data["detail"])

    def test_un_poste_de_otra_sst_avisa_de_cual(self):
        otra = SST.objects.create(
            sst="9999", codigo="SST-9999", empresa=self.empresa,
            distrito="LIMA", actividad=self.reforma)
        poste = Suministro.objects.create(numero_suministro="771000100")
        SSTSuministro.objects.create(sst=otra, suministro=poste)
        r = self.agregar("771000100")
        self.assertEqual(r.status_code, 400)
        self.assertIn("SST-9999", r.data["detail"])

    def test_un_poste_suelto_se_reaprovecha(self):
        """Existe en el catálogo pero no está en ninguna SST: se cuelga aquí
        en vez de fallar por número repetido."""
        Suministro.objects.create(numero_suministro="771000100")
        self.assertEqual(self.agregar("771000100").status_code, 201)
        self.assertEqual(
            Suministro.objects.filter(numero_suministro="771000100").count(), 1)

    def test_faltando_datos_no_hace_nada(self):
        self.auth(self.capataz)
        r = self.client.post("/api/ssts/agregar_punto/",
                             {"sst_codigo": self.sst.codigo}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_una_sst_que_no_existe(self):
        r = self.agregar("771000100", codigo="SST-NO-EXISTE")
        self.assertEqual(r.status_code, 404)

    def test_hay_que_estar_autenticado(self):
        self.client.credentials()
        r = self.client.post("/api/ssts/agregar_punto/", {
            "sst_codigo": self.sst.codigo,
            "numero_suministro": "771000100",
        }, format="json")
        self.assertIn(r.status_code, (401, 403))

    # ── El selector de puntos ───────────────────────────────────────────────

    def puntos(self, codigo=None):
        self.auth(self.capataz)
        return self.client.get("/api/ssts/puntos/",
                               {"sst_codigo": codigo or self.sst.codigo})

    def test_los_puntos_salen_en_el_orden_en_que_se_agregaron(self):
        for numero in ("771000100", "771000101", "771000102"):
            self.agregar(numero)
        r = self.puntos()
        self.assertEqual([p["numero_suministro"] for p in r.data["puntos"]],
                         ["771000100", "771000101", "771000102"])

    def test_los_puntos_dicen_si_la_sst_admite_varios(self):
        self.assertTrue(self.puntos().data["varios_postes"])
        self.sst.actividad = self.aerea
        self.sst.save(update_fields=["actividad"])
        self.assertFalse(self.puntos().data["varios_postes"])

    def test_una_sst_sin_postes_devuelve_la_lista_vacia(self):
        self.assertEqual(self.puntos().data["puntos"], [])

    def test_los_puntos_de_una_sst_que_no_existe(self):
        self.assertEqual(self.puntos(codigo="SST-NO-EXISTE").status_code, 404)

    # ── La app sabe cuándo mostrar el botón ─────────────────────────────────

    def test_las_actividades_dicen_si_admiten_varios_postes(self):
        self.auth(self.capataz)
        r = self.client.get("/api/actividades/")
        datos = r.data["results"] if isinstance(r.data, dict) else r.data
        porque = {a["nombre"]: a["varios_postes"] for a in datos}
        self.assertTrue(porque[REFORMA])
        self.assertFalse(porque[AEREA])
