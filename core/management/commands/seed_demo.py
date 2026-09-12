"""Carga datos de demostración para probar el API y la app móvil de TECSUR.

Uso:  python manage.py seed_demo

Usuarios creados (clave para todos: "tecsur123"):
    admin@tecsur.pe        (SuperAdmin)
    capataz@tecsur.pe      (Capataz)            <- usuario de campo
    encargado@tecsur.pe    (Encargado)
    almacen@tecsur.pe      (Encargado de Almacén)
    liquidador@tecsur.pe   (Liquidador)
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password
from django.db import transaction

from core.models import (
    Empresa, Rol, Usuario, Camion, UsuarioCamion, Actividad, SST,
    Suministro, Material, Almacen, StockCamion, StockAlmacen,
    SSTSuministro, SSTEncargado, ManoDeObra, TipoTrabajo,
    ActividadTipoTrabajo, TipoTrabajoManoDeObra, TipoTrabajoMaterial,
)

CLAVE = "tecsur123"

ROLES = {
    Rol.SUPERADMIN: "SuperAdmin",
    Rol.ADMIN_EMPRESA: "Administrador de Empresa",
    Rol.ENCARGADO: "Encargado",
    Rol.CAPATAZ: "Capataz",
    Rol.LIQUIDADOR: "Liquidador",
    Rol.ENCARGADO_ALMACEN: "Encargado de Almacén",
    Rol.COORDINADOR: "Coordinador",
}


class Command(BaseCommand):
    help = "Carga datos de demostración para TECSUR."

    @transaction.atomic
    def handle(self, *args, **options):
        for id_rol, desc in ROLES.items():
            Rol.objects.update_or_create(id_rol=id_rol, defaults={"descripcion": desc})
        self.stdout.write("Roles listos.")

        empresa, _ = Empresa.objects.update_or_create(
            ruc="20123456789",
            defaults=dict(nombre="TECSUR S.A.", direccion="Av. Principal 123, Lima",
                          telefono="014567890", email="contacto@tecsur.pe"),
        )

        clave_hash = make_password(CLAVE)

        def usuario(email, nombre, rol_id, emp=empresa):
            u, _ = Usuario.objects.update_or_create(
                email=email,
                defaults=dict(nombre=nombre, rol_id=rol_id, empresa=emp, clave=clave_hash),
            )
            return u

        usuario("admin@tecsur.pe", "Admin General", Rol.SUPERADMIN, emp=None)
        capataz     = usuario("capataz@tecsur.pe", "Juan Capataz", Rol.CAPATAZ)
        usuario("encargado@tecsur.pe", "Carlos Encargado", Rol.ENCARGADO)
        usuario("almacen@tecsur.pe", "Ana Almacén", Rol.ENCARGADO_ALMACEN)
        usuario("liquidador@tecsur.pe", "Luis Liquidador", Rol.LIQUIDADOR)
        usuario("coordinador@tecsur.pe", "Sofia Coordinadora", Rol.COORDINADOR)
        self.stdout.write("Usuarios listos (clave: tecsur123).")

        actividad, _ = Actividad.objects.update_or_create(nombre="Mantenimiento de redes")

        almacen, _ = Almacen.objects.update_or_create(
            empresa=empresa, nombre="Almacén Central",
            defaults=dict(direccion="Av. Industrial 500"),
        )

        camiones = []
        for placa, desc in [("ABC-123", "Camión grúa"), ("XYZ-789", "Camión canasta")]:
            c, _ = Camion.objects.update_or_create(
                placa=placa, defaults=dict(empresa=empresa, descripcion=desc))
            camiones.append(c)

        # Asigna el primer camión al capataz (usuario de campo)
        if not UsuarioCamion.objects.filter(usuario=capataz, activo=True).exists():
            uc = UsuarioCamion(usuario=capataz, camion=camiones[0],
                               fecha_inicio=date.today())
            uc.save()

        # ── Materiales ──
        materiales = []
        datos_mat = [
            ("MAT-001", "Cable NYY 3x10mm", "12.50"),
            ("MAT-002", "Conector bimetálico", "3.20"),
            ("MAT-003", "Aislador polimérico", "45.00"),
            ("MAT-004", "Poste de concreto 8m", "320.00"),
            ("MAT-005", "Luminaria LED 150W", "185.00"),
        ]
        for matr, desc, precio in datos_mat:
            m, _ = Material.objects.update_or_create(
                matricula=matr, defaults=dict(descripcion=desc, precio=Decimal(precio)))
            materiales.append(m)

        for i, mat in enumerate(materiales):
            StockCamion.objects.update_or_create(
                camion=camiones[0], material=mat, defaults=dict(cantidad=Decimal(10 + i * 5)))
            StockAlmacen.objects.update_or_create(
                almacen=almacen, material=mat, defaults=dict(cantidad=100 + i * 20))

        # ── Mano de obra (partidas) ──
        manos = []
        datos_mo = [
            ("P-0001", "Instalación de acometida", "35.00"),
            ("P-0002", "Cambio de medidor", "28.50"),
            ("P-0003", "Montaje de luminaria", "42.00"),
        ]
        for partida, desc, precio in datos_mo:
            mo, _ = ManoDeObra.objects.update_or_create(
                partida=partida, defaults=dict(descripcion=desc, precio=Decimal(precio)))
            manos.append(mo)

        # ── Tipos de trabajo + relaciones ──
        tt1, _ = TipoTrabajo.objects.update_or_create(nombre="Instalación de suministro")
        tt2, _ = TipoTrabajo.objects.update_or_create(nombre="Mantenimiento de luminaria")
        for tt in (tt1, tt2):
            ActividadTipoTrabajo.objects.update_or_create(actividad=actividad, tipo_trabajo=tt)
        # Partidas por tipo de trabajo
        for mo in (manos[0], manos[1]):
            TipoTrabajoManoDeObra.objects.update_or_create(tipo_trabajo=tt1, mano_de_obra=mo)
        TipoTrabajoManoDeObra.objects.update_or_create(tipo_trabajo=tt2, mano_de_obra=manos[2])
        # Materiales por tipo de trabajo
        for mat in (materiales[0], materiales[1]):
            TipoTrabajoMaterial.objects.update_or_create(tipo_trabajo=tt1, material=mat)
        TipoTrabajoMaterial.objects.update_or_create(tipo_trabajo=tt2, material=materiales[4])

        # ── SST + Suministros asignados al capataz ──
        for i in range(1, 4):
            sst, _ = SST.objects.update_or_create(
                codigo=f"SST-2026-{i:03d}",
                defaults=dict(sst=f"S{i:06d}", empresa=empresa, distrito="Miraflores",
                              actividad=actividad, fecha_inicio=date.today(),
                              monto_sst=Decimal("1500.00")),
            )
            SSTEncargado.objects.update_or_create(sst=sst, usuario=capataz)
            # 2 suministros por SST, asignados al capataz, estado 'asignado'
            for j in range(1, 3):
                num = f"SUM-{i:02d}{j:03d}"
                sm, _ = Suministro.objects.update_or_create(
                    numero_suministro=num,
                    defaults=dict(medidor=f"MED{i}{j:03d}", distrito="Miraflores",
                                  monto_sum=Decimal("250.00"), estado="asignado"),
                )
                SSTSuministro.objects.update_or_create(
                    sst=sst, suministro=sm, defaults=dict(asignado_a=capataz))

        self.stdout.write(self.style.SUCCESS("Datos de demo cargados correctamente."))
