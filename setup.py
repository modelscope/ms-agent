# Copyright (c) ModelScope Contributors. All rights reserved.
# !/usr/bin/env python
from setuptools import find_packages, setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.sdist import sdist as _sdist

import importlib.util
import os
import shutil
from pathlib import Path

_webui_spec = importlib.util.spec_from_file_location(
    '_ms_agent_webui_build',
    Path(__file__).resolve().parent / '.dev_scripts/webui/webui_packaging.py')
webui_packaging = importlib.util.module_from_spec(_webui_spec)
_webui_spec.loader.exec_module(webui_packaging)


def readme():
    with open('README.md', encoding='utf-8') as f:
        content = f.read()
    return content


version_file = 'ms_agent/version.py'


def get_version():
    namespace = {}
    with open(version_file, 'r', encoding='utf-8') as f:
        exec(compile(f.read(), version_file, 'exec'), namespace)
    return namespace['__version__']


def parse_requirements(fname='requirements.txt', with_version=True):
    """
    Parse the package dependencies listed in a requirements file but strips
    specific versioning information.

    Args:
        fname (str): path to requirements file
        with_version (bool, default=False): if True include version specs

    Returns:
        List[str]: list of requirements items

    CommandLine:
        python -c "import setup; print(setup.parse_requirements())"
    """
    import re
    import sys
    from os.path import exists
    require_fpath = fname

    def parse_line(line):
        """
        Parse information from a line in a requirements text file
        """
        if line.startswith('-r '):
            # Allow specifying requirements in other files
            target = line.split(' ')[1]
            relative_base = os.path.dirname(fname)
            absolute_target = os.path.join(relative_base, target)
            for info in parse_require_file(absolute_target):
                yield info
        else:
            info = {'line': line}
            if line.startswith('-e '):
                info['package'] = line.split('#egg=')[1]
            else:
                # Remove versioning from the package
                pat = '(' + '|'.join(['>=', '==', '>']) + ')'
                parts = re.split(pat, line, maxsplit=1)
                parts = [p.strip() for p in parts]

                info['package'] = parts[0]
                if len(parts) > 1:
                    op, rest = parts[1:]
                    if ';' in rest:
                        # Handle platform specific dependencies
                        # http://setuptools.readthedocs.io/en/latest/setuptools.html#declaring-platform-specific-dependencies
                        version, platform_deps = map(str.strip,
                                                     rest.split(';'))
                        info['platform_deps'] = platform_deps
                    else:
                        version = rest  # NOQA
                    info['version'] = (op, version)
            yield info

    def parse_require_file(fpath):
        with open(fpath, 'r', encoding='utf-8') as f:
            for line in f.readlines():
                line = line.strip()
                if line.startswith(('http://', 'https://')):
                    print('skip http requirements %s' % line)
                    continue
                if line and not line.startswith('#') and not line.startswith(
                        '--'):
                    for info in parse_line(line):
                        yield info
                elif line and line.startswith('--find-links'):
                    eles = line.split()
                    for e in eles:
                        e = e.strip()
                        if 'http' in e:
                            info = dict(dependency_links=e)
                            yield info

    def gen_packages_items():
        items = []
        deps_link = []
        if exists(require_fpath):
            for info in parse_require_file(require_fpath):
                if 'dependency_links' not in info:
                    parts = [info['package']]
                    if with_version and 'version' in info:
                        parts.extend(info['version'])
                    if not sys.version.startswith('3.4'):
                        # apparently package_deps are broken in 3.4
                        platform_deps = info.get('platform_deps')
                        if platform_deps is not None:
                            parts.append(';' + platform_deps)
                    item = ''.join(parts)
                    items.append(item)
                else:
                    deps_link.append(info['dependency_links'])
        return items, deps_link

    return gen_packages_items()


class build_py(_build_py):

    def run(self):
        if getattr(self, 'editable_mode', False):
            super().run()
            return
        if (webui_packaging.WEBUI / webui_packaging.MANIFEST).is_file():
            webui_packaging.validate_release()
        super().run()

        # Copy the repository root's `projects/` into the build directory's `ms_agent/projects/`
        src = os.path.join(os.path.dirname(__file__), 'projects')
        if os.path.isdir(src):
            dst = os.path.join(self.build_lib, 'ms_agent', 'projects')
            os.makedirs(os.path.dirname(dst), exist_ok=True)

            if os.path.exists(dst):
                shutil.rmtree(dst)

            shutil.copytree(src, dst)

        webui_packaging.copy_resources(Path(self.build_lib) / 'ms_agent/webui')

        # Copy the Capability Gateway skill package into the built-in skills
        # tree so ``pip install ms-agent`` ships a discoverable skill
        # (skill_id = ``ms-agent``) under ``ms_agent/skills/ms-agent/``.
        skill_src = os.path.join(os.path.dirname(__file__), 'ms-agent-skills')
        if os.path.isdir(skill_src):
            skill_dst = os.path.join(self.build_lib, 'ms_agent', 'skills',
                                     'ms-agent')
            os.makedirs(os.path.dirname(skill_dst), exist_ok=True)
            if os.path.exists(skill_dst):
                shutil.rmtree(skill_dst)
            shutil.copytree(
                skill_src,
                skill_dst,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'),
            )

    def get_source_files(self):
        files = super().get_source_files()
        files.extend('webui/' + rel
                     for rel in webui_packaging.resource_paths(
                         include_build=(webui_packaging.WEBUI /
                                        webui_packaging.MANIFEST).is_file())
                     if (webui_packaging.WEBUI / rel).is_file())
        if (webui_packaging.WEBUI / webui_packaging.MANIFEST).is_file():
            files.append('webui/' + webui_packaging.MANIFEST)
        return files

    def get_outputs(self, include_bytecode=1):
        files = super().get_outputs(include_bytecode=include_bytecode)
        if not getattr(self, 'editable_mode', False):
            files.extend(
                str(Path(self.build_lib) / 'ms_agent/webui' / rel)
                for rel in webui_packaging.resource_paths(
                    include_build=(webui_packaging.WEBUI /
                                   webui_packaging.MANIFEST).is_file())
                + [webui_packaging.MANIFEST])
        return files


class sdist(_sdist):

    def run(self):
        if (webui_packaging.WEBUI / webui_packaging.MANIFEST).is_file():
            webui_packaging.validate_release()
        super().run()


if __name__ == '__main__':
    print(
        'Usage: `python setup.py sdist bdist_wheel` or `pip install .` from source code'
    )

    install_requires, deps_link = parse_requirements(
        'requirements/framework.txt')

    extra_requires = {}
    extra_requires['research'], _ = parse_requirements(
        'requirements/research.txt')
    extra_requires['code'], _ = parse_requirements('requirements/code.txt')
    extra_requires['acp'], _ = parse_requirements('requirements/acp.txt')
    extra_requires['a2a'], _ = parse_requirements('requirements/a2a.txt')
    extra_requires['retrieval'], _ = parse_requirements(
        'requirements/retrieval.txt')
    extra_requires['cinema'], _ = parse_requirements('requirements/cinema.txt')
    extra_requires['docs'], _ = parse_requirements('requirements/docs.txt')
    extra_requires['webui'], _ = parse_requirements('requirements/webui.txt')

    # ``all`` aggregates every *runtime* extra so that `pip install ms-agent[all]`
    # yields a fully-featured install. ``docs`` is build-only and intentionally
    # excluded. De-duplicated for a clean, deterministic dependency set.
    all_requires = list(install_requires)
    for _group in ('research', 'code', 'acp', 'a2a', 'retrieval', 'cinema',
                   'webui'):
        all_requires.extend(extra_requires[_group])
    extra_requires['all'] = sorted(set(all_requires))

    setup(
        name='ms-agent',
        version=get_version(),
        description=
        'MS-Agent: Lightweight Framework for Empowering Agents with Autonomous Exploration',
        long_description=readme(),
        long_description_content_type='text/markdown',
        author='The ModelScope teams',
        author_email='contact@modelscope.cn',
        keywords='python, agent, LLM',
        url='https://github.com/modelscope/ms-agent',
        packages=find_packages(exclude=('configs', 'demo')),
        python_requires='>=3.10',
        include_package_data=True,
        cmdclass={
            'build_py': build_py,
            'sdist': sdist
        },
        package_data={
            'ms_agent': [
                'projects/**/*',
                # agent_hub conversion templates — without these in the wheel,
                # get_defaults() returns {} and cross-framework convert
                # silently degrades to a raw file copy.
                'agent_hub/default_configs/**/*',
                'webui/**/*',
                # Capability Gateway skill package (copied into ms_agent/skills at build).
                'skills/**/*',
            ],
            '': ['*.h', '*.cpp', '*.cu'],
        },
        classifiers=[
            'Development Status :: 4 - Beta',
            'License :: OSI Approved :: Apache Software License',
            'Operating System :: OS Independent',
            'Programming Language :: Python :: 3',
            'Programming Language :: Python :: 3.10',
            'Programming Language :: Python :: 3.11',
            'Programming Language :: Python :: 3.12',
        ],
        license='Apache License 2.0',
        install_requires=install_requires,
        extras_require=extra_requires,
        entry_points={
            'console_scripts': ['ms-agent=ms_agent.cli.cli:run_cmd']
        },
        dependency_links=deps_link,
        zip_safe=False)
