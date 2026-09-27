# 실행 로그

서버를 시작하면 `${DATA_DIR}/logs/insurelens.jsonl`에 JSON 한 줄씩 기록한다. `DATA_DIR` 기본값은 프로젝트의 `.local-data`이므로 별도 설정은 필요 없다. 로그는 웹으로 공개하지 않으며 Git 추적 대상에서도 제외한다.

```sh
cd /Users/rook/project/insure-lens
tail -f .local-data/logs/insurelens.jsonl
```

파일당 최대 5 MiB, 현재 파일과 이전 파일 3개까지 약 20 MiB를 보관한다. 오래된 로그는 순환하면서 삭제한다. 로그 디렉터리는 소유자만 접근 가능하고 파일 권한은 0600이다. 이 구성은 로컬 단일 서버용이다.

## 요청 추적

HTTP 응답의 `X-Request-ID`는 서버가 생성한 ID다. 해당 요청이 만든 백그라운드 작업과 도구 호출도 같은 `request_id`를 사용한다. 작업은 추가로 `job_id`를 가지므로 여러 검색이 섞여도 구분할 수 있다. 재연결한 SSE HTTP 요청 자체는 새 ID를 갖고, 실행 중인 작업의 원래 ID는 바뀌지 않는다.

| 이벤트 | 확인할 내용 |
|---|---|
| `request.completed` | 요청 ID, API 경로 형식, HTTP 상태, 응답까지 걸린 시간 |
| `request.error` | 검증·동의·외부 서비스 등의 오류 코드 |
| `job.queued`, `job.started` | 작업 ID, 시작 전 큐 대기 시간 |
| `job.stage` | 입력 확인·검색 계획·검색·원문 검증 단계, SSE 대기 경과 시간 |
| `operation.started/completed/failed/cancelled` | NIM·OCR·식약처·PDF 호출, 제한 시간, 소요 시간, 오류 코드 |
| `provider.response` | NIM 종료 사유, 제공된 토큰 사용량 또는 HTTP 상태 |
| `job.finished` | 완료·실패·취소, 큐 대기를 포함한 전체 소요 시간 |
| `app.started`, `app.stopped` | 서버 시작·정상 종료 |

검색 화면에는 `검색 1단계`(입력 확인)와 `검색 2단계`(약관 검색·검증)만 표시한다. 상세 단계와 경과 시간은 SSE 데이터와 실행 로그에 계속 기록한다.

시각은 UTC이며 `duration_ms`와 `wait_ms`는 밀리초, `elapsed_seconds`와 `timeout_seconds`는 초다. 토큰 사용량은 제공자가 반환했을 때만 기록한다. `operation.completed`는 개별 호출 종료이며, 전체 조사 성공은 `job.finished`의 `state=completed`로 확인한다. HTTP 202는 작업 접수이므로 조사 완료를 뜻하지 않는다. SSE 요청의 HTTP 소요 시간은 연결 유지 시간도 포함한다.

서버 재시작으로 중단된 작업은 `SERVER_RESTARTED`로 기록한다. 정상 취소는 실패와 구분하며, 재시작 전 요청 ID와 정확한 중단 시각은 복원하지 않는다. 최초 적용 전 과거 작업의 소요 시간은 소급해서 만들지 않는다.

## 기록하지 않는 내용

질문·상황 설명·검색어·약관 발췌·처방/OCR 텍스트·이미지·파일명·파일 경로·요청 본문·응답 본문·HTTP 헤더·쿠키·API 키·원시 예외 메시지는 기록하지 않는다. 허용한 메타데이터 필드만 받아 저장하고, API는 실제 URL 대신 `/api/jobs/{identifier}` 같은 경로 형식으로 기록한다. 모델의 추론 내용도 저장하지 않는다. 원본과 검색 결과를 보관하는 기존 로컬 데이터 저장소는 진단 로그와 별개다.

## 검증

`tests/test_diagnostics.py`는 요청/작업 연결, 큐 취소, 서비스 실패·시간 초과, 재시작, 필드 제한, 원문·키 제외, 파일 순환 및 권한을 확인한다. 모델 응답은 테스트 대역으로 제공하므로 이 검사는 외부 NVIDIA 서비스의 가용성 측정이 아니다.
