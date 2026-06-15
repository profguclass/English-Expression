# Memorizer — English Learning App

클라우드 기반 영어 단어 학습 애플리케이션. Streamlit + Google Sheets로 구현.

## 기능

- **JSON 입력**: 복잡한 JSON 형식으로 단어 추가 (뜻, 어원, 예문, 발음 등)
- **Browse & Edit**: 저장된 단어 검색/편집/삭제
- **Review (SRS)**: 기억망각곡선 기반 객관식 퀴즈 (SM-2 알고리즘)
  - 예문 표시
  - 객관식 선택 (4개 선지)
  - 정답/오답 자동 점수 처리
- **통계**: 학습 진행 상황 확인
- **클라우드 저장**: Google Sheets에 모든 데이터 저장

## 로컬 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud 배포

1. Google Cloud: 서비스 계정 생성 & JSON 키 다운로드
2. Google Sheets: 시트 생성 & 서비스 계정 이메일로 공유
3. GitHub에 이 repo 푸시
4. https://share.streamlit.io 접속 → GitHub 인증 → Deploy
5. Secrets 탭에서:
   - `google_service_account`: JSON 전체 내용
   - `google_sheet_id`: 시트 ID

## JSON 입력 형식

```json
{
  "word": "phenotype",
  "pronunciation": {
    "us": "/ˈfiːnətaɪp/",
    "uk": "/ˈfiːnəʊtaɪp/"
  },
  "meaning": "표형, 표현형",
  "etymology": "그리스어...",
  "synonyms": ["physical characteristics", "manifestation"],
  "antonyms": ["genotype"],
  "examples": [
    "The environment plays a significant role...",
    "Identical twins..."
  ],
  "translations": [
    "환경은 생물의 표현형을...",
    "일란성 쌍둥이는..."
  ],
  "context": "생물학, 유전학, 의학 등..."
}
```

## 기술 스택

- **Frontend**: Streamlit
- **Backend**: Google Sheets API (gspread)
- **SRS Algorithm**: SM-2 (Supermemo2)
- **Auth**: OAuth2 (서비스 계정)

## 라이선스

MIT License
