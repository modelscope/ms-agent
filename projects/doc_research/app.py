# flake8: noqa
import base64
import os
import re
import shutil
import socketserver
import threading
import time
import uuid
from datetime import datetime
from typing import List, Tuple

import gradio as gr
import json
import markdown
from ms_agent.llm.openai import OpenAIChat
from ms_agent.workflow.research_workflow import ResearchWorkflow


class ResearchWorkflowExtend:

    def __init__(self, client, workdir: str):
        self.client = client
        self.workdir = workdir

        # TODO: download easyocr model first, for temp use
        target_dir: str = '~/.EasyOCR/model'
        if not os.path.exists(
                os.path.join(
                    os.path.expanduser(target_dir), 'craft_mlt_25k.pth')):
            from modelscope import snapshot_download

            os.makedirs(os.path.expanduser(target_dir), exist_ok=True)
            # 下载模型到指定目录
            snapshot_download(
                model_id='ms-agent/craft_mlt_25k',
                local_dir=os.path.expanduser(target_dir),
            )
            snapshot_download(
                model_id='ms-agent/latin_g2',
                local_dir=os.path.expanduser(target_dir),
            )
            print(f'EasyOCR模型已下载到: {os.path.expanduser(target_dir)}')
            # unzip craft_mlt_25k.zip, latin_g2.zip
            import zipfile
            zip_path_craft = os.path.join(
                os.path.expanduser(target_dir), 'craft_mlt_25k.zip')
            zip_path_latin = os.path.join(
                os.path.expanduser(target_dir), 'latin_g2.zip')
            if os.path.exists(zip_path_craft):
                with zipfile.ZipFile(zip_path_craft, 'r') as zip_ref_craft:
                    zip_ref_craft.extractall(os.path.expanduser(target_dir))
            if os.path.exists(zip_path_latin):
                with zipfile.ZipFile(zip_path_latin, 'r') as zip_ref_latin:
                    zip_ref_latin.extractall(os.path.expanduser(target_dir))

            print(f'EasyOCR模型已解压到: {os.path.expanduser(target_dir)}')

        self._workflow = ResearchWorkflow(
            client=self.client,
            workdir=self.workdir,
            verbose=True,
        )

    def run(self, user_prompt: str, urls_or_files: List[str]) -> str:
        # 检查输入文件/URLs是否为空
        if not urls_or_files:
            return """
❌ 输入错误：未提供任何文件或URLs

请确保：
1. 上传至少一个文件，或
2. 在URLs输入框中输入至少一个有效的URL

然后重新运行研究工作流。
"""

        self._workflow.run(
            user_prompt=user_prompt,
            urls_or_files=urls_or_files,
        )

        # 返回执行情况统计
        result = f"""
研究工作流执行完成！

工作目录: {self.workdir}
用户提示: {user_prompt}
输入文件/URLs数量: {len(urls_or_files)}

处理的内容:
"""
        for i, item in enumerate(urls_or_files, 1):
            if item.startswith('http'):
                result += f'{i}. URL: {item}\n'
            else:
                result += f'{i}. 文件: {os.path.basename(item)}\n'

        result += '\n✅ 研究分析已完成，结果已保存到工作目录中。'
        return result


# 全局变量
BASE_WORKDIR = 'temp_workspace'
IMAGE_SERVER_PORT = 52682
IMAGE_SERVER_URL = f'http://localhost:{IMAGE_SERVER_PORT}'

# 并发控制配置
GRADIO_DEFAULT_CONCURRENCY_LIMIT = int(
    os.environ.get('GRADIO_DEFAULT_CONCURRENCY_LIMIT', '8'))
TASK_TIMEOUT = int(os.environ.get('TASK_TIMEOUT', '1200'))  # 20分钟超时


# 简化的用户状态管理器
class UserStatusManager:

    def __init__(self):
        self.active_users = {
        }  # {user_id: {'start_time': time, 'status': status}}
        self.lock = threading.Lock()

    def get_user_status(self, user_id: str) -> dict:
        """获取用户任务状态"""
        with self.lock:
            if user_id in self.active_users:
                user_info = self.active_users[user_id]
                elapsed_time = time.time() - user_info['start_time']
                return {
                    'status': user_info['status'],
                    'elapsed_time': elapsed_time,
                    'is_active': True
                }
            return {'status': 'idle', 'elapsed_time': 0, 'is_active': False}

    def start_user_task(self, user_id: str):
        """标记用户任务开始"""
        with self.lock:
            self.active_users[user_id] = {
                'start_time': time.time(),
                'status': 'running'
            }
            print(
                f'用户任务开始 - 用户: {user_id[:8]}***, 当前活跃用户数: {len(self.active_users)}'
            )

    def finish_user_task(self, user_id: str):
        """标记用户任务完成"""
        with self.lock:
            if user_id in self.active_users:
                del self.active_users[user_id]
                print(
                    f'用户任务完成 - 用户: {user_id[:8]}***, 剩余活跃用户数: {len(self.active_users)}'
                )

    def get_system_status(self) -> dict:
        """获取系统状态"""
        with self.lock:
            active_count = len(self.active_users)
        return {
            'active_tasks': active_count,
            'max_concurrent': GRADIO_DEFAULT_CONCURRENCY_LIMIT,
            'available_slots': GRADIO_DEFAULT_CONCURRENCY_LIMIT - active_count,
            'task_details': {
                user_id: {
                    'status': info['status'],
                    'elapsed_time': time.time() - info['start_time']
                }
                for user_id, info in self.active_users.items()
            }
        }

    def force_cleanup_user(self, user_id: str) -> bool:
        """强制清理用户任务"""
        with self.lock:
            if user_id in self.active_users:
                del self.active_users[user_id]
                print(f'强制清理用户任务 - 用户: {user_id[:8]}***')
                return True
            return False


# 创建全局用户状态管理器实例
user_status_manager = UserStatusManager()


def get_user_id_from_request(request: gr.Request) -> str:
    """从请求头获取用户ID"""
    if request and hasattr(request, 'headers'):
        user_id = request.headers.get('x-modelscope-router-id', '')
        return user_id.strip() if user_id else ''
    return ''


def check_user_auth(request: gr.Request) -> Tuple[bool, str]:
    """检查用户认证状态"""
    user_id = get_user_id_from_request(request)
    if not user_id:
        return False, '请登录后使用'
    return True, user_id


def create_user_workdir(user_id: str) -> str:
    """为用户创建专属工作目录"""
    user_base_dir = os.path.join(BASE_WORKDIR, f'user_{user_id}')
    if not os.path.exists(user_base_dir):
        os.makedirs(user_base_dir)
    return user_base_dir


def create_task_workdir(user_id: str) -> str:
    """创建新的任务工作目录"""
    user_base_dir = create_user_workdir(user_id)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    task_id = str(uuid.uuid4())[:8]
    task_workdir = os.path.join(user_base_dir, f'task_{timestamp}_{task_id}')
    os.makedirs(task_workdir, exist_ok=True)
    return task_workdir


def process_urls_text(urls_text: str) -> List[str]:
    """处理URL文本输入，按换行分割"""
    if not urls_text.strip():
        return []

    urls = []
    for line in urls_text.strip().split('\n'):
        line = line.strip()
        if line:
            urls.append(line)
    return urls


def process_files(files) -> List[str]:
    """处理上传的文件"""
    if not files:
        return []

    file_paths = []
    # 确保files是列表格式
    if not isinstance(files, list):
        files = [files] if files else []

    for file in files:
        if file is not None:
            if hasattr(file, 'name') and file.name:
                file_paths.append(file.name)
            elif isinstance(file, str) and file:
                file_paths.append(file)

    return file_paths


def check_port_available(port: int) -> bool:
    """检查端口是否可用"""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(('localhost', port))
            return result != 0  # 0表示连接成功，端口被占用
    except Exception:
        return True


def check_image_server_running(port: int = IMAGE_SERVER_PORT) -> bool:
    """检查图片服务器是否正在运行"""
    import requests
    try:
        response = requests.get(f'http://localhost:{port}', timeout=2)
        return response.status_code in [200, 404]  # 404也表示服务器在运行
    except Exception:
        return False


class ReusableTCPServer(socketserver.TCPServer):
    """支持地址重用的TCP服务器"""
    allow_reuse_address = True


def create_static_image_server(workdir: str = BASE_WORKDIR,
                               port: int = IMAGE_SERVER_PORT) -> str:
    """创建静态图片服务器"""
    import threading
    import http.server
    import socketserver
    from urllib.parse import quote

    class ImageHandler(http.server.SimpleHTTPRequestHandler):

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=workdir, **kwargs)

        def end_headers(self):
            # 添加CORS头部以允许跨域访问
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET')
            self.send_header('Access-Control-Allow-Headers', '*')
            super().end_headers()

        def log_message(self, format, *args):
            # 静默日志输出
            pass

    try:
        httpd = ReusableTCPServer(('', port), ImageHandler)
        # 在后台线程中启动服务器，设置为非守护进程以保持长期运行
        server_thread = threading.Thread(
            target=httpd.serve_forever, daemon=False)
        server_thread.start()
        print(f'图片服务器已启动在端口 {port}，服务目录: {workdir}')
        return f'http://localhost:{port}'
    except Exception as e:
        print(f'无法启动图片服务器: {e}')
        return None


def ensure_image_server_running(workdir: str = BASE_WORKDIR) -> str:
    """确保图片服务器正在运行"""
    # 首先检查服务器是否已经在运行
    if check_image_server_running(IMAGE_SERVER_PORT):
        print(f'图片服务器已在端口 {IMAGE_SERVER_PORT} 运行')
        return IMAGE_SERVER_URL

    # 如果服务器未运行，尝试创建新的服务器
    print(f'端口 {IMAGE_SERVER_PORT} 上没有检测到图片服务器，正在创建...')
    server_url = create_static_image_server(workdir, IMAGE_SERVER_PORT)

    if server_url:
        # 等待服务器启动
        import time
        time.sleep(1)

        # 验证服务器是否成功启动
        if check_image_server_running(IMAGE_SERVER_PORT):
            print(f'图片服务器成功启动在 {server_url}')
            return server_url
        else:
            print('图片服务器启动失败')
            return None
    else:
        print('无法创建图片服务器')
        return None


def convert_markdown_images_to_base64(markdown_content: str,
                                      workdir: str) -> str:
    """将markdown中的相对路径图片转换为base64格式（适用于在线环境）"""

    def replace_image(match):
        alt_text = match.group(1)
        image_path = match.group(2)

        # 处理相对路径
        if not os.path.isabs(image_path):
            full_path = os.path.join(workdir, image_path)
        else:
            full_path = image_path

        # 检查文件是否存在
        if os.path.exists(full_path):
            try:
                # 获取文件扩展名来确定MIME类型
                ext = os.path.splitext(full_path)[1].lower()
                mime_types = {
                    '.png': 'image/png',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.gif': 'image/gif',
                    '.bmp': 'image/bmp',
                    '.webp': 'image/webp',
                    '.svg': 'image/svg+xml'
                }
                mime_type = mime_types.get(ext, 'image/png')

                # 检查文件大小，避免过大的图片
                file_size = os.path.getsize(full_path)
                max_size = 5 * 1024 * 1024  # 5MB限制

                if file_size > max_size:
                    return f"""
**🖼️ 图片文件过大: {alt_text or os.path.basename(image_path)}**
- 📁 路径: `{image_path}`
- 📏 大小: {file_size / (1024 * 1024):.2f} MB (超过5MB限制)
- 💡 提示: 图片文件过大，无法在线显示，请通过文件管理器查看

---
"""

                # 读取图片文件并转换为base64
                with open(full_path, 'rb') as img_file:
                    img_data = img_file.read()
                    base64_data = base64.b64encode(img_data).decode('utf-8')

                # 创建data URL
                data_url = f'data:{mime_type};base64,{base64_data}'
                return f'![{alt_text}]({data_url})'

            except Exception as e:
                print(f'无法处理图片 {full_path}: {e}')
                return f"""
**❌ 图片处理失败: {alt_text or os.path.basename(image_path)}**
- 📁 路径: `{image_path}`
- ❌ 错误: {str(e)}

---
"""
        else:
            return f'**❌ 图片文件不存在: {alt_text or image_path}**\n\n'

    # 匹配markdown图片语法: ![alt](path)
    pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    return re.sub(pattern, replace_image, markdown_content)


def convert_markdown_images_to_urls(markdown_content: str,
                                    workdir: str,
                                    server_url: str = None) -> str:
    """将markdown中的相对路径图片转换为可访问的URL（本地环境使用）"""

    # 如果没有提供服务器URL，确保图片服务器运行
    if server_url is None:
        server_url = ensure_image_server_running(BASE_WORKDIR)
        if server_url is None:
            # 如果无法确保服务器运行，回退到base64方式
            return convert_markdown_images_to_base64(markdown_content, workdir)

    def replace_image(match):
        alt_text = match.group(1)
        image_path = match.group(2)

        # 处理相对路径
        if not os.path.isabs(image_path):
            full_path = os.path.join(workdir, image_path)
            # 计算相对于BASE_WORKDIR的路径
            rel_path = os.path.relpath(full_path, BASE_WORKDIR)
        else:
            full_path = image_path
            rel_path = os.path.relpath(full_path, BASE_WORKDIR)

        # 检查文件是否存在
        if os.path.exists(full_path):
            try:
                # 构建可访问的URL
                from urllib.parse import quote
                url_path = quote(rel_path.replace('\\', '/'))
                image_url = f'{server_url}/{url_path}'
                return f'![{alt_text}]({image_url})'
            except Exception as e:
                print(f'无法处理图片路径 {full_path}: {e}')
                return f'![{alt_text}]({image_path}) <!-- 图片路径处理失败 -->'
        else:
            return f'![{alt_text}]({image_path}) <!-- 图片文件不存在: {full_path} -->'

    # 匹配markdown图片语法: ![alt](path)
    pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    return re.sub(pattern, replace_image, markdown_content)


def convert_markdown_images_to_file_info(markdown_content: str,
                                         workdir: str) -> str:
    """将markdown中的图片转换为文件信息显示（回退方案）"""

    def replace_image(match):
        alt_text = match.group(1)
        image_path = match.group(2)

        # 处理相对路径
        if not os.path.isabs(image_path):
            full_path = os.path.join(workdir, image_path)
        else:
            full_path = image_path

        # 检查文件是否存在
        if os.path.exists(full_path):
            try:
                # 获取文件信息
                file_size = os.path.getsize(full_path)
                file_size_mb = file_size / (1024 * 1024)
                ext = os.path.splitext(full_path)[1].lower()

                return f"""
**🖼️ 图片文件: {alt_text or os.path.basename(image_path)}**
- 📁 路径: `{image_path}`
- 📏 大小: {file_size_mb:.2f} MB
- 🎨 格式: {ext.upper()}
- 💡 提示: 图片已保存到工作目录中，可通过文件管理器查看

---
"""
            except Exception as e:
                print(f'无法读取图片信息 {full_path}: {e}')
                return f'**❌ 图片加载失败: {alt_text or image_path}**\n\n'
        else:
            return f'**❌ 图片文件不存在: {alt_text or image_path}**\n\n'

    # 匹配markdown图片语法: ![alt](path)
    pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    return re.sub(pattern, replace_image, markdown_content)


def convert_markdown_to_html(markdown_content: str) -> str:
    """将markdown转换为HTML，使用KaTeX处理LaTeX公式"""
    try:
        import re

        # 保护LaTeX公式，避免被markdown处理器误处理
        latex_placeholders = {}
        placeholder_counter = 0

        def protect_latex(match):
            nonlocal placeholder_counter
            placeholder = f'LATEX_PLACEHOLDER_{placeholder_counter}'
            latex_placeholders[placeholder] = match.group(0)
            placeholder_counter += 1
            return placeholder

        # 保护各种LaTeX公式格式
        protected_content = markdown_content

        # 保护 $$...$$（块级公式）
        protected_content = re.sub(
            r'\$\$([^$]+?)\$\$',
            protect_latex,
            protected_content,
            flags=re.DOTALL)

        # 保护 $...$ （行内公式）
        protected_content = re.sub(r'(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)',
                                   protect_latex, protected_content)

        # 保护 \[...\]（块级公式）
        protected_content = re.sub(
            r'\\\[([^\\]+?)\\\]',
            protect_latex,
            protected_content,
            flags=re.DOTALL)

        # 保护 \(...\)（行内公式）
        protected_content = re.sub(
            r'\\\(([^\\]+?)\\\)',
            protect_latex,
            protected_content,
            flags=re.DOTALL)

        # 配置markdown扩展
        extensions = [
            'markdown.extensions.extra', 'markdown.extensions.codehilite',
            'markdown.extensions.toc', 'markdown.extensions.tables',
            'markdown.extensions.fenced_code', 'markdown.extensions.nl2br'
        ]

        # 配置扩展参数
        extension_configs = {
            'markdown.extensions.codehilite': {
                'css_class': 'highlight',
                'use_pygments': True
            },
            'markdown.extensions.toc': {
                'permalink': True
            }
        }

        # 创建markdown实例
        md = markdown.Markdown(
            extensions=extensions, extension_configs=extension_configs)

        # 转换为HTML
        html_content = md.convert(protected_content)

        # 恢复LaTeX公式
        for placeholder, latex_formula in latex_placeholders.items():
            html_content = html_content.replace(placeholder, latex_formula)

        # 生成唯一的容器ID，确保每次渲染都有独立的KaTeX处理
        container_id = f'katex-content-{int(time.time() * 1000000)}'

        # 使用KaTeX渲染LaTeX公式
        styled_html = f"""
        <div class="markdown-html-content" id="{container_id}">
            <!-- KaTeX CSS -->
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css" integrity="sha384-n8MVd4RsNIU0tAv4ct0nTaAbDJwPJzDEaqSD1odI+WdtXRGWt2kTvGFasHpSy3SV" crossorigin="anonymous">

            <!-- 内容区域 -->
            <div class="content-area">
                {html_content}
            </div>

            <!-- KaTeX JavaScript和auto-render扩展 -->
            <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js" integrity="sha384-XjKyOOlGwcjNTAIQHIpVOOVA+CuTF5UvLqGSXPM6njWx5iNxN7jyVjNOq8Ks4pxy" crossorigin="anonymous"></script>
            <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js" integrity="sha384-+VBxd3r6XgURycqtZ117nYw44OOcIax56Z4dCRWbxyPt0Koah1uHoK0o4+/RRE05" crossorigin="anonymous"></script>

            <!-- KaTeX渲染脚本 -->
            <script type="text/javascript">
                (function() {{
                    const containerId = '{container_id}';
                    const container = document.getElementById(containerId);

                    if (!container) {{
                        console.warn('KaTeX容器未找到:', containerId);
                        return;
                    }}

                    // 等待KaTeX加载完成后渲染
                    function renderKaTeX() {{
                        if (typeof renderMathInElement !== 'undefined') {{
                            console.log('开始KaTeX渲染 - 容器:', containerId);

                            try {{
                                renderMathInElement(container, {{
                                    // 配置分隔符
                                    delimiters: [
                                        {{left: '$$', right: '$$', display: true}},
                                        {{left: '$', right: '$', display: false}},
                                        {{left: '\\\\[', right: '\\\\]', display: true}},
                                        {{left: '\\\\(', right: '\\\\)', display: false}}
                                    ],
                                    // 其他配置选项
                                    throwOnError: false,
                                    errorColor: '#cc0000',
                                    strict: false,
                                    trust: false,
                                    macros: {{
                                        "\\\\RR": "\\\\mathbb{{R}}",
                                        "\\\\NN": "\\\\mathbb{{N}}",
                                        "\\\\ZZ": "\\\\mathbb{{Z}}",
                                        "\\\\QQ": "\\\\mathbb{{Q}}",
                                        "\\\\CC": "\\\\mathbb{{C}}"
                                    }}
                                }});

                                console.log('KaTeX渲染完成 - 容器:', containerId);

                                // 统计渲染的公式数量
                                const mathElements = container.querySelectorAll('.katex');
                                console.log('发现并处理了', mathElements.length, '个数学公式');

                                // 应用样式修正
                                mathElements.forEach(el => {{
                                    const isDisplay = el.classList.contains('katex-display');
                                    if (isDisplay) {{
                                        el.style.margin = '1em 0';
                                        el.style.textAlign = 'center';
                                    }} else {{
                                        el.style.margin = '0 0.2em';
                                        el.style.verticalAlign = 'baseline';
                                    }}
                                }});

                            }} catch (error) {{
                                console.error('KaTeX渲染错误:', error);
                            }}
                        }} else {{
                            console.warn('KaTeX auto-render未加载，等待重试...');
                            setTimeout(renderKaTeX, 200);
                        }}
                    }}

                    // 使用延迟确保Gradio完全渲染完成
                    setTimeout(() => {{
                        console.log('开始加载KaTeX...');
                        renderKaTeX();
                    }}, 300);
                }})();
            </script>

            <style>
                #{container_id} {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 100%;
                    margin: 0 auto;
                    padding: 20px;
                }}

                /* KaTeX公式样式优化 */
                #{container_id} .katex {{
                    font-size: 1.1em !important;
                    color: inherit !important;
                }}

                #{container_id} .katex-display {{
                    margin: 1em 0 !important;
                    text-align: center !important;
                    overflow-x: auto !important;
                    display: block !important;
                }}

                /* 行内公式样式 */
                #{container_id} .katex:not(.katex-display) {{
                    display: inline-block !important;
                    margin: 0 0.1em !important;
                    vertical-align: baseline !important;
                }}

                /* 公式溢出处理 */
                #{container_id} .katex .katex-html {{
                    max-width: 100% !important;
                    overflow-x: auto !important;
                }}

                /* 确保LaTeX公式在Gradio中正确显示 */
                #{container_id} .katex {{
                    line-height: normal !important;
                }}

                #{container_id} h1 {{
                    font-size: 2.2em;
                    margin-bottom: 1rem;
                    color: #2c3e50;
                    border-bottom: 2px solid #3498db;
                    padding-bottom: 0.5rem;
                }}

                #{container_id} h2 {{
                    font-size: 1.8em;
                    margin-bottom: 0.8rem;
                    color: #34495e;
                    border-bottom: 1px solid #bdc3c7;
                    padding-bottom: 0.3rem;
                }}

                #{container_id} h3 {{
                    font-size: 1.5em;
                    margin-bottom: 0.6rem;
                    color: #34495e;
                }}

                #{container_id} h4, #{container_id} h5, #{container_id} h6 {{
                    color: #34495e;
                    margin-bottom: 0.5rem;
                }}

                #{container_id} p {{
                    margin-bottom: 1rem;
                    text-align: justify;
                }}

                #{container_id} img {{
                    max-width: 100%;
                    height: auto;
                    border-radius: 8px;
                    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                    margin: 1rem 0;
                    display: block;
                    margin-left: auto;
                    margin-right: auto;
                }}

                #{container_id} ul, #{container_id} ol {{
                    margin-bottom: 1rem;
                    padding-left: 2rem;
                }}

                #{container_id} li {{
                    margin-bottom: 0.3rem;
                }}

                #{container_id} blockquote {{
                    background: #f8f9fa;
                    border-left: 4px solid #3498db;
                    padding: 1rem;
                    margin: 1rem 0;
                    border-radius: 0 4px 4px 0;
                    font-style: italic;
                }}

                #{container_id} code {{
                    background: #f1f2f6;
                    padding: 0.2rem 0.4rem;
                    border-radius: 3px;
                    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
                    font-size: 0.9em;
                    color: #e74c3c;
                }}

                #{container_id} pre {{
                    background: #2c3e50;
                    color: #ecf0f1;
                    padding: 1rem;
                    border-radius: 6px;
                    overflow-x: auto;
                    margin: 1rem 0;
                    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
                }}

                #{container_id} pre code {{
                    background: transparent;
                    padding: 0;
                    color: inherit;
                }}

                #{container_id} table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 1rem 0;
                    background: white;
                    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                    border-radius: 6px;
                    overflow: hidden;
                }}

                #{container_id} th, #{container_id} td {{
                    padding: 0.75rem;
                    text-align: left;
                    border-bottom: 1px solid #ddd;
                }}

                #{container_id} th {{
                    background: #3498db;
                    color: white;
                    font-weight: 600;
                }}

                #{container_id} tr:nth-child(even) {{
                    background: #f8f9fa;
                }}

                #{container_id} a {{
                    color: #3498db;
                    text-decoration: none;
                    border-bottom: 1px solid transparent;
                    transition: border-bottom-color 0.2s ease;
                }}

                #{container_id} a:hover {{
                    border-bottom-color: #3498db;
                }}

                #{container_id} hr {{
                    border: none;
                    height: 2px;
                    background: linear-gradient(to right, #3498db, #2ecc71);
                    margin: 2rem 0;
                    border-radius: 1px;
                }}

                #{container_id} .highlight {{
                    background: #2c3e50;
                    color: #ecf0f1;
                    padding: 1rem;
                    border-radius: 6px;
                    overflow-x: auto;
                    margin: 1rem 0;
                }}

                /* 深色主题适配 */
                @media (prefers-color-scheme: dark) {{
                    #{container_id} {{
                        color: #ecf0f1;
                        background: #2c3e50;
                    }}

                    #{container_id} h1, #{container_id} h2, #{container_id} h3,
                    #{container_id} h4, #{container_id} h5, #{container_id} h6 {{
                        color: #ecf0f1;
                    }}

                    #{container_id} h1 {{
                        border-bottom-color: #3498db;
                    }}

                    #{container_id} h2 {{
                        border-bottom-color: #7f8c8d;
                    }}

                    #{container_id} blockquote {{
                        background: #34495e;
                        color: #ecf0f1;
                    }}

                    #{container_id} code {{
                        background: #34495e;
                        color: #e74c3c;
                    }}

                    #{container_id} table {{
                        background: #34495e;
                    }}

                    #{container_id} th {{
                        background: #2980b9;
                    }}

                    #{container_id} tr:nth-child(even) {{
                        background: #2c3e50;
                    }}

                    #{container_id} td {{
                        border-bottom-color: #7f8c8d;
                    }}

                    #{container_id} .katex {{
                        color: #ecf0f1 !important;
                    }}

                    #{container_id} .katex .katex-html {{
                        color: #ecf0f1 !important;
                    }}
                }}

                /* 响应式设计 */
                @media (max-width: 768px) {{
                    #{container_id} {{
                        padding: 15px;
                        font-size: 14px;
                    }}

                    #{container_id} h1 {{
                        font-size: 1.8em;
                    }}

                    #{container_id} h2 {{
                        font-size: 1.5em;
                    }}

                    #{container_id} h3 {{
                        font-size: 1.3em;
                    }}

                    #{container_id} table {{
                        font-size: 12px;
                    }}

                    #{container_id} th, #{container_id} td {{
                        padding: 0.5rem;
                    }}

                    /* 移动端KaTeX优化 */
                    #{container_id} .katex {{
                        font-size: 1em !important;
                    }}
                }}
            </style>
        </div>
        """

        return styled_html

    except Exception as e:
        print(f'Markdown转HTML失败: {e}')
        # 如果转换失败，返回原始markdown内容包装在pre标签中
        return f"""
        <div class="markdown-fallback">
            <h3>⚠️ Markdown渲染失败，显示原始内容</h3>
            <pre style="white-space: pre-wrap; word-wrap: break-word; background: #f8f9fa; padding: 1rem; border-radius: 6px; border: 1px solid #dee2e6;">{markdown_content}</pre>
        </div>
        """


def read_markdown_report(workdir: str) -> Tuple[str, str, str]:
    """读取并处理markdown报告，返回markdown和html两种格式"""
    report_path = os.path.join(workdir, 'report.md')

    if not os.path.exists(report_path):
        return '', '', '未找到报告文件 report.md'

    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()

        # 统一使用base64方式处理图片
        try:
            processed_markdown = convert_markdown_images_to_base64(
                markdown_content, workdir)
        except Exception as e:
            print(f'base64转换失败，使用文件信息显示: {e}')
            processed_markdown = convert_markdown_images_to_file_info(
                markdown_content, workdir)

        # 检查是否为非local_mode，如果是则转换为HTML
        local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'
        if not local_mode:
            try:
                processed_html = convert_markdown_to_html(processed_markdown)
            except Exception as e:
                print(f'HTML转换失败，使用markdown显示: {e}')
                processed_html = processed_markdown
        else:
            processed_html = processed_markdown

        return processed_markdown, processed_html, ''
    except Exception as e:
        return '', '', f'读取报告文件失败: {str(e)}'


def list_resources_files(workdir: str) -> str:
    """列出resources文件夹中的文件"""
    resources_path = os.path.join(workdir, 'resources')

    if not os.path.exists(resources_path):
        return '未找到 resources 文件夹'

    try:
        files = []
        for root, dirs, filenames in os.walk(resources_path):
            for filename in filenames:
                rel_path = os.path.relpath(
                    os.path.join(root, filename), workdir)
                files.append(rel_path)

        if files:
            return '📁 资源文件列表:\n' + '\n'.join(f'• {file}'
                                             for file in sorted(files))
        else:
            return 'resources 文件夹为空'
    except Exception as e:
        return f'读取资源文件失败: {str(e)}'


def run_research_workflow_internal(
        user_prompt: str,
        uploaded_files,
        urls_text: str,
        user_id: str,
        progress_callback=None) -> Tuple[str, str, str, str, str]:
    """内部研究工作流执行函数"""
    try:
        if progress_callback:
            progress_callback(0.02, '验证输入参数...')

        # 处理文件和URLs
        file_paths = process_files(uploaded_files)
        urls = process_urls_text(urls_text)

        # 合并文件路径和URLs
        urls_or_files = file_paths + urls

        if progress_callback:
            progress_callback(0.05, '初始化工作环境...')

        # 创建新的工作目录
        task_workdir = create_task_workdir(user_id)

        user_prompt = user_prompt.strip() or '请深入分析和总结下列文档：'

        if progress_callback:
            progress_callback(0.10, '初始化AI客户端...')

        # 初始化聊天客户端
        chat_client = OpenAIChat(
            api_key=os.environ.get('OPENAI_API_KEY'),
            base_url=os.environ.get('OPENAI_BASE_URL'),
            model=os.environ.get('OPENAI_MODEL_ID'),
        )

        if progress_callback:
            progress_callback(0.15, '创建研究工作流...')

        # 创建研究工作流
        research_workflow = ResearchWorkflowExtend(
            client=chat_client,
            workdir=task_workdir,
        )

        if progress_callback:
            progress_callback(0.20, '开始执行研究工作流...')

        # 运行工作流 - 这一步占大部分进度
        result = research_workflow.run(
            user_prompt=user_prompt,
            urls_or_files=urls_or_files,
        )

        if progress_callback:
            progress_callback(0.90, '处理研究报告...')

        # 读取markdown报告
        markdown_report, html_report, report_error = read_markdown_report(
            task_workdir)

        if progress_callback:
            progress_callback(0.95, '整理资源文件...')

        # 列出资源文件
        resources_info = list_resources_files(task_workdir)

        if progress_callback:
            progress_callback(1.0, '任务完成！')

        return result, task_workdir, markdown_report, html_report, resources_info

    except Exception as e:
        error_msg = f'❌ 执行过程中发生错误：{str(e)}'
        return error_msg, '', '', '', ''


def run_research_workflow(
    user_prompt: str,
    uploaded_files,
    urls_text: str,
    request: gr.Request,
    progress=gr.Progress()) -> Tuple[str, str, str, str, str]:
    """运行研究工作流（使用Gradio内置队列控制）"""
    try:
        # 检查LOCAL_MODE环境变量，默认为true
        local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

        if not local_mode:
            # 检查用户认证
            is_authenticated, user_id_or_error = check_user_auth(request)
            if not is_authenticated:
                return f'❌ 认证失败：{user_id_or_error}', '', '', '', ''

            user_id = user_id_or_error
        else:
            # 本地模式，使用默认用户ID加上时间戳避免冲突
            user_id = f'local_user_{int(time.time() * 1000)}'

        progress(0.01, desc='开始执行任务...')

        # 标记用户任务开始
        user_status_manager.start_user_task(user_id)

        # 创建进度回调函数
        def progress_callback(value, desc):
            # 将内部进度映射到0.05-0.95范围
            mapped_progress = 0.05 + (value * 0.9)
            progress(mapped_progress, desc=desc)

        try:
            # 直接执行任务，由Gradio队列控制并发
            result = run_research_workflow_internal(user_prompt,
                                                    uploaded_files, urls_text,
                                                    user_id, progress_callback)

            progress(1.0, desc='任务完成！')
            return result

        except Exception as e:
            print(f'任务执行异常 - 用户: {user_id[:8]}***, 错误: {str(e)}')
            error_msg = f'❌ 任务执行失败：{str(e)}'
            return error_msg, '', '', '', ''
        finally:
            # 确保清理用户状态
            user_status_manager.finish_user_task(user_id)

    except Exception as e:
        error_msg = f'❌ 系统错误：{str(e)}'
        return error_msg, '', '', '', ''


def clear_workspace(request: gr.Request):
    """清理工作空间"""
    try:
        # 检查LOCAL_MODE环境变量，默认为true
        local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

        if not local_mode:
            # 检查用户认证
            is_authenticated, user_id_or_error = check_user_auth(request)
            if not is_authenticated:
                return f'❌ 认证失败：{user_id_or_error}', '', ''

            user_id = user_id_or_error
        else:
            # 本地模式，使用默认用户ID
            user_id = 'local_user'

        user_workdir = create_user_workdir(user_id)

        if os.path.exists(user_workdir):
            shutil.rmtree(user_workdir)
        return '✅ 工作空间已清理', '', ''
    except Exception as e:
        return f'❌ 清理失败：{str(e)}', '', ''


def get_session_file_path(user_id: str) -> str:
    """获取用户专属的会话文件路径"""
    user_workdir = create_user_workdir(user_id)
    return os.path.join(user_workdir, 'session_data.json')


def save_session_data(data, user_id: str):
    """保存会话数据到文件"""
    try:
        session_file = get_session_file_path(user_id)
        os.makedirs(os.path.dirname(session_file), exist_ok=True)
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'保存会话数据失败: {e}')


def load_session_data(user_id: str):
    """从文件加载会话数据"""
    try:
        session_file = get_session_file_path(user_id)
        if os.path.exists(session_file):
            with open(session_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f'加载会话数据失败: {e}')

    # 返回默认数据
    return {
        'workdir': '',
        'result': '',
        'markdown': '',
        'resources': '',
        'user_prompt': '',
        'urls_text': '',
        'timestamp': ''
    }


def get_user_status_html(request: gr.Request) -> str:
    # To be removed in future versions
    return ''


def get_system_status_html() -> str:
    """获取系统状态HTML"""
    local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

    if local_mode:
        return ''  # 本地模式不显示系统状态信息

    system_status = user_status_manager.get_system_status()

    status_html = f"""
    <div class="status-indicator status-info">
        🖥️ 系统状态 | 活跃任务: {system_status['active_tasks']}/{system_status['max_concurrent']} | 可用槽位: {system_status['available_slots']}
    </div>
    """

    if system_status['task_details']:
        status_html += "<div style='margin-top: 0.5rem; font-size: 0.9rem; color: #666;'>"
        status_html += '<strong>活跃任务详情:</strong><br>'
        for user_id, details in system_status['task_details'].items():
            masked_id = user_id[:8] + '***' if len(user_id) > 8 else user_id
            status_html += f"• {masked_id}: {details['status']} ({details['elapsed_time']:.1f}s)<br>"
        status_html += '</div>'

    return status_html


# 创建Gradio界面
def create_interface():
    with gr.Blocks(
            title='研究工作流应用 | Research Workflow App',
            theme=gr.themes.Soft(),
            css="""
        /* 响应式容器设置 */
        .gradio-container {
            max-width: none !important;
            width: 100% !important;
            padding: 0 1rem !important;
        }

        /* 非local_mode HTML报告滚动样式 */
        .scrollable-html-report {
            height: 650px !important;
            overflow-y: auto !important;
            border: 1px solid var(--border-color-primary) !important;
            border-radius: 0.5rem !important;
            padding: 1rem !important;
            background: var(--background-fill-primary) !important;
        }

        /* HTML报告内容区域样式 */
        #html-report {
            height: 650px !important;
            overflow-y: auto !important;
        }

        /* 全屏模式下的HTML报告滚动 */
        #fullscreen-html {
            height: calc(100vh - 2.5rem) !important;
            overflow-y: auto !important;
        }

        /* HTML报告滚动条美化 */
        .scrollable-html-report::-webkit-scrollbar,
        #html-report::-webkit-scrollbar,
        #fullscreen-html::-webkit-scrollbar {
            width: 12px !important;
        }

        .scrollable-html-report::-webkit-scrollbar-track,
        #html-report::-webkit-scrollbar-track,
        #fullscreen-html::-webkit-scrollbar-track {
            background: var(--background-fill-secondary) !important;
            border-radius: 6px !important;
        }

        .scrollable-html-report::-webkit-scrollbar-thumb,
        #html-report::-webkit-scrollbar-thumb,
        #fullscreen-html::-webkit-scrollbar-thumb {
            background: var(--border-color-primary) !important;
            border-radius: 6px !important;
        }

        .scrollable-html-report::-webkit-scrollbar-thumb:hover,
        #html-report::-webkit-scrollbar-thumb:hover,
        #fullscreen-html::-webkit-scrollbar-thumb:hover {
            background: var(--color-accent) !important;
        }

        /* 确保HTML内容在容器内正确显示 */
        .scrollable-html-report .markdown-html-content {
            max-width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        /* 响应式适配 */
        @media (max-width: 768px) {
            .scrollable-html-report,
            #html-report {
                height: 500px !important;
                padding: 0.75rem !important;
            }

            #fullscreen-html {
                height: calc(100vh - 2rem) !important;
            }

            #fullscreen-modal {
                padding: 0.25rem !important;
            }

            #fullscreen-modal .gr-column {
                padding: 0.5rem !important;
                height: calc(100vh - 0.5rem) !important;
            }

            #fullscreen-markdown {
                height: calc(100vh - 1.5rem) !important;
            }
        }

        @media (max-width: 480px) {
            .scrollable-html-report,
            #html-report {
                height: 400px !important;
                padding: 0.5rem !important;
            }

            #fullscreen-html {
                height: calc(100vh - 1.5rem) !important;
            }

            #fullscreen-modal {
                padding: 0.25rem !important;
            }

            #fullscreen-modal .gr-column {
                padding: 0.25rem !important;
                height: calc(100vh - 0.5rem) !important;
            }

            #fullscreen-markdown {
                height: calc(100vh - 1rem) !important;
            }
        }

        /* 全屏模态框样式 */
        #fullscreen-modal {
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            background: var(--background-fill-primary) !important;
            z-index: 9999 !important;
            padding: 0.5rem !important;
            box-sizing: border-box !important;
        }

        #fullscreen-modal .gr-column {
            background: var(--background-fill-primary) !important;
            border: 1px solid var(--border-color-primary) !important;
            border-radius: 0.5rem !important;
            padding: 0.5rem !important;
            height: calc(100vh - 1rem) !important;
            overflow: hidden !important;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.15) !important;
        }

        #fullscreen-markdown {
            height: calc(100vh - 2.5rem) !important;
            overflow-y: auto !important;
            background: var(--background-fill-primary) !important;
            color: var(--body-text-color) !important;
        }

        #fullscreen-btn {
            min-width: 40px !important;
            height: 40px !important;
            padding: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-size: 1.2rem !important;
            margin-bottom: 0.5rem !important;
        }

        #close-btn {
            min-width: 30px !important;
            height: 30px !important;
            padding: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-size: 1.2rem !important;
            margin-left: auto !important;
            background: var(--button-secondary-background-fill) !important;
            color: var(--button-secondary-text-color) !important;
            border: 1px solid var(--border-color-primary) !important;
        }

        #close-btn:hover {
            background: var(--button-secondary-background-fill-hover) !important;
        }

        /* 全屏模式标题样式 */
        #fullscreen-modal h3 {
            color: var(--body-text-color) !important;
            margin: 0 !important;
            flex: 1 !important;
            font-size: 1.1rem !important;
        }

        /* 全屏模式下的markdown样式优化 */
        #fullscreen-markdown .gr-markdown {
            font-size: 1.1rem !important;
            line-height: 1.7 !important;
            color: var(--body-text-color) !important;
            background: var(--background-fill-primary) !important;
        }

        #fullscreen-markdown .gr-markdown * {
            color: inherit !important;
        }

        #fullscreen-markdown h1 {
            font-size: 2.2rem !important;
            margin-bottom: 1.5rem !important;
            color: var(--body-text-color) !important;
            border-bottom: 2px solid var(--border-color-primary) !important;
            padding-bottom: 0.5rem !important;
        }

        #fullscreen-markdown h2 {
            font-size: 1.8rem !important;
            margin-bottom: 1.2rem !important;
            color: var(--body-text-color) !important;
            border-bottom: 1px solid var(--border-color-primary) !important;
            padding-bottom: 0.3rem !important;
        }

        #fullscreen-markdown h3 {
            font-size: 1.5rem !important;
            margin-bottom: 1rem !important;
            color: var(--body-text-color) !important;
        }

        #fullscreen-markdown h4,
        #fullscreen-markdown h5,
        #fullscreen-markdown h6 {
            color: var(--body-text-color) !important;
            margin-bottom: 0.8rem !important;
        }

        #fullscreen-markdown p {
            color: var(--body-text-color) !important;
            margin-bottom: 1rem !important;
        }

        #fullscreen-markdown ul,
        #fullscreen-markdown ol {
            color: var(--body-text-color) !important;
            margin-bottom: 1rem !important;
            padding-left: 1.5rem !important;
        }

        #fullscreen-markdown li {
            color: var(--body-text-color) !important;
            margin-bottom: 0.3rem !important;
        }

        #fullscreen-markdown strong,
        #fullscreen-markdown b {
            color: var(--body-text-color) !important;
            font-weight: 600 !important;
        }

        #fullscreen-markdown em,
        #fullscreen-markdown i {
            color: var(--body-text-color) !important;
        }

        #fullscreen-markdown a {
            color: var(--link-text-color) !important;
            text-decoration: none !important;
        }

        #fullscreen-markdown a:hover {
            color: var(--link-text-color-hover) !important;
            text-decoration: underline !important;
        }

        #fullscreen-markdown blockquote {
            background: var(--background-fill-secondary) !important;
            border-left: 4px solid var(--color-accent) !important;
            padding: 1rem !important;
            margin: 1rem 0 !important;
            color: var(--body-text-color) !important;
            border-radius: 0 0.5rem 0.5rem 0 !important;
        }

        #fullscreen-markdown img {
            max-width: 100% !important;
            height: auto !important;
            border-radius: 0.5rem !important;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1) !important;
            margin: 1rem 0 !important;
        }

        #fullscreen-markdown pre {
            background: var(--background-fill-secondary) !important;
            color: var(--body-text-color) !important;
            padding: 1rem !important;
            border-radius: 0.5rem !important;
            overflow-x: auto !important;
            font-size: 0.95rem !important;
            border: 1px solid var(--border-color-primary) !important;
            margin: 1rem 0 !important;
        }

        #fullscreen-markdown code {
            background: var(--background-fill-secondary) !important;
            color: var(--body-text-color) !important;
            padding: 0.2rem 0.4rem !important;
            border-radius: 0.25rem !important;
            font-size: 0.9rem !important;
            border: 1px solid var(--border-color-primary) !important;
        }

        #fullscreen-markdown pre code {
            background: transparent !important;
            padding: 0 !important;
            border: none !important;
        }

        #fullscreen-markdown table {
            width: 100% !important;
            border-collapse: collapse !important;
            margin: 1rem 0 !important;
            background: var(--background-fill-primary) !important;
        }

        #fullscreen-markdown th,
        #fullscreen-markdown td {
            padding: 0.75rem !important;
            border: 1px solid var(--border-color-primary) !important;
            color: var(--body-text-color) !important;
        }

        #fullscreen-markdown th {
            background: var(--background-fill-secondary) !important;
            font-weight: 600 !important;
        }

        #fullscreen-markdown tr:nth-child(even) {
            background: var(--background-fill-secondary) !important;
        }

        #fullscreen-markdown hr {
            border: none !important;
            height: 1px !important;
            background: var(--border-color-primary) !important;
            margin: 2rem 0 !important;
        }

        /* 全屏模式滚动条样式 */
        #fullscreen-markdown::-webkit-scrollbar {
            width: 12px !important;
        }

        #fullscreen-markdown::-webkit-scrollbar-track {
            background: var(--background-fill-secondary) !important;
            border-radius: 6px !important;
        }

        #fullscreen-markdown::-webkit-scrollbar-thumb {
            background: var(--border-color-primary) !important;
            border-radius: 6px !important;
        }

        #fullscreen-markdown::-webkit-scrollbar-thumb:hover {
            background: var(--color-accent) !important;
        }

        /* 深色主题特殊适配 */
        @media (prefers-color-scheme: dark) {
            #fullscreen-modal {
                background: var(--background-fill-primary) !important;
            }

            #fullscreen-markdown img {
                box-shadow: 0 4px 6px rgba(255, 255, 255, 0.1) !important;
            }
        }

        .dark #fullscreen-modal {
            background: var(--background-fill-primary) !important;
        }

        .dark #fullscreen-markdown img {
            box-shadow: 0 4px 6px rgba(255, 255, 255, 0.1) !important;
        }

        /* 大屏幕适配 */
        @media (min-width: 1400px) {
            .gradio-container {
                max-width: 1600px !important;
                margin: 0 auto !important;
                padding: 0 2rem !important;
            }
        }

        @media (min-width: 1800px) {
            .gradio-container {
                max-width: 1800px !important;
                padding: 0 3rem !important;
            }
        }

        /* 主标题样式 */
        .main-header {
            text-align: center;
            margin-bottom: 2rem;
            padding: 1rem 0;
        }

        .main-header h1 {
            font-size: clamp(1.8rem, 4vw, 3rem);
            margin-bottom: 0.5rem;
        }

        .main-header h2 {
            font-size: clamp(1.2rem, 2.5vw, 2rem);
            margin-bottom: 0.5rem;
            color: #6b7280;
        }

        /* 描述文本样式 */
        .description {
            font-size: clamp(1rem, 1.8vw, 1.2rem);
            color: #6b7280;
            margin-bottom: 0.5rem;
            font-weight: 500;
            line-height: 1.5;
        }

        /* Powered by 样式 */
        .powered-by {
            font-size: clamp(0.85rem, 1.2vw, 1rem);
            color: #9ca3af;
            margin-top: 0.25rem;
            font-weight: 400;
        }

        .powered-by a {
            color: #06b6d4;
            text-decoration: none;
            font-weight: normal;
            transition: color 0.2s ease;
        }

        .powered-by a:hover {
            color: #0891b2;
            text-decoration: underline;
        }

        /* 深色主题适配 */
        @media (prefers-color-scheme: dark) {
            .description {
                color: #9ca3af;
            }

            .powered-by {
                color: #6b7280;
            }

            .powered-by a {
                color: #22d3ee;
                font-weight: normal;
            }

            .powered-by a:hover {
                color: #67e8f9;
            }
        }

        .dark .description {
            color: #9ca3af;
        }

        .dark .powered-by {
            color: #6b7280;
        }

        .dark .powered-by a {
            color: #22d3ee;
            font-weight: normal;
        }

        .dark .powered-by a:hover {
            color: #67e8f9;
        }

        /* 区域标题 */
        .section-header {
            color: #2563eb;
            font-weight: 600;
            margin: 1rem 0 0.5rem 0;
            font-size: clamp(1rem, 1.8vw, 1.3rem);
        }

        /* 状态指示器 */
        .status-indicator {
            padding: 0.75rem 1rem;
            border-radius: 0.5rem;
            margin: 0.5rem 0;
            font-size: clamp(0.85rem, 1.2vw, 1rem);
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        .status-success {
            background-color: #dcfce7;
            color: #166534;
            border: 1px solid #bbf7d0;
        }

        .status-info {
            background-color: #dbeafe;
            color: #1e40af;
            border: 1px solid #bfdbfe;
        }

        /* 输入组件优化 */
        .gr-textbox, .gr-file {
            font-size: clamp(0.85rem, 1.1vw, 1rem) !important;
        }

        /* 按钮样式优化 */
        .gr-button {
            font-size: clamp(0.9rem, 1.2vw, 1.1rem) !important;
            padding: 0.75rem 1.5rem !important;
            border-radius: 0.5rem !important;
            font-weight: 500 !important;
        }

        /* Tab标签优化 */
        .gr-tab-nav {
            font-size: clamp(0.85rem, 1.1vw, 1rem) !important;
        }

        /* 输出区域优化 */
        .gr-markdown {
            font-size: clamp(0.85rem, 1vw, 1rem) !important;
            line-height: 1.6 !important;
        }

        /* 使用说明区域 */
        .instructions {
            margin-top: 2rem;
            padding: 1.5rem;
            background-color: var(--background-fill-secondary);
            border-radius: 0.75rem;
            border: 1px solid var(--border-color-primary);
        }

        .instructions h4 {
            font-size: clamp(1rem, 1.5vw, 1.2rem);
            margin-bottom: 1rem;
            color: var(--body-text-color);
        }

        .instructions-subtitle {
            color: var(--body-text-color);
            margin-bottom: 0.75rem;
            font-size: 1.1rem;
            font-weight: 600;
        }

        .instructions-list {
            font-size: clamp(0.85rem, 1.1vw, 1rem);
            line-height: 1.6;
            margin: 0;
            padding-left: 1.2rem;
            color: var(--body-text-color);
        }

        .instructions-list li {
            margin-bottom: 0.5rem;
            color: var(--body-text-color);
        }

        .instructions-list strong {
            color: var(--body-text-color);
            font-weight: 600;
        }

        /* 深色主题适配 */
        @media (prefers-color-scheme: dark) {
            .instructions {
                background-color: rgba(255, 255, 255, 0.05);
                border-color: rgba(255, 255, 255, 0.1);
            }

            .instructions h4,
            .instructions-subtitle,
            .instructions-list,
            .instructions-list li,
            .instructions-list strong {
                color: rgba(255, 255, 255, 0.9) !important;
            }
        }

        /* Gradio 深色主题适配 */
        .dark .instructions {
            background-color: rgba(255, 255, 255, 0.05);
            border-color: rgba(255, 255, 255, 0.1);
        }

        .dark .instructions h4,
        .dark .instructions-subtitle,
        .dark .instructions-list,
        .dark .instructions-list li,
        .dark .instructions-list strong {
            color: rgba(255, 255, 255, 0.9) !important;
        }

        /* 响应式列布局 */
        @media (max-width: 768px) {
            .gr-row {
                flex-direction: column !important;
            }

            .gr-column {
                width: 100% !important;
                margin-bottom: 1rem !important;
            }
        }

        /* 大屏幕下的列宽优化 */
        @media (min-width: 1400px) {
            .input-column {
                min-width: 500px !important;
            }

            .output-column {
                min-width: 700px !important;
            }
        }

        /* 滚动条美化 */
        .gr-textbox textarea::-webkit-scrollbar,
        .gr-markdown::-webkit-scrollbar {
            width: 8px;
        }

        .gr-textbox textarea::-webkit-scrollbar-track,
        .gr-markdown::-webkit-scrollbar-track {
            background: #f1f5f9;
            border-radius: 4px;
        }

        .gr-textbox textarea::-webkit-scrollbar-thumb,
        .gr-markdown::-webkit-scrollbar-thumb {
            background: #cbd5e1;
            border-radius: 4px;
        }

        .gr-textbox textarea::-webkit-scrollbar-thumb:hover,
        .gr-markdown::-webkit-scrollbar-thumb:hover {
            background: #94a3b8;
        }
        """) as demo:

        # 状态管理 - 用于保持数据持久性
        current_workdir = gr.State('')
        current_result = gr.State('')
        current_markdown = gr.State('')
        current_html = gr.State('')
        current_resources = gr.State('')
        current_user_prompt = gr.State('')
        current_urls_text = gr.State('')

        gr.HTML("""
        <div class="main-header">
            <h1>🔬 文档深度研究</h1>
            <h2>Doc Research Workflow</h2>
            <p class="description">Your Daily Paper Copilot - URLs or Files IN, Multimodal Report OUT</p>
            <p class="powered-by">Powered by <a href="https://github.com/modelscope/ms-agent" target="_blank" rel="noopener noreferrer">MS-Agent</a></p>
        </div>
        """)

        # 用户状态显示
        user_status = gr.HTML()

        # 系统状态显示
        system_status = gr.HTML()

        with gr.Row():
            with gr.Column(scale=2, elem_classes=['input-column']):
                gr.HTML('<h3 class="section-header">📝 输入区域 | Input Area</h3>')

                # 用户提示输入
                user_prompt = gr.Textbox(
                    label='用户提示 | User Prompt',
                    placeholder=
                    '请输入您的研究问题或任务描述(可为空)...\nPlease enter your research question or task description (Optional)...',
                    lines=4,
                    max_lines=8)

                with gr.Row():
                    with gr.Column():
                        # 文件上传
                        uploaded_files = gr.File(
                            label='上传文件 | Upload Files',
                            file_count='multiple',
                            file_types=None,
                            interactive=True,
                            height=120)

                    with gr.Column():
                        # URLs输入
                        urls_text = gr.Textbox(
                            label='URLs输入 | URLs Input',
                            placeholder=
                            '请输入URLs，每行一个...\nEnter URLs, one per line...\n\nhttps://example1.com\nhttps://example2.com',
                            lines=6,
                            max_lines=10)

                # 运行按钮
                run_btn = gr.Button(
                    '🚀 开始研究 | Start Research', variant='primary', size='lg')

                # 清理按钮
                clear_btn = gr.Button(
                    '🧹 清理工作空间 | Clear Workspace', variant='secondary')

                # 恢复按钮
                restore_btn = gr.Button(
                    '🔄 重载最近结果 | Reload Latest Results', variant='secondary')

                # 会话状态指示器
                session_status = gr.HTML()

                # 刷新系统状态按钮
                refresh_status_btn = gr.Button(
                    '🔄 刷新系统状态 | Refresh System Status',
                    variant='secondary',
                    size='sm')

            with gr.Column(scale=3, elem_classes=['output-column']):
                gr.HTML('<h3 class="section-header">📊 输出区域 | Output Area</h3>')

                with gr.Tabs():
                    with gr.TabItem('📋 执行结果 | Results'):
                        # 结果显示
                        result_output = gr.Textbox(
                            label='执行结果 | Execution Results',
                            lines=22,
                            max_lines=25,
                            interactive=False,
                            show_copy_button=True)

                        # 工作目录显示
                        workdir_output = gr.Textbox(
                            label='工作目录 | Working Directory',
                            lines=2,
                            interactive=False,
                            show_copy_button=True)

                    with gr.TabItem('📄 研究报告 | Research Report'):
                        # 检查是否为非local_mode来决定显示格式
                        local_mode = os.environ.get('LOCAL_MODE',
                                                    'true').lower() == 'true'

                        if local_mode:
                            # Local模式：显示Markdown
                            with gr.Row():
                                with gr.Column(scale=10):
                                    # Markdown报告显示
                                    markdown_output = gr.Markdown(
                                        label='Markdown报告 | Markdown Report',
                                        height=650)
                                with gr.Column(scale=1, min_width=50):
                                    # 全屏按钮
                                    fullscreen_btn = gr.Button(
                                        '⛶',
                                        size='sm',
                                        variant='secondary',
                                        elem_id='fullscreen-btn')

                            # 全屏模态框
                            with gr.Row(
                                    visible=False, elem_id='fullscreen-modal'
                            ) as fullscreen_modal:
                                with gr.Column():
                                    with gr.Row():
                                        gr.HTML(
                                            '<h3 style="margin: 0; flex: 1;">📄 研究报告 - 全屏模式</h3>'
                                        )
                                        close_btn = gr.Button(
                                            '✕',
                                            size='sm',
                                            variant='secondary',
                                            elem_id='close-btn')
                                    fullscreen_markdown = gr.Markdown(
                                        height=600,
                                        elem_id='fullscreen-markdown')

                            # 为本地模式创建空的HTML组件（保持兼容性）
                            html_output = gr.HTML(visible=False)
                            fullscreen_html = gr.HTML(visible=False)
                        else:
                            # 非Local模式：显示HTML
                            with gr.Row():
                                with gr.Column(scale=10):
                                    # HTML报告显示
                                    html_output = gr.HTML(
                                        label='研究报告 | Research Report',
                                        value='',
                                        elem_id='html-report',
                                        elem_classes=[
                                            'scrollable-html-report'
                                        ])
                                with gr.Column(scale=1, min_width=50):
                                    # 全屏按钮
                                    fullscreen_btn = gr.Button(
                                        '⛶',
                                        size='sm',
                                        variant='secondary',
                                        elem_id='fullscreen-btn')

                            # 全屏模态框
                            with gr.Row(
                                    visible=False, elem_id='fullscreen-modal'
                            ) as fullscreen_modal:
                                with gr.Column():
                                    with gr.Row():
                                        gr.HTML(
                                            '<h3 style="margin: 0; flex: 1;">📄 研究报告 - 全屏模式</h3>'
                                        )
                                        close_btn = gr.Button(
                                            '✕',
                                            size='sm',
                                            variant='secondary',
                                            elem_id='close-btn')
                                    fullscreen_html = gr.HTML(
                                        value='',
                                        elem_id='fullscreen-html',
                                        elem_classes=[
                                            'scrollable-html-report'
                                        ])

                            # 为非local模式创建空的markdown组件（保持兼容性）
                            markdown_output = gr.Markdown(visible=False)
                            fullscreen_markdown = gr.Markdown(visible=False)

                    with gr.TabItem('📁 资源文件 | Resources'):
                        # 资源文件列表
                        resources_output = gr.Textbox(
                            label='资源文件信息 | Resources Info',
                            lines=25,
                            max_lines=50,
                            interactive=False,
                            show_copy_button=True)

        # 使用说明
        gr.HTML("""
        <div class="instructions">
            <h4>📖 使用说明 | Instructions</h4>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-top: 1rem;">
                <div>
                    <h5 class="instructions-subtitle">🇨🇳 中文说明</h5>
                    <ul class="instructions-list">
                        <li><strong>用户提示：</strong>描述您的研究目标或问题，支持详细的任务描述</li>
                        <li><strong>文件上传：</strong>支持多文件上传，默认支持PDF格式</li>
                        <li><strong>URLs输入：</strong>每行输入一个URL，支持网页、文档、论文等链接</li>
                        <li><strong>工作目录：</strong>每次运行都会创建新的临时工作目录，便于管理结果</li>
                        <li><strong>会话保存：</strong>自动保存执行结果，支持页面刷新后重载数据</li>
                        <li><strong>用户隔离：</strong>每个用户拥有独立的工作空间和会话数据</li>
                    </ul>
                </div>
                <div>
                    <h5 class="instructions-subtitle">🇺🇸 English Instructions</h5>
                    <ul class="instructions-list">
                        <li><strong>User Prompt:</strong> Describe your research goals or questions with detailed task descriptions</li>
                        <li><strong>File Upload:</strong> Support multiple file uploads, default support for PDF format</li>
                        <li><strong>URLs Input:</strong> Enter one URL per line, supports web pages, documents, papers, etc.</li>
                        <li><strong>Working Directory:</strong> A new temporary working directory is created for each run for better result management</li>
                        <li><strong>Session Save:</strong> Automatically save execution results, support data reload after page refresh</li>
                        <li><strong>User Isolation:</strong> Each user has independent workspace and session data</li>
                    </ul>
                </div>
            </div>
        </div>
        """)

        # 页面加载时的初始化函数
        def initialize_page(request: gr.Request):
            """页面加载时初始化用户状态和会话数据"""
            local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

            # 获取用户状态HTML
            user_status_html = get_user_status_html(request)

            # 确定用户ID
            if local_mode:
                user_id = 'local_user'
            else:
                is_authenticated, user_id_or_error = check_user_auth(request)
                if not is_authenticated:
                    return (
                        user_status_html,
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',  # 界面显示 (6个)
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',  # 状态保存 (6个)
                        '',
                        '',  # 输入状态保存 (2个)
                        """<div class="status-indicator status-info">📊 会话状态: 游客模式（请登录后使用）</div>""",  # 会话状态
                        get_system_status_html()  # 系统状态
                    )
                user_id = user_id_or_error

            # 加载会话数据
            session_data = load_session_data(user_id)

            # 生成会话状态HTML
            if local_mode:
                session_status_html = ''  # 本地模式不显示会话状态
            else:
                session_status_html = f"""
                <div class="status-indicator status-info">
                    📊 会话状态: {'已加载历史数据' if any(session_data.values()) else '新会话'}
                    {f'| 最后更新: {session_data.get("timestamp", "未知")}' if session_data.get("timestamp") else ''}
                </div>
                """ if any(session_data.values()) else """
                <div class="status-indicator status-info">
                    📊 会话状态: 新会话
                </div>
                """

            return (
                user_status_html,
                session_data.get('user_prompt', ''),
                session_data.get('urls_text', ''),
                session_data.get('result', ''),
                session_data.get('workdir', ''),
                session_data.get('markdown', ''),
                session_data.get('html', ''),
                session_data.get('resources', ''),
                session_data.get('workdir', ''),
                session_data.get('result', ''),
                session_data.get('markdown', ''),
                session_data.get('html', ''),
                session_data.get('resources', ''),
                session_data.get('user_prompt', ''),
                session_data.get('urls_text', ''),
                session_status_html,
                get_system_status_html()  # 系统状态
            )

        # 全屏功能函数
        def toggle_fullscreen(markdown_content, html_content):
            """切换全屏显示"""
            local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'
            if local_mode:
                return gr.update(visible=True), markdown_content, ''
            else:
                return gr.update(visible=True), '', html_content

        def close_fullscreen():
            """关闭全屏显示"""
            return gr.update(visible=False), '', ''

        # 保存状态的包装函数
        def run_research_workflow_with_state(
                user_prompt_val, uploaded_files_val, urls_text_val,
                current_workdir_val, current_result_val, current_markdown_val,
                current_html_val, current_resources_val,
                current_user_prompt_val, current_urls_text_val,
                request: gr.Request):
            result, workdir, markdown, html, resources = run_research_workflow(
                user_prompt_val, uploaded_files_val, urls_text_val, request)

            local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

            # 确定用户ID
            if local_mode:
                user_id = 'local_user'
            else:
                is_authenticated, user_id_or_error = check_user_auth(request)
                if not is_authenticated:
                    status_html = f"""
                    <div class="status-indicator status-info">
                        🚫 游客模式 - {user_id_or_error}
                    </div>
                    """
                    return (result, workdir, markdown, html, resources,
                            workdir, result, markdown, html, resources,
                            user_prompt_val, urls_text_val, status_html,
                            get_system_status_html(),
                            get_user_status_html(request))
                user_id = user_id_or_error

            # 保存会话数据
            session_data = {
                'workdir': workdir,
                'result': result,
                'markdown': markdown,
                'html': html,
                'resources': resources,
                'user_prompt': user_prompt_val,
                'urls_text': urls_text_val,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            save_session_data(session_data, user_id)

            # 更新会话状态指示器
            if local_mode:
                status_html = ''  # 本地模式不显示会话状态
            else:
                status_html = f"""
                <div class="status-indicator status-success">
                    ✅ 会话已保存 | 最后更新: {session_data['timestamp']}
                </div>
                """

            return (
                result,
                workdir,
                markdown,
                html,
                resources,  # 输出显示
                workdir,
                result,
                markdown,
                html,
                resources,  # 状态保存
                user_prompt_val,
                urls_text_val,  # 输入状态保存
                status_html,  # 状态指示器
                get_system_status_html(),  # 系统状态
                get_user_status_html(request)  # 用户状态
            )

        # 恢复状态函数
        def restore_latest_results(workdir, result, markdown, html, resources,
                                   user_prompt_state, urls_text_state,
                                   request: gr.Request):
            local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

            # 确定用户ID
            if local_mode:
                user_id = 'local_user'
            else:
                is_authenticated, user_id_or_error = check_user_auth(request)
                if not is_authenticated:
                    status_html = f"""
                    <div class="status-indicator status-info">
                        🚫 游客模式 - {user_id_or_error}
                    </div>
                    """
                    return result, workdir, markdown, html, resources, user_prompt_state, urls_text_state, status_html, get_system_status_html(
                    )
                user_id = user_id_or_error

            # 重新加载会话数据
            session_data = load_session_data(user_id)

            # 更新状态指示器
            if local_mode:
                status_html = ''  # 本地模式不显示状态
            else:
                status_html = f"""
                <div class="status-indicator status-success">
                    🔄 已恢复会话数据 | 最后更新: {session_data.get('timestamp', '未知')}
                </div>
                """ if any(session_data.values()) else """
                <div class="status-indicator status-info">
                    ℹ️ 没有找到可恢复的会话数据
                </div>
                """

            return (session_data.get('result', result),
                    session_data.get('workdir', workdir),
                    session_data.get('markdown',
                                     markdown), session_data.get('html', html),
                    session_data.get('resources', resources),
                    session_data.get('user_prompt', user_prompt_state),
                    session_data.get('urls_text',
                                     urls_text_state), status_html,
                    get_system_status_html())

        # 清理函数
        def clear_all_inputs_and_state(request: gr.Request):
            local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

            # 确定用户ID
            if local_mode:
                user_id = 'local_user'
            else:
                is_authenticated, user_id_or_error = check_user_auth(request)
                if not is_authenticated:
                    status_html = f"""
                    <div class="status-indicator status-info">
                        🚫 游客模式 - {user_id_or_error}
                    </div>
                    """
                    return '', None, '', '', '', '', '', '', '', '', '', '', '', '', '', status_html, get_system_status_html(
                    ), get_user_status_html(request)
                user_id = user_id_or_error

            # 强制清理用户任务
            user_status_manager.force_cleanup_user(user_id)

            # 清理会话数据文件
            try:
                session_file = get_session_file_path(user_id)
                if os.path.exists(session_file):
                    os.remove(session_file)
            except Exception as e:
                print(f'清理会话文件失败: {e}')

            if local_mode:
                status_html = ''  # 本地模式不显示状态
            else:
                status_html = """
                <div class="status-indicator status-info">
                    🧹 会话数据已清理
                </div>
                """

            return '', None, '', '', '', '', '', '', '', '', '', '', '', '', '', status_html, get_system_status_html(
            ), get_user_status_html(request)

        # 清理工作空间并保持状态
        def clear_workspace_keep_state(current_workdir_val, current_result_val,
                                       current_markdown_val, current_html_val,
                                       current_resources_val,
                                       request: gr.Request):
            clear_result, clear_markdown, clear_resources = clear_workspace(
                request)

            local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

            if local_mode:
                status_html = ''  # 本地模式不显示状态
            else:
                status_html = """
                <div class="status-indicator status-success">
                    🧹 工作空间已清理，会话数据已保留
                </div>
                """

            return clear_result, clear_markdown, clear_resources, current_workdir_val, current_result_val, current_markdown_val, current_html_val, current_resources_val, status_html, get_system_status_html(
            )

        # 刷新系统状态函数
        def refresh_system_status():
            return get_system_status_html()

        # 页面加载时初始化
        demo.load(
            fn=initialize_page,
            outputs=[
                user_status, user_prompt, urls_text, result_output,
                workdir_output, markdown_output,
                html_output if not local_mode else markdown_output,
                resources_output, current_workdir, current_result,
                current_markdown, current_html, current_resources,
                current_user_prompt, current_urls_text, session_status,
                system_status
            ])

        # 定期刷新状态显示
        def periodic_status_update(request: gr.Request):
            """定期更新状态显示"""
            return get_user_status_html(request), get_system_status_html()

        # 使用定时器组件实现定期状态更新
        status_timer = gr.Timer(10)  # 每10秒触发一次
        status_timer.tick(
            fn=periodic_status_update, outputs=[user_status, system_status])

        # 全屏功能事件绑定
        fullscreen_btn.click(
            fn=toggle_fullscreen,
            inputs=[current_markdown, current_html],
            outputs=[fullscreen_modal, fullscreen_markdown, fullscreen_html])

        close_btn.click(
            fn=close_fullscreen,
            outputs=[fullscreen_modal, fullscreen_markdown, fullscreen_html])

        # 事件绑定
        run_btn.click(
            fn=run_research_workflow_with_state,
            inputs=[
                user_prompt, uploaded_files, urls_text, current_workdir,
                current_result, current_markdown, current_html,
                current_resources, current_user_prompt, current_urls_text
            ],
            outputs=[
                result_output, workdir_output, markdown_output,
                html_output if not local_mode else markdown_output,
                resources_output, current_workdir, current_result,
                current_markdown, current_html, current_resources,
                current_user_prompt, current_urls_text, session_status,
                system_status, user_status
            ],
            show_progress=True)

        # 恢复最近结果
        restore_btn.click(
            fn=restore_latest_results,
            inputs=[
                current_workdir, current_result, current_markdown,
                current_html, current_resources, current_user_prompt,
                current_urls_text
            ],
            outputs=[
                result_output, workdir_output, markdown_output,
                html_output if not local_mode else markdown_output,
                resources_output, user_prompt, urls_text, session_status,
                system_status
            ])

        # 刷新系统状态
        refresh_status_btn.click(
            fn=refresh_system_status, outputs=[system_status])

        clear_btn.click(
            fn=clear_workspace_keep_state,
            inputs=[
                current_workdir, current_result, current_markdown,
                current_html, current_resources
            ],
            outputs=[
                result_output, markdown_output, resources_output,
                current_workdir, current_result, current_markdown,
                current_html, current_resources, session_status, system_status
            ]).then(
                fn=clear_all_inputs_and_state,
                outputs=[
                    user_prompt, uploaded_files, urls_text, result_output,
                    workdir_output, markdown_output,
                    html_output if not local_mode else markdown_output,
                    resources_output, current_workdir, current_result,
                    current_markdown, current_html, current_resources,
                    current_user_prompt, current_urls_text, session_status,
                    system_status, user_status
                ])

        # 示例数据
        gr.Examples(
            examples=
            [[
                '深入分析和总结下列文档', None,
                'https://modelscope.cn/models/ms-agent/ms_agent_resources/resolve/master/numina_dataset.pdf'
            ],
             [
                 'Qwen3跟Qwen2.5对比，有哪些优化？', None,
                 'https://arxiv.org/abs/2505.09388\nhttps://arxiv.org/abs/2412.15115'
             ],
             [
                 'Analyze and summarize the following documents in English',
                 None, 'https://arxiv.org/abs/2505.09388'
             ]],
            inputs=[user_prompt, uploaded_files, urls_text],
            label='示例 | Examples')

    return demo


if __name__ == '__main__':
    # 创建界面
    demo = create_interface()

    # 配置Gradio队列并发控制
    demo.queue(default_concurrency_limit=GRADIO_DEFAULT_CONCURRENCY_LIMIT)

    # 启动应用
    demo.launch(
        server_name='0.0.0.0',
        server_port=7860,
        share=False,
        debug=True,
        show_error=True)
