# flake8: noqa
# isort: skip_file
# yapf: disable
import base64
import os
import re
import shutil
import socketserver
import threading
import time
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

import gradio as gr
import json
import markdown
from ms_agent.llm.openai import OpenAIChat
from ms_agent.utils.logger import get_logger
from ms_agent.workflow.research_workflow import ResearchWorkflow

logger = get_logger()


"""
This module provides a Gradio application for running a research workflow with file and URL inputs.

It includes functionalities for:
- Initializing the research workflow application
- Processing user inputs (files and URLs)
- Managing user status and task concurrency
- Converting markdown content with images to HTML or base64 format
- Reading and processing markdown reports
- Listing resource files in the working directory
"""


class ResearchWorkflowApp:
    """
    Research Workflow Application, this class initializes the research workflow with the necessary model downloads.
    """
    def __init__(self, client, workdir: str):
        from modelscope import snapshot_download
        from modelscope.hub.utils.utils import get_cache_dir

        self.client = client
        self.workdir = workdir

        target_dir: str = os.path.join(get_cache_dir(), 'models/EasyOCR')
        if not os.path.exists(os.path.join(os.path.expanduser(target_dir), 'craft_mlt_25k.pth')):

            os.makedirs(os.path.expanduser(target_dir), exist_ok=True)
            # Download model to specified directory
            snapshot_download(
                model_id='ms-agent/craft_mlt_25k',
                local_dir=os.path.expanduser(target_dir),
            )
            snapshot_download(
                model_id='ms-agent/latin_g2',
                local_dir=os.path.expanduser(target_dir),
            )
            logger.info(f'EasyOCR model downloaded to: {os.path.expanduser(target_dir)}')
            # Unzip craft_mlt_25k.zip, latin_g2.zip
            import zipfile
            zip_path_craft = os.path.join(os.path.expanduser(target_dir), 'craft_mlt_25k.zip')
            zip_path_latin = os.path.join(os.path.expanduser(target_dir), 'latin_g2.zip')
            if os.path.exists(zip_path_craft):
                with zipfile.ZipFile(zip_path_craft, 'r') as zip_ref_craft:
                    zip_ref_craft.extractall(os.path.expanduser(target_dir))
            if os.path.exists(zip_path_latin):
                with zipfile.ZipFile(zip_path_latin, 'r') as zip_ref_latin:
                    zip_ref_latin.extractall(os.path.expanduser(target_dir))

            logger.info(f'EasyOCR model extracted to: {os.path.expanduser(target_dir)}')

        self._workflow = ResearchWorkflow(
            client=self.client,
            workdir=self.workdir,
            verbose=True,
        )

    def run(self, user_prompt: str, urls_or_files: List[str]) -> str:
        # Check if input files/URLs are empty
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

        # Return execution statistics
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

        result += '\n✅ 研究分析已完成，结果已保存到工作目录中。 请查看研究报告。'
        return result


# Global variables
BASE_WORKDIR = 'temp_workspace'

# Concurrency control configuration
GRADIO_DEFAULT_CONCURRENCY_LIMIT = int(os.environ.get('GRADIO_DEFAULT_CONCURRENCY_LIMIT', '10'))


# Simplified user status manager
class UserStatusManager:
    def __init__(self):
        self.active_users = {}  # {user_id: {'start_time': time, 'status': status}}
        self.lock = threading.Lock()

    def get_user_status(self, user_id: str) -> dict:
        """Get user task status"""
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
        """Mark user task start"""
        with self.lock:
            self.active_users[user_id] = {
                'start_time': time.time(),
                'status': 'running'
            }
            logger.info(f'User task started - User: {user_id[:8]}***, Current active users: {len(self.active_users)}')

    def finish_user_task(self, user_id: str):
        """Mark user task completion"""
        with self.lock:
            if user_id in self.active_users:
                del self.active_users[user_id]
                logger.info(f'User task completed - User: {user_id[:8]}***, Remaining active users: {len(self.active_users)}')

    def get_system_status(self) -> dict:
        """Get system status"""
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
        """Force cleanup user task"""
        with self.lock:
            if user_id in self.active_users:
                del self.active_users[user_id]
                logger.info(f'Force cleanup user task - User: {user_id[:8]}***')
                return True
            return False


# Create global user status manager instance
user_status_manager = UserStatusManager()


def get_user_id_from_request(request: gr.Request) -> str:
    """Get user ID from request headers"""
    if request and hasattr(request, 'headers'):
        user_id = request.headers.get('x-modelscope-router-id', '')
        return user_id.strip() if user_id else ''
    return ''


def check_user_auth(request: gr.Request) -> Tuple[bool, str]:
    """Check user authentication status"""
    user_id = get_user_id_from_request(request)
    if not user_id:
        return False, '请登录后使用 | Please log in to use this feature.'
    return True, user_id


def create_user_workdir(user_id: str) -> str:
    """Create dedicated working directory for user"""
    user_base_dir = os.path.join(BASE_WORKDIR, f'user_{user_id}')
    if not os.path.exists(user_base_dir):
        os.makedirs(user_base_dir)
    return user_base_dir


def create_task_workdir(user_id: str) -> str:
    """Create new task working directory"""
    user_base_dir = create_user_workdir(user_id)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    task_id = str(uuid.uuid4())[:8]
    task_workdir = os.path.join(user_base_dir, f'task_{timestamp}_{task_id}')
    os.makedirs(task_workdir, exist_ok=True)
    return task_workdir


def process_urls_text(urls_text: str) -> List[str]:
    """Process URL text input, split by newlines"""
    if not urls_text.strip():
        return []

    urls = []
    for line in urls_text.strip().split('\n'):
        line = line.strip()
        if line:
            urls.append(line)
    return urls


def process_files(files) -> List[str]:
    """Process uploaded files"""
    if not files:
        return []

    file_paths = []
    # Ensure files is in list format
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
    """Check if port is available"""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(('localhost', port))
            return result != 0  # 0 means connection successful, port is occupied
    except Exception:
        return True


class ReusableTCPServer(socketserver.TCPServer):
    """TCP server that supports address reuse"""
    allow_reuse_address = True


def convert_markdown_images_to_base64(markdown_content: str, workdir: str) -> str:
    """Convert relative path images in markdown to base64 format (for online environments)"""

    def replace_image(match):
        alt_text = match.group(1)
        image_path = match.group(2)

        # Handle relative paths
        if not os.path.isabs(image_path):
            full_path = os.path.join(workdir, image_path)
        else:
            full_path = image_path

        # Check if file exists
        if os.path.exists(full_path):
            try:
                # Get file extension to determine MIME type
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

                # Check file size to avoid oversized images
                file_size = os.path.getsize(full_path)
                max_size = 5 * 1024 * 1024  # 5MB limit

                if file_size > max_size:
                    return f"""
**🖼️ 图片文件过大: {alt_text or os.path.basename(image_path)}**
- 📁 路径: `{image_path}`
- 📏 大小: {file_size / (1024 * 1024):.2f} MB (超过5MB限制)
- 💡 提示: 图片文件过大，无法在线显示，请通过文件管理器查看

---
"""

                # Read image file and convert to base64
                with open(full_path, 'rb') as img_file:
                    img_data = img_file.read()
                    base64_data = base64.b64encode(img_data).decode('utf-8')

                # Create data URL
                data_url = f'data:{mime_type};base64,{base64_data}'
                return f'![{alt_text}]({data_url})'

            except Exception as e:
                logger.info(f'Unable to process image {full_path}: {e}')
                return f"""
**❌ 图片处理失败: {alt_text or os.path.basename(image_path)}**
- 📁 路径: `{image_path}`
- ❌ 错误: {str(e)}

---
"""
        else:
            return f'**❌ 图片文件不存在: {alt_text or image_path}**\n\n'

    # Match markdown image syntax: ![alt](path)
    pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    return re.sub(pattern, replace_image, markdown_content)


def convert_markdown_images_to_file_info(markdown_content: str, workdir: str) -> str:
    """Convert images in markdown to file info display (fallback solution)"""

    def replace_image(match):
        alt_text = match.group(1)
        image_path = match.group(2)

        # Handle relative paths
        if not os.path.isabs(image_path):
            full_path = os.path.join(workdir, image_path)
        else:
            full_path = image_path

        # Check if file exists
        if os.path.exists(full_path):
            try:
                # Get file information
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
                logger.info(f'Unable to read image info {full_path}: {e}')
                return f'**❌ 图片加载失败: {alt_text or image_path}**\n\n'
        else:
            return f'**❌ 图片文件不存在: {alt_text or image_path}**\n\n'

    # Match markdown image syntax: ![alt](path)
    pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    return re.sub(pattern, replace_image, markdown_content)


def convert_markdown_to_html(markdown_content: str) -> str:
    """Convert markdown to HTML, using KaTeX to process LaTeX formulas"""
    try:
        import re

        # Protect LaTeX formulas to avoid misprocessing by markdown processor
        latex_placeholders = {}
        placeholder_counter = 0

        def protect_latex(match):
            nonlocal placeholder_counter
            placeholder = f'LATEX_PLACEHOLDER_{placeholder_counter}'
            latex_placeholders[placeholder] = match.group(0)
            placeholder_counter += 1
            return placeholder

        # Protect various LaTeX formula formats
        protected_content = markdown_content

        # Protect $$...$$ (block-level formulas)
        protected_content = re.sub(r'\$\$([^$]+?)\$\$', protect_latex, protected_content, flags=re.DOTALL)

        # Protect $...$ (inline formulas)
        protected_content = re.sub(r'(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)', protect_latex, protected_content)

        # Protect \[...\] (block-level formulas)
        protected_content = re.sub(r'\\\[([^\\]+?)\\\]', protect_latex, protected_content, flags=re.DOTALL)

        # Protect \(...\) (inline formulas)
        protected_content = re.sub(r'\\\(([^\\]+?)\\\)', protect_latex, protected_content, flags=re.DOTALL)

        # Configure markdown extensions
        extensions = [
            'markdown.extensions.extra',
            'markdown.extensions.codehilite',
            'markdown.extensions.toc',
            'markdown.extensions.tables',
            'markdown.extensions.fenced_code',
            'markdown.extensions.nl2br'
        ]

        # Configure extension parameters
        extension_configs = {
            'markdown.extensions.codehilite': {
                'css_class': 'highlight',
                'use_pygments': True
            },
            'markdown.extensions.toc': {
                'permalink': True
            }
        }

        # Create markdown instance
        md = markdown.Markdown(
            extensions=extensions,
            extension_configs=extension_configs
        )

        # Convert to HTML
        html_content = md.convert(protected_content)

        # Restore LaTeX formulas
        for placeholder, latex_formula in latex_placeholders.items():
            html_content = html_content.replace(placeholder, latex_formula)

        # Generate unique container ID to ensure independent KaTeX processing for each render
        container_id = f'katex-content-{int(time.time() * 1000000)}'

        # Use KaTeX to render LaTeX formulas
        styled_html = f"""
        <div class="markdown-html-content" id="{container_id}">
            <!-- KaTeX CSS -->
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css" integrity="sha384-n8MVd4RsNIU0tAv4ct0nTaAbDJwPJzDEaqSD1odI+WdtXRGWt2kTvGFasHpSy3SV" crossorigin="anonymous">

            <!-- Content area -->
            <div class="content-area">
                {html_content}
            </div>

            <!-- KaTeX JavaScript and auto-render extension -->
            <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js" integrity="sha384-XjKyOOlGwcjNTAIQHIpVOOVA+CuTF5UvLqGSXPM6njWx5iNxN7jyVjNOq8Ks4pxy" crossorigin="anonymous"></script>
            <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js" integrity="sha384-+VBxd3r6XgURycqtZ117nYw44OOcIax56Z4dCRWbxyPt0Koah1uHoK0o4+/RRE05" crossorigin="anonymous"></script>

            <!-- KaTeX rendering script -->
            <script type="text/javascript">
                (function() {{
                    const containerId = '{container_id}';
                    const container = document.getElementById(containerId);

                    if (!container) {{
                        console.warn('KaTeX container not found:', containerId);
                        return;
                    }}

                    // Wait for KaTeX to load before rendering
                    function renderKaTeX() {{
                        if (typeof renderMathInElement !== 'undefined') {{
                            console.log('Starting KaTeX rendering - Container:', containerId);

                            try {{
                                renderMathInElement(container, {{
                                    // Configure delimiters
                                    delimiters: [
                                        {{left: '$$', right: '$$', display: true}},
                                        {{left: '$', right: '$', display: false}},
                                        {{left: '\\\\[', right: '\\\\]', display: true}},
                                        {{left: '\\\\(', right: '\\\\)', display: false}}
                                    ],
                                    // Other configuration options
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

                                console.log('KaTeX rendering completed - Container:', containerId);

                                // Count rendered formulas
                                const mathElements = container.querySelectorAll('.katex');
                                console.log('Found and processed', mathElements.length, 'mathematical formulas');

                                // Apply style corrections
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
                                console.error('KaTeX rendering error:', error);
                            }}
                        }} else {{
                            console.warn('KaTeX auto-render not loaded, waiting for retry...');
                            setTimeout(renderKaTeX, 200);
                        }}
                    }}

                    // Use delay to ensure Gradio is fully rendered
                    setTimeout(() => {{
                        console.log('Starting to load KaTeX...');
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

                /* KaTeX formula style optimization */
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

                /* Inline formula styles */
                #{container_id} .katex:not(.katex-display) {{
                    display: inline-block !important;
                    margin: 0 0.1em !important;
                    vertical-align: baseline !important;
                }}

                /* Formula overflow handling */
                #{container_id} .katex .katex-html {{
                    max-width: 100% !important;
                    overflow-x: auto !important;
                }}

                /* Ensure LaTeX formulas display correctly in Gradio */
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

                /* Dark theme adaptation */
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

                /* Responsive design */
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

                    /* Mobile KaTeX optimization */
                    #{container_id} .katex {{
                        font-size: 1em !important;
                    }}
                }}
            </style>
        </div>
        """

        return styled_html

    except Exception as e:
        logger.info(f'Markdown to HTML conversion failed: {e}')
        # If conversion fails, return original markdown content wrapped in pre tags
        return f"""
        <div class="markdown-fallback">
            <h3>⚠️ Markdown渲染失败，显示原始内容</h3>
            <pre style="white-space: pre-wrap; word-wrap: break-word; background: #f8f9fa; padding: 1rem; border-radius: 6px; border: 1px solid #dee2e6;">{markdown_content}</pre>
        </div>
        """


def read_markdown_report(workdir: str) -> Tuple[str, str, str]:
    """Read and process markdown report, return both markdown and html formats"""
    report_path = os.path.join(workdir, 'report.md')

    if not os.path.exists(report_path):
        return '', '', '未找到报告文件 report.md'

    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()

        # Uniformly use base64 method to process images
        try:
            processed_markdown = convert_markdown_images_to_base64(markdown_content, workdir)
        except Exception as e:
            logger.info(f'Base64 conversion failed, using file info display: {e}')
            processed_markdown = convert_markdown_images_to_file_info(markdown_content, workdir)

        # Check if non-local_mode, if so convert to HTML
        local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'
        if not local_mode:
            try:
                processed_html = convert_markdown_to_html(processed_markdown)
            except Exception as e:
                logger.info(f'HTML conversion failed, using markdown display: {e}')
                processed_html = processed_markdown
        else:
            processed_html = processed_markdown

        return processed_markdown, processed_html, ''
    except Exception as e:
        return '', '', f'读取报告文件失败: {str(e)}'


def list_resources_files(workdir: str) -> str:
    """List files in resources folder"""
    resources_path = os.path.join(workdir, 'resources')

    if not os.path.exists(resources_path):
        return '未找到 resources 文件夹'

    try:
        files = []
        for root, dirs, filenames in os.walk(resources_path):
            for filename in filenames:
                rel_path = os.path.relpath(os.path.join(root, filename), workdir)
                files.append(rel_path)

        if files:
            return '📁 资源文件列表:\n' + '\n'.join(f'• {file}' for file in sorted(files))
        else:
            return 'resources 文件夹为空'
    except Exception as e:
        return f'读取资源文件失败: {str(e)}'


def run_research_workflow_internal(
        user_prompt: str,
        uploaded_files,
        urls_text: str,
        user_id: str,
        progress_callback=None
) -> Tuple[str, str, str, str, str]:
    """Internal research workflow execution function"""
    try:
        if progress_callback:
            progress_callback(0.02, '验证输入参数...')

        # Process files and URLs
        file_paths = process_files(uploaded_files)
        urls = process_urls_text(urls_text)

        # Merge file paths and URLs
        urls_or_files = file_paths + urls

        if progress_callback:
            progress_callback(0.05, '初始化工作环境...')

        # Create new working directory
        task_workdir = create_task_workdir(user_id)

        user_prompt = user_prompt.strip() or '请深入分析和总结下列文档：'

        if progress_callback:
            progress_callback(0.10, '初始化AI客户端...')

        # Initialize chat client
        chat_client = OpenAIChat(
            api_key=os.environ.get('OPENAI_API_KEY'),
            base_url=os.environ.get('OPENAI_BASE_URL'),
            model=os.environ.get('OPENAI_MODEL_ID'),
        )

        if progress_callback:
            progress_callback(0.15, '创建研究工作流...')

        # Create research workflow
        research_workflow = ResearchWorkflowApp(
            client=chat_client,
            workdir=task_workdir,
        )

        if progress_callback:
            progress_callback(0.20, '开始执行研究工作流...')

        # Run workflow - this step takes most of the progress
        result = research_workflow.run(
            user_prompt=user_prompt,
            urls_or_files=urls_or_files,
        )

        if progress_callback:
            progress_callback(0.90, '处理研究报告...')

        # Read markdown report
        markdown_report, html_report, report_error = read_markdown_report(task_workdir)

        if progress_callback:
            progress_callback(0.95, '整理资源文件...')

        # List resource files
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
        progress=gr.Progress()
) -> Tuple[str, str, str, str, str]:
    """Run research workflow (using Gradio built-in queue control)"""
    try:
        # Check LOCAL_MODE environment variable, default is true
        local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

        if not local_mode:
            # Check user authentication
            is_authenticated, user_id_or_error = check_user_auth(request)
            if not is_authenticated:
                return f'❌ 认证失败：{user_id_or_error}', '', '', '', ''

            user_id = user_id_or_error
        else:
            # Local mode, use default user ID with timestamp to avoid conflicts
            user_id = f'local_user_{int(time.time() * 1000)}'

        progress(0.01, desc='开始执行任务...')

        # Mark user task start
        user_status_manager.start_user_task(user_id)

        # Create progress callback function
        def progress_callback(value, desc):
            # Map internal progress to 0.05-0.95 range
            mapped_progress = 0.05 + (value * 0.9)
            progress(mapped_progress, desc=desc)

        try:
            # Execute task directly, controlled by Gradio queue for concurrency
            result = run_research_workflow_internal(
                user_prompt,
                uploaded_files,
                urls_text,
                user_id,
                progress_callback
            )

            progress(1.0, desc='任务完成！')
            return result

        except Exception as e:
            logger.info(f'Task execution exception - User: {user_id[:8]}***, Error: {str(e)}')
            error_msg = f'❌ 任务执行失败：{str(e)}'
            return error_msg, '', '', '', ''
        finally:
            # Ensure user status cleanup
            user_status_manager.finish_user_task(user_id)

    except Exception as e:
        error_msg = f'❌ 系统错误：{str(e)}'
        return error_msg, '', '', '', ''


def clear_workspace(request: gr.Request):
    """Clear workspace"""
    try:
        # Check LOCAL_MODE environment variable, default is true
        local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

        if not local_mode:
            # Check user authentication
            is_authenticated, user_id_or_error = check_user_auth(request)
            if not is_authenticated:
                return f'❌ 认证失败：{user_id_or_error}', '', ''

            user_id = user_id_or_error
        else:
            # Local mode, use default user ID
            user_id = 'local_user'

        user_workdir = create_user_workdir(user_id)

        if os.path.exists(user_workdir):
            shutil.rmtree(user_workdir)
        return '✅ 工作空间已清理', '', ''
    except Exception as e:
        return f'❌ 清理失败：{str(e)}', '', ''


def get_session_file_path(user_id: str) -> str:
    """Get user-specific session file path"""
    user_workdir = create_user_workdir(user_id)
    return os.path.join(user_workdir, 'session_data.json')


def save_session_data(data, user_id: str):
    """Save session data to file"""
    try:
        session_file = get_session_file_path(user_id)
        os.makedirs(os.path.dirname(session_file), exist_ok=True)
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.info(f'Failed to save session data: {e}')


def load_session_data(user_id: str):
    """Load session data from file"""
    try:
        session_file = get_session_file_path(user_id)
        if os.path.exists(session_file):
            with open(session_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.info(f'Failed to load session data: {e}')

    # Return default data
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
    """Get system status HTML"""
    local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

    if local_mode:
        return ''  # Local mode doesn't display system status info

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


# Create Gradio interface
def create_interface():
    with gr.Blocks(
            title='研究工作流应用 | Research Workflow App',
            theme=gr.themes.Soft(),
            css="""
        /* Responsive container settings */
        .gradio-container {
            max-width: none !important;
            width: 100% !important;
            padding: 0 1rem !important;
        }

        /* Non-local_mode HTML report scrolling styles */
        .scrollable-html-report {
            height: 750px !important;
            overflow-y: auto !important;
            border: 1px solid var(--border-color-primary) !important;
            border-radius: 0.5rem !important;
            padding: 1rem !important;
            background: var(--background-fill-primary) !important;
        }

        /* HTML report content area styles */
        #html-report {
            height: 750px !important;
            overflow-y: auto !important;
        }

        /* HTML report scrolling in fullscreen mode */
        #fullscreen-html {
            height: calc(100vh - 1.2rem) !important;
            overflow-y: auto !important;
        }

        /* HTML report scrollbar beautification */
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

        /* Ensure HTML content displays correctly within container */
        .scrollable-html-report .markdown-html-content {
            max-width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        /* Responsive adaptation */
        @media (max-width: 768px) {
            .scrollable-html-report,
            #html-report {
                height: 600px !important;
                padding: 0.75rem !important;
            }

            #fullscreen-html {
                height: calc(100vh - 1rem) !important;
            }

            #fullscreen-modal {
                padding: 0.1rem !important;
            }

            #fullscreen-modal .gr-column {
                padding: 0.1rem !important;
                height: calc(100vh - 0.2rem) !important;
            }

            #fullscreen-markdown {
                height: calc(100vh - 1rem) !important;
            }

            #fullscreen-btn {
                min-width: 20px !important;
                width: 20px !important;
                height: 20px !important;
                font-size: 0.8rem !important;
            }

            #close-btn {
                min-width: 18px !important;
                width: 18px !important;
                height: 18px !important;
                font-size: 0.8rem !important;
            }
        }

        @media (max-width: 480px) {
            .scrollable-html-report,
            #html-report {
                height: 500px !important;
                padding: 0.5rem !important;
            }

            #fullscreen-html {
                height: calc(100vh - 0.8rem) !important;
            }

            #fullscreen-modal {
                padding: 0.05rem !important;
            }

            #fullscreen-modal .gr-column {
                padding: 0.05rem !important;
                height: calc(100vh - 0.1rem) !important;
            }

            #fullscreen-markdown {
                height: calc(100vh - 0.8rem) !important;
            }

            #fullscreen-btn {
                min-width: 18px !important;
                width: 18px !important;
                height: 18px !important;
                font-size: 0.75rem !important;
            }

            #close-btn {
                min-width: 16px !important;
                width: 16px !important;
                height: 16px !important;
                font-size: 0.75rem !important;
            }
        }

        /* Fullscreen modal styles */
        #fullscreen-modal {
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            background: var(--background-fill-primary) !important;
            z-index: 9999 !important;
            padding: 0.15rem !important;
            box-sizing: border-box !important;
        }

        #fullscreen-modal .gr-column {
            background: var(--background-fill-primary) !important;
            border: 1px solid var(--border-color-primary) !important;
            border-radius: 0.5rem !important;
            padding: 0.15rem !important;
            height: calc(100vh - 0.3rem) !important;
            overflow: hidden !important;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.15) !important;
        }

        #fullscreen-markdown {
            height: calc(100vh - 1.2rem) !important;
            overflow-y: auto !important;
            background: var(--background-fill-primary) !important;
            color: var(--body-text-color) !important;
        }

        #fullscreen-html {
            height: calc(100vh - 1.2rem) !important;
            overflow-y: auto !important;
        }

        #fullscreen-btn {
            min-width: 24px !important;
            width: 24px !important;
            height: 24px !important;
            padding: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-size: 0.9rem !important;
            margin-bottom: 0.25rem !important;
            border-radius: 4px !important;
        }

        #close-btn {
            min-width: 22px !important;
            width: 22px !important;
            height: 22px !important;
            padding: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-size: 0.9rem !important;
            margin-left: auto !important;
            background: var(--button-secondary-background-fill) !important;
            color: var(--button-secondary-text-color) !important;
            border: 1px solid var(--border-color-primary) !important;
            border-radius: 4px !important;
        }

        #close-btn:hover {
            background: var(--button-secondary-background-fill-hover) !important;
        }

        /* Fullscreen mode title styles */
        #fullscreen-modal h3 {
            color: var(--body-text-color) !important;
            margin: 0 !important;
            flex: 1 !important;
            font-size: 1.1rem !important;
            line-height: 1.2 !important;
            padding: 0 !important;
        }

        /* Fullscreen mode title row styles */
        #fullscreen-modal .gr-row {
            margin-bottom: 0.15rem !important;
            align-items: center !important;
            padding: 0 !important;
            min-height: auto !important;
        }

        /* Fullscreen mode markdown style optimization */
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

        /* Fullscreen mode scrollbar styles */
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

        /* Dark theme special adaptation */
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

        /* Large screen adaptation */
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

        /* Main title styles */
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

        /* Description text styles */
        .description {
            font-size: clamp(1rem, 1.8vw, 1.2rem);
            color: #6b7280;
            margin-bottom: 0.5rem;
            font-weight: 500;
            line-height: 1.5;
        }

        /* Powered by styles */
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

        /* Dark theme adaptation */
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

        /* Section headers */
        .section-header {
            color: #2563eb;
            font-weight: 600;
            margin: 1rem 0 0.5rem 0;
            font-size: clamp(1rem, 1.8vw, 1.3rem);
        }

        /* Status indicators */
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

        /* Input component optimization */
        .gr-textbox, .gr-file {
            font-size: clamp(0.85rem, 1.1vw, 1rem) !important;
        }

        /* Button style optimization */
        .gr-button {
            font-size: clamp(0.9rem, 1.2vw, 1.1rem) !important;
            padding: 0.75rem 1.5rem !important;
            border-radius: 0.5rem !important;
            font-weight: 500 !important;
        }

        /* Tab label optimization */
        .gr-tab-nav {
            font-size: clamp(0.85rem, 1.1vw, 1rem) !important;
        }

        /* Output area optimization */
        .gr-markdown {
            font-size: clamp(0.85rem, 1vw, 1rem) !important;
            line-height: 1.6 !important;
        }

        /* Instructions area */
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

        /* Dark theme adaptation */
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

        /* Gradio dark theme adaptation */
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

        /* Responsive column layout */
        @media (max-width: 768px) {
            .gr-row {
                flex-direction: column !important;
            }

            .gr-column {
                width: 100% !important;
                margin-bottom: 1rem !important;
            }
        }

        /* Column width optimization for large screens */
        @media (min-width: 1400px) {
            .input-column {
                min-width: 500px !important;
            }

            .output-column {
                min-width: 700px !important;
            }
        }

        /* Scrollbar beautification */
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
        """
    ) as demo:

        # State management - for maintaining data persistence
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
            <p class="powered-by">Powered by <a href="https://github.com/modelscope/ms-agent" target="_blank" rel="noopener noreferrer">MS-Agent</a> | <a href="https://github.com/modelscope/ms-agent/blob/main/projects/doc_research/README.md" target="_blank" rel="noopener noreferrer">Readme</a> </p>
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
                    placeholder='请输入您的研究问题或任务描述(可为空)...\nPlease enter your research question or task description (Optional)...',
                    lines=4,
                    max_lines=8
                )

                with gr.Row():
                    with gr.Column():
                        # 文件上传
                        uploaded_files = gr.File(
                            label='上传文件 | Upload Files',
                            file_count='multiple',
                            file_types=None,
                            interactive=True,
                            height=120
                        )

                    with gr.Column():
                        # URLs输入
                        urls_text = gr.Textbox(
                            label='URLs输入 | URLs Input',
                            placeholder='请输入URLs，每行一个...\nEnter URLs, one per line...\n\nhttps://example1.com\nhttps://example2.com',
                            lines=6,
                            max_lines=10
                        )

                # 运行按钮
                run_btn = gr.Button(
                    '🚀 开始研究 | Start Research',
                    variant='primary',
                    size='lg'
                )

                # 清理按钮
                clear_btn = gr.Button(
                    '🧹 清理工作空间 | Clear Workspace',
                    variant='secondary'
                )

                # 恢复按钮
                restore_btn = gr.Button(
                    '🔄 重载最近结果 | Reload Latest Results',
                    variant='secondary'
                )

                # 会话状态指示器
                session_status = gr.HTML()

                # 刷新系统状态按钮
                refresh_status_btn = gr.Button(
                    '🔄 刷新系统状态 | Refresh System Status',
                    variant='secondary',
                    size='sm'
                )

            with gr.Column(scale=3, elem_classes=['output-column']):
                gr.HTML('<h3 class="section-header">📊 输出区域 | Output Area</h3>')

                with gr.Tabs():
                    with gr.TabItem('📋 执行结果 | Results'):
                        # 结果显示
                        result_output = gr.Textbox(
                            label='执行结果 | Execution Results',
                            lines=26,
                            max_lines=30,
                            interactive=False,
                            show_copy_button=True
                        )

                        # 工作目录显示
                        workdir_output = gr.Textbox(
                            label='工作目录 | Working Directory',
                            lines=2,
                            interactive=False,
                            show_copy_button=True
                        )

                    with gr.TabItem('📄 研究报告 | Research Report'):
                        # 检查是否为非local_mode来决定显示格式
                        local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

                        if local_mode:
                            # Local模式：显示Markdown
                            with gr.Row():
                                with gr.Column(scale=10):
                                    # Markdown报告显示
                                    markdown_output = gr.Markdown(
                                        label='Markdown报告 | Markdown Report',
                                        height=750
                                    )
                                with gr.Column(scale=1, min_width=30):
                                    # 全屏按钮
                                    fullscreen_btn = gr.Button(
                                        '⛶',
                                        size='sm',
                                        variant='secondary',
                                        elem_id='fullscreen-btn'
                                    )

                            # 全屏模态框
                            with gr.Row(visible=False, elem_id='fullscreen-modal') as fullscreen_modal:
                                with gr.Column():
                                    with gr.Row():
                                        gr.HTML('<h3 style="margin: 0; flex: 1;">📄 研究报告 - 全屏模式</h3>')
                                        close_btn = gr.Button(
                                            '✕',
                                            size='sm',
                                            variant='secondary',
                                            elem_id='close-btn'
                                        )
                                    fullscreen_markdown = gr.Markdown(
                                        height=700,
                                        elem_id='fullscreen-markdown'
                                    )

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
                                        elem_classes=['scrollable-html-report']
                                    )
                                with gr.Column(scale=1, min_width=30):
                                    # 全屏按钮
                                    fullscreen_btn = gr.Button(
                                        '⛶',
                                        size='sm',
                                        variant='secondary',
                                        elem_id='fullscreen-btn'
                                    )

                            # 全屏模态框
                            with gr.Row(visible=False, elem_id='fullscreen-modal') as fullscreen_modal:
                                with gr.Column():
                                    with gr.Row():
                                        gr.HTML('<h3 style="margin: 0; flex: 1;">📄 研究报告 - 全屏模式</h3>')
                                        close_btn = gr.Button(
                                            '✕',
                                            size='sm',
                                            variant='secondary',
                                            elem_id='close-btn'
                                        )
                                    fullscreen_html = gr.HTML(
                                        value='',
                                        elem_id='fullscreen-html',
                                        elem_classes=['scrollable-html-report']
                                    )

                            # 为非local模式创建空的markdown组件（保持兼容性）
                            markdown_output = gr.Markdown(visible=False)
                            fullscreen_markdown = gr.Markdown(visible=False)

                    with gr.TabItem('📁 资源文件 | Resources'):
                        # 资源文件列表
                        resources_output = gr.Textbox(
                            label='资源文件信息 | Resources Info',
                            lines=30,
                            max_lines=50,
                            interactive=False,
                            show_copy_button=True
                        )

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

        # Page initialization function on load
        def initialize_page(request: gr.Request):
            """Initialize user status and session data when page loads"""
            local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

            # Get user status HTML
            user_status_html = get_user_status_html(request)

            # Determine user ID
            if local_mode:
                user_id = 'local_user'
            else:
                is_authenticated, user_id_or_error = check_user_auth(request)
                if not is_authenticated:
                    return (
                        user_status_html,
                        '', '', '', '', '', '',  # Interface display (6 items)
                        '', '', '', '', '', '',  # State saving (6 items)
                        '', '',  # Input state saving (2 items)
                        """<div class="status-indicator status-info">📊 会话状态: 游客模式（请登录后使用）</div>""",  # Session status
                        get_system_status_html()  # System status
                    )
                user_id = user_id_or_error

            # Load session data
            session_data = load_session_data(user_id)

            # Generate session status HTML
            if local_mode:
                session_status_html = ''  # Local mode doesn't display session status
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
                get_system_status_html()  # System status
            )

        # Fullscreen functionality functions
        def toggle_fullscreen(markdown_content, html_content):
            """Toggle fullscreen display"""
            local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'
            if local_mode:
                return gr.update(visible=True), markdown_content, ''
            else:
                return gr.update(visible=True), '', html_content

        def close_fullscreen():
            """Close fullscreen display"""
            return gr.update(visible=False), '', ''

        # State-saving wrapper function
        def run_research_workflow_with_state(
                user_prompt_val, uploaded_files_val, urls_text_val,
                current_workdir_val, current_result_val, current_markdown_val, current_html_val, current_resources_val,
                current_user_prompt_val, current_urls_text_val,
                request: gr.Request
        ):
            result, workdir, markdown, html, resources = run_research_workflow(
                user_prompt_val, uploaded_files_val, urls_text_val, request
            )

            local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

            # Determine user ID
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
                    return (
                        result, workdir, markdown, html, resources,
                        workdir, result, markdown, html, resources,
                        user_prompt_val, urls_text_val,
                        status_html,
                        get_system_status_html(),
                        get_user_status_html(request)
                    )
                user_id = user_id_or_error

            # Save session data
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

            # Update session status indicator
            if local_mode:
                status_html = ''  # Local mode doesn't display session status
            else:
                status_html = f"""
                <div class="status-indicator status-success">
                    ✅ 会话已保存 | 最后更新: {session_data['timestamp']}
                </div>
                """

            return (
                result, workdir, markdown, html, resources,  # Output display
                workdir, result, markdown, html, resources,  # State saving
                user_prompt_val, urls_text_val,  # Input state saving
                status_html,  # Status indicator
                get_system_status_html(),  # System status
                get_user_status_html(request)  # User status
            )

        # Restore state function
        def restore_latest_results(workdir, result, markdown, html, resources, user_prompt_state, urls_text_state,
                                   request: gr.Request):
            local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

            # Determine user ID
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
                    return result, workdir, markdown, html, resources, user_prompt_state, urls_text_state, status_html, get_system_status_html()
                user_id = user_id_or_error

            # Reload session data
            session_data = load_session_data(user_id)

            # Update status indicator
            if local_mode:
                status_html = ''  # Local mode doesn't display status
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

            return (
                session_data.get('result', result),
                session_data.get('workdir', workdir),
                session_data.get('markdown', markdown),
                session_data.get('html', html),
                session_data.get('resources', resources),
                session_data.get('user_prompt', user_prompt_state),
                session_data.get('urls_text', urls_text_state),
                status_html,
                get_system_status_html()
            )

        # Cleanup function
        def clear_all_inputs_and_state(request: gr.Request):
            local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

            # Determine user ID
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
                    return '', None, '', '', '', '', '', '', '', '', '', '', '', '', '', status_html, get_system_status_html(), get_user_status_html(
                        request)
                user_id = user_id_or_error

            # Force cleanup user task
            user_status_manager.force_cleanup_user(user_id)

            # Cleanup session data file
            try:
                session_file = get_session_file_path(user_id)
                if os.path.exists(session_file):
                    os.remove(session_file)
            except Exception as e:
                logger.info(f'Failed to cleanup session file: {e}')

            if local_mode:
                status_html = ''  # Local mode doesn't display status
            else:
                status_html = """
                <div class="status-indicator status-info">
                    🧹 会话数据已清理
                </div>
                """

            return '', None, '', '', '', '', '', '', '', '', '', '', '', '', '', status_html, get_system_status_html(), get_user_status_html(
                request)

        # Clear workspace and keep state
        def clear_workspace_keep_state(current_workdir_val, current_result_val, current_markdown_val, current_html_val,
                                       current_resources_val, request: gr.Request):
            clear_result, clear_markdown, clear_resources = clear_workspace(request)

            local_mode = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'

            if local_mode:
                status_html = ''  # Local mode doesn't display status
            else:
                status_html = """
                <div class="status-indicator status-success">
                    🧹 工作空间已清理，会话数据已保留
                </div>
                """

            return clear_result, clear_markdown, clear_resources, current_workdir_val, current_result_val, current_markdown_val, current_html_val, current_resources_val, status_html, get_system_status_html()

        # Refresh system status function
        def refresh_system_status():
            return get_system_status_html()

        # Initialize on page load
        demo.load(
            fn=initialize_page,
            outputs=[
                user_status,
                user_prompt, urls_text,
                result_output, workdir_output, markdown_output, html_output if not local_mode else markdown_output,
                resources_output,
                current_workdir, current_result, current_markdown, current_html, current_resources,
                current_user_prompt, current_urls_text, session_status, system_status
            ]
        )

        # Periodic status display refresh
        def periodic_status_update(request: gr.Request):
            """Periodically update status display"""
            return get_user_status_html(request), get_system_status_html()

        # Use timer component to implement periodic status updates
        status_timer = gr.Timer(10)  # Trigger every 10 seconds
        status_timer.tick(
            fn=periodic_status_update,
            outputs=[user_status, system_status]
        )

        # Fullscreen functionality event binding
        fullscreen_btn.click(
            fn=toggle_fullscreen,
            inputs=[current_markdown, current_html],
            outputs=[fullscreen_modal, fullscreen_markdown, fullscreen_html]
        )

        close_btn.click(
            fn=close_fullscreen,
            outputs=[fullscreen_modal, fullscreen_markdown, fullscreen_html]
        )

        # Event binding
        run_btn.click(
            fn=run_research_workflow_with_state,
            inputs=[
                user_prompt, uploaded_files, urls_text,
                current_workdir, current_result, current_markdown, current_html, current_resources,
                current_user_prompt, current_urls_text
            ],
            outputs=[
                result_output, workdir_output, markdown_output, html_output if not local_mode else markdown_output,
                resources_output,
                current_workdir, current_result, current_markdown, current_html, current_resources,
                current_user_prompt, current_urls_text, session_status, system_status, user_status
            ],
            show_progress=True
        )

        # Restore recent results
        restore_btn.click(
            fn=restore_latest_results,
            inputs=[current_workdir, current_result, current_markdown, current_html, current_resources,
                    current_user_prompt, current_urls_text],
            outputs=[result_output, workdir_output, markdown_output, html_output if not local_mode else markdown_output,
                     resources_output, user_prompt, urls_text, session_status, system_status]
        )

        # Refresh system status
        refresh_status_btn.click(
            fn=refresh_system_status,
            outputs=[system_status]
        )

        clear_btn.click(
            fn=clear_workspace_keep_state,
            inputs=[current_workdir, current_result, current_markdown, current_html, current_resources],
            outputs=[result_output, markdown_output, resources_output, current_workdir, current_result,
                     current_markdown, current_html, current_resources, session_status, system_status]
        ).then(
            fn=clear_all_inputs_and_state,
            outputs=[
                user_prompt, uploaded_files, urls_text,
                result_output, workdir_output, markdown_output, html_output if not local_mode else markdown_output,
                resources_output,
                current_workdir, current_result, current_markdown, current_html, current_resources,
                current_user_prompt, current_urls_text, session_status, system_status, user_status
            ]
        )

        # Example data
        gr.Examples(
            examples=[
                [
                    '深入分析和总结下列文档',
                    None,
                    'https://modelscope.cn/models/ms-agent/ms_agent_resources/resolve/master/numina_dataset.pdf'
                ],
                [
                    'Qwen3跟Qwen2.5对比，有哪些优化？',
                    None,
                    'https://arxiv.org/abs/2505.09388\nhttps://arxiv.org/abs/2412.15115'
                ],
                [
                    'Analyze and summarize the following documents, you must use English to answer.',
                    None,
                    'https://arxiv.org/abs/1706.03762'
                ]
            ],
            inputs=[user_prompt, uploaded_files, urls_text],
            label='示例 | Examples'
        )

    return demo


def launch_server(
        server_name: Optional[str] = '0.0.0.0',
        server_port: Optional[int] = 7860,
        share: Optional[bool] = False,
        debug: Optional[bool] = False,
        show_error: Optional[bool] = False,
        gradio_default_concurrency_limit: Optional[int] = GRADIO_DEFAULT_CONCURRENCY_LIMIT,
) -> None:

    # Create interface
    demo = create_interface()

    # Configure Gradio queue concurrency control
    demo.queue(default_concurrency_limit=gradio_default_concurrency_limit)

    # Launch application
    demo.launch(
        server_name=server_name,
        server_port=server_port,
        share=share,
        debug=debug,
        show_error=show_error,
    )


if __name__ == '__main__':
    launch_server()
