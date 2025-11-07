#!/bin/bash

# DevContainer 启动脚本
# 提供快速启动命令和便利功能

echo "=== MS-Agent DevContainer 管理脚本 ==="
echo ""

# 显示帮助信息
show_help() {
    echo "使用方法:"
    echo "  ./devctl.sh [命令]"
    echo ""
    echo "可用命令:"
    echo "  build     - 构建DevContainer镜像"
    echo "  up        - 启动DevContainer"
    echo "  down      - 停止DevContainer"
    echo "  shell     - 进入DevContainer shell"
    echo "  status    - 查看容器状态"
    echo "  logs      - 查看容器日志"
    echo "  clean     - 清理容器和镜像"
    echo "  help      - 显示此帮助信息"
    echo ""
}

# 构建镜像
build_image() {
    echo "🔨 构建DevContainer镜像..."
    docker-compose -f .devcontainer/docker-compose.yml build
}

# 启动容器
start_container() {
    echo "🚀 启动DevContainer..."
    docker-compose -f .devcontainer/docker-compose.yml up -d
}

# 停止容器
stop_container() {
    echo "🛑 停止DevContainer..."
    docker-compose -f .devcontainer/docker-compose.yml down
}

# 进入容器shell
enter_shell() {
    echo "🐚 进入DevContainer shell..."
    docker-compose -f .devcontainer/docker-compose.yml exec ms-agent-dev bash
}

# 查看状态
show_status() {
    echo "📊 容器状态:"
    docker-compose -f .devcontainer/docker-compose.yml ps
}

# 查看日志
show_logs() {
    echo "📋 容器日志:"
    docker-compose -f .devcontainer/docker-compose.yml logs -f
}

# 清理资源
clean_resources() {
    echo "🧹 清理DevContainer资源..."
    docker-compose -f .devcontainer/docker-compose.yml down -v --rmi all
}

# 主逻辑
case "${1:-help}" in
    "build")
        build_image
        ;;
    "up")
        start_container
        ;;
    "down")
        stop_container
        ;;
    "shell")
        enter_shell
        ;;
    "status")
        show_status
        ;;
    "logs")
        show_logs
        ;;
    "clean")
        clean_resources
        ;;
    "help"|*)
        show_help
        ;;
esac
