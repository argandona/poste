"""Partida de retiro de cable NYBY - NKY de baja tensión hasta 3x16 mm2.

Va como migración para que llegue a Render en el deploy. No pisa la partida
si ya existe: su precio pudo haberse corregido desde Configuración.
"""
from decimal import Decimal

from django.db import migrations

PARTIDA = "*091448"
DESCRIPCION = "RETIRO DE CABLE NYBY - NKY BT  HASTA 3x16mm2"
PRECIO = Decimal("4.48")


def crear(apps, schema_editor):
    ManoDeObra = apps.get_model("core", "ManoDeObra")
    ManoDeObra.objects.get_or_create(
        partida=PARTIDA, defaults={"descripcion": DESCRIPCION, "precio": PRECIO})


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_cuaderno_obra"),
    ]

    operations = [
        # Al revertir no se borra: ya puede estar usada en liquidaciones.
        migrations.RunPython(crear, migrations.RunPython.noop),
    ]
