import dotenv from 'dotenv';
dotenv.config();

import app from './app';
import { runMigrations } from './db/migrations';
import { seedAdmin } from './db/seed';

const PORT = parseInt(process.env.PORT || '3000', 10);

runMigrations();

seedAdmin().then(() => {
  app.listen(PORT, () => {
    console.log(`[server] Listening on port ${PORT}`);
  });
}).catch((err) => {
  console.error('[seed] Failed to seed admin user:', err);
  app.listen(PORT, () => {
    console.log(`[server] Listening on port ${PORT}`);
  });
});
