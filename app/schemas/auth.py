from pydantic import BaseModel, EmailStr, Field


class SignupForm(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1)
    password: str = Field(..., min_length=8)


class LoginForm(BaseModel):
    email: EmailStr
    password: str
