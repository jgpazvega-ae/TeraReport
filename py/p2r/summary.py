# -*- coding: utf-8 -*-
"""Extrae la matriz ejecutiva a partir de los campos semi-estructurados de
'Resumen de la Aplicación' y 'Factibilidad'.

Esto es contenido que Plaud ya produce y que hoy nadie consolida: un gerente
que hojea el reporte no tiene, hoy, una sola tabla con dificultad, tipo de
aplicación, robot recomendado, payload y ROI de las N estaciones. Cada campo
se extrae con tolerancia — si no está, la celda queda en blanco en vez de
reventar la generación.
"""

import re

_DIFFICULTY = re.compile(r'(\d)\s*(?:\(|de\s*5|/\s*5)', re.IGNORECASE)
_DIFFICULTY_BARE = re.compile(r'^\s*(\d)\s*$')


def _field_text(station, label):
    field = station.field(label)
    return field.text.strip().rstrip('.') if field else ''


def difficulty_level(station):
    """Nivel 1-5 extraído de 'Nivel de dificultad', o None si no se pudo leer."""
    field = station.field('Nivel de dificultad')
    if field is None:
        return None
    text = field.text
    m = _DIFFICULTY.search(text) or _DIFFICULTY_BARE.match(text.strip())
    if not m:
        digits = re.findall(r'[1-5]', text)
        return int(digits[0]) if digits else None
    try:
        level = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return level if 1 <= level <= 5 else None


class Row(object):
    __slots__ = ('estacion', 'dificultad', 'tipo_aplicacion', 'robot',
                 'payload', 'roi')

    def __init__(self, estacion, dificultad, tipo_aplicacion, robot, payload, roi):
        self.estacion = estacion
        self.dificultad = dificultad
        self.tipo_aplicacion = tipo_aplicacion
        self.robot = robot
        self.payload = payload
        self.roi = roi


def build_matrix(report):
    """Una Row por estación activa, en el orden en que aparecen en el reporte."""
    rows = []
    for station in report.active_stations():
        rows.append(Row(
            estacion=station.name,
            dificultad=difficulty_level(station),
            tipo_aplicacion=_field_text(station, 'Tipo de Aplicación'),
            robot=_field_text(station, 'Modelo de Robot Recomendado'),
            payload=_field_text(station, 'Peso de la Pieza / Carga útil del Robot'),
            roi=_field_text(station, 'Impacto Económico / ROI'),
        ))
    return rows
