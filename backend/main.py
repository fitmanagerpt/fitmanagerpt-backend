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
from .models import (
    User,
    TrainerProfile,
    StudentProfile,
    PasswordResetToken,
    Lesson,
    LessonEnrollment,
    StudentProgress,
)
from .schemas import (
    UserCreate,
    UserResponse,
    LinkTrainerRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
    LessonCreate,
    LessonEnrollRequest,
    StudentBodyProfileUpdate,
    StudentBodyProfileResponse,
    StudentProgressCreate,
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


def parse_iso_datetime(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        raise HTTPException(status_code=400, detail="Data/hora inválida")


def calculate_bmi(weight_kg: float | None, height_cm: float | None):
    if not weight_kg or not height_cm or height_cm <= 0:
        return None
    height_m = height_cm / 100
    return round(weight_kg / (height_m * height_m), 2)


def build_lesson_response(lesson: Lesson, student_profile: StudentProfile | None = None):
    is_enrolled = False
    can_watch_video = False

    if student_profile:
        enrollment = next(
            (e for e in lesson.enrollments if e.student_id == student_profile.id),
            None,
        )
        is_enrolled = enrollment is not None

        now = datetime.now(timezone.utc)
        scheduled_at = lesson.scheduled_at
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

        can_watch_video = (
            lesson.lesson_type == "online"
            and is_enrolled
            and now >= scheduled_at
        )

    return {
        "id": lesson.id,
        "title": lesson.title,
        "description": lesson.description,
        "scheduledat": lesson.scheduled_at.isoformat(),
        "lessontype": lesson.lesson_type,
        "location": lesson.location,
        "videolink": lesson.video_link,
        "videouploadname": lesson.video_upload_name,
        "enrolledcount": len(lesson.enrollments),
        "isenrolled": is_enrolled,
        "canwatchvideo": can_watch_video,
    }


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
            current_weight = (
                db.query(StudentProgress)
                .filter(StudentProgress.student_id == student.id)
                .order_by(StudentProgress.created_at.desc())
                .first()
            )
            result.append({
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "height_cm": student.height_cm,
                "initial_weight_kg": student.initial_weight_kg,
                "current_weight_kg": current_weight.weight_kg if current_weight else student.initial_weight_kg,
                "bmi": calculate_bmi(
                    current_weight.weight_kg if current_weight else student.initial_weight_kg,
                    student.height_cm,
                ),
            })

    return result


@app.post("/trainer-lessons")
def create_lesson(
    data: LessonCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tipo != "treinador":
        raise HTTPException(status_code=403, detail="Só treinadores podem criar aulas")

    trainer_profile = db.query(TrainerProfile).filter(
        TrainerProfile.user_id == current_user.id
    ).first()

    if not trainer_profile:
        raise HTTPException(status_code=404, detail="Trainer não encontrado")

    if data.lesson_type not in ["online", "presencial"]:
        raise HTTPException(status_code=400, detail="Tipo de aula inválido")

    if data.lesson_type == "presencial" and not data.location:
        raise HTTPException(status_code=400, detail="Indica o local da aula presencial")

    scheduled_at = parse_iso_datetime(data.scheduled_at)

    lesson = Lesson(
        trainer_id=trainer_profile.id,
        title=data.title.strip(),
        description=(data.description or "").strip(),
        scheduled_at=scheduled_at,
        lesson_type=data.lesson_type,
        location=(data.location or "").strip() or None,
        video_link=(data.video_link or "").strip() or None,
        video_upload_name=(data.video_upload_name or "").strip() or None,
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)

    return {"message": "Aula criada com sucesso", "id": lesson.id}


@app.get("/trainer-lessons")
def get_trainer_lessons(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tipo != "treinador":
        raise HTTPException(status_code=403, detail="Só treinadores podem ver as suas aulas")

    trainer_profile = db.query(TrainerProfile).filter(
        TrainerProfile.user_id == current_user.id
    ).first()

    if not trainer_profile:
        return []

    lessons = (
        db.query(Lesson)
        .filter(Lesson.trainer_id == trainer_profile.id, Lesson.is_active == True)
        .order_by(Lesson.scheduled_at.asc())
        .all()
    )

    return [build_lesson_response(lesson) for lesson in lessons]


@app.get("/student-lessons")
def get_student_lessons(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tipo != "aluno":
        raise HTTPException(status_code=403, detail="Só alunos podem ver aulas")

    student_profile = db.query(StudentProfile).filter(
        StudentProfile.user_id == current_user.id
    ).first()

    if not student_profile or not student_profile.trainer_id:
        return []

    lessons = (
        db.query(Lesson)
        .filter(Lesson.trainer_id == student_profile.trainer_id, Lesson.is_active == True)
        .order_by(Lesson.scheduled_at.asc())
        .all()
    )

    return [build_lesson_response(lesson, student_profile) for lesson in lessons]


@app.post("/enroll-lesson")
def enroll_lesson(
    data: LessonEnrollRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tipo != "aluno":
        raise HTTPException(status_code=403, detail="Só alunos podem inscrever-se em aulas")

    student_profile = db.query(StudentProfile).filter(
        StudentProfile.user_id == current_user.id
    ).first()

    if not student_profile or not student_profile.trainer_id:
        raise HTTPException(status_code=400, detail="Aluno sem trainer associado")

    lesson = db.query(Lesson).filter(Lesson.id == data.lesson_id, Lesson.is_active == True).first()

    if not lesson:
        raise HTTPException(status_code=404, detail="Aula não encontrada")

    if lesson.trainer_id != student_profile.trainer_id:
        raise HTTPException(status_code=403, detail="Só te podes inscrever em aulas do teu trainer")

    existing = db.query(LessonEnrollment).filter(
        LessonEnrollment.lesson_id == lesson.id,
        LessonEnrollment.student_id == student_profile.id,
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Já estás inscrito nesta aula")

    enrollment = LessonEnrollment(
        lesson_id=lesson.id,
        student_id=student_profile.id,
        status="inscrito",
    )
    db.add(enrollment)
    db.commit()

    return {"message": "Inscrição feita com sucesso"}


@app.get("/student-body-profile", response_model=StudentBodyProfileResponse)
def get_student_body_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tipo != "aluno":
        raise HTTPException(status_code=403, detail="Só alunos podem ver o próprio perfil corporal")

    student_profile = db.query(StudentProfile).filter(
        StudentProfile.user_id == current_user.id
    ).first()

    if not student_profile:
        student_profile = StudentProfile(user_id=current_user.id)
        db.add(student_profile)
        db.commit()
        db.refresh(student_profile)

    latest_progress = (
        db.query(StudentProgress)
        .filter(StudentProgress.student_id == student_profile.id)
        .order_by(StudentProgress.created_at.desc())
        .first()
    )

    current_weight = latest_progress.weight_kg if latest_progress else student_profile.initial_weight_kg

    return {
        "height_cm": student_profile.height_cm,
        "initial_weight_kg": student_profile.initial_weight_kg,
        "goal": student_profile.goal,
        "injuries": student_profile.injuries,
        "weekly_availability": student_profile.weekly_availability,
        "current_weight_kg": current_weight,
        "bmi": calculate_bmi(current_weight, student_profile.height_cm),
    }


@app.put("/student-body-profile", response_model=StudentBodyProfileResponse)
def update_student_body_profile(
    data: StudentBodyProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tipo != "aluno":
        raise HTTPException(status_code=403, detail="Só alunos podem atualizar o próprio perfil corporal")

    student_profile = db.query(StudentProfile).filter(
        StudentProfile.user_id == current_user.id
    ).first()

    if not student_profile:
        student_profile = StudentProfile(user_id=current_user.id)
        db.add(student_profile)
        db.commit()
        db.refresh(student_profile)

    student_profile.height_cm = data.height_cm
    student_profile.initial_weight_kg = data.initial_weight_kg
    student_profile.goal = data.goal
    student_profile.injuries = data.injuries
    student_profile.weekly_availability = data.weekly_availability
    db.commit()
    db.refresh(student_profile)

    latest_progress = (
        db.query(StudentProgress)
        .filter(StudentProgress.student_id == student_profile.id)
        .order_by(StudentProgress.created_at.desc())
        .first()
    )

    current_weight = latest_progress.weight_kg if latest_progress else student_profile.initial_weight_kg

    return {
        "height_cm": student_profile.height_cm,
        "initial_weight_kg": student_profile.initial_weight_kg,
        "goal": student_profile.goal,
        "injuries": student_profile.injuries,
        "weekly_availability": student_profile.weekly_availability,
        "current_weight_kg": current_weight,
        "bmi": calculate_bmi(current_weight, student_profile.height_cm),
    }


@app.post("/student-progress")
def add_student_progress(
    data: StudentProgressCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tipo != "aluno":
        raise HTTPException(status_code=403, detail="Só alunos podem registar progresso")

    if data.weight_kg <= 0:
        raise HTTPException(status_code=400, detail="Peso inválido")

    student_profile = db.query(StudentProfile).filter(
        StudentProfile.user_id == current_user.id
    ).first()

    if not student_profile:
        student_profile = StudentProfile(user_id=current_user.id)
        db.add(student_profile)
        db.commit()
        db.refresh(student_profile)

    progress = StudentProgress(
        student_id=student_profile.id,
        weight_kg=data.weight_kg,
        week_label=(data.week_label or "").strip() or None,
        notes=(data.notes or "").strip() or None,
    )
    db.add(progress)
    db.commit()
    db.refresh(progress)

    return {
        "message": "Progresso registado com sucesso",
        "id": progress.id,
        "bmi": calculate_bmi(progress.weight_kg, student_profile.height_cm),
    }


@app.get("/student-progress")
def get_student_progress(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tipo != "aluno":
        raise HTTPException(status_code=403, detail="Só alunos podem ver o próprio progresso")

    student_profile = db.query(StudentProfile).filter(
        StudentProfile.user_id == current_user.id
    ).first()

    if not student_profile:
        return []

    progress_entries = (
        db.query(StudentProgress)
        .filter(StudentProgress.student_id == student_profile.id)
        .order_by(StudentProgress.created_at.asc())
        .all()
    )

    return [
        {
            "id": item.id,
            "weight_kg": item.weight_kg,
            "week_label": item.week_label,
            "notes": item.notes,
            "created_at": item.created_at.isoformat() if item.created_at else "",
            "bmi": calculate_bmi(item.weight_kg, student_profile.height_cm),
        }
        for item in progress_entries
    ]


@app.get("/trainer-student-progress/{student_user_id}")
def get_trainer_student_progress(
    student_user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tipo != "treinador":
        raise HTTPException(status_code=403, detail="Só treinadores podem ver progresso dos alunos")

    trainer_profile = db.query(TrainerProfile).filter(
        TrainerProfile.user_id == current_user.id
    ).first()

    if not trainer_profile:
        raise HTTPException(status_code=404, detail="Trainer não encontrado")

    student_user = db.query(User).filter(User.id == student_user_id, User.tipo == "aluno").first()

    if not student_user:
        raise HTTPException(status_code=404, detail="Aluno não encontrado")

    student_profile = db.query(StudentProfile).filter(
        StudentProfile.user_id == student_user.id,
        StudentProfile.trainer_id == trainer_profile.id,
    ).first()

    if not student_profile:
        raise HTTPException(status_code=403, detail="Este aluno não está associado a ti")

    progress_entries = (
        db.query(StudentProgress)
        .filter(StudentProgress.student_id == student_profile.id)
        .order_by(StudentProgress.created_at.asc())
        .all()
    )

    current_weight = progress_entries[-1].weight_kg if progress_entries else student_profile.initial_weight_kg

    return {
        "student_id": student_user.id,
        "username": student_user.username,
        "email": student_user.email,
        "height_cm": student_profile.height_cm,
        "initial_weight_kg": student_profile.initial_weight_kg,
        "current_weight_kg": current_weight,
        "bmi": calculate_bmi(current_weight, student_profile.height_cm),
        "progress": [
            {
                "id": item.id,
                "weight_kg": item.weight_kg,
                "week_label": item.week_label,
                "notes": item.notes,
                "created_at": item.created_at.isoformat() if item.created_at else "",
                "bmi": calculate_bmi(item.weight_kg, student_profile.height_cm),
            }
            for item in progress_entries
        ],
    }


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