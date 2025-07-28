#!/bin/bash

# install dependencies for ci
wget -O ffmpeg.tar.xz https://modelscope-agent.oss-cn-hangzhou.aliyuncs.com/resources/ffmpeg.tar.xz
tar xvf ffmpeg.tar.xz

export PATH=`pwd`/ffmpeg-git-20240629-amd64-static:$PATH

sudo apt-get install libcurl4 openssl
wget https://fastdl.mongodb.org/linux/mongodb-linux-x86_64-ubuntu2004-7.0.11.tgz
tar -zxvf mongodb-linux-x86_64-ubuntu2004-7.0.11.tgz
export PATH=`pwd`/mongodb-linux-x86_64-ubuntu2004-7.0.11/bin:$PATH

mkdir mongodb
mongod --dbpath ./mongodb --logpath ./mongo.log --fork

export PATH=`pwd`:$PATH
pip install torch
export CODE_INTERPRETER_WORK_DIR=${GITHUB_WORKSPACE}
echo "${CODE_INTERPRETER_WORK_DIR}"

# cp file
cp tests/samples/* "${CODE_INTERPRETER_WORK_DIR}/"
ls  "${CODE_INTERPRETER_WORK_DIR}"
pip install playwright
playwright install --with-deps chromium

# install package
pip install fastapi pydantic uvicorn docker sqlmodel transformers ray
pip install pymongo motor llama-index-storage-docstore-mongodb==0.1.3 llama-index-storage-index-store-mongodb==0.1.2 llama-index-readers-mongodb==0.1.7
pip install tensorflow pyclipper shapely tf_slim
pip install oss2 moviepy==1.0.3

# run ci
pytest tests
