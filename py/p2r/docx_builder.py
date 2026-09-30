# -*- coding: utf-8 -*-
"""Genera el reporte final .docx a partir del modelo y la plantilla.

Respecto a v1, agrega tres piezas de contenido nuevas, todas construidas a
partir de datos que Plaud ya produce y que antes se desperdiciaban:

  - matriz ejecutiva (p2r/summary.py) con semáforo de dificultad por celda;
  - índice (campo TOC real de Word, se actualiza con F9);
  - fotos con pie de foto, ancladas después de la sección que el usuario
    elija en vez de solo al final de la estación, y con reparación automática
    de JPEG que python-docx rechazaría (p2r/jpeg_fix.py).

Como en v1, el texto que se escribe es el efectivo del modelo de tres capas
(`bullet.text`, no `bullet.original_text`): la capa manual del usuario, si
existe, siempre gana sobre la automática.
"""

import os

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Emu, Inches, Pt

from docx.text.paragraph import Paragraph

from . import docx_xml, jpeg_fix, summary

STATIONS_MARKER = '{{ESTACIONES}}'

FIELD_MAP = [
    ('cliente', 'CLIENTE'), ('tipo_reporte', 'TIPO_REPORTE'),
    ('ubicacion', 'UBICACION'), ('fecha_visita', 'FECHA_VISITA'),
    ('fecha_reporte', 'FECHA_REPORTE'), ('encabezado', 'ENCABEZADO'),
    ('encabezado_portada', 'ENCABEZADO_PORTADA'), ('firma_mir', 'FIRMA_MIR'),
    ('firma_ur', 'FIRMA_UR'), ('fecha_firma', 'FECHA_FIRMA'),
]


class BuildError(Exception):
    pass


def _find_marker(body):
    for el in body.iter(qn('w:p')):
        if STATIONS_MARKER in docx_xml.element_text(el):
            return el
    return None


def _usable_width(doc):
    section = doc.sections[0]
    return section.page_width - section.left_margin - section.right_margin


def _style_cell(cell, text, bold=False, size=11):
    cell.text = ''
    paragraph = cell.paragraphs[0]
    run = paragraph.add_run(text)
    run.font.name = 'Arial'
    run.font.size = Pt(size)
    run.font.bold = bold
    run._element.rPr.rFonts.set(qn('w:cs'), 'Arial')


def _move_table_before(doc, table, marker):
    """add_table() escribe al final del documento; se reubica junto al marcador."""
    doc.element.body.remove(table._tbl)
    marker.addprevious(table._tbl)


def _insert_index(doc, marker):
    for p in docx_xml.toc_field_paragraphs():
        marker.addprevious(p)
    marker.addprevious(docx_xml.page_break_paragraph())


def _insert_executive_summary(doc, marker, report, config):
    rows = summary.build_matrix(report)
    if not rows:
        return False

    marker.addprevious(docx_xml.section_paragraph(
        config.get('titulo_resumen_ejecutivo') or 'Resumen ejecutivo'))

    table = doc.add_table(rows=1, cols=5)
    try:
        table.style = 'Table Grid'
    except KeyError:
        pass

    headers = ('Estación', 'Dificultad', 'Tipo de aplicación', 'Robot', 'ROI')
    for cell, text in zip(table.rows[0].cells, headers):
        _style_cell(cell, text, bold=True)

    for row in rows:
        cells = table.add_row().cells
        _style_cell(cells[0], row.estacion)
        _style_cell(cells[1], str(row.dificultad) if row.dificultad else '—')
        if row.dificultad:
            docx_xml.difficulty_bar_cell(cells[1], row.dificultad)
        _style_cell(cells[2], row.tipo_aplicacion)
        _style_cell(cells[3], row.robot)
        _style_cell(cells[4], row.roi)

    widths = (Inches(1.7), Inches(0.7), Inches(1.5), Inches(0.9), Inches(1.8))
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            cell.width = width

    _move_table_before(doc, table, marker)
    marker.addprevious(docx_xml.plain_paragraph())
    marker.addprevious(docx_xml.page_break_paragraph())
    return True


def _insert_robot_table(doc, marker, robots, config):
    rows = [r for r in robots
            if r.count > 0 or not config.get('omitir_robots_en_cero', True)]
    if not rows:
        return False

    title = config.get('titulo_tabla_robots') or 'Resumen de robots propuestos'
    marker.addprevious(docx_xml.section_paragraph(title))

    table = doc.add_table(rows=1, cols=3)
    try:
        table.style = 'Table Grid'
    except KeyError:
        pass

    for cell, text in zip(table.rows[0].cells, ('Modelo', 'Cantidad', 'Aplicación')):
        _style_cell(cell, text, bold=True)

    total = 0
    for robot in rows:
        cells = table.add_row().cells
        _style_cell(cells[0], robot.model)
        _style_cell(cells[1], str(robot.count))
        _style_cell(cells[2], robot.note)
        total += robot.count

    cells = table.add_row().cells
    _style_cell(cells[0], 'Total', bold=True)
    _style_cell(cells[1], str(total), bold=True)
    _style_cell(cells[2], '', bold=True)

    for row in table.rows:
        row.cells[0].width = Inches(1.5)
        row.cells[1].width = Inches(1.0)
        row.cells[2].width = Inches(4.2)

    _move_table_before(doc, table, marker)
    marker.addprevious(docx_xml.plain_paragraph())
    return True


def _add_picture(doc, marker, photo, max_width_emu, workdir):
    """Inserta una foto (con reparación de JPEG si hace falta) y su pie."""
    insert_path, is_temp = jpeg_fix.ensure_insertable(photo.path, workdir)
    try:
        element = docx_xml.plain_paragraph()
        marker.addprevious(element)
        paragraph = Paragraph(element, doc)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run()
        run.add_picture(insert_path, width=max_width_emu)
        if photo.caption:
            marker.addprevious(docx_xml.caption_paragraph(photo.caption))
    finally:
        if is_temp:
            os.remove(insert_path)


def _insert_stations(doc, marker, report, config, workdir):
    prefix = config.get('prefijo_estacion', '')
    photo_width = Inches(float(config.get('ancho_foto_pulgadas', 6.0)))
    max_width = min(Emu(int(photo_width)), Emu(int(_usable_width(doc))))

    written = 0
    for station in report.active_stations():
        sections = []
        for section in station.sections:
            if not section.enabled:
                continue
            bullets = section.active_bullets()
            if bullets:
                sections.append((section, bullets))

        photos = [p for p in station.photos if p.enabled and os.path.isfile(p.path)]
        if not sections and not photos:
            continue

        marker.addprevious(docx_xml.station_paragraph(prefix, station.name))

        # Fotos ancladas justo después de la sección indicada; el resto (o
        # todas, si 'after_section' quedó vacío) van al cierre de la estación.
        photos_after = {}
        trailing_photos = []
        for photo in photos:
            if photo.after_section:
                photos_after.setdefault(photo.after_section, []).append(photo)
            else:
                trailing_photos.append(photo)

        for section, bullets in sections:
            if section.title:
                marker.addprevious(docx_xml.section_paragraph(section.title))
            for bullet in bullets:
                marker.addprevious(docx_xml.bullet_paragraph(bullet.label, bullet.text))
            for photo in photos_after.get(section.uid, []):
                _add_picture(doc, marker, photo, max_width, workdir)

        for photo in trailing_photos:
            _add_picture(doc, marker, photo, max_width, workdir)

        marker.addprevious(docx_xml.page_break_paragraph())
        written += 1

    return written


def build(report, config, output_path, template=None, workdir=None):
    """Escribe el reporte final. Devuelve un resumen de lo generado."""
    template = template or config.get('plantilla')
    if not template or not os.path.isfile(template):
        raise BuildError(
            'No encuentro la plantilla del reporte:\n%s\n\n'
            'Genérala una vez con tools/make_template.py.' % template)

    doc = docx.Document(template)
    body = doc.element.body

    removed = []
    for key, enabled in (config.get('bloques') or {}).items():
        if not enabled and docx_xml.delete_bookmark_block(body, 'P2R_' + key):
            removed.append(key)

    datos = config.get('datos') or {}
    values = dict((placeholder, (datos.get(key) or '').strip())
                 for key, placeholder in FIELD_MAP)
    docx_xml.substitute_placeholders(body, values)
    for section in doc.sections:
        for attr in ('header', 'first_page_header', 'even_page_header'):
            part = getattr(section, attr, None)
            if part is not None:
                docx_xml.substitute_placeholders(part._element, values)

    marker = _find_marker(body)
    if marker is None:
        raise BuildError(
            'La plantilla no contiene el marcador %s. Vuelve a generarla con '
            'tools/make_template.py.' % STATIONS_MARKER)

    if config.get('incluir_indice', True):
        _insert_index(doc, marker)

    exec_summary_written = False
    if config.get('incluir_resumen_ejecutivo', True):
        exec_summary_written = _insert_executive_summary(doc, marker, report, config)

    stations_written = _insert_stations(doc, marker, report, config, workdir)

    robot_table_written = False
    if config.get('incluir_tabla_robots', True) and report.robots:
        robot_table_written = _insert_robot_table(doc, marker, report.robots, config)

    marker.getparent().remove(marker)
    docx_xml.prune_orphan_bookmarks(body)

    folder = os.path.dirname(os.path.abspath(output_path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    doc.save(output_path)

    return {
        'ruta': output_path,
        'estaciones': stations_written,
        'tabla_robots': robot_table_written,
        'resumen_ejecutivo': exec_summary_written,
        'bloques_omitidos': removed,
    }
