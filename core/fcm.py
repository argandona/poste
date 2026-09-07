import os
import json
import base64
import logging

logger = logging.getLogger(__name__)
_app = None


def _init():
    global _app
    if _app is not None:
        return True
    try:
        import firebase_admin
        from firebase_admin import credentials

        cred_path = os.environ.get('FIREBASE_CREDENTIALS_PATH')
        cred_b64  = os.environ.get('FIREBASE_CREDENTIALS_B64')

        if cred_path:
            cred = credentials.Certificate(cred_path)
        elif cred_b64:
            cred_dict = json.loads(base64.b64decode(cred_b64))
            cred = credentials.Certificate(cred_dict)
        else:
            return False

        _app = firebase_admin.initialize_app(cred)
        return True
    except Exception as e:
        logger.warning(f'Firebase init error: {e}')
        return False


def send_notification(tokens, title, body, data=None):
    """Envía notificación FCM. Falla silenciosamente si Firebase no está configurado."""
    if not tokens:
        return
    if not _init():
        return
    try:
        from firebase_admin import messaging
        clean = [t for t in tokens if t]
        if not clean:
            return
        msg = messaging.MulticastMessage(
            tokens=clean,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    channel_id='encossa_alertas',
                    default_vibrate_timings=True,
                    sound='default',
                ),
            ),
        )
        resp = messaging.send_each_for_multicast(msg)
        if resp.failure_count:
            logger.warning(f'FCM: {resp.failure_count} fallidos de {len(clean)}')
    except Exception as e:
        logger.warning(f'FCM send error: {e}')
