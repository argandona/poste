"""Avisos al celular cuando el coordinador asigna o quita postes de una SST.

Al capataz o encargado le llega la SST, cuántos postes y la actividad, para
que no tenga que entrar a buscarla. Si se los quitan (desasignar, o pasarlos
a otro), también se le avisa, así no va a un poste que ya no le toca.

Se llama después de grabar: si Firebase no está, no se avisa y nada falla."""

MAX_POSTES_EN_TEXTO = 3


def _postes(numeros):
    numeros = sorted(numeros)
    texto = ', '.join(numeros[:MAX_POSTES_EN_TEXTO])
    if len(numeros) > MAX_POSTES_EN_TEXTO:
        texto += f' y {len(numeros) - MAX_POSTES_EN_TEXTO} más'
    cuantos = f'{len(numeros)} poste' + ('s' if len(numeros) != 1 else '')
    return f'{cuantos}: {texto}'


def _codigo(sst):
    return sst.codigo or sst.sst


def _enviar(usuario, titulo, cuerpo, tipo, sst):
    from .fcm import send_notification
    if not usuario.fcm_token:
        return
    send_notification([usuario.fcm_token], title=titulo, body=cuerpo,
                      data={'tipo': tipo, 'sst_id': str(sst.pk)})


def avisar_asignacion(sst, usuario, numeros, ya_la_tenia=False):
    """Postes nuevos para `usuario` en la SST. Sin postes nuevos, no avisa."""
    if not numeros:
        return
    actividad = f' · {sst.actividad.nombre}' if sst.actividad_id else ''
    titulo = 'Más postes en tu SST' if ya_la_tenia else 'Nueva SST asignada'
    _enviar(usuario, titulo,
            f'SST {_codigo(sst)}{actividad} · {_postes(numeros)}',
            'sst_asignada', sst)


def avisar_retiro(sst, usuario, numeros, sigue_en_la_sst=False):
    """Le quitaron postes a `usuario`: los desasignaron o pasaron a otro."""
    if not numeros:
        return
    if sigue_en_la_sst:
        titulo = 'Te quitaron postes de una SST'
        cola = 'Los demás postes siguen contigo.'
    else:
        titulo = 'Te quitaron una SST'
        cola = 'Ya no te toca.'
    _enviar(usuario, titulo, f'SST {_codigo(sst)} · {_postes(numeros)}. {cola}',
            'sst_retirada', sst)
