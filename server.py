from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timedelta

# MongoDB connection
mongo_url = os.environ.get('MONGO_URL', os.environ.get('MONGODB_URL', 'mongodb://localhost:27017'))
db_name = os.environ.get('DB_NAME', 'vivy')
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

app = FastAPI()
api_router = APIRouter(prefix="/api")

# Global currencies
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
    "RUB": {"name": "Russian Ruble", "symbol": "₽"},
    "TRY": {"name": "Turkish Lira", "symbol": "₺"},
    "PLN": {"name": "Polish Zloty", "symbol": "zł"},
    "THB": {"name": "Thai Baht", "symbol": "฿"},
    "IDR": {"name": "Indonesian Rupiah", "symbol": "Rp"},
    "MYR": {"name": "Malaysian Ringgit", "symbol": "RM"},
    "PHP": {"name": "Philippine Peso", "symbol": "₱"},
    "CZK": {"name": "Czech Koruna", "symbol": "Kč"},
    "ILS": {"name": "Israeli Shekel", "symbol": "₪"},
    "CLP": {"name": "Chilean Peso", "symbol": "$"},
    "AED": {"name": "UAE Dirham", "symbol": "د.إ"},
    "SAR": {"name": "Saudi Riyal", "symbol": "﷼"},
    "TWD": {"name": "Taiwan Dollar", "symbol": "NT$"},
    "DKK": {"name": "Danish Krone", "symbol": "kr"},
    "COP": {"name": "Colombian Peso", "symbol": "$"},
    "ARS": {"name": "Argentine Peso", "symbol": "$"},
    "VND": {"name": "Vietnamese Dong", "symbol": "₫"},
    "EGP": {"name": "Egyptian Pound", "symbol": "£"},
    "PKR": {"name": "Pakistani Rupee", "symbol": "₨"},
    "NGN": {"name": "Nigerian Naira", "symbol": "₦"},
    "BDT": {"name": "Bangladeshi Taka", "symbol": "৳"},
    "HUF": {"name": "Hungarian Forint", "symbol": "Ft"},
}

# Models
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

# Settlement calculation
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

# API Routes
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
    await db.sessions.update_one(
        {"id": session_id},
        {"$push": {"participants": participant.dict()}}
    )
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
    await db.sessions.update_one(
        {"id": session_id},
        {"$pull": {"participants": {"id": participant_id}}}
    )
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
    
    await db.sessions.update_one(
        {"id": session_id},
        {"$push": {"expenses": expense.dict()}}
    )
    session = await db.sessions.find_one({"id": session_id})
    return Session(**session)

@api_router.delete("/sessions/{session_id}/expenses/{expense_id}", response_model=Session)
async def remove_expense(session_id: str, expense_id: str):
    session = await db.sessions.find_one({"id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.sessions.update_one(
        {"id": session_id},
        {"$pull": {"expenses": {"id": expense_id}}}
    )
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

@api_router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    session = await db.sessions.find_one({"id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.sessions.delete_one({"id": session_id})
    return {"message": "Session deleted successfully"}

@api_router.get("/stats")
async def get_stats():
    total_sessions = await db.sessions.count_documents({})
    
    pipeline = [
        {"$project": {"expense_count": {"$size": {"$ifNull": ["$expenses", []]}}}},
        {"$group": {"_id": None, "total": {"$sum": "$expense_count"}}}
    ]
    expense_result = await db.sessions.aggregate(pipeline).to_list(1)
    total_expenses = expense_result[0]["total"] if expense_result else 0
    
    pipeline_participants = [
        {"$project": {"participant_count": {"$size": {"$ifNull": ["$participants", []]}}}},
        {"$group": {"_id": None, "total": {"$sum": "$participant_count"}}}
    ]
    participant_result = await db.sessions.aggregate(pipeline_participants).to_list(1)
    total_participants = participant_result[0]["total"] if participant_result else 0
    
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    active_sessions = await db.sessions.count_documents({"created_at": {"$gte": seven_days_ago}})
    
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sessions_today = await db.sessions.count_documents({"created_at": {"$gte": today_start}})
    
    return {
        "total_sessions": total_sessions,
        "total_expenses": total_expenses,
        "total_participants": total_participants,
        "active_sessions_7d": active_sessions,
        "sessions_today": sessions_today,
        "generated_at": datetime.utcnow().isoformat()
    }

# Include API router
app.include_router(api_router)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (frontend)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/session", StaticFiles(directory=static_dir, html=True), name="session_static")
    app.mount("/_expo", StaticFiles(directory=os.path.join(static_dir, "_expo")), name="expo_static")
    app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets_static")
    
    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(static_dir, "index.html"))
    
    @app.get("/stats")
    async def serve_stats():
        return FileResponse(os.path.join(static_dir, "stats.html"))
    
    @app.get("/session/{session_id}")
    async def serve_session(session_id: str):
        return FileResponse(os.path.join(static_dir, "session", "[id].html"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
