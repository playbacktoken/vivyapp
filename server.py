from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timedelta

mongo_url = os.environ.get('MONGO_URL', os.environ.get('MONGODB_URL', 'mongodb://localhost:27017'))
db_name = os.environ.get('DB_NAME', 'vivy')
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

app = FastAPI()
api_router = APIRouter(prefix="/api")

CURRENCIES = {
    "USD": {"name": "US Dollar", "symbol": "$"},
    "EUR": {"name": "Euro", "symbol": "€"},
    "GBP": {"name": "British Pound", "symbol": "£"},
    "JPY": {"name": "Japanese Yen", "symbol": "¥"},
    "CNY": {"name": "Chinese Yuan", "symbol": "¥"},
    "INR": {"name": "Indian Rupee", "symbol": "₹"},
    "AUD": {"name": "Australian Dollar", "symbol": "A$"},
    "CAD": {"name": "Canadian Dollar", "symbol": "C$"},
    "CHF": {"name": "Swiss Franc", "symbol": "CHF"},
    "HKD": {"name": "Hong Kong Dollar", "symbol": "HK$"},
    "SGD": {"name": "Singapore Dollar", "symbol": "S$"},
    "SEK": {"name": "Swedish Krona", "symbol": "kr"},
    "KRW": {"name": "South Korean Won", "symbol": "₩"},
    "NOK": {"name": "Norwegian Krone", "symbol": "kr"},
    "NZD": {"name": "New Zealand Dollar", "symbol": "NZ$"},
    "MXN": {"name": "Mexican Peso", "symbol": "$"},
    "BRL": {"name": "Brazilian Real", "symbol": "R$"},
    "ZAR": {"name": "South African Rand", "symbol": "R"},
    "THB": {"name": "Thai Baht", "symbol": "฿"},
    "PHP": {"name": "Philippine Peso", "symbol": "₱"},
}

class Participant(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str

class ParticipantCreate(BaseModel):
    name: str

class PayerContribution(BaseModel):
    participant_id: str
    amount: float

class Expense(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    amount: float
    payer_id: Optional[str] = None
    payers: Optional[List[PayerContribution]] = None
    split_among: List[str]
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ExpenseCreate(BaseModel):
    description: str
    amount: float
    payer_id: Optional[str] = None
    payers: Optional[List[PayerContribution]] = None
    split_among: List[str]

class Session(BaseModel):
    id: str = Field(default_factory=lambda: ''.join(__import__('random').choices(__import__('string').ascii_lowercase + __import__('string').digits, k=8)))
    name: str
    currency: str = "USD"
    participants: List[Participant] = []
    expenses: List[Expense] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)

class SessionCreate(BaseModel):
    name: str
    currency: str = "USD"

class Settlement(BaseModel):
    from_participant: Participant
    to_participant: Participant
    amount: float

class SettleUpResponse(BaseModel):
    settlements: List[Settlement]
    total_expenses: float
    currency: str
    currency_symbol: str

def calculate_settlements(participants: List[Participant], expenses: List[Expense]) -> List[Settlement]:
    if not participants or not expenses:
        return []
    balances: Dict[str, float] = {p.id: 0.0 for p in participants}
    participant_map = {p.id: p for p in participants}
    for expense in expenses:
        if not expense.split_among:
            continue
        share = expense.amount / len(expense.split_among)
        for person_id in expense.split_among:
            balances[person_id] -= share
        if expense.payers:
            for payer in expense.payers:
                if payer.participant_id in balances:
                    balances[payer.participant_id] += payer.amount
        elif expense.payer_id:
            balances[expense.payer_id] += expense.amount
    debtors = []
    creditors = []
    for person_id, balance in balances.items():
        if balance < -0.01:
            debtors.append((person_id, -balance))
        elif balance > 0.01:
            creditors.append((person_id, balance))
    debtors.sort(key=lambda x: x[1], reverse=True)
    creditors.sort(key=lambda x: x[1], reverse=True)
    settlements = []
    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        debtor_id, debt = debtors[i]
        creditor_id, credit = creditors[j]
        amount = min(debt, credit)
        if amount > 0.01:
            settlements.append(Settlement(
                from_participant=participant_map[debtor_id],
                to_participant=participant_map[creditor_id],
                amount=round(amount, 2)
            ))
        debtors[i] = (debtor_id, debt - amount)
        creditors[j] = (creditor_id, credit - amount)
        if debtors[i][1] < 0.01:
            i += 1
        if creditors[j][1] < 0.01:
            j += 1
    return settlements

@api_router.get("/")
async def root():
    return {"message": "Welcome to Vivy API"}

@api_router.get("/currencies")
async def get_currencies():
    return CURRENCIES

@api_router.post("/sessions", response_model=Session)
async def create_session(input: SessionCreate):
    if input.currency not in CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {input.currency}")
    session = Session(name=input.name, currency=input.currency)
    await db.sessions.insert_one(session.dict())
    return session

@api_router.get("/sessions/{session_id}", response_model=Session)
async def get_session(session_id: str):
    session = await db.sessions.find_one({"id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return Session(**session)

@api_router.post("/sessions/{session_id}/participants", response_model=Session)
async def add_participant(session_id: str, input: ParticipantCreate):
    session = await db.sessions.find_one({"id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    participant = Participant(name=input.name)
    await db.sessions.update_one({"id": session_id}, {"$push": {"participants": participant.dict()}})
    session = await db.sessions.find_one({"id": session_id})
    return Session(**session)

@api_router.delete("/sessions/{session_id}/participants/{participant_id}", response_model=Session)
async def remove_participant(session_id: str, participant_id: str):
    session = await db.sessions.find_one({"id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    for expense in session.get("expenses", []):
        if expense["payer_id"] == participant_id or participant_id in expense["split_among"]:
            raise HTTPException(status_code=400, detail="Cannot remove participant involved in expenses")
    await db.sessions.update_one({"id": session_id}, {"$pull": {"participants": {"id": participant_id}}})
    session = await db.sessions.find_one({"id": session_id})
    return Session(**session)

@api_router.post("/sessions/{session_id}/expenses", response_model=Session)
async def add_expense(session_id: str, input: ExpenseCreate):
    session = await db.sessions.find_one({"id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    participant_ids = [p["id"] for p in session.get("participants", [])]
    for person_id in input.split_among:
        if person_id not in participant_ids:
            raise HTTPException(status_code=400, detail=f"Participant {person_id} is not in this session")
    if input.payers:
        for payer in input.payers:
            if payer.participant_id not in participant_ids:
                raise HTTPException(status_code=400, detail=f"Payer {payer.participant_id} is not a participant")
        total_paid = sum(p.amount for p in input.payers)
        if abs(total_paid - input.amount) > 0.01:
            raise HTTPException(status_code=400, detail=f"Total paid doesn't match expense amount")
    elif input.payer_id:
        if input.payer_id not in participant_ids:
            raise HTTPException(status_code=400, detail="Payer is not a participant")
    else:
        raise HTTPException(status_code=400, detail="Either payer_id or payers must be provided")
    expense = Expense(
        description=input.description,
        amount=input.amount,
        payer_id=input.payer_id,
        payers=[p.dict() for p in input.payers] if input.payers else None,
        split_among=input.split_among
    )
    await db.sessions.update_one({"id": session_id}, {"$push": {"expenses": expense.dict()}})
    session = await db.sessions.find_one({"id": session_id})
    return Session(**session)

@api_router.delete("/sessions/{session_id}/expenses/{expense_id}", response_model=Session)
async def remove_expense(session_id: str, expense_id: str):
    session = await db.sessions.find_one({"id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.sessions.update_one({"id": session_id}, {"$pull": {"expenses": {"id": expense_id}}})
    session = await db.sessions.find_one({"id": session_id})
    return Session(**session)

@api_router.get("/sessions/{session_id}/settle", response_model=SettleUpResponse)
async def settle_up(session_id: str):
    session = await db.sessions.find_one({"id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session_obj = Session(**session)
    settlements = calculate_settlements(session_obj.participants, session_obj.expenses)
    total_expenses = sum(e.amount for e in session_obj.expenses)
    currency_info = CURRENCIES.get(session_obj.currency, {"symbol": session_obj.currency})
    return SettleUpResponse(
        settlements=settlements,
        total_expenses=round(total_expenses, 2),
        currency=session_obj.currency,
        currency_symbol=currency_info["symbol"]
    )

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

INDEX_HTML = ""
if os.path.exists("index.html"):
    with open("index.html", "r") as f:
        INDEX_HTML = f.read()

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return INDEX_HTML or "<h1>Vivy API Running</h1>"

@app.get("/session/{session_id}", response_class=HTMLResponse)
async def serve_session(session_id: str):
    return INDEX_HTML or "<h1>Vivy API Running</h1>"

logging.basicConfig(level=logging.INFO)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
