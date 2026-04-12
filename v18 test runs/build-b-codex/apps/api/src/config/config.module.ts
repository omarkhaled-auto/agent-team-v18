import { Module } from '@nestjs/common';
import { ConfigModule as NestConfigModule } from '@nestjs/config';
import * as Joi from 'joi';

@Module({
  imports: [
    NestConfigModule.forRoot({
      isGlobal: true,
      envFilePath: ['.env', '../../.env'],
      validationSchema: Joi.object({
        DATABASE_URL: Joi.string().required(),
        JWT_SECRET: Joi.string().required(),
        JWT_EXPIRY: Joi.string().default('24h'),
        PORT: Joi.number().default(8080),
        NODE_ENV: Joi.string()
          .valid('development', 'production', 'test')
          .default('development'),
        REDIS_HOST: Joi.string().default('localhost'),
        REDIS_PORT: Joi.number().default(6379),
      }),
    }),
  ],
})
export class AppConfigModule {}
