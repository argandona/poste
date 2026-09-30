"""
El formato de recupero TS-REC-FR-001.

En "Departamento" va el área de Tecsur que recibe el recupero, Mantenimiento,
y no el distrito de la SST.
"""
from datetime import date
from unittest import mock

from ..models import SST, SSTSuministro, Suministro
from .base import BaseAPITestCase


class FormatoRecuperoTests(BaseAPITestCase):

    def test_el_departamento_es_mantenimiento(self):
        sst = SST.objects.create(codigo="SST-0001", sst="1234567",
                                 empresa=self.empresa, distrito="SURCO",
                                 fecha_ejecucion=date.today())
        suministro = Suministro.objects.create(numero_suministro="7777777")
        SSTSuministro.objects.create(sst=sst, suministro=suministro,
                                     asignado_a=self.capataz)
        self.auth(self.encargado)
        with mock.patch("core.pdf_recupero.generar_pdf_recupero",
                        return_value=b"%PDF") as generar:
            resp = self.client.get("/api/recuperos/formato_pdf/?sst=SST-0001")
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        datos = generar.call_args.args[0]
        self.assertEqual(datos["departamento"], "Mantenimiento")
