"""El tipo de trabajo "Otros cabria" pasa a llamarse "Retiros - otros - cabria".

Se renombra la fila y no se crea otra: sus liquidaciones y su catálogo siguen
colgados del mismo tipo. Si el nombre nuevo ya existiera, no se toca nada.
"""
from django.db import migrations

ANTES = "Otros cabria"
AHORA = "Retiros - otros - cabria"


def renombrar(apps, schema_editor):
    TipoTrabajo = apps.get_model("core", "TipoTrabajo")
    if not TipoTrabajo.objects.filter(nombre=AHORA).exists():
        TipoTrabajo.objects.filter(nombre=ANTES).update(nombre=AHORA)


def deshacer(apps, schema_editor):
    TipoTrabajo = apps.get_model("core", "TipoTrabajo")
    if not TipoTrabajo.objects.filter(nombre=ANTES).exists():
        TipoTrabajo.objects.filter(nombre=AHORA).update(nombre=ANTES)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_partida_retiro_nky"),
    ]

    operations = [
        migrations.RunPython(renombrar, deshacer),
    ]
