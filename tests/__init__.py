"""测试包：在导入 workhub 之前把数据目录指到临时目录，避免污染真实环境。"""
import os
import tempfile

os.environ.setdefault("WORKHUB_DATA", tempfile.mkdtemp(prefix="workhub-test-data-"))
os.environ.setdefault("WORKHUB_WORKDIR", tempfile.mkdtemp(prefix="workhub-test-wd-"))
