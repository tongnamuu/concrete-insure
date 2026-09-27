# InsureLens 모듈 정의

구현 규약은 [contracts.md](contracts.md), 현재 연결 구조는 [architecture.md](architecture.md)를 기준으로 한다. 보험금 지급 판단·청구 권유·질병 추정·약관 요약은 제공하지 않는다.

**필수 입력은 약관 PDF와 사용자 질문 또는 상황 설명이다. 처방전·약봉투는 선택 자료다.** 이미지나 처방 PDF 없이도 상황을 설명해 진행한다. 별도 질문 없이 설명만으로도 검색할 수 있다. 설명의 명시된 질병명·질병코드·약품명만 검색 요소로 사용한다. OCR 확인 항목과 선택 제품이 비어 있어도 조사할 수 있다. 사용자 진술을 확인된 진단으로 승격하지 않는다.

| 모듈 | 입력 | 출력 | 실행 방식 |
|---|---|---|---|
| 문서 등록 | 사용자 약관 PDF | 문서 hash, 원문 문자/좌표 인덱스 | 별도 PDF 프로세스, 비동기 작업 |
| 처방 읽기 | 이미지 또는 처방 PDF | OCR/text 초안, 확인 전 후보 | text layer 또는 NIM OCR |
| 입력 확인 subagent | 사용자 발화/상황 설명/확인된 후보 | 원문에 있는 검색 요소 | Nemotron + substring 검증 / 로컬 규칙 |
| 약품 확인 subagent | 사용자가 고른 공식 제품 ID | 공식 성분명/제조원/출처 | 식약처 API 기록 |
| 검색 subagent | 검증된 검색어 ID/기존 hit ID | 원문 span/페이지/좌표 | PDF search/context 도구 |
| ReAct supervisor | 위 상태와 tool observation | 다음 허용 도구 호출 또는 종료 | Nemotron native tool calling |
| 보장 항목 연결 | 특약 조항 원문·제품 근거 | 보장 항목 존재·직접/성분 간접 연결·실제 보장 확인사항 | 규칙 기반 코드, 지급 판단 없음 |
| 원문 검증 subagent | 검색 결과와 source span | 구조화된 인용/제품 사실 | 애플리케이션 코드, 자유문 생성 없음 |
| 결과 표시 | 검증된 결과 | 1:1 웹 화면/표준 PDF 주석 | PDF.js, native Highlight |
| 작업 관리 | 요청/취소 | 저장된 결과, SSE 상태 이벤트 | SQLite, NAT workflow, Node queue |

각 subagent는 독립된 입력/출력 함수를 가지며 별도로 테스트할 수 있다. 모든 모듈을 LLM으로 만들지는 않는다. 특히 원문 구간/좌표 계산/주석 작성은 결정적인 코드가 담당한다. ReAct는 검색 결과를 관찰한 뒤 주변 문맥을 더 읽을지 선택하는 곳에 적용한다.
