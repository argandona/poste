"""Las asignaciones de camión dejan de vencer por calendario.

Antes no se podía dejar `fecha_fin` vacía, así que las asignaciones abiertas se
sembraban con un centinela (2100-01-01). Ahora una asignación viva simplemente
no tiene fecha de fin: se cierra al liberar o traspasar el camión.
"""
from datetime import date

from django.db import migrations

CENTINELA = date(2100, 1, 1)


def abrir_asignaciones_centinela(apps, schema_editor):
    UsuarioCamion = apps.get_model("core", "UsuarioCamion")
    UsuarioCamion.objects.filter(fecha_fin__gte=CENTINELA).update(fecha_fin=None)


def restaurar_centinela(apps, schema_editor):
    UsuarioCamion = apps.get_model("core", "UsuarioCamion")
    UsuarioCamion.objects.filter(fecha_fin__isnull=True).update(fecha_fin=CENTINELA)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_traspasocamion_detalletraspasocamion"),
    ]

    operations = [
        migrations.RunPython(abrir_asignaciones_centinela, restaurar_centinela),
    ]
