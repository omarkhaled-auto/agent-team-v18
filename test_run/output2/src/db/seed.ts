import bcrypt from 'bcrypt';
import { v4 as uuidv4 } from 'uuid';
import { getDb } from './connection';

export async function seedAdmin(): Promise<void> {
  const db = getDb();

  const existing = db.prepare('SELECT id FROM users WHERE email = ?').get('admin@example.com');
  if (existing) return;

  const passwordHash = await bcrypt.hash('Admin1234', 10);
  db.prepare(
    'INSERT INTO users (id, email, password_hash, name, created_at) VALUES (?, ?, ?, ?, datetime(\'now\'))'
  ).run(uuidv4(), 'admin@example.com', passwordHash, 'Admin');

  console.log('[seed] Admin user created: admin@example.com / Admin1234');
}
