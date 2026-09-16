"""Saldo de prueba para todos los que piden material.

A cada capataz y encargado (por rol principal o secundario) que no tenga camión
se le crea uno y se le asigna. Después cada uno de esos camiones queda con 1000
de cada material del catálogo, y los materiales con precio cero pasan a costar
S/ 1.

Va como migración y no como comando porque Render gratis no da consola: un
comando en build.sh correría en cada deploy y volvería a llenar los saldos que
ya se gastaron. La migración corre una sola vez por base.
"""
from datetime import date
from decimal import Decimal

from django.db import migrations
from django.db.models import Q

CAPATAZ, ENCARGADO = 4, 3
SALDO = Decimal("1000")


def _placa_libre(Camion, n):
    while True:
        placa = f"TCS-{n:03d}"
        if not Camion.objects.filter(placa=placa).exists():
            return placa, n + 1
        n += 1


def dar_saldo_de_prueba(apps, schema_editor):
    Camion = apps.get_model("core", "Camion")
    Material = apps.get_model("core", "Material")
    StockCamion = apps.get_model("core", "StockCamion")
    Usuario = apps.get_model("core", "Usuario")
    UsuarioCamion = apps.get_model("core", "UsuarioCamion")

    hoy = date.today()
    Material.objects.filter(precio=0).update(precio=Decimal("1"))

    usuarios = (Usuario.objects
                .filter(activo=True, empresa__isnull=False)
                .filter(Q(rol_id__in=[CAPATAZ, ENCARGADO])
                        | Q(rol_secundario_id__in=[CAPATAZ, ENCARGADO]))
                .order_by("pk"))

    camiones, n = [], 101
    for usuario in usuarios:
        asignacion = (UsuarioCamion.objects
                      .filter(usuario=usuario, activo=True, fecha_inicio__lte=hoy)
                      .filter(Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=hoy))
                      .first())
        if asignacion:
            camiones.append(asignacion.camion_id)
            continue
        placa, n = _placa_libre(Camion, n)
        camion = Camion.objects.create(
            empresa_id=usuario.empresa_id, placa=placa,
            descripcion=f"Camión de {usuario.nombre}")
        UsuarioCamion.objects.create(usuario=usuario, camion=camion, fecha_inicio=hoy)
        camiones.append(camion.pk)

    materiales = list(Material.objects.values_list("pk", flat=True))
    for camion_id in camiones:
        for material_id in materiales:
            StockCamion.objects.update_or_create(
                camion_id=camion_id, material_id=material_id,
                defaults={"cantidad": SALDO})


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_rol_secundario"),
    ]

    operations = [
        # Al revertir no se borra nada: para entonces ese saldo ya pudo moverse.
        migrations.RunPython(dar_saldo_de_prueba, migrations.RunPython.noop),
    ]
