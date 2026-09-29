"""
Los movimientos de almacén se crean por la API con sus detalles.

El detalle exigía el campo de su padre (ingreso, transferencia...), que
todavía no existe cuando se manda el cuerpo, así que ninguno se podía crear:
la respuesta era 400 con "ingreso: Este campo es requerido".
"""
from datetime import date
from decimal import Decimal

from ..models import Almacen, Proveedor
from .base import BaseAPITestCase


class MovimientosDeAlmacenTests(BaseAPITestCase):

    def setUp(self):
        super().setUp()
        self.proveedor = Proveedor.objects.create(nombre="TECSUR", ruc="TECSUR-SIN-RUC")
        self.auth(self.encargado)

    def cabecera(self, **extra):
        return {"almacen": self.almacen.pk, "proveedor": self.proveedor.pk,
                "usuario": self.encargado.pk, "fecha": date.today().isoformat(),
                "observacion": "", **extra}

    def test_ingreso_suma_al_almacen(self):
        resp = self.client.post("/api/ingresos-tecsur/", self.cabecera(
            folio="ING-1",
            detalles=[{"material": self.material_a.pk, "cantidad": 500},
                      {"material": self.material_b.pk, "cantidad": 1000}]),
            format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("510"))
        self.assertEqual(self.stock_almacen(self.material_b), Decimal("1000"))

    def test_el_folio_repetido_no_carga_dos_veces(self):
        cuerpo = self.cabecera(
            folio="ING-1",
            detalles=[{"material": self.material_a.pk, "cantidad": 5}])
        self.client.post("/api/ingresos-tecsur/", cuerpo, format="json")
        resp = self.client.post("/api/ingresos-tecsur/", cuerpo, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("15"))

    def test_devolucion_a_tecsur_resta_del_almacen(self):
        resp = self.client.post("/api/devoluciones-tecsur/", self.cabecera(
            folio="DEV-1",
            detalles=[{"material": self.material_a.pk, "cantidad": 3}]),
            format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("7"))

    def test_material_malogrado_resta_del_almacen(self):
        resp = self.client.post("/api/materiales-malogrados/", self.cabecera(
            folio_factura="F-1",
            detalles=[{"material": self.material_a.pk, "cantidad": 2,
                       "costo_unitario": "10.00"}]),
            format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("8"))

    def test_transferencia_mueve_entre_almacenes(self):
        otro = Almacen.objects.create(empresa=self.empresa, nombre="Obra")
        resp = self.client.post("/api/transferencias/", {
            "almacen_origen": self.almacen.pk, "almacen_destino": otro.pk,
            "usuario": self.encargado.pk, "fecha": date.today().isoformat(),
            "observacion": "",
            "detalles": [{"material": self.material_a.pk, "cantidad": 4}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("6"))


class ModuloDeIngresosTests(BaseAPITestCase):
    """Lo que usa el módulo de ingresos de la app."""

    def setUp(self):
        super().setUp()
        self.proveedor = Proveedor.objects.create(nombre="TECSUR", ruc="20206018411")

    def ingreso(self, folio="ING-1", detalles=None, **extra):
        return self.client.post("/api/ingresos-tecsur/", {
            "almacen": self.almacen.pk, "proveedor": self.proveedor.pk,
            "usuario": self.capataz.pk, "folio": folio,
            "fecha": date.today().isoformat(), "observacion": "",
            "detalles": detalles or [{"material": self.material_a.pk,
                                      "cantidad": "2.5"}],
            **extra}, format="json")

    def test_entra_con_decimales_y_a_nombre_de_quien_lo_registra(self):
        self.auth(self.encargado)
        resp = self.ingreso()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("12.50"))
        # El cuerpo decía el capataz; queda el que tiene la sesión.
        self.assertEqual(resp.json()["usuario"], self.encargado.pk)
        self.assertEqual(resp.json()["detalles"][0]["cantidad"], 2.5)

    def test_un_capataz_no_registra_ingresos(self):
        self.auth(self.capataz)
        resp = self.ingreso()
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("10"))

    def test_no_entra_una_cantidad_en_cero(self):
        self.auth(self.encargado)
        resp = self.ingreso(detalles=[{"material": self.material_a.pk,
                                       "cantidad": "0"}])
        self.assertEqual(resp.status_code, 400)

    def test_la_lista_muestra_solo_los_de_su_empresa(self):
        from ..models import Empresa, IngresoTecsur
        otra = Empresa.objects.create(nombre="Otra", ruc="20999999999")
        ajeno = Almacen.objects.create(empresa=otra, nombre="Ajeno")
        IngresoTecsur.objects.create(
            almacen=ajeno, proveedor=self.proveedor, usuario=self.encargado,
            folio="AJENO", fecha=date.today())
        self.auth(self.encargado)
        self.ingreso()
        datos = self.client.get("/api/ingresos-tecsur/").json()
        folios = [i["folio"] for i in datos.get("results", datos)]
        self.assertEqual(folios, ["ING-1"])

    def test_faltantes_de_los_pedidos_pendientes(self):
        from ..models import DetallePedido, Pedido
        pedido = Pedido.objects.create(
            camion=self.camion, usuario=self.capataz, estado="pendiente")
        # Del A hay 10 y se piden 14: faltan 4. Del B no hay y se piden 2.5.
        DetallePedido.objects.create(pedido=pedido, material=self.material_a,
                                     cantidad_solicitada=14)
        DetallePedido.objects.create(pedido=pedido, material=self.material_b,
                                     cantidad_solicitada=Decimal("2.5"))
        # Un pedido ya aprobado no cuenta.
        viejo = Pedido.objects.create(
            camion=self.camion, usuario=self.capataz, estado="aprobado")
        DetallePedido.objects.create(pedido=viejo, material=self.material_a,
                                     cantidad_solicitada=100)
        self.auth(self.encargado)
        resp = self.client.get(
            f"/api/ingresos-tecsur/faltantes/?almacen={self.almacen.pk}")
        self.assertEqual(resp.status_code, 200, resp.content)
        falta = {f["matricula"]: f["falta"] for f in resp.json()}
        self.assertEqual(falta, {"MAT-A": 4.0, "MAT-B": 2.5})

    def test_sin_faltantes_la_lista_viene_vacia(self):
        self.auth(self.encargado)
        resp = self.client.get(
            f"/api/ingresos-tecsur/faltantes/?almacen={self.almacen.pk}")
        self.assertEqual(resp.json(), [])


class IngresoDesdeExcelTests(BaseAPITestCase):
    """El Excel se lee para revisarlo: no mueve stock hasta registrar."""

    def excel(self, filas):
        import base64
        import io

        import openpyxl
        libro = openpyxl.Workbook()
        for fila in filas:
            libro.active.append(fila)
        salida = io.BytesIO()
        libro.save(salida)
        return base64.b64encode(salida.getvalue()).decode()

    def leer(self, filas=None, archivo=None):
        self.auth(self.encargado)
        return self.client.post("/api/ingresos-tecsur/leer_excel/",
                                {"archivo": archivo or self.excel(filas)},
                                format="json")

    def test_lee_por_titulos_suma_repetidas_y_no_mueve_stock(self):
        resp = self.leer([
            ["INGRESO DE MATERIALES"],
            ["Descripción", "Matrícula", "Cantidad"],
            ["Cable A", "MAT-A", 2.5],
            ["Cable B", "MAT-B", 3],
            ["Cable A otra vez", "MAT-A", "1,5"],
        ])
        self.assertEqual(resp.status_code, 200, resp.content)
        lineas = {l["matricula"]: l["cantidad"] for l in resp.json()["lineas"]}
        self.assertEqual(lineas, {"MAT-A": 4.0, "MAT-B": 3.0})
        self.assertEqual(self.stock_almacen(self.material_a), Decimal("10"))

    def test_sin_titulos_toma_la_a_y_la_b(self):
        from ..models import Material
        Material.objects.create(matricula="6913292", descripcion="REFUERZO",
                                precio="1.00")
        # Excel guarda la matrícula como número: 6913292.0
        resp = self.leer([[6913292.0, 500], ["MAT-B", 2]])
        lineas = {l["matricula"]: l["cantidad"] for l in resp.json()["lineas"]}
        self.assertEqual(lineas, {"6913292": 500.0, "MAT-B": 2.0})

    def test_avisa_lo_que_no_esta_y_lo_que_no_tiene_cantidad(self):
        resp = self.leer([
            ["Matrícula", "Cantidad"],
            ["MAT-A", 5],
            ["NO-EXISTE", 3],
            ["MAT-B", "mucho"],
            ["MAT-B", 0],
            [None, None],
        ])
        datos = resp.json()
        self.assertEqual([l["matricula"] for l in datos["lineas"]], ["MAT-A"])
        self.assertEqual(datos["no_encontrados"],
                         [{"fila": 3, "matricula": "NO-EXISTE"}])
        self.assertEqual([f["fila"] for f in datos["sin_cantidad"]], [4, 5])

    def test_un_archivo_que_no_es_excel_da_un_mensaje_claro(self):
        import base64
        resp = self.leer(archivo=base64.b64encode(b"hola").decode())
        self.assertEqual(resp.status_code, 400)
        self.assertIn(".xlsx", resp.json()["detail"])

    def test_un_capataz_no_lee_excel_de_ingreso(self):
        self.auth(self.capataz)
        resp = self.client.post("/api/ingresos-tecsur/leer_excel/",
                                {"archivo": self.excel([["MAT-A", 1]])},
                                format="json")
        self.assertEqual(resp.status_code, 403)

    def test_la_plantilla_se_lee_a_si_misma(self):
        import base64
        self.auth(self.encargado)
        resp = self.client.get("/api/ingresos-tecsur/plantilla_excel/")
        self.assertEqual(resp.status_code, 200)
        leida = self.leer(archivo=base64.b64encode(resp.content).decode()).json()
        # La fila de ejemplo es el fleje, que en esta base no existe.
        self.assertEqual(leida["no_encontrados"][0]["matricula"], "1014213")
