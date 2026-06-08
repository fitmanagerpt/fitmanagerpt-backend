from pydantic import BaseModel, EmailStr
from typing import Optional, List


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    tipo: str
    trainer_code: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    tipo: str
    trainer_code: Optional[str] = None
    linked_trainer_code: Optional[str] = None

    class Config:
        from_attributes = True


class LinkTrainerRequest(BaseModel):
    trainer_code: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    confirm_password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class LessonCreate(BaseModel):
    title: str
    description: Optional[str] = None
    scheduled_at: str
    lesson_type: str
    location: Optional[str] = None
    video_link: Optional[str] = None
    video_upload_name: Optional[str] = None


class LessonResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    scheduledat: str
    lessontype: str
    location: Optional[str] = None
    videolink: Optional[str] = None
    videouploadname: Optional[str] = None
    enrolledcount: int = 0
    isenrolled: bool = False
    canwatchvideo: bool = False


class LessonEnrollRequest(BaseModel):
    lesson_id: int


class StudentBodyProfileUpdate(BaseModel):
    height_cm: Optional[float] = None
    initial_weight_kg: Optional[float] = None
    goal: Optional[str] = None
    injuries: Optional[str] = None
    weekly_availability: Optional[str] = None


class StudentBodyProfileResponse(BaseModel):
    height_cm: Optional[float] = None
    initial_weight_kg: Optional[float] = None
    goal: Optional[str] = None
    injuries: Optional[str] = None
    weekly_availability: Optional[str] = None
    current_weight_kg: Optional[float] = None
    bmi: Optional[float] = None


class StudentProgressCreate(BaseModel):
    weight_kg: float
    week_label: Optional[str] = None
    notes: Optional[str] = None


class StudentProgressItem(BaseModel):
    id: int
    weight_kg: float
    week_label: Optional[str] = None
    notes: Optional[str] = None
    created_at: str
    bmi: Optional[float] = None


class TrainerStudentProgressResponse(BaseModel):
    student_id: int
    username: str
    email: str
    height_cm: Optional[float] = None
    initial_weight_kg: Optional[float] = None
    current_weight_kg: Optional[float] = None
    bmi: Optional[float] = None
    progress: List[StudentProgressItem]