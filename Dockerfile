FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装依赖
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝应用文件
COPY app/server.py .
COPY app/meters.py .
COPY app/monthly_energy.py .
COPY app/index.html .
COPY app/requirements.txt .
COPY app/dashboard.db .

# 暴露端口（默认 5000，可通过环境变量覆盖）
EXPOSE 5000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/')" || exit 1

# 启动命令
CMD ["python3", "-u", "server.py"]
