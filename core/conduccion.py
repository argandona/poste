"""Formato de Conducción (F03-IA-QHSE-001) en la app.

El chofer lo llena cada día antes de manejar. Va aparte de su IPC: puede
hacer uno, el otro o los dos, en cualquier orden (decisión del usuario,
2026-10-19); si ya hay IPC de hoy, la Conducción queda ligada a él. Responde
los 8 controles y empieza con una SST; durante el día le suma las
demás y cada una queda como una fila firmada (su confirmación desde la app).
Si un control sale No, se avisa al responsable del camión y al coordinador,
y se deja seguir (decisión del usuario, 2026-10-18).

Las SST que se le ofrecen son las del responsable del camión que maneja (el de
su salida abierta, o el último que manejó); también puede escribir otra.
"""
from django.db import models, transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from . import conduccion_formato as F
from .camiones import _avisar, _camiones_de, responsable_de, ssts_del_responsable
from .errores import ErrorNegocio
from .models import (
    IPC, Conduccion, ConduccionSST, JornadaCamion, Usuario,
)
from .serializers import SSTSerializer


def _actor(request):
    return (Usuario.objects.select_related('rol', 'empresa')
            .filter(pk=request.user.id_usuario).first())


def camion_del_chofer(chofer, camion_id=None):
    """El camión que maneja: el pedido (de su empresa), el de su salida
    abierta o el último que manejó. None si no hay ninguno."""
    if camion_id:
        camion = _camiones_de(chofer).filter(pk=camion_id).first()
        if camion is None:
            raise ErrorNegocio('Elige un camión de tu empresa.')
        return camion
    salidas = JornadaCamion.objects.filter(chofer=chofer).select_related('camion')
    elegida = (salidas.filter(km_cierre__isnull=True).first()
               or salidas.order_by('-hora_salida').first())
    return elegida.camion if elegida else None


def datos_conduccion(c):
    en_no = F.controles_en_no(c.controles)
    hoy = timezone.localdate()
    return {
        'id_conduccion': c.pk,
        'fecha': c.fecha,
        'creada': c.creada,
        'es_de_hoy': c.fecha == hoy,
        'chofer': c.chofer_id,
        'chofer_nombre': c.chofer.nombre,
        'cargo': c.cargo,
        'camion': c.camion_id,
        'camion_placa': c.camion.placa if c.camion_id else '',
        'ipc': c.ipc_id,
        'formato': f'{c.formato_codigo} v{c.formato_version}',
        'controles': c.controles,
        'controles_en_no': [f'{i}. {ctrl["control"]}' for i, ctrl in en_no],
        'ssts': [{'id_sst': s.sst_id, 'sst': s.codigo, 'manual': s.sst_id is None,
                  'firmada': s.firmada} for s in c.ssts.all()],
    }


def avisar_controles_en_no(c, en_no):
    """Al responsable del camión, a los coordinadores de la empresa y al
    SuperAdmin: el chofer marcó No en algún control y sigue."""
    if not en_no:
        return
    from .fcm import send_notification
    placa = f' ({c.camion.placa})' if c.camion_id else ''
    titulo = 'Conducción con controles en No'
    cuerpo = (f'{c.chofer.nombre}{placa} marcó No en: '
              + '; '.join(f'{i}. {ctrl["control"]}' for i, ctrl in en_no)
              + ' Revisar y tomar medidas.')
    data = {'tipo': 'conduccion_no', 'conduccion_id': str(c.pk)}
    responsable = responsable_de(c.camion, c.fecha) if c.camion_id else None
    if responsable and responsable.fcm_token:
        send_notification([responsable.fcm_token], title=titulo, body=cuerpo, data=data)
    _avisar(c.empresa_id, titulo, cuerpo, data)


class ConduccionViewSet(viewsets.ViewSet):
    """Conducción del chofer: crear la de hoy, sumarle SST, corregir los
    controles y bajar el PDF. El SuperAdmin y el coordinador ven las de su
    empresa."""
    permission_classes = [permissions.IsAuthenticated]

    @staticmethod
    def _con_todo(qs):
        return qs.select_related('chofer', 'camion').prefetch_related('ssts')

    @staticmethod
    def _visibles(actor):
        qs = Conduccion.objects.all()
        if actor.puede_ver_todos_los_ipc():
            if not actor.es_superadmin() and actor.empresa_id:
                qs = qs.filter(empresa_id=actor.empresa_id)
            return qs
        return qs.filter(chofer=actor)

    @staticmethod
    def _del_chofer(request):
        actor = _actor(request)
        if actor is None or not actor.puede_hacer_conduccion():
            raise PermissionDenied('La Conducción la llena el chofer.')
        return actor

    def _mia_de_hoy(self, request, pk):
        actor = self._del_chofer(request)
        c = Conduccion.objects.filter(pk=pk, chofer=actor).first()
        if c is None:
            raise PermissionDenied('Solo el chofer modifica su Conducción.')
        if c.fecha != timezone.localdate():
            raise ErrorNegocio('La Conducción solo sirve el día en que se hizo: '
                               'para hoy llena una nueva.')
        return actor, c

    def _responder(self, c, status=200):
        c = self._con_todo(Conduccion.objects).get(pk=c.pk)
        return Response(datos_conduccion(c), status=status)

    @staticmethod
    def _sumar(c, sst, codigo):
        repetida = models.Q(codigo__iexact=codigo)
        if sst is not None:
            repetida |= models.Q(sst=sst)
        if c.ssts.filter(repetida).exists():
            raise ErrorNegocio(f'La SST {codigo} ya está en tu Conducción de hoy.')
        return ConduccionSST.objects.create(
            conduccion=c, sst=sst, codigo=codigo, orden=c.ssts.count())

    @staticmethod
    def _sst_de(actor, datos):
        from .views.ipc import IPCViewSet
        return IPCViewSet._sst_de(actor, datos)

    # ── Endpoints ───────────────────────────────────────────────────────────
    @action(detail=False, methods=['get'])
    def formato(self, request):
        """GET /api/conducciones/formato/ — los 8 controles del papel."""
        return Response(F.formato())

    def list(self, request):
        """GET /api/conducciones/?fecha=AAAA-MM-DD — las del chofer; el
        SuperAdmin y el coordinador, las de su empresa. Las últimas 200."""
        qs = self._visibles(_actor(request))
        if request.query_params.get('fecha'):
            qs = qs.filter(fecha=request.query_params['fecha'])
        return Response([datos_conduccion(c) for c in self._con_todo(qs)[:200]])

    def retrieve(self, request, pk=None):
        c = self._con_todo(self._visibles(_actor(request))).filter(pk=pk).first()
        if c is None:
            return Response({'detail': 'No existe.'}, status=404)
        return Response(datos_conduccion(c))

    @action(detail=False, methods=['get'])
    def hoy(self, request):
        """GET /api/conducciones/hoy/ — la Conducción de hoy del chofer (o
        null) y su IPC de hoy (o null)."""
        actor = self._del_chofer(request)
        hoy = timezone.localdate()
        c = self._con_todo(Conduccion.objects.filter(chofer=actor, fecha=hoy)).first()
        ipc = (IPC.objects.filter(responsable=actor, fecha=hoy)
               .order_by('-id_ipc').values_list('pk', flat=True).first())
        return Response({'conduccion': datos_conduccion(c) if c else None,
                         'ipc_de_hoy': ipc})

    @action(detail=False, methods=['get'])
    def ssts(self, request):
        """GET /api/conducciones/ssts/?camion= — el camión que maneja y las
        SST de su responsable, para el IPC y la Conducción del chofer."""
        actor = self._del_chofer(request)
        camion = camion_del_chofer(actor, request.query_params.get('camion'))
        hoy = timezone.localdate()
        r = responsable_de(camion, hoy) if camion else None
        return Response({
            'camion': camion.pk if camion else None,
            'camion_placa': camion.placa if camion else '',
            'responsable_nombre': r.nombre if r else '',
            'ssts': SSTSerializer(ssts_del_responsable(r, hoy), many=True).data,
        })

    def create(self, request):
        """POST /api/conducciones/ {controles, camion?, sst | codigo}

        La de hoy, una por día; no pide IPC, pero si ya lo hizo la liga a
        él. Si algún control sale No, avisa y la deja igual."""
        actor = self._del_chofer(request)
        hoy = timezone.localdate()
        ipc = IPC.objects.filter(responsable=actor, fecha=hoy).order_by('-id_ipc').first()
        if Conduccion.objects.filter(chofer=actor, fecha=hoy).exists():
            raise ErrorNegocio('Ya tienes tu Conducción de hoy: súmale la SST.')
        controles = F.limpiar_controles(request.data.get('controles'))
        camion = camion_del_chofer(actor, request.data.get('camion'))
        sst, codigo = self._sst_de(actor, request.data)
        with transaction.atomic():
            c = Conduccion.objects.create(
                empresa_id=actor.empresa_id, chofer=actor, camion=camion, ipc=ipc,
                fecha=hoy, cargo=actor.rol.descripcion if actor.rol_id else '',
                formato_codigo=F.CODIGO, formato_version=F.VERSION,
                controles=controles)
            self._sumar(c, sst, codigo)
        c = self._con_todo(Conduccion.objects).get(pk=c.pk)
        avisar_controles_en_no(c, F.controles_en_no(controles))
        return Response(datos_conduccion(c), status=201)

    @action(detail=True, methods=['post'])
    def agregar_sst(self, request, pk=None):
        """POST /api/conducciones/{id}/agregar_sst/ {sst | codigo} — la
        siguiente SST del día, con su firma."""
        actor, c = self._mia_de_hoy(request, pk)
        sst, codigo = self._sst_de(actor, request.data)
        self._sumar(c, sst, codigo)
        return self._responder(c)

    @action(detail=True, methods=['post'])
    def controles(self, request, pk=None):
        """POST /api/conducciones/{id}/controles/ {controles} — corregir lo
        respondido hoy (por ejemplo, ya se aseguró la carga). Si aparece un No
        que antes no estaba, avisa."""
        actor, c = self._mia_de_hoy(request, pk)
        antes = {i for i, _ in F.controles_en_no(c.controles)}
        c.controles = F.limpiar_controles(request.data.get('controles'))
        c.save(update_fields=['controles'])
        nuevos = [(i, ctrl) for i, ctrl in F.controles_en_no(c.controles) if i not in antes]
        c = self._con_todo(Conduccion.objects).get(pk=c.pk)
        avisar_controles_en_no(c, nuevos)
        return Response(datos_conduccion(c))

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        """GET /api/conducciones/{id}/pdf/ — el formato F03-IA-QHSE-001 lleno."""
        from .conduccion_pdf import generar_pdf_conduccion
        c = self._con_todo(self._visibles(_actor(request))).filter(pk=pk).first()
        if c is None:
            return Response({'detail': 'No existe.'}, status=404)
        resp = HttpResponse(generar_pdf_conduccion(c), content_type='application/pdf')
        resp['Content-Disposition'] = (
            f'attachment; filename="Conduccion_{c.fecha:%Y%m%d}_{c.pk}.pdf"')
        return resp
