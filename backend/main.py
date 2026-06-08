import os
import random
import string
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine, get_db
from .models import User, TrainerProfile, StudentProfile, PasswordResetToken
from .schemas import (
    UserCreate,
    UserResponse,
    LinkTrainerRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
)
from .auth import (
    hash_password,
    verify_password,
    authenticate_user,
    create_access_token,
    get_current_user,
    generate_reset_token,
    hash_reset_token,
)
from .email_service import send_email

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RESET_PASSWORD_URL = os.getenv("RESET_PASSWORD_URL", "https://teu-dominio.com/reset-password")
RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("RESET_TOKEN_EXPIRE_MINUTES", "30"))


def generate_trainer_code(db: Session):
    while True:
        code = "FMPT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        exists = db.query(TrainerProfile).filter(TrainerProfile.trainer_code == code).first()
        if not exists:
            return code


@app.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    if user.tipo not in ["aluno", "treinador"]:
        raise HTTPException(status_code=400, detail="Tipo inválido")

    existing_user = db.query(User).filter(
        (User.username == user.username) | (User.email == user.email)
    ).first()

    if existing_user:
        raise HTTPException(status_code=400, detail="Username ou email já existe")

    try:
        trainer_code_response = None
        linked_trainer_code_response = None

        new_user = User(
            username=user.username.strip(),
            email=user.email.strip().lower(),
            password_hash=hash_password(user.password),
            tipo=user.tipo,
        )

        db.add(new_user)
        db.flush()

        if user.tipo == "treinador":
            trainer_code = generate_trainer_code(db)
            trainer_profile = TrainerProfile(
                user_id=new_user.id,
                trainer_code=trainer_code
            )
            db.add(trainer_profile)
            trainer_code_response = trainer_code

        elif user.tipo == "aluno":
            student_profile = StudentProfile(user_id=new_user.id)

            if user.trainer_code:
                trainer = db.query(TrainerProfile).filter(
                    TrainerProfile.trainer_code == user.trainer_code.strip()
                ).first()

                if not trainer:
                    raise HTTPException(status_code=400, detail="Código do trainer inválido")

                student_profile.trainer_id = trainer.id
                linked_trainer_code_response = trainer.trainer_code

            db.add(student_profile)

        db.commit()
        db.refresh(new_user)

        return {
            "id": new_user.id,
            "username": new_user.username,
            "email": new_user.email,
            "tipo": new_user.tipo,
            "trainer_code": trainer_code_response,
            "linked_trainer_code": linked_trainer_code_response,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro interno no registo")


@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)

    if not user:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    access_token = create_access_token(data={"sub": user.username})
    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@app.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    trainer_code = None
    linked_trainer_code = None

    if current_user.tipo == "treinador":
        trainer_profile = db.query(TrainerProfile).filter(
            TrainerProfile.user_id == current_user.id
        ).first()
        if trainer_profile:
            trainer_code = trainer_profile.trainer_code

    if current_user.tipo == "aluno":
        student_profile = db.query(StudentProfile).filter(
            StudentProfile.user_id == current_user.id
        ).first()
        if student_profile and student_profile.trainer_id:
            trainer = db.query(TrainerProfile).filter(
                TrainerProfile.id == student_profile.trainer_id
            ).first()
            if trainer:
                linked_trainer_code = trainer.trainer_code

    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "tipo": current_user.tipo,
        "trainer_code": trainer_code,
        "linked_trainer_code": linked_trainer_code,
    }


@app.post("/link-trainer")
def link_trainer(
    data: LinkTrainerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tipo != "aluno":
        raise HTTPException(status_code=403, detail="Só alunos podem associar trainer")

    student_profile = db.query(StudentProfile).filter(
        StudentProfile.user_id == current_user.id
    ).first()

    if not student_profile:
        student_profile = StudentProfile(user_id=current_user.id)
        db.add(student_profile)
        db.commit()
        db.refresh(student_profile)

    trainer = db.query(TrainerProfile).filter(
        TrainerProfile.trainer_code == data.trainer_code.strip()
    ).first()

    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer não encontrado")

    student_profile.trainer_id = trainer.id
    db.commit()

    return {
        "message": "Aluno associado ao trainer com sucesso",
        "trainer_code": trainer.trainer_code
    }


@app.get("/my-students")
def my_students(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tipo != "treinador":
        raise HTTPException(status_code=403, detail="Só treinadores podem ver alunos")

    trainer_profile = db.query(TrainerProfile).filter(
        TrainerProfile.user_id == current_user.id
    ).first()

    if not trainer_profile:
        return []

    students = db.query(StudentProfile).filter(
        StudentProfile.trainer_id == trainer_profile.id
    ).all()

    result = []
    for student in students:
        user = db.query(User).filter(User.id == student.user_id).first()
        if user:
            result.append({
                "id": user.id,
                "username": user.username,
                "email": user.email,
            })

    return result


@app.post("/forgot-password")
def forgot_password(
    data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    generic_message = {
        "message": "Se existir uma conta associada a este email, vais receber instruções para redefinir a password."
    }

    user = db.query(User).filter(User.email == data.email.strip().lower()).first()

    if not user:
        return generic_message

    active_tokens = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used == False
    ).all()

    for token in active_tokens:
        token.used = True

    raw_token = generate_reset_token()
    token_hash = hash_reset_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)

    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        used=False,
    )
    db.add(reset_token)
    db.commit()

    reset_link = f"{RESET_PASSWORD_URL}?token={raw_token}"

    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #111827;">
        <h2>Redefinição de password</h2>
        <p>Recebemos um pedido para redefinir a password da tua conta FitManagerPT.</p>
        <p>Carrega no botão abaixo para continuar:</p>
        <p>
          <a href="{reset_link}" style="background:#16a34a;color:#ffffff;padding:12px 18px;text-decoration:none;border-radius:8px;display:inline-block;">
            Redefinir password
          </a>
        </p>
        <p>Este link expira em {RESET_TOKEN_EXPIRE_MINUTES} minutos.</p>
        <p>Se não foste tu, ignora este email.</p>
      </body>
    </html>
    """

    background_tasks.add_task(
        send_email,
        user.email,
        "Redefinição de password - FitManagerPT",
        html_body,
    )

    return generic_message


@app.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    if data.new_password != data.confirm_password:
        raise HTTPException(status_code=400, detail="As passwords não coincidem")

    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="A password deve ter pelo menos 8 caracteres")

    token_hash = hash_reset_token(data.token)

    reset_entry = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used == False
    ).first()

    if not reset_entry:
        raise HTTPException(status_code=400, detail="Token inválido ou já utilizado")

    if reset_entry.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Token expirado")

    user = db.query(User).filter(User.id == reset_entry.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")

    user.password_hash = hash_password(data.new_password)
    reset_entry.used = True
    db.commit()

    return {"message": "Password atualizada com sucesso"}


@app.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.new_password != data.confirm_password:
        raise HTTPException(status_code=400, detail="As passwords não coincidem")

    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="A password deve ter pelo menos 8 caracteres")

    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Password atual incorreta")

    current_user.password_hash = hash_password(data.new_password)
    db.commit()

    return {"message": "Password alterada com sucesso"}