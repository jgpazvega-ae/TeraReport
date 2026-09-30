# -*- coding: utf-8 -*-
"""Carga y consulta del perfil de lectura (data/perfil_plaud.json).

El perfil declara, en JSON editable sin tocar código, cómo reconocer
estaciones, secciones y campos en lo que emite Plaud. Existe porque el usuario
está ajustando su prompt de Plaud activamente: cuando cambie el nombre de una
sección o agregue una nueva, el ajuste va en este archivo, no en el parser.
"""

import io
import json

from . import textutil


class SectionSpec(object):
    __slots__ = ('canonico', 'alias', 'campos', '_lookup')

    def __init__(self, canonico, alias, campos):
        self.canonico = canonico
        self.alias = alias
        self.campos = campos
        self._lookup = set(textutil.key(a).rstrip(':') for a in [canonico] + alias)

    def matches(self, title):
        return textutil.key(title).rstrip(':') in self._lookup


class Profile(object):
    """Perfil de lectura, con búsquedas ya indexadas."""

    def __init__(self, data):
        self.data = data
        self.nombre = data.get('nombre', '')

        self.station_prefixes = list(data.get('estacion', {}).get('prefijos', []))
        self.robots_markers = list(data.get('listado_robots', {})
                                   .get('encabezado_contiene', []))
        # Bloques informativos que Plaud puede agregar fuera de las estaciones
        # (p.ej. "Notas de Descarte / Pendientes de Levantamiento"): no son ni
        # una estación ni un listado de robots, así que necesitan su propio
        # marcador para no colarse como una estación falsa.
        # Ojo: la clave del perfil es "bloque_notas", NO "notas" — esa ya la usa
        # el perfil para su propia documentación interna (ver clave "notas" al
        # final de perfil_plaud.json, una lista de comentarios de esquema).
        self.notes_markers = list(data.get('bloque_notas', {})
                                  .get('encabezado_contiene', []))

        self.metadata_aliases = {}
        for field, aliases in data.get('metadatos', {}).items():
            self.metadata_aliases[field] = list(aliases)

        self.sections = [
            SectionSpec(s['canonico'], s.get('alias', []), s.get('campos', []))
            for s in data.get('secciones', [])
        ]
        self.canonical_order = [s.canonico for s in self.sections]

        # etiqueta de campo (canónica o alias) -> etiqueta canónica
        self.field_lookup = {}
        for section in self.sections:
            for field in section.campos:
                self.field_lookup[textutil.key(field).rstrip(':')] = field
        for canonical, aliases in data.get('alias_de_campo', {}).items():
            key = textutil.key(canonical).rstrip(':')
            self.field_lookup[key] = canonical
            for alias in aliases:
                self.field_lookup[textutil.key(alias).rstrip(':')] = canonical

    # -- reconocimiento -----------------------------------------------------
    def strip_station_prefix(self, text):
        """Quita el prefijo de estación si el texto empieza con uno conocido."""
        key = textutil.key(text)
        for prefix in self.station_prefixes:
            pkey = textutil.key(prefix)
            if key.startswith(pkey + ':') or key.startswith(pkey + ' '):
                idx = text.lower().find(':')
                return text[idx + 1:].strip() if idx != -1 else text
        return None

    def is_robots_heading(self, text):
        key = textutil.key(text)
        return any(textutil.key(m) in key for m in self.robots_markers)

    def is_notes_heading(self, text):
        key = textutil.key(text)
        return any(textutil.key(m) in key for m in self.notes_markers)

    def find_section(self, title):
        """Sección canónica que corresponde a `title`, o None si no matchea."""
        for section in self.sections:
            if section.matches(title):
                return section.canonico
        # Ni exacto ni alias: intenta un parecido difuso antes de rendirse,
        # por si el prompt de Plaud cambió ligeramente el nombre.
        best = textutil.best_match(title, self.canonical_order)
        return best

    def canonicalize_field(self, label):
        """Etiqueta canónica de un campo, o la etiqueta tal cual si no se conoce."""
        key = textutil.key(label).rstrip(':')
        return self.field_lookup.get(key, label)

    def section_rank(self, canonical_title):
        """Posición en el orden canónico, o un número alto si no se reconoce."""
        try:
            return self.canonical_order.index(canonical_title)
        except ValueError:
            return len(self.canonical_order) + 1

    def metadata_field_for(self, text):
        """Si `text` es 'Etiqueta: valor' y la etiqueta es un alias de metadato,
        devuelve (nombre_del_campo, valor); si no, devuelve (None, None).
        """
        idx = text.find(':')
        if idx <= 0:
            return None, None
        label, value = text[:idx].strip(), text[idx + 1:].strip()
        label_key = textutil.key(label)
        for field, aliases in self.metadata_aliases.items():
            if any(textutil.key(a) == label_key for a in aliases):
                return field, value
        return None, None


def load(path):
    with io.open(path, encoding='utf-8') as fh:
        return Profile(json.load(fh))


def default_profile():
    """Perfil embebido de emergencia, por si data/perfil_plaud.json no está.

    Cubre lo mínimo indispensable para no dejar la app sin poder leer nada.
    """
    return Profile({
        'nombre': 'Perfil mínimo embebido',
        'estacion': {'prefijos': ['Nombre de la estación']},
        'listado_robots': {'encabezado_contiene': ['Listado de Robots']},
        'metadatos': {
            'cliente': ['Nombre del Cliente'],
            'fecha_visita': ['Fecha de la Visita'],
            'ubicacion': ['Ubicación'],
        },
        'secciones': [],
        'alias_de_campo': {},
    })
