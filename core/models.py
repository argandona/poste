from decimal import Decimal

from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from datetime import date, timedelta


class Empresa(models.Model):
    id_empresa  = models.AutoField(primary_key=True)
    nombre      = models.CharField(max_length=150)
    ruc         = models.CharField(max_length=20, unique=True)
    direccion   = models.CharField(max_length=200, blank=True)
    telefono    = models.CharField(max_length=20, blank=True)
    email       = models.EmailField(blank=True)
    logo        = models.ImageField(upload_to="empresas/logos/", null=True, blank=True)
    activo      = models.BooleanField(default=True)
    fecha_creacion = models.DateField(auto_now_add=True)
    class Meta:
        db_table = "empresa"
    def __str__(self):
        return f"{self.nombre} ({self.ruc})"


class Rol(models.Model):
    SUPERADMIN = 1; ADMIN_EMPRESA = 2; ENCARGADO = 3
    CAPATAZ = 4; LIQUIDADOR = 5; ENCARGADO_ALMACEN = 6
    COORDINADOR = 7
    id_rol      = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)
    class Meta:
        db_table = "rol"
    def __str__(self):
        return self.descripcion


class Usuario(models.Model):
    id_usuario     = models.AutoField(primary_key=True)
    nombre         = models.CharField(max_length=150)
    rol            = models.ForeignKey(Rol, on_delete=models.PROTECT, related_name="usuarios")
    # Un segundo sombrero. En obra hay gente que es capataz y coordinador a la
    # vez, y con un solo rol tendria que entrar con dos cuentas distintas.
    rol_secundario = models.ForeignKey(Rol, on_delete=models.PROTECT, related_name="usuarios_secundarios", null=True, blank=True)
    empresa        = models.ForeignKey("Empresa", on_delete=models.PROTECT, related_name="usuarios", null=True, blank=True)
    clave          = models.CharField(max_length=255)
    activo         = models.BooleanField(default=True)
    email          = models.EmailField(unique=True)
    fecha_creacion = models.DateField(auto_now_add=True)
    ultimo_acceso  = models.DateTimeField(null=True, blank=True)
    telefono       = models.CharField(max_length=20, blank=True)
    fcm_token      = models.CharField(max_length=500, blank=True, null=True)

    @property
    def roles(self):
        """Los roles que tiene puestos. Siempre el principal; el segundo si hay."""
        return {self.rol_id, self.rol_secundario_id} - {None}

    def _tiene(self, *roles): return bool(self.roles & set(roles))

    def es_superadmin(self): return self._tiene(Rol.SUPERADMIN)
    def es_admin_empresa(self): return self._tiene(Rol.ADMIN_EMPRESA)
    def puede_hacer_pedido(self): return self._tiene(Rol.ENCARGADO, Rol.CAPATAZ)
    def puede_hacer_devolucion(self): return self._tiene(Rol.ENCARGADO, Rol.CAPATAZ)
    def puede_hacer_consumo(self): return self._tiene(Rol.LIQUIDADOR, Rol.ENCARGADO_ALMACEN)
    def puede_aprobar_pedido(self): return self._tiene(Rol.ENCARGADO_ALMACEN, Rol.SUPERADMIN)
    def puede_aprobar_devolucion(self): return self._tiene(Rol.ENCARGADO_ALMACEN, Rol.SUPERADMIN)
    # Conteo fisico de existencias. En TECSUR el Capataz inventaria su propio
    # camion (ver Inventario.clean), a diferencia de ENCOSSA.
    def puede_hacer_inventario(self): return self._tiene(Rol.CAPATAZ, Rol.ENCARGADO_ALMACEN, Rol.SUPERADMIN)
    # Movimientos del almacen: ingresos de proveedor, devoluciones a Tecsur,
    # materiales malogrados y transferencias entre almacenes.
    def puede_gestionar_almacen(self): return self._tiene(Rol.ENCARGADO_ALMACEN, Rol.SUPERADMIN)
    def puede_gestionar_empresa(self): return self._tiene(Rol.ADMIN_EMPRESA, Rol.SUPERADMIN)
    def puede_asignar_sst(self): return self._tiene(Rol.COORDINADOR, Rol.SUPERADMIN)

    def clean(self):
        if self.rol_secundario_id and self.rol_secundario_id == self.rol_id:
            raise ValidationError("El rol secundario tiene que ser distinto.")
        if self.rol_id == Rol.SUPERADMIN and self.empresa_id:
            raise ValidationError("El SuperAdmin no pertenece a ninguna empresa.")
        if self.rol_id != Rol.SUPERADMIN and not self.empresa_id:
            raise ValidationError("El usuario debe pertenecer a una empresa.")
    class Meta:
        db_table = "usuario"
    def __str__(self):
        return self.nombre


class Camion(models.Model):
    id_camion   = models.AutoField(primary_key=True)
    empresa     = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="camiones")
    placa       = models.CharField(max_length=20, unique=True)
    descripcion = models.CharField(max_length=200, blank=True)
    activo      = models.BooleanField(default=True)
    class Meta:
        db_table = "camion"
    def __str__(self):
        return self.placa


class UsuarioCamion(models.Model):
    id_usuario_camion = models.AutoField(primary_key=True)
    camion       = models.ForeignKey(Camion,  on_delete=models.PROTECT, related_name="asignaciones")
    usuario      = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="asignaciones")
    fecha_inicio = models.DateField()
    fecha_fin    = models.DateField(null=True, blank=True)
    activo       = models.BooleanField(default=True)
    class Meta:
        db_table = "usuario_camion"
    def __str__(self):
        return f"{self.usuario} → {self.camion}"

    # ── Responsabilidad sobre el saldo del camión ────────────────────────────
    # La asignación NO vence sola: nace abierta (`fecha_fin` nula) y solo se
    # cierra con `liberar()` o `traspasar_a()`. Si caducara por calendario, un
    # capataz podría pedir material, dejar pasar la fecha y quedarse sin saldos
    # que devolver: el stock seguiría en el camión y ya no habría a quién
    # reclamárselo.

    # Lo activa `traspasar_a()` para poder cerrar con saldo, porque en un
    # traspaso el material no queda huérfano: pasa al siguiente responsable.
    _traspaso_en_curso = False

    def saldo_camion(self):
        """Cuánto material carga hoy el camión (suma de StockCamion)."""
        total = StockCamion.objects.filter(camion=self.camion).aggregate(
            t=models.Sum("cantidad"))["t"]
        return total or Decimal("0")

    def _esta_cerrando(self, original):
        """True si el cambio le quita al usuario la responsabilidad del camión."""
        if original.activo and not self.activo:
            return True
        if original.fecha_fin is None:
            return self.fecha_fin is not None
        return self.fecha_fin is not None and self.fecha_fin < original.fecha_fin

    def clean(self):
        if self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValidationError("La fecha de fin no puede ser anterior a la de inicio.")
        original = UsuarioCamion.objects.filter(pk=self.pk).first() if self.pk else None
        if original is None and self.fecha_fin:
            raise ValidationError("Una asignación nueva no lleva fecha de fin: se cierra al liberar o traspasar el camión.")
        if (original is not None and not self._traspaso_en_curso
                and self._esta_cerrando(original) and self.saldo_camion() > 0):
            raise ValidationError(
                f"El camión {self.camion} tiene saldo a nombre de {self.usuario}: "
                "devuelve el material al almacén o traspásalo a otro responsable "
                "antes de cerrar la asignación.")
        # Solape: una asignación abierta ocupa el camión desde su inicio en adelante.
        fin = self.fecha_fin or date.max
        qs = UsuarioCamion.objects.filter(camion=self.camion, activo=True, fecha_inicio__lte=fin).filter(models.Q(fecha_fin__isnull=True)|models.Q(fecha_fin__gte=self.fecha_inicio))
        if self.pk: qs = qs.exclude(pk=self.pk)
        if qs.exists(): raise ValidationError("El camión ya tiene un encargado en ese rango de fechas.")

    def save(self, *args, **kwargs):
        if not self.pk:
            # Antes esto cerraba la asignación anterior del usuario con un
            # `update()` masivo, que se salta clean(): era la forma fácil de
            # soltar un camión con saldo encima. Ahora se cierra una por una y
            # cada cierre valida el saldo.
            anteriores = (UsuarioCamion.objects
                          .filter(usuario=self.usuario, activo=True)
                          .filter(models.Q(fecha_fin__isnull=True)|models.Q(fecha_fin__gte=self.fecha_inicio)))
            for anterior in anteriores:
                anterior.liberar(self.fecha_inicio - timedelta(days=1))
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.saldo_camion() > 0:
            raise ValidationError(
                f"No se puede borrar la asignación: el camión {self.camion} tiene "
                f"saldo a nombre de {self.usuario}.")
        return super().delete(*args, **kwargs)

    def liberar(self, fecha_fin=None, _traspaso=False):
        """Cierra la asignación. Fuera de un traspaso exige el camión en cero."""
        self.fecha_fin = fecha_fin or date.today()
        self.activo    = False
        self._traspaso_en_curso = _traspaso
        try:
            self.full_clean()
            self.save()
        finally:
            self._traspaso_en_curso = False
        return self

    def traspasar_a(self, usuario_recibe, fecha=None, observacion=""):
        """Entrega el camión a otro responsable: cierra esta asignación, abre la
        del que recibe y levanta el acta con el saldo que cambió de manos."""
        fecha = fecha or date.today()
        if usuario_recibe.pk == self.usuario_id:
            raise ValidationError("El camión ya está a nombre de ese usuario.")
        if not self.activo:
            raise ValidationError("Esta asignación ya está cerrada.")
        with transaction.atomic():
            acta = TraspasoCamion(camion=self.camion, usuario_entrega=self.usuario,
                                  usuario_recibe=usuario_recibe, fecha=fecha,
                                  observacion=observacion)
            acta.full_clean()
            acta.save()
            for sc in (StockCamion.objects.filter(camion=self.camion, cantidad__gt=0)
                       .select_related("material").order_by("material__matricula")):
                DetalleTraspasoCamion.objects.create(
                    traspaso=acta, material=sc.material, cantidad=sc.cantidad)
            self.liberar(fecha, _traspaso=True)
            nueva = UsuarioCamion(camion=self.camion, usuario=usuario_recibe,
                                  fecha_inicio=fecha)
            nueva.full_clean()
            nueva.save()
        return acta
    @staticmethod
    def camion_activo_de_usuario(usuario, fecha=None):
        fecha = fecha or date.today()
        asignacion = UsuarioCamion.objects.filter(usuario=usuario, fecha_inicio__lte=fecha, activo=True).filter(models.Q(fecha_fin__isnull=True)|models.Q(fecha_fin__gte=fecha)).select_related("camion").first()
        return asignacion.camion if asignacion else None


class Actividad(models.Model):
    id_actividad = models.AutoField(primary_key=True)
    nombre       = models.CharField(max_length=200, unique=True)
    class Meta:
        db_table = "actividad"
    def __str__(self):
        return self.nombre


class SST(models.Model):
    id_sst        = models.AutoField(primary_key=True)
    sst           = models.CharField(max_length=7, blank=True)
    codigo        = models.CharField(max_length=20, blank=True, db_index=True)
    empresa       = models.ForeignKey(Empresa,   on_delete=models.PROTECT, related_name="ssts")
    distrito      = models.CharField(max_length=100)
    actividad     = models.ForeignKey(Actividad, on_delete=models.PROTECT, related_name="ssts", null=True, blank=True)
    fecha_inicio  = models.DateField(null=True, blank=True)
    fecha_termino = models.DateField(null=True, blank=True)
    fecha_ejecucion = models.DateField(null=True, blank=True)
    # La hora sale en el cuaderno de obra junto con la fecha de ejecución.
    hora_ejecucion  = models.TimeField(null=True, blank=True)
    monto_sst     = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    class Meta:
        db_table = "sst"
    def __str__(self):
        return self.sst or self.codigo or f"SST #{self.id_sst}"


class SSTEncargado(models.Model):
    id_sst_encargado = models.AutoField(primary_key=True)
    sst     = models.ForeignKey(SST,     on_delete=models.PROTECT, related_name="sst_encargados")
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="sst_encargados")
    class Meta:
        db_table = "sst_encargado"
        unique_together = (("sst", "usuario"),)
    def __str__(self):
        return f"{self.usuario} → {self.sst}"


class Suministro(models.Model):
    ESTADO_CHOICES = [("asignado", "Asignado"), ("ejecutado", "Ejecutado"), ("devuelto", "Devuelto")]
    id_suministro     = models.AutoField(primary_key=True)
    numero_suministro = models.CharField(max_length=20, unique=True, db_index=True)
    medidor           = models.CharField(max_length=20, blank=True)
    distrito          = models.CharField(max_length=100, blank=True)
    monto_sum         = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)])
    estado            = models.CharField(max_length=20, choices=ESTADO_CHOICES, default="asignado")
    fecha_ejecucion   = models.DateField(null=True, blank=True)
    ejecutado_por     = models.CharField(max_length=150, blank=True)
    motivo_devolucion = models.TextField(blank=True)
    observacion       = models.TextField(blank=True)
    class Meta:
        db_table = "suministro"
    def __str__(self):
        return self.numero_suministro


class SSTSuministro(models.Model):
    id_sst_suministro = models.AutoField(primary_key=True)
    sst        = models.ForeignKey(SST,        on_delete=models.PROTECT, related_name="sst_suministros")
    suministro = models.ForeignKey(Suministro, on_delete=models.PROTECT, related_name="sst_suministros")
    asignado_a = models.ForeignKey(Usuario,    on_delete=models.SET_NULL, null=True, blank=True, related_name="suministros_asignados")
    class Meta:
        db_table = "sst_suministro"
        unique_together = (("sst", "suministro"),)
    def __str__(self):
        return f"{self.sst} → {self.suministro}"


class ManoDeObra(models.Model):
    id_mano_de_obra = models.AutoField(primary_key=True)
    partida         = models.CharField(max_length=7, unique=True)
    descripcion     = models.CharField(max_length=200)
    precio          = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    class Meta:
        db_table = "mano_de_obra"
    def __str__(self):
        return f"{self.partida} - {self.descripcion}"


class Material(models.Model):
    id_material = models.AutoField(primary_key=True)
    matricula   = models.CharField(max_length=50, unique=True)
    descripcion = models.CharField(max_length=200)
    precio      = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    class Meta:
        db_table = "material"
    def __str__(self):
        return f"{self.matricula} - {self.descripcion}"


class StockCamion(models.Model):
    id_stock = models.AutoField(primary_key=True)
    camion   = models.ForeignKey(Camion,   on_delete=models.PROTECT, related_name="stocks")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="stocks")
    cantidad = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    class Meta:
        db_table = "stock_camion"
        unique_together = ("camion", "material")
    def descontar(self, cantidad):
        if self.cantidad - cantidad < 0: raise ValidationError(f"Stock insuficiente para {self.material}.")
        self.cantidad -= cantidad; self.save()
    def agregar(self, cantidad):
        self.cantidad += cantidad; self.save()
    def __str__(self):
        return f"{self.camion} | {self.material} | {self.cantidad}"


class TraspasoCamion(models.Model):
    """Acta de entrega de un camión con saldo: quién lo entrega, quién lo recibe
    y qué material cambió de manos. Es lo que permite cerrar una asignación sin
    que el stock del camión quede sin responsable."""
    id_traspaso     = models.AutoField(primary_key=True)
    camion          = models.ForeignKey(Camion,  on_delete=models.PROTECT, related_name="traspasos")
    usuario_entrega = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="traspasos_entregados")
    usuario_recibe  = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="traspasos_recibidos")
    fecha           = models.DateField()
    observacion     = models.TextField(blank=True)
    class Meta:
        db_table = "traspaso_camion"
        ordering = ["-fecha", "-id_traspaso"]
    def clean(self):
        if self.usuario_entrega_id and self.usuario_entrega_id == self.usuario_recibe_id:
            raise ValidationError("El que entrega y el que recibe no pueden ser el mismo.")
    def __str__(self):
        return f"{self.camion} | {self.usuario_entrega} → {self.usuario_recibe} ({self.fecha})"


class DetalleTraspasoCamion(models.Model):
    """Foto del saldo del camión en el momento del traspaso."""
    id_detalle_traspaso = models.AutoField(primary_key=True)
    traspaso = models.ForeignKey(TraspasoCamion, on_delete=models.CASCADE, related_name="detalles")
    material = models.ForeignKey(Material,       on_delete=models.PROTECT, related_name="detalles_traspaso")
    cantidad = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    class Meta:
        db_table = "detalle_traspaso_camion"
        unique_together = ("traspaso", "material")
        ordering = ["material__matricula"]
    def __str__(self):
        return f"{self.material} | {self.cantidad}"


class Almacen(models.Model):
    id_almacen  = models.AutoField(primary_key=True)
    empresa     = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="almacenes")
    nombre      = models.CharField(max_length=100)
    direccion   = models.CharField(max_length=200, blank=True)
    activo      = models.BooleanField(default=True)
    class Meta:
        db_table = "almacen"
    def __str__(self):
        return self.nombre


class StockAlmacen(models.Model):
    id_stock_almacen = models.AutoField(primary_key=True)
    almacen  = models.ForeignKey(Almacen,  on_delete=models.PROTECT, related_name="stocks")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="stocks_almacen")
    cantidad = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    class Meta:
        db_table = "stock_almacen"
        unique_together = ("almacen", "material")
    def descontar(self, cantidad):
        if self.cantidad - cantidad < 0: raise ValidationError(f"Stock insuficiente en {self.almacen}.")
        self.cantidad -= cantidad; self.save()
    def agregar(self, cantidad):
        self.cantidad += cantidad; self.save()
    def __str__(self):
        return f"{self.almacen} | {self.material} | {self.cantidad}"


class Proveedor(models.Model):
    id_proveedor = models.AutoField(primary_key=True)
    nombre       = models.CharField(max_length=150)
    ruc          = models.CharField(max_length=20, unique=True)
    direccion    = models.CharField(max_length=200, blank=True)
    telefono     = models.CharField(max_length=20, blank=True)
    email        = models.EmailField(blank=True)
    contacto     = models.CharField(max_length=100, blank=True)
    activo       = models.BooleanField(default=True)
    class Meta:
        db_table = "proveedor"
    def __str__(self):
        return f"{self.nombre} ({self.ruc})"


class IngresoTecsur(models.Model):
    id_ingreso  = models.AutoField(primary_key=True)
    almacen     = models.ForeignKey(Almacen,   on_delete=models.PROTECT, related_name="ingresos")
    proveedor   = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="ingresos")
    usuario     = models.ForeignKey(Usuario,   on_delete=models.PROTECT, related_name="ingresos_tecsur")
    folio       = models.CharField(max_length=50, unique=True)
    fecha       = models.DateField()
    observacion = models.TextField(blank=True)
    class Meta:
        db_table = "ingreso_tecsur"
    def clean(self):
        if self.usuario_id and not self.usuario.puede_gestionar_almacen():
            raise ValidationError("Solo el Encargado de Almacén puede registrar ingresos.")
    def __str__(self):
        return f"Ingreso {self.folio} | {self.almacen}"


class DetalleIngresoTecsur(models.Model):
    id_detalle_ingreso = models.AutoField(primary_key=True)
    ingreso   = models.ForeignKey(IngresoTecsur, on_delete=models.CASCADE, related_name="detalles")
    material  = models.ForeignKey(Material,      on_delete=models.PROTECT, related_name="detalles_ingreso")
    cantidad  = models.PositiveIntegerField()
    class Meta:
        db_table = "detalle_ingreso_tecsur"
        unique_together = ("ingreso", "material")


class DevolucionTecsur(models.Model):
    id_devolucion_tecsur = models.AutoField(primary_key=True)
    almacen     = models.ForeignKey(Almacen,   on_delete=models.PROTECT, related_name="devoluciones_tecsur")
    proveedor   = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="devoluciones_tecsur")
    usuario     = models.ForeignKey(Usuario,   on_delete=models.PROTECT, related_name="devoluciones_tecsur")
    folio       = models.CharField(max_length=50, unique=True)
    fecha       = models.DateField()
    observacion = models.TextField(blank=True)
    class Meta:
        db_table = "devolucion_tecsur"
    def clean(self):
        if self.usuario_id and not self.usuario.puede_gestionar_almacen():
            raise ValidationError("Solo el Encargado de Almacén puede registrar devoluciones a Tecsur.")


class DetalleDevolucionTecsur(models.Model):
    id_detalle_dev_tecsur = models.AutoField(primary_key=True)
    devolucion_tecsur = models.ForeignKey(DevolucionTecsur, on_delete=models.CASCADE, related_name="detalles")
    material          = models.ForeignKey(Material,         on_delete=models.PROTECT, related_name="detalles_dev_tecsur")
    cantidad          = models.PositiveIntegerField()
    class Meta:
        db_table = "detalle_devolucion_tecsur"
        unique_together = ("devolucion_tecsur", "material")


class MaterialMalogrado(models.Model):
    id_malogrado   = models.AutoField(primary_key=True)
    almacen        = models.ForeignKey(Almacen,   on_delete=models.PROTECT, related_name="materiales_malogrados")
    proveedor      = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="materiales_malogrados")
    usuario        = models.ForeignKey(Usuario,   on_delete=models.PROTECT, related_name="materiales_malogrados")
    folio_factura  = models.CharField(max_length=50, unique=True)
    fecha          = models.DateField()
    observacion    = models.TextField(blank=True)
    class Meta:
        db_table = "material_malogrado"
    def clean(self):
        if self.usuario_id and not self.usuario.puede_gestionar_almacen():
            raise ValidationError("Solo el Encargado de Almacén puede registrar materiales malogrados.")


class DetalleMaterialMalogrado(models.Model):
    id_detalle_malogrado = models.AutoField(primary_key=True)
    malogrado      = models.ForeignKey(MaterialMalogrado, on_delete=models.CASCADE, related_name="detalles")
    material       = models.ForeignKey(Material,          on_delete=models.PROTECT, related_name="detalles_malogrado")
    cantidad       = models.PositiveIntegerField()
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    class Meta:
        db_table = "detalle_material_malogrado"
        unique_together = ("malogrado", "material")
    @property
    def costo_total(self):
        return self.cantidad * self.costo_unitario


class TransferenciaAlmacen(models.Model):
    id_transferencia = models.AutoField(primary_key=True)
    almacen_origen   = models.ForeignKey(Almacen, on_delete=models.PROTECT, related_name="transferencias_salida")
    almacen_destino  = models.ForeignKey(Almacen, on_delete=models.PROTECT, related_name="transferencias_entrada")
    usuario          = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="transferencias")
    fecha            = models.DateField()
    observacion      = models.TextField(blank=True)
    class Meta:
        db_table = "transferencia_almacen"
    def clean(self):
        if self.usuario_id and not self.usuario.puede_gestionar_almacen():
            raise ValidationError("Solo el Encargado de Almacén puede realizar transferencias.")
        if self.almacen_origen_id == self.almacen_destino_id:
            raise ValidationError("El almacén origen y destino no pueden ser el mismo.")


class DetalleTransferencia(models.Model):
    id_detalle_transferencia = models.AutoField(primary_key=True)
    transferencia = models.ForeignKey(TransferenciaAlmacen, on_delete=models.CASCADE, related_name="detalles")
    material      = models.ForeignKey(Material,             on_delete=models.PROTECT, related_name="detalles_transferencia")
    cantidad      = models.PositiveIntegerField()
    class Meta:
        db_table = "detalle_transferencia"
        unique_together = ("transferencia", "material")


class Pedido(models.Model):
    ESTADO_CHOICES = [("pendiente","Pendiente"),("aprobado","Aprobado"),("rechazado","Rechazado")]
    id_pedido        = models.AutoField(primary_key=True)
    camion           = models.ForeignKey(Camion,  on_delete=models.PROTECT, related_name="pedidos")
    usuario          = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="pedidos")
    almacen          = models.ForeignKey("Almacen", on_delete=models.PROTECT, related_name="pedidos", null=True, blank=True)
    estado           = models.CharField(max_length=20, choices=ESTADO_CHOICES, default="pendiente")
    usuario_aprueba  = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name="pedidos_aprobados")
    fecha_aprobacion = models.DateField(null=True, blank=True)
    observacion      = models.TextField(blank=True)
    fecha            = models.DateField(auto_now_add=True)
    class Meta:
        db_table = "pedido"
    def clean(self):
        if self.usuario_id and not self.usuario.puede_hacer_pedido():
            raise ValidationError("Solo un Encargado o Capataz puede realizar un pedido.")
        if self.usuario_aprueba_id and self.usuario_aprueba_id == self.usuario_id:
            raise ValidationError("El aprobador no puede ser el mismo que realizó el pedido.")
        if self.usuario_aprueba_id and not self.usuario_aprueba.puede_aprobar_pedido():
            raise ValidationError("Solo el Encargado de Almacén puede aprobar pedidos.")
        fecha_ref = self.fecha or date.today()
        camion_asignado = UsuarioCamion.camion_activo_de_usuario(self.usuario, fecha_ref)
        if camion_asignado is None: raise ValidationError("No tienes un camión asignado en este momento.")
        if self.camion_id != camion_asignado.id_camion: raise ValidationError("El camión no está asignado a este usuario.")
        if self.pk:
            original = Pedido.objects.get(pk=self.pk)
            if original.estado == "rechazado": raise ValidationError("Un pedido rechazado no puede modificarse.")
            if original.estado == "aprobado":  raise ValidationError("Un pedido aprobado no puede modificarse.")
    def __str__(self):
        return f"Pedido #{self.id_pedido} - {self.estado}"


class DetallePedido(models.Model):
    id_detalle_pedido   = models.AutoField(primary_key=True)
    pedido              = models.ForeignKey(Pedido,   on_delete=models.CASCADE, related_name="detalles")
    material            = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="detalles_pedido")
    cantidad_solicitada = models.PositiveIntegerField()
    cantidad_aprobada   = models.PositiveIntegerField(default=0)
    class Meta:
        db_table = "detalle_pedido"
    def clean(self):
        if self.cantidad_aprobada > self.cantidad_solicitada:
            raise ValidationError("La cantidad aprobada no puede superar la solicitada.")


class Devolucion(models.Model):
    ESTADO_CHOICES = [("pendiente","Pendiente"),("aprobado","Aprobado"),("rechazado","Rechazado")]
    id_devolucion    = models.AutoField(primary_key=True)
    camion           = models.ForeignKey(Camion,  on_delete=models.PROTECT, related_name="devoluciones")
    usuario          = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="devoluciones")
    almacen_destino  = models.ForeignKey("Almacen", on_delete=models.PROTECT, related_name="devoluciones_recibidas", null=True, blank=True)
    estado           = models.CharField(max_length=20, choices=ESTADO_CHOICES, default="pendiente")
    usuario_aprueba  = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name="devoluciones_aprobadas")
    fecha_aprobacion = models.DateField(null=True, blank=True)
    observacion      = models.TextField(blank=True)
    fecha            = models.DateField(auto_now_add=True)
    class Meta:
        db_table = "devolucion"
    def clean(self):
        if self.usuario_id and not self.usuario.puede_hacer_devolucion():
            raise ValidationError("Solo un Encargado o Capataz puede realizar una devolución.")
        if self.usuario_aprueba_id and self.usuario_aprueba_id == self.usuario_id:
            raise ValidationError("El aprobador no puede ser el mismo que realizó la devolución.")
        if self.pk:
            original = Devolucion.objects.get(pk=self.pk)
            if original.estado == "rechazado": raise ValidationError("Una devolución rechazada no puede modificarse.")
            if original.estado == "aprobado":  raise ValidationError("Una devolución aprobada no puede modificarse.")
    def __str__(self):
        return f"Devolución #{self.id_devolucion} - {self.estado}"


class DetalleDevolucion(models.Model):
    id_detalle_devolucion = models.AutoField(primary_key=True)
    devolucion            = models.ForeignKey(Devolucion, on_delete=models.CASCADE, related_name="detalles")
    material              = models.ForeignKey(Material,   on_delete=models.PROTECT, related_name="detalles_devolucion")
    cantidad_solicitada   = models.PositiveIntegerField()
    cantidad_aprobada     = models.PositiveIntegerField(default=0)
    class Meta:
        db_table = "detalle_devolucion"


class UploadConsumo(models.Model):
    ESTADO_CHOICES = [("pendiente","Pendiente"),("aprobado","Aprobado"),("rechazado","Rechazado")]
    id_upload      = models.AutoField(primary_key=True)
    sst            = models.OneToOneField(SST, on_delete=models.PROTECT, related_name="upload_consumo")
    usuario        = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="uploads_consumo")
    fecha_upload   = models.DateTimeField(auto_now=True)
    nombre_archivo = models.CharField(max_length=255, blank=True)
    estado         = models.CharField(max_length=20, choices=ESTADO_CHOICES, default="pendiente")
    class Meta:
        db_table = "upload_consumo"
    def clean(self):
        if self.usuario_id and not self.usuario.puede_hacer_consumo():
            raise ValidationError("Solo un Liquidador o Encargado de Almacén puede subir consumos.")


class Consumo(models.Model):
    id_consumo      = models.AutoField(primary_key=True)
    upload          = models.ForeignKey(UploadConsumo, on_delete=models.CASCADE, related_name="consumos")
    usuario_consume = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="consumos_realizados")
    camion          = models.ForeignKey(Camion, on_delete=models.PROTECT, related_name="consumos")
    suministro      = models.CharField(max_length=50, blank=True)
    fecha           = models.DateField()
    class Meta:
        db_table = "consumo"
        unique_together = ("upload", "usuario_consume", "camion", "suministro", "fecha")


class DetalleConsumo(models.Model):
    id_detalle_consumo = models.AutoField(primary_key=True)
    consumo   = models.ForeignKey(Consumo,  on_delete=models.CASCADE, related_name="detalles")
    material  = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="detalles_consumo")
    cantidad  = models.PositiveIntegerField()
    class Meta:
        db_table = "detalle_consumo"
        unique_together = ("consumo", "material")


class Inventario(models.Model):
    ESTADO_CHOICES = [("borrador","Borrador"),("cerrado","Cerrado")]
    id_inventario = models.AutoField(primary_key=True)
    camion        = models.ForeignKey(Camion,   on_delete=models.PROTECT, related_name="inventarios", null=True, blank=True)
    almacen       = models.ForeignKey(Almacen,  on_delete=models.PROTECT, related_name="inventarios", null=True, blank=True)
    usuario       = models.ForeignKey(Usuario,  on_delete=models.PROTECT, related_name="inventarios")
    fecha         = models.DateField(auto_now_add=True)
    mes           = models.PositiveSmallIntegerField()
    anio          = models.PositiveSmallIntegerField()
    estado        = models.CharField(max_length=20, choices=ESTADO_CHOICES, default="borrador")
    observacion   = models.TextField(blank=True)
    class Meta:
        db_table = "inventario"
        unique_together = [("camion","mes","anio"),("almacen","mes","anio")]
    def clean(self):
        if self.usuario_id and not self.usuario.puede_hacer_inventario():
            raise ValidationError("Este rol no puede realizar inventarios.")
        if self.camion_id and self.almacen_id: raise ValidationError("El inventario debe ser de un camión O un almacén, no ambos.")
        if not self.camion_id and not self.almacen_id: raise ValidationError("El inventario debe apuntar a un camión o un almacén.")
        # El Capataz solo cuenta el camión que tiene asignado; el almacén es
        # del Encargado de Almacén.
        if self.usuario_id and self.usuario.rol_id == Rol.CAPATAZ:
            if not self.camion_id:
                raise ValidationError("El Capataz solo puede inventariar su camión, no el almacén.")
            camion_asignado = UsuarioCamion.camion_activo_de_usuario(self.usuario, self.fecha or date.today())
            if camion_asignado is None:
                raise ValidationError("No tienes un camión asignado en este momento.")
            if self.camion_id != camion_asignado.id_camion:
                raise ValidationError("El camión no está asignado a este usuario.")


class DetalleInventario(models.Model):
    id_detalle_inventario = models.AutoField(primary_key=True)
    inventario       = models.ForeignKey(Inventario, on_delete=models.CASCADE, related_name="detalles")
    material         = models.ForeignKey(Material,   on_delete=models.PROTECT, related_name="detalles_inventario")
    cantidad_fisica  = models.IntegerField()
    cantidad_teorica = models.IntegerField()
    diferencia       = models.IntegerField()
    observacion      = models.TextField(blank=True)
    class Meta:
        db_table = "detalle_inventario"
        ordering = ["material__matricula"]
    def save(self, *args, **kwargs):
        self.diferencia = self.cantidad_fisica - self.cantidad_teorica
        super().save(*args, **kwargs)


class TipoTrabajo(models.Model):
    id_tipo_trabajo = models.AutoField(primary_key=True)
    nombre          = models.CharField(max_length=200, unique=True)
    class Meta:
        db_table = "tipo_trabajo"
    def __str__(self):
        return self.nombre


class SuministroTipoTrabajo(models.Model):
    id_suministro_tipo_trabajo = models.AutoField(primary_key=True)
    suministro   = models.ForeignKey(Suministro,  on_delete=models.PROTECT, related_name="tipos_trabajo")
    tipo_trabajo = models.ForeignKey(TipoTrabajo, on_delete=models.PROTECT, related_name="suministros")
    class Meta:
        db_table = "suministro_tipo_trabajo"
        unique_together = (("suministro", "tipo_trabajo"),)


class TipoTrabajoManoDeObra(models.Model):
    id_tipo_trabajo_mano_de_obra = models.AutoField(primary_key=True)
    tipo_trabajo = models.ForeignKey(TipoTrabajo, on_delete=models.PROTECT, related_name="partidas")
    mano_de_obra = models.ForeignKey(ManoDeObra,  on_delete=models.PROTECT, related_name="tipos_trabajo")
    # Lo que se propone al elegir el tipo de trabajo. El capataz lo corrige si
    # en obra salió distinto; cero significa que arranca en blanco.
    cantidad_inicial = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    class Meta:
        db_table = "tipo_trabajo_mano_de_obra"
        unique_together = (("tipo_trabajo", "mano_de_obra"),)
    def __str__(self):
        return f"{self.tipo_trabajo} – {self.mano_de_obra}"


class TipoTrabajoMaterial(models.Model):
    id_tipo_trabajo_material = models.AutoField(primary_key=True)
    tipo_trabajo = models.ForeignKey(TipoTrabajo, on_delete=models.PROTECT, related_name="materiales")
    material     = models.ForeignKey(Material,    on_delete=models.PROTECT, related_name="tipos_trabajo")
    # Lo que se propone al elegir el tipo de trabajo. El capataz lo corrige si
    # en obra salió distinto; cero significa que arranca en blanco.
    cantidad_inicial = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    class Meta:
        db_table = "tipo_trabajo_material"
        unique_together = (("tipo_trabajo", "material"),)
    def __str__(self):
        return f"{self.tipo_trabajo} – {self.material}"


class ActividadTipoTrabajo(models.Model):
    actividad    = models.ForeignKey(Actividad,   on_delete=models.PROTECT, related_name='tipos_trabajo')
    tipo_trabajo = models.ForeignKey(TipoTrabajo, on_delete=models.PROTECT, related_name='actividades')
    # En qué orden se le muestran al capataz. El orden es el de la obra: se
    # empieza por el poste y se termina por lo suelto, no por el abecedario.
    orden        = models.PositiveIntegerField(default=0)
    class Meta:
        db_table        = "actividad_tipo_trabajo"
        unique_together = (("actividad", "tipo_trabajo"),)
        ordering        = ["orden", "tipo_trabajo__nombre"]
    def __str__(self):
        return f"{self.actividad} → {self.tipo_trabajo}"


class TipoTrabajoMaterialProxy(TipoTrabajo):
    class Meta:
        proxy = True
        verbose_name        = "Tipo trabajo material"
        verbose_name_plural = "Tipo trabajos materiales"


class SuministroManoDeObra(models.Model):
    id_suministro_mano_de_obra = models.AutoField(primary_key=True)
    suministro   = models.ForeignKey(Suministro, on_delete=models.PROTECT, related_name="mano_de_obra")
    mano_de_obra = models.ForeignKey(ManoDeObra, on_delete=models.PROTECT, related_name="suministros")
    class Meta:
        db_table = "suministro_mano_de_obra"
        unique_together = (("suministro", "mano_de_obra"),)
    def __str__(self):
        return f"{self.suministro} – {self.mano_de_obra}"


class LiquidacionSuministro(models.Model):
    id_liquidacion      = models.AutoField(primary_key=True)
    suministro          = models.ForeignKey(Suministro,  on_delete=models.PROTECT, related_name="liquidaciones", null=True, blank=True)
    suministro_externo  = models.CharField(max_length=20, blank=True)   # numero_suministro de Render
    sst_externo         = models.CharField(max_length=20, blank=True)   # sst_codigo de Render
    usuario             = models.ForeignKey(Usuario,     on_delete=models.PROTECT, related_name="liquidaciones")
    tipo_trabajo        = models.ForeignKey(TipoTrabajo, on_delete=models.PROTECT, related_name="liquidaciones")
    fecha               = models.DateField(auto_now_add=True)
    observacion         = models.TextField(blank=True)
    # Lo que el tipo de trabajo pidió anotar aparte, sin la observación general:
    # por ejemplo los suministros de las conexiones trasladadas, que van tal
    # cual al cuaderno de obra.
    comentario          = models.TextField(blank=True)
    class Meta:
        db_table = "liquidacion_suministro"
    def __str__(self):
        ref = self.suministro or self.suministro_externo or self.id_liquidacion
        return f"Liq #{self.id_liquidacion} – {ref}"


class LiquidacionPartida(models.Model):
    id_liquidacion_partida = models.AutoField(primary_key=True)
    liquidacion  = models.ForeignKey(LiquidacionSuministro, on_delete=models.CASCADE,  related_name="partidas")
    mano_de_obra = models.ForeignKey(ManoDeObra,            on_delete=models.PROTECT,  related_name="liquidaciones")
    cantidad     = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    class Meta:
        db_table = "liquidacion_partida"
        unique_together = (("liquidacion", "mano_de_obra"),)


class Recupero(models.Model):
    id_recupero = models.AutoField(primary_key=True)
    matricula   = models.CharField(max_length=50, unique=True)
    descripcion = models.CharField(max_length=200)
    # Unidad de medida para el formato TS-REC-FR-001: casi todo va por unidad,
    # los cables por metro.
    unidad      = models.CharField(max_length=10, default="UND")
    class Meta:
        db_table = "recupero"
    def __str__(self):
        return f"{self.matricula} - {self.descripcion}"


class SuministroRecupero(models.Model):
    id_suministro_recupero = models.AutoField(primary_key=True)
    suministro  = models.ForeignKey(Suministro, on_delete=models.PROTECT, related_name="recuperos")
    recupero    = models.ForeignKey(Recupero,   on_delete=models.PROTECT, related_name="suministros")
    cantidad    = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    fecha       = models.DateField()
    class Meta:
        db_table = "suministro_recupero"
    def __str__(self):
        return f"{self.suministro} – {self.recupero} x{self.cantidad}"


class ConsumoMaterialSuministro(models.Model):
    id_consumo_material = models.AutoField(primary_key=True)
    liquidacion         = models.ForeignKey(LiquidacionSuministro, on_delete=models.CASCADE,
                                            related_name="materiales_consumidos", null=True, blank=True)
    suministro          = models.ForeignKey(Suministro, on_delete=models.PROTECT, related_name="consumos_material", null=True, blank=True)
    suministro_externo  = models.CharField(max_length=20, blank=True)
    material            = models.ForeignKey(Material,   on_delete=models.PROTECT, related_name="consumos_suministro")
    usuario             = models.ForeignKey(Usuario,    on_delete=models.PROTECT, related_name="consumos_suministro")
    cantidad            = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    fecha               = models.DateField(auto_now_add=True)
    class Meta:
        db_table = "consumo_material_suministro"
    def __str__(self):
        return f"{self.suministro} – {self.material} x{self.cantidad}"


class CuadernoObra(models.Model):
    """Número correlativo del cuaderno de obra de una SST.

    El formato impreso trae su número; aquí se lo da el sistema, uno por SST y
    por empresa. Se fija la primera vez que se genera y no cambia al volver a
    descargarlo, para que el papel y el sistema digan lo mismo."""
    id_cuaderno = models.AutoField(primary_key=True)
    empresa     = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="cuadernos")
    sst_codigo  = models.CharField(max_length=20)
    numero      = models.PositiveIntegerField()
    fecha       = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = "cuaderno_obra"
        unique_together = (("empresa", "sst_codigo"), ("empresa", "numero"))
    def __str__(self):
        return f"C.O. {self.numero:06d} – SST {self.sst_codigo}"


class PlanoSST(models.Model):
    """Plano/croquis editable asociado a un SST (1 plano por SST por empresa).

    Se identifica por el código de SST que llega de Render (igual que
    LiquidacionSuministro.sst_externo), no por la tabla local SST. El dibujo se
    guarda como lista de elementos (assetId, x, y, escala, rotacion, z)."""
    id_plano   = models.AutoField(primary_key=True)
    empresa    = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="planos")
    sst_codigo = models.CharField(max_length=20, db_index=True)
    usuario    = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="planos")  # último editor
    elementos  = models.JSONField(default=list)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    class Meta:
        db_table = "plano_sst"
        unique_together = (("empresa", "sst_codigo"),)
    def __str__(self):
        return f"Plano SST {self.sst_codigo} ({len(self.elementos)} elementos)"
