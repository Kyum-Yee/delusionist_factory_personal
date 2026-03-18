# Delusionist Factory - Agent 운영 가이드

이 문서는 AI Agent가 Delusionist Factory를 처음부터 끝까지 운영하기 위한 완전한 매뉴얼이다. 파일 탐색 없이 이 문서만 읽으면 즉시 실행 가능하다.

---

## 1. 이게 뭐하는 프로젝트인가

LLM은 혼자서는 자기 자신을 놀라게 할 수 없다. 같은 맥락을 주면 확률적 평균으로 수렴해서 진부한 결과가 나온다.

Delusionist Factory는 **Python의 random.sample로 무작위 단어를 뽑아서 LLM의 맥락을 강제로 오염시킨다.** 오염된 맥락에서 AI는 평소라면 절대 연결하지 않았을 개념들을 충돌시키게 되고, 그 충돌에서 창의적인 아이디어가 나온다.

이것을 **Stochastic Context Pollution (확률적 맥락 오염)** 이라 부른다.

---

## 2. 3단계 파이프라인

전체 흐름은 **Step 1 → Step 2 → Step 3** 순서로 진행된다.

### Step 1: Chaining (A단계) - 원석 채굴
- **목표**: CHAINS_COUNT개의 "망상적 변이 문장" 대량 생산
- **메커니즘**: Python이 단어 풀에서 무작위 3단어를 뽑아줌 → AI가 그 단어들과 STARTING_SENTENCE를 충돌시켜 문장 생성
- **출력 파일**: `output/section_a_chains.txt` (한 줄에 한 문장)
- **배치 단위**: 100문장씩
- **핵심 규칙**:
  - MANDATORY_WORD는 매 문장에 **반드시** 전부 포함
  - 한국어+영어 혼용 시 영어 3단어 연속 사용 금지 (LANGUAGE_RULE)
  - 무작위 단어가 뜬금없으면 그대로 쓰지 말고 문맥에 맞게 치환
  - 과감할 것. 안전하고 말이 되는 문장은 실패
- **실행 방식**: STEP1_EXECUTOR 값에 따라 다름
  - `"SELF"`: Agent가 직접 문장 생성
  - `"GEMINI_CLI"`: main.py가 Gemini CLI용 프롬프트를 `staging/step1_gemini_prompt.txt`에 생성 → 외부에서 Gemini CLI로 실행 → 결과를 section_a_chains.txt에 append

### Step 2: Refining (B단계) - 선별과 명명
- **목표**: Step 1의 대량 문장에서 SELECTION_B_COUNT개의 정제된 아이디어 추출
- **출력 파일**: `output/section_b_refined.txt`
- **배치 단위**: 10문장씩
- **핵심 작업**:
  1. Step 1에서 "기존에 함께 쓰이지 않던 관념/아이디어의 조합"을 찾기
  2. 찾아낸 충돌에 **고유한 이름** 붙이기 (기존 용어 재사용 금지)
  3. 그 이름이 가리키는 실체를 구체적으로 서술
  4. 기존의 단일 관념으로 환원 가능하면 탈락
  5. 고유명사 나열, 비유의 비유, 미사여구 3단 중첩 → 즉시 삭제

### Step 3: Final (C단계) - 완성형 가공
- **목표**: Step 2의 재료를 REFINING_COUNT개의 최종 결과물로 가공
- **출력 파일**: `output/section_c_final.txt`
- **배치 단위**: 5개씩
- **핵심 작업**:
  1. DIRECTION에 맞는 형식과 구조로 최종 결과물 구성
  2. DIRECTION 작성자의 어휘 수준/톤에 맞춤 (독해 난이도 조절)
  3. 자기 표현 제한: 제목 1개 + 핵심 키워드 1개까지만 독창적 표현 허용
  4. 나머지는 DIRECTION과 Step 2 재료에서 유추 가능한 표현으로 구성
  5. 주관적 감탄/미사여구 배제, "~하면 ~가 된다" 조건-결과 구조로 서술
  6. 읽으면 바로 활용 가능한 형태 (해석이 필요한 암호가 아닐 것)
- **C단계 작성 기준** (작성하는 동안 적용하는 판단 기준):
  - **완결성**: 전제/비유/질문/비교를 열 때, 귀결시킬 수 있는 경우에만 연다. 귀결 계획 없이 여는 것 금지.
  - **추적 가능성**: A→B 전환 시, 독자가 근거를 본문 내에서 재구성할 수 있어야 한다. 근거 없는 전환은 만들지 않는다.
  - **자족성**: 메타 설명("이 글은~", "여기서 말하고자 하는 것은~") 쓰지 않는다. 메타가 필요하면 본문 자체가 불충분하다는 신호.

---

## 3. 실행 방법 (정확한 순서)

### MCP 도구를 사용하는 경우

이 프로젝트는 MCP 서버(`mcp_server.py`)로 등록되어 있다. 사용 가능한 도구:

| 도구 | 기능 |
|------|------|
| `run_delusionist` | 현재 상태 확인 → 다음 Step의 작업 지시 반환 |
| `get_status` | 현재 진행 상황 (step, 각 단계 count) |
| `append_result` | 생성한 문장을 해당 step의 파일에 추가. `step`="1"/"2"/"3", `content`=줄바꿈 구분 텍스트 |
| `get_request_config` | 현재 request.json 설정 확인 |
| `update_request_config` | request.json 설정 변경 |
| `reset_factory` | output/과 staging/ 초기화 (`confirm`=true 필수) |
| `get_random_words` | 단어 풀에서 무작위 단어 추출 (`count` 지정 가능) |
| `read_output_file` | 각 step의 출력 파일 읽기 (`step`="1"/"2"/"3") |
| `prepare_parallel_gemini_workers` | Step 1 병렬 Gemini CLI 워커 준비. 각 워커용 프롬프트를 staging/에 저장하고 cmd 배열 반환. Operator가 run_command로 직접 병렬 실행 |

**MCP 실행 루프 (단일 에이전트):**
1. `run_delusionist` 호출 → 현재 Step의 작업 지시 수신
2. 지시에 따라 문장 생성
3. `append_result`로 결과 추가
4. 다시 `run_delusionist` 호출 → 다음 배치 또는 다음 Step 진행
5. "ALL STEPS COMPLETE" 메시지가 나올 때까지 반복

### Step 1 병렬 실행 — Gemini CLI 워커 방식

Step 1(Chaining)은 sub-agent 없이 Gemini CLI를 직접 워커로 사용한다.
각 sub-agent가 독립적으로 문장을 생성하는 대신,
Operator(메인 에이전트)가 `run_command`로 gemini를 N개 병렬 실행하고
응답을 `append_result`로 올린다. **sub-agent 토큰 = 0.**

**병렬 실행 순서:**
1. `prepare_parallel_gemini_workers` 호출 — 두 가지 모드:
   - `batch_size=25` → 워커당 25줄, 워커 수 자동 계산 (예: 50줄 남음 + batch_size=25 → 2워커)
   - `worker_count=3` → 3워커, 줄 수 균등 분할
   - 둘 다 미지정 시 batch_size=25 기본값. batch_size 우선.
2. 반환값: `{total_workers, total_lines, workers: [{worker_id, line_count, prompt_path, cmd, batch_start, batch_end}]}` 배열
   - 각 워커의 gemini 프롬프트가 `staging/worker_{id}_prompt.txt`에 저장돼 있음
3. **각 워커의 `cmd` 값을 아래 파이프로 래핑해서 Bash background로 병렬 실행**
   - `{원본_cmd}` = 위 **2번 항목** 반환값의 `workers[i]["cmd"]` 그대로 치환
   - 래핑 형태 (프로젝트 루트에서 실행):
     ```
     cd /Users/jakesmacair/프로젝트\ 파일/delusionist_factory_personal && {원본_cmd} | python3 -c "import sys,json,fcntl,re; raw=sys.stdin.read(); m=re.search(r'\{.*\}',raw,re.DOTALL); d=json.loads(m.group()) if m else {}; ls='\n'.join(l for l in d.get('response','').split('\n') if len(l)>4 and l[:3].isdigit()); (lambda f:(fcntl.flock(f,2),f.write(ls+chr(10)),fcntl.flock(f,8),f.close()))(open('output/section_a_chains.txt','a')) if ls else None"
     ```
   - `run_in_background=true`로 워커 수만큼 동시 실행
   - JSON 파싱 실패 / 매칭 줄 없음 → 자동으로 아무것도 쓰지 않음 (코드가 처리)
   - **AI는 Bash 반환값을 읽지 않는다. `append_result` 호출 금지.**
4. 모든 background 작업 완료 후 `get_status`로 줄 수 확인
5. `run_delusionist` 호출 → Step 2 자동 진입

**실패 재시도 프로토콜:**
1. gemini 실행 결과를 확인. 실패한 워커가 있으면:
2. `get_status`로 현재 `section_a_chains.txt` 줄 수 확인
3. 목표(CHAINS_COUNT)에 미달이면 → `prepare_parallel_gemini_workers(worker_count=1)` 재호출
   - 이 함수는 **남은 분량만큼** 새 프롬프트를 배정하며 자동으로 부족분만 채운다
4. 재실행 후 다시 줄 수 확인
5. 목표 도달할 때까지 반복

**동시 쓰기 안전:**
- `append_result`는 내부적으로 파일 잠금(`fcntl.flock`)을 사용한다
- 여러 gemini 응답 처리가 동시에 호출해도 데이터가 깨지지 않는다
- `state.json`, `request.json` 접근도 파일 잠금으로 보호된다

### main.py를 직접 실행하는 경우

```bash
cd /Users/jakesmacair/프로젝트 파일/delusionist_factory_personal
python main.py
```

main.py는 stdout으로 작업 지시를 출력한다. Agent는:
1. 출력된 지시를 읽고 해당 작업 수행
2. 결과를 해당 output 파일에 append
3. 다시 `python main.py` 실행
4. "ALL STEPS COMPLETE"가 나올 때까지 반복

---

## 4. request.json 설정

파일 위치: `input/request.json`

```json
{
  "STARTING_SENTENCE": "시작 문장 또는 주제",
  "MANDATORY_WORD": ["필수단어1", "필수단어2"],
  "PREFERRED_IMAGERY": ["이미지어1", "이미지어2"],
  "CHAINS_COUNT": 200,
  "MODE_SELECTION": "CHAOS",
  "SELECTION_B_COUNT": 10,
  "REFINING_COUNT": 5,
  "STEP1_EXECUTOR": "SELF",
  "DIRECTION": "최종 결과물의 방향성",
  "FINAL_LANGUAGE": "Korean",
  "LANGUAGE_RULE": "NO_3_CONSECUTIVE_FOREIGN_WORDS"
}
```

| 필드 | 설명 | 기본값 |
|------|------|--------|
| STARTING_SENTENCE | Step 1의 시작점. 주제/분위기/에너지의 씨앗 | (필수) |
| MANDATORY_WORD | 모든 문장에 반드시 포함할 단어 배열 | [] |
| PREFERRED_IMAGERY | AI가 참조할 이미지어 배열 (선호 모티프) | [] |
| CHAINS_COUNT | Step 1에서 생성할 총 문장 수 | 100 |
| MODE_SELECTION | `"CHAOS"` (70% 랜덤) 또는 `"NUANCE"` (30% 랜덤) | "CHAOS" |
| SELECTION_B_COUNT | Step 2에서 추출할 정제 문장 수 | 10 |
| REFINING_COUNT | Step 3 최종 출력 수 | 2 |
| STEP1_EXECUTOR | `"SELF"` (Agent 직접) 또는 `"GEMINI_CLI"` (외부 Gemini) | "GEMINI_CLI" |
| DIRECTION | 최종 결과물의 방향성 (아래 DIRECTION 원칙 참조) | (필수) |
| FINAL_LANGUAGE | 최종 출력 언어. "Korean" 또는 "English" | "Korean" |
| LANGUAGE_RULE | 언어 혼용 규칙 | "NO_3_CONSECUTIVE_FOREIGN_WORDS" |

---

## 5. DIRECTION 설정 원칙

DIRECTION은 C단계의 방향을 정하는 핵심 필드다. 잘못 쓰면 발산이 죽고, 안 쓰면 결과가 흩어진다.

### 넣는 것: 구조적 요소
- 형식 (서정시, 에세이, 논설, 블로그 등)
- 논리구조 ("왜 되는지", "어떻게 따라하는지" 등)
- 챕터/섹션 구성
- 예: "서정시 한 편 창작", "이 원리의 작동 이유와 실천법을 담은 해설"

### 넣지 않는 것: 상상의 폭
- 구체적 분위기, 이미지어, 감성 방향
- 유저가 명시적으로 요청한 경우에만 포함
- 미지정 감성/분위기는 Step 1~2의 확률적 오염에서 자연 발생

### 유저가 지시할 때만: 감성/이성 프레임워크
- 문학/형이상학 같은 감성 영역, 그림체/스타일 테이블 같은 이성 영역
- 유저 의도를 정확히 파악한 뒤 반영. 모호하면 넣지 않는다.

---

## 6. 파일 구조

```
delusionist_factory_personal/
├── input/
│   ├── request.json                    # 설정 파일
│   ├── 100000word.txt                  # 영어 단어 풀 (466,551줄)
│   ├── extracted_words.txt             # 한국어 단어 풀 (917,273줄)
│   ├── section_a_chains_reference.txt  # Step 1 참조 예시 (과거 결과)
│   └── section_b_refined_reference.txt # Step 2 참조 예시 (과거 결과)
├── output/
│   ├── section_a_chains.txt            # Step 1 출력 (한 줄 = 한 문장)
│   ├── section_b_refined.txt           # Step 2 출력
│   └── section_c_final.txt             # Step 3 최종 출력
├── staging/
│   ├── state.json                      # 진행 상태 {"current_step": 1|2|3}
│   ├── step1_gemini_prompt.txt         # Gemini CLI용 프롬프트 (자동 생성)
│   ├── append.lock                     # 병렬 append 파일 잠금 (자동 생성)
│   ├── state.lock                      # state.json 파일 잠금 (자동 생성)
│   └── config.lock                     # request.json 파일 잠금 (자동 생성)
├── main.py                             # 엔진 코어 (파이프라인 제어, 프롬프트 생성, 상태 관리)
├── mcp_server.py                       # MCP 서버 (Claude Code에서 도구로 사용)
├── gemini_cli.py                       # Gemini CLI 래퍼 (외부 실행 유틸)
├── extract_results.py                  # staging/step1_result.json → section_a에 append
├── auto_run.py                         # main.py 자동 반복 실행 스크립트
├── check_duplicates.py                 # 중복 문장 검사 유틸
├── convert_to_docx.py                  # 결과물 DOCX 변환
├── fast_convert_docx.py                # 빠른 DOCX 변환
├── prompt.txt                          # 프로젝트 설명 + DIRECTION 원칙
├── 100000word.txt                      # 영어 단어 풀 (루트에도 사본 있음)
└── .env                                # 환경변수 (GOOGLE_API_KEY)
```

---

## 7. 상태 관리

진행 상태는 `staging/state.json`에 저장된다.

```json
{"current_step": 1}
```

- Step 1 → section_a_chains.txt 줄 수가 CHAINS_COUNT에 도달하면 자동으로 Step 2로 전환
- Step 2 → section_b_refined.txt 줄 수가 SELECTION_B_COUNT에 도달하면 자동으로 Step 3으로 전환
- Step 3 → section_c_final.txt 줄 수가 REFINING_COUNT에 도달하면 완료

**초기화 (처음부터 다시 시작):**
```bash
rm -rf output/* staging/*
```
또는 MCP: `reset_factory` (confirm=true)

---

## 8. 단어 풀과 언어 감지

- FINAL_LANGUAGE가 "Korean"이면 → `input/extracted_words.txt` (한국어 풀) 사용
- FINAL_LANGUAGE가 "English"이면 → `input/100000word.txt` (영어 풀) 사용
- 명시 안 하면 → STARTING_SENTENCE + DIRECTION 텍스트에서 한글 포함 여부로 자동 감지

단어 추출은 `linecache`를 사용해 랜덤 줄 번호로 직접 접근한다 (24MB 파일을 통째로 메모리에 올리지 않음).

---

## 9. 환경 변수 (선택)

| 변수 | 기능 | 기본값 |
|------|------|--------|
| DELUSIONIST_GEMINI_MODEL | Gemini CLI 사용 시 모델 지정 | (CLI 기본) |
| DELUSIONIST_STEP1 | Step 1 실행 방식 오버라이드 ("GEMINI_CLI" / "SELF") | request.json 값 |
| DELUSIONIST_STEP1_ETA_OVERHEAD_S | ETA 계산 오버헤드 (초) | 20 |
| DELUSIONIST_STEP1_ETA_S_PER_LINE | ETA 계산 줄당 소요 (초) | 1.2 |

---

## 10. 주의사항

1. **output 파일에는 append만 한다.** 덮어쓰기(overwrite) 절대 금지. 항상 기존 내용 뒤에 추가.
2. **main.py는 한 번 실행하면 한 배치만 처리하고 종료된다.** 전체를 돌리려면 반복 호출해야 한다.
3. **Step 1이 GEMINI_CLI 모드면 Agent가 문장을 생성하지 않는다.** main.py가 프롬프트만 만들어주고, 외부에서 Gemini CLI를 돌려서 결과를 append해야 한다.
4. **Step 진행은 줄 수 기반이다.** 파일의 줄 수가 목표치에 도달하면 다음 Step으로 넘어간다. 빈 줄도 카운트되므로 빈 줄이 들어가지 않도록 주의.
5. **MANDATORY_WORD는 Step 1~2에서만 강제된다.** Step 3에서는 자연스럽게 녹아든 형태로 사용.
6. **참조 파일**: `input/section_a_chains_reference.txt`와 `input/section_b_refined_reference.txt`에 과거 성공 사례가 있다. 톤과 수준을 참고할 것.
