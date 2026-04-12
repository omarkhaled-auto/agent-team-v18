# TaskFlow — Mini Task Management App

> **Purpose:** This PRD exists to run a controlled Wave D provider comparison experiment. It is intentionally small (3-4 milestones, ~5-8K LOC) but covers every concern that matters for the Wave D decision: generated client wiring, i18n, RTL, forms with validation, data tables, and multi-endpoint API integration.

## Overview

TaskFlow is a task management application for small teams. Users can create projects, add tasks with priorities and due dates, assign tasks to team members, and track progress through a kanban board and data table view.

**Stack:** NestJS (backend) + Next.js App Router (frontend) + PostgreSQL + Prisma ORM

**Language support:** English (LTR) + Arabic (RTL) — both must work from day one.

---

## Domain Model

### Entities

#### User
- id: UUID (auto-generated)
- email: string (unique, required)
- name: string (required)
- role: enum [ADMIN, MEMBER] (default: MEMBER)
- avatar_url: string (optional)
- created_at: datetime
- updated_at: datetime

#### Project
- id: UUID (auto-generated)
- name: string (required, max 100)
- description: string (optional, max 500)
- status: enum [ACTIVE, ARCHIVED] (default: ACTIVE)
- owner_id: FK → User (required)
- created_at: datetime
- updated_at: datetime

#### Task
- id: UUID (auto-generated)
- title: string (required, max 200)
- description: string (optional, max 2000)
- status: enum [TODO, IN_PROGRESS, IN_REVIEW, DONE] (default: TODO)
- priority: enum [LOW, MEDIUM, HIGH, URGENT] (default: MEDIUM)
- due_date: date (optional)
- project_id: FK → Project (required)
- assignee_id: FK → User (optional)
- reporter_id: FK → User (required)
- created_at: datetime
- updated_at: datetime

#### Comment
- id: UUID (auto-generated)
- content: string (required, max 1000)
- task_id: FK → Task (required)
- author_id: FK → User (required)
- created_at: datetime

### State Machine

#### Task Status Transitions
```
TODO → IN_PROGRESS (only assignee or admin)
IN_PROGRESS → IN_REVIEW (only assignee or admin)
IN_REVIEW → DONE (only reporter or admin)
IN_REVIEW → IN_PROGRESS (only reporter or admin — rejection)
DONE → TODO (only admin — reopen)
```

Invalid transitions must return 400 with a message explaining the allowed transitions.

---

## API Endpoints

### Auth
- POST /api/auth/login — email + password → JWT token
- POST /api/auth/register — create account
- GET /api/auth/me — current user profile

### Projects
- GET /api/projects — list all projects (paginated, filterable by status)
- POST /api/projects — create project
- GET /api/projects/:id — get project with task count summary
- PATCH /api/projects/:id — update project
- DELETE /api/projects/:id — soft delete (set ARCHIVED)

### Tasks
- GET /api/projects/:projectId/tasks — list tasks (paginated, filterable by status/priority/assignee, sortable by due_date/priority/created_at)
- POST /api/projects/:projectId/tasks — create task
- GET /api/tasks/:id — get task with comments
- PATCH /api/tasks/:id — update task fields
- PATCH /api/tasks/:id/status — transition task status (validated against state machine)
- DELETE /api/tasks/:id — soft delete

### Comments
- GET /api/tasks/:taskId/comments — list comments (paginated)
- POST /api/tasks/:taskId/comments — add comment

### Users
- GET /api/users — list team members
- GET /api/users/:id — get user profile with task stats

**Total: 16 endpoints**

---

## Frontend Pages

### 1. Login Page (`/login`)
- Email + password form
- Validation: required fields, email format
- Error display for invalid credentials
- Redirect to /projects on success

### 2. Projects List (`/projects`)
- Data table with columns: Name, Status, Tasks Count, Owner, Created
- Sortable by name, created date
- Filter by status (Active/Archived)
- "New Project" button → modal with create form
- Click row → navigate to project detail

### 3. Project Detail / Task Board (`/projects/:id`)
- Project header with name, description, edit button
- Two view modes (toggle):
  - **Kanban Board:** columns for TODO, IN_PROGRESS, IN_REVIEW, DONE. Each task card shows title, priority badge, assignee avatar, due date. Cards are NOT drag-and-drop (keep it simple).
  - **Table View:** data table with columns: Title, Status, Priority, Assignee, Due Date, Created. Sortable. Filterable by status, priority, assignee.
- "New Task" button → modal with create form
- Click task → navigate to task detail

### 4. Task Detail (`/tasks/:id`)
- Task header: title, status badge, priority badge
- Task body: description, assignee, reporter, due date, project link
- Status transition buttons (only valid transitions shown based on current user role)
- Edit form (inline or modal)
- Comments section: list of comments with author, timestamp. Add comment form at bottom.

### 5. Team Members (`/team`)
- List of users with name, email, role, task count (assigned open tasks)
- Click user → simple profile view with their tasks

**Total: 5 pages + modals**

---

## Business Rules

1. Only project owners and admins can delete projects
2. Only admins can change user roles
3. Task status transitions follow the state machine — invalid transitions return 400
4. Only the assignee or admin can move a task from TODO → IN_PROGRESS
5. Only the reporter or admin can move a task from IN_REVIEW → DONE
6. Deleting a project soft-deletes all its tasks
7. Users cannot delete their own account
8. All timestamps displayed in user's local timezone
9. Pagination defaults: 20 items per page, max 100

---

## i18n Requirements

**This is critical for the Wave D experiment.**

- All user-facing strings must use translation keys via next-intl or react-i18next
- NO hardcoded strings in JSX — everything goes through `t('key')`
- Two locale files: `en.json` and `ar.json`
- The Arabic locale must have actual Arabic translations, not placeholders
- Date formatting must respect locale (e.g., `Intl.DateTimeFormat`)
- Number formatting must respect locale
- Form validation messages must be translated

### Translation Examples

| Key | English | Arabic |
|-----|---------|--------|
| projects.title | Projects | المشاريع |
| projects.create | New Project | مشروع جديد |
| tasks.status.todo | To Do | قيد الانتظار |
| tasks.status.in_progress | In Progress | قيد التنفيذ |
| tasks.priority.urgent | Urgent | عاجل |
| common.save | Save | حفظ |
| common.cancel | Cancel | إلغاء |
| common.delete | Delete | حذف |
| errors.required | This field is required | هذا الحقل مطلوب |

---

## RTL Requirements

**This is critical for the Wave D experiment.**

- Layout must flip correctly for Arabic (RTL)
- Use CSS logical properties: `margin-inline-start` not `margin-left`, `padding-inline-end` not `padding-right`
- Use `text-align: start` not `text-align: left`
- Kanban board columns should flow right-to-left in RTL
- Data table text alignment should respect direction
- Icons with directional meaning (arrows, chevrons) must flip in RTL
- Navigation must work in both directions

---

## Seed Data

Provide seed data for development/testing:

- 3 users: admin@taskflow.com (ADMIN), alice@taskflow.com (MEMBER), bob@taskflow.com (MEMBER)
- 2 projects: "Website Redesign" (ACTIVE, 6 tasks), "Mobile App" (ACTIVE, 4 tasks)
- 10 tasks across both projects with various statuses, priorities, and assignments
- 5 comments on different tasks

---

## Non-Functional Requirements

- JWT authentication with 24h token expiry
- Password hashing with bcrypt
- API response format: `{ data: T, meta?: { total, page, limit } }`
- Error response format: `{ error: { code: string, message: string, details?: any } }`
- All API endpoints require authentication except /auth/login and /auth/register
- Swagger/OpenAPI decorators on all endpoints
- Prisma for database access with repository pattern
- Frontend uses the generated API client (from Wave C OpenAPI spec) — NO manual fetch/axios

---

## What Makes This Good for the Experiment

This PRD deliberately targets every Wave D concern:

1. **Generated client wiring:** 16 endpoints across 4 resource types. Wave D must wire all of them through the generated client.
2. **i18n:** Mandatory translation keys for all strings. Wave E scanner will catch hardcoded strings.
3. **RTL:** Arabic support requires CSS logical properties. Wave E scanner will catch directional CSS.
4. **Forms with validation:** Login, create project, create task, add comment — all with validation that must use translated error messages.
5. **Data tables:** Projects list and task table with sorting, filtering, pagination — all through the generated client.
6. **State machine UI:** Task status transitions require showing only valid buttons based on user role and current status.
7. **Component composition:** Kanban board, data table, modals, forms, comment threads — enough variety to test whether Codex handles component structure well.

**Estimated size:** 3-4 milestones, ~5-8K LOC, ~$10-15 per full build.
**Experiment total:** Two builds (~$20-30) for a definitive Wave D verdict.
