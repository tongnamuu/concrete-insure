# 선택 기능과 설정

기본 웹 흐름은 약관 PDF와 상황 설명을 받아 NAT·Nemotron NIM으로 관련 원문을 찾습니다. `NVIDIA_API_KEY`가 필요하며, 약품명으로 공식 성분을 조회할 때는 `MFDS_API_KEY`도 필요합니다. 아래 두 설정은 기본 `.env.example`에서 제외합니다. 설정하지 않아도 이 기본 흐름을 사용할 수 있습니다.

## 이미지·스캔 처방전 OCR

`NIM_OCR_URL`은 처방 이미지나 텍스트 레이어가 없는 처방 PDF를 첨부할 때 사용하는 OCR 추론 URL입니다. 약관 PDF 인덱싱·상황 설명 검색·텍스트 레이어가 있는 처방 PDF의 글자 추출은 이 URL을 사용하지 않습니다. 텍스트 처방 PDF도 사용자가 동의하면 추출 후보를 확인하는 일반 Nemotron 호출이 발생할 수 있습니다.

- 실행 경로: 웹의 `POST /api/cases/{id}/ocr` 또는 `ocr-prescription` CLI → 이미지 정리/PDF 렌더링 → `Nvidia.ocr()`.
- 설정: 기존 `.env`에 `NIM_OCR_URL`을 추가하고 해당 OCR 서비스의 추론 URL을 지정합니다. `NVIDIA_API_KEY`와 명시적 전송 동의도 필요합니다. 설정 후 서버를 재시작합니다.
- 계약: 현재 어댑터는 `input`의 PNG data URL과 `merge_levels`를 전송하고, `data[].text_detections[].text_prediction.text`를 읽습니다. 임의의 OCR URL이 아니라 이 요청·응답 형식과 인증을 지원하는 서비스를 연결해야 합니다. [제공자 코드](../concreteinsure/providers.py)와 [스킬 규약](../skills/ocr-prescription/SKILL.md)을 참고하세요.
- 미설정 시: 이미지·스캔 처방 자료 처리는 설정 필요 오류로 종료합니다. 추출 내용을 만들거나 일반 모델로 자동 대체하지 않습니다. 약관 PDF와 상황 설명으로는 계속 사용할 수 있습니다.

OCR 결과는 사용자 확인 전 후보입니다. 약품명·질병코드를 원본과 대조한 뒤 검색에 사용하며, OCR로 질병을 추정하지 않습니다. EXIF 등 이미지 메타데이터 제거와 응답 처리는 합성 이미지·HTTP 테스트 대역으로 검증했습니다. 실제 OCR 서비스의 한국어 인식 품질과 연결 성공은 별도 확인이 필요합니다. 약관 자체의 스캔 PDF는 지원하지 않습니다.

## API 전용 참고 번역

`TRANSLATION_MODEL`은 현재 웹에서 호출하지 않습니다. 웹에는 번역 선택 기능이 없고, 검색 요청에서 `translation`을 생략하면 서버가 `false`로 처리합니다. `.env`에 이 모델을 설정하는 것만으로는 웹 번역이 활성화되지 않습니다.

- 실행 조건: API 클라이언트가 조사 요청에 `translation:true`와 `cloudConsent:true`를 명시하고, 기존 `.env`에 `TRANSLATION_MODEL`을 설정한 경우입니다.
- 모델 연결: `NIM_BASE_URL`의 chat completions API에서 지원하는 모델 ID를 지정합니다. 별도 번역 URL을 받는 구조는 아닙니다.
- 처리: 검증된 검색어의 한국어→영어 참고 표현을 생성해 ReAct 검색 계획의 참고 정보로 전달합니다. 원문·원본 검색어·검색어 ID를 유지하며 번역문을 PDF 검색어나 인용문으로 사용하지 않습니다.
- 미설정 시: API가 번역을 요청하면 `TRANSLATION_CONFIG_REQUIRED`로 종료합니다. 번역 없는 기본 검색에는 영향이 없습니다.

일반적인 한국어↔영어 양방향 번역이나 무손실 번역을 구현한 기능은 아닙니다. ID와 원문 불변 조건은 테스트 대역으로 검증했으며 실제 번역 모델의 품질·속도 개선은 검증하지 않았습니다. 계약은 [contracts.md](contracts.md), 구현은 [agent.py](../concreteinsure/agent.py)와 [providers.py](../concreteinsure/providers.py)에 있습니다.
