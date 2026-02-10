# Copyright (c) ModelScope Contributors. All rights reserved.
# !/usr/bin/env python
import os
import shutil
from setuptools import find_packages, setup
from setuptools.command.build_py import build_py as _build_py
from typing import List


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
                if line.startswith('http'):
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
        super().run()

        # Copy the repository root's `projects/` into the build directory's `ms_agent/projects/`
        src = os.path.join(os.path.dirname(__file__), 'projects')
        if os.path.isdir(src):
            dst = os.path.join(self.build_lib, 'ms_agent', 'projects')
            os.makedirs(os.path.dirname(dst), exist_ok=True)

            if os.path.exists(dst):
                shutil.rmtree(dst)

            shutil.copytree(src, dst)

        # Build and copy webui
        self._build_and_copy_webui()

    def _build_and_copy_webui(self):
        """Build frontend and copy webui files to build directory"""
        import subprocess

        repo_root = os.path.dirname(__file__)
        webui_src = os.path.join(repo_root, 'webui')

        if not os.path.isdir(webui_src):
            print(
                'Warning: webui directory not found, skipping webui packaging')
            return

        frontend_src = os.path.join(webui_src, 'frontend')
        backend_src = os.path.join(webui_src, 'backend')

        # Check if npm is available
        try:
            subprocess.run(['npm', '--version'],
                           capture_output=True,
                           check=True,
                           timeout=5)
            npm_available = True
        except (subprocess.CalledProcessError, FileNotFoundError,
                subprocess.TimeoutExpired):
            npm_available = False
            print(
                'Warning: npm not found, cannot build frontend. WebUI may not work properly.'
            )

        # Build frontend if npm is available
        if npm_available and os.path.isdir(frontend_src):
            print('Building frontend with npm...')

            # Install dependencies if needed
            node_modules = os.path.join(frontend_src, 'node_modules')
            if not os.path.exists(node_modules):
                print('Installing frontend dependencies...')
                try:
                    subprocess.run(['npm', 'install'],
                                   cwd=frontend_src,
                                   check=True,
                                   timeout=300)
                except (subprocess.CalledProcessError,
                        subprocess.TimeoutExpired) as e:
                    print(f'Warning: npm install failed: {e}')
                    return

            # Build frontend
            try:
                subprocess.run(['npm', 'run', 'build'],
                               cwd=frontend_src,
                               check=True,
                               timeout=300)
                print('Frontend built successfully')
            except (subprocess.CalledProcessError,
                    subprocess.TimeoutExpired) as e:
                print(f'Warning: npm build failed: {e}')
                return

        # Copy webui to build directory
        webui_dst = os.path.join(self.build_lib, 'ms_agent', 'webui')

        # Copy backend
        if os.path.isdir(backend_src):
            backend_dst = os.path.join(webui_dst, 'backend')
            if os.path.exists(backend_dst):
                shutil.rmtree(backend_dst)
            shutil.copytree(backend_src, backend_dst)
            print(f'Copied backend to {backend_dst}')

        # Copy frontend dist (built files)
        frontend_dist_src = os.path.join(frontend_src, 'dist')
        if os.path.isdir(frontend_dist_src):
            frontend_dst = os.path.join(webui_dst, 'frontend', 'dist')
            os.makedirs(os.path.dirname(frontend_dst), exist_ok=True)
            if os.path.exists(frontend_dst):
                shutil.rmtree(frontend_dst)
            shutil.copytree(frontend_dist_src, frontend_dst)
            print(f'Copied frontend dist to {frontend_dst}')
        else:
            print(
                'Warning: frontend dist not found, WebUI may not work in production mode'
            )


if __name__ == '__main__':
    print(
        'Usage: `python setup.py sdist bdist_wheel` or `pip install .[framework]` from source code'
    )

    install_requires, deps_link = parse_requirements(
        'requirements/framework.txt')

    extra_requires = {}
    all_requires = []
    extra_requires['research'], _ = parse_requirements(
        'requirements/research.txt')
    extra_requires['code'], _ = parse_requirements('requirements/code.txt')
    extra_requires['webui'], _ = parse_requirements('requirements/webui.txt')
    all_requires.extend(install_requires)
    all_requires.extend(extra_requires['research'])
    all_requires.extend(extra_requires['code'])
    all_requires.extend(extra_requires['webui'])
    extra_requires['all'] = all_requires

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
        include_package_data=True,
        cmdclass={'build_py': build_py},
        package_data={
            'ms_agent': [
                'projects/**/*',
                'webui/backend/**/*',
                'webui/frontend/dist/**/*',
            ],
            '': ['*.h', '*.cpp', '*.cu'],
        },
        classifiers=[
            'Development Status :: 4 - Beta',
            'License :: OSI Approved :: Apache Software License',
            'Operating System :: OS Independent',
            'Programming Language :: Python :: 3',
            'Programming Language :: Python :: 3.8',
            'Programming Language :: Python :: 3.9',
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
