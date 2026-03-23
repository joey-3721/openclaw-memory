FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8765

# 代理（内网代理，确保容器内 TMDB 等外网请求可用）
ENV HTTP_PROXY=http://192.168.50.209:7890
ENV HTTPS_PROXY=http://192.168.50.209:7890
ENV http_proxy=http://192.168.50.209:7890
ENV https_proxy=http://192.168.50.209:7890

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765"]
