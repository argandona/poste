"""
Cabria subterráneo: el renombre de la actividad y sus tres tipos de trabajo.

"Cambio de poste inaccesible subterráneo" pasa a llamarse "Cambio de poste
inacc. cabria subterraneo". Su alumbrado y su "Otros" pasan a ser los MISMOS
tipos de trabajo que usa cabria aérea —no copias—, así que comparten catálogo
y no se pueden desincronizar. El poste se queda con lo suyo, que el cambio de
poste subterráneo no es el mismo trabajo que el aéreo.
"""
from datetime import date

from django.core.management import call_command

from ..models import (
    Actividad, ActividadTipoTrabajo, LiquidacionSuministro, ManoDeObra, SST,
    SSTSuministro, Suministro, TipoTrabajo, TipoTrabajoManoDeObra,
)
from .base import BaseAPITestCase

NOMBRE = "Cambio de poste inacc. cabria subterraneo"
VIEJO = "Cambio de poste inaccesible subterráneo"


class CabriaSubterraneoTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        # Los tipos compartidos, tal como los deja configurar_cabria.
        self.alumbrado_cabria = TipoTrabajo.objects.create(
            nombre="Alumbrado cabria")
        self.retiros = TipoTrabajo.objects.create(
            nombre="Retiros - otros - cabria")
        self.partida = ManoDeObra.objects.create(
            partida="*091320", descripcion="LUMINARIA", precio="10.00")
        TipoTrabajoManoDeObra.objects.create(
            tipo_trabajo=self.alumbrado_cabria, mano_de_obra=self.partida)
        self.aerea = Actividad.objects.create(
            nombre="Cambio de poste inacc. cabria aereo")
        for orden, tipo in enumerate([self.alumbrado_cabria, self.retiros]):
            ActividadTipoTrabajo.objects.create(
                actividad=self.aerea, tipo_trabajo=tipo, orden=orden)

        # La actividad vieja, con los tipos que tenía.
        self.actividad = Actividad.objects.create(nombre=VIEJO)
        self.poste = TipoTrabajo.objects.create(nombre="poste")
        self.alumbrado = TipoTrabajo.objects.create(nombre="alumbrado")
        self.otros = TipoTrabajo.objects.create(nombre="Otros")
        for orden, tipo in enumerate([self.poste, self.alumbrado, self.otros]):
            ActividadTipoTrabajo.objects.create(
                actividad=self.actividad, tipo_trabajo=tipo, orden=orden)

    def configurar(self):
        call_command("configurar_cabria_subterraneo", verbosity=0)

    def tipos_de(self, nombre_actividad):
        """Los tipos de la actividad, en el orden en que se le muestran."""
        return list(ActividadTipoTrabajo.objects
                    .filter(actividad__nombre=nombre_actividad)
                    .order_by("orden")
                    .values_list("tipo_trabajo__nombre", flat=True))

    # ── El nombre ───────────────────────────────────────────────────────────

    def test_la_actividad_se_renombra(self):
        self.configurar()
        self.assertTrue(Actividad.objects.filter(nombre=NOMBRE).exists())
        self.assertFalse(Actividad.objects.filter(nombre=VIEJO).exists())

    def test_renombrar_no_crea_otra_actividad(self):
        self.configurar()
        self.assertEqual(Actividad.objects.filter(nombre=NOMBRE).count(), 1)

    def test_las_sst_siguen_con_su_actividad(self):
        sst = SST.objects.create(
            sst="12345", codigo="SST-12345", empresa=self.empresa,
            distrito="LIMA", actividad=self.actividad,
            fecha_ejecucion=date.today())
        self.configurar()
        sst.refresh_from_db()
        self.assertEqual(sst.actividad.nombre, NOMBRE)

    def test_si_ya_existe_la_nueva_se_fusionan(self):
        """Una base a medio migrar: la vieja le entrega lo suyo a la nueva."""
        nueva = Actividad.objects.create(nombre=NOMBRE)
        sst = SST.objects.create(
            sst="12346", codigo="SST-12346", empresa=self.empresa,
            distrito="LIMA", actividad=self.actividad,
            fecha_ejecucion=date.today())
        self.configurar()
        sst.refresh_from_db()
        self.assertEqual(sst.actividad_id, nueva.pk)
        self.assertEqual(Actividad.objects.filter(nombre=VIEJO).count(), 0)
        self.assertEqual(Actividad.objects.filter(nombre=NOMBRE).count(), 1)

    # ── Los tipos de trabajo ────────────────────────────────────────────────

    def test_quedan_los_tres_tipos_en_orden_de_obra(self):
        self.configurar()
        self.assertEqual(self.tipos_de(NOMBRE),
                         ["poste", "Alumbrado cabria", "Retiros - otros - cabria"])

    def test_los_compartidos_son_el_mismo_tipo_que_en_la_aerea(self):
        """No son copias: es el mismo objeto, así que el catálogo es uno solo."""
        self.configurar()
        ids = set(ActividadTipoTrabajo.objects
                  .filter(actividad__nombre=NOMBRE,
                          tipo_trabajo__nombre__in=["Alumbrado cabria",
                                                    "Retiros - otros - cabria"])
                  .values_list("tipo_trabajo_id", flat=True))
        self.assertEqual(ids, {self.alumbrado_cabria.pk, self.retiros.pk})

    def test_el_catalogo_llega_por_ser_el_mismo_tipo(self):
        self.configurar()
        partidas = TipoTrabajoManoDeObra.objects.filter(
            tipo_trabajo__nombre="Alumbrado cabria").values_list(
            "mano_de_obra__partida", flat=True)
        self.assertIn("*091320", list(partidas))

    def test_los_viejos_salen_de_la_actividad(self):
        self.configurar()
        self.assertNotIn("alumbrado", self.tipos_de(NOMBRE))
        self.assertNotIn("Otros", self.tipos_de(NOMBRE))

    def test_los_viejos_no_se_borran(self):
        """Pueden tener liquidaciones colgando: esas deben seguir diciendo lo
        que decían."""
        self.configurar()
        self.assertTrue(TipoTrabajo.objects.filter(nombre="alumbrado").exists())
        self.assertTrue(TipoTrabajo.objects.filter(nombre="Otros").exists())

    def test_una_liquidacion_vieja_no_se_toca(self):
        poste = Suministro.objects.create(
            numero_suministro="900001234", distrito="LIMA")
        sst = SST.objects.create(
            sst="12347", codigo="SST-12347", empresa=self.empresa,
            distrito="LIMA", actividad=self.actividad,
            fecha_ejecucion=date.today())
        SSTSuministro.objects.create(sst=sst, suministro=poste)
        liq = LiquidacionSuministro.objects.create(
            suministro=poste, usuario=self.capataz,
            tipo_trabajo=self.alumbrado)
        self.configurar()
        liq.refresh_from_db()
        self.assertEqual(liq.tipo_trabajo.nombre, "alumbrado")

    def test_la_aerea_se_queda_como_estaba(self):
        self.configurar()
        self.assertEqual(self.tipos_de("Cambio de poste inacc. cabria aereo"),
                         ["Alumbrado cabria", "Retiros - otros - cabria"])

    # ── Repetirlo no rompe nada ─────────────────────────────────────────────

    def test_es_idempotente(self):
        self.configurar()
        self.configurar()
        self.assertEqual(self.tipos_de(NOMBRE),
                         ["poste", "Alumbrado cabria", "Retiros - otros - cabria"])
        self.assertEqual(Actividad.objects.filter(nombre=NOMBRE).count(), 1)

    def test_sin_la_actividad_no_hace_nada(self):
        ActividadTipoTrabajo.objects.filter(actividad=self.actividad).delete()
        self.actividad.delete()
        self.configurar()
        self.assertFalse(Actividad.objects.filter(nombre=NOMBRE).exists())
