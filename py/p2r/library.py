# -*- coding: utf-8 -*-
"""Biblioteca de fragmentos de criterio de experto.

Este es el mecanismo que cierra la brecha del 8.3% medida entre v1 y un
reporte real: cosas como "Model de Robot AMR recomendado: MiR MC250" o
"verificar con layout tamaño de los pasillos" no salen del audio de Plaud,
salen del criterio del experto, y hoy se vuelven a teclear en cada reporte.

Cada fragmento vive en data/biblioteca.json y tiene:
  - a qué sección canónica pertenece (para sugerirlo en el lugar correcto)
  - reglas de activación: palabras que, si aparecen en el texto de la
    estación, hacen que el fragmento se sugiera (p.ej. "AMR" o "MiR" activan
    el fragmento del modelo de AMR recomendado)
  - cuántas veces se ha usado (para ordenar las sugerencias por relevancia)

tools/extraer_conocimiento.py siembra la biblioteca la primera vez, leyendo
reportes ya entregados. Después, cada vez que el usuario agrega un texto nuevo
y contesta "guardar en la biblioteca" en la interfaz, el fragmento entra aquí
para el siguiente reporte.
"""

import io
import json
import os
import re

from . import textutil
from .model import ORIGIN_LIBRARY, Bullet, Section, make_uid

_WORD = re.compile(r'[a-záéíóúñ0-9]+', re.IGNORECASE)


class Fragment(object):
    """Un fragmento reutilizable de criterio de experto."""

    __slots__ = ('id', 'seccion_destino', 'etiqueta', 'texto', 'activadores',
                 'usos', 'origen', 'despues_de')

    def __init__(self, id='', seccion_destino='', etiqueta='', texto='',
                activadores=None, usos=0, origen='biblioteca', despues_de=''):
        self.id = id
        self.seccion_destino = seccion_destino
        self.etiqueta = etiqueta
        self.texto = texto
        self.activadores = activadores if activadores is not None else []
        self.usos = usos
        self.origen = origen
        # Etiqueta de la viñeta tras la que debe insertarse (p.ej. "Modelo de
        # Robot Recomendado"), para que "Modelo de Robot AMR Recomendado" caiga
        # justo a su lado, como en el reporte real, y no al final de la sección.
        self.despues_de = despues_de

    @property
    def full_text(self):
        if self.etiqueta and self.texto:
            return '%s %s' % (self.etiqueta, self.texto)
        return self.etiqueta or self.texto

    def matches(self, station_text):
        """True si algún activador aparece en el texto de la estación."""
        if not self.activadores:
            return False
        haystack = textutil.key(station_text)
        return any(textutil.key(a) in haystack for a in self.activadores)

    def to_dict(self):
        return {'id': self.id, 'seccion_destino': self.seccion_destino,
                'etiqueta': self.etiqueta, 'texto': self.texto,
                'activadores': list(self.activadores), 'usos': self.usos,
                'origen': self.origen, 'despues_de': self.despues_de}

    @classmethod
    def from_dict(cls, data):
        return cls(id=data.get('id', ''),
                   seccion_destino=data.get('seccion_destino', ''),
                   etiqueta=data.get('etiqueta', ''),
                   texto=data.get('texto', ''),
                   activadores=list(data.get('activadores', [])),
                   usos=int(data.get('usos', 0)),
                   origen=data.get('origen', 'biblioteca'),
                   despues_de=data.get('despues_de', ''))


_NON_SLUG = re.compile(r'[^a-z0-9]+')


def _slugify(text, existing):
    words = textutil.key(text).split()[:5]
    base = _NON_SLUG.sub('-', ' '.join(words)).strip('-')[:40].strip('-') or 'fragmento'
    slug, n = base, 1
    while slug in existing:
        n += 1
        slug = '%s-%d' % (base, n)
    return slug


def _is_strong_signal(word):
    """True si la palabra probablemente identifica algo específico (una sigla,
    un modelo, una marca) y no es solo una palabra de título en mayúscula.

    Esta distinción importa: la etiqueta "Modelo de Robot AMR Recomendado"
    pone en mayúscula inicial "Modelo", "Robot" y "Recomendado" por ser un
    título de campo, no porque identifiquen nada. Si esas palabras se
    aceptaran como activador, el fragmento se sugeriría en TODAS las
    estaciones (todas tienen un "Modelo de Robot Recomendado"), no solo en
    las que de verdad tratan de un AMR.
    """
    if any(c.isdigit() for c in word):
        return True  # modelo con número: MC250, UR20, MiR600
    if word.isupper() and len(word) >= 2:
        return True  # sigla: AMR, MES, ROI, SECS
    if any(c.isupper() for c in word[1:]):
        return True  # mayúscula interna: MiR, McDonald-style
    return False


def _auto_triggers(etiqueta, texto):
    """Activadores razonables por defecto: siglas y modelos mencionados en el
    fragmento. El usuario puede editar la lista desde la interfaz en cualquier
    momento; esto es solo un punto de partida."""
    words = _WORD.findall('%s %s' % (etiqueta, texto))
    triggers = []
    for word in words:
        if len(word) < 2 or not _is_strong_signal(word):
            continue
        key = textutil.key(word)
        if key and key not in triggers:
            triggers.append(key)
    return triggers[:6]


class Library(object):
    """Colección de fragmentos, respaldada por un archivo JSON."""

    def __init__(self, fragments=None, path=None):
        self.fragments = fragments if fragments is not None else []
        self.path = path

    # -- persistencia -------------------------------------------------------
    @classmethod
    def load(cls, path):
        if not os.path.isfile(path):
            return cls(path=path)
        with io.open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        fragments = [Fragment.from_dict(f) for f in data.get('fragmentos', [])]
        return cls(fragments=fragments, path=path)

    def save(self, path=None):
        target = path or self.path
        if not target:
            raise ValueError('la biblioteca no tiene una ruta asociada')
        folder = os.path.dirname(target)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        payload = {'version': 1, 'fragmentos': [f.to_dict() for f in self.fragments]}
        with io.open(target, 'w', encoding='utf-8') as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, indent=2))
        self.path = target

    # -- edición --------------------------------------------------------------
    def add(self, seccion_destino, etiqueta, texto, activadores=None,
           despues_de=''):
        existing_ids = set(f.id for f in self.fragments)
        fragment = Fragment(
            id=_slugify(etiqueta or texto, existing_ids),
            seccion_destino=seccion_destino, etiqueta=etiqueta, texto=texto,
            activadores=activadores if activadores is not None
            else _auto_triggers(etiqueta, texto),
            despues_de=despues_de)
        self.fragments.append(fragment)
        return fragment

    def remove(self, fragment_id):
        self.fragments = [f for f in self.fragments if f.id != fragment_id]

    def register_use(self, fragment_id):
        for fragment in self.fragments:
            if fragment.id == fragment_id:
                fragment.usos += 1
                return

    # -- consulta -------------------------------------------------------------
    def for_section(self, seccion_destino):
        wanted = textutil.key(seccion_destino).rstrip(':')
        return [f for f in self.fragments
                if textutil.key(f.seccion_destino).rstrip(':') == wanted]

    def suggest(self, station, top=5):
        """Fragmentos que probablemente apliquen a `station`, sin repetir lo
        que ya está en su texto y ordenados por relevancia.

        `station` es un p2r.model.Station ya cargado.
        """
        existing = textutil.key(' '.join(
            b.full_text for sec in station.sections for b in sec.bullets))
        station_text = station.name + ' ' + ' '.join(
            sec.title + ' ' + ' '.join(b.full_text for b in sec.bullets)
            for sec in station.sections)

        candidates = []
        for fragment in self.fragments:
            if textutil.key(fragment.full_text) in existing:
                continue  # ya está, de una edición previa o de otra fuente
            if fragment.matches(station_text):
                candidates.append(fragment)

        candidates.sort(key=lambda f: -f.usos)
        return candidates[:top]

    def apply(self, station, fragment, uid_seen, profile=None):
        """Inserta `fragment` como viñeta real en `station`. Devuelve el Bullet
        creado, o None si ya estaba aplicado (evita duplicar con doble clic).

        `uid_seen` es el mismo diccionario de conteo que usó el parser
        (ver model.make_uid): pasarlo asegura que el uid de la viñeta nueva no
        choque con los que ya existen en el reporte.
        """
        full = textutil.key(fragment.full_text)
        for section in station.sections:
            for bullet in section.bullets:
                if textutil.key(bullet.full_text) == full:
                    return None  # ya está, de una edición previa o de otra fuente

        section = station.section(fragment.seccion_destino)
        if section is None:
            title = fragment.seccion_destino
            if not title.endswith(':'):
                title += ':'
            section = Section(title=title, uid=make_uid('s', title, uid_seen))
            rank = profile.section_rank(title) if profile else len(station.sections)
            insert_at = len(station.sections)
            for i, existing in enumerate(station.sections):
                existing_rank = profile.section_rank(existing.title) if profile else i
                if existing_rank > rank:
                    insert_at = i
                    break
            station.sections.insert(insert_at, section)

        bullet = Bullet(label=fragment.etiqueta, text=fragment.texto,
                        uid=make_uid('b', fragment.full_text, uid_seen),
                        origin=ORIGIN_LIBRARY)

        position = len(section.bullets)
        if fragment.despues_de:
            anchor = textutil.key(fragment.despues_de).rstrip(':')
            for i, existing in enumerate(section.bullets):
                if textutil.key(existing.label).rstrip(':') == anchor:
                    position = i + 1
                    break

        section.bullets.insert(position, bullet)
        self.register_use(fragment.id)
        return bullet

    def import_seed(self, seed_path, min_veces=1):
        """Importa el JSON que produce tools/extraer_conocimiento.py.

        Solo se agregan fragmentos que no existan ya (por texto normalizado),
        así que importar el mismo reporte dos veces no duplica nada.
        """
        with io.open(seed_path, encoding='utf-8') as fh:
            data = json.load(fh)

        existing_texts = set(textutil.key(f.full_text) for f in self.fragments)
        added = 0
        for item in data.get('fragmentos', []):
            if item.get('veces', 1) < min_veces:
                continue
            full = '%s %s' % (item.get('etiqueta', ''), item.get('texto', ''))
            if textutil.key(full) in existing_texts:
                continue
            self.add(seccion_destino=item.get('seccion_destino', ''),
                     etiqueta=item.get('etiqueta', ''),
                     texto=item.get('texto', ''),
                     despues_de=item.get('despues_de', ''))
            existing_texts.add(textutil.key(full))
            added += 1
        return added
