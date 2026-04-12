import { Module } from '@nestjs/common';
import { ConfigModule as NestConfigModule } from '@nestjs/config';
import * as Joi from 'joi';

const databaseUrl = buildDatabaseUrl();
if (databaseUrl) {
  process.env.DATABASE_URL = process.env.DATABASE_URL || databaseUrl;
}

@Module({
  imports: [
    NestConfigModule.forRoot({
      isGlobal: true,
      envFilePath: ['.env', '.env.local'],
      validationSchema: Joi.object({
        DB_HOST: Joi.string().required(),
        DB_PORT: Joi.number().port().required(),
        DB_USERNAME: Joi.string().required(),
        DB_PASSWORD: Joi.string().allow('').required(),
        DB_DATABASE: Joi.string().required(),
        DATABASE_URL: Joi.string().required(),
        JWT_SECRET: Joi.string().required(),
        JWT_EXPIRY: Joi.string().default('24h'),
        PORT: Joi.number().default(8080),
        NODE_ENV: Joi.string().valid('development', 'production', 'test').default('development'),
        REDIS_HOST: Joi.string().default('localhost'),
        REDIS_PORT: Joi.number().port().default(6379),
      }),
    }),
  ],
})
export class AppConfigModule {}

function buildDatabaseUrl(): string | undefined {
  if (process.env.DATABASE_URL) {
    return process.env.DATABASE_URL;
  }

  const { DB_HOST, DB_PORT, DB_USERNAME, DB_PASSWORD, DB_DATABASE } = process.env;
  if (!DB_HOST || !DB_PORT || !DB_USERNAME || DB_PASSWORD === undefined || !DB_DATABASE) {
    return undefined;
  }

  const username = encodeURIComponent(DB_USERNAME);
  const password = encodeURIComponent(DB_PASSWORD);
  const database = encodeURIComponent(DB_DATABASE);
  return `postgresql://${username}:${password}@${DB_HOST}:${DB_PORT}/${database}`;
}
