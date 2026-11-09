# Copyright (c) ModelScope Contributors. All rights reserved.
"""Keep exported Markdown reports' local image references intact."""
from pathlib import Path

from bs4 import BeautifulSoup
from PIL import Image

from ms_agent.utils.markdown_converter import MarkdownConverter


def _image(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (4, 4), color).save(path)


def _exported_colors(html_path):
    soup = BeautifulSoup(html_path.read_text(encoding='utf-8'), 'html.parser')
    paths = [html_path.parent / image['src'] for image in soup.find_all('img')]
    colors = []
    for path in paths:
        with Image.open(path) as image:
            colors.append(image.convert('RGB').getpixel((0, 0)))
    return paths, colors


def test_repeated_reference_does_not_overwrite_distinct_image(tmp_path):
    source = tmp_path / 'source'
    _image(source / 'before' / 'chart.png', 'red')
    _image(source / 'after' / 'chart.png', 'blue')
    document = source / 'report.md'
    document.write_text(
        '# Report\n\n![Before](before/chart.png)\n\n'
        '![Before again](before/chart.png)\n\n![After](after/chart.png)\n',
        encoding='utf-8')
    output = tmp_path / 'export' / 'report.html'
    MarkdownConverter.markdown_to_html(str(document), str(output))
    paths, colors = _exported_colors(output)
    assert colors == [(255, 0, 0), (255, 0, 0), (0, 0, 255)]
    assert paths[0] == paths[1]
    assert paths[0] != paths[2]


def test_folder_export_preserves_same_named_images_across_reports(tmp_path):
    source = tmp_path / 'source'
    _image(source / 'before' / 'chart.png', 'red')
    _image(source / 'after' / 'chart.png', 'blue')
    for name, directory in [('first', 'before'), ('second', 'after')]:
        (source / f'{name}.md').write_text(
            f'# {name}\n\n![Chart]({directory}/chart.png)\n', encoding='utf-8')
    output = tmp_path / 'export'
    MarkdownConverter.markdown_to_html(str(source), str(output))
    first_paths, first_colors = _exported_colors(output / 'first.html')
    second_paths, second_colors = _exported_colors(output / 'second.html')
    assert first_colors == [(255, 0, 0)]
    assert second_colors == [(0, 0, 255)]
    assert first_paths != second_paths


def test_reexport_changed_image_does_not_change_previous_report(tmp_path):
    source = tmp_path / 'source'
    image = source / 'chart.png'
    _image(image, 'red')
    document = source / 'report.md'
    document.write_text('# Report\n\n![Chart](chart.png)\n', encoding='utf-8')
    first = tmp_path / 'export' / 'first.html'
    second = tmp_path / 'export' / 'second.html'
    MarkdownConverter.markdown_to_html(str(document), str(first))
    _image(image, 'blue')
    MarkdownConverter.markdown_to_html(str(document), str(second))
    assert _exported_colors(first)[1] == [(255, 0, 0)]
    assert _exported_colors(second)[1] == [(0, 0, 255)]


def test_identical_images_share_asset_and_svg_is_preserved(tmp_path):
    source = tmp_path / 'source'
    _image(source / 'one.png', 'red')
    _image(source / 'two.png', 'red')
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><title>chart</title></svg>'
    (source / 'chart.svg').write_text(svg, encoding='utf-8')
    output = tmp_path / 'export'
    output.mkdir()
    mapping = MarkdownConverter._copy_and_process_images(
        [('one.png', ''), ('two.png', ''), ('chart.svg', '')], output, source)
    assert mapping['one.png'] == mapping['two.png']
    assert (output / mapping['chart.svg']).read_text(encoding='utf-8') == svg
