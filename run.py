import sys
import os
from pathlib import Path

from dotenv import load_dotenv

# 加载仓库根目录 .env（三仓库统一网络键名）
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

# 将父目录添加到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from FuxiYu_NodeKernel import create_app  # noqa: E402
from FuxiYu_NodeKernel.config import NetConfig  # noqa: E402

if __name__ == '__main__':
    app = create_app('development')
    app.run(host='0.0.0.0', port=NetConfig.NODE_PORT, debug=True, threaded=True)
