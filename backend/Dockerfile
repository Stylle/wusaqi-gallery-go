FROM python:3.13-slim

WORKDIR /app

# 依赖层单独 COPY，利用构建缓存（代码改动不重装依赖）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# 不写 .pyc（容器只读运行即可）+ 日志直出 stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
