import { Router, Response, NextFunction } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { z } from 'zod';
import { getDb } from '../db/connection';
import { verifyToken, AuthRequest } from '../middleware/auth';
import { Bookmark, BookmarkState } from '../types';

const router = Router();
router.use(verifyToken);

const VALID_TRANSITIONS: Record<BookmarkState, BookmarkState[]> = {
  ACTIVE: ['ARCHIVED'],
  ARCHIVED: ['DELETED'],
  DELETED: [],
};

const createBookmarkSchema = z.object({
  url: z.string().url('Invalid URL format').refine(
    (url) => url.startsWith('http://') || url.startsWith('https://'),
    'URL must start with http:// or https://'
  ),
  title: z.string().trim().min(1, 'Title required').max(200),
  tags: z.string().optional(),
});

const updateBookmarkSchema = z.object({
  url: z.string().url('Invalid URL format').refine(
    (url) => url.startsWith('http://') || url.startsWith('https://'),
    'URL must start with http:// or https://'
  ).optional(),
  title: z.string().trim().min(1).max(200).optional(),
  tags: z.string().optional(),
});

function normalizeTags(tagsStr: string | undefined): string {
  if (!tagsStr) return '[]';
  try {
    const parsed = JSON.parse(tagsStr);
    if (!Array.isArray(parsed)) return '[]';
    const normalized = [...new Set(
      parsed
        .filter((t: unknown) => typeof t === 'string')
        .map((t: string) => t.trim().toLowerCase())
        .filter((t: string) => t.length > 0)
    )].slice(0, 5);
    return JSON.stringify(normalized);
  } catch {
    return '[]';
  }
}

// POST /bookmarks — Create bookmark
router.post('/', (req: AuthRequest, res: Response, next: NextFunction) => {
  try {
    const parsed = createBookmarkSchema.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: true, message: parsed.error.errors[0].message });
      return;
    }
    const { url, title, tags } = parsed.data;
    const db = getDb();
    const userId = req.user!.userId;

    // Check duplicate URL per user
    const existing = db.prepare('SELECT id FROM bookmarks WHERE user_id = ? AND url = ?').get(userId, url);
    if (existing) {
      res.status(409).json({ error: true, message: 'Bookmark with this URL already exists' });
      return;
    }

    const id = uuidv4();
    const now = new Date().toISOString();
    const normalizedTags = normalizeTags(tags);

    const bookmark: Bookmark = {
      id,
      user_id: userId,
      url,
      title,
      tags: normalizedTags,
      state: 'ACTIVE',
      created_at: now,
      updated_at: now,
    };

    db.prepare(
      'INSERT INTO bookmarks (id, user_id, url, title, tags, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)'
    ).run(bookmark.id, bookmark.user_id, bookmark.url, bookmark.title, bookmark.tags, bookmark.state, bookmark.created_at, bookmark.updated_at);

    console.log('[event] bookmark.created', { bookmarkId: id, userId });
    res.status(201).json(bookmark);
  } catch (err) {
    next(err);
  }
});

// GET /bookmarks — List bookmarks (excludes DELETED)
router.get('/', (req: AuthRequest, res: Response, next: NextFunction) => {
  try {
    const { tag } = req.query;
    const db = getDb();
    const userId = req.user!.userId;

    let query = 'SELECT * FROM bookmarks WHERE user_id = ? AND state != ?';
    const params: unknown[] = [userId, 'DELETED'];

    const bookmarks = db.prepare(query).all(...params) as Bookmark[];

    let results = bookmarks;
    if (tag && typeof tag === 'string') {
      const searchTag = tag.toLowerCase().trim();
      results = bookmarks.filter((b) => {
        try {
          const tags: string[] = JSON.parse(b.tags);
          return tags.some((t) => t.toLowerCase() === searchTag);
        } catch {
          return false;
        }
      });
    }

    res.json({ bookmarks: results });
  } catch (err) {
    next(err);
  }
});

// GET /bookmarks/:id — Get single bookmark
router.get('/:id', (req: AuthRequest, res: Response, next: NextFunction) => {
  try {
    const db = getDb();
    const bookmark = db.prepare('SELECT * FROM bookmarks WHERE id = ?').get(req.params.id) as Bookmark | undefined;
    if (!bookmark || bookmark.state === 'DELETED') {
      res.status(404).json({ error: true, message: 'Bookmark not found' });
      return;
    }
    if (bookmark.user_id !== req.user!.userId) {
      res.status(403).json({ error: true, message: 'Forbidden' });
      return;
    }
    res.json(bookmark);
  } catch (err) {
    next(err);
  }
});

// PATCH /bookmarks/:id — Update bookmark fields
router.patch('/:id', (req: AuthRequest, res: Response, next: NextFunction) => {
  try {
    const parsed = updateBookmarkSchema.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: true, message: parsed.error.errors[0].message });
      return;
    }
    const db = getDb();
    const bookmark = db.prepare('SELECT * FROM bookmarks WHERE id = ?').get(req.params.id) as Bookmark | undefined;
    if (!bookmark || bookmark.state === 'DELETED') {
      res.status(404).json({ error: true, message: 'Bookmark not found' });
      return;
    }
    if (bookmark.user_id !== req.user!.userId) {
      res.status(403).json({ error: true, message: 'Forbidden' });
      return;
    }

    const updates = parsed.data;

    // Check duplicate URL if URL is being changed
    if (updates.url && updates.url !== bookmark.url) {
      const dup = db.prepare('SELECT id FROM bookmarks WHERE user_id = ? AND url = ? AND id != ?').get(
        req.user!.userId, updates.url, bookmark.id
      );
      if (dup) {
        res.status(409).json({ error: true, message: 'Bookmark with this URL already exists' });
        return;
      }
    }

    const now = new Date().toISOString();
    const updated: Bookmark = {
      ...bookmark,
      url: updates.url ?? bookmark.url,
      title: updates.title ?? bookmark.title,
      tags: updates.tags !== undefined ? normalizeTags(updates.tags) : bookmark.tags,
      updated_at: now,
    };

    db.prepare(
      'UPDATE bookmarks SET url=?, title=?, tags=?, updated_at=? WHERE id=?'
    ).run(updated.url, updated.title, updated.tags, updated.updated_at, bookmark.id);

    res.json(updated);
  } catch (err) {
    next(err);
  }
});

// PATCH /bookmarks/:id/archive — Transition to ARCHIVED
router.patch('/:id/archive', (req: AuthRequest, res: Response, next: NextFunction) => {
  try {
    const db = getDb();
    const bookmark = db.prepare('SELECT * FROM bookmarks WHERE id = ?').get(req.params.id) as Bookmark | undefined;
    if (!bookmark || bookmark.state === 'DELETED') {
      res.status(404).json({ error: true, message: 'Bookmark not found' });
      return;
    }
    if (bookmark.user_id !== req.user!.userId) {
      res.status(403).json({ error: true, message: 'Forbidden' });
      return;
    }
    if (bookmark.state !== 'ACTIVE') {
      res.status(422).json({ error: true, message: `Invalid state transition: ${bookmark.state} -> ARCHIVED` });
      return;
    }

    const now = new Date().toISOString();
    db.prepare('UPDATE bookmarks SET state=?, updated_at=? WHERE id=?').run('ARCHIVED', now, bookmark.id);

    console.log('[event] bookmark.archived', { bookmarkId: bookmark.id });
    res.json({ id: bookmark.id, state: 'ARCHIVED' as BookmarkState, updated_at: now });
  } catch (err) {
    next(err);
  }
});

// DELETE /bookmarks/:id — Soft delete (ARCHIVED -> DELETED)
router.delete('/:id', (req: AuthRequest, res: Response, next: NextFunction) => {
  try {
    const db = getDb();
    const bookmark = db.prepare('SELECT * FROM bookmarks WHERE id = ?').get(req.params.id) as Bookmark | undefined;
    if (!bookmark || bookmark.state === 'DELETED') {
      res.status(404).json({ error: true, message: 'Bookmark not found' });
      return;
    }
    if (bookmark.user_id !== req.user!.userId) {
      res.status(403).json({ error: true, message: 'Forbidden' });
      return;
    }
    if (bookmark.state !== 'ARCHIVED') {
      res.status(422).json({ error: true, message: `Invalid state transition: ${bookmark.state} -> DELETED. Must archive first.` });
      return;
    }

    const now = new Date().toISOString();
    db.prepare('UPDATE bookmarks SET state=?, updated_at=? WHERE id=?').run('DELETED', now, bookmark.id);

    console.log('[event] bookmark.deleted', { bookmarkId: bookmark.id });
    res.status(204).end();
  } catch (err) {
    next(err);
  }
});

export default router;
