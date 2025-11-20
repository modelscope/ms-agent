# flake8: noqa
# isort: skip_file
# yapf: disable
# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
import os
import sys
from dataclasses import asdict

from sphinxawesome_theme import ThemeOptions

sys.path.insert(0, os.path.abspath('../../'))

project = 'MS-Agent'
copyright = '2022-2024, Alibaba ModelScope'
author = 'ModelScope Authors'
version_file = '../../ms_agent/version.py'


def get_version():
    with open(version_file, 'r', encoding='utf-8') as f:
        exec(compile(f.read(), version_file, 'exec'))
    return locals()['__version__']


# The full version, including alpha/beta/rc tags
version = get_version()
release = version

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.napoleon',
    'sphinx.ext.autosummary',
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx_design',
    'myst_parser',
]

# build the templated autosummary files
autosummary_generate = True
numpydoc_show_class_members = False

# Enable overriding of function signatures in the first line of the docstring.
autodoc_docstring_signature = True

# Disable docstring inheritance
autodoc_inherit_docstrings = False

# Show type hints in the description
autodoc_typehints = 'description'

# Add parameter types if the parameter is documented in the docstring
autodoc_typehints_description_target = 'documented_params'

autodoc_default_options = {
    'member-order': 'bysource',
}

templates_path = ['_templates']
exclude_patterns = []

language = 'en'

# The master toctree document.
root_doc = 'index'

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# The suffix(es) of source filenames.
# You can specify multiple suffix as a list of string:
#
source_suffix = ['.rst', '.md']

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_title = 'MS-Agent'
html_theme = 'sphinxawesome_theme'
html_static_path = ['_static']
html_favicon = './_static/images/ms_agent_icon.svg'
html_permalinks_icon = '<span>#</span>'
html_sidebars: dict[str, list[str]] = {
    'blog/**': ['sidebar_main_nav_links.html'],
}

pygments_style = 'default'
pygments_style_dark = 'one-dark'
# -- Extension configuration -------------------------------------------------

# Auto-generated header anchors
myst_heading_anchors = 3
# Enable "colon_fence" extension of myst.
myst_enable_extensions = ['colon_fence', 'dollarmath']

napoleon_custom_sections = [
    # Custom sections for data elements.
    ('Meta fields', 'params_style'),
    ('Data fields', 'params_style'),
]

theme_options = ThemeOptions(
    awesome_external_links=True,
    show_scrolltop=True,
    main_nav_links={
        'Docs': 'index',
        # 'Blogs': 'blog/index'
    },
    logo_light='./_static/images/ms_agent_icon.svg',
    logo_dark='./_static/images/ms_agent_icon.svg',
    extra_header_link_icons={
        'language': {
            'link':
            'https://ms-agent.readthedocs.io/zh-cn/latest/index.html',
            'icon':
            """
            <svg height="25px" style="margin-top:-2px;display:inline" viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
            <path fill-rule="evenodd" clip-rule="evenodd" d="M4 0H6V2H10V4H8.86807C8.57073 5.66996 7.78574 7.17117 6.6656 8.35112C7.46567 8.73941 8.35737 8.96842 9.29948 8.99697L10.2735 6H12.7265L15.9765 16H13.8735L13.2235 14H9.77647L9.12647 16H7.0235L8.66176 10.9592C7.32639 10.8285 6.08165 10.3888 4.99999 9.71246C3.69496 10.5284 2.15255 11 0.5 11H0V9H0.5C1.5161 9 2.47775 8.76685 3.33437 8.35112C2.68381 7.66582 2.14629 6.87215 1.75171 6H4.02179C4.30023 6.43491 4.62904 6.83446 4.99999 7.19044C5.88743 6.33881 6.53369 5.23777 6.82607 4H0V2H4V0ZM12.5735 12L11.5 8.69688L10.4265 12H12.5735Z" fill="currentColor"/>
            </svg>
            """
        },
        'github': {
            'link':
            'https://github.com/modelscope/ms-agent',
            'icon': (
                '<svg height="26px" style="margin-top:-2px;display:inline" '
                'viewBox="0 0 45 44" '
                'fill="currentColor" xmlns="http://www.w3.org/2000/svg">'
                '<path fill-rule="evenodd" clip-rule="evenodd" '
                'd="M22.477.927C10.485.927.76 10.65.76 22.647c0 9.596 6.223 17.736 '
                '14.853 20.608 1.087.2 1.483-.47 1.483-1.047 '
                '0-.516-.019-1.881-.03-3.693-6.04 '
                '1.312-7.315-2.912-7.315-2.912-.988-2.51-2.412-3.178-2.412-3.178-1.972-1.346.149-1.32.149-1.32 '  # noqa
                '2.18.154 3.327 2.24 3.327 2.24 1.937 3.318 5.084 2.36 6.321 '
                '1.803.197-1.403.759-2.36 '
                '1.379-2.903-4.823-.548-9.894-2.412-9.894-10.734 '
                '0-2.37.847-4.31 2.236-5.828-.224-.55-.969-2.759.214-5.748 0 0 '
                '1.822-.584 5.972 2.226 '
                '1.732-.482 3.59-.722 5.437-.732 1.845.01 3.703.25 5.437.732 '
                '4.147-2.81 5.967-2.226 '
                '5.967-2.226 1.185 2.99.44 5.198.217 5.748 1.392 1.517 2.232 3.457 '
                '2.232 5.828 0 '
                '8.344-5.078 10.18-9.916 10.717.779.67 1.474 1.996 1.474 4.021 0 '
                '2.904-.027 5.247-.027 '
                '5.96 0 .58.392 1.256 1.493 1.044C37.981 40.375 44.2 32.24 44.2 '
                '22.647c0-11.996-9.726-21.72-21.722-21.72" '
                'fill="currentColor"/></svg>'),
        },
    },
)

html_theme_options = asdict(theme_options)
