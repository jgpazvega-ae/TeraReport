# -*- coding: utf-8 -*-
"""Configuración persistente de TeraReport (versión web).

Idéntico en contenido al settings.py de la app de escritorio (Plaud2Report),
salvo por tres funciones: install_dir(), resource_dir() y user_data_dir().
En la app de escritorio esas apuntan a carpetas reales de Windows
(%LOCALAPPDATA%, la carpeta del .exe); aquí apuntan a carpetas del sistema de
archivos virtual de Pyodide:

    /app   recursos de solo lectura, escritos una vez al arrancar la página
           (la plantilla .docx, el perfil de fábrica, el catálogo de robots)
    /data  carpeta del usuario, montada sobre IndexedDB (IDBFS) por el
           bootstrap en index.html — lo que se escriba aquí sobrevive a
           cerrar la pestaña, exactamente como %LOCALAPPDATA% en escritorio

Como el resto de este módulo (y de profile.py/library.py/validate.py, que
leen y escriben por ruta) no sabe ni le importa si una ruta es real o
virtual, ninguna otra línea de este archivo cambió respecto a la versión de
escritorio.
"""

import copy
import io
import json
import os

DEFAULT_REPLACEMENTS = [
    {'id': 'amrs-mir', 'buscar': 'AMRs', 'reemplazar': 'MIR (AMR)',
     'palabra_completa': True, 'distingue_mayusculas': True, 'activo': True,
     'colapsar_redundancia': True, 'anonimiza': False},
    {'id': 'amr-mir', 'buscar': 'AMR', 'reemplazar': 'MIR (AMR)',
     'palabra_completa': True, 'distingue_mayusculas': True, 'activo': True,
     'colapsar_redundancia': True, 'anonimiza': False},
    {'id': 'axela-sputtering', 'buscar': 'Axela', 'reemplazar': 'Sputtering',
     'palabra_completa': True, 'distingue_mayusculas': False, 'activo': True,
     'colapsar_redundancia': True, 'anonimiza': True},
    {'id': 'ur5e-ur7e', 'buscar': 'UR5e', 'reemplazar': 'UR7e',
     'palabra_completa': True, 'distingue_mayusculas': False, 'activo': True,
     'colapsar_redundancia': True, 'anonimiza': False},
    {'id': 'ur5-ur7e', 'buscar': 'UR5', 'reemplazar': 'UR7e',
     'palabra_completa': True, 'distingue_mayusculas': False, 'activo': True,
     'colapsar_redundancia': True, 'anonimiza': False},
    {'id': 'ur10e-ur12e', 'buscar': 'UR10e', 'reemplazar': 'UR12e',
     'palabra_completa': True, 'distingue_mayusculas': False, 'activo': True,
     'colapsar_redundancia': True, 'anonimiza': False},
    {'id': 'ur12e-ur15', 'buscar': 'UR12e', 'reemplazar': 'UR15',
     'palabra_completa': True, 'distingue_mayusculas': False, 'activo': True,
     'colapsar_redundancia': True, 'anonimiza': False},
]

BLOCK_LABELS = [
    ('videos', 'Videos relevantes de interés'),
    ('integrador', 'Trabajo con integrador y certificación'),
    ('durabilidad', 'Durabilidad (MTBF e-Series)'),
    ('educacion', 'Educación y capacitación'),
    ('servicio', 'Servicio y centro de reparación'),
    ('entrega', 'Tiempo de entrega'),
    ('montaje', 'Consideraciones de montaje'),
    ('seguridad', 'Consideraciones de seguridad'),
    ('firmas', 'Tabla de firmas'),
]

DEFAULTS = {
    'reemplazos': DEFAULT_REPLACEMENTS,
    'secciones_a_eliminar': ['Consideraciones de Seguridad', 'Recursos Humanos'],
    'bloques': dict((key, True) for key, _ in BLOCK_LABELS),
    'incluir_tabla_robots': True,
    'incluir_resumen_ejecutivo': True,
    'incluir_indice': True,
    'titulo_tabla_robots': 'Resumen de robots propuestos',
    'omitir_robots_en_cero': True,
    'prefijo_estacion': 'Nombre de la estación: ',
    'ancho_foto_pulgadas': 6.0,
    'sugerir_fragmentos_biblioteca': True,
    'validar_antes_de_generar': True,
    'datos': {
        'cliente': '', 'ubicacion': '', 'tipo_reporte': 'Plant Assessment',
        'fecha_visita': '', 'fecha_reporte': '',
        'encabezado': 'Levantamiento en planta.',
        'encabezado_portada': 'Plant Assessment',
        'firma_mir': '',
        'firma_ur': '',
        'fecha_firma': '', 'autor': '',
    },
    'ultima_carpeta_entrada': '',
    'ultima_carpeta_salida': '',
    'archivos_recientes': [],
    'tema': 'claro',
}

MAX_RECENT = 8

# -- las tres únicas funciones distintas a la versión de escritorio ---------


def install_dir():
    """Raíz de los recursos empaquetados, dentro del FS virtual de Pyodide."""
    return '/app'


def resource_dir():
    """En la web no hay _MEIPASS ni .exe: los recursos siempre viven en /app,
    donde el bootstrap de index.html los escribió al cargar la página."""
    return install_dir()


def user_data_dir():
    """Carpeta del usuario, montada como IDBFS (persistente en IndexedDB) por
    el bootstrap de index.html. Equivale a %LOCALAPPDATA% en escritorio."""
    return '/data'


# -- de aquí en adelante, exactamente igual que en escritorio ---------------


def _migrate_legacy_file(legacy_path, target_path):
    """Copia un archivo de una instalación vieja la primera vez que se
    necesita en la nueva ubicación, y no vuelve a tocarlo después.

    En la web no hay 'instalación vieja junto al ejecutable', así que
    legacy_path nunca existe y esto no hace nada — se conserva para que el
    resto del archivo sea un calco exacto del de escritorio."""
    if os.path.isfile(target_path) or not os.path.isfile(legacy_path):
        return
    folder = os.path.dirname(target_path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with io.open(legacy_path, 'rb') as src, io.open(target_path, 'wb') as dst:
        dst.write(src.read())


def config_path():
    target = os.path.join(user_data_dir(), 'settings.json')
    _migrate_legacy_file(os.path.join(install_dir(), 'config', 'settings.json'),
                         target)
    return target


def template_path():
    return os.path.join(resource_dir(), 'templates', 'plant_assessment.docx')


def profile_path():
    """El perfil se copia a la carpeta de usuario en el primer arranque para
    que se pueda editar sin tocar el de fábrica; el de resource_dir() es la
    semilla de fábrica."""
    target = os.path.join(user_data_dir(), 'perfil_plaud.json')
    _migrate_legacy_file(os.path.join(install_dir(), 'config', 'perfil_plaud.json'),
                         target)
    return target


def profile_seed_path():
    return os.path.join(resource_dir(), 'data', 'perfil_plaud.json')


def catalog_path():
    return os.path.join(resource_dir(), 'data', 'catalogo_robots.json')


def library_path():
    target = os.path.join(user_data_dir(), 'biblioteca.json')
    _migrate_legacy_file(os.path.join(install_dir(), 'config', 'biblioteca.json'),
                         target)
    return target


def library_seed_path():
    return os.path.join(resource_dir(), 'data', 'biblioteca_semilla.json')


def ensure_profile_copy():
    """Copia el perfil de fábrica a la carpeta de usuario la primera vez que
    se necesita."""
    target = profile_path()
    if os.path.isfile(target):
        return target
    seed = profile_seed_path()
    folder = os.path.dirname(target)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    if os.path.isfile(seed):
        with io.open(seed, encoding='utf-8') as fh:
            data = fh.read()
        with io.open(target, 'w', encoding='utf-8') as fh:
            fh.write(data)
    return target


def restore_profile_from_seed():
    """Sobrescribe el perfil del usuario con la versión de fábrica.

    Antes de sobrescribir, deja un respaldo de la copia actual (se
    sobreescribe en cada restauración, no se acumulan varios).
    """
    seed = profile_seed_path()
    if not os.path.isfile(seed):
        raise IOError('No se encontró el perfil de fábrica en %s' % seed)

    target = profile_path()
    folder = os.path.dirname(target)
    if not os.path.isdir(folder):
        os.makedirs(folder)

    if os.path.isfile(target):
        backup = target + '.bak'
        with io.open(target, 'rb') as src, io.open(backup, 'wb') as dst:
            dst.write(src.read())

    with io.open(seed, encoding='utf-8') as fh:
        data = fh.read()
    with io.open(target, 'w', encoding='utf-8') as fh:
        fh.write(data)
    return target


def _merge(base, override):
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load():
    path = config_path()
    if not os.path.isfile(path):
        return copy.deepcopy(DEFAULTS)
    try:
        with io.open(path, encoding='utf-8') as fh:
            stored = json.load(fh)
    except (ValueError, IOError):
        return copy.deepcopy(DEFAULTS)
    return _merge(DEFAULTS, stored)


def save(config):
    path = config_path()
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with io.open(path, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(config, ensure_ascii=False, indent=2))
    return path


def push_recent(config, path):
    """Agrega `path` al frente de los archivos recientes, sin duplicar."""
    recent = [p for p in config.get('archivos_recientes', []) if p != path]
    recent.insert(0, path)
    config['archivos_recientes'] = recent[:MAX_RECENT]
