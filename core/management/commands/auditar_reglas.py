"""
Audita qué filas existentes violarían las reglas de negocio de los modelos.

Los `clean()` de core/models.py no se ejecutan por la API (DRF nunca llama a
full_clean), así que hoy son reglas escritas pero no aplicadas. Antes de
activarlas conviene saber cuántos datos ya guardados las incumplen.

Solo lee: no escribe ni modifica nada.

    python manage.py auditar_reglas
    python manage.py auditar_reglas --modelo Pedido
    python manage.py auditar_reglas --detalle        # lista los ids infractores
"""
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from core import models


# Modelos con clean(), con el campo por el que se los identifica en el reporte.
MODELOS = [
    ("Usuario",              models.Usuario,              "id_usuario"),
    ("UsuarioCamion",        models.UsuarioCamion,        "id_usuario_camion"),
    ("IngresoTecsur",        models.IngresoTecsur,        "id_ingreso"),
    ("DevolucionTecsur",     models.DevolucionTecsur,     "id_devolucion_tecsur"),
    ("MaterialMalogrado",    models.MaterialMalogrado,    "id_malogrado"),
    ("TransferenciaAlmacen", models.TransferenciaAlmacen, "id_transferencia"),
    ("Pedido",               models.Pedido,               "id_pedido"),
    ("DetallePedido",        models.DetallePedido,        "id_detalle_pedido"),
    ("Devolucion",           models.Devolucion,           "id_devolucion"),
    ("UploadConsumo",        models.UploadConsumo,        "id_upload"),
    ("Inventario",           models.Inventario,           "id_inventario"),
]

# Reglas que solo tienen sentido al MODIFICAR una fila, no al crearla. Una fila
# ya aprobada las "incumple" siempre; contarlas como deuda de datos es ruido.
SOLO_AL_MODIFICAR = (
    "no puede modificarse",
)


class Command(BaseCommand):
    help = "Reporta qué filas existentes violan los clean() de los modelos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--modelo", help="Auditar solo este modelo (ej. Pedido).")
        parser.add_argument(
            "--detalle", action="store_true",
            help="Listar los ids de las filas infractoras.")

    def handle(self, *args, **opciones):
        filtro = opciones.get("modelo")
        detalle = opciones.get("detalle")

        total_filas = 0
        total_infracciones = 0
        hubo_bloqueantes = False

        for nombre, modelo, campo_id in MODELOS:
            if filtro and filtro.lower() != nombre.lower():
                continue

            filas = modelo.objects.all()
            cantidad = filas.count()
            total_filas += cantidad

            if not cantidad:
                self.stdout.write(f"{nombre:22} sin filas")
                continue

            # mensaje -> [ids]
            infracciones = defaultdict(list)
            for fila in filas.iterator(chunk_size=500):
                try:
                    fila.clean()
                except ValidationError as exc:
                    for mensaje in exc.messages:
                        infracciones[mensaje].append(getattr(fila, campo_id))
                except Exception as exc:                       # noqa: BLE001
                    infracciones[f"[error al validar: {exc}]"].append(
                        getattr(fila, campo_id))

            afectadas = {i for ids in infracciones.values() for i in ids}
            total_infracciones += len(afectadas)

            if not infracciones:
                self.stdout.write(self.style.SUCCESS(
                    f"{nombre:22} {cantidad:>6} filas, todas válidas"))
                continue

            self.stdout.write(
                f"{nombre:22} {cantidad:>6} filas, "
                f"{len(afectadas)} con problemas")

            for mensaje, ids in sorted(
                    infracciones.items(), key=lambda kv: -len(kv[1])):
                al_modificar = any(t in mensaje for t in SOLO_AL_MODIFICAR)
                etiqueta = "  (solo al modificar)" if al_modificar else ""
                if not al_modificar:
                    hubo_bloqueantes = True
                estilo = self.style.WARNING if al_modificar else self.style.ERROR
                self.stdout.write(estilo(
                    f"    {len(ids):>5}x  {mensaje}{etiqueta}"))
                if detalle:
                    muestra = ", ".join(str(i) for i in ids[:20])
                    resto = f" … (+{len(ids) - 20})" if len(ids) > 20 else ""
                    self.stdout.write(f"           ids: {muestra}{resto}")

        self.stdout.write("")
        self.stdout.write(
            f"Total: {total_filas} filas revisadas, "
            f"{total_infracciones} con al menos una infracción.")
        if hubo_bloqueantes:
            self.stdout.write(self.style.ERROR(
                "Hay infracciones que NO son 'solo al modificar': activar esas "
                "reglas rechazaría peticiones que hoy pasan. Revisar antes."))
        else:
            self.stdout.write(self.style.SUCCESS(
                "Sin infracciones bloqueantes: las reglas se pueden activar."))
