# NVIDIA 연결 상태

실행 버전은 `pyproject.toml`의 고정 의존성을 기준으로 합니다. 사용자 입력부터 결과 표시까지의 구조도와 핵심 기술 목록은 [README](../README.md#사용자-입력부터-nvidia-연동까지)에 있습니다.

- **Nemotron 3.5 Lightning 30B A3B**: 기본 모델은 `nvidia/nemotron-3.5-lightning-30b-a3b`입니다. 명시된 검색어·약품명 추출과 허용 도구·ID 선택을 담당합니다.
- **NVIDIA hosted NIM**: 위 모델을 실행하는 추론 서비스입니다. 공통 SDK 클라이언트로 구조화 JSON과 함수 도구 호출을 요청합니다.
- **NeMo Microservices Python SDK 1.5.0**: `AsyncNeMoMicroservices.chat.completions.create`로 NIM에 연결하는 공식 Python 클라이언트입니다.
- **NVIDIA NeMo Agent Toolkit 1.9.0 (`nvidia-nat[langchain]`)**: 전체 Python 조사 워크플로를 실행합니다. 조건부 성분 조사는 내장 `tool_calling_agent`와 `medicine` Function Group, 약관 검색은 등록 워크플로 안의 자체 ReAct 루프입니다.
- **Agent Skills·skills.sh 호환 형식**: 커스텀 `SKILL.md` 세 개로 원문 처리 규칙과 성분·PDF 도구 계약을 정의합니다. 개별 JSON CLI는 성분 조회와 PDF 처리 두 가지이며 웹과 Python 모듈을 공유합니다. skills.sh는 스킬 배포·발견 도구이며 NAT를 대신해 웹 에이전트를 실행하지 않습니다.
- **NVIDIA SkillSpector**: 별도 설치하는 개발용 스킬 정적 검사 도구입니다. `scripts/scan-skills.sh`가 `--recursive --no-llm`으로 실행하며 현재 앱 의존성이나 CI의 필수 검사가 아닙니다. 과거 실행 기록과 현재 검사 범위는 [validation.md](validation.md)를 참고하세요.

NeMo Guardrails Microservice와 NemoClaw는 현재 사용하지 않습니다. OpenShell은 선택적 정책 예제만 있으며 현재 웹 런타임에 적용하지 않습니다. 원문·좌표·도구 검증은 항상 애플리케이션 코드에서 수행합니다.

## 모델 호출과 도구 실행의 경계

1. 입력 확인 단계는 SDK로 NIM을 호출해 `terms`와 `drugNames`를 추출하고, 코드가 원문 부분 문자열인지 검사합니다.
2. 명시된 약품명이나 사용자 선택 품목이 있을 때만 NAT 성분 에이전트를 호출합니다. 약품명이 없는 요청은 이 단계와 식약처 API를 건너뜁니다.
3. 미선택 약품명은 `lookup_products`로 후보를 찾고 사용자 선택·재동의를 기다립니다. 서버 체크포인트로 재개하므로 입력 추론과 후보 조회를 반복하지 않습니다.
4. 선택된 품목마다 모델이 `inspect_product`와 허용된 품목 ID를 선택합니다. Python 도구가 최신 식약처 상세정보에서 성분과 모든 가용 허가문서를 함께 검증합니다. 성분 확인과 허가문서 확인 사이에는 추가 NIM 호출이 없습니다.
5. 모든 필수 근거가 모이면 애플리케이션이 내부 `finish_evidence` 제어 호출을 만들고 NAT의 `return_direct`로 성분 에이전트를 종료합니다. 이 종료 도구는 모델에게 노출하지 않으며 종료 확인용 추론도 실행하지 않습니다. 검증 실패 시 부분 결과를 완료로 기록하지 않습니다.
6. 약관 검색 ReAct는 `search_policy`·`read_context`의 관찰 결과로 다음 행동을 선택합니다. 이 루프의 `finish_retrieval`은 모델이 선택하는 종료 도구입니다. 최종 인용·좌표·보장 항목 연결은 코드가 검증해 반환하며 생성된 최종 문장은 폐기합니다.

선택 품목 하나의 성분·허가문서 조사에는 정상 경로에서 모델 호출 1회가 필요합니다. 이 수치는 입력 추출·후보 조회·약관 검색과 실패 시 재시도를 포함하지 않습니다. SSE는 앱의 진행·완료 이벤트이며 현재 NIM 호출은 `stream=False`입니다.

## SDK와 NAT의 차이

SDK는 서비스 REST API의 Python 클라이언트이고, NAT는 에이전트 workflow 실행 도구입니다. SDK와 NAT를 같은 것으로 취급하지 않습니다. SDK 설치가 모델 커스터마이징·평가·Guardrails 서비스 배포를 대신하지 않습니다. 이 프로젝트에는 파인튜닝이 없습니다.

SDK 1.5.0에서 확인한 실제 호출은 `client.chat.completions.create(...)`입니다. `client.inference.chat`은 사용하지 않습니다. 생성자에 `base_url`과 `inference_base_url`을 구분해 넘기고, `default_headers`로 NVIDIA 인증 헤더를 설정합니다. SDK가 `/v1/chat/completions`를 붙이므로 adapter에서 설정의 마지막 `/v1`을 제거해 중복 경로를 방지합니다. 입력 추출은 `response_format.type=json_schema`로 `terms`와 `drugNames` 배열을 요청하고 시도당 300초로 제한합니다. 시간 초과·연결 오류·5xx는 애플리케이션에서 1회 재시도하며 SDK의 중첩 재시도는 사용하지 않습니다. 스키마 제약과 별개로 애플리케이션이 원문 일치 여부를 검증합니다. 현재 hosted Nemotron에서 실제 API 호출로 확인했으며, [NIM 구조화 생성 문서](https://docs.nvidia.com/nim/large-language-models/1.15.0/nim-container-variants.html)에 배포 backend별 응답 형식 차이가 설명돼 있습니다. 함수 도구 정의는 SDK의 `extra_body` 확장으로 실제 NIM JSON 형식을 전달합니다. HTTP MockTransport가 공식 SDK의 요청 URL·인증·본문을 검증합니다.

`NEMO_MICROSERVICES_BASE_URL`은 별도 플랫폼에만 필요합니다. 기본 hosted 추론은 `NVIDIA_API_KEY`와 기본 NIM 주소로 동작합니다. 현재 namespace/model customization/evaluation/guardrail 관리 API는 호출하지 않습니다.

## 공식 자료

- [SDK 설치와 비동기 클라이언트](https://docs.nvidia.com/nemo/microservices/25.8.0/get-started/sdk.html)
- [SDK chat completions](https://docs.nvidia.com/nemo/microservices/25.8.0/pysdk/resources/inference/chat_completions.html)
- [NAT Tool Calling Agent](https://docs.nvidia.com/nemo/agent-toolkit/latest/components/agents/tool-calling-agent/tool-calling-agent.html)
- [NAT Function Groups](https://docs.nvidia.com/nemo/agent-toolkit/latest/build-workflows/functions-and-function-groups/function-groups.html)
- [NAT plugin API](https://docs.nvidia.com/nemo/agent-toolkit/latest/extend/plugin-api.html)
- [DLI ReAct Loop](https://nvdli.github.io/NemoClawDLI/nemoclaw/01b-react.html#the-react-loop)
- [Nemotron 3.5 Lightning NIM](https://docs.nvidia.com/nim/large-language-models/2.0.10/get-started/advanced/get-started-nemotron-3.5-lightning.html)
- [NVIDIA Agent Skills](https://github.com/NVIDIA/skills), [skills.sh](https://skills.sh/docs), [SkillSpector](https://github.com/NVIDIA/SkillSpector)

범용 `build.nvidia.com Skill API`의 검증된 실행 규약은 확인하지 못해 가짜 endpoint를 추가하지 않았습니다. 공식 모델 endpoint와 공개 스킬 형식을 사용합니다. 실제 호출 성공과 미검증 옵션은 [validation.md](validation.md)에 기록합니다.

모든 조사는 NAT와 NIM을 필수로 사용한다. 키 누락은 조사를 차단하고 제공자 오류는 실패로 전달한다. 실행모드 선택과 로컬 대체 결과는 제공하지 않는다. PDF 처리·출처 검증·식약처 조회 등 도구의 결정적인 작업은 Python 코드로 수행한다.
