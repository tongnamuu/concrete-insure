# InsureLens

보험약관 PDF와 사용자 설명·처방 자료에서 관련 보장 항목과 근거를 찾아 보여 주는 웹 에이전트입니다. 약관 문구는 원문 그대로 표시하고 PDF에 형광펜 주석으로 저장합니다. **약관에 명시된 보장 항목과 성분 근거를 통한 연결**을 표시하며, 실제 가입·진단·처방·지급 조건 충족 여부는 별도 확인 대상으로 둡니다. 보험금 지급 여부나 질병을 추정하지 않습니다.

백엔드는 **Python FastAPI + NeMo Microservices Python SDK + NVIDIA NeMo Agent Toolkit(NAT)** 입니다. JavaScript는 PDF.js 웹 화면과 브라우저 검사에 사용합니다. Node.js 서버나 Node로 돌아가는 에이전트는 없습니다. 사용자 접점은 웹이며 NemoClaw와 파인튜닝은 포함하지 않습니다.

## 실행

Python 3.12 또는 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22.13 이상이 필요합니다. Node/npm은 PDF.js 정적 파일 설치와 브라우저 검사 도구용입니다.

```sh
uv sync --extra dev
uv run python scripts/install-git-hooks.py
npm ci
# 처음 설치한 경우에만 .env.example을 .env로 복사합니다.
# 기존 .env가 있으면 그대로 사용합니다.
uv run insure-lens
```

브라우저에서 http://127.0.0.1:8000 을 엽니다. 기존 `npm start`도 Python 서버를 실행하도록 연결했습니다. 한 프로젝트의 데이터 디렉터리에는 서버를 하나만 실행하세요.

`.env`의 `NVIDIA_API_KEY`만 설정하면 기본 Nemotron 모델을 사용할 수 있습니다. 기본값은 `nvidia/nemotron-3.5-lightning-30b-a3b`입니다. 키가 없으면 조사를 시작할 수 없고 설정 필요 상태를 표시합니다. 검색 버튼을 누르면 전송 동의문만 표시됩니다. 매번 체크 후 진행해야 요청을 전송하며, 취소·미동의 시 새 작업이나 결과를 만들지 않습니다. 처방 자료 업로드도 전송 전에 같은 동의를 받습니다. 모든 조사는 NAT와 Nemotron NIM을 거칩니다. 제공자 시간 초과나 잘못된 도구 응답은 실패로 알리며 재시도할 수 있습니다.

| 선택 설정 | 필요한 경우 |
|---|---|
| `NIM_BASE_URL`, `NIM_MODEL` | 기본 hosted NIM endpoint 또는 모델 변경 |
| `NEMO_MICROSERVICES_BASE_URL` | 별도로 배포한 NeMo 플랫폼 주소. 일반 hosted NIM 추론에는 입력할 필요 없음 |
| `NIM_OCR_URL` | 이미지·스캔 처방전 OCR. 실제 사용 가능한 한국어 지원 endpoint 필요 |
| `MFDS_API_KEY` | 공공데이터포털 의약품 제품 허가정보 v08 실시간 조회용 디코딩 키 |
| `TRANSLATION_MODEL` | API의 선택 번역용 모델. 웹 화면에는 추가 설정을 제공하지 않음 |

NeMo Microservices SDK는 서비스에 접속하는 클라이언트입니다. SDK 설치만으로 Guardrails·Evaluator·Customizer 서비스가 배포되지는 않습니다. 현재 SDK로 실행하는 기능은 **NIM 추론**이며, 별도 NeMo Guardrails Microservice를 사용했다고 표시하지 않습니다. 원문·검색어·좌표 검증은 애플리케이션에서 항상 수행합니다.

## 사용 흐름

1. 보험약관 PDF를 업로드합니다. 샘플 자료 없이 본인 파일로 동작합니다.
2. 질문이나 **상황 설명하기**에 사고 경위나 진료 상황 등을 입력합니다. 설명만 있어도 진행하며, 사용자 진술을 확인된 진단으로 취급하지 않습니다.
3. 처방전·약봉투 이미지 또는 처방 PDF가 있다면 선택적으로 업로드합니다. 추출 후보는 사용자가 확인한 뒤 적용됩니다. 텍스트가 있는 처방 PDF는 로컬에서 읽고, 이미지·스캔은 OCR 설정과 전송 동의가 필요합니다.
4. 조플루자·타미플루는 출처가 등록된 제조사 자료를 통해 성분과 약관 표현을 연결합니다. 이 자료는 **날짜가 명시된 정적 참고 자료**이며 실시간 식약처 조회나 진단 당시 허가 인증이 아닙니다. 다른 약품은 식약처 조회 설정 후 정확한 제품을 직접 선택합니다.
5. 관련 특약·지급사유·정의·제외사항·청구서류를 원문으로 확인합니다. 위치 버튼으로 PDF를 이동하고, 표시된 PDF를 저장하면 표준 Highlight 주석이 포함됩니다.
6. 새로고침하면 약관은 유지하고 완료된 결과는 초기화합니다. 진행 중 작업은 SSE로 다시 연결됩니다. **검색 결과 지우기**는 표시만 지우며, **자료 삭제**는 원본과 저장된 결과를 삭제합니다.

검색 실패나 약 이름의 부재를 보장 제외로 해석하지 않습니다. 성분의 염·제형을 임의로 통합하거나 약품에서 질병을 추정하지 않습니다.

## 모듈과 실행 규약

입출력은 [contracts.md](docs/contracts.md), 책임은 [module-definition.md](docs/module-definition.md)에 정의합니다.

| Python 모듈 | 책임 |
|---|---|
| `insurelens/server.py`, `store.py` | 업로드·소유권·SQLite·작업 취소·재연결 가능한 SSE |
| `providers.py` | 실제 `AsyncNeMoMicroservices` SDK 추론, OCR, 식약처 조회 |
| `nat.py` | 등록된 NAT workflow에서 Python 에이전트를 직접 실행 |
| `agent.py`, `agents/` | 명시 정보 추출 → 제품 근거 → ReAct 검색/문맥 → 보장 항목 연결 → 원문 검증 |
| `pdf.py`, `python/pdf_worker.py` | 제한 시간·취소가 있는 별도 프로세스, 문자 좌표 추적, 원문 검증, 표준 주석 |
| `skills_cli.py`, `skills/` | 세 도구의 JSON 입출력 CLI와 skills.sh 호환 지침 |
| `public/` | 1:1 split PDF.js 화면 |

ReAct의 모델 출력은 허용된 도구와 ID를 고르는 데만 사용합니다. 자유롭게 생성한 최종 답변은 폐기하고, 애플리케이션이 PDF의 source span을 직접 반환합니다. 번역은 참고용 표현이며 검색·인용의 원문을 대체하지 않습니다. 원문 계산·주석 같은 결정적인 작업에는 모델을 사용하지 않습니다.

## 스킬과 테스트

웹과 CLI는 같은 Python 모듈을 호출합니다. 웹이 매번 별도 CLI 프로세스를 실행하는 구조는 아닙니다. 세 스킬은 `ocr-prescription`, `drug-ingredient-resolver`, `pdf-iso32000-annotator`이며 각 `SKILL.md`에 JSON 입출력과 사용법이 있습니다. 상위 원문 규칙은 `insure-lens-source`입니다.

```sh
uv run --extra dev pytest -q
npm run test:browser
npm run test:browser:coverage
npm run test:browser:consent
npm run test:browser:progress
npx skills@1.7.0 add . --list
# SkillSpector를 별도 설치한 경우:
sh scripts/scan-skills.sh
```

브라우저 검사는 자체 임시 저장소와 합성 PDF를 사용합니다. 시스템 Chromium을 쓰려면 `BROWSER_EXECUTABLE`을 지정하세요. 없으면 `npx playwright install chromium`으로 설치합니다. [검증 기록](docs/validation.md)에 실제 실행 결과와 미검증 기능을 구분합니다.

## 실행 로그와 코드 리뷰

웹 서버의 실행 로그는 서버를 실행한 터미널의 표준 오류(`stderr`)에 JSON 한 줄씩 출력합니다. 로그 파일은 생성하거나 저장하지 않으며 추가 환경변수 설정도 필요 없습니다. 요청·작업 ID로 처리 단계와 NVIDIA/PDF 소요 시간, 실패·취소를 확인할 수 있습니다. 사용자 입력·약관 원문·키·개인 경로는 기록하지 않습니다. [로깅 지침](docs/logging.md)을 따릅니다.

코드 변경은 작업 브랜치에서 검증 후 PR로 제출합니다. 변경 내용과 테스트 결과를 PR에서 확인하고 병합 여부를 결정합니다. 작업 규칙은 [AGENTS.md](AGENTS.md)에 기록했습니다.

저장소를 복제한 뒤 위 설치 명령으로 Git 훅을 반드시 설정합니다. 설정 후 `git commit` 직전에 **커밋에 포함될 전체 파일과 파일명**을 검사하고 개인 경로가 있거나 검사를 실행할 수 없으면 커밋을 차단합니다. 작업 폴더에서만 지우고 다시 스테이징하지 않은 경로도 차단합니다. macOS·Linux·Windows 홈 경로와 macOS 개인 임시 경로, URL 인코딩·UTF-16·심볼릭 링크 대상도 검사하며 발견한 경로 자체는 출력하지 않습니다.

수동 점검은 `uv run python scripts/check-personal-paths.py`로 실행합니다. `--no-verify`나 훅 설정 해제로 검사를 우회하지 않습니다. 로컬 Git 설정은 복제 시 전달되지 않으므로 새 복제본마다 설치해야 하며, GitHub PR·푸시에서도 같은 검사를 다시 실행합니다. 경로 패턴으로 식별할 수 없는 사용자 지정 경로는 리뷰에서도 확인합니다.

## 지원 범위

- 약관: 20MiB·1000쪽·200만 문자. 원문을 보장하기 위해 텍스트 레이어 없는 약관은 거절합니다. 처방 자료는 8MiB·8쪽, 이미지 2500만 픽셀까지입니다.
- 첫 검색어 추출은 명시적 JSON Schema로 요청하며 최대 60초입니다. 이후 NIM 호출도 각각 최대 60초입니다. 전체 검색은 여러 호출로 구성되므로 총 소요 시간은 1분을 넘을 수 있습니다. 모델 응답 대기는 5초마다 SSE로 현재 단계와 경과 시간을 보내며, 취소하면 해당 호출도 취소됩니다. 시간 초과 시 자동 재시도나 로컬 대체 결과를 만들지 않습니다.
- PDF 작업은 기본 120초이며 취소 시 프로세스를 종료합니다. 긴 요청은 작업 ID를 반환하고 SSE로 완료를 알립니다.
- `.local-data`에 기존과 호환되는 SQLite·원본·인덱스를 보관합니다. 재시작하면 완료된 기록은 유지하고 중단된 작업은 `SERVER_RESTARTED`로 표시합니다.
- 로컬 단일 사용자 데모입니다. 서비스 배포용 계정 인증·암호화·보관 기한·분산 큐는 별도입니다.
- 원문은 PDF text layer에서 추출한 동일 Unicode 구간이며 추출 줄바꿈을 포함합니다. 전체 약관의 모든 관련 문구를 찾았다는 보장은 하지 않습니다. 지원하지 않는 조항 형식은 미확인 상태로 남습니다.
- ISO 32000의 Highlight/QuadPoints/Contents/AP 주석을 사용합니다. 전체 표준 적합성 인증을 의미하지 않으며 원본은 보존합니다. PyMuPDF는 AGPL/상용 이중 라이선스입니다.
- [OpenShell](integrations/openshell/README.md)은 선택적 정책 예제만 제공하며 현재 실행 환경에 적용됐다고 주장하지 않습니다. 범용 `build.nvidia.com Skill API`는 확인된 규약이 없어 임의로 만들지 않았습니다.

NVIDIA 연결과 공식 출처는 [nvidia-stack.md](docs/nvidia-stack.md)를 참고하세요.
