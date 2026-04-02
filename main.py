import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Optional
from database import get_db, engine, Base
from models import User, Message, Appointment
from dotenv import load_dotenv

load_dotenv()

# Barcha jadvallarni yaratish
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Klinika AI Bot API")

# CORS — React frontend uchun
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────
# PYDANTIC SCHEMAS
# ─────────────────────────────────────────

class AppointmentUpdate(BaseModel):
    status: str
    note: Optional[str] = None

class MessageCreate(BaseModel):
    telegram_id: str
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    role: str
    content: str

class AppointmentCreate(BaseModel):
    telegram_id: str
    full_name: str
    phone: str
    doctor: str
    preferred_time: str

# ─────────────────────────────────────────
# BOT ENDPOINTLARI (bot.py ishlatadi)
# ─────────────────────────────────────────

@app.post("/bot/message")
def save_message(data: MessageCreate, db: Session = Depends(get_db)):
    """Bot har bir xabarni shu yerga saqlaydi"""
    user = db.query(User).filter(User.telegram_id == data.telegram_id).first()
    if not user:
        user = User(
            telegram_id=data.telegram_id,
            first_name=data.first_name,
            last_name=data.last_name,
            username=data.username,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    message = Message(user_id=user.id, role=data.role, content=data.content)
    db.add(message)
    db.commit()
    return {"ok": True}


@app.post("/bot/appointment")
def save_appointment(data: AppointmentCreate, db: Session = Depends(get_db)):
    """Bot qabul so'rovini saqlaydi"""
    user = db.query(User).filter(User.telegram_id == data.telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    appt = Appointment(
        user_id=user.id,
        full_name=data.full_name,
        phone=data.phone,
        doctor=data.doctor,
        preferred_time=data.preferred_time,
    )
    db.add(appt)
    db.commit()
    return {"ok": True}


# ─────────────────────────────────────────
# ADMIN PANEL ENDPOINTLARI
# ─────────────────────────────────────────

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    """Dashboard statistikasi"""
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())

    total_users = db.query(func.count(User.id)).scalar()
    today_messages = db.query(func.count(Message.id)).filter(
        Message.created_at >= today_start
    ).scalar()
    pending_appointments = db.query(func.count(Appointment.id)).filter(
        Appointment.status == "pending"
    ).scalar()
    total_appointments = db.query(func.count(Appointment.id)).scalar()

    # Haftalik xabarlar
    weekly = []
    for i in range(6, -1, -1):
        day = datetime.utcnow() - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day.replace(hour=23, minute=59, second=59)
        count = db.query(func.count(Message.id)).filter(
            Message.created_at >= day_start,
            Message.created_at <= day_end,
            Message.role == "user"
        ).scalar()
        weekly.append({"day": day.strftime("%a"), "count": count})

    return {
        "total_users": total_users,
        "today_messages": today_messages,
        "pending_appointments": pending_appointments,
        "total_appointments": total_appointments,
        "weekly": weekly,
    }


@app.get("/api/chats")
def get_chats(db: Session = Depends(get_db)):
    """Barcha foydalanuvchilar ro'yxati"""
    users = db.query(User).order_by(desc(User.created_at)).all()
    result = []
    for user in users:
        last_msg = db.query(Message).filter(
            Message.user_id == user.id
        ).order_by(desc(Message.created_at)).first()

        result.append({
            "id": user.id,
            "telegram_id": user.telegram_id,
            "name": f"{user.first_name} {user.last_name or ''}".strip(),
            "username": user.username,
            "last_message": last_msg.content[:60] if last_msg else "",
            "last_time": last_msg.created_at.strftime("%H:%M") if last_msg else "",
            "created_at": user.created_at.isoformat(),
        })
    return result


@app.get("/api/chats/{user_id}/messages")
def get_messages(user_id: int, db: Session = Depends(get_db)):
    """Bitta foydalanuvchi suhbati"""
    messages = db.query(Message).filter(
        Message.user_id == user_id
    ).order_by(Message.created_at).all()

    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "time": m.created_at.strftime("%H:%M"),
        }
        for m in messages
    ]


@app.get("/api/appointments")
def get_appointments(db: Session = Depends(get_db)):
    """Barcha qabul so'rovlari"""
    appts = db.query(Appointment).order_by(desc(Appointment.created_at)).all()
    return [
        {
            "id": a.id,
            "full_name": a.full_name,
            "phone": a.phone,
            "doctor": a.doctor,
            "preferred_time": a.preferred_time,
            "status": a.status,
            "note": a.note,
            "created_at": a.created_at.strftime("%d.%m.%Y %H:%M"),
        }
        for a in appts
    ]


@app.patch("/api/appointments/{appt_id}")
def update_appointment(
    appt_id: int, data: AppointmentUpdate, db: Session = Depends(get_db)
):
    """Qabulni tasdiqlash yoki bekor qilish"""
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Topilmadi")
    appt.status = data.status
    if data.note:
        appt.note = data.note
    db.commit()
    return {"ok": True}


@app.get("/")
def root():
    return {"status": "Klinika AI Bot API ishlayapti!"}