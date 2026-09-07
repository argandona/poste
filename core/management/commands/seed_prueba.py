"""Siembra un entorno de PRUEBA completo en una base vacía.

Ideal para producción (Render) o para reconstruir todo local:
    python manage.py seed_prueba

Incluye:
  - Roles (incluye Coordinador) y usuarios (clave: tecsur123).
  - Empresa, almacén, camión ABC-123 asignado al capataz.
  - Mano de obra (73 partidas) y materiales + stock del camión.
  - Actividad "Cambio de poste inaccesible subterráneo".
  - Tipos de trabajo "poste" y "alumbrado" con sus partidas y materiales.
  - 2 SST con suministros asignados al capataz para liquidar.
"""
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password
from django.db import transaction

from core.models import (
    Empresa, Rol, Usuario, Camion, UsuarioCamion, Almacen, Actividad,
    Material, ManoDeObra, TipoTrabajo, ActividadTipoTrabajo,
    TipoTrabajoManoDeObra, TipoTrabajoMaterial,
    StockCamion, SST, Suministro, SSTSuministro, SSTEncargado,
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

ACTIVIDAD = "Cambio de poste inaccesible subterráneo"

POSTE_MO = ['*094395', '*095266', '*091840', '*091842', '*094918', '*094913',
            '*094911', '*090471', '*090470', '*090633', '*090632', '*090630']
POSTE_MAT = ['5331596', '5331616', '5411056', '5111102', '5131920', '5114702',
             '5031165', '5111587']

ALUMBRADO_MO = ['*091320', '*091316', '*091322', '*091346', '*091357', '*091356',
                '*091608']
ALUMBRADO_MAT = ['5567146', '5111215', '5347088', '5347206', '5347174', '5347015',
                 '5021407', '6941274', '5411058']


class Command(BaseCommand):
    help = "Siembra un entorno de prueba completo (usuarios, catálogos, tipos de trabajo)."

    @transaction.atomic
    def handle(self, *args, **options):
        # ── Roles ──
        for id_rol, desc in ROLES.items():
            Rol.objects.update_or_create(id_rol=id_rol, defaults={"descripcion": desc})
        self.stdout.write("Roles listos.")

        # ── Empresa ──
        empresa, _ = Empresa.objects.update_or_create(
            ruc="20123456789",
            defaults=dict(nombre="TECSUR S.A.", direccion="Av. Principal 123, Lima",
                          telefono="014567890", email="contacto@tecsur.pe"),
        )

        # ── Usuarios ──
        clave = make_password(CLAVE)

        def usuario(email, nombre, rol_id, emp=empresa):
            u, _ = Usuario.objects.update_or_create(
                email=email,
                defaults=dict(nombre=nombre, rol_id=rol_id, empresa=emp, clave=clave))
            return u

        usuario("admin@tecsur.pe", "Admin General", Rol.SUPERADMIN, emp=None)
        capataz = usuario("capataz@tecsur.pe", "Juan Capataz", Rol.CAPATAZ)
        usuario("encargado@tecsur.pe", "Carlos Encargado", Rol.ENCARGADO)
        usuario("almacen@tecsur.pe", "Ana Almacén", Rol.ENCARGADO_ALMACEN)
        usuario("liquidador@tecsur.pe", "Luis Liquidador", Rol.LIQUIDADOR)
        usuario("coordinador@tecsur.pe", "Sofia Coordinadora", Rol.COORDINADOR)
        self.stdout.write("Usuarios listos (clave: tecsur123).")

        # ── Almacén y camión ──
        Almacen.objects.update_or_create(
            empresa=empresa, nombre="Almacén Central",
            defaults=dict(direccion="Av. Industrial 500"))

        camion, _ = Camion.objects.update_or_create(
            placa="ABC-123", defaults=dict(empresa=empresa, descripcion="Camión grúa"))
        Camion.objects.update_or_create(
            placa="XYZ-789", defaults=dict(empresa=empresa, descripcion="Camión canasta"))

        if not UsuarioCamion.objects.filter(usuario=capataz, activo=True).exists():
            UsuarioCamion(usuario=capataz, camion=camion,
                          fecha_inicio=date.today(), fecha_fin=date(2100, 1, 1)).save()

        # ── Catálogos: mano de obra + materiales + stock ──
        call_command("cargar_mano_de_obra")
        call_command("cargar_saldo_camion", placa="ABC-123")

        # Saldo especial pedido: cable 5031165 a 500
        m5031165 = Material.objects.filter(matricula="5031165").first()
        if m5031165:
            StockCamion.objects.update_or_create(
                camion=camion, material=m5031165, defaults={"cantidad": Decimal("500")})

        # ── Actividad + tipos de trabajo ──
        actividad, _ = Actividad.objects.update_or_create(nombre=ACTIVIDAD)

        def crear_tipo(nombre, partidas, matriculas):
            tt, _ = TipoTrabajo.objects.update_or_create(nombre=nombre)
            ActividadTipoTrabajo.objects.get_or_create(actividad=actividad, tipo_trabajo=tt)
            TipoTrabajoManoDeObra.objects.filter(tipo_trabajo=tt).delete()
            for p in partidas:
                mo = ManoDeObra.objects.filter(partida=p).first()
                if mo:
                    TipoTrabajoManoDeObra.objects.get_or_create(tipo_trabajo=tt, mano_de_obra=mo)
            TipoTrabajoMaterial.objects.filter(tipo_trabajo=tt).delete()
            for mm in matriculas:
                mat = Material.objects.filter(matricula=mm).first()
                if mat:
                    TipoTrabajoMaterial.objects.get_or_create(tipo_trabajo=tt, material=mat)
            return tt

        crear_tipo("poste", POSTE_MO, POSTE_MAT)
        crear_tipo("alumbrado", ALUMBRADO_MO, ALUMBRADO_MAT)
        self.stdout.write("Actividad y tipos de trabajo (poste, alumbrado) listos.")

        # ── SST + suministros asignados al capataz (para liquidar) ──
        for i in range(1, 3):
            sst, _ = SST.objects.update_or_create(
                codigo=f"SST-2026-{i:03d}",
                defaults=dict(sst=f"S{i:06d}", empresa=empresa, distrito="Miraflores",
                              actividad=actividad, fecha_inicio=date.today(),
                              monto_sst=Decimal("1500.00")))
            SSTEncargado.objects.get_or_create(sst=sst, usuario=capataz)
            for j in range(1, 3):
                num = f"SUM-{i:02d}{j:03d}"
                sm, _ = Suministro.objects.update_or_create(
                    numero_suministro=num,
                    defaults=dict(medidor=f"MED{i}{j:03d}", distrito="Miraflores",
                                  monto_sum=Decimal("250.00"), estado="asignado"))
                SSTSuministro.objects.update_or_create(
                    sst=sst, suministro=sm, defaults=dict(asignado_a=capataz))

        self.stdout.write(self.style.SUCCESS("Entorno de prueba sembrado correctamente."))
