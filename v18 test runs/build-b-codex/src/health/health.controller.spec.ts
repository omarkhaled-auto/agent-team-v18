import { INestApplication } from '@nestjs/common';
import { APP_INTERCEPTOR } from '@nestjs/core';
import { Test } from '@nestjs/testing';
import request from 'supertest';
import { ResponseInterceptor } from '../common/interceptors/response.interceptor';
import { HealthModule } from './health.module';

describe('HealthController', () => {
  let app: INestApplication;

  beforeAll(async () => {
    const moduleRef = await Test.createTestingModule({
      imports: [HealthModule],
      providers: [
        {
          provide: APP_INTERCEPTOR,
          useClass: ResponseInterceptor,
        },
      ],
    }).compile();

    app = moduleRef.createNestApplication();
    await app.init();
  });

  afterAll(async () => {
    await app.close();
  });

  it('responds with a health payload', async () => {
    const response = await request(app.getHttpServer()).get('/health').expect(200);
    expect(response.body.data.status).toBe('ok');
    expect(typeof response.body.data.timestamp).toBe('string');
  });

  it('wraps the health response in the global envelope', async () => {
    const response = await request(app.getHttpServer()).get('/health').expect(200);
    expect(response.body).toHaveProperty('data');
    expect(response.body).not.toHaveProperty('meta');
  });
});
