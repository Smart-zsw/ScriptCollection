import os
import shutil
import datetime
import logging
import re
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

LOG_FILE = os.getenv('LOG_FILE', '/config/logs/sync.log')
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
SYNC_DIRECTORIES = os.getenv('SYNC_DIRECTORIES', '').split(';')  # 多个路径映射用分号分隔
MEDIA_FILE_TYPES = os.getenv('MEDIA_FILE_TYPES',
                             "*.mp4;*.mkv;*.ts;*.iso;*.rmvb;*.avi;*.mov;*.mpeg;*.mpg;*.wmv;*.3gp;*.asf;*.m4v;*.flv;*.m2ts;*.strm;*.tp;*.f4v").split(
    ';')
OVERWRITE_EXISTING = os.getenv('OVERWRITE_EXISTING', 'False').lower() == 'true'
ENABLE_CLEANUP = os.getenv('ENABLE_CLEANUP', 'False').lower() == 'true'
FULL_SYNC_ON_STARTUP = os.getenv('FULL_SYNC_ON_STARTUP', 'True').lower() == 'true'
MAX_LOG_FILE_SIZE = 10 * 1024 * 1024
MAX_LOG_FILES = int(os.getenv('MAX_LOG_FILES', 5))
USE_DIRECT_LINK = os.getenv('USE_DIRECT_LINK', 'False').lower() == 'true'
BASE_URL = os.getenv('BASE_URL', '')

# 忽略的文件扩展名
IGNORE_FILE_TYPES = ['.mp']

# 初始化日志
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='[%(asctime)s] %(message)s', datefmt='%Y/%m/%d %H:%M:%S')
console = logging.StreamHandler()
console.setLevel(logging.INFO)
formatter = logging.Formatter('%(message)s')
console.setFormatter(formatter)
logging.getLogger('').addHandler(console)


def log_message(message):
    logging.info(message)
    manage_log_files()


# 日志管理函数，用于处理日志文件大小和数量
def manage_log_files():
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_LOG_FILE_SIZE:
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        os.rename(LOG_FILE, f"{LOG_FILE}.{timestamp}")
        with open(LOG_FILE, 'w') as log_file:
            log_file.write(
                f"[{datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S')}] 日志文件大小超过限制，已创建新日志文件\n")

    log_dir = os.path.dirname(LOG_FILE)
    log_files = sorted([f for f in os.listdir(log_dir) if f.startswith(os.path.basename(LOG_FILE))], reverse=True)
    if len(log_files) > MAX_LOG_FILES:
        for old_log in log_files[MAX_LOG_FILES:]:
            os.remove(os.path.join(log_dir, old_log))


log_message("========== 同步和清理任务开始 {} ==========".format(datetime.datetime.now()))


class SyncHandler(FileSystemEventHandler):
    def __init__(self, source_dir, target_dir, media_prefix):
        super().__init__()
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.media_prefix = media_prefix

    def get_relative_path(self, full_path):
        return os.path.relpath(full_path, self.source_dir).replace("\\", "/")

    def is_media_file(self, relative_path):
        """检查文件是否是媒体文件"""
        return any(re.fullmatch(pattern.replace("*", ".*"), relative_path) for pattern in MEDIA_FILE_TYPES)

    def is_ignored_file(self, relative_path):
        """检查文件是否是需要忽略的文件类型（例如 .mp）"""
        return os.path.splitext(relative_path)[1].lower() in IGNORE_FILE_TYPES

    def handle_file_event(self, event, relative_path):
        """处理文件的创建、修改或删除"""
        if self.is_ignored_file(relative_path):
            log_message(f"跳过: 忽略文件类型: {relative_path}")
            return

        if event.event_type in ['created', 'modified']:
            if self.is_media_file(relative_path):
                self.create_strm_file(relative_path)
            else:
                self.sync_file(relative_path)
        elif event.event_type == 'deleted' and ENABLE_CLEANUP:
            self.delete_target_file(relative_path)

    def handle_directory_event(self, event, relative_path):
        """处理目录的创建或删除"""
        target_dir_path = os.path.join(self.target_dir, relative_path).replace("\\", "/")
        if event.event_type == 'deleted' and ENABLE_CLEANUP:
            if os.path.exists(target_dir_path):
                try:
                    shutil.rmtree(target_dir_path)
                    log_message(f"成功删除目标目录: {target_dir_path}")
                except Exception as e:
                    log_message(f"错误: 无法删除目标目录: {target_dir_path}, {e}")
        elif event.event_type == 'created':
            if not os.path.exists(target_dir_path):
                try:
                    os.makedirs(target_dir_path, exist_ok=True)
                    log_message(f"成功创建目标目录: {target_dir_path}")
                except Exception as e:
                    log_message(f"错误: 无法创建目标目录: {target_dir_path}, {e}")

    def create_strm_file(self, relative_path):
        """生成 .strm 文件"""
        target_strm_file = os.path.join(self.target_dir, os.path.splitext(relative_path)[0] + ".strm").replace("\\",
                                                                                                               "/")
        if os.path.exists(target_strm_file) and not OVERWRITE_EXISTING:
            log_message(f"跳过: .strm 文件已存在: {target_strm_file}")
            return

        strm_content = f"{BASE_URL}{self.media_prefix}/{relative_path}" if USE_DIRECT_LINK else f"{self.media_prefix}/{relative_path}"

        try:
            os.makedirs(os.path.dirname(target_strm_file), exist_ok=True)
            with open(target_strm_file, "w") as f:
                f.write(strm_content)
            log_message(f"成功生成 .strm 文件: {target_strm_file}")
        except Exception as e:
            log_message(f"错误: 无法生成 .strm 文件: {target_strm_file}, {e}")

    def sync_file(self, relative_path):
        """同步文件"""
        source_file_path = os.path.join(self.source_dir, relative_path).replace("\\", "/")
        target_file_path = os.path.join(self.target_dir, relative_path).replace("\\", "/")

        os.makedirs(os.path.dirname(target_file_path), exist_ok=True)

        if not OVERWRITE_EXISTING and os.path.exists(target_file_path):
            log_message(f"跳过: 非媒体文件已存在: {target_file_path}")
            return

        try:
            shutil.copy2(source_file_path, target_file_path)
            log_message(f"成功同步非媒体文件: {source_file_path} -> {target_file_path}")
        except Exception as e:
            log_message(f"错误: 无法同步非媒体文件: {source_file_path} -> {target_file_path}, {e}")

    def delete_target_file(self, relative_path):
        """删除目标文件及其关联的 .strm 文件"""
        target_file_path = os.path.join(self.target_dir, relative_path).replace("\\", "/")

        # 如果目标是一个文件，首先删除它
        if os.path.exists(target_file_path):
            try:
                # 如果是文件夹，使用 rmtree 删除文件夹
                if os.path.isdir(target_file_path):
                    shutil.rmtree(target_file_path)
                    log_message(f"成功删除目标目录: {target_file_path}")
                else:
                    os.remove(target_file_path)
                    log_message(f"成功删除目标文件: {target_file_path}")
            except Exception as e:
                log_message(f"错误: 无法删除目标文件/目录: {target_file_path}, {e}")

        # 如果是媒体文件且存在相应的 .strm 文件，删除对应的 .strm 文件
        # 判断是否是媒体文件并构建 .strm 文件路径
        if self.is_media_file(relative_path):
            strm_file_path = os.path.splitext(target_file_path)[0] + ".strm"
            if os.path.exists(strm_file_path):
                try:
                    os.remove(strm_file_path)
                    log_message(f"成功删除关联的 .strm 文件: {strm_file_path}")
                except Exception as e:
                    log_message(f"错误: 无法删除 .strm 文件: {strm_file_path}, {e}")

    def on_created(self, event):
        relative_path = self.get_relative_path(event.src_path)
        if event.is_directory:
            self.handle_directory_event(event, relative_path)
        else:
            self.handle_file_event(event, relative_path)

    def on_modified(self, event):
        # 对于目录的修改事件，一般不需要特别处理
        if not event.is_directory:
            relative_path = self.get_relative_path(event.src_path)
            self.handle_file_event(event, relative_path)

    def on_deleted(self, event):
        relative_path = self.get_relative_path(event.src_path)
        if event.is_directory:
            self.handle_directory_event(event, relative_path)
        else:
            self.handle_file_event(event, relative_path)


# 启动文件系统监控器
observers = []
for mapping in SYNC_DIRECTORIES:
    try:
        source_dir, target_dir, media_prefix = mapping.split(" ", 2)
    except ValueError:
        log_message(f"配置错误: SYNC_DIRECTORIES 中的映射 '{mapping}' 格式不正确。应为 'source_dir target_dir media_prefix'")
        continue

    log_message(f"开始监控目录: {source_dir} -> {target_dir} (media 前缀: {media_prefix})")

    event_handler = SyncHandler(source_dir, target_dir, media_prefix)

    # 执行初始全量同步
    if FULL_SYNC_ON_STARTUP:
        log_message(f"执行初始全量同步: {source_dir} -> {target_dir}")
        for root, dirs, files in os.walk(source_dir):
            relative_root = os.path.relpath(root, source_dir).replace("\\", "/")
            if relative_root == ".":
                relative_root = ""
            # 创建目录结构
            target_root = os.path.join(target_dir, relative_root).replace("\\", "/")
            if not os.path.exists(target_root):
                try:
                    os.makedirs(target_root, exist_ok=True)
                    log_message(f"创建目录: {target_root}")
                except Exception as e:
                    log_message(f"错误: 无法创建目录: {target_root}, {e}")

            for file in files:
                relative_path = os.path.join(relative_root, file).replace("\\", "/")
                if event_handler.is_media_file(relative_path):
                    event_handler.create_strm_file(relative_path)
                else:
                    event_handler.sync_file(relative_path)
        FULL_SYNC_ON_STARTUP = False

    observer = Observer()
    observer.schedule(event_handler, path=source_dir, recursive=True)
    observer.start()
    observers.append(observer)

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    log_message("========== 停止监控任务 ==========")
    for observer in observers:
        observer.stop()
    for observer in observers:
        observer.join()

log_message("========== 实时监控同步和清理任务完成 {} ==========".format(datetime.datetime.now()))
