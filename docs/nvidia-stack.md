# NVIDIA 기술 연결 상태

| 기술 | InsureLens 적용 | 검증 상태 |
|---|---|---|
| Nemotron | 입력 요소 추출, 허용된 도구 ID 선택, ReAct | 실키 JSON·native tool call 및 NAT 전체 흐름 성공; 지연/실패 경계는 validation.md 참고 |
| NIM | chat completions 및 별도 image OCR 계약 | chat 인증 호출 검증; OCR 인증 호출 미실행 |
| NVIDIA NeMo Agent Toolkit | 등록된 Python workflow에서 Node subagent 실행 | 실제1.9.0 설치/실행/통합 테스트 통과 |
| Agent Skills / skills.sh | SKILL.md 지침을 supervisor가 로드 | CLI발견/문서 검증 통과 |
| SkillSpector | custom skill 정적 분석 | no-llm 검사 통과; report 포함 |
| OpenShell | 파일·네트워크 정책 배포 예제 | 배포 미실행, 기본 실행은 sandbox 아님 |
| NemoClaw | 사용자 결정에 따라 제외 | 웹 접점만 제공 |

범용 build.nvidia.com Skill API의 검증된 실행 규약은 찾지 못하여 가짜 URL이나 패키지를 추가하지 않았다. NIM endpoint와 공개 Agent Skills 형식을 사용한다. 파인튜닝은 구현하지 않는다. 선택 번역은 원문을 대체하지 않는 영어 gloss이며 번역문을 원문 검색/인용에 사용하지 않는다.

공식 출처와 경계는 [architecture.md](architecture.md), 실제 검증 범위는 [validation.md](validation.md)를 참고한다.
