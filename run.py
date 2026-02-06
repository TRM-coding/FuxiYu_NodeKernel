import sys
import os

# 将父目录添加到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from FuxiYu_NodeKernel import create_app

if __name__ == '__main__':
    app = create_app('development')
    app.run(host = '0.0.0.0', port=5001, debug=True)

