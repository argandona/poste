from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .authentication import LoginView, RefreshView
from .views import (
    EmpresaViewSet, RolViewSet, UsuarioViewSet,
    CamionViewSet, UsuarioCamionViewSet, SSTViewSet,
    MaterialViewSet, StockCamionViewSet, AlmacenViewSet, StockAlmacenViewSet,
    ProveedorViewSet,
    IngresoTecsurViewSet, DevolucionTecsurViewSet,
    MaterialMalogradoViewSet, TransferenciaAlmacenViewSet,
    PedidoViewSet, DevolucionViewSet,
    UploadConsumoViewSet, InventarioViewSet,
    SuministroViewSet, LiquidacionViewSet,
    PlanoSSTViewSet,
    ActividadViewSet, TipoTrabajoViewSet, ManoDeObraViewSet,
    RecuperoViewSet,
)

router = DefaultRouter()
router.register(r'empresas',              EmpresaViewSet,              basename='empresa')
router.register(r'roles',                 RolViewSet,                  basename='rol')
router.register(r'usuarios',              UsuarioViewSet,              basename='usuario')
router.register(r'camiones',              CamionViewSet,               basename='camion')
router.register(r'usuario-camion',        UsuarioCamionViewSet,        basename='usuario-camion')
router.register(r'ssts',                  SSTViewSet,                  basename='sst')
router.register(r'materiales',            MaterialViewSet,             basename='material')
router.register(r'stock-camion',          StockCamionViewSet,          basename='stock-camion')
router.register(r'almacenes',             AlmacenViewSet,              basename='almacen')
router.register(r'stock-almacen',         StockAlmacenViewSet,         basename='stock-almacen')
router.register(r'proveedores',           ProveedorViewSet,            basename='proveedor')
router.register(r'ingresos-tecsur',       IngresoTecsurViewSet,        basename='ingreso-tecsur')
router.register(r'devoluciones-tecsur',   DevolucionTecsurViewSet,     basename='devolucion-tecsur')
router.register(r'materiales-malogrados', MaterialMalogradoViewSet,    basename='material-malogrado')
router.register(r'transferencias',        TransferenciaAlmacenViewSet, basename='transferencia')
router.register(r'pedidos',              PedidoViewSet,                basename='pedido')
router.register(r'devoluciones',         DevolucionViewSet,            basename='devolucion')
router.register(r'uploads-consumo',      UploadConsumoViewSet,         basename='upload-consumo')
router.register(r'inventarios',          InventarioViewSet,            basename='inventario')
router.register(r'suministros',          SuministroViewSet,            basename='suministro')
router.register(r'liquidaciones',        LiquidacionViewSet,           basename='liquidacion')
router.register(r'planos',               PlanoSSTViewSet,              basename='plano')
router.register(r'actividades',          ActividadViewSet,             basename='actividad')
router.register(r'tipos-trabajo',        TipoTrabajoViewSet,           basename='tipo-trabajo')
router.register(r'mano-de-obra',         ManoDeObraViewSet,            basename='mano-de-obra')
router.register(r'recuperos',            RecuperoViewSet,              basename='recupero')

urlpatterns = [
    path('auth/login/',   LoginView.as_view(),   name='login'),
    path('auth/refresh/', RefreshView.as_view(),  name='refresh'),
    path('',              include(router.urls)),
]
