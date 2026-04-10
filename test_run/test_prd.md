# Task Tracker API

## Overview
Build a simple REST API for managing tasks (todo items) with user authentication. This is a small Node.js/Express backend with SQLite database.

## Tech Stack
- Runtime: Node.js with Express
- Database: SQLite via better-sqlite3
- Auth: JWT tokens with bcrypt password hashing
- Language: TypeScript

## Entities

### User
- id: UUID (primary key)
- email: String (unique, not null)
- password_hash: String (not null)
- name: String (not null)
- created_at: DateTime (default: now)

### Task
- id: UUID (primary key)
- title: String (not null, max 200 chars)
- description: Text (nullable)
- status: Enum (PENDING, IN_PROGRESS, DONE)
- priority: Enum (LOW, MEDIUM, HIGH)
- user_id: UUID (foreign key -> User.id, not null)
- due_date: DateTime (nullable)
- created_at: DateTime (default: now)
- updated_at: DateTime (auto-update)

## State Machines

### Task Status
- PENDING -> IN_PROGRESS (trigger: user starts task)
- IN_PROGRESS -> DONE (trigger: user completes task)
- IN_PROGRESS -> PENDING (trigger: user pauses task)
- DONE -> PENDING (trigger: user reopens task)

## API Endpoints

### Auth
- POST /api/auth/register - Register new user (email, password, name)
- POST /api/auth/login - Login (email, password) -> JWT token

### Tasks (all require JWT auth)
- GET /api/tasks - List user's tasks (filterable by status, priority)
- POST /api/tasks - Create task (title, description, priority, due_date)
- GET /api/tasks/:id - Get single task (must belong to user)
- PATCH /api/tasks/:id - Update task (title, description, status, priority, due_date)
- DELETE /api/tasks/:id - Soft delete task

## Business Rules
- BR-001: Password must be at least 8 characters with 1 uppercase and 1 number
- BR-002: Users can only access their own tasks (IDOR prevention)
- BR-003: Task title cannot be empty or whitespace-only
- BR-004: Status transitions must follow the state machine (e.g., cannot go from PENDING directly to DONE)
- BR-005: Soft delete sets a deleted_at timestamp, doesn't remove the row

## Events
- user.registered -> send welcome log entry
- task.created -> increment user's task count
- task.status_changed -> log the transition with timestamp

## Acceptance Criteria
- AC-001: User can register with valid credentials
- AC-002: User can login and receive a JWT token
- AC-003: Authenticated user can create a task
- AC-004: Tasks list returns only the authenticated user's tasks
- AC-005: Task status transitions follow the state machine
- AC-006: Invalid status transitions are rejected with 400 error
- AC-007: Soft delete marks task as deleted, doesn't return in list
- AC-008: Password validation enforces BR-001
- AC-009: Unauthorized access to other user's tasks returns 403
- AC-010: All endpoints return proper error responses (400, 401, 403, 404)
