"""Saca del catálogo el recupero repetido.

"LUMINARIA 70W" y "LUMINARIA DE 70W" son el mismo material escrito distinto, y
al capataz le aparecían dos opciones idénticas al buscar. Se queda la segunda.
Si alguien ya cargó el repetido en un suministro no se borra nada: primero hay
que mover esos registros a mano.
"""
from django.db import migrations

REPETIDO = "REC-035"


def quitar_repetido(apps, schema_editor):
    Recupero = apps.get_model("core", "Recupero")
    SuministroRecupero = apps.get_model("core", "SuministroRecupero")
    repetido = Recupero.objects.filter(matricula=REPETIDO).first()
    if repetido is None:
        return
    if SuministroRecupero.objects.filter(recupero=repetido).exists():
        return
    repetido.delete()


def volver_a_ponerlo(apps, schema_editor):
    Recupero = apps.get_model("core", "Recupero")
    Recupero.objects.get_or_create(
        matricula=REPETIDO,
        defaults={"descripcion": "LUMINARIA 70W", "unidad": "UND"})


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_tipotrabajomanodeobra_cantidad_inicial_and_more"),
    ]

    operations = [
        migrations.RunPython(quitar_repetido, volver_a_ponerlo),
    ]
