# 使用Ubuntu作为基础镜像
FROM ubuntu:22.04

# 设置非交互式安装
ENV DEBIAN_FRONTEND=noninteractive

# 设置时区与默认语言环境
ENV TZ=Asia/Shanghai
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV LANGUAGE=en_US:en

# 先安装CA证书，避免切换HTTPS源后因证书缺失导致失败
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 优先使用可访问的国内镜像源并增加apt重试，减少网络抖动导致的失败
RUN sed -i 's|http://archive.ubuntu.com/ubuntu/|https://mirrors.aliyun.com/ubuntu/|g' /etc/apt/sources.list \
    && sed -i 's|http://security.ubuntu.com/ubuntu/|https://mirrors.aliyun.com/ubuntu/|g' /etc/apt/sources.list \
    && printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\n' > /etc/apt/apt.conf.d/80-retries

# 创建用户（避免使用root）
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID

# 更新系统并安装基础软件包
RUN apt-get update && apt-get install -y \
    # 基础工具
    sudo \
    curl \
    wget \
    git \
    vim \
    nano \
    unzip \
    zip \
    build-essential \
    cmake \
    pkg-config \
    # Python 3.10相关
    python3.10 \
    python3-pip \
    python3-venv \
    python3-dev \
    python3-distutils \
    # 网络工具
    openssh-client \
    # 语言环境
    locales \
    # 其他有用工具
    htop \
    tree \
    jq \
    # 配置语言环境并清理缓存
    && locale-gen en_US.UTF-8 \
    && update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 创建用户
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

# 切换到用户
USER $USERNAME

# 设置用户环境变量
ENV PATH="/home/${USERNAME}/.local/bin:${PATH}"
ENV PYTHONPATH="/workspace"
ENV PYTHONUNBUFFERED=1

# 升级pip并安装基础Python包
RUN python3.10 -m pip install --user --upgrade pip setuptools wheel

# 创建工作目录
WORKDIR /workspace

# 设置命令提示符
RUN echo 'export PS1="\[\033[01;32m\]\u@devcontainer\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ "' >> /home/${USERNAME}/.bashrc

# 添加便利别名
RUN echo 'alias ll="ls -alF"' >> /home/${USERNAME}/.bashrc \
    && echo 'alias la="ls -A"' >> /home/${USERNAME}/.bashrc \
    && echo 'alias l="ls -CF"' >> /home/${USERNAME}/.bashrc

# 切换回root以执行后续命令
USER root

# 在容器启动时执行的脚本
COPY <<EOF /usr/local/bin/post-start.sh
#!/bin/bash
echo "=== MS-Agent DevContainer 已启动 ==="
echo "工作目录: $(pwd)"
echo "Python版本: $(python3.10 --version)"
echo "用户: $(whoami)"
echo "====================================="
EOF

RUN chmod +x /usr/local/bin/post-start.sh

# 设置默认命令
CMD ["/bin/bash"]
