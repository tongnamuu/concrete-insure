# NVIDIA 연결 상태

| 기술 | 실제 역할 | 구현 |
|---|---|---|
| Nemotron | 명시된 입력 요소 선택, 허용 도구 호출 | 기본 `nvidia/nemotron-3.5-lightning-30b-a3b` |
| NIM | hosted 모델 추론 | NeMo SDK로 구조화 JSON·함수 도구 호출 |
| NeMo Microservices Python SDK | NIM 요청을 보내는 공식 Python 클라이언트 | `nemo-microservices==1.5.0`, `AsyncNeMoMicroservices` |
| NVIDIA NeMo Agent Toolkit | Python 서브에이전트 실행을 감싸는 등록 workflow | `nvidia-nat==1.9.0`, 필수 실행, Node 중계 없음 |
| Agent Skills / skills.sh | 도구별 사용 지침과 Python JSON CLI | `skills/`의 SKILL.md 형식 |
| SkillSpector | 스킬 정적 검사 | 별도 도구, `--no-llm` 검사 |
| NeMo Guardrails Microservice | 별도 배포가 필요한 서비스 | 현재 미사용; 애플리케이션 원문·좌표·도구 검증은 항상 적용 |
| OpenShell | 선택적 실행 정책 예제 | 현재 Mac에서 sandbox 배포 미실행 |
| NemoClaw | 사용자 결정에 따라 제외 | 웹 접점만 제공 |

## SDK와 NAT의 차이

SDK는 서비스 REST API의 Python 클라이언트이고, NAT는 에이전트 workflow 실행 도구입니다. SDK와 NAT를 같은 것으로 취급하지 않습니다. SDK 설치가 모델 커스터마이징·평가·Guardrails 서비스 배포를 대신하지 않습니다. 이 프로젝트에는 파인튜닝이 없습니다.

SDK 1.5.0에서 확인한 실제 호출은 `client.chat.completions.create(...)`입니다. `client.inference.chat`은 사용하지 않습니다. 생성자에 `base_url`과 `inference_base_url`을 구분해 넘기고, `default_headers`로 NVIDIA 인증 헤더를 설정합니다. SDK가 `/v1/chat/completions`를 붙이므로 adapter에서 설정의 마지막 `/v1`을 제거해 중복 경로를 방지합니다. 입력 추출은 `response_format.type=json_schema`로 `terms`와 `drugNames` 배열을 요청하고 시도당 300초로 제한합니다. 시간 초과·연결 오류·5xx는 애플리케이션에서 1회 재시도하며 SDK의 중첩 재시도는 사용하지 않습니다. 스키마 제약과 별개로 애플리케이션이 원문 일치 여부를 검증합니다. 현재 hosted Nemotron에서 실제 API 호출로 확인했으며, [NIM 구조화 생성 문서](https://docs.nvidia.com/nim/large-language-models/1.15.0/nim-container-variants.html)에 배포 backend별 응답 형식 차이가 설명돼 있습니다. 함수 도구 정의는 SDK의 `extra_body` 확장으로 실제 NIM JSON 형식을 전달합니다. HTTP MockTransport가 공식 SDK의 요청 URL·인증·본문을 검증합니다.

`NEMO_MICROSERVICES_BASE_URL`은 별도 플랫폼에만 필요합니다. 기본 hosted 추론은 `NVIDIA_API_KEY`와 기본 NIM 주소로 동작합니다. 현재 namespace/model customization/evaluation/guardrail 관리 API는 호출하지 않습니다.

## 공식 자료

- [SDK 설치와 비동기 클라이언트](https://docs.nvidia.com/nemo/microservices/25.8.0/get-started/sdk.html)
- [SDK chat completions](https://docs.nvidia.com/nemo/microservices/25.8.0/pysdk/resources/inference/chat_completions.html)
- [NAT plugin API](https://docs.nvidia.com/nemo/agent-toolkit/latest/extend/plugin-api.html)
- [DLI ReAct Loop](https://nvdli.github.io/NemoClawDLI/nemoclaw/01b-react.html#the-react-loop)
- [Nemotron 3.5 Lightning NIM](https://docs.nvidia.com/nim/large-language-models/2.0.10/get-started/advanced/get-started-nemotron-3.5-lightning.html)
- [NVIDIA Agent Skills](https://github.com/NVIDIA/skills), [skills.sh](https://skills.sh/docs), [SkillSpector](https://github.com/NVIDIA/SkillSpector)

범용 `build.nvidia.com Skill API`의 검증된 실행 규약은 확인하지 못해 가짜 endpoint를 추가하지 않았습니다. 공식 모델 endpoint와 공개 스킬 형식을 사용합니다. 실제 호출 성공과 미검증 옵션은 [validation.md](validation.md)에 기록합니다.

모든 조사는 NAT와 NIM을 필수로 사용한다. 키 누락은 조사를 차단하고 제공자 오류는 실패로 전달한다. 실행모드 선택과 로컬 대체 결과는 제공하지 않는다. PDF 처리·출처 검증·식약처 조회 등 도구의 결정적인 작업은 Python 코드로 수행한다.
