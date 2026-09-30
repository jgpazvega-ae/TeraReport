# -*- coding: utf-8 -*-
"""Repara JPEG que python-docx 0.8.11 rechaza, sin recodificar nada.

Hallazgo de diagnóstico (ver tools/probe_jpeg_fix.py): python-docx solo
reconoce un JPEG si el primer marcador tras el SOI es APP0/JFIF (FFE0) o
APP1/EXIF (FFE1). Muchos teléfonos y cámaras escriben el DQT (FFDB) de
inmediato — 5 de 6 fotos de prueba tomadas de Windows caían en ese caso — y
esos archivos revientan la generación con UnrecognizedImageError justo cuando
el usuario intenta agregar las fotos del recorrido.

La reparación inserta un segmento JFIF APP0 mínimo (18 bytes) después del SOI.
Los datos de imagen no se tocan: es reversible y no cambia lo que se ve.
"""

import os
import tempfile

SOI = b'\xff\xd8'
_ACCEPTED_MARKERS = (b'\xff\xe0', b'\xff\xe1')

# APP0 JFIF mínimo: marcador, longitud(16), "JFIF\0", versión 1.1, sin
# unidades de densidad, densidad 1x1, sin miniatura incrustada.
_JFIF_APP0 = (b'\xff\xe0\x00\x10JFIF\x00'
             b'\x01\x01\x00\x00\x01\x00\x01\x00\x00')


def is_jpeg(blob):
    return blob[:2] == SOI


def needs_fix(blob):
    """True si es un JPEG cuyo primer marcador no es APP0 ni APP1."""
    return is_jpeg(blob) and blob[2:4] not in _ACCEPTED_MARKERS


def repair_bytes(blob):
    """Devuelve los bytes del JPEG con el segmento JFIF insertado."""
    return blob[:2] + _JFIF_APP0 + blob[2:]


def ensure_insertable(path, workdir=None):
    """Devuelve una ruta segura para `add_picture`.

    Si el archivo no necesita reparación, devuelve `path` tal cual. Si la
    necesita, escribe una copia reparada en un archivo temporal y devuelve esa
    ruta junto con un indicador de que hay que borrarla después.

    Devuelve (ruta_a_usar, es_temporal).
    """
    with open(path, 'rb') as fh:
        blob = fh.read()
    if not needs_fix(blob):
        return path, False

    folder = workdir or tempfile.gettempdir()
    if not os.path.isdir(folder):
        os.makedirs(folder)
    fd, tmp_path = tempfile.mkstemp(suffix='.jpg', prefix='p2r_jpg_', dir=folder)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(repair_bytes(blob))
    return tmp_path, True
