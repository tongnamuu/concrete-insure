# InsureLens

약관 PDF와 진료·처방 자료에서 **관련 원문과 위치를 찾아 보여 주는 웹 에이전트**입니다. 질병을 추정하거나 보험금 지급 여부를 판단하지 않습니다. 약관 요약·의역·모델 생성 인용문을 반환하지 않습니다. **약관에 보장 항목이 명시되어 있는지와 상표명 직접 기재 또는 성분 근거를 통한 간접 연결**을 표시하며, 실제 가입·지급 요건 충족 여부는 별도로 확인해야 합니다.

Node.js 웹/API + 모듈별 서브에이전트 + 실제 Python NeMo Agent Toolkit 워크플로 + NVIDIA NIM 연결입니다. PDF의 문자 좌표와 표준 주석은 PyMuPDF 보조 프로세스가 처리합니다. 사용자 접점은 웹 하나이며 NemoClaw는 포함하지 않습니다.

## 실행

필요 환경: Node.js22.13이상(검증24), npm, [uv](https://docs.astral.sh/uv/), Python3.12또는3.13. 로컬 원문 탐색은 GPU/API키 없이 작동합니다.

```sh
npm ci
npm run setup:pdf
npm run setup:nat
cp .env.example .env
npm start
```

브라우저: http://127.0.0.1:8000

새 프로젝트의 `.env`에 키를 직접 입력하세요. `NVIDIA_API_KEY`가 비어 있으면 로컬 탐색 모드라고 표시합니다. 원문 탐색과 PDF 저장은 이 상태에서도 작동합니다. 키를 넣으면 Nemotron native tool-calling ReAct를 사용합니다. 기본 모델은 `nvidia/nemotron-3.5-lightning-30b-a3b`입니다. 서비스 오류·시간 초과·잘못된 응답은 화면에 알리고 검증된 로컬 근거로 복구합니다. 이 결과는 모델 추론으로 표시하지 않습니다. 외부 모델에 질의·발췌문을 보내기 전 웹 동의란을 체크해야 합니다.

| 설정 | 사용 기능 |
|---|---|
| NVIDIA_API_KEY / NIM_MODEL / NIM_BASE_URL | Nemotron 추론·ReAct |
| NIM_OCR_URL | 한국어 지원 multilingual OCR endpoint. 비어 있으면 이미지 OCR 비활성 |
| MFDS_API_KEY | 별도 공식 제품 조회에 필요한 공공데이터포털의 의약품 제품 허가정보 API **v08** 구독 키, 디코딩 형태 |
| TRANSLATION_MODEL | 선택적 영어 gloss 모델. 원문 검색 문자열·인용은 변경하지 않음 |
| AGENT_RUNNER=auto | NAT가 설치되어 있으면 native workflow 사용, 없으면 Node harness. nat로 지정하면 미설치 시 오류 |

NIM용 GPU 서버의 `/v1/ocr`와 build.nvidia.com hosted OCR URL은 제공 형태가 다릅니다. `.env.example`의 안내와 공식 API 문서를 확인해 계정에서 실제 사용할 수 있는 multilingual endpoint를 지정하세요. OCR모델명을 적는 것만으로 서비스가 배포되지는 않습니다. 키 없는 테스트를 실제 NIM/OCR 호출 성공으로 표시하지 않습니다.

## 사용 방법

1. 오른쪽에 볼 보험약관 PDF를 업로드합니다. 샘플 PDF 없이 본인 파일로 동작합니다.
2. **처방 자료 대신 설명하기**에 “조카가 독감 진단을 받고 조플루자를 처방받았어요. 처방전은 없어요”처럼 상황을 적고 **이 설명으로 원문 찾기**를 누릅니다. 사진이나 별도의 질문은 필요하지 않습니다. 추가 질문을 적으면 설명과 함께 사용합니다. 입력한 설명은 수정 없이 별도 `description` 필드로 전달하며, 사용자 진술로 표시하고 문서로 확인된 진단으로 취급하지 않습니다. 설명을 지우면 다음 검색부터 제외됩니다.
3. 필요하면 처방전/약봉투의 PNG·JPEG 또는 처방 PDF를 올립니다. OCR초안과 자동으로 채워진 후보를 원본과 비교해 약품명·성분명·질병코드를 확인합니다. 확인 버튼을 누르기 전에는 검색에 반영되지 않습니다. 자동으로 질병을 추가하지 않습니다.
4. 조플루자·타미플루는 설명에 상표명만 적어도 출처가 등록된 제조사 제품자료에서 성분·관련 표현을 연결하고 약관 원문을 찾습니다. 제품자료와 약관 인용을 별도로 표시합니다. 이 참고 자료는 실시간 식약처 허가 조회, 실제 처방 제품 선택, 진단 확인 또는 지급 판단이 아닙니다. 다른 제품은 사진이 없어도 알고 있는 상표명을 공식 의약품 조회에 직접 입력할 수 있습니다. 제품을 찾고 함량·제형·제조원을 확인해 선택합니다. 선택된 공식 주성분 문자열을 그대로 표시하고 약관 검색에 사용합니다.
5. **보장 범위 확인**에서 관련 특약과 연결 경로를 확인합니다. 지급사유·정의·지급 제외·청구서류를 원문 그대로 펼쳐 볼 수 있습니다. 실제 가입 여부, 진단·처방 목적, 횟수·한도, 당시 허가사항과 참조 조항은 추가 확인 대상으로 표시합니다. 원문 카드의 위치 버튼으로 해당 페이지를 봅니다. 원문 구간과 문자별 하이라이트를 표시하며, 표시된 PDF를 저장하면 네이티브 Highlight주석과 원문 Contents가 포함됩니다.
6. 새로고침하면 약관은 유지하고 완료된 검색 결과·하이라이트는 초기화합니다. 진행 중인 작업은 계속 상태를 받습니다. **검색 결과 지우기**는 현재 대화·검색 결과와 하이라이트만 비우며, 입력 내용·업로드한 자료·서버 기록은 유지합니다. **자료 삭제**는 문서와 결과 기록을 모두 지웁니다.

약관에 약 이름이 없거나 조회 결과가 없다는 이유로 보장 제외라고 출력하지 않습니다. 약품의 성분 이름에 염(salt)이 포함되면 이를 임의 삭제해 동일 성분이라고 주장하지 않습니다. 질병코드 설명은 공식 용어 사전 없이 모델 기억으로 생성하지 않습니다.

## 모듈 규약과 ReAct

먼저 [contracts.md](docs/contracts.md)에 입출력을 정하고 모듈별로 구현했습니다. [architecture.md](docs/architecture.md)에 책임·공식 근거·제약이 있습니다.

- `src/agents/input.js`: 명시된 원문 검색 요소만 추출.
- `src/agents/prescription.js`: 문서에 명시된 후보만 추출하고 사용자 확인 대기.
- `src/agents/drug.js`: 선택된 공식 제품 정보만 사용.
- `src/agents/drug-references.js`, `data/drug-references.json`: 출처·자료 날짜·원문이 있는 제품 참고 자료를 검증하고 약관 검색 표현에 연결. 현재 조플루자·타미플루만 등록.
- `src/agents/retrieval.js`: 확인된 검색어 ID → PDF 원문 구간.
- `src/agents/policy-scope.js`: 지급사유 원문과 상표명·성분 연결 근거를 대조해 보장 항목의 존재를 표시. 실제 지급 판단이나 환자 상태 추정은 하지 않음.
- `src/agents/verification.js`: 원문·좌표 계약 검사 및 응답 조립.
- `src/agent.js`: ReAct supervisor. `tool_calls → 실행 → tool observation → 재호출`, 최대8단계. 모델의 자유문 최종 답변은 버립니다.
- `src/pdf.js`, `python/pdf_worker.py`: 격리된 PDF 추출·검색·주변 원문·주석 도구.
- `src/providers.js`: NIM·OCR·식약처 공식 API 어댑터.
- `src/store.js`, `src/server.js`: 소유권·파일·SQLite·작업 큐·SSE.
- `src/nat.js`, `integrations/nat`: 실제 NAT 등록 workflow로 Node 서브에이전트를 실행. NAT의 일반 내장 ReAct 에이전트를 쓴다고 주장하지 않습니다.
- `public/`: 1:1 split PDF.js 웹 UI.

NAT 안에 custom workflow를 등록하고 그 workflow가 Node harness를 실행합니다. 모델이 없어도 native NAT 런타임 자체는 테스트할 수 있습니다. 숨겨진 추론문 대신 단계 이름과 완료 상태만 SSE로 전달합니다.

## Skills / 보안 실행

`skills/insure-lens-source/SKILL.md`는 skills.sh 호환이며 실제 supervisor의 신뢰된 지침으로 읽습니다.

```sh
npx skills@1.7.0 add . --list
# 원하는 호환 agent에 설치할 때만:
npx skills@1.7.0 add . --skill insure-lens-source
# SkillSpector 별도 설치 후 정적 검사:
sh scripts/scan-skills.sh
```

[OpenShell 배포 경계](integrations/openshell/README.md)는 서버 도구 격리용입니다. 로컬 실행이 자동으로 OpenShell에 격리되는 것은 아닙니다. NemoClaw는 사용하지 않습니다. `build.nvidia.com Skill API`라는 범용 실행 계약은 확인하지 못해 임의 API를 만들지 않았습니다. 대신 공식 NIM endpoint와 NVIDIA Agent Skills 배포 형식을 사용합니다. 파인튜닝은 없습니다.

## 검증

```sh
npm test
integrations/nat/.venv/bin/python integrations/nat/test_bridge.py
BROWSER_EXECUTABLE='/path/to/chromium' node scripts/browser-smoke.mjs
# 별도 임시 서버/합성 자료를 쓰는 보장 항목 화면 검증:
BROWSER_EXECUTABLE='/path/to/chromium' npm run test:browser:coverage
```

테스트는 PDF를 메모리/임시 폴더에서 생성합니다. 실제 보험약관이나 처방전을 코드에 포함하지 않습니다. [검증 기록](docs/validation.md)을 참고하세요.

## 데이터와 지원 범위

- 기본 localhost 전용. HttpOnly/SameSite 세션, Host/Origin검사, 변경 요청 헤더, strict request schema 적용.
- 약관20MiB/1000쪽/200만문자, 처방8MiB/8쪽, 이미지2500만픽셀. 텍스트 레이어 없는 약관은 verbatim 보장을 위해 거절하고 처방 스캔만 OCR합니다.
- PDF작업 기본120초. 디스크 SQLite와 원본/인덱스는 `.local-data`에 보관합니다. 삭제 전까지 보관하며, 단말 OS보안에 의존합니다. 운영 서비스용 사용자 인증·암호화·보관기한 관리와 분산큐는 별도입니다.
- 중단된 작업은 재시작 후 SERVER_RESTARTED로 명시하고 재시도해야 합니다. 완료 결과와 SSE이벤트는 유지됩니다.
- 추출 읽기 순서는 PDF text layer 기준이며 합성 줄바꿈을 포함합니다. 원문은 그 저장된 text의 동일 구간입니다. PDFbinary byte offset과는 다릅니다.
- 원문 주변 블록은 문맥을 보여 주지만 모든 약관의 법적 조항 경계를 완벽하게 인식하지는 않습니다. 전체 약관의 모든 관련 구절을 찾았다는 보장을 하지 않습니다.
- 표준 Highlight/QuadPoints/AP/Contents를 사용하고 회전/CropBox를 테스트했습니다. ISO32000 전체 적합성 인증 제품은 아닙니다. 원본은 보존하며 수정 사본은 전자서명을 무효화할 수 있습니다.
- PyMuPDF는 AGPL/상용 이중 라이선스입니다. 배포 방식에 맞는 라이선스를 검토해야 합니다. 저장소 자체 라이선스가 의존성 라이선스를 대체하지 않습니다.

보장 항목 묶기는 현재 번호가 붙은 특별약관 제목과 `제N조 (...)` 형식을 인식합니다. 인식할 수 없는 서식, 제목만 있는 검색 결과, 불충분하거나 부정 문구가 있는 연결 근거는 보장 항목으로 확정 표시하지 않습니다. 별표·보통약관 전체 참조를 자동으로 검토했다고 주장하지 않습니다. 공백/제어문자만 있는 블록은 제외하고 유효한 원문의 공백·줄바꿈은 보존합니다. 이 기능은 일반 코드 모듈이며, 세 개의 Python CLI Skill로 분리된 구현은 아직 아닙니다.
