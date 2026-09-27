# Python 전환 검증

검증일: 2026-09-27. Python3.12.13, FastAPI0.141.1, PyMuPDF1.28.2, nemo-microservices1.5.0, NVIDIA NeMo Agent Toolkit1.9.0. Node는 PDF.js 자산과 Chromium 검사에만 사용한다.

## 실행 결과

- 잠금 파일 설치: `uv sync --extra nat --extra dev --locked`, `npm ci --ignore-scripts` 성공. npm 의존성 검사 시 취약점0.
- Python 전체 검사: **96 passed, 20 subtests passed**, 실패0. PDF 원문·좌표·회전/CropBox·표준 주석, SDK 요청·응답 형식, 입력 규약, 성분 출처, ReAct 도구 제한, 번역 경계, 보장 항목 근거, 빈 결과 제거, 세션 격리, SSE 재생, 취소·재시작, 세 스킬 CLI 포함.
- 실제 NAT runtime 검사7개: Python 직접 호출, 콜백 전달, ContextVar 분리, 불투명 토큰 입력, 취소, provider 오류 타입 보존. Node 실행이나 HTTP 중계가 없다.
- SDK 검사는 실제 AsyncNeMoMicroservices와 HTTP MockTransport를 사용해 인증 헤더·URL의 단일 `/v1`·JSON mode·native tool definitions·finish_reason·취소·오류 코드를 확인한다.
- 실제 NVIDIA API + Python SDK + NAT ReAct 호출: 공개 약품명과 합성 약관만 사용, **23.30초**, `mode=nim-react`, warnings없음, 원문9건과 제품 근거1건. 테스트용 약관 서식의 보장 연결 상태는 unresolved였으며 지급 판단을 생성하지 않았다. 실제 사용자 의료자료·약관은 외부 전송하지 않았다.
- Chromium smoke/coverage 모두 통과, browserErrors없음. Python 임시 서버·자체 DATA_DIR·합성 PDF로 업로드 → SSE → 원문 → text layer·좌표 강조·확대 → 표준 주석 저장 → 새로고침 → OCR 후보 확인 → 삭제를 검사했다. 보장 항목·성분 간접 연결·4종 조항·인접 특약 혼입 방지·빈 카드0도 확인했다.
- 업로드 본문을 받는 중 사건을 삭제하는 경쟁, 이전 파일 정리 실패 후 새 문서 보존, 출력 파이프가 막힌 PDF 작업의 제한 시간 종료를 재현하고 회귀 검사를 추가했다.

## 실제 약관 로컬 검사

두 파일은 사용자가 제공한 원본을 읽기 전용으로 사용했다. 결과 PDF는 임시 폴더에서 생성·검증 후 삭제했고 배포물에 사용자 자료를 넣지 않았다. 외부 호출은 하지 않았다. 입력은 두 경우 모두 “조플루자를 처방받았습니다.”였다.

| 파일 | 쪽 | 색인 | Python/NAT 조사 | 보장 항목 | 원문·주석 | 전체 처리 |
|---|---:|---:|---:|---|---:|---:|
| CM210S_20260801.pdf | 230 | 13.82초 | 2.30초 | 미확인 | 0·0 | 30.67초 |
| CM11M0_20250901.pdf | 412 | 24.03초 | 8.23초 | 관련 항목1개 | 7·7 | 58.40초 |

두 사본 모두 전체 페이지의 추출 원문이 저장 전후 동일했다. 빈 원문0건. 230쪽 문서에서 근거를 찾지 못한 결과를 보장 제외로 해석하지 않는다. 시간은 이 컴퓨터에서 다른 검사와 함께 실행한 관측값이며 환경에 따라 달라진다.

## 스킬 검사

세 신규 스킬의 quick_validate 통과. CLI6개 검사로 JSON 입출력·동의 경계·원문 후보·제품 출처·PDF Highlight·변조 및 원본 덮어쓰기 거부를 확인했다. skills.sh 목록에서 상위 지침과 세 도구를 발견한다.

SkillSpector2.12.0의 `--recursive --no-llm` 정적 검사 결과는 [skillspector-report.json](skillspector-report.json)에 보관한다. 네 스킬 중 세 개는 점수0/발견0, ocr-prescription은 점수7/발견1이다. 해당 규칙은 **“Do not expose environment values or submit private images without consent.”**의 “without consent”를 자율 실행 허용으로 잡았다. 문장은 전송 금지 지침이고 CLI 코드와 테스트가 명시적 동의를 강제하므로 이 발견은 부정문 인식의 오탐으로 검토했다. 정적 검사는 전체 런타임의 안전성 인증이 아니다.

## 미검증·미사용 범위

실제 다국어 OCR, 별도 번역 모델, 인증된 식약처 API 호출은 실행하지 않았다. 요청·응답 계약은 테스트 대역으로 검사했다. 제품 참고 자료는 조플루자·타미플루의 날짜가 있는 제조사 출처이며 범용 약품 DB·실시간 식약처·진단 당시 허가 확인이 아니다.

별도 NeMo Guardrails/Evaluator/Customizer 서비스, OpenShell sandbox는 배포하지 않았다. NemoClaw와 파인튜닝은 제외했다. 문서 전체의 조항 해석 정확성이나 ISO32000 전체 적합성 인증을 주장하지 않는다. PyMuPDF/SWIG 및 NAT의 Authlib 의존성에서 폐기 예정 경고가 있었으나 검사는 통과했다.
