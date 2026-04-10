export interface User {
  id: string;
  email: string;
  password_hash: string;
  name: string;
  created_at: string;
}

export interface Bookmark {
  id: string;
  user_id: string;
  url: string;
  title: string;
  tags: string;
  state: BookmarkState;
  created_at: string;
  updated_at: string;
}

export type BookmarkState = 'ACTIVE' | 'ARCHIVED' | 'DELETED';

export interface JwtPayload {
  userId: string;
  email: string;
}
