"""Las fotos de la app (EPP malogrado, tablero del camión...) viven fuera de la
base de datos: en Cloudinary cuando está CLOUDINARY_URL (Render), y en
MEDIA_ROOT/fotos en local y en las pruebas. La base solo guarda el nombre que
devuelve el almacenamiento."""
import base64
import binascii
import uuid
from urllib.request import urlopen

from django.core.files.base import ContentFile
from django.core.files.storage import Storage, storages
from django.http import HttpResponse, HttpResponseRedirect

from .errores import ErrorNegocio

# Ya llegan comprimidas del celular. Más que esto es un error.
FOTO_MAXIMA = 3 * 1024 * 1024


class CloudinaryStorage(Storage):
    """Sube a Cloudinary con el SDK oficial, que lee CLOUDINARY_URL del
    entorno. El nombre guardado es el public_id."""

    def _save(self, name, content):
        import cloudinary.uploader
        public_id = name.rsplit('.', 1)[0]
        r = cloudinary.uploader.upload(
            content.read(), public_id=public_id, resource_type='image',
            overwrite=False, unique_filename=False)
        return r['public_id']

    def _open(self, name, mode='rb'):
        with urlopen(self.url(name)) as resp:
            return ContentFile(resp.read(), name=name)

    def url(self, name):
        import cloudinary
        return cloudinary.CloudinaryImage(name).build_url(secure=True)

    def exists(self, name):
        # Los nombres llevan un uuid: nunca chocan.
        return False

    def delete(self, name):
        import cloudinary.uploader
        cloudinary.uploader.destroy(name, resource_type='image')


def leer_base64(valor):
    """La foto que manda la app (jpeg en base64) en bytes, o None si no vino."""
    if not valor:
        return None
    try:
        contenido = base64.b64decode(valor, validate=True)
    except (binascii.Error, ValueError):
        raise ErrorNegocio('La foto no se pudo leer.')
    if len(contenido) > FOTO_MAXIMA:
        raise ErrorNegocio('La foto es muy pesada.')
    return contenido


def guardar_foto(contenido, carpeta):
    """Guarda los bytes de un jpeg y devuelve el nombre para la base."""
    return storages['fotos'].save(
        f'tecsur/{carpeta}/{uuid.uuid4().hex}.jpg', ContentFile(contenido))


def url_foto(nombre):
    """La dirección pública de la foto, o '' si no hay."""
    if not nombre:
        return ''
    return storages['fotos'].url(nombre)


def responder_foto(nombre):
    """Para los GET .../foto/: en Cloudinary redirige (el cliente sigue el
    redirect); en local devuelve los bytes."""
    url = url_foto(nombre)
    if url.startswith('http'):
        return HttpResponseRedirect(url)
    with storages['fotos'].open(nombre) as f:
        return HttpResponse(f.read(), content_type='image/jpeg')
