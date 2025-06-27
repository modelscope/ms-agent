#!/bin/bash

# install dependencies for ci

sudo apt-get install libcurl4 openssl
wget https://fastdl.mongodb.org/linux/mongodb-linux-x86_64-ubuntu2004-7.0.11.tgz
tar -zxvf mongodb-linux-x86_64-ubuntu2004-7.0.11.tgz
export PATH=`pwd`/mongodb-linux-x86_64-ubuntu2004-7.0.11/bin:$PATH

pip install torch
export CODE_INTERPRETER_WORK_DIR=${GITHUB_WORKSPACE}
echo "${CODE_INTERPRETER_WORK_DIR}"

# cp file
cp tests/* "${CODE_INTERPRETER_WORK_DIR}/"
ls  "${CODE_INTERPRETER_WORK_DIR}"
pip install playwright
playwright install --with-deps chromium

# install package

# run ci
pytest tests
