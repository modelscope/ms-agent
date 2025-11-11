#!/bin/bash

# install dependencies for ci
pip install torch
export CODE_INTERPRETER_WORK_DIR=${GITHUB_WORKSPACE}
echo "${CODE_INTERPRETER_WORK_DIR}"

# cp file
cp -r tests/* "${CODE_INTERPRETER_WORK_DIR}/"
ls  "${CODE_INTERPRETER_WORK_DIR}"
# pip install playwright
# playwright install --with-deps chromium

# install package
pip install pytest
python setup.py install

# run ci
pytest tests
