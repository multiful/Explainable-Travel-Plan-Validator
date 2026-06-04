# Explainable Travel Plan Validator — 컨테이너 이미지
FROM python:3.12-slim

# 빌드 도구 (pdfplumber/pandas 휠 설치 안정성 확보)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 레이어 (소스보다 먼저 복사해 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 애플리케이션 소스 + 데이터
COPY . .

EXPOSE 8000

# 컨테이너 헬스체크 — 기동 후 /health 200 확인
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
