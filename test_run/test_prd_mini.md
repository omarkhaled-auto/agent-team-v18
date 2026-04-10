# Bookmark API

## Overview
A minimal REST API for saving bookmarks. Node.js/Express with SQLite.

## Tech Stack
- Runtime: Node.js with Express
- Database: SQLite via better-sqlite3
- Auth: JWT tokens with bcrypt
- Language: TypeScript

## Entities

### Bookmark
- id: UUID (primary key)
- url: String (not null, valid URL)
- title: String (not null, max 200 chars)
- tags: String (comma-separated, nullable)
- user_id: UUID (foreign key -> User.id, not null)
- created_at: DateTime (default: now)

### User
- id: UUID (primary key)
- email: String (unique, not null)
- password_hash: String (not null)
- created_at: DateTime (default: now)

## State Machine
- Bookmark: ACTIVE -> ARCHIVED -> DELETED

## Business Rules
- BR-001: Users can only see their own bookmarks
- BR-002: Duplicate URLs per user are rejected (409)
- BR-003: Tags are normalized to lowercase, trimmed, max 5 per bookmark

## API Endpoints

### Auth
- POST /api/register — create account (email, password)
- POST /api/login — returns JWT

### Bookmarks
- GET /api/bookmarks — list user's bookmarks (supports ?tag= filter)
- POST /api/bookmarks — create bookmark (url, title, tags)
- PATCH /api/bookmarks/:id — update bookmark
- DELETE /api/bookmarks/:id — soft delete (set DELETED status)

## Events
- bookmark.created — emitted after successful creation
- bookmark.archived — emitted on status change to ARCHIVED

## Non-Functional
- All endpoints return JSON
- Auth via Bearer token in Authorization header
- Input validation on all endpoints
- Error responses: { error: string, code: string }
