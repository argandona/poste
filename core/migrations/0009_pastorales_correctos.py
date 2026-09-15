"""Deja una sola matrícula por pastoral, con su nombre de obra.

Las correctas son 5347174 chileno corto, 5347015 bastón y 5347095 JP. Las otras
dos, 5347088 y 5347206, salen de todos los tipos de trabajo para que no se
puedan volver a elegir.

La ficha del material solo se borra si no arrastra nada. Si tiene stock,
inventarios o material ya liquidado, se conserva y se le marca el nombre: esos
registros cuentan lo que de verdad pasó y borrarlos sería falsear la historia.
"""
from django.db import migrations

CORRECTOS = {
    "5347174": "PASTORAL CHILENO CORTO",
    "5347015": "PASTORAL BASTON",
    "5347095": "PASTORAL JP",
}

REEMPLAZADOS = ["5347088", "5347206"]

# Dónde puede estar referenciado un material. Si aparece en alguno, no se borra.
REFERENCIAS = [
    "stocks", "stocks_almacen", "consumos_suministro", "detalles_inventario",
    "detalles_ingreso", "detalles_dev_tecsur", "detalles_malogrado",
    "detalles_transferencia", "detalles_pedido", "detalles_devolucion",
    "detalles_consumo", "detalles_traspaso",
]


def arreglar(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    TipoTrabajoMaterial = apps.get_model("core", "TipoTrabajoMaterial")

    for matricula, descripcion in CORRECTOS.items():
        Material.objects.filter(matricula=matricula).update(
            descripcion=descripcion)

    for matricula in REEMPLAZADOS:
        material = Material.objects.filter(matricula=matricula).first()
        if material is None:
            continue
        # Fuera de los tipos de trabajo: deja de ofrecerse al liquidar.
        TipoTrabajoMaterial.objects.filter(material=material).delete()

        usado = any(
            getattr(material, rel).exists()
            for rel in REFERENCIAS
            if hasattr(material, rel))
        if usado:
            marca = " (REEMPLAZADO)"
            if not material.descripcion.endswith(marca):
                material.descripcion = f"{material.descripcion}{marca}"
                material.save(update_fields=["descripcion"])
        else:
            material.delete()


def deshacer(apps, schema_editor):
    # No se reconstruye: los nombres viejos estaban equivocados.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_recupero_duplicado"),
    ]

    operations = [
        migrations.RunPython(arreglar, deshacer),
    ]
