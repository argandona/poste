from rest_framework import serializers
from .models import (
    Empresa, Rol, Usuario, Camion, UsuarioCamion, SST,
    TraspasoCamion, DetalleTraspasoCamion,
    Material, StockCamion, Almacen, StockAlmacen, Proveedor,
    IngresoTecsur, DetalleIngresoTecsur,
    DevolucionTecsur, DetalleDevolucionTecsur,
    MaterialMalogrado, DetalleMaterialMalogrado,
    TransferenciaAlmacen, DetalleTransferencia,
    Pedido, DetallePedido,
    Devolucion, DetalleDevolucion,
    UploadConsumo, Consumo, DetalleConsumo,
    Inventario, DetalleInventario,
    Suministro, ManoDeObra, TipoTrabajo, SuministroTipoTrabajo,
    Actividad, ActividadTipoTrabajo,
    SuministroManoDeObra, TipoTrabajoManoDeObra, TipoTrabajoMaterial, Recupero, SuministroRecupero,
    LiquidacionSuministro, LiquidacionPartida, ConsumoMaterialSuministro,
    PlanoSST,
)


# ── Empresa ─────────────────────────────────────
class EmpresaSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Empresa
        fields = '__all__'


# ── Rol ─────────────────────────────────────────
class RolSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Rol
        fields = '__all__'


# ── Usuario ─────────────────────────────────────
class UsuarioSerializer(serializers.ModelSerializer):
    rol_descripcion    = serializers.CharField(source='rol.descripcion', read_only=True)
    empresa_nombre     = serializers.CharField(source='empresa.nombre',  read_only=True)

    class Meta:
        model  = Usuario
        fields = [
            'id_usuario','nombre','email','telefono',
            'rol','rol_descripcion','empresa','empresa_nombre',
            'activo','fecha_creacion','ultimo_acceso',
        ]
        # clave nunca se expone en lectura
        extra_kwargs = {'clave': {'write_only': True}}

class UsuarioCreateSerializer(serializers.ModelSerializer):
    """Para crear/actualizar usuario con clave en texto plano (se hashea en el signal)."""
    class Meta:
        model  = Usuario
        fields = ['nombre','email','telefono','rol','empresa','clave','activo']

    def create(self, validated_data):
        import hashlib
        clave = validated_data.pop('clave')
        usuario = Usuario(**validated_data)
        usuario.clave = hashlib.sha256(clave.encode()).hexdigest()
        usuario.save()
        return usuario

    def update(self, instance, validated_data):
        import hashlib
        if 'clave' in validated_data:
            instance.clave = hashlib.sha256(validated_data.pop('clave').encode()).hexdigest()
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


# ── Camion ──────────────────────────────────────
class CamionSerializer(serializers.ModelSerializer):
    empresa_nombre = serializers.CharField(source='empresa.nombre', read_only=True)
    class Meta:
        model  = Camion
        fields = '__all__'


# ── UsuarioCamion ────────────────────────────────
class UsuarioCamionSerializer(serializers.ModelSerializer):
    usuario_nombre = serializers.CharField(source='usuario.nombre', read_only=True)
    camion_placa   = serializers.CharField(source='camion.placa',   read_only=True)
    saldo_camion   = serializers.SerializerMethodField()
    class Meta:
        model  = UsuarioCamion
        fields = '__all__'
        # El cierre de una asignación no se edita a mano: pasa por
        # /usuario-camion/{id}/liberar/ o /usuario-camion/traspasar/, que son
        # los que verifican que el camión no quede con saldo sin responsable.
        read_only_fields = ('fecha_fin', 'activo')

    def get_saldo_camion(self, obj):
        return obj.saldo_camion()


# ── Traspaso de camión ───────────────────────────
class DetalleTraspasoCamionSerializer(serializers.ModelSerializer):
    material_matricula   = serializers.CharField(source='material.matricula', read_only=True)
    material_descripcion = serializers.CharField(source='material.descripcion', read_only=True)
    class Meta:
        model  = DetalleTraspasoCamion
        fields = ('id_detalle_traspaso', 'material', 'material_matricula',
                  'material_descripcion', 'cantidad')


class TraspasoCamionSerializer(serializers.ModelSerializer):
    camion_placa    = serializers.CharField(source='camion.placa', read_only=True)
    entrega_nombre  = serializers.CharField(source='usuario_entrega.nombre', read_only=True)
    recibe_nombre   = serializers.CharField(source='usuario_recibe.nombre', read_only=True)
    detalles        = DetalleTraspasoCamionSerializer(many=True, read_only=True)
    class Meta:
        model  = TraspasoCamion
        fields = '__all__'


# ── SST ─────────────────────────────────────────
class SSTSerializer(serializers.ModelSerializer):
    empresa_nombre   = serializers.CharField(source='empresa.nombre',   read_only=True)
    actividad_nombre = serializers.CharField(source='actividad.nombre', read_only=True, default='', allow_null=True)
    class Meta:
        model  = SST
        fields = '__all__'


# ── Material ─────────────────────────────────────
class MaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Material
        fields = '__all__'


# ── StockCamion ──────────────────────────────────
class StockCamionSerializer(serializers.ModelSerializer):
    camion_placa       = serializers.CharField(source='camion.placa',       read_only=True)
    material_descripcion = serializers.CharField(source='material.descripcion', read_only=True)
    material_matricula   = serializers.CharField(source='material.matricula',   read_only=True)
    class Meta:
        model  = StockCamion
        fields = '__all__'


# ── Almacen ──────────────────────────────────────
class AlmacenSerializer(serializers.ModelSerializer):
    empresa_nombre = serializers.CharField(source='empresa.nombre', read_only=True)
    class Meta:
        model  = Almacen
        fields = '__all__'


# ── StockAlmacen ─────────────────────────────────
class StockAlmacenSerializer(serializers.ModelSerializer):
    almacen_nombre       = serializers.CharField(source='almacen.nombre',       read_only=True)
    material_descripcion = serializers.CharField(source='material.descripcion', read_only=True)
    material_matricula   = serializers.CharField(source='material.matricula',   read_only=True)
    class Meta:
        model  = StockAlmacen
        fields = '__all__'


# ── Proveedor ────────────────────────────────────
class ProveedorSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Proveedor
        fields = '__all__'


# ── IngresoTecsur ────────────────────────────────
class DetalleIngresoTecsurSerializer(serializers.ModelSerializer):
    material_descripcion = serializers.CharField(source='material.descripcion', read_only=True)
    class Meta:
        model  = DetalleIngresoTecsur
        fields = '__all__'

class IngresoTecsurSerializer(serializers.ModelSerializer):
    detalles          = DetalleIngresoTecsurSerializer(many=True, read_only=True)
    almacen_nombre    = serializers.CharField(source='almacen.nombre',    read_only=True)
    proveedor_nombre  = serializers.CharField(source='proveedor.nombre',  read_only=True)
    usuario_nombre    = serializers.CharField(source='usuario.nombre',    read_only=True)
    class Meta:
        model  = IngresoTecsur
        fields = '__all__'

class IngresoTecsurCreateSerializer(serializers.ModelSerializer):
    detalles = DetalleIngresoTecsurSerializer(many=True)
    class Meta:
        model  = IngresoTecsur
        fields = ['almacen','proveedor','usuario','folio','fecha','observacion','detalles']

    def create(self, validated_data):
        from django.db import transaction
        detalles_data = validated_data.pop('detalles')
        with transaction.atomic():
            ingreso = IngresoTecsur.objects.create(**validated_data)
            for d in detalles_data:
                det = DetalleIngresoTecsur.objects.create(ingreso=ingreso, **d)
                # Actualizar stock almacen
                stock, _ = StockAlmacen.objects.get_or_create(
                    almacen=ingreso.almacen, material=det.material,
                    defaults={'cantidad': 0}
                )
                stock.agregar(det.cantidad)
        return ingreso


# ── DevolucionTecsur ─────────────────────────────
class DetalleDevolucionTecsurSerializer(serializers.ModelSerializer):
    material_descripcion = serializers.CharField(source='material.descripcion', read_only=True)
    class Meta:
        model  = DetalleDevolucionTecsur
        fields = '__all__'

class DevolucionTecsurSerializer(serializers.ModelSerializer):
    detalles = DetalleDevolucionTecsurSerializer(many=True, read_only=True)
    almacen_nombre   = serializers.CharField(source='almacen.nombre',   read_only=True)
    proveedor_nombre = serializers.CharField(source='proveedor.nombre', read_only=True)
    usuario_nombre   = serializers.CharField(source='usuario.nombre',   read_only=True)
    class Meta:
        model  = DevolucionTecsur
        fields = '__all__'

class DevolucionTecsurCreateSerializer(serializers.ModelSerializer):
    detalles = DetalleDevolucionTecsurSerializer(many=True)
    class Meta:
        model  = DevolucionTecsur
        fields = ['almacen','proveedor','usuario','folio','fecha','observacion','detalles']

    def create(self, validated_data):
        from django.db import transaction
        detalles_data = validated_data.pop('detalles')
        with transaction.atomic():
            devolucion = DevolucionTecsur.objects.create(**validated_data)
            for d in detalles_data:
                det = DetalleDevolucionTecsur.objects.create(devolucion_tecsur=devolucion, **d)
                stock = StockAlmacen.objects.get(almacen=devolucion.almacen, material=det.material)
                stock.descontar(det.cantidad)
        return devolucion


# ── MaterialMalogrado ────────────────────────────
class DetalleMaterialMalogradoSerializer(serializers.ModelSerializer):
    material_descripcion = serializers.CharField(source='material.descripcion', read_only=True)
    costo_total          = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    class Meta:
        model  = DetalleMaterialMalogrado
        fields = '__all__'

class MaterialMalogradoSerializer(serializers.ModelSerializer):
    detalles = DetalleMaterialMalogradoSerializer(many=True, read_only=True)
    almacen_nombre   = serializers.CharField(source='almacen.nombre',   read_only=True)
    proveedor_nombre = serializers.CharField(source='proveedor.nombre', read_only=True)
    usuario_nombre   = serializers.CharField(source='usuario.nombre',   read_only=True)
    class Meta:
        model  = MaterialMalogrado
        fields = '__all__'

class MaterialMalogradoCreateSerializer(serializers.ModelSerializer):
    detalles = DetalleMaterialMalogradoSerializer(many=True)
    class Meta:
        model  = MaterialMalogrado
        fields = ['almacen','proveedor','usuario','folio_factura','fecha','observacion','detalles']

    def create(self, validated_data):
        from django.db import transaction
        detalles_data = validated_data.pop('detalles')
        with transaction.atomic():
            malogrado = MaterialMalogrado.objects.create(**validated_data)
            for d in detalles_data:
                det = DetalleMaterialMalogrado.objects.create(malogrado=malogrado, **d)
                stock = StockAlmacen.objects.get(almacen=malogrado.almacen, material=det.material)
                stock.descontar(det.cantidad)
        return malogrado


# ── TransferenciaAlmacen ─────────────────────────
class DetalleTransferenciaSerializer(serializers.ModelSerializer):
    material_descripcion = serializers.CharField(source='material.descripcion', read_only=True)
    class Meta:
        model  = DetalleTransferencia
        fields = '__all__'

class TransferenciaAlmacenSerializer(serializers.ModelSerializer):
    detalles               = DetalleTransferenciaSerializer(many=True, read_only=True)
    almacen_origen_nombre  = serializers.CharField(source='almacen_origen.nombre',  read_only=True)
    almacen_destino_nombre = serializers.CharField(source='almacen_destino.nombre', read_only=True)
    usuario_nombre         = serializers.CharField(source='usuario.nombre',          read_only=True)
    class Meta:
        model  = TransferenciaAlmacen
        fields = '__all__'

class TransferenciaAlmacenCreateSerializer(serializers.ModelSerializer):
    detalles = DetalleTransferenciaSerializer(many=True)
    class Meta:
        model  = TransferenciaAlmacen
        fields = ['almacen_origen','almacen_destino','usuario','fecha','observacion','detalles']

    def create(self, validated_data):
        from django.db import transaction
        detalles_data = validated_data.pop('detalles')
        with transaction.atomic():
            transferencia = TransferenciaAlmacen.objects.create(**validated_data)
            for d in detalles_data:
                det = DetalleTransferencia.objects.create(transferencia=transferencia, **d)
                origen  = StockAlmacen.objects.get(almacen=transferencia.almacen_origen,  material=det.material)
                destino, _ = StockAlmacen.objects.get_or_create(almacen=transferencia.almacen_destino, material=det.material, defaults={'cantidad':0})
                origen.descontar(det.cantidad)
                destino.agregar(det.cantidad)
        return transferencia


# ── Pedido ───────────────────────────────────────
class DetallePedidoSerializer(serializers.ModelSerializer):
    material_descripcion = serializers.CharField(source='material.descripcion', read_only=True)
    material_matricula   = serializers.CharField(source='material.matricula',   read_only=True)
    class Meta:
        model  = DetallePedido
        fields = '__all__'
        extra_kwargs = {'pedido': {'read_only': True}}

class PedidoSerializer(serializers.ModelSerializer):
    detalles        = DetallePedidoSerializer(many=True, read_only=True)
    usuario_nombre  = serializers.CharField(source='usuario.nombre', read_only=True)
    camion_placa    = serializers.CharField(source='camion.placa',   read_only=True)
    almacen_nombre  = serializers.CharField(source='almacen.nombre', read_only=True)
    class Meta:
        model  = Pedido
        fields = '__all__'

class PedidoCreateSerializer(serializers.ModelSerializer):
    detalles = DetallePedidoSerializer(many=True)
    class Meta:
        model  = Pedido
        fields = ['camion','usuario','observacion','detalles']

    def create(self, validated_data):
        from django.db import transaction
        detalles_data = validated_data.pop('detalles')
        with transaction.atomic():
            pedido = Pedido.objects.create(**validated_data)
            for d in detalles_data:
                DetallePedido.objects.create(pedido=pedido, material=d['material'], cantidad_solicitada=d['cantidad_solicitada'])
        return pedido

class PedidoAprobarSerializer(serializers.Serializer):
    """Body para aprobar o rechazar un pedido."""
    accion          = serializers.ChoiceField(choices=['aprobar','rechazar'])
    usuario_aprueba = serializers.PrimaryKeyRelatedField(queryset=Usuario.objects.all())
    almacen         = serializers.PrimaryKeyRelatedField(queryset=Almacen.objects.all(), required=False)
    observacion     = serializers.CharField(required=False, allow_blank=True)
    detalles        = DetallePedidoSerializer(many=True, required=False)


# ── Devolucion ───────────────────────────────────
class DetalleDevolucionSerializer(serializers.ModelSerializer):
    material_descripcion = serializers.CharField(source='material.descripcion', read_only=True)
    material_matricula   = serializers.CharField(source='material.matricula',   read_only=True)
    class Meta:
        model  = DetalleDevolucion
        fields = '__all__'
        extra_kwargs = {'devolucion': {'read_only': True}}

class DevolucionSerializer(serializers.ModelSerializer):
    detalles       = DetalleDevolucionSerializer(many=True, read_only=True)
    usuario_nombre = serializers.CharField(source='usuario.nombre', read_only=True)
    camion_placa   = serializers.CharField(source='camion.placa',   read_only=True)
    class Meta:
        model  = Devolucion
        fields = '__all__'

class DevolucionCreateSerializer(serializers.ModelSerializer):
    detalles = DetalleDevolucionSerializer(many=True)
    class Meta:
        model  = Devolucion
        fields = ['camion','usuario','observacion','detalles']

    def validate(self, data):
        from django.db.models import Sum
        camion   = data.get('camion')
        detalles = data.get('detalles', [])
        errores  = []
        for det in detalles:
            material        = det['material']
            cant_solicitada = det['cantidad_solicitada']
            try:
                stock_actual = StockCamion.objects.get(camion=camion, material=material).cantidad
            except StockCamion.DoesNotExist:
                errores.append(f'{material.matricula}: sin stock registrado en este camión.')
                continue
            pendiente = (DetalleDevolucion.objects
                         .filter(devolucion__camion=camion,
                                 devolucion__estado='pendiente',
                                 material=material)
                         .aggregate(total=Sum('cantidad_solicitada'))['total'] or 0)
            disponible = stock_actual - pendiente
            if cant_solicitada > disponible:
                errores.append(
                    f'{material.matricula}: solicitás {cant_solicitada} pero solo hay '
                    f'{disponible} disponible (stock {stock_actual}, en trámite {pendiente}).'
                )
        if errores:
            raise serializers.ValidationError({'detalles': errores})
        return data

    def create(self, validated_data):
        from django.db import transaction
        detalles_data = validated_data.pop('detalles')
        with transaction.atomic():
            devolucion = Devolucion.objects.create(**validated_data)
            for d in detalles_data:
                DetalleDevolucion.objects.create(devolucion=devolucion, material=d['material'], cantidad_solicitada=d['cantidad_solicitada'])
        return devolucion

class DevolucionAprobarSerializer(serializers.Serializer):
    accion          = serializers.ChoiceField(choices=['aprobar','rechazar'])
    usuario_aprueba = serializers.PrimaryKeyRelatedField(queryset=Usuario.objects.all())
    almacen_destino = serializers.PrimaryKeyRelatedField(queryset=Almacen.objects.all(), required=False)
    observacion     = serializers.CharField(required=False, allow_blank=True)
    detalles        = DetalleDevolucionSerializer(many=True, required=False)


# ── UploadConsumo / Consumo ──────────────────────
class DetalleConsumoSerializer(serializers.ModelSerializer):
    material_descripcion = serializers.CharField(source='material.descripcion', read_only=True)
    class Meta:
        model  = DetalleConsumo
        fields = '__all__'

class ConsumoSerializer(serializers.ModelSerializer):
    detalles        = DetalleConsumoSerializer(many=True, read_only=True)
    usuario_nombre  = serializers.CharField(source='usuario_consume.nombre', read_only=True)
    camion_placa    = serializers.CharField(source='camion.placa', read_only=True)
    class Meta:
        model  = Consumo
        fields = '__all__'

class UploadConsumoSerializer(serializers.ModelSerializer):
    consumos       = ConsumoSerializer(many=True, read_only=True)
    usuario_nombre = serializers.CharField(source='usuario.nombre', read_only=True)
    sst_actividad  = serializers.CharField(source='sst.actividad.nombre', read_only=True, default='', allow_null=True)
    class Meta:
        model  = UploadConsumo
        fields = '__all__'


# ── Inventario ───────────────────────────────────
class DetalleInventarioSerializer(serializers.ModelSerializer):
    material_descripcion = serializers.CharField(source='material.descripcion', read_only=True)
    material_matricula   = serializers.CharField(source='material.matricula',   read_only=True)
    class Meta:
        model  = DetalleInventario
        fields = '__all__'

class InventarioSerializer(serializers.ModelSerializer):
    detalles       = DetalleInventarioSerializer(many=True, read_only=True)
    usuario_nombre = serializers.CharField(source='usuario.nombre', read_only=True)
    camion_placa   = serializers.CharField(source='camion.placa',   read_only=True)
    almacen_nombre = serializers.CharField(source='almacen.nombre', read_only=True)
    class Meta:
        model  = Inventario
        fields = '__all__'

class InventarioCreateSerializer(serializers.ModelSerializer):
    detalles = DetalleInventarioSerializer(many=True)
    class Meta:
        model  = Inventario
        fields = ['camion','almacen','usuario','mes','anio','observacion','detalles']

    def create(self, validated_data):
        from django.db import transaction
        detalles_data = validated_data.pop('detalles')
        with transaction.atomic():
            inventario = Inventario.objects.create(**validated_data)
            for d in detalles_data:
                DetalleInventario.objects.create(inventario=inventario, **d)
        return inventario


# ── Suministro ──────────────────────────────────────────────────────────────
class SuministroSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Suministro
        fields = '__all__'


# ── ManoDeObra ──────────────────────────────────────────────────────────────
class ManoDeObraSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ManoDeObra
        fields = '__all__'


# ── TipoTrabajo ─────────────────────────────────────────────────────────────
class TipoTrabajoPartidaSerializer(serializers.ModelSerializer):
    id_mano_de_obra = serializers.IntegerField(source='mano_de_obra.id_mano_de_obra', read_only=True)
    partida         = serializers.CharField(source='mano_de_obra.partida',            read_only=True)
    descripcion     = serializers.CharField(source='mano_de_obra.descripcion',        read_only=True)
    precio          = serializers.DecimalField(source='mano_de_obra.precio', max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model  = TipoTrabajoManoDeObra
        fields = ['id_mano_de_obra', 'partida', 'descripcion', 'precio']


class TipoTrabajoMaterialSerializer(serializers.ModelSerializer):
    id_material = serializers.IntegerField(source='material.id_material', read_only=True)
    matricula   = serializers.CharField(source='material.matricula',      read_only=True)
    descripcion = serializers.CharField(source='material.descripcion',    read_only=True)

    class Meta:
        model  = TipoTrabajoMaterial
        fields = ['id_material', 'matricula', 'descripcion']


class ActividadSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Actividad
        fields = ['id_actividad', 'nombre']


class TipoTrabajoSerializer(serializers.ModelSerializer):
    partidas    = TipoTrabajoPartidaSerializer(many=True, read_only=True)
    materiales  = TipoTrabajoMaterialSerializer(many=True, read_only=True)
    actividades = serializers.SerializerMethodField()

    class Meta:
        model  = TipoTrabajo
        fields = ['id_tipo_trabajo', 'nombre', 'actividades', 'partidas', 'materiales']

    def get_actividades(self, obj):
        return [
            {'id_actividad': att.actividad_id, 'nombre': att.actividad.nombre}
            for att in obj.actividades.select_related('actividad').all()
        ]


# ── SuministroManoDeObra ─────────────────────────────────────────────────────
class SuministroManoDeObraSerializer(serializers.ModelSerializer):
    partida     = serializers.CharField(source='mano_de_obra.partida',     read_only=True)
    descripcion = serializers.CharField(source='mano_de_obra.descripcion', read_only=True)
    precio      = serializers.DecimalField(source='mano_de_obra.precio',
                                           max_digits=12, decimal_places=2, read_only=True)
    class Meta:
        model  = SuministroManoDeObra
        fields = ['id_suministro_mano_de_obra', 'mano_de_obra', 'partida', 'descripcion', 'precio']


# ── Recupero ─────────────────────────────────────────────────────────────────
class RecuperoSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Recupero
        fields = '__all__'


# ── SuministroRecupero ───────────────────────────────────────────────────────
class SuministroRecuperoSerializer(serializers.ModelSerializer):
    matricula   = serializers.CharField(source='recupero.matricula',   read_only=True)
    descripcion = serializers.CharField(source='recupero.descripcion', read_only=True)
    class Meta:
        model  = SuministroRecupero
        fields = ['id_suministro_recupero', 'suministro', 'recupero',
                  'matricula', 'descripcion', 'cantidad', 'fecha']


# ── Liquidacion Suministro ───────────────────────────────────────────────────
class LiquidacionPartidaSerializer(serializers.ModelSerializer):
    partida     = serializers.CharField(source='mano_de_obra.partida',     read_only=True)
    descripcion = serializers.CharField(source='mano_de_obra.descripcion', read_only=True)
    class Meta:
        model  = LiquidacionPartida
        fields = ['id_liquidacion_partida', 'mano_de_obra', 'partida', 'descripcion', 'cantidad']


class ConsumoMaterialSuministroSerializer(serializers.ModelSerializer):
    matricula   = serializers.CharField(source='material.matricula',   read_only=True)
    descripcion = serializers.CharField(source='material.descripcion', read_only=True)
    class Meta:
        model  = ConsumoMaterialSuministro
        fields = ['id_consumo_material', 'material', 'matricula', 'descripcion', 'cantidad', 'fecha']


class LiquidacionSuministroSerializer(serializers.ModelSerializer):
    numero_suministro   = serializers.SerializerMethodField()
    usuario_nombre      = serializers.CharField(source='usuario.nombre',      read_only=True)
    tipo_trabajo_nombre = serializers.CharField(source='tipo_trabajo.nombre', read_only=True)
    partidas            = LiquidacionPartidaSerializer(many=True, read_only=True)
    materiales          = ConsumoMaterialSuministroSerializer(source='materiales_consumidos', many=True, read_only=True)

    def get_numero_suministro(self, obj):
        if obj.suministro_id:
            return obj.suministro.numero_suministro
        return obj.suministro_externo or ''

    class Meta:
        model  = LiquidacionSuministro
        fields = [
            'id_liquidacion',
            'suministro', 'numero_suministro',
            'suministro_externo', 'sst_externo',
            'usuario', 'usuario_nombre', 'tipo_trabajo', 'tipo_trabajo_nombre',
            'fecha', 'observacion', 'partidas', 'materiales',
        ]


class LiquidacionPartidaCreateSerializer(serializers.Serializer):
    mano_de_obra = serializers.PrimaryKeyRelatedField(queryset=ManoDeObra.objects.all())
    cantidad     = serializers.DecimalField(max_digits=10, decimal_places=2)


class ConsumoMaterialCreateSerializer(serializers.Serializer):
    material = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all())
    cantidad = serializers.DecimalField(max_digits=10, decimal_places=2)


class LiquidacionSuministroCreateSerializer(serializers.Serializer):
    # Suministro local (opcional si se usa suministro externo)
    suministro          = serializers.PrimaryKeyRelatedField(queryset=Suministro.objects.all(), required=False, allow_null=True)
    # Suministro externo (del proyecto Render)
    suministro_externo  = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    sst_externo         = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    usuario             = serializers.PrimaryKeyRelatedField(queryset=Usuario.objects.all())
    tipo_trabajo        = serializers.PrimaryKeyRelatedField(queryset=TipoTrabajo.objects.all())
    observacion         = serializers.CharField(required=False, allow_blank=True, default='')
    partidas            = LiquidacionPartidaCreateSerializer(many=True)
    materiales          = ConsumoMaterialCreateSerializer(many=True, required=False, default=list)
    # Estado a fijar en Render: EJECUTADO (liquida MO + materiales) o DEVUELTO (solo MO)
    estado_suministro   = serializers.ChoiceField(
        choices=['EJECUTADO', 'DEVUELTO'], required=False, default='EJECUTADO')
    # Motivo de devolución (obligatorio si DEVUELTO) → va a observacion_contratista en Render
    motivo              = serializers.CharField(required=False, allow_blank=True, default='')
    # id del suministro en Render (para reflejar el estado/observación allá)
    suministro_render_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, data):
        if not data.get('suministro') and not data.get('suministro_externo'):
            raise serializers.ValidationError(
                'Debe indicar suministro (local) o suministro_externo (Render).'
            )
        if (data.get('estado_suministro') or 'EJECUTADO').upper() == 'DEVUELTO' \
                and not (data.get('motivo') or '').strip():
            raise serializers.ValidationError(
                {'motivo': 'El motivo es obligatorio cuando el suministro es DEVUELTO.'}
            )
        return data

    def create(self, validated_data):
        from django.db import transaction
        from django.core.exceptions import ValidationError as DjangoValidationError
        from .models import UsuarioCamion, StockCamion
        from .render_api import actualizar_suministro
        partidas_data      = validated_data.pop('partidas')
        materiales_data    = validated_data.pop('materiales', [])
        estado             = (validated_data.pop('estado_suministro', 'EJECUTADO') or 'EJECUTADO').upper()
        motivo             = validated_data.pop('motivo', '') or ''
        render_id          = validated_data.pop('suministro_render_id', None)
        usuario            = validated_data['usuario']
        suministro_local   = validated_data.get('suministro')
        suministro_externo = validated_data.get('suministro_externo', '')
        sst_externo        = validated_data.get('sst_externo', '')
        es_devuelto        = estado == 'DEVUELTO'
        with transaction.atomic():
            # Reemplazo: si el usuario ya liquidó este poste con este tipo de
            # trabajo, se borra la anterior (re-liquidar = corregir, no acumular).
            prev = LiquidacionSuministro.objects.filter(
                usuario=usuario, tipo_trabajo=validated_data.get('tipo_trabajo'))
            if suministro_local:
                prev = prev.filter(suministro=suministro_local)
            elif suministro_externo:
                prev = prev.filter(suministro_externo=suministro_externo,
                                   sst_externo=sst_externo)
            else:
                prev = prev.none()
            prev.delete()

            liq = LiquidacionSuministro.objects.create(**validated_data)
            # La mano de obra (partidas) se liquida siempre, ejecutado o devuelto
            for p in partidas_data:
                LiquidacionPartida.objects.create(liquidacion=liq, **p)
            # Los materiales solo se consumen/descuentan si el suministro fue EJECUTADO.
            # Si fue DEVUELTO no se toca stock aunque vengan materiales en el payload.
            if materiales_data and not es_devuelto:
                camion = UsuarioCamion.camion_activo_de_usuario(usuario)
                if camion is None:
                    raise serializers.ValidationError(
                        {'materiales': 'El usuario no tiene un camión activo asignado para descontar stock.'}
                    )
                for m in materiales_data:
                    try:
                        stock = StockCamion.objects.select_for_update().get(
                            camion=camion, material=m['material']
                        )
                        stock.descontar(m['cantidad'])
                    except StockCamion.DoesNotExist:
                        raise serializers.ValidationError(
                            {'materiales': f'El material {m["material"]} no está en el camión {camion}.'}
                        )
                    except DjangoValidationError as e:
                        raise serializers.ValidationError({'materiales': e.message})
                    ConsumoMaterialSuministro.objects.create(
                        liquidacion=liq,
                        suministro=suministro_local,
                        suministro_externo=suministro_externo,
                        usuario=usuario,
                        material=m['material'],
                        cantidad=m['cantidad'],
                    )
            # Reflejar el estado en el suministro local (si lo hay)
            if suministro_local:
                suministro_local.estado = 'devuelto' if es_devuelto else 'ejecutado'
                suministro_local.save(update_fields=['estado'])
            # Reflejar estado/observación en Render (si la app mandó el id de Render).
            # Va dentro de la transacción: si Render falla, se revierte la liquidación.
            if render_id:
                payload = {'estado_suministro': estado}
                if es_devuelto:
                    payload['observacion_contratista'] = motivo
                try:
                    actualizar_suministro(render_id, payload)
                except Exception as exc:
                    raise serializers.ValidationError(
                        {'estado_suministro': f'No se pudo actualizar el suministro en Render: {exc}'}
                    )
        return liq


# ── PlanoSST ─────────────────────────────────────
class PlanoSSTSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PlanoSST
        fields = '__all__'
        read_only_fields = ('empresa', 'fecha_actualizacion')
