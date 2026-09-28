"""Strict input contracts. Original strings are never translated or corrected."""
import json
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


class AppError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def ensure(condition, code, status=400):
    if not condition:
        raise AppError(code, status)


Term = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=120)]
DrugId = Annotated[str, StringConstraints(strict=True, pattern=r"^\d{5,20}$")]


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(default="", max_length=4000)
    description: str = Field(default="", max_length=4000)
    confirmedTerms: list[Term] = Field(default_factory=list, max_length=20)
    drugIds: list[DrugId] = Field(default_factory=list, max_length=5)
    cloudConsent: bool = False
    translation: bool = False
    conversationId: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")] | None = None

    @field_validator("confirmedTerms")
    @classmethod
    def visible_terms(cls, terms):
        if any(not term.strip() for term in terms):
            raise ValueError("Empty term")
        return terms

    @model_validator(mode="after")
    def has_input(self):
        if not (self.query.strip() or self.description.strip()):
            raise ValueError("Question or description required")
        return self


class ResumeSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    drugIds: list[DrugId] = Field(min_length=1, max_length=5)
    cloudConsent: bool = False

    @field_validator('drugIds')
    @classmethod
    def unique_products(cls, ids):
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate selected product')
        return ids


class DrugLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=2, max_length=120)


CONVERSATIONAL_WORDS = set("약관 보험약관 보험금 보험 청구 지급 보장 대상 해당 사안 경우 내용 관련 관한 대해 대해서 여기 거기 이것 그것 이거 그거 지금 이번 다시 좀 더 또 혹시 분명 실제 실제로 저 제가 저는 나는 내 나 우리 조카 아이 것 건 수 때 처방 확인 검색 검토 질문 설명 알려 보여 찾아 있음 없음".split())
CONVERSATIONAL_PHRASE = re.compile(r"^(?:(?:다시)?(?:확인|검색|검토|설명|알려|보여|찾아)(?:해|해줘|해주세요|해주세|해주실래요|해줄래|해줄래요|해봐|해봐줘|해봐주세요|주세요|줘|주세|줄래|줄래요|봐|봐줘)?|(?:처방)?받(?:았|았습니다|았어요|았는데|았다고|은|은데|아서|아|고|았다|았어)|(?:있|없|맞|아니|되|안되|했|그랬|몰랐)(?:어|어요|습니다|는데|다고|나요|나|니|는|을텐데|을|음|다|죠|잖아|잖아요)?|(?:해당|관련)(?:하는|된|되는|한다|합니다|한다고)?|(?:걸렸|앓았)(?:어|어요|습니다|는데|다고|다)?|(?:해|해주세요|해야|될|인지|인가요|입니다|이에요|예요|텐데|같아요|같은데|부탁해|부탁해요|부탁드립니다))$")
SUFFIX = re.compile(r"(?:걸렸습니다|걸렸어요|걸렸는데|걸렸다고|걸렸어|관련된|관련|찾아줘|알려줘|보여줘|입니다|인가요|이네요|이야|했어요|이에요|으로는|에서는|에게는|에는|에서|으로|에게|이랑|하고|까지|부터|처럼|보다|이라면|이라서|라고|은요|는요|을|를|은|는|이|가|에|도)$")


def is_conversational_term(term):
    return term in CONVERSATIONAL_WORDS or bool(CONVERSATIONAL_PHRASE.fullmatch(term))


def literal_terms(query, confirmed=None):
    tokens = re.findall(r"[^\W_][\w.-]*", query, re.UNICODE)
    stripped = (token.rstrip("._-") for token in tokens)
    extracted = [SUFFIX.sub("", t) for t in stripped if not is_conversational_term(t)]
    common = [t for t in ("독감", "인플루엔자") if t in query]
    derived = [t for t in common + extracted if 2 <= len(t) <= 120 and not is_conversational_term(t) and t in query]
    return list(dict.fromkeys(t for t in list(confirmed or []) + derived if t.strip() and len(t) <= 120))[:25]


def grounded_terms(raw, query, confirmed=None, description="", *, context=()):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        raise AppError("NIM_INVALID_JSON", 502) from None
    ensure(isinstance(value, dict) and set(value) == {"terms"}, "INVALID_TERMS")
    terms = value["terms"]
    ensure(isinstance(terms, list) and len(terms) <= 25 and all(isinstance(t, str) and t.strip() and len(t) <= 120 for t in terms), "INVALID_TERMS")
    ensure(all(t in query or t in description or t in (confirmed or []) or any(t in source for source in context) for t in terms), "UNGROUNDED_TERM")
    return terms


NOTICE = "보장 항목 확인은 약관의 지급사유와 관련 표현을 찾은 결과입니다. 실제 보장은 가입 특약·사고 상황·진단·처방 내용과 지급 조건을 확인해야 합니다. 검색 결과 없음은 보장 제외를 뜻하지 않습니다."
