"""La empresa que usa el sistema es ENCOSSA.

TECSUR es la mandante: de ella entra el material y a ella se devuelve, y por eso
los modelos IngresoTecsur y DevolucionTecsur conservan el nombre. Lo que estaba
mal era el registro de la empresa propia, sembrado como "TECSUR S.A.".
"""
from django.db import migrations

ANTES = "TECSUR S.A."
AHORA = "ENCOSSA"


def renombrar(apps, schema_editor):
    Empresa = apps.get_model("core", "Empresa")
    Empresa.objects.filter(nombre=ANTES).update(
        nombre=AHORA, email="contacto@encossa.pe")


def revertir(apps, schema_editor):
    Empresa = apps.get_model("core", "Empresa")
    Empresa.objects.filter(nombre=AHORA).update(
        nombre=ANTES, email="contacto@tecsur.pe")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_asignaciones_sin_vencimiento"),
    ]

    operations = [
        migrations.RunPython(renombrar, revertir),
    ]
