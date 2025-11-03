from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import json
import os

class AnimationProductionMode(Enum):
    """动画制作模式"""
    AUTO = "auto"              # 全自动模式
    HUMAN_CONTROLLED = "human" # 人工控制模式

class AnimationStatus(Enum):
    """动画状态"""
    PENDING = "pending"       # 等待制作
    DRAFT = "draft"           # 草稿阶段
    PREVIEW = "preview"       # 预览阶段  
    REVISION = "revision"     # 修订中
    APPROVED = "approved"     # 已批准
    COMPLETED = "completed"   # 制作完成
    FAILED = "failed"         # 制作失败

@dataclass
class AnimationTask:
    """动画任务数据结构"""
    task_id: str
    segment_index: int
    content: str
    content_type: str
    mode: AnimationProductionMode
    status: AnimationStatus
    
    # 制作相关
    script: Optional[str] = None
    manim_code: Optional[str] = None
    preview_video_path: Optional[str] = None
    final_video_path: Optional[str] = None
    placeholder_path: Optional[str] = None
    
    # 人机交互
    human_feedback: List[str] = None
    revision_count: int = 0
    max_revisions: int = 5
    
    # 时间信息
    audio_duration: float = 8.0
    creation_time: Optional[str] = None
    completion_time: Optional[str] = None
    
    def __post_init__(self):
        if self.human_feedback is None:
            self.human_feedback = []

@dataclass  
class PlaceholderConfig:
    """占位符配置"""
    width: int = 1280
    height: int = 720
    background_color: str = "#f0f0f0"
    text_color: str = "#333333"
    font_size: int = 48
    placeholder_text: str = "动画制作中..."
    show_content_preview: bool = True
    show_progress_indicator: bool = True

class AnimationTaskManager:
    """动画任务管理"""
    
    def __init__(self, project_dir):
        self.project_dir = project_dir
        self.tasks_file = os.path.join(project_dir, "animation_tasks.json")
        self.tasks: Dict[str, AnimationTask] = {}
        self.load_tasks()
    
    def create_task(self, segment_index, content, content_type, mode, audio_duration):
        """创建新动画任务，重复任务直接返回ID"""
        import uuid
        from datetime import datetime
        
        # 检查是否已存在相同段落的任务
        existing_task = self.get_task_by_segment(segment_index, content_type)
        if existing_task:
            print(f"发现已存在的任务: {existing_task.task_id}")
            return existing_task.task_id
        
        task_id = f"anim_{segment_index}_{uuid.uuid4().hex[:8]}"
        
        task = AnimationTask(
            task_id=task_id,
            segment_index=segment_index,
            content=content,
            content_type=content_type,
            mode=mode,
            status=AnimationStatus.PENDING,
            audio_duration=audio_duration,
            creation_time=datetime.now().isoformat()
        )
        
        self.tasks[task_id] = task
        self.save_tasks()
        print(f"创建新任务: {task_id}")
        return task_id
    
    def get_task_by_segment(self, segment_index, content_type):
        """根据段落索引和内容类型查找任务"""
        for task in self.tasks.values():
            if task.segment_index == segment_index and task.content_type == content_type:
                return task
        return None
    
    def update_task_status(self, task_id, status):
        """更新任务状态"""
        if task_id in self.tasks:
            self.tasks[task_id].status = status
            self.save_tasks()
    
    def add_human_feedback(self, task_id, feedback):
        """添加人工反馈"""
        if task_id in self.tasks:
            self.tasks[task_id].human_feedback.append(feedback)
            self.tasks[task_id].revision_count += 1
            self.save_tasks()
    
    def get_task(self, task_id):
        """获取任务"""
        return self.tasks.get(task_id)
    
    def get_tasks_by_status(self, status):
        """根据状态获取任务列表"""
        return [task for task in self.tasks.values() if task.status == status]
    
    def save_tasks(self):
        """保存任务到文件"""
        import json
        from dataclasses import asdict
        
        tasks_data = {}
        for task_id, task in self.tasks.items():
            task_dict = asdict(task)
            # 处理枚举类型
            task_dict['mode'] = task.mode.value
            task_dict['status'] = task.status.value
            tasks_data[task_id] = task_dict
        
        with open(self.tasks_file, 'w', encoding='utf-8') as f:
            json.dump(tasks_data, f, ensure_ascii=False, indent=2)
    
    def load_tasks(self):
        """从文件加载任务"""
        if not os.path.exists(self.tasks_file):
            return
            
        try:
            with open(self.tasks_file, 'r', encoding='utf-8') as f:
                tasks_data = json.load(f)
            
            for task_id, task_dict in tasks_data.items():
                # 恢复枚举类型
                task_dict['mode'] = AnimationProductionMode(task_dict['mode'])
                task_dict['status'] = AnimationStatus(task_dict['status'])
                
                self.tasks[task_id] = AnimationTask(**task_dict)
                
        except Exception as e:
            print(f"加载任务文件失败: {e}")

class PlaceholderGenerator:
    """占位符生成工具"""
    
    def __init__(self, config = None):
        self.config = config or PlaceholderConfig()
    
    def create_placeholder(self, task, output_path):
        """创建占位符视频"""
        from PIL import Image, ImageDraw, ImageFont
        import tempfile
        import subprocess
        
        # 创建占位符图片
        img = Image.new('RGB', (self.config.width, self.config.height), 
                       self.config.background_color)
        draw = ImageDraw.Draw(img)
        
        # 添加占位文本
        try:
            # 尝试使用自定义字体
            font_path = os.path.join(os.path.dirname(__file__), 'asset', '字魂龙吟手书(商用需授权).ttf')
            if os.path.exists(font_path):
                font = ImageFont.truetype(font_path, self.config.font_size)
            else:
                font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()
        
        # 主标题
        title = self.config.placeholder_text
        title_bbox = draw.textbbox((0, 0), title, font=font)
        title_width = title_bbox[2] - title_bbox[0]
        title_height = title_bbox[3] - title_bbox[1]
        title_x = (self.config.width - title_width) // 2
        title_y = self.config.height // 3
        
        draw.text((title_x, title_y), title, fill=self.config.text_color, font=font)
        
        # 内容预览
        if self.config.show_content_preview and task.content:
            content_preview = task.content[:50] + "..." if len(task.content) > 50 else task.content
            try:
                content_font = ImageFont.truetype(font_path, self.config.font_size // 2) if os.path.exists(font_path) else ImageFont.load_default()
            except:
                content_font = ImageFont.load_default()
            
            content_bbox = draw.textbbox((0, 0), content_preview, font=content_font)
            content_width = content_bbox[2] - content_bbox[0]
            content_x = (self.config.width - content_width) // 2
            content_y = title_y + title_height + 50
            
            draw.text((content_x, content_y), content_preview, 
                     fill=self.config.text_color, font=content_font)
        
        # 进度指示器
        if self.config.show_progress_indicator:
            status_text = f"状态: {task.status.value} | 类型: {task.content_type}"
            try:
                status_font = ImageFont.truetype(font_path, self.config.font_size // 3) if os.path.exists(font_path) else ImageFont.load_default()
            except:
                status_font = ImageFont.load_default()
            
            status_bbox = draw.textbbox((0, 0), status_text, font=status_font)
            status_width = status_bbox[2] - status_bbox[0]
            status_x = (self.config.width - status_width) // 2
            status_y = self.config.height - 100
            
            draw.text((status_x, status_y), status_text, 
                     fill=self.config.text_color, font=status_font)
        
        # 保存占位符图片
        temp_img_path = output_path.replace('.mov', '_placeholder.png')
        img.save(temp_img_path)
        
        # 转换为视频
        try:
            cmd = [
                'ffmpeg', '-y',
                '-f', 'image2', '-loop', '1',
                '-i', temp_img_path,
                '-t', str(task.audio_duration),
                '-pix_fmt', 'yuv420p',
                '-r', '15',
                output_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            os.remove(temp_img_path)  # 清理临时文件
            return output_path
        except Exception as e:
            print(f"创建占位符视频失败: {e}")
            return None
