from pydantic import BaseModel, EmailStr
from typing import Optional


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