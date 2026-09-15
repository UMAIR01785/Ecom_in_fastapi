# Ecom_in_fastapi

A FastAPI-based e-commerce backend project for authentication and user profile management.

## Overview

This project is built with FastAPI and SQLAlchemy to provide a backend API for an e-commerce application.  
It currently focuses on user account features such as registration, login, token generation, and automatic profile creation.

## Features

- User registration
- User login
- JWT access token creation
- Password hashing
- Email, username, and phone number validation
- Automatic profile creation for every new user
- Database session handling with SQLAlchemy
- Pydantic schema validation

## Tech Stack

- **FastAPI** — API framework
- **SQLAlchemy** — ORM and database models
- **Pydantic** — request and response validation
- **PyJWT** — token generation
- **pwdlib** — password hashing
- **phonenumbers** — phone number validation
- **python-dotenv** — environment variable loading
- **PostgreSQL** — database

## Project Structure

- `app/main.py` — FastAPI app entry point
- `app/database.py` — database connection and session handling
- `app/core/security.py` — JWT token creation
- `app/models/user.py` — user model
- `app/models/profile.py` — profile model
- `app/routers/auth.py` — authentication routes
- `app/schemas/user.py` — user schemas and validation
- `alembic/` — database migrations
- `main.py` — launcher script

## Authentication Flow

### Registration
When a user registers:

1. The system checks whether the email already exists.
2. The system checks whether the username already exists.
3. The password and confirm password must match.
4. The password must be at least 8 characters long.
5. The password is hashed securely.
6. The user is saved in the database.
7. A profile is automatically created for the new user.

### Login
When a user logs in:

1. The user is found by email.
2. The password is verified against the stored hash.
3. If valid, a JWT access token is returned.

## API Endpoints

### `GET /`
Simple health/status endpoint to confirm the app is running.

### `POST /accounts/register`
Registers a new user.

**Request fields:**
- `first_name`
- `last_name`
- `email`
- `username`
- `password`
- `confirm_password`
- `phone_number`

**Rules:**
- Email must be unique
- Username must be unique
- Passwords must match
- Password length must be greater than 8
- Phone number must be valid

### `POST /accounts/login`
Logs in a user and returns:

```json
{
  "access_token": "your_token_here",
  "token_type": "bearer"
}
