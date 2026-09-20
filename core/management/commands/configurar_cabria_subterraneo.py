"""Deja la actividad de cabria subterráneo con sus tres tipos de trabajo.

Se llamaba "Cambio de poste inaccesible subterráneo" y desde el 2026-09-20 se
llama "Cambio de poste inacc. cabria subterraneo".

Dos de sus tipos de trabajo son **los mismos objetos** que usa cabria aéreo, no
copias: "Alumbrado cabria" y "Retiros - otros - cabria". Al ser el mismo tipo,
comparten materiales, partidas y regla, y no se pueden desincronizar. El
tercero, "poste", se queda con lo suyo: el cambio de poste subterráneo no es el
mismo trabajo que el aéreo.

Los tipos que salen de la actividad ("alumbrado" y "Otros") no se borran: solo
se desvinculan. Si alguien liquidó con ellos, esa liquidación debe seguir
diciendo lo que decía.

Es idempotente. Lo corre el script de despliegue en cada build, después de
`configurar_cabria`, que es quien crea los tipos compartidos.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    Actividad, ActividadTipoTrabajo, LiquidacionSuministro, SST, TipoTrabajo,
)

NOMBRE = "Cambio de poste inacc. cabria subterraneo"

# Como se ha llamado antes. Se buscan todos para poder renombrar una base
# vieja sin importar si tenía la tilde.
NOMBRES_ANTERIORES = [
    "Cambio de poste inaccesible subterráneo",
    "Cambio de poste inaccesible subterraneo",
]

# En el orden de la obra: primero el poste, al final lo suelto.
TIPOS = ["poste", "Alumbrado cabria", "Retiros - otros - cabria"]

# Los que hacían ese trabajo antes y ya no pertenecen a esta actividad.
TIPOS_QUE_SALEN = ["alumbrado", "Otros"]


class Command(BaseCommand):
    help = ('Renombra la actividad de cabria subterráneo y le deja sus tres '
            'tipos de trabajo, dos compartidos con cabria aéreo.')

    @transaction.atomic
    def handle(self, *args, **options):
        actividad = self._actividad()
        if actividad is None:
            self.stdout.write(self.style.WARNING(
                "No existe la actividad de cabria subterráneo; no hay nada "
                "que configurar."))
            return

        self._vincular(actividad)
        self._desvincular(actividad)

        tipos = (ActividadTipoTrabajo.objects
                 .filter(actividad=actividad)
                 .select_related("tipo_trabajo")
                 .order_by("orden"))
        self.stdout.write(self.style.SUCCESS(
            f"{actividad.nombre}: " +
            ", ".join(t.tipo_trabajo.nombre for t in tipos)))

    # ── La actividad ────────────────────────────────────────────────────────

    def _actividad(self):
        """La actividad con su nombre nuevo, renombrando o fusionando si hace
        falta. Si existieran las dos (la vieja y una ya renombrada), se queda
        la nueva y la vieja le entrega lo que tenga."""
        nueva = Actividad.objects.filter(nombre=NOMBRE).first()
        viejas = list(Actividad.objects.filter(nombre__in=NOMBRES_ANTERIORES))

        if nueva is None:
            if not viejas:
                return None
            nueva = viejas.pop(0)
            nueva.nombre = NOMBRE
            nueva.save(update_fields=["nombre"])
            self.stdout.write(f"Actividad renombrada a «{NOMBRE}».")

        for vieja in viejas:
            self._fusionar(vieja, nueva)
        return nueva

    def _fusionar(self, vieja, nueva):
        """Pasa a [nueva] lo que colgaba de [vieja] y borra la vieja."""
        movidas = SST.objects.filter(actividad=vieja).update(actividad=nueva)
        ya_estan = set(ActividadTipoTrabajo.objects
                       .filter(actividad=nueva)
                       .values_list("tipo_trabajo_id", flat=True))
        for vinculo in ActividadTipoTrabajo.objects.filter(actividad=vieja):
            if vinculo.tipo_trabajo_id in ya_estan:
                vinculo.delete()
            else:
                vinculo.actividad = nueva
                vinculo.save(update_fields=["actividad"])
        vieja.delete()
        self.stdout.write(
            f"Se fusionó «{vieja.nombre}» con «{nueva.nombre}» "
            f"({movidas} SST movidas).")

    # ── Los tipos de trabajo ────────────────────────────────────────────────

    def _vincular(self, actividad):
        for orden, nombre in enumerate(TIPOS):
            tipo = TipoTrabajo.objects.filter(nombre=nombre).first()
            if tipo is None:
                self.stdout.write(self.style.WARNING(
                    f"  No existe el tipo de trabajo «{nombre}»: se omite. "
                    "¿Corrió configurar_cabria antes que este comando?"))
                continue
            _, creado = ActividadTipoTrabajo.objects.update_or_create(
                actividad=actividad, tipo_trabajo=tipo,
                defaults={"orden": orden})
            if creado:
                self.stdout.write(f"  + {nombre}")

    def _desvincular(self, actividad):
        """Saca de la actividad los tipos que ya no van. No los borra: pueden
        tener liquidaciones viejas colgando, y esas no se tocan."""
        vinculos = (ActividadTipoTrabajo.objects
                    .filter(actividad=actividad,
                            tipo_trabajo__nombre__in=TIPOS_QUE_SALEN)
                    .select_related("tipo_trabajo"))
        for vinculo in vinculos:
            tipo = vinculo.tipo_trabajo
            liquidadas = LiquidacionSuministro.objects.filter(
                tipo_trabajo=tipo).count()
            vinculo.delete()
            aviso = f"  - {tipo.nombre}"
            if liquidadas:
                aviso += (f" ({liquidadas} liquidacion(es) siguen guardadas "
                          "con este nombre)")
            self.stdout.write(aviso)
