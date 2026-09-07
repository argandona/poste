from django.contrib import admin

from .models import (
    Empresa, Rol, Usuario, Camion, UsuarioCamion, Actividad, SST,
    Suministro, Material, Almacen, StockCamion, StockAlmacen, Proveedor,
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


admin.site.register(Actividad)
admin.site.register(UsuarioCamion)
admin.site.register(StockCamion)
admin.site.register(StockAlmacen)
admin.site.register(Proveedor)
