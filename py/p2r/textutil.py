# -*- coding: utf-8 -*-
"""Normalización de texto compartida por todo el proyecto.

Las comparaciones de títulos y etiquetas se hacen sin acentos, sin mayúsculas y
sin puntuación de borde. Así "Descripción de la Aplicación:", "DESCRIPCION DE
LA APLICACION" y "Descripcion de la aplicacion" son la misma sección, sin tener
que declarar cada variante como alias.
"""

import re
import unicodedata

_SPACES = re.compile(r'[ \t   ]+')
_EDGE = ' \t .:;,-–—•*#'


def clean(text):
    """Colapsa espacios y recorta. Conserva acentos y mayúsculas."""
    return _SPACES.sub(' ', (text or '')).strip()


def strip_accents(text):
    decomposed = unicodedata.normalize('NFD', text or '')
    return ''.join(c for c in decomposed if unicodedata.category(c) != 'Mn')


def key(text):
    """Clave de comparación: sin acentos, minúsculas, sin puntuación de borde."""
    return strip_accents(clean(text)).lower().strip(_EDGE)


def similar(a, b):
    """Parecido 0..1 entre dos textos ya normalizados con `key`."""
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def best_match(needle, candidates, threshold=0.86):
    """Candidato más parecido a `needle`, o None si ninguno llega al umbral.

    Sirve para reconocer una sección cuyo título cambió un poco al ajustar el
    prompt de Plaud, sin obligar a declarar el alias exacto.
    """
    target = key(needle)
    if not target:
        return None
    best, score = None, threshold
    for candidate in candidates:
        ratio = similar(target, key(candidate))
        if ratio >= score:
            best, score = candidate, ratio
    return best
