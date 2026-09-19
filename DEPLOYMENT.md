<!-- updated: 2026-09-19 | hash: 5b6bb7a9 | summary: Vercel 배포 설정과 검증 범위 및 운영 제약 -->
# Vercel 배포

프로젝트 루트를 배포한다. Python ASGI 진입점은 `app.py`이며 실제 앱은
`src.api.main:app`이다. 프레임워크는 FastAPI로 선택하고 Docker나 프론트엔드용
빌드 명령, Output Directory를 별도로 지정하지 않는다. `.python-version`은
Python 3.12를 지정한다. `package.json`의 pptxgenjs는 발표자료용이며 웹 빌드가 아니다.

## 환경변수

Vercel 프로젝트 설정에 Production과 필요한 Preview 환경변수를 등록한다.
`.env`는 업로드하지 않는다.

- `ENVIRONMENT=production`
- `API_AUTH_TOKEN`: 운영자가 생성한 접근 키. 웹 화면에서 첫 인증 오류 시 입력하며 메모리에만 보관한다.
- `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`: 문서 파싱과 설명 생성에 사용할 키와 계정에서 사용 가능한 모델.
- `KAKAO_REST_API_KEY`, `KAKAO_MOBILITY_KEY`: 장소 검색과 도로 이동시간 계산.
- `TOUR_API_KEY`, `SEOUL_DATA_API_KEY`: 관광 데이터와 서울 혼잡도.
- `CORS_ALLOWED_ORIGINS`: 별도 프론트엔드를 둘 경우 정확한 HTTPS origin. 같은 도메인의 웹 화면은 CORS 설정 없이 요청 가능.

Vercel 환경(`VERCEL=1`)에서는 환경 지정이 없으면 production이 기본값이다.
접근 키가 없으면 비용이 발생하는 API는 503으로 거부한다. 접근 키를
프론트엔드 소스에 넣지 않는다. 이 방식은 운영자/초대 사용자용이며, 공개 서비스의
회원 인증을 대체하지 않는다. 공개 운영에는 사용자 인증과 플랫폼 측 비용 제한이 필요하다.

## 서버리스 대응

- 정적 화면과 데이터 파일을 Python 함수 번들에 포함한다.
- 이동시간 캐시는 `/tmp/qtrip/route_cache.json`에 쓴다. 인스턴스 간 공유하거나 영구 저장하지 않는다.
- 업로드는 4MiB까지 허용한다. 큰 문서는 분할하거나 텍스트 입력을 사용한다.
- 함수 실행시간은 300초로 요청한다. 배포 계정에서 적용되는 실행시간을 확인한다.
- Rate Limit은 프로세스별이다. 여러 인스턴스 전체를 제한하려면 Vercel 방화벽 등의 별도 제한이 필요하다.
- SciPy, scikit-learn, OR-Tools를 포함하므로 실제 Linux 빌드의 함수 용량을 반드시 확인한다.
  용량 초과 시 라이브러리를 무작정 제외하면 최적화 기능이 달라진다. 백엔드를 별도
  컨테이너 서비스로 분리하는 방법을 검토한다.

## 공개 전 확인

로컬 테스트 통과는 Vercel 배포 성공을 보장하지 않는다. Preview 빌드에서
의존성 설치와 함수 크기, 콜드 스타트를 확인한 후 다음을 점검한다.

1. `/`, `/static/landing.css`, `/static/qtrip-map.png`가 200인지 확인한다.
2. `/health`가 200인지 확인한다. 이 엔드포인트는 외부 API 연결 성공을 보증하지 않는다.
3. 키 없이 `/api/validate` 요청 시 401, 올바른 키와 잘못된 요청 본문은 422인지 확인한다.
4. 웹에서 일정 텍스트와 4MiB 이하 PDF를 각각 입력하고 검증 결과까지 확인한다.
5. 실제 이동시간 API와 Claude 호출 성공 여부를 Vercel 로그에서 확인한다.
6. 모바일 화면과 재방문 시 서비스 워커의 새 버전 적용을 확인한다.

개발 확인: `python -m pytest tests/ -q`, `ruff check src/ tests/ app.py`.
