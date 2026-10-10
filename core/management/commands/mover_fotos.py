"""Pasa a Cloudinary las fotos que quedaron guardadas en la base (pedidos de
EPP de antes de core/fotos.py) y vacía la columna vieja. Es idempotente: solo
toca las que aún no tienen archivo. Sin CLOUDINARY_URL no hace nada, para no
mandar las fotos de producción a un disco que Render borra."""
import os

from django.core.management.base import BaseCommand

from core.fotos import guardar_foto
from core.models import PedidoEPP


class Command(BaseCommand):
    help = 'Mueve las fotos guardadas en la base a Cloudinary.'

    def add_arguments(self, parser):
        parser.add_argument('--local', action='store_true',
                            help='Moverlas aunque no haya CLOUDINARY_URL.')

    def handle(self, *args, **opciones):
        if not os.getenv('CLOUDINARY_URL') and not opciones['local']:
            self.stdout.write('Sin CLOUDINARY_URL: no se mueve ninguna foto.')
            return
        pendientes = (PedidoEPP.objects.filter(foto__isnull=False, foto_archivo='')
                      .values_list('pk', flat=True))
        movidas = 0
        for pk in list(pendientes):
            pedido = PedidoEPP.objects.get(pk=pk)
            if pedido.foto:
                pedido.foto_archivo = guardar_foto(bytes(pedido.foto), 'epp')
            pedido.foto = None
            pedido.save(update_fields=['foto', 'foto_archivo'])
            movidas += 1
        self.stdout.write(f'Fotos de EPP movidas: {movidas}.')
