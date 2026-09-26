"""
Agregar un punto de trabajo a una SST.

En una reforma los postes aparecen en obra: no vienen en la asignación, los
suma el capataz mientras trabaja. Solo en las actividades que admiten varios;
en cambio de poste una SST es un poste y ahí esto no se puede.
"""
from datetime import date

from ..models import (
    Actividad, ConsumoMaterialSuministro, CorreccionLiquidacion,
    LiquidacionPartida, LiquidacionSuministro, ManoDeObra, Recupero, Rol, SST,
    SSTSuministro, StockCamion, Suministro, SuministroRecupero, TipoTrabajo,
    Usuario,
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

    def test_el_mismo_numero_en_otra_sst_ahora_si_se_puede(self):
        """Antes esto avisaba "ya pertenece a la SST tal".

        El capataz numera los puntos de cada reforma como Poste 01, Poste 02:
        son etiquetas que se repiten en toda SST. El número solo tiene que ser
        único dentro de la suya."""
        otra = SST.objects.create(
            sst="9999", codigo="SST-9999", empresa=self.empresa,
            distrito="LIMA", actividad=self.reforma)
        poste = Suministro.objects.create(numero_suministro="Poste 01")
        SSTSuministro.objects.create(sst=otra, suministro=poste)
        r = self.agregar("Poste 01")
        self.assertEqual(r.status_code, 201, r.data)

    def test_cada_sst_tiene_su_propio_registro(self):
        """Si compartieran uno, las liquidaciones de una SST saldrían en el
        cuaderno y el Excel de la otra."""
        otra = SST.objects.create(
            sst="9999", codigo="SST-9999", empresa=self.empresa,
            distrito="LIMA", actividad=self.reforma)
        ajeno = Suministro.objects.create(numero_suministro="Poste 01")
        SSTSuministro.objects.create(sst=otra, suministro=ajeno)
        r = self.agregar("Poste 01")
        self.assertNotEqual(r.data["id_suministro"], ajeno.pk)
        self.assertEqual(
            Suministro.objects.filter(numero_suministro="Poste 01").count(), 2)

    def test_lo_liquidado_no_se_mezcla_entre_sst(self):
        from ..cuaderno_obra import reunir

        otra = SST.objects.create(
            sst="9999", codigo="SST-9999", empresa=self.empresa,
            distrito="LIMA", actividad=self.reforma)
        ajeno = Suministro.objects.create(numero_suministro="Poste 01")
        SSTSuministro.objects.create(sst=otra, suministro=ajeno)
        LiquidacionSuministro.objects.create(
            suministro=ajeno, sst_externo=otra.codigo, usuario=self.capataz,
            tipo_trabajo=TipoTrabajo.objects.create(nombre="Poste cabria"))
        self.agregar("Poste 01")
        # La SST nueva tiene su Poste 01, pero vacío: lo liquidado es de la otra.
        self.assertEqual(reunir(self.sst).por_poste, [])
        self.assertEqual(len(reunir(otra).por_poste), 1)

    def test_el_mismo_numero_dos_veces_en_la_misma_sst_sigue_avisando(self):
        self.agregar("Poste 01")
        r = self.agregar("Poste 01")
        self.assertEqual(r.status_code, 400)
        self.assertIn("ya está en esta SST", r.data["detail"])


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


class EditarPuntosTests(BaseAPITestCase):
    """Corregir los puntos de trabajo: renombrarlos, moverlos y quitarlos.

    El capataz los va agregando en obra y se equivoca: teclea mal un número,
    los crea en otro orden del que trabajó, o suma uno que no era. Todo eso se
    arregla desde la misma pantalla.
    """

    def setUp(self):
        super().setUp()
        self.reforma = Actividad.objects.create(
            nombre=REFORMA, varios_postes=True)
        self.sst = SST.objects.create(
            sst="3920624", codigo="SST-3920624", empresa=self.empresa,
            distrito="SURCO", actividad=self.reforma,
            fecha_ejecucion=date.today())
        self.tipo = TipoTrabajo.objects.create(nombre="Poste cabria")
        self.partida = ManoDeObra.objects.create(
            partida="*094395", descripcion="INSPECCION", precio="53.30")

    def agregar(self, numero):
        self.auth(self.capataz)
        r = self.client.post("/api/ssts/agregar_punto/", {
            "sst_codigo": self.sst.codigo, "numero_suministro": numero,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["id_suministro"]

    def numeros(self):
        self.auth(self.capataz)
        r = self.client.get("/api/ssts/puntos/",
                            {"sst_codigo": self.sst.codigo})
        return [p["numero_suministro"] for p in r.data["puntos"]]

    def liquidar(self, id_suministro, cantidad=1):
        liq = LiquidacionSuministro.objects.create(
            suministro_id=id_suministro, sst_externo=self.sst.codigo,
            usuario=self.capataz, tipo_trabajo=self.tipo)
        LiquidacionPartida.objects.create(
            liquidacion=liq, mano_de_obra=self.partida, cantidad=cantidad)
        return liq

    # ── Renombrar ───────────────────────────────────────────────────────────

    def test_se_corrige_el_numero(self):
        uno = self.agregar("771000100")
        self.auth(self.capataz)
        r = self.client.post("/api/ssts/renombrar_punto/", {
            "sst_codigo": self.sst.codigo, "id_suministro": uno,
            "numero_suministro": "771000199",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.numeros(), ["771000199"])

    def test_lo_liquidado_sigue_colgado_del_punto(self):
        """Renombrar es corregir un tipeo: no se pierde nada."""
        uno = self.agregar("771000100")
        liq = self.liquidar(uno)
        self.auth(self.capataz)
        self.client.post("/api/ssts/renombrar_punto/", {
            "sst_codigo": self.sst.codigo, "id_suministro": uno,
            "numero_suministro": "771000199",
        }, format="json")
        liq.refresh_from_db()
        self.assertEqual(liq.suministro.numero_suministro, "771000199")

    def test_no_se_puede_pisar_un_numero_que_ya_existe(self):
        uno = self.agregar("771000100")
        self.agregar("771000101")
        self.auth(self.capataz)
        r = self.client.post("/api/ssts/renombrar_punto/", {
            "sst_codigo": self.sst.codigo, "id_suministro": uno,
            "numero_suministro": "771000101",
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("ya está en esta SST", r.data["detail"])

    # ── Mover ───────────────────────────────────────────────────────────────

    def test_se_pueden_acomodar_en_otro_orden(self):
        uno = self.agregar("Poste 01")
        dos = self.agregar("Poste 02")
        tres = self.agregar("091002020")
        self.assertEqual(self.numeros(), ["Poste 01", "Poste 02", "091002020"])
        self.auth(self.capataz)
        r = self.client.post("/api/ssts/ordenar_puntos/", {
            "sst_codigo": self.sst.codigo, "ids": [tres, uno, dos],
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.numeros(), ["091002020", "Poste 01", "Poste 02"])

    def test_un_punto_que_no_vino_en_la_lista_queda_al_final(self):
        uno = self.agregar("771000100")
        dos = self.agregar("771000101")
        self.agregar("771000102")
        self.auth(self.capataz)
        self.client.post("/api/ssts/ordenar_puntos/", {
            "sst_codigo": self.sst.codigo, "ids": [dos, uno],
        }, format="json")
        self.assertEqual(self.numeros(),
                         ["771000101", "771000100", "771000102"])

    def test_no_se_puede_meter_un_punto_de_otra_sst(self):
        self.agregar("771000100")
        otra = SST.objects.create(
            sst="9999", codigo="SST-9999", empresa=self.empresa,
            distrito="LIMA", actividad=self.reforma)
        ajeno = Suministro.objects.create(numero_suministro="880000100")
        SSTSuministro.objects.create(sst=otra, suministro=ajeno)
        self.auth(self.capataz)
        r = self.client.post("/api/ssts/ordenar_puntos/", {
            "sst_codigo": self.sst.codigo, "ids": [ajeno.pk],
        }, format="json")
        self.assertEqual(r.status_code, 400)

    def test_el_punto_nuevo_se_agrega_al_final(self):
        uno = self.agregar("771000100")
        dos = self.agregar("771000101")
        self.auth(self.capataz)
        self.client.post("/api/ssts/ordenar_puntos/", {
            "sst_codigo": self.sst.codigo, "ids": [dos, uno],
        }, format="json")
        self.agregar("771000102")
        self.assertEqual(self.numeros(),
                         ["771000101", "771000100", "771000102"])

    # ── Quitar ──────────────────────────────────────────────────────────────

    def test_se_quita_un_punto_vacio(self):
        self.agregar("771000100")
        dos = self.agregar("771000101")
        self.auth(self.capataz)
        r = self.client.post("/api/ssts/quitar_punto/", {
            "sst_codigo": self.sst.codigo, "id_suministro": dos,
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.numeros(), ["771000100"])
        self.assertFalse(
            Suministro.objects.filter(numero_suministro="771000101").exists())

    def test_se_lleva_lo_liquidado_y_el_recupero(self):
        uno = self.agregar("771000100")
        self.liquidar(uno)
        recupero = Recupero.objects.create(
            matricula="REC-001", descripcion="CABLE CAAIS 3X16+1X16")
        SuministroRecupero.objects.create(
            suministro_id=uno, recupero=recupero, cantidad=12,
            fecha=date.today())
        self.auth(self.capataz)
        r = self.client.post("/api/ssts/quitar_punto/", {
            "sst_codigo": self.sst.codigo, "id_suministro": uno,
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["liquidaciones_borradas"], 1)
        self.assertEqual(r.data["recuperos_borrados"], 1)
        self.assertEqual(LiquidacionSuministro.objects.count(), 0)
        self.assertEqual(SuministroRecupero.objects.count(), 0)

    def test_queda_el_acta_de_lo_que_se_borro(self):
        """El usuario pidió que el punto se fuera entero, pero lo que decía
        queda registrado: es plata que alguien liquidó."""
        uno = self.agregar("771000100")
        self.liquidar(uno, cantidad=3)
        self.auth(self.capataz)
        self.client.post("/api/ssts/quitar_punto/", {
            "sst_codigo": self.sst.codigo, "id_suministro": uno,
        }, format="json")
        acta = CorreccionLiquidacion.objects.get()
        self.assertIn("Se eliminó el punto de trabajo 771000100",
                      acta.cambios)
        self.assertEqual(acta.anterior["partidas"][0]["cantidad"], "3")

    def test_el_material_vuelve_al_camion(self):
        uno = self.agregar("771000100")
        stock = StockCamion.objects.create(
            camion=self.camion, material=self.material_a, cantidad=10)
        liq = self.liquidar(uno)
        ConsumoMaterialSuministro.objects.create(
            liquidacion=liq, suministro_id=uno, material=self.material_a,
            usuario=self.capataz, cantidad=4)
        self.auth(self.capataz)
        self.client.post("/api/ssts/quitar_punto/", {
            "sst_codigo": self.sst.codigo, "id_suministro": uno,
        }, format="json")
        stock.refresh_from_db()
        self.assertEqual(str(stock.cantidad), "14.00")

    def test_un_punto_de_otra_sst_no_se_toca(self):
        # El capataz trabaja en esta SST, pero el punto que manda es de otra.
        self.agregar("771000100")
        otra = SST.objects.create(
            sst="9999", codigo="SST-9999", empresa=self.empresa,
            distrito="LIMA", actividad=self.reforma)
        ajeno = Suministro.objects.create(numero_suministro="880000100")
        SSTSuministro.objects.create(sst=otra, suministro=ajeno)
        self.auth(self.capataz)
        r = self.client.post("/api/ssts/quitar_punto/", {
            "sst_codigo": self.sst.codigo, "id_suministro": ajeno.pk,
        }, format="json")
        self.assertEqual(r.status_code, 404)

    # ── Quién puede ─────────────────────────────────────────────────────────

    def test_alguien_ajeno_a_la_sst_no_puede(self):
        uno = self.agregar("771000100")
        r = self.client.post("/api/ssts/quitar_punto/", {
            "sst_codigo": self.sst.codigo, "id_suministro": uno,
        }, format="json")
        self.auth(self.encargado)
        r = self.client.post("/api/ssts/quitar_punto/", {
            "sst_codigo": self.sst.codigo, "id_suministro": uno,
        }, format="json")
        self.assertEqual(r.status_code, 403)

    def test_el_coordinador_si_puede(self):
        uno = self.agregar("771000100")
        Rol.objects.get_or_create(
            id_rol=Rol.COORDINADOR, defaults={"descripcion": "Coordinador"})
        coordinador = Usuario.objects.create(
            nombre="Coordinador Uno", rol_id=Rol.COORDINADOR,
            empresa=self.empresa, email="coord@tecsur.pe", clave="x")
        self.auth(coordinador)
        r = self.client.post("/api/ssts/quitar_punto/", {
            "sst_codigo": self.sst.codigo, "id_suministro": uno,
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
