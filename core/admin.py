from django.contrib import admin
from django.db.models import Q

from .models import (
    Empresa, Rol, Usuario, Camion, UsuarioCamion, Actividad, SST,
    Suministro, Material, Almacen, StockCamion, StockAlmacen, Proveedor,
    CorreccionLiquidacion,
)

admin.site.site_header = "TECSUR — Administración"
admin.site.site_title = "TECSUR"
admin.site.index_title = "Panel de gestión"


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("id_empresa", "nombre", "ruc", "activo")
    search_fields = ("nombre", "ruc")


@admin.register(Rol)
class RolAdmin(admin.ModelAdmin):
    list_display = ("id_rol", "descripcion")


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ("id_usuario", "nombre", "email", "rol", "empresa", "activo")
    list_filter = ("rol", "empresa", "activo")
    search_fields = ("nombre", "email")


@admin.register(Camion)
class CamionAdmin(admin.ModelAdmin):
    list_display = ("id_camion", "placa", "empresa", "activo")
    list_filter = ("empresa", "activo")
    search_fields = ("placa",)


@admin.register(SST)
class SSTAdmin(admin.ModelAdmin):
    list_display = ("id_sst", "sst", "codigo", "distrito", "empresa", "monto_sst")
    search_fields = ("sst", "codigo", "distrito")


@admin.register(Suministro)
class SuministroAdmin(admin.ModelAdmin):
    list_display = ("id_suministro", "numero_suministro", "distrito", "estado", "monto_sum")
    list_filter = ("estado",)
    search_fields = ("numero_suministro", "medidor")


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("id_material", "matricula", "descripcion", "precio")
    search_fields = ("matricula", "descripcion")


@admin.register(Almacen)
class AlmacenAdmin(admin.ModelAdmin):
    list_display = ("id_almacen", "nombre", "empresa", "activo")


def _es_coordinador(request):
    """Si quien entró al admin es Coordinador en el sistema.

    El admin de Django tiene sus propias cuentas, aparte de la tabla Usuario:
    el puente entre las dos es el correo. Sin correo, o con uno que no está en
    Usuario, no es coordinador de nada."""
    correo = (getattr(request.user, "email", "") or "").strip()
    if not correo:
        return False
    return (Usuario.objects
            .filter(email__iexact=correo)
            .filter(Q(rol_id=Rol.COORDINADOR) |
                    Q(rol_secundario_id=Rol.COORDINADOR))
            .exists())


@admin.register(CorreccionLiquidacion)
class CorreccionLiquidacionAdmin(admin.ModelAdmin):
    """El acta de lo que se corrigió: solo se lee, y solo la lee el Coordinador.

    No es un formulario. Nadie la crea, la edita ni la borra desde aquí: si se
    pudiera, dejaría de servir para lo que es."""
    list_display = ("fecha", "numero_suministro", "sst_externo", "tipo_trabajo",
                    "usuario_anterior", "usuario", "cambios")
    list_filter = ("fecha", "tipo_trabajo", "usuario")
    search_fields = ("suministro__numero_suministro", "suministro_externo",
                     "sst_externo", "cambios")
    date_hierarchy = "fecha"

    @admin.display(description="Suministro")
    def numero_suministro(self, obj):
        if obj.suministro_id:
            return obj.suministro.numero_suministro
        return obj.suministro_externo or "—"

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or _es_coordinador(request)

    def has_module_permission(self, request):
        return request.user.is_superuser or _es_coordinador(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Actividad)
admin.site.register(UsuarioCamion)
admin.site.register(StockCamion)
admin.site.register(StockAlmacen)
admin.site.register(Proveedor)
