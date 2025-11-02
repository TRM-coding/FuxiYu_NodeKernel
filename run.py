import sys
import os

# 将项目根目录添加到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from __init__ import create_app

if __name__ == '__main__':
    app = create_app('development')
    app.run(debug=True)

