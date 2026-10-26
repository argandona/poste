"""El plano proyectado de las obras de varios días: subirlo, ver lo que falta,
marcar lo hecho en el parte del día y bajar el replanteo."""
from .comun import *  # noqa: F401,F403
from ..models import AvanceTrabajo, PlanoProyecto, TrabajoPlano

__all__ = ['PlanoProyectoViewSet', 'avance_del_plano']


def _cuanto(trabajo):
    """Lo hecho de un trabajo, sumando los partes de todos."""
    return sum((a.cantidad for a in trabajo.avances.all()), Decimal('0'))


def _fraccion(trabajo, hecho):
    """Qué tanto de un trabajo está hecho, de 0 a 1. Sin metros en el
    proyecto, basta con haberlo empezado."""
    if trabajo.proyectado:
        return min(Decimal('1'), hecho / trabajo.proyectado)
    return Decimal('1') if hecho > 0 else Decimal('0')


def avance_del_plano(plano, terminada=False):
    """El avance de la obra en %, para el cajetín. Terminada es 100."""
    if terminada:
        return 100
    activos = [t for t in plano.trabajos.all() if t.activo]
    if not activos:
        return 0
    suma = sum(_fraccion(t, _cuanto(t)) for t in activos)
    return int(round(suma * 100 / len(activos)))


class PlanoProyectoViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def _actor(self, request):
        return Usuario.objects.filter(pk=request.user.id_usuario).first()

    def _sst(self, request, codigo):
        from ..partes import es_de_varios_dias

        codigo = (codigo or '').strip()
        if not codigo:
            raise ErrorNegocio('Se requiere el código de la SST.')
        sst = (qs_empresa(SST.objects.select_related('actividad'), request)
               .filter(models.Q(codigo=codigo) | models.Q(sst=codigo))
               .first())
        if sst is None:
            raise ErrorNegocio(f'No existe la SST {codigo}.')
        if not es_de_varios_dias(sst):
            raise ErrorNegocio(f'La SST {codigo} no es una obra de varios días.')
        return sst

    def _plano(self, sst):
        return (PlanoProyecto.objects
                .filter(empresa_id=sst.empresa_id,
                        sst_codigo=sst.codigo or sst.sst)
                .prefetch_related('trabajos__avances__usuario')
                .first())

    @action(detail=False, methods=['get'])
    def de_sst(self, request):
        """GET /api/planos-proyecto/de_sst/?sst=<codigo>

        El plano de la obra: su dibujo y sus trabajos, con lo que cada
        capataz hizo de cada uno y el avance. Sin plano todavía, dice si
        quien pregunta puede subirlo."""
        sst = self._sst(request, request.query_params.get('sst'))
        actor = self._actor(request)
        plano = self._plano(sst)
        puede_subir = bool(actor and actor.puede_terminar_obra())
        if plano is None:
            return Response({'existe': False, 'puede_subir': puede_subir})
        trabajos = []
        for t in plano.trabajos.all():
            hecho = _cuanto(t)
            trabajos.append({
                'id': t.pk, 'texto': t.texto, 'tipo': t.tipo,
                'unidad': t.unidad, 'cantidad': t.cantidad,
                'proyectado': str(t.proyectado) if t.proyectado is not None else None,
                'x': t.x, 'y': t.y, 'activo': t.activo,
                'hecho': str(hecho), 'avance': float(_fraccion(t, hecho)),
                'avances': [{'fecha': str(a.fecha_parte), 'usuario': a.usuario_id,
                             'usuario_nombre': a.usuario.nombre,
                             'cantidad': str(a.cantidad)}
                            for a in t.avances.all()],
            })
        return Response({
            'existe': True,
            'puede_subir': puede_subir,
            'nombre_archivo': plano.nombre_archivo,
            'subido_por': plano.subido_por.nombre,
            'fecha': plano.fecha,
            'avance': avance_del_plano(
                plano, terminada=sst.obra_terminada_el is not None),
            'dibujo': plano.dibujo,
            'trabajos': trabajos,
        })

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser])
    def subir(self, request):
        """POST /api/planos-proyecto/subir/  (multipart: sst_codigo, archivo)

        El coordinador sube el plano proyectado en DXF. Si la obra ya tiene
        avances marcados en el plano, no se reemplaza: se perderían."""
        from .. import plano_aparte
        from ..plano_proyecto import comprimir, revisar_archivo

        actor = self._actor(request)
        if not (actor and actor.puede_terminar_obra()):
            raise PermissionDenied('Solo el coordinador sube el plano proyectado.')
        sst = self._sst(request, request.data.get('sst_codigo'))
        archivo = request.FILES.get('archivo')
        if archivo is None:
            raise ErrorNegocio('Falta el archivo del plano.')
        contenido = archivo.read()
        revisar_archivo(contenido)
        anterior = self._plano(sst)
        if anterior and AvanceTrabajo.objects.filter(
                trabajo__plano=anterior).exists():
            raise ErrorNegocio('La obra ya tiene avances marcados en su plano: '
                               'no se puede reemplazar.')
        # Lo pesado va en otro proceso, fuera de la transacción.
        datos = plano_aparte.analizar(contenido)
        with transaction.atomic():
            if anterior:
                anterior.delete()
            plano = PlanoProyecto.objects.create(
                empresa_id=sst.empresa_id, sst_codigo=sst.codigo or sst.sst,
                nombre_archivo=(archivo.name or 'plano.dxf')[:200],
                archivo=comprimir(contenido), dibujo=datos['dibujo'],
                subido_por=actor)
            TrabajoPlano.objects.bulk_create([
                TrabajoPlano(plano=plano, handle=t['handle'],
                             texto=t['texto'], tipo=t['tipo'],
                             unidad=t['unidad'], proyectado=t['proyectado'],
                             cantidad=t['cantidad'], x=t['x'], y=t['y'])
                for t in datos['trabajos']
            ])
        return Response({'status': 'ok', 'trabajos': len(datos['trabajos'])},
                        status=201)

    @action(detail=False, methods=['post'])
    def trabajos(self, request):
        """POST /api/planos-proyecto/trabajos/  { sst_codigo, activos: [ids] }

        El coordinador deja como obra solo los trabajos de [activos]; los
        demás (el mismo cable repetido en un corte, por ejemplo) no cuentan
        para el avance ni se marcan."""
        actor = self._actor(request)
        if not (actor and actor.puede_terminar_obra()):
            raise PermissionDenied('Solo el coordinador revisa los trabajos.')
        sst = self._sst(request, request.data.get('sst_codigo'))
        plano = self._plano(sst)
        if plano is None:
            raise ErrorNegocio('La obra no tiene plano proyectado.')
        activos = {int(i) for i in request.data.get('activos') or []}
        for t in plano.trabajos.all():
            if (t.pk in activos) != t.activo:
                if t.pk not in activos and t.avances.exists():
                    raise ErrorNegocio(f'«{t.texto}» ya tiene avance: no se '
                                       'puede descartar.')
                t.activo = t.pk in activos
                t.save(update_fields=['activo'])
        return Response({'status': 'ok', 'activos': len(activos)})

    @action(detail=False, methods=['post'])
    def avance(self, request):
        """POST /api/planos-proyecto/avance/
        { sst_codigo, fecha_parte, usuario?, items: [{trabajo, cantidad}] }

        Lo que el capataz hizo del plano en el parte de ese día. Reemplaza lo
        que ese capataz había marcado ese día, como el resto del parte."""
        from ..partes import fecha_del_parte, revisar_parte

        actor = self._actor(request)
        sst = self._sst(request, request.data.get('sst_codigo'))
        plano = self._plano(sst)
        if plano is None:
            raise ErrorNegocio('La obra no tiene plano proyectado.')
        fecha = fecha_del_parte(request.data.get('fecha_parte'))
        usuario = actor
        if request.data.get('usuario'):
            usuario = Usuario.objects.filter(pk=request.data['usuario']).first()
            if usuario is None:
                raise ErrorNegocio('Usuario no encontrado.')
        revisar_parte(actor, sst, usuario)
        de_la_obra = {t.pk: t for t in plano.trabajos.all() if t.activo}
        nuevos = []
        for item in request.data.get('items') or []:
            trabajo = de_la_obra.get(int(item.get('trabajo') or 0))
            if trabajo is None:
                raise ErrorNegocio('Ese trabajo no es de esta obra.')
            try:
                cantidad = Decimal(str(item.get('cantidad') or 0))
            except Exception:
                raise ErrorNegocio('La cantidad no es válida.')
            if cantidad < 0:
                raise ErrorNegocio('La cantidad no puede ser negativa.')
            if cantidad > 0:
                nuevos.append(AvanceTrabajo(trabajo=trabajo, usuario=usuario,
                                            fecha_parte=fecha,
                                            cantidad=cantidad))
        with transaction.atomic():
            AvanceTrabajo.objects.filter(trabajo__plano=plano, usuario=usuario,
                                         fecha_parte=fecha).delete()
            AvanceTrabajo.objects.bulk_create(nuevos)
        return Response({'status': 'ok', 'items': len(nuevos)})

    @action(detail=False, methods=['get'])
    def replanteo(self, request):
        """GET /api/planos-proyecto/replanteo/?sst=<codigo>

        El DXF replanteado: el proyectado con lo hecho pasado a instalado,
        los metros reales y el avance en el cajetín. Se termina en AutoCAD."""
        from django.http import HttpResponse

        from .. import plano_aparte
        from ..plano_proyecto import descomprimir

        actor = self._actor(request)
        if not (actor and actor.puede_corregir_partes()):
            raise PermissionDenied('El replanteo lo bajan el coordinador y el '
                                   'liquidador.')
        sst = self._sst(request, request.query_params.get('sst'))
        plano = self._plano(sst)
        if plano is None:
            raise ErrorNegocio('La obra no tiene plano proyectado.')
        hechos = {}
        for t in plano.trabajos.all():
            hecho = _cuanto(t)
            if not t.activo or hecho <= 0:
                continue
            metros = hecho if t.unidad == 'M' and t.proyectado is not None else None
            hechos[t.handle] = (metros, t.cantidad)
        contenido = plano_aparte.replanteo(
            descomprimir(plano.archivo), hechos,
            avance_del_plano(plano, terminada=sst.obra_terminada_el is not None))
        codigo = sst.codigo or sst.sst
        resp = HttpResponse(contenido, content_type='application/dxf')
        resp['Content-Disposition'] = f'attachment; filename="replanteo_{codigo}.dxf"'
        return resp
