from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Float, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    tipo = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    trainer_profile = relationship("TrainerProfile", back_populates="user", uselist=False)
    student_profile = relationship("StudentProfile", back_populates="user", uselist=False)


class TrainerProfile(Base):
    __tablename__ = "trainer_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    trainer_code = Column(String, unique=True, index=True, nullable=False)

    user = relationship("User", back_populates="trainer_profile")
    students = relationship("StudentProfile", back_populates="trainer")
    lessons = relationship("Lesson", back_populates="trainer", cascade="all, delete-orphan")


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    trainer_id = Column(Integer, ForeignKey("trainer_profiles.id"), nullable=True)

    height_cm = Column(Float, nullable=True)
    initial_weight_kg = Column(Float, nullable=True)
    goal = Column(String, nullable=True)
    injuries = Column(Text, nullable=True)
    weekly_availability = Column(String, nullable=True)

    user = relationship("User", back_populates="student_profile")
    trainer = relationship("TrainerProfile", back_populates="students")
    progress_entries = relationship("StudentProgress", back_populates="student", cascade="all, delete-orphan")
    lesson_enrollments = relationship("LessonEnrollment", back_populates="student", cascade="all, delete-orphan")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")


class Lesson(Base):
    __tablename__ = "lessons"

    id = Column(Integer, primary_key=True, index=True)
    trainer_id = Column(Integer, ForeignKey("trainer_profiles.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=False, index=True)
    lesson_type = Column(String, nullable=False)  # online | presencial
    location = Column(String, nullable=True)
    video_link = Column(Text, nullable=True)
    video_upload_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    trainer = relationship("TrainerProfile", back_populates="lessons")
    enrollments = relationship("LessonEnrollment", back_populates="lesson", cascade="all, delete-orphan")


class LessonEnrollment(Base):
    __tablename__ = "lesson_enrollments"

    id = Column(Integer, primary_key=True, index=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("student_profiles.id"), nullable=False, index=True)
    status = Column(String, default="inscrito", nullable=False)  # inscrito | presente | faltou | concluida
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lesson = relationship("Lesson", back_populates="enrollments")
    student = relationship("StudentProfile", back_populates="lesson_enrollments")


class StudentProgress(Base):
    __tablename__ = "student_progress"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("student_profiles.id"), nullable=False, index=True)
    weight_kg = Column(Float, nullable=False)
    week_label = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    student = relationship("StudentProfile", back_populates="progress_entries")