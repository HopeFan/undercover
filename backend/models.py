"""The shapes of the backend's requests and responses."""

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

Status = Literal["waiting", "in_progress", "waiting_for_sign_off", "decided"]
DecisionKind = Literal["approve", "decline", "refer"]
StepKind = Literal["tool_call", "tool_result", "message", "read"]


class Item(BaseModel):
    description: str
    category: str
    amount: float


class Document(BaseModel):
    name: str
    type: str
    content: str


class Decision(BaseModel):
    decision: DecisionKind
    payout: float
    section: str
    reason: str
    decided_at: str


class Payment(BaseModel):
    amount: float
    paid_at: str
    signed_off_by: str | None


class ClaimSummary(BaseModel):
    claim_id: str
    customer_name: str
    claim_type: str
    summary: str
    amount_claimed: float
    submitted_on: str
    status: Status
    decision: DecisionKind | None
    payout: float | None


class Claim(BaseModel):
    claim_id: str
    policy_id: str
    customer_id: str
    customer_name: str
    claim_type: str
    submitted_on: str
    incident_date: str
    incident_location: str
    summary: str
    story: str
    items: list[Item]
    amount_claimed: float
    documents: list[Document]
    status: Status
    thread_id: str | None
    decision: Decision | None
    payment: Payment | None


class Trip(BaseModel):
    destination: str
    departs_on: str
    returns_on: str
    trip_cost: float


class Policy(BaseModel):
    policy_id: str
    customer_id: str
    plan: str
    add_ons: list[str]
    purchased_on: str
    sold_through: str
    trip: Trip
    travelers: list[str]
    status: str


class PreviousClaim(BaseModel):
    claim_id: str
    filed_on: str
    incident_date: str
    claim_type: str
    summary: str
    outcome: str
    amount_paid: float


class Handler(BaseModel):
    handler_id: str
    name: str
    role: str
    can_approve_over_limit: bool


class Step(BaseModel):
    step_id: int
    thread_id: str
    kind: StepKind
    content: str
    created_at: str


class Instructions(BaseModel):
    text: str


class SectionTitle(BaseModel):
    section: int
    title: str


class Section(BaseModel):
    document: str
    section: int
    title: str
    text: str


class StartRequest(BaseModel):
    thread_id: str = Field(min_length=1)


class StepRequest(BaseModel):
    kind: StepKind
    content: str = Field(min_length=1)


class DecisionRequest(BaseModel):
    decision: DecisionKind
    payout: float = Field(
        ge=0, description="In US dollars, 0 for a decline or referral"
    )
    section: str = Field(
        min_length=1, description="The section of the policy wording relied on"
    )
    reason: str = Field(
        min_length=1, description="Two or three sentences explaining the decision"
    )

    @model_validator(mode="after")
    def check_payout(self) -> Self:
        """An approval pays something, and a decline or referral pays nothing."""
        if self.decision == "approve" and self.payout == 0:
            raise ValueError("An approval needs a payout above zero")
        if self.decision != "approve" and self.payout != 0:
            raise ValueError("A decline or a referral has a payout of zero")
        return self


class PaymentRequest(BaseModel):
    amount: float = Field(gt=0, description="The approved payout in US dollars")


class SignOffRequest(BaseModel):
    handler_id: str
