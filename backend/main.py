"""The UnderCover backend."""

import json
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException

from backend.database import connect, database_path, seed
from backend.models import (
    Claim,
    ClaimSummary,
    Decision,
    DecisionRequest,
    FailureRequest,
    FinishRunRequest,
    Handler,
    Instructions,
    Payment,
    PaymentRequest,
    Policy,
    PreviousClaim,
    Run,
    Section,
    SectionTitle,
    SignOffRequest,
    StartRequest,
    StartRunRequest,
    Status,
    Step,
    StepRequest,
    TodosRequest,
)

INSTRUCTIONS = Path(__file__).parent / "instructions"
ATTEMPTS = 2


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Seed the database on startup if it doesn't exist yet."""
    if not database_path().exists():
        seed(database_path())
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)


def database() -> Iterator[sqlite3.Connection]:
    """Open the database for one request and commit if the request succeeds."""
    with closing(connect()) as connection, connection:
        yield connection


Database = Annotated[sqlite3.Connection, Depends(database)]


def now() -> str:
    """Return the current time in UTC, to the second."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def dollars(amount: float) -> str:
    """Format an amount like $1,250.00."""
    return f"${amount:,.2f}"


def approval_limit(db: sqlite3.Connection) -> float:
    """Return the largest payout that can be paid without a handler's sign-off."""
    return db.execute("SELECT payout_approval_limit FROM settings").fetchone()[0]


def fetch_one(
    db: sqlite3.Connection, sql: str, params: tuple[object, ...], missing: str
) -> sqlite3.Row:
    """Return the one row a query finds, or raise a 404 saying what wasn't found."""
    row = db.execute(sql, params).fetchone()
    if row is None:
        raise HTTPException(404, f"{missing} not found")
    return row


def find_claim(db: sqlite3.Connection, claim_id: str) -> sqlite3.Row:
    """Return one claim's row, or raise a 404."""
    return fetch_one(
        db,
        "SELECT * FROM claim_view WHERE claim_id = ?",
        (claim_id,),
        f"Claim {claim_id}",
    )


def claim_in(
    db: sqlite3.Connection, claim_id: str, status: Status, state: str
) -> sqlite3.Row:
    """Return a claim's row if it is in the given status, or raise a 409."""
    claim = find_claim(db, claim_id)
    if claim["status"] != status:
        raise HTTPException(409, f"Claim {claim_id} is not {state}")
    return claim


def claim_fields(row: sqlite3.Row) -> dict[str, Any]:
    """Return a claim's own record with its status and customer's name."""
    return json.loads(row["record"]) | {
        "status": row["status"],
        "customer_name": row["customer_name"],
    }


def to_summary(row: sqlite3.Row) -> ClaimSummary:
    """Build a claim's line in the queue from its row."""
    return ClaimSummary(
        **claim_fields(row) | {"decision": row["decision"], "payout": row["payout"]}
    )


def to_claim(row: sqlite3.Row) -> Claim:
    """Build a claim in full, with its decision and payment, from its row."""
    decision = None
    if row["decision"] is not None:
        decision = Decision(**dict(row))
    payment = None
    if row["paid_at"] is not None:
        payment = Payment(**dict(row))
    return Claim(
        **claim_fields(row)
        | {"thread_id": row["thread_id"], "decision": decision, "payment": payment}
    )


def to_run(row: sqlite3.Row) -> Run:
    """Build a run, with its to-do list, from its row."""
    return Run(**dict(row) | {"todos": json.loads(row["todos"])})


def find_run(db: sqlite3.Connection, run_id: str) -> Run:
    """Return one run, or raise a 404."""
    sql = "SELECT * FROM runs WHERE run_id = ?"
    return to_run(fetch_one(db, sql, (run_id,), f"Run {run_id}"))


def add_step(
    db: sqlite3.Connection, claim_id: str, thread_id: str, kind: str, content: str
) -> Step:
    """Record one step of the agent's work on a claim."""
    row = db.execute(
        "INSERT INTO steps (claim_id, thread_id, kind, content, created_at)"
        " VALUES (?, ?, ?, ?, ?) RETURNING *",
        (claim_id, thread_id, kind, content, now()),
    ).fetchone()
    return Step(**dict(row))


def fail(db: sqlite3.Connection, claim: sqlite3.Row, error: str) -> None:
    """Send a claim in progress back to the queue, or leave it for a handler."""
    add_step(db, claim["claim_id"], claim["thread_id"], "error", error)
    db.execute(
        "UPDATE claims SET failures = failures + 1,"
        " status = IIF(failures + 1 < ?, 'waiting', 'left_for_handler')"
        " WHERE claim_id = ?",
        (ATTEMPTS, claim["claim_id"]),
    )


def pay(
    db: sqlite3.Connection, claim_id: str, amount: float, signed_off_by: str | None
) -> Payment:
    """Record a payment on a claim."""
    payment = Payment(amount=amount, paid_at=now(), signed_off_by=signed_off_by)
    db.execute(
        "INSERT INTO payments VALUES (?, ?, ?, ?)",
        (claim_id, payment.amount, payment.paid_at, payment.signed_off_by),
    )
    return payment


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


@app.get("/api/claims", operation_id="list_claims")
def list_claims(db: Database) -> list[ClaimSummary]:
    """List every claim in the queue, in id order."""
    rows = db.execute("SELECT * FROM claim_view ORDER BY claim_id").fetchall()
    return [to_summary(row) for row in rows]


@app.get("/api/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, db: Database) -> Claim:
    """Get one claim in full: the story, the items claimed and the documents."""
    return to_claim(find_claim(db, claim_id))


@app.get("/api/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, db: Database) -> Policy:
    """Get a policy: the plan, add-ons, purchase date, trip and travelers."""
    sql = "SELECT record FROM policies WHERE policy_id = ?"
    row = fetch_one(db, sql, (policy_id,), f"Policy {policy_id}")
    return Policy(**json.loads(row["record"]))


@app.get("/api/customers/{customer_id}/claims", operation_id="get_claim_history")
def get_claim_history(customer_id: str, db: Database) -> list[PreviousClaim]:
    """Get a customer's earlier claims, with the outcome and the amount paid."""
    sql = "SELECT record FROM customers WHERE customer_id = ?"
    row = fetch_one(db, sql, (customer_id,), f"Customer {customer_id}")
    return [
        PreviousClaim(**claim) for claim in json.loads(row["record"])["previous_claims"]
    ]


@app.get("/api/instructions", operation_id="get_instructions")
def get_instructions() -> Instructions:
    """Get the agent's instructions for running the queue and for working a claim."""
    return Instructions(
        queue=(INSTRUCTIONS / "queue.md").read_text(encoding="utf-8"),
        claim=(INSTRUCTIONS / "claim.md").read_text(encoding="utf-8"),
    )


@app.get("/api/documents/{document}/sections", operation_id="list_sections")
def list_sections(document: str, db: Database) -> list[SectionTitle]:
    """List the numbered sections of the policy wording or the claims manual."""
    rows = db.execute(
        "SELECT section, title FROM sections WHERE document = ? ORDER BY section",
        (document,),
    ).fetchall()
    if not rows:
        raise HTTPException(404, f"Document {document} not found")
    return [SectionTitle(**dict(row)) for row in rows]


@app.get("/api/documents/{document}/sections/{section}", operation_id="read_section")
def read_section(document: str, section: int, db: Database) -> Section:
    """Read one numbered section of the policy wording or the claims manual."""
    sql = "SELECT * FROM sections WHERE document = ? AND section = ?"
    row = fetch_one(db, sql, (document, section), f"Section {section} of {document}")
    return Section(**dict(row))


@app.get("/api/handlers", operation_id="list_handlers")
def list_handlers(db: Database) -> list[Handler]:
    """List the claims handlers."""
    rows = db.execute("SELECT * FROM handlers ORDER BY handler_id").fetchall()
    return [Handler(**dict(row)) for row in rows]


@app.post("/api/claims/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, request: StartRequest, db: Database) -> Claim:
    """Start work on a waiting claim, which moves it to in progress."""
    claim_in(db, claim_id, "waiting", "waiting")
    db.execute(
        "UPDATE claims SET status = 'in_progress', thread_id = ? WHERE claim_id = ?",
        (request.thread_id, claim_id),
    )
    return get_claim(claim_id, db)


@app.post("/api/claims/{claim_id}/steps", operation_id="record_step")
def record_step(claim_id: str, request: StepRequest, db: Database) -> Step:
    """Record one step of the agent's work on a claim."""
    thread_id = find_claim(db, claim_id)["thread_id"]
    if thread_id is None:
        raise HTTPException(409, f"Claim {claim_id} has not been started")
    return add_step(db, claim_id, thread_id, request.kind, request.content)


@app.get("/api/claims/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, db: Database) -> list[Step]:
    """List the steps of the agent's work on a claim, in order."""
    find_claim(db, claim_id)
    rows = db.execute(
        "SELECT * FROM steps WHERE claim_id = ? ORDER BY step_id", (claim_id,)
    ).fetchall()
    return [Step(**dict(row)) for row in rows]


@app.post("/api/claims/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, request: DecisionRequest, db: Database) -> Claim:
    """Record the decision on a claim; an approval over the limit waits for sign-off."""
    claim_in(db, claim_id, "in_progress", "in progress")
    payout = round(request.payout, 2)
    held = request.decision == "approve" and payout > approval_limit(db)
    db.execute(
        "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?)",
        (claim_id, request.decision, payout, request.section, request.reason, now()),
    )
    db.execute(
        "UPDATE claims SET status = ? WHERE claim_id = ?",
        ("waiting_for_sign_off" if held else "decided", claim_id),
    )
    return get_claim(claim_id, db)


@app.post("/api/claims/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, request: PaymentRequest, db: Database) -> Payment:
    """Pay an approved claim its payout, unless it needs a handler's sign-off."""
    claim = find_claim(db, claim_id)
    if claim["decision"] != "approve":
        raise HTTPException(409, f"Claim {claim_id} has not been approved")
    if claim["paid_at"] is not None:
        raise HTTPException(409, f"Claim {claim_id} has already been paid")
    if claim["status"] == "waiting_for_sign_off":
        raise HTTPException(
            403,
            f"A payout over {dollars(approval_limit(db))} needs a handler's sign-off",
        )
    if round(request.amount, 2) != claim["payout"]:
        raise HTTPException(
            422, f"The amount must be the approved payout of {dollars(claim['payout'])}"
        )
    return pay(db, claim_id, claim["payout"], None)


@app.post("/api/claims/{claim_id}/sign-off", operation_id="sign_off_claim")
def sign_off_claim(claim_id: str, request: SignOffRequest, db: Database) -> Claim:
    """Sign off a held payout as a handler, which pays it and decides the claim."""
    claim = claim_in(db, claim_id, "waiting_for_sign_off", "waiting for sign-off")
    sql = "SELECT * FROM handlers WHERE handler_id = ?"
    row = fetch_one(db, sql, (request.handler_id,), f"Handler {request.handler_id}")
    handler = Handler(**dict(row))
    if not handler.can_approve_over_limit:
        raise HTTPException(
            403,
            f"{handler.name} can't sign off payouts over {dollars(approval_limit(db))}",
        )
    pay(db, claim_id, claim["payout"], handler.name)
    db.execute("UPDATE claims SET status = 'decided' WHERE claim_id = ?", (claim_id,))
    return get_claim(claim_id, db)


@app.post("/api/claims/{claim_id}/failure", operation_id="fail_claim")
def fail_claim(claim_id: str, request: FailureRequest, db: Database) -> Claim:
    """Record a failed attempt: the claim goes back in the queue, or to a handler."""
    claim = claim_in(db, claim_id, "in_progress", "in progress")
    fail(db, claim, request.error)
    return get_claim(claim_id, db)


@app.post("/api/runs", operation_id="start_run")
def start_run(request: StartRunRequest, db: Database) -> Run:
    """Start a run, first failing any claim a stopped run left in progress."""
    if db.execute("SELECT 1 FROM runs WHERE run_id = ?", (request.run_id,)).fetchone():
        raise HTTPException(409, f"Run {request.run_id} already exists")
    for claim in db.execute(
        "SELECT * FROM claims WHERE status = 'in_progress' ORDER BY claim_id"
    ).fetchall():
        fail(db, claim, "The run working this claim was stopped")
    db.execute(
        "INSERT INTO runs (run_id, cap, started_at, todos) VALUES (?, ?, ?, '[]')",
        (request.run_id, request.cap, now()),
    )
    return find_run(db, request.run_id)


@app.put("/api/runs/{run_id}/todos", operation_id="write_todos")
def write_todos(run_id: str, request: TodosRequest, db: Database) -> Run:
    """Replace a run's to-do list."""
    find_run(db, run_id)
    todos = json.dumps([todo.model_dump() for todo in request.todos])
    db.execute("UPDATE runs SET todos = ? WHERE run_id = ?", (todos, run_id))
    return find_run(db, run_id)


@app.post("/api/runs/{run_id}/finish", operation_id="finish_run")
def finish_run(run_id: str, request: FinishRunRequest, db: Database) -> Run:
    """Finish a run with a short summary for the handlers."""
    find_run(db, run_id)
    db.execute(
        "UPDATE runs SET finished_at = ?, summary = ? WHERE run_id = ?",
        (now(), request.summary, run_id),
    )
    return find_run(db, run_id)


@app.get("/api/runs/current", operation_id="get_current_run")
def get_current_run(db: Database) -> Run | None:
    """Get the latest run with its to-do list and summary, or null before the first."""
    row = db.execute(
        "SELECT * FROM runs ORDER BY started_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    return None if row is None else to_run(row)
