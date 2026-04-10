import express from 'express';
import path from 'path';
import dotenv from 'dotenv';
dotenv.config();

import authRouter from './routes/auth';
import bookmarksRouter from './routes/bookmarks';
import { errorHandler } from './middleware/errorHandler';

const app = express();
app.use(express.json());

// Serve frontend static files
app.use(express.static(path.join(__dirname, '..', 'public')));

app.use('/api/auth', authRouter);
app.use('/api/bookmarks', bookmarksRouter);

// Explicit route aliases so /login and /login.html both serve the login page
app.get('/login', (_req, res) => {
  res.sendFile(path.join(__dirname, '..', 'public', 'index.html'));
});

// Suppress favicon 404
app.get('/favicon.ico', (_req, res) => res.status(204).end());

app.use(errorHandler);

export default app;
